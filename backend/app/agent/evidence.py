"""Evidencia de un turno: que hizo REALMENTE el agente para responder. La interfaz solo muestra esto, no inventa nada.

Se construye a partir de `ToolContext.trace` (llamadas a herramientas efectivamente ejecutadas en el turno) y de los hechos
del turno (derivacion creada, correo del resumen). Si el turno no uso ninguna herramienta (saludo, agradecimiento...),
no hay evidencia (`None`) y la interfaz muestra una respuesta simple, sin sellos de verificacion.

Estados de verificacion (el texto lo pone la interfaz, por idioma):
  verified      la comprobacion se ejecuto en codigo y su resultado fue concluyente
  inconclusive  la comprobacion se ejecuto pero no pudo concluir (revision humana o datos faltantes)
  unverified    el dato lo declaro el cliente en el chat y el banco no lo verifico (p. ej. el ingreso)
  reference     dato de referencia del conjunto de datos, no una cotizacion en vivo (tipos de cambio)
"""
from __future__ import annotations

from app.policy import credit_engine as ce

CONCLUSIVE = (ce.ELIGIBLE, ce.ELIGIBLE_PROVISIONAL, ce.DECLINED)
HANDOFF_KINDS = ("handoff_created", "application_ready")


def _last(trace: list[dict], tool: str) -> dict | None:
    return next((t for t in reversed(trace) if t["tool"] == tool), None)


def _customer(profile: dict) -> dict:
    return {"status": profile["customer_status"], "country": profile["country"],
            "monthly_income": profile["monthly_income"], "income_ccy": profile["income_ccy"],
            "monthly_debt": profile["existing_monthly_debt"], "active_products": profile["n_active_products"],
            "days_past_due": profile["max_days_past_due"]}


def _evaluation(run: dict) -> dict:
    d, req = run["decision"], run["request"]
    return {"product": req["product"], "amount": req["amount"], "months": req["months"], "ccy": run["ccy"],
            "outcome": d.outcome, "reasons": list(d.reasons), "rate_pct": d.rate_pct, "payment": d.payment,
            "dti_after": d.dti_after, "max_dti": run["max_dti"], "max_amount": d.max_amount,
            "policy_version": d.policy_version, "income_declared": run["income_declared"]}


def build_evidence(trace: list[dict], facts: dict) -> dict | None:
    kind = facts.get("kind")
    steps: list[dict] = []
    verification: list[dict] = []
    evaluation = None

    for fx in (t for t in trace if t["tool"] == "fx_rates"):
        if fx["status"] == "success":
            steps.append({"id": "fx_rates", "type": "database", "status": "success",
                          "data": {"src": fx["src"], "dst": fx["dst"], "rate": fx["rate"], "as_of": fx["as_of"]}})
            verification.append({"code": "fx", "status": "reference"})
        else:
            steps.append({"id": "fx_rates", "type": "database", "status": "failed",
                          "data": {"src": fx["src"], "dst": fx["dst"]}})

    run = _last(trace, "credit_policy")
    if run:
        evaluation = _evaluation(run)
        steps.append({"id": "credit_policy", "type": "validation", "status": "success",
                      "data": {"outcome": evaluation["outcome"], "policy_version": evaluation["policy_version"],
                               "dti_after": evaluation["dti_after"], "max_dti": evaluation["max_dti"],
                               "reasons": evaluation["reasons"]}})
        verification.append({"code": "policy", "status": "verified" if evaluation["outcome"] in CONCLUSIVE else "inconclusive",
                             "detail": evaluation["policy_version"]})
        if run["income_declared"]:
            verification.append({"code": "income_declared", "status": "unverified"})

    offer = _last(trace, "offer_rates") if kind == "offers" or facts.get("proactive_offer") else None
    if offer:                                   # la sonda de una oferta que no se hizo no se presenta como consulta
        steps.append({"id": "offer_rates", "type": "tool", "status": "success",
                      "data": {"rates": offer["rates"], "max_amount": offer["max_amount"], "ccy": offer["ccy"]}})
        verification.append({"code": "rates", "status": "verified" if offer["rates"] else "inconclusive",
                             "detail": offer["policy_version"]})

    if kind in HANDOFF_KINDS and facts.get("handoff_ticket"):
        steps.append({"id": "handoff", "type": "tool", "status": "success", "data": {"ticket": facts["handoff_ticket"]}})
    if facts.get("email"):
        steps.append({"id": "summary_email", "type": "tool", "status": "success",
                      "data": {"status": facts["email"]["status"], "to": facts["email"].get("to")}})

    profile = _last(trace, "customer_profile")
    customer = None
    if profile and steps:                       # leer el perfil solo importa si respaldo algo de lo que se ve
        customer = _customer(profile["profile"])
        steps.insert(0, {"id": "customer_profile", "type": "database", "status": "success",
                         "data": {"status": customer["status"]}})
        verification.insert(0, {"code": "customer_data", "status": "verified"})

    if facts.get("summary") and facts.get("income_declared") and not any(v["code"] == "income_declared" for v in verification):
        verification.append({"code": "income_declared", "status": "unverified"})   # el resumen hereda la reserva sobre el ingreso

    if not steps:
        return None
    if any(s["status"] == "failed" for s in steps):
        verification = []                       # tras un fallo de herramienta, ninguna respuesta se presenta como verificada
    return {"steps": steps, "verification": verification, "customer": customer, "evaluation": evaluation}
