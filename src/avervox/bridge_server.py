"""Warm speech daemon for host integrations.

Every ``avrvx --synthesize`` pays for a Python start plus a Piper model load —
a couple of seconds — before it produces a single sample. Hosts that speak
every agent reply pay it on every turn. This daemon pays it once.

It listens on a Unix domain socket and speaks newline-delimited JSON: one
request object per line, one response object per line. Adapters try the socket
first and fall back to spawning ``avrvx`` when it is absent, so the CLI stays
the authoritative contract and nothing breaks for users who never start it.

Methods: ``capabilities``, ``synthesize``, ``transcribe``, ``cancel``, ``ping``.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import socketserver
import threading
from pathlib import Path
from typing import Any, Callable

from .logger import get_logger

log = get_logger(__name__)

PROTOCOL_VERSION = 1

# Synthesis is single-flight: the stop flag behind cancel() is module-global in
# tts, so two concurrent requests could cancel each other.
_synth_lock = threading.Lock()


def socket_path() -> Path:
    """Where the daemon listens.

    $XDG_RUNTIME_DIR is per-user and mode 0700, which is what makes the socket
    private. Without it, fall back to a directory we create with the same mode.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path(f"/tmp/avervox-{os.getuid()}")
    return base / "avervox" / "bridge.sock"


def is_running(path: Path | None = None) -> bool:
    """True if something is listening on the socket right now."""
    target = path or socket_path()
    if not target.exists():
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(1.0)
    try:
        probe.connect(str(target))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _clear_stale_socket(path: Path) -> None:
    """Remove a socket left behind by a daemon that did not shut down cleanly."""
    if not path.exists():
        return
    if is_running(path):
        raise OSError(f"AverVOX bridge already running at {path}")
    log.info("Removing stale bridge socket: %s", path)
    path.unlink()


# ── Request handling ─────────────────────────────────────────────────────────

def _error(message: str, *, code: str = "error") -> dict:
    return {"ok": False, "error": message, "code": code}


def _handle_capabilities(_req: dict) -> dict:
    from . import __edition__, __version__, tts

    return {
        "ok": True,
        "edition": __edition__,
        "version": __version__,
        "protocol": PROTOCOL_VERSION,
        "voices": tts.list_voices(),
    }


def _synth_overrides(req: dict) -> dict:
    return {
        key: req[key] for key in ("voice", "speed") if req.get(key) is not None
    }


def _handle_synthesize(req: dict) -> dict:
    from . import tts

    text = (req.get("text") or "").strip()
    if not text:
        return _error("No text to synthesize", code="empty_text")
    output = req.get("output")
    if not output:
        return _error("synthesize requires an output path", code="no_output")

    if not _synth_lock.acquire(blocking=False):
        return _error("Another synthesis is already running", code="busy")
    try:
        path = tts.synthesize_to_file(text, output, **_synth_overrides(req))
    except tts.Cancelled:
        return _error("Synthesis cancelled", code="cancelled")
    except (OSError, RuntimeError, ValueError) as exc:
        return _error(str(exc))
    finally:
        _synth_lock.release()
    return {"ok": True, "path": str(path)}


def _stream_synthesize(req: dict, write: Callable[[bytes], None]) -> None:
    """Emit audio frames as they are produced instead of one reply at the end.

    Each frame is a JSON header line followed by exactly ``bytes`` of raw
    little-endian PCM16, so a reader never has to guess where a frame ends:

        {"ok": true, "frame": 0, "rate": 22050, "bytes": 8192}\\n<8192 bytes>
        {"ok": true, "done": true, "frames": 12}\\n
    """
    from . import tts

    def send(payload: dict, body: bytes = b"") -> None:
        if req.get("id") is not None:
            payload["id"] = req["id"]
        write(json.dumps(payload).encode("utf-8") + b"\n" + body)

    text = (req.get("text") or "").strip()
    if not text:
        send(_error("No text to synthesize", code="empty_text"))
        return
    if not _synth_lock.acquire(blocking=False):
        send(_error("Another synthesis is already running", code="busy"))
        return

    frames = 0
    try:
        for pcm, rate in tts.synthesize_stream(text, **_synth_overrides(req)):
            body = pcm.tobytes()
            send({"ok": True, "frame": frames, "rate": rate, "bytes": len(body)}, body)
            frames += 1
    except tts.Cancelled:
        send(_error("Synthesis cancelled", code="cancelled"))
        return
    except (OSError, RuntimeError, ValueError) as exc:
        send(_error(str(exc)))
        return
    finally:
        _synth_lock.release()
    send({"ok": True, "done": True, "frames": frames})


