"""La evidencia que ve la interfaz refleja lo que el agente hizo de verdad: sin herramientas no hay evidencia ni sellos."""
from __future__ import annotations

import pytest

from tests.conftest import correct_answers, customers_by_offer_profile, hdr, login, open_session, pick_customers


def say(client, sid, h, text, language=None):
    body = {"message": text, **({"language": language} if language else {})}
    r = client.post(f"/v1/sessions/{sid}/messages", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def steps(r) -> list[str]:
    return [s["id"] for s in r["evidence"]["steps"]]


def codes(r) -> dict[str, str]:
    return {v["code"]: v["status"] for v in r["evidence"]["verification"]}


@pytest.fixture()
def eligible(state):
    ok, _ = pick_customers(state)
    r = ok.iloc[0]
    return r.document_number, float(r.monthly_income)


def test_authentication_returns_only_basic_customer_data(client, state, eligible):
    new = open_session(client, eligible[0]).json()
    sid = new["session_id"]
    v = client.post(f"/v1/sessions/{sid}/verify", json={"answers": correct_answers(state, sid)}, headers=hdr(new["token"])).json()
    s = state.store.get(sid)
    assert v["customer"]["customer_id"] == s.customer_id and v["customer"]["first_name"] == s.first_name
    assert set(v["customer"]) == {"customer_id", "first_name", "country", "segment", "status"}   # sin documento ni finanzas


def test_a_greeting_uses_no_tools_so_it_has_no_evidence(client, state, eligible):
    sid, h = login(client, state, eligible[0])
    r = say(client, sid, h, "hola")
    assert r["evidence"] is None


def test_eligibility_evidence_shows_the_policy_run_and_the_profile_it_read(client, state, eligible):
    doc, income = eligible
    sid, h = login(client, state, doc)
    r = say(client, sid, h, f"quiero un préstamo de {int(income * 0.3)} a 24 meses")
    ev = r["evidence"]
    assert steps(r) == ["customer_profile", "credit_policy"]
    assert codes(r) == {"customer_data": "verified", "policy": "verified"}
    assert ev["evaluation"]["outcome"] == r["outcome"] and ev["evaluation"]["months"] == 24
    assert ev["evaluation"]["policy_version"] == state.policy["version"]
    assert ev["customer"]["monthly_income"] == income and "credit_score" not in ev["customer"]


def test_declared_income_is_never_labelled_as_verified(client, state, eligible):
    doc, income = eligible
    sid, h = login(client, state, doc)
    say(client, sid, h, f"necesito un préstamo de {int(income * 6)} a 36 meses")
    r = say(client, sid, h, f"ahora gano {int(income * 1.4)} al mes")
    assert r["outcome"] in ("eligible_provisional", "declined", "needs_review")
    assert codes(r)["income_declared"] == "unverified"
    assert r["evidence"]["evaluation"]["income_declared"] is True


def test_offers_show_rates_but_a_declined_proactive_probe_is_not_shown(client, state, eligible):
    sid, h = login(client, state, eligible[0])
    r = say(client, sid, h, "¿qué tasas tienen para mí?")
    assert "offer_rates" in steps(r) and codes(r)["rates"] == "verified"
    assert r["evidence"]["evaluation"] is None            # la sonda de capacidad no se presenta como evaluacion del cliente


def test_the_silent_probe_for_a_proactive_offer_that_is_not_made_leaves_no_evidence(client, state):
    no_consent = customers_by_offer_profile(state)["noconsent_pre"]
    if not no_consent:
        pytest.skip("sin cliente sin consentimiento en el conjunto de datos")
    sid, h = login(client, state, no_consent[0]["doc"])
    r = say(client, sid, h, "gracias, eso es todo")
    assert r["proactive_offer"] is False and r["evidence"] is None


def test_handoff_is_reported_as_a_step_with_its_ticket(client, state, eligible):
    sid, h = login(client, state, eligible[0])
    r = say(client, sid, h, "quiero hablar con un asesor")
    assert steps(r) == ["handoff"] and r["evidence"]["steps"][0]["data"]["ticket"] == r["handoff_ticket"]
    assert r["evidence"]["verification"] == [] and r["evidence"]["customer"] is None


def test_a_failed_tool_leaves_no_verification_seals(client, state, eligible):
    sid, h = login(client, state, eligible[0])
    state.repo._fx.clear()
    r = say(client, sid, h, "quiero un préstamo de 1000 dólares")
    failed = [s for s in r["evidence"]["steps"] if s["status"] == "failed"]
    assert failed and failed[0]["id"] == "fx_rates"
    assert r["evidence"]["verification"] == []            # tras un fallo, la respuesta no se presenta como verificada


def test_the_closing_summary_keeps_the_reservation_about_a_declared_income(client, state, eligible):
    doc, income = eligible
    sid, h = login(client, state, doc)
    say(client, sid, h, f"gano {int(income * 1.2)} al mes")
    r = say(client, sid, h, f"quiero un préstamo de {int(income * 0.2)} a 24 meses")
    assert r["outcome"] == "eligible_provisional"
    bye = say(client, sid, h, "gracias, eso es todo")
    assert bye["summary_ready"] is True
    assert codes(bye)["income_declared"] == "unverified"      # la propuesta se basa en un ingreso sin verificar
