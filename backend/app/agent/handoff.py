"""Resumen estructurado para el agente humano. Sin cadena de pensamiento del modelo: solo hechos verificados,
acciones ejecutadas, la evidencia del motor de politica y lo que el cliente conto (marcado como DECLARADO, sin verificar).

Se arma con todo lo acumulado en la sesion: contexto del cliente (casos abiertos, productos), tema y notas, animo a lo largo
de la conversacion, prioridad y ruta sugeridas. `narrative` es un parrafo corto para leer de un vistazo: lo escribe el codigo
(determinista) y, si hay LLM, puede reemplazarlo siempre que no introduzca datos ajenos al resumen (ver orchestrator).
"""
from __future__ import annotations

import re

from app.agent.language import norm
from app.agent.support import redact, status_text
from app.core.sessions import Session

TRANSCRIPT_TAIL = 8
TOP_CASES = 5

REASON_LABEL = {
    "USER_REQUEST": "el cliente pidió hablar con una persona", "OTHER_TOPIC": "tema que el asistente no resuelve",
    "ACCOUNT_DETAIL": "consulta de detalle de un producto (saldos o movimientos)", "INCIDENT": "incidente reportado por el cliente",
    "CASE_FOLLOWUP": "seguimiento de un caso abierto", "UNCLEAR": "el asistente no logró entender la consulta",
    "MISSING_DATA": "faltan datos para evaluar el crédito", "INCOME_UPLIFT_REVIEW": "ingreso declarado muy superior al registrado",
    "UNSUPPORTED_PRODUCT": "producto que el asistente no gestiona", "POLICY_DECLINED": "crédito no elegible por política",
    "APPLICATION_READY": "solicitud de crédito lista para revisión final", "DOCS_INCOMPLETE": "solicitud con documentación pendiente",
}
CREDIT_REASONS = frozenset({"MISSING_DATA", "INCOME_UPLIFT_REVIEW", "UNSUPPORTED_PRODUCT", "POLICY_DECLINED",
                            "APPLICATION_READY", "DOCS_INCOMPLETE"})
ROUTE = {"ACCOUNT_DETAIL": "atencion_de_productos", "CASE_FOLLOWUP": "seguimiento_de_casos",
         "OTHER_TOPIC": "atencion_general", "UNCLEAR": "atencion_general"}
TOPIC_ROUTE = {"account_inquiry": "atencion_de_productos", "case_status": "seguimiento_de_casos"}
# Senales de fraude o uso no autorizado en lo que el cliente conto. Un incidente sin ellas (una queja por una comision, por
# ejemplo) es importante pero no es una urgencia de seguridad: no va a "fraudes" ni sube a urgente por si solo.
_FRAUD = re.compile(r"(fraude|fraud|robo|robaron|roubo|roubaram|estafa|golpe|clon|no reconozco|nao reconheco|"
                    r"sin (mi )?(permiso|autorizacion)|sem (a )?(minha )?(permissao|autorizacao)|usaron mi|usou meu|usaram meu|"
                    r"hackea|suplant|perdi|extravi)")


def _fraud_signal(case: dict | None) -> bool:
    return bool(case and _FRAUD.search(norm(" ".join(n["text"] for n in case["notes"]))))


def _sentiment(session: Session, flags: dict) -> dict:
    seq = session.slots.get("sentiments", [])
    negative = sum(1 for s in seq if s == "negative")
    if negative >= 2 or (negative >= 1 and flags.get("repeat_complainer")):
        level = "high"
    elif negative == 1 or flags.get("recent_negative_sentiment"):
        level = "low"
    else:
        level = "none"
    return {"turns": len(seq), "negative_turns": negative, "last": seq[-1] if seq else None, "frustration": level}


def _priority(reason: str, ctx: dict, sentiment: dict, case: dict | None) -> str:
    flags, counts = ctx.get("flags", {}), ctx.get("counts", {})
    if flags.get("has_critical_open") or (reason == "INCIDENT" and _fraud_signal(case)):
        return "urgent"
    if (reason == "INCIDENT" or sentiment["frustration"] == "high" or counts.get("high_priority")
            or flags.get("has_sla_breach") or flags.get("repeat_complainer")):
        return "high"
    return "normal"


def _route(reason: str, case: dict | None, has_credit: bool) -> str:
    if reason == "INCIDENT" or (reason == "USER_REQUEST" and case and case["topic"] == "incident"):
        return "fraudes_y_disputas" if _fraud_signal(case) else "reclamos_y_quejas"
    if reason in ROUTE:
        return ROUTE[reason]
    if reason in CREDIT_REASONS:
        return "asesor_de_credito"
    if case:                                        # el cliente pidio un humano en medio de un tema de soporte
        return TOPIC_ROUTE.get(case["topic"], "atencion_general")
    return "asesor_de_credito" if has_credit else "atencion_general"


