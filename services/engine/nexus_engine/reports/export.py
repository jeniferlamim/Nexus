"""Findings report export (XLSX). Every row carries rule/version, methodology, confidence and status,
so the document stands on its own in front of an auditor."""
from __future__ import annotations

import io
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from ..persistence.db import FindingRow, Tenant

KIND_LABEL = {"ESTIMATE": "Estimativa", "ALERT": "Alerta", "VALIDATED": "Conclusão validada"}
AMOUNT_LABEL = {"RECOVERABLE_ESTIMATE": "Recuperação potencial (estimada)", "EXPOSURE_ESTIMATE": "Exposição (estimada)",
                "DIVERGENCE_VALUE": "Divergência de dados", "NONE": "—"}


def findings_xlsx(tenant: Tenant, rows: list[FindingRow], generated_by: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ocorrências"
    ws.append([f"NEXUS — Relatório de ocorrências · {tenant.legal_name}"])
    ws.append([f"Gerado em {datetime.now(timezone.utc):%d/%m/%Y %H:%M} UTC por {generated_by}. "
               "Valores estimados NÃO constituem crédito garantido nem conclusão fiscal; dependem de validação "
               "por profissional habilitado. Nenhuma compensação ou retificação é executada pela plataforma."])
    ws.append([])
    header = ["ID", "Regra", "Versão", "Categoria", "Tipo", "Severidade", "Status", "Título", "Tributo", "Período",
              "Natureza do valor", "Valor estimado (R$)", "Valor validado (R$)", "Confiança", "Chave NF-e",
              "Participante", "Metodologia", "Base legal", "Evidências"]
    ws.append(header)
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0B1F3A")
    for r in rows:
        ws.append([
            f"NX-{r.seq:05d}", r.rule_code, r.rule_version, r.category, KIND_LABEL.get(r.kind, r.kind), r.severity,
            r.status, r.title, r.tax or "", r.period or "", AMOUNT_LABEL.get(r.amount_type, r.amount_type),
            float(r.estimated_amount), float(r.validated_amount) if r.validated_amount is not None else None,
            round(r.confidence, 2), r.access_key or "", f"{r.counterparty_name or ''} {r.counterparty_cnpj or ''}".strip(),
            r.methodology, r.legal_basis,
            " | ".join(f"{e.source} [{e.locator}] {e.field}: {e.observed}" + (f" (esperado {e.expected})" if e.expected else "")
                       for e in r.evidence[:15]),
        ])
    for col, width in zip("ABCDEFGHIJKLMNOPQRS", [10, 11, 7, 18, 16, 10, 16, 60, 10, 9, 28, 16, 16, 9, 46, 40, 60, 50, 90]):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=5):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=c.column_letter in "HQRS")
        row[11].number_format = row[12].number_format = '#,##0.00'
    ws.freeze_panes = "A5"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
