"""Text-to-Speech engine (Piper).

Public API: configure(), preload(), speak(), speak_streamed(),
synthesize_to_file(), synthesize_stream(), list_voices(), clear_cache(), stop()

stop() interrupts playback and raises Cancelled out of synthesize_to_file().

speak(), speak_streamed(), and synthesize_to_file() accept per-request
voice/speed overrides; anything left unset falls back to configure().
"""

from __future__ import annotations

import inspect
import json
import os
import queue
import re
import threading
import time
import wave
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Generator, Iterable, Optional

import numpy as np

from .logger import get_logger
from .text import split_sentences

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

class Cancelled(Exception):
    """Raised when stop() interrupts an in-progress synthesis."""


_stop_event = threading.Event()
_voice_model: str = ""
_speed: float = 1.0

# Loaded voices keyed by model path, least-recently-used first, so switching
# back to a previous voice does not reload it.
_backends: OrderedDict[str, _PiperBackend] = OrderedDict()
_backends_lock = threading.RLock()
_BACKEND_CACHE_SIZE = 3


# ── Backend ──────────────────────────────────────────────────────────────────

class _PiperBackend:

    #: Only used when a voice's sidecar JSON cannot be read. Piper's medium
    #: voices are the common case; its low voices run at 16 kHz.
    FALLBACK_SAMPLE_RATE = 22050

    def __init__(self, voice_model: str) -> None:
        from piper import PiperVoice
        resolved = str(Path(voice_model).expanduser())
        log.info("Loading Piper voice: %s", resolved)
        self._voice = PiperVoice.load(resolved)
        # piper-tts grew per-call synthesis options partway through 1.x; older
        # builds take the text alone and cannot vary speed.
        self._tunable = "syn_config" in inspect.signature(
            self._voice.synthesize
        ).parameters
        log.info("Piper voice loaded (sample_rate=%d)", self._voice.config.sample_rate)

    @property
    def sample_rate(self) -> int:
        return self._voice.config.sample_rate

    def synthesize(
        self, text: str, *, speed: float = 1.0
    ) -> Generator[np.ndarray, None, None]:
        kwargs = {}
        if speed and speed != 1.0:
            if self._tunable:
                from piper import SynthesisConfig
                kwargs["syn_config"] = SynthesisConfig(length_scale=1.0 / speed)
            else:
                log.debug("Installed piper-tts cannot vary speed; ignoring %.2fx", speed)
        for chunk in self._voice.synthesize(text, **kwargs):
            yield chunk.audio_float_array.astype(np.float32)


# ── Public API ───────────────────────────────────────────────────────────────

def configure(voice_model: str = "", speed: float = 1.0) -> None:
    """Set the default TTS voice. Call before speak()."""
    global _voice_model, _speed
    _voice_model = voice_model
    _speed = speed


def clear_cache() -> None:
    """Drop every loaded model. Only needed if a voice file changed on disk."""
    with _backends_lock:
        _backends.clear()


def _resolve(
    voice: str | None = None, speed: float | None = None
) -> tuple[str, float]:
    """Fill per-request overrides in from the configured defaults."""
    model = voice or _voice_model
    return (
        str(Path(model).expanduser()) if model else "",
        float(_speed if speed is None else speed),
    )


def _load_backend(voice: str = "") -> Optional[_PiperBackend]:
    """Return a ready backend, loading it on first use and caching it after."""
    voice = voice or _voice_model
    if not voice:
        log.warning("TTS voice model path not configured")
        return None
    with _backends_lock:
        cached = _backends.get(voice)
        if cached is not None:
            _backends.move_to_end(voice)
            return cached
        try:
            backend = _PiperBackend(voice)
        except ImportError as exc:
            log.error("Piper TTS not installed: %s", exc)
            return None
        except FileNotFoundError as exc:
            log.error("%s", exc)
            return None
        _backends[voice] = backend
        while len(_backends) > _BACKEND_CACHE_SIZE:
            evicted, _ = _backends.popitem(last=False)
            log.debug("Evicted cached TTS backend: %s", evicted)
        return backend


