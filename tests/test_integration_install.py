"""`avrvx --install-integration` writes host config and verifies synthesis.

The property worth guarding hardest is that an existing host config is never
modified — losing someone's OpenClaw settings to a speech installer would be a
far worse bug than failing to configure anything at all.
"""

from __future__ import annotations

import pytest

from avervox import integration_install as ii


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(ii.Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


@pytest.fixture
def synthesis_works(monkeypatch):
    """Stand in for a healthy install so tests exercise config handling."""
    monkeypatch.setattr(ii, "_verify", lambda: True)


class TestHosts:
    def test_both_hosts_are_offered(self):
        assert ii.HOST_CHOICES == ["hermes", "openclaw"]

    def test_unknown_host_is_a_usage_error(self, capsys):
        assert ii.install("nope") == ii.EXIT_USAGE
        assert "hermes, openclaw" in capsys.readouterr().err

    def test_nothing_is_written_for_an_unknown_host(self, home):
        ii.install("nope")
        assert list(home.iterdir()) == []


class TestFreshInstall:
    def test_writes_the_host_config(self, home, synthesis_works):
        assert ii.install("hermes") == ii.EXIT_OK
        assert (home / ".hermes" / "config.yaml").exists()

    def test_written_config_selects_avervox(self, home, synthesis_works):
        ii.install("hermes")
        text = (home / ".hermes" / "config.yaml").read_text()
        assert "provider: avervox" in text

    def test_openclaw_goes_to_its_own_path(self, home, synthesis_works):
        ii.install("openclaw")
        assert (home / ".openclaw" / "openclaw.json").exists()
        assert not (home / ".hermes").exists()


class TestExistingConfig:
    @pytest.fixture
    def existing(self, home):
        config = home / ".openclaw" / "openclaw.json"
        config.parent.mkdir(parents=True)
        config.write_text('{ agent: { name: "mine" } }\n')
        return config

    def test_the_users_file_is_left_byte_for_byte(
        self, existing, synthesis_works
    ):
        before = existing.read_bytes()
        ii.install("openclaw")
        assert existing.read_bytes() == before

    def test_the_snippet_lands_beside_it(self, existing, synthesis_works):
        ii.install("openclaw")
        snippet = existing.parent / "avervox.json5"
        assert "tts-local-cli" in snippet.read_text()

    def test_it_says_the_merge_is_manual(
        self, existing, synthesis_works, capsys
    ):
        ii.install("openclaw")
        assert "was not modified" in capsys.readouterr().out

    def test_a_config_already_mentioning_avervox_is_left_alone(
        self, existing, synthesis_works, capsys
    ):
        existing.write_text('{ tts: { provider: "avervox" } }\n')
        ii.install("openclaw")
        assert not (existing.parent / "avervox.json5").exists()
        assert "left alone" in capsys.readouterr().out


class TestVerification:
    def test_a_broken_install_fails_even_though_config_was_written(
        self, home, monkeypatch
    ):
        monkeypatch.setattr(ii, "_verify", lambda: False)
        assert ii.install("hermes") == ii.EXIT_FAILED
        assert (home / ".hermes" / "config.yaml").exists()

    def test_missing_avrvx_is_reported_not_raised(self, monkeypatch, capsys):
        monkeypatch.setattr(ii.shutil, "which", lambda _: None)
        assert ii._verify() is False
        assert "not on PATH" in capsys.readouterr().err

    def test_a_nonzero_exit_surfaces_the_stderr(self, monkeypatch, capsys):
        monkeypatch.setattr(ii.shutil, "which", lambda _: "/usr/bin/avrvx")
        monkeypatch.setattr(
            ii.subprocess,
            "run",
            lambda *a, **kw: _Completed(1, "no voice installed"),
        )
        assert ii._verify() is False
        assert "no voice installed" in capsys.readouterr().err

    def test_it_synthesizes_rather_than_only_probing(self, monkeypatch):
        """A capability probe passes on an install that cannot make audio."""
        seen = {}
        monkeypatch.setattr(ii.shutil, "which", lambda _: "/usr/bin/avrvx")

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            return _Completed(1, "stopped before writing")

        monkeypatch.setattr(ii.subprocess, "run", fake_run)
        ii._verify()
        assert "--synthesize" in seen["argv"]


class _Completed:
    def __init__(self, returncode, stderr):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""
