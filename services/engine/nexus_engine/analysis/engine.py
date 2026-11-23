"""Deterministic analysis engine.

Input : normalised documents (XML), fiscal book entries and ledger entries for ONE tenant.
Output: list of ``Finding`` — each one bound to a rule version, with methodology, evidence,
        confidence and an explicit amount type. Nothing here creates, files or offsets taxes.

Design notes
------------
* Rules are resolved per document date (``RuleCatalog.resolve``), so a 2022 invoice and a 2024
  invoice can be evaluated by different versions of the same rule within the same run.
* Coverage guard: "missing on the other side" checks only run for periods covered by BOTH
  datasets. Partial uploads must not generate floods of false positives.
* Item-level signals are aggregated per (rule, document) to keep the review queue actionable;
  every item stays listed as evidence.
"""
from __future__ import annotations

import hashlib
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from ..domain.models import (
    CENT, ZERO, AmountType, BookEntry, Direction, Evidence, FiscalDocument, Finding,
    FindingCategory, FindingKind, LedgerEntry, Severity,
)
from ..ingestion.validators import access_key_parts, expected_inbound_cfop_prefix, is_valid_cnpj
from ..rules.catalog import DEFAULT_CATALOG, RuleCatalog, RuleVersion


@dataclass
class TenantProfile:
    cnpj_roots: set[str]                       # 8-digit CNPJ roots of the tenant's establishments
    tax_regime: str = "NON_CUMULATIVE"         # PIS/COFINS: NON_CUMULATIVE | CUMULATIVE
    ledger_accounts: dict[str, list[str]] = field(default_factory=dict)  # tax -> accounts


@dataclass
class AnalysisInput:
    tenant: TenantProfile
    documents: list[FiscalDocument]
    book: list[BookEntry]
    ledger: list[LedgerEntry]


@dataclass
class AnalysisStats:
    documents: int = 0
    inbound: int = 0
    outbound: int = 0
    unrelated: int = 0
    book_entries: int = 0
    ledger_entries: int = 0
    matched_documents: int = 0
    covered_periods: list[str] = field(default_factory=list)
    rule_versions_applied: dict[str, list[int]] = field(default_factory=dict)


