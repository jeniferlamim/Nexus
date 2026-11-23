"""Human review workflow with segregation of duties.

    OPEN ──start_review──► IN_REVIEW ──propose_validation──► PENDING_APPROVAL ──approve──► VALIDATED
      └──────────────propose_dismissal──────────────────────►      │      └─approve─► DISMISSED
                                                                    └──return──► IN_REVIEW
    VALIDATED / DISMISSED ──reopen──► IN_REVIEW

* Approvals require Permission.APPROVE and a DIFFERENT person from the proposer.
* Every transition requires a justification (except start_review) and is audited.
* A VALIDATED finding is a documented conclusion. It never triggers offsets, filings or ERP
  postings: by design there is no such capability in the platform.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..audit import log as audit
from ..domain.models import FindingKind, FindingStatus as S
from ..persistence.db import FindingReviewRow, FindingRow
from ..security.auth import Principal
from ..security.rbac import Permission


@dataclass(frozen=True)
class Transition:
    sources: frozenset[S]
    permission: Permission
    needs_comment: bool
    label: str


TRANSITIONS: dict[str, Transition] = {
    "start_review": Transition(frozenset({S.OPEN}), Permission.REVIEW, False, "Iniciar análise"),
    "propose_validation": Transition(frozenset({S.IN_REVIEW}), Permission.REVIEW, True, "Propor validação"),
    "propose_dismissal": Transition(frozenset({S.OPEN, S.IN_REVIEW}), Permission.REVIEW, True, "Propor descarte"),
    "approve": Transition(frozenset({S.PENDING_APPROVAL}), Permission.APPROVE, True, "Aprovar proposta"),
    "return": Transition(frozenset({S.PENDING_APPROVAL}), Permission.APPROVE, True, "Devolver para análise"),
    "reopen": Transition(frozenset({S.VALIDATED, S.DISMISSED}), Permission.APPROVE, True, "Reabrir"),
}


def available_actions(row: FindingRow, principal: Principal) -> list[dict]:
    out = []
    for name, t in TRANSITIONS.items():
        if S(row.status) not in t.sources or not principal.can(t.permission):
            continue
        blocked = None
        if name == "approve" and row.proposed_by == principal.user_id:
            blocked = "Segregação de funções: quem propôs não pode aprovar"
        out.append({"action": name, "label": t.label, "needs_comment": t.needs_comment, "blocked_reason": blocked})
    return out


def transition(session: Session, principal: Principal, row: FindingRow, action: str, comment: str,
               validated_amount: str | None = None) -> FindingRow:
    t = TRANSITIONS.get(action)
    if t is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ação desconhecida")
    if not principal.can(t.permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Permissão necessária: {t.permission.value}")
    current = S(row.status)
    if current not in t.sources:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ação '{t.label}' não permitida no status {current.value}")
    comment = (comment or "").strip()
    if t.needs_comment and len(comment) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Justificativa obrigatória (mín. 10 caracteres)")

    amount: Decimal | None = None
    if action == "start_review":
        new = S.IN_REVIEW
    elif action in ("propose_validation", "propose_dismissal"):
        new = S.PENDING_APPROVAL
        row.proposal = "VALIDATE" if action == "propose_validation" else "DISMISS"
        row.proposed_by = principal.user_id
    elif action == "approve":
        if row.proposed_by == principal.user_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Segregação de funções: quem propôs não pode aprovar")
        if row.proposal == "VALIDATE":
            new = S.VALIDATED
            row.kind = FindingKind.VALIDATED.value
            if validated_amount not in (None, ""):
                try:
                    amount = Decimal(str(validated_amount)).quantize(Decimal("0.01"))
                except InvalidOperation as exc:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Valor validado inválido") from exc
                if amount < 0:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Valor validado não pode ser negativo")
            else:
                amount = row.estimated_amount
            row.validated_amount = amount
        else:
            new = S.DISMISSED
    elif action == "return":
        new = S.IN_REVIEW
        row.proposal, row.proposed_by = None, None
    else:  # reopen
        new = S.IN_REVIEW
        row.proposal, row.proposed_by, row.validated_amount = None, None, None
        row.kind = "ESTIMATE" if row.amount_type == "RECOVERABLE_ESTIMATE" else "ALERT"

    session.add(FindingReviewRow(
        tenant_id=row.tenant_id, finding_id=row.id, actor_id=principal.user_id, actor_name=principal.name,
        actor_role=principal.role, action=action, from_status=current.value, to_status=new.value,
        comment=comment, validated_amount=amount))
    row.status = new.value
    row.updated_at = datetime.now(timezone.utc)
    audit.record(session, tenant_id=row.tenant_id, actor_id=principal.user_id, actor_name=principal.name,
                 action=f"finding.{action}", entity_type="finding", entity_id=row.id,
                 payload={"seq": row.seq, "rule": f"{row.rule_code} v{row.rule_version}", "from": current.value,
                          "to": new.value, "comment": comment,
                          "validated_amount": str(amount) if amount is not None else None})
    session.commit()
    return row