def _next_actions(reason: str, ctx: dict, case: dict | None, sentiment: dict) -> list[str]:
    out: list[str] = []
    flags = ctx.get("flags", {})
    if sentiment["frustration"] != "none":
        # solo se habla de espera si hay un caso abierto que la respalde; si no, seria afirmar algo que el dato no dice
        out.append("Abrir reconociendo la molestia del cliente" + (" y el tiempo que lleva con su caso abierto." if ctx.get("open_cases") else "."))
    if ctx.get("open_cases"):
        out.append("Revisar primero el caso abierto más relevante antes de ofrecer otros productos.")
    if flags.get("has_sla_breach"):
        out.append("Hay un caso con SLA incumplido: priorizar su atención.")
    if case and case.get("notes"):
        out.append("Validar con el cliente lo que declaró en el chat (no está verificado).")
    return out


def _case_line(c: dict) -> str:
    kind = "reclamo" if c["case_source"] == "complaint" else "interacción sin resolver"
    prio = f", prioridad {c['priority']}" if c.get("priority") else ""
    return f"{kind} de {c.get('category')} ({status_text(c, 'es')}, {c.get('days_open')} días{prio})"


def build_narrative(summary: dict) -> str:
    """Parrafo corto y determinista para el asesor. Solo reordena lo que ya esta en el resumen."""
    parts = [f"Motivo: {REASON_LABEL.get(summary['reason'], summary['reason'])}. Prioridad sugerida: {summary['priority']}."]
    notes = [n["text"] for n in summary.get("case_notes", [])]
    if notes:
        parts.append("El cliente contó (sin verificar): " + "; ".join(f"«{t}»" for t in notes[:3]) + ".")
    ctx = summary["customer_context"]
    if ctx["open_cases"]:
        top = ctx["open_cases"][0]
        extra = f" y {ctx['counts']['open'] - 1} más" if ctx["counts"]["open"] > 1 else ""
        parts.append(f"Tiene {ctx['counts']['open']} caso(s) abierto(s); el más relevante: {_case_line(top)}{extra}.")
    else:
        parts.append("No tiene casos abiertos.")
    s = summary["sentiment"]
    if s["negative_turns"]:
        parts.append(f"Mostró molestia en {s['negative_turns']} de {s['turns']} mensajes.")
    ev = summary.get("evaluation")
    if ev:
        parts.append(f"Evaluación de crédito: {ev.get('outcome')}.")
    return " ".join(parts)


def build_summary(session: Session, ticket_id: str, created_at: str, reason: str, evaluation: dict | None,
                  open_questions: list[str]) -> dict:
    context = session.slots.get("context") or {}
    case = session.slots.get("case")
    flags = context.get("flags", {})
    sentiment = _sentiment(session, flags)
    summary = {
        "ticket_id": ticket_id,
        "created_at": created_at,
        "reason": reason,
        "customer": {"customer_id": session.customer_id, "country": session.country, "language": session.language,
                     "authenticated": True, "auth_method": "kba_transactions_and_account_opening"},
        "priority": _priority(reason, context, sentiment, case),
        "suggested_route": _route(reason, case, bool(session.slots.get("pending_request"))),
        "sentiment": sentiment,
        "topic": {"primary": case["topic"], "all": list(case["topics"]), "families": list(case["families"])} if case else None,
        # Lo que el cliente escribio, con numeros largos y correos omitidos. Es DECLARADO: no esta verificado.
        "case_notes": list(case["notes"]) if case else [],
        "customer_context": {
            "open_cases": [{k: c.get(k) for k in ("case_source", "case_id", "category", "case_type", "priority", "status",
                                                  "opened_on", "days_open", "is_escalated", "sla_breached", "channel")}
                           for c in context.get("open_cases", [])[:TOP_CASES]],
            "counts": context.get("counts", {"open": 0, "complaints": 0, "interactions": 0, "high_priority": 0}),
            "flags": flags,
            "products": context.get("products", []),
        },
        "request": session.slots.get("pending_request"),
        "declared_income_unverified": session.slots.get("declared_income"),
        "application": session.slots.get("application"),
        "verified_facts": session.slots.get("verified_facts", []),
        "evaluation": evaluation,
        "actions_taken": list(session.actions),
        "open_questions": open_questions,
        "suggested_next_actions": _next_actions(reason, context, case, sentiment),
        # Ultimos mensajes, con numeros largos y correos omitidos (el cliente pudo escribir una tarjeta o un documento).
        "transcript_tail": [{**h, "text": redact(h["text"], limit=None)} for h in session.history[-TRANSCRIPT_TAIL:]],
    }
    summary["narrative"] = build_narrative(summary)
    summary["narrative_source"] = "rules"
    return summary
