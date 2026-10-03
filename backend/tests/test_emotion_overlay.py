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


def test_api_cleaner_no_longer_leaves_stranded_punctuation() -> None:
    """An emotion that is the only content leaves nothing speakable.

    The callers still guard with has_speakable_text(); this pins down that
    the guard has to stay.
    """
    cleaned = clean_emotion_text("*Aah*!")
    assert not has_speakable_text(cleaned), f"{cleaned!r} zou naar Qwen gaan"
    assert not has_speakable_text(clean_emotion_text("...", None))


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


REPO_DATA = Path(__file__).resolve().parents[2] / "data"
REAL_PATTERNS = REPO_DATA / "emotion_patterns.json"


def _real() -> EmotionSounds:
    """EmotionSounds reading the shipped emotion_patterns.json."""
    es = EmotionSounds.__new__(EmotionSounds)
    es.dir = REPO_DATA
    es.map_file = REPO_DATA / "__nonexistent_map__.json"
    es.patterns_file = REAL_PATTERNS
    es.aliases_file = REPO_DATA / "__nonexistent_aliases__.json"
    es._on_disk = {}
    es._slug_index = {}
    es._lock = __import__("threading").Lock()
    es.sound_map = {}
    es.pattern_defs = []
    es.compiled = []
    es.aliases = {}
    es._reload()
    return es


# Ordinary words and the kind of names an AVN is full of. These used to be
# played as a moan: "\b[mnhaeou]+[mngh][mnhaeou]{2,}\b" matches "human"
# (hu + m + an) and every Anna / Emma / Hannah.
REAL_WORDS = [
    "human", "Anna", "Emma", "Hannah", "Anne", "Megan", "anana", "Nina",
    "I felt human again.", "Anna looked at me.", "Emma and Hannah waited.",
    "Megan and Anna hummed.", "Anne is human.",
]

# Words the shipped patterns themselves own. Names like "moan" or "gasp" are
# only matched in their starred form (*moan*), and the spelled-out runs like
# "aaaaaaaah" live in the user's alias file, so neither belongs in this list.
REAL_SOUNDS = ["haha", "sigh", "aaannh", "hnnng", "hmpf", "argh"]


def test_shipped_patterns_do_not_eat_real_words() -> None:
    es = _real()
    bad = [(line, tags) for line in REAL_WORDS for _, tags in [es.extract(line)] if tags]
    assert not bad, f"woorden die als emotie werden afgespeeld: {bad}"


def test_shipped_patterns_still_catch_real_emotions() -> None:
    es = _real()
    missed = [w for w in REAL_SOUNDS if not es.extract(w)[1]]
    assert not missed, f"emoties die niet meer herkend worden: {missed}"


def test_shipped_patterns_keep_every_pattern_compilable() -> None:
    """The GUI edits this file, so a broken regex must fail loudly, not at runtime."""
    es = _real()
    assert es.pattern_defs, "emotion_patterns.json leverde geen patronen op"
    for item in es.pattern_defs:
        assert item.get("pattern"), f"patroon zonder regex: {item}"


def test_three_letters_in_a_row_is_always_an_emotion() -> None:
    """Any letter, not just [mnh]: no English or Dutch word has xxx in it."""
    es = _real()
    for word in ("harrrraaahrrreee", "haaaaaa", "ohhh", "eeeit", "tzzzz"):
        cleaned, positions = es.extract(word)
        assert word not in cleaned, f"{word!r} bereikte Qwen: {cleaned!r}"
    # and it must not fire on anything pronounceable
    for word in ("assess", "coffee", "committee", "bookkeeper", "successful", "mamma"):
        cleaned, _ = es.extract(word)
        assert word in cleaned, f"{word!r} werd onterecht verwijderd"


def test_short_names_are_never_moan_patterns() -> None:
    """The moan class needs two nasals after a vowel run; a name cannot supply both."""
    es = _real()
    for name in ("Anna", "Emma", "Hannah", "Nina", "Megan", "Anne", "Ines", "Emanuela"):
        assert not es.extract(name)[1], f"{name!r} speelde een emotie"


def test_sniff_family_all_reach_the_sniffle_sound() -> None:
    """"sniff" is common in AVN text but is not always a sniffle."""
    es = _real()
    for word in ("sniff", "sniffs", "sniffle", "sniffles", "sniffling", "snifflings"):
        cleaned, positions = es.extract(word)
        assert [t for _, t in positions] == ["sniffle"], f"{word!r} -> {positions}"
        assert not cleaned.strip(), f"{word!r} bereikte ook nog Qwen: {cleaned!r}"


def test_sniff_family_does_not_swallow_ordinary_verbs() -> None:
    """"sniffled" and "sniffily" are real words; only the -le/-ling forms go."""
    es = _real()
    for word in ("sniffled", "sniffily", "sniffl"):
        assert not es.extract(word)[1], f"{word!r} speelde een emotie"


def test_sobs_still_reaches_the_sniffle_sound() -> None:
    es = _real()
    assert [t for _, t in es.extract("sobs")[1]] == ["sniffle"]


ALIASES = {"slurp": "slurp", "hiccup": "hic", "splurt": "moanb"}


def test_speak_route_honours_the_users_aliases() -> None:
    """Before, 26 of the shipped aliases were read out loud on this route."""
    for expr in ALIASES:
        line = f"Zij zei {expr} en lachte."
        assert clean_emotion_text(line, ALIASES) == "Zij zei en lachte.", expr


def test_speak_route_without_aliases_is_unchanged() -> None:
    """The default must keep working for callers that pass no mapping."""
    assert clean_emotion_text("*Aah!* Come here.") == "Come here."
    assert clean_emotion_text("Zij zei slurp.") == "Zij zei slurp."


def test_speak_route_never_hands_qwen_stranded_punctuation() -> None:
    """A removed emotion can leave ",." or a leading "!" behind."""
    assert clean_emotion_text("I love it, aah.", {"aah": "moang"}) == "I love it,"
    assert clean_emotion_text("Aah! Yes...", {"aah": "moang"}) == "Yes"
    assert clean_emotion_text("Zij zei slurp.", ALIASES) == "Zij zei."
    assert not has_speakable_text(clean_emotion_text("Hmm.", {"hmm": "hmm"}))


def test_punctuation_folding_spares_abbreviations() -> None:
    assert clean_emotion_text("Mr. Smith said no.") == "Mr. Smith said no."


def test_old_loose_patterns_are_gone() -> None:
    """Guards the specific regression: the character-class pattern is removed."""
    patterns = [p["pattern"] for p in json.loads(REAL_PATTERNS.read_text(encoding="utf-8"))]
    assert not [p for p in patterns if "[mnhaeou]" in p], "de losse-klasse-patronen zijn terug"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
