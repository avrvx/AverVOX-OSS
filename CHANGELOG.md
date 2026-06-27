# Changelog

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
