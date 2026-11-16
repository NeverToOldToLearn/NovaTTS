"""Tests for the LunaTranslator hook parser.

The fixtures are real payloads from Luna's translation history (RPG Maker
MV via a text hook): the game's own colour tag carries the speaker, and the
line keeps its ``\\n``/``\\c``/``\\sa`` control codes. A second hook can append
duplicated word-wrap fragments and browser JS paths.
"""

from __future__ import annotations

import threading

from novatts.adapters.clipboard import ClipboardAdapter
from novatts.main import NovaApp
from novatts.models import Dialogue
from novatts.parser.luna import LunaParser, has_hook_markup, parse_actor_names

SPEAKER_RAW = (
    "<WordWrap>\n"
    "<\\c[2]Man>\\c[0]\\sa[10]Tch! If I ever see you in my establishment again...\n"
    "<WordWrap>\\da[10]"
)
NARRATOR_RAW = "<WordWrap>But that was years ago."
LONG_NARRATOR_RAW = "<WordWrap>I can remember a time back when a show like that..."

JS_PATH = "chrome-extension://odlameecjipmbmbejkplpemijjgpljce/www/js/rpg_managers.js"
NOISY_RAW = (
    SPEAKER_RAW + "\\fb\\fs[25]\\c[29]\\ow[4] \x1bc[2]Man\n" + JS_PATH + "\n"
    "chrome-extension://odlameecjipmbmbejkplpemijjgpljce/www/js/rpg_objects.js"
)

parser = LunaParser()


def test_speaker_tag_wins_over_colon_heuristics():
    d = parser.parse(SPEAKER_RAW)
    assert d.speaker == "Man"
    assert d.text == "Tch! If I ever see you in my establishment again..."
    assert d.is_voiceable


def test_narrator_line_has_no_speaker():
    d = parser.parse(NARRATOR_RAW)
    assert d.speaker is None
    assert d.text == "But that was years ago."


def test_long_narrator_is_not_split_into_a_speaker():
    d = parser.parse(LONG_NARRATOR_RAW)
    assert d.speaker is None
    assert d.text == "I can remember a time back when a show like that..."


def test_noisy_multi_hook_payload_keeps_first_dialogue_segment():
    d = parser.parse(NOISY_RAW)
    assert d.speaker == "Man"
    assert d.text == "Tch! If I ever see you in my establishment again..."
    assert "chrome-extension" not in d.text
    assert ".js" not in d.text


def test_esc_speaker_tag_is_understood():
    raw = "\x1bc[2]Aria\nThen we leave at dawn."
    d = parser.parse(raw)
    assert d.speaker == "Aria"
    assert d.text == "Then we leave at dawn."


def test_known_speaker_spelling_is_restored():
    p = LunaParser(known_names=["Man", "Aria"])
    d = p.parse("<\\c[2]MAN>\\c[0]Still here?")
    assert d.speaker == "Man"


def test_loose_colon_form_still_works_without_markup():
    d = parser.parse("Rick: Hi all.")
    assert d.speaker == "Rick"
    assert d.text == "Hi all."


def test_mention_of_a_name_is_narration():
    d = parser.parse("Rick said hello to everyone.")
    assert d.speaker is None
    assert d.text == "Rick said hello to everyone."


def test_control_codes_are_stripped():
    d = parser.parse("<WordWrap>\\c[29]\\fs[25]The night was cold.")
    assert d.text == "The night was cold."


# -- RPG Maker name placeholders (\n[1] = actor 1's name) -------------------

PROTAGONIST_TAG_RAW = "<WordWrap>\\n<\\c[14]\\n[1]>\\c[0]Maybe not..."


def test_actor_name_mapping_is_parsed():
    assert parse_actor_names("1=Rick, 2=Otsu") == {1: "Rick", 2: "Otsu"}
    assert parse_actor_names({1: "Rick"}) == {1: "Rick"}
    assert parse_actor_names("") == {}


def test_inline_name_placeholder_is_resolved_before_newlines():
    p = LunaParser(name_codes="1=Rick")
    d = p.parse("<WordWrap>No. I'm not leaving \\n[1]'s side.")
    assert d.text == "No. I'm not leaving Rick's side."


def test_protagonist_speaker_tag_resolves_to_the_actor_name():
    p = LunaParser(name_codes="1=Rick")
    d = p.parse(PROTAGONIST_TAG_RAW)
    assert d.speaker == "Rick"
    assert d.text == "Maybe not..."


def test_unmapped_name_placeholder_is_dropped_cleanly():
    d = parser.parse("<WordWrap>WAIT! \\n[1]...! At least hear me out!")
    assert d.text == "WAIT! ...! At least hear me out!"


def test_duplicate_rendering_does_not_override_the_tagged_line():
    p = LunaParser(name_codes="1=Rick")
    raw = (
        "<WordWrap>\\n<\\c[14]\\n[1]>\\c[0]I only know what I'm seeing.\n\n"
        " Rick\n RickI only know what I'm seeing."
    )
    d = p.parse(raw)
    assert d.speaker == "Rick"
    assert d.text == "I only know what I'm seeing."


