"""Synthetic but realistic demo dataset (fictional companies).

Produces the three raw inputs a client would upload — a ZIP of NF-e XMLs, a fiscal book CSV
(Brazilian format: ';' and decimal comma) and a ledger XLSX — plus a ``truth`` manifest of the
anomalies injected. The platform never reads ``truth``: tests use it to check the engine finds
exactly what was planted. Every number shown in the demo is computed by the engine from the files.
"""
from __future__ import annotations

import csv
import io
import random
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from xml.sax.saxutils import escape

from openpyxl import Workbook

from ..ingestion.validators import build_access_key, cnpj_with_dv

D = Decimal
C2 = D("0.01")
NS = "http://www.portalfiscal.inf.br/nfe"
SOUTH_SOUTHEAST = {"SP", "MG", "RJ", "PR", "SC", "RS"}


def q(v) -> Decimal:
    return D(v).quantize(C2, rounding=ROUND_HALF_UP)


def br(v: Decimal) -> str:
    return f"{q(v):.2f}".replace(".", ",")


def interstate_rate(orig: str, dest: str) -> D:
    if orig == dest:
        return D("18")
    if orig in SOUTH_SOUTHEAST and dest not in SOUTH_SOUTHEAST | {"ES"}:
        return D("7")
    return D("12")


@dataclass
class Product:
    code: str
    description: str
    ncm: str
    kind: str  # INPUT | RESALE | CONSUMPTION | ASSET
    price: tuple[int, int]


@dataclass
class Supplier:
    cnpj: str
    name: str
    uf: str
    products: list[Product]
    emits_ibs_cbs: bool = True
    wrong_ibs_cbs: bool = False


@dataclass
class Item:
    n: int
    product: Product
    cfop: str
    qty: D
    vprod: D
    vdesc: D
    rate: D
    vbc: D
    vicms: D
    vpis: D
    vcofins: D
    ibs_cbs: tuple[D, D, D] | None  # base, ibs, cbs


@dataclass
class Doc:
    key: str
    number: int
    issue: date
    issuer_cnpj: str
    issuer_name: str
    issuer_uf: str
    dest_cnpj: str
    dest_uf: str
    tp_nf: str
    items: list[Item]
    cstat: str = "100"

    @property
    def vicms(self) -> D:
        return sum((i.vicms for i in self.items), D(0))

    @property
    def vnf(self) -> D:
        return sum((i.vprod - i.vdesc for i in self.items), D(0))


@dataclass
class BookLine:
    key: str
    number: str
    entry_date: date
    direction: str
    cnpj: str
    item: int
    cfop: str
    ncm: str
    amount: D
    bc: D
    icms: D
    pis: D
    cofins: D
    cst_pis: str


@dataclass
class DemoDataset:
    tenant_name: str
    cnpj_roots: list[str]
    xml_zip: bytes
    book_csv: bytes
    ledger_xlsx: bytes
    ledger_accounts: dict[str, list[str]]
    truth: dict[str, list] = field(default_factory=lambda: defaultdict(list))
    stats: dict[str, int] = field(default_factory=dict)


INDUSTRY_PRODUCTS = [
    Product("AC-1020", "Chapa aço laminado a quente 3mm", "72085100", "INPUT", (40_000, 260_000)),
    Product("AC-1045", "Bobina aço carbono SAE 1045", "72083990", "INPUT", (60_000, 320_000)),
    Product("AL-6061", "Chapa alumínio liga 6061", "76061190", "INPUT", (25_000, 140_000)),
    Product("PF-M10", "Parafuso sextavado M10 zincado", "73181500", "INPUT", (2_000, 18_000)),
    Product("RL-6205", "Rolamento rígido de esferas 6205", "84821010", "INPUT", (3_000, 30_000)),
    Product("JT-NBR", "Junta de vedação NBR", "40169300", "INPUT", (1_500, 12_000)),
    Product("TN-EPX", "Tinta epóxi industrial cinza", "32089010", "INPUT", (5_000, 45_000)),
    Product("CX-PAP", "Caixa papelão ondulado embalagem", "48191000", "INPUT", (4_000, 22_000)),
    Product("OL-LUB", "Óleo lubrificante manutenção ISO 68", "27101932", "CONSUMPTION", (1_000, 9_000)),
    Product("EPI-LUV", "Luva de segurança nitrílica", "40151900", "CONSUMPTION", (800, 6_000)),
    Product("MQ-CNC", "Centro de usinagem CNC vertical", "84571000", "ASSET", (380_000, 1_200_000)),
    Product("CP-FRQ", "Conversor de frequência 75kW", "85044090", "INPUT", (18_000, 90_000)),
]

