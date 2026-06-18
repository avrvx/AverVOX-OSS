"""LLM backend — calls OpenAI-compatible chat completion APIs via httpx."""

from __future__ import annotations

import json
import re
import uuid
from typing import Generator, TYPE_CHECKING

import httpx

from .logger import get_logger

if TYPE_CHECKING:
    from .config import LLMProfile

log = get_logger(__name__)

_SENTENCE_END = re.compile(r'[.!?:;]\s')

_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful voice assistant. The user's messages are transcribed from "
    "speech using automatic speech recognition (ASR) and may contain transcription "
    "errors, spoken hesitations (um, uh, etc.), or missing punctuation. Interpret "
    "input charitably and infer intent from context. When the user speaks numbers, "
    "addresses, or data (e.g. 'one two three main street'), render them in natural "
    "written form (e.g. '123 Main Street'). Keep responses concise and "
    "conversational, suitable for text-to-speech playback."
)


def _normalize_base(url: str) -> str:
    """Strip trailing /v1 or /v1/ so we can always append /v1/... ourselves."""
    url = url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


class LLMBackend:
    """Synchronous client for any OpenAI-compatible ``/v1/chat/completions`` endpoint."""

    def __init__(self, config: LLMProfile) -> None:
        self._api_base = _normalize_base(config.api_base)
        self._api_key = config.api_key
        self._default_model = config.default_model
        self._session_header = config.session_header
        self._session_id: str = str(uuid.uuid4()) if config.session_header else ""
        self._client = httpx.Client(timeout=120.0)

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id
        log.debug("Session ID set: %s", session_id[:8])

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if self._session_header and self._session_id:
            headers[self._session_header] = self._session_id
        return headers

    def _adopt_session_id(self, headers: httpx.Headers) -> None:
        """If the server echoes a different session ID, adopt it."""
        if not self._session_header:
            return
        server_id = headers.get(self._session_header)
        if server_id and server_id != self._session_id:
            log.debug("Adopted server session ID: %s", server_id[:8])
            self._session_id = server_id

    def _payload(self, messages: list[dict], model: str, stream: bool = False) -> dict:
        model = model or self._default_model
        if not model:
            raise ValueError("No model specified and no default_model configured")
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": _DEFAULT_SYSTEM_PROMPT}] + messages
        payload: dict = {
            "model": model,
            "messages": messages,
        }
        if stream:
            payload["stream"] = True
        return payload

    def complete(self, messages: list[dict], model: str = "") -> dict:
        """Send a chat completion request and return the parsed response."""
        url = f"{self._api_base}/v1/chat/completions"
        payload = self._payload(messages, model)

        log.info("LLM request: model=%s, messages=%d", payload["model"], len(messages))
        resp = self._client.post(url, json=payload, headers=self._headers())
        resp.raise_for_status()
        self._adopt_session_id(resp.headers)
        data = resp.json()

        choice = data["choices"][0]
        content = choice["message"]["content"]
        usage = data.get("usage", {})
        log.info("LLM response: %d chars, usage=%s", len(content), usage)

        return {
            "content": content,
            "model": data.get("model", payload["model"]),
            "usage": usage,
        }

    def stream_sentences(self, messages: list[dict], model: str = "") -> Generator[str, None, str]:
        """Stream a completion, yielding complete sentences as they form.

        Returns the full accumulated response text (via generator return value,
        accessible in the caller's StopIteration).
        """
        url = f"{self._api_base}/v1/chat/completions"
        payload = self._payload(messages, model, stream=True)

        log.info("LLM stream request: model=%s, messages=%d", payload["model"], len(messages))
        full_text = ""
        buffer = ""

        with self._client.stream("POST", url, json=payload, headers=self._headers()) as resp:
            resp.raise_for_status()
            self._adopt_session_id(resp.headers)
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content", "")
                if not token:
                    continue

                buffer += token

                while True:
                    m = _SENTENCE_END.search(buffer)
                    if not m:
                        break
                    split_at = m.end()
                    sentence = buffer[:split_at].strip()
                    buffer = buffer[split_at:]
                    if sentence:
                        full_text += sentence + " "
                        log.debug("Streaming sentence: %s", sentence[:80])
                        yield sentence

        if buffer.strip():
            full_text += buffer.strip()
            yield buffer.strip()

        log.info("LLM stream complete: %d chars total", len(full_text))
        return full_text.strip()

    def shutdown(self) -> None:
        self._client.close()
