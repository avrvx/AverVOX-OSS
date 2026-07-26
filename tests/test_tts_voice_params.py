"""Backend caching and per-request voice/speed overrides."""

import numpy as np
import pytest

import avervox.tts as tts_mod


class FakeBackend:
    """Records what each synthesize call asked for."""

    sample_rate = 22050

    def __init__(self, label):
        self.label = label
        self.calls = []

    def synthesize(self, text, *, speed=1.0):
        self.calls.append({"text": text, "speed": speed})
        yield np.zeros(64, dtype=np.float32)


@pytest.fixture
def loads(monkeypatch):
    """Replace the Piper backend with a fake and record every construction."""
    built = []

    def fake_piper(voice_model):
        built.append(voice_model)
        return FakeBackend(voice_model)

    monkeypatch.setattr(tts_mod, "_PiperBackend", fake_piper)
    tts_mod.clear_cache()
    yield built
    tts_mod.clear_cache()


class TestBackendCache:
    def test_the_same_voice_loads_once(self, loads, tmp_path):
        tts_mod.configure(voice_model="/voices/a.onnx")
        for i in range(4):
            tts_mod.synthesize_to_file("hello", tmp_path / f"{i}.wav")

        assert loads == ["/voices/a.onnx"]

    def test_switching_voices_keeps_both_loaded(self, loads, tmp_path):
        tts_mod.configure(voice_model="/voices/a.onnx")
        tts_mod.synthesize_to_file("hello", tmp_path / "1.wav")
        tts_mod.synthesize_to_file("hello", tmp_path / "2.wav", voice="/voices/b.onnx")
        tts_mod.synthesize_to_file("hello", tmp_path / "3.wav", voice="/voices/a.onnx")

        assert loads == ["/voices/a.onnx", "/voices/b.onnx"]

    def test_least_recently_used_backends_are_evicted(self, loads, tmp_path):
        tts_mod.configure(voice_model="/voices/a.onnx")
        for name in "abcd":
            tts_mod.synthesize_to_file("hi", tmp_path / f"{name}.wav",
                                       voice=f"/voices/{name}.onnx")

        assert len(tts_mod._backends) == tts_mod._BACKEND_CACHE_SIZE
        assert "/voices/a.onnx" not in tts_mod._backends

    def test_configure_does_not_throw_away_loaded_models(self, loads, tmp_path):
        tts_mod.configure(voice_model="/voices/a.onnx")
        tts_mod.synthesize_to_file("hello", tmp_path / "1.wav")
        tts_mod.configure(voice_model="/voices/a.onnx", speed=1.5)
        tts_mod.synthesize_to_file("hello", tmp_path / "2.wav")

        assert loads == ["/voices/a.onnx"]

    def test_clear_cache_forces_a_reload(self, loads, tmp_path):
        tts_mod.configure(voice_model="/voices/a.onnx")
        tts_mod.synthesize_to_file("hello", tmp_path / "1.wav")
        tts_mod.clear_cache()
        tts_mod.synthesize_to_file("hello", tmp_path / "2.wav")

        assert len(loads) == 2


class TestResolution:
    def test_defaults_come_from_configure(self, loads):
        tts_mod.configure(voice_model="/voices/a.onnx", speed=1.25)
        assert tts_mod._resolve() == ("/voices/a.onnx", 1.25)

    def test_per_request_values_win(self, loads):
        tts_mod.configure(voice_model="/voices/a.onnx", speed=1.25)
        assert tts_mod._resolve(voice="/voices/b.onnx", speed=0.9) == (
            "/voices/b.onnx",
            0.9,
        )


class TestCancellation:
    def test_stop_interrupts_synthesis_mid_stream(self, monkeypatch, tmp_path):
        """Without this, a long passage can only be interrupted with SIGKILL."""

        class SlowBackend:
            sample_rate = 22050

            def synthesize(self, _text, **_kwargs):
                for _ in range(100):
                    yield np.zeros(64, dtype=np.float32)
                    tts_mod.stop()  # as if the user hit stop after chunk one

        monkeypatch.setattr(tts_mod, "_PiperBackend", lambda _v: SlowBackend())
        tts_mod.clear_cache()
        tts_mod.configure(voice_model="/voices/a.onnx")

        with pytest.raises(tts_mod.Cancelled):
            tts_mod.synthesize_to_file("hello", tmp_path / "o.wav")
        assert not (tmp_path / "o.wav").exists()
        tts_mod.clear_cache()

    def test_a_stale_stop_does_not_cancel_the_next_request(self, loads, tmp_path):
        tts_mod.configure(voice_model="/voices/a.onnx")
        tts_mod.stop()

        tts_mod.synthesize_to_file("hello", tmp_path / "o.wav")
        assert (tmp_path / "o.wav").exists()

    def test_is_stopped_reports_the_flag(self, loads):
        tts_mod._stop_event.clear()
        assert tts_mod.is_stopped() is False
        tts_mod.stop()
        assert tts_mod.is_stopped() is True
        tts_mod._stop_event.clear()


class TestStreaming:
    def test_yields_one_group_of_chunks_per_sentence(self, loads):
        tts_mod.configure(voice_model="/voices/a.onnx")
        frames = list(tts_mod.synthesize_stream("One. Two. Three."))

        assert len(frames) == 3
        backend = tts_mod._backends["/voices/a.onnx"]
        assert [c["text"] for c in backend.calls] == ["One.", "Two.", "Three."]

    def test_frames_carry_int16_pcm_and_the_sample_rate(self, loads):
        tts_mod.configure(voice_model="/voices/a.onnx")
        pcm, rate = next(iter(tts_mod.synthesize_stream("Hello.")))

        assert pcm.dtype == np.int16
        assert rate == 22050

    def test_empty_text_is_rejected_before_any_work(self, loads):
        tts_mod.configure(voice_model="/voices/a.onnx")
        with pytest.raises(ValueError):
            list(tts_mod.synthesize_stream("   "))

    def test_a_backend_that_produces_nothing_raises(self, monkeypatch):
        class SilentBackend:
            sample_rate = 22050

            def synthesize(self, _text, **_kwargs):
                return iter(())

        monkeypatch.setattr(tts_mod, "_PiperBackend", lambda _v: SilentBackend())
        tts_mod.clear_cache()
        tts_mod.configure(voice_model="/voices/a.onnx")

        with pytest.raises(RuntimeError, match="produced no audio"):
            list(tts_mod.synthesize_stream("Hello."))
        tts_mod.clear_cache()

    def test_stop_interrupts_the_stream(self, loads):
        tts_mod.configure(voice_model="/voices/a.onnx")
        stream = tts_mod.synthesize_stream("One. Two. Three.")

        next(stream)
        tts_mod.stop()
        with pytest.raises(tts_mod.Cancelled):
            next(stream)
        tts_mod._stop_event.clear()


class TestOverridesReachTheBackend:
    def test_speed_is_passed_through(self, loads, tmp_path):
        tts_mod.configure(voice_model="/voices/a.onnx")
        tts_mod.synthesize_to_file("hello", tmp_path / "o.wav", speed=1.4)

        backend = tts_mod._backends["/voices/a.onnx"]
        assert backend.calls == [{"text": "hello", "speed": 1.4}]
