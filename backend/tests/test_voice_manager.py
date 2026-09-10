"""Tests for voice manager cache behavior."""

import wave
from dataclasses import replace

from novatts.models import Dialogue
from novatts.registry.speakers import SpeakerRegistry
from novatts.tts.voice_manager import VoiceManager


class FakeBackend:
    """Deterministic backend recording the last requested voice."""

    def __init__(self):
        self.calls = []
        self.available = True

    def is_available(self):
        return self.available

    def list_voices(self):
        return ["default", "gpu1", "gpu2"]

    def synthesize(
        self, text, output_path, *, voice=None, instruct=None, emotion=None, params=None
    ):
        self.calls.append({"voice": voice, "text": text, "instruct": instruct})
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00" * 2205)
        return output_path


def make_ctx(tmp_path):
    backend = FakeBackend()
    registry = SpeakerRegistry(tmp_path / "speakers.json")
    mgr = VoiceManager(backend, registry, cache_dir=tmp_path / "cache")
    return backend, registry, mgr


def test_unknown_speaker_uses_fallback_voice(tmp_path):
    backend, _, mgr = make_ctx(tmp_path)
    mgr.synthesize(Dialogue(speaker="Nobody", text="Hello", source="api"))
    # Empty voice == model built-in default (no unknown name sent to engine).
    assert backend.calls[0]["voice"] == ""


def test_registered_speaker_voice_lookup(tmp_path):
    backend, registry, mgr = make_ctx(tmp_path)
    registry.register("Rick")
    registry.update("Rick", voice="gpu1")
    mgr.synthesize(Dialogue(speaker="Rick", text="Hello", source="api"))
    assert backend.calls[0]["voice"] == "gpu1"


def test_voice_override_wins(tmp_path):
    backend, registry, mgr = make_ctx(tmp_path)
    registry.register("Rick")
    registry.update("Rick", voice="gpu1")
    mgr.synthesize(Dialogue(speaker="Rick", text="Hello", source="api"), voice_override="gpu2")
    assert backend.calls[0]["voice"] == "gpu2"


def test_cache_hit_avoids_second_synthesis(tmp_path):
    backend, registry, mgr = make_ctx(tmp_path)
    d = Dialogue(speaker="Rick", text="Same line", source="api")
    mgr.synthesize(d)
    assert len(backend.calls) == 1
    mgr.synthesize(d)
    assert len(backend.calls) == 1  # cached


def test_same_text_different_voice_not_shared(tmp_path):
    backend, registry, mgr = make_ctx(tmp_path)
    registry.register("A")
    registry.register("B")
    registry.update("A", voice="gpu1")
    registry.update("B", voice="gpu2")

    da = Dialogue(speaker="A", text="Line")
    db = Dialogue(speaker="B", text="Line")
    pa = mgr.synthesize(da)
    pb = mgr.synthesize(db)

    assert pa != pb  # distinct voices -> distinct cached files
    assert len(backend.calls) == 2


def test_instruct_change_invalidates_cache(tmp_path):
    backend, registry, mgr = make_ctx(tmp_path)
    d = Dialogue(speaker="Rick", text="Hey", source="api")
    mgr.synthesize(d)
    mgr.synthesize(replace(d, instruct="whisper"))
    assert len(backend.calls) == 2


def test_voice_mapping_change_produces_fresh_audio(tmp_path):
    backend, registry, mgr = make_ctx(tmp_path)
    registry.register("Rick")
    d = Dialogue(speaker="Rick", text="Hello", source="api")

    registry.update("Rick", voice="gpu1")
    pa = mgr.synthesize(d)

    registry.update("Rick", voice="gpu2")
    pb = mgr.synthesize(d)

    assert pa != pb
    assert backend.calls[0]["voice"] == "gpu1"
    assert backend.calls[1]["voice"] == "gpu2"
