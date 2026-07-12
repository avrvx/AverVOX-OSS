"""Configuration for AverVOX — LLM speech bridge."""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Optional

import yaml

from .secrets_store import decrypt, encrypt

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "avervox"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


@dataclass
class HotkeysConfig:
    listen: str = "<ctrl>+<alt>+space"
    speak_selection: str = "<ctrl>+<alt>+s"
    converse: str = "<ctrl>+<alt>+c"


@dataclass
class STTConfig:
    model: str = "base"
    language: str = "en"
    device: str = "auto"  # auto | cpu | cuda


@dataclass
class TTSConfig:
    voice_model: str = ""


@dataclass
class AudioConfig:
    vad_aggressiveness: int = 1


@dataclass
class DictateConfig:
    interim_pause_ms: int = 1000


@dataclass
class BackendsConfig:
    text_inserter: str = "xdotool"
    selection_provider: str = "xclip"


@dataclass
class LLMProfile:
    label: str = ""
    api_base: str = ""
    api_key: str = ""
    default_model: str = ""
    session_header: str = ""


@dataclass
class ConverseConfig:
    end_of_turn_ms: int = 1100
    silence_timeout_ms: int = 7000
    rearm_delay_ms: int = 250
    early_listen_ms: int = 300
    goodbye_phrases: list[str] = field(default_factory=lambda: [
        "talk to you later", "talk soon", "we'll talk soon",
        "goodbye", "bye bye", "bye for now",
        "see you later", "see you soon", "catch you later",
        "that's all", "good night", "i'm done",
    ])
    interrupt_enabled: bool = False
    interrupt_mode: str = "vad"  # OSS: VAD only (legacy wake_word configs migrate to vad)
    interrupt_headphones_confirmed: bool = False


