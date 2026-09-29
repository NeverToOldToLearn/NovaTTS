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


def test_update_stores_the_instruct(registry):
    """G5.5: ``instruct`` was accepted by ``update`` and then dropped.

    The parameter was in the signature and nothing assigned it, so any
    caller that set a voice instruction got no error and no stored value.

    Note what this test does *not* cover, because I got it wrong first: I
    originally wrote in this docstring that ``PATCH /speakers/{name}``
    forwarded ``instruct`` and therefore the endpoint reported success while
    storing nothing. The endpoint never forwarded it at all -- it forwarded
    only ``voice``, and ``SpeakerPatchBody`` did not even have the field. I
    had read a ``grep`` hit on ``instruct=body.instruct`` as being the
    speaker PATCH when it was ``/speak``. Two broken layers, not one.

    Asserted on the stored value, not the returned one: ``update`` returns
    the same instance it just failed to write, so a test checking only the
    return value would have passed against the broken code.
    """
    registry.register("Rick")
    registry.update("Rick", instruct="whisper, very slowly")
    assert registry.get("Rick").instruct == "whisper, very slowly"


def test_update_instruct_survives_a_save(tmp_path):
    """The user-visible half of G5.5: the value has to reach the file too.

    Without this, a fix that only writes the attribute in memory would still
    lose the instruction on the next restart, and the GUI would look like it
    had saved.
    """
    path = tmp_path / "speakers.json"
    reg = SpeakerRegistry(path, auto_save_interval=0.0)
    reg.register("Rick")
    reg.update("Rick", instruct="whisper")
    reg.save()

    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["speakers"]["Rick"]["instruct"] == "whisper"


def test_load_restores_the_instruct_and_emotion(tmp_path):
    """The other direction, and the one that was actually broken.

    ``_load()`` built ``Speaker(name=..., voice=...)`` and dropped the other
    two fields. So the value reached the file, and came back empty: after a
    restart the instruction was gone and ``GET /speakers`` reported ``""`` for
    a file that plainly said otherwise.

    The file is written by hand here on purpose. Going through ``update()`` +
    ``save()`` to produce the input would mean one broken direction could mask
    the other -- the save test above and this one would then pass or fail
    together and stop telling them apart.
    """
    path = tmp_path / "speakers.json"
    path.write_text(
        json.dumps(
            {
                "versions": 1,
                "speakers": {
                    "Rick": {
                        "name": "Rick",
                        "voice": "gpu1",
                        "instruct": "whisper, very slowly",
                        "emotion": "calm",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    reg = SpeakerRegistry(path, auto_save_interval=0.0)

    rick = reg.get("Rick")
    assert rick.voice == "gpu1"
    assert rick.instruct == "whisper, very slowly"
    assert rick.emotion == "calm"


def test_a_saved_speaker_survives_a_restart(tmp_path):
    """The whole round trip, which is the only version a user ever experiences.

    The test above pins each direction separately; this one pins the pair,
    because the reported bug was never "the file is wrong" or "the load is
    wrong" but "I set it, it looked saved, and after a restart it was gone".
    """
    path = tmp_path / "speakers.json"
    first = SpeakerRegistry(path, auto_save_interval=0.0)
    first.register("Rick")
    first.update("Rick", voice="gpu1", instruct="whisper", emotion="calm")
    first.save()

    second = SpeakerRegistry(path, auto_save_interval=0.0)

    rick = second.get("Rick")
    assert (rick.voice, rick.instruct, rick.emotion) == ("gpu1", "whisper", "calm")


def test_load_defaults_the_fields_an_old_file_omits(tmp_path):
    """Files written before these fields existed must still load.

    Two reasons this matters: ``SpeakerRegistry`` also loads hand-edited
    files, and an old file has no ``instruct`` key at all. Without a default,
    adding the fields to ``_load()`` would have been a breaking change.
    """
    path = tmp_path / "speakers.json"
    path.write_text(
        json.dumps({"versions": 1, "speakers": {"Rick": {"name": "Rick", "voice": "gpu1"}}}),
        encoding="utf-8",
    )

    rick = SpeakerRegistry(path, auto_save_interval=0.0).get("Rick")

    assert rick.instruct == ""
    assert rick.emotion == "neutral"


def test_load_tolerates_a_null_in_a_hand_edited_file(tmp_path):
    """``null`` must not put a ``None`` where the dataclass promises a ``str``.

    Someone editing the JSON by hand writes ``"instruct": null`` for "no
    instruction" far more often than they write ``""``. Without the ``or`` in
    ``_load()`` that ``None`` travels straight into the cache path and the
    model call, and fails there instead of here.
    """
    path = tmp_path / "speakers.json"
    path.write_text(
        json.dumps(
            {
                "versions": 1,
                "speakers": {"Rick": {"name": "Rick", "voice": "", "instruct": None}},
            }
        ),
        encoding="utf-8",
    )

    rick = SpeakerRegistry(path, auto_save_interval=0.0).get("Rick")

    assert rick.instruct == ""
    assert rick.emotion == "neutral"


def test_update_ignores_none_fields(registry):
    """``None`` means "leave this field alone", not "clear it".

    Pinned because the registry docstring now says so. A PATCH body that
    omits a key sends ``None`` for it, so treating ``None`` as a clear would
    wipe every unspecified field on every save from the GUI.
    """
    registry.register("Rick")
    registry.update("Rick", voice="gpu1", instruct="whisper", emotion="calm")
    registry.update("Rick", emotion="angry")

    rick = registry.get("Rick")
    assert rick.voice == "gpu1"
    assert rick.instruct == "whisper"
    assert rick.emotion == "angry"


def test_update_can_clear_a_field_with_empty_string(registry):
    """The documented way to clear a field, since ``None`` no longer does.

    Otherwise the ``None``-means-leave contract above would leave a user with
    no way to remove an instruction once set.
    """
    registry.register("Rick")
    registry.update("Rick", instruct="whisper")
    registry.update("Rick", instruct="")
    assert registry.get("Rick").instruct == ""


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
