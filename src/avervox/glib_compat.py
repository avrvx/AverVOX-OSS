"""PyGObject API compatibility — works with 3.42.x (Docker/22.04) and 3.50+ (dev)."""

from __future__ import annotations

from typing import Any

import gi
from gi.repository import GLib

_PYGOBJECT_NEW = tuple(int(x) for x in gi.__version__.split(".")[:2]) >= (3, 50)


def timeout_add(interval_ms: int, callback, *args: Any, priority=GLib.PRIORITY_DEFAULT) -> int:
    if _PYGOBJECT_NEW:
        return GLib.timeout_add(priority, interval_ms, callback, *args)
    return GLib.timeout_add(interval_ms, callback, *args)


def idle_add(callback, *args: Any, priority=GLib.PRIORITY_DEFAULT_IDLE) -> int:
    if _PYGOBJECT_NEW:
        return GLib.idle_add(priority, callback, *args)
    return GLib.idle_add(callback, *args)


def markup_escape_text(text: str) -> str:
    if _PYGOBJECT_NEW:
        return GLib.markup_escape_text(text, -1)
    return GLib.markup_escape_text(text)


def text_buffer_set_text(buf, text: str) -> None:
    if _PYGOBJECT_NEW:
        buf.set_text(text, -1)
    else:
        buf.set_text(text)


def clipboard_set_text(clipboard, text: str) -> None:
    if _PYGOBJECT_NEW:
        clipboard.set_text(text, -1)
    else:
        clipboard.set_text(text)
