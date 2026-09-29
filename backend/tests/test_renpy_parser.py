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


# -- F14: the payload shape a real game actually produces -------------------
# Every string below is a verbatim copy from data/logs/clipboard_raw.log in
# the F14 session. Before F14 each of these was voiced as narration, with the
# speaker's name read out loud as part of the text.
#
# What was measured: the clipboard carries BOTH lines. The earlier docstring
# claimed the bare-name form was only recoverable via
# NOVATTS_HOOK_DUAL_HOOK=1; the 78-character payload in that log contains
# the newline, so the information was never thrown away -- only unread.

REAL_PLAIN = "Tatsuo\nThe girl with the bag of groceries says something about how healthy she eats."
REAL_HTML = "<b>Tatsuo</b>\nEach pawn has a story half concealed."


def test_bare_name_line_becomes_speaker():
    d = parser.parse(REAL_PLAIN)
    assert d.speaker == "Tatsuo"
    assert d.text == "The girl with the bag of groceries says something about how healthy she eats."


def test_bare_name_line_with_html_tags():
    d = parser.parse(REAL_HTML)
    assert d.speaker == "Tatsuo"
    assert d.text == "Each pawn has a story half concealed."
    assert "<" not in d.text


def test_bare_name_line_survives_crlf_and_blank_lines():
    # The payload as it actually arrived: a leading newline, CRLF endings and
    # a stray space in front of the tag.
    raw = "\r\n <b>Tatsuo</b>\r\nAnd with every belonging their secret gets revealed.\r\n"
    d = parser.parse(raw)
    assert d.speaker == "Tatsuo"
    assert d.text == "And with every belonging their secret gets revealed."


def test_bare_name_line_body_containing_a_colon():
    # Joined into one line this parses as a speaker called "Tatsuo Hello",
    # so the bare-name branch has to be tried before the colon branch.
    d = parser.parse("Tatsuo\nHello: world.")
    assert d.speaker == "Tatsuo"
    assert d.text == "Hello: world."


def test_bare_name_line_maps_to_the_registered_spelling():
    p = RenPyParser(known_names=["Tatsuo"])
    d = p.parse("tatsuo\nMove it!")
    assert d.speaker == "Tatsuo"


def test_bare_name_line_caps_maps_to_the_registered_spelling():
    # An all-caps name line *does* pass the strict rules, so the registry has
    # to be consulted first -- otherwise "TATSUO" is returned verbatim and
    # main.py registers it as a second speaker with a second voice.
    p = RenPyParser(known_names=["Tatsuo"])
    d = p.parse("TATSUO\nMove it!")
    assert d.speaker == "Tatsuo"


def test_bare_name_line_registered_long_name_wins():
    # 3 words, so the strict heuristics reject it -- the registry still wins,
    # exactly as it does for the "Name: text" form.
    p = RenPyParser(known_names=["Charles Mettador Savieur"])
    d = p.parse("Charles Mettador Savieur\nGreetings.")
    assert d.speaker == "Charles Mettador Savieur"
    assert d.text == "Greetings."


# -- the false positives the bare-name rule has to refuse -------------------
# The rule is "first line is a name". These are the ways that is wrong.


def test_one_word_sentence_is_not_a_speaker():
    d = parser.parse("Hello.\nThis is a test.")
    assert d.speaker is None
    assert d.text == "Hello. This is a test."


def test_question_line_is_not_a_speaker():
    d = parser.parse("What?\nNothing at all.")
    assert d.speaker is None


def test_long_first_line_is_narration():
    d = parser.parse(
        "The girl with the bag of groceries says something\n"
        "about how healthy she eats."
    )
    assert d.speaker is None
    assert d.text == "The girl with the bag of groceries says something about how healthy she eats."


def test_stopword_first_line_is_narration():
    d = parser.parse("The\ngirl with the bag.")
    assert d.speaker is None
    assert d.text == "The girl with the bag."


def test_lowercase_first_line_is_narration():
    d = parser.parse("tatsuo\nSomething happened.")
    assert d.speaker is None
    assert d.text == "tatsuo Something happened."


def test_single_line_narration_is_untouched():
    # The other real shape in that log: narration with no name at all.
    d = parser.parse("What will be your next move?")
    assert d.speaker is None
    assert d.text == "What will be your next move?"


def test_colon_form_is_untouched():
    # The pre-F14 shape must keep working exactly as before.
    d = parser.parse("Rick: Hi all.")
    assert d.speaker == "Rick"
    assert d.text == "Hi all."


# -- markup -----------------------------------------------------------------


def test_entities_are_decoded():
    d = parser.parse("Tatsuo\nHe said &quot;hi&quot; &amp; left.")
    assert d.speaker == "Tatsuo"
    assert d.text == 'He said "hi" & left.'


def test_escaped_tags_stay_readable_text():
    # &lt;b&gt; is text the game wrote, not formatting: tags are stripped
    # before entities are decoded, so this survives as visible text.
    d = parser.parse("Tatsuo\nWrite &lt;b&gt;bold&lt;/b&gt; here.")
    assert d.text == "Write <b>bold</b> here."


def test_line_break_tag_does_not_glue_words():
    d = parser.parse("Tatsuo\none<br/>two")
    assert d.text == "one two"


def test_markup_only_payload_is_not_voiceable():
    d = parser.parse("<b></b>")
    assert d.is_voiceable is False


# -- pinned limitation (D41) -----------------------------------------------


def test_a_block_of_pairs_stays_one_turn():
    """Pinned, not wished for: a block of pairs stays a single turn.

    RenPyParser returns one Dialogue, so only the first name becomes a
    speaker and the later ones are read aloud inside the text.

    This is real, not hypothetical: measured on the user's own clipboard log
    in F14, 3 of the 61 multi-line payloads held two or three pairs. The pin
    exists to say "we know", not "we suspect" -- an earlier draft of this
    docstring claimed the case had not been observed, and that was wrong.
    A 5% rate reported as zero reads as reassurance.

    If this test fails because the block *was* split, the class contract
    changed and every caller has to be revisited; do not just delete the
    assertion.
    """
    d = parser.parse("Tatsuo\nFirst line.\nAnna\nSecond line.")
    assert d.speaker == "Tatsuo"
    assert d.text == "First line. Anna Second line."
