"""Tests for src/avervox/config.py — config loading, defaults, overrides, and warnings."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from avervox.config import (
    AppConfig,
    AudioConfig,
    BackendsConfig,
    HotkeysConfig,
    STTConfig,
    TTSConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)


# ---------------------------------------------------------------------------
# Default config creation
# ---------------------------------------------------------------------------

class TestDefaultConfig:
    def test_default_hotkeys(self):
        cfg = AppConfig()
        assert cfg.hotkeys.listen == "<ctrl>+<alt>+space"
        assert cfg.hotkeys.speak_selection == "<ctrl>+<alt>+s"

    def test_default_stt(self):
        cfg = AppConfig()
        assert cfg.stt.model == "base"
        assert cfg.stt.language == "en"

    def test_default_tts(self):
        cfg = AppConfig()
        assert cfg.tts.voice_model == ""

    def test_default_audio(self):
        cfg = AppConfig()
        assert cfg.audio.vad_aggressiveness == 2
        assert cfg.audio.silence_duration_ms == 1000

    def test_default_backends(self):
        cfg = AppConfig()
        assert cfg.backends.text_inserter == "xdotool"
        assert cfg.backends.selection_provider == "xclip"

    def test_all_sections_present(self):
        cfg = AppConfig()
        assert isinstance(cfg.hotkeys, HotkeysConfig)
        assert isinstance(cfg.stt, STTConfig)
        assert isinstance(cfg.tts, TTSConfig)
        assert isinstance(cfg.audio, AudioConfig)
        assert isinstance(cfg.backends, BackendsConfig)


# ---------------------------------------------------------------------------
# Loading a valid YAML file
# ---------------------------------------------------------------------------

class TestLoadValidYAML:
    def test_loads_stt_overrides(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"stt": {"model": "large-v2", "language": "fr"}})

        cfg = AppConfig.load(cfg_file)

        assert cfg.stt.model == "large-v2"
        assert cfg.stt.language == "fr"

    def test_loads_hotkeys_overrides(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"hotkeys": {"listen": "<ctrl>+<shift>+l"}})

        cfg = AppConfig.load(cfg_file)

        assert cfg.hotkeys.listen == "<ctrl>+<shift>+l"
        assert cfg.hotkeys.speak_selection == "<ctrl>+<alt>+s"

    def test_loads_audio_overrides(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"audio": {"vad_aggressiveness": 3, "silence_duration_ms": 500}})

        cfg = AppConfig.load(cfg_file)

        assert cfg.audio.vad_aggressiveness == 3
        assert cfg.audio.silence_duration_ms == 500

    def test_loads_tts_overrides(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"tts": {"voice_model": "en_US-amy-medium"}})

        cfg = AppConfig.load(cfg_file)

        assert cfg.tts.voice_model == "en_US-amy-medium"

    def test_deprecated_tts_sample_rate_logs_warning(self, tmp_path, caplog):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"tts": {"voice_model": "en_US-amy-medium", "sample_rate": 16000}})

        with caplog.at_level(logging.WARNING, logger="avervox.config"):
            cfg = AppConfig.load(cfg_file)

        assert cfg.tts.voice_model == "en_US-amy-medium"
        assert any("sample_rate" in msg for msg in caplog.messages)

    def test_loads_backends_overrides(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"backends": {"text_inserter": "ydotool"}})

        cfg = AppConfig.load(cfg_file)

        assert cfg.backends.text_inserter == "ydotool"
        assert cfg.backends.selection_provider == "xclip"

    def test_unspecified_sections_keep_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"stt": {"model": "small"}})

        cfg = AppConfig.load(cfg_file)

        assert cfg.hotkeys.listen == "<ctrl>+<alt>+space"
        assert cfg.audio.vad_aggressiveness == 2
        assert cfg.backends.text_inserter == "xdotool"


# ---------------------------------------------------------------------------
# Partial overrides (only some keys in a section)
# ---------------------------------------------------------------------------

class TestPartialOverrides:
    def test_partial_stt_override_preserves_other_key(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"stt": {"model": "tiny"}})

        cfg = AppConfig.load(cfg_file)

        assert cfg.stt.model == "tiny"
        assert cfg.stt.language == "en"

    def test_partial_hotkeys_override_preserves_other_key(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"hotkeys": {"speak_selection": "<ctrl>+<alt>+r"}})

        cfg = AppConfig.load(cfg_file)

        assert cfg.hotkeys.listen == "<ctrl>+<alt>+space"
        assert cfg.hotkeys.speak_selection == "<ctrl>+<alt>+r"


# ---------------------------------------------------------------------------
# Unknown key warnings
# ---------------------------------------------------------------------------

class TestUnknownKeyWarnings:
    def test_unknown_top_level_key_is_ignored_silently(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"stt": {"model": "base"}, "nonexistent_section": True})

        cfg = AppConfig.load(cfg_file)
        assert cfg.stt.model == "base"

    def test_unknown_key_in_stt_logs_warning(self, tmp_path, caplog):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"stt": {"model": "base", "typo_key": "oops"}})

        with caplog.at_level(logging.WARNING, logger="avervox.config"):
            cfg = AppConfig.load(cfg_file)

        assert any("typo_key" in msg for msg in caplog.messages)
        assert cfg.stt.model == "base"

    def test_unknown_key_in_hotkeys_logs_warning(self, tmp_path, caplog):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"hotkeys": {"listem": "<ctrl>+<alt>+space"}})

        with caplog.at_level(logging.WARNING, logger="avervox.config"):
            cfg = AppConfig.load(cfg_file)

        assert any("listem" in msg for msg in caplog.messages)

    def test_unknown_key_in_audio_logs_warning(self, tmp_path, caplog):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"audio": {"vad_aggressiveness": 1, "unknown_audio_opt": 99}})

        with caplog.at_level(logging.WARNING, logger="avervox.config"):
            cfg = AppConfig.load(cfg_file)

        assert any("unknown_audio_opt" in msg for msg in caplog.messages)
        assert cfg.audio.vad_aggressiveness == 1

    def test_unknown_key_does_not_raise(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"tts": {"bad_key": "value"}})

        cfg = AppConfig.load(cfg_file)
        assert isinstance(cfg, AppConfig)

    def test_multiple_unknown_keys_each_warned(self, tmp_path, caplog):
        cfg_file = tmp_path / "config.yaml"
        write_yaml(cfg_file, {"backends": {"text_inserter": "xdotool", "foo": 1, "bar": 2}})

        with caplog.at_level(logging.WARNING, logger="avervox.config"):
            AppConfig.load(cfg_file)

        messages = " ".join(caplog.messages)
        assert "foo" in messages
        assert "bar" in messages


# ---------------------------------------------------------------------------
# Missing / empty file
# ---------------------------------------------------------------------------

class TestMissingOrEmptyFile:
    def test_missing_file_returns_defaults_and_creates_file(self, tmp_path):
        cfg_file = tmp_path / "avervox" / "config.yaml"

        cfg = AppConfig.load(cfg_file)

        assert isinstance(cfg, AppConfig)
        assert cfg.stt.model == "base"
        assert cfg_file.exists()

    def test_empty_file_returns_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("")

        cfg = AppConfig.load(cfg_file)

        assert isinstance(cfg, AppConfig)
        assert cfg.hotkeys.listen == "<ctrl>+<alt>+space"
        assert cfg.audio.vad_aggressiveness == 2

    def test_whitespace_only_file_returns_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("   \n\n  ")

        cfg = AppConfig.load(cfg_file)

        assert isinstance(cfg, AppConfig)
        assert cfg.backends.text_inserter == "xdotool"

    def test_saved_default_is_valid_yaml(self, tmp_path):
        cfg_file = tmp_path / "avervox" / "config.yaml"

        AppConfig.load(cfg_file)

        with open(cfg_file) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "stt" in data
        assert "hotkeys" in data