def preload(voice: str | None = None) -> None:
    """Eagerly load a TTS model (call from main thread at startup)."""
    resolved_voice, _ = _resolve(voice)
    _load_backend(resolved_voice)


def list_voices() -> list[dict]:
    """Enumerate selectable voices so hosts can render a picker.

    Scans the ``.onnx`` files next to the configured model and in the standard
    piper-tts directory.
    """
    voices: list[dict] = []
    seen: set[str] = set()

    search_dirs = [Path.home() / ".local" / "share" / "piper-tts" / "voices"]
    if _voice_model:
        search_dirs.insert(0, Path(_voice_model).expanduser().parent)
    for directory in search_dirs:
        try:
            candidates = sorted(directory.glob("*.onnx"))
        except OSError:
            continue
        for model in candidates:
            key = str(model)
            if key in seen:
                continue
            seen.add(key)
            voices.append({"engine": "piper", "id": key, "name": model.stem})

    return voices


def sample_rate(voice: str | None = None) -> int:
    """The rate synthesis will produce, without loading a model to find out.

    A host that opens an audio device before the first chunk arrives needs
    this up front. Piper records it in the ``.onnx.json`` beside the model and
    it varies by voice quality.
    """
    resolved_voice, _ = _resolve(voice, None)

    backend = _backends.get(resolved_voice)
    if backend is not None:
        return int(backend.sample_rate)
    try:
        with open(f"{resolved_voice}.json", encoding="utf-8") as handle:
            return int(json.load(handle)["audio"]["sample_rate"])
    except (OSError, ValueError, KeyError) as exc:
        log.debug("Could not read the sample rate for %s: %s", resolved_voice, exc)
        return _PiperBackend.FALLBACK_SAMPLE_RATE


def synthesize_stream(
    text: str,
    *,
    voice: str | None = None,
    speed: float | None = None,
) -> Generator[tuple[np.ndarray, int], None, None]:
    """Yield ``(pcm_int16, sample_rate)`` chunks as they are produced.

    Piper yields incrementally, so a long passage starts arriving almost at
    once. The text is split into sentences first so a caller playing the
    stream gets natural boundaries.
    """
    text = _strip_markdown(text)
    if not text:
        raise ValueError("No text to synthesize")

    resolved_voice, resolved_speed = _resolve(voice, speed)
    backend = _load_backend(resolved_voice)
    if backend is None:
        raise RuntimeError("TTS not available — no engine configured")

    _stop_event.clear()
    rate = int(backend.sample_rate)
    produced = False
    for sentence in split_sentences(text):
        for samples in backend.synthesize(sentence, speed=resolved_speed):
            if _stop_event.is_set():
                raise Cancelled("Synthesis cancelled")
            if samples is None or len(samples) == 0:
                continue
            audio = np.asarray(samples, dtype=np.float32).reshape(-1)
            produced = True
            yield (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16), rate
    if _stop_event.is_set():
        raise Cancelled("Synthesis cancelled")
    if not produced:
        raise RuntimeError("TTS produced no audio")


def synthesize_to_file(
    text: str,
    output_path: str | Path,
    *,
    voice: str | None = None,
    speed: float | None = None,
) -> Path:
    """Synthesize *text* to a mono PCM16 WAV file. Returns the resolved path.

    Unset arguments fall back to whatever :func:`configure` last set.
    """
    text = _strip_markdown(text)
    if not text:
        raise ValueError("No text to synthesize")

    resolved_voice, resolved_speed = _resolve(voice, speed)
    backend = _load_backend(resolved_voice)
    if backend is None:
        raise RuntimeError("TTS not available — no engine configured")

    _stop_event.clear()
    chunks: list[np.ndarray] = []
    for samples in backend.synthesize(text, speed=resolved_speed):
        # Long passages take seconds; without this the only way out is SIGKILL.
        if _stop_event.is_set():
            raise Cancelled("Synthesis cancelled")
        if samples is not None and len(samples) > 0:
            chunks.append(np.asarray(samples, dtype=np.float32).reshape(-1))
    if _stop_event.is_set():
        raise Cancelled("Synthesis cancelled")
    if not chunks:
        raise RuntimeError("TTS produced no audio")

    audio = np.concatenate(chunks)
    path = Path(output_path).expanduser().resolve()
    if not path.parent.is_dir():
        raise NotADirectoryError(f"Output directory does not exist: {path.parent}")

    pcm = np.clip(audio, -1.0, 1.0)
    pcm_i16 = (pcm * 32767.0).astype(np.int16)
    # 0600: host integrations write these into shared temp dirs.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as raw, wave.open(raw, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(backend.sample_rate))
        wf.writeframes(pcm_i16.tobytes())

    log.debug("Wrote TTS WAV: %s (%d samples @ %d Hz)", path, len(pcm_i16), backend.sample_rate)
    return path


