"""Text-to-Speech engine (Piper).

Public API: configure(), preload(), speak(), speak_streamed(), stop()
"""

from __future__ import annotations

import queue
import re
import threading
import time
from pathlib import Path
from typing import Generator, Iterable, Optional

import numpy as np

from .logger import get_logger

log = get_logger(__name__)


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting so only plain words are spoken."""
    text = re.sub(r'```[\s\S]*?```', ' ', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{2,}', '\n', text)
    text = re.sub(r'  +', ' ', text)
    return text.strip()

_stop_event = threading.Event()
_backend: Optional[_PiperBackend] = None
_voice_model: str = ""


# ── Backend ──────────────────────────────────────────────────────────────────

class _PiperBackend:

    def __init__(self, voice_model: str) -> None:
        from piper import PiperVoice
        resolved = str(Path(voice_model).expanduser())
        log.info("Loading Piper voice: %s", resolved)
        self._voice = PiperVoice.load(resolved)
        log.info("Piper voice loaded (sample_rate=%d)", self._voice.config.sample_rate)

    @property
    def sample_rate(self) -> int:
        return self._voice.config.sample_rate

    def synthesize(self, text: str) -> Generator[np.ndarray, None, None]:
        for chunk in self._voice.synthesize(text):
            yield chunk.audio_float_array.astype(np.float32)


# ── Public API ───────────────────────────────────────────────────────────────

def configure(voice_model: str = "") -> None:
    """Set the TTS voice. Call before speak()."""
    global _backend, _voice_model
    _voice_model = voice_model
    _backend = None


def _load_backend() -> Optional[_PiperBackend]:
    global _backend
    if _backend is not None:
        return _backend
    try:
        if not _voice_model:
            log.warning("TTS voice model path not configured")
            return None
        _backend = _PiperBackend(_voice_model)
    except ImportError as exc:
        log.error("Piper TTS not installed: %s", exc)
        return None
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return None
    return _backend


def preload() -> None:
    """Eagerly load the TTS model (call from main thread at startup)."""
    _load_backend()


def speak(text: str) -> None:
    """Synthesize and stream-play text. Blocks until done or stop() is called."""
    text = _strip_markdown(text)
    if not text:
        return

    backend = _load_backend()
    if backend is None:
        log.warning("TTS not available — no engine configured")
        return

    _stop_event.clear()

    _DONE = object()
    audio_queue: queue.Queue = queue.Queue(maxsize=16)
    sample_rate = backend.sample_rate

    state = {"leftover": np.empty(0, dtype=np.float32), "done": False}

    def _callback(outdata: np.ndarray, frames: int, _time, _status) -> None:
        import sounddevice as sd

        buf = state["leftover"]
        result = np.zeros(frames, dtype=np.float32)
        written = 0

        while written < frames:
            if len(buf) == 0:
                try:
                    item = audio_queue.get_nowait()
                except queue.Empty:
                    break
                if item is _DONE:
                    state["done"] = True
                    break
                buf = item

            take = min(frames - written, len(buf))
            result[written : written + take] = buf[:take]
            buf = buf[take:]
            written += take

        state["leftover"] = buf
        outdata[:, 0] = result

        if state["done"] and len(state["leftover"]) == 0:
            raise sd.CallbackStop()

    try:
        import sounddevice as sd

        with sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            callback=_callback,
        ) as stream:
            for samples in backend.synthesize(text):
                if _stop_event.is_set():
                    return
                while not _stop_event.is_set():
                    try:
                        audio_queue.put(samples, timeout=0.05)
                        break
                    except queue.Full:
                        continue
                if _stop_event.is_set():
                    return

            while not _stop_event.is_set():
                try:
                    audio_queue.put(_DONE, timeout=0.05)
                    break
                except queue.Full:
                    continue

            while stream.active:
                if _stop_event.is_set():
                    return
                time.sleep(0.05)

    except Exception as exc:
        log.error("TTS playback error: %s", exc)


def speak_streamed(sentences: Iterable[str]) -> None:
    """Synthesize and play an iterable of sentences as continuous audio.

    Keeps a single audio stream open for the entire sequence, eliminating
    inter-sentence gaps.  A background thread handles synthesis so the next
    sentence is ready before the current one finishes playing.

    If the *sentences* iterator raises, playback finishes with whatever audio
    is already queued and the exception is re-raised to the caller.
    """
    backend = _load_backend()
    if backend is None:
        log.warning("TTS not available — no engine configured")
        return

    _stop_event.clear()

    _DONE = object()
    audio_queue: queue.Queue = queue.Queue(maxsize=16)
    sample_rate = backend.sample_rate

    state = {"leftover": np.empty(0, dtype=np.float32), "done": False}
    synth_error: list[BaseException] = []

    def _callback(outdata: np.ndarray, frames: int, _time, _status) -> None:
        import sounddevice as sd

        buf = state["leftover"]
        result = np.zeros(frames, dtype=np.float32)
        written = 0

        while written < frames:
            if len(buf) == 0:
                try:
                    item = audio_queue.get_nowait()
                except queue.Empty:
                    break
                if item is _DONE:
                    state["done"] = True
                    break
                buf = item

            take = min(frames - written, len(buf))
            result[written : written + take] = buf[:take]
            buf = buf[take:]
            written += take

        state["leftover"] = buf
        outdata[:, 0] = result

        if state["done"] and len(state["leftover"]) == 0:
            raise sd.CallbackStop()

    def _put(item) -> bool:
        """Put an item on the queue. Returns False if stop was requested."""
        while not _stop_event.is_set():
            try:
                audio_queue.put(item, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    def _synthesize_all():
        try:
            for sentence in sentences:
                if _stop_event.is_set():
                    return
                sentence = _strip_markdown(sentence)
                if not sentence:
                    continue
                for samples in backend.synthesize(sentence):
                    if _stop_event.is_set():
                        return
                    if not _put(samples):
                        return
        except Exception as exc:
            synth_error.append(exc)
        finally:
            _put(_DONE)

    try:
        import sounddevice as sd

        synth_thread = threading.Thread(target=_synthesize_all, daemon=True,
                                        name="tts-synth")
        synth_thread.start()

        with sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            callback=_callback,
        ) as stream:
            while stream.active:
                if _stop_event.is_set():
                    return
                time.sleep(0.05)

        synth_thread.join(timeout=2.0)

    except Exception as exc:
        log.error("TTS playback error: %s", exc)

    if synth_error:
        raise synth_error[0]


def stop() -> None:
    """Interrupt any active playback."""
    _stop_event.set()
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        pass
