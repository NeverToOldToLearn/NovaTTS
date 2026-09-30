"""Tests for the LunaHook/Textractor parser.

The first class is ported verbatim from the donor project
(NovaTTSLuna tests/test_core.py :: TestLunaParser) so the heuristics that
were tuned against real games keep their behaviour after the rewrite.
The rest cover the multi-speaker split, which the donor does not have at
all, plus the ``raw`` contract added in F1.
"""

from __future__ import annotations

import pytest

from novatts.parser import (
    LunaParser,
    is_plausible_character_name,
    parse_luna,
    parse_luna_turns,
    reject_ui_line,
    split_speaker_turns,
)
from novatts.parser.luna import _MAX_NAME_LEN, _VN_UI_BLACKLIST

# --- ported from the donor: the name heuristics -----------------------------


class TestLunaParser:
    def test_space_form_name(self) -> None:
        d = parse_luna("Rick Hello there")
        assert d is not None
        assert d.speaker == "Rick"
        assert d.text == "Hello there"

    def test_space_form_narrator_stopword(self) -> None:
        d = parse_luna("You have your shower.")
        assert d is not None
        assert d.speaker is None

    def test_space_form_greeting(self) -> None:
        d = parse_luna("Good night babe!")
        assert d is not None
        assert d.speaker is None

    def test_mention_verb_is_narration(self) -> None:
        """The most common false positive: a sentence *about* Anne, not by her."""
        d = parse_luna("Anne has been quiet.")
        assert d is not None
        assert d.speaker is None

    def test_scene_label_is_narration(self) -> None:
        d = parse_luna("Later that day")
        assert d is not None
        assert d.speaker is None

    def test_save_ui_is_rejected(self) -> None:
        assert parse_luna("Save Game 3") is None
        assert parse_luna("Save Game 3 selected") is None

    def test_ui_line_rejected(self) -> None:
        assert reject_ui_line("Save Game 3 selected")
        assert reject_ui_line("END OF LINE")
        assert reject_ui_line("Auto Forward selected")
        assert not reject_ui_line("I got it.")
        assert parse_luna("END OF LINE") is None

    def test_colon_form_still_works(self) -> None:
        d = parse_luna("Anne: Hello!")
        assert d is not None
        assert d.speaker == "Anne"

    def test_plausible_names(self) -> None:
        assert is_plausible_character_name("Rick")
        assert is_plausible_character_name("Miss Brooks")
        assert not is_plausible_character_name("You")
        assert not is_plausible_character_name("Save Game 3")
        assert not is_plausible_character_name("END OF LINE")
        assert not is_plausible_character_name("Kitchen")


# --- UI patterns actually compiled ------------------------------------------


def test_all_ui_patterns_compiled() -> None:
    """A pattern that silently fails to compile would stop rejecting its UI.

    The module skips uncompilable patterns rather than crashing the import,
    so without this test a typo would show up only as "Save Game 3 starts
    playing out loud" months later.
    """
    assert len(_VN_UI_BLACKLIST) == 16


def test_ui_rejection_covers_the_common_shapes() -> None:
    for text in (
        "Save Game 3",
        "Load File",
        "Quick Save",
        "Monday 12 March",
        "Day 4",
        "Chapter 2",
        "Settings",
        "Options",
    ):
        assert reject_ui_line(text), f"{text!r} should be rejected as game chrome"


def test_known_gap_ui_patterns_only_match_the_whole_line() -> None:
    r"""A documented weakness of the ported pattern set, kept at parity.

    The Start/New/... pattern ends in ``(?:\s|$)`` but the pattern is
    anchored with ``^...$``, so the alternation can only ever match the
    bare word: "Start" is rejected, "Start Game" is not. Likewise the
    Narrator pattern requires the colon at the *end* of the line, so
    "System: welcome" survives.

    "Start Game" is not catastrophic -- "Start" is in the
    non-character token set, so it comes back as narration instead of
    being dropped -- but it is narration the user did not want. Inherited
    verbatim from the donor, which inherited it from VN_Suite.py, so it is
    pinned here rather than silently "fixed" in a parser. Widening these
    is a candidate for a follow-up once someone has real captures to tune
    against.
    """
    assert reject_ui_line("Start")
    assert not reject_ui_line("Start Game")
    assert not reject_ui_line("New Game")
    assert not reject_ui_line("System: welcome")


