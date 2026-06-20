"""GTK settings dialog for AverVOX LLM and TTS configuration."""

from __future__ import annotations

import os
import signal
import threading
from copy import deepcopy
from dataclasses import asdict

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from .glib_compat import idle_add, markup_escape_text

from .config import get_config, AppConfig, LLMProfile, CONFIG_FILE, _slugify
from .hotkeys import _parse_hotkey
from .logger import get_logger
from .ui_secrets import create_secret_entry

log = get_logger(__name__)

_WHISPER_MODELS: tuple[tuple[str, str], ...] = (
    ("tiny", "Tiny (fastest)"),
    ("base", "Base (balanced)"),
    ("small", "Small (more accurate)"),
    ("medium", "Medium (slower)"),
    ("large-v3", "Large v3 (best, slowest)"),
)

_ICON_TEST = "\u21bb"      # ↻  circular arrow

# Pro purchase page — see LINKS.md.
_PRO_UPGRADE_URL = "https://avervoxpro.com/"


def _spin(grid: Gtk.Grid, row: int, label: str, value: float,
           lo: float, hi: float, step: float, digits: int = 1) -> Gtk.SpinButton:
    lbl = Gtk.Label(label=label, xalign=0)
    grid.attach(lbl, 0, row, 1, 1)
    adj = Gtk.Adjustment(value=value, lower=lo, upper=hi,
                         step_increment=step, page_increment=step * 5)
    spin = Gtk.SpinButton(adjustment=adj, digits=digits)
    spin.set_hexpand(True)
    grid.attach(spin, 1, row, 1, 1)
    return spin


def _entry_labeled(grid: Gtk.Grid, row: int, label: str, value: str) -> Gtk.Entry:
    lbl = Gtk.Label(label=label, xalign=0)
    grid.attach(lbl, 0, row, 1, 1)
    entry = Gtk.Entry()
    entry.set_text(value)
    entry.set_hexpand(True)
    grid.attach(entry, 1, row, 1, 1)
    return entry


def _settings_tab(*widgets: Gtk.Widget) -> Gtk.ScrolledWindow:
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    inner.set_margin_start(4)
    inner.set_margin_end(4)
    inner.set_margin_top(8)
    inner.set_margin_bottom(8)
    for widget in widgets:
        inner.pack_start(widget, False, False, 0)
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(320)
    scroll.add(inner)
    return scroll


def _add_tab(notebook: Gtk.Notebook, label: str, *widgets: Gtk.Widget) -> None:
    notebook.append_page(_settings_tab(*widgets), Gtk.Label(label=label))


def _combo_labeled(
    grid: Gtk.Grid, row: int, label: str,
    options: tuple[tuple[str, str], ...], active_id: str,
) -> Gtk.ComboBoxText:
    lbl = Gtk.Label(label=label, xalign=0)
    grid.attach(lbl, 0, row, 1, 1)
    combo = Gtk.ComboBoxText()
    for opt_id, opt_label in options:
        combo.append(opt_id, opt_label)
    valid = {opt_id for opt_id, _ in options}
    if active_id in valid:
        combo.set_active_id(active_id)
    elif active_id:
        combo.append(active_id, f"{active_id} (custom)")
        combo.set_active_id(active_id)
    else:
        combo.set_active_id(options[0][0])
    combo.set_hexpand(True)
    grid.attach(combo, 1, row, 1, 1)
    return combo


def _valid_hotkey(combo: str) -> bool:
    combo = combo.strip()
    if not combo:
        return False
    try:
        return len(_parse_hotkey(combo)) >= 2
    except Exception:
        return False


def _hotkeys_error(listen: str, speak: str, converse: str) -> str | None:
    checks = (
        ("Dictate", listen),
        ("Speak selection", speak),
        ("Converse", converse),
    )
    for name, combo in checks:
        if not _valid_hotkey(combo):
            return (
                f"Invalid hotkey for {name}: {combo!r}\n\n"
                "Use pynput format, e.g. <ctrl>+<alt>+space"
            )
    return None


