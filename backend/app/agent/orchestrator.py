"""Orquestador: maquina de estados del chat de credito.

Flujo por turno:  mensaje -> NLU (LLM o reglas) -> validacion en codigo -> accion/herramienta/politica
                  -> hechos verificados -> texto (plantilla es/pt, opcionalmente reescrito por el LLM).
El LLM nunca decide: la elegibilidad sale de app.policy.credit_engine y las acciones, de tools.py.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import json

from app.agent import documents, money, proactive, support, templates
from app.agent.evidence import build_evidence
from app.agent.handoff import build_summary
from app.agent.language import norm, parse_amounts, parse_months
from app.agent.llm import LLM, MockLLM
from app.agent.nlu import HUMAN_REQUEST, NLUResult
from app.agent.tools import (DEFAULT_MONTHS, SUPPORTED_PRODUCTS, HandoffQueue, ToolContext, evaluate_credit,
                             get_customer_context, get_profile, new_ticket_id, offer_rates, utc_iso)
from app.core.fmt import fmt_money, fmt_pct
from app.core.pdf import render_summary_pdf
from app.core.sessions import Session
from app.logging_setup import log
from app.policy import credit_engine as ce

logger = logging.getLogger(__name__)
MAX_REPLY_CHARS = 1200
# Solo estos mensajes pueden ser reescritos por el LLM. Decisiones de credito, ofertas, derivaciones y avisos legales
# salen siempre de la plantilla revisada: el guardia de numeros no detecta frases nuevas que cambien el compromiso.
DEFAULT_REWRITE_KINDS = frozenset({"thanks", "closing", "goodbye", "unknown", "ask_amount", "ask_income",
                                   "handoff_declined", "offer_declined", "offer_accepted",
                                   # soporte: tono, sin decisiones ni datos de la cuenta (los mensajes de productos y de casos
                                   # llevan hechos del banco y salen siempre de la plantilla)
                                   "other_topic", "incident", "detail_noted", "handoff_declined_support", "case_skip"})
# Casos de soporte en curso: el cliente esta contando algo y la derivacion espera su confirmacion
EMPATHY_EVERY_N_TURNS = 3


@dataclass
class ChatReply:
    reply: str
    language: str
    intent: str
    outcome: str | None = None
    handoff_ticket: str | None = None
    suggested_replies: list[str] = field(default_factory=list)
    awaiting: str | None = None
    llm_rewritten: bool = False
    proactive_offer: bool = False
    summary_ready: bool = False          # la respuesta incluye el resumen final de la propuesta
    email: dict | None = None            # correo con el PDF (SIMULADO en el prototipo): {to, status, id}
    evidence: dict | None = None         # lo que el agente hizo de verdad en el turno (agent/evidence.py); None si no uso herramientas


def _conv_dict(c: money.Conversion) -> dict:
    from datetime import date as _date

    y, m, d = (c.quote.as_of or "1970-01-01").split("-")
    return {"amount_src": c.amount_src, "src": c.src, "amount_dst": c.amount_dst, "dst": c.dst, "rate": c.quote.rate,
            "as_of": c.quote.as_of, "as_of_fmt": f"{d}/{m}/{y}", "rate_text": c.rate_text}


def _digit_runs(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


# El asistente nunca se hace pasar por una persona: un texto que lo afirme se descarta siempre.
_CLAIMS_HUMAN = re.compile(
    r"\b(soy|sou)\s+(una?\s+|um\s+|uma\s+)?(persona|pessoa|humano|humana|agente humano|ejecutiv[oa]|asesor[a]?|consultor[a]?)\b"
    r"|\bno soy (un |una )?(robot|bot|ia|inteligencia artificial)\b|\bn[aã]o sou (um |uma )?(rob[oô]|bot|ia|intelig[eê]ncia artificial)\b",
    re.IGNORECASE)


# Promesas que el asistente no puede cumplir (resultado, plazo, reembolso): un texto que las contenga se descarta siempre.
_PROMISES = re.compile(
    r"\b(garantiz\w*|garant[oi]\w*|prometo|prometemos|le aseguro|aseguro que|reembols\w*|devolver[ea]mos|devolveremos|"
    r"devolvemos|compensar[ea]mos|resolver[ea]mos|solucionar[ea]mos|resolveremos|vamos a resolver|vamos a solucionar|"
    r"vamos resolver|sera (resuelto|solucionado|resolvido)|se resolvera|se solucionara|se devolvera|lo antes posible|"
    r"cuanto antes lo resuel\w*)\b")


def safe_text(candidate: str, facts: dict) -> bool:
    """Acepta el texto del LLM solo si no introduce numeros ajenos a los hechos, no se hace pasar por una persona, no hace
    promesas y tiene tamano razonable. Si el mensaje espera una respuesta (p. ej. '¿lo conecto?'), debe seguir preguntandolo."""
    allowed = _digit_runs(" ".join(facts.get("fmt", {}).values()))
    return (0 < len(candidate) <= MAX_REPLY_CHARS and _digit_runs(candidate) <= allowed
            and not _CLAIMS_HUMAN.search(candidate) and not _PROMISES.search(norm(candidate))
            and (not facts.get("awaiting") or "?" in candidate))


def validate_nlu(nlu: NLUResult, message: str) -> NLUResult:
    """Contrasta en codigo lo que dijo el LLM con el texto original: montos y plazos deben aparecer en el mensaje."""
    amounts, months = parse_amounts(message), parse_months(message)
    upd: dict = {}
    for key in ("amount", "declared_income"):
        v = getattr(nlu, key)
        if v is not None and not any(abs(v - a) <= 1e-6 * max(a, 1) for a in amounts):
            upd[key] = None
    if nlu.months is not None and nlu.months != months:
        upd["months"] = None
    # Una derivacion a humano es una accion: solo se acepta si el cliente la pidio de forma explicita en su texto.
    if nlu.intent == "request_human" and not HUMAN_REQUEST.search(norm(message)):
        upd["intent"] = "other_topic" if nlu.sensitive_topic else "unknown"
    return nlu.model_copy(update=upd) if upd else nlu


class Orchestrator:
    def __init__(self, repo, policy: dict, llm: LLM, queue: HandoffQueue,
                 rewrite_kinds: frozenset[str] = DEFAULT_REWRITE_KINDS, outbox=None):
        self.repo, self.policy, self.llm, self.queue, self.outbox = repo, policy, llm, queue, outbox
        self.rewrite_kinds = rewrite_kinds
        self._fallback = MockLLM()

    # ------------------------------------------------------------------ entrada
    def handle(self, session: Session, message: str) -> ChatReply:
        nlu = self._understand(session, message)
        if nlu.language:
            session.language = nlu.language
        lang = session.language
        session.history.append({"role": "user", "text": message})
        ctx = ToolContext(session.customer_id, self.repo, self.policy)
        if nlu.sentiment == "negative" or nlu.sensitive_topic:
            session.slots["no_offers"] = True  # en toda la sesion: ninguna oferta comercial
        session.slots.setdefault("sentiments", []).append(nlu.sentiment or "neutral")   # curva de animo para el resumen del asesor

        facts = self._dispatch(session, ctx, nlu, message)
        facts["variant"] = len(session.history) // 2        # rota las formulaciones de los mensajes de bajo riesgo
        self._empathy(session, nlu, facts)
        reply = self._render(facts, lang)
        reply.evidence = build_evidence(ctx.trace, facts)
        session.history.append({"role": "assistant", "text": reply.reply})
        log(logger, "turn", intent=nlu.intent, kind=facts["kind"], outcome=facts.get("outcome"),
            awaiting=facts.get("awaiting"), proactive=reply.proactive_offer, llm=self.llm.name,
            llm_rewritten=reply.llm_rewritten, lang=lang)
        return reply

    @staticmethod
    def _empathy(session: Session, nlu: NLUResult, facts: dict) -> None:
        """Si el cliente se muestra molesto, el mensaje abre reconociendolo (una frase fija revisada). No se repite en cada
        turno: seria artificial. Los incidentes ya traen su propio reconocimiento."""
        turn = len(session.history) // 2
        if (nlu.sentiment == "negative" and facts["kind"] not in ("incident", "handoff_created", "application_ready")
                and turn - session.slots.get("empathy_turn", -EMPATHY_EVERY_N_TURNS) >= EMPATHY_EVERY_N_TURNS):
            facts["pre"] = ["empathy_negative"]
            session.slots["empathy_turn"] = turn

    def _understand(self, session: Session, message: str) -> NLUResult:
        pending = session.slots.get("awaiting") in ("confirm_handoff", "offer_interest")  # hay una pregunta de si/no
        try:
            nlu = self.llm.extract(message, session.language, pending)
        except Exception as exc:  # fallo de red, JSON invalido, etc.: respaldo por reglas
            log(logger, "nlu_fallback", error=type(exc).__name__)
            nlu = self._fallback.extract(message, session.language, pending)
        return validate_nlu(nlu, message)

    # ------------------------------------------------------------------ despacho
    def _dispatch(self, session: Session, ctx: ToolContext, nlu: NLUResult, message: str) -> dict:
        awaiting = session.slots.pop("awaiting", None)
        amounts = parse_amounts(message)
        intent = nlu.intent
        mention = money.detect_currency(message)
        if mention.unsupported and amounts and (awaiting in ("amount", "income") or intent in (
                "credit_eligibility", "update_income", "unknown")):
            if awaiting:
                session.slots["awaiting"] = awaiting  # sigue esperando el dato, ahora en una moneda soportada
            return self._facts("currency_unsupported", intent, awaiting=awaiting, ccy=mention.unsupported,
                               supported=", ".join(money.SUPPORTED))

        if awaiting == "case_intro":                              # abrimos con un caso pendiente: "¿quiere que le cuente?"
            if intent == "confirm_yes":
                return self._support_case_status(session, ctx, intent, "")     # el "si" no es un dato del caso: no se anota
            if intent == "confirm_no":
                return self._facts("case_skip", intent, suggest="start")
        if awaiting == "confirm_handoff":
            # Ya no se encadena una oferta de credito tras atender otro tema: el cliente vino por otra cosa.
            if intent == "confirm_yes":
                return self._handoff(session, session.slots.pop("handoff_reason", "USER_REQUEST"))
            if intent == "confirm_no":
                reason = session.slots.pop("handoff_reason", "USER_REQUEST")
                return self._facts("handoff_declined_support" if reason in support.SUPPORT_REASONS else "handoff_declined", intent)
            # Cuenta mas detalles en vez de decir si/no: se anotan (un tema generico o ininteligible no cambia el motivo).
            if session.slots.get("case") and (intent == "unknown" or (intent == "other_topic" and not nlu.sensitive_topic)):
                return self._collect_detail(session, message)
        if awaiting == "offer_interest":
            if intent == "confirm_yes":
                session.slots["pending_request"] = {"product": "personal_loan", "amount": None,
                                                    "months": DEFAULT_MONTHS["personal_loan"]}
                session.slots["awaiting"] = "amount"
                return self._facts("offer_accepted", intent, awaiting="amount", months=str(DEFAULT_MONTHS["personal_loan"]))
            if intent == "confirm_no":
                session.slots["offer_declined"] = True
                return self._facts("offer_declined", intent)
        if awaiting == "proceed":
            if intent == "confirm_yes":
                return self._start_application(session, ctx)
            if intent == "confirm_no":
                session.slots["proceed_declined"] = True
                return self._facts("proceed_declined", intent)
        if awaiting in ("docs_all", "doc_item"):
            reply = self._docs_answer(session, ctx, awaiting, intent)
            if reply is not None:
                return reply
        if awaiting == "amount" and amounts and intent in ("unknown", "credit_eligibility", "confirm_yes"):
            nlu = nlu.model_copy(update={"intent": "credit_eligibility", "amount": amounts[0]})
            intent = "credit_eligibility"
        if awaiting == "income" and amounts and intent in ("unknown", "update_income"):
            nlu = nlu.model_copy(update={"intent": "update_income", "declared_income": amounts[0]})
            intent = "update_income"

        session.unknown_streak = session.unknown_streak + 1 if intent == "unknown" else 0

        if intent == "ask_identity":
            return self._facts("identity", intent, suggest="start")      # respuesta honesta: es un asistente virtual, no una persona
        if intent == "request_human":
            return self._handoff(session, "USER_REQUEST")
        if intent == "greeting":
            return self._facts("greeting", intent, first_name=session.first_name or "", suggest="start")
        if intent in ("thanks", "closing"):
            return self._close_turn(session, ctx, intent)
        if intent == "case_status":
            return self._support_case_status(session, ctx, intent, message)
        if nlu.sensitive_topic and intent in ("other_topic", "account_inquiry"):
            return self._support_incident(session, intent, message)
        if intent == "account_inquiry":
            return self._support_account(session, ctx, intent, message)
        if intent == "other_topic":
            return self._support_other(session, intent, message)
        if intent == "credit_offers":
            return self._offers(session, ctx)
        if intent == "credit_eligibility":
            return self._eligibility(session, ctx, nlu, mention)
        if intent == "update_income":
            return self._income(session, ctx, nlu, mention)
        # confirm_yes/no sin nada pendiente, o unknown
        if session.unknown_streak >= 2:
            return self._offer_handoff(session, "UNCLEAR", intent)
        return self._facts("unknown", intent, suggest="start")

    # ------------------------------------------------------------------ oferta proactiva
    def _with_offer(self, session: Session, ctx: ToolContext, facts: dict) -> dict:
        """Encadena la oferta proactiva al mensaje si la politica lo permite (consentimiento, preaprobacion, momento)."""
        d = proactive.decide(session, ctx)
        if not d.make:
            return facts
        session.slots["offer_made"] = True
        session.slots["awaiting"] = "offer_interest"
        session.actions.append({"type": "proactive_offer_made", "verified": True, **d.evidence})
        session.slots.setdefault("verified_facts", []).append({"type": "proactive_offer", **d.evidence})
        facts["kind2"] = "offer_proactive"
        facts["fmt"].update(d.fmt)
        facts.update(awaiting="offer_interest", suggest="yes_no", proactive_offer=True)
        return facts

    # ------------------------------------------------------------------ soporte (productos, casos, incidentes, otros temas)
    # Regla comun: el agente responde lo que puede con datos verificados del banco (existencia de productos, casos abiertos),
    # anota lo que el cliente cuenta como DECLARADO y solo ofrece conectar con un asesor; la derivacion se ejecuta con un "si".
    def _support(self, session: Session, topic: str, reason: str, kind: str, intent: str, message: str,
                 family: str | None = None, **fmt: str) -> dict:
        support.add_note(session.slots, topic, message, family)
        session.slots["awaiting"] = "confirm_handoff"
        session.slots["handoff_reason"] = reason
        return self._facts(kind, intent, awaiting="confirm_handoff", suggest="yes_no", **fmt)

    def _support_account(self, session: Session, ctx: ToolContext, intent: str, message: str) -> dict:
        """'¿Tengo una tarjeta?', 'mi saldo': confirma que el producto existe (tipo y terminacion) y deriva el detalle."""
        context = get_customer_context(ctx)
        session.slots["context"] = context
        family, hint = support.mentioned_family(message)
        kind, data = support.product_answer(context["products"], family, hint, session.language)
        return self._support(session, "account_inquiry", "ACCOUNT_DETAIL", kind, intent, message, family, **data)

    def _support_case_status(self, session: Session, ctx: ToolContext, intent: str, message: str) -> dict:
        """Lo que el banco ve del caso abierto mas relevante (categoria, fecha, estado). El avance lo informa un asesor."""
        context = get_customer_context(ctx)
        session.slots["context"] = context
        top, lang = context["most_relevant"], session.language
        if top is None:
            return self._support(session, "case_status", "CASE_FOLLOWUP", "case_status_none", intent, message)
        more = templates.render("case_more", lang, {}) if context["counts"]["open"] > 1 else ""
        return self._support(session, "case_status", "CASE_FOLLOWUP", "case_status_open", intent, message,
                             case=support.case_phrase(top, lang), status=support.status_text(top, lang), more=more)

    def _support_incident(self, session: Session, intent: str, message: str) -> dict:
        """Fraude, cargo no reconocido, robo, reclamo nuevo: se reconoce, se pide lo basico para el asesor y se ofrece conectar."""
        family, _ = support.mentioned_family(message)
        return self._support(session, "incident", "INCIDENT", "incident", intent, message, family)

    def _support_other(self, session: Session, intent: str, message: str) -> dict:
        """Tema que el asistente no resuelve (horarios, claves, app...): se anota lo que cuenta y se ofrece conectar."""
        return self._support(session, "other", "OTHER_TOPIC", "other_topic", intent, message)

    def _collect_detail(self, session: Session, message: str) -> dict:
        """El cliente conto mas detalles en lugar de responder si/no: se anotan y se vuelve a preguntar por la derivacion."""
        session.unknown_streak = 0
        case = support.add_note(session.slots, session.slots["case"]["topic"], message)
        session.slots["awaiting"] = "confirm_handoff"        # la razon de la derivacion sigue en slots["handoff_reason"]
        session.actions.append({"type": "customer_detail_noted", "notes": len(case["notes"]), "verified": False})
        return self._facts("detail_noted", "unknown", awaiting="confirm_handoff", suggest="yes_no")

    # ------------------------------------------------------------------ casos
    def _eligibility(self, session: Session, ctx: ToolContext, nlu: NLUResult, mention: money.CurrencyMention) -> dict:
        pending = session.slots.get("pending_request") or {}
        product = nlu.product or pending.get("product") or "personal_loan"
        if product not in SUPPORTED_PRODUCTS:
            return self._offer_handoff(session, "UNSUPPORTED_PRODUCT", "credit_eligibility", kind="unsupported_product")
        months = nlu.months or DEFAULT_MONTHS[product]
        conv = pending.get("conv") if pending.get("product") == product else None
        if nlu.amount is not None:
            amount, conv, err = self._to_local(session, ctx, nlu.amount, mention)
            if err:
                return self._facts("fx_unavailable", "credit_eligibility", awaiting="amount", ccy=err)
        else:
            amount = pending.get("amount") if pending.get("product") == product and not nlu.product else None
        if amount is None:
            session.slots["awaiting"] = "amount"
            session.slots["pending_request"] = {"product": product, "amount": None, "months": months}
            return self._facts("ask_amount", "credit_eligibility", awaiting="amount",
                               product=templates.PRODUCT_NAME[session.language][product], months=str(months))
        session.slots["pending_request"] = {"product": product, "amount": amount, "months": months, "conv": conv}
        return self._evaluate(session, ctx, "credit_eligibility")

    def _income(self, session: Session, ctx: ToolContext, nlu: NLUResult, mention: money.CurrencyMention) -> dict:
        profile = get_profile(ctx)
        if nlu.declared_income is None:
            session.slots["awaiting"] = "income"
            return self._facts("ask_income", "update_income", awaiting="income", ccy=profile["income_ccy"])
        inc, conv, err = self._to_local(session, ctx, nlu.declared_income, mention)
        if err:
            return self._facts("fx_unavailable", "update_income", awaiting="income", ccy=err)
        session.slots["declared_income"] = inc
        session.slots["declared_income_conv"] = conv
        on_file = profile["monthly_income"]
        if on_file and inc > on_file * (1 + self.policy["declared_income"]["max_uplift_without_review"]):
            return self._offer_handoff(session, "INCOME_UPLIFT_REVIEW", "update_income", kind="income_review")
        if session.slots.get("pending_request", {}).get("amount"):
            return self._evaluate(session, ctx, "update_income")  # recalculo inmediato con el dato nuevo
        return self._facts("income_saved", "update_income", income=self._m(session, inc, profile["income_ccy"]),
                           fx=self._fx_note(session))

    def _offers(self, session: Session, ctx: ToolContext) -> dict:
        info = offer_rates(ctx, session.slots.get("declared_income"))
        probe, ccy = info["probe"], info["ccy"]
        if not info["rates"]:
            return self._from_decision(session, "credit_offers", probe.decision, ccy)
        names = templates.PRODUCT_NAME[session.language]
        lines = ", ".join(f"{names[p]}: {fmt_pct(r)}" for p, r in info["rates"].items())
        d = probe.decision
        if d.max_amount:
            cap = templates.render("offers_capacity", session.language,
                                   {"months": str(DEFAULT_MONTHS["personal_loan"]), "max_amount": self._m(session, d.max_amount, ccy)})
        else:
            cap = templates.render("offers_no_capacity", session.language, {})
        session.slots.setdefault("verified_facts", []).append(
            {"type": "offer_rates", "rates": {k: round(v, 2) for k, v in info["rates"].items()},
             "policy_version": self.policy["version"]})
        return self._facts("offers", "credit_offers", outcome="offers", lines=lines, capacity=cap)

    def _evaluate(self, session: Session, ctx: ToolContext, intent: str) -> dict:
        req = session.slots["pending_request"]
        res = evaluate_credit(ctx, req["product"], req["amount"], req["months"], session.slots.get("declared_income"))
        d = res.decision
        evaluation = {"request": res.request, "outcome": d.outcome, "reasons": d.reasons, "band": d.band,
                      "rate_pct": d.rate_pct, "payment": d.payment, "dti_after": d.dti_after,
                      "max_amount": d.max_amount, "policy_version": d.policy_version,
                      "income_declared_unverified": res.income_declared}
        session.slots["last_evaluation"] = evaluation
        session.actions.append({"type": "credit_evaluation", "outcome": d.outcome, "verified": True,
                                "policy_version": d.policy_version})
        session.slots.setdefault("verified_facts", []).append({"type": "credit_evaluation", **evaluation})
        if d.outcome in (ce.ELIGIBLE, ce.ELIGIBLE_PROVISIONAL):
            p = self.policy
            facts = self._facts(d.outcome, intent, outcome=d.outcome,
                               product=templates.PRODUCT_NAME[session.language][req["product"]],
                               amount=self._m(session, req["amount"], res.ccy), months=str(req["months"]),
                               payment=self._m(session, d.payment, res.ccy, 2), rate=fmt_pct(d.rate_pct),
                               dti=fmt_pct(d.dti_after * 100), max_dti=fmt_pct(p["max_dti"] * 100),
                               fx=self._fx_note(session))
            facts["kind2"] = "ask_proceed"                      # "¿Le gustaria que avancemos con la solicitud?"
            facts.update(awaiting="proceed", suggest="yes_no")
            session.slots["awaiting"] = "proceed"
            return facts
        return self._from_decision(session, intent, d, res.ccy, req)

    def _from_decision(self, session: Session, intent: str, d: ce.Decision, ccy: str, req: dict | None = None) -> dict:
        reason = d.reasons[0] if d.reasons else ""
        if d.outcome == ce.NEEDS_DATA:
            if "monthly_income" in d.missing and "credit_score" not in d.missing:
                session.slots["awaiting"] = "income"
                return self._facts("ask_income", intent, outcome=d.outcome, awaiting="income", ccy=ccy)
            return self._offer_handoff(session, "MISSING_DATA", intent, kind="needs_data_score", outcome=d.outcome)
        if d.outcome == ce.DECLINED and reason == "DTI_EXCEEDED" and req and (d.max_amount or 0) <= 0:
            return self._facts("declined_no_capacity", intent, outcome=d.outcome,
                               dti=fmt_pct(d.dti_after * 100), max_dti=fmt_pct(self.policy["max_dti"] * 100),
                               fx=self._fx_note(session))
        if d.outcome == ce.DECLINED and reason == "DTI_EXCEEDED" and req:
            return self._facts("declined_dti", intent, outcome=d.outcome,
                               dti=fmt_pct(d.dti_after * 100), max_dti=fmt_pct(self.policy["max_dti"] * 100),
                               months=str(req["months"]), max_amount=self._m(session, d.max_amount or 0, ccy),
                               fx=self._fx_note(session))
        if d.outcome == ce.DECLINED:
            return self._offer_handoff(session, "POLICY_DECLINED", intent, kind="declined_generic", outcome=d.outcome)
        return self._offer_handoff(session, reason or "MISSING_DATA", intent, kind="needs_review", outcome=d.outcome)

    # ------------------------------------------------------------------ solicitud y documentos
    def _doc_list(self, session: Session, ids: list[str]) -> str:
        names = templates.DOC_NAME[session.language]
        return templates.join_list([names[i] for i in ids], session.language)

    def _start_application(self, session: Session, ctx: ToolContext) -> dict:
        req = session.slots.get("pending_request") or {}
        ev = session.slots.get("last_evaluation") or {}
        if not req.get("amount") or ev.get("outcome") not in (ce.ELIGIBLE, ce.ELIGIBLE_PROVISIONAL):
            return self._facts("unknown", "confirm_yes", suggest="start")
        plan = documents.plan(self.policy, self.repo, ctx.customer_id, req["product"],
                              bool(ev.get("income_declared_unverified")))
        session.slots["application"] = {"status": "documents", "product": req["product"], "required": plan.required,
                                        "on_file": plan.on_file, "need": plan.need, "declared": [], "missing": [],
                                        "queue": [], "current": None}
        session.actions.append({"type": "application_started", "required": plan.required, "on_file": plan.on_file,
                                "verified": True})
        if not plan.need:                                        # el banco ya tiene todo lo necesario
            return self._finish_application(session, ctx)
        session.slots["awaiting"] = "docs_all"
        return self._facts("docs_request", "credit_eligibility", awaiting="docs_all", suggest="yes_no",
                           docs=self._doc_list(session, plan.need), lead="")

    def _docs_answer(self, session: Session, ctx: ToolContext, awaiting: str, intent: str) -> dict | None:
        """Responde a la pregunta de documentos. None = que siga el flujo general (pidio un asesor, se despide, etc.)."""
        app = session.slots.get("application")
        if not app or intent in ("request_human", "closing", "thanks", "other_topic", "greeting"):
            return None
        if intent not in ("confirm_yes", "confirm_no"):          # no entendio: se repite la misma pregunta
            session.slots["awaiting"] = awaiting
            lead = templates.REASK[session.language]
            if awaiting == "docs_all":
                return self._facts("docs_request", intent, awaiting="docs_all", suggest="yes_no", lead=lead,
                                   docs=self._doc_list(session, app["need"]))
            return self._facts("docs_item", intent, awaiting="doc_item", suggest="yes_no", lead=lead,
                               doc=self._doc_list(session, [app["current"]]))
        if awaiting == "docs_all":
            if intent == "confirm_yes":
                app["declared"] = list(app["need"])
                return self._finish_application(session, ctx)
            if len(app["need"]) == 1:                            # un solo documento y dijo que no: no se repite la pregunta
                return self._finish_application(session, ctx)
            app["queue"] = list(app["need"])                     # "no": se pregunta uno por uno
            return self._next_doc(session, ctx)
        (app["declared"] if intent == "confirm_yes" else app["missing"]).append(app["current"])
        return self._next_doc(session, ctx)

    def _next_doc(self, session: Session, ctx: ToolContext) -> dict:
        app = session.slots["application"]
        if not app["queue"]:
            return self._finish_application(session, ctx)
        app["current"] = app["queue"].pop(0)
        session.slots["awaiting"] = "doc_item"
        return self._facts("docs_item", "confirm_no", awaiting="doc_item", suggest="yes_no", lead="",
                           doc=self._doc_list(session, [app["current"]]))

    def _finish_application(self, session: Session, ctx: ToolContext) -> dict:
        app = session.slots["application"]
        app["missing"] = [d for d in app["need"] if d not in app["declared"]]
        if app["missing"]:
            app["status"] = "incomplete"
            session.actions.append({"type": "documents_pending", "missing": app["missing"], "verified": True})
            session.slots["awaiting"] = "confirm_handoff"
            session.slots["handoff_reason"] = "DOCS_INCOMPLETE"
            return self._facts("docs_incomplete", "confirm_no", awaiting="confirm_handoff", suggest="yes_no",
                               missing=self._doc_list(session, app["missing"]))
        app["status"] = "ready"
        facts = self._handoff(session, "APPLICATION_READY")      # todo en orden: se deriva a un asesor
        if facts["kind"] == "handoff_created":
            facts["kind"] = "application_ready"
        return self._with_conclusion(session, ctx, facts)

    # ------------------------------------------------------------------ resumen final y correo
    @staticmethod
    def _has_proposal(session: Session) -> bool:
        ev = session.slots.get("last_evaluation") or {}
        return ev.get("outcome") in (ce.ELIGIBLE, ce.ELIGIBLE_PROVISIONAL) and bool(session.slots.get("pending_request"))

    def _close_turn(self, session: Session, ctx: ToolContext, intent: str) -> dict:
        if self._has_proposal(session) and not session.slots.get("summary_delivered"):
            facts = self._with_conclusion(session, ctx, self._facts("closing_summary", intent))
            facts["extras"].append("goodbye")
            return facts
        base = self._facts(intent, intent)
        return base if self._has_proposal(session) else self._with_offer(session, ctx, base)

    def conclude(self, session: Session) -> ChatReply:
        """Cierre explicito de la conversacion (POST /end): resumen y aviso de correo si hay una propuesta."""
        ctx = ToolContext(session.customer_id, self.repo, self.policy)
        if self._has_proposal(session) and not session.slots.get("summary_delivered"):
            facts = self._with_conclusion(session, ctx, self._facts("closing_summary", "closing"))
            facts["extras"].append("goodbye")
        else:
            facts = self._facts("closing", "closing")
        session.slots["ended"] = True
        facts["variant"] = len(session.history) // 2
        reply = self._render(facts, session.language)
        reply.evidence = build_evidence(ctx.trace, facts)
        session.history.append({"role": "assistant", "text": reply.reply})
        return reply

    def _summary_fmt(self, session: Session, ctx: ToolContext) -> dict[str, str]:
        lang, req, ev = session.language, session.slots["pending_request"], session.slots["last_evaluation"]
        ccy = get_profile(ctx)["income_ccy"]
        tx, app = templates.SUMMARY_TEXT[lang], session.slots.get("application") or {}
        if app.get("status") == "ready":
            docs_status = tx["docs_complete"]
        elif app.get("status") == "incomplete":
            docs_status = tx["docs_pending"].format(missing=self._doc_list(session, app["missing"]))
        else:
            docs_status = tx["docs_not_started"]
        ticket = session.handoff["ticket_id"] if session.handoff else ""
        email = self.repo.contact_email_masked(ctx.customer_id) or ""
        months = str(req["months"])
        return {
            "product": templates.PRODUCT_NAME[lang][req["product"]], "amount": self._m(session, req["amount"], ccy),
            "months": months, "rate": fmt_pct(ev["rate_pct"]), "payment": self._m(session, ev["payment"], ccy, 2),
            "dti": fmt_pct(ev["dti_after"] * 100), "max_dti": fmt_pct(self.policy["max_dti"] * 100),
            "status": tx["provisional"] if ev["outcome"] == ce.ELIGIBLE_PROVISIONAL else tx["eligible"],
            "docs_status": docs_status, "ticket": ticket, "ticket_line": tx["ticket_line"].format(ticket=ticket) if ticket else "",
            "email": email,
        }

    def _with_conclusion(self, session: Session, ctx: ToolContext, facts: dict) -> dict:
        """Agrega el resumen de la propuesta y el aviso de que el detalle se envia por correo en un PDF."""
        if session.slots.get("summary_delivered") or not self._has_proposal(session):
            return facts
        fmt = self._summary_fmt(session, ctx)
        facts["fmt"].update(fmt)
        facts["extras"] = ["summary", "email_notice" if fmt["email"] else "email_notice_noaddr"]
        facts["summary"] = True
        facts["income_declared"] = bool(session.slots["last_evaluation"].get("income_declared_unverified"))   # la propuesta se baso en un ingreso sin verificar
        record = self._queue_email(session, ctx, fmt)
        if record:
            facts["email"] = {"to": fmt["email"] or None, "status": record["status"], "id": record["id"]}
        session.slots["summary_delivered"] = True
        return facts

    def _queue_email(self, session: Session, ctx: ToolContext, fmt: dict[str, str]) -> dict | None:
        if self.outbox is None:
            return None
        lang = session.language
        values = {**fmt, "months_text": f"{fmt['months']} meses", "dti_text": f"{fmt['dti']} (max. {fmt['max_dti']})"}
        rows = [(label, values[key]) for key, label in templates.SUMMARY_LABELS[lang]]
        notes = list(templates.PDF_NOTES[lang])
        fx = self._fx_note(session).strip()
        if fx:
            notes.insert(0, fx)
        pdf = render_summary_pdf(lang=lang, first_name=session.first_name or "", rows=rows, notes=notes,
                                 ticket=fmt["ticket"] or None, policy_version=self.policy["version"])
        record = self.outbox.queue(customer_id=ctx.customer_id, to_masked=fmt["email"] or None,
                                   subject=templates.EMAIL_SUBJECT[lang], pdf=pdf, language=lang,
                                   ticket_id=fmt["ticket"] or None)
        session.slots["summary_email"] = record
        session.actions.append({"type": "summary_email_queued", "email_id": record["id"], "status": record["status"],
                                "to_masked": record["to_masked"], "verified": True})
        if session.handoff:                                      # el agente humano ve el resumen y el correo en su ticket
            self.queue.update(session.handoff["ticket_id"], offer_summary=fmt, summary_email=record,
                              actions_taken=list(session.actions))
        return record

    # ------------------------------------------------------------------ monedas
    def _to_local(self, session: Session, ctx: ToolContext, value: float, mention: money.CurrencyMention):
        """(valor en la moneda local, conversion o None, error o None). La politica trabaja en la moneda del ingreso."""
        local = get_profile(ctx)["income_ccy"]
        spoken = money.resolve(mention, local)
        if spoken is None:
            return value, None, None                      # no dijo moneda: se asume la local y se conserva lo que haya
        if spoken == local:
            session.slots["spoken_ccy"] = None
            return value, None, None
        conv = money.convert(self.repo, value, spoken, local)
        if conv is None:
            ctx.trace.append({"tool": "fx_rates", "status": "failed", "src": spoken, "dst": local})
            return value, None, spoken                    # sin tasa disponible: se avisa, no se inventa
        ctx.trace.append({"tool": "fx_rates", "status": "success", "src": spoken, "dst": local,
                          "rate": conv.quote.rate, "as_of": conv.quote.as_of})
        session.slots["spoken_ccy"] = spoken
        # Los equivalentes se muestran con la MISMA tasa de esta conversion: las tasas directa e inversa del dataset no son
        # exactamente reciprocas y, si no, pedir 1.000 USD se mostraria como "≈ 1.023 USD" al volver.
        session.slots["spoken_fx"] = {"ccy": spoken, "local": local, "rate": conv.quote.rate}
        return conv.amount_dst, _conv_dict(conv), None

    def _m(self, session: Session, amount: float, ccy: str, decimals: int = 0) -> str:
        """Monto en la moneda local y, si el cliente habla en otra, su equivalente aproximado."""
        base = fmt_money(amount, ccy, decimals)
        spoken, fx = session.slots.get("spoken_ccy"), session.slots.get("spoken_fx")
        if spoken and spoken != ccy and fx and fx["ccy"] == spoken and fx["local"] == ccy:
            return f"{base} (≈ {fmt_money(amount / fx['rate'], spoken, decimals)})"
        return base

    def _fx_note(self, session: Session) -> str:
        """Aviso de conversion (monto original, equivalente, tasa y fecha) mientras se use un monto convertido."""
        notes = []
        for conv in (session.slots.get("pending_request", {}).get("conv"), session.slots.get("declared_income_conv")):
            if conv:
                notes.append(templates.render("fx_note", session.language, {
                    "src_amount": fmt_money(conv["amount_src"], conv["src"], 0), "dst_amount": fmt_money(conv["amount_dst"], conv["dst"], 0),
                    "date": conv["as_of_fmt"], "rate": conv["rate_text"]}))
        return " ".join(notes) + (" " if notes else "")

    # ------------------------------------------------------------------ derivacion
    def _offer_handoff(self, session: Session, reason: str, intent: str, kind: str = "needs_review",
                       outcome: str | None = None) -> dict:
        """Pide confirmacion antes de derivar (la accion se ejecuta solo con un 'si' explicito)."""
        session.slots["awaiting"] = "confirm_handoff"
        session.slots["handoff_reason"] = reason
        text = templates.REASON_TEXT[session.language].get(reason, "")
        return self._facts(kind, intent, outcome=outcome, awaiting="confirm_handoff", suggest="yes_no", reason=text)

    def _handoff(self, session: Session, reason: str) -> dict:
        if session.handoff:
            return self._facts("handoff_exists", "request_human", ticket=session.handoff["ticket_id"],
                               handoff_ticket=session.handoff["ticket_id"])
        ticket, now = new_ticket_id(), utc_iso()
        questions = {
            "USER_REQUEST": ["Motivo de la consulta no especificado por el cliente"],
            "MISSING_DATA": ["Completar score o ingreso faltantes del cliente"],
            "INCOME_UPLIFT_REVIEW": ["Verificar el ingreso declarado, muy superior al registrado"],
            "UNSUPPORTED_PRODUCT": ["Atender solicitud de tarjeta de credito"],
            "UNCLEAR": ["El asistente no logro entender la consulta"],
            "POLICY_DECLINED": ["El cliente puede pedir revision manual del rechazo"],
            "APPLICATION_READY": ["Verificar los documentos que el cliente declaro tener y el ingreso; completar la revision final"],
            "DOCS_INCOMPLETE": ["Ayudar al cliente a completar la documentacion pendiente: "
                                + ", ".join((session.slots.get("application") or {}).get("missing", []))],
            "ACCOUNT_DETAIL": ["Atender la consulta sobre el producto: el cliente pidio detalle (saldos o movimientos) que el "
                               "asistente no muestra; el asistente solo confirmo que el producto existe"],
            "INCIDENT": ["Atender un incidente que reporta el cliente (fraude, cargo no reconocido, robo u otro): validar los "
                         "hechos y tomar las medidas de seguridad que correspondan"],
            "CASE_FOLLOWUP": ["Informar al cliente el avance de su caso abierto (el asistente solo le dijo categoria, fecha y estado)"],
            "OTHER_TOPIC": ["Atender el tema que el cliente describio (ver case_notes); el asistente no lo resuelve"],
        }.get(reason, ["Revisar el caso segun el motivo indicado"])
        if reason == "USER_REQUEST" and session.slots.get("case"):   # pidio un humano en medio de un tema: retomarlo
            questions = ["Retomar el tema que el cliente describio en el chat (ver case_notes y topic)"]
        session.actions.append({"type": "handoff_created", "ticket_id": ticket, "verified": True, "at": now})
        session.handoff = {"ticket_id": ticket, "created_at": now, "reason": reason}
        summary = build_summary(session, ticket, now, reason, session.slots.get("last_evaluation"), questions)
        self._improve_narrative(summary)
        self.queue.add(summary)
        return self._facts("handoff_created", "request_human", outcome="handed_off", ticket=ticket, handoff_ticket=ticket)

    def _improve_narrative(self, summary: dict) -> None:
        """Si hay LLM, su parrafo reemplaza al de reglas SOLO si no introduce datos ajenos al resumen ni promesas. Un fallo
        o un texto invalido deja el parrafo determinista: el asesor siempre recibe un resumen util."""
        summarize = getattr(self.llm, "summarize", None)
        if summarize is None:
            return
        try:
            candidate = summarize(summary)
        except Exception as exc:
            log(logger, "summary_fallback", error=type(exc).__name__)
            return
        allowed = _digit_runs(json.dumps(summary, ensure_ascii=False, default=str))
        if (candidate and len(candidate) <= 900 and _digit_runs(candidate) <= allowed
                and not _PROMISES.search(norm(candidate)) and not _CLAIMS_HUMAN.search(candidate)):
            summary["narrative"], summary["narrative_source"] = candidate, "llm"

    # ------------------------------------------------------------------ salida
    @staticmethod
    def _facts(kind: str, intent: str, outcome: str | None = None, awaiting: str | None = None,
               suggest: str | None = None, handoff_ticket: str | None = None, **fmt: str) -> dict:
        return {"kind": kind, "intent": intent, "outcome": outcome, "awaiting": awaiting, "suggest": suggest,
                "handoff_ticket": handoff_ticket, "proactive_offer": False,
                "fmt": {k: str(v) for k, v in fmt.items()}}

    def _render(self, facts: dict, lang: str) -> ChatReply:
        draft = templates.render_facts(facts, lang)
        text, rewritten = draft, False
        if facts["kind"] in self.rewrite_kinds and not facts.get("kind2") and not facts.get("extras"):
            try:
                candidate = self.llm.compose(facts, lang, draft)
                if candidate and safe_text(candidate, facts):
                    text, rewritten = candidate, True
            except Exception as exc:
                log(logger, "compose_fallback", error=type(exc).__name__)
        sug = templates.SUGGESTIONS[facts["suggest"]][lang] if facts.get("suggest") else []
        return ChatReply(reply=text, language=lang, intent=facts["intent"], outcome=facts.get("outcome"),
                         handoff_ticket=facts.get("handoff_ticket"), suggested_replies=sug,
                         awaiting=facts.get("awaiting"), llm_rewritten=rewritten,
                         proactive_offer=facts.get("proactive_offer", False),
                         summary_ready=bool(facts.get("summary")), email=facts.get("email"))
