"""CSV / XLSX parsers for fiscal book (escrituração) and ledger (razão) exports.

ERP exports vary a lot, so headers are normalised (case, accents, separators) and matched against
aliases. Unknown columns are ignored (minimisation); missing mandatory columns fail the file.
"""
from __future__ import annotations

import csv
import io
import unicodedata
from datetime import date, datetime
from decimal import InvalidOperation
from typing import Callable, Iterable

from ..domain.models import BookEntry, Direction, LedgerEntry, money
from .errors import ErrorSeverity, IngestionError, RecordError
from .validators import is_valid_cfop, is_valid_cnpj, is_valid_ncm, only_digits, validate_access_key

MAX_ROWS = 1_000_000


def normalise_header(h: str) -> str:
    h = unicodedata.normalize("NFKD", str(h or "")).encode("ascii", "ignore").decode()
    return "".join(ch if ch.isalnum() else "_" for ch in h.strip().lower()).strip("_")


BOOK_COLUMNS: dict[str, tuple[list[str], bool]] = {
    # canonical: (aliases, mandatory)
    "access_key": (["chave", "chave_nfe", "chave_acesso", "chv_nfe"], True),
    "document_number": (["numero", "num_doc", "numero_nf", "nf"], False),
    "entry_date": (["data", "dt_entrada", "data_entrada", "dt_doc", "data_documento"], True),
    "direction": (["tipo", "ind_oper", "entrada_saida", "operacao"], True),
    "counterparty_cnpj": (["cnpj_participante", "cnpj", "cnpj_fornecedor", "participante"], True),
    "item_number": (["item", "num_item", "n_item"], True),
    "cfop": (["cfop"], True),
    "ncm": (["ncm", "cod_ncm"], False),
    "amount": (["valor", "vl_item", "valor_item"], True),
    "icms_base": (["bc_icms", "vl_bc_icms", "base_icms"], False),
    "icms_credit": (["vl_icms", "icms", "valor_icms", "icms_creditado"], True),
    "pis_credit": (["vl_pis", "pis", "pis_creditado"], False),
    "cofins_credit": (["vl_cofins", "cofins", "cofins_creditado"], False),
    "pis_cst": (["cst_pis"], False),
}

LEDGER_COLUMNS: dict[str, tuple[list[str], bool]] = {
    "entry_date": (["data", "dt_lancamento", "data_lancamento"], True),
    "account": (["conta", "cod_conta", "conta_contabil"], True),
    "account_name": (["descricao_conta", "nome_conta", "desc_conta"], False),
    "history": (["historico", "hist", "descricao"], False),
    "debit": (["debito", "vl_debito"], True),
    "credit": (["credito", "vl_credito"], True),
    "access_key": (["chave", "chave_nfe"], False),
}


def _read_rows(filename: str, content: bytes) -> tuple[list[str], Iterable[tuple[int, list[str]]]]:
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001
            raise IngestionError("Planilha XLSX inválida ou corrompida") from exc
        ws = wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = [str(c) if c is not None else "" for c in next(rows, [])]

        def gen():
            for i, r in enumerate(rows, start=2):
                yield i, ["" if c is None else (c.isoformat() if isinstance(c, (date, datetime)) else str(c)) for c in r]

        return header, gen()
    if lower.endswith((".csv", ".txt")):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        sample = text[:4096]
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        header = next(reader, [])
        return header, ((i, row) for i, row in enumerate(reader, start=2))
    raise IngestionError("Formato não suportado: envie .csv ou .xlsx")


def _map_columns(header: list[str], spec: dict[str, tuple[list[str], bool]]) -> dict[str, int]:
    norm = [normalise_header(h) for h in header]
    mapping: dict[str, int] = {}
    for canonical, (aliases, _) in spec.items():
        for alias in [canonical, *aliases]:
            if alias in norm:
                mapping[canonical] = norm.index(alias)
                break
    missing = [c for c, (al, mandatory) in spec.items() if mandatory and c not in mapping]
    if missing:
        raise IngestionError(
            "Colunas obrigatórias ausentes: " + ", ".join(f"{m} (aceita: {', '.join(spec[m][0])})" for m in missing)
        )
    return mapping


def _parse_date(raw: str) -> date:
    raw = raw.strip()[:19]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(raw)


def _direction(raw: str) -> Direction:
    r = normalise_header(raw)
    if r in {"e", "0", "entrada", "in", "inbound"}:
        return Direction.INBOUND
    if r in {"s", "1", "saida", "out", "outbound"}:
        return Direction.OUTBOUND
    raise ValueError(raw)