# --- multi-speaker split (the donor's gap) ----------------------------------


def test_two_speakers_in_one_line() -> None:
    turns = parse_luna_turns("Anne Hallo! Rick Mooi.")
    assert [(t.speaker, t.text) for t in turns] == [("Anne", "Hallo!"), ("Rick", "Mooi.")]


def test_two_speakers_needs_no_registry() -> None:
    """Unknown names still split, as long as they clear the plausibility check.

    The registry is not a prerequisite for splitting -- otherwise a brand
    new game would speak the first line of every conversation on the
    narrator voice until the user registered everyone by hand.
    """
    assert len(parse_luna_turns("Anne Hallo! Rick Mooi.")) == 2


def test_newline_bare_name_is_merged() -> None:
    """The "Rick\\nAnswer the door." shape: a name with nothing to attach to."""
    turns = parse_luna_turns("Rick\nAnswer the door.", known_names=["Rick"])
    assert [(t.speaker, t.text) for t in turns] == [("Rick", "Answer the door.")]


def test_newline_bare_name_needs_the_registry() -> None:
    """A bare capitalised line is only a name if it is already registered.

    Otherwise "Kitchen." on its own line would invent a character.
    """
    unmerged = split_speaker_turns("Kitchen.\nNobody is home.")
    assert unmerged == ["Kitchen. Nobody is home."]


def test_known_name_does_not_hijack_a_continuation() -> None:
    """"Rick totally agrees" is Rick speaking, about Rick -- one turn, not two."""
    assert split_speaker_turns("Rick totally agrees with that.", known_names=["Rick"]) == [
        "Rick totally agrees with that."
    ]


def test_scene_label_comma_is_not_a_speaker() -> None:
    assert split_speaker_turns("Meanwhile, back at the house Rick waited.", known_names=["Rick"]) == [
        "Meanwhile, back at the house Rick waited."
    ]


def test_digit_after_name_is_not_a_speaker() -> None:
    """Player 2 / Rick 2 steps forward -- a number, not a character."""
    assert split_speaker_turns("Rick 2 steps forward.", known_names=["Rick"]) == [
        "Rick 2 steps forward."
    ]


def test_mention_verb_does_not_open_a_turn() -> None:
    assert len(split_speaker_turns("Anne has been waiting. Rick waves.", known_names=["Anne"])) == 1


def test_trailing_sentence_stays_with_the_last_speaker() -> None:
    """A split point only exists where a *validated speaker* starts one.

    "Anne Hallo! Rick Mooi. Good night." is two speakers, not three --
    "Good night." is Rick's second sentence. If the final split only
    required sentence punctuation, it would cut here and hand a bare
    "Good night." to the parser, which would return it as narration and
    speak it out loud on the narrator voice.
    """
    assert split_speaker_turns("Anne Hallo! Rick Mooi. Good night.") == [
        "Anne: Hallo!",
        "Rick: Mooi. Good night.",
    ]
    turns = parse_luna_turns("Anne Hallo! Rick Mooi. Good night.")
    assert [(t.speaker, t.text) for t in turns] == [
        ("Anne", "Hallo!"),
        ("Rick", "Mooi. Good night."),
    ]


def test_speaker_may_speak_twice() -> None:
    """A repeated speaker splits again, even mid-line and non-adjacent."""
    turns = parse_luna_turns("Anne Hallo! Rick Mooi. Anne Bye.")
    assert [(t.speaker, t.text) for t in turns] == [
        ("Anne", "Hallo!"),
        ("Rick", "Mooi."),
        ("Anne", "Bye."),
    ]


def test_split_survives_ragged_whitespace() -> None:
    """Two spaces after punctuation must not hide the second speaker.

    The bound-finder's lookbehind wants exactly one space, so the splitter
    normalises first. Regression guard: without that, ragged hook text
    silently played every line on the first speaker's voice.
    """
    assert split_speaker_turns("Anne Hallo!  Rick Mooi.") == ["Anne: Hallo!", "Rick: Mooi."]


def test_space_form_false_does_not_split() -> None:
    """hook_space_form=0 means the game is not sending space-form text."""
    assert split_speaker_turns("Anne Hallo! Rick Mooi.", space_form=False) == [
        "Anne Hallo! Rick Mooi."
    ]


