"""Soporte conversacional: lo que el agente dice de los productos y casos del cliente, y como anota lo que el cliente cuenta.

Los datos salen del contexto verificado del banco (agent/context.py). El agente confirma que un producto existe y cuenta lo
que ve de un caso (categoria, fecha, estado); NUNCA detalla saldos, movimientos, montos ni resoluciones: eso lo ve un asesor.
Lo que el cliente cuenta en el chat se guarda como DECLARADO (sin verificar) para el resumen del asesor.
"""
from __future__ import annotations

import re
from datetime import date

from app.agent import templates
from app.agent.context import greeting_case
from app.agent.language import norm
from app.auth.kba import PRODUCT_LABELS
from app.core.fmt import fmt_date

# Motivos de derivacion que NO son de credito: al declinar la derivacion no se habla de "otro monto o plazo".
SUPPORT_REASONS = frozenset({"OTHER_TOPIC", "ACCOUNT_DETAIL", "INCIDENT", "CASE_FOLLOWUP", "UNCLEAR"})
MAX_NOTES = 8
NOTE_CHARS = 300

# ---------------------------------------------------------------- productos
FAMILY_OF = {"Cuenta Ahorro": "account", "Cuenta Corriente": "account", "Tarjeta Débito": "card", "Tarjeta Crédito": "card",
             "Préstamo Personal": "loan", "Préstamo Hipotecario": "mortgage", "Inversión": "investment", "Seguro": "insurance"}
_FAMILY_RX = [("mortgage", r"hipotec|imobili"), ("loan", r"prestamo|emprestimo"), ("card", r"tarjeta|cartao|cartoes"),
              ("account", r"cuenta|\bcontas?\b|ahorro|poupanca|corriente"), ("investment", r"inversion|investimento"),
              ("insurance", r"\bseguro")]
FAMILY_NAME = {
    "es": {"card": ("tarjeta", "f"), "account": ("cuenta", "f"), "loan": ("préstamo", "m"), "mortgage": ("préstamo hipotecario", "m"),
           "investment": ("inversión", "f"), "insurance": ("seguro", "m")},
    "pt": {"card": ("cartão", "m"), "account": ("conta", "f"), "loan": ("empréstimo", "m"),
           "mortgage": ("financiamento imobiliário", "m"), "investment": ("investimento", "m"), "insurance": ("seguro", "m")},
}
GENDER = {"Cuenta Ahorro": {"es": "f", "pt": "f"}, "Cuenta Corriente": {"es": "f", "pt": "f"},
          "Tarjeta Débito": {"es": "f", "pt": "m"}, "Tarjeta Crédito": {"es": "f", "pt": "m"},
          "Préstamo Personal": {"es": "m", "pt": "m"}, "Préstamo Hipotecario": {"es": "m", "pt": "m"},
          "Inversión": {"es": "f", "pt": "m"}, "Seguro": {"es": "m", "pt": "m"}}
ART = {"es": {"f": "una", "m": "un"}, "pt": {"f": "uma", "m": "um"}}
ADJ = {"es": {"f": "activa", "m": "activo"}, "pt": {"f": "ativa", "m": "ativo"}}
TERMINATION = {"es": "terminación", "pt": "final"}


def mentioned_family(text: str) -> tuple[str | None, str | None]:
    """(familia de producto, tipo exacto si el cliente lo precisa) que menciona el mensaje. Ej.: 'mi tarjeta de débito'."""
    t = norm(text)
    family = next((f for f, rx in _FAMILY_RX if re.search(rx, t)), None)
    hint = None
    if family == "card":
        hint = "Tarjeta Débito" if "debito" in t else "Tarjeta Crédito" if "credit" in t else None
    elif family == "account":
        hint = "Cuenta Ahorro" if re.search(r"ahorro|poupanca", t) else "Cuenta Corriente" if "corrente" in t or "corriente" in t else None
    return family, hint


def _item(p: dict, lang: str, article: bool = False) -> str:
    label = PRODUCT_LABELS[lang].get(p["type"], p["type"])
    art = f"{ART[lang][GENDER[p['type']][lang]]} " if article and p["type"] in GENDER else ""
    return f"{art}{label} ({TERMINATION[lang]} {p['last4']})"


def product_answer(products: list[dict], family: str | None, hint: str | None, lang: str) -> tuple[str, dict]:
    """(tipo de mensaje, datos) para '¿tengo X?': solo existencia, tipo y terminacion. Nunca saldos ni movimientos."""
    active = [p for p in products if p.get("status") == "Active"]
    if not active:
        return "products_empty", {}
    if family is None:
        return "products_overview", {"what": templates.join_list([_item(p, lang) for p in active], lang)}
    found = [p for p in active if FAMILY_OF.get(p["type"]) == family and (hint is None or p["type"] == hint)]
    if found:
        return "products_found", {"what": templates.join_list([_item(p, lang, article=True) for p in found], lang)}
    noun, gender = (PRODUCT_LABELS[lang][hint], GENDER[hint][lang]) if hint else FAMILY_NAME[lang][family]
    return "products_none", {"art": ART[lang][gender], "noun": noun, "adj": ADJ[lang][gender]}


