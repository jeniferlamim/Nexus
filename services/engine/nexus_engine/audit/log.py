"""Append-only, hash-chained audit trail (per tenant).

hash_n = SHA-256( prev_hash || canonical_json(entry_n) )

Any update/delete/reorder breaks the chain and is detected by ``verify``. In PostgreSQL the
table additionally has UPDATE/DELETE revoked and a trigger that rejects them (migration 0003).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..persistence.db import AuditLogRow

GENESIS = "0" * 64


def _canonical(tenant_id: str, seq: int, actor_id: str, actor_name: str, action: str, entity_type: str,
               entity_id: str, payload: dict, created_at: str) -> bytes:
    """Every stored column except the hashes themselves is covered."""
    return json.dumps(
        {"tenant_id": tenant_id, "seq": seq, "actor_id": actor_id, "actor_name": actor_name, "action": action,
         "entity_type": entity_type, "entity_id": entity_id, "payload": payload,
         "created_at": created_at},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str,
    ).encode()


def record(session: Session, *, tenant_id: str, actor_id: str, actor_name: str, action: str,
           entity_type: str, entity_id: str, payload: dict[str, Any] | None = None) -> AuditLogRow:
    payload = json.loads(json.dumps(payload or {}, default=str))
    last = session.execute(
        select(AuditLogRow).where(AuditLogRow.tenant_id == tenant_id).order_by(AuditLogRow.seq.desc()).limit(1)
    ).scalar_one_or_none()
    seq = (last.seq + 1) if last else 1
    prev = last.hash if last else GENESIS
    created_at = datetime.now(timezone.utc).isoformat()
    digest = hashlib.sha256(prev.encode() + _canonical(
        tenant_id, seq, actor_id, actor_name, action, entity_type, str(entity_id), payload, created_at)).hexdigest()
    row = AuditLogRow(tenant_id=tenant_id, seq=seq, actor_id=actor_id, actor_name=actor_name,
                      action=action, entity_type=entity_type, entity_id=str(entity_id),
                      payload=payload, created_at=created_at, prev_hash=prev, hash=digest)
    session.add(row)
    session.flush()
    return row


def verify(session: Session, tenant_id: str) -> dict[str, Any]:
    prev = GENESIS
    count = 0
    rows = session.execute(
        select(AuditLogRow).where(AuditLogRow.tenant_id == tenant_id).order_by(AuditLogRow.seq)
    ).scalars()
    for expected_seq, row in enumerate(rows, start=1):
        count += 1
        digest = hashlib.sha256(prev.encode() + _canonical(
            row.tenant_id, row.seq, row.actor_id, row.actor_name, row.action, row.entity_type, row.entity_id,
            row.payload, row.created_at)).hexdigest()
        if row.seq != expected_seq or row.prev_hash != prev or row.hash != digest:
            return {"valid": False, "entries": count, "broken_at_seq": row.seq,
                    "reason": "sequência, encadeamento ou conteúdo alterado"}
        prev = row.hash
    return {"valid": True, "entries": count, "head": prev}


def count(session: Session, tenant_id: str) -> int:
    return session.scalar(select(func.count()).select_from(AuditLogRow).where(AuditLogRow.tenant_id == tenant_id)) or 0
