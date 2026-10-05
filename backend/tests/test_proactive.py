"""Oferta proactiva de credito: consentimiento, preaprobacion y momento. Y que el camino reactivo no depende de ella."""
from __future__ import annotations

import pytest

from tests.conftest import customers_by_offer_profile, login


@pytest.fixture()
def groups(state):
    g = customers_by_offer_profile(state)
    assert g["consent_pre"] and g["noconsent_pre"] and g["consent_notpre"], {k: len(v) for k, v in g.items()}
    return g


def say(client, sid, h, text):
    r = client.post(f"/v1/sessions/{sid}/messages", json={"message": text}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def start(client, state, groups, key, language="es", i=0):
    c = groups[key][i]
    sid, h = login(client, state, c["doc"], language)
    return sid, h, c


# ---------------------------------------------------------------- cuando SI se ofrece

@pytest.mark.parametrize("closing", ["gracias", "eso es todo", "adiós"])
def test_offer_is_made_when_the_conversation_closes(client, state, groups, closing):
    sid, h, _ = start(client, state, groups, "consent_pre")
    r = say(client, sid, h, closing)
    assert r["proactive_offer"] is True and r["awaiting"] == "offer_interest"
    assert "simulación" in r["reply"] and "preaprobación" in r["reply"] and r["suggested_replies"] == ["Sí", "No"]
    assert any(a["type"] == "proactive_offer_made" and a["basis"] == "bank_data_only"
               for a in state.store.get(sid).actions)


def test_no_offer_after_handing_off_another_topic(client, state, groups):
    """Antes se ofrecia credito justo despues de derivar un tema ajeno. Ahora el cliente vino por otra cosa: se atiende eso."""
    sid, h, _ = start(client, state, groups, "consent_pre")
    r1 = say(client, sid, h, "quiero consultar el horario de la sucursal")
    assert r1["intent"] == "other_topic" and r1["awaiting"] == "confirm_handoff" and not r1["proactive_offer"]
    r2 = say(client, sid, h, "sí")
    assert r2["handoff_ticket"] and r2["proactive_offer"] is False
    assert say(client, sid, h, "gracias")["proactive_offer"] is False      # tampoco al despedirse: la conversacion fue de soporte


def test_no_offer_after_a_declined_handoff_on_a_light_topic(client, state, groups):
    sid, h, _ = start(client, state, groups, "consent_pre")
    say(client, sid, h, "necesito el saldo de mi cuenta")
    r = say(client, sid, h, "no")
    assert r["proactive_offer"] is False and "otro monto" not in r["reply"]      # y no habla de creditos: no era el tema


def test_credit_offer_is_still_possible_when_the_customer_asks_for_credit_after_a_support_topic(client, state, groups):
    sid, h, c = start(client, state, groups, "consent_pre")
    say(client, sid, h, "necesito el saldo de mi cuenta")
    say(client, sid, h, "no")
    r = say(client, sid, h, "¿qué tasas tienen para mí?")                  # la oferta reactiva no depende de nada de esto
    assert r["outcome"] == "offers"


def test_no_offer_while_a_recent_or_critical_case_is_open(client, state, groups):
    """Un caso critico abierto o uno abierto en los ultimos 180 dias frena la oferta por iniciativa del banco."""
    from app.agent.context import build_context
    sid, h, _ = start(client, state, groups, "consent_pre")
    recent = {"case_source": "complaint", "priority": "Low", "days_open": 20}
    state.store.get(sid).slots["context"] = build_context([recent], [])
    assert say(client, sid, h, "gracias")["proactive_offer"] is False
    sid2, h2, _ = start(client, state, groups, "consent_pre", i=0)
    old = {"case_source": "complaint", "priority": "Low", "days_open": 900}
    state.store.get(sid2).slots["context"] = build_context([old], [])       # abierto desde hace anos: no frena
    assert say(client, sid2, h2, "gracias")["proactive_offer"] is True
    sid3, h3, _ = start(client, state, groups, "consent_pre", i=0)
    critical_old = {"case_source": "complaint", "priority": "Critical", "days_open": 900}
    state.store.get(sid3).slots["context"] = build_context([critical_old], [])   # critico: frena aunque sea viejo
    assert say(client, sid3, h3, "gracias")["proactive_offer"] is False


def test_accepting_the_offer_leads_into_the_normal_eligibility_flow(client, state, groups):
    sid, h, c = start(client, state, groups, "consent_pre")
    say(client, sid, h, "gracias")
    r = say(client, sid, h, "sí")
    assert r["awaiting"] == "amount"
    r2 = say(client, sid, h, str(int(c["income"] * 0.2)))
    assert r2["intent"] == "credit_eligibility" and r2["outcome"] in ("eligible", "declined")


def test_declining_the_offer_means_it_is_not_repeated(client, state, groups):
    sid, h, _ = start(client, state, groups, "consent_pre")
    say(client, sid, h, "gracias")
    r = say(client, sid, h, "no")
    assert "no se lo volveré a proponer" in r["reply"]
    assert say(client, sid, h, "gracias")["proactive_offer"] is False


def test_offer_is_made_only_once_per_session(client, state, groups):
    sid, h, _ = start(client, state, groups, "consent_pre")
    assert say(client, sid, h, "gracias")["proactive_offer"] is True
    assert say(client, sid, h, "gracias de nuevo")["proactive_offer"] is False


def test_offer_in_portuguese(client, state, groups):
    sid, h, _ = start(client, state, groups, "consent_pre", language="pt")
    r = say(client, sid, h, "obrigado, isso é tudo")
    assert r["proactive_offer"] is True and "pré-aprovação" in r["reply"] and r["language"] == "pt"


def test_offer_shows_up_in_the_handoff_summary_for_the_agent(client, state, groups):
    sid, h, _ = start(client, state, groups, "consent_pre")
    say(client, sid, h, "gracias")
    r = say(client, sid, h, "quiero hablar con un asesor")
    summary = client.get(f"/v1/sessions/{sid}/handoff", headers=h).json()
    assert r["handoff_ticket"]
    assert any(a["type"] == "proactive_offer_made" for a in summary["actions_taken"])
    assert any(f["type"] == "proactive_offer" for f in summary["verified_facts"])


# ---------------------------------------------------------------- cuando NO se ofrece

def test_no_offer_without_marketing_consent(client, state, groups):
    sid, h, _ = start(client, state, groups, "noconsent_pre")
    assert say(client, sid, h, "gracias")["proactive_offer"] is False
    assert say(client, sid, h, "eso es todo")["proactive_offer"] is False


def test_reactive_request_ignores_marketing_consent(client, state, groups):
    """Quien pide un credito se evalua aunque NO acepte marketing: el consentimiento solo gobierna lo proactivo."""
    sid, h, c = start(client, state, groups, "noconsent_pre")
    r = say(client, sid, h, f"quiero un préstamo de {int(c['income'] * 0.2)} a 24 meses")
    assert r["intent"] == "credit_eligibility" and r["outcome"] in ("eligible", "declined")
    assert r["proactive_offer"] is False
    r2 = say(client, sid, h, "¿qué tasas tienen para mí?")
    assert r2["outcome"] == "offers"                # la consulta de tasas tambien funciona sin consentimiento


def test_no_offer_when_not_preapproved_on_bank_data(client, state, groups):
    sid, h, _ = start(client, state, groups, "consent_notpre")
    assert say(client, sid, h, "gracias")["proactive_offer"] is False


def test_declared_income_in_the_chat_never_creates_a_proactive_offer(client, state, groups):
    sid, h, c = start(client, state, groups, "consent_notpre")
    say(client, sid, h, "gano 9000000 al mes")      # dato no verificado
    assert say(client, sid, h, "gracias")["proactive_offer"] is False


@pytest.mark.parametrize("msg", [
    "esto es pésimo, estoy muy molesto, gracias",
    "no reconozco un cargo en mi tarjeta, gracias",
    "quiero hacer un reclamo",
])
def test_no_offer_in_a_bad_moment(client, state, groups, msg):
    sid, h, _ = start(client, state, groups, "consent_pre")
    say(client, sid, h, msg)
    assert say(client, sid, h, "gracias")["proactive_offer"] is False      # y se mantiene toda la sesion


def test_sensitive_topic_handed_off_gets_no_offer(client, state, groups):
    sid, h, _ = start(client, state, groups, "consent_pre")
    r1 = say(client, sid, h, "creo que fue un fraude en mi cuenta")
    assert r1["awaiting"] == "confirm_handoff"
    r2 = say(client, sid, h, "sí")
    assert r2["handoff_ticket"] and r2["proactive_offer"] is False


def test_no_offer_after_a_declined_credit_evaluation(client, state, groups):
    sid, h, c = start(client, state, groups, "consent_pre")
    r = say(client, sid, h, f"necesito un préstamo de {int(c['income'] * 8)} a 36 meses")
    assert r["outcome"] == "declined"
    assert say(client, sid, h, "gracias")["proactive_offer"] is False


def test_no_offer_when_the_customer_asked_for_a_human(client, state, groups):
    sid, h, _ = start(client, state, groups, "consent_pre")
    r = say(client, sid, h, "quiero hablar con un asesor")
    assert r["handoff_ticket"] and r["proactive_offer"] is False


def test_unrelated_chatter_gets_no_offer(client, state, groups):
    sid, h, _ = start(client, state, groups, "consent_pre")
    assert say(client, sid, h, "asdf qwer")["proactive_offer"] is False
