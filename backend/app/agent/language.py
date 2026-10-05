"""Utilidades de idioma en codigo (no en el LLM): deteccion es/pt y lectura de montos con formato local."""
from __future__ import annotations

import re
import unicodedata


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def norm(text: str) -> str:
    return strip_accents(text).lower().strip()


_PT = re.compile(r"\b(quero|preciso|emprestimo|voce|voces|obrigad[oa]|gostaria|ola|oi|nao|meu|minha|salario|ganho|"
                 r"bom dia|boa tarde|boa noite|falar|atendente|cartao|juros|taxa|valor|reais|renda|financiamento|sim)\b")
_ES = re.compile(r"\b(quiero|necesito|prestamo|usted|ustedes|gracias|hola|buenas|buenos|mi|sueldo|gano|tengo|tasa|monto|"
                 r"plata|hablar|agente|ingreso|ingresos|credito|tarjeta|si|dolares|pesos)\b")


def detect_language(text: str) -> str | None:
    """'es' o 'pt' si hay indicios claros; None si es ambiguo (se conserva el idioma de la sesion)."""
    t = norm(text)
    pt, es = len(_PT.findall(t)), len(_ES.findall(t))
    if pt > es:
        return "pt"
    if es > pt:
        return "es"
    return None


_NUM = re.compile(r"(\d[\d.,]*)\s*(mil|k|millones|millon|milhoes|milhao)?\b")
_MULT = {"mil": 1_000, "k": 1_000, "millon": 1_000_000, "millones": 1_000_000, "milhao": 1_000_000,
         "milhoes": 1_000_000}
_MONTHS = re.compile(r"(\d{1,3})\s*(meses|mes|months|anos|ano|años|año)\b")


def _to_float(token: str) -> float | None:
    token = token.strip(".,")
    if not token:
        return None
    if "," in token and "." in token:
        dec = "," if token.rfind(",") > token.rfind(".") else "."
        thou = "." if dec == "," else ","
        token = token.replace(thou, "").replace(dec, ".")
    elif "," in token or "." in token:
        sep = "," if "," in token else "."
        parts = token.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:
            token = "".join(parts)           # separador de miles: 5.000 | 1.250.000
        else:
            token = ".".join(parts)          # decimal: 5,50
    try:
        return float(token)
    except ValueError:
        return None


def parse_months(text: str) -> int | None:
    m = _MONTHS.search(norm(text))
    if not m:
        return None
    n = int(m.group(1))
    return n * 12 if m.group(2).startswith(("an", "ano")) or m.group(2) in ("ano", "anos") else n


def parse_amounts(text: str) -> list[float]:
    """Montos en el texto, interpretando 1.500,50 / 1,500.50 / 5.000 / 5k / 5 mil. Excluye plazos ('36 meses')."""
    t = _MONTHS.sub(" ", norm(text))
    out: list[float] = []
    for num, mult in _NUM.findall(t):
        v = _to_float(num)
        if v is None:
            continue
        out.append(v * _MULT.get(mult, 1))
    return out
