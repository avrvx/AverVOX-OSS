"""AverVOX OSS — LLM speech bridge.

Usage:
  avrvx              Launch the tray app (hotkeys active)
  avrvx --listen     Capture speech (VAD auto-stop), print transcript to stdout, exit
  avrvx --speak      Read stdin, synthesize via TTS, play, exit
  avrvx --speak "text"  Speak literal text, exit
"""

import os
import signal
import sys
import faulthandler
import argparse

os.environ["CUDA_VISIBLE_DEVICES"] = ""
faulthandler.enable(file=sys.stderr, all_threads=True)

signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def _cli_listen() -> None:
    """Record until VAD detects silence, transcribe, print to stdout."""
    from .config import get_config
    from . import stt
    from .audio import AudioCapture, SAMPLE_RATE

    cfg = get_config()
    stt.configure(model=cfg.stt.model, language=cfg.stt.language)
    stt.preload()

    audio_cap = AudioCapture()
    audio_cap.configure(
        aggressiveness=cfg.audio.vad_aggressiveness,
        silence_duration_ms=cfg.audio.silence_duration_ms,
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
    from .config import get_config
    from . import tts

    cfg = get_config()
    tts.configure(voice_model=cfg.tts.voice_model)
    tts.speak(text)


def main():
    from . import __version__

    parser = argparse.ArgumentParser(
        prog="avrvx",
        description="AverVOX — Add voice to any LLM using an OpenAI-compatible endpoint."
    )
    parser.add_argument("--version", action="version",
                        version=f"AverVOX OSS {__version__}")
    parser.add_argument("--listen", action="store_true",
                        help="Capture speech and print transcript to stdout")
    parser.add_argument("--speak", nargs="?", const="-", default=None,
                        help="Speak text (from argument or stdin)")
    args = parser.parse_args()

    if args.listen:
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
