"""Configuration for AverVOX — LLM speech bridge."""

from __future__ import annotations

import os
import logging
from copy import deepcopy
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Optional

import yaml

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


@dataclass
class TTSConfig:
    voice_model: str = ""


@dataclass
class AudioConfig:
    vad_aggressiveness: int = 2  # speech/silence sensitivity (Dictate interim + Converse)
    silence_duration_ms: int = 1000  # pause before interim insert / Converse end-of-turn


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
    silence_timeout_ms: int = 7000
    rearm_delay_ms: int = 250
    goodbye_phrases: list[str] = field(default_factory=lambda: [
        "talk to you later", "goodbye", "bye bye", "see you later",
        "that's all", "good night", "i'm done",
    ])
    interrupt_enabled: bool = False
    interrupt_headphones_confirmed: bool = False


@dataclass
class AppConfig:
    hotkeys: HotkeysConfig = field(default_factory=HotkeysConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    backends: BackendsConfig = field(default_factory=BackendsConfig)
    converse: ConverseConfig = field(default_factory=ConverseConfig)
    llm_active: str = ""
    llm_profiles: dict[str, LLMProfile] = field(default_factory=dict)

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

    def save(self, path: Path = CONFIG_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for sect in ("hotkeys", "stt", "tts", "audio", "backends", "converse"):
            data[sect] = asdict(getattr(self, sect))

        if self.llm_profiles:
            data["llm"] = {
                "active": self.llm_active,
                "profiles": {
                    name: asdict(prof)
                    for name, prof in self.llm_profiles.items()
                },
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
            "backends": (BackendsConfig, "backends"),
            "converse": (ConverseConfig, "converse"),
        }
        for key, (dc_cls, attr) in section_map.items():
            if key in data:
                setattr(cfg, attr, _merge(dc_cls, data[key]))

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

        return cfg


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
