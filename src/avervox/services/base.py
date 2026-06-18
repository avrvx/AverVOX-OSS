"""Service protocol definitions for AverVOX.

These protocols define the boundary between AverVoxApp and the underlying
implementations, allowing local and remote backends to be swapped
transparently.
"""

from __future__ import annotations

from typing import Optional, Protocol

import numpy as np


class SpeechService(Protocol):
    """Transcribe audio to text."""

    def configure(self, model: str, language: str) -> None: ...
    def preload(self) -> None: ...
    def transcribe(self, audio: np.ndarray, *, long_form: bool = False) -> str: ...


class InsertService(Protocol):
    """Insert text into the focused window and read selections."""

    def insert_text(self, text: str, backend: str) -> str: ...
    def get_selection(self, backend: str) -> Optional[str]: ...


class LLMService(Protocol):
    """Send chat completions to a language model."""

    def complete(self, messages: list[dict], model: str = "") -> str: ...
    def list_models(self) -> list[str]: ...
    def is_available(self) -> bool: ...
    def shutdown(self) -> None: ...
