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
        patterns=[{"pattern": r"\baaah\b", "tag": "sigh"}],
        aliases={"aah": "sigh", "mmmm": "sigh", "mm-hm": "gasp"},
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
    the guard has to stay. (Aah itself is speakable now; sighs still drops.)
    """
    cleaned = clean_emotion_text("*sighs*!")
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


def _real(tmp_path: Path) -> EmotionSounds:
    """EmotionSounds reading the shipped patterns and the 13 shipped clips."""
    es = EmotionSounds.__new__(EmotionSounds)
    es.dir = REPO_DATA / "emotion_sounds"
    es.map_file = tmp_path / "emotion_sound_map.json"
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

# Bare forms of the shipped clips. Starred-only families (kiss, knock) are
# covered separately below. Anything else has no clip and must pass through.
REAL_SOUNDS = [
    "sigh", "gasp", "yawn", "cough", "gulp", "hic", "doorbell",
    "shh", "whistle", "panting", "sniff", "sob",
]


def test_shipped_patterns_do_not_eat_real_words(tmp_path: Path) -> None:
    es = _real(tmp_path)
    bad = [(line, tags) for line in REAL_WORDS for _, tags in [es.extract(line)] if tags]
    assert not bad, f"woorden die als emotie werden afgespeeld: {bad}"


def test_shipped_patterns_still_catch_real_emotions(tmp_path: Path) -> None:
    es = _real(tmp_path)
    missed = [w for w in REAL_SOUNDS if not es.extract(w)[1]]
    assert not missed, f"emoties die niet meer herkend worden: {missed}"


def test_shipped_patterns_keep_every_pattern_compilable(tmp_path: Path) -> None:
    """The GUI edits this file, so a broken regex must fail loudly, not at runtime."""
    es = _real(tmp_path)
    assert es.pattern_defs, "emotion_patterns.json leverde geen patronen op"
    for item in es.pattern_defs:
        assert item.get("pattern"), f"patroon zonder regex: {item}"


def test_words_without_a_clip_pass_through(tmp_path: Path) -> None:
    """Stretched sounds have no clip, so they must reach Qwen as text."""
    es = _real(tmp_path)
    for word in ("harrrraaahrrreee", "haaaaaa", "ohhh", "eeeit", "tzzzz"):
        cleaned, positions = es.extract(word)
        assert not positions, f"{word!r} speelde een emotie"
        assert word in cleaned, f"{word!r} werd onterecht verwijderd: {cleaned!r}"
    for word in ("assess", "coffee", "committee", "bookkeeper", "successful", "mamma"):
        cleaned, _ = es.extract(word)
        assert word in cleaned, f"{word!r} werd onterecht verwijderd"


def test_short_names_are_never_emotions(tmp_path: Path) -> None:
    """Names like Anna/Emma must never be played as a moan clip."""
    es = _real(tmp_path)
    for name in ("Anna", "Emma", "Hannah", "Nina", "Megan", "Anne", "Ines", "Emanuela"):
        assert not es.extract(name)[1], f"{name!r} speelde een emotie"


def test_sniff_family_all_reach_the_sniffle_sound(tmp_path: Path) -> None:
    """"sniff" is common in AVN text but is not always a sniffle."""
    es = _real(tmp_path)
    for word in ("sniff", "sniffs", "sniffle", "sniffles", "sniffling", "snifflings"):
        cleaned, positions = es.extract(word)
        assert [t for _, t in positions] == ["sniffle"], f"{word!r} -> {positions}"
        assert not cleaned.strip(), f"{word!r} bereikte ook nog Qwen: {cleaned!r}"


def test_sniff_family_does_not_swallow_ordinary_verbs(tmp_path: Path) -> None:
    """"sniffled" and "sniffily" are real words; only the -le/-ling forms go."""
    es = _real(tmp_path)
    for word in ("sniffled", "sniffily", "sniffl"):
        assert not es.extract(word)[1], f"{word!r} speelde een emotie"


def test_sobs_still_reaches_the_sniffle_sound(tmp_path: Path) -> None:
    es = _real(tmp_path)
    assert [t for _, t in es.extract("sobs")[1]] == ["sniffle"]


def test_cough_family_is_starred_and_bare(tmp_path: Path) -> None:
    es = _real(tmp_path)
    for word in ("cough", "coughs", "coughed", "coughing",
                 "*cough*", "*coughs*", "*coughing*"):
        cleaned, positions = es.extract(word)
        assert [t for _, t in positions] == ["cough"], f"{word!r} -> {positions}"
        assert not cleaned.strip(), f"{word!r} bereikte ook nog Qwen: {cleaned!r}"


def test_sniff_and_sob_share_one_clip() -> None:
    es = EmotionSounds(player=None)
    words = ("sniff", "sniffs", "sniffed", "sniffing",
             "sniffle", "sniffles", "sniffling",
             "sob", "sobs", "sobbed", "sobbing")
    for word in words:
        cleaned, positions = es.extract(word)
        assert [t for _, t in positions] == ["sniffle"], f"{word!r} -> {positions}"
        assert not cleaned.strip(), f"{word!r} bereikte ook nog Qwen: {cleaned!r}"
        assert es.resolve_path(positions[0][1]) == es.dir / "sniff_sob.wav", word


def test_hic_family_reaches_the_hic_clip() -> None:
    es = EmotionSounds(player=None)
    words = ("hic", "hics", "hiccup", "hiccups", "hiccuped",
             "hiccuping", "hiccupped", "hiccupping")
    for word in words:
        cleaned, positions = es.extract(word)
        assert [t for _, t in positions] == ["hic"], f"{word!r} -> {positions}"
        assert not cleaned.strip(), f"{word!r} bereikte ook nog Qwen: {cleaned!r}"
        assert es.resolve_path(positions[0][1]) == es.dir / "hic.wav", word


def test_shh_and_whistle_families_reach_their_clips() -> None:
    es = EmotionSounds(player=None)
    for word in ("shh", "shhh", "*shh*", "*shhh*", "whistle", "whistles",
                 "whistled", "whistling", "*whistle*"):
        cleaned, positions = es.extract(word)
        assert positions, f"{word!r} speelde geen emotie"
        assert not cleaned.strip(), f"{word!r} bereikte ook nog Qwen: {cleaned!r}"
    assert es.resolve_path("shhh") == es.dir / "shhh.ogg"
    assert es.resolve_path("whistle") == es.dir / "wistle.ogg"


ALIASES = {"sigh": "sigh", "hiccup": "hic", "gasp": "gasp"}


def test_speak_route_honours_the_users_aliases() -> None:
    """Before, 26 of the shipped aliases were read out loud on this route."""
    for expr in ALIASES:
        line = f"Zij zei {expr} en lachte."
        assert clean_emotion_text(line, ALIASES) == "Zij zei en lachte.", expr


def test_speak_route_without_aliases_still_strips_sound_words() -> None:
    """The default must keep working for callers that pass no mapping."""
    assert clean_emotion_text("*sighs* Come here.") == "Come here."
    # Bare sound words are filtered too, not only their starred form.
    assert clean_emotion_text("Zij zei cough.") == "Zij zei."


def test_speak_route_never_hands_qwen_stranded_punctuation() -> None:
    """A removed emotion can leave ",." or a leading "!" behind."""
    assert clean_emotion_text("I love it, aah.", {"aah": "sigh"}) == "I love it."
    assert clean_emotion_text("Aah! Yes...", {"aah": "sigh"}) == "Yes..."
    assert clean_emotion_text("Zij zei cough.", ALIASES) == "Zij zei."
    assert not has_speakable_text(clean_emotion_text("Sigh.", {"sigh": "sigh"}))


def test_ellipsis_between_words_survives() -> None:
    """The pause is prosody Qwen3 renders as silence; it must reach the model.

    This is the line the user listened to: "if you want... I... ehm" only gets
    its waiting periods if the dots reach the backend.
    """
    text = "Later, if you want... I... ehm... I'll do the same thing as the other day."
    assert clean_emotion_text(text) == text


def test_ellipsis_glued_to_a_word_survives() -> None:
    assert clean_emotion_text("Yeah...") == "Yeah..."
    assert clean_emotion_text("Wait... what?") == "Wait... what?"
    assert clean_emotion_text("Is that all there is…") == "Is that all there is…"


def test_ellipsis_on_its_own_is_dropped() -> None:
    """A line of nothing but dots has nothing to say, so nothing is spoken."""
    for line in ("...", "…", ".....", "  ...  ", "Aah! ...", "aah ...", "aah, ..."):
        assert not has_speakable_text(clean_emotion_text(line, {"aah": "sigh"})), line
    assert clean_emotion_text("...") == ""


def test_trailing_ellipsis_next_to_text_is_demoted_not_eaten() -> None:
    """A pause glued to the last word stays; a detached one is dropped."""
    assert clean_emotion_text("Yes... aah.", {"aah": "sigh"}) == "Yes..."
    assert clean_emotion_text("Yes... ...") == "Yes..."
    # "Mm-hm" is not an emotion pattern here, so it stays real text and only
    # the detached ellipsis after it goes.
    assert clean_emotion_text("Mm-hm. ...") == "Mm-hm."


def test_stranded_mark_between_two_marks_is_dropped() -> None:
    assert clean_emotion_text("I love it, aah.", {"aah": "sigh"}) == "I love it."
    assert clean_emotion_text("I love it,. aah", {"aah": "sigh"}) == "I love it."


def test_deliberate_punctuation_survives() -> None:
    """Question marks, exclamation marks and pauses are the model's job."""
    assert clean_emotion_text("Really?!") == "Really?!"
    assert clean_emotion_text("Yeah.") == "Yeah."
    assert clean_emotion_text("Stop!") == "Stop!"


