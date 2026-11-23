from datetime import date
from decimal import Decimal

import pytest

from nexus_engine.ingestion.errors import ErrorSeverity, IngestionError
from nexus_engine.ingestion.nfe_xml import iter_xml_payloads, parse_nfe
from nexus_engine.ingestion.tabular import parse_fiscal_book, parse_ledger
from nexus_engine.ingestion.validators import (
    access_key_dv, build_access_key, cnpj_with_dv, is_valid_cnpj, mask_cpf, validate_access_key,
)
from nexus_engine.rules.catalog import RuleCatalog, RuleVersion, DEFAULT_CATALOG
from nexus_engine.domain.models import FindingCategory, money


def test_cnpj_validation():
    assert is_valid_cnpj("11.222.333/0001-81")
    assert not is_valid_cnpj("11.222.333/0001-82")
    assert not is_valid_cnpj("00000000000000")
    assert is_valid_cnpj(cnpj_with_dv("457231740001"))


def test_access_key_dv_and_validation():
    key = build_access_key("SP", "2601", cnpj_with_dv("457231740001"), "55", 1, 1234)
    assert len(key) == 44 and validate_access_key(key) == []
    broken = key[:43] + str((int(key[43]) + 1) % 10)
    assert "dígito verificador da chave não confere" in validate_access_key(broken)
    assert access_key_dv(key[:43]) == key[43]


def test_cpf_is_masked():
    assert mask_cpf("123.456.789-09") == "***.456.***-**"


def test_money_parsing_brazilian_and_plain():
    assert money("1.234,56") == Decimal("1234.56")
    assert money("1234.56") == Decimal("1234.56")
    assert money("R$ 10,00") == Decimal("10.00")


def test_parse_generated_nfe_roundtrip(dataset):
    payloads = list(iter_xml_payloads("lote.zip", dataset.xml_zip))
    assert len(payloads) == dataset.stats["documents"]
    doc, errors = parse_nfe(payloads[0][1], "x.xml")
    assert doc is not None and not [e for e in errors if e.severity == ErrorSeverity.BLOCKING]
    assert doc.items and doc.total_amount > 0
    assert doc.icms_total == sum(i.icms_amount for i in doc.items)


def test_malformed_and_hostile_xml_rejected_not_raised():
    doc, errors = parse_nfe(b"<NFe><infNFe>", "bad.xml")
    assert doc is None and errors[0].severity == ErrorSeverity.BLOCKING
    bomb = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
            b"<NFe>&lol2;</NFe>")
    doc, errors = parse_nfe(bomb, "bomb.xml")
    assert doc is None and "inseguro" in errors[0].message


def test_fiscal_book_csv_brazilian_format_and_row_errors():
    key = build_access_key("SP", "2601", cnpj_with_dv("457231740001"), "55", 1, 99)
    csv = (
        "CHAVE_NFE;DT_ENTRADA;TIPO;CNPJ_PARTICIPANTE;NUM_ITEM;CFOP;NCM;VL_ITEM;VL_ICMS\n"
        f"{key};15/01/2026;E;11222333000181;1;1101;72085100;1.234,56;222,22\n"
        f"{key};15/01/2026;E;11222333000181;2;9999;72085100;10,00;1,00\n"      # invalid CFOP → blocking
        f"{key};32/01/2026;E;11222333000181;3;1101;72085100;10,00;1,00\n"      # invalid date → blocking
    ).encode()
    entries, errors, total = parse_fiscal_book("livro.csv", csv)
    assert total == 3 and len(entries) == 1
    assert entries[0].amount == Decimal("1234.56") and entries[0].entry_date == date(2026, 1, 15)
    assert {e.field for e in errors} == {"cfop", "entry_date"}


def test_missing_mandatory_columns_fails_file():
    with pytest.raises(IngestionError, match="Colunas obrigatórias ausentes"):
        parse_fiscal_book("livro.csv", b"CHAVE;VALOR\n1;2\n")


def test_ledger_xlsx(dataset):
    entries, errors, total = parse_ledger("razao.xlsx", dataset.ledger_xlsx)
    assert total == len(entries) > 0 and not errors


def test_rule_resolution_by_document_date():
    c = DEFAULT_CATALOG
    assert c.resolve("NX-CRD-003", date(2023, 4, 30)).version == 1
    assert c.resolve("NX-CRD-003", date(2023, 5, 1)).version == 2
    assert c.resolve("NX-CRD-003", date(2027, 1, 1)) is None          # PIS/COFINS extinct → rule not applied
    assert c.resolve("NX-RTC-001", date(2025, 12, 31)) is None        # reform rule only from 2026
    assert c.resolve("NX-RTC-002", date(2026, 6, 1)).parameters["cbs_rate"] == "0.009"


def test_overlapping_rule_validity_is_rejected():
    v = dict(name="x", category=FindingCategory.ANOMALY, methodology="m", legal_basis="l", legal_review_status="NOT_REQUIRED")
    with pytest.raises(ValueError, match="sobrepostas"):
        RuleCatalog([RuleVersion("R", 1, valid_from=date(2020, 1, 1), valid_to=date(2021, 1, 1), **v),
                     RuleVersion("R", 2, valid_from=date(2020, 6, 1), valid_to=date(2022, 1, 1), **v)])
