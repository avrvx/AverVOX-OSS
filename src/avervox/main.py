"""AverVOX — LLM speech bridge controller.

Three hotkey actions:
  Listen hotkey   → record until hotkey pressed again → STT → insert (Dictate)
                    interim text appears at natural pauses while recording
  Speak hotkey    → grab selection → TTS → play audio
  Converse hotkey → capture speech → STT → LLM → TTS → play audio (loops)

State machine:
  IDLE → LISTENING → TRANSCRIBING → INSERTING → IDLE   (Dictate: manual stop)
  IDLE → SPEAKING → IDLE
  IDLE → LISTENING ⇄ TRANSCRIBING → CONVERSING → SPEAKING → (loop back)
         └─ silence timeout or goodbye phrase ends the session
"""

from __future__ import annotations

import enum
import signal
import subprocess
import sys
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GLib", "2.0")
from gi.repository import GLib, Gtk

from .logger import setup_logging, get_logger
from .config import get_config, reload_config
from .hotkeys import HotkeyManager
from .audio import AudioCapture, InterruptMonitor
from . import tts
from .services import create_services
from .tray import TrayIcon
from .hud import ConversationHUD
from .glib_compat import timeout_add, idle_add, clipboard_set_text

log = get_logger(__name__)

_DEFAULT_GOODBYE_PHRASES = ("talk to you later", "goodbye", "bye bye",
                            "see you later", "that's all", "good night",
                            "i'm done")


