# Changelog

## 0.5.0 - 2026-07-25

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