def test_empty_input_produces_no_turns() -> None:
    assert split_speaker_turns("") == []
    assert split_speaker_turns("   \n  ") == []
    assert parse_luna_turns("") == []


def test_ui_line_produces_no_turns() -> None:
    assert parse_luna_turns("Save Game 3") == []


def test_known_gap_colon_form_multi_speaker_is_not_split() -> None:
    """A documented limitation, kept at parity with the reference engine.

    "Rick: Hello there. Anne: Hi!" is two speakers in one line, but the
    bound-finder requires whitespace after a candidate name and here a
    colon follows, so the second speaker is not found and the whole line
    plays on Rick's voice.

    VN_Suite.py has the identical regex and the identical limitation. It
    is not fixed here on purpose: the reference is a build that has been
    run against real games, and deviating from it in a parser is how a
    rare case turns into a wrong-voice bug nobody can reproduce. This test
    exists so the limitation is visible rather than forgotten -- if it is
    ever fixed, this test is the thing to change.
    """
    turns = parse_luna_turns("Rick: Hello there. Anne: Hi!")
    assert len(turns) == 1
    assert turns[0].speaker == "Rick"
    assert turns[0].text == "Hello there. Anne: Hi!"


# --- raw propagation (the F1 contract) --------------------------------------


def test_raw_is_the_unmodified_hook_line() -> None:
    raw_in = "  Anne   Hallo!  Rick Mooi.  "
    d = parse_luna("Rick  Hello")
    assert d is not None
    # raw is the forensic record, so it keeps the spacing it arrived with.
    assert d.text == "Hello"
    assert d.raw == "Rick  Hello"
    for turn in parse_luna_turns(raw_in):
        assert turn.raw == raw_in


def test_all_split_turns_share_one_raw() -> None:
    """After a split the original line must stay reconstructable."""
    raw_in = "Anne Hallo! Rick Mooi."
    raws = {t.raw for t in parse_luna_turns(raw_in)}
    assert raws == {raw_in}


def test_dropped_line_is_none_not_an_empty_dialogue() -> None:
    """Dropping and narrating are different answers."""
    assert parse_luna("Save Game 3") is None
    narrated = parse_luna("You have your shower.")
    assert narrated is not None and narrated.speaker is None


# --- emotion tag interaction ------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "speaker", "text"),
    [
        # A leading capitalised tag must not be read as a character.
        ("*Laughs* Rick greets you.", None, "*Laughs* Rick greets you."),
        ("*Whispers* Come here.", None, "*Whispers* Come here."),
        # A tag after a real name is kept in the text; the emotion extractor
        # downstream removes it, so the parser must not strip it here.
        ("Rick *sighs* heavily.", "Rick", "*sighs* heavily."),
        ("Rick Hello *beeps* there.", "Rick", "Hello *beeps* there."),
    ],
)
def test_emotion_tags_do_not_become_speakers(raw: str, speaker: str | None, text: str) -> None:
    d = parse_luna(raw)
    assert d is not None
    assert d.speaker == speaker
    assert d.text == text


# --- the class wrapper ------------------------------------------------------


def test_parser_class_matches_the_module_functions() -> None:
    p = LunaParser()
    d = p.parse("Rick Hello there")
    assert d is not None
    assert d.speaker == "Rick"


def test_parser_class_uses_the_registry() -> None:
    p = LunaParser(known_names=["Rick", "Anne"])
    turns = p.parse_turns("Rick Hi there. Anne Bye.")
    assert [(t.speaker, t.text) for t in turns] == [("Rick", "Hi there."), ("Anne", "Bye.")]


def test_parser_class_registry_beats_the_heuristic() -> None:
    """A registered speaker is honoured even where the name set would refuse it.

    "Dr" is in the stopword set, so the heuristic would call it narration.
    Registration is the user overriding the heuristic, so it wins.
    """
    assert not is_plausible_character_name("Dr")
    p = LunaParser(known_names=["Dr"])
    turns = p.parse_turns("Dr Watts is in.")
    assert turns and turns[0].speaker == "Dr"