def test_leading_and_trailing_strip_is_symmetric() -> None:
    from novatts.text_clean import (
        strip_leading_punctuation,
        strip_trailing_stray_punctuation,
    )

    assert strip_leading_punctuation("! Yes") == "Yes"
    assert strip_leading_punctuation("Yes...") == "Yes..."
    assert strip_trailing_stray_punctuation("Yes...") == "Yes..."
    assert strip_trailing_stray_punctuation("Yes... ...") == "Yes..."
    assert strip_trailing_stray_punctuation("Yes") == "Yes"
    assert strip_trailing_stray_punctuation("...") == "..."


def test_punctuation_folding_spares_abbreviations() -> None:
    assert clean_emotion_text("Mr. Smith said no.") == "Mr. Smith said no."


def test_old_loose_patterns_are_gone() -> None:
    """Guards the specific regression: the character-class pattern is removed."""
    patterns = [p["pattern"] for p in json.loads(REAL_PATTERNS.read_text(encoding="utf-8"))]
    assert not [p for p in patterns if "[mnhaeou]" in p], "de losse-klasse-patronen zijn terug"


SHIPPED_CLIPS = {
    "cough.wav", "doorbell.ogg", "gasp.ogg", "gulp.ogg", "hic.wav",
    "kiss.ogg", "knock.ogg", "panting.wav", "shhh.ogg", "sigh.wav",
    "sniff_sob.wav", "wistle.ogg", "yawn.wav",
}