@dataclass
class AppConfig:
    hotkeys: HotkeysConfig = field(default_factory=HotkeysConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    dictate: DictateConfig = field(default_factory=DictateConfig)
    backends: BackendsConfig = field(default_factory=BackendsConfig)
    converse: ConverseConfig = field(default_factory=ConverseConfig)
    llm_active: str = ""
    llm_profiles: dict[str, LLMProfile] = field(default_factory=dict)
    disabled_models: dict[str, str] = field(default_factory=dict)

    @property
    def llm(self) -> LLMProfile:
        """Return the active LLM profile. All existing callers keep working."""
        if self.llm_active and self.llm_active in self.llm_profiles:
            return self.llm_profiles[self.llm_active]
        if self.llm_profiles:
            first = next(iter(self.llm_profiles))
            self.llm_active = first
            return self.llm_profiles[first]
        return LLMProfile()

    def set_active_profile(self, name: str) -> None:
        """Switch to a different LLM profile by name."""
        if name in self.llm_profiles:
            self.llm_active = name

    def mark_model_failed(
        self, model_id: str, reason: str, catalog: list[str] | None = None,
    ) -> list[str]:
        """Disable a model; return other enabled model ids from *catalog*."""
        self.disabled_models[model_id] = reason
        if not catalog:
            return []
        disabled = set(self.disabled_models)
        return [m for m in catalog if m not in disabled]

    def clear_disabled_models(self) -> list[str]:
        """Re-enable all disabled models; return cleared model ids."""
        cleared = list(self.disabled_models)
        self.disabled_models.clear()
        return cleared

    def is_model_enabled(self, model_id: str) -> bool:
        return model_id not in self.disabled_models

    def save(self, path: Path = CONFIG_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for sect in ("hotkeys", "stt", "tts", "audio", "dictate", "backends", "converse"):
            data[sect] = asdict(getattr(self, sect))

        data["disabled_models"] = dict(self.disabled_models)

        if self.llm_profiles:
            profiles_out = {}
            for name, prof in self.llm_profiles.items():
                prof_data = asdict(prof)
                prof_data["api_key"] = _encrypt_config_secret(prof_data.get("api_key", ""))
                profiles_out[name] = prof_data
            data["llm"] = {
                "active": self.llm_active,
                "profiles": profiles_out,
            }
        else:
            data["llm"] = {}

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "AppConfig":
        if not path.exists():
            cfg = cls()
            cfg.save(path)
            return cfg
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "AppConfig":
        _log = logging.getLogger(__name__)

        def _merge(dc_cls, d):
            obj = dc_cls()
            if not isinstance(d, dict):
                return obj
            valid_keys = {f.name for f in fields(dc_cls)}
            for key, val in d.items():
                if key in valid_keys:
                    if key in _SECRET_CONFIG_FIELDS and isinstance(val, str):
                        val = _decrypt_config_secret(val)
                    setattr(obj, key, val)
                else:
                    _log.warning(
                        "Unknown config key %r in [%s] — ignoring (check for typos)",
                        key, dc_cls.__name__,
                    )
            return obj

        cfg = cls()
        section_map = {
            "hotkeys": (HotkeysConfig, "hotkeys"),
            "stt": (STTConfig, "stt"),
            "tts": (TTSConfig, "tts"),
            "audio": (AudioConfig, "audio"),
            "dictate": (DictateConfig, "dictate"),
            "backends": (BackendsConfig, "backends"),
            "converse": (ConverseConfig, "converse"),
        }
        for key, (dc_cls, attr) in section_map.items():
            if key in data:
                setattr(cfg, attr, _merge(dc_cls, data[key]))

        disabled = data.get("disabled_models")
        if isinstance(disabled, dict):
            cfg.disabled_models = {str(k): str(v) for k, v in disabled.items()}

        llm_data = data.get("llm", {})
        if isinstance(llm_data, dict) and "profiles" in llm_data:
            cfg.llm_active = llm_data.get("active", "")
            raw_profiles = llm_data.get("profiles", {})
            for name, prof_data in raw_profiles.items():
                if isinstance(prof_data, dict):
                    cfg.llm_profiles[name] = _merge(LLMProfile, prof_data)
        elif isinstance(llm_data, dict) and llm_data.get("api_base"):
            profile = _merge(LLMProfile, llm_data)
            slug = _slugify(profile.label or profile.api_base or "default")
            if not profile.label:
                profile.label = profile.api_base or "Default"
            cfg.llm_profiles[slug] = profile
            cfg.llm_active = slug

        converse_data = data.get("converse", {})
        if isinstance(converse_data, dict) and "interrupt_mode" not in converse_data:
            if converse_data.get("interrupt_headphones_confirmed"):
                cfg.converse.interrupt_mode = "vad"

        # Migrate legacy audio.silence_duration_ms → dictate + converse keys
        audio_data = data.get("audio", {})
        if isinstance(audio_data, dict):
            legacy_pause = audio_data.get("silence_duration_ms")
            if legacy_pause is not None:
                if "dictate" not in data:
                    cfg.dictate.interim_pause_ms = int(legacy_pause)
                if isinstance(converse_data, dict) and "end_of_turn_ms" not in converse_data:
                    cfg.converse.end_of_turn_ms = min(int(legacy_pause), 1200)

        return cfg


_SECRET_CONFIG_FIELDS = frozenset({"api_key"})


def _encrypt_config_secret(value: str) -> str:
    if not value:
        return value
    return encrypt(value)


def _decrypt_config_secret(value: str) -> str:
    if not value:
        return value
    try:
        return decrypt(value)
    except ValueError:
        logging.getLogger(__name__).warning(
            "Could not decrypt a stored secret — treating as empty (re-enter in Settings)"
        )
        return ""


def _slugify(text: str) -> str:
    """Generate a simple URL-safe key from a label or URL."""
    import re
    text = text.strip().lower()
    text = re.sub(r'https?://', '', text)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')[:40] or "default"


_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig.load()
    return _config


def reload_config() -> AppConfig:
    global _config
    _config = AppConfig.load()
    return _config
