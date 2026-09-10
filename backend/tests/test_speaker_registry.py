"""Tests for the speaker registry."""

import json

import pytest

from novatts.registry.speakers import SpeakerRegistry


@pytest.fixture()
def registry(tmp_path):
    return SpeakerRegistry(tmp_path / "speakers.json", auto_save_interval=0.0)


def test_default_has_fallback(registry):
    assert registry.fallback_speaker in registry.names()
    assert registry.names() == ["Narrator"]


def test_unknown_speaker_falls_back(registry):
    s = registry.get("Nobody")
    assert s.name == "Narrator"
    # Empty voice = model built-in default, no unknown voice name.
    assert registry.lookup_voice("Calcifer") == ""


def test_none_speaker_falls_back(registry):
    assert registry.get(None).name == "Narrator"


def test_register_then_get(registry):
    registry.register("Rick")
    assert registry.get("Rick").name == "Rick"
    assert "Rick" in registry.names()


def test_register_is_idempotent(registry):
    a = registry.register("Rick")
    b = registry.register("Rick")
    assert a is b


def test_update_existing(registry):
    registry.register("Rick")
    updated = registry.update("Rick", voice="gpu1")
    assert updated is not None
    assert registry.get("Rick").voice == "gpu1"


def test_update_unknown_returns_none(registry):
    assert registry.update("Ghost", voice="x") is None


def test_remove(registry):
    registry.register("Rick")
    assert registry.remove("Rick") is True
    assert "Rick" not in registry.names()
    assert registry.remove("Rick") is False


def test_persists_and_reloads(tmp_path):
    path = tmp_path / "speakers.json"
    reg = SpeakerRegistry(path, auto_save_interval=0.0)
    reg.register("Rick")
    reg.update("Rick", voice="gpu2")
    reg.save()

    loaded = SpeakerRegistry(path, auto_save_interval=0.0)
    assert loaded.get("Rick").voice == "gpu2"


def test_autosave_flush(tmp_path):
    path = tmp_path / "speakers.json"
    reg = SpeakerRegistry(path, auto_save_interval=0.0)
    reg.register("Rick")
    reg.maybe_autosave()
    assert json.loads(path.read_text(encoding="utf-8"))["speakers"]["Rick"]


def test_rejects_empty_name(registry):
    with pytest.raises(ValueError):
        registry.register("   ")
