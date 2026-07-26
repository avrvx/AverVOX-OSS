"""The console script is `avervox.__main__:main`, so importing that module must
not do anything on its own. When it did, pip-installed avrvx ran every command
twice: two capability payloads on stdout (which no host could parse) and two
passes of synthesis for one request.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": SRC, "PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
    )


class TestImportIsSideEffectFree:
    def test_importing_main_runs_nothing(self):
        """What the console script does before it calls main() itself."""
        result = _run("-c", "import avervox.__main__")
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_importing_main_does_not_see_argv(self):
        """An unguarded call would pick up argv and act on it here."""
        result = _run("-c", "import avervox.__main__", "--capabilities")
        assert result.stdout == ""


class TestEntryPointRunsOnce:
    def test_console_script_path_emits_one_payload(self):
        """Exactly what `pip install avrvx` wires up."""
        result = _run(
            "-c",
            "import sys; sys.argv=['avrvx','--capabilities'];"
            "from avervox.__main__ import main; main()",
        )
        assert result.returncode == 0, result.stderr
        json.loads(result.stdout)  # raises "Extra data" on a doubled payload

    def test_module_path_emits_one_payload(self):
        """The `python -m avervox` path the launcher script uses."""
        result = _run("-m", "avervox", "--capabilities")
        assert result.returncode == 0, result.stderr
        json.loads(result.stdout)
