"""Local service implementations that delegate to existing AverVOX modules.

These wrappers allow AverVoxApp to use the service protocols while keeping
stt.py, inserter.py, etc. completely unchanged.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..logger import get_logger

log = get_logger(__name__)


class LocalSpeechService:
    """Wraps the stt module behind the SpeechService protocol."""

    def configure(self, model: str, language: str) -> None:
        from .. import stt
        stt.configure(model=model, language=language)

    def preload(self) -> None:
        from .. import stt
        stt.preload()

    def transcribe(self, audio: np.ndarray, *, long_form: bool = False) -> str:
        from .. import stt
        return stt.listen(audio, long_form=long_form or None)


class LocalInsertService:
    """Wraps the inserter module behind the InsertService protocol."""

    def insert_text(self, text: str, backend: str) -> str:
        from ..inserter import insert
        return insert(text, backend=backend)

    def get_selection(self, backend: str) -> Optional[str]:
        from ..inserter import get_selection
        return get_selection(backend=backend)


class LocalLLMService:
    """Stub LLM service for standalone mode (no server configured)."""

    def complete(self, messages: list[dict], model: str = "") -> str:
        raise RuntimeError("LLM not configured — set llm.api_base in Settings")

    def list_models(self) -> list[str]:
        return []

    def is_available(self) -> bool:
        return False

    def shutdown(self) -> None:
        pass
