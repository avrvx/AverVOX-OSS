"""Fetch OpenAI-compatible model lists from LLM endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from .logger import get_logger

log = get_logger(__name__)


@dataclass
class EndpointProbeResult:
    models: list[str]
    latency_ms: float
    ok: bool
    message: str = ""


def _normalize_base(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


def fetch_model_ids(api_base: str, api_key: str = "", timeout: float = 10.0) -> list[str]:
    """Return model ids from ``GET /v1/models``."""
    base = _normalize_base(api_base.strip())
    if not base:
        raise ValueError("API base URL is required")

    headers: dict[str, str] = {}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    url = f"{base}/v1/models"
    resp = httpx.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    models = [m.get("id", "?") for m in data.get("data", []) if m.get("id")]
    models.sort()
    return models


def probe_endpoint(api_base: str, api_key: str = "", timeout: float = 10.0) -> EndpointProbeResult:
    """Test connectivity and return available models."""
    start = time.perf_counter()
    try:
        models = fetch_model_ids(api_base, api_key, timeout=timeout)
        latency_ms = (time.perf_counter() - start) * 1000.0
        count = len(models)
        msg = f"{count} model{'s' if count != 1 else ''} available"
        return EndpointProbeResult(models=models, latency_ms=latency_ms, ok=True, message=msg)
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        log.warning("Endpoint probe failed: %s", exc)
        return EndpointProbeResult(
            models=[],
            latency_ms=latency_ms,
            ok=False,
            message=str(exc),
        )
