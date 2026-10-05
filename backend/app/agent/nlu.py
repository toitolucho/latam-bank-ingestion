"""Comprension de lenguaje: esquema canonico (en espanol) y un extractor por reglas (MockNLU).

El LLM real produce el mismo esquema (ver llm_anthropic.py); el orquestador solo conoce NLUResult.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.agent.language import detect_language, norm, parse_amounts, parse_months

Intent = Literal["credit_eligibility", "credit_offers", "update_income", "request_human", "greeting", "thanks",
                 "closing", "other_topic", "account_inquiry", "case_status", "ask_identity", "confirm_yes", "confirm_no",
                 "unknown"]
Product = Literal["personal_loan", "credit_card", "mortgage"]
Sentiment = Literal["positive", "neutral", "negative"]


class NLUResult(BaseModel):
    intent: Intent = "unknown"
    language: Literal["es", "pt"] | None = None
    product: Product | None = None
    amount: float | None = Field(default=None, gt=0, lt=1e10)
    months: int | None = Field(default=None, ge=1, le=480)
    declared_income: float | None = Field(default=None, gt=0, lt=1e10)
    sentiment: Sentiment | None = None
    # Tema delicado (fraude, disputa, queja, tarjeta robada...): nunca se acompana de una oferta comercial.
    sensitive_topic: bool = False
    confidence: float = Field(default=1.0, ge=0, le=1)


_HUMAN = re.compile(r"\b(agente|asesor|ejecutiv[oa]|humano|persona real|atendente|operador|falar com|hablar con)\b|"
                    r"\b(atienda|atender|atendido|hablar|falar|comunica|comunicar|pasame|pasar|conecta|transferir)\b.{0,30}"
                    r"\b(persona|pessoa|humano|asesor|ejecutivo)\b")
# Pregunta por la naturaleza de quien atiende ("¿eres un robot?", "¿hablo con una persona?"). Se evalua ANTES que la peticion
# de un humano: "hablo con" (pregunta) no es "hablar con" (peticion).
_IDENTITY = re.compile(r"\b(eres|sos|es usted|usted es|tu eres|voce e|voce eh|vc e|hablo con|estoy hablando con|falo com|estou falando com)\b"
                       r".{0,40}\b(robot|bot|chatbot|maquina|ia|inteligencia artificial|humano|humana|persona|pessoa|robo|programa|real)\b"
                       r"|\bcon quien hablo\b|\bcom quem (falo|estou falando)\b|\bes (un|una) (robot|bot|persona|maquina)\b")
HUMAN_REQUEST = _HUMAN  # peticion EXPLICITA de hablar con una persona; el LLM no puede inferirla
_INCOME = re.compile(r"\b(gano|ganamos|ganho|cobro|sueldo|salario|ingresos?|renda|rendimento)\b")
_CREDIT = re.compile(r"(credit|prestamo|prestad|prestar|emprestimo|emprestad|emprestar|financiar|financiamento|hipotec)")
_OFFER_BASE = (r"oferta|proposta|preaprob|pre-aprov|preaprov|\btasas?\b|\btaxas?\b|juros|intereses?|"
               r"cuanto (me|puedo)|quanto (posso|eu)|limite|capacidad|capacidade")
_OFFERS = re.compile(rf"({_OFFER_BASE}|que (creditos|productos))")
_OFFER_SIGNALS = re.compile(rf"({_OFFER_BASE})")      # lo que de verdad pregunta por ofertas ("que productos" es ambiguo)
_GREET = re.compile(r"^(hola|buenas|buenos|hello|hi|ola|oi|bom dia|boa tarde|boa noite|buen dia)\b")
_THANKS = re.compile(r"(gracias|agradezco|obrigad|valeu|agradeco)")
_CLOSING = re.compile(r"(adios|hasta luego|chao|eso es todo|nada mas|es todo|ya esta todo|tchau|ate logo|isso e tudo|"
                      r"so isso|nada mais|ate mais)")
_YES = re.compile(r"^(si|claro|dale|ok|okay|de acuerdo|acepto|confirmo|sim|pode|me interesa|interessa)\b")
_NO = re.compile(r"^(no|nao|nunca|cancela|cancelar|prefiero que no|por ahora no|agora nao)\b")
# Pregunta por el estado de un reclamo, queja o caso que ya tiene abierto (no es un reclamo nuevo).
_CASE_STATUS = re.compile(
    r"\b(estado|seguimiento|como va|como vai|avance|novedad\w*|status|andamento|situacao|ya (hice|presente|abri)|ja (fiz|abri)|"
    r"sigue|continua|ainda)\b.{0,30}\b(reclamo|queja|caso|solicitud|ticket|reclamacao|queixa|chamado|protocolo|solicitacao)\b"
    r"|\b(mi|meu|minha)\s+(reclamo|queja|caso|ticket|reclamacao|queixa|chamado|protocolo)\b"
    r"|\b(reclamo|queja|caso|reclamacao|queixa)\b.{0,40}\b(sin respuesta|sem resposta|pendiente|pendente|abierto|aberto|"
    r"sin resolver|sem resolver)\b")
# Consulta sobre sus productos o su cuenta (saldo, movimientos, extracto, que tiene): el agente confirma que existen y
# deriva el detalle.
_ACCOUNT = re.compile(r"(saldo|extracto|extrato|movimiento|movimento|mis productos|meus produtos|"
                      r"que productos (tengo|tiene a mi nombre)|quais produtos (eu )?tenho|"
                      r"constancia|mi cuenta|mis cuentas|minha conta|minhas contas|mi tarjeta|mis tarjetas|meu cartao|meus cartoes|"
                      r"tengo (una|alguna|algun|un) (cuenta|tarjeta|credito|prestamo|hipoteca|seguro|inversion)|"
                      r"tenho (uma|alguma|algum|um) (conta|cartao|credito|emprestimo|financiamento|seguro|investimento)|"
                      r"cuanto (tengo|debo)|quanto (tenho|devo))")
_WANT = re.compile(r"(solicit|me interesa|pedir|sacar|tomar|obtener|financi|quiero (un|una|otro|otra)\b|quero (um|uma|outro|outra)\b|"
                   r"necesito (un|una)\b|preciso de (um|uma)\b|gostaria de (um|uma|solicitar))")
# Otros temas bancarios (horarios, sucursales, claves...): un asesor los atiende; el agente los anota y ofrece conectarlo.
_OTHER = re.compile(r"(saldo|transferenc|cajero|caixa eletronico|horario|sucursal|agencia|contrasena|clave|senha|cuenta|"
                    r"conta|deposit|pago|pagamento|extracto|extrato|\bapp\b|aplicacion|aplicativo|tarjeta|cartao)")
_SENSITIVE = re.compile(r"(fraude|fraud|robo|robaron|roubo|roubaram|estafa|golpe|no reconozco|nao reconheco|reclam|"
                        r"queja|disputa|cobro indebido|cobranca indevida|perdi|extravi|bloquead|bloquearon|clonad|"
                        # uso no autorizado: "usaron mi tarjeta", "sin mi permiso", "sem minha autorizacao"
                        r"sin (mi )?(permiso|autorizacion|consentimiento)|sem (a )?(minha )?(permissao|autorizacao)|"
                        r"no autoric|nao autoriz|sin que yo|usaron mi|usou meu|usaram meu|suplant|vitima|hackearon|hackeado)")
_NEGATIVE = re.compile(r"(pesim|horrible|molest|enoj|furios|harto|harta|odio|verguenza|inaceitavel|ruim|irritad|"
                       r"indignad|nunca mas|absurdo)")


def _product(t: str) -> Product | None:
    if "hipotec" in t or "imobili" in t:
        return "mortgage"
    if "tarjeta" in t or "cartao" in t:
        return "credit_card"
    if re.search(r"(prestamo|emprestimo|credito|financiamento)", t):
        return "personal_loan"
    return None


class MockNLU:
    """Extractor determinista por palabras clave (es/pt). Sirve sin red ni clave y como respaldo del LLM."""

    def extract(self, message: str, language_hint: str | None = None, yes_no_pending: bool = False) -> NLUResult:
        t = norm(message)
        lang = detect_language(message) or language_hint
        amounts = parse_amounts(message)
        sensitive = bool(_SENSITIVE.search(t))
        sentiment: Sentiment | None = "negative" if _NEGATIVE.search(t) else None
        base = dict(language=lang, months=parse_months(message), sentiment=sentiment, sensitive_topic=sensitive)

        if _IDENTITY.search(t):                          # "robot"/"robô" contiene "robo" (robo = hurto): no es un tema sensible
            return NLUResult(intent="ask_identity", **{**base, "sensitive_topic": False})
        if _HUMAN.search(t):
            return NLUResult(intent="request_human", **base)
        if _INCOME.search(t) and amounts:
            return NLUResult(intent="update_income", declared_income=amounts[0], **base)
        words = t.split()
        # con una pregunta de si/no pendiente, respuestas algo mas largas ("no gracias") siguen siendo confirmaciones
        limit = 6 if yes_no_pending else 4
        if len(words) <= limit and _YES.match(t):
            return NLUResult(intent="confirm_yes", **base)
        if len(words) <= limit and _NO.match(t):
            return NLUResult(intent="confirm_no", **base)
        if _CASE_STATUS.search(t):
            return NLUResult(intent="case_status", **base)
        if sensitive:
            return NLUResult(intent="other_topic", **base)
        # "el saldo de mi tarjeta de credito" o "¿tengo un credito hipotecario?" no piden un credito; "¿tengo algun credito
        # preaprobado?" si pregunta por ofertas.
        if _ACCOUNT.search(t) and not _OFFER_SIGNALS.search(t) and not (_WANT.search(t) and _CREDIT.search(t)):
            return NLUResult(intent="account_inquiry", **base)
        if amounts and _CREDIT.search(t):
            return NLUResult(intent="credit_eligibility", product=_product(t) or "personal_loan", amount=amounts[0], **base)
        if _OFFERS.search(t):
            return NLUResult(intent="credit_offers", **base)
        if _CREDIT.search(t):
            return NLUResult(intent="credit_eligibility", product=_product(t) or "personal_loan", **base)
        if _GREET.match(t):
            return NLUResult(intent="greeting", **base)
        if _CLOSING.search(t):
            return NLUResult(intent="closing", **base)
        if _THANKS.search(t):
            return NLUResult(intent="thanks", **base)
        if _OTHER.search(t):
            return NLUResult(intent="other_topic", **base)
        return NLUResult(intent="unknown", confidence=0.0, **base)
