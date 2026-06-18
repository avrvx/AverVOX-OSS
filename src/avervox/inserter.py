"""Text insertion and selection — pluggable backends for X11/Wayland.

Provides two interfaces:
  insert(text)        — type text into the focused window
  get_selection()     — grab the currently selected text
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Optional

from .logger import get_logger

log = get_logger(__name__)


def _session_type() -> str:
    return os.environ.get("XDG_SESSION_TYPE", "x11").lower()


def _run(*args, timeout: int = 10, input_bytes: Optional[bytes] = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            args, capture_output=True, input=input_bytes, text=(input_bytes is None), timeout=timeout
        )
        return result.returncode, result.stdout if isinstance(result.stdout, str) else result.stdout.decode(), result.stderr if isinstance(result.stderr, str) else result.stderr.decode()
    except FileNotFoundError:
        return -1, "", f"command not found: {args[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", "timeout"


# ─── Text Insertion ─────────────────────────────────────────────────────────────

def insert(text: str, backend: str = "xdotool") -> str:
    """Insert text into the active window. Returns the method used."""
    session = _session_type()
    log.debug("Inserting text (%d chars, backend=%s)", len(text), backend)

    if backend == "xdotool" and session != "wayland" and shutil.which("xdotool"):
        rc, _, err = _run("xdotool", "type", "--clearmodifiers", "--delay", "0", text)
        if rc == 0:
            return "xdotool"
        log.warning("xdotool type failed: %s", err)

    if backend == "ydotool" or (backend == "xdotool" and session == "wayland"):
        if shutil.which("ydotool"):
            rc, _, err = _run("ydotool", "type", "--", text)
            if rc == 0:
                return "ydotool"
            log.warning("ydotool type failed: %s", err)

    if _set_clipboard(text):
        time.sleep(0.1)
        if session != "wayland" and shutil.which("xdotool"):
            rc, _, _ = _run("xdotool", "key", "--clearmodifiers", "ctrl+v")
            if rc == 0:
                return "clipboard+paste"
        if shutil.which("ydotool"):
            rc, _, _ = _run("ydotool", "key", "29:1", "47:1", "47:0", "29:0")
            if rc == 0:
                return "clipboard+paste"

    log.error("All insertion methods failed")
    return "failed"


# ─── Selection Provider ─────────────────────────────────────────────────────────

def get_selection(backend: str = "xclip") -> Optional[str]:
    """Grab the current text selection. Returns None if nothing is selected."""

    if backend == "xclip" and shutil.which("xclip"):
        rc, out, _ = _run("xclip", "-selection", "primary", "-o")
        if rc == 0 and out.strip():
            return out.strip()
        rc, out, _ = _run("xclip", "-selection", "clipboard", "-o")
        if rc == 0 and out.strip():
            return out.strip()

    if backend == "xsel" and shutil.which("xsel"):
        rc, out, _ = _run("xsel", "--primary", "--output")
        if rc == 0 and out.strip():
            return out.strip()
        rc, out, _ = _run("xsel", "--clipboard", "--output")
        if rc == 0 and out.strip():
            return out.strip()

    if backend == "wl-paste" and shutil.which("wl-paste"):
        rc, out, _ = _run("wl-paste", "--primary")
        if rc == 0 and out.strip():
            return out.strip()
        rc, out, _ = _run("wl-paste")
        if rc == 0 and out.strip():
            return out.strip()

    # Fallback: try xclip regardless of configured backend
    if backend != "xclip" and shutil.which("xclip"):
        rc, out, _ = _run("xclip", "-selection", "primary", "-o")
        if rc == 0 and out.strip():
            return out.strip()

    log.warning("No text selection available")
    return None


# ─── Clipboard Helpers ──────────────────────────────────────────────────────────

def _set_clipboard(text: str) -> bool:
    encoded = text.encode("utf-8")
    if shutil.which("xclip"):
        proc = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
        proc.communicate(input=encoded)
        return proc.returncode == 0
    if shutil.which("xsel"):
        proc = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE)
        proc.communicate(input=encoded)
        return proc.returncode == 0
    if shutil.which("wl-copy"):
        proc = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
        proc.communicate(input=encoded)
        return proc.returncode == 0
    return False
