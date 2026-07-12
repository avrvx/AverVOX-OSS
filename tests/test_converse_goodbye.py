"""Tests for converse goodbye detection."""

from __future__ import annotations

from avervox.main import (
    _DEFAULT_GOODBYE_PHRASES,
    _is_terse_goodbye,
    _matches_goodbye,
)


def test_talk_soon_triggers_goodbye():
    text = (
        "oh, nothing, you don't need to check anything. "
        "this has been very helpful, thank you. we'll talk soon."
    )
    assert _matches_goodbye(text, _DEFAULT_GOODBYE_PHRASES)


def test_terse_bye_bye_skips_llm():
    assert _is_terse_goodbye("okay, bye bye.")


def test_long_farewell_with_talk_soon_is_not_terse():
    text = (
        "oh, nothing, you don't need to check anything. "
        "this has been very helpful, thank you. we'll talk soon."
    )
    assert _matches_goodbye(text, _DEFAULT_GOODBYE_PHRASES)
    assert not _is_terse_goodbye(text)


def test_normal_message_is_not_goodbye():
    assert not _matches_goodbye("we are testing right now", _DEFAULT_GOODBYE_PHRASES)
