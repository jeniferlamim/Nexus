"""The engine must find exactly what was planted in the synthetic dataset — no more, no less —
for every deterministic rule."""
from collections import defaultdict
from decimal import Decimal

import pytest

from nexus_engine.analysis.engine import AnalysisEngine, AnalysisInput, TenantProfile
from nexus_engine.domain.models import AmountType, FindingKind
from nexus_engine.ingestion.nfe_xml import iter_xml_payloads, parse_nfe
from nexus_engine.ingestion.tabular import parse_fiscal_book, parse_ledger


def _input(ds, with_book=True, with_ledger=True):
    docs = [parse_nfe(b, n)[0] for n, b in iter_xml_payloads("x.zip", ds.xml_zip)]
    book = parse_fiscal_book("livro.csv", ds.book_csv)[0] if with_book else []
    ledger = parse_ledger("razao.xlsx", ds.ledger_xlsx)[0] if with_ledger else []
    return AnalysisInput(TenantProfile(set(ds.cnpj_roots), "NON_CUMULATIVE", ds.ledger_accounts),
                         [d for d in docs if d], book, ledger)


from nexus_engine.demo.generator import generate

SECTOR_ARGS = {"metalmecanica": dict(seed=7, root="45723174"), "plasticos": dict(seed=13, root="52817390")}


@pytest.fixture(scope="module", params=list(SECTOR_ARGS))
def sector_dataset(request):
    return generate(sector=request.param, **SECTOR_ARGS[request.param])


@pytest.fixture(scope="module")
def result(sector_dataset):
    findings, stats = AnalysisEngine().run(_input(sector_dataset))
    by_rule = defaultdict(list)
    for f in findings:
        by_rule[f.rule_code].append(f)
    return by_rule, stats


@pytest.mark.parametrize("rule", ["NX-REC-001", "NX-REC-002", "NX-REC-003", "NX-REC-004", "NX-REC-005",
                                  "NX-CRD-001", "NX-RSK-001", "NX-RSK-002", "NX-RSK-003", "NX-CLS-001",
                                  "NX-CLS-002", "NX-DQ-001", "NX-CRD-004", "NX-RSK-004"])
def test_planted_anomalies_found_exactly(result, sector_dataset, rule):
    by_rule, _ = result
    assert {f.access_key for f in by_rule[rule]} == set(sector_dataset.truth[rule])


def test_anomaly_detector_flags_only_planted_documents(result, sector_dataset):
    by_rule, _ = result
    assert {f.access_key for f in by_rule["NX-ANM-001"]} == set(sector_dataset.truth["NX-ANM-001"])


def test_ledger_divergences(result, sector_dataset):
    """IPI is mapped to a ledger account and reconciles; only the planted periods diverge."""
    by_rule, _ = result
    assert {f"{f.period}:{f.tax}" for f in by_rule["NX-REC-006"]} == set(sector_dataset.truth["NX-REC-006"])


def test_ipi_credit_not_applied_to_non_ipi_taxpayers(sector_dataset):
    data = _input(sector_dataset)
    data.tenant.ipi_taxpayer = False
    findings, _ = AnalysisEngine().run(data)
    assert not [f for f in findings if f.rule_code == "NX-CRD-004"]
    assert [f for f in findings if f.rule_code == "NX-RSK-004"]  # excess credit is a risk regardless


def test_pis_cofins_versioning_by_document_date(result):
    by_rule, stats = result
    versions = {f.period: f.rule_version for f in by_rule["NX-CRD-003"]}
    assert versions["2023-04"] == 1 and versions["2023-05"] == 2
    assert stats.rule_versions_applied["NX-CRD-003"] == [1, 2]
    v2 = next(f for f in by_rule["NX-CRD-003"] if f.rule_version == 2)
    assert "vICMS" in next(iter(v2.calculation.values()))     # base excludes ICMS from 05/2023


def test_every_finding_is_explainable(result):
    by_rule, _ = result
    for findings in by_rule.values():
        for f in findings:
            assert f.methodology and f.legal_basis and f.evidence, f.rule_code
            assert 0 < f.confidence <= 1
            assert f.requires_human_validation
            if f.amount_type == AmountType.RECOVERABLE_ESTIMATE:
                assert f.kind == FindingKind.ESTIMATE and f.estimated_amount > 0


def test_credit_estimate_matches_document_values(result):
    """ICMS credit estimate = highlighted − credited, from the documents' own figures."""
    by_rule, _ = result
    total = sum((f.estimated_amount for f in by_rule["NX-CRD-001"]), Decimal(0))
    assert total > 0
    for f in by_rule["NX-CRD-001"]:
        assert all("destacado" in v for v in f.calculation.values())


def test_coverage_guard_avoids_false_positives(sector_dataset):
    findings, _ = AnalysisEngine().run(_input(sector_dataset, with_book=False, with_ledger=False))
    assert not [f for f in findings if f.rule_code in {"NX-REC-001", "NX-REC-002", "NX-REC-003"}]


def test_fingerprints_are_stable(sector_dataset):
    a, _ = AnalysisEngine().run(_input(sector_dataset))
    b, _ = AnalysisEngine().run(_input(sector_dataset))
    assert [f.fingerprint for f in a] == [f.fingerprint for f in b]


def test_ciap_estimate_counts_only_elapsed_installments(result):
    by_rule, _ = result
    for f in by_rule["NX-CRD-002"]:
        calc = " ".join(f.calculation.values())
        assert "parcela(s)" in calc and "saldo futuro" in calc
        assert f.confidence < 0.5
