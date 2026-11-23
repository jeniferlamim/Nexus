"""NF-e XML (layout 4.00) parser.

Uses ``defusedxml`` to neutralise XML bombs / external entities: files come from third parties.
Only the fields needed for tax analysis are extracted (data minimisation).
"""
from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

from ..domain.models import ZERO, DocumentItem, FiscalDocument
from .errors import ErrorSeverity, IngestionError, RecordError
from .validators import is_valid_cnpj, mask_cpf, only_digits, validate_access_key

NS = "{http://www.portalfiscal.inf.br/nfe}"
MAX_XML_BYTES = 5 * 1024 * 1024
MAX_ZIP_ENTRIES = 50_000


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _find(el: Element | None, path: str) -> Element | None:
    """Namespace-agnostic find using '/'-separated local names."""
    if el is None:
        return None
    current: Element | None = el
    for part in path.split("/"):
        nxt = None
        for child in list(current):  # type: ignore[arg-type]
            if _strip_ns(child.tag) == part:
                nxt = child
                break
        if nxt is None:
            return None
        current = nxt
    return current


def _text(el: Element | None, path: str, default: str = "") -> str:
    node = _find(el, path)
    return (node.text or "").strip() if node is not None and node.text else default


def _dec(el: Element | None, path: str) -> Decimal:
    raw = _text(el, path)
    if not raw:
        return ZERO
    try:
        return Decimal(raw)
    except InvalidOperation:
        return ZERO


def _first_descendant(el: Element | None, local: str) -> Element | None:
    if el is None:
        return None
    for node in el.iter():
        if _strip_ns(node.tag) == local:
            return node
    return None


def _desc_dec(el: Element | None, local: str) -> Decimal | None:
    node = _first_descendant(el, local)
    if node is None or not node.text:
        return None
    try:
        return Decimal(node.text.strip())
    except InvalidOperation:
        return None


def _icms_group(imposto: Element | None) -> Element | None:
    icms = _find(imposto, "ICMS")
    if icms is None or not list(icms):
        return None
    return list(icms)[0]  # ICMS00, ICMS10, ..., ICMSSN102


def _parse_date(raw: str) -> date:
    # dhEmi: 2025-03-14T10:22:00-03:00
    return datetime.fromisoformat(raw[:19]).date() if "T" in raw else date.fromisoformat(raw[:10])


