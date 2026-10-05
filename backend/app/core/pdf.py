"""PDF del resumen de la propuesta (fpdf2, solo fuentes base: texto Latin-1, suficiente para es/pt)."""
from __future__ import annotations

from datetime import date

from fpdf import FPDF

TITLES = {
    "es": {"title": "Resumen de su propuesta de crédito", "demo": "Documento de demostración. Datos y política sintéticos.",
           "generated": "Generado el", "customer": "Cliente", "ref": "Seguimiento", "footer": "Versión de política"},
    "pt": {"title": "Resumo da sua proposta de crédito", "demo": "Documento de demonstração. Dados e política sintéticos.",
           "generated": "Gerado em", "customer": "Cliente", "ref": "Acompanhamento", "footer": "Versão da política"},
}
_REPLACE = {"•": "-", "≈": "~", "–": "-", "—": "-", "“": '"', "”": '"', "’": "'", " ": " "}


def _latin1(text: str) -> str:
    for a, b in _REPLACE.items():
        text = text.replace(a, b)
    return text.encode("latin-1", "replace").decode("latin-1")


def render_summary_pdf(*, lang: str, first_name: str, rows: list[tuple[str, str]], notes: list[str],
                       ticket: str | None, policy_version: str) -> bytes:
    t = TITLES[lang]
    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _latin1(t["title"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 5, _latin1(t["demo"]), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _latin1(f"{t['generated']} {date.today().strftime('%d/%m/%Y')}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, _latin1(f"{t['customer']}: {first_name}"), new_x="LMARGIN", new_y="NEXT")
    if ticket:
        pdf.cell(0, 7, _latin1(f"{t['ref']}: {ticket}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for label, value in rows:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(62, 8, _latin1(label), border="B")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 8, _latin1(value), border="B", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 9)
    for n in notes:
        pdf.multi_cell(0, 5, _latin1(n), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    pdf.set_y(-20)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(0, 5, _latin1(f"{t['footer']}: {policy_version}"), align="C")
    return bytes(pdf.output())
