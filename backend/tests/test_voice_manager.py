"""Tests for voice manager synthesis and cache behavior."""

import wave
from dataclasses import replace

from novatts.config import settings
from novatts.models import Dialogue
from novatts.registry.speakers import SpeakerRegistry
from novatts.tts.voice_manager import VoiceManager, default_voice_for_new_speaker


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
        self.calls.append(
            {"voice": voice, "text": text, "instruct": instruct, "params": params}
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00" * 2205)
        return output_path


def make_ctx(tmp_path, *, cache_enabled=False):
    backend = FakeBackend()
    registry = SpeakerRegistry(tmp_path / "speakers.json")
    mgr = VoiceManager(
        backend, registry, cache_dir=tmp_path / "cache", cache_enabled=cache_enabled
    )
    return backend, registry, mgr


def cached_ctx(tmp_path):
    return make_ctx(tmp_path, cache_enabled=True)


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
    backend, registry, mgr = cached_ctx(tmp_path)
    d = Dialogue(speaker="Rick", text="Same line", source="api")
    mgr.synthesize(d)
    assert len(backend.calls) == 1
    mgr.synthesize(d)
    assert len(backend.calls) == 1  # cached


def test_cache_off_resynthesizes_every_time(tmp_path):
    backend, _, mgr = make_ctx(tmp_path)
    assert mgr.cache_enabled is False
    d = Dialogue(speaker="Rick", text="Same line", source="api")
    pa = mgr.synthesize(d)
    pb = mgr.synthesize(d)
    assert len(backend.calls) == 2
    assert pa != pb  # nothing is deduplicated any more


def test_cache_off_never_reports_a_hit(tmp_path):
    _, _, mgr = make_ctx(tmp_path)
    mgr.synthesize(Dialogue(speaker="Rick", text="Same line", source="api"))
    assert mgr.is_cached(Dialogue(speaker="Rick", text="Same line", source="api")) is False


def test_cache_on_reports_a_hit(tmp_path):
    _, _, mgr = cached_ctx(tmp_path)
    d = Dialogue(speaker="Rick", text="Same line", source="api")
    assert mgr.is_cached(d) is False
    mgr.synthesize(d)
    assert mgr.is_cached(d) is True


def test_release_deletes_only_its_own_throwaway_files(tmp_path):
    backend, _, mgr = make_ctx(tmp_path)
    mine = mgr.synthesize(Dialogue(speaker="Rick", text="Mine", source="api"))
    assert mine.exists()
    mgr.release(mine)
    assert not mine.exists()

    # An emotion sound or a cached take is none of its business.
    keeper = mgr.cache_dir / "breathing_heavily.wav"
    keeper.write_bytes(b"RIFF")
    mgr.release(keeper)
    assert keeper.exists()
    mgr.release(keeper)
    assert keeper.exists()


def test_release_is_harmless_on_unknown_or_missing_paths(tmp_path):
    _, _, mgr = make_ctx(tmp_path)
    mgr.release(None)
    mgr.release(mgr.cache_dir / "never-existed.wav")
    mgr.clear_cache()  # and a sweep must not choke either


def test_clear_cache_removes_throwaway_files_too(tmp_path):
    _, _, mgr = make_ctx(tmp_path)
    mgr.synthesize(Dialogue(speaker="Rick", text="One", source="api"))
    mgr.synthesize(Dialogue(speaker="Rick", text="Two", source="api"))
    assert len(list(mgr.cache_dir.iterdir())) == 2
    mgr.clear_cache()
    assert len(list(mgr.cache_dir.iterdir())) == 0


def test_sampling_params_are_always_sent(tmp_path):
    backend, _, mgr = make_ctx(tmp_path)
    mgr.synthesize(Dialogue(speaker="Rick", text="Yeah.", source="api"))
    params = backend.calls[0]["params"]
    # Omitted, the server samples on a fresh random seed, which is how a line
    # can trail off past its full stop one time and not the next.
    assert params["seed"] == settings.qwen_seed
    assert params["temperature"] == settings.qwen_temperature
    assert params["top_p"] == settings.qwen_top_p
    assert params["top_k"] == settings.qwen_top_k
    assert params["repetition_penalty"] == settings.qwen_repetition_penalty


def test_same_text_different_voice_not_shared(tmp_path):
    backend, registry, mgr = cached_ctx(tmp_path)
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
    backend, registry, mgr = cached_ctx(tmp_path)
    d = Dialogue(speaker="Rick", text="Hey", source="api")
    mgr.synthesize(d)
    mgr.synthesize(replace(d, instruct="whisper"))
    assert len(backend.calls) == 2


def test_voice_mapping_change_produces_fresh_audio(tmp_path):
    backend, registry, mgr = cached_ctx(tmp_path)
    registry.register("Rick")
    d = Dialogue(speaker="Rick", text="Hello", source="api")

    registry.update("Rick", voice="gpu1")
    pa = mgr.synthesize(d)

    registry.update("Rick", voice="gpu2")
    pb = mgr.synthesize(d)

    assert pa != pb
    assert backend.calls[0]["voice"] == "gpu1"
    assert backend.calls[1]["voice"] == "gpu2"


def test_clear_cache_removes_all_files(tmp_path):
    backend, registry, mgr = cached_ctx(tmp_path)
    mgr.synthesize(Dialogue(speaker="Rick", text="Hello", source="api"))
    mgr.synthesize(Dialogue(speaker="Rick", text="Another", source="api"))
    assert len(list(mgr.cache_dir.iterdir())) == 2

    mgr.clear_cache()

    assert len(list(mgr.cache_dir.iterdir())) == 0
    # Cache hit no longer applies: synthesis runs again.
    mgr.synthesize(Dialogue(speaker="Rick", text="Hello", source="api"))
    assert len(backend.calls) == 3


def test_clear_cache_absent_dir_is_noop(tmp_path):
    backend, registry, mgr = cached_ctx(tmp_path)
    # Cache dir created on construct; drop it to emulate "nothing cached".
    import shutil

    shutil.rmtree(mgr.cache_dir, ignore_errors=True)
    mgr.clear_cache()  # must not raise
    assert not mgr.cache_dir.exists()


def test_default_voice_prefers_female():
    assert default_voice_for_new_speaker(["M-Boris", "Anna", "M-Carl", "Zoe"]) == "Anna"


def test_default_voice_skips_m_prefix_case_insensitive():
    assert default_voice_for_new_speaker(["Eva", "m-boris", "M_Carl"]) == "Eva"


def test_default_voice_all_male_falls_back_to_first():
    assert default_voice_for_new_speaker(["M-Carl", "M-Boris"]) == "M-Boris"


def test_default_voice_empty_when_engine_offline():
    assert default_voice_for_new_speaker([]) == ""


def test_default_voice_prefers_unused():
    assert default_voice_for_new_speaker(["Anna", "Zoe", "M-Boris"], {"Anna"}) == "Zoe"


def test_default_voice_unused_male_over_used_female():
    assert default_voice_for_new_speaker(["Anna", "M-Boris"], {"Anna"}) == "M-Boris"


def test_default_voice_all_used_falls_back_to_female():
    assert default_voice_for_new_speaker(["Zoe", "Anna"], {"Anna", "Zoe"}) == "Anna"


def test_default_voice_ignores_empty_used():
    assert default_voice_for_new_speaker(["M-Boris", "Anna"], set()) == "Anna"
