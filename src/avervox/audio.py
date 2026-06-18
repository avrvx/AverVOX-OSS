"""Audio capture with VAD (Voice Activity Detection).

Records from the microphone using parec (PulseAudio/PipeWire native).

Two capture modes:

- **Recorder** (Dictate): buffers all audio until manual stop. Optional interim
  callbacks fire after a configurable pause so text can be inserted mid-session
  without ending the recording.
- **VAD segment** (Converse, ``avrvx --listen``): detects silence boundaries
  and emits complete speech segments automatically.

Also provides InterruptMonitor — a lightweight VAD watcher used during
TTS playback to detect voice interrupts (barge-in).

This bypasses PortAudio/ALSA entirely, avoiding mmap segfaults.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

from .logger import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_DURATION_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
FRAME_BYTES = FRAME_SAMPLES * 2  # 16-bit = 2 bytes per sample
DTYPE = "int16"
MIN_SPEECH_FRAMES = 10  # ~300ms minimum speech before we'll emit a segment

# Energy gate (int16 RMS) applied *in addition to* webrtcvad.  webrtcvad is
# tuned for telephony and false-positives on steady ambient noise; requiring a
# minimum frame energy rejects that hum/hiss while letting real speech through.
# Pure energy-only fallback (no webrtcvad) uses the higher ENERGY_ONLY_GATE.
ENERGY_GATE = 300.0
ENERGY_ONLY_GATE = 800.0


@dataclass
class CaptureResult:
    """Audio returned by :meth:`AudioCapture.stop`."""

    audio: np.ndarray
    committed_samples: int = 0  # samples already sent via interim Dictate inserts


class AudioCapture:
    """Captures microphone audio via parec.

    Use ``start(recorder_mode=True)`` for Dictate (manual stop; optional interim inserts).
    Use ``start()`` or ``start(recorder_mode=False)`` for VAD segment mode.
    """

    def __init__(self) -> None:
        self._vad = None
        self._process: Optional[subprocess.Popen] = None
        self._recording = False
        self._recorder_mode = False
        self._lock = threading.Lock()
        self._speech_frames: List[bytes] = []
        self._silence_frames = 0
        self._silence_threshold = 0
        self._on_segment_cb: Optional[Callable[[np.ndarray], None]] = None
        self._on_interim_cb: Optional[Callable[[np.ndarray], None]] = None
        self._interim_committed_frame_idx = 0
        self._thread: Optional[threading.Thread] = None
        self._aggressiveness = 2
        self._silence_duration_ms = 800

    def configure(self, aggressiveness: int = 2, silence_duration_ms: int = 800, **kwargs) -> None:
        self._aggressiveness = aggressiveness
        self._silence_duration_ms = silence_duration_ms
        frames_per_second = 1000 / FRAME_DURATION_MS
        self._silence_threshold = int((silence_duration_ms / 1000) * frames_per_second)

    def set_on_segment(self, cb: Optional[Callable[[np.ndarray], None]]) -> None:
        self._on_segment_cb = cb

    def set_on_interim_segment(self, cb: Optional[Callable[[np.ndarray], None]]) -> None:
        """Interim phrase callback for Dictate recorder mode (does not stop capture)."""
        self._on_interim_cb = cb

    def has_speech_activity(self) -> bool:
        """True if speech frames are currently buffered (user is mid-utterance)."""
        with self._lock:
            return len(self._speech_frames) > 0

    def _init_vad(self) -> bool:
        try:
            import webrtcvad
            self._vad = webrtcvad.Vad(self._aggressiveness)
            return True
        except ImportError:
            log.warning("webrtcvad not installed — using energy-based VAD")
            return False

    def start(self, recorder_mode: bool = False) -> None:
        """Begin capture. *recorder_mode* buffers continuously until ``stop()``."""
        with self._lock:
            if self._recording:
                return
            self._recording = True
            self._recorder_mode = recorder_mode
            self._speech_frames = []
            self._silence_frames = 0
            self._interim_committed_frame_idx = 0

        if recorder_mode and self._on_interim_cb:
            if not self._init_vad():
                self._vad = None
        elif not recorder_mode and not self._init_vad():
            self._vad = None
        elif recorder_mode:
            self._vad = None

        thread = threading.Thread(target=self._record, daemon=True, name="audio-capture")
        self._thread = thread
        thread.start()

    def stop(self) -> Optional[CaptureResult]:
        """Stop recording and return buffered audio plus interim commit offset."""
        with self._lock:
            self._recording = False

        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        with self._lock:
            frames = list(self._speech_frames)
            self._speech_frames = []
            committed_frames = self._interim_committed_frame_idx
            self._interim_committed_frame_idx = 0

        if frames:
            return CaptureResult(
                audio=self._frames_to_array(frames),
                committed_samples=committed_frames * FRAME_SAMPLES,
            )
        return None

    def _emit_recorder_interim(self, end_frame_idx: int, speech_frame_count: int) -> None:
        if not self._on_interim_cb or speech_frame_count < MIN_SPEECH_FRAMES:
            return
        with self._lock:
            start = self._interim_committed_frame_idx
            end = end_frame_idx
            if end <= start:
                return
            chunk_frames = list(self._speech_frames[start:end])
            self._interim_committed_frame_idx = end
        chunk = self._frames_to_array(chunk_frames)
        if len(chunk) > 0:
            log.debug("Dictate interim phrase: %.1fs", len(chunk) / SAMPLE_RATE)
            self._on_interim_cb(chunk)

    def _drain_recorder_pipe(self) -> None:
        """Read any audio already buffered by parec before we close the pipe."""
        if not self._process or self._process.poll() is not None:
            return
        import select

        deadline = time.time() + 0.5
        stdout = self._process.stdout
        while time.time() < deadline and self._process.poll() is None:
            ready, _, _ = select.select([stdout], [], [], 0.05)
            if not ready:
                continue
            frame_bytes = stdout.read(FRAME_BYTES)
            if not frame_bytes:
                break
            with self._lock:
                self._speech_frames.append(frame_bytes)
            if len(frame_bytes) < FRAME_BYTES:
                break

    def _record(self) -> None:
        log.debug("Starting audio capture via parec at %d Hz", SAMPLE_RATE)

        try:
            self._process = subprocess.Popen(
                [
                    "parec",
                    "--rate", str(SAMPLE_RATE),
                    "--channels", str(CHANNELS),
                    "--format", "s16le",
                    "--latency-msec", "30",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            log.error("parec not found — install pulseaudio-utils")
            return
        except Exception as exc:
            log.error("Failed to start parec: %s", exc)
            return

        log.debug("parec started (pid=%d)", self._process.pid)
        if self._recorder_mode:
            log.debug("Recorder mode — buffering until manual stop")
        in_speech = False
        speech_frame_count = 0
        recorder_interim = self._recorder_mode and self._on_interim_cb is not None

        try:
            while self._recording and self._process.poll() is None:
                frame_bytes = self._process.stdout.read(FRAME_BYTES)
                if not frame_bytes or len(frame_bytes) < FRAME_BYTES:
                    break

                if self._recorder_mode:
                    with self._lock:
                        self._speech_frames.append(frame_bytes)
                    if recorder_interim:
                        is_speech = self._is_speech(frame_bytes)
                        if is_speech:
                            if not in_speech:
                                in_speech = True
                                self._silence_frames = 0
                                speech_frame_count = 0
                            speech_frame_count += 1
                            self._silence_frames = 0
                        elif in_speech:
                            self._silence_frames += 1
                            if self._silence_frames >= self._silence_threshold:
                                with self._lock:
                                    end_idx = len(self._speech_frames) - self._silence_frames
                                self._emit_recorder_interim(end_idx, speech_frame_count)
                                in_speech = False
                                speech_frame_count = 0
                                self._silence_frames = 0
                    continue

                is_speech = self._is_speech(frame_bytes)

                if is_speech:
                    if not in_speech:
                        in_speech = True
                        self._silence_frames = 0
                        speech_frame_count = 0
                    with self._lock:
                        self._speech_frames.append(frame_bytes)
                    speech_frame_count += 1
                    self._silence_frames = 0
                else:
                    if in_speech:
                        with self._lock:
                            self._speech_frames.append(frame_bytes)
                        self._silence_frames += 1
                        if self._silence_frames >= self._silence_threshold:
                            in_speech = False
                            with self._lock:
                                frames_snapshot = list(self._speech_frames)
                                self._speech_frames = []
                            self._silence_frames = 0
                            if speech_frame_count >= MIN_SPEECH_FRAMES:
                                segment = self._frames_to_array(frames_snapshot)
                                if self._on_segment_cb and len(segment) > 0:
                                    self._on_segment_cb(segment)
                            else:
                                log.debug("Discarded noise burst (%d frames < %d min)",
                                          speech_frame_count, MIN_SPEECH_FRAMES)
        except Exception as exc:
            log.error("Audio capture error: %s", exc, exc_info=True)
        finally:
            if self._recorder_mode:
                self._drain_recorder_pipe()
            if self._process and self._process.poll() is None:
                self._process.terminate()

    def _is_speech(self, frame_bytes: bytes) -> bool:
        pcm = np.frombuffer(frame_bytes, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        if self._vad is None:
            # Energy-only fallback (webrtcvad unavailable).
            return rms > ENERGY_ONLY_GATE
        # Hybrid: webrtcvad must agree AND the frame must clear the energy gate.
        # This rejects steady ambient noise that fools webrtcvad on noisy mics.
        if rms <= ENERGY_GATE:
            return False
        try:
            return self._vad.is_speech(frame_bytes, SAMPLE_RATE)
        except Exception:
            return False

    @staticmethod
    def _frames_to_array(frames: List[bytes]) -> np.ndarray:
        raw = b"".join(frames)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767.0
        return samples


class InterruptMonitor:
    """Lightweight VAD monitor that fires a callback when sustained speech is detected.

    Used during TTS playback in Converse mode to let the user interrupt
    (barge-in) by speaking.  Runs its own parec subprocess so it can
    operate concurrently with audio output.
    """

    def __init__(self, on_interrupt: Callable[[], None],
                 aggressiveness: int = 2,
                 threshold_frames: int = 10,
                 grace_ms: int = 1000) -> None:
        self._on_interrupt = on_interrupt
        self._aggressiveness = aggressiveness
        self._threshold = threshold_frames
        # Ignore speech for this long after arming, so the tail of the user's
        # own utterance (and TTS synthesis latency) doesn't trigger a false
        # barge-in before playback has even started.
        self._grace_frames = int(grace_ms / FRAME_DURATION_MS)
        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._fired = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._fired = False
        threading.Thread(target=self._monitor, daemon=True,
                         name="interrupt-monitor").start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
        proc = self._process
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._process = None

    def _monitor(self) -> None:
        try:
            import webrtcvad
            vad = webrtcvad.Vad(self._aggressiveness)
        except ImportError:
            log.warning("webrtcvad not installed — interrupt monitor unavailable")
            return

        try:
            self._process = subprocess.Popen(
                [
                    "parec",
                    "--rate", str(SAMPLE_RATE),
                    "--channels", str(CHANNELS),
                    "--format", "s16le",
                    "--latency-msec", "30",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            log.error("parec not found — interrupt monitor unavailable")
            return
        except Exception as exc:
            log.error("Failed to start parec for interrupt monitor: %s", exc)
            return

        log.debug("Interrupt monitor started (pid=%d, threshold=%d frames)",
                   self._process.pid, self._threshold)

        consecutive = 0
        frames_seen = 0
        try:
            while self._running and self._process.poll() is None:
                frame = self._process.stdout.read(FRAME_BYTES)
                if not frame or len(frame) < FRAME_BYTES:
                    break
                frames_seen += 1
                # Grace window: swallow audio right after arming so the tail of
                # the user's own utterance can't trip a false barge-in.
                if frames_seen <= self._grace_frames:
                    continue
                # Energy gate first: reject ambient noise / TTS bleed-through
                # before consulting webrtcvad, so barge-in only fires on a real
                # raised voice rather than steady background sound.
                pcm = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(pcm ** 2)))
                if rms <= ENERGY_GATE:
                    is_speech = False
                else:
                    try:
                        is_speech = vad.is_speech(frame, SAMPLE_RATE)
                    except Exception:
                        is_speech = False

                if is_speech:
                    consecutive += 1
                    if consecutive >= self._threshold and not self._fired:
                        self._fired = True
                        log.info("Interrupt monitor: speech detected (%d frames)",
                                 consecutive)
                        self._on_interrupt()
                        break
                else:
                    consecutive = 0
        except Exception as exc:
            log.error("Interrupt monitor error: %s", exc)
        finally:
            self.stop()
