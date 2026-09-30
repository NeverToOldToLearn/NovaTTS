"""The markup helper both input routes share, and the agreement between them.

F14 follow-up. The original defect was not "markup was mishandled" but
"markup was handled on one route and not the other": ``strip_markup`` sat
private in ``parser/renpy.py``, so the clipboard route stripped tags and the
websocket route read them aloud. Measured on the user's log: 23 of 124
accepted payloads carried a tag, and 16 of the 90 multiline payloads were
``<b>Name</b>`` on its own line -- all 16 spoken with the narrator's voice
before the fix, all 16 with the right voice after it.

So the tests here come in two kinds. The agreement tests pin that both routes
now give the same answer for the payloads that carry markup -- that is the
regression that actually happened, and it cannot come back silently. The
difference tests pin the three payloads where the routes *should* disagree,
with the reason in the name, so that anyone changing one of them has to read
why first.

Every expected value here is copied from running the code, not from reading
it. The payloads are verbatim from ``data/logs/clipboard_raw.log``.
"""

from __future__ import annotations

import pytest

from novatts.adapters.luna import HookTextProcessor
from novatts.parser.markup import strip_markup
from novatts.parser.renpy import RenPyParser

REGISTRY = ["Tatsuo", "Narrator"]


class TestStripMarkup:
    """The contract of the shared helper itself."""

    def test_a_tag_becomes_a_space(self) -> None:
        # A space, not nothing: "a<br/>b" must not become "ab".
        assert strip_markup("a<br/>b") == "a b"

    def test_entities_are_decoded(self) -> None:
        assert strip_markup("it&rsquo;s") == "it’s"

    def test_an_escaped_tag_stays_readable_text(self) -> None:
        """Tags are removed *before* entities are decoded (D51).

        Reversed, "&lt;b&gt;Hi&lt;/b&gt;" would decode to "<b>Hi</b>" and then
        be stripped as if it were markup, leaving nothing at all.
        """
        assert strip_markup("&lt;b&gt;Hi&lt;/b&gt;") == "<b>Hi</b>"

    def test_a_comparison_is_not_a_tag(self) -> None:
        """A tag needs a name; a comparison only has a number.

        The looser pattern this replaced, ``<[^<>]{0,200}>``, also matched
        ``< b and c >`` and so deleted a comparison instead of cleaning it.
        In a puzzle game that is a plausible line of dialogue.
        """
        assert strip_markup("a < b and c > d") == "a < b and c > d"
        assert strip_markup("5<10 and 10>5") == "5<10 and 10>5"

    def test_a_color_tag_with_a_hash_is_stripped(self) -> None:
        """Game markup writes attributes with no space: "<color=#E0BCE7>".

        Measured F20 on a live hook frame: the old pattern demanded leading
        whitespace in the attribute group, so the opening tag survived, the
        speaker check failed on the "<", and the color code was synthesized
        with an empty voice.
        """
        assert strip_markup("<color=#E0BCE7>Tatsuo") == " Tatsuo"
        assert strip_markup("weren\u2019t you?</color>") == "weren\u2019t you? "

    def test_a_plain_equals_comparison_is_not_a_tag(self) -> None:
        """The "=" allowance must not eat text without angle brackets."""
        assert strip_markup("a=b and c=d") == "a=b and c=d"
        assert strip_markup("5<10 and 10>5") == "5<10 and 10>5"

    def test_plain_text_is_untouched(self) -> None:
        assert strip_markup("Tatsuo\nConsider it your lucky day.") == (
            "Tatsuo\nConsider it your lucky day."
        )

    def test_an_unclosed_angle_bracket_does_not_match(self) -> None:
        # No closing ">", so not a tag, and the 200 bound stops a long
        # unclosed run from being treated as one enormous tag either.
        payload = "open <" + "x" * 5000
        assert strip_markup(payload) == payload


def _luna(raw: str) -> list[tuple[str | None, str]]:
    processor = HookTextProcessor(min_text_length=4, known_names=REGISTRY)
    return [(d.speaker, d.text) for d in processor.push(raw)]


def _renpy(raw: str) -> list[tuple[str | None, str]]:
    dialogue = RenPyParser(REGISTRY).parse(raw)
    return [] if dialogue is None else [(dialogue.speaker, dialogue.text)]


