from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import BASE_DIR, Settings
from app.main import create_app


def make_settings(**kw) -> Settings:
    base = dict(env="dev", jwt_secret="test-secret", llm_provider="mock", api_keys="", admin_api_keys="")
    base.update(kw)
    return Settings(_env_file=None, **base)


@pytest.fixture()
def app(tmp_path):
    return create_app(make_settings(outbox_dir=tmp_path / "outbox"))      # PDFs de cada prueba en su propia carpeta


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def state(app):
    return app.state.ctx


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def open_session(client, doc: str, language: str = "es"):
    r = client.post("/v1/sessions", json={"document_number": doc, "language": language})
    return r


def correct_answers(state, sid: str) -> list[dict]:
    """Lee las respuestas correctas del servidor (solo posible desde un test)."""
    ch = state.store.get(sid).challenge
    return [{"question_id": q.id, "option_id": q.correct_option_id} for q in ch.questions]


def login(client, state, doc: str, language: str = "es") -> tuple[str, dict]:
    r = open_session(client, doc, language)
    assert r.status_code == 201, r.text
    sid, token = r.json()["session_id"], r.json()["token"]
    v = client.post(f"/v1/sessions/{sid}/verify", json={"answers": correct_answers(state, sid)}, headers=hdr(token))
    assert v.status_code == 200 and v.json()["status"] == "authenticated", v.text
    return sid, hdr(token)


def authenticable(state, doc) -> bool:
    """El cliente tiene datos para un reto de seguridad completo (si no, la API responde AUTH_UNAVAILABLE)."""
    from app.auth import kba

    customer = state.repo.find_by_document(str(doc))
    return kba.build_challenge(state.repo, customer, n=state.settings.auth_questions, lang="es",
                               as_of=state.settings.as_of_date) is not None


def pick_customers(state):
    """Clientes del snapshot por perfil (que ademas pueden autenticarse), para pruebas deterministas de la politica."""
    df = state.repo._customers
    ok = df[(df.customer_status == "Active") & df.credit_score.notna() & df.monthly_income.notna()
            & (df.credit_score >= 680) & (df.max_days_past_due == 0)]
    no_income = df[df.credit_score.notna() & df.monthly_income.isna() & (df.customer_status == "Active")
                   & (df.credit_score >= 680) & (df.max_days_past_due == 0)]
    return ok[ok.document_number.map(lambda d: authenticable(state, d))], \
        no_income[no_income.document_number.map(lambda d: authenticable(state, d))]


def customers_by_offer_profile(state) -> dict[str, list[dict]]:
    """Clasifica el snapshot por (consentimiento, preaprobacion con datos del banco) para pruebas de oferta proactiva."""
    from app.agent.context import blocks_proactive_offer
    from app.agent.tools import ToolContext, get_customer_context, offer_rates
    from app.policy import credit_engine as ce

    # "consent_pre_case": preaprobado y con consentimiento, pero con un caso abierto que frena la oferta proactiva
    out: dict[str, list[dict]] = {"consent_pre": [], "consent_pre_case": [], "noconsent_pre": [], "consent_notpre": []}
    df = state.repo._customers
    for r in df.itertuples():
        if not authenticable(state, r.document_number):
            continue                                  # sin datos para el reto de seguridad: no puede iniciar sesion en una prueba
        prof = state.repo.credit_profile(r.customer_id)
        tc = ToolContext(r.customer_id, state.repo, state.policy)
        info = offer_rates(tc)
        pre = info["probe"].decision.outcome == ce.ELIGIBLE and bool(info["rates"]) and (info["probe"].decision.max_amount or 0) > 0
        rec = {"doc": r.document_number, "income": prof["monthly_income"], "cid": r.customer_id}
        if prof["accepts_marketing"] and pre and blocks_proactive_offer(get_customer_context(tc)):
            out["consent_pre_case"].append(rec)
        elif prof["accepts_marketing"] and pre:
            out["consent_pre"].append(rec)
        elif not prof["accepts_marketing"] and pre:
            out["noconsent_pre"].append(rec)
        elif prof["accepts_marketing"] and not pre:
            out["consent_notpre"].append(rec)
    return out
