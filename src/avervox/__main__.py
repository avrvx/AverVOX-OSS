"""AverVOX OSS — LLM speech bridge.

Usage:
  avrvx                 Launch the tray app (hotkeys active)
  avrvx --listen        Capture speech (VAD auto-stop), print transcript, exit
  avrvx --speak         Read stdin, synthesize via TTS, play, exit
  avrvx --speak "text"  Speak literal text, exit
  avrvx --synthesize --output PATH [--text … | --text-file … | stdin]
  avrvx --transcribe PATH
  avrvx --capabilities  Print JSON capability probe for host integrations
  avrvx --install-integration HOST   Configure a host and verify it works
"""

import json
import os
import signal
import sys
import faulthandler
import argparse
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
faulthandler.enable(file=sys.stderr, all_threads=True)

signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def _configure_stt():
    from .config import get_config
    from . import stt

    cfg = get_config()
    stt.configure(model=cfg.stt.model, language=cfg.stt.language, device=cfg.stt.device)
    return stt


def _configure_tts():
    from .config import get_config
    from . import tts

    cfg = get_config()
    tts.configure(voice_model=cfg.tts.voice_model)
    return tts


def _cli_listen() -> None:
    """Record until VAD detects silence, transcribe, print to stdout."""
    from .audio import AudioCapture, SAMPLE_RATE

    stt = _configure_stt()
    stt.preload()

    audio_cap = AudioCapture()
    from .config import get_config

    cfg = get_config()
    audio_cap.configure(
        aggressiveness=cfg.audio.vad_aggressiveness,
        converse_end_ms=cfg.converse.end_of_turn_ms,
    )

    import threading

    result = [None]
    done = threading.Event()

    def on_segment(audio):
        result[0] = audio
        done.set()

    audio_cap.set_on_segment(on_segment)
    audio_cap.start()

    sys.stderr.write("Listening... (speak, then pause)\n")
    sys.stderr.flush()
    done.wait()
    capture = audio_cap.stop()

    if capture is not None and len(capture.audio) > 0:
        text = stt.listen(capture.audio, SAMPLE_RATE)
        if text:
            print(text)
        else:
            sys.stderr.write("(no speech detected)\n")
    else:
        sys.stderr.write("(no audio captured)\n")


def _voice_overrides(args) -> dict:
    """Per-request voice/speed, omitting anything the caller left unset."""
    return {
        k: v
        for k, v in (("voice", args.voice), ("speed", args.speed))
        if v is not None
    }


# Distinct from 1 (failure) so an adapter can tell "the user hit stop" from
# "synthesis broke" without parsing stderr.
EXIT_CANCELLED = 130


def _install_cancel_handler(tts) -> None:
    """Turn SIGTERM/SIGINT into a clean stop instead of a killed process."""
    def _on_signal(_signum, _frame):
        tts.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (OSError, ValueError):
            pass  # not the main thread, or the platform disallows it


def _cli_speak(text: str, **overrides) -> None:
    """Synthesize and play text."""
    tts = _configure_tts()
    _install_cancel_handler(tts)
    tts.speak(text, **overrides)
    # speak() returns quietly when interrupted, so the exit code carries the news.
    if tts.is_stopped():
        sys.stderr.write("avrvx --speak cancelled\n")
        sys.exit(EXIT_CANCELLED)