# -- loose speakers must never invent characters ---------------------------


def test_unknown_speaker_tag_does_not_invent_a_name():
    d = parser.parse("<WordWrap>\\n<\\c[2]???>\\c[0]Yes... This city eats fools alive.")
    assert d.speaker is None
    assert d.text == "Yes... This city eats fools alive."


def test_narration_starting_with_a_sentence_word_is_not_a_speaker():
    for raw in (
        "<WordWrap>Because her parents were my old man's servants.",
        "<WordWrap>Seeing her like this makes me realize how much I've missed.",
        "<WordWrap>Almost ten years, huh...?",
    ):
        d = parser.parse(raw)
        assert d.speaker is None, raw
        assert d.text


def test_registry_name_space_form_is_accepted():
    p = LunaParser(known_names=["Hana"])
    d = p.parse("<WordWrap>Hana City...")
    assert d.speaker == "Hana"
    assert d.text == "City..."


def test_registry_name_in_narration_stays_narration():
    p = LunaParser(known_names=["Otsu"])
    d = p.parse("<WordWrap>Otsu goes quiet for a moment.")
    assert d.speaker is None
    assert d.text == "Otsu goes quiet for a moment."


def test_glued_registry_name_is_split_from_its_line():
    p = LunaParser(known_names=["Rick", "Otsu"])
    first = p.parse("RickI only know what I'm seeing.")
    assert first.speaker == "Rick"
    assert first.text == "I only know what I'm seeing."
    second = p.parse("OtsuWAIT! Rick...! At least hear me out!")
    assert second.speaker == "Otsu"
    assert second.text == "WAIT! Rick...! At least hear me out!"


def test_has_hook_markup_detects_hook_payloads():
    assert has_hook_markup(SPEAKER_RAW)
    assert has_hook_markup("<WordWrap>Hello.")
    assert not has_hook_markup("Rick: Hi all.")


def test_empty_payload_is_not_voiceable():
    d = parser.parse("<WordWrap>\\da[10]")
    assert d.text == ""
    assert not d.is_voiceable


def _adapter(tmp_path, monkeypatch) -> ClipboardAdapter:
    monkeypatch.setattr("novatts.config.settings.clipboard_raw_log", tmp_path / "raw.log", raising=False)
    monkeypatch.setattr("novatts.config.settings.log_raw_clipboard", False, raising=False)
    return ClipboardAdapter(on_dialogue=lambda dialogue: None)


def test_clipboard_hook_payload_goes_through_luna_parser(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, monkeypatch)
    seen = []
    adapter.on_dialogue = seen.append

    adapter._handle_hook_payload(SPEAKER_RAW)

    assert len(seen) == 1
    assert seen[0].speaker == "Man"
    assert seen[0].text == "Tch! If I ever see you in my establishment again..."
    assert seen[0].source == "clipboard"


def test_unusable_clipboard_hook_payload_is_reported(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, monkeypatch)
    reasons = []
    adapter._on_filtered = lambda reason, raw: reasons.append(reason)

    adapter._handle_hook_payload("<WordWrap>\\da[10]")

    assert reasons == ["garbage"]


# -- cross-adapter dedup (Luna + clipboard in "both" mode) ------------------


def _deduper(monkeypatch, mode: str = "both") -> NovaApp:
    app = NovaApp.__new__(NovaApp)
    app._dedup_lock = threading.Lock()
    app._last_dialogue = None
    monkeypatch.setattr("novatts.config.settings.hook_mode", mode, raising=False)
    monkeypatch.setattr("novatts.config.settings.hook_dedup_window", 3.0, raising=False)
    return app


def _line(source: str, text: str = "Tch! Not again.", speaker: str = "Man") -> Dialogue:
    return Dialogue(speaker=speaker, text=text, source=source)


def test_same_line_from_other_adapter_is_deduped(monkeypatch):
    app = _deduper(monkeypatch)
    assert app._is_duplicate_dialogue(_line("luna")) is False
    assert app._is_duplicate_dialogue(_line("clipboard")) is True


def test_genuine_repeat_after_a_deduped_copy_still_plays(monkeypatch):
    app = _deduper(monkeypatch)
    assert app._is_duplicate_dialogue(_line("luna")) is False
    assert app._is_duplicate_dialogue(_line("clipboard")) is True
    # Same source as the accepted line: a game really did repeat itself.
    assert app._is_duplicate_dialogue(_line("luna")) is False


def test_different_lines_are_never_deduped(monkeypatch):
    app = _deduper(monkeypatch)
    assert app._is_duplicate_dialogue(_line("luna")) is False
    assert app._is_duplicate_dialogue(_line("clipboard", text="Something else.")) is False


def test_dedup_is_off_outside_both_mode(monkeypatch):
    app = _deduper(monkeypatch, mode="luna")
    assert app._is_duplicate_dialogue(_line("luna")) is False
    assert app._is_duplicate_dialogue(_line("clipboard")) is False