def test_a_registered_multi_word_name_opens_a_turn_in_every_form() -> None:
    """A registered two-word name is one name, in all three shapes.

    Pinned as a known gap and closed in F15. ``_NAME_TOKEN_SPACE`` matches a
    single capitalised word, so the boundary finder used to cut "Passenger 1"
    at "Passenger" and speak the rest of the name as dialogue -- a wrong voice
    rather than a crash, which is why it survived every earlier test.

    It was found by running a frame from a live LunaTranslator through the
    route, not by reading the code; the frames are in
    ``test_luna_adapter.py::TestRealLunaTranslatorFrames``. That is also why
    the closing tests were needed before the fix could be written: the defect
    only appears when a *real* capture shows up with a two-word speaker, and
    no hand-written case in this file had one.

    All three shapes are asserted because all three went through the same
    loop, and the colon form is the one with no ambiguity to blame -- the name
    is written out in full, and the splitter overrode it anyway.
    """
    reg = ["Passenger 1"]
    for line, expected in (
        ("Passenger 1\nHi there.", "Hi there."),
        ("Passenger 1 Hi there.", "Hi there."),
        ("Passenger 1: Hi there.", "Hi there."),
    ):
        turns = LunaParser(known_names=reg).parse_turns(line)
        assert [(t.speaker, t.text) for t in turns] == [("Passenger 1", expected)], line


def test_two_registered_multi_word_names_split_into_two_turns() -> None:
    """Two people, both named with a word and a digit, in one line.

    Guards ``covered_until``: without it the word inside an already-accepted
    name is offered as a boundary of its own, so the second name never opens.
    """
    p = LunaParser(known_names=["Passenger 1", "Passenger 2"])
    turns = p.parse_turns("Passenger 1 Hi there. Passenger 2 Bye.")
    assert [(t.speaker, t.text) for t in turns] == [
        ("Passenger 1", "Hi there."),
        ("Passenger 2", "Bye."),
    ]


def test_a_registered_name_is_not_matched_inside_a_longer_word() -> None:
    """"Work Inspector" must not reach into "Inspector2".

    The widening asks the registry for the longest name starting at a token,
    so it needs a word boundary of its own. Without the guard, the registered
    name claims four characters of a word it is not, and the turn that follows
    is swallowed whole.

    The input shape is not obvious and was got wrong first: the name has to be
    preceded by a sentence boundary, because ``_NAME_TOKEN_SPACE`` only anchors
    at the start of the line or after sentence-ending punctuation, so a name
    sitting at position 0 is never consulted. And "Rickardo" cannot test this at
    all, because the widening only applies when the registered name is *longer*
    than the matched token -- "Rick" is shorter than "Rickardo", so the guard is
    never reached.

    Measured F15: removing the guard changes the parse of 27 of 320 swept
    inputs, and this one still changes with a single name registered.

    The "Work" speaker that survives in the expected value is the heuristic
    guessing an unknown capitalised word, not the registry being honoured. That
    is a separate behaviour and pinned separately; this test is only about the
    registered name not bleeding into the next word.
    """
    p = LunaParser(known_names=["Work Inspector"])
    turns = p.parse_turns("Yeah. Work Inspector2 Hello there.")
    assert [(t.speaker, t.text) for t in turns] == [
        (None, "Yeah."),
        ("Work", "Inspector2 Hello there."),
    ]


def test_an_unregistered_multi_word_name_is_still_cut_at_its_first_word() -> None:
    """The widening is for registered names only.

    An unknown two-word line has to survive the heuristic on its own, exactly
    as before. "Cut the corporate talk." must keep reading as a sentence rather
    than becoming a speaker called "Cut".
    """
    p = LunaParser(known_names=[])
    turns = p.parse_turns("Meanwhile my office is here.")
    assert [(t.speaker, t.text) for t in turns] == [(None, "Meanwhile my office is here.")]


def test_parser_class_maps_case_to_the_registered_spelling() -> None:
    """Same contract as RenPyParser: a case-insensitive hit maps back to
    the exact registered name, so the registry lookup succeeds."""
    p = LunaParser(known_names=["Miss Brooks"])
    d = p.parse("miss brooks Hello there")
    assert d is not None


def test_parser_class_forwards_instruct() -> None:
    p = LunaParser()
    d = p.parse("Rick Hello", instruct="whisper")
    assert d is not None
    assert d.instruct == "whisper"


