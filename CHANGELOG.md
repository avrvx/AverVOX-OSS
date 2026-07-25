# Changelog

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
