"""Sesiones de chat en memoria con expiracion por inactividad.

Interfaz `SessionStore` reemplazable (Redis en produccion). El estado de autenticacion vive SOLO aqui,
nunca dentro del token: el JWT solo identifica la sesion.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.auth.kba import Challenge
from app.data.repository import Customer

CHALLENGE = "challenge"
AUTHENTICATED = "authenticated"
LOCKED = "locked"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Session:
    id: str
    language: str
    state: str
    created_at: datetime
    last_seen: datetime
    customer_id: str | None = None
    first_name: str | None = None
    country: str | None = None
    challenge: Challenge | None = None
    candidate: Customer | None = None   # cliente al que pertenece el documento; NO autenticado hasta verificar
    doc_key: str | None = None          # hash del documento para el bloqueo
    auth_attempts_used: int = 0
    history: list[dict] = field(default_factory=list)      # {"role": "user"|"assistant", "text": str}
    slots: dict = field(default_factory=dict)              # solicitud en curso, ingreso declarado, etc.
    actions: list[dict] = field(default_factory=list)      # acciones ejecutadas y verificadas
    handoff: dict | None = None
    unknown_streak: int = 0


class SessionStore:
    def __init__(self, ttl_minutes: int, clock: Callable[[], datetime] = utcnow):
        self._ttl = timedelta(minutes=ttl_minutes)
        self._clock = clock
        self._items: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, language: str) -> Session:
        now = self._clock()
        s = Session(id=secrets.token_urlsafe(16), language=language, state=CHALLENGE, created_at=now, last_seen=now)
        with self._lock:
            self._purge(now)
            self._items[s.id] = s
        return s

    def get(self, sid: str) -> Session | None:
        """Devuelve la sesion y renueva su inactividad; None si no existe o expiro."""
        now = self._clock()
        with self._lock:
            s = self._items.get(sid)
            if s is None:
                return None
            if now - s.last_seen > self._ttl:
                del self._items[sid]
                return None
            s.last_seen = now
            return s

    def delete(self, sid: str) -> None:
        with self._lock:
            self._items.pop(sid, None)

    def _purge(self, now: datetime) -> None:
        for k in [k for k, v in self._items.items() if now - v.last_seen > self._ttl]:
            del self._items[k]

    def __len__(self) -> int:
        return len(self._items)
