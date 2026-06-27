"""Tests for config-reload failure notifications in src/avervox/main.py.

Covers:
- _notify_config_reload_failed: title, urgency flag, summary format,
  truncation at 200 chars, silent degradation when notify-send is absent.
- AverVoxApp._reload_config: failure notification sent (and no success
  notification) when reload_config() raises; success path sends success
  notification only; return value is always False (GLib idle convention).
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Stub out GTK / GLib / pynput / sounddevice / webrtcvad before any avervox import
# ---------------------------------------------------------------------------

def _make_gi_stubs() -> None:
    """Inject minimal fakes for gi, Gtk, GLib, AppIndicator3, and other C-extension modules."""
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

    for name in ("pynput", "pynput.keyboard", "sounddevice", "webrtcvad",
                 "faster_whisper", "numpy"):
        sys.modules.setdefault(name, MagicMock())


_make_gi_stubs()

from avervox.main import _notify_config_reload_failed, _notify_config_reloaded  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _subprocess_args(mock_run) -> list[str]:
    """Return the command-list passed to the most recent subprocess.run call."""
    return mock_run.call_args[0][0]


# ---------------------------------------------------------------------------
# _notify_config_reload_failed — unit tests
# ---------------------------------------------------------------------------

class TestNotifyConfigReloadFailed:
    def test_title_is_correct(self):
        exc = ValueError("bad value")
        with patch("subprocess.run") as mock_run:
            _notify_config_reload_failed(exc)
        assert "AverVOX OSS \u2014 config reload failed" in _subprocess_args(mock_run)

    def test_urgency_flag_is_critical(self):
        exc = ValueError("bad value")
        with patch("subprocess.run") as mock_run:
            _notify_config_reload_failed(exc)
        assert "--urgency=critical" in _subprocess_args(mock_run)

    def test_summary_contains_exception_type_and_message(self):
        exc = ValueError("something went wrong")
        with patch("subprocess.run") as mock_run:
            _notify_config_reload_failed(exc)
        summary = _subprocess_args(mock_run)[-1]
        assert "ValueError" in summary
        assert "something went wrong" in summary

    def test_summary_truncated_at_200_chars(self):
        long_msg = "x" * 300
        exc = RuntimeError(long_msg)
        with patch("subprocess.run") as mock_run:
            _notify_config_reload_failed(exc)
        summary = _subprocess_args(mock_run)[-1]
        first_line = summary.split("\n")[0]
        assert len(first_line) <= 200
        assert first_line.endswith("...")

    def test_summary_exactly_200_chars_not_truncated(self):
        # Build a message so that "RuntimeError: " + msg is exactly 200 chars.
        prefix = "RuntimeError: "
        msg = "y" * (200 - len(prefix))
        exc = RuntimeError(msg)
        with patch("subprocess.run") as mock_run:
            _notify_config_reload_failed(exc)
        summary = _subprocess_args(mock_run)[-1]
        first_line = summary.split("\n")[0]
        assert len(first_line) == 200
        assert not first_line.endswith("...")

    def test_short_summary_not_truncated(self):
        exc = ValueError("short msg")
        with patch("subprocess.run") as mock_run:
            _notify_config_reload_failed(exc)
        summary = _subprocess_args(mock_run)[-1]
        assert not summary.endswith("...")
        assert "short msg" in summary

    def test_silent_when_notify_send_missing(self):
        exc = ValueError("something")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            _notify_config_reload_failed(exc)  # must not raise

    def test_works_with_various_exception_types(self):
        for exc in [
            FileNotFoundError("no file"),
            PermissionError("no perm"),
            KeyError("missing key"),
            OSError("os problem"),
        ]:
            with patch("subprocess.run") as mock_run:
                _notify_config_reload_failed(exc)
            summary = _subprocess_args(mock_run)[-1]
            assert type(exc).__name__ in summary


# ---------------------------------------------------------------------------
# AverVoxApp._reload_config — integration-style tests
# ---------------------------------------------------------------------------

class TestReloadConfigIntegration:
    """Test AverVoxApp._reload_config without starting the full GTK application."""

    def _make_app(self):
        """Instantiate AverVoxApp, bypassing __init__, with minimal mocked state."""
        from avervox.main import AverVoxApp
        app = object.__new__(AverVoxApp)
        app._cfg = MagicMock()
        app._cfg.hotkeys.listen = "<ctrl>+<alt>+space"
        app._cfg.hotkeys.speak_selection = "<ctrl>+<alt>+s"
        app._cfg.hotkeys.converse = "<ctrl>+<alt>+c"
        app._audio = MagicMock()
        app._hotkeys = MagicMock()
        app._speech = MagicMock()
        app._insert = MagicMock()
        app._llm = MagicMock()
        app._converse_history = []
        app._listen_mode = "dictation"
        app._tray = MagicMock()
        return app

    def test_failure_notification_sent_when_reload_raises(self):
        app = self._make_app()
        exc = RuntimeError("YAML parse error")

        with patch("avervox.main.reload_config", side_effect=exc), \
             patch("avervox.main._notify_config_reload_failed") as mock_fail, \
             patch("avervox.main._notify_config_reloaded") as mock_ok:
            app._reload_config()

        mock_fail.assert_called_once_with(exc, rolled_back=True)
        mock_ok.assert_not_called()

    def test_no_success_notification_when_reload_raises(self):
        app = self._make_app()

        with patch("avervox.main.reload_config", side_effect=ValueError("bad yaml")), \
             patch("avervox.main._notify_config_reload_failed"), \
             patch("avervox.main._notify_config_reloaded") as mock_ok:
            app._reload_config()

        mock_ok.assert_not_called()

    def test_success_notification_sent_when_reload_succeeds(self):
        app = self._make_app()
        new_cfg = MagicMock()
        new_cfg.hotkeys.listen = "<ctrl>+<alt>+l"
        new_cfg.hotkeys.speak_selection = "<ctrl>+<alt>+s"
        new_cfg.hotkeys.converse = "<ctrl>+<alt>+c"

        with patch("avervox.main.reload_config", return_value=new_cfg), \
             patch("avervox.main.tts"), \
             patch("avervox.main._notify_config_reload_failed") as mock_fail, \
             patch("avervox.main._notify_config_reloaded") as mock_ok:
            app._reload_config()

        mock_ok.assert_called_once()
        mock_fail.assert_not_called()

    def test_returns_false_on_failure(self):
        """_reload_config must return False (GLib idle/timeout callback convention)."""
        app = self._make_app()

        with patch("avervox.main.reload_config", side_effect=ValueError("bad")), \
             patch("avervox.main._notify_config_reload_failed"):
            result = app._reload_config()

        assert result is False

    def test_returns_false_on_success(self):
        app = self._make_app()
        new_cfg = MagicMock()
        new_cfg.hotkeys.converse = "<ctrl>+<alt>+c"

        with patch("avervox.main.reload_config", return_value=new_cfg), \
             patch("avervox.main.tts"), \
             patch("avervox.main._notify_config_reload_failed"), \
             patch("avervox.main._notify_config_reloaded"):
            result = app._reload_config()

        assert result is False

    def test_failure_notification_receives_the_raised_exception(self):
        """The exact exception object propagates to _notify_config_reload_failed."""
        app = self._make_app()
        exc = PermissionError("cannot read config file")

        with patch("avervox.main.reload_config", side_effect=exc), \
             patch("avervox.main._notify_config_reload_failed") as mock_fail, \
             patch("avervox.main._notify_config_reloaded"):
            app._reload_config()

        called_with = mock_fail.call_args[0][0]
        assert called_with is exc
