"""Interfaz del LLM y fabrica de proveedores.

El LLM tiene dos tareas, ambas de lenguaje: extraer (mensaje -> NLUResult) y reescribir un borrador con hechos
ya calculados. Nunca decide, calcula ni ejecuta acciones.
"""
from __future__ import annotations

from typing import Protocol

from app.agent.nlu import MockNLU, NLUResult
from app.config import Settings


class LLM(Protocol):
    name: str

    def extract(self, message: str, language_hint: str | None, yes_no_pending: bool = False) -> NLUResult: ...

    def compose(self, facts: dict, lang: str, draft: str) -> str | None:
        """Reescribe `draft` con tono natural. Devuelve None para conservar la plantilla."""
        ...

    def summarize(self, summary: dict) -> str | None:
        """Parrafo corto para el asesor a partir del resumen estructurado. None para conservar el de reglas.
        Opcional: el orquestador lo busca con getattr y descarta lo que introduzca datos ajenos al resumen."""
        ...


class MockLLM:
    """Sin red ni clave: extractor por reglas y plantillas tal cual."""

    name = "mock"

    def __init__(self) -> None:
        self._nlu = MockNLU()

    def extract(self, message: str, language_hint: str | None, yes_no_pending: bool = False) -> NLUResult:
        return self._nlu.extract(message, language_hint, yes_no_pending)

    def compose(self, facts: dict, lang: str, draft: str) -> str | None:
        return None

    def summarize(self, summary: dict) -> str | None:
        return None


def make_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "anthropic":
        from app.agent.llm_anthropic import AnthropicLLM

        return AnthropicLLM(settings.anthropic_api_key, settings.anthropic_model)
    return MockLLM()
