"""Soporte conversacional: el agente atiende primero lo que el cliente trae (productos, casos, incidentes, otros temas),
anota lo que cuenta y arma el resumen para el asesor. El credito solo aparece si lo pide o si es el momento.

Usa el fixture del equipo (inventado y determinista), no el snapshot del organizador."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.nlu import MockNLU, NLUResult
from app.agent.orchestrator import safe_text
from app.auth import kba
from app.config import BASE_DIR
from app.main import create_app
from tests.conftest import correct_answers, hdr, make_settings, open_session
from tests.test_llm_guards import MisbehavingLLM

FIXTURE = BASE_DIR / "data" / "fixture"
CREDIT_WORDS = ("crédito", "préstamo", "preaprob", "empréstimo", "pré-aprov")


@pytest.fixture()
def app(tmp_path):
    return create_app(make_settings(outbox_dir=tmp_path / "outbox", data_dir=FIXTURE))


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def state(app):
    return app.state.ctx


def doc_of(state, cid: str) -> str:
    return str(state.repo._customers.set_index("customer_id").loc[cid, "document_number"])


def start(client, state, cid: str, language: str = "es"):
    """Autentica y devuelve (session_id, headers, respuesta de verificacion)."""
    r = open_session(client, doc_of(state, cid), language)
    assert r.status_code == 201, r.text
    sid, token = r.json()["session_id"], r.json()["token"]
    v = client.post(f"/v1/sessions/{sid}/verify", json={"answers": correct_answers(state, sid)}, headers=hdr(token))
    assert v.json()["status"] == "authenticated", v.text
    return sid, hdr(token), v.json()


def say(client, sid, h, text):
    r = client.post(f"/v1/sessions/{sid}/messages", json={"message": text}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def summary_of(client, sid, h):
    return client.get(f"/v1/sessions/{sid}/handoff", headers=h).json()


def customer_with(state, product_type: str) -> str:
    """Un cliente que puede autenticarse y tiene ese tipo de producto."""
    for r in state.repo._customers.itertuples():
        cust = state.repo.find_by_document(r.document_number)
        if (any(p["product_type"] == product_type for p in state.repo.products(r.customer_id))
                and kba.build_challenge(state.repo, cust, n=3, lang="es", as_of=state.settings.as_of_date)):
            return r.customer_id
    pytest.skip(f"sin cliente con {product_type}")


# ---------------------------------------------------------------- NLU: intenciones nuevas
@pytest.mark.parametrize("text,intent,sensitive", [
    ("¿cómo va mi reclamo?", "case_status", True),
    ("quiero saber el estado de mi caso", "case_status", False),
    ("meu protocolo ainda está pendente?", "case_status", False),
    ("necesito el saldo de mi cuenta", "account_inquiry", False),
    ("¿tengo alguna tarjeta activa?", "account_inquiry", False),
    ("quanto tenho de saldo na minha conta?", "account_inquiry", False),
    ("quiero el saldo de mi tarjeta de crédito", "account_inquiry", False),      # no es pedir un credito
    ("quiero una tarjeta de crédito", "credit_eligibility", False),              # esto si
    ("quiero hacer un reclamo por un cobro", "other_topic", True),               # reclamo NUEVO: incidente, no estado de un caso
    ("no reconozco un cargo en mi tarjeta", "other_topic", True),
    ("¿a qué hora abren en la sucursal?", "other_topic", False),
])
def test_new_intents_are_recognized_by_the_rules_extractor(text, intent, sensitive):
    r = MockNLU().extract(text)
    assert (r.intent, r.sensitive_topic) == (intent, sensitive)


# ---------------------------------------------------------------- bienvenida: primero lo pendiente
def test_welcome_opens_with_a_recent_open_case(client, state):
    sid, h, v = start(client, state, "FXC-011")                  # reclamo High en proceso, abierto hace 12 dias
    g = v["greeting"]
    assert "asistente virtual" in g and "reclamo sobre comisiones y cargos" in g and "17/06/2026" not in g
    assert v["suggested_replies"][0] == "Sí, cuénteme"
    assert state.store.get(sid).slots["awaiting"] == "case_intro"
    r = say(client, sid, h, "sí, cuénteme")
    assert r["awaiting"] == "confirm_handoff" and "en proceso" in r["reply"] and "05/06/2026" in r["reply"]
    assert not any(w in r["reply"].lower() for w in CREDIT_WORDS)


def test_welcome_phrasing_is_grammatical_for_a_call_and_for_a_complaint(client, state):
    _, _, call = start(client, state, "FXC-003")                 # llamada sin resolver hace 20 dias
    g = call["greeting"]
    assert "que quedó sin resolver y quiero ayudarle" in g and "que sigue pendiente" not in g
    _, _, complaint = start(client, state, "FXC-011")            # reclamo
    assert "desde el 05/06/2026 que sigue pendiente y quiero ayudarle" in complaint["greeting"]


def test_welcome_can_be_skipped_without_pushing_anything(client, state):
    sid, h, _ = start(client, state, "FXC-011")
    r = say(client, sid, h, "no, gracias")
    assert r["intent"] == "confirm_no" and not r["proactive_offer"] and "¿En qué le ayudo?" in r["reply"]


def test_a_case_open_for_years_is_not_mentioned_in_the_welcome_but_is_known_when_asked(client, state):
    sid, h, v = start(client, state, "FXC-005")                  # reclamo abierto desde hace 400 dias
    assert "reclamo" not in v["greeting"] and v["suggested_replies"][0] != "Sí, cuénteme"
    r = say(client, sid, h, "¿cómo va mi reclamo?")
    assert "reclamo sobre el servicio" in r["reply"] and "abierto" in r["reply"]


def test_customer_without_cases_gets_the_plain_welcome(client, state):
    _, _, v = start(client, state, "FXC-001")
    assert "asistente virtual" in v["greeting"] and "pendiente" not in v["greeting"]


def test_case_status_for_a_customer_with_nothing_open(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    r = say(client, sid, h, "¿cómo va mi reclamo?")
    assert "No veo reclamos ni casos abiertos" in r["reply"] and r["awaiting"] == "confirm_handoff"


def test_case_status_never_discloses_amounts_or_resolution(client, state):
    sid, h, _ = start(client, state, "FXC-002")                  # reclamo critico escalado + una llamada sin resolver
    r = say(client, sid, h, "¿cómo va mi reclamo?")
    assert "escalado" in r["reply"] and "Además, tiene otros casos abiertos" in r["reply"]
    assert "monto" not in r["reply"].lower() and "reclam" in r["reply"]


# ---------------------------------------------------------------- productos: solo existencia
def test_asking_for_a_product_confirms_it_exists_and_hands_the_detail_to_an_advisor(client, state):
    cid = customer_with(state, "Tarjeta Crédito")
    sid, h, _ = start(client, state, cid)
    r = say(client, sid, h, "¿tengo una tarjeta de crédito?")
    last4 = [p["last4"] for p in state.repo.products(cid) if p["product_type"] == "Tarjeta Crédito"][0]
    assert r["intent"] == "account_inquiry" and r["awaiting"] == "confirm_handoff"
    assert f"Sí, veo una tarjeta de crédito (terminación {last4})" in r["reply"] and "asesor" in r["reply"]


def test_a_missing_product_is_reported_honestly(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    r = say(client, sid, h, "¿tengo un crédito hipotecario?")     # el fixture no tiene hipotecas
    assert "No veo un préstamo hipotecario activo" in r["reply"]


def test_balance_questions_never_get_a_balance(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    r = say(client, sid, h, "necesito el saldo de mi cuenta")
    assert "el detalle de saldos y movimientos lo revisa un asesor" in r["reply"]
    # lo unico numerico que puede aparecer son las terminaciones de producto (4 digitos), nunca una cifra de saldo
    import re
    assert all(len(n) == 4 for n in re.findall(r"\d+", r["reply"]))


def test_product_answer_in_portuguese(client, state):
    sid, h, _ = start(client, state, "FXC-001", language="pt")
    r = say(client, sid, h, "quanto tenho de saldo na minha conta?")
    assert r["language"] == "pt" and r["awaiting"] == "confirm_handoff" and "consultor" in r["reply"] and "final" in r["reply"]


# ---------------------------------------------------------------- notas, incidentes y derivacion con contexto
def test_what_the_customer_tells_is_noted_and_reaches_the_advisor_as_declared(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    say(client, sid, h, "necesito el saldo de mi cuenta")
    r = say(client, sid, h, "el 12 de mayo retiré 500 pesos en un cajero y no me los descontaron bien")
    assert r["awaiting"] == "confirm_handoff" and "anotado" in r["reply"].lower()
    r2 = say(client, sid, h, "sí")
    assert r2["handoff_ticket"] and not r2["proactive_offer"]
    s = summary_of(client, sid, h)
    assert s["reason"] == "ACCOUNT_DETAIL" and s["topic"]["primary"] == "account_inquiry"
    assert [n["declared_by_customer"] for n in s["case_notes"]] == [True, True] and not any(n["verified"] for n in s["case_notes"])
    assert "retiré 500 pesos" in s["case_notes"][1]["text"] and "amounts" not in s["case_notes"][1]
    assert any(a["type"] == "customer_detail_noted" and a["verified"] is False for a in s["actions_taken"])
    assert "cajero" in s["narrative"] and "sin verificar" in s["narrative"]


def test_long_numbers_are_never_stored(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    say(client, sid, h, "necesito el saldo de mi cuenta")
    say(client, sid, h, "mi tarjeta es 4111 1111 1111 1111 y mi correo es ana@example.com")
    say(client, sid, h, "sí")
    s = summary_of(client, sid, h)
    blob = json.dumps(s, ensure_ascii=False).replace(s["ticket_id"], "")     # el id del ticket es hexadecimal aleatorio
    assert "4111" not in blob and "ana@example.com" not in blob and "[número omitido]" in blob and "[correo omitido]" in blob


def test_incident_is_acknowledged_with_empathy_and_goes_up_as_urgent(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    r = say(client, sid, h, "no reconozco un cargo de 300 dólares en mi tarjeta")
    assert r["awaiting"] == "confirm_handoff" and ("Lamento" in r["reply"] or "Siento" in r["reply"])
    assert not any(w in r["reply"].lower() for w in CREDIT_WORDS) and r["handoff_ticket"] is None
    say(client, sid, h, "sí")
    s = summary_of(client, sid, h)
    assert (s["priority"], s["suggested_route"], s["reason"]) == ("urgent", "fraudes_y_disputas", "INCIDENT")
    assert s["topic"]["primary"] == "incident" and "300 dólares" in s["case_notes"][0]["text"]


def test_a_complaint_without_fraud_signals_is_high_priority_not_a_fraud_emergency(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    say(client, sid, h, "me siguen cobrando una comisión que no entiendo, quiero hacer un reclamo")
    say(client, sid, h, "sí")
    s = summary_of(client, sid, h)
    assert (s["reason"], s["priority"], s["suggested_route"]) == ("INCIDENT", "high", "reclamos_y_quejas")


def test_next_actions_only_mention_waiting_time_when_there_is_an_open_case(client, state):
    sid, h, _ = start(client, state, "FXC-001")                  # sin casos abiertos
    say(client, sid, h, "esto es pésimo, estoy muy molesto, quiero hacer un reclamo")
    say(client, sid, h, "sí")
    s = summary_of(client, sid, h)
    actions = " ".join(s["suggested_next_actions"])
    assert "molestia" in actions and "espera" not in actions and "lleva con su caso" not in actions
    sid2, h2, _ = start(client, state, "FXC-002")                # con casos abiertos
    say(client, sid2, h2, "esto es pésimo, estoy muy molesto, quiero hacer un reclamo")
    say(client, sid2, h2, "sí")
    assert "lleva con su caso abierto" in " ".join(summary_of(client, sid2, h2)["suggested_next_actions"])


def test_an_open_critical_case_makes_any_handoff_urgent(client, state):
    sid, h, _ = start(client, state, "FXC-002")
    say(client, sid, h, "me siguen cobrando una comisión que no entiendo, quiero hacer un reclamo")
    say(client, sid, h, "sí")
    s = summary_of(client, sid, h)
    assert s["priority"] == "urgent" and s["suggested_route"] == "reclamos_y_quejas"      # urgente por el caso, ruta por el tema


def test_other_topics_are_noted_without_rushing_the_customer_or_selling(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    r = say(client, sid, h, "olvidé la clave de mi app")
    assert r["intent"] == "other_topic" and r["awaiting"] == "confirm_handoff" and "anotado" in r["reply"].lower()
    declined = say(client, sid, h, "no")
    assert "otro monto" not in declined["reply"] and not declined["proactive_offer"]


def test_unclear_messages_no_longer_sound_like_a_credit_menu(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    r = say(client, sid, h, "asdf qwer")
    assert "productos" in r["reply"] and "caso" in r["reply"]


def test_asking_for_a_person_midway_keeps_the_topic_for_the_advisor(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    say(client, sid, h, "necesito el saldo de mi cuenta")
    r = say(client, sid, h, "quiero hablar con un asesor")
    assert r["handoff_ticket"]
    s = summary_of(client, sid, h)
    assert s["reason"] == "USER_REQUEST" and s["topic"]["primary"] == "account_inquiry"
    assert s["suggested_route"] == "atencion_de_productos" and "case_notes" in s


# ---------------------------------------------------------------- resumen para el asesor: contexto y prioridad
def test_summary_carries_open_cases_priority_and_route_without_sensitive_fields(client, state):
    sid, h, _ = start(client, state, "FXC-002")                 # critico escalado, SLA incumplido, reincidente
    say(client, sid, h, "esto es pésimo, estoy muy molesto, necesito el saldo de mi cuenta")
    say(client, sid, h, "sí")
    s = summary_of(client, sid, h)
    ctx = s["customer_context"]
    assert ctx["counts"]["open"] == 2 and ctx["open_cases"][0]["priority"] == "Critical" and ctx["flags"]["has_sla_breach"]
    assert s["priority"] == "urgent" and s["sentiment"]["negative_turns"] == 1 and s["sentiment"]["frustration"] == "high"
    assert "Revisar primero el caso abierto" in " ".join(s["suggested_next_actions"])
    assert "2 caso(s) abierto(s)" in s["narrative"] and s["narrative_source"] == "rules"
    blob = json.dumps(s)
    for leaked in ("description", "claimed_amount", "compensation_granted", "resolution", "current_balance", "credit_limit"):
        assert leaked not in blob, leaked


def test_summary_for_a_clean_customer_says_there_is_nothing_open(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    say(client, sid, h, "quiero hablar con un asesor")
    s = summary_of(client, sid, h)
    assert s["customer_context"]["counts"]["open"] == 0 and "No tiene casos abiertos" in s["narrative"] and s["priority"] == "normal"


# ---------------------------------------------------------------- empatia
def test_empathy_opens_the_reply_once_not_on_every_turn(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    r1 = say(client, sid, h, "estoy muy molesto, necesito el saldo de mi cuenta")
    assert r1["reply"].split(".")[0] in ("Entiendo su molestia y lamento los inconvenientes", "Lamento que esté pasando por esto")
    r2 = say(client, sid, h, "esto es pésimo, sigo molesto")
    assert not r2["reply"].startswith(("Entiendo su molestia", "Lamento que esté"))     # recien reconocida: no se repite


# ---------------------------------------------------------------- el credito ya no es lo primero
def test_credit_is_not_pushed_after_support_and_still_available_on_request(client, state):
    sid, h, _ = start(client, state, "FXC-001")                 # preaprobado y con consentimiento: antes se le ofrecia credito
    say(client, sid, h, "olvidé la clave de mi app")
    say(client, sid, h, "sí")
    assert say(client, sid, h, "gracias")["proactive_offer"] is False
    assert say(client, sid, h, "¿qué tasas tienen para mí?")["outcome"] == "offers"


# ---------------------------------------------------------------- salvaguardas del LLM en soporte
@pytest.mark.parametrize("text", [
    "Le aseguro que su caso se resolverá hoy mismo. ¿Lo conecto?", "Garantizamos la devolución del dinero. ¿Lo conecto?",
    "Vamos a resolver esto lo antes posible. ¿Lo conecto?", "Sua reclamação será resolvida, garanto. Conecto?",
])
def test_promises_are_rejected(text):
    assert not safe_text(text, {"fmt": {}, "awaiting": "confirm_handoff"})


def test_a_rewrite_that_drops_the_handoff_question_is_rejected():
    facts = {"fmt": {}, "awaiting": "confirm_handoff"}
    assert not safe_text("Lamento lo ocurrido, ya queda anotado.", facts)
    assert safe_text("Lamento lo ocurrido. ¿Quiere que lo conecte con un asesor?", facts)


def test_support_messages_may_be_rewritten_but_not_with_promises(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    llm = MisbehavingLLM(NLUResult(intent="other_topic"), rewrite="Su caso se resolverá hoy, se lo garantizo. ¿Lo conecto?")
    state.orchestrator.llm = llm
    r = say(client, sid, h, "olvidé la clave de mi app")
    assert "garantizo" not in r["reply"] and llm.compose_calls == ["other_topic"]
    state.orchestrator.llm = MisbehavingLLM(NLUResult(intent="other_topic"), rewrite="Con gusto lo veo con usted. ¿Lo conecto ahora con un asesor?")
    sid2, h2, _ = start(client, state, "FXC-001")
    assert say(client, sid2, h2, "olvidé la clave de mi app")["reply"].startswith("Con gusto lo veo")


def test_product_and_case_facts_are_never_rewritten_by_the_model(client, state):
    sid, h, _ = start(client, state, "FXC-001")
    llm = MisbehavingLLM(NLUResult(intent="account_inquiry"), rewrite="Tiene 1.000.000 en su cuenta. ¿Lo conecto?")
    state.orchestrator.llm = llm
    r = say(client, sid, h, "necesito el saldo de mi cuenta")
    assert llm.compose_calls == [] and "1.000.000" not in r["reply"]


class _Narrator(MisbehavingLLM):
    def __init__(self, text):
        super().__init__(NLUResult(intent="request_human"))
        self.text = text

    def summarize(self, summary):
        return self.text


def test_llm_narrative_replaces_the_rules_one_only_if_it_adds_nothing_new(client, state):
    sid, h, _ = start(client, state, "FXC-002")
    state.orchestrator.llm = _Narrator("Cliente con un reclamo crítico escalado y una llamada pendiente; llega molesto. Conviene revisar el reclamo primero.")
    say(client, sid, h, "quiero hablar con un asesor")
    s = summary_of(client, sid, h)
    assert s["narrative_source"] == "llm" and s["narrative"].startswith("Cliente con un reclamo crítico")
    for bad in ("Tiene una deuda de 987654 pesos.", "Le aseguro que se resolverá hoy.", ""):
        sid2, h2, _ = start(client, state, "FXC-002")
        state.orchestrator.llm = _Narrator(bad)
        say(client, sid2, h2, "quiero hablar con un asesor")
        s2 = summary_of(client, sid2, h2)
        assert s2["narrative_source"] == "rules" and "Motivo:" in s2["narrative"]


def test_the_model_sees_products_as_bank_verified_and_never_the_case_ids(client, state):
    """El resumen que recibe Claude marca los productos como verificados (antes los omitia y el modelo escribio que una
    tarjeta 'no estaba verificada') y no lleva identificadores ni datos de la cuenta."""
    from app.agent.llm_anthropic import SYSTEM_SUMMARY, AnthropicLLM

    sid, h, _ = start(client, state, "FXC-002")
    say(client, sid, h, "necesito el saldo de mi cuenta")
    say(client, sid, h, "sí")
    summary = summary_of(client, sid, h)
    seen = {}
    llm = object.__new__(AnthropicLLM)                              # sin cliente ni red
    llm._call = lambda system, user, max_tokens: seen.update(system=system, user=user) or "ok"
    before = json.dumps(summary, sort_keys=True)
    llm.summarize(summary)
    payload = json.loads(seen["user"])
    assert payload["customer_context"]["products_verified_by_bank"] and "case_id" not in seen["user"]
    assert "customer_id" not in seen["user"] and "FXC-002" not in seen["user"]
    assert json.dumps(summary, sort_keys=True) == before            # no modifica el resumen original
    assert "VERIFICADOS" in SYSTEM_SUMMARY and "No infieras" in SYSTEM_SUMMARY


def test_a_failing_narrator_falls_back_to_the_rules_paragraph(client, state):
    class Boom(_Narrator):
        def summarize(self, summary):
            raise RuntimeError("red caida")

    sid, h, _ = start(client, state, "FXC-002")
    state.orchestrator.llm = Boom("x")
    assert say(client, sid, h, "quiero hablar con un asesor")["handoff_ticket"]
    assert summary_of(client, sid, h)["narrative_source"] == "rules"