#: (id, payload) for every payload where both routes must agree. The markup
#: ones are the F14 regression; the plain ones guard against a future
#: "normalise harder" edit that changes one route only.
AGREE: list[tuple[str, str]] = [
    ("bare_name_on_its_own_line", "Tatsuo\nConsider it your lucky day."),
    (
        "name_wrapped_in_bold",
        "<b>Tatsuo</b>\nThe girl with the bag of groceries says something "
        "about how healthy she eats.",
    ),
    (
        "whole_line_wrapped_in_bold",
        "<b>“George from work: Love you lots, I’ll wait for you :D”</b>",
    ),
    (
        "narration_with_a_bold_name_inside",
        ". . . I know you can hear me, <b>Chronos</b>\n. . . I know you can "
        "hear me, <b>Chronos</b>.",
    ),
    (
        "bare_name_then_bold_dialogue",
        "Tatsuo\n<b>“George from work: Did your wife let you come "
        "today?”</b>",
    ),
    ("colon_form", "Anna: Move it!"),
    (
        "colored_name_colon_form",
        "<color=#E0BCE7>Tatsuo: You actually hoped my powers are legit. You were  \n"
        "curious how that feels during sex, weren\u2019t you?</color>\n",
    ),
    ("an_escaped_tag_is_text", "&lt;b&gt;Hi&lt;/b&gt;"),
]


#: Every AGREE payload except the escaped-tag one, which is the documented
#: exception: "&lt;b&gt;Hi&lt;/b&gt;" decodes to the readable text "<b>Hi</b>"
#: and is *meant* to reach TTS with its angle brackets (D51). Asserting "no
#: angle bracket survives" over it would assert the opposite of the rule.
WITH_REAL_TAGS = [pair for pair in AGREE if pair[0] != "an_escaped_tag_is_text"]


class TestRoutesAgree:
    @pytest.mark.parametrize(("label", "payload"), AGREE, ids=[i for i, _ in AGREE])
    def test_both_routes_give_the_same_turn(self, label: str, payload: str) -> None:
        assert _luna(payload) == _renpy(payload), label

    @pytest.mark.parametrize(
        ("label", "payload"), WITH_REAL_TAGS, ids=[i for i, _ in WITH_REAL_TAGS]
    )
    def test_no_tag_survives_into_the_spoken_text(self, label: str, payload: str) -> None:
        for _speaker, text in _luna(payload):
            assert "<" not in text and ">" not in text, label

    def test_a_bold_name_becomes_the_speaker_not_a_word(self) -> None:
        """The specific line the fix exists for.

        Before it, ``<b>Tatsuo</b>`` failed ``is_name_only`` and was read
        aloud as narration, which put the character name in the narrator's
        mouth and picked the wrong voice.
        """
        assert _luna(
            "<b>Tatsuo</b>\nThe girl with the bag of groceries says something "
            "about how healthy she eats."
        ) == [
            (
                "Tatsuo",
                "The girl with the bag of groceries says something about how "
                "healthy she eats.",
            )
        ]

    def test_raw_keeps_the_tags_for_forensics(self) -> None:
        """Stripping the text must not rewrite the evidence."""
        payload = "<b>Tatsuo</b>\nConsider it your lucky day."
        out = HookTextProcessor(min_text_length=4, known_names=REGISTRY).push(payload)
        assert {d.raw for d in out} == {payload}


class TestDocumentedRouteDifferences:
    """Where the two routes should *not* agree, and why.

    These are pinned rather than fixed. Each one is a consequence of a rule
    that exists on purpose on one route and has no counterpart on the other,
    so a test that simply demanded agreement would be asserting that those
    rules go away.
    """

    def test_a_name_alone_is_dropped_by_the_hook_and_spoken_by_the_clipboard(
        self,
    ) -> None:
        """``is_name_only`` drops it unless dual_hook is on.

        Deliberate and commented at the branch: with the merge off there is
        no dialogue attached, and speaking a bare name is never wanted. The
        clipboard route has no such branch, so it reads it as narration.
        """
        assert _luna("Tatsuo") == []
        assert _renpy("Tatsuo") == [(None, "Tatsuo")]

    def test_a_line_break_tag_reads_as_a_space_on_the_hook(self) -> None:
        """``<br/>`` on one line.

        The hook route splits on it and finds a speaker; the clipboard route
        joins and finds narration. Not a real clipboard shape -- the clipboard
        delivers real newlines, which is why this never showed up in the log
        -- but the hook does send one-line payloads, so the difference is
        kept visible instead of papered over.
        """
        assert _luna("Tatsuo<br/>Consider it your lucky day.") == [
            ("Tatsuo", "Consider it your lucky day.")
        ]
        assert _renpy("Tatsuo<br/>Consider it your lucky day.") == [
            (None, "Tatsuo Consider it your lucky day.")
        ]

    def test_an_ampersand_in_a_name_is_one_route_only(self) -> None:
        """``Tatsuo &amp; Co`` on its own line.

        The hook's ``_NAME_ONLY`` accepts the two words and the entity decodes
        inside them; the clipboard's bare-name rule stops at the ``&``. No such
        payload appears in the log, so neither answer is known to be the one
        the user wants -- which is why it is pinned as a difference rather
        than resolved here.
        """
        assert _luna("Tatsuo &amp; Co\nMove it!") == [("Tatsuo", "& Co Move it!")]
        assert _renpy("Tatsuo &amp; Co\nMove it!") == [(None, "Tatsuo & Co Move it!")]