def test_parse_luna_forwards_instruct() -> None:
    d = parse_luna("Rick Hello", instruct="shout")
    assert d is not None
    assert d.instruct == "shout"


def test_max_name_len_is_enforced() -> None:
    too_long = "Bartholomew" * 2
    assert len(too_long) > _MAX_NAME_LEN
    assert not is_plausible_character_name(too_long)


# --- speaker provenance (F4) ------------------------------------------------


class TestSpeakerProvenance:
    """``Dialogue.speaker_is_guess``: was the name stated or inferred?

    The gate uses this to decide whether a speaker may be written to
    ``speakers.json``, so it has to be exact rather than approximate. It
    lives on the model because the multi-speaker splitter rewrites the
    line into colon form before the per-turn parse, which erases the
    difference -- by the time a caller holds the result, the parser is the
    only witness left.
    """

    def test_colon_form_is_stated(self) -> None:
        d = parse_luna("Rick: Hello")
        assert d is not None
        assert d.speaker == "Rick"
        assert d.speaker_is_guess is False

    def test_space_form_is_inferred(self) -> None:
        d = parse_luna("Rick Hello")
        assert d is not None
        assert d.speaker == "Rick"
        assert d.speaker_is_guess is True

    def test_registered_name_is_never_a_guess(self) -> None:
        """The user naming "Rick" outranks the heuristic that would have
        guessed him anyway."""
        d = parse_luna("Rick Hello", known_names=["Rick"])
        assert d is not None
        assert d.speaker_is_guess is False

    def test_renpy_shaped_name_is_stated(self) -> None:
        """The clipboard route sends "Rick: Hello", so nothing it produces
        is ever flagged -- which is what keeps the RenPy path's
        auto-registration unchanged."""
        d = LunaParser().parse("Rick: Hello")
        assert d is not None
        assert d.speaker_is_guess is False

    def test_narration_is_never_a_guess(self) -> None:
        d = parse_luna("You have your shower.")
        assert d is not None
        assert d.speaker is None
        assert d.speaker_is_guess is False

    def test_split_marks_only_the_invented_names(self) -> None:
        """In "Anne: Hallo! Rick Mooi." Anne is stated, Rick is not.

        No caller could reconstruct this afterwards: the splitter has
        already rewritten the line so both names look stated.
        """
        turns = parse_luna_turns("Anne: Hallo! Rick Mooi.")
        assert [(t.speaker, t.speaker_is_guess) for t in turns] == [
            ("Anne", False),
            ("Rick", True),
        ]

    def test_bare_space_form_split_marks_every_name(self) -> None:
        turns = parse_luna_turns("Anne Hallo! Rick Mooi.")
        assert [(t.speaker, t.speaker_is_guess) for t in turns] == [
            ("Anne", True),
            ("Rick", True),
        ]

    def test_a_registered_name_in_a_split_is_not_a_guess(self) -> None:
        turns = parse_luna_turns("Anne Hallo! Rick Mooi.", known_names=["Rick"])
        assert [(t.speaker, t.speaker_is_guess) for t in turns] == [
            ("Anne", True),
            ("Rick", False),
        ]

    def test_split_keeps_text_and_provenance_aligned(self) -> None:
        """Regression for the offset cut added alongside the flag.

        Cutting the pre-colon text while indexing the colon-normalised
        text shifts every bound after each inserted colon by one, which
        showed up as a turn losing its final character. Because the flag
        is attached by position, that same bug would also have attached
        the wrong provenance to each turn -- a silently wrong answer
        rather than a visible one.
        """
        turns = parse_luna_turns("Anne Hallo! Rick Mooi. Anne Bye.", known_names=["Rick"])
        assert [(t.text, t.speaker_is_guess) for t in turns] == [
            ("Hallo!", True),
            ("Mooi.", False),
            ("Bye.", True),
        ]

    def test_split_speaker_turns_public_contract_is_unchanged(self) -> None:
        """The provenance-aware cut is internal; the documented return
        type stays a list of colon-normalised strings."""
        assert split_speaker_turns("Anne Hallo! Rick Mooi.") == ["Anne: Hallo!", "Rick: Mooi."]
        assert split_speaker_turns("  ") == []
