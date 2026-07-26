"""``avrvx --doctor`` — preflight checks for a working AverVOX installation.

Answers "will this machine run AverVOX?" before anything is purchased or
debugged: distro, display server, system binaries, Python dependencies,
microphone, playback, models, text insertion, the configured LLM endpoint,
the warm daemon, host integrations, and edition/license state.

Non-intrusive by design: it captures a short microphone sample and queries
the playback device, but never plays audio, types into windows, or modifies
a file. Proving synthesis end to end is ``--install-integration``'s job.

Exit codes match integration_install: 0 all clear (warnings allowed),
1 when any check fails.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
INFO = "INFO"

#: Distros the documentation promises; everything else is untested, not banned.
SUPPORTED_DISTROS = ("ubuntu", "linuxmint")

#: Binaries AverVOX spawns at runtime. notify-send only costs notifications.
REQUIRED_BINARIES = ("xdotool", "xclip", "parec")
OPTIONAL_BINARIES = ("notify-send",)

#: Python packages both editions import at runtime.
PYTHON_DEPS = ("gi", "sounddevice", "webrtcvad", "faster_whisper", "piper")

#: ~0.1 s of 16 kHz mono s16le — enough to prove frames are flowing.
MIC_PROBE_BYTES = 3200
MIC_PROBE_TIMEOUT_S = 5.0

ENDPOINT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Result:
    status: str
    name: str
    finding: str
    hint: str = ""


def _say(message: str = "") -> None:
    print(message, flush=True)


def _spawn_env() -> dict[str, str]:
    """Environment safe for host binaries; matches host_env where it exists."""
    try:
        from .host_env import host_env  # Pro/dev tree

        return host_env()
    except ImportError:
        env = os.environ.copy()
        for key in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
            env.pop(key, None)
        return env


# ── Checks ───────────────────────────────────────────────────────────────────


def check_distro(os_release: Path = Path("/etc/os-release")) -> Result:
    try:
        raw = os_release.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Result(WARN, "distro", "cannot read /etc/os-release",
                      "AverVOX targets Linux Mint and Ubuntu.")
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip().strip('"')
    pretty = fields.get("PRETTY_NAME") or fields.get("NAME", "unknown")
    family = {fields.get("ID", "").lower()}
    family.update(fields.get("ID_LIKE", "").lower().split())
    if family & set(SUPPORTED_DISTROS):
        return Result(PASS, "distro", pretty)
    return Result(WARN, "distro", f"{pretty} — untested, not unsupported",
                  "AverVOX is developed and tested on Linux Mint and Ubuntu.")


def check_display(environ: dict[str, str] | None = None) -> Result:
    env = os.environ if environ is None else environ
    session = env.get("XDG_SESSION_TYPE", "").lower()
    display = env.get("DISPLAY", "")
    wayland = env.get("WAYLAND_DISPLAY", "")
    if display:
        if session == "wayland" or wayland:
            return Result(PASS, "display",
                          f"Wayland session with XWayland (DISPLAY={display})")
        return Result(PASS, "display", f"X11 session (DISPLAY={display})")
    if session == "wayland" or wayland:
        return Result(FAIL, "display", "pure Wayland session — no X display",
                      "xdotool and xclip need an X display. Enable XWayland "
                      "or log into an X11 session.")
    return Result(FAIL, "display", "no graphical display (DISPLAY unset)",
                  "Run doctor inside the desktop session AverVOX will use.")


def check_system_binaries() -> Result:
    missing = [b for b in REQUIRED_BINARIES if not shutil.which(b)]
    missing_optional = [b for b in OPTIONAL_BINARIES if not shutil.which(b)]
    if missing:
        return Result(FAIL, "system binaries", f"missing: {', '.join(missing)}",
                      "Install them (Mint/Ubuntu: apt install xdotool xclip "
                      "pulseaudio-utils) or run install.sh.")
    if missing_optional:
        return Result(WARN, "system binaries",
                      f"required tools present; missing: {', '.join(missing_optional)}",
                      "Only desktop notifications are affected.")
    found = ", ".join(REQUIRED_BINARIES + OPTIONAL_BINARIES)
    return Result(PASS, "system binaries", f"all present ({found})")


def check_python_deps() -> Result:
    import importlib

    missing: list[str] = []
    for name in PYTHON_DEPS:
        try:
            importlib.import_module(name)
        except Exception:
            missing.append(name)
    if missing:
        return Result(FAIL, "python packages", f"cannot import: {', '.join(missing)}",
                      "Re-run install.sh, or pip install avrvx into the "
                      "environment this avrvx runs from.")
    return Result(PASS, "python packages",
                  f"all importable ({', '.join(PYTHON_DEPS)})")


def check_microphone() -> Result:
    if not shutil.which("parec"):
        return Result(FAIL, "microphone", "parec is not installed",
                      "Install pulseaudio-utils; AverVOX records through "
                      "PulseAudio/PipeWire.")
    argv = ["parec", "--format=s16le", "--rate=16000", "--channels=1"]
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=_spawn_env())
    except OSError as exc:
        return Result(FAIL, "microphone", f"could not start parec: {exc}")
    # parec streams forever (silence included), so read a fixed amount with a
    # watchdog instead of waiting for an exit that never comes.
    watchdog = threading.Timer(MIC_PROBE_TIMEOUT_S, proc.kill)
    watchdog.start()
    try:
        data = proc.stdout.read(MIC_PROBE_BYTES) if proc.stdout else b""
    finally:
        watchdog.cancel()
        proc.kill()
        proc.wait()
    if len(data) >= MIC_PROBE_BYTES:
        return Result(PASS, "microphone", "default source is delivering audio")
    return Result(FAIL, "microphone", "no audio frames from the default source",
                  "Check that a microphone is connected and selected as the "
                  "default input in your sound settings.")


def check_playback() -> Result:
    try:
        import sounddevice

        device = sounddevice.query_devices(kind="output")
    except Exception as exc:
        return Result(FAIL, "playback", f"no default output device: {exc}",
                      "Check your sound settings; AverVOX plays audio through "
                      "the default output.")
    name = device["name"] if isinstance(device, dict) else str(device)
    return Result(PASS, "playback", f"default output: {name}")


def _hf_cache_dir() -> Path:
    if "HF_HUB_CACHE" in os.environ:
        return Path(os.environ["HF_HUB_CACHE"])
    if "HF_HOME" in os.environ:
        return Path(os.environ["HF_HOME"]) / "hub"
    return Path(os.environ.get("XDG_CACHE_HOME",
                               Path.home() / ".cache")) / "huggingface" / "hub"


def check_stt_model(cfg) -> Result:
    model = cfg.stt.model
    candidate = Path(model).expanduser()
    if candidate.exists():
        return Result(PASS, "STT model", f"local model at {candidate}")
    cached = list(_hf_cache_dir().glob(f"models--*faster-whisper-{model}"))
    if cached:
        return Result(PASS, "STT model", f"faster-whisper '{model}' is cached")
    return Result(WARN, "STT model",
                  f"faster-whisper '{model}' not downloaded yet",
                  "It downloads automatically on first use; the first "
                  "dictation needs the network and a short wait.")


def _kokoro_models_dir() -> Path:
    # Mirrors tts._KokoroBackend without importing the TTS stack.
    return Path(os.environ.get("XDG_DATA_HOME",
                               Path.home() / ".local" / "share")) / "avervox" / "kokoro"


def check_tts_voice(cfg) -> Result:
    engine = getattr(cfg.tts, "engine", "piper")
    if engine == "kokoro":
        models_dir = _kokoro_models_dir()
        missing = [f for f in ("kokoro-v1.0.onnx", "voices-v1.0.bin")
                   if not (models_dir / f).exists()]
        if missing:
            return Result(FAIL, "TTS voice",
                          f"Kokoro engine selected but {', '.join(missing)} "
                          f"missing from {models_dir}",
                          "Run install.sh or download the files from "
                          "https://github.com/thewh1teagle/kokoro-onnx/releases")
        voice = getattr(cfg.tts, "kokoro_voice", "af_heart")
        return Result(PASS, "TTS voice", f"Kokoro models present (voice {voice})")
    voice_model = cfg.tts.voice_model
    if not voice_model:
        return Result(FAIL, "TTS voice", "no Piper voice configured",
                      "Run install.sh, or set tts.voice_model in "
                      "~/.config/avervox/config.yaml to a Piper .onnx file.")
    voice_path = Path(voice_model).expanduser()
    if not voice_path.exists():
        return Result(FAIL, "TTS voice", f"configured voice missing: {voice_path}",
                      "Re-run install.sh or point tts.voice_model at an "
                      "existing Piper .onnx file.")
    sidecar = Path(str(voice_path) + ".json")
    if not sidecar.exists():
        return Result(WARN, "TTS voice",
                      f"{voice_path.name} present, but its .onnx.json sidecar "
                      "is missing",
                      "Piper falls back to a guessed sample rate; download "
                      "the matching .onnx.json next to the voice.")
    return Result(PASS, "TTS voice", f"Piper voice {voice_path.name}")


def check_text_insertion(environ: dict[str, str] | None = None) -> Result:
    env = os.environ if environ is None else environ
    if not shutil.which("xdotool"):
        return Result(FAIL, "text insertion", "xdotool is not installed",
                      "apt install xdotool — dictation types through it.")
    if not env.get("DISPLAY"):
        return Result(FAIL, "text insertion", "no X display for xdotool",
                      "See the display check above.")
    try:
        proc = subprocess.run(["xdotool", "version"], capture_output=True,
                              text=True, timeout=10, env=_spawn_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Result(FAIL, "text insertion", f"xdotool did not answer: {exc}")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return Result(FAIL, "text insertion", f"xdotool failed: {detail}")
    return Result(PASS, "text insertion",
                  "xdotool answers on this display (doctor does not type "
                  "into windows)")


def check_llm_endpoint(cfg) -> Result:
    profile = cfg.llm
    api_base = (profile.api_base or "").strip()
    label = profile.label or getattr(profile, "display_name", "") or api_base
    if not api_base:
        return Result(WARN, "LLM endpoint", "no endpoint configured",
                      "Converse works once you add one — local Ollama or "
                      "LM Studio, or any OpenAI-compatible URL.")
    url = api_base.rstrip("/") + "/models"
    try:
        import httpx

        response = httpx.get(url, timeout=ENDPOINT_TIMEOUT_S,
                             follow_redirects=True)
    except Exception as exc:
        return Result(FAIL, "LLM endpoint", f"cannot reach {label}: {exc}",
                      "Is the server running, and the URL right? Doctor "
                      "checks reachability only and sends no API key.")
    # Any HTTP answer proves the server is there; 401/404 just mean the
    # unauthenticated probe was turned away, which is fine.
    return Result(PASS, "LLM endpoint",
                  f"{label} answered HTTP {response.status_code}")


def check_daemon() -> Result:
    try:
        from .bridge_server import is_running

        running = is_running()
    except Exception:
        running = False
    if running:
        return Result(INFO, "warm daemon", "running — hosts get fast first audio")
    return Result(INFO, "warm daemon",
                  "not running (optional — start with avrvx --daemon for "
                  "faster host integrations)")


def check_integrations() -> Result:
    from .integration_install import _hosts

    states: list[str] = []
    for key, host in sorted(_hosts().items()):
        try:
            configured = (host.config.exists()
                          and "avervox" in host.config.read_text(
                              encoding="utf-8", errors="replace").lower())
        except OSError:
            configured = False
        states.append(f"{key}: {'configured' if configured else 'not configured'}")
    return Result(INFO, "integrations", "; ".join(states))


def check_edition(cfg) -> list[Result]:
    from . import __edition__ as edition, __version__

    results: list[Result] = []
    if edition == "pro":
        try:
            from .license import LicenseManager

            valid = LicenseManager.load().is_valid()
        except Exception:
            valid = False
        if valid:
            results.append(Result(PASS, "edition",
                                  f"AverVOX Pro {__version__}, license valid"))
        else:
            results.append(Result(FAIL, "edition",
                                  f"AverVOX Pro {__version__}, no valid license",
                                  "Activate your license key from the tray "
                                  "menu or Dashboard."))
        wake = getattr(cfg, "wake_word", None)
        if wake is not None and wake.enabled:
            try:
                from .wakeword import wake_word_model_valid

                model_ok = bool(wake.model_path) and wake_word_model_valid(
                    wake.model_path)
            except Exception:
                model_ok = False
            if model_ok:
                results.append(Result(PASS, "wake word",
                                      f"model at {wake.model_path}"))
            else:
                results.append(Result(WARN, "wake word",
                                      "enabled, but its model file is missing "
                                      "or invalid",
                                      "Pick a valid .onnx model in "
                                      "Preferences, or disable the wake word."))
    else:
        results.append(Result(INFO, "edition",
                              f"AverVOX OSS {__version__} — Pro adds Kokoro "
                              "TTS, wake word, session memory, and LAN mode "
                              "(avervoxpro.com)"))
    return results


# ── Runner ───────────────────────────────────────────────────────────────────


def collect() -> list[Result]:
    """Run every check; config problems become a single failed check."""
    results = [
        check_distro(),
        check_display(),
        check_system_binaries(),
        check_python_deps(),
        check_microphone(),
        check_playback(),
    ]
    try:
        from .config import get_config

        cfg = get_config()
    except Exception as exc:
        results.append(Result(FAIL, "configuration",
                              f"could not load config: {exc}",
                              "Fix or remove ~/.config/avervox/config.yaml "
                              "and run doctor again."))
        cfg = None
    if cfg is not None:
        results.append(check_stt_model(cfg))
        results.append(check_tts_voice(cfg))
    results.append(check_text_insertion())
    if cfg is not None:
        results.append(check_llm_endpoint(cfg))
    results.append(check_daemon())
    results.append(check_integrations())
    results.extend(check_edition(cfg))
    return results


def run() -> int:
    from . import __edition__ as edition, __version__

    label = {"pro": "Pro", "oss": "OSS"}.get(edition, edition)
    _say(f"AverVOX {label} {__version__} — doctor\n")
    results = collect()

    width = len(str(len(results)))
    for index, result in enumerate(results, start=1):
        _say(f"{index:>{width}}. {result.status:<4}  "
             f"{result.name}: {result.finding}")
        if result.hint and result.status in (WARN, FAIL):
            _say(f"{' ' * (width + 8)}{result.hint}")

    warnings = sum(1 for r in results if r.status == WARN)
    failures = sum(1 for r in results if r.status == FAIL)
    passed = len(results) - warnings - failures

    _say()
    if failures == 0 and warnings == 0:
        _say(f"{len(results)} checks passed")
        return EXIT_OK
    parts = [f"{passed} passed"]
    if warnings:
        parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    if failures:
        parts.append(f"{failures} failed")
    _say(", ".join(parts))
    return EXIT_FAILED if failures else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
