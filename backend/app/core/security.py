"""API key de integracion y token de sesion (JWT)."""
from __future__ import annotations

import hmac
from datetime import timedelta

import jwt

from app.core.sessions import utcnow

ALGORITHM = "HS256"


def make_session_token(session_id: str, secret: str, ttl_minutes: int) -> str:
    now = utcnow()
    return jwt.encode({"sid": session_id, "iat": now, "exp": now + timedelta(minutes=ttl_minutes)},
                      secret, algorithm=ALGORITHM)


def read_session_token(token: str, secret: str) -> str | None:
    """Devuelve el session_id si el token es valido; None en cualquier otro caso."""
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM])["sid"]
    except (jwt.PyJWTError, KeyError):
        return None


def api_key_valid(provided: str | None, allowed: set[str]) -> bool:
    if not allowed:
        return True  # sin claves configuradas: solo desarrollo local
    if not provided:
        return False
    return any(hmac.compare_digest(provided.encode(), k.encode()) for k in allowed)
