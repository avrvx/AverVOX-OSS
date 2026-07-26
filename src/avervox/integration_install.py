"""``avrvx --install-integration HOST`` — wire a host to AverVOX, then prove it.

Two jobs, and the second is the one that saves a support round-trip: writing a
config snippet is easy to get right, but "I pasted the snippet and nothing
happens" is almost always something else — avrvx not on PATH, no voice
installed, a model that never downloaded. So this synthesizes real audio
afterwards and reports what it found.

An existing host config is never modified. Editing someone's YAML or JSON5 in
place risks losing comments and formatting for a merge they can do in a few
seconds, so a snippet is written alongside instead.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2

HERMES_SNIPPET = """\
# AverVOX speech providers for Hermes Agent.
# Written by `avrvx --install-integration hermes`.
#
# Verify with: avrvx --capabilities

tts:
  provider: avervox
  providers:
    avervox:
      type: command
      command: "avrvx --synthesize --text-file {input_path} --output {output_path}"
      output_format: wav
      voice_compatible: true
      timeout: 180

stt:
  provider: avervox
  providers:
    avervox:
      type: command
      command: "avrvx --transcribe {input_path} > {output_path}"
      format: txt
      timeout: 300
"""

OPENCLAW_SNIPPET = """\
// AverVOX speech provider for OpenClaw.
// Written by `avrvx --install-integration openclaw`.
//
// tts-local-cli has no file placeholder for the text, so reply text is visible
// in the process list while synthesis runs. On a shared machine install
// @avervox/openclaw-plugin instead, which pipes text over stdin.
{
  tts: {
    auto: "always",
    provider: "tts-local-cli",
    providers: {
      "tts-local-cli": {
        command: "avrvx",
        args: ["--synthesize", "--text", "{{Text}}", "--output", "{{OutputPath}}"],
        outputFormat: "wav",
        timeoutMs: 180000,
      },
    },
  },
}
"""


def _say(message: str = "") -> None:
    print(message, flush=True)


def _err(message: str) -> None:
    # Flush first: stdout is block-buffered when piped to a log, and without
    # this the errors surface above the steps they refer to.
    sys.stdout.flush()
    print(message, file=sys.stderr, flush=True)


@dataclass(frozen=True)
class Host:
    name: str
    config: Path
    snippet_name: str
    snippet: str
    plugin_hint: str


def _hosts() -> dict[str, Host]:
    home = Path.home()
    return {
        "hermes": Host(
            name="Hermes Agent",
            config=home / ".hermes" / "config.yaml",
            snippet_name="avervox.yaml",
            snippet=HERMES_SNIPPET,
            plugin_hint="pip install avervox-hermes",
        ),
        "openclaw": Host(
            name="OpenClaw",
            config=home / ".openclaw" / "openclaw.json",
            snippet_name="avervox.json5",
            snippet=OPENCLAW_SNIPPET,
            plugin_hint="clawhub package install @avervox/openclaw-plugin",
        ),
    }


HOST_CHOICES = sorted(_hosts())


def _write_config(host: Host) -> bool:
    """Place the snippet. False means the caller must merge it by hand."""
    host.config.parent.mkdir(parents=True, exist_ok=True)

    if not host.config.exists():
        host.config.write_text(host.snippet, encoding="utf-8")
        _say(f"wrote {host.config}")
        return True

    existing = host.config.read_text(encoding="utf-8", errors="replace")
    if "avervox" in existing.lower():
        _say(f"{host.config} already mentions avervox — left alone")
        return True

    target = host.config.parent / host.snippet_name
    target.write_text(host.snippet, encoding="utf-8")
    _say(f"{host.config} already exists and was not modified")
    _say(f"wrote {target} — merge its contents into {host.config.name}")
    return False


def _verify() -> bool:
    """Synthesize for real. Anything less does not prove the host will work."""
    avrvx = shutil.which("avrvx")
    if not avrvx:
        _err("avrvx is not on PATH — hosts spawn it by name and will not find it")
        return False
    _say(f"avrvx: {avrvx}")

    from . import __edition__ as edition, __version__

    _say(f"edition: {edition} {__version__}")

    try:
        from .bridge_server import is_running

        _say(f"warm bridge: {'running' if is_running() else 'not running'}")
    except Exception:
        pass

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "verify.wav"
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [avrvx, "--synthesize", "--text", "-", "--output", str(out)],
                input="AverVOX is installed and working.",
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            _err("synthesis timed out after 5 minutes")
            return False
        elapsed = time.monotonic() - started

        if proc.returncode != 0 or not out.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            _err(f"synthesis failed: {detail}")
            return False

        _say(f"synthesized {out.stat().st_size} bytes in {elapsed:.1f}s")
    return True


def install(host_key: str) -> int:
    host = _hosts().get(host_key)
    if host is None:
        _err(f"unknown host '{host_key}'; choose from {', '.join(HOST_CHOICES)}")
        return EXIT_USAGE

    _say(f"Configuring {host.name}\n")
    merged = _write_config(host)

    _say()
    ok = _verify()

    _say()
    if not ok:
        _err(
            f"{host.name} config is in place, but AverVOX itself is not "
            f"working yet — fix the error above first."
        )
        return EXIT_FAILED

    if merged:
        _say(f"{host.name} is ready. Restart it to pick up the change.")
    else:
        _say(f"AverVOX works. Merge the snippet above, then restart {host.name}.")
    _say(f"For voice selection and streaming, install the plugin: {host.plugin_hint}")
    return EXIT_OK
