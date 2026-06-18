"""AppIndicator3 system tray icon and menu.

The tray icon reflects the current app state (idle / listening / speaking).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")

from gi.repository import GLib, Gtk

from .glib_compat import idle_add
from .logger import get_logger

log = get_logger(__name__)

APP_ID = "io.github.avervox"
ICONS_DIR = Path(__file__).parent.parent.parent / "assets" / "icons"


def _create_tray_indicator(app_id: str, icon_name: str):
    if getattr(sys, "frozen", False):
        order = [("AppIndicator3", "0.1"), ("AyatanaAppIndicator3", "0.1")]
    else:
        order = [("AyatanaAppIndicator3", "0.1"), ("AppIndicator3", "0.1")]

    errors: list[str] = []
    for namespace, version in order:
        try:
            gi.require_version(namespace, version)
            if namespace == "AppIndicator3":
                from gi.repository import AppIndicator3 as mod
            else:
                from gi.repository import AyatanaAppIndicator3 as mod
            indicator = mod.Indicator.new(
                app_id, icon_name, mod.IndicatorCategory.APPLICATION_STATUS,
            )
            log.info("System tray using %s", namespace)
            return mod, indicator
        except Exception as exc:
            errors.append(f"{namespace}: {exc}")
            log.warning("Tray backend %s unavailable: %s", namespace, exc)

    raise RuntimeError(
        "No system tray backend available. Errors: " + "; ".join(errors)
    )

_STATE_ICONS = {
    "idle":         "avervox-idle",
    "listening":    "avervox-listening",
    "transcribing": "avervox-processing",
    "conversing":   "avervox-processing",
    "speaking":     "avervox-processing",
    "inserting":    "avervox-processing",
    "error":        "avervox-error",
}

_STATE_LABELS = {
    "idle":         "",
    "listening":    " \u25cf",
    "transcribing": " \u2026",
    "conversing":   " \u2194",
    "speaking":     " \u266a",
    "inserting":    " \u21a9",
    "error":        " !",
}


class TrayIcon:
    def __init__(self,
                 on_quit: Optional[Callable[[], None]] = None,
                 on_reload: Optional[Callable[[], None]] = None,
                 on_settings: Optional[Callable[[], None]] = None,
                 on_switch_profile: Optional[Callable[[str], None]] = None,
                 on_copy_last: Optional[Callable[[], None]] = None,
                 on_open_log: Optional[Callable[[], None]] = None,
                 on_about: Optional[Callable[[], None]] = None) -> None:
        self._on_quit = on_quit
        self._on_reload = on_reload
        self._on_settings = on_settings
        self._on_switch_profile = on_switch_profile
        self._on_copy_last = on_copy_last
        self._on_open_log = on_open_log
        self._on_about = on_about

        self._profiles: dict[str, str] = {}
        self._active_profile: str = ""
        self._llm_menu_item: Optional[Gtk.MenuItem] = None

        self._ai3, self._indicator = _create_tray_indicator(
            APP_ID, "audio-input-microphone",
        )

        if ICONS_DIR.exists():
            self._indicator.set_icon_theme_path(str(ICONS_DIR))
            self._indicator.set_icon_full("avervox-idle", "AverVOX OSS \u2014 Idle")
            self._indicator.set_attention_icon_full("avervox-listening", "AverVOX OSS \u2014 Listening")
        else:
            log.warning("Icon directory not found: %s", ICONS_DIR)

        self._indicator.set_status(self._ai3.IndicatorStatus.ACTIVE)
        self._indicator.set_label("", "")
        self._indicator.set_menu(self._build_menu())

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        title = Gtk.MenuItem(label="AverVOX OSS \u2014 LLM Speech Bridge")
        title.set_sensitive(False)
        menu.append(title)

        menu.append(Gtk.SeparatorMenuItem())

        self._llm_menu_item = Gtk.MenuItem(label="LLM: (none)")
        self._llm_menu_item.set_submenu(Gtk.Menu())
        menu.append(self._llm_menu_item)

        menu.append(Gtk.SeparatorMenuItem())

        reload_item = Gtk.MenuItem(label="Reload config")
        reload_item.connect("activate", lambda _: self._on_reload and self._on_reload())
        menu.append(reload_item)

        if self._on_settings:
            settings_item = Gtk.MenuItem(label="Settings\u2026")
            settings_item.connect("activate", lambda _: self._on_settings())
            menu.append(settings_item)

        copy_item = Gtk.MenuItem(label="Copy Last Response")
        copy_item.connect("activate",
                          lambda _: self._on_copy_last and self._on_copy_last())
        menu.append(copy_item)

        open_log_item = Gtk.MenuItem(label="Open Log")
        open_log_item.connect("activate",
                              lambda _: self._on_open_log and self._on_open_log())
        menu.append(open_log_item)

        menu.append(Gtk.SeparatorMenuItem())

        if self._on_about:
            about_item = Gtk.MenuItem(label="About AverVOX OSS")
            about_item.connect("activate", lambda _: self._on_about())
            menu.append(about_item)

        quit_item = Gtk.MenuItem(label="Quit AverVOX OSS")
        quit_item.connect("activate", lambda _: self._on_quit and self._on_quit())
        menu.append(quit_item)

        menu.show_all()
        return menu

    def set_llm_profiles(self, profiles: dict[str, str], active: str) -> None:
        """Update the LLM profile submenu.

        *profiles* maps profile key → display label.
        *active* is the key of the currently selected profile.
        """
        idle_add(self._update_llm_menu, profiles, active)

    def _update_llm_menu(self, profiles: dict[str, str], active: str) -> bool:
        self._profiles = profiles
        self._active_profile = active

        active_label = profiles.get(active, "none")
        self._llm_menu_item.set_label(f"LLM: {active_label}")

        submenu = Gtk.Menu()
        if len(profiles) <= 1:
            self._llm_menu_item.set_submenu(None)
            self._llm_menu_item.show()
            return False

        group = []
        for key, label in profiles.items():
            item = Gtk.RadioMenuItem(label=label, group=group[0] if group else None)
            group.append(item)
            item.set_active(key == active)
            item.connect("toggled", self._on_profile_toggled, key)
            submenu.append(item)

        submenu.show_all()
        self._llm_menu_item.set_submenu(submenu)
        self._llm_menu_item.show()
        return False

    def _on_profile_toggled(self, item: Gtk.RadioMenuItem, key: str) -> None:
        if not item.get_active():
            return
        if key == self._active_profile:
            return
        self._active_profile = key
        label = self._profiles.get(key, key)
        self._llm_menu_item.set_label(f"LLM: {label}")
        if self._on_switch_profile:
            self._on_switch_profile(key)

    def set_state(self, state: str) -> None:
        idle_add(self._update_state, state)

    def _update_state(self, state: str) -> bool:
        label = _STATE_LABELS.get(state, "")
        self._indicator.set_label(label, "")

        if state == "listening":
            self._indicator.set_status(self._ai3.IndicatorStatus.ATTENTION)
        else:
            self._indicator.set_status(self._ai3.IndicatorStatus.ACTIVE)
            if ICONS_DIR.exists():
                icon_name = _STATE_ICONS.get(state, "avervox-idle")
                self._indicator.set_icon_full(icon_name, f"AverVOX OSS \u2014 {state}")

        return False

    def destroy(self) -> None:
        self._indicator.set_status(self._ai3.IndicatorStatus.PASSIVE)