def _cli_synthesize_stdout(text: str, **overrides) -> None:
    """Stream raw PCM to stdout so shell pipelines can start playing at once."""
    tts = _configure_tts()
    _install_cancel_handler(tts)
    announced = False
    try:
        for pcm, rate in tts.synthesize_stream(text, **overrides):
            if not announced:
                # Headerless audio, so the format goes to stderr where it cannot
                # corrupt it — before any samples, so a pipeline can set up.
                sys.stderr.write(f"format: pcm_s16le mono {rate} Hz\n")
                sys.stderr.flush()
                announced = True
            sys.stdout.buffer.write(pcm.tobytes())
            sys.stdout.buffer.flush()
    except tts.Cancelled:
        sys.stderr.write("avrvx --synthesize cancelled\n")
        sys.exit(EXIT_CANCELLED)
    # A reader that hangs up early (`| head -c`) kills us with SIGPIPE, which
    # is left at SIG_DFL above so avrvx behaves like any other pipeline tool.
    except (OSError, RuntimeError, ValueError) as exc:
        sys.stderr.write(f"avrvx --synthesize failed: {exc}\n")
        sys.exit(1)


def _cli_synthesize(text: str, output: str, **overrides) -> None:
    """Synthesize text to a WAV file (no playback)."""
    if output == "-":
        _cli_synthesize_stdout(text, **overrides)
        return
    tts = _configure_tts()
    _install_cancel_handler(tts)
    try:
        path = tts.synthesize_to_file(text, output, **overrides)
    except tts.Cancelled:
        sys.stderr.write("avrvx --synthesize cancelled\n")
        sys.exit(EXIT_CANCELLED)
    except (OSError, RuntimeError, ValueError) as exc:
        # Host integrations parse stderr, so a traceback is noise to them.
        sys.stderr.write(f"avrvx --synthesize failed: {exc}\n")
        sys.exit(1)
    print(path)


def _cli_transcribe(audio_path: str) -> None:
    """Transcribe an audio file; print transcript to stdout."""
    stt = _configure_stt()
    stt.preload()
    try:
        text = stt.transcribe_file(audio_path)
    except (OSError, RuntimeError, ValueError) as exc:
        sys.stderr.write(f"avrvx --transcribe failed: {exc}\n")
        sys.exit(1)
    if text:
        print(text)
    else:
        sys.stderr.write("(no speech detected)\n")
        sys.exit(1)


def _cli_daemon() -> None:
    """Run the warm speech bridge for host integrations."""
    from .bridge_server import serve, socket_path

    try:
        serve()
    except OSError as exc:
        sys.stderr.write(f"avrvx --daemon failed: {exc}\n")
        sys.stderr.write(f"socket: {socket_path()}\n")
        sys.exit(1)


def _cli_capabilities() -> None:
    """Emit a JSON capability probe for host integrations."""
    from . import __edition__ as edition, __version__
    from .config import get_config

    cfg = get_config()

    try:
        from .bridge_server import is_running, socket_path

        daemon_socket = str(socket_path())
        daemon_running = is_running()
    except Exception:
        daemon_socket, daemon_running = "", False

    try:
        from . import tts as _tts

        _tts.configure(voice_model=cfg.tts.voice_model)
        voices = _tts.list_voices()
        rate = _tts.sample_rate()
    except Exception as exc:  # enumeration is best-effort; the probe must not fail
        sys.stderr.write(f"could not enumerate voices: {exc}\n")
        voices, rate = [], 0

    payload = {
        "product": f"avervox-{edition}",
        "edition": edition,
        # OSS needs no activation, so nothing is ever license-gated.
        "licensed": True,
        "version": __version__,
        "cli": "avrvx",
        "tts": {
            "engines": ["piper"],
            "active_engine": "piper",
            "synthesize_to_file": True,
            "formats": ["wav"],
            "voices": voices,
            "active_voice": cfg.tts.voice_model,
            "speed": 1.0,
            # Hosts that open an audio device before the first chunk arrives
            # need the rate up front; it varies by Piper voice.
            "sample_rate": rate,
        },
        "stt": {
            "engine": "faster-whisper",
            "model": cfg.stt.model,
            "transcribe_file": True,
            "listen_mic": True,
        },
        "features": {
            "speak_playback": True,
            "listen_mic": True,
            "synthesize": True,
            "transcribe": True,
            "serve": False,
            "wake_word": False,
            "session_memory": False,
            "kokoro": False,
            "daemon": True,
        },
        "daemon": {
            "socket": daemon_socket,
            "running": daemon_running,
            "protocol": 1,
        },
    }
    print(json.dumps(payload, indent=2))


