"""Oferta proactiva de credito: cuando y a quien se ofrece.

Dos caminos distintos que NO deben mezclarse:
- Reactivo: el cliente pide un credito -> se evalua su elegibilidad. NO mira el consentimiento de marketing.
- Proactivo (este modulo): se ofrece por iniciativa del banco. Exige TODAS estas condiciones:
    1. el cliente acepta marketing (accepts_marketing);
    2. esta preaprobado por la politica con datos del banco (no con ingreso declarado en el chat);
    3. el momento es adecuado: sin sentimiento negativo, sin tema delicado (fraude, disputa, queja) y sin
       rechazo previo en la sesion;
    4. no se ofrecio ya en esta sesion ni el cliente dijo que no;
    5. al cliente no le queda nada pendiente: ni un tema de soporte en esta conversacion (producto, incidente, caso), ni una
       derivacion, ni un caso critico abierto, ni un caso abierto reciente (agent/context.py). Antes se ofrecia credito justo
       despues de derivar un problema; ahora primero se atiende lo que el cliente trajo.
Es una decision en codigo: el LLM solo redacta el mensaje.

LIMITE: el tope de frecuencia es por sesion (en memoria). En produccion debe persistirse (ultima oferta por cliente).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.agent import templates
from app.agent.context import blocks_proactive_offer
from app.agent.tools import DEFAULT_MONTHS, ToolContext, get_profile, offer_rates
from app.core.fmt import fmt_money, fmt_pct
from app.core.sessions import Session
from app.logging_setup import log
from app.policy import credit_engine as ce

logger = logging.getLogger(__name__)

OK = "OK"
NO_CONSENT = "NO_CONSENT"
NEGATIVE_MOMENT = "NEGATIVE_MOMENT"
ALREADY_OFFERED = "ALREADY_OFFERED"
ALREADY_DECLINED = "ALREADY_DECLINED"
RECENT_DECLINE = "RECENT_DECLINE"
NOT_PREAPPROVED = "NOT_PREAPPROVED"
SUPPORT_TOPIC = "SUPPORT_TOPIC"
OPEN_CASE = "OPEN_CASE"


@dataclass
class OfferDecision:
    make: bool
    reason: str
    fmt: dict[str, str] = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)


def decide(session: Session, ctx: ToolContext) -> OfferDecision:
    slots = session.slots
    if slots.get("offer_declined"):
        return _no(ALREADY_DECLINED)
    if slots.get("offer_made"):
        return _no(ALREADY_OFFERED)
    if slots.get("no_offers"):
        return _no(NEGATIVE_MOMENT)
    if slots.get("case") or session.handoff:
        return _no(SUPPORT_TOPIC)
    if blocks_proactive_offer(slots.get("context") or {}):
        return _no(OPEN_CASE)
    last = slots.get("last_evaluation")
    if last and last["outcome"] in (ce.DECLINED, ce.NEEDS_REVIEW, ce.NEEDS_DATA):
        return _no(RECENT_DECLINE)
    if last and last["outcome"] in (ce.ELIGIBLE, ce.ELIGIBLE_PROVISIONAL):
        return _no("ALREADY_EVALUATED")      # ya tiene una propuesta: se le resume, no se le ofrece otra

    profile = get_profile(ctx)
    if not profile["accepts_marketing"]:
        return _no(NO_CONSENT)

    info = offer_rates(ctx)          # solo datos del banco: nunca el ingreso declarado en el chat
    probe = info["probe"].decision
    if probe.outcome != ce.ELIGIBLE or not info["rates"] or not probe.max_amount or probe.max_amount <= 0:
        return _no(NOT_PREAPPROVED)

    lang, ccy = session.language, info["ccy"]
    fmt = {"first_name": session.first_name or "", "max_amount": fmt_money(probe.max_amount, ccy, 0),
           "months": str(DEFAULT_MONTHS["personal_loan"]), "rate": fmt_pct(info["rates"]["personal_loan"]),
           "product": templates.PRODUCT_NAME[lang]["personal_loan"]}
    evidence = {"product": "personal_loan", "indicative_max_amount": round(probe.max_amount, 2),
                "rate_pct": round(info["rates"]["personal_loan"], 2), "band": probe.band,
                "policy_version": probe.policy_version, "basis": "bank_data_only"}
    log(logger, "proactive_decision", reason=OK, make=True)
    return OfferDecision(True, OK, fmt, evidence)


def _no(reason: str) -> OfferDecision:
    log(logger, "proactive_decision", reason=reason, make=False)
    return OfferDecision(False, reason)
