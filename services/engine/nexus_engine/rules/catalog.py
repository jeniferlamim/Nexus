"""Versioned tax rule catalog with temporal validity.

Principles
----------
* A rule is **data** (parameters, methodology, legal basis) plus a detector in ``analysis/``.
* Each (code, version) has a validity window ``[valid_from, valid_to]``. The engine resolves the
  version in force on the *document date* (fato gerador), not on the analysis date.
* Every finding stores ``rule_code`` + ``rule_version``.
* ``legal_review_status`` makes explicit what still needs a tax lawyer's sign-off:
    - NOT_REQUIRED : pure data-consistency check (no legal interpretation)
    - RECOMMENDED  : interpretation involved; output is always an ESTIMATE
    - PENDING      : rule depends on regulation still evolving (e.g. Reforma Tributária)
* Rates live in ``parameters`` only when they are statutory and cited. ICMS rates are never
  hard-coded: the engine uses the rate printed on the document itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..domain.models import FindingCategory

OPEN_END = date(9999, 12, 31)

ICMS_CREDIT_CFOPS = ["1101", "1102", "2101", "2102", "1122", "2122", "1116", "2116"]
FIXED_ASSET_CFOPS = ["1551", "2551"]
USE_CONSUMPTION_CFOPS = ["1556", "2556"]
PIS_COFINS_CREDIT_CFOPS = ["1101", "1102", "2101", "2102"]
PIS_COFINS_CREDIT_CSTS = ["50", "51", "52", "53", "54", "55", "56"]


@dataclass(frozen=True)
class RuleVersion:
    code: str
    version: int
    name: str
    category: FindingCategory
    valid_from: date
    valid_to: date
    methodology: str
    legal_basis: str
    legal_review_status: str
    parameters: dict[str, Any] = field(default_factory=dict)
    change_note: str = ""

    def in_force(self, on: date) -> bool:
        return self.valid_from <= on <= self.valid_to

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "version": self.version, "name": self.name,
            "category": self.category.value, "valid_from": self.valid_from.isoformat(),
            "valid_to": None if self.valid_to == OPEN_END else self.valid_to.isoformat(),
            "methodology": self.methodology, "legal_basis": self.legal_basis,
            "legal_review_status": self.legal_review_status, "parameters": self.parameters,
            "change_note": self.change_note,
        }


C = FindingCategory
D = date

RULES: list[RuleVersion] = [
    # ------------------------------------------------------------------ data quality
    RuleVersion(
        "NX-DQ-001", 1, "Chave de acesso inconsistente com o emitente", C.DATA_QUALITY,
        D(2006, 4, 1), OPEN_END,
        "Compara o CNPJ embutido na chave de acesso (posições 7–20) com o CNPJ do emitente "
        "informado no XML.",
        "Leiaute da NF-e — composição da chave de acesso (Manual de Orientação do Contribuinte).",
        "NOT_REQUIRED",
    ),
    RuleVersion(
        "NX-DQ-002", 1, "CNPJ de participante inválido", C.DATA_QUALITY, D(2006, 4, 1), OPEN_END,
        "Validação do dígito verificador do CNPJ (módulo 11).",
        "Algoritmo público de validação do CNPJ (Receita Federal).", "NOT_REQUIRED",
    ),
    # ------------------------------------------------------------------ reconciliation
    RuleVersion(
        "NX-REC-001", 1, "NF-e de entrada sem escrituração", C.RECONCILIATION, D(2006, 4, 1), OPEN_END,
        "XML recebido (tenant como destinatário) cuja chave não consta na escrituração fiscal. "
        "Valor estimado = ICMS destacado no XML. A elegibilidade ao crédito depende da destinação "
        "da mercadoria (não inferível do XML); por isso a confiança é reduzida.",
        "LC 87/1996, arts. 19 a 23 (não cumulatividade do ICMS e condições do crédito); "
        "obrigatoriedade de escrituração conforme legislação estadual e Guia Prático EFD ICMS/IPI.",
        "RECOMMENDED",
        {"min_amount": "0.01"},
    ),
    RuleVersion(
        "NX-REC-002", 1, "NF-e de saída sem escrituração", C.RECONCILIATION, D(2006, 4, 1), OPEN_END,
        "XML emitido pelo tenant cuja chave não consta na escrituração. Exposição estimada = "
        "ICMS destacado (débito potencialmente não apurado).",
        "LC 87/1996, art. 12 (fato gerador); Guia Prático EFD ICMS/IPI (registro C100).",
        "NOT_REQUIRED",
    ),
    RuleVersion(
        "NX-REC-003", 1, "Escrituração sem XML correspondente", C.RECONCILIATION, D(2006, 4, 1), OPEN_END,
        "Lançamento de entrada na escrituração cuja chave não possui XML na base. Exposição "
        "estimada = ICMS creditado sem documento comprobatório disponível.",
        "LC 87/1996, art. 23 (crédito condicionado à idoneidade da documentação).",
        "NOT_REQUIRED",
    ),
    RuleVersion(
        "NX-REC-004", 1, "Divergência de valor entre XML e escrituração", C.RECONCILIATION,
        D(2006, 4, 1), OPEN_END,
        "Compara, por chave e número do item, o valor líquido do item no XML (vProd − vDesc) com o "
        "valor escriturado. Divergência acima da tolerância gera alerta.",
        "Verificação de consistência de dados (sem interpretação legal).", "NOT_REQUIRED",
        {"abs_tolerance": "1.00", "rel_tolerance": "0.005"},
    ),
    RuleVersion(
        "NX-REC-005", 1, "Item da NF-e não escriturado", C.RECONCILIATION, D(2006, 4, 1), OPEN_END,
        "Documento escriturado parcialmente: item presente no XML e ausente na escrituração. "
        "Valor estimado = ICMS destacado do item.",
        "LC 87/1996, arts. 19 a 23.", "RECOMMENDED",
    ),
    RuleVersion(
        "NX-REC-006", 1, "Divergência escrituração × contabilidade", C.RECONCILIATION,
        D(2006, 4, 1), OPEN_END,
        "Por período e tributo, compara o total de créditos escriturados com a movimentação a "
        "débito nas contas contábeis de tributos a recuperar mapeadas pelo cliente.",
        "Verificação de consistência entre registros fiscais e contábeis.", "NOT_REQUIRED",
        {"abs_tolerance": "1.00"},
    ),
    # ------------------------------------------------------------------ credit opportunities
    RuleVersion(
        "NX-CRD-001", 1, "ICMS destacado não creditado integralmente", C.CREDIT_OPPORTUNITY,
        D(2006, 4, 1), OPEN_END,
        "Para itens de entrada com CFOP de aquisição para industrialização/comercialização, "
        "estimativa = ICMS destacado no XML − ICMS creditado na escrituração. Usa a alíquota e o "
        "valor impressos no próprio documento; nenhuma alíquota é presumida.",
        "LC 87/1996, arts. 19 e 20 (não cumulatividade e direito ao crédito).",
        "RECOMMENDED",
        {"eligible_cfops": ICMS_CREDIT_CFOPS, "excluded_cfops": USE_CONSUMPTION_CFOPS,
         "min_amount": "1.00"},
    ),
    RuleVersion(
        "NX-CRD-002", 1, "ICMS sobre ativo imobilizado não creditado (CIAP)", C.CREDIT_OPPORTUNITY,
        D(2006, 4, 1), OPEN_END,
        "Entradas com CFOP de ativo imobilizado sem crédito escriturado. O valor exibido é o "
        "crédito total potencial, apropriável em 1/48 por mês, condicionado à proporção de saídas "
        "tributadas. Confiança baixa: depende de controle CIAP e uso do bem.",
        "LC 87/1996, art. 20, § 5º (apropriação em 48 parcelas).", "RECOMMENDED",
        {"eligible_cfops": FIXED_ASSET_CFOPS, "installments": 48},
    ),
    RuleVersion(
        "NX-CRD-003", 1, "PIS/COFINS não cumulativo não creditado", C.CREDIT_OPPORTUNITY,
        D(2004, 2, 1), D(2023, 4, 30),
        "Aplicável apenas a tenants no regime não cumulativo. Base = valor do item (vProd − vDesc). "
        "Estimativa = base × alíquota. Elegibilidade de insumos depende dos critérios de "
        "essencialidade/relevância e de exceções (monofásicos, alíquota zero, aquisição de não "
        "contribuinte), não verificáveis apenas pelo XML.",
        "Lei 10.637/2002, art. 3º (PIS); Lei 10.833/2003, art. 3º (COFINS); "
        "STJ, REsp 1.221.170/PR (conceito de insumo).",
        "RECOMMENDED",
        {"pis_rate": "0.0165", "cofins_rate": "0.0760", "eligible_cfops": PIS_COFINS_CREDIT_CFOPS,
         "credit_csts": PIS_COFINS_CREDIT_CSTS, "exclude_icms_from_base": False},
    ),
    RuleVersion(
        "NX-CRD-003", 2, "PIS/COFINS não cumulativo não creditado", C.CREDIT_OPPORTUNITY,
        D(2023, 5, 1), D(2026, 12, 31),
        "Como a v1, porém a base exclui o ICMS destacado no documento. Vigência encerrada em "
        "31/12/2026 com a extinção de PIS/COFINS e início da CBS.",
        "Lei 10.637/2002 e Lei 10.833/2003, art. 3º; exclusão do ICMS da base de crédito: "
        "MP 1.159/2023, convertida na Lei 14.592/2023; extinção: EC 132/2023.",
        "RECOMMENDED",
        {"pis_rate": "0.0165", "cofins_rate": "0.0760", "eligible_cfops": PIS_COFINS_CREDIT_CFOPS,
         "credit_csts": PIS_COFINS_CREDIT_CSTS, "exclude_icms_from_base": True},
        change_note="Exclusão do ICMS destacado da base de cálculo do crédito (a partir de 05/2023).",
    ),
    # ------------------------------------------------------------------ classification
    RuleVersion(
        "NX-CLS-001", 1, "CFOP de entrada incompatível com a operação", C.CLASSIFICATION,
        D(2006, 4, 1), OPEN_END,
        "Na perspectiva do destinatário, CFOP iniciado em 1 = operação interna (mesma UF) e 2 = "
        "interestadual. Compara o primeiro dígito escriturado com as UFs do emitente e destinatário.",
        "Convênio s/nº de 1970 e Ajuste SINIEF 07/2001 (tabela CFOP).", "NOT_REQUIRED",
    ),
    RuleVersion(
        "NX-CLS-002", 1, "NCM divergente entre XML e escrituração", C.CLASSIFICATION,
        D(2006, 4, 1), OPEN_END,
        "Compara o NCM do item no XML com o NCM informado na escrituração.",
        "Consistência cadastral; a classificação correta deve ser validada por especialista.",
        "NOT_REQUIRED",
    ),
    RuleVersion(
        "NX-CLS-003", 1, "Mesmo produto com NCMs diferentes", C.CLASSIFICATION, D(2006, 4, 1), OPEN_END,
        "Agrupa itens por (CNPJ do fornecedor, código do produto) e sinaliza quando há mais de "
        "um NCM — indício de classificação inconsistente.",
        "Consistência cadastral; não conclui qual NCM é o correto.", "NOT_REQUIRED",
    ),
    # ------------------------------------------------------------------ risk
    RuleVersion(
        "NX-RSK-001", 1, "Crédito de ICMS escriturado maior que o destacado", C.COMPLIANCE_RISK,
        D(2006, 4, 1), OPEN_END,
        "Crédito escriturado por item acima do ICMS destacado no XML. Exposição = excesso.",
        "LC 87/1996, art. 23; crédito limitado ao imposto destacado em documento idôneo.",
        "NOT_REQUIRED", {"abs_tolerance": "0.05"},
    ),
    RuleVersion(
        "NX-RSK-002", 1, "Lançamento duplicado na escrituração", C.COMPLIANCE_RISK,
        D(2006, 4, 1), OPEN_END,
        "Mesma chave + item escriturados mais de uma vez. Exposição = créditos das ocorrências "
        "excedentes.",
        "Verificação de consistência; crédito em duplicidade é indevido.", "NOT_REQUIRED",
    ),
    RuleVersion(
        "NX-RSK-003", 1, "Crédito sobre documento não autorizado", C.COMPLIANCE_RISK,
        D(2006, 4, 1), OPEN_END,
        "Documento com situação diferente de autorizada (cStat ≠ 100/150) escriturado com crédito.",
        "LC 87/1996, art. 23 (idoneidade documental).", "NOT_REQUIRED",
    ),
    # ------------------------------------------------------------------ anomaly
    RuleVersion(
        "NX-ANM-001", 1, "Alíquota efetiva de ICMS fora do padrão do NCM", C.ANOMALY,
        D(2006, 4, 1), OPEN_END,
        "Para cada NCM com amostra mínima, calcula a alíquota efetiva (vICMS / vBC) e o desvio "
        "robusto (mediana e MAD). Alerta apenas quando |z| supera o limiar E o desvio absoluto é de pelo menos 0,5 p.p. (evita ruído de arredondamento). Não indica, por "
        "si só, erro ou valor devido.",
        "Método estatístico de priorização (sem base legal própria).", "NOT_REQUIRED",
        {"min_sample": 8, "z_threshold": 3.5, "min_abs_deviation": "0.005", "rate_precision": "0.0001"},
    ),
    # ------------------------------------------------------------------ tax reform
    RuleVersion(
        "NX-RTC-001", 1, "NF-e sem grupo IBS/CBS (Reforma Tributária)", C.TAX_REFORM,
        D(2026, 1, 1), OPEN_END,
        "Documentos emitidos a partir de 01/01/2026 sem informação de IBS/CBS por item. Alerta "
        "informativo de prontidão: o cronograma de obrigatoriedade e eventuais dispensas de "
        "penalidade devem ser confirmados nas normas e notas técnicas vigentes.",
        "EC 132/2023; LC 214/2025; leiaute NF-e com grupo IBS/CBS (NT 2025.002 e atualizações).",
        "PENDING",
    ),
    RuleVersion(
        "NX-RTC-002", 1, "IBS/CBS destacados fora das alíquotas do ano de teste", C.TAX_REFORM,
        D(2026, 1, 1), D(2026, 12, 31),
        "Para 2026, compara IBS/CBS destacados com base × alíquotas de teste parametrizadas. "
        "Não considera reduções de alíquota, regimes específicos ou dispensas.",
        "LC 214/2025 — disposições transitórias para 2026 (CBS 0,9% e IBS 0,1%).",
        "PENDING",
        {"cbs_rate": "0.009", "ibs_rate": "0.001", "abs_tolerance": "0.05"},
    ),
]


class RuleCatalog:
    def __init__(self, rules: list[RuleVersion] | None = None):
        self._by_code: dict[str, list[RuleVersion]] = {}
        for r in rules or RULES:
            self._by_code.setdefault(r.code, []).append(r)
        for code, versions in self._by_code.items():
            versions.sort(key=lambda v: v.valid_from)
            for a, b in zip(versions, versions[1:]):
                if b.valid_from <= a.valid_to:
                    raise ValueError(f"Vigências sobrepostas na regra {code}: v{a.version} e v{b.version}")

    def resolve(self, code: str, on: date) -> RuleVersion | None:
        for v in self._by_code.get(code, []):
            if v.in_force(on):
                return v
        return None

    def latest(self, code: str) -> RuleVersion:
        return self._by_code[code][-1]

    def all(self) -> list[RuleVersion]:
        return [v for versions in self._by_code.values() for v in versions]


DEFAULT_CATALOG = RuleCatalog()
