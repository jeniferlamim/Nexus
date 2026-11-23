"""Ingestion pipeline: the 8 tracked stages.

UPLOAD → VALIDATION → ERROR_IDENTIFICATION → NORMALIZATION → STORAGE → ANALYSIS →
DIVERGENCE_DETECTION → REPORTING

The raw file is NOT persisted (only its SHA-256): data minimisation. In production the raw file
goes to encrypted object storage with a contractual retention period.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..audit import log as audit
from ..domain.models import SourceType
from ..ingestion.errors import ErrorSeverity, IngestionError, RecordError
from ..ingestion.nfe_xml import iter_xml_payloads, parse_nfe
from ..ingestion.tabular import parse_fiscal_book, parse_ledger
from ..persistence.db import (
    BatchError, BookEntryRow, FiscalDocumentItemRow, FiscalDocumentRow, IngestionBatch,
    LedgerEntryRow, Tenant,
)
from ..security.auth import Principal

log = logging.getLogger("nexus.ingestion")

STAGES = ["UPLOAD", "VALIDATION", "ERROR_IDENTIFICATION", "NORMALIZATION", "STORAGE",
          "ANALYSIS", "DIVERGENCE_DETECTION", "REPORTING"]
STAGE_LABELS = {
    "UPLOAD": "Upload", "VALIDATION": "Validação", "ERROR_IDENTIFICATION": "Identificação de erros",
    "NORMALIZATION": "Normalização", "STORAGE": "Armazenamento", "ANALYSIS": "Análise",
    "DIVERGENCE_DETECTION": "Detecção de divergências", "REPORTING": "Relatórios",
}


class DuplicateBatch(Exception):
    def __init__(self, batch: IngestionBatch):
        self.batch = batch


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stage(batch: IngestionBatch, name: str, status: str, detail: str = "") -> None:
    stages = [s for s in (batch.stages or []) if s["stage"] != name]
    stages.append({"stage": name, "label": STAGE_LABELS[name], "status": status, "at": _ts(), "detail": detail})
    stages.sort(key=lambda s: STAGES.index(s["stage"]))
    batch.stages = stages


def create_batch(session: Session, principal: Principal, source_type: SourceType, filename: str,
                 content: bytes) -> IngestionBatch:
    sha = hashlib.sha256(content).hexdigest()
    existing = session.execute(select(IngestionBatch).where(
        IngestionBatch.tenant_id == principal.tenant_id, IngestionBatch.sha256 == sha)).scalar_one_or_none()
    if existing:
        raise DuplicateBatch(existing)
    tenant = session.get(Tenant, principal.tenant_id)
    max_mb = tenant.plan.max_file_mb
    if len(content) > max_mb * 1024 * 1024:
        raise IngestionError(f"Arquivo excede o limite do plano ({max_mb} MB)")
    batch = IngestionBatch(tenant_id=principal.tenant_id, source_type=source_type.value,
                           filename=filename[:255], sha256=sha, size_bytes=len(content),
                           status="QUEUED", created_by=principal.user_id, stages=[])
    _stage(batch, "UPLOAD", "DONE", f"{len(content):,} bytes · SHA-256 {sha[:12]}…".replace(",", "."))
    session.add(batch)
    session.flush()
    audit.record(session, tenant_id=principal.tenant_id, actor_id=principal.user_id, actor_name=principal.name,
                 action="ingestion.uploaded", entity_type="ingestion_batch", entity_id=batch.id,
                 payload={"filename": filename, "source_type": source_type.value, "sha256": sha,
                          "size_bytes": len(content)})
    return batch


def _documents_this_month(session: Session, tenant_id: str) -> int:
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return session.scalar(select(func.coalesce(func.sum(IngestionBatch.records_valid), 0)).where(
        IngestionBatch.tenant_id == tenant_id, IngestionBatch.source_type == SourceType.NFE_XML.value,
        IngestionBatch.created_at >= start, IngestionBatch.status.in_(["COMPLETED", "COMPLETED_WITH_WARNINGS"]))) or 0


def process_batch(session: Session, principal: Principal, batch_id: str, content: bytes,
                  run_analysis: bool = True) -> IngestionBatch:
    batch = session.get(IngestionBatch, batch_id)
    assert batch is not None and batch.tenant_id == principal.tenant_id
    batch.status = "RUNNING"
    session.commit()
    try:
        _process(session, principal, batch, content)
        if run_analysis:
            from .analysis import run_analysis as _run
            _run(session, principal, trigger="INGESTION", batch=batch)
        else:
            for st in ("ANALYSIS", "DIVERGENCE_DETECTION", "REPORTING"):
                _stage(batch, st, "SKIPPED", "Consolidado na análise do próximo lote do mesmo carregamento")
        batch.status = "COMPLETED_WITH_WARNINGS" if batch.warnings or batch.records_rejected else "COMPLETED"
    except IngestionError as exc:
        session.rollback()
        batch = session.get(IngestionBatch, batch_id)
        batch.status = "FAILED"
        batch.error = str(exc)
        failed = next((s for s in STAGES if s not in {x["stage"] for x in batch.stages or []}), "VALIDATION")
        _stage(batch, failed, "FAILED", str(exc))
    except Exception as exc:  # noqa: BLE001 — never leave a batch hanging in RUNNING
        log.exception("batch %s failed", batch_id)
        session.rollback()
        batch = session.get(IngestionBatch, batch_id)
        batch.status = "FAILED"
        batch.error = f"Erro interno no processamento ({type(exc).__name__})"
    batch.finished_at = datetime.now(timezone.utc)
    audit.record(session, tenant_id=principal.tenant_id, actor_id=principal.user_id, actor_name=principal.name,
                 action="ingestion.processed", entity_type="ingestion_batch", entity_id=batch.id,
                 payload={"status": batch.status, "valid": batch.records_valid,
                          "rejected": batch.records_rejected, "warnings": batch.warnings, "error": batch.error})
    session.commit()
    return batch


def _process(session: Session, principal: Principal, batch: IngestionBatch, content: bytes) -> None:
    tid = principal.tenant_id
    src = SourceType(batch.source_type)
    errors: list[RecordError] = []

    # ---- VALIDATION
    if src == SourceType.NFE_XML:
        docs = []
        total = 0
        for name, payload in iter_xml_payloads(batch.filename, content):
            total += 1
            doc, errs = parse_nfe(payload, name.rsplit("/", 1)[-1])
            errors += errs
            if doc:
                docs.append(doc)
        records = docs
    elif src == SourceType.FISCAL_BOOK:
        records, errors, total = parse_fiscal_book(batch.filename, content)
    else:
        records, errors, total = parse_ledger(batch.filename, content)
    batch.records_total = total
    _stage(batch, "VALIDATION", "DONE", f"{total} registro(s) lidos e validados")

    # ---- ERROR IDENTIFICATION
    blocking = [e for e in errors if e.severity == ErrorSeverity.BLOCKING]
    warnings = [e for e in errors if e.severity == ErrorSeverity.WARNING]
    for e in errors[:5000]:
        session.add(BatchError(tenant_id=tid, batch_id=batch.id, **{k: v for k, v in e.as_dict().items()}))
    batch.warnings = len(warnings)
    if not records:
        raise IngestionError(f"Nenhum registro válido ({len(blocking)} erro(s) bloqueante(s))")
    _stage(batch, "ERROR_IDENTIFICATION", "DONE",
           f"{len(blocking)} erro(s) bloqueante(s), {len(warnings)} aviso(s)")

    # ---- NORMALIZATION
    if src == SourceType.NFE_XML:
        unique = {}
        for d in records:
            if d.access_key in unique:
                session.add(BatchError(tenant_id=tid, batch_id=batch.id, source=d.source_file, locator="arquivo",
                                       field="chave", value=d.access_key,
                                       message="XML duplicado no lote (mantida a última ocorrência)",
                                       severity="WARNING"))
                batch.warnings += 1
            d.issuer_uf, d.recipient_uf = d.issuer_uf.upper(), d.recipient_uf.upper()
            unique[d.access_key] = d
        records = list(unique.values())
        periods = sorted({d.period for d in records})
    else:
        periods = sorted({r.period for r in records})
    batch.records_valid = len(records)
    batch.records_rejected = max(total - len(records), 0)
    batch.periods = periods
    _stage(batch, "NORMALIZATION", "DONE",
           f"{len(records)} registro(s) normalizados · períodos {', '.join(periods[:6])}{'…' if len(periods) > 6 else ''}")

    # ---- STORAGE
    tenant = session.get(Tenant, tid)
    if src == SourceType.NFE_XML:
        used = _documents_this_month(session, tid)
        limit = tenant.plan.max_documents_month
        if used + len(records) > limit:
            raise IngestionError(f"Limite do plano excedido: {used + len(records):,} de {limit:,} documentos/mês. "
                                 "Contate o gestor do contrato para ampliar o plano.".replace(",", "."))
        keys = [d.access_key for d in records]
        for chunk in (keys[i:i + 500] for i in range(0, len(keys), 500)):
            for row in session.execute(select(FiscalDocumentRow).where(
                    FiscalDocumentRow.tenant_id == tid, FiscalDocumentRow.access_key.in_(chunk))).scalars():
                session.delete(row)
        session.flush()
        for d in records:
            row = FiscalDocumentRow(
                tenant_id=tid, batch_id=batch.id, access_key=d.access_key, model=d.model, series=d.series,
                number=d.number, issue_date=d.issue_date, period=d.period, issuer_cnpj=d.issuer_cnpj,
                issuer_name=d.issuer_name, issuer_uf=d.issuer_uf, recipient_doc=d.recipient_doc,
                recipient_uf=d.recipient_uf, operation_type=d.operation_type, total_amount=d.total_amount,
                icms_total=d.icms_total, status=d.status, has_ibs_cbs_group=d.has_ibs_cbs_group,
                source_file=d.source_file)
            row.items = [FiscalDocumentItemRow(
                tenant_id=tid, item_number=i.item_number, product_code=i.product_code[:60],
                description=i.description, ncm=i.ncm[:8], cfop=i.cfop[:4], quantity=i.quantity,
                gross_amount=i.gross_amount, discount=i.discount, icms_cst=i.icms_cst[:4], icms_base=i.icms_base,
                icms_rate=i.icms_rate, icms_amount=i.icms_amount, ipi_amount=i.ipi_amount, pis_cst=i.pis_cst[:3],
                pis_amount=i.pis_amount, cofins_cst=i.cofins_cst[:3], cofins_amount=i.cofins_amount,
                ibs_cbs_base=i.ibs_cbs_base, ibs_amount=i.ibs_amount, cbs_amount=i.cbs_amount) for i in d.items]
            session.add(row)
        detail = f"{len(records)} NF-e gravadas (chaves existentes substituídas)"
    elif src == SourceType.FISCAL_BOOK:
        replaced = session.execute(delete(BookEntryRow).where(
            BookEntryRow.tenant_id == tid, BookEntryRow.period.in_(periods))).rowcount
        session.add_all([BookEntryRow(
            tenant_id=tid, batch_id=batch.id, access_key=e.access_key, document_number=e.document_number[:20],
            entry_date=e.entry_date, period=e.period, direction=e.direction.value,
            counterparty_cnpj=e.counterparty_cnpj, item_number=e.item_number, cfop=e.cfop, ncm=e.ncm,
            amount=e.amount, icms_base=e.icms_base, icms_credit=e.icms_credit, pis_credit=e.pis_credit,
            cofins_credit=e.cofins_credit, pis_cst=e.pis_cst[:3], source_file=e.source_file,
            source_row=e.source_row) for e in records])
        detail = f"{len(records)} lançamentos gravados · {replaced} substituídos nos mesmos períodos"
    else:
        replaced = session.execute(delete(LedgerEntryRow).where(
            LedgerEntryRow.tenant_id == tid, LedgerEntryRow.period.in_(periods))).rowcount
        session.add_all([LedgerEntryRow(
            tenant_id=tid, batch_id=batch.id, entry_date=e.entry_date, period=e.period, account=e.account[:40],
            account_name=e.account_name[:120], history=e.history, debit=e.debit, credit=e.credit,
            access_key=e.access_key, source_file=e.source_file, source_row=e.source_row) for e in records])
        detail = f"{len(records)} lançamentos contábeis gravados · {replaced} substituídos"
    session.flush()
    _stage(batch, "STORAGE", "DONE", detail)
    session.commit()