def _row_parser(source: str, spec, mapping):
    def get(row: list[str], col: str) -> str:
        idx = mapping.get(col)
        return row[idx].strip() if idx is not None and idx < len(row) and row[idx] is not None else ""

    def parse_field(row_errors, row_no, row, col, fn: Callable, default=None, sev=ErrorSeverity.BLOCKING):
        raw = get(row, col)
        if raw == "" and default is not None:
            return default
        try:
            return fn(raw)
        except (ValueError, InvalidOperation):
            row_errors.append(RecordError(source, f"linha {row_no}", col, raw, "valor inválido", sev))
            return default

    return get, parse_field


def parse_fiscal_book(filename: str, content: bytes) -> tuple[list[BookEntry], list[RecordError], int]:
    header, rows = _read_rows(filename, content)
    mapping = _map_columns(header, BOOK_COLUMNS)
    get, pf = _row_parser(filename, BOOK_COLUMNS, mapping)
    out: list[BookEntry] = []
    errors: list[RecordError] = []
    total = 0
    for row_no, row in rows:
        if not any(str(c).strip() for c in row):
            continue
        total += 1
        if total > MAX_ROWS:
            raise IngestionError(f"Arquivo excede {MAX_ROWS} linhas; divida por período")
        row_errors: list[RecordError] = []
        key = only_digits(get(row, "access_key"))
        for p in validate_access_key(key):
            row_errors.append(RecordError(filename, f"linha {row_no}", "access_key", key, p))
        cnpj = only_digits(get(row, "counterparty_cnpj"))
        if not is_valid_cnpj(cnpj):
            row_errors.append(RecordError(filename, f"linha {row_no}", "counterparty_cnpj", cnpj,
                                          "CNPJ do participante inválido", ErrorSeverity.WARNING))
        cfop = only_digits(get(row, "cfop"))
        if not is_valid_cfop(cfop):
            row_errors.append(RecordError(filename, f"linha {row_no}", "cfop", cfop, "CFOP inválido"))
        ncm = get(row, "ncm")
        if ncm and not is_valid_ncm(ncm):
            row_errors.append(RecordError(filename, f"linha {row_no}", "ncm", ncm,
                                          "NCM deve ter 8 dígitos", ErrorSeverity.WARNING))
        entry_date = pf(row_errors, row_no, row, "entry_date", _parse_date)
        direction = pf(row_errors, row_no, row, "direction", _direction)
        item_number = pf(row_errors, row_no, row, "item_number", lambda r: int(float(r)))
        amount = pf(row_errors, row_no, row, "amount", money)
        icms_base = pf(row_errors, row_no, row, "icms_base", money, default=money(0))
        icms = pf(row_errors, row_no, row, "icms_credit", money, default=money(0))
        pis = pf(row_errors, row_no, row, "pis_credit", money, default=money(0))
        cofins = pf(row_errors, row_no, row, "cofins_credit", money, default=money(0))
        errors.extend(row_errors)
        if any(e.severity == ErrorSeverity.BLOCKING for e in row_errors):
            continue
        out.append(BookEntry(
            access_key=key, document_number=get(row, "document_number"), entry_date=entry_date,
            direction=direction, counterparty_cnpj=cnpj, item_number=item_number, cfop=cfop,
            ncm=only_digits(ncm), amount=amount, icms_base=icms_base, icms_credit=icms,
            pis_credit=pis, cofins_credit=cofins, pis_cst=get(row, "pis_cst"),
            source_file=filename, source_row=row_no,
        ))
    return out, errors, total


def parse_ledger(filename: str, content: bytes) -> tuple[list[LedgerEntry], list[RecordError], int]:
    header, rows = _read_rows(filename, content)
    mapping = _map_columns(header, LEDGER_COLUMNS)
    get, pf = _row_parser(filename, LEDGER_COLUMNS, mapping)
    out: list[LedgerEntry] = []
    errors: list[RecordError] = []
    total = 0
    for row_no, row in rows:
        if not any(str(c).strip() for c in row):
            continue
        total += 1
        if total > MAX_ROWS:
            raise IngestionError(f"Arquivo excede {MAX_ROWS} linhas; divida por período")
        row_errors: list[RecordError] = []
        entry_date = pf(row_errors, row_no, row, "entry_date", _parse_date)
        debit = pf(row_errors, row_no, row, "debit", money, default=money(0))
        credit = pf(row_errors, row_no, row, "credit", money, default=money(0))
        account = get(row, "account")
        if not account:
            row_errors.append(RecordError(filename, f"linha {row_no}", "account", "", "conta vazia"))
        errors.extend(row_errors)
        if any(e.severity == ErrorSeverity.BLOCKING for e in row_errors):
            continue
        out.append(LedgerEntry(
            entry_date=entry_date, account=account, account_name=get(row, "account_name"),
            history=get(row, "history")[:200], debit=debit, credit=credit,
            access_key=only_digits(get(row, "access_key")), source_file=filename, source_row=row_no,
        ))
    return out, errors, total
