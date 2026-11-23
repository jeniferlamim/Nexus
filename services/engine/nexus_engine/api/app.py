"""NEXUS HTTP API."""
from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Iterator

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import Float, case, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import __version__
from ..audit import log as audit
from ..demo.loader import load_demo
from ..domain.models import SourceType, confidence_label
from ..ingestion.errors import IngestionError
from ..persistence.db import (
    AuditLogRow, BatchError, FindingRow, IngestionBatch, Membership, Tenant, make_engine, make_session_factory,
)
from ..reports.export import findings_xlsx
from ..rules.catalog import DEFAULT_CATALOG
from ..security.auth import Principal, require, resolve_principal
from ..security.rbac import ROLE_LABELS, Permission, Role
from ..seed import seed
from ..services import insights
from ..services.analysis import run_analysis
from ..services.ingestion import STAGE_LABELS, STAGES, DuplicateBatch, create_batch, process_batch
from ..services.review import available_actions, transition

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("nexus.api")

engine = make_engine()
SessionLocal = make_session_factory(engine)
# One worker serialises analysis per process (avoids concurrent re-analysis of the same tenant).
# Production: replace with pgmq/Redis queue + horizontally scaled workers (same process_batch()).
jobs = ThreadPoolExecutor(max_workers=int(os.environ.get("NEXUS_WORKERS", "1")), thread_name_prefix="nexus-job")
SYNC_JOBS = os.environ.get("NEXUS_SYNC_JOBS") == "1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    with SessionLocal() as s:
        seed(s)
    yield
    jobs.shutdown(wait=False)