def test_only_the_thirteen_shipped_clips_are_used(tmp_path: Path) -> None:
    """Every tagged pattern must point at one of the 13 files on disk."""
    folder = REPO_DATA / "emotion_sounds"
    assert {p.name for p in folder.iterdir() if p.is_file()} == SHIPPED_CLIPS
    es = _real(tmp_path)
    assert set(es.sound_map.values()) == SHIPPED_CLIPS
    for item in es.pattern_defs:
        tag = item.get("tag")
        if tag is None:
            continue
        resolved = es.resolve_path(str(tag))
        assert resolved is not None, f"{tag!r} heeft geen clip"
        assert resolved.name in SHIPPED_CLIPS, f"{tag!r} -> {resolved}"


def test_knock_only_matches_inside_asterisks(tmp_path: Path) -> None:
    es = _real(tmp_path)
    for bare in ("knock", "knocks", "knocked", "knocking",
                 "I knock on the door.", "She knocked twice."):
        cleaned, positions = es.extract(bare)
        assert not positions, f"{bare!r} speelde een clip"
        assert "knock" in cleaned.lower(), f"{bare!r} werd gedropt: {cleaned!r}"
    for starred in ("*knock*", "*knocks*", "*knocked*", "*knocking*"):
        cleaned, positions = es.extract(starred)
        assert [t for _, t in positions] == ["knock"], f"{starred!r} -> {positions}"
        assert not cleaned.strip(), f"{starred!r} bereikte ook Qwen: {cleaned!r}"
    # /speak route: bare stays, starred drops (no clip playback there).
    assert clean_emotion_text("I knock on the door.") == "I knock on the door."
    assert clean_emotion_text("*knock*") == ""


def test_mmm_passes_through_on_both_routes(tmp_path: Path) -> None:
    es = _real(tmp_path)
    for raw in ("mmm", "*mmm*"):
        cleaned, positions = es.extract(raw)
        assert positions == [], f"{raw!r} speelde een clip"
        assert cleaned == "mmm", f"{raw!r} -> {cleaned!r}"
        assert clean_emotion_text(raw) == "mmm", raw


def test_alias_without_a_clip_is_ignored(tmp_path: Path) -> None:
    # /speak route: the alias target has no clip, so the word stays.
    assert clean_emotion_text("Zij zei splurt.", {"splurt": "moanb"}) == "Zij zei splurt."
    # Clipboard route: the same alias is dropped while loading.
    aliases = tmp_path / "emotion_aliases.json"
    aliases.write_text(json.dumps({"splurt": "moanb"}), encoding="utf-8")
    es = _real(tmp_path)
    es.aliases_file = aliases
    es.reload()
    assert es.aliases == {}
    cleaned, positions = es.extract("Zij zei splurt.")
    assert positions == []
    assert "splurt" in cleaned


def test_pattern_without_a_clip_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patterns = tmp_path / "emotion_patterns.json"
    patterns.write_text(
        json.dumps([
            {"pattern": r"\bmoan\b", "tag": "moan"},
            {"pattern": r"\bcough\b", "tag": "cough"},
        ]),
        encoding="utf-8",
    )
    # Clipboard route: only the clip-backed pattern is compiled.
    es = _real(tmp_path)
    es.patterns_file = patterns
    es.reload()
    cleaned, positions = es.extract("moan cough")
    assert [t for _, t in positions] == ["cough"]
    assert cleaned.strip() == "moan"

    # /speak route: the same file is read through settings.
    from novatts.config import settings
    from novatts.text_clean import reload_patterns

    try:
        monkeypatch.setattr(settings, "emotion_patterns_file", patterns)
        reload_patterns()
        assert clean_emotion_text("moan cough") == "moan"
    finally:
        monkeypatch.undo()
        reload_patterns()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
