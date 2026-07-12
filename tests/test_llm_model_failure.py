"""Tests for LLM failure handling and model disable."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from avervox.config import AppConfig
from avervox.llm_control import (
    EMPTY_RESPONSE_MIN_S,
    LLMModelFailure,
    abort_and_unload,
    unload_lm_studio_model,
    unload_ollama_model,
)


def test_mark_model_failed_keeps_other_models():
    cfg = AppConfig()
    alts = cfg.mark_model_failed(
        "bad-model", "empty response after 162s",
        catalog=["bad-model", "good-model"],
    )
    assert alts == ["good-model"]
    assert cfg.disabled_models["bad-model"] == "empty response after 162s"
    assert not cfg.is_model_enabled("bad-model")
    assert cfg.is_model_enabled("good-model")


def test_clear_disabled_models_on_startup():
    cfg = AppConfig()
    cfg.disabled_models = {
        "bad-model": "no usable output within 30s",
        "other-bad": "empty response after 45s",
    }
    cleared = cfg.clear_disabled_models()
    assert set(cleared) == {"bad-model", "other-bad"}
    assert cfg.is_model_enabled("bad-model")
    assert cfg.is_model_enabled("other-bad")
    assert cfg.clear_disabled_models() == []


def test_abort_and_unload_tries_lm_studio_first():
    with patch("avervox.llm_control.unload_lm_studio_model", return_value=True) as lm, \
         patch("avervox.llm_control.unload_ollama_model") as ollama:
        abort_and_unload("http://spark:1234/v1", "", "omnicoder-9b")
    lm.assert_called_once()
    ollama.assert_not_called()


def test_abort_and_unload_falls_back_to_ollama():
    with patch("avervox.llm_control.unload_lm_studio_model", return_value=False), \
         patch("avervox.llm_control.unload_ollama_model", return_value=True) as ollama:
        abort_and_unload("http://localhost:11434/v1", "", "llama3.2")
    ollama.assert_called_once()


@patch("avervox.llm_control.httpx.post")
def test_unload_lm_studio_posts_instance_id(mock_post):
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
    assert unload_lm_studio_model("http://localhost:1234", "tok", "openai/gpt-oss-120b")
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["json"] == {"instance_id": "openai/gpt-oss-120b"}


@patch("avervox.llm_control.httpx.post")
def test_unload_ollama_uses_keep_alive_zero(mock_post):
    mock_post.return_value = MagicMock(status_code=200, raise_for_status=MagicMock())
    assert unload_ollama_model("http://localhost:11434", "llama3.2")
    assert mock_post.call_args.kwargs["json"] == {"model": "llama3.2", "keep_alive": 0}


def test_empty_stream_raises_after_threshold():
    from avervox.config import LLMProfile
    from avervox.llm import LLMBackend

    backend = LLMBackend(LLMProfile(api_base="http://test", default_model="bad"))
    lines = iter(["data: [DONE]\n"])

    class FakeResp:
        headers = {}

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return lines

    class FakeStream:
        def __enter__(self):
            return FakeResp()

        def __exit__(self, *args):
            return False

    with patch.object(backend._client, "stream", return_value=FakeStream()), \
         patch("avervox.llm.time.perf_counter", side_effect=[0.0, 25.0, EMPTY_RESPONSE_MIN_S + 1]):
        gen = backend.stream_sentences([{"role": "user", "content": "hi"}])
        with pytest.raises(LLMModelFailure, match="empty response"):
            list(gen)


def test_slow_first_token_raises():
    from avervox.config import LLMProfile
    from avervox.llm_control import FIRST_TOKEN_TIMEOUT_S
    from avervox.llm import LLMBackend

    backend = LLMBackend(LLMProfile(api_base="http://test", default_model="omnicoder-9b"))
    keepalive = iter([
        'data: {"choices":[{"delta":{}}]}\n',
        'data: {"choices":[{"delta":{"content":"Hi!"}}]}\n',
    ])

    class FakeResp:
        headers = {}

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return keepalive

    class FakeStream:
        def __enter__(self):
            return FakeResp()

        def __exit__(self, *args):
            return False

    with patch.object(backend._client, "stream", return_value=FakeStream()), \
         patch("avervox.llm.time.perf_counter", side_effect=[0.0, FIRST_TOKEN_TIMEOUT_S + 1, FIRST_TOKEN_TIMEOUT_S + 2]):
        gen = backend.stream_sentences([{"role": "user", "content": "hi"}])
        with pytest.raises(LLMModelFailure, match="no usable output"):
            list(gen)


def test_read_timeout_becomes_model_failure():
    from avervox.config import LLMProfile
    from avervox.llm import LLMBackend

    backend = LLMBackend(LLMProfile(api_base="http://test", default_model="bad"))

    class FakeStream:
        def __enter__(self):
            raise httpx.ReadTimeout("stall")

        def __exit__(self, *args):
            return False

    with patch.object(backend._client, "stream", return_value=FakeStream()):
        gen = backend.stream_sentences([{"role": "user", "content": "hi"}])
        with pytest.raises(LLMModelFailure, match="stalled"):
            list(gen)
