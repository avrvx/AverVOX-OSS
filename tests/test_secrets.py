"""Tests for src/avervox/secrets_store.py and encrypted config fields."""

from __future__ import annotations

import pytest
import yaml

from avervox.config import AppConfig, LLMProfile
from avervox.secrets_store import decrypt, encrypt, is_encrypted


class TestSecretsStore:
    def test_round_trip(self):
        plain = "sk-test-api-key-12345"
        stored = encrypt(plain)
        assert is_encrypted(stored)
        assert decrypt(stored) == plain

    def test_plaintext_passthrough(self):
        assert decrypt("plain-old-key") == "plain-old-key"
        assert decrypt("") == ""

    def test_double_encrypt_is_idempotent(self):
        once = encrypt("secret")
        twice = encrypt(once)
        assert twice == once

    def test_tampered_blob_fails(self):
        stored = encrypt("secret")
        idx = len("enc:") + 5
        bad = stored[:idx] + ("A" if stored[idx] != "A" else "B") + stored[idx + 1:]
        with pytest.raises(ValueError):
            decrypt(bad)


class TestEncryptedConfig:
    def test_api_key_encrypted_on_save(self, tmp_path):
        cfg = AppConfig()
        cfg.llm_profiles["default"] = LLMProfile(
            label="Test",
            api_base="http://localhost:1234/v1",
            api_key="sk-live-secret",
        )
        cfg.llm_active = "default"
        cfg_path = tmp_path / "config.yaml"
        cfg.save(cfg_path)

        raw = yaml.safe_load(cfg_path.read_text())
        stored = raw["llm"]["profiles"]["default"]["api_key"]
        assert is_encrypted(stored)
        assert "sk-live-secret" not in cfg_path.read_text()

    def test_api_key_decrypted_on_load(self, tmp_path):
        cfg = AppConfig()
        cfg.llm_profiles["default"] = LLMProfile(api_key="sk-reload-me")
        cfg.llm_active = "default"
        cfg_path = tmp_path / "config.yaml"
        cfg.save(cfg_path)

        loaded = AppConfig.load(cfg_path)
        assert loaded.llm.api_key == "sk-reload-me"

    def test_legacy_plaintext_api_key_still_loads(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({
            "llm": {
                "active": "default",
                "profiles": {
                    "default": {
                        "label": "Legacy",
                        "api_base": "http://localhost/v1",
                        "api_key": "plain-old-key",
                    },
                },
            },
        }))

        loaded = AppConfig.load(cfg_path)
        assert loaded.llm.api_key == "plain-old-key"
