"""Herramientas del agente. Ninguna recibe customer_id: el contexto lo fija la sesion autenticada.

Es la unica via a datos y acciones; el LLM no llama a nada directamente.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.agent.context import build_context
from app.data.repository import CustomerRepository
from app.policy import credit_engine as ce

DEFAULT_MONTHS = {"personal_loan": 36, "mortgage": 180}
SUPPORTED_PRODUCTS = tuple(DEFAULT_MONTHS)  # tarjeta de credito: se deriva a un asesor


@dataclass
class ToolContext:
    customer_id: str
    repo: CustomerRepository
    policy: dict
    # Llamadas reales a herramientas de ESTE turno. Alimenta la "evidencia" que muestra la interfaz (ver agent/evidence.py):
    # solo se registra lo que de verdad se ejecuto.
    trace: list[dict] = field(default_factory=list)


@dataclass
class EvalResult:
    decision: ce.Decision
    request: dict
    income_used: float | None
    income_declared: bool
    ccy: str


def get_profile(ctx: ToolContext) -> dict:
    profile = ctx.repo.credit_profile(ctx.customer_id)
    ctx.trace.append({"tool": "customer_profile", "profile": profile})
    return profile


def get_customer_context(ctx: ToolContext) -> dict:
    """Casos abiertos y existencia de productos del cliente de la sesion (ver agent/context.py). Solo lectura."""
    context = build_context(ctx.repo.case_context(ctx.customer_id), ctx.repo.product_overview(ctx.customer_id))
    ctx.trace.append({"tool": "customer_context", "open_cases": context["counts"]["open"],
                      "products": len(context["products"])})
    return context


def evaluate_credit(ctx: ToolContext, product: str, amount: float, months: int,
                    declared_income: float | None = None, record: bool = True) -> EvalResult:
    """Corre el motor determinista. Un ingreso declarado muy superior al registrado va a revision humana.

    `record=False` para consultas internas (p. ej. la sonda de capacidad de `offer_rates`), que no son una evaluacion
    de lo que pidio el cliente y no deben presentarse como tal."""
    res = _evaluate_credit(ctx, product, amount, months, declared_income)
    if record:
        ctx.trace.append({"tool": "credit_policy", "request": res.request, "decision": res.decision, "ccy": res.ccy,
                          "income_declared": res.income_declared, "max_dti": ctx.policy["max_dti"]})
    return res


def _evaluate_credit(ctx: ToolContext, product: str, amount: float, months: int,
                     declared_income: float | None) -> EvalResult:
    profile = get_profile(ctx)
    on_file = profile["monthly_income"]
    income = declared_income if declared_income is not None else on_file
    request = {"product": product, "amount": amount, "months": months}
    ccy = profile["income_ccy"]

    if declared_income is not None and on_file:
        max_uplift = ctx.policy["declared_income"]["max_uplift_without_review"]
        if declared_income > on_file * (1 + max_uplift):
            d = ce.Decision(outcome=ce.NEEDS_REVIEW, reasons=["INCOME_UPLIFT_REVIEW"],
                            policy_version=ctx.policy["version"])
            return EvalResult(d, request, income, True, ccy)

    applicant = {
        "customer_status": profile["customer_status"], "credit_score": profile["credit_score"],
        "monthly_income": income, "income_is_declared": declared_income is not None,
        "existing_monthly_debt": profile["existing_monthly_debt"], "max_days_past_due": profile["max_days_past_due"],
        "n_active_products": profile["n_active_products"],
    }
    d = ce.evaluate(applicant, request, ctx.policy)
    return EvalResult(d, request, income, declared_income is not None, ccy)


def offer_rates(ctx: ToolContext, declared_income: float | None = None) -> dict:
    """Tasas de referencia por producto para la banda del cliente, y capacidad maxima de un prestamo personal."""
    profile = get_profile(ctx)
    probe = evaluate_credit(ctx, "personal_loan", 1.0, DEFAULT_MONTHS["personal_loan"], declared_income, record=False)
    band = probe.decision.band
    rates = {}
    if band is not None and band not in ctx.policy["no_lending_bands"]:
        for p in ("personal_loan", "mortgage", "credit_card"):
            rates[p] = ce.annual_rate(p, band, profile["n_active_products"], ctx.policy)
    ctx.trace.append({"tool": "offer_rates", "rates": dict(rates), "max_amount": probe.decision.max_amount,
                      "ccy": profile["income_ccy"], "policy_version": ctx.policy["version"]})
    return {"rates": rates, "probe": probe, "ccy": profile["income_ccy"]}


@dataclass
class HandoffQueue:
    """Cola en memoria para el prototipo. En produccion: sistema de tickets / cola del contact center."""
    items: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, summary: dict) -> None:
        with self._lock:
            self.items.append(summary)

    def update(self, ticket_id: str, **fields) -> None:
        with self._lock:
            for it in self.items:
                if it["ticket_id"] == ticket_id:
                    it.update(fields)

    def list(self) -> list[dict]:
        with self._lock:
            return list(self.items)


def new_ticket_id() -> str:
    return "HND-" + secrets.token_hex(4).upper()


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
