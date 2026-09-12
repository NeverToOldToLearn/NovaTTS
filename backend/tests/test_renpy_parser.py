"""Tests for the strict RenPy parser."""

from novatts.models import Dialogue
from novatts.parser.renpy import RenPyParser

parser = RenPyParser()


def test_colon_speaker():
    d: Dialogue = parser.parse("Rick: Hi all.")
    assert d.speaker == "Rick"
    assert d.text == "Hi all."


def test_lowercase_prefix_is_narrator():
    d = parser.parse("rick: Hi all.")
    assert d.speaker is None
    assert d.text == "rick: Hi all."


def test_parenthesized_speaker_is_narrator():
    d = parser.parse("(narrator) It was a dark night.")
    assert d.speaker is None
    assert d.text == "It was a dark night."


def test_no_colon_is_narrator():
    d = parser.parse("Just some narration.")
    assert d.speaker is None
    assert d.text == "Just some narration."


def test_colon_in_middle_is_not_speaker():
    d = parser.parse("I said: hello everyone.")
    assert d.speaker is None
    assert d.text == "I said: hello everyone."


def test_multi_word_short_name_ok():
    d = parser.parse("Dr. Miller: Good morning.")
    assert d.speaker == "Dr. Miller"
    assert d.text == "Good morning."


def test_multi_word_long_prefix_is_narrator():
    d = parser.parse("Auto Forward selected: click to continue.")
    assert d.speaker is None
    assert d.text == "Auto Forward selected: click to continue."


def test_normalizes_whitespace():
    d = parser.parse("  Rick:   Hi   all.  ")
    assert d.speaker == "Rick"
    assert d.text == "Hi all."


def test_speaker_with_underscore():
    d = parser.parse("Mary_Jane: Hey Peter!")
    assert d.speaker == "Mary_Jane"
    assert d.text == "Hey Peter!"


def test_empty_text_is_not_voiceable():
    d = parser.parse("Rick:   ")
    assert d.is_voiceable is False


# -- user-registered names win over the strict heuristics -------------------


def test_known_name_with_number_wins():
    p = RenPyParser(known_names=["Passenger 1"])
    d = p.parse("Passenger 1: Move it!")
    assert d.speaker == "Passenger 1"
    assert d.text == "Move it!"


def test_known_long_name_wins():
    p = RenPyParser(known_names=["Charles Mettador Savieur"])
    d = p.parse("Charles Mettador Savieur: Greetings.")
    assert d.speaker == "Charles Mettador Savieur"


def test_known_name_case_insensitive_maps_to_canonical():
    p = RenPyParser(known_names=["Passenger 1"])
    d = p.parse("passenger 1: Hi.")
    assert d.speaker == "Passenger 1"  # canonical spelling, not the raw prefix


def test_unknown_offbeat_name_still_narrator():
    p = RenPyParser(known_names=["Passenger 1"])
    # A 3-word prefix that the user did NOT register stays narration,
    # so we don't start voice-mapping arbitrary text.
    d = p.parse("Fred Smith Jones: Hello.")
    assert d.speaker is None


def test_known_name_set_can_be_updated():
    p = RenPyParser(known_names=["Passenger 1"])
    assert p.parse("Passenger 1: A.").speaker == "Passenger 1"
    p.set_known_names(["New Guy"])
    assert p.parse("Passenger 1: A.").speaker is None
    assert p.parse("New Guy: B.").speaker == "New Guy"


def test_whitespace_normalization_in_known_set():
    p = RenPyParser(known_names=["  Passenger 1  "])
    assert p.parse("Passenger 1: A.").speaker == "Passenger 1"


def test_default_parser_no_known_names():
    p = RenPyParser()
    d = p.parse("Passenger 1: Move it!")
    assert d.speaker is None
