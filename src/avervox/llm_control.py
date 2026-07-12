"""Best-effort abort/unload helpers for misbehaving LLM endpoints.

Failure thresholds (see website docs — "LLM model health"):
  FIRST_TOKEN_TIMEOUT_S  — max wait for first content token (includes server load time)
  EMPTY_RESPONSE_MIN_S   — stream ends empty after at least this long
  STREAM_READ_TIMEOUT_S  — no SSE bytes at all for this long
"""

from __future__ import annotations

import httpx

from .logger import get_logger
from .model_catalog import _normalize_base

log = get_logger(__name__)

# Stream read stall — no SSE bytes for this long triggers failure.
STREAM_READ_TIMEOUT_S = 90.0
# No usable content token within this window triggers failure (keepalive SSE doesn't count).
FIRST_TOKEN_TIMEOUT_S = 30.0
# Empty body after at least this many seconds is treated as misbehavior.
EMPTY_RESPONSE_MIN_S = 30.0


class LLMModelFailure(Exception):
    """Raised when an endpoint/model fails during inference."""

    def __init__(self, model: str, reason: str) -> None:
        self.model = model
        self.reason = reason
        super().__init__(f"{model}: {reason}")


def _auth_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    return headers


def unload_lm_studio_model(api_base: str, api_key: str, model_id: str) -> bool:
    """POST /api/v1/models/unload (LM Studio native API)."""
    base = _normalize_base(api_base)
    url = f"{base}/api/v1/models/unload"
    try:
        resp = httpx.post(
            url,
            json={"instance_id": model_id},
            headers=_auth_headers(api_key),
            timeout=15.0,
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        log.info("LM Studio unload requested for %s", model_id)
        return True
    except Exception as exc:
        log.debug("LM Studio unload not available: %s", exc)
        return False


def unload_ollama_model(api_base: str, model_id: str) -> bool:
    """POST /api/generate with keep_alive=0 (Ollama unload)."""
    base = _normalize_base(api_base)
    url = f"{base}/api/generate"
    try:
        resp = httpx.post(
            url,
            json={"model": model_id, "keep_alive": 0},
            headers={"Content-Type": "application/json"},
            timeout=15.0,
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        log.info("Ollama unload requested for %s", model_id)
        return True
    except Exception as exc:
        log.debug("Ollama unload not available: %s", exc)
        return False


def abort_and_unload(api_base: str, api_key: str, model_id: str) -> None:
    """Best-effort signal for the server to stop and unload a bad model."""
    if not api_base.strip() or not model_id.strip():
        return
    if unload_lm_studio_model(api_base, api_key, model_id):
        return
    unload_ollama_model(api_base, model_id)
