"""Bridge daemon protocol, socket permissions, and single-flight behaviour."""

import json
import os
import socket
import threading
from pathlib import Path

import numpy as np
import pytest

from avervox import bridge_server


def _stub_stream(text, **_kwargs):
    """One 40-sample frame per sentence, matching the real generator's shape."""
    from avervox.text import split_sentences

    text = text.strip()
    if not text:
        raise ValueError("No text to synthesize")
    for _ in split_sentences(text):
        yield np.zeros(40, dtype=np.int16), 22050


@pytest.fixture
def running_bridge(tmp_path, monkeypatch):
    """A daemon on a private socket, with the speech modules stubbed out."""
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))

    from avervox import stt, tts

    monkeypatch.setattr(tts, "preload", lambda *a, **k: None)
    monkeypatch.setattr(stt, "preload", lambda *a, **k: None)
    monkeypatch.setattr(
        tts, "synthesize_to_file", lambda text, out, **kw: Path(out)
    )
    monkeypatch.setattr(stt, "transcribe_file", lambda path: "stub transcript")
    monkeypatch.setattr(tts, "list_voices", lambda: [])
    monkeypatch.setattr(tts, "synthesize_stream", _stub_stream)

    ready = threading.Event()
    thread = threading.Thread(target=bridge_server.serve, args=(None,),
                              kwargs={"ready": ready}, daemon=True)
    thread.start()
    assert ready.wait(20), "daemon never signalled ready"

    yield bridge_server.socket_path()

    # serve() installs signal handlers only on the main thread, so shut down
    # by hand here.
    sock = bridge_server.socket_path()
    if sock.exists():
        sock.unlink()


def call(sock_path, **request) -> dict:
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(10)
    conn.connect(str(sock_path))
    try:
        stream = conn.makefile("rwb")
        stream.write((json.dumps(request) + "\n").encode())
        stream.flush()
        return json.loads(stream.readline())
    finally:
        conn.close()


class TestSocket:
    def test_only_the_owner_can_reach_it(self, running_bridge) -> None:
        assert oct(running_bridge.stat().st_mode & 0o777) == "0o600"
        assert oct(running_bridge.parent.stat().st_mode & 0o777) == "0o700"

    def test_is_running_tracks_the_daemon(self, running_bridge) -> None:
        assert bridge_server.is_running() is True

    def test_a_socket_with_nothing_behind_it_is_not_running(self, tmp_path) -> None:
        orphan = tmp_path / "bridge.sock"
        orphan.touch()
        assert bridge_server.is_running(orphan) is False

    def test_starting_twice_is_refused(self, running_bridge) -> None:
        with pytest.raises(OSError, match="already running"):
            bridge_server.serve()

    def test_a_stale_socket_is_cleared(self, tmp_path) -> None:
        stale = tmp_path / "bridge.sock"
        stale.touch()
        bridge_server._clear_stale_socket(stale)
        assert not stale.exists()


class TestProtocol:
    def test_ping(self, running_bridge) -> None:
        assert call(running_bridge, method="ping") == {"ok": True, "protocol": 1}

    def test_request_ids_come_back(self, running_bridge) -> None:
        assert call(running_bridge, method="ping", id="abc")["id"] == "abc"

    def test_capabilities(self, running_bridge) -> None:
        reply = call(running_bridge, method="capabilities")
        assert reply["ok"] and reply["edition"] and reply["version"]

    def test_unknown_method(self, running_bridge) -> None:
        reply = call(running_bridge, method="teleport")
        assert reply["code"] == "unknown_method"

    def test_malformed_json_does_not_kill_the_daemon(self, running_bridge) -> None:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(10)
        conn.connect(str(running_bridge))
        stream = conn.makefile("rwb")
        stream.write(b"{not json\n")
        stream.flush()
        assert json.loads(stream.readline())["code"] == "bad_json"

        # Same connection, valid request: the daemon is still there.
        stream.write(b'{"method": "ping"}\n')
        stream.flush()
        assert json.loads(stream.readline())["ok"] is True
        conn.close()

    def test_several_requests_share_one_connection(self, running_bridge, tmp_path) -> None:
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(10)
        conn.connect(str(running_bridge))
        stream = conn.makefile("rwb")
        for i in range(3):
            request = {"method": "synthesize", "text": "hi",
                       "output": str(tmp_path / f"{i}.wav"), "id": i}
            stream.write((json.dumps(request) + "\n").encode())
            stream.flush()
            assert json.loads(stream.readline())["id"] == i
        conn.close()