def speak(
    text: str, *, voice: str | None = None, speed: float | None = None
) -> None:
    """Synthesize and stream-play text. Blocks until done or stop() is called."""
    text = _strip_markdown(text)
    if not text:
        return

    resolved_voice, resolved_speed = _resolve(voice, speed)
    backend = _load_backend(resolved_voice)
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
            for samples in backend.synthesize(text, speed=resolved_speed):
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


def speak_streamed(
    sentences: Iterable[str],
    *,
    on_near_complete: Callable[[], None] | None = None,
    near_complete_seconds: float = 0.3,
    voice: str | None = None,
    speed: float | None = None,
) -> None:
    """Synthesize and play an iterable of sentences as continuous audio.

    Keeps a single audio stream open for the entire sequence, eliminating
    inter-sentence gaps.  A background thread handles synthesis so the next
    sentence is ready before the current one finishes playing.

    If *on_near_complete* is set, it is called once when roughly
    *near_complete_seconds* of audio remain in the output buffer (used to
    pre-open the mic before TTS finishes).

    If the *sentences* iterator raises, playback finishes with whatever audio
    is already queued and the exception is re-raised to the caller.
    """
    resolved_voice, resolved_speed = _resolve(voice, speed)
    backend = _load_backend(resolved_voice)
    if backend is None:
        log.warning("TTS not available — no engine configured")
        return

    _stop_event.clear()

    _DONE = object()
    audio_queue: queue.Queue = queue.Queue(maxsize=16)
    sample_rate = backend.sample_rate

    state = {
        "leftover": np.empty(0, dtype=np.float32),
        "done": False,
        "synth_finished": False,
        "remaining": 0,
        "peak_remaining": 0,
        "near_fired": False,
    }
    synth_error: list[BaseException] = []
    near_threshold = max(1, int(near_complete_seconds * sample_rate))

    def _note_remaining(delta: int) -> None:
        if delta > 0:
            state["remaining"] += delta
            if state["remaining"] > state["peak_remaining"]:
                state["peak_remaining"] = state["remaining"]

    def _check_near_complete() -> None:
        if (
            on_near_complete is not None
            and not state["near_fired"]
            and state["synth_finished"]
            and state["peak_remaining"] > near_threshold
            and state["remaining"] <= near_threshold
        ):
            state["near_fired"] = True
            try:
                on_near_complete()
            except Exception as exc:
                log.debug("on_near_complete callback error: %s", exc)

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
        if written:
            state["remaining"] = max(0, state["remaining"] - written)
            _check_near_complete()

        if state["done"] and len(state["leftover"]) == 0:
            raise sd.CallbackStop()

    def _put(item) -> bool:
        """Put an item on the queue. Returns False if stop was requested."""
        while not _stop_event.is_set():
            try:
                audio_queue.put(item, timeout=0.05)
                if item is _DONE:
                    state["synth_finished"] = True
                    _check_near_complete()
                elif isinstance(item, np.ndarray):
                    _note_remaining(len(item))
                    _check_near_complete()
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
                for samples in backend.synthesize(sentence, speed=resolved_speed):
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


def is_stopped() -> bool:
    """True if stop() was called and nothing has started speaking since."""
    return _stop_event.is_set()


def stop() -> None:
    """Interrupt any active playback."""
    _stop_event.set()
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        pass
