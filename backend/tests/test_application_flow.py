"""Avanzar con la solicitud: documentacion faltante -> derivacion a un asesor -> resumen final y correo (simulado) con PDF."""
from __future__ import annotations

import json

import pytest

from app.agent import documents
from app.core.outbox import Outbox
from app.core.pdf import render_summary_pdf
from tests.conftest import customers_by_offer_profile, login, pick_customers

ALL_DOCS = "id_copy,address_proof,income_proof"


@pytest.fixture()
def cust(state):
    """Cliente preaprobado (cualquier consentimiento) con ingreso registrado."""
    g = customers_by_offer_profile(state)
    return (g["consent_pre"] + g["noconsent_pre"])[0]


def set_docs(state, cid, docs: str):
    state.repo._cust.loc[cid, "docs_on_file"] = docs


def say(client, sid, h, text, language=None):
    body = {"message": text, **({"language": language} if language else {})}
    r = client.post(f"/v1/sessions/{sid}/messages", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def evaluated(client, state, cust, docs=ALL_DOCS, language="es"):
    """Sesion con una propuesta elegible ya evaluada."""
    set_docs(state, cust["cid"], docs)
    sid, h = login(client, state, cust["doc"], language)
    r = say(client, sid, h, f"quiero un préstamo de {int(cust['income'] * 0.1)} a 24 meses" if language == "es"
            else f"quero um empréstimo de {int(cust['income'] * 0.1)} em 24 meses")
    assert r["outcome"] == "eligible", r
    return sid, h, r


# ---------------------------------------------------------------- avanzar y documentos

def test_after_a_favourable_evaluation_the_agent_asks_whether_to_move_forward(client, state, cust):
    _, _, r = evaluated(client, state, cust)
    assert r["awaiting"] == "proceed" and r["suggested_replies"] == ["Sí", "No"]


def test_everything_on_file_goes_straight_to_a_human_advisor_with_the_summary(client, state, cust):
    sid, h, _ = evaluated(client, state, cust, docs=ALL_DOCS)
    r = say(client, sid, h, "sí")
    assert r["handoff_ticket"] and r["handoff_ticket"] in r["reply"] and r["summary_ready"] is True
    assert "Monto" in r["reply"] and "Cuota mensual" in r["reply"] and "PDF" in r["reply"]
    assert state.store.get(sid).slots["application"]["status"] == "ready"


def test_missing_documents_are_requested_and_declaring_all_completes_the_application(client, state, cust):
    sid, h, _ = evaluated(client, state, cust, docs="id_copy")
    r = say(client, sid, h, "sí")
    assert r["awaiting"] == "docs_all" and "comprobante de domicilio" in r["reply"] and "comprobante de ingresos" in r["reply"]
    assert "copia del documento de identidad" not in r["reply"]                  # lo que el banco ya tiene no se pide
    r2 = say(client, sid, h, "sí, los tengo todos")
    assert r2["handoff_ticket"] and r2["summary_ready"] is True
    app = state.store.get(sid).slots["application"]
    assert app["declared"] == ["address_proof", "income_proof"] and app["missing"] == []
    summary = next(x for x in state.queue.list() if x["ticket_id"] == r2["handoff_ticket"])
    assert summary["application"]["declared"] == app["declared"]                   # el asesor ve lo declarado, sin verificar


def test_documents_are_asked_one_by_one_and_missing_ones_are_reported(client, state, cust):
    sid, h, _ = evaluated(client, state, cust, docs="id_copy")
    say(client, sid, h, "sí")
    r = say(client, sid, h, "no")
    assert r["awaiting"] == "doc_item" and "domicilio" in r["reply"]
    r = say(client, sid, h, "sí")
    assert r["awaiting"] == "doc_item" and "ingresos" in r["reply"]
    r = say(client, sid, h, "no")
    assert r["awaiting"] == "confirm_handoff" and "ingresos" in r["reply"] and r["handoff_ticket"] is None
    assert state.store.get(sid).slots["application"]["missing"] == ["income_proof"]
    r = say(client, sid, h, "sí")                                                  # acepta que un asesor lo contacte
    assert r["handoff_ticket"]
    summary = next(x for x in state.queue.list() if x["ticket_id"] == r["handoff_ticket"])
    assert summary["reason"] == "DOCS_INCOMPLETE" and "income_proof" in str(summary["open_questions"])
    end = say(client, sid, h, "gracias")
    assert end["summary_ready"] is True and "pendiente" in end["reply"] and "ingresos" in end["reply"]


def test_a_single_missing_document_answered_no_is_not_asked_twice(client, state, cust):
    sid, h, _ = evaluated(client, state, cust, docs="id_copy,address_proof")      # solo falta el de ingresos
    r = say(client, sid, h, "sí")
    assert r["awaiting"] == "docs_all"
    r = say(client, sid, h, "no")
    assert r["awaiting"] == "confirm_handoff" and "ingresos" in r["reply"]


def test_an_unclear_answer_repeats_the_same_question(client, state, cust):
    sid, h, _ = evaluated(client, state, cust, docs="id_copy")
    say(client, sid, h, "sí")
    r = say(client, sid, h, "mmm no sé")
    assert r["awaiting"] == "docs_all" and r["reply"].startswith("Perdone") and "domicilio" in r["reply"]


def test_income_declared_in_the_chat_adds_bank_statements_to_the_requirements(client, state):
    _, no_income = pick_customers(state)
    if no_income.empty:
        pytest.skip("sin cliente sin ingreso registrado")
    row = no_income.iloc[0]
    set_docs(state, row.name if hasattr(row, "name") else row.customer_id, "id_copy")
    sid, h = login(client, state, str(row.document_number))
    say(client, sid, h, "quiero un préstamo de 2000 a 24 meses")
    r = say(client, sid, h, "gano 9000000")
    if r["outcome"] != "eligible_provisional":
        pytest.skip("el caso no quedo elegible provisional con este conjunto de datos")
    r = say(client, sid, h, "sí")
    assert "estados de cuenta" in r["reply"]                                       # exigencia extra por ingreso no verificado
    assert "bank_statements_3m" in state.store.get(sid).slots["application"]["required"]


def test_declining_to_move_forward_keeps_the_conversation_open_and_the_summary_says_so(client, state, cust):
    sid, h, _ = evaluated(client, state, cust)
    r = say(client, sid, h, "no")
    assert r["handoff_ticket"] is None and "retomarla" in r["reply"]
    end = say(client, sid, h, "gracias")
    assert end["summary_ready"] is True and "aún sin iniciar" in end["reply"] and end["handoff_ticket"] is None


# ---------------------------------------------------------------- resumen final y correo

def test_closing_after_an_evaluation_gives_the_summary_and_the_email_notice_but_no_new_offer(client, state, cust):
    sid, h, _ = evaluated(client, state, cust)
    r = say(client, sid, h, "gracias, eso es todo")
    assert r["summary_ready"] is True and r["proactive_offer"] is False
    assert "Plazo: 24 meses" in r["reply"] and "PDF" in r["reply"] and "***@" in r["reply"]
    assert r["email"]["status"] == "simulated_not_sent" and "***@" in r["email"]["to"]


def test_the_summary_is_delivered_only_once(client, state, cust):
    sid, h, _ = evaluated(client, state, cust)
    assert say(client, sid, h, "gracias, eso es todo")["summary_ready"] is True
    assert say(client, sid, h, "gracias de nuevo")["summary_ready"] is False
    assert len(state.outbox.records) == 1


def test_the_pdf_is_downloadable_and_the_outbox_never_stores_the_full_address(client, state, cust):
    sid, h, _ = evaluated(client, state, cust)
    r = say(client, sid, h, "gracias, eso es todo")
    pdf = client.get(f"/v1/sessions/{sid}/summary.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"
    record = json.loads((state.outbox.dir / f"{r['email']['id']}.json").read_text(encoding="utf-8"))
    full = state.repo._cust.loc[cust["cid"], "email"]
    assert record["status"] == "simulated_not_sent" and full not in json.dumps(record) and "***@" in record["to_masked"]


def test_the_summary_pdf_is_not_available_before_there_is_a_proposal(client, state, cust):
    sid, h = login(client, state, cust["doc"])
    assert client.get(f"/v1/sessions/{sid}/summary.pdf", headers=h).status_code == 404


def test_explicit_end_returns_the_summary_and_blocks_further_messages(client, state, cust):
    sid, h, _ = evaluated(client, state, cust)
    r = client.post(f"/v1/sessions/{sid}/end", headers=h)
    assert r.status_code == 200 and r.json()["summary_ready"] is True and r.json()["email"]["status"] == "simulated_not_sent"
    again = client.post(f"/v1/sessions/{sid}/messages", json={"message": "hola"}, headers=h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "SESSION_ENDED"


def test_explicit_end_without_a_proposal_just_says_goodbye(client, state, cust):
    sid, h = login(client, state, cust["doc"])
    r = client.post(f"/v1/sessions/{sid}/end", headers=h).json()
    assert r["summary_ready"] is False and r["email"] is None and r["reply"]


def test_the_agent_summary_includes_the_offer_and_the_queued_email(client, state, cust):
    sid, h, _ = evaluated(client, state, cust, docs=ALL_DOCS)
    r = say(client, sid, h, "sí")
    s = next(x for x in state.queue.list() if x["ticket_id"] == r["handoff_ticket"])
    assert s["offer_summary"]["product"] and s["summary_email"]["status"] == "simulated_not_sent"
    assert any(a["type"] == "summary_email_queued" for a in s["actions_taken"])


def test_portuguese_flow_uses_portuguese_documents_and_labels(client, state, cust):
    sid, h, _ = evaluated(client, state, cust, docs="id_copy", language="pt")
    r = say(client, sid, h, "sim")
    assert "comprovante de endereço" in r["reply"]
    r2 = say(client, sid, h, "sim, tenho todos")
    assert r2["summary_ready"] is True and "Produto" in r2["reply"] and "PDF" in r2["reply"]


# ---------------------------------------------------------------- unidades

def test_required_documents_depend_on_product_and_on_unverified_income(state):
    p = state.policy
    assert documents.required_documents(p, "personal_loan", False) == ["id_copy", "address_proof", "income_proof"]
    assert "property_deed" in documents.required_documents(p, "mortgage", False)
    assert documents.required_documents(p, "personal_loan", True)[-1] == "bank_statements_3m"


def test_pdf_handles_accents_and_special_symbols():
    pdf = render_summary_pdf(lang="pt", first_name="João", rows=[("Valor", "10.000 MXN (≈ 580 USD)"), ("Situação", "preliminarmente elegível")],
                             notes=["Simulação • sujeita à aprovação."], ticket="HND-1", policy_version="0.2.0")
    assert pdf[:4] == b"%PDF" and len(pdf) > 800


def test_outbox_rejects_path_tricks(tmp_path):
    ob = Outbox(tmp_path)
    rec = ob.queue(customer_id="c", to_masked="a***@x.com", subject="s", pdf=b"%PDF-test", language="es")
    assert ob.pdf_bytes(rec["id"]) == b"%PDF-test"
    assert ob.pdf_bytes("../secret") is None and ob.pdf_bytes("EML-../x") is None