SUPPLIER_NAMES = [
    ("Siderúrgica Vale do Aço Ltda", "MG"), ("Laminados Paulista S.A.", "SP"), ("Alumínios do Sul Ltda", "RS"),
    ("Fixadores Campinas Ind. Ltda", "SP"), ("Rolamentos Brasil Comércio Ltda", "PR"),
    ("Vedações Técnicas Joinville Ltda", "SC"), ("Tintas Industriais Guarulhos S.A.", "SP"),
    ("Embalagens Paraná Ltda", "PR"), ("Lubrificantes Rio Distribuidora Ltda", "RJ"),
    ("Proteção Total EPIs Ltda", "GO"), ("Máquinas Operatrizes Caxias S.A.", "RS"),
    ("Eletrotécnica Nordeste Ltda", "BA"), ("Metais Especiais Sorocaba Ltda", "SP"),
    ("Componentes Mecânicos BH Ltda", "MG"), ("Distribuidora Aço Centro-Oeste Ltda", "GO"),
    ("Química Fina Camaçari S.A.", "BA"), ("Ferragens Santa Catarina Ltda", "SC"),
    ("Polímeros Técnicos ABC Ltda", "SP"),
]

CUSTOMERS = [("Montadora Planalto Ltda", "SP"), ("Implementos Agrícolas Cerrado S.A.", "GO"),
             ("Construtora Atlântico Ltda", "RJ"), ("Equipamentos Nordeste S.A.", "PE"),
             ("Máquinas Pesadas Sul Ltda", "RS"), ("Indústria Naval Baía Ltda", "BA")]


