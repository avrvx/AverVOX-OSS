"""Conversation-mode HUD overlay.

Shows a color-coded pill banner above the panel (bottom-right, near
the tray icon):

  Converse:
    Red    — Recording
    Amber  — Awaiting Response
    Green  — Streaming Response
    Red    — Conversation Ended (auto-dismisses)

  Dictate:
    Red    — Recording (press hotkey again to finish)
    Amber  — Transcribing / inserting
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gi.repository import Gtk, Gdk

_STATES: dict[str, tuple[str, str, str]] = {
    #  state               label text                         bg color   fg color
    "recording":          ("Converse — Recording",            "#D32F2F", "#FFFFFF"),
    "awaiting":           ("Converse — Awaiting Response",    "#F57C00", "#FFFFFF"),
    "streaming":          ("Converse — Streaming Response",   "#2E7D32", "#FFFFFF"),
    "ended":              ("Conversation Ended",              "#D32F2F", "#FFFFFF"),
    "dictate_recording":  ("Dictate — Recording",             "#D32F2F", "#FFFFFF"),
    "dictate_processing": ("Dictate — Transcribing…",         "#F57C00", "#FFFFFF"),
}

_PANEL_HEIGHT = 40
_MARGIN_BOTTOM = 8
_MARGIN_RIGHT = 16

_CSS_TEMPLATE = """
#converse-hud {{
    background-color: {bg};
    border-radius: 24px;
    padding: 14px 36px;
}}
#converse-hud-label {{
    color: {fg};
    font-weight: bold;
    font-size: 16px;
}}
"""


class ConversationHUD:
    """Floating notification pill for Converse-mode state."""

    def __init__(self) -> None:
        self._window: Gtk.Window | None = None
        self._label: Gtk.Label | None = None
        self._css: Gtk.CssProvider | None = None
        self._dismiss_id: int = 0
        self._GLib = None

    def _ensure_gi(self):
        if self._GLib is not None:
            return
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import GLib
        self._GLib = GLib

    def show(self, state: str, auto_dismiss_ms: int = 0) -> None:
        """Show (or update) the HUD.  Must be called on the main thread."""
        self._ensure_gi()
        self._cancel_dismiss()

        if self._window is None:
            self._build()

        text, bg, fg = _STATES.get(state, ("Converse", "#555555", "#FFFFFF"))
        self._label.set_text(text)
        self._css.load_from_data(_CSS_TEMPLATE.format(bg=bg, fg=fg).encode())

        self._reposition()
        self._window.show_all()

        if auto_dismiss_ms > 0:
            from .glib_compat import timeout_add
            self._dismiss_id = timeout_add(auto_dismiss_ms, self._do_hide)

    def hide(self) -> None:
        """Hide the HUD immediately."""
        if self._GLib is None:
            return
        self._cancel_dismiss()
        self._do_hide()

    def destroy(self) -> None:
        """Tear down the HUD window."""
        self._cancel_dismiss()
        if self._window:
            self._window.destroy()
            self._window = None

    def _do_hide(self) -> bool:
        self._dismiss_id = 0
        if self._window:
            self._window.hide()
        return False

    def _cancel_dismiss(self) -> None:
        if self._dismiss_id and self._GLib:
            self._GLib.source_remove(self._dismiss_id)
            self._dismiss_id = 0

    def _build(self) -> None:
        from gi.repository import Gtk, Gdk

        win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        win.set_name("converse-hud")
        win.set_decorated(False)
        win.set_resizable(False)
        win.set_keep_above(True)
        win.set_accept_focus(False)
        win.set_skip_taskbar_hint(True)
        win.set_skip_pager_hint(True)
        win.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)

        screen = win.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            win.set_visual(visual)

        self._label = Gtk.Label()
        self._label.set_name("converse-hud-label")
        win.add(self._label)

        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            screen, self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._window = win

    def _reposition(self) -> None:
        """Place the pill above the panel, right-aligned (near the tray icon)."""
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geom = monitor.get_geometry()

        self._window.realize()
        req = self._window.get_preferred_size()[1]  # natural size
        x = geom.x + geom.width - req.width - _MARGIN_RIGHT
        y = geom.y + geom.height - req.height - _PANEL_HEIGHT - _MARGIN_BOTTOM
        self._window.move(x, y)
