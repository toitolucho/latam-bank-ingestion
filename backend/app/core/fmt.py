"""Formato de numeros y fechas para es/pt (punto de miles, coma decimal)."""
from __future__ import annotations

from datetime import date, datetime

MONTHS = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"],
    "pt": ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
           "outubro", "novembro", "dezembro"],
}


def fmt_number(x: float, decimals: int = 0) -> str:
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def fmt_money(x: float, ccy: str = "", decimals: int = 2) -> str:
    return f"{fmt_number(x, decimals)} {ccy}".strip()


def fmt_pct(x: float) -> str:
    return f"{fmt_number(x, 1)}%"


def fmt_date(d: date | datetime) -> str:
    return d.strftime("%d/%m/%Y")


def fmt_month_year(d: date | datetime, lang: str) -> str:
    de = "de" if lang in ("es", "pt") else ""
    return f"{MONTHS[lang][d.month - 1]} {de} {d.year}"
