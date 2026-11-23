"""Read models for the dashboard and reconciliation screens."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.models import ZERO
from ..persistence.db import (
    AnalysisRun, BookEntryRow, FindingRow, FiscalDocumentRow, LedgerEntryRow, Tenant,
)

REC, EXP, DIV = "RECOVERABLE_ESTIMATE", "EXPOSURE_ESTIMATE", "DIVERGENCE_VALUE"


def s(v: Decimal) -> str:
    return str(Decimal(v).quantize(Decimal("0.01")))


def dashboard(session: Session, tenant_id: str) -> dict:
    rows = list(session.execute(select(FindingRow).where(
        FindingRow.tenant_id == tenant_id, FindingRow.is_active.is_(True))).scalars())
    live = [r for r in rows if r.status != "DISMISSED"]

    def tot(rs, t, weighted=False):
        return sum(((r.estimated_amount * Decimal(str(r.confidence))) if weighted else r.estimated_amount
                    for r in rs if r.amount_type == t), ZERO)

    by_tax: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"recoverable": ZERO, "exposure": ZERO})
    by_period: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"recoverable": ZERO, "exposure": ZERO, "divergence": ZERO})
    by_cat: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount": ZERO})
    by_sev: dict[str, int] = defaultdict(int)
    suppliers: dict[str, dict] = {}
    for r in live:
        key = {REC: "recoverable", EXP: "exposure", DIV: "divergence"}.get(r.amount_type)
        if r.tax and key in ("recoverable", "exposure"):
            by_tax[r.tax][key] += r.estimated_amount
        if r.period and key:
            by_period[r.period][key] += r.estimated_amount
        by_cat[r.category]["count"] += 1
        by_cat[r.category]["amount"] += r.estimated_amount if key in ("recoverable", "exposure") else ZERO
        if r.status in ("OPEN", "IN_REVIEW", "PENDING_APPROVAL"):
            by_sev[r.severity] += 1
        if r.counterparty_cnpj and r.counterparty_name and r.category != "TAX_REFORM":
            sp = suppliers.setdefault(r.counterparty_cnpj, {"cnpj": r.counterparty_cnpj, "name": r.counterparty_name,
                                                             "findings": 0, "recoverable": ZERO, "exposure": ZERO,
                                                             "critical": 0})
            sp["findings"] += 1
            sp["critical"] += r.severity in ("CRITICAL", "HIGH")
            if key in ("recoverable", "exposure"):
                sp[key] += r.estimated_amount

    pipeline = []
    for st in ("OPEN", "IN_REVIEW", "PENDING_APPROVAL", "VALIDATED", "DISMISSED"):
        rs = [r for r in rows if r.amount_type == REC and r.status == st]
        amt = sum(((r.validated_amount if st == "VALIDATED" and r.validated_amount is not None else r.estimated_amount)
                   for r in rs), ZERO)
        pipeline.append({"status": st, "count": len(rs), "amount": s(amt)})

    top = sorted([r for r in live if r.amount_type in (REC, EXP)], key=lambda r: r.estimated_amount, reverse=True)[:10]
    runs = list(session.execute(select(AnalysisRun).where(AnalysisRun.tenant_id == tenant_id)
                                .order_by(AnalysisRun.started_at.desc()).limit(12)).scalars())
    tenant = session.get(Tenant, tenant_id)
    n_docs = session.scalar(select(func.count()).select_from(FiscalDocumentRow).where(FiscalDocumentRow.tenant_id == tenant_id))
    periods = sorted(p for (p,) in session.execute(select(FiscalDocumentRow.period).where(
        FiscalDocumentRow.tenant_id == tenant_id).distinct()))
    xml_total = session.scalar(select(func.coalesce(func.count(), 0)).select_from(FiscalDocumentRow).where(
        FiscalDocumentRow.tenant_id == tenant_id))
    validated = [r for r in rows if r.status == "VALIDATED" and r.amount_type == REC]
    return {
        "kpis": {
            "recoverable_estimate": s(tot(live, REC)),
            "recoverable_weighted": s(tot(live, REC, weighted=True)),
            "exposure_estimate": s(tot(live, EXP)),
            "exposure_weighted": s(tot(live, EXP, weighted=True)),
            "divergence_value": s(tot(live, DIV)),
            "validated_recoverable": s(sum(((r.validated_amount or ZERO) for r in validated), ZERO)),
            "validated_count": len(validated),
            "findings_active": len(live),
            "open": sum(r.status == "OPEN" for r in live),
            "in_review": sum(r.status == "IN_REVIEW" for r in live),
            "pending_approval": sum(r.status == "PENDING_APPROVAL" for r in live),
            "critical_open": sum(r.severity == "CRITICAL" and r.status in ("OPEN", "IN_REVIEW") for r in live),
        },
        "by_tax": [{"tax": k, "recoverable": s(v["recoverable"]), "exposure": s(v["exposure"])}
                   for k, v in sorted(by_tax.items(), key=lambda kv: -(kv[1]["recoverable"] + kv[1]["exposure"]))],
        "by_period": [{"period": k, **{kk: s(vv) for kk, vv in v.items()}} for k, v in sorted(by_period.items())],
        "by_category": [{"category": k, "count": v["count"], "amount": s(v["amount"])} for k, v in by_cat.items()],
        "by_severity": dict(by_sev),
        "credit_pipeline": pipeline,
        "top_findings": [{"id": r.id, "seq": r.seq, "title": r.title, "amount": s(r.estimated_amount),
                          "amount_type": r.amount_type, "severity": r.severity, "confidence": r.confidence,
                          "status": r.status, "rule_code": r.rule_code, "tax": r.tax, "kind": r.kind} for r in top],
        "top_suppliers": [{**v, "recoverable": s(v["recoverable"]), "exposure": s(v["exposure"])} for v in sorted(
            suppliers.values(), key=lambda v: -(v["recoverable"] + v["exposure"]))[:8]],
        "coverage": {"documents": n_docs or 0, "periods": periods, "xml_total": xml_total or 0,
                     "book_entries": session.scalar(select(func.count()).select_from(BookEntryRow).where(BookEntryRow.tenant_id == tenant_id)) or 0,
                     "ledger_entries": session.scalar(select(func.count()).select_from(LedgerEntryRow).where(LedgerEntryRow.tenant_id == tenant_id)) or 0,
                     "tax_regime": tenant.tax_regime},
        "runs": [{"id": r.id, "started_at": r.started_at.isoformat(), "trigger": r.trigger, "status": r.status,
                  "findings_total": r.findings_total, "findings_new": r.findings_new,
                  "findings_resolved": r.findings_resolved, "engine_version": r.engine_version,
                  "rule_versions": r.rule_versions, "stats": r.stats,
                  "amount_by_type": (r.report or {}).get("amount_by_type", {})} for r in runs],
    }


def reconciliation(session: Session, tenant_id: str) -> dict:
    tenant = session.get(Tenant, tenant_id)
    roots = set(tenant.cnpj_roots)
    docs = session.execute(select(FiscalDocumentRow.access_key, FiscalDocumentRow.period, FiscalDocumentRow.issuer_cnpj,
                                  FiscalDocumentRow.total_amount, FiscalDocumentRow.icms_total)
                           .where(FiscalDocumentRow.tenant_id == tenant_id)).all()
    book = session.execute(select(BookEntryRow.access_key, BookEntryRow.period, BookEntryRow.direction,
                                  BookEntryRow.icms_credit, BookEntryRow.pis_credit, BookEntryRow.cofins_credit,
                                  BookEntryRow.ipi_credit)
                           .where(BookEntryRow.tenant_id == tenant_id)).all()
    book_keys = {b.access_key for b in book}
    xml_keys = {d.access_key for d in docs}
    per: dict[str, dict] = defaultdict(lambda: {"xml_in": 0, "xml_out": 0, "matched": 0, "xml_only": 0, "book_only": 0,
                                                "xml_value": ZERO, "unmatched_value": ZERO})
    for d in docs:
        p = per[d.period]
        p["xml_out" if d.issuer_cnpj[:8] in roots else "xml_in"] += 1
        p["xml_value"] += d.total_amount
        if d.access_key in book_keys:
            p["matched"] += 1
        else:
            p["xml_only"] += 1
            p["unmatched_value"] += d.total_amount
    seen = set()
    for b in book:
        if b.access_key not in xml_keys and b.access_key not in seen:
            seen.add(b.access_key)
            per[b.period]["book_only"] += 1
    xml_periods = {d.period for d in docs}
    book_periods = {b.period for b in book}

    totals: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for b in book:
        if b.direction == "INBOUND":
            totals[(b.period, "ICMS")] += b.icms_credit
            totals[(b.period, "PIS")] += b.pis_credit
            totals[(b.period, "COFINS")] += b.cofins_credit
            if b.ipi_credit:
                totals[(b.period, "IPI")] += b.ipi_credit
    acct = {a: t for t, accts in (tenant.ledger_accounts or {}).items() for a in accts}
    led: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for l_ in session.execute(select(LedgerEntryRow.period, LedgerEntryRow.account, LedgerEntryRow.debit)
                              .where(LedgerEntryRow.tenant_id == tenant_id)).all():
        if l_.account in acct:
            led[(l_.period, acct[l_.account])] += l_.debit
    ledger_rows = []
    for (period, tax) in sorted(set(totals) | set(led)):
        b, l_ = totals[(period, tax)], led[(period, tax)]
        ledger_rows.append({"period": period, "tax": tax, "book": s(b), "ledger": s(l_), "difference": s(b - l_),
                            "status": "OK" if abs(b - l_) <= 1 else "DIVERGENT"})
    return {
        "summary": {"xml_documents": len(xml_keys), "book_documents": len(book_keys),
                    "matched": len(xml_keys & book_keys), "xml_only": len(xml_keys - book_keys),
                    "book_only": len(book_keys - xml_keys),
                    "covered_periods": sorted(xml_periods & book_periods),
                    "uncovered_periods": sorted((xml_periods | book_periods) - (xml_periods & book_periods))},
        "by_period": [{"period": k, "covered": k in xml_periods and k in book_periods, **{
            kk: (s(vv) if isinstance(vv, Decimal) else vv) for kk, vv in v.items()}} for k, v in sorted(per.items())],
        "ledger": ledger_rows,
        "ledger_accounts": tenant.ledger_accounts or {},
    }
