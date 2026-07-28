# Changelog

## 0.5.7 - 2026-07-27

- Fixes the Settings dialog not opening at all on newer PyGObject: `Gtk.Dialog(..., flags=Gtk.DialogFlags.MODAL)` raises `TypeError: gobject 'GtkDialog' doesn't support property 'flags'` on PyGObject 3.50+, which dropped the legacy shim that let `flags=` be passed as a constructor keyword. Replaced with the `modal=True` constructor keyword in the Settings dialog and its "invalid hotkey" validation popup.
- Fixes the `pip install avrvx` instructions in README/DOCS, which failed on Ubuntu 24.04, Debian 12+, and Linux Mint 22 with `error: externally-managed-environment` (PEP 668). Now recommends `pipx install avrvx` and explains the venv/`--break-system-packages` alternatives for plain `pip`.
- Fixes Converse mode getting stuck in an infinite "wake → instantly end conversation" loop if `converse.silence_timeout_ms` ever ended up stored below its valid 1–30 s range (e.g. `0`), which made every conversation end immediately with "No speech for 0 s". Root cause: `Gtk.Adjustment(value=..., lower=..., ...)`'s construction-time clamping of an out-of-range initial `value` isn't reliable across PyGObject versions, and Settings always re-saves whatever the widget currently shows, so a corrupted value never self-corrected. Settings' shared `_spin()` helper now constructs the adjustment without an initial value and calls the explicit `set_value()` setter instead, which clamps reliably either way. `main.py` also now sanity-checks the value at the point of use and falls back to the documented default (7 s) with a logged warning, so an already-corrupted config self-heals on the next launch without a trip through Settings first.
- Fixes Converse mode silently never contacting the LLM at all whenever no TTS voice was configured — speech was transcribed correctly, but the app would jump straight from "Listening" to "awaiting response" and right back to "Listening" with zero LLM traffic. Root cause: the streamed conversation path hands `tts.speak_streamed()` a *lazy* sentence generator whose iteration is what actually drives the LLM's streaming call. `speak_streamed()` returned immediately on `"TTS not available — no engine configured"` without ever touching that generator, so the LLM call embedded inside it never ran. It now drains the generator in that case — still no audio plays, but the LLM request goes out and the reply is captured for memory/transcript as normal.
- Fixes TTS being unconfigured out of the box for anyone who skipped `install.sh`'s Piper voice download step (e.g. a manual pip/pipx install) — the underlying reason the LLM-not-called bug above was so easy to hit. `avrvx` now calls a new `tts.ensure_default_voice_model()` at startup: it leaves an already-configured voice alone, adopts any Piper voice it finds already sitting in `~/.local/share/piper-tts/voices/`, and otherwise downloads the same default voice `install.sh` uses (`en_US-lessac-high`, ~109 MB). A network hiccup here only leaves TTS unconfigured as before; it never blocks the app from starting.
- Fixes Settings silently proposing to re-save a still-dangerously-low value for Converse's "Silence timeout (sec)" after loading a corrupted config: `Gtk.Adjustment.set_value()` correctly clamps an out-of-range stored value to the field's own minimum (1 s) — technically valid, but nowhere near the sane default (7 s) `main.py`'s own runtime floor falls back to, and easy to click Save without noticing. The field now shows the same sane default main.py would use whenever the stored value is invalid, so Save persists something reasonable even if the field is never touched.
- Extends the fix above to Converse's "Re-arm delay (ms)" and Dictate's "Interim pause (ms)": a real config.yaml recovered from testing showed both stored as `0` alongside `converse.silence_timeout_ms`, confirming the corruption wasn't limited to just that one field. A new shared `_sane_default()` helper now backs all three, each showing its documented default (7 s, 250 ms, 1000 ms respectively) instead of silently clamping to the field's own UI floor whenever the stored value is invalid.
- Fixes `stt.device: cuda`/`auto` (documented in the Performance Tuning table) being unable to ever actually see a GPU: startup unconditionally *overwrote* `CUDA_VISIBLE_DEVICES` to `""` (even if you'd already exported it yourself) before `faster-whisper`/`ctranslate2` got a chance to probe for CUDA, so the auto-detection in `stt._resolve_device()` could never find one. GPUs are now only hidden when your own config explicitly asks for `stt.device: cpu`.
- Fixes `avervox` (documented as a general-purpose alias for `avrvx`, registered as a second `console_scripts` entry point in `pyproject.toml`) not actually working after running `install.sh`, which only ever created an `avrvx` launcher. It now also writes an `avervox` symlink alongside it, so the alias works regardless of install method.
- Fixes several documentation-only inaccuracies found in a full docs-vs-code audit (no runtime behavior changes beyond the two items above): README's `disabled_models` re-enable example showed it nested under `llm.endpoints.<name>`, which doesn't match the code (`disabled_models` is a top-level `config.yaml` key, a sibling of `llm:`) — a user following that example verbatim would have had no effect; the same section referenced "the dashboard" greying out a disabled model, but AverVOX (this edition) has no Dashboard, only Settings; `TTS speed control` in the edition matrix didn't distinguish that the CLI `--speed` flag and `tts.speed` config already work in this edition — only the Settings UI control for it is Pro-only; the HUD pill was described as Converse-only when it also appears during Dictate; DOCS.md's edition matrix was missing the "Warm bridge daemon" row that README.md has; and `stt.beam_size` was listed as a tunable `config.yaml` default in both README.md and DOCS.md when it's actually an internal, automatic choice in `stt.py`.
- Fixes `audio.vad_aggressiveness`'s dataclass default (`1`) disagreeing with both `install.sh` (which writes `2`) and the documented sample `config.yaml` (which showed `2`) — a plain `pip install` user got a different default than the docs described. The dataclass default is now `2`, matching both.

## 0.5.6 - 2026-07-26

- Adds `avrvx --doctor`: preflight checks for the distro, display server, system packages, Python dependencies, microphone and playback, STT/TTS models, text insertion, the configured LLM endpoint, the warm daemon, and host integrations — each with a PASS/WARN/FAIL line and a fix hint. Non-intrusive (never plays audio, types, or writes files) and exits non-zero on failure, so it works in provisioning scripts.

## 0.5.5 - 2026-07-26

- Adds `avervox` as a command alias for `avrvx`; both launch the same app. A companion `avervox` alias package on PyPI makes `pip install avervox` work as well.
- Corrects the pip install command in README/DOCS (`pip install avrvx`, not `avervox`) and adds a naming note mapping the AverVOX product name to the `avrvx` package.

## 0.5.4 - 2026-07-26

- Documentation only; the code is unchanged from 0.5.3. Aligns Quick Start / DOCS with the Settings UI (including End-of-turn pause), fixes the Pro purchase link, and corrects startup notification wording.

## 0.5.3 - 2026-07-26

- No functional change. The version moves in step with AverVOX Pro 0.5.3, which repairs an AppImage entry point that the OSS edition does not ship.

## 0.5.2 - 2026-07-26

- Documentation only; the code is unchanged from 0.5.1. The README and quick start described Odysseus as a ready-made integration package alongside Hermes Agent and OpenClaw. Odysseus has no package — it ships its own local TTS and its plugin ABI is still settling, so the supported path is pointing AverVOX Converse at its OpenAI-compatible endpoint. `DOCS.md` already worded this correctly and the rest now matches it.

## 0.5.1 - 2026-07-26

- `avrvx --install-integration openclaw` suggested `clawhub package install`, which is not a ClawHub subcommand. OpenClaw plugins install through OpenClaw itself with `openclaw plugins install @avervox/openclaw-plugin`, which tries ClawHub and falls back to npm, where the plugin is published.

## 0.5.0 - 2026-07-26

- Bridge CLI: `--voice` and `--speed` override the configured defaults for a single call, and `--capabilities` gained a `tts.voices` list so host applications can render a voice picker.
- TTS backends are now cached per voice, so switching voices no longer reloads a model that was already in memory.
- `SIGTERM` during synthesis stops cleanly and exits `130`, letting callers distinguish a cancellation from a failure.
- New `avrvx --daemon`: keeps the models loaded and serves `capabilities`, `synthesize`, `transcribe`, `cancel`, and `ping` over a `0600` Unix socket at `$XDG_RUNTIME_DIR/avervox/bridge.sock`. Roughly 2.5x faster per call on the reference machine. Reported in `--capabilities` as `features.daemon`.
- Streaming synthesis: `--synthesize --output -` writes raw PCM to stdout as it is generated, and the daemon's `synthesize` accepts `"stream": true` to send framed audio. First audio arrives after the first sentence rather than after the whole reply.
- New `text.py` holds the sentence splitter the LLM stream and the speech pipeline both use, which previously existed as two separate definitions.
- New `avrvx --install-integration hermes|openclaw` writes a host's speech configuration and then verifies it by synthesizing real audio. An existing host configuration is never modified; the snippet is written alongside it instead.
- Fixed: every `avrvx` command ran twice when AverVOX was installed from PyPI. The console script entry point calls `main()`, and `__main__.py` also called it on import, so `--capabilities` printed two JSON objects (which no host could parse) and `--synthesize` synthesized twice. Installs launched through the tray script were unaffected.

## 0.4.0 - 2026-07-25

- Bridge CLI: `avrvx --synthesize` writes speech to a WAV file (`--text`, `--text-file`, or stdin via `--text -`), `avrvx --transcribe FILE` prints a transcript, and `avrvx --capabilities` emits a JSON capability probe (edition, engines, features) for host integrations.
- Synthesized WAV files are created mode `0600`; the output directory must already exist.
- TTS: new `synthesize_to_file()`; STT: new `transcribe_file()`.
- Integrations: plugin packages for Hermes Agent and OpenClaw plus an Odysseus guide, all built on the bridge CLI.
- Documentation: bridge CLI reference in README, DOCS, and the quick start guide.

## 0.3.9 - 2026-07-12

- Config: split `dictate.interim_pause_ms` and `converse.end_of_turn_ms` (default 1100 ms); legacy `audio.silence_duration_ms` migrates automatically.
- Converse latency and stability improvements (streaming turn handling, end-of-turn tuning, early-listen gating).
- STT: optional GPU auto-detect (`stt.device: auto`).
- LLM: model health checks during Converse (30 s first-token timeout, empty response, stream stall); misbehaving models disabled for the session and re-enabled on next app start.
- Documentation: updated configuration reference, performance tuning, and LLM model health section.

## 0.3.8 - 2026-06-28

- Version alignment with AverVOX Pro 0.3.8 (no user-facing OSS changes in this release).

## 0.3.7 - 2026-06-27

- Add Quick Start User Guide (`QUICK_START-OSS.md`).
- Settings: add **About** tab (replaces separate About dialog); tray **About** opens Settings on About.
- Documentation: AverVOX OSS/Pro designations in README, DOCS, and Quick Start.
- Tests: fix GTK `gi` stubs in `test_main_reload.py`.

## 0.3.6 - 2026-06-26

- Version alignment with AverVOX Pro 0.3.6 (no user-facing OSS changes in this release).

## 0.3.5 - 2026-06-19

- API keys are masked in Settings (show/hide toggle).
- API keys are stored encrypted in `config.yaml` as `enc:...` values, bound to your machine.
- Legacy plaintext API keys still load until the next save.
