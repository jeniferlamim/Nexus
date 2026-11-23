from sqlalchemy import update

from conftest import H, T1, T2, U_ADMIN, U_ANALYST, U_AUDITOR, U_CFO, U_DIRECTOR

from nexus_engine.api.app import SessionLocal
from nexus_engine.persistence.db import AuditLogRow, Plan, Tenant


def test_demo_load_runs_full_pipeline(client, loaded):
    batches = client.get("/api/ingestion/batches", headers=H(U_ANALYST)).json()
    assert len(batches) == 3 and all(b["status"].startswith("COMPLETED") for b in batches)
    book = next(b for b in batches if b["source_type"] == "FISCAL_BOOK")
    assert [s["status"] for s in book["stages"]] == ["DONE"] * 8


def test_dashboard_separates_amount_natures(client, loaded):
    d = client.get("/api/dashboard", headers=H(U_CFO)).json()
    k = d["kpis"]
    assert float(k["recoverable_estimate"]) > 0 and float(k["exposure_estimate"]) > 0
    assert float(k["recoverable_weighted"]) < float(k["recoverable_estimate"])
    assert d["coverage"]["documents"] > 0


def test_reimport_same_file_is_idempotent(client, loaded, dataset):
    r = client.post("/api/ingestion/upload", headers=H(U_ANALYST), data={"source_type": "FISCAL_BOOK"},
                    files={"file": ("copia_do_livro.csv", dataset.book_csv)})
    assert r.status_code == 409


def test_tenant_isolation(client, loaded):
    f = client.get("/api/findings?limit=1", headers=H(U_DIRECTOR, T1)).json()["items"][0]
    assert client.get(f"/api/findings/{f['id']}", headers=H(U_DIRECTOR, T2)).status_code == 404
    assert client.get("/api/findings", headers=H(U_DIRECTOR, T2)).json()["total"] == 0
    # a user without membership in T2 cannot even select it
    assert client.get("/api/me", headers=H(U_ANALYST, T2)).status_code == 403


def test_rbac(client, loaded):
    files = {"file": ("x.csv", b"a;b\n1;2\n")}
    assert client.post("/api/ingestion/upload", headers=H(U_AUDITOR), data={"source_type": "LEDGER"},
                       files=files).status_code == 403
    assert client.get("/api/audit", headers=H(U_ANALYST)).status_code == 403
    assert client.get("/api/audit", headers=H(U_AUDITOR)).status_code == 200
    assert client.post("/api/analysis/run", headers=H(U_CFO)).status_code == 403


def test_review_workflow_with_segregation_of_duties(client, loaded):
    items = client.get("/api/findings?amount_type=RECOVERABLE_ESTIMATE&status=OPEN&limit=2",
                       headers=H(U_ANALYST)).json()["items"]
    fid, fid2 = items[0]["id"], items[1]["id"]
    t = lambda user, action, comment="Justificativa detalhada do revisor", **kw: client.post(  # noqa: E731
        f"/api/findings/{fid}/transition", headers=H(user), json={"action": action, "comment": comment, **kw})

    assert t(U_ANALYST, "approve").status_code == 403                  # analysts cannot approve
    assert t(U_ANALYST, "start_review").json()["status"] == "IN_REVIEW"
    assert t(U_ANALYST, "propose_validation", comment="curto").status_code == 422  # justification required
    assert t(U_ANALYST, "propose_validation").json()["status"] == "PENDING_APPROVAL"
    r = t(U_DIRECTOR, "approve", validated_amount="1000.50").json()
    assert r["status"] == "VALIDATED" and r["kind"] == "VALIDATED" and r["validated_amount"] == "1000.50"
    assert [v["action"] for v in r["reviews"]] == ["start_review", "propose_validation", "approve"]

    # the proposer can never approve their own proposal
    p = lambda action: client.post(f"/api/findings/{fid2}/transition", headers=H(U_DIRECTOR),  # noqa: E731
                                   json={"action": action, "comment": "Proposta pelo próprio diretor"})
    assert p("propose_dismissal").status_code == 200
    assert p("approve").status_code == 403

    d = client.get("/api/dashboard", headers=H(U_CFO)).json()
    assert d["kpis"]["validated_recoverable"] == "1000.50"


def test_reanalysis_preserves_human_decisions(client, loaded):
    validated = client.get("/api/findings?status=VALIDATED", headers=H(U_DIRECTOR)).json()["items"]
    assert client.post("/api/analysis/run", headers=H(U_ANALYST)).status_code == 202
    again = client.get("/api/findings?status=VALIDATED", headers=H(U_DIRECTOR)).json()["items"]
    assert [f["id"] for f in again] == [f["id"] for f in validated]
    assert again[0]["validated_amount"] == "1000.50"


def test_audit_chain_verifies_and_detects_tampering(client, loaded):
    v = client.get("/api/audit/verify", headers=H(U_AUDITOR)).json()
    assert v["valid"] and v["entries"] > 5
    with SessionLocal() as s:
        s.execute(update(AuditLogRow).where(AuditLogRow.tenant_id == T1, AuditLogRow.seq == 2)
                  .values(actor_name="Adulterado"))
        s.commit()
    v = client.get("/api/audit/verify", headers=H(U_AUDITOR)).json()
    assert not v["valid"] and v["broken_at_seq"] == 2


def test_plan_module_gating_and_document_limit(client, dataset):
    with SessionLocal() as s:
        s.add(Plan(code="TINY", name="Tiny", modules=["ingestion", "audit_trail"], max_documents_month=10,
                   max_users=1, max_file_mb=50))
        s.flush()
        s.execute(update(Tenant).where(Tenant.id == T2).values(plan_code="TINY"))
        s.commit()
    assert client.get("/api/dashboard", headers=H(U_DIRECTOR, T2)).status_code == 402
    r = client.post("/api/ingestion/upload", headers=H(U_DIRECTOR, T2), data={"source_type": "NFE_XML"},
                    files={"file": ("lote.zip", dataset.xml_zip)})
    assert r.status_code == 202
    b = client.get(f"/api/ingestion/batches/{r.json()['id']}", headers=H(U_DIRECTOR, T2)).json()
    assert b["status"] == "FAILED" and "Limite do plano" in b["error"]
    with SessionLocal() as s:
        s.execute(update(Tenant).where(Tenant.id == T2).values(plan_code="PROFESSIONAL"))
        s.commit()


def test_export_xlsx(client, loaded):
    r = client.get("/api/reports/findings.xlsx", headers=H(U_AUDITOR))
    assert r.status_code == 200 and r.content[:2] == b"PK"
