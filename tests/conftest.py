"""Shared test fixtures — stub GTK/GLib before avervox.main imports."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock


def _make_gi_stubs() -> None:
    gi_mod = types.ModuleType("gi")
    gi_mod.require_version = lambda *_: None  # type: ignore[attr-defined]
    gi_mod.__version__ = "3.42.2"
    sys.modules.setdefault("gi", gi_mod)

    repo_mod = types.ModuleType("gi.repository")
    sys.modules.setdefault("gi.repository", repo_mod)

    glib_mod = types.ModuleType("gi.repository.GLib")
    glib_mod.idle_add = MagicMock()
    glib_mod.timeout_add = MagicMock()
    glib_mod.set_prgname = MagicMock()
    glib_mod.set_application_name = MagicMock()
    glib_mod.PRIORITY_DEFAULT = 0
    glib_mod.PRIORITY_DEFAULT_IDLE = 200
    sys.modules.setdefault("gi.repository.GLib", glib_mod)
    repo_mod.GLib = glib_mod  # type: ignore[attr-defined]

    gtk_mod = types.ModuleType("gi.repository.Gtk")
    gtk_mod.main = MagicMock()
    gtk_mod.main_quit = MagicMock()
    sys.modules.setdefault("gi.repository.Gtk", gtk_mod)
    repo_mod.Gtk = gtk_mod  # type: ignore[attr-defined]

    appindicator_mod = types.ModuleType("gi.repository.AppIndicator3")
    appindicator_mod.Indicator = MagicMock()
    appindicator_mod.IndicatorCategory = MagicMock()
    appindicator_mod.IndicatorStatus = MagicMock()
    sys.modules.setdefault("gi.repository.AppIndicator3", appindicator_mod)
    repo_mod.AppIndicator3 = appindicator_mod  # type: ignore[attr-defined]

    # numpy is deliberately absent: avervox.tts imports it at module scope and
    # operates on real arrays, so a MagicMock silently turns audio into nothing.
    for name in ("pynput", "pynput.keyboard", "sounddevice", "webrtcvad",
                 "faster_whisper"):
        sys.modules.setdefault(name, MagicMock())


_make_gi_stubs()
