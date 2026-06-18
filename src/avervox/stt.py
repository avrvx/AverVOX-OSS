"""Speech-to-Text via faster-whisper (local, CPU).

Provides: listen(audio) -> text
Model is pre-loaded at startup to avoid import conflicts with audio threads.
"""

from __future__ import annotations

import numpy as np

from .logger import get_logger

log = get_logger(__name__)

# Pre-import at module load time to avoid segfaults when importing
# native libraries (av/FFmpeg) concurrent with PortAudio.
try:
    from faster_whisper import WhisperModel as _WhisperModel
except ImportError:
    _WhisperModel = None

_model = None
_model_size: str = "base"
_language: str = "en"

# Silero VAD settings for long Dictate recordings (speech with pauses).
_LONG_FORM_VAD = {
    "min_silence_duration_ms": 400,
    "speech_pad_ms": 400,
    "threshold": 0.35,
}


def configure(model: str = "base", language: str = "en") -> None:
    """Set the model size and language. Call before listen()."""
    global _model_size, _language, _model
    _model_size = model
    _language = language
    _model = None


def preload() -> None:
    """Eagerly load the model (call from main thread at startup)."""
    _load_model()


def _load_model():
    global _model
    if _model is None:
        if _WhisperModel is None:
            raise RuntimeError("faster-whisper not installed")
        log.info("Loading faster-whisper model: %s (CPU, int8)", _model_size)
        _model = _WhisperModel(_model_size, device="cpu", compute_type="int8")
        log.info("faster-whisper model loaded")
    return _model


def _prepare_audio(audio: np.ndarray) -> np.ndarray:
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32)
    if len(audio) > 0 and np.abs(audio).max() > 1.0:
        audio = audio / 32767.0
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    if 0 < peak < 0.1:
        audio = audio * (0.9 / peak)
        log.debug("Normalized quiet audio (peak %.4f → 0.9)", peak)
    return audio


def listen(
    audio: np.ndarray,
    sample_rate: int = 16000,
    *,
    long_form: bool | None = None,
) -> str:
    """Transcribe an audio segment. Returns the recognized text.

    *long_form* enables Silero VAD chunking inside faster-whisper — required for
    Dictate recordings where the speaker pauses mid-thought. Short Converse
    turns keep the fast path (``long_form=False``).
    """
    model = _load_model()
    audio = _prepare_audio(audio)

    duration_s = len(audio) / sample_rate if sample_rate else 0.0
    if long_form is None:
        long_form = duration_s > 8.0

    if long_form:
        transcribe_kwargs = {
            "language": _language or None,
            "beam_size": 5,
            "vad_filter": True,
            "vad_parameters": dict(_LONG_FORM_VAD),
        }
    else:
        transcribe_kwargs = {
            "language": _language or None,
            "beam_size": 1,
            "vad_filter": False,
        }

    segments, info = model.transcribe(audio, **transcribe_kwargs)
    segment_list = list(segments)
    text = " ".join(seg.text.strip() for seg in segment_list if seg.text.strip())

    if long_form and segment_list:
        covered_s = segment_list[-1].end - segment_list[0].start
        log.debug(
            "Transcribed (%s, long-form): %d segments, %.1fs speech / %.1fs audio, %d chars",
            info.language, len(segment_list), covered_s, duration_s, len(text),
        )
    else:
        log.debug("Transcribed (%s): %d chars", info.language, len(text))

    return text.strip()
