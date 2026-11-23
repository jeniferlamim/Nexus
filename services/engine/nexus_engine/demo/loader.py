"""Loads the synthetic dataset through the REAL ingestion pipeline (no shortcuts)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..domain.models import SourceType
from ..persistence.db import IngestionBatch, Tenant
from ..security.auth import Principal
from ..services.ingestion import DuplicateBatch, create_batch, process_batch
from .generator import generate

PROFILES = {
    "45723174": dict(seed=7, tenant_name="Vértice Componentes Industriais S.A.", docs_per_month=70),
    "31954862": dict(seed=11, tenant_name="Rede Aurora Supermercados Ltda", docs_per_month=40),
}


def load_demo(session: Session, principal: Principal) -> list[IngestionBatch]:
    tenant = session.get(Tenant, principal.tenant_id)
    root = tenant.cnpj_roots[0]
    ds = generate(root=root, **PROFILES.get(root, dict(seed=3, tenant_name=tenant.legal_name, docs_per_month=40)))
    if not tenant.ledger_accounts:
        tenant.ledger_accounts = ds.ledger_accounts
        session.commit()
    files = [
        (SourceType.NFE_XML, f"nfe_{root}_2023-2026.zip", ds.xml_zip, False),
        (SourceType.LEDGER, f"razao_contabil_{root}.xlsx", ds.ledger_xlsx, False),
        (SourceType.FISCAL_BOOK, f"escrituracao_fiscal_{root}.csv", ds.book_csv, True),  # last: triggers analysis
    ]
    batches = []
    for src, name, content, analyse in files:
        try:
            batch = create_batch(session, principal, src, name, content)
            session.commit()
        except DuplicateBatch as dup:
            batches.append(dup.batch)
            continue
        batches.append(process_batch(session, principal, batch.id, content, run_analysis=analyse))
    return batches
