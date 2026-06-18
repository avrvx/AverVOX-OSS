"""Global hotkey capture using pynput.

Uses a raw Listener with manual key tracking rather than GlobalHotKeys,
which is unreliable on many Linux desktop environments.

Results are posted back to the GLib main loop via GLib.idle_add so that
GTK UI updates remain thread-safe.
"""

from __future__ import annotations

import threading
from typing import Callable, FrozenSet, Optional, Set

from gi.repository import GLib

from .glib_compat import idle_add
from .logger import get_logger

log = get_logger(__name__)

_KEY_ALIASES = {
    "super": "cmd", "win": "cmd",
    "return": "enter", "escape": "esc",
}


def _parse_hotkey(combo: str) -> FrozenSet[str]:
    """Parse a hotkey string into a frozenset of canonical key names."""
    parts = combo.split("+")
    keys: Set[str] = set()
    for part in parts:
        stripped = part.strip()
        if stripped.startswith("<") and stripped.endswith(">"):
            name = stripped[1:-1].lower()
        else:
            name = stripped.lower()
        name = _KEY_ALIASES.get(name, name)
        keys.add(name)
    return frozenset(keys)


def _key_to_name(key) -> Optional[str]:
    """Convert a pynput key event to a canonical name string."""
    from pynput import keyboard

    if isinstance(key, keyboard.Key):
        name = key.name.lower()
        # Normalize left/right variants to base name for modifiers
        if name in ("ctrl_l", "ctrl_r"):
            return "ctrl"
        if name in ("shift_l", "shift_r"):
            return "shift"
        if name in ("alt_l", "alt_r"):
            return "alt"
        if name in ("cmd_l", "cmd_r", "cmd"):
            return "cmd"
        return name
    elif isinstance(key, keyboard.KeyCode):
        if key.char:
            # Ctrl+Space often produces '\x00'; Ctrl+letter produces chr(1-26)
            if key.char == ' ' or key.char == '\x00':
                return "space"
            return key.char.lower()
        if key.vk is not None:
            vk = key.vk
            # Space: ASCII 32, or XKB keysym variants produced with modifiers
            if vk in (32, 65032):
                return "space"
            return f"vk{vk}"
    return None


class HotkeyManager:
    """Registers global hotkeys via pynput raw Listener and fires callbacks on the GLib main loop.

    Accepts an arbitrary dict of ``{combo_string: callback}`` so the set of
    hotkeys is not hard-coded.
    """

    def __init__(self) -> None:
        self._listener = None
        self._bindings: list[tuple[FrozenSet[str], Callable[[], None]]] = []
        self._pressed: Set[str] = set()
        self._lock = threading.Lock()

    def start(self, bindings: dict[str, Callable[[], None]]) -> None:
        """Start listening for *bindings* (``{combo: callback}``)."""
        self._bindings = [
            (_parse_hotkey(combo), cb) for combo, cb in bindings.items() if combo
        ]
        self._pressed = set()

        try:
            from pynput import keyboard
        except ImportError:
            log.error("pynput not installed — global hotkeys disabled")
            return

        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        names = ", ".join(bindings.keys())
        log.info("HotkeyManager started (%s)", names)

    def _on_press(self, key) -> None:
        name = _key_to_name(key)
        if name is None:
            log.debug("Unrecognized key event: %r (type=%s)", key, type(key).__name__)
            return

        with self._lock:
            already_pressed = name in self._pressed
            self._pressed.add(name)

            if already_pressed:
                return

            for keys, callback in self._bindings:
                if keys and keys <= self._pressed:
                    log.debug("Hotkey fired (pressed=%s)", self._pressed)
                    idle_add(callback)
                    break

    def _on_release(self, key) -> None:
        name = _key_to_name(key)
        if name is None:
            return
        with self._lock:
            self._pressed.discard(name)

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        log.info("HotkeyManager stopped")

    def update(self, bindings: dict[str, Callable[[], None]]) -> None:
        """Restart with new hotkey bindings."""
        self.stop()
        self.start(bindings)
