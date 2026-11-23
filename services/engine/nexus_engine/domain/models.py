"""Core domain model for NEXUS.

Pure dataclasses, no I/O. Everything monetary is ``Decimal``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

ZERO = Decimal("0")
CENT = Decimal("0.01")


def money(value: Any) -> Decimal:
    """Parse a monetary value accepting both '1234.56' and Brazilian '1.234,56'."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text:
        return ZERO
    if "," in text:
        # Brazilian format: thousands '.' and decimal ','
        text = text.replace(".", "").replace(",", ".")
    return Decimal(text)


class SourceType(str, Enum):
    NFE_XML = "NFE_XML"          # NF-e XML files (or a ZIP of them)
    FISCAL_BOOK = "FISCAL_BOOK"  # Escrituração fiscal (livro de entradas/saídas) - CSV/XLSX
    LEDGER = "LEDGER"            # Razão contábil - CSV/XLSX


class Direction(str, Enum):
    INBOUND = "INBOUND"    # entrada (tenant is the recipient)
    OUTBOUND = "OUTBOUND"  # saída (tenant is the issuer)
    UNRELATED = "UNRELATED"


class FindingCategory(str, Enum):
    RECONCILIATION = "RECONCILIATION"
    CREDIT_OPPORTUNITY = "CREDIT_OPPORTUNITY"
    CLASSIFICATION = "CLASSIFICATION"
    COMPLIANCE_RISK = "COMPLIANCE_RISK"
    DATA_QUALITY = "DATA_QUALITY"
    ANOMALY = "ANOMALY"
    TAX_REFORM = "TAX_REFORM"


class FindingKind(str, Enum):
    ESTIMATE = "ESTIMATE"    # estimated opportunity, never guaranteed
    ALERT = "ALERT"          # inconsistency / risk signal
    VALIDATED = "VALIDATED"  # conclusion validated by an authorised human


class AmountType(str, Enum):
    RECOVERABLE_ESTIMATE = "RECOVERABLE_ESTIMATE"  # potential credit not taken
    EXPOSURE_ESTIMATE = "EXPOSURE_ESTIMATE"        # potential liability / undue credit
    DIVERGENCE_VALUE = "DIVERGENCE_VALUE"          # data difference, not a tax amount
    NONE = "NONE"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    VALIDATED = "VALIDATED"   # approved by an authorised reviewer
    DISMISSED = "DISMISSED"   # approved as false positive / not applicable


def confidence_label(value: float) -> str:
    if value >= 0.85:
        return "ALTA"
    if value >= 0.6:
        return "MÉDIA"
    return "BAIXA"


# --------------------------------------------------------------------------- documents


@dataclass
class DocumentItem:
    item_number: int
    product_code: str
    description: str
    ncm: str
    cfop: str
    quantity: Decimal
    gross_amount: Decimal          # vProd
    discount: Decimal = ZERO
    icms_cst: str = ""
    icms_base: Decimal = ZERO
    icms_rate: Decimal = ZERO
    icms_amount: Decimal = ZERO
    ipi_amount: Decimal = ZERO
    pis_cst: str = ""
    pis_amount: Decimal = ZERO
    cofins_cst: str = ""
    cofins_amount: Decimal = ZERO
    ibs_cbs_base: Decimal | None = None  # Reforma Tributária (grupo IBSCBS)
    ibs_amount: Decimal | None = None
    cbs_amount: Decimal | None = None
    xpath: str = ""

    @property
    def net_amount(self) -> Decimal:
        return self.gross_amount - self.discount


@dataclass
class FiscalDocument:
    access_key: str           # chave de acesso (44 dígitos)
    model: str                # 55 = NF-e
    series: str
    number: str
    issue_date: date
    issuer_cnpj: str
    issuer_name: str
    issuer_uf: str
    recipient_doc: str        # CNPJ, or masked CPF
    recipient_uf: str
    operation_type: str       # tpNF: 0 entrada / 1 saída (issuer perspective)
    total_amount: Decimal     # vNF
    icms_total: Decimal
    items: list[DocumentItem] = field(default_factory=list)
    status: str = "AUTHORIZED"
    source_file: str = ""
    has_ibs_cbs_group: bool = False
    direction: Direction = Direction.UNRELATED

    @property
    def period(self) -> str:
        return self.issue_date.strftime("%Y-%m")


@dataclass
class BookEntry:
    """One item line of the fiscal book (escrituração), flattened from C100/C170-like exports."""
    access_key: str
    document_number: str
    entry_date: date
    direction: Direction
    counterparty_cnpj: str
    item_number: int
    cfop: str
    ncm: str
    amount: Decimal
    icms_base: Decimal
    icms_credit: Decimal      # ICMS escriturado (crédito na entrada / débito na saída)
    pis_credit: Decimal
    cofins_credit: Decimal
    pis_cst: str = ""
    ipi_credit: Decimal = ZERO
    source_file: str = ""
    source_row: int = 0

    @property
    def period(self) -> str:
        return self.entry_date.strftime("%Y-%m")


@dataclass
class LedgerEntry:
    entry_date: date
    account: str
    account_name: str
    history: str
    debit: Decimal
    credit: Decimal
    access_key: str = ""
    source_file: str = ""
    source_row: int = 0

    @property
    def period(self) -> str:
        return self.entry_date.strftime("%Y-%m")


# --------------------------------------------------------------------------- findings


@dataclass
class Evidence:
    source: str                     # file name or dataset
    locator: str                    # row number, xpath, period ...
    field: str
    observed: str
    expected: str = ""
    note: str = ""


@dataclass
class Finding:
    rule_code: str
    rule_version: int
    category: FindingCategory
    kind: FindingKind
    severity: Severity
    title: str
    description: str
    methodology: str
    legal_basis: str
    confidence: float
    amount_type: AmountType
    estimated_amount: Decimal = ZERO
    tax: str | None = None
    access_key: str | None = None
    counterparty_cnpj: str | None = None
    period: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    calculation: dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""

    @property
    def requires_human_validation(self) -> bool:
        return self.kind != FindingKind.VALIDATED

    @property
    def confidence_label(self) -> str:
        return confidence_label(self.confidence)
