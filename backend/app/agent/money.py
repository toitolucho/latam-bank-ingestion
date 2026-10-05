"""Monedas en el texto del cliente: deteccion y conversion. Todo en codigo; el LLM no convierte ni elige tasas.

Reglas:
- "dolares", "USD", "US$"            -> USD
- "pesos mexicanos/colombianos/argentinos", "MXN", "COP", "ARS" -> esa moneda
- "pesos" a secas o "$"               -> la moneda local del cliente (las tres monedas locales son pesos)
- reales, euros u otras               -> no soportadas: se avisa en lugar de adivinar o inventar una tasa
La conversion usa la tasa de referencia del dataset a su fecha de corte; no es una cotizacion en vivo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.agent.language import norm
from app.data.repository import CustomerRepository, FxQuote

SUPPORTED = ("USD", "MXN", "COP", "ARS")

_EXPLICIT = [
    (re.compile(r"\busd\b|\bus\$|\bu\$s\b|\bdolar(?:es)?\b|\bdollars?\b"), "USD"),
    (re.compile(r"\bmxn\b|\bmx\$|\bpesos? mexican"), "MXN"),
    (re.compile(r"\bcop\b|\bpesos? colombian"), "COP"),
    (re.compile(r"\bars\b|\bar\$|\bpesos? argentin"), "ARS"),
]
_UNSUPPORTED = [
    (re.compile(r"\bbrl\b|\br\$|\breais\b|\breal brasileiro\b"), "BRL"),
    (re.compile(r"\beur\b|\beuros?\b"), "EUR"),
]
_GENERIC_PESO = re.compile(r"\bpesos?\b|(?<![a-z])\$")


@dataclass(frozen=True)
class CurrencyMention:
    code: str | None          # moneda explicita (USD, MXN, COP, ARS) o None
    unsupported: str | None   # moneda reconocida pero sin tasa (BRL, EUR)
    generic_peso: bool        # "pesos" o "$" sin pais: se interpreta como la moneda local


def detect_currency(text: str) -> CurrencyMention:
    t = norm(text)
    for pat, code in _EXPLICIT:
        if pat.search(t):
            return CurrencyMention(code, None, False)
    for pat, code in _UNSUPPORTED:
        if pat.search(t):
            return CurrencyMention(None, code, False)
    return CurrencyMention(None, None, bool(_GENERIC_PESO.search(t)))


@dataclass(frozen=True)
class Conversion:
    amount_src: float
    src: str
    amount_dst: float
    dst: str
    quote: FxQuote

    @property
    def rate_text(self) -> str:
        """'1 USD = 17,30 MXN' (siempre con la tasa >= 1 para que se lea bien)."""
        from app.core.fmt import fmt_number

        r = self.quote.rate
        if r >= 1:
            return f"1 {self.src} = {fmt_number(r, 2)} {self.dst}"
        return f"1 {self.dst} = {fmt_number(1 / r, 2)} {self.src}"


def convert(repo: CustomerRepository, amount: float, src: str, dst: str) -> Conversion | None:
    """Convierte `amount` de src a dst con la tasa de referencia; None si no hay tasa disponible."""
    q = repo.fx_rate(src, dst)
    if q is None:
        return None
    return Conversion(amount, src, amount * q.rate, dst, q)


def resolve(mention: CurrencyMention, local: str) -> str | None:
    """Moneda en la que habla el cliente: explicita, o la local si dijo 'pesos'/'$'; None si no dijo ninguna."""
    if mention.code:
        return mention.code
    if mention.generic_peso:
        return local
    return None
