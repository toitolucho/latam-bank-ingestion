"""Estado compartido de la app y dependencias de FastAPI."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, Request

from app.agent.orchestrator import Orchestrator
from app.agent.tools import HandoffQueue
from app.config import Settings
from app.core.outbox import Outbox
from app.core.ratelimit import AuthLockout
from app.core.security import api_key_valid, read_session_token
from app.core.sessions import AUTHENTICATED, Session, SessionStore
from app.data.repository import CustomerRepository
from app.errors import ApiError
from app.logging_setup import trace_id_var


@dataclass
class AppState:
    settings: Settings
    repo: CustomerRepository
    policy: dict
    store: SessionStore
    lockout: AuthLockout
    queue: HandoffQueue
    orchestrator: Orchestrator
    outbox: Outbox
    jwt_secret: str


def get_state(request: Request) -> AppState:
    return request.app.state.ctx


def require_api_key(state: AppState = Depends(get_state), x_api_key: str | None = Header(default=None)) -> None:
    if not api_key_valid(x_api_key, state.settings.api_key_set):
        raise ApiError(401, "INVALID_API_KEY", "API key ausente o invalida.")


def require_session(session_id: str, state: AppState = Depends(get_state),
                    authorization: str | None = Header(default=None)) -> Session:
    token = authorization.removeprefix("Bearer ").strip() if authorization and authorization.startswith("Bearer ") else None
    sid = read_session_token(token, state.jwt_secret) if token else None
    if sid is None or sid != session_id:
        raise ApiError(401, "INVALID_TOKEN", "Token de sesion ausente o invalido.")
    session = state.store.get(session_id)
    if session is None:
        raise ApiError(401, "SESSION_EXPIRED", "La sesion expiro. Inicie una nueva.")
    return session


def require_authenticated(session: Session = Depends(require_session)) -> Session:
    if session.state != AUTHENTICATED:
        raise ApiError(403, "AUTH_REQUIRED", "Debe verificar su identidad antes de conversar.")
    return session


def current_trace_id() -> str:
    return trace_id_var.get()
