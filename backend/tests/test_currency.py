"""Monedas: el agente identifica la moneda en la que habla el cliente y la convierte; no inventa tasas ni monedas."""
from __future__ import annotations

import pytest

from app.agent import money
from app.core.fmt import fmt_number
from tests.conftest import customers_by_offer_profile, login


@pytest.fixture()
def mx(state):
    """Un cliente con ingreso en MXN, preaprobado."""
    for c in customers_by_offer_profile(state)["consent_pre"]:
        if state.repo.credit_profile(c["cid"])["income_ccy"] == "MXN":
            return c
    pytest.skip("sin cliente MXN en el conjunto de datos")


def usd_mxn(state) -> float:
    return state.repo.fx_rate("USD", "MXN").rate


def say(client, sid, h, text, language=None):
    body = {"message": text, **({"language": language} if language else {})}
    r = client.post(f"/v1/sessions/{sid}/messages", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- deteccion

@pytest.mark.parametrize("text,code,unsupported,generic", [
    ("quiero 5000 dólares", "USD", None, False), ("5.000 USD", "USD", None, False), ("US$ 800", "USD", None, False),
    ("20 mil pesos mexicanos", "MXN", None, False), ("3.000.000 pesos colombianos", "COP", None, False),
    ("500000 ars", "ARS", None, False), ("50.000 pesos", None, None, True), ("$ 4.000", None, None, True),
    ("quero 10 mil reais", None, "BRL", False), ("2000 euros", None, "EUR", False), ("quiero un préstamo", None, None, False),
])
def test_detect_currency(text, code, unsupported, generic):
    m = money.detect_currency(text)
    assert (m.code, m.unsupported, m.generic_peso) == (code, unsupported, generic)


def test_conversion_uses_the_reference_rate_and_triangulates_when_a_pair_is_missing(state):
    rate = state.repo.fx_rate("USD", "MXN").rate                     # la tasa que traiga el conjunto de datos en uso
    c = money.convert(state.repo, 1000, "USD", "MXN")
    assert c and c.amount_dst == pytest.approx(1000 * rate) and c.quote.as_of == "2026-06-17"
    assert c.rate_text == f"1 USD = {fmt_number(rate, 2)} MXN"
    mxn_usd, usd_cop = state.repo.fx_rate("MXN", "USD").rate, state.repo.fx_rate("USD", "COP").rate
    del state.repo._fx[("MXN", "COP")]
    tri = money.convert(state.repo, 1000, "MXN", "COP")          # MXN -> USD -> COP
    assert tri and tri.amount_dst == pytest.approx(1000 * mxn_usd * usd_cop)


def test_conversion_is_none_without_a_rate(state):
    state.repo._fx.clear()
    assert money.convert(state.repo, 10, "USD", "MXN") is None


# ---------------------------------------------------------------- conversaciones

def test_dollars_are_converted_to_the_customer_currency_before_evaluating(client, state, mx):
    sid, h = login(client, state, mx["doc"])
    r = say(client, sid, h, "necesito un préstamo de 1000 dólares a 24 meses")
    s = state.store.get(sid)
    rate = usd_mxn(state)
    assert s.slots["pending_request"]["amount"] == pytest.approx(1000 * rate)   # evaluado en MXN
    assert s.slots["pending_request"]["conv"]["src"] == "USD" and s.slots["spoken_ccy"] == "USD"
    assert fmt_number(rate, 2) in r["reply"] and "USD" in r["reply"] and "MXN" in r["reply"]  # tasa, monto original y convertido
    assert "17/06/2026" in r["reply"]                                              # fecha de la tasa: no es cotizacion en vivo
    assert "≈ 1.000 USD" in r["reply"]                                             # ida y vuelta coherente: 1.000 USD sigue siendo 1.000 USD
    assert r["outcome"] in ("eligible", "declined")


def test_the_amount_in_local_pesos_is_not_converted(client, state, mx):
    sid, h = login(client, state, mx["doc"])
    r = say(client, sid, h, "quiero un préstamo de 20.000 pesos a 24 meses")
    s = state.store.get(sid)
    assert s.slots["pending_request"]["amount"] == 20000.0 and not s.slots["pending_request"]["conv"]
    assert "tasa de referencia" not in r["reply"] and s.slots.get("spoken_ccy") is None


def test_spoken_currency_is_kept_to_show_equivalents_later(client, state, mx):
    sid, h = login(client, state, mx["doc"])
    say(client, sid, h, "necesito un préstamo de 500 dólares")
    r = say(client, sid, h, "¿qué tasas tienen para mí?")
    assert "≈" in r["reply"] and "USD" in r["reply"]                               # el máximo se muestra también en USD


def test_declared_income_in_dollars_is_converted(client, state, mx):
    sid, h = login(client, state, mx["doc"])
    say(client, sid, h, "necesito un préstamo de 500000 pesos")                       # probablemente rechazado por capacidad
    r = say(client, sid, h, "ahora gano 1000 dólares al mes")
    s = state.store.get(sid)
    rate = usd_mxn(state)
    assert s.slots["declared_income"] == pytest.approx(1000 * rate)
    assert s.slots["declared_income_conv"]["src"] == "USD" and fmt_number(rate, 2) in r["reply"]


def test_unsupported_currency_is_declined_instead_of_guessed(client, state, mx):
    sid, h = login(client, state, mx["doc"])
    r = say(client, sid, h, "quiero un préstamo de 5000 euros")
    s = state.store.get(sid)
    assert "EUR" in r["reply"] and "MXN" in r["reply"] and "last_evaluation" not in s.slots   # no se evaluo nada


def test_missing_rate_is_reported_not_invented(client, state, mx):
    sid, h = login(client, state, mx["doc"])
    state.repo._fx.clear()
    r = say(client, sid, h, "quiero un préstamo de 1000 dólares")
    assert "last_evaluation" not in state.store.get(sid).slots and "USD" in r["reply"]


def test_portuguese_conversion_and_unsupported_currency(client, state, mx):
    sid, h = login(client, state, mx["doc"], language="pt")
    r = say(client, sid, h, "preciso de um empréstimo de 1000 dólares em 24 meses")
    assert "Converti" in r["reply"] and fmt_number(usd_mxn(state), 2) in r["reply"]
    r2 = say(client, sid, h, "na verdade quero 8000 reais")
    assert "BRL" in r2["reply"] and r2["language"] == "pt"
