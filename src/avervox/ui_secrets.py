"""GTK widgets for masked secret entry with show/hide toggle."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango

_ICON_EYE_OPEN = "\u25cf"   # ● visible
_ICON_EYE_SHUT = "\u25cb"   # ○ hidden


def _set_entry_monospace(entry: Gtk.Entry) -> None:
    """Use GtkEntry:monospace when available; fall back for older GTK 3."""
    try:
        entry.set_property("monospace", True)
    except (TypeError, AttributeError):
        entry.override_font(Pango.FontDescription("Monospace 10"))


def bind_secret_visibility(entry: Gtk.Entry, btn_eye: Gtk.ToggleButton) -> None:
    """Wire an eye toggle to show or hide *entry* text."""

    def _on_toggled(btn: Gtk.ToggleButton) -> None:
        visible = btn.get_active()
        entry.set_visibility(visible)
        btn.set_label(_ICON_EYE_OPEN if visible else _ICON_EYE_SHUT)

    btn_eye.connect("toggled", _on_toggled)


def create_secret_entry(
    value: str = "",
    placeholder: str = "",
    monospace: bool = False,
) -> tuple[Gtk.Entry, Gtk.ToggleButton]:
    """Return a masked entry and its eye toggle button."""
    entry = Gtk.Entry()
    entry.set_text(value)
    entry.set_visibility(False)
    entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
    entry.set_hexpand(True)
    if placeholder:
        entry.set_placeholder_text(placeholder)
    if monospace:
        _set_entry_monospace(entry)

    btn_eye = Gtk.ToggleButton(label=_ICON_EYE_SHUT)
    btn_eye.set_tooltip_text("Show / hide")
    btn_eye.set_size_request(36, -1)
    bind_secret_visibility(entry, btn_eye)
    return entry, btn_eye
