"""AverVOX OSS — LLM speech bridge.

Usage:
  avrvx                 Launch the tray app (hotkeys active)
  avrvx --listen        Capture speech (VAD auto-stop), print transcript, exit
  avrvx --speak         Read stdin, synthesize via TTS, play, exit
  avrvx --speak "text"  Speak literal text, exit
  avrvx --synthesize --output PATH [--text … | --text-file … | stdin]
  avrvx --transcribe PATH
  avrvx --capabilities  Print JSON capability probe for host integrations
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


def _cli_speak(text: str) -> None:
    """Synthesize and play text."""
    tts = _configure_tts()
    tts.speak(text)


def _cli_synthesize(text: str, output: str) -> None:
    """Synthesize text to a WAV file (no playback)."""
    tts = _configure_tts()
    try:
        path = tts.synthesize_to_file(text, output)
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


def _cli_capabilities() -> None:
    """Emit a JSON capability probe for host integrations."""
    from . import __edition__ as edition, __version__
    from .config import get_config

    cfg = get_config()
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
        help="Output WAV path for --synthesize",
    )
    args = parser.parse_args()

    if args.capabilities:
        _cli_capabilities()
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
        _cli_synthesize(text.strip(), args.output)
    elif args.listen:
        _cli_listen()
    elif args.speak is not None:
        if args.speak == "-":
            text = sys.stdin.read()
        else:
            text = args.speak
        if text.strip():
            _cli_speak(text.strip())
        else:
            sys.stderr.write("No text provided\n")
            sys.exit(1)
    else:
        from .main import main as gui_main

        gui_main()


main()