def q(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


def brl(v: Decimal) -> str:
    s = f"{q(v):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: Decimal) -> str:
    return f"{v:.2f}%".replace(".", ",")


def severity_by_amount(amount: Decimal, high: int = 50_000, medium: int = 5_000) -> Severity:
    if amount >= high:
        return Severity.HIGH
    if amount >= medium:
        return Severity.MEDIUM
    return Severity.LOW


class _DocAccumulator:
    """Aggregates item-level contributions into one finding per (rule, document)."""

    def __init__(self) -> None:
        self.amount = ZERO
        self.evidence: list[Evidence] = []
        self.calc: dict[str, str] = {}
        self.items: list[int] = []
        self.partial = False  # some credit was taken, but less than highlighted


class AnalysisEngine:
    def __init__(self, catalog: RuleCatalog | None = None):
        self.catalog = catalog or DEFAULT_CATALOG

    # ------------------------------------------------------------------ public
    def run(self, data: AnalysisInput) -> tuple[list[Finding], AnalysisStats]:
        self.findings: list[Finding] = []
        self.stats = AnalysisStats(documents=len(data.documents), book_entries=len(data.book),
                                   ledger_entries=len(data.ledger))
        self.tenant = data.tenant
        self._applied: dict[str, set[int]] = defaultdict(set)

        docs = self._classify_directions(data.documents)
        book_idx: dict[tuple[str, int], list[BookEntry]] = defaultdict(list)
        for e in data.book:
            book_idx[(e.access_key, e.item_number)].append(e)
        book_keys = {e.access_key for e in data.book}
        doc_keys = {d.access_key for d in docs}
        xml_periods = {d.period for d in docs}
        book_periods = {e.period for e in data.book}
        covered = xml_periods & book_periods
        self.stats.covered_periods = sorted(covered)

        self._data_quality(docs)
        self._missing_in_book(docs, book_keys, covered)
        self._missing_xml(data.book, doc_keys, covered)
        self._item_level(docs, book_idx, book_keys)
        self._duplicates(book_idx)
        self._ledger_reconciliation(data.book, data.ledger)
        self._ncm_consistency(docs)
        self._rate_anomalies(docs)
        self._tax_reform(docs)

        self.stats.matched_documents = len(doc_keys & book_keys)
        self.stats.rule_versions_applied = {k: sorted(v) for k, v in self._applied.items()}
        return self.findings, self.stats

    # ------------------------------------------------------------------ helpers
    def _rule(self, code: str, on) -> RuleVersion | None:
        rule = self.catalog.resolve(code, on)
        if rule:
            self._applied[code].add(rule.version)
        return rule

    def _emit(self, rule: RuleVersion, *, kind: FindingKind, severity: Severity, title: str,
              description: str, confidence: float, amount_type: AmountType, amount: Decimal = ZERO,
              tax: str | None = None, access_key: str | None = None, counterparty: str | None = None,
              period: str | None = None, evidence: list[Evidence] | None = None,
              calculation: dict[str, str] | None = None, discriminator: str = "") -> None:
        fp_src = "|".join([rule.code, access_key or "", counterparty or "", period or "", tax or "",
                           discriminator])
        self.findings.append(Finding(
            rule_code=rule.code, rule_version=rule.version, category=rule.category, kind=kind,
            severity=severity, title=title, description=description, methodology=rule.methodology,
            legal_basis=rule.legal_basis, confidence=confidence, amount_type=amount_type,
            estimated_amount=q(amount), tax=tax, access_key=access_key, counterparty_cnpj=counterparty,
            period=period, evidence=evidence or [], calculation=calculation or {},
            fingerprint=hashlib.sha256(fp_src.encode()).hexdigest()[:32],
        ))

    def _classify_directions(self, documents: list[FiscalDocument]) -> list[FiscalDocument]:
        roots = self.tenant.cnpj_roots
        for d in documents:
            if d.issuer_cnpj[:8] in roots:
                d.direction = Direction.OUTBOUND
                self.stats.outbound += 1
            elif d.recipient_doc[:8] in roots:
                d.direction = Direction.INBOUND
                self.stats.inbound += 1
            else:
                d.direction = Direction.UNRELATED
                self.stats.unrelated += 1
        return [d for d in documents if d.direction != Direction.UNRELATED]

    @staticmethod
    def _xml_ev(d: FiscalDocument, field_: str, observed: str, expected: str = "", locator: str = "") -> Evidence:
        return Evidence(source=d.source_file, locator=locator or f"chave {d.access_key}",
                        field=field_, observed=observed, expected=expected)

    @staticmethod
    def _book_ev(e: BookEntry, field_: str, observed: str, expected: str = "") -> Evidence:
        return Evidence(source=e.source_file, locator=f"linha {e.source_row}", field=field_,
                        observed=observed, expected=expected)

    # ------------------------------------------------------------------ detectors
    def _data_quality(self, docs: list[FiscalDocument]) -> None:
        bad_suppliers: dict[str, list[FiscalDocument]] = defaultdict(list)
        for d in docs:
            rule = self._rule("NX-DQ-001", d.issue_date)
            key_cnpj = access_key_parts(d.access_key)["cnpj"]
            if rule and key_cnpj != d.issuer_cnpj:
                self._emit(
                    rule, kind=FindingKind.ALERT, severity=Severity.MEDIUM,
                    title=f"NF-e {d.number}: CNPJ da chave difere do emitente",
                    description="O CNPJ embutido na chave de acesso não corresponde ao CNPJ do emitente "
                                "no XML. Pode indicar documento adulterado ou erro de emissão; verificar "
                                "a autenticidade no portal da SEFAZ.",
                    confidence=0.95, amount_type=AmountType.NONE, access_key=d.access_key,
                    counterparty=d.issuer_cnpj, period=d.period,
                    evidence=[self._xml_ev(d, "chave[7:20]", key_cnpj, d.issuer_cnpj),
                              self._xml_ev(d, "emit/CNPJ", d.issuer_cnpj)],
                )
            if d.direction == Direction.INBOUND and not is_valid_cnpj(d.issuer_cnpj):
                bad_suppliers[d.issuer_cnpj].append(d)
        for cnpj, ds in bad_suppliers.items():
            rule = self._rule("NX-DQ-002", ds[0].issue_date)
            if rule:
                self._emit(
                    rule, kind=FindingKind.ALERT, severity=Severity.MEDIUM,
                    title=f"Fornecedor com CNPJ inválido ({len(ds)} documento(s))",
                    description="O CNPJ do emitente não passa na validação do dígito verificador.",
                    confidence=0.99, amount_type=AmountType.NONE, counterparty=cnpj,
                    evidence=[self._xml_ev(d, "emit/CNPJ", cnpj) for d in ds[:10]],
                )

    def _missing_in_book(self, docs, book_keys, covered) -> None:
        for d in docs:
            if d.access_key in book_keys or d.period not in covered or not d.status == "AUTHORIZED":
                continue
            if d.direction == Direction.INBOUND:
                rule = self._rule("NX-REC-001", d.issue_date)
                if not rule:
                    continue
                self._emit(
                    rule, kind=FindingKind.ESTIMATE,
                    severity=severity_by_amount(d.icms_total) if d.icms_total > 0 else Severity.MEDIUM,
                    title=f"NF-e de entrada {d.number} não escriturada — {d.issuer_name}",
                    description=f"XML recebido em {d.issue_date:%d/%m/%Y} (valor {brl(d.total_amount)}) "
                                "não foi localizado na escrituração do período. Além do possível crédito "
                                "não aproveitado, a falta de escrituração é, por si, um risco de "
                                "conformidade.",
                    confidence=0.5, amount_type=AmountType.RECOVERABLE_ESTIMATE, amount=d.icms_total,
                    tax="ICMS", access_key=d.access_key, counterparty=d.issuer_cnpj, period=d.period,
                    evidence=[self._xml_ev(d, "ICMSTot/vICMS", brl(d.icms_total)),
                              self._xml_ev(d, "ICMSTot/vNF", brl(d.total_amount)),
                              Evidence("escrituração fiscal", f"período {d.period}", "chave",
                                       "não localizada", d.access_key)],
                    calculation={"Valor estimado": f"ICMS destacado no XML = {brl(d.icms_total)}",
                                 "Ressalva": "Elegibilidade depende da destinação da mercadoria"},
                )
            else:
                rule = self._rule("NX-REC-002", d.issue_date)
                if not rule:
                    continue
                self._emit(
                    rule, kind=FindingKind.ALERT,
                    severity=Severity.CRITICAL if d.icms_total > 0 else Severity.HIGH,
                    title=f"NF-e de saída {d.number} não escriturada",
                    description="Documento emitido pela empresa sem registro na escrituração do período. "
                                "Débito de ICMS potencialmente não apurado.",
                    confidence=0.85, amount_type=AmountType.EXPOSURE_ESTIMATE, amount=d.icms_total,
                    tax="ICMS", access_key=d.access_key, counterparty=d.recipient_doc, period=d.period,
                    evidence=[self._xml_ev(d, "ICMSTot/vICMS", brl(d.icms_total)),
                              Evidence("escrituração fiscal", f"período {d.period}", "chave",
                                       "não localizada", d.access_key)],
                    calculation={"Exposição": f"ICMS destacado = {brl(d.icms_total)}"},
                )

    def _missing_xml(self, book, doc_keys, covered) -> None:
        by_key: dict[str, list[BookEntry]] = defaultdict(list)
        for e in book:
            if e.direction == Direction.INBOUND and e.access_key not in doc_keys and e.period in covered:
                by_key[e.access_key].append(e)
        for key, entries in by_key.items():
            first = entries[0]
            rule = self._rule("NX-REC-003", first.entry_date)
            if not rule:
                continue
            credit = sum((e.icms_credit for e in entries), ZERO)
            self._emit(
                rule, kind=FindingKind.ALERT,
                severity=severity_by_amount(credit, 20_000, 2_000) if credit else Severity.LOW,
                title=f"Entrada escriturada sem XML — doc. {first.document_number or key[25:34]}",
                description="Crédito escriturado sem o XML correspondente na base analisada. Pode ser "
                            "apenas XML não enviado à plataforma; confirme a existência e situação do "
                            "documento antes de concluir.",
                confidence=0.7, amount_type=AmountType.EXPOSURE_ESTIMATE, amount=credit, tax="ICMS",
                access_key=key, counterparty=first.counterparty_cnpj, period=first.period,
                evidence=[self._book_ev(e, "vl_icms", brl(e.icms_credit)) for e in entries[:20]]
                + [Evidence("base de XML", f"período {first.period}", "chave", "não localizada", key)],
                calculation={"Exposição": f"Σ ICMS creditado = {brl(credit)}"},
            )

    def _item_level(self, docs, book_idx, book_keys) -> None:
        for d in docs:
            if d.access_key not in book_keys:
                continue
            acc: dict[str, _DocAccumulator] = defaultdict(_DocAccumulator)
            rules: dict[str, RuleVersion | None] = {
                c: self._rule(c, d.issue_date) for c in
                ("NX-REC-004", "NX-REC-005", "NX-CRD-001", "NX-CRD-002", "NX-CRD-003", "NX-RSK-001",
                 "NX-RSK-003", "NX-CLS-001", "NX-CLS-002")
            }
            for it in d.items:
                entries = book_idx.get((d.access_key, it.item_number))
                if not entries:
                    if rules["NX-REC-005"] and d.direction == Direction.INBOUND:
                        a = acc["NX-REC-005"]
                        a.amount += it.icms_amount
                        a.items.append(it.item_number)
                        a.evidence.append(self._xml_ev(d, "det/ICMS/vICMS", brl(it.icms_amount),
                                                       locator=it.xpath))
                    continue
                e = entries[0]
                # value divergence
                r = rules["NX-REC-004"]
                if r:
                    diff = e.amount - it.net_amount
                    tol = max(Decimal(r.parameters["abs_tolerance"]),
                              Decimal(r.parameters["rel_tolerance"]) * it.net_amount)
                    if abs(diff) > tol:
                        a = acc["NX-REC-004"]
                        a.amount += abs(diff)
                        a.items.append(it.item_number)
                        a.evidence += [self._xml_ev(d, "vProd − vDesc", brl(it.net_amount), locator=it.xpath),
                                       self._book_ev(e, "valor", brl(e.amount), brl(it.net_amount))]
                # classification
                r = rules["NX-CLS-002"]
                if r and it.ncm and e.ncm and it.ncm != e.ncm:
                    a = acc["NX-CLS-002"]
                    a.items.append(it.item_number)
                    a.evidence += [self._xml_ev(d, "prod/NCM", it.ncm, locator=it.xpath),
                                   self._book_ev(e, "ncm", e.ncm, it.ncm)]
                r = rules["NX-CLS-001"]
                if r and d.direction == Direction.INBOUND:
                    expected = expected_inbound_cfop_prefix(d.issuer_uf, d.recipient_uf)
                    if e.cfop[:1] != expected:
                        a = acc["NX-CLS-001"]
                        a.items.append(it.item_number)
                        a.evidence.append(self._book_ev(
                            e, "cfop", e.cfop, f"{expected}xxx ({d.issuer_uf}→{d.recipient_uf})"))
                if d.direction != Direction.INBOUND:
                    continue
                # ICMS credit
                highlighted, credited = it.icms_amount, e.icms_credit
                r = rules["NX-RSK-001"]
                if r and credited - highlighted > Decimal(r.parameters["abs_tolerance"]):
                    a = acc["NX-RSK-001"]
                    a.amount += credited - highlighted
                    a.items.append(it.item_number)
                    a.evidence += [self._xml_ev(d, "det/ICMS/vICMS", brl(highlighted), locator=it.xpath),
                                   self._book_ev(e, "vl_icms", brl(credited), f"≤ {brl(highlighted)}")]
                elif (r := rules["NX-CRD-001"]) and e.cfop in r.parameters["eligible_cfops"] \
                        and highlighted - credited >= Decimal(r.parameters["min_amount"]):
                    a = acc["NX-CRD-001"]
                    a.partial = a.partial or credited > 0
                    a.amount += highlighted - credited
                    a.items.append(it.item_number)
                    a.calc[f"Item {it.item_number}"] = (
                        f"{brl(highlighted)} destacado ({pct(it.icms_rate)} s/ {brl(it.icms_base)}) − "
                        f"{brl(credited)} creditado = {brl(highlighted - credited)}")
                    a.evidence += [self._xml_ev(d, "det/ICMS/vICMS", brl(highlighted), locator=it.xpath),
                                   self._book_ev(e, "vl_icms", brl(credited), brl(highlighted))]
                elif (r := rules["NX-CRD-002"]) and e.cfop in r.parameters["eligible_cfops"] \
                        and credited == 0 and highlighted > 0:
                    a = acc["NX-CRD-002"]
                    a.amount += highlighted
                    a.items.append(it.item_number)
                    a.calc[f"Item {it.item_number}"] = (
                        f"{brl(highlighted)} total → {brl(highlighted / 48)} por mês (1/48)")
                    a.evidence += [self._xml_ev(d, "det/ICMS/vICMS", brl(highlighted), locator=it.xpath),
                                   self._book_ev(e, "cfop / vl_icms", f"{e.cfop} / {brl(credited)}")]
                r = rules["NX-RSK-003"]
                if r and d.status != "AUTHORIZED" and credited > 0:
                    a = acc["NX-RSK-003"]
                    a.amount += credited
                    a.items.append(it.item_number)
                    a.evidence += [self._xml_ev(d, "protNFe/cStat", d.status),
                                   self._book_ev(e, "vl_icms", brl(credited), "0,00")]
                # PIS/COFINS
                r = rules["NX-CRD-003"]
                if r and self.tenant.tax_regime == "NON_CUMULATIVE" \
                        and e.cfop in r.parameters["eligible_cfops"] \
                        and e.pis_credit == 0 and e.cofins_credit == 0 \
                        and e.pis_cst not in r.parameters["credit_csts"]:
                    base = it.net_amount - (it.icms_amount if r.parameters["exclude_icms_from_base"] else ZERO)
                    pis = base * Decimal(r.parameters["pis_rate"])
                    cof = base * Decimal(r.parameters["cofins_rate"])
                    a = acc["NX-CRD-003"]
                    a.amount += pis + cof
                    a.items.append(it.item_number)
                    base_desc = "vProd − vDesc − vICMS" if r.parameters["exclude_icms_from_base"] else "vProd − vDesc"
                    a.calc[f"Item {it.item_number}"] = (
                        f"base ({base_desc}) {brl(base)} × 1,65% = {brl(pis)}; × 7,60% = {brl(cof)}")
                    a.evidence.append(self._book_ev(e, "vl_pis / vl_cofins / cst_pis",
                                                    f"0,00 / 0,00 / {e.pis_cst or '—'}"))
            self._flush_doc(d, acc, rules)

    def _flush_doc(self, d: FiscalDocument, acc: dict[str, _DocAccumulator], rules) -> None:
        sup = d.issuer_cnpj if d.direction == Direction.INBOUND else d.recipient_doc
        items = lambda a: ", ".join(map(str, sorted(set(a.items))))  # noqa: E731
        common = dict(access_key=d.access_key, counterparty=sup, period=d.period)
        for code, a in acc.items():
            r = rules[code]
            ev, calc = a.evidence[:40], a.calc
            if code == "NX-REC-004":
                self._emit(r, kind=FindingKind.ALERT, severity=Severity.MEDIUM,
                           title=f"NF-e {d.number}: valores divergentes em {len(set(a.items))} item(ns)",
                           description=f"Valor escriturado difere do XML nos itens {items(a)}.",
                           confidence=0.9, amount_type=AmountType.DIVERGENCE_VALUE, amount=a.amount,
                           evidence=ev, calculation={"Σ |divergência|": brl(a.amount)}, **common)
            elif code == "NX-REC-005":
                self._emit(r, kind=FindingKind.ESTIMATE, severity=severity_by_amount(a.amount),
                           title=f"NF-e {d.number}: {len(a.items)} item(ns) não escriturado(s)",
                           description=f"Documento escriturado parcialmente. Itens ausentes: {items(a)}.",
                           confidence=0.6, amount_type=AmountType.RECOVERABLE_ESTIMATE, amount=a.amount,
                           tax="ICMS", evidence=ev, calculation={"Σ ICMS destacado": brl(a.amount)},
                           **common)
            elif code == "NX-CLS-001":
                self._emit(r, kind=FindingKind.ALERT, severity=Severity.LOW,
                           title=f"NF-e {d.number}: CFOP de entrada incompatível com as UFs",
                           description=f"Operação {d.issuer_uf}→{d.recipient_uf}; CFOP escriturado com "
                                       f"primeiro dígito incorreto nos itens {items(a)}.",
                           confidence=0.95, amount_type=AmountType.NONE, evidence=ev, **common)
            elif code == "NX-CLS-002":
                self._emit(r, kind=FindingKind.ALERT, severity=Severity.MEDIUM,
                           title=f"NF-e {d.number}: NCM divergente entre XML e escrituração",
                           description=f"NCM escriturado difere do XML nos itens {items(a)}. Pode afetar "
                                       "alíquotas, benefícios e substituição tributária.",
                           confidence=0.9, amount_type=AmountType.NONE, evidence=ev, **common)
            elif code == "NX-RSK-001":
                self._emit(r, kind=FindingKind.ALERT, severity=Severity.CRITICAL,
                           title=f"NF-e {d.number}: crédito de ICMS acima do destacado",
                           description=f"Crédito escriturado excede o ICMS destacado nos itens {items(a)}. "
                                       "Risco de glosa com multa e juros.",
                           confidence=0.9, amount_type=AmountType.EXPOSURE_ESTIMATE, amount=a.amount,
                           tax="ICMS", evidence=ev, calculation={"Excesso de crédito": brl(a.amount)},
                           **common)
            elif code == "NX-RSK-003":
                self._emit(r, kind=FindingKind.ALERT, severity=Severity.CRITICAL,
                           title=f"NF-e {d.number}: crédito sobre documento não autorizado",
                           description=f"Situação do documento: {d.status}. Crédito escriturado deve ser "
                                       "revisto.",
                           confidence=0.9, amount_type=AmountType.EXPOSURE_ESTIMATE, amount=a.amount,
                           tax="ICMS", evidence=ev, **common)
            elif code == "NX-CRD-001":
                partial = a.partial
                self._emit(r, kind=FindingKind.ESTIMATE, severity=severity_by_amount(a.amount),
                           title=f"Possível crédito de ICMS não aproveitado — NF-e {d.number}",
                           description=f"{d.issuer_name}: ICMS destacado em itens com CFOP de aquisição para "
                                       f"industrialização/comercialização não foi creditado "
                                       f"{'integralmente' if partial else ''} (itens {items(a)}). "
                                       "Confirmar destinação e eventuais vedações/estornos antes de "
                                       "aproveitar.",
                           confidence=0.7 if partial else 0.75,
                           amount_type=AmountType.RECOVERABLE_ESTIMATE, amount=a.amount, tax="ICMS",
                           evidence=ev, calculation=calc, **common)
            elif code == "NX-CRD-002":
                self._emit(r, kind=FindingKind.ESTIMATE, severity=severity_by_amount(a.amount),
                           title=f"ICMS de ativo imobilizado sem crédito (CIAP) — NF-e {d.number}",
                           description="Aquisição para ativo imobilizado sem crédito escriturado. Apropriação "
                                       "em 48 parcelas mensais, proporcional às saídas tributadas.",
                           confidence=0.45, amount_type=AmountType.RECOVERABLE_ESTIMATE, amount=a.amount,
                           tax="ICMS", evidence=ev, calculation=calc, **common)
            elif code == "NX-CRD-003":
                self._emit(r, kind=FindingKind.ESTIMATE, severity=severity_by_amount(a.amount),
                           title=f"Possível crédito de PIS/COFINS não aproveitado — NF-e {d.number}",
                           description=f"{d.issuer_name}: aquisições com CFOP elegível sem crédito de "
                                       f"PIS/COFINS escriturado (itens {items(a)}). Requer análise de "
                                       "essencialidade/relevância e de exceções (monofásicos, alíquota zero).",
                           confidence=0.55, amount_type=AmountType.RECOVERABLE_ESTIMATE, amount=a.amount,
                           tax="PIS/COFINS", evidence=ev,
                           calculation={**calc, "Regra": f"{r.code} v{r.version} ({r.change_note or 'base sem exclusão do ICMS'})"},
                           **common)

    def _duplicates(self, book_idx) -> None:
        for (key, item), entries in book_idx.items():
            if len(entries) < 2 or entries[0].direction != Direction.INBOUND:
                continue
            rule = self._rule("NX-RSK-002", entries[0].entry_date)
            if not rule:
                continue
            extra = entries[1:]
            exposure = sum((e.icms_credit + e.pis_credit + e.cofins_credit for e in extra), ZERO)
            self._emit(
                rule, kind=FindingKind.ALERT, severity=Severity.CRITICAL if exposure > 0 else Severity.MEDIUM,
                title=f"Item {item} escriturado {len(entries)}× — doc. {entries[0].document_number or key[25:34]}",
                description="O mesmo item do mesmo documento aparece mais de uma vez na escrituração; "
                            "créditos das ocorrências excedentes são indevidos.",
                confidence=0.95, amount_type=AmountType.EXPOSURE_ESTIMATE, amount=exposure,
                tax="ICMS/PIS/COFINS", access_key=key, counterparty=entries[0].counterparty_cnpj,
                period=entries[0].period, discriminator=str(item),
                evidence=[self._book_ev(e, "chave+item", f"{key[-10:]}…/{item}") for e in entries],
                calculation={"Exposição": f"créditos das {len(extra)} ocorrência(s) excedente(s) = {brl(exposure)}"},
            )

    def _ledger_reconciliation(self, book: list[BookEntry], ledger: list[LedgerEntry]) -> None:
        if not ledger or not self.tenant.ledger_accounts:
            return
        ledger_periods = {e.period for e in ledger}
        book_tot: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        for e in book:
            if e.direction != Direction.INBOUND:
                continue
            book_tot[(e.period, "ICMS")] += e.icms_credit
            book_tot[(e.period, "PIS")] += e.pis_credit
            book_tot[(e.period, "COFINS")] += e.cofins_credit
        ledger_tot: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        ledger_rows: dict[tuple[str, str], int] = defaultdict(int)
        acct_to_tax = {a: t for t, accts in self.tenant.ledger_accounts.items() for a in accts}
        for e in ledger:
            tax = acct_to_tax.get(e.account)
            if tax:
                ledger_tot[(e.period, tax)] += e.debit
                ledger_rows[(e.period, tax)] += 1
        for period in sorted({p for p, _ in book_tot} & ledger_periods):
            for tax in ("ICMS", "PIS", "COFINS"):
                b, l_ = book_tot[(period, tax)], ledger_tot[(period, tax)]
                year, month = map(int, period.split("-"))
                from datetime import date as _d
                rule = self._rule("NX-REC-006", _d(year, month, 1))
                if not rule:
                    continue
                diff = b - l_
                if abs(diff) <= Decimal(rule.parameters["abs_tolerance"]):
                    continue
                accts = ", ".join(self.tenant.ledger_accounts.get(tax, []))
                self._emit(
                    rule, kind=FindingKind.ALERT,
                    severity=Severity.HIGH if abs(diff) >= 10_000 else Severity.MEDIUM,
                    title=f"{tax} {period}: escrituração × contabilidade divergem em {brl(abs(diff))}",
                    description=("Créditos escriturados superam o contabilizado" if diff > 0 else
                                 "Valor contabilizado supera os créditos escriturados") +
                                f" na(s) conta(s) {accts}. Investigar lançamentos manuais, estornos e "
                                "competência.",
                    confidence=0.85, amount_type=AmountType.DIVERGENCE_VALUE, amount=abs(diff), tax=tax,
                    period=period,
                    evidence=[Evidence("escrituração fiscal", f"período {period}", f"Σ crédito {tax}", brl(b)),
                              Evidence("razão contábil", f"período {period} · {ledger_rows[(period, tax)]} lanç.",
                                       f"Σ débito {accts}", brl(l_), brl(b))],
                    calculation={"Escriturado": brl(b), "Contabilizado": brl(l_), "Diferença": brl(diff)},
                )

    def _ncm_consistency(self, docs) -> None:
        groups: dict[tuple[str, str], dict[str, list[tuple[FiscalDocument, int]]]] = defaultdict(lambda: defaultdict(list))
        for d in docs:
            if d.direction != Direction.INBOUND:
                continue
            for it in d.items:
                if it.product_code and it.ncm:
                    groups[(d.issuer_cnpj, it.product_code)][it.ncm].append((d, it.item_number))
        for (cnpj, code), by_ncm in groups.items():
            if len(by_ncm) < 2:
                continue
            last_doc = max((x[0] for v in by_ncm.values() for x in v), key=lambda d: d.issue_date)
            rule = self._rule("NX-CLS-003", last_doc.issue_date)
            if not rule:
                continue
            desc = next(iter(by_ncm.values()))[0][0].items[0].description
            ev = []
            for ncm, occ in by_ncm.items():
                for d, n in occ[:5]:
                    ev.append(self._xml_ev(d, "prod/NCM", ncm, locator=f"chave {d.access_key} · item {n}"))
            self._emit(
                rule, kind=FindingKind.ALERT, severity=Severity.MEDIUM,
                title=f"Produto {code} com {len(by_ncm)} NCMs distintos — {last_doc.issuer_name}",
                description=f"O mesmo código de produto do fornecedor foi faturado com NCMs "
                            f"{', '.join(sorted(by_ncm))}. Classificação inconsistente pode afetar créditos, "
                            "alíquotas e ST.",
                confidence=0.85, amount_type=AmountType.NONE, counterparty=cnpj, discriminator=code,
                evidence=ev, calculation={"Ocorrências": "; ".join(f"{k}: {len(v)}" for k, v in by_ncm.items())},
            )

    def _rate_anomalies(self, docs) -> None:
        samples: dict[tuple[str, str], list[tuple[Decimal, FiscalDocument, object]]] = defaultdict(list)
        for d in docs:
            if d.direction != Direction.INBOUND:
                continue
            scope = "interna" if d.issuer_uf == d.recipient_uf else "interestadual"
            for it in d.items:
                if it.icms_base > 0 and it.icms_amount > 0:
                    samples[(it.ncm, scope)].append((it.icms_amount / it.icms_base, d, it))
        # (rates are quantised below with the rule's precision to drop cent-rounding noise)
        for (ncm, scope), rows in samples.items():
            if not rows:
                continue
            rule = self._rule("NX-ANM-001", rows[0][1].issue_date)
            if not rule or len(rows) < rule.parameters["min_sample"]:
                continue
            prec = Decimal(rule.parameters["rate_precision"])
            min_dev = float(rule.parameters["min_abs_deviation"])
            rows = [(r.quantize(prec), d, it) for r, d, it in rows]
            rates = [float(r[0]) for r in rows]
            med = statistics.median(rates)
            mad = statistics.median([abs(x - med) for x in rates])
            scale = mad / 0.6745 if mad > 0 else 1.2533 * statistics.fmean([abs(x - med) for x in rates])
            if scale == 0:
                continue
            for rate, d, it in rows:
                z = (float(rate) - med) / scale
                if abs(z) < rule.parameters["z_threshold"] or abs(float(rate) - med) < min_dev:
                    continue
                self._emit(
                    rule, kind=FindingKind.ALERT, severity=Severity.LOW,
                    title=f"Alíquota efetiva atípica: NCM {ncm} ({scope}) — NF-e {d.number}",
                    description=f"Alíquota efetiva de {pct(rate * 100)} contra mediana de "
                                f"{pct(Decimal(str(med * 100)))} em {len(rows)} itens comparáveis. Sinal de priorização, "
                                "não de erro.",
                    confidence=0.4, amount_type=AmountType.NONE, tax="ICMS", access_key=d.access_key,
                    counterparty=d.issuer_cnpj, period=d.period, discriminator=str(it.item_number),
                    evidence=[self._xml_ev(d, "pICMS / vBC / vICMS",
                                           f"{pct(it.icms_rate)} / {brl(it.icms_base)} / {brl(it.icms_amount)}",
                                           f"≈ {pct(Decimal(str(med * 100)))}", locator=it.xpath)],
                    calculation={"z robusto": f"{z:.1f}", "Mediana do grupo": pct(Decimal(str(med * 100))),
                                 "Amostra": str(len(rows))},
                )

    def _tax_reform(self, docs) -> None:
        missing: dict[tuple[str, str], list[FiscalDocument]] = defaultdict(list)
        for d in docs:
            r1 = self._rule("NX-RTC-001", d.issue_date)
            if r1 and not d.has_ibs_cbs_group:
                missing[(d.issuer_cnpj, d.period)].append(d)
            r2 = self._rule("NX-RTC-002", d.issue_date)
            if not r2 or not d.has_ibs_cbs_group:
                continue
            diff_total, ev = ZERO, []
            tol = Decimal(r2.parameters["abs_tolerance"])
            for it in d.items:
                if it.ibs_cbs_base is None:
                    continue
                exp_cbs = q(it.ibs_cbs_base * Decimal(r2.parameters["cbs_rate"]))
                exp_ibs = q(it.ibs_cbs_base * Decimal(r2.parameters["ibs_rate"]))
                for name, got, exp in (("vCBS", it.cbs_amount or ZERO, exp_cbs), ("vIBS", it.ibs_amount or ZERO, exp_ibs)):
                    if abs(got - exp) > tol:
                        diff_total += abs(got - exp)
                        ev.append(self._xml_ev(d, f"IBSCBS/{name}", brl(got), brl(exp), locator=it.xpath))
            if ev:
                self._emit(r2, kind=FindingKind.ALERT, severity=Severity.LOW,
                           title=f"NF-e {d.number}: IBS/CBS fora das alíquotas de teste de 2026",
                           description="Valores de IBS/CBS destacados diferem de base × alíquotas de teste "
                                       "parametrizadas. Pode haver redução/regime específico legítimo.",
                           confidence=0.5, amount_type=AmountType.DIVERGENCE_VALUE, amount=diff_total,
                           tax="IBS/CBS", access_key=d.access_key,
                           counterparty=d.issuer_cnpj if d.direction == Direction.INBOUND else d.recipient_doc,
                           period=d.period, evidence=ev)
        for (cnpj, period), ds in missing.items():
            rule = self._rule("NX-RTC-001", ds[0].issue_date)
            outbound = ds[0].direction == Direction.OUTBOUND
            self._emit(
                rule, kind=FindingKind.ALERT, severity=Severity.MEDIUM if outbound else Severity.INFO,
                title=(f"Emissões próprias sem IBS/CBS em {period} ({len(ds)} NF-e)" if outbound else
                       f"Fornecedor sem IBS/CBS em {period} ({len(ds)} NF-e) — {ds[0].issuer_name}"),
                description="Documentos emitidos a partir de 2026 sem o grupo IBS/CBS por item. Avaliar "
                            "prontidão do emissor para a Reforma Tributária conforme cronograma vigente.",
                confidence=0.9, amount_type=AmountType.NONE, tax="IBS/CBS", counterparty=cnpj, period=period,
                evidence=[self._xml_ev(d, "det/imposto/IBSCBS", "ausente") for d in ds[:15]],
            )