def generate(seed: int = 7, root: str = "45723174", tenant_name: str = "Vértice Componentes Industriais S.A.",
             months: list[tuple[int, int]] | None = None, docs_per_month: int = 70) -> DemoDataset:
    rnd = random.Random(seed)
    months = months or [(2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3)]
    legacy_months = [(2023, 4), (2023, 5)]  # extemporaneous review window → shows rule versioning
    hq = cnpj_with_dv(root + "0001")
    branch = cnpj_with_dv(root + "0002")
    establishments = [(hq, "SP"), (branch, "MG")]
    truth: dict[str, list] = defaultdict(list)

    suppliers: list[Supplier] = []
    for i, (name, uf) in enumerate(SUPPLIER_NAMES):
        cnpj = cnpj_with_dv(f"{10_000_000 + i * 734_521:08d}0001")
        prods = rnd.sample(INDUSTRY_PRODUCTS[:8] + [INDUSTRY_PRODUCTS[11]], 3)
        if "Lubrificantes" in name or "EPIs" in name:
            prods = [p for p in INDUSTRY_PRODUCTS if p.kind == "CONSUMPTION"]
        if "Máquinas" in name:
            prods = [INDUSTRY_PRODUCTS[10]]
        suppliers.append(Supplier(cnpj, name, uf, prods))
    suppliers[11].emits_ibs_cbs = False   # Eletrotécnica Nordeste: not ready for the reform
    suppliers[15].emits_ibs_cbs = False
    suppliers[13].wrong_ibs_cbs = True    # Componentes Mecânicos BH: wrong test rates
    bad_cnpj_supplier = suppliers[16]
    bad_cnpj_supplier.cnpj = bad_cnpj_supplier.cnpj[:12] + ("00" if bad_cnpj_supplier.cnpj[12:] != "00" else "11")
    truth["NX-DQ-002"].append(bad_cnpj_supplier.cnpj)
    # same product from the same supplier with two NCMs (classification inconsistency)
    ncm_split_supplier = suppliers[3]

    customers = [(cnpj_with_dv(f"{60_000_000 + i * 912_331:08d}0001"), n, uf) for i, (n, uf) in enumerate(CUSTOMERS)]

    docs: list[Doc] = []
    numbers: dict[str, int] = defaultdict(lambda: 1000)

    def make_items(prods: list[Product], cfop_prefix: str, rate: D, issue: date, with_ibs: bool,
                   wrong_ibs: bool) -> list[Item]:
        items = []
        for n, p in enumerate(prods, start=1):
            vprod = q(D(rnd.randint(*p.price)) + D(rnd.randint(0, 99)) / 100)
            vdesc = q(vprod * D(rnd.choice([0, 0, 0, 1, 2])) / 100)
            base = vprod - vdesc
            vicms = q(base * rate / 100)
            cfop = cfop_prefix + ("101" if p.kind in ("INPUT", "ASSET") else "102")
            ibs = None
            if issue >= date(2026, 1, 1) and with_ibs:
                cbs_rate, ibs_rate = (D("0.009"), D("0.001")) if not wrong_ibs else (D("0.0125"), D("0.001"))
                ibs = (base, q(base * ibs_rate), q(base * cbs_rate))
            items.append(Item(n, p, cfop, D(rnd.randint(1, 400)), vprod, vdesc, rate, base, vicms,
                              q(base * D("0.0165")), q(base * D("0.076")), ibs))
        return items

    def new_doc(issuer_cnpj, issuer_name, issuer_uf, dest_cnpj, dest_uf, tp, issue, items) -> Doc:
        numbers[issuer_cnpj] += rnd.randint(1, 9)
        num = numbers[issuer_cnpj]
        key = build_access_key(issuer_uf, issue.strftime("%y%m"), issuer_cnpj, "55", 1, num,
                               code=rnd.randint(10_000_000, 99_999_999))
        return Doc(key, num, issue, issuer_cnpj, issuer_name, issuer_uf, dest_cnpj, dest_uf, tp, items)

    for (y, m) in legacy_months + months:
        n_docs = docs_per_month if (y, m) in months else 14
        for _ in range(n_docs):
            sup = rnd.choice(suppliers)
            est_cnpj, est_uf = rnd.choice(establishments)
            issue = date(y, m, 1) + timedelta(days=rnd.randint(0, 26))
            rate = interstate_rate(sup.uf, est_uf)
            prods = rnd.sample(sup.products, k=min(len(sup.products), rnd.randint(1, 3)))
            prefix = "5" if sup.uf == est_uf else "6"
            items = make_items(prods, prefix, rate, issue, sup.emits_ibs_cbs, sup.wrong_ibs_cbs)
            if sup is ncm_split_supplier and m in (2, 3) and y == 2026:
                for it in items:
                    if it.product.code == sup.products[0].code:
                        it.product = Product(it.product.code, it.product.description, "73182900",
                                             it.product.kind, it.product.price)
            docs.append(new_doc(sup.cnpj, sup.name, sup.uf, est_cnpj, est_uf, "1", issue, items))
        if (y, m) in months:
            for _ in range(docs_per_month // 3):
                c_cnpj, c_name, c_uf = rnd.choice(customers)
                issue = date(y, m, 1) + timedelta(days=rnd.randint(0, 26))
                rate = interstate_rate("SP", c_uf)
                prods = [Product("VC-" + str(rnd.randint(100, 999)), "Conjunto usinado sob encomenda", "84879000",
                                 "INPUT", (30_000, 420_000))]
                items = make_items(prods, "5" if c_uf == "SP" else "6", rate, issue, (y, m) != (2026, 2), False)
                docs.append(new_doc(hq, tenant_name, "SP", c_cnpj, c_uf, "1", issue, items))
    truth["NX-RTC-001-own"].append("2026-02")

    inbound = [d for d in docs if d.dest_cnpj[:8] == root]
    outbound = [d for d in docs if d.issuer_cnpj[:8] == root]
    recent_in = [d for d in inbound if d.issue >= date(2025, 10, 1)]

    # ---------------------------------------------------------------- build fiscal book
    def entry_cfop(d: Doc, it: Item) -> str:
        local = d.issuer_uf == d.dest_uf
        p = "1" if local else "2"
        return p + {"INPUT": "101", "RESALE": "102", "CONSUMPTION": "556", "ASSET": "551"}[it.product.kind]

    book: list[BookLine] = []
    skip_docs = set()
    for d in rnd.sample([d for d in recent_in if d.vicms > 1000 and d.issuer_cnpj != bad_cnpj_supplier.cnpj], 12):
        skip_docs.add(d.key)
        truth["NX-REC-001"].append(d.key)
    for d in rnd.sample(outbound, 3):
        skip_docs.add(d.key)
        truth["NX-REC-002"].append(d.key)

    pool = [d for d in recent_in if d.key not in skip_docs]
    rnd.shuffle(pool)
    cursor = iter(pool)

    def take(n, cond=lambda d: True):
        out = []
        for d in cursor:
            if cond(d):
                out.append(d)
                if len(out) == n:
                    break
        return out

    is_input = lambda d: all(i.product.kind == "INPUT" for i in d.items)  # noqa: E731
    no_icms_credit = {d.key for d in take(15, is_input)}
    partial_icms = {d.key for d in take(6, is_input)}
    over_credit = {d.key for d in take(3, is_input)}
    value_div = {d.key for d in take(8)}
    partial_docs = {d.key for d in take(3, lambda d: len(d.items) >= 2 and is_input(d))}
    ncm_div = {d.key for d in take(5)}
    cfop_err = {d.key for d in take(4, is_input)}
    dup_docs = {d.key for d in take(2, is_input)}
    no_pis = {d.key for d in take(14, is_input)}
    no_pis |= {d.key for d in inbound if d.issue < date(2024, 1, 1) and is_input(d)}
    rate_anom = take(2, lambda d: d.issuer_uf == d.dest_uf and is_input(d))
    cancelled = take(1, is_input)
    key_mismatch = take(1)
    for d in rate_anom:  # 7% on an internal operation: statistical outlier
        for it in d.items:
            it.rate, it.vicms = D("7"), q(it.vbc * D("0.07"))
        truth["NX-ANM-001"].append(d.key)
    for d in cancelled:
        d.cstat = "101"
        truth["NX-RSK-003"].append(d.key)
    for d in key_mismatch:
        other = suppliers[0].cnpj if d.issuer_cnpj != suppliers[0].cnpj else suppliers[1].cnpj
        d.key = d.key[:6] + other + d.key[20:]
        from ..ingestion.validators import access_key_dv
        d.key = d.key[:43] + access_key_dv(d.key[:43])
        truth["NX-DQ-001"].append(d.key)

    for k in no_icms_credit | partial_icms:
        truth["NX-CRD-001"].append(k)
    truth["NX-RSK-001"] = sorted(over_credit)
    truth["NX-REC-004"] = sorted(value_div)
    truth["NX-REC-005"] = sorted(partial_docs)
    truth["NX-CLS-002"] = sorted(ncm_div)
    truth["NX-CLS-001"] = sorted(cfop_err)
    truth["NX-RSK-002"] = sorted(dup_docs)
    truth["NX-CRD-003"] = sorted(no_pis)

    for d in docs:
        if d.key in skip_docs:
            continue
        direction = "E" if d in inbound else "S"
        counterparty = d.issuer_cnpj if direction == "E" else d.dest_cnpj
        entry = d.issue + timedelta(days=rnd.randint(0, 3)) if direction == "E" else d.issue
        if entry.month != d.issue.month:
            entry = d.issue
        for it in d.items:
            if d.key in partial_docs and it.n == len(d.items):
                continue
            cfop = entry_cfop(d, it) if direction == "E" else it.cfop
            amount = it.vprod - it.vdesc
            icms = it.vicms
            pis, cof, cst = it.vpis, it.vcofins, "50"
            if direction == "E":
                if it.product.kind == "CONSUMPTION":
                    icms, pis, cof, cst = D(0), D(0), D(0), "98"
                if it.product.kind == "ASSET":
                    icms = D(0) if rnd.random() < 0.6 else icms
                    if icms == 0:
                        truth["NX-CRD-002"].append(d.key)
                if d.key in no_icms_credit:
                    icms = D(0)
                if d.key in partial_icms:
                    icms = q(icms * D("0.5"))
                if d.key in over_credit:
                    icms = q(icms * D("1.5"))
                if d.key in value_div and it.n == 1:
                    amount = q(amount * D("1.08"))
                if d.key in no_pis:
                    pis, cof, cst = D(0), D(0), "70"
                if d.key in cfop_err:
                    cfop = ("2" if cfop[0] == "1" else "1") + cfop[1:]
            ncm = it.product.ncm
            if d.key in ncm_div and it.n == 1:
                ncm = "84799090"
            line = BookLine(d.key, str(d.number), entry, direction, counterparty, it.n, cfop, ncm, amount,
                            it.vbc, icms, pis, cof, cst)
            book.append(line)
            if d.key in dup_docs and it.n == 1:
                book.append(line)
    # book entries without XML
    for k in range(4):
        sup = rnd.choice(suppliers[:8])
        issue = date(2026, 1 + k % 3, 10 + k)
        fake = new_doc(sup.cnpj, sup.name, sup.uf, hq, "SP", "1", issue,
                       make_items(sup.products[:1], "5" if sup.uf == "SP" else "6",
                                  interstate_rate(sup.uf, "SP"), issue, True, False))
        it = fake.items[0]
        book.append(BookLine(fake.key, str(fake.number), issue, "E", sup.cnpj, 1, entry_cfop(fake, it),
                             it.product.ncm, it.vprod - it.vdesc, it.vbc, it.vicms, it.vpis, it.vcofins, "50"))
        truth["NX-REC-003"].append(fake.key)

    # ---------------------------------------------------------------- ledger
    accounts = {"ICMS": ["1.1.3.01"], "PIS": ["1.1.3.02"], "COFINS": ["1.1.3.03"]}
    totals: dict[tuple[str, str], D] = defaultdict(lambda: D(0))
    for b in book:
        if b.direction == "E":
            p = b.entry_date.strftime("%Y-%m")
            totals[(p, "ICMS")] += b.icms
            totals[(p, "PIS")] += b.pis
            totals[(p, "COFINS")] += b.cofins
    wb = Workbook()
    ws = wb.active
    ws.title = "Razao"
    ws.append(["Data", "Conta", "Descrição Conta", "Histórico", "Débito", "Crédito"])
    names = {"1.1.3.01": "ICMS a Recuperar", "1.1.3.02": "PIS a Recuperar", "1.1.3.03": "COFINS a Recuperar"}
    divergent = {("2025-12", "ICMS"): D("-38412.77"), ("2026-02", "COFINS"): D("21950.40")}
    for (p, tax), v in sorted(totals.items()):
        y, m = map(int, p.split("-"))
        adj = divergent.get((p, tax), D(0))
        if adj:
            truth["NX-REC-006"].append(f"{p}:{tax}")
        acct = accounts[tax][0]
        last = date(y, m, 28)
        ws.append([last.isoformat(), acct, names[acct], f"Créditos {tax} ref. {p} (apuração)", float(q(v + adj)), 0.0])
        ws.append([last.isoformat(), "4.1.1.01", "Custo de Materiais", f"Compras {p}", float(q(v * 9)), 0.0])
    buf = io.BytesIO()
    wb.save(buf)

    # ---------------------------------------------------------------- serialise XML + CSV
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in docs:
            zf.writestr(f"{d.key}-nfe.xml", _to_xml(d))
    cbuf = io.StringIO()
    w = csv.writer(cbuf, delimiter=";")
    w.writerow(["CHAVE_NFE", "NUM_DOC", "DT_ENTRADA", "TIPO", "CNPJ_PARTICIPANTE", "NUM_ITEM", "CFOP", "NCM",
                "VL_ITEM", "VL_BC_ICMS", "VL_ICMS", "VL_PIS", "VL_COFINS", "CST_PIS"])
    for b in book:
        w.writerow([b.key, b.number, b.entry_date.strftime("%d/%m/%Y"), b.direction, b.cnpj, b.item, b.cfop,
                    b.ncm, br(b.amount), br(b.bc), br(b.icms), br(b.pis), br(b.cofins), b.cst_pis])

    return DemoDataset(
        tenant_name=tenant_name, cnpj_roots=[root], xml_zip=zbuf.getvalue(),
        book_csv=cbuf.getvalue().encode("utf-8-sig"), ledger_xlsx=buf.getvalue(), ledger_accounts=accounts,
        truth=truth, stats={"documents": len(docs), "inbound": len(inbound), "outbound": len(outbound),
                            "book_lines": len(book)},
    )


def _to_xml(d: Doc) -> str:
    dets = []
    for it in d.items:
        ibs = ""
        if it.ibs_cbs:
            base, vibs, vcbs = it.ibs_cbs
            ibs = (f"<IBSCBS><CST>000</CST><cClassTrib>000001</cClassTrib><gIBSCBS><vBC>{base:.2f}</vBC>"
                   f"<gIBSUF><pIBSUF>0.1000</pIBSUF><vIBSUF>{vibs:.2f}</vIBSUF></gIBSUF>"
                   f"<gIBSMun><pIBSMun>0.0000</pIBSMun><vIBSMun>0.00</vIBSMun></gIBSMun><vIBS>{vibs:.2f}</vIBS>"
                   f"<gCBS><pCBS>0.9000</pCBS><vCBS>{vcbs:.2f}</vCBS></gCBS></gIBSCBS></IBSCBS>")
        desc = f"<vDesc>{it.vdesc:.2f}</vDesc>" if it.vdesc else ""
        dets.append(
            f'<det nItem="{it.n}"><prod><cProd>{it.product.code}</cProd><cEAN>SEM GTIN</cEAN>'
            f"<xProd>{escape(it.product.description)}</xProd><NCM>{it.product.ncm}</NCM><CFOP>{it.cfop}</CFOP>"
            f"<uCom>UN</uCom><qCom>{it.qty:.4f}</qCom><vUnCom>{(it.vprod / it.qty):.10f}</vUnCom>"
            f"<vProd>{it.vprod:.2f}</vProd>{desc}<indTot>1</indTot></prod><imposto>"
            f"<ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>3</modBC><vBC>{it.vbc:.2f}</vBC>"
            f"<pICMS>{it.rate:.4f}</pICMS><vICMS>{it.vicms:.2f}</vICMS></ICMS00></ICMS>"
            f"<PIS><PISAliq><CST>01</CST><vBC>{it.vbc:.2f}</vBC><pPIS>1.6500</pPIS><vPIS>{it.vpis:.2f}</vPIS></PISAliq></PIS>"
            f"<COFINS><COFINSAliq><CST>01</CST><vBC>{it.vbc:.2f}</vBC><pCOFINS>7.6000</pCOFINS>"
            f"<vCOFINS>{it.vcofins:.2f}</vCOFINS></COFINSAliq></COFINS>{ibs}</imposto></det>")
    vprod = sum((i.vprod for i in d.items), D(0))
    vdesc = sum((i.vdesc for i in d.items), D(0))
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><nfeProc xmlns="{NS}" versao="4.00"><NFe xmlns="{NS}">'
        f'<infNFe Id="NFe{d.key}" versao="4.00"><ide><cUF>{d.key[:2]}</cUF><natOp>VENDA</natOp><mod>55</mod>'
        f"<serie>1</serie><nNF>{d.number}</nNF><dhEmi>{d.issue.isoformat()}T10:00:00-03:00</dhEmi>"
        f"<tpNF>{d.tp_nf}</tpNF></ide>"
        f"<emit><CNPJ>{d.issuer_cnpj}</CNPJ><xNome>{escape(d.issuer_name)}</xNome><enderEmit><UF>{d.issuer_uf}</UF></enderEmit></emit>"
        f"<dest><CNPJ>{d.dest_cnpj}</CNPJ><enderDest><UF>{d.dest_uf}</UF></enderDest></dest>"
        + "".join(dets) +
        f"<total><ICMSTot><vBC>{sum((i.vbc for i in d.items), D(0)):.2f}</vBC><vICMS>{d.vicms:.2f}</vICMS>"
        f"<vProd>{vprod:.2f}</vProd><vDesc>{vdesc:.2f}</vDesc><vNF>{d.vnf:.2f}</vNF></ICMSTot></total>"
        f"</infNFe></NFe><protNFe versao=\"4.00\"><infProt><chNFe>{d.key}</chNFe><cStat>{d.cstat}</cStat>"
        f"</infProt></protNFe></nfeProc>"
    )