# ---------------------------------------------------------------- casos
CASE_NOUN = {
    "es": {"Claim": "un reclamo", "Complaint": "un reclamo", "Request": "una solicitud", "Suggestion": "una sugerencia", None: "un caso"},
    "pt": {"Claim": "uma reclamação", "Complaint": "uma reclamação", "Request": "uma solicitação", "Suggestion": "uma sugestão", None: "um caso"},
}
CATEGORY = {
    "es": {"Transactions": "transacciones", "Fees": "comisiones y cargos", "Technical": "un tema técnico",
           "Branch": "la atención en sucursal", "Service": "el servicio", "Transaccional": "transacciones", "Producto": "un producto",
           "Queja": "una queja", "Técnico": "un tema técnico", "Comercial": "un tema comercial", "Retención": "su relación con el banco"},
    "pt": {"Transactions": "transações", "Fees": "tarifas e cobranças", "Technical": "um tema técnico",
           "Branch": "o atendimento na agência", "Service": "o serviço", "Transaccional": "transações", "Producto": "um produto",
           "Queja": "uma reclamação", "Técnico": "um tema técnico", "Comercial": "um tema comercial", "Retención": "a sua relação com o banco"},
}
STATUS = {
    "es": {"Open": "abierto", "In Process": "en proceso", "Escalated": "escalado a un área especializada", "Unresolved": "pendiente de resolver"},
    "pt": {"Open": "aberto", "In Process": "em andamento", "Escalated": "encaminhado a uma área especializada", "Unresolved": "pendente de solução"},
}
_SINCE = {"es": "desde el", "pt": "desde"}
_PENDING = {"es": " que sigue pendiente", "pt": " que continua pendente"}
_ON = {"es": "del", "pt": "de"}


def _date(case: dict) -> str:
    return fmt_date(date.fromisoformat(str(case["opened_on"])[:10]))


def case_phrase(case: dict, lang: str) -> str:
    """'un reclamo sobre comisiones y cargos, desde el 05/06/2026'. Sin montos, descripciones ni resoluciones."""
    cat = CATEGORY[lang].get(case.get("category"), CATEGORY[lang]["Service"] if case["case_source"] == "complaint" else "su consulta")
    if case["case_source"] == "complaint":
        return f"{CASE_NOUN[lang].get(case.get('case_type'), CASE_NOUN[lang][None])} sobre {cat}, {_SINCE[lang]} {_date(case)}"
    return {"es": f"una consulta anterior sobre {cat}, {_ON[lang]} {_date(case)}, que quedó sin resolver",
            "pt": f"uma consulta anterior sobre {cat}, {_ON[lang]} {_date(case)}, que ficou sem solução"}[lang]


def status_text(case: dict, lang: str) -> str:
    return STATUS[lang].get(case.get("status"), STATUS[lang]["Open"])


def welcome(lang: str, first_name: str, context: dict) -> tuple[str, str | None]:
    """(texto de bienvenida, 'case_intro' si abre con un caso pendiente reciente). Las plantillas son de texto fijo."""
    case = greeting_case(context)
    if case:
        # la frase de una llamada ya dice "que quedo sin resolver"; la de un reclamo necesita decir que sigue pendiente
        pending = "" if case["case_source"] == "interaction" else _PENDING[lang]
        return templates.render("welcome_case", lang, {"first_name": first_name, "case": case_phrase(case, lang),
                                                       "pending": pending}), "case_intro"
    return templates.render("welcome", lang, {"first_name": first_name}), None


# ---------------------------------------------------------------- notas del cliente
_LONG_NUMBER = re.compile(r"(?:\d[ -]?){9,19}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def redact(text: str, limit: int | None = NOTE_CHARS) -> str:
    """Quita numeros largos (cuentas, tarjetas, documentos) y correos antes de guardar lo que el cliente escribio."""
    clean = _EMAIL.sub("[correo omitido]", _LONG_NUMBER.sub("[número omitido]", text)).strip()
    return clean if limit is None else clean[:limit]


def add_note(slots: dict, topic: str, message: str, family: str | None = None) -> dict:
    """Registra el tema y lo que el cliente cuenta, como DECLARADO. Devuelve el caso en curso (para el resumen del asesor)."""
    case = slots.setdefault("case", {"topic": topic, "topics": [], "notes": [], "families": []})
    case["topic"] = topic
    if topic not in case["topics"]:
        case["topics"].append(topic)
    if family and family not in case["families"]:
        case["families"].append(family)
    text = redact(message)
    if len(text) > 3 and len(case["notes"]) < MAX_NOTES:
        # Solo el texto (anonimizado). No se extraen "montos": parse_amounts lee "12 de mayo" como 12 y un numero largo como
        # monto, y un dato equivocado engana mas que ayuda al asesor.
        case["notes"].append({"text": text, "declared_by_customer": True, "verified": False})
    return case