class TestSynthesize:
    def test_returns_the_written_path(self, running_bridge, tmp_path) -> None:
        out = tmp_path / "reply.wav"
        reply = call(running_bridge, method="synthesize", text="hello", output=str(out))
        assert reply["ok"] and reply["path"] == str(out)

    def test_empty_text_is_rejected(self, running_bridge, tmp_path) -> None:
        reply = call(running_bridge, method="synthesize", text="   ",
                     output=str(tmp_path / "o.wav"))
        assert reply["code"] == "empty_text"

    def test_missing_output_is_rejected(self, running_bridge) -> None:
        assert call(running_bridge, method="synthesize", text="hi")["code"] == "no_output"


def stream(sock_path, **request) -> list[tuple[dict, bytes]]:
    """Read a streaming synthesis to its end, returning every message and body."""
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(10)
    conn.connect(str(sock_path))
    try:
        io = conn.makefile("rwb")
        io.write((json.dumps({**request, "stream": True}) + "\n").encode())
        io.flush()
        messages = []
        while True:
            header = json.loads(io.readline())
            body = io.read(header["bytes"]) if header.get("bytes") else b""
            messages.append((header, body))
            if header.get("done") or not header.get("ok"):
                return messages
    finally:
        conn.close()


class TestStreamingSynthesis:
    def test_one_frame_per_sentence_then_done(self, running_bridge) -> None:
        messages = stream(running_bridge, method="synthesize", text="One. Two. Three.")

        *frames, (final, _) = messages
        assert [h["frame"] for h, _ in frames] == [0, 1, 2]
        assert final == {"ok": True, "done": True, "frames": 3}

    def test_a_frame_body_is_exactly_the_length_it_declares(self, running_bridge) -> None:
        (header, body), *_ = stream(running_bridge, method="synthesize", text="Hello.")

        assert header["bytes"] == len(body) == 80  # 40 int16 samples
        assert header["rate"] == 22050

    def test_no_output_path_is_needed(self, running_bridge) -> None:
        """Streaming skips the temp file the file-based path requires."""
        assert stream(running_bridge, method="synthesize", text="Hi.")[-1][0]["done"]

    def test_request_ids_come_back_on_every_message(self, running_bridge) -> None:
        messages = stream(running_bridge, method="synthesize", text="One. Two.", id=9)
        assert all(header["id"] == 9 for header, _ in messages)

    def test_empty_text_is_rejected(self, running_bridge) -> None:
        (header, _), = stream(running_bridge, method="synthesize", text="  ")
        assert header["code"] == "empty_text"

    def test_the_connection_stays_usable_afterwards(self, running_bridge) -> None:
        """A stream must not leave the reader mid-frame for the next request."""
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.settimeout(10)
        conn.connect(str(running_bridge))
        try:
            io = conn.makefile("rwb")
            io.write((json.dumps(
                {"method": "synthesize", "text": "One. Two.", "stream": True}
            ) + "\n").encode())
            io.flush()
            while True:
                header = json.loads(io.readline())
                if header.get("bytes"):
                    io.read(header["bytes"])
                if header.get("done"):
                    break
            io.write((json.dumps({"method": "ping"}) + "\n").encode())
            io.flush()
            assert json.loads(io.readline()) == {"ok": True, "protocol": 1}
        finally:
            conn.close()

    def test_a_second_stream_is_refused_while_one_runs(self, running_bridge) -> None:
        bridge_server._synth_lock.acquire()
        try:
            (header, _), = stream(running_bridge, method="synthesize", text="Hi.")
            assert header["code"] == "busy"
        finally:
            bridge_server._synth_lock.release()

    def test_the_lock_is_released_after_an_error(self, running_bridge) -> None:
        stream(running_bridge, method="synthesize", text="")
        assert stream(running_bridge, method="synthesize", text="Hi.")[-1][0]["done"]

    def test_a_second_synthesis_is_told_the_daemon_is_busy(
        self, running_bridge, tmp_path, monkeypatch
    ) -> None:
        """Single-flight: the stop flag behind cancel is module-global."""
        bridge_server._synth_lock.acquire()
        try:
            reply = call(running_bridge, method="synthesize", text="hello",
                         output=str(tmp_path / "o.wav"))
            assert reply["code"] == "busy"
        finally:
            bridge_server._synth_lock.release()


class TestTranscribe:
    def test_returns_the_transcript(self, running_bridge) -> None:
        reply = call(running_bridge, method="transcribe", path="/tmp/clip.wav")
        assert reply["ok"] and reply["transcript"] == "stub transcript"

    def test_missing_path_is_rejected(self, running_bridge) -> None:
        assert call(running_bridge, method="transcribe")["code"] == "no_path"


class TestSocketPath:
    def test_follows_xdg_runtime_dir(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        assert bridge_server.socket_path() == tmp_path / "avervox" / "bridge.sock"

    def test_falls_back_to_a_per_user_tmp_dir(self, monkeypatch) -> None:
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        assert str(bridge_server.socket_path()).startswith(f"/tmp/avervox-{os.getuid()}")
