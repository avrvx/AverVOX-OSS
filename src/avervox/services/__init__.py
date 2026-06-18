"""Service layer for AverVOX — abstracts local vs. direct LLM backends."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import InsertService, LLMService, SpeechService
from .local import LocalInsertService, LocalLLMService, LocalSpeechService

if TYPE_CHECKING:
    from ..config import AppConfig

__all__ = [
    "SpeechService",
    "InsertService",
    "LLMService",
    "create_services",
]


def create_services(config: AppConfig) -> tuple[SpeechService, InsertService, LLMService]:
    """Build the service instances appropriate for the current config.

    Returns (speech, insert, llm).  Selection logic for LLM:
      1. ``llm.api_base`` set → DirectLLMService (call LLM API directly)
      2. Otherwise → LocalLLMService stub (Converse unavailable)
    """
    speech: SpeechService = LocalSpeechService()
    insert: InsertService = LocalInsertService()

    llm: LLMService
    api_base = getattr(getattr(config, "llm", None), "api_base", "")

    if api_base:
        from .direct import DirectLLMService
        llm = DirectLLMService(config)
    else:
        llm = LocalLLMService()

    return speech, insert, llm
