"""SQLAlchemy schema. Mirrors ``supabase/migrations`` (which adds RLS and grants).

Portable: SQLite for local/demo, PostgreSQL (Supabase) in production via ``DATABASE_URL``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint, create_engine, event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Money(TypeDecorator):
    """Exact decimal money: NUMERIC(18,2) on PostgreSQL, TEXT on SQLite (no float drift)."""
    impl = Numeric(18, 2)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(32))
        return dialect.type_descriptor(Numeric(18, 2))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        value = Decimal(value)
        return str(value) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class TenantScoped:
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)


# --------------------------------------------------------------------------- tenancy


class Plan(Base):
    __tablename__ = "plans"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    modules: Mapped[list] = mapped_column(JSON)
    max_documents_month: Mapped[int] = mapped_column(Integer)
    max_users: Mapped[int] = mapped_column(Integer)
    max_file_mb: Mapped[int] = mapped_column(Integer, default=200)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    legal_name: Mapped[str] = mapped_column(String(200))
    segment: Mapped[str] = mapped_column(String(80), default="")
    cnpj_roots: Mapped[list] = mapped_column(JSON)
    plan_code: Mapped[str] = mapped_column(ForeignKey("plans.code"))
    tax_regime: Mapped[str] = mapped_column(String(32), default="NON_CUMULATIVE")
    ipi_taxpayer: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True)
    ledger_accounts: Mapped[dict] = mapped_column(JSON, default=dict)
    data_retention_days: Mapped[int] = mapped_column(Integer, default=1825)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    plan: Mapped[Plan] = relationship()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(120), default="")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    user: Mapped[User] = relationship()
    tenant: Mapped[Tenant] = relationship()


# --------------------------------------------------------------------------- ingestion


class IngestionBatch(TenantScoped, Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (UniqueConstraint("tenant_id", "sha256"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_type: Mapped[str] = mapped_column(String(32))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="QUEUED")  # QUEUED|RUNNING|COMPLETED|COMPLETED_WITH_WARNINGS|FAILED
    stages: Mapped[list] = mapped_column(JSON, default=list)
    records_total: Mapped[int] = mapped_column(Integer, default=0)
    records_valid: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    periods: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BatchError(TenantScoped, Base):
    __tablename__ = "batch_errors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(255))
    locator: Mapped[str] = mapped_column(String(120))
    field: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(16))


class FiscalDocumentRow(TenantScoped, Base):
    __tablename__ = "fiscal_documents"
    __table_args__ = (UniqueConstraint("tenant_id", "access_key"), Index("ix_doc_tenant_period", "tenant_id", "period"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id"))
    access_key: Mapped[str] = mapped_column(String(44))
    model: Mapped[str] = mapped_column(String(2))
    series: Mapped[str] = mapped_column(String(3))
    number: Mapped[str] = mapped_column(String(9))
    issue_date: Mapped[datetime] = mapped_column(Date)
    period: Mapped[str] = mapped_column(String(7))
    issuer_cnpj: Mapped[str] = mapped_column(String(14), index=True)
    issuer_name: Mapped[str] = mapped_column(String(120))
    issuer_uf: Mapped[str] = mapped_column(String(2))
    recipient_doc: Mapped[str] = mapped_column(String(20))
    recipient_uf: Mapped[str] = mapped_column(String(2))
    operation_type: Mapped[str] = mapped_column(String(1))
    total_amount: Mapped[Decimal] = mapped_column(Money)
    icms_total: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(24))
    has_ibs_cbs_group: Mapped[bool] = mapped_column(Boolean, default=False)
    source_file: Mapped[str] = mapped_column(String(255))
    items: Mapped[list["FiscalDocumentItemRow"]] = relationship(cascade="all, delete-orphan",
                                                                 order_by="FiscalDocumentItemRow.item_number")


class FiscalDocumentItemRow(TenantScoped, Base):
    __tablename__ = "fiscal_document_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("fiscal_documents.id", ondelete="CASCADE"), index=True)
    item_number: Mapped[int] = mapped_column(Integer)
    product_code: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(120))
    ncm: Mapped[str] = mapped_column(String(8))
    cfop: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[Decimal] = mapped_column(Money)
    gross_amount: Mapped[Decimal] = mapped_column(Money)
    discount: Mapped[Decimal] = mapped_column(Money)
    icms_cst: Mapped[str] = mapped_column(String(4))
    icms_base: Mapped[Decimal] = mapped_column(Money)
    icms_rate: Mapped[Decimal] = mapped_column(Money)
    icms_amount: Mapped[Decimal] = mapped_column(Money)
    ipi_amount: Mapped[Decimal] = mapped_column(Money)
    pis_cst: Mapped[str] = mapped_column(String(3))
    pis_amount: Mapped[Decimal] = mapped_column(Money)
    cofins_cst: Mapped[str] = mapped_column(String(3))
    cofins_amount: Mapped[Decimal] = mapped_column(Money)
    ibs_cbs_base: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    ibs_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    cbs_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)


class BookEntryRow(TenantScoped, Base):
    __tablename__ = "book_entries"
    __table_args__ = (Index("ix_book_tenant_key", "tenant_id", "access_key"), Index("ix_book_tenant_period", "tenant_id", "period"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id"))
    access_key: Mapped[str] = mapped_column(String(44))
    document_number: Mapped[str] = mapped_column(String(20))
    entry_date: Mapped[datetime] = mapped_column(Date)
    period: Mapped[str] = mapped_column(String(7))
    direction: Mapped[str] = mapped_column(String(10))
    counterparty_cnpj: Mapped[str] = mapped_column(String(14))
    item_number: Mapped[int] = mapped_column(Integer)
    cfop: Mapped[str] = mapped_column(String(4))
    ncm: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(Money)
    icms_base: Mapped[Decimal] = mapped_column(Money)
    icms_credit: Mapped[Decimal] = mapped_column(Money)
    pis_credit: Mapped[Decimal] = mapped_column(Money)
    cofins_credit: Mapped[Decimal] = mapped_column(Money)
    ipi_credit: Mapped[Decimal | None] = mapped_column(Money, nullable=True, default=Decimal(0))
    pis_cst: Mapped[str] = mapped_column(String(3))
    source_file: Mapped[str] = mapped_column(String(255))
    source_row: Mapped[int] = mapped_column(Integer)


class LedgerEntryRow(TenantScoped, Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (Index("ix_ledger_tenant_period", "tenant_id", "period"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("ingestion_batches.id"))
    entry_date: Mapped[datetime] = mapped_column(Date)
    period: Mapped[str] = mapped_column(String(7))
    account: Mapped[str] = mapped_column(String(40))
    account_name: Mapped[str] = mapped_column(String(120))
    history: Mapped[str] = mapped_column(String(200))
    debit: Mapped[Decimal] = mapped_column(Money)
    credit: Mapped[Decimal] = mapped_column(Money)
    access_key: Mapped[str] = mapped_column(String(44))
    source_file: Mapped[str] = mapped_column(String(255))
    source_row: Mapped[int] = mapped_column(Integer)


# --------------------------------------------------------------------------- analysis


class AnalysisRun(TenantScoped, Base):
    __tablename__ = "analysis_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    trigger: Mapped[str] = mapped_column(String(32))         # INGESTION | MANUAL
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")
    started_by: Mapped[str] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    engine_version: Mapped[str] = mapped_column(String(16))
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    rule_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    findings_total: Mapped[int] = mapped_column(Integer, default=0)
    findings_new: Mapped[int] = mapped_column(Integer, default=0)
    findings_resolved: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)


class FindingRow(TenantScoped, Base):
    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("tenant_id", "fingerprint"),
                      Index("ix_findings_tenant_status", "tenant_id", "status"),
                      Index("ix_findings_tenant_cat", "tenant_id", "category"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    seq: Mapped[int] = mapped_column(Integer)                       # human-friendly per-tenant id
    fingerprint: Mapped[str] = mapped_column(String(32))
    first_run_id: Mapped[str] = mapped_column(String(36))
    last_run_id: Mapped[str] = mapped_column(String(36))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # still detected in latest run
    rule_code: Mapped[str] = mapped_column(String(16), index=True)
    rule_version: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    methodology: Mapped[str] = mapped_column(Text)
    legal_basis: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    amount_type: Mapped[str] = mapped_column(String(32))
    estimated_amount: Mapped[Decimal] = mapped_column(Money)
    validated_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    tax: Mapped[str | None] = mapped_column(String(24), nullable=True)
    access_key: Mapped[str | None] = mapped_column(String(44), nullable=True)
    counterparty_cnpj: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    period: Mapped[str | None] = mapped_column(String(7), nullable=True)
    calculation: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="OPEN")
    proposal: Mapped[str | None] = mapped_column(String(16), nullable=True)
    proposed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    evidence: Mapped[list["FindingEvidenceRow"]] = relationship(cascade="all, delete-orphan",
                                                                  order_by="FindingEvidenceRow.id")
    reviews: Mapped[list["FindingReviewRow"]] = relationship(order_by="FindingReviewRow.created_at")


class FindingEvidenceRow(TenantScoped, Base):
    __tablename__ = "finding_evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(255))
    locator: Mapped[str] = mapped_column(String(160))
    field: Mapped[str] = mapped_column(String(80))
    observed: Mapped[str] = mapped_column(String(200))
    expected: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(String(300), default="")


class FindingReviewRow(TenantScoped, Base):
    __tablename__ = "finding_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(36))
    actor_name: Mapped[str] = mapped_column(String(120))
    actor_role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    comment: Mapped[str] = mapped_column(Text, default="")
    validated_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# --------------------------------------------------------------------------- audit


class AuditLogRow(Base):
    __tablename__ = "audit_log"
    __table_args__ = (UniqueConstraint("tenant_id", "seq", name="uq_audit_tenant_seq"),)  # a race forks nothing: it fails
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(36))
    seq: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))
    actor_name: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(40))  # ISO-8601 string: hashed verbatim
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


# --------------------------------------------------------------------------- engine


def make_engine(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL") or "sqlite:///" + os.path.join(
        os.environ.get("NEXUS_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data")), "nexus.db")
    if url.startswith("sqlite:///"):
        os.makedirs(os.path.dirname(os.path.abspath(url.removeprefix("sqlite:///"))), exist_ok=True)
    engine = create_engine(url, future=True, pool_pre_ping=True,
                           connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def ensure_columns(engine) -> list[str]:
    """Local/SQLite upgrade path: add columns introduced after a database was first created.

    Only additive, nullable columns are handled here. Production (Supabase) uses the versioned SQL
    migrations in supabase/migrations instead.
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    added: list[str] = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing or not col.nullable:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl_type}'))
                added.append(f"{table.name}.{col.name}")
    return added
