"""What ``PATCH /speakers/{name}`` actually forwards.

G5.5 turned out to be two broken layers, not one, and only measuring the
second one revealed the first:

  1. ``SpeakerRegistry.update()`` took ``instruct`` and never assigned it.
  2. ``update_speaker()`` wrapped that method and forwarded only ``voice``,
     and ``SpeakerPatchBody`` did not even have the field -- so ``instruct``
     and ``emotion`` were unreachable from outside the process.

Fixing only (1) is the mistake this file exists to prevent, because the
resulting code is *worse* than before: ``update()`` now honours ``instruct``,
the signature invites callers to use it, and the endpoint still swallows it.
The failure moves from obvious to invisible.

So this file tests the endpoint, not the registry. The registry's own
behaviour is pinned in ``test_speaker_registry.py``.

Both halves of a round trip are asserted. Checking only the HTTP response
body is not enough, because the response is built from the same object the
handler just failed to write -- a handler that drops a field and then
serialises that same object returns a body that *looks* right. The
``load`` assertions go back to the registry and re-read the field.

The GUI is deliberately not involved and deliberately not extended: it sends
``voice`` only (``updateSpeaker`` in ``api.ts`` is typed
``Partial<Pick<Speaker, "voice">>``). Adding an input for ``instruct`` is a
feature, and this is a fix.
"""

from __future__ import annotations

from typing import Any

import pytest

from novatts import main as main_mod
from novatts.registry.speakers import SpeakerRegistry


@pytest.fixture()
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> SpeakerRegistry:
    """A NovaApp shell carrying a real registry, wired in as the runtime."""
    reg = SpeakerRegistry(tmp_path / "speakers.json", auto_save_interval=0.0)
    reg.register("Rick")

    app = main_mod.NovaApp.__new__(main_mod.NovaApp)
    app.registry = reg
    monkeypatch.setattr(main_mod, "_runtime", app, raising=False)
    return reg


def _patch(name: str, body: Any) -> Any:
    import asyncio

    return asyncio.run(
        main_mod.update_speaker(name, main_mod.SpeakerPatchBody(**body))
    )


# --- the fields that were lost -------------------------------------------------


def test_patch_stores_the_instruct(runtime: SpeakerRegistry) -> None:
    _patch("Rick", {"instruct": "whisper"})
    assert runtime.get("Rick").instruct == "whisper"


def test_patch_stores_the_emotion(runtime: SpeakerRegistry) -> None:
    _patch("Rick", {"emotion": "calm"})
    assert runtime.get("Rick").emotion == "calm"


def test_patch_still_stores_the_voice(runtime: SpeakerRegistry) -> None:
    """The field that worked before, so the fix is not a swap."""
    _patch("Rick", {"voice": "M-All_Peter_Griffin"})
    assert runtime.get("Rick").voice == "M-All_Peter_Griffin"


# --- omitted means unchanged, "" means clear ----------------------------------


def test_an_omitted_field_is_left_alone(runtime: SpeakerRegistry) -> None:
    _patch("Rick", {"voice": "gpu1", "instruct": "whisper", "emotion": "calm"})
    _patch("Rick", {"emotion": "angry"})

    rick = runtime.get("Rick")
    assert rick.voice == "gpu1"
    assert rick.instruct == "whisper"
    assert rick.emotion == "angry"


def test_the_response_body_reflects_all_three_fields(runtime: SpeakerRegistry) -> None:
    body = _patch("Rick", {"voice": "gpu1", "instruct": "whisper", "emotion": "calm"})
    assert body["voice"] == "gpu1"
    assert body["instruct"] == "whisper"
    assert body["emotion"] == "calm"


# --- the parts that were already right, kept from regressing ------------------


def test_unknown_speaker_still_404s(runtime: SpeakerRegistry) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        _patch("Ghost", {"instruct": "whisper"})
    assert excinfo.value.status_code == 404


def test_patch_persists_to_disk(runtime: SpeakerRegistry) -> None:
    """The endpoint calls ``save()``; without this, a PATCH looks saved until
    the next restart, which is the same shape of bug one layer down."""
    import json

    _patch("Rick", {"instruct": "whisper", "emotion": "calm"})
    stored = json.loads(runtime.file_path.read_text(encoding="utf-8"))
    assert stored["speakers"]["Rick"]["instruct"] == "whisper"
    assert stored["speakers"]["Rick"]["emotion"] == "calm"
