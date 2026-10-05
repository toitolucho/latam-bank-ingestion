"""Conversacion y consulta de derivaciones."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Response

from app.agent.orchestrator import ChatReply
from app.api.schemas import EmailInfo, Evidence, MessageRequest, MessageResponse
from app.core.security import api_key_valid
from app.core.sessions import Session
from app.deps import AppState, current_trace_id, get_state, require_api_key, require_authenticated
from app.errors import ApiError

router = APIRouter(prefix="/v1", tags=["chat"], dependencies=[Depends(require_api_key)])


@router.post("/sessions/{session_id}/messages", response_model=MessageResponse)
def send_message(body: MessageRequest, session: Session = Depends(require_authenticated),
                 state: AppState = Depends(get_state)) -> MessageResponse:
    if len(body.message) > state.settings.max_message_chars:
        raise ApiError(422, "MESSAGE_TOO_LONG", f"El mensaje supera {state.settings.max_message_chars} caracteres.")
    if body.language:
        session.language = body.language
    if session.slots.get("ended"):
        raise ApiError(409, "SESSION_ENDED", "La conversacion ya termino. Inicie una nueva.")
    return _response(state.orchestrator.handle(session, body.message.strip()))


def _response(r: ChatReply) -> MessageResponse:
    return MessageResponse(reply=r.reply, language=r.language, intent=r.intent, outcome=r.outcome, awaiting=r.awaiting,
                           suggested_replies=r.suggested_replies, handoff_ticket=r.handoff_ticket,
                           proactive_offer=r.proactive_offer, summary_ready=r.summary_ready,
                           email=EmailInfo(**r.email) if r.email else None, evidence=Evidence(**r.evidence) if r.evidence else None,
                           trace_id=current_trace_id())


@router.post("/sessions/{session_id}/end", response_model=MessageResponse)
def end_conversation(session: Session = Depends(require_authenticated), state: AppState = Depends(get_state)) -> MessageResponse:
    """Cierra la conversacion: si hay una propuesta, devuelve su resumen y el aviso del correo con el PDF (simulado)."""
    return _response(state.orchestrator.conclude(session))


@router.get("/sessions/{session_id}/summary.pdf")
def summary_pdf(session: Session = Depends(require_authenticated), state: AppState = Depends(get_state)) -> Response:
    """PDF del resumen de la propuesta de ESTA sesion (el mismo que se enviaria por correo)."""
    record = session.slots.get("summary_email")
    data = state.outbox.pdf_bytes(record["id"]) if record else None
    if data is None:
        raise ApiError(404, "NO_SUMMARY", "Esta sesion todavia no tiene un resumen de propuesta.")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="resumen-propuesta.pdf"'})


@router.get("/sessions/{session_id}/handoff")
def session_handoff(session: Session = Depends(require_authenticated), state: AppState = Depends(get_state)) -> dict:
    """Resumen de la derivacion de ESTA sesion (lo que recibe el agente humano)."""
    if not session.handoff:
        raise ApiError(404, "NO_HANDOFF", "Esta sesion no tiene derivacion.")
    tid = session.handoff["ticket_id"]
    return next(h for h in state.queue.list() if h["ticket_id"] == tid)


def require_admin(state: AppState = Depends(get_state), x_admin_key: str | None = Header(default=None)) -> None:
    keys = state.settings.admin_key_set
    if keys:
        if not api_key_valid(x_admin_key, keys):
            raise ApiError(401, "INVALID_ADMIN_KEY", "Clave de administracion ausente o invalida.")
    elif state.settings.env != "dev":
        raise ApiError(403, "ADMIN_DISABLED", "Consola de agentes deshabilitada: configure CHAT_ADMIN_API_KEYS.")


@router.get("/handoffs", tags=["agent-console"], dependencies=[Depends(require_admin)])
def list_handoffs(state: AppState = Depends(get_state)) -> list[dict]:
    """Cola de derivaciones para la consola del agente humano (clave de administracion aparte)."""
    return state.queue.list()
