"""Salvaguardas que NO dependen del modelo: se prueban con un LLM falso que se equivoca a proposito (sin red)."""
from __future__ import annotations

from app.agent.nlu import NLUResult
from tests.conftest import customers_by_offer_profile, login


class MisbehavingLLM:
    """Clasifica mal y reescribe con contenido nuevo, como podria hacerlo un modelo real."""

    name = "fake"

    def __init__(self, nlu: NLUResult | None = None, rewrite: str | None = None, fail: bool = False):
        self.nlu, self.rewrite, self.fail, self.compose_calls = nlu, rewrite, fail, []

    def extract(self, message, language_hint, yes_no_pending=False):
        if self.fail:
            raise RuntimeError("red caida")
        return self.nlu or NLUResult(intent="unknown")

    def compose(self, facts, lang, draft):
        self.compose_calls.append(facts["kind"])
        return self.rewrite


def _session(client, state):
    g = customers_by_offer_profile(state)
    return login(client, state, g["consent_pre"][0]["doc"])


def say(client, sid, h, text):
    return client.post(f"/v1/sessions/{sid}/messages", json={"message": text}, headers=h).json()


def test_llm_cannot_trigger_a_handoff_the_customer_did_not_ask_for(client, state):
    sid, h = _session(client, state)
    state.orchestrator.llm = MisbehavingLLM(NLUResult(intent="request_human", sensitive_topic=True))
    r = say(client, sid, h, "no reconozco un cargo en mi cuenta")           # no pidio hablar con nadie
    assert r["handoff_ticket"] is None and r["awaiting"] == "confirm_handoff"   # se pide confirmacion, no se ejecuta
    assert state.queue.list() == []


def test_explicit_human_request_is_still_honored(client, state):
    sid, h = _session(client, state)
    state.orchestrator.llm = MisbehavingLLM(NLUResult(intent="request_human"))
    assert say(client, sid, h, "quiero hablar con un asesor")["handoff_ticket"]


def test_llm_cannot_rewrite_credit_decisions_or_offers(client, state):
    sid, h = _session(client, state)
    llm = MisbehavingLLM(NLUResult(intent="credit_eligibility", amount=1000.0, months=12),
                         rewrite="Su crédito está aprobado sin condiciones, sin verificación.")
    state.orchestrator.llm = llm
    r = say(client, sid, h, "quiero un préstamo de 1000 a 12 meses")
    assert r["outcome"] == "eligible" and "aprobado sin condiciones" not in r["reply"] and "simulación" in r["reply"]
    assert llm.compose_calls == []                                           # ni se le pidio reescribir una decision
    # Con una propuesta ya evaluada, al despedirse llega el RESUMEN de esa propuesta (plantilla), no una oferta nueva
    state.orchestrator.llm = MisbehavingLLM(NLUResult(intent="closing"), rewrite="Hasta pronto.")
    r2 = say(client, sid, h, "gracias, eso es todo")
    assert r2["proactive_offer"] is False and r2["summary_ready"] is True and "Hasta pronto" not in r2["reply"]
    # Sin propuesta previa, la oferta proactiva tampoco la reescribe el modelo
    sid2, h2 = _session(client, state)
    state.orchestrator.llm = MisbehavingLLM(NLUResult(intent="closing"), rewrite="Hasta pronto.")
    r3 = say(client, sid2, h2, "gracias, eso es todo")
    assert r3["proactive_offer"] is True and "preaprobación" in r3["reply"] and "Hasta pronto" not in r3["reply"]


def test_low_risk_messages_may_be_rewritten_but_not_with_foreign_numbers(client, state):
    sid, h = _session(client, state)
    state.orchestrator.llm = MisbehavingLLM(NLUResult(intent="unknown"), rewrite="Disculpe, ¿me lo puede repetir?")
    assert say(client, sid, h, "asdf")["reply"] == "Disculpe, ¿me lo puede repetir?"      # 'unknown' es de bajo riesgo
    sid2, h2 = _session(client, state)
    state.orchestrator.llm = MisbehavingLLM(NLUResult(intent="unknown"), rewrite="Disculpe. Tiene un bono de 5000.")
    assert "5000" not in say(client, sid2, h2, "asdf")["reply"]                            # numero ajeno a los hechos: se descarta


def test_llm_failure_falls_back_to_rules_without_breaking_the_turn(client, state):
    sid, h = _session(client, state)
    state.orchestrator.llm = MisbehavingLLM(fail=True)
    r = say(client, sid, h, "¿qué tasas tienen para mí?")
    assert r["outcome"] == "offers"


def test_rewrite_kinds_can_be_disabled_by_configuration():
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import make_settings
    app = create_app(make_settings(llm_rewrite_kinds="none"))
    assert app.state.ctx.orchestrator.rewrite_kinds == frozenset()
    assert TestClient(app).get("/health").status_code == 200
