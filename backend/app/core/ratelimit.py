"""Bloqueo por documento tras intentos fallidos de autenticacion.

Se indexa por un hash del documento (no se guarda el numero). Aplica igual a documentos que no existen,
para no revelar cuales existen.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta
from typing import Callable

from app.core.sessions import utcnow


class AuthLockout:
    def __init__(self, max_failures: int, lockout_minutes: int, secret: str,
                 clock: Callable[[], datetime] = utcnow):
        self._max = max_failures
        self._lock_for = timedelta(minutes=lockout_minutes)
        self._secret = secret
        self._clock = clock
        self._fails: dict[str, int] = {}
        self._locked_until: dict[str, datetime] = {}
        self._mutex = threading.Lock()

    def key(self, document_number: str) -> str:
        return hashlib.sha256(f"{self._secret}:{document_number}".encode()).hexdigest()

    def is_locked(self, k: str) -> bool:
        with self._mutex:
            until = self._locked_until.get(k)
            if until and self._clock() < until:
                return True
            if until:  # vencio el bloqueo
                self._locked_until.pop(k, None)
                self._fails.pop(k, None)
            return False

    def register_failure(self, k: str) -> bool:
        """Cuenta un fallo; devuelve True si con este fallo queda bloqueado."""
        with self._mutex:
            self._fails[k] = self._fails.get(k, 0) + 1
            if self._fails[k] >= self._max:
                self._locked_until[k] = self._clock() + self._lock_for
                return True
            return False

    def register_success(self, k: str) -> None:
        with self._mutex:
            self._fails.pop(k, None)
            self._locked_until.pop(k, None)
