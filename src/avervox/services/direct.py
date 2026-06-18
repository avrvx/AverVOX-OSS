"""Direct LLM service — calls an OpenAI-compatible API.

Used for setups where the LLM (e.g. Ollama, LM Studio) runs locally
or on a remote server accessible via HTTP.
"""

from __future__ import annotations

from typing import Generator, TYPE_CHECKING

from ..logger import get_logger

if TYPE_CHECKING:
    from ..config import AppConfig

log = get_logger(__name__)


class DirectLLMService:
    """LLMService implementation that talks directly to an OpenAI-compatible API."""

    def __init__(self, config: AppConfig) -> None:
        from ..llm import LLMBackend
        self._backend = LLMBackend(config.llm)

    def complete(self, messages: list[dict], model: str = "") -> str:
        result = self._backend.complete(messages, model=model)
        return result.get("content", "")

    def stream_complete(self, messages: list[dict], model: str = "") -> Generator[str, None, None]:
        """Yield complete sentences as the LLM generates them."""
        yield from self._backend.stream_sentences(messages, model=model)

    def list_models(self) -> list[str]:
        if self._backend._default_model:
            return [self._backend._default_model]
        return []

    def set_session_id(self, session_id: str) -> None:
        self._backend.set_session_id(session_id)

    def is_available(self) -> bool:
        return bool(self._backend._api_base)

    def shutdown(self) -> None:
        self._backend.shutdown()
