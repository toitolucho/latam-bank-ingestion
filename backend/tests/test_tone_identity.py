"""Tono natural e identidad honesta: el asistente no se anuncia a cada rato, pero nunca se hace pasar por una persona."""
from __future__ import annotations

import re

import pytest

from app.agent import templates
from app.agent.nlu import MockNLU, NLUResult
from app.agent.orchestrator import _CLAIMS_HUMAN, safe_text
from tests.conftest import customers_by_offer_profile, login
from tests.test_llm_guards import MisbehavingLLM


def _texts():
    for kind, langs in templates.T.items():
        for lang, value in langs.items():
            for i, text in enumerate(value if isinstance(value, list) else [value]):
                yield kind, lang, i, text


def say(client, sid, h, text, language=None):
    body = {"message": text, **({"language": language} if language else {})}
    r = client.post(f"/v1/sessions/{sid}/messages", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def quiet(state):
    """Cliente que no acepta marketing (sin ofertas proactivas que mezclen mensajes)."""
    return customers_by_offer_profile(state)["noconsent_pre"][0]


# ---------------------------------------------------------------- las plantillas

def test_no_template_claims_to_be_a_person():
    offenders = [(k, lang, i) for k, lang, i, t in _texts() if _CLAIMS_HUMAN.search(t)]
    assert offenders == []


def test_every_variant_uses_the_same_placeholders():
    for kind, langs in templates.T.items():
        for lang, value in langs.items():
            if isinstance(value, list):
                sets = [frozenset(re.findall(r"\{(\w+)\}", v)) for v in value]
                assert len(set(sets)) == 1, (kind, lang, sets)       # si no, rotar variantes podria fallar al formatear


def test_both_languages_have_every_template():
    assert [k for k, v in templates.T.items() if set(v) != {"es", "pt"}] == []


def test_the_virtual_assistant_is_named_in_the_welcome_message_only():
    assert "asistente virtual" in templates.T["welcome"]["es"] and "assistente virtual" in templates.T["welcome"]["pt"]
    repeats = [(k, i) for k, lang, i, t in _texts()
               if lang == "es" and k not in ("welcome", "welcome_case", "identity") and "asistente virtual" in t]
    assert repeats == []                                               # el resto de mensajes no se vuelve a presentar


# ---------------------------------------------------------------- conversaciones

def test_welcome_after_verification_introduces_the_assistant_once(client, state, quiet):
    from tests.conftest import correct_answers, hdr, open_session
    r = open_session(client, quiet["doc"]).json()
    v = client.post(f"/v1/sessions/{r['session_id']}/verify", json={"answers": correct_answers(state, r["session_id"])},
                    headers=hdr(r["token"])).json()
    assert "asistente virtual" in v["greeting"]
    sid, h = r["session_id"], hdr(r["token"])
    hola = say(client, sid, h, "hola")
    assert "asistente virtual" not in hola["reply"]                    # ya se presento: ahora saluda sin repetirse


@pytest.mark.parametrize("question,lang,must", [
    ("¿eres un robot?", "es", ("asistente virtual", "no una persona")),
    ("¿hablo con una persona real?", "es", ("asistente virtual", "no una persona")),
    ("você é um robô?", "pt", ("assistente virtual", "não uma pessoa")),
])
def test_asked_directly_the_assistant_answers_honestly(client, state, quiet, question, lang, must):
    sid, h = login(client, state, quiet["doc"], lang)
    r = say(client, sid, h, question)
    assert r["intent"] == "ask_identity" and all(m in r["reply"] for m in must)
    assert not _CLAIMS_HUMAN.search(r["reply"]) and r["proactive_offer"] is False


def test_asking_for_a_person_is_still_a_handoff_request_not_an_identity_question():
    n = MockNLU()
    assert n.extract("quiero hablar con una persona").intent == "request_human"
    assert n.extract("¿hablo con una persona?").intent == "ask_identity"


def test_low_risk_messages_rotate_their_wording(client, state, quiet):
    sid, h = login(client, state, quiet["doc"])
    first = say(client, sid, h, "gracias")["reply"]
    second = say(client, sid, h, "gracias")["reply"]
    assert first != second


# ---------------------------------------------------------------- el modelo no puede hacerse pasar por una persona

@pytest.mark.parametrize("text", [
    "Soy una persona real, no un robot.", "Claro, soy un asesor humano. ¿En qué le ayudo?",
    "Sou uma pessoa, pode ficar tranquilo.", "No soy un robot, soy ejecutivo del banco.",
])
def test_text_claiming_to_be_a_person_is_rejected(text):
    assert not safe_text(text, {"fmt": {}})


@pytest.mark.parametrize("text", ["Soy el asistente virtual del banco.", "Con gusto, ¿algo más?", "Sou o assistente virtual do banco."])
def test_normal_text_is_accepted(text):
    assert safe_text(text, {"fmt": {}})


def test_a_rewrite_that_pretends_to_be_human_is_discarded(client, state, quiet):
    sid, h = login(client, state, quiet["doc"])
    state.orchestrator.llm = MisbehavingLLM(NLUResult(intent="thanks"), rewrite="Soy una persona real, encantado de ayudarle.")
    r = say(client, sid, h, "gracias")
    assert "persona real" not in r["reply"] and r["reply"]


def test_a_rewrite_cannot_replace_the_identity_answer(client, state, quiet):
    sid, h = login(client, state, quiet["doc"])
    state.orchestrator.llm = MisbehavingLLM(NLUResult(intent="ask_identity"), rewrite="Soy una persona.")
    r = say(client, sid, h, "¿eres una máquina?")
    assert "asistente virtual" in r["reply"]                           # esa respuesta sale siempre de la plantilla


def test_asking_if_it_is_a_robot_is_not_mistaken_for_a_theft_report():
    """'robot'/'robô' contiene 'robo' (hurto): no debe marcar el tema como sensible ni cortar las ofertas de la sesion."""
    n = MockNLU()
    for q in ("¿eres un robot?", "você é um robô?"):
        r = n.extract(q)
        assert r.intent == "ask_identity" and r.sensitive_topic is False
    assert n.extract("me robaron la tarjeta").sensitive_topic is True        # y el robo real sigue detectandose
