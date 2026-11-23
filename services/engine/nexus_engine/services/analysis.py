"""Analysis run: load tenant data → deterministic engine → merge findings → report."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import __version__
from ..analysis.engine import AnalysisEngine, AnalysisInput, TenantProfile
from ..audit import log as audit
from ..domain.models import (
    ZERO, BookEntry, Direction, DocumentItem, FiscalDocument, FindingStatus, LedgerEntry,
)
from ..persistence.db import (
    AnalysisRun, BookEntryRow, FindingEvidenceRow, FindingRow, FiscalDocumentRow, IngestionBatch,
    LedgerEntryRow, Tenant,
)
from ..security.auth import Principal
from .ingestion import _stage


def load_input(session: Session, tenant: Tenant) -> AnalysisInput:
    tid = tenant.id
    docs = []
    for r in session.execute(select(FiscalDocumentRow).where(FiscalDocumentRow.tenant_id == tid)
                             .options(selectinload(FiscalDocumentRow.items))).scalars():
        docs.append(FiscalDocument(
            access_key=r.access_key, model=r.model, series=r.series, number=r.number, issue_date=r.issue_date,
            issuer_cnpj=r.issuer_cnpj, issuer_name=r.issuer_name, issuer_uf=r.issuer_uf,
            recipient_doc=r.recipient_doc, recipient_uf=r.recipient_uf, operation_type=r.operation_type,
            total_amount=r.total_amount, icms_total=r.icms_total, status=r.status, source_file=r.source_file,
            has_ibs_cbs_group=r.has_ibs_cbs_group,
            items=[DocumentItem(
                item_number=i.item_number, product_code=i.product_code, description=i.description, ncm=i.ncm,
                cfop=i.cfop, quantity=i.quantity, gross_amount=i.gross_amount, discount=i.discount,
                icms_cst=i.icms_cst, icms_base=i.icms_base, icms_rate=i.icms_rate, icms_amount=i.icms_amount,
                ipi_amount=i.ipi_amount, pis_cst=i.pis_cst, pis_amount=i.pis_amount, cofins_cst=i.cofins_cst,
                cofins_amount=i.cofins_amount, ibs_cbs_base=i.ibs_cbs_base, ibs_amount=i.ibs_amount,
                cbs_amount=i.cbs_amount, xpath=f"/NFe/infNFe/det[@nItem='{i.item_number}']") for i in r.items],
        ))
    book = [BookEntry(
        access_key=r.access_key, document_number=r.document_number, entry_date=r.entry_date,
        direction=Direction(r.direction), counterparty_cnpj=r.counterparty_cnpj, item_number=r.item_number,
        cfop=r.cfop, ncm=r.ncm, amount=r.amount, icms_base=r.icms_base, icms_credit=r.icms_credit,
        pis_credit=r.pis_credit, cofins_credit=r.cofins_credit, pis_cst=r.pis_cst, source_file=r.source_file,
        source_row=r.source_row) for r in session.execute(
            select(BookEntryRow).where(BookEntryRow.tenant_id == tid).order_by(BookEntryRow.id)).scalars()]
    ledger = [LedgerEntry(
        entry_date=r.entry_date, account=r.account, account_name=r.account_name, history=r.history,
        debit=r.debit, credit=r.credit, access_key=r.access_key, source_file=r.source_file,
        source_row=r.source_row) for r in session.execute(
            select(LedgerEntryRow).where(LedgerEntryRow.tenant_id == tid)).scalars()]
    profile = TenantProfile(cnpj_roots=set(tenant.cnpj_roots), tax_regime=tenant.tax_regime,
                            ledger_accounts=tenant.ledger_accounts or {})
    return AnalysisInput(tenant=profile, documents=docs, book=book, ledger=ledger)


def run_analysis(session: Session, principal: Principal, trigger: str = "MANUAL",
                 batch: IngestionBatch | None = None) -> AnalysisRun:
    tenant = session.get(Tenant, principal.tenant_id)
    run = AnalysisRun(tenant_id=tenant.id, trigger=trigger, started_by=principal.user_id,
                      engine_version=__version__)
    session.add(run)
    session.flush()

    data = load_input(session, tenant)
    findings, stats = AnalysisEngine().run(data)
    names = {d.issuer_cnpj: d.issuer_name for d in data.documents}
    if batch:
        _stage(batch, "ANALYSIS", "DONE",
               f"{stats.documents} NF-e × {stats.book_entries} lançamentos × {stats.ledger_entries} contábeis · "
               f"{len(stats.rule_versions_applied)} regras aplicadas")
        batch.analysis_run_id = run.id

    # ---- merge (dedupe by fingerprint; human decisions are never overwritten)
    existing = {f.fingerprint: f for f in session.execute(
        select(FindingRow).where(FindingRow.tenant_id == tenant.id)).scalars()}
    next_seq = (session.scalar(select(func.max(FindingRow.seq)).where(FindingRow.tenant_id == tenant.id)) or 0) + 1
    seen, new = set(), 0
    for f in findings:
        if f.fingerprint in seen:
            continue
        seen.add(f.fingerprint)
        row = existing.get(f.fingerprint)
        if row is None:
            row = FindingRow(tenant_id=tenant.id, seq=next_seq, fingerprint=f.fingerprint, first_run_id=run.id,
                             status=FindingStatus.OPEN.value)
            next_seq += 1
            new += 1
            session.add(row)
        elif row.status != FindingStatus.OPEN.value:
            # Under human review or decided: keep content frozen, only mark as still detected.
            row.last_run_id, row.is_active = run.id, True
            continue
        row.last_run_id, row.is_active = run.id, True
        row.rule_code, row.rule_version = f.rule_code, f.rule_version
        row.category, row.kind, row.severity = f.category.value, f.kind.value, f.severity.value
        row.title, row.description = f.title[:300], f.description
        row.methodology, row.legal_basis = f.methodology, f.legal_basis
        row.confidence, row.amount_type, row.estimated_amount = f.confidence, f.amount_type.value, f.estimated_amount
        row.tax, row.access_key, row.counterparty_cnpj = f.tax, f.access_key, f.counterparty_cnpj
        row.counterparty_name = names.get(f.counterparty_cnpj or "")
        row.period, row.calculation = f.period, f.calculation
        row.updated_at = datetime.now(timezone.utc)
        row.evidence = [FindingEvidenceRow(tenant_id=tenant.id, source=e.source[:255], locator=e.locator[:160],
                                           field=e.field[:80], observed=e.observed[:200],
                                           expected=e.expected[:200], note=e.note[:300]) for e in f.evidence]
    resolved = 0
    for fp, row in existing.items():
        if fp not in seen and row.is_active:
            row.is_active = False
            resolved += 1
    session.flush()
    if batch:
        _stage(batch, "DIVERGENCE_DETECTION", "DONE",
               f"{len(seen)} ocorrência(s) ativas · {new} nova(s) · {resolved} não mais detectada(s)")

    # ---- report snapshot
    by_type: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_cat: Counter = Counter()
    by_sev: Counter = Counter()
    for f in findings:
        by_type[f.amount_type.value] += f.estimated_amount
        by_cat[f.category.value] += 1
        by_sev[f.severity.value] += 1
    run.report = {"amount_by_type": {k: str(v) for k, v in by_type.items()}, "by_category": dict(by_cat),
                  "by_severity": dict(by_sev)}
    run.stats = {k: v for k, v in stats.__dict__.items() if k != "rule_versions_applied"}
    run.rule_versions = stats.rule_versions_applied
    run.findings_total, run.findings_new, run.findings_resolved = len(seen), new, resolved
    run.status = "COMPLETED"
    run.finished_at = datetime.now(timezone.utc)
    if batch:
        _stage(batch, "REPORTING", "DONE", "Relatório consolidado e exportação disponíveis")
    audit.record(session, tenant_id=tenant.id, actor_id=principal.user_id, actor_name=principal.name,
                 action="analysis.completed", entity_type="analysis_run", entity_id=run.id,
                 payload={"trigger": trigger, "findings_total": len(seen), "findings_new": new,
                          "findings_resolved": resolved, "rule_versions": stats.rule_versions_applied,
                          "engine_version": __version__})
    session.commit()
    return run