app = FastAPI(title="NEXUS Enterprise Tax Intelligence API", version=__version__, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    log.info(json.dumps({"method": request.method, "path": request.url.path, "status": response.status_code,
                         "ms": round((time.perf_counter() - t0) * 1000, 1)}))
    return response


@app.exception_handler(IngestionError)
async def ingestion_error(_: Request, exc: IngestionError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def db() -> Iterator[Session]:
    with SessionLocal() as s:
        yield s


def principal(session: Session = Depends(db), authorization: str | None = Header(None),
              x_nexus_user: str | None = Header(None), x_nexus_tenant: str | None = Header(None)) -> Principal:
    return resolve_principal(session, authorization=authorization, x_user=x_nexus_user, x_tenant=x_nexus_tenant)


def module(name: str):
    def check(p: Principal = Depends(principal), session: Session = Depends(db)) -> Principal:
        tenant = session.get(Tenant, p.tenant_id)
        if name not in tenant.plan.modules:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, f"Módulo '{name}' não contratado no plano {tenant.plan.name}")
        return p
    return check


def _run_job(fn, *args) -> None:
    def wrapped():
        try:
            with SessionLocal() as s:
                fn(s, *args)
        except Exception:  # noqa: BLE001 — a background failure must never be silent
            log.exception("background job %s failed", getattr(fn, "__name__", fn))
            if SYNC_JOBS:
                raise
    if SYNC_JOBS:
        wrapped()
    else:
        jobs.submit(wrapped)


# --------------------------------------------------------------------------- serialisers


def finding_out(r: FindingRow, full: bool = False, p: Principal | None = None) -> dict:
    out = {
        "id": r.id, "seq": r.seq, "code": f"NX-{r.seq:05d}", "rule_code": r.rule_code, "rule_version": r.rule_version,
        "category": r.category, "kind": r.kind, "severity": r.severity, "title": r.title, "status": r.status,
        "amount_type": r.amount_type, "estimated_amount": str(r.estimated_amount),
        "validated_amount": str(r.validated_amount) if r.validated_amount is not None else None,
        "confidence": r.confidence, "confidence_label": confidence_label(r.confidence), "tax": r.tax,
        "period": r.period, "access_key": r.access_key, "counterparty_cnpj": r.counterparty_cnpj,
        "counterparty_name": r.counterparty_name, "is_active": r.is_active,
        "requires_human_validation": r.kind != "VALIDATED", "proposal": r.proposal,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
    if full:
        rule = next((v for v in DEFAULT_CATALOG.all() if v.code == r.rule_code and v.version == r.rule_version), None)
        out.update({
            "description": r.description, "methodology": r.methodology, "legal_basis": r.legal_basis,
            "calculation": r.calculation,
            "rule": rule.as_dict() if rule else None,
            "evidence": [{"source": e.source, "locator": e.locator, "field": e.field, "observed": e.observed,
                          "expected": e.expected, "note": e.note} for e in r.evidence],
            "reviews": [{"actor_name": v.actor_name, "actor_role": v.actor_role, "action": v.action,
                         "from_status": v.from_status, "to_status": v.to_status, "comment": v.comment,
                         "validated_amount": str(v.validated_amount) if v.validated_amount is not None else None,
                         "at": v.created_at.isoformat()} for v in r.reviews],
            "actions": available_actions(r, p) if p else [],
        })
    return out


def batch_out(b: IngestionBatch, errors: list[BatchError] | None = None) -> dict:
    done = {s["stage"]: s for s in b.stages or []}
    out = {
        "id": b.id, "source_type": b.source_type, "filename": b.filename, "sha256": b.sha256,
        "size_bytes": b.size_bytes, "status": b.status, "records_total": b.records_total,
        "records_valid": b.records_valid, "records_rejected": b.records_rejected, "warnings": b.warnings,
        "periods": b.periods, "error": b.error, "created_at": b.created_at.isoformat(),
        "finished_at": b.finished_at.isoformat() if b.finished_at else None, "analysis_run_id": b.analysis_run_id,
        "stages": [done.get(s, {"stage": s, "label": STAGE_LABELS[s], "status": "PENDING", "at": None, "detail": ""})
                   for s in STAGES],
    }
    if errors is not None:
        out["errors"] = [{"source": e.source, "locator": e.locator, "field": e.field, "value": e.value,
                          "message": e.message, "severity": e.severity} for e in errors]
    return out


# --------------------------------------------------------------------------- routes: session


@app.get("/api/health")
def health(session: Session = Depends(db)):
    session.execute(select(1))
    return {"status": "ok", "version": __version__, "auth_mode": os.environ.get("AUTH_MODE", "dev")}


@app.get("/api/me")
def me(p: Principal = Depends(principal), session: Session = Depends(db)):
    tenant = session.get(Tenant, p.tenant_id)
    memberships = session.execute(select(Membership).where(Membership.user_id == p.user_id)).scalars().all()
    return {
        "user": {"id": p.user_id, "name": p.name, "email": p.email, "title": memberships[0].user.title if memberships else ""},
        "role": p.role, "role_label": ROLE_LABELS[Role(p.role)], "permissions": sorted(x.value for x in p.permissions),
        "tenant": {"id": tenant.id, "name": tenant.name, "legal_name": tenant.legal_name, "segment": tenant.segment,
                   "cnpj_roots": tenant.cnpj_roots, "tax_regime": tenant.tax_regime,
                   "ledger_accounts": tenant.ledger_accounts, "data_retention_days": tenant.data_retention_days},
        "plan": {"code": tenant.plan.code, "name": tenant.plan.name, "modules": tenant.plan.modules,
                 "max_documents_month": tenant.plan.max_documents_month, "max_users": tenant.plan.max_users,
                 "max_file_mb": tenant.plan.max_file_mb},
        "tenants": [{"id": m.tenant.id, "name": m.tenant.name, "role": m.role} for m in memberships],
    }


@app.get("/api/demo/users")
def demo_users(session: Session = Depends(db)):
    """Dev-mode only: lists demo personas for the persona switcher."""
    if os.environ.get("AUTH_MODE", "dev") != "dev":
        raise HTTPException(404)
    ms = session.execute(select(Membership)).scalars().all()
    return [{"user_id": m.user_id, "name": m.user.name, "title": m.user.title, "tenant_id": m.tenant_id,
             "tenant_name": m.tenant.name, "role": m.role, "role_label": ROLE_LABELS[Role(m.role)]} for m in ms]


# --------------------------------------------------------------------------- routes: ingestion


@app.post("/api/ingestion/upload", status_code=202)
async def upload(source_type: SourceType = Form(...), file: UploadFile = File(...),
                 p: Principal = Depends(module("ingestion")), session: Session = Depends(db)):
    require(p, Permission.INGEST)
    content = await file.read()
    if not content:
        raise HTTPException(422, "Arquivo vazio")
    try:
        batch = create_batch(session, p, source_type, file.filename or "arquivo", content)
        session.commit()
    except DuplicateBatch as dup:
        raise HTTPException(409, f"Arquivo idêntico já importado em {dup.batch.created_at:%d/%m/%Y %H:%M} "
                                 f"(lote {dup.batch.id[:8]})")
    _run_job(process_batch, p, batch.id, content)
    return batch_out(batch)


@app.get("/api/ingestion/batches")
def batches(p: Principal = Depends(principal), session: Session = Depends(db)):
    rows = session.execute(select(IngestionBatch).where(IngestionBatch.tenant_id == p.tenant_id)
                           .order_by(IngestionBatch.created_at.desc()).limit(100)).scalars()
    return [batch_out(b) for b in rows]


@app.get("/api/ingestion/batches/{batch_id}")
def batch_detail(batch_id: str, p: Principal = Depends(principal), session: Session = Depends(db)):
    b = session.execute(select(IngestionBatch).where(IngestionBatch.id == batch_id,
                                                     IngestionBatch.tenant_id == p.tenant_id)).scalar_one_or_none()
    if not b:
        raise HTTPException(404, "Lote não encontrado")
    errs = session.execute(select(BatchError).where(BatchError.batch_id == b.id, BatchError.tenant_id == p.tenant_id)
                           .order_by(BatchError.id).limit(500)).scalars().all()
    return batch_out(b, errs)


@app.post("/api/demo/load", status_code=202)
def demo_load(p: Principal = Depends(module("ingestion"))):
    require(p, Permission.INGEST)
    _run_job(load_demo, p)
    return {"status": "queued"}


# --------------------------------------------------------------------------- routes: analysis


@app.post("/api/analysis/run", status_code=202)
def analysis_run(p: Principal = Depends(principal)):
    require(p, Permission.RUN_ANALYSIS)
    _run_job(lambda s, pr: run_analysis(s, pr, trigger="MANUAL"), p)
    return {"status": "queued"}


@app.get("/api/dashboard")
def dashboard(p: Principal = Depends(module("executive_dashboard")), session: Session = Depends(db)):
    return insights.dashboard(session, p.tenant_id)


@app.get("/api/reconciliation")
def reconciliation(p: Principal = Depends(module("tax_reconciliation")), session: Session = Depends(db)):
    return insights.reconciliation(session, p.tenant_id)


SEVERITY_RANK = case({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}, value=FindingRow.severity, else_=5)
# money is TEXT on SQLite: cast so "amount" sorts numerically on every backend
SORTS = {"amount": cast(FindingRow.estimated_amount, Float).desc(), "severity": SEVERITY_RANK, "recent": FindingRow.updated_at.desc(),
         "confidence": FindingRow.confidence.desc(), "seq": FindingRow.seq}


def _finding_query(p: Principal, category, kind, severity, status_, tax, amount_type, q, include_inactive, counterparty):
    stmt = select(FindingRow).where(FindingRow.tenant_id == p.tenant_id)
    if not include_inactive:
        stmt = stmt.where(FindingRow.is_active.is_(True))
    for col, val in ((FindingRow.category, category), (FindingRow.kind, kind), (FindingRow.severity, severity),
                     (FindingRow.status, status_), (FindingRow.tax, tax), (FindingRow.amount_type, amount_type),
                     (FindingRow.counterparty_cnpj, counterparty)):
        if val:
            stmt = stmt.where(col.in_(val.split(",")))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(FindingRow.title.ilike(like), FindingRow.access_key.ilike(like),
                              FindingRow.counterparty_name.ilike(like), FindingRow.counterparty_cnpj.ilike(like),
                              FindingRow.rule_code.ilike(like)))
    return stmt


@app.get("/api/findings")
def findings(category: str | None = None, kind: str | None = None, severity: str | None = None,
             status_: str | None = Query(None, alias="status"), tax: str | None = None,
             amount_type: str | None = None, q: str | None = None, counterparty: str | None = None,
             include_inactive: bool = False, sort: str = "amount", limit: int = Query(100, le=500),
             offset: int = 0, p: Principal = Depends(principal), session: Session = Depends(db)):
    stmt = _finding_query(p, category, kind, severity, status_, tax, amount_type, q, include_inactive, counterparty)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    agg: dict[str, Decimal] = {}
    for amount_type_, amount in session.execute(
            select(FindingRow.amount_type, FindingRow.estimated_amount).where(
                FindingRow.id.in_(select(stmt.subquery().c.id)))):
        agg[amount_type_] = agg.get(amount_type_, Decimal(0)) + amount
    rows = session.execute(stmt.order_by(SORTS.get(sort, SORTS["amount"]), FindingRow.seq).offset(offset).limit(limit)).scalars()
    return {"total": total, "totals_by_amount_type": {k: str(v) for k, v in agg.items()},
            "items": [finding_out(r) for r in rows]}


@app.get("/api/findings/{finding_id}")
def finding_detail(finding_id: str, p: Principal = Depends(principal), session: Session = Depends(db)):
    r = session.execute(select(FindingRow).where(FindingRow.id == finding_id, FindingRow.tenant_id == p.tenant_id)
                        .options(selectinload(FindingRow.evidence), selectinload(FindingRow.reviews))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Ocorrência não encontrada")
    return finding_out(r, full=True, p=p)


class TransitionIn(BaseModel):
    action: str
    comment: str = Field("", max_length=4000)
    validated_amount: str | None = None


@app.post("/api/findings/{finding_id}/transition")
def finding_transition(finding_id: str, body: TransitionIn, p: Principal = Depends(principal),
                       session: Session = Depends(db)):
    r = session.execute(select(FindingRow).where(FindingRow.id == finding_id, FindingRow.tenant_id == p.tenant_id)
                        .with_for_update()).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Ocorrência não encontrada")
    transition(session, p, r, body.action, body.comment, body.validated_amount)
    session.refresh(r)
    return finding_out(r, full=True, p=p)


@app.get("/api/reports/findings.xlsx")
def export_findings(category: str | None = None, kind: str | None = None, severity: str | None = None,
                    status_: str | None = Query(None, alias="status"), tax: str | None = None,
                    amount_type: str | None = None, q: str | None = None,
                    p: Principal = Depends(principal), session: Session = Depends(db)):
    require(p, Permission.EXPORT)
    stmt = _finding_query(p, category, kind, severity, status_, tax, amount_type, q, False, None)
    rows = session.execute(stmt.order_by(FindingRow.seq).options(selectinload(FindingRow.evidence))).scalars().all()
    tenant = session.get(Tenant, p.tenant_id)
    content = findings_xlsx(tenant, rows, p.name)
    audit.record(session, tenant_id=p.tenant_id, actor_id=p.user_id, actor_name=p.name, action="report.exported",
                 entity_type="report", entity_id="findings.xlsx", payload={"rows": len(rows)})
    session.commit()
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="nexus-ocorrencias.xlsx"'})


# --------------------------------------------------------------------------- routes: governance


@app.get("/api/rules")
def rules(p: Principal = Depends(principal)):
    return [r.as_dict() for r in sorted(DEFAULT_CATALOG.all(), key=lambda r: (r.code, r.version))]


@app.get("/api/audit")
def audit_log(limit: int = Query(200, le=1000), p: Principal = Depends(module("audit_trail")),
              session: Session = Depends(db)):
    require(p, Permission.VIEW_AUDIT)
    rows = session.execute(select(AuditLogRow).where(AuditLogRow.tenant_id == p.tenant_id)
                           .order_by(AuditLogRow.seq.desc()).limit(limit)).scalars()
    return [{"seq": r.seq, "at": r.created_at, "actor_name": r.actor_name, "action": r.action,
             "entity_type": r.entity_type, "entity_id": r.entity_id, "payload": r.payload,
             "hash": r.hash, "prev_hash": r.prev_hash} for r in rows]


@app.get("/api/audit/verify")
def audit_verify(p: Principal = Depends(module("audit_trail")), session: Session = Depends(db)):
    require(p, Permission.VIEW_AUDIT)
    return audit.verify(session, p.tenant_id)
