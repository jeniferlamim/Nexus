"""Reference data (plans) and demo tenants/users. Idempotent."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .persistence.db import Base, Membership, Plan, Tenant, User

ALL_MODULES = ["executive_dashboard", "ingestion", "tax_reconciliation", "tax_intelligence", "credit_recovery",
               "tax_risk", "audit_trail", "tax_simulator", "supplier_intelligence", "financial_intelligence",
               "ai_copilot"]

PLANS = [
    Plan(code="ESSENTIALS", name="Essentials", max_documents_month=50_000, max_users=10, max_file_mb=100,
         modules=["executive_dashboard", "ingestion", "tax_reconciliation", "audit_trail"]),
    Plan(code="PROFESSIONAL", name="Professional", max_documents_month=250_000, max_users=40, max_file_mb=200,
         modules=["executive_dashboard", "ingestion", "tax_reconciliation", "tax_intelligence", "credit_recovery",
                  "tax_risk", "audit_trail"]),
    Plan(code="ENTERPRISE", name="Enterprise", max_documents_month=2_000_000, max_users=500, max_file_mb=500,
         modules=ALL_MODULES),
]

T1 = "7a1f3c52-0d4e-4b8a-9a61-2f0c5e9b1a01"
T2 = "c3e8b9d4-5f21-4a77-8e0b-6d4a2c1f9e02"
U_DIRECTOR = "11111111-1111-4111-8111-111111111111"
U_ANALYST = "22222222-2222-4222-8222-222222222222"
U_AUDITOR = "33333333-3333-4333-8333-333333333333"
U_ADMIN = "44444444-4444-4444-8444-444444444444"
U_CFO = "55555555-5555-4555-8555-555555555555"

TENANTS = [
    dict(id=T1, name="Vértice Componentes", legal_name="Vértice Componentes Industriais S.A.",
         segment="Indústria metalmecânica · SP/MG", cnpj_roots=["45723174"], plan_code="ENTERPRISE",
         tax_regime="NON_CUMULATIVE",
         ledger_accounts={"ICMS": ["1.1.3.01"], "PIS": ["1.1.3.02"], "COFINS": ["1.1.3.03"]}),
    dict(id=T2, name="Rede Aurora", legal_name="Rede Aurora Supermercados Ltda",
         segment="Varejo alimentar · 4 UFs", cnpj_roots=["31954862"], plan_code="PROFESSIONAL",
         tax_regime="NON_CUMULATIVE", ledger_accounts={}),
]

USERS = [
    dict(id=U_DIRECTOR, email="ricardo.almeida@vertice.example", name="Ricardo Almeida", title="Diretor Tributário"),
    dict(id=U_ANALYST, email="camila.nogueira@vertice.example", name="Camila Nogueira", title="Analista Tributária Sênior"),
    dict(id=U_AUDITOR, email="paulo.siqueira@auditoria.example", name="Paulo Siqueira", title="Auditor Externo"),
    dict(id=U_ADMIN, email="bruno.teixeira@vertice.example", name="Bruno Teixeira", title="Administrador da Plataforma"),
    dict(id=U_CFO, email="fernanda.lima@vertice.example", name="Fernanda Lima", title="CFO"),
]

MEMBERSHIPS = [
    (T1, U_DIRECTOR, "tax_director"), (T1, U_ANALYST, "tax_analyst"), (T1, U_AUDITOR, "auditor"),
    (T1, U_ADMIN, "admin"), (T1, U_CFO, "viewer"), (T2, U_DIRECTOR, "tax_director"), (T2, U_ADMIN, "admin"),
]


def seed(session: Session) -> None:
    Base.metadata.create_all(session.get_bind())
    for p in PLANS:
        session.merge(Plan(**{c.name: getattr(p, c.name) for c in Plan.__table__.columns}))
    for t in TENANTS:
        if not session.get(Tenant, t["id"]):
            session.add(Tenant(**t))
    for u in USERS:
        if not session.get(User, u["id"]):
            session.add(User(**u))
    session.flush()
    existing = {(m.tenant_id, m.user_id) for m in session.query(Membership).all()}
    for tid, uid, role in MEMBERSHIPS:
        if (tid, uid) not in existing:
            session.add(Membership(tenant_id=tid, user_id=uid, role=role))
    session.commit()
