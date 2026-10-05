from __future__ import annotations

import pytest

from app.agent.language import detect_language, parse_amounts, parse_months
from app.agent.nlu import MockNLU


@pytest.mark.parametrize("text,expected", [
    ("necesito un préstamo de 5.000", [5000.0]),
    ("quiero 5,000", [5000.0]),
    ("quero 5.000,50 reais", [5000.5]),
    ("1,500.75", [1500.75]),
    ("1.250.000", [1250000.0]),
    ("5k", [5000.0]),
    ("5 mil", [5000.0]),
    ("2 millones", [2000000.0]),
    ("30 mil a 24 meses", [30000.0]),          # el plazo no es un monto
    ("gano 3200 al mes", [3200.0]),
])
def test_parse_amounts_locale_formats(text, expected):
    assert parse_amounts(text) == expected


def test_parse_months():
    assert parse_months("a 24 meses") == 24
    assert parse_months("em 3 anos") == 36
    assert parse_months("sin plazo") is None


@pytest.mark.parametrize("text,lang", [
    ("Hola, quiero un préstamo", "es"), ("Olá, quero um empréstimo", "pt"),
    ("preciso de um financiamento, obrigado", "pt"), ("necesito hablar con un agente", "es"),
])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


@pytest.mark.parametrize("text,intent", [
    ("Hola", "greeting"), ("quiero un préstamo de 8000 a 24 meses", "credit_eligibility"),
    ("quero um empréstimo de 8.000", "credit_eligibility"), ("¿qué tasas tienen?", "credit_offers"),
    ("ahora gano 4500 al mes", "update_income"), ("quero falar com um atendente", "request_human"),
    ("quiero hablar con un asesor", "request_human"), ("sí", "confirm_yes"), ("não", "confirm_no"),
    ("blablabla", "unknown"),
])
def test_mock_nlu_intents(text, intent):
    assert MockNLU().extract(text).intent == intent


@pytest.mark.parametrize("text", ["necesito que me atienda una persona", "quero ser atendido por um humano",
                                  "pásame con un asesor, por favor", "me comunica con un ejecutivo",
                                  "quero falar com uma pessoa de verdade"])
def test_explicit_human_requests_are_recognized(text):
    from app.agent.nlu import HUMAN_REQUEST
    from app.agent.language import norm
    assert HUMAN_REQUEST.search(norm(text))


@pytest.mark.parametrize("text", ["una persona usó mi tarjeta sin permiso", "la persona que me atendió fue amable",
                                  "alguien usó mi tarjeta sin permiso"])
def test_a_bare_mention_of_person_is_not_a_human_request(text):
    from app.agent.nlu import HUMAN_REQUEST
    from app.agent.language import norm
    assert not HUMAN_REQUEST.search(norm(text))
