"""Emotion extraction must not leave unspeakable text for the TTS backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novatts.emotions import EmotionSounds
from novatts.text_clean import clean_emotion_text, has_speakable_text, strip_leading_punctuation


class _Stub(EmotionSounds):
    """EmotionSounds with a fixed pattern/alias set, so tests need no sound files."""

    def __init__(self, patterns: list[dict], aliases: dict[str, str]) -> None:
        self.dir = Path(__file__).parent
        self.map_file = self.dir / "__map__.json"
        self.patterns_file = self.dir / "__patterns__.json"
        self.aliases_file = self.dir / "__aliases__.json"
        self._player = None
        self.sound_map = dict(aliases)
        self.pattern_defs = patterns
        self.aliases = dict(aliases)
        self._on_disk = {}
        self._slug_index = {}
        self._lock = __import__("threading").Lock()
        self.compiled = []
        for item in patterns:
            pat, tag = item.get("pattern"), item.get("tag")
            if pat:
                self.compiled.append((__import__("re").compile(pat, __import__("re").I), tag))


def _stub() -> _Stub:
    return _Stub(
        patterns=[{"pattern": r"\baaah\b", "tag": "moanc"}],
        aliases={"aah": "moang", "mmmm": "mmmm", "mm-hm": "aha"},
    )


def qwen_text(stub: _Stub, raw: str) -> list[str]:
    """Everything the plan would hand to the TTS backend, in order."""
    cleaned, positions = stub.extract(raw)
    return [v for k, v in stub.plan(cleaned, positions) if k == "text"]


def test_leftover_punctuation_is_not_synthesized() -> None:
    """The core bug: stripping 'Aah!' left '!' and it was spoken."""
    stub = _stub()
    assert qwen_text(stub, "Aah!") == []
    assert qwen_text(stub, "Mm-hm!") == []
    assert qwen_text(stub, "Aah! Aah!") == []
    assert qwen_text(stub, "*Aah*") == []


def test_leading_punctuation_after_emotion_is_trimmed() -> None:
    stub = _stub()
    assert qwen_text(stub, "Aaah! Yes...") == ["Yes..."]


def test_real_text_keeps_its_own_punctuation() -> None:
    """Trailing ellipses are prosody, not leftovers."""
    stub = _Stub(patterns=[], aliases={})
    assert qwen_text(stub, "Well...") == ["Well..."]
    assert qwen_text(stub, "I... I trust you.") == ["I... I trust you."]


def test_sound_stays_between_the_words() -> None:
    stub = _stub()
    cleaned, positions = stub.extract("hot... mmmm, I love it.")
    kinds = stub.plan(cleaned, positions)
    assert [k for k, _ in kinds] == ["text", "sound", "text"]
    assert kinds[0][1] == "hot..."
    assert kinds[2][1] == "I love it."


def test_plan_never_emits_unspeakable_text() -> None:
    stub = _stub()
    for raw in ("Aah!", "Mm-hm.", "Aah!", "Aaah! Yes...", "aah", "*Aah*", "Aah! Aah! Mm-hm."):
        for chunk in qwen_text(stub, raw):
            assert has_speakable_text(chunk), f"{raw!r} produced {chunk!r}"


def test_has_speakable_text() -> None:
    assert has_speakable_text("Yes")
    assert has_speakable_text("42 procent")
    assert not has_speakable_text("")
    assert not has_speakable_text("...")
    assert not has_speakable_text(" ! , ? ")
    assert not has_speakable_text("*_*")


def test_strip_leading_punctuation_keeps_trailing() -> None:
    assert strip_leading_punctuation("! Yes...") == "Yes..."
    assert strip_leading_punctuation(" , wat?") == "wat?"
    assert strip_leading_punctuation("Yes...") == "Yes..."


def test_api_cleaner_leaves_punctuation_that_callers_must_guard() -> None:
    """The /speak route uses clean_emotion_text, which stops at "!".

    Callers there check has_speakable_text() instead of .strip() -- that guard
    is the only thing standing between a bare "!" and a synthesis request.
    """
    assert clean_emotion_text("*Aah*!").strip() == "!"
    assert not has_speakable_text(clean_emotion_text("*Aah*!"))


def test_map_file_is_synced_and_ignores_missing_files(tmp_path: Path) -> None:
    folder = tmp_path / "sounds"
    folder.mkdir()
    (folder / "sigh.wav").write_bytes(b"RIFF" + b"\0" * 32)
    (folder / "breathing_heavily.wav").write_bytes(b"RIFF" + b"\0" * 32)
    (folder / "empty.wav").write_bytes(b"")

    stub = EmotionSounds.__new__(EmotionSounds)
    stub.dir = folder
    stub.map_file = tmp_path / "emotion_sound_map.json"
    stub.patterns_file = tmp_path / "nope.json"
    stub.aliases_file = tmp_path / "nope.json"
    stub._on_disk = {}
    stub._slug_index = {}
    stub.sound_map = {}
    stub.pattern_defs = []
    stub.compiled = []
    stub.aliases = {}
    stub._reload()

    # both discovered, zero-byte file skipped
    assert set(stub.sound_map) == {"sigh", "breathing_heavily"}
    # underscores and digits resolve, so the map is written and stays in sync
    assert stub.resolve_path("breathing_heavily") is not None
    assert stub.resolve_path("breathingheavily") is not None
    assert json.loads(stub.map_file.read_text(encoding="utf-8")) == stub.sound_map

    # a new file shows up on reload, a deleted one disappears
    (folder / "gasp.wav").write_bytes(b"RIFF" + b"\0" * 32)
    (folder / "sigh.wav").unlink()
    stub.reload()
    assert set(stub.sound_map) == {"breathing_heavily", "gasp"}
    assert json.loads(stub.map_file.read_text(encoding="utf-8")) == stub.sound_map


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