def show_settings_dialog() -> None:
    """Open a modal settings dialog.  Saves to config.yaml and sends SIGHUP on OK."""
    cfg = get_config()

    profiles: dict[str, LLMProfile] = deepcopy(cfg.llm_profiles)
    active_key: list[str] = [cfg.llm_active]

    dialog = Gtk.Dialog(title="AverVOX Settings", flags=Gtk.DialogFlags.MODAL)
    dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                       Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
    dialog.set_default_size(520, 480)
    dialog.set_resizable(True)

    box = dialog.get_content_area()
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.set_margin_top(8)
    box.set_margin_bottom(8)

    upgrade_bar = Gtk.InfoBar()
    upgrade_bar.set_message_type(Gtk.MessageType.INFO)
    upgrade_bar.set_show_close_button(False)
    bar_content = upgrade_bar.get_content_area()
    lbl_upgrade = Gtk.Label()
    lbl_upgrade.set_markup(
        "Please consider upgrading to <b>AverVOX Pro</b>"
        " to support ongoing development &amp; maintenance."
    )
    lbl_upgrade.set_xalign(0.0)
    lbl_upgrade.set_line_wrap(True)
    bar_content.pack_start(lbl_upgrade, True, True, 0)
    btn_pro = Gtk.LinkButton(uri=_PRO_UPGRADE_URL, label="Upgrade to Pro \u2192")
    bar_content.pack_start(btn_pro, False, False, 0)
    box.pack_start(upgrade_bar, False, False, 0)

    notebook = Gtk.Notebook()
    notebook.set_tab_pos(Gtk.PositionType.TOP)
    box.pack_start(notebook, True, True, 0)

    fetched_models: list[str] = []

    # ── Hotkeys tab ──
    g_hotkeys = Gtk.Grid(column_spacing=8, row_spacing=8)
    e_hk_listen = _entry_labeled(g_hotkeys, 0, "Dictate", cfg.hotkeys.listen)
    e_hk_listen.set_placeholder_text("<ctrl>+<alt>+space")
    e_hk_speak = _entry_labeled(g_hotkeys, 1, "Speak selection", cfg.hotkeys.speak_selection)
    e_hk_speak.set_placeholder_text("<ctrl>+<alt>+s")
    e_hk_converse = _entry_labeled(g_hotkeys, 2, "Converse", cfg.hotkeys.converse)
    e_hk_converse.set_placeholder_text("<ctrl>+<alt>+c")
    lbl_hk_hint = Gtk.Label(xalign=0)
    lbl_hk_hint.set_markup(
        '<small>Modifier keys use angle brackets, e.g. <tt>&lt;ctrl&gt;+&lt;alt&gt;+c</tt>. '
        'Changes apply immediately after Save.</small>'
    )
    lbl_hk_hint.set_line_wrap(True)
    g_hotkeys.attach(lbl_hk_hint, 0, 3, 2, 1)
    _add_tab(notebook, "Hotkeys", g_hotkeys)

    # ── LLM tab ──
    g_prof = Gtk.Grid(column_spacing=8, row_spacing=8)

    combo_profile = Gtk.ComboBoxText()
    combo_profile.set_hexpand(True)
    g_prof.attach(combo_profile, 0, 0, 1, 1)

    btn_add = Gtk.Button(label="+")
    btn_add.set_tooltip_text("Add new profile")
    btn_add.set_size_request(36, -1)
    g_prof.attach(btn_add, 1, 0, 1, 1)

    btn_del = Gtk.Button(label="\u2212")  # −
    btn_del.set_tooltip_text("Delete this profile")
    btn_del.set_size_request(36, -1)
    g_prof.attach(btn_del, 2, 0, 1, 1)

    def _repopulate_combo():
        _switching[0] = True
        combo_profile.remove_all()
        for key, prof in profiles.items():
            combo_profile.append(key, prof.label or key)
        if active_key[0] in profiles:
            combo_profile.set_active_id(active_key[0])
        elif profiles:
            first = next(iter(profiles))
            combo_profile.set_active_id(first)
            active_key[0] = first
        btn_del.set_sensitive(len(profiles) > 1)
        _switching[0] = False

    g_conn = Gtk.Grid(column_spacing=8, row_spacing=8)

    e_label = _entry_labeled(g_conn, 0, "Label", "")
    e_label.set_placeholder_text("e.g. Ollama (local)")

    lbl_url = Gtk.Label(label="URL", xalign=0)
    g_conn.attach(lbl_url, 0, 1, 1, 1)

    e_base = Gtk.Entry()
    e_base.set_placeholder_text("http://localhost:1234/v1")
    e_base.set_hexpand(True)
    g_conn.attach(e_base, 1, 1, 1, 1)

    btn_test = Gtk.Button(label=_ICON_TEST)
    btn_test.set_tooltip_text("Test connection")
    btn_test.set_size_request(36, -1)
    g_conn.attach(btn_test, 2, 1, 1, 1)

    sw_enabled = Gtk.Switch()
    sw_enabled.set_tooltip_text("Enable connection")
    sw_enabled.set_valign(Gtk.Align.CENTER)
    g_conn.attach(sw_enabled, 3, 1, 1, 1)

    lbl_status = Gtk.Label(label="", xalign=0)
    lbl_status.set_line_wrap(True)
    lbl_status.set_selectable(True)
    g_conn.attach(lbl_status, 1, 2, 3, 1)

    lbl_key = Gtk.Label(label="API Key", xalign=0)
    g_conn.attach(lbl_key, 0, 3, 1, 1)

    e_key, btn_eye = create_secret_entry(placeholder="leave blank for local models")
    g_conn.attach(e_key, 1, 3, 1, 1)
    g_conn.attach(btn_eye, 2, 3, 1, 1)

    lbl_model = Gtk.Label(label="Model", xalign=0)
    g_conn.attach(lbl_model, 0, 4, 1, 1)

    combo_model = Gtk.ComboBoxText.new_with_entry()
    combo_model.set_hexpand(True)
    model_entry = combo_model.get_child()
    model_entry.set_placeholder_text('Leave empty to include all models')
    g_conn.attach(combo_model, 1, 4, 3, 1)

    e_session_hdr = _entry_labeled(g_conn, 5, "Session header", "")
    e_session_hdr.set_placeholder_text("e.g. X-Hermes-Session-Id (blank = none)")

    _add_tab(notebook, "LLM", g_prof, g_conn)

    # ── Profile ↔ fields synchronization ──
    _switching = [False]

    def _load_profile_into_fields(key: str):
        """Populate connection fields from the given profile."""
        prof = profiles.get(key, LLMProfile())
        _switching[0] = True
        e_label.set_text(prof.label)
        e_base.set_text(prof.api_base)
        sw_enabled.set_active(bool(prof.api_base))
        e_key.set_text(prof.api_key)
        model_entry.set_text(prof.default_model)
        e_session_hdr.set_text(prof.session_header)
        lbl_status.set_text("")
        _switching[0] = False

    def _save_fields_to_profile(key: str):
        """Write current field values back into the named profile."""
        if key not in profiles:
            return
        prof = profiles[key]
        prof.label = e_label.get_text().strip()
        prof.api_base = e_base.get_text().strip() if sw_enabled.get_active() else ""
        prof.api_key = e_key.get_text().strip()
        prof.default_model = model_entry.get_text().strip()
        prof.session_header = e_session_hdr.get_text().strip()

    def _on_profile_changed(combo):
        if _switching[0]:
            return
        old = active_key[0]
        if old and old in profiles:
            _save_fields_to_profile(old)
        new = combo.get_active_id()
        if new:
            active_key[0] = new
            _load_profile_into_fields(new)

    combo_profile.connect("changed", _on_profile_changed)

    def _on_add_clicked(_btn):
        _save_fields_to_profile(active_key[0])
        new_prof = LLMProfile(label="New Connection")
        new_key = _slugify("new-connection")
        suffix = 1
        while new_key in profiles:
            new_key = _slugify(f"new-connection-{suffix}")
            suffix += 1
        profiles[new_key] = new_prof
        active_key[0] = new_key
        _repopulate_combo()
        _load_profile_into_fields(new_key)

    def _on_del_clicked(_btn):
        if len(profiles) <= 1:
            return
        key = active_key[0]
        if key in profiles:
            del profiles[key]
        active_key[0] = next(iter(profiles)) if profiles else ""
        _repopulate_combo()
        if active_key[0]:
            _load_profile_into_fields(active_key[0])

    btn_add.connect("clicked", _on_add_clicked)
    btn_del.connect("clicked", _on_del_clicked)

    _repopulate_combo()
    if active_key[0]:
        _load_profile_into_fields(active_key[0])

    # ── Test connection logic ──
    def _on_test_clicked(_btn):
        base = e_base.get_text().strip()
        key = e_key.get_text().strip()
        if not base:
            lbl_status.set_markup('<span color="red">Enter a URL first.</span>')
            return
        btn_test.set_sensitive(False)
        lbl_status.set_markup("Connecting\u2026")
        threading.Thread(target=_do_test, args=(base, key), daemon=True).start()

    def _do_test(base: str, key: str):
        try:
            import httpx
            headers: dict[str, str] = {}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            normalized = base.rstrip("/")
            if normalized.endswith("/v1"):
                normalized = normalized[:-3]
            url = f"{normalized}/v1/models"
            resp = httpx.get(url, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("id", "?") for m in data.get("data", [])]
            idle_add(_on_test_success, models)
        except Exception as exc:
            msg = f'<span color="red">{markup_escape_text(str(exc))}</span>'
            idle_add(_on_test_fail, msg)

    def _on_test_success(models: list[str]):
        fetched_models.clear()
        fetched_models.extend(models)
        combo_model.remove_all()
        for m in models:
            combo_model.append_text(m)
        current = model_entry.get_text().strip()
        if not current and models:
            model_entry.set_text(models[0])
        count = len(models)
        lbl_status.set_markup(
            f'<span color="green">\u2714 Connected — {count} model{"s" if count != 1 else ""} available</span>'
        )
        sw_enabled.set_active(True)
        btn_test.set_sensitive(True)
        return False

    def _on_test_fail(msg: str):
        lbl_status.set_markup(msg)
        sw_enabled.set_active(False)
        btn_test.set_sensitive(True)
        return False

    btn_test.connect("clicked", _on_test_clicked)

    # ── TTS tab ──
    g_tts = Gtk.Grid(column_spacing=8, row_spacing=8)

    e_voice_model = _entry_labeled(g_tts, 0, "Piper voice model", cfg.tts.voice_model)
    e_voice_model.set_placeholder_text("~/.local/share/piper-tts/voices/en_US-lessac-high.onnx")

    _add_tab(notebook, "Text-to-Speech", g_tts)

    # ── Dictate tab ──
    g_dict = Gtk.Grid(column_spacing=8, row_spacing=8)

    lbl_stt = Gtk.Label(label="Speech model", xalign=0)
    g_dict.attach(lbl_stt, 0, 0, 1, 1)
    combo_stt = Gtk.ComboBoxText()
    for model_id, model_label in _WHISPER_MODELS:
        combo_stt.append(model_id, model_label)
    combo_stt.set_hexpand(True)
    g_dict.attach(combo_stt, 1, 0, 1, 1)
    if cfg.stt.model in {m[0] for m in _WHISPER_MODELS}:
        combo_stt.set_active_id(cfg.stt.model)
    else:
        combo_stt.append(cfg.stt.model, f"{cfg.stt.model} (custom)")
        combo_stt.set_active_id(cfg.stt.model)

    e_stt_lang = _entry_labeled(g_dict, 1, "Language", cfg.stt.language)
    e_stt_lang.set_placeholder_text("en")

    s_dict_pause = _spin(
        g_dict, 2, "Interim pause (ms)",
        float(cfg.audio.silence_duration_ms),
        500.0, 5000.0, 100.0, digits=0,
    )
    s_dict_vad = _spin(
        g_dict, 3, "Pause sensitivity (0–3)",
        float(cfg.audio.vad_aggressiveness),
        0.0, 3.0, 1.0, digits=0,
    )

    lbl_dict_hint = Gtk.Label(xalign=0)
    lbl_dict_hint.set_markup(
        '<small>After each pause, spoken text is typed into the focused app while '
        'recording continues. Press the Dictate hotkey again to finish. '
        'Pause timing also applies to Converse end-of-turn and '
        '<tt>avrvx --listen</tt>.</small>'
    )
    lbl_dict_hint.set_line_wrap(True)
    g_dict.attach(lbl_dict_hint, 0, 4, 2, 1)

    _add_tab(notebook, "Dictate", g_dict)

    # ── Converse tab ──
    g_conv = Gtk.Grid(column_spacing=8, row_spacing=8)

    s_silence = _spin(g_conv, 0, "Silence timeout (sec)",
                      cfg.converse.silence_timeout_ms / 1000,
                      1.0, 30.0, 1.0, digits=0)
    s_rearm = _spin(g_conv, 1, "Re-arm delay (ms)",
                    float(cfg.converse.rearm_delay_ms),
                    50.0, 2000.0, 50.0, digits=0)

    lbl_goodbye = Gtk.Label(label="Goodbye phrases (comma-separated)", xalign=0)
    g_conv.attach(lbl_goodbye, 0, 2, 1, 1)
    e_goodbye = Gtk.Entry()
    e_goodbye.set_text(", ".join(cfg.converse.goodbye_phrases))
    e_goodbye.set_hexpand(True)
    g_conv.attach(e_goodbye, 1, 2, 1, 1)

    lbl_intr = Gtk.Label(label="Voice interrupt (barge-in)", xalign=0)
    g_conv.attach(lbl_intr, 0, 3, 1, 1)
    sw_interrupt = Gtk.Switch()
    sw_interrupt.set_active(cfg.converse.interrupt_enabled)
    sw_interrupt.set_valign(Gtk.Align.CENTER)
    sw_interrupt.set_halign(Gtk.Align.START)
    g_conv.attach(sw_interrupt, 1, 3, 1, 1)

    lbl_hp_warn = Gtk.Label(xalign=0)
    lbl_hp_warn.set_markup(
        '<span color="red"><b>Headphones Required!</b></span>  '
        'This feature will malfunction due to feedback\n'
        'if use is attempted without headphones.'
    )
    lbl_hp_warn.set_line_wrap(True)
    lbl_hp_warn.set_no_show_all(True)
    lbl_hp_warn.set_visible(cfg.converse.interrupt_enabled)
    g_conv.attach(lbl_hp_warn, 0, 4, 2, 1)

    cb_headphones = Gtk.CheckButton(label="Headphones are in use.")
    cb_headphones.set_active(cfg.converse.interrupt_headphones_confirmed)
    cb_headphones.set_no_show_all(True)
    cb_headphones.set_visible(cfg.converse.interrupt_enabled)
    g_conv.attach(cb_headphones, 0, 5, 2, 1)

    def _on_interrupt_switch(sw, _gparam):
        active = sw.get_active()
        lbl_hp_warn.set_visible(active)
        cb_headphones.set_visible(active)
        if not active:
            cb_headphones.set_active(False)

    sw_interrupt.connect("notify::active", _on_interrupt_switch)

    _add_tab(notebook, "Converse", g_conv)

    # ── Advanced tab ──
    g_adv = Gtk.Grid(column_spacing=8, row_spacing=8)
    combo_inserter = _combo_labeled(
        g_adv, 0, "Text inserter",
        (("xdotool", "xdotool (X11)"), ("ydotool", "ydotool (Wayland)")),
        cfg.backends.text_inserter,
    )
    combo_selection = _combo_labeled(
        g_adv, 1, "Selection provider",
        (
            ("xclip", "xclip (X11)"),
            ("xsel", "xsel (X11)"),
            ("wl-paste", "wl-paste (Wayland)"),
        ),
        cfg.backends.selection_provider,
    )
    lbl_adv_hint = Gtk.Label(xalign=0)
    lbl_adv_hint.set_markup(
        '<small>Dictate typing and Speak Selection clipboard access. '
        'On Wayland, prefer ydotool and wl-paste.</small>'
    )
    lbl_adv_hint.set_line_wrap(True)
    g_adv.attach(lbl_adv_hint, 0, 2, 2, 1)
    _add_tab(notebook, "Advanced", g_adv)

    while True:
        dialog.show_all()
        resp = dialog.run()
        if resp != Gtk.ResponseType.OK:
            break

        hk_err = _hotkeys_error(
            e_hk_listen.get_text(),
            e_hk_speak.get_text(),
            e_hk_converse.get_text(),
        )
        if hk_err:
            err_dlg = Gtk.MessageDialog(
                transient_for=dialog,
                flags=Gtk.DialogFlags.MODAL,
                type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="Invalid hotkey",
            )
            err_dlg.format_secondary_text(hk_err)
            err_dlg.run()
            err_dlg.destroy()
            continue

        _save_fields_to_profile(active_key[0])

        cfg.llm_profiles = profiles
        cfg.llm_active = active_key[0]

        cfg.hotkeys.listen = e_hk_listen.get_text().strip()
        cfg.hotkeys.speak_selection = e_hk_speak.get_text().strip()
        cfg.hotkeys.converse = e_hk_converse.get_text().strip()

        cfg.backends.text_inserter = combo_inserter.get_active_id() or "xdotool"
        cfg.backends.selection_provider = combo_selection.get_active_id() or "xclip"

        cfg.tts.voice_model = e_voice_model.get_text().strip()

        cfg.stt.model = combo_stt.get_active_id() or "base"
        cfg.stt.language = e_stt_lang.get_text().strip() or "en"
        cfg.audio.silence_duration_ms = int(s_dict_pause.get_value())
        cfg.audio.vad_aggressiveness = int(s_dict_vad.get_value())

        cfg.converse.silence_timeout_ms = int(s_silence.get_value() * 1000)
        cfg.converse.rearm_delay_ms = int(s_rearm.get_value())
        raw_goodbye = e_goodbye.get_text().strip()
        cfg.converse.goodbye_phrases = [
            p.strip().lower() for p in raw_goodbye.split(",") if p.strip()
        ] if raw_goodbye else []
        cfg.converse.interrupt_enabled = sw_interrupt.get_active()
        cfg.converse.interrupt_headphones_confirmed = cb_headphones.get_active()

        cfg.save()
        log.info("Settings saved to %s", CONFIG_FILE)
        os.kill(os.getpid(), signal.SIGHUP)
        break

    dialog.destroy()
