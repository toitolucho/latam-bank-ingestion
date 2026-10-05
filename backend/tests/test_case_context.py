"""Contexto de casos abiertos: derivacion (scripts/case_context.py), lista blanca del repositorio, prioridad y carga
al autenticar. Usa el fixture del equipo (inventado, determinista): no depende del snapshot del organizador."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.agent.context import build_context, case_weight, rank_cases
from app.agent.tools import ToolContext, get_customer_context
from app.config import BASE_DIR
from app.data.repository import CASE_FIELDS, PRODUCT_FIELDS, SnapshotRepository
from app.main import create_app
from tests.conftest import login, make_settings

sys.path.insert(0, str(BASE_DIR / "scripts"))
from case_context import derive_case_context  # noqa: E402

FIXTURE = BASE_DIR / "data" / "fixture"
AS_OF = date(2026, 6, 17)


@pytest.fixture(scope="module")
def repo() -> SnapshotRepository:
    return SnapshotRepository(FIXTURE)


# ---------------------------------------------------------------- derivacion
def _complaints(rows):
    cols = ["complaint_id", "customer_id", "creation_date", "case_type", "category", "reception_channel",
            "origin_interaction_id", "priority", "status", "sla_breached", "is_repeat_complainer"]
    return pd.DataFrame(rows, columns=cols)


def _interactions(rows):
    cols = ["interaction_id", "customer_id", "interaction_date", "channel", "reason_category", "was_resolved",
            "requires_followup", "was_escalated", "detected_sentiment"]
    return pd.DataFrame(rows, columns=cols)


def test_derive_keeps_open_complaints_of_any_age_and_drops_closed():
    comp = _complaints([
        ("C1", "A", "2023-01-10 10:00:00", "Complaint", "Fees", "App", None, "High", "Open", "True", "False"),
        ("C2", "A", "2026-06-01 10:00:00", "Claim", "Fees", "App", None, "Low", "Resolved", "False", "False"),
        ("C3", "A", "2026-06-10 10:00:00", "Claim", "Fees", "App", None, "Low", "Escalated", "False", "True"),
    ])
    out = derive_case_context(comp, _interactions([]), AS_OF)
    assert sorted(out.case_id) == ["C1", "C3"]
    c1 = out[out.case_id == "C1"].iloc[0]
    assert c1.days_open == (AS_OF - date(2023, 1, 10)).days and bool(c1.sla_breached)
    assert bool(out[out.case_id == "C3"].iloc[0].is_escalated)


def test_derive_interactions_need_unresolved_and_followup_or_escalation_within_window():
    inter = _interactions([
        ("I1", "A", "2026-05-20 09:00:00", "Phone", "Queja", "False", "True", "False", "Negativo"),       # entra
        ("I2", "A", "2026-05-20 09:00:00", "Phone", "Queja", "True", "True", "False", "Neutral"),         # resuelta
        ("I3", "A", "2026-05-20 09:00:00", "Phone", "Queja", "False", "False", "False", "Neutral"),       # sin seguimiento
        ("I4", "A", "2026-05-20 09:00:00", "Phone", "Queja", "False", "False", "True", "Neutral"),        # escalada: entra
        ("I5", "A", "2026-01-01 09:00:00", "Phone", "Queja", "False", "True", "False", "Neutral"),        # fuera de la ventana
        ("I6", "A", "2026-06-20 09:00:00", "Phone", "Queja", "False", "True", "False", "Neutral"),        # posterior al corte
        ("I7", "A", "2026-05-20 09:00:00", "Phone", "Queja", None, "True", "False", "Neutral"),           # sin dato: no se afirma
    ])
    out = derive_case_context(_complaints([]), inter, AS_OF)
    assert sorted(out.case_id) == ["I1", "I4"]
    assert (out.status == "Unresolved").all() and out.case_source.eq("interaction").all()


def test_derive_window_is_anchored_on_as_of_not_today():
    inter = _interactions([("I1", "A", "2026-06-16 09:00:00", "Phone", "Queja", "False", "True", "False", "Neutral")])
    assert len(derive_case_context(_complaints([]), inter, AS_OF)) == 1
    assert len(derive_case_context(_complaints([]), inter, date(2026, 12, 1))) == 0     # 168 dias despues: fuera de ventana


def test_derive_drops_interaction_that_originated_a_complaint():
    comp = _complaints([("C1", "A", "2026-06-01 10:00:00", "Claim", "Fees", "App", "I1", "Low", "Resolved", "False", "False")])
    inter = _interactions([("I1", "A", "2026-05-20 09:00:00", "Phone", "Queja", "False", "True", "False", "Neutral")])
    assert derive_case_context(comp, inter, AS_OF).empty


def test_derive_never_carries_sensitive_columns():
    out = derive_case_context(_complaints([]), _interactions([]), AS_OF)
    assert not {"description", "claimed_amount", "compensation_granted", "resolution"} & set(out.columns)


# ---------------------------------------------------------------- repositorio: lista blanca
def test_repository_returns_only_whitelisted_fields(repo):
    cases = repo.case_context("FXC-002")
    assert cases and all(set(c) == set(CASE_FIELDS) for c in cases)
    prods = repo.product_overview("FXC-002")
    assert prods and all(set(p) == set(PRODUCT_FIELDS) for p in prods)
    leaked = {"current_balance", "credit_limit", "opening_date", "product_number", "description", "claimed_amount"}
    assert not leaked & {k for c in cases for k in c} and not leaked & {k for p in prods for k in p}


def test_repository_without_case_file_has_no_cases(tmp_path):
    for name in ("customers", "products", "branches", "transactions"):
        pd.read_parquet(FIXTURE / f"{name}.parquet").to_parquet(tmp_path / f"{name}.parquet")
    assert SnapshotRepository(tmp_path).case_context("FXC-002") == []


# ---------------------------------------------------------------- prioridad y contexto
def test_critical_escalated_complaint_outranks_everything(repo):
    ctx = get_customer_context(ToolContext("FXC-002", repo, {}))
    top = ctx["most_relevant"]
    assert top["priority"] == "Critical" and top["status"] == "Escalated" and top["case_source"] == "complaint"
    assert ctx["counts"] == {"open": 2, "complaints": 1, "interactions": 1, "high_priority": 1}
    f = ctx["flags"]
    assert f["has_critical_open"] and f["has_sla_breach"] and f["repeat_complainer"] and f["recent_negative_sentiment"]


def test_customer_without_cases_has_empty_context(repo):
    ctx = get_customer_context(ToolContext("FXC-010", repo, {}))
    assert ctx["most_relevant"] is None and ctx["counts"]["open"] == 0 and not ctx["flags"]["has_open_case"]
    assert ctx["products"], "la existencia de productos se informa aunque no haya casos"


def test_tool_records_a_trace_entry(repo):
    tc = ToolContext("FXC-011", repo, {})
    get_customer_context(tc)
    assert any(t["tool"] == "customer_context" and t["open_cases"] == 1 for t in tc.trace)


def test_ranking_prefers_priority_then_escalation_then_age():
    low_old = {"case_source": "complaint", "priority": "Low", "days_open": 900}
    high = {"case_source": "complaint", "priority": "High", "days_open": 5}
    esc_inter = {"case_source": "interaction", "priority": None, "is_escalated": True, "days_open": 10}
    plain_inter = {"case_source": "interaction", "priority": None, "days_open": 40}
    assert [c["days_open"] for c in rank_cases([plain_inter, low_old, esc_inter, high])] == [5, 900, 10, 40]
    older, newer = dict(low_old, days_open=500), dict(low_old, days_open=50)
    assert rank_cases([newer, older])[0] is older                       # a igual peso, el que lleva mas esperando
    assert case_weight(high) > case_weight(low_old)
    assert build_context([], [])["most_relevant"] is None


# ---------------------------------------------------------------- carga al autenticar
def test_context_is_loaded_into_the_session_on_authentication(tmp_path):
    app = create_app(make_settings(outbox_dir=tmp_path / "outbox", data_dir=FIXTURE))
    state = app.state.ctx
    doc = state.repo._customers.set_index("customer_id").loc["FXC-002", "document_number"]
    sid, _ = login(TestClient(app), state, str(doc))
    ctx = state.store.get(sid).slots["context"]
    assert ctx["most_relevant"]["priority"] == "Critical" and ctx["counts"]["open"] == 2