def _handle_transcribe(req: dict) -> dict:
    from . import stt

    audio = req.get("path")
    if not audio:
        return _error("transcribe requires a path", code="no_path")
    try:
        text = stt.transcribe_file(audio)
    except (OSError, RuntimeError, ValueError) as exc:
        return _error(str(exc))
    if not text:
        return _error("No speech detected", code="no_speech")
    return {"ok": True, "transcript": text}


def _handle_cancel(_req: dict) -> dict:
    from . import tts

    tts.stop()
    return {"ok": True}


def _handle_ping(_req: dict) -> dict:
    return {"ok": True, "protocol": PROTOCOL_VERSION}


_METHODS: dict[str, Callable[[dict], dict]] = {
    "capabilities": _handle_capabilities,
    "synthesize": _handle_synthesize,
    "transcribe": _handle_transcribe,
    "cancel": _handle_cancel,
    "ping": _handle_ping,
}


def dispatch(request: dict) -> dict:
    """Route one decoded request. Never raises; errors come back as responses."""
    method = request.get("method")
    handler = _METHODS.get(method or "")
    if handler is None:
        return _error(f"Unknown method: {method!r}", code="unknown_method")
    try:
        return handler(request)
    except Exception as exc:  # a bad request must not take the daemon down
        log.exception("Bridge method %s failed", method)
        return _error(f"{type(exc).__name__}: {exc}")


class _Handler(socketserver.StreamRequestHandler):
    """One connection, many requests: hosts keep the socket open between turns."""

    def handle(self) -> None:
        for line in self.rfile:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("request must be a JSON object")
            except ValueError as exc:
                response: dict[str, Any] = _error(f"Bad request: {exc}", code="bad_json")
            else:
                if request.get("method") == "synthesize" and request.get("stream"):
                    try:
                        _stream_synthesize(request, self._write)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    continue
                response = dispatch(request)
                if request.get("id") is not None:
                    response["id"] = request["id"]
            try:
                self._write((json.dumps(response) + "\n").encode("utf-8"))
            except (BrokenPipeError, ConnectionResetError):
                return  # host hung up mid-reply

    def _write(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(path: Path | None = None, *, ready: threading.Event | None = None) -> None:
    """Run the daemon until interrupted. Blocks."""
    from .config import get_config
    from . import stt, tts

    target = path or socket_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _clear_stale_socket(target)

    cfg = get_config()
    tts.configure(voice_model=cfg.tts.voice_model)
    stt.configure(model=cfg.stt.model, language=cfg.stt.language, device=cfg.stt.device)

    # The whole point of the daemon: pay for the models once, here.
    log.info("Warming speech models...")
    tts.preload()
    stt.preload()

    # umask so the socket is created 0600 rather than chmod'd a moment later.
    previous_umask = os.umask(0o177)
    try:
        server = _Server(str(target), _Handler)
    finally:
        os.umask(previous_umask)

    # shutdown() blocks until serve_forever() returns, so it cannot be called
    # from the main thread that is sitting inside it.
    def _on_signal(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (OSError, ValueError):
            pass

    log.info("AverVOX bridge listening on %s", target)
    if ready is not None:
        ready.set()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        log.info("AverVOX bridge stopped")
