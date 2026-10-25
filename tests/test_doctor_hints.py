"""``avrvx --doctor`` fix hints for missing system binaries.

install.sh does not install pulseaudio-utils (parec), so the hints must point
at the package manager rather than telling the user to re-run install.sh.
"""

import avervox.doctor as doctor


def _which_without(*missing):
    def which(name):
        return None if name in missing else f"/usr/bin/{name}"
    return which


def test_missing_parec_system_binaries_hint(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", _which_without("parec"))
    result = doctor.check_system_binaries()
    assert result.status == doctor.FAIL
    assert "parec" in result.finding
    assert "sudo apt install" in result.hint
    assert "pulseaudio-utils" in result.hint
    assert "install.sh" not in result.hint


def test_missing_parec_microphone_hint(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", _which_without("parec"))
    result = doctor.check_microphone()
    assert result.status == doctor.FAIL
    assert "sudo apt install pulseaudio-utils" in result.hint
    assert "install.sh" not in result.hint