class AppState(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    INSERTING = "inserting"
    CONVERSING = "conversing"
    SPEAKING = "speaking"
    ERROR = "error"


class AverVoxApp:
    def __init__(self) -> None:
        self._state = AppState.IDLE
        self._cfg = get_config()
        self._converse_history: list[dict] = []
        self._listen_mode: str = "dictation"
        self._conversing_session = False
        self._converse_ending = False
        self._converse_timer_id: int = 0
        self._interrupted = False
        self._last_response: str = ""
        self._dictate_insert_lock = threading.Lock()
        self._dictate_had_interim = False

        self._speech, self._insert, self._llm = create_services(self._cfg)

        self._speech.configure(model=self._cfg.stt.model, language=self._cfg.stt.language)
        self._speech.preload()

        tts.configure(voice_model=self._cfg.tts.voice_model)
        tts.preload()

        self._audio = AudioCapture()
        self._audio.configure(
            aggressiveness=self._cfg.audio.vad_aggressiveness,
            silence_duration_ms=self._cfg.audio.silence_duration_ms,
        )

        self._hotkeys = HotkeyManager()
        self._hud = ConversationHUD()
        self._tray = TrayIcon(
            on_quit=self._quit,
            on_reload=self._reload_config,
            on_settings=self._show_settings,
            on_switch_profile=self._switch_llm_profile,
            on_copy_last=self._copy_last_response,
            on_open_log=self._open_log,
            on_about=self._show_about,
        )
        self._sync_tray_profiles()

    def run(self) -> None:
        converse_key = getattr(self._cfg.hotkeys, "converse", "")
        bindings = {
            self._cfg.hotkeys.listen: self._toggle_listen,
            self._cfg.hotkeys.speak_selection: self._speak_selection,
        }
        if converse_key:
            bindings[converse_key] = self._converse

        log.info("AverVOX ready (listen=%s, speak=%s, converse=%s)",
                 self._cfg.hotkeys.listen, self._cfg.hotkeys.speak_selection,
                 converse_key or "disabled")
        self._hotkeys.start(bindings)
        self._notify_startup()
        signal.signal(signal.SIGINT, lambda *_: self._quit())
        signal.signal(signal.SIGTERM, lambda *_: self._quit())
        signal.signal(signal.SIGHUP, lambda *_: idle_add(self._reload_config))
        Gtk.main()

    def _notify_startup(self) -> None:
        try:
            subprocess.Popen(
                ["notify-send", "-a", "AverVOX OSS", "AverVOX OSS",
                 "Ready — hotkeys active"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    # ─── State ──────────────────────────────────────────────────────────────────

    def _set_state(self, state: AppState) -> None:
        self._state = state
        self._tray.set_state(state.value)
        if self._conversing_session:
            _HUD_MAP = {
                AppState.LISTENING: "recording",
                AppState.TRANSCRIBING: "awaiting",
                AppState.CONVERSING: "awaiting",
                AppState.SPEAKING: "streaming",
            }
            hud_state = _HUD_MAP.get(state)
            if hud_state:
                self._hud.show(hud_state)
        elif self._listen_mode == "dictation":
            _DICTATE_HUD = {
                AppState.LISTENING: "dictate_recording",
                AppState.TRANSCRIBING: "dictate_processing",
                AppState.INSERTING: "dictate_processing",
            }
            hud_state = _DICTATE_HUD.get(state)
            if hud_state:
                self._hud.show(hud_state)
            elif state == AppState.IDLE:
                self._hud.hide()

    # ─── Listen → Transcribe → Insert ──────────────────────────────────────────

    def _toggle_listen(self) -> None:
        if self._state == AppState.IDLE:
            self._start_listening()
        elif self._state == AppState.LISTENING:
            self._stop_listening()

    def _start_listening(self, mode: str = "dictation") -> None:
        log.info("Listening (%s)...", mode)
        self._listen_mode = mode
        self._set_state(AppState.LISTENING)
        if mode == "dictation":
            self._dictate_had_interim = False
            self._audio.set_on_segment(None)
            self._audio.set_on_interim_segment(self._on_dictate_interim)
            self._audio.start(recorder_mode=True)
        else:
            self._audio.set_on_interim_segment(None)
            self._audio.set_on_segment(self._on_audio_segment)
            self._audio.start(recorder_mode=False)

    def _stop_listening(self) -> None:
        log.info("Stopping listen (%s)", self._listen_mode)
        result = self._audio.stop()
        if result is None or len(result.audio) == 0:
            self._set_state(AppState.IDLE)
            return

        if self._listen_mode == "dictation":
            remainder = result.audio[result.committed_samples:]
            if len(remainder) > 0:
                timeout_add(100, self._transcribe_audio, remainder)
            elif self._dictate_had_interim:
                log.debug("Dictate finished — remainder empty after interim inserts")
                self._set_state(AppState.IDLE)
            else:
                timeout_add(100, self._transcribe_audio, result.audio)
            return

        timeout_add(100, self._transcribe_audio, result.audio)

    def _on_dictate_interim(self, audio) -> None:
        idle_add(self._schedule_dictate_interim, audio.copy())

    def _schedule_dictate_interim(self, audio) -> bool:
        threading.Thread(
            target=self._do_dictate_interim_insert,
            args=(audio,),
            daemon=True,
            name="stt-interim",
        ).start()
        return False

    def _dictate_format_chunk(self, text: str, *, final: bool = False) -> str:
        text = text.strip()
        if not final and text:
            if text[-1] not in " \n":
                text += " "
        return text

    def _do_dictate_interim_insert(self, audio) -> None:
        duration_s = len(audio) / 16000
        log.debug("Dictate interim: transcribing %.1fs...", duration_s)
        try:
            with self._dictate_insert_lock:
                text = self._speech.transcribe(audio, long_form=False)
                if not text:
                    return
                text = self._dictate_format_chunk(text)
                log.info("Dictate interim (%d chars): %s", len(text), text[:80])
                method = self._insert.insert_text(text, backend=self._cfg.backends.text_inserter)
                log.info("Dictate interim inserted via %s", method)
                self._dictate_had_interim = True
        except Exception as exc:
            log.error("Dictate interim insert error: %s", exc)

    def _on_audio_segment(self, audio) -> None:
        """Called from audio thread when VAD detects end of speech (Converse only)."""
        idle_add(self._on_segment_main_thread, audio)

    def _on_segment_main_thread(self, audio) -> bool:
        if self._state != AppState.LISTENING:
            return False
        if self._listen_mode == "dictation":
            return False
        self._cancel_converse_timer()
        self._audio.stop()
        timeout_add(100, self._transcribe_audio, audio)
        return False

    def _transcribe_audio(self, audio) -> bool:
        """Called on the main thread; dispatches to the correct pipeline."""
        self._set_state(AppState.TRANSCRIBING)
        if self._listen_mode == "converse":
            threading.Thread(
                target=self._do_transcribe_converse, args=(audio,),
                daemon=True, name="stt-llm",
            ).start()
        else:
            threading.Thread(
                target=self._do_transcribe_insert, args=(audio,),
                daemon=True, name="stt-insert",
            ).start()
        return False

    def _do_transcribe_insert(self, audio) -> None:
        """Background thread: transcribe audio then insert the result."""
        duration_s = len(audio) / 16000
        log.debug("Transcribing %.1fs of audio...", duration_s)
        try:
            with self._dictate_insert_lock:
                if self._dictate_had_interim:
                    long_form = duration_s > 8.0
                else:
                    long_form = True
                text = self._speech.transcribe(audio, long_form=long_form)
        except Exception as exc:
            log.error("STT error: %s", exc)
            idle_add(self._enter_error_state)
            return

        if text:
            text = self._dictate_format_chunk(text, final=True)
            log.info("Transcribed (%d chars): %s", len(text), text[:120])
            idle_add(self._set_state, AppState.INSERTING)
            try:
                with self._dictate_insert_lock:
                    method = self._insert.insert_text(text, backend=self._cfg.backends.text_inserter)
                log.info("Inserted via %s", method)
            except Exception as exc:
                log.error("Insert error: %s", exc)
                idle_add(self._enter_error_state)
                return
        else:
            log.info("No speech detected (%.1fs audio yielded empty text)", duration_s)

        idle_add(self._set_state, AppState.IDLE)

    def _enter_error_state(self) -> bool:
        """Must be called on the main thread (schedules a GLib timer)."""
        self._set_state(AppState.ERROR)
        timeout_add(2000, self._clear_error)
        return False

    # ─── Selection → Speak ──────────────────────────────────────────────────────

    def _speak_selection(self) -> None:
        if self._state == AppState.SPEAKING:
            tts.stop()
            self._set_state(AppState.IDLE)
            return

        text = self._insert.get_selection(backend=self._cfg.backends.selection_provider)
        if not text:
            log.info("No text selected to speak")
            return

        log.info("Speaking selection: %s", text[:100])
        self._set_state(AppState.SPEAKING)
        threading.Thread(target=self._speak_thread, args=(text,), daemon=True).start()

    def _speak_thread(self, text: str) -> None:
        try:
            tts.speak(text)
        except Exception as exc:
            log.error("TTS error: %s", exc)
        idle_add(self._on_speak_done)

    def _on_speak_done(self) -> bool:
        if self._state == AppState.SPEAKING:
            self._set_state(AppState.IDLE)
        return False

    # ─── Converse (STT → LLM → TTS) ─────────────────────────────────────────

    def _converse(self) -> None:
        """Hotkey handler: start or stop the conversation loop."""
        if self._conversing_session:
            log.info("Converse hotkey pressed — ending session")
            self._end_converse_session()
            return
        if self._state == AppState.SPEAKING:
            tts.stop()
            self._set_state(AppState.IDLE)
            return
        if self._state != AppState.IDLE:
            return
        if not self._llm.is_available():
            log.warning("Converse unavailable — LLM service not connected")
            _notify("Converse unavailable", "No LLM server configured or connected.")
            return
        self._conversing_session = True
        self._converse_history.clear()
        log.info("Starting new conversation")
        self._start_listening(mode="converse")
        self._arm_converse_timer()

    # ─── Converse session management ─────────────────────────────────────────

    def _arm_converse_timer(self) -> None:
        """Start (or restart) the silence timeout for converse mode."""
        self._cancel_converse_timer()
        self._converse_timer_id = timeout_add(
            self._cfg.converse.silence_timeout_ms, self._on_converse_silence_timeout,
        )

    def _cancel_converse_timer(self) -> None:
        if self._converse_timer_id:
            GLib.source_remove(self._converse_timer_id)
            self._converse_timer_id = 0

    def _on_converse_silence_timeout(self) -> bool:
        """No speech for 7 s while listening — end the conversation."""
        self._converse_timer_id = 0
        if self._conversing_session and self._state == AppState.LISTENING:
            if self._audio.has_speech_activity():
                log.debug("Silence timer fired but speech active — re-arming")
                self._arm_converse_timer()
            else:
                log.info("No speech for %d s — ending conversation",
                         self._cfg.converse.silence_timeout_ms // 1000)
                self._end_converse_session()
        return False

    def _end_converse_session(self) -> None:
        """Clean up an active converse session regardless of current state."""
        was_active = self._conversing_session or self._converse_ending
        ending_goodbye = self._converse_ending
        self._conversing_session = False
        self._converse_ending = False
        self._cancel_converse_timer()
        if self._state == AppState.LISTENING:
            self._audio.stop()
        elif self._state == AppState.SPEAKING:
            tts.stop()
        if ending_goodbye:
            self._converse_history.clear()
        self._set_state(AppState.IDLE)
        if was_active:
            self._hud.show("ended", auto_dismiss_ms=2500)
            log.info("Conversation ended")

    def _do_transcribe_converse(self, audio) -> None:
        """Background thread: transcribe audio, send to LLM, speak response.

        Uses streaming when the LLM service supports it, speaking each
        sentence as it arrives rather than waiting for the full response.
        """
        duration_s = len(audio) / 16000
        log.debug("Transcribing %.1fs of audio for conversation...", duration_s)
        try:
            text = self._speech.transcribe(audio)
        except Exception as exc:
            log.error("STT error: %s", exc)
            idle_add(self._enter_error_state)
            return

        if not text:
            log.info("No speech detected (%.1fs)", duration_s)
            if self._conversing_session:
                idle_add(self._converse_rearm)
            else:
                idle_add(self._set_state, AppState.IDLE)
            return

        log.info("User: %s", text[:100])

        text_lower = text.lower().strip()
        phrases = self._cfg.converse.goodbye_phrases or _DEFAULT_GOODBYE_PHRASES
        if any(p in text_lower for p in phrases):
            log.info("Goodbye phrase detected — will end session after response")
            self._converse_ending = True

        self._converse_history.append({"role": "user", "content": text})

        idle_add(self._set_state, AppState.CONVERSING)

        llm_cfg = getattr(self._cfg, "llm", None)
        model = getattr(llm_cfg, "default_model", "") if llm_cfg else ""
        stream_fn = getattr(self._llm, "stream_complete", None)

        if stream_fn is not None:
            self._do_stream_converse(stream_fn, model)
        else:
            self._do_batch_converse(model)

    def _on_voice_interrupt(self) -> None:
        """Called from InterruptMonitor thread when speech is detected."""
        log.info("Voice interrupt detected — stopping TTS")
        self._interrupted = True
        tts.stop()

    def _interrupt_active(self) -> bool:
        return (self._cfg.converse.interrupt_enabled
                and self._cfg.converse.interrupt_headphones_confirmed)

    def _do_stream_converse(self, stream_fn, model: str) -> None:
        """Stream LLM response, speaking each sentence as it arrives.

        A single audio stream stays open for the entire response so there
        are no audible gaps between sentences.
        """
        full_response = ""

        def _sentences():
            nonlocal full_response
            for sentence in stream_fn(list(self._converse_history), model=model):
                full_response += sentence + " "
                yield sentence

        monitor = None
        if self._interrupt_active():
            monitor = InterruptMonitor(
                on_interrupt=self._on_voice_interrupt,
                aggressiveness=self._cfg.audio.vad_aggressiveness,
            )

        idle_add(self._set_state, AppState.SPEAKING)
        if monitor:
            monitor.start()
        try:
            tts.speak_streamed(_sentences())
        except Exception as exc:
            log.error("LLM/TTS stream error: %s", exc)
            if not full_response:
                if monitor:
                    monitor.stop()
                idle_add(self._enter_error_state)
                return
        finally:
            if monitor:
                monitor.stop()

        if self._interrupted:
            self._interrupted = False
            full_response = full_response.strip()
            if full_response:
                log.info("Interrupted — partial: %s", full_response[:100])
                self._converse_history.append(
                    {"role": "assistant", "content": full_response})
                self._last_response = full_response
            idle_add(self._converse_rearm)
            return

        full_response = full_response.strip()
        if full_response:
            log.info("Assistant: %s", full_response[:100])
            self._converse_history.append({"role": "assistant", "content": full_response})
            self._last_response = full_response
        idle_add(self._on_converse_turn_done)

    def _do_batch_converse(self, model: str) -> None:
        """Non-streaming fallback: wait for full response, then speak."""
        try:
            response = self._llm.complete(list(self._converse_history), model=model)
        except Exception as exc:
            log.error("LLM error: %s", exc)
            idle_add(self._enter_error_state)
            return

        if not response:
            log.info("LLM returned empty response")
            if self._conversing_session:
                idle_add(self._converse_rearm)
            else:
                idle_add(self._set_state, AppState.IDLE)
            return

        log.info("Assistant: %s", response[:100])
        self._converse_history.append({"role": "assistant", "content": response})
        self._last_response = response

        monitor = None
        if self._interrupt_active():
            monitor = InterruptMonitor(
                on_interrupt=self._on_voice_interrupt,
                aggressiveness=self._cfg.audio.vad_aggressiveness,
            )

        idle_add(self._set_state, AppState.SPEAKING)
        if monitor:
            monitor.start()
        try:
            tts.speak(response)
        except Exception as exc:
            log.error("TTS error: %s", exc)
        finally:
            if monitor:
                monitor.stop()

        if self._interrupted:
            self._interrupted = False
            idle_add(self._converse_rearm)
            return

        idle_add(self._on_converse_turn_done)

    def _on_converse_turn_done(self) -> bool:
        """Called on main thread after a converse turn's TTS finishes."""
        if self._conversing_session and not self._converse_ending:
            timeout_add(self._cfg.converse.rearm_delay_ms, self._converse_rearm)
        else:
            self._end_converse_session()
        return False

    def _converse_rearm(self) -> bool:
        """Re-arm the mic after a short delay to avoid echo/feedback."""
        if not self._conversing_session:
            self._end_converse_session()
            return False
        log.debug("Re-arming converse listener")
        self._start_listening(mode="converse")
        self._arm_converse_timer()
        return False

    # ─── Config reload ──────────────────────────────────────────────────────────

    def _build_hotkey_bindings(self) -> dict[str, object]:
        """Return the hotkey→callback mapping from current config."""
        bindings: dict = {
            self._cfg.hotkeys.listen: self._toggle_listen,
            self._cfg.hotkeys.speak_selection: self._speak_selection,
        }
        converse_key = getattr(self._cfg.hotkeys, "converse", "")
        if converse_key:
            bindings[converse_key] = self._converse
        return bindings

    def _apply_config(self, cfg) -> None:
        """Push config values into all subsystems, rebuilding services if needed."""
        old_llm = self._llm
        self._speech, self._insert, self._llm = create_services(cfg)
        old_llm.shutdown()

        self._speech.configure(model=cfg.stt.model, language=cfg.stt.language)
        tts.configure(voice_model=cfg.tts.voice_model)
        self._audio.configure(
            aggressiveness=cfg.audio.vad_aggressiveness,
            silence_duration_ms=cfg.audio.silence_duration_ms,
        )
        self._sync_tray_profiles()

    def _reload_config(self) -> bool:
        """Reload config.yaml and re-apply all settings. Safe to call on main thread."""
        log.info("Reloading config...")
        prev_cfg = self._cfg
        try:
            self._cfg = reload_config()
            self._apply_config(self._cfg)
            self._hotkeys.update(self._build_hotkey_bindings())
            log.info("Config reloaded (listen=%s, speak=%s)",
                     self._cfg.hotkeys.listen, self._cfg.hotkeys.speak_selection)
            _notify_config_reloaded(self._cfg.hotkeys.listen, self._cfg.hotkeys.speak_selection)
        except Exception as exc:
            log.exception("Config reload failed: %s", exc)
            log.warning("Rolling back to previous config (listen=%s, speak=%s)",
                        prev_cfg.hotkeys.listen, prev_cfg.hotkeys.speak_selection)
            self._cfg = prev_cfg
            try:
                self._apply_config(prev_cfg)
                self._hotkeys.update(self._build_hotkey_bindings())
                log.info("Rollback complete — previous config restored")
                _notify_config_reload_failed(exc, rolled_back=True)
            except Exception as rb_exc:
                log.exception("Rollback itself failed: %s", rb_exc)
                _notify_config_reload_failed(exc, rolled_back=False)
        return False

    # ─── Utilities ──────────────────────────────────────────────────────────────

    def _clear_error(self) -> bool:
        if self._state == AppState.ERROR:
            self._set_state(AppState.IDLE)
        return False

    def _sync_tray_profiles(self) -> None:
        """Push the current LLM profile list to the tray menu."""
        labels = {k: p.label or k for k, p in self._cfg.llm_profiles.items()}
        self._tray.set_llm_profiles(labels, self._cfg.llm_active)

    def _switch_llm_profile(self, profile_key: str) -> None:
        """Switch the active LLM profile from the tray menu."""
        if profile_key == self._cfg.llm_active:
            return
        self._cfg.set_active_profile(profile_key)
        old_llm = self._llm
        self._speech, self._insert, self._llm = create_services(self._cfg)
        old_llm.shutdown()
        self._cfg.save()
        label = self._cfg.llm.label or profile_key
        log.info("Switched LLM profile to: %s", label)
        _notify("LLM Profile", f"Switched to {label}")

    def _show_settings(self) -> None:
        from .settings import show_settings_dialog
        show_settings_dialog()

    def _copy_last_response(self) -> None:
        if not self._last_response:
            log.info("No response to copy")
            return
        try:
            from gi.repository import Gdk
            display = Gdk.Display.get_default()
            clipboard = Gtk.Clipboard.get_default(display)
            clipboard_set_text(clipboard, self._last_response)
            clipboard.store()
        except Exception:
            subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
            ).communicate(self._last_response.encode())
        log.info("Copied last response to clipboard (%d chars)", len(self._last_response))

    def _open_log(self) -> None:
        from pathlib import Path
        log_path = Path.home() / ".local" / "share" / "avervox" / "avervox.log"
        if log_path.exists():
            subprocess.Popen(["xdg-open", str(log_path)])
        else:
            log.warning("Log file not found: %s", log_path)

    def _show_about(self) -> None:
        from .settings import show_settings_dialog
        show_settings_dialog(initial_tab="about")

    def _quit(self) -> None:
        log.info("AverVOX quitting")
        self._cancel_converse_timer()
        self._hud.destroy()
        tts.stop()
        self._llm.shutdown()
        self._audio.stop()
        self._hotkeys.stop()
        self._tray.destroy()
        Gtk.main_quit()


def _notify(title: str, body: str = "") -> None:
    """Send a desktop notification. Degrades silently."""
    try:
        cmd = ["notify-send", "--expire-time=3000", f"AverVOX OSS \u2014 {title}"]
        if body:
            cmd.append(body)
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        pass


def _notify_config_reloaded(listen_hotkey: str, speak_hotkey: str) -> None:
    """Send a desktop notification after a successful config reload.

    Degrades silently when ``notify-send`` is not installed.
    """
    body = f"Listen: {listen_hotkey}  |  Speak: {speak_hotkey}"
    try:
        subprocess.run(
            ["notify-send", "--expire-time=3000", "AverVOX OSS \u2014 config reloaded", body],
            check=False,
        )
    except FileNotFoundError:
        log.debug("notify-send not found; skipping desktop notification")


def _notify_config_reload_failed(exc: BaseException, *, rolled_back: bool = False) -> None:
    """Send a desktop notification after a failed config reload.

    When *rolled_back* is True the body notes that the previous config was
    restored successfully.  Degrades silently when ``notify-send`` is not
    installed.
    """
    summary = type(exc).__name__ + ": " + str(exc)
    if len(summary) > 200:
        summary = summary[:197] + "..."
    if rolled_back:
        summary += "\nPrevious config restored — AverVOX OSS is still running."
    else:
        summary += "\nRollback also failed — AverVOX OSS may be in an inconsistent state."
    try:
        subprocess.run(
            [
                "notify-send",
                "--urgency=critical",
                "--expire-time=5000",
                "AverVOX OSS \u2014 config reload failed",
                summary,
            ],
            check=False,
        )
    except FileNotFoundError:
        log.debug("notify-send not found; skipping desktop notification")


def main() -> None:
    GLib.set_prgname("avervox")
    GLib.set_application_name("AverVOX OSS")
    setup_logging()
    log.info("AverVOX starting")
    app = AverVoxApp()
    app.run()


if __name__ == "__main__":
    main()
