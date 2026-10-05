"""Contexto de casos abiertos por cliente (snapshot local). Misma definicion que
data/databricks/gold/33_customer_case_context.sql: mantener ambos alineados.

Una fila por cliente y caso abierto:
  - reclamos aun abiertos (Open / In Process / Escalated), sin limite de antiguedad;
  - interacciones del call center sin resolver en los ultimos WINDOW_DAYS dias:
    no resuelta Y (requiere seguimiento O fue escalada).
La ventana y la antiguedad se miden desde `as_of`, nunca desde hoy: el dataset es estatico.
No se copian descripciones, montos reclamados ni resoluciones (el chat no detalla la cuenta).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

WINDOW_DAYS = 90
OPEN_STATUSES = ("Open", "In Process", "Escalated")
COLUMNS = ["customer_id", "case_source", "case_id", "opened_on", "days_open", "channel", "category", "case_type",
           "priority", "status", "is_escalated", "sla_breached", "sentiment", "is_repeat_complainer", "as_of_date"]


def _flag(s: pd.Series) -> pd.Series:
    """Booleanos del CSV ('True'/'False') a bool; lo desconocido cuenta como False."""
    return s.astype(str).str.lower().eq("true")


def derive_case_context(complaints: pd.DataFrame, interactions: pd.DataFrame, as_of: date,
                        window_days: int = WINDOW_DAYS) -> pd.DataFrame:
    as_of_ts = pd.Timestamp(as_of)

    c = complaints.copy()
    c["opened_on"] = pd.to_datetime(c.creation_date).dt.normalize()
    c = c[c.status.isin(OPEN_STATUSES) & (c.opened_on <= as_of_ts)]
    comp = pd.DataFrame({
        "customer_id": c.customer_id, "case_source": "complaint", "case_id": c.complaint_id, "opened_on": c.opened_on,
        "channel": c.reception_channel, "category": c.category, "case_type": c.case_type, "priority": c.priority,
        "status": c.status, "is_escalated": c.status.eq("Escalated"), "sla_breached": _flag(c.sla_breached),
        "sentiment": None, "is_repeat_complainer": _flag(c.is_repeat_complainer),
    })

    i = interactions.copy()
    i["opened_on"] = pd.to_datetime(i.interaction_date).dt.normalize()
    resolved, followup, escalated = _flag(i.was_resolved), _flag(i.requires_followup), _flag(i.was_escalated)
    known = i.was_resolved.astype(str).str.lower().isin(["true", "false"])   # was_resolved nulo: no se afirma nada
    keep = (known & ~resolved & (followup | escalated)
            & (i.opened_on > as_of_ts - pd.Timedelta(days=window_days)) & (i.opened_on <= as_of_ts))
    # la interaccion que origino un reclamo se descarta: el reclamo es el caso
    if "origin_interaction_id" in complaints.columns:      # cualquier reclamo, abierto o no, igual que el SQL
        keep &= ~i.interaction_id.isin(set(complaints.origin_interaction_id.dropna()))
    i = i[keep]
    inter = pd.DataFrame({
        "customer_id": i.customer_id, "case_source": "interaction", "case_id": i.interaction_id, "opened_on": i.opened_on,
        "channel": i.channel, "category": i.reason_category, "case_type": None, "priority": None, "status": "Unresolved",
        "is_escalated": _flag(i.was_escalated)[keep], "sla_breached": False, "sentiment": i.detected_sentiment,
        "is_repeat_complainer": False,
    })

    out = pd.concat([comp, inter], ignore_index=True)
    out["days_open"] = (as_of_ts - out.opened_on).dt.days.astype("int64")
    out["opened_on"] = out.opened_on.dt.date.astype(str)
    out["as_of_date"] = as_of.isoformat()
    return out[COLUMNS].sort_values(["customer_id", "opened_on"]).reset_index(drop=True)
