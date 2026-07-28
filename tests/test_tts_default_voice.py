"""ensure_default_voice_model(): first-run TTS auto-configuration.

install.sh (pip/source installs) has always downloaded a default Piper voice
and written it into config.yaml; the AppImage had no equivalent step, so a
fresh AppImage install left tts.voice_model empty forever. These tests cover
the startup helper that closes that gap — see tts.py's docstring for the
full story.
"""

from types import SimpleNamespace

import avervox.tts as tts_mod


class FakeTTSConfig:
    def __init__(self, voice_model=""):
        self.voice_model = voice_model


def make_cfg(**kwargs):
    return SimpleNamespace(tts=FakeTTSConfig(**kwargs))


def test_noop_when_voice_model_already_configured(tmp_path):
    existing = tmp_path / "my-voice.onnx"
    existing.write_bytes(b"fake")
    cfg = make_cfg(voice_model=str(existing))

    changed = tts_mod.ensure_default_voice_model(cfg)

    assert changed is False
    assert cfg.tts.voice_model == str(existing)


def test_redownloads_if_configured_path_no_longer_exists(monkeypatch, tmp_path):
    """A voice_model pointing at a since-deleted file should be treated the
    same as unconfigured, not silently left broken."""
    monkeypatch.setattr(tts_mod, "_piper_voices_dir", lambda: tmp_path)
    cfg = make_cfg(voice_model=str(tmp_path / "gone.onnx"))

    downloaded = []
    monkeypatch.setattr(
        tts_mod, "_download_to",
        lambda url, dest: (downloaded.append((url, dest)), dest.write_bytes(b"x"))[-1],
    )

    changed = tts_mod.ensure_default_voice_model(cfg)

    assert changed is True
    assert len(downloaded) == 2  # voice .onnx + its .onnx.json sidecar
    assert cfg.tts.voice_model == str(tmp_path / tts_mod._DEFAULT_PIPER_VOICE_NAME)


def test_adopts_existing_local_voice_without_downloading(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_mod, "_piper_voices_dir", lambda: tmp_path)
    local_voice = tmp_path / "en_US-amy-medium.onnx"
    local_voice.write_bytes(b"fake")
    cfg = make_cfg(voice_model="")

    def fail_download(url, dest):
        raise AssertionError("should not download when a local voice exists")

    monkeypatch.setattr(tts_mod, "_download_to", fail_download)

    changed = tts_mod.ensure_default_voice_model(cfg)

    assert changed is True
    assert cfg.tts.voice_model == str(local_voice)


def test_downloads_default_voice_when_nothing_local(monkeypatch, tmp_path):
    monkeypatch.setattr(tts_mod, "_piper_voices_dir", lambda: tmp_path / "voices")

    downloaded = []

    def fake_download(url, dest):
        downloaded.append(url)
        dest.write_bytes(b"x")

    monkeypatch.setattr(tts_mod, "_download_to", fake_download)
    cfg = make_cfg(voice_model="")

    changed = tts_mod.ensure_default_voice_model(cfg)

    assert changed is True
    assert cfg.tts.voice_model == str(
        tmp_path / "voices" / tts_mod._DEFAULT_PIPER_VOICE_NAME
    )
    assert tts_mod._DEFAULT_PIPER_VOICE_URL in downloaded
    assert tts_mod._DEFAULT_PIPER_CONFIG_URL in downloaded


def test_download_failure_leaves_config_untouched_and_cleans_up(monkeypatch, tmp_path):
    voices_dir = tmp_path / "voices"
    monkeypatch.setattr(tts_mod, "_piper_voices_dir", lambda: voices_dir)

    def flaky_download(url, dest):
        dest.write_bytes(b"partial")  # simulate a partial write before failure
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(tts_mod, "_download_to", flaky_download)
    cfg = make_cfg(voice_model="")

    changed = tts_mod.ensure_default_voice_model(cfg)

    assert changed is False
    assert cfg.tts.voice_model == ""
    # No leftover partial file from the failed attempt.
    assert not (voices_dir / tts_mod._DEFAULT_PIPER_VOICE_NAME).exists()


def test_missing_tts_config_is_a_noop():
    cfg = SimpleNamespace()  # no .tts attribute at all

    assert tts_mod.ensure_default_voice_model(cfg) is False
