from __future__ import annotations

import tempfile
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Configuracion por variables de entorno (prefijo CHAT_). Nada sensible va en la imagen."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CHAT_", extra="ignore")

    env: str = "dev"
    data_dir: Path = BASE_DIR / "data" / "snapshot"
    policy_path: Path = BASE_DIR / "policy" / "credit_policy.yaml"
    # Fecha "hoy" del dataset (el ultimo dia de datos). Las preguntas de seguridad se calculan respecto a ella.
    as_of_date: date = date(2026, 6, 17)

    # Integracion externa: lista separada por comas. Vacio = sin API key (solo desarrollo local).
    api_keys: str = ""
    cors_origins: str = ""  # lista separada por comas; vacio = sin CORS
    # Bandeja de salida de correos (SIMULADA: no se envia nada). En el contenedor /tmp es el unico lugar escribible.
    outbox_dir: Path = Path(tempfile.gettempdir()) / "chat-outbox"
    # Consola de agentes (GET /v1/handoffs): clave aparte. Sin claves solo se permite con CHAT_ENV=dev.
    admin_api_keys: str = ""

    # Tokens de sesion. Si esta vacio se genera uno aleatorio al arrancar (las sesiones no sobreviven al reinicio).
    jwt_secret: str = ""
    session_ttl_minutes: int = 30
    max_message_chars: int = 1000

    # Autenticacion por preguntas de seguridad
    auth_questions: int = 3
    auth_max_attempts: int = 3
    auth_lockout_minutes: int = 15

    # LLM: "mock" funciona sin red ni clave; "anthropic" usa la API de Claude.
    llm_provider: Literal["mock", "anthropic"] = "mock"
    anthropic_model: str = "claude-haiku-4-5-20251001"
    # Tipos de mensaje que el LLM puede reescribir (lista por comas). "none" = nunca; vacio = valores por defecto.
    llm_rewrite_kinds: str = ""
    anthropic_api_key: str = Field(
        default="", validation_alias=AliasChoices("ANTHROPIC_API_KEY", "CHAT_ANTHROPIC_API_KEY")
    )

    @model_validator(mode="after")
    def _fallback_to_team_fixture(self):
        """Sin snapshot local (datos derivados del organizador, fuera de git) se usa el conjunto de ejemplo del equipo."""
        if "data_dir" not in self.model_fields_set and not (self.data_dir / "customers.parquet").exists():
            self.data_dir = BASE_DIR / "data" / "fixture"
        return self

    @property
    def data_source(self) -> str:
        return "team_fixture" if self.data_dir.name == "fixture" else "organizer_snapshot"

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def admin_key_set(self) -> set[str]:
        return {k.strip() for k in self.admin_api_keys.split(",") if k.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