def _resolve_synthesize_text(args) -> str:
    if args.text_file:
        return Path(args.text_file).expanduser().read_text(encoding="utf-8")
    if args.text is not None:
        if args.text == "-":
            return sys.stdin.read()
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def main():
    from . import __version__
    from .integration_install import HOST_CHOICES

    parser = argparse.ArgumentParser(
        prog="avrvx",
        description="AverVOX — Add voice to any LLM using an OpenAI-compatible endpoint.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"AverVOX OSS {__version__}",
    )
    parser.add_argument(
        "--listen",
        action="store_true",
        help="Capture speech and print transcript to stdout",
    )
    parser.add_argument(
        "--speak",
        nargs="?",
        const="-",
        default=None,
        help="Speak text (from argument or stdin)",
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        help="Synthesize speech to a WAV file (requires --output)",
    )
    parser.add_argument(
        "--transcribe",
        metavar="AUDIO",
        default=None,
        help="Transcribe an audio file; print transcript to stdout",
    )
    parser.add_argument(
        "--capabilities",
        action="store_true",
        help="Print JSON capability probe for host integrations",
    )
    parser.add_argument(
        "--install-integration",
        metavar="HOST",
        default=None,
        help=(
            "Write the AverVOX speech config for a host and verify synthesis "
            f"works ({', '.join(HOST_CHOICES)})"
        ),
    )
    parser.add_argument(
        "--text",
        nargs="?",
        const="-",
        default=None,
        help="Text for --synthesize (literal, or '-' for stdin)",
    )
    parser.add_argument(
        "--text-file",
        metavar="PATH",
        default=None,
        help="Read synthesize text from a UTF-8 file",
    )
    parser.add_argument(
        "--output",
        "-o",
        metavar="PATH",
        default=None,
        help="Output WAV path for --synthesize, or '-' for raw PCM on stdout",
    )
    parser.add_argument(
        "--voice",
        metavar="VOICE",
        default=None,
        help="Piper .onnx path to use for this request; see --capabilities",
    )
    parser.add_argument(
        "--speed",
        type=float,
        metavar="RATE",
        default=None,
        help="Speech rate multiplier, e.g. 0.8 slower or 1.25 faster",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run the warm speech bridge so host integrations skip model loading",
    )
    args = parser.parse_args()

    if args.speed is not None and not 0.1 <= args.speed <= 4.0:
        sys.stderr.write("--speed must be between 0.1 and 4.0\n")
        sys.exit(2)

    if args.capabilities:
        _cli_capabilities()
    elif args.install_integration is not None:
        from .integration_install import install

        sys.exit(install(args.install_integration))
    elif args.daemon:
        _cli_daemon()
    elif args.transcribe is not None:
        _cli_transcribe(args.transcribe)
    elif args.synthesize:
        if not args.output:
            sys.stderr.write("--synthesize requires --output PATH\n")
            sys.exit(2)
        text = _resolve_synthesize_text(args)
        if not text.strip():
            sys.stderr.write("No text provided for --synthesize\n")
            sys.exit(1)
        _cli_synthesize(text.strip(), args.output, **_voice_overrides(args))
    elif args.listen:
        _cli_listen()
    elif args.speak is not None:
        if args.speak == "-":
            text = sys.stdin.read()
        else:
            text = args.speak
        if text.strip():
            _cli_speak(text.strip(), **_voice_overrides(args))
        else:
            sys.stderr.write("No text provided\n")
            sys.exit(1)
    else:
        from .main import main as gui_main

        gui_main()


# Guarded: the avrvx console script is "avervox.__main__:main", so an
# unguarded call here would run every command a second time on import.
if __name__ == "__main__":
    main()