def parse_nfe(content: bytes, source: str) -> tuple[FiscalDocument | None, list[RecordError]]:
    errors: list[RecordError] = []

    def err(field: str, value: str, msg: str, sev: ErrorSeverity = ErrorSeverity.BLOCKING) -> None:
        errors.append(RecordError(source, "arquivo", field, value, msg, sev))

    if len(content) > MAX_XML_BYTES:
        err("arquivo", str(len(content)), "XML excede o tamanho máximo permitido (5 MB)")
        return None, errors
    try:
        root = SafeET.fromstring(content)
    except Exception as exc:  # noqa: BLE001 - any parse failure is reported, never raised
        err("arquivo", "", f"XML malformado ou inseguro: {type(exc).__name__}")
        return None, errors

    inf = _first_descendant(root, "infNFe")
    if inf is None:
        err("infNFe", "", "Elemento infNFe não encontrado — arquivo não é uma NF-e")
        return None, errors

    key = only_digits(inf.attrib.get("Id", ""))
    for problem in validate_access_key(key):
        err("chave", key, problem)

    ide = _find(inf, "ide")
    emit = _find(inf, "emit")
    dest = _find(inf, "dest")
    total = _find(inf, "total/ICMSTot")

    issuer_cnpj = only_digits(_text(emit, "CNPJ"))
    if not is_valid_cnpj(issuer_cnpj):
        err("emit/CNPJ", issuer_cnpj, "CNPJ do emitente inválido (dígito verificador)",
            ErrorSeverity.WARNING)

    dest_cnpj = only_digits(_text(dest, "CNPJ"))
    dest_cpf = only_digits(_text(dest, "CPF"))
    recipient_doc = dest_cnpj or mask_cpf(dest_cpf)

    raw_date = _text(ide, "dhEmi") or _text(ide, "dEmi")
    try:
        issue_date = _parse_date(raw_date)
    except ValueError:
        err("ide/dhEmi", raw_date, "Data de emissão inválida")
        return None, errors

    if any(e.severity == ErrorSeverity.BLOCKING for e in errors):
        return None, errors

    items: list[DocumentItem] = []
    for det in [c for c in list(inf) if _strip_ns(c.tag) == "det"]:
        n_item = int(det.attrib.get("nItem", len(items) + 1))
        prod = _find(det, "prod")
        imp = _find(det, "imposto")
        icms = _icms_group(imp)
        pis = _find(imp, "PIS")
        pis_g = list(pis)[0] if pis is not None and list(pis) else None
        cof = _find(imp, "COFINS")
        cof_g = list(cof)[0] if cof is not None and list(cof) else None
        ibscbs = _find(imp, "IBSCBS")
        items.append(DocumentItem(
            item_number=n_item,
            product_code=_text(prod, "cProd"),
            description=_text(prod, "xProd")[:120],
            ncm=_text(prod, "NCM"),
            cfop=_text(prod, "CFOP"),
            quantity=_dec(prod, "qCom"),
            gross_amount=_dec(prod, "vProd"),
            discount=_dec(prod, "vDesc"),
            icms_cst=_text(icms, "CST") or _text(icms, "CSOSN"),
            icms_base=_dec(icms, "vBC"),
            icms_rate=_dec(icms, "pICMS"),
            icms_amount=_dec(icms, "vICMS"),
            ipi_amount=_desc_dec(_find(imp, "IPI"), "vIPI") or ZERO,
            pis_cst=_text(pis_g, "CST"),
            pis_amount=_dec(pis_g, "vPIS"),
            cofins_cst=_text(cof_g, "CST"),
            cofins_amount=_dec(cof_g, "vCOFINS"),
            ibs_cbs_base=_desc_dec(ibscbs, "vBC"),
            ibs_amount=_desc_dec(ibscbs, "vIBS"),
            cbs_amount=_desc_dec(ibscbs, "vCBS"),
            xpath=f"/NFe/infNFe/det[@nItem='{n_item}']",
        ))

    if not items:
        err("det", "", "NF-e sem itens")
        return None, errors

    status = "AUTHORIZED"
    c_stat = _text(_first_descendant(root, "infProt"), "cStat")
    if c_stat and c_stat not in {"100", "150"}:
        status = f"STATUS_{c_stat}"
        err("protNFe/cStat", c_stat, "NF-e não autorizada/denegada; mantida apenas para cruzamento",
            ErrorSeverity.WARNING)

    doc = FiscalDocument(
        access_key=key,
        model=_text(ide, "mod"),
        series=_text(ide, "serie"),
        number=_text(ide, "nNF"),
        issue_date=issue_date,
        issuer_cnpj=issuer_cnpj,
        issuer_name=_text(emit, "xNome")[:120],
        issuer_uf=_text(emit, "enderEmit/UF"),
        recipient_doc=recipient_doc,
        recipient_uf=_text(dest, "enderDest/UF"),
        operation_type=_text(ide, "tpNF"),
        total_amount=_dec(total, "vNF"),
        icms_total=_dec(total, "vICMS"),
        items=items,
        status=status,
        source_file=source,
        has_ibs_cbs_group=any(i.ibs_amount is not None or i.cbs_amount is not None for i in items),
    )
    return doc, errors


def iter_xml_payloads(filename: str, content: bytes):
    """Yield (name, bytes) for a single XML or for each XML inside a ZIP."""
    lower = filename.lower()
    if lower.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile as exc:
            raise IngestionError("Arquivo ZIP inválido") from exc
        entries = [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith(".xml")]
        if len(entries) > MAX_ZIP_ENTRIES:
            raise IngestionError(f"ZIP com mais de {MAX_ZIP_ENTRIES} XMLs; divida o lote")
        for info in entries:
            if info.file_size > MAX_XML_BYTES:  # zip-bomb guard (declared size)
                yield info.filename, b"\x00" * (MAX_XML_BYTES + 1)
                continue
            with zf.open(info) as fh:
                yield f"{filename}/{info.filename}", fh.read(MAX_XML_BYTES + 1)
    elif lower.endswith(".xml"):
        yield filename, content
    else:
        raise IngestionError("Formato não suportado para NF-e: envie .xml ou .zip")
