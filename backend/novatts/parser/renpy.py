"""Strict RenPy dialogue parser.

RenPy's ``copy_voice_to_clipboard`` emits ``Name: Text``. We accept a
speaker only when it passes strict rules — otherwise the line is
treated as narration (speaker=None) and never auto-registers.

Strict rules (all must hold):
- At most 2 words, first word starts with an uppercase letter.
- First word is not a common English narration starter ("I said: ...")
  or UI chrome.
- "(narrator)"/"(narrator):" prefixes are narration.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import Dialogue
from .markup import strip_markup

_COLON_PATTERN = re.compile(r"^\s*(?P<name>[^:]{1,40})\s*:\s*(?P<line>\S.*?)\s*$")
_PAREN_COLON_PATTERN = re.compile(r"^\s*\((?P<name>[^)]+)\)\s*:\s*(?P<line>\S.*?)\s*$")
_PAREN_PATTERN = re.compile(r"^\s*\((?P<name>[^)]+)\)\s*(?P<line>\S.*?)\s*$")

_MAX_SPEAKER_WORDS = 2

# Common English sentence-starters that must never become speakers.
_NARRATION_STOPLIST = frozenset(
    {
        "i",
        "it",
        "its",
        "the",
        "this",
        "that",
        "these",
        "those",
        "you",
        "he",
        "she",
        "they",
        "we",
        "them",
        "him",
        "her",
        "there",
        "here",
        "now",
        "then",
        "when",
        "what",
        "where",
        "which",
        "who",
        "why",
        "how",
        "so",
        "and",
        "but",
        "one",
        "all",
        "some",
        "if",
        "as",
        "auto",
        "click",
        "press",
        "wait",
    }
)


# Punctuation a bare name line never ends with. "Tatsuo" is a name on a
# line of its own; "Hello." on a line of its own is the start of a sentence.
# Without this rule a one-word sentence becomes a speaker named after it.
_NAME_LINE_ENDINGS = frozenset(".!?,;:")

def _normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


def _content_lines(raw: str) -> list[str]:
    """Non-empty stripped lines, whatever newline style the source used."""
    unified = raw.replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in unified.split("\n") if line.strip()]


def _word_passes(word: str) -> bool:
    """True if one token of a name looks like a proper name word."""
    if not word:
        return False
    base = word.rstrip(".").rstrip("'")
    if not base:
        return False
    return base[0].isalpha() and base[0].isupper()


class RenPyParser:
    """Parses a single raw clipboard string into a Dialogue.

    A colon-prefix that case-insensitively matches an entry in
    ``known_names`` is treated as that speaker even when it would fail the
    strict heuristics (e.g. "Passenger 1" or a long multi-word name). This
    lets user-registered speakers win over the heuristics while keeping the
    strict rules for everything else.

    Two payload shapes are accepted, because both were measured arriving
    from a real game (F14, ``data/logs/clipboard_raw.log``):

      * ``"Rick: Hi all."`` -- Ren'Py's own ``Name: Text``.
      * ``"Rick\\nHi all."`` -- a bare name on its own line. This is what
        LunaTranslator copies, with or without ``<b>`` tags around the name.

    The second shape only counts as a speaker when the first line passes the
    same strict rules as a colon-prefix *and* does not end in sentence
    punctuation; anything else is narration, joined exactly as before. Only
    the *first* name is split off: a payload holding several name/text pairs
    stays one turn with the later names read aloud, because this class
    returns a single :class:`Dialogue`. That case is real, not hypothetical
    -- measured on the user's own clipboard log in F14, 3 of the 61
    multi-line payloads held two or three pairs. Pinned, not fixed; see
    ``test_a_block_of_pairs_stays_one_turn``.
    """

    def __init__(self, known_names: Iterable[str] = ()) -> None:
        self.set_known_names(known_names)

    def set_known_names(self, names: Iterable[str]) -> None:
        """Replace the set of case-insensitive names treated as speakers.

        Stores the canonical (registry) spelling per lowercased key so a
        clipboard name matching case-insensitively maps back to the exact
        registered name (e.g. "alex: ..." -> "Alex").
        """
        self._known: dict[str, str] = {}
        for n in names:
            if n and n.strip():
                self._known[n.strip().lower()] = n.strip()

    def parse(self, raw: str, source: str = "renpy", instruct: str = "") -> Dialogue:
        cleaned = strip_markup(raw)

        # "Name" on its own line, then the dialogue. Checked first: joined
        # into one line it would otherwise be narration, or -- if the body
        # happens to contain a colon -- a speaker made of both lines.
        bare = self._bare_name_form(cleaned)
        if bare is not None:
            name, body = bare
            # A registered name wins and maps to its canonical spelling,
            # exactly as in the "Name: text" branch below.
            speaker = self._known.get(name.lower()) or self._clean_speaker(name)
            return Dialogue(
                speaker=speaker, text=body, source=source, instruct=instruct
            )

        text = _normalize_text(cleaned)
        if not text:
            return Dialogue(speaker=None, text="", source=source)

        # Parenthesized narrator prefix, with or without a colon.
        for pattern in (_PAREN_COLON_PATTERN, _PAREN_PATTERN):
            m = pattern.match(text)
            if m is not None:
                return Dialogue(
                    speaker=None,
                    text=_normalize_text(m.group("line")),
                    source=source,
                    instruct=instruct,
                )

        # "Name:" with nothing after it (colon at end of line).
        if text.endswith(":"):
            raw_name = text[:-1].strip()
            speaker = self._clean_speaker(raw_name)
            return Dialogue(speaker=speaker, text="", source=source, instruct=instruct)

        # "Name: text" form.
        m = _COLON_PATTERN.match(text)
        if m is not None:
            raw_name = m.group("name").strip()
            raw_line = _normalize_text(m.group("line"))
            if not raw_line:
                # "Rick:" with no dialogue — keep the speaker, nothing to say.
                speaker = self._clean_speaker(raw_name)
                return Dialogue(speaker=speaker, text="", source=source, instruct=instruct)
            # A user-registered name always wins over the strict heuristics,
            # and maps to its canonical spelling so the registry matches.
            canonical = self._known.get(raw_name.lower())
            if canonical is not None:
                return Dialogue(speaker=canonical, text=raw_line, source=source, instruct=instruct)
            speaker = self._clean_speaker(raw_name)
            if speaker is not None:
                return Dialogue(speaker=speaker, text=raw_line, source=source, instruct=instruct)
            # Colon-prefix that failed the name rules: keep the whole line.
            return Dialogue(speaker=None, text=text, source=source, instruct=instruct)

        # No colon: plain narration.
        return Dialogue(speaker=None, text=text, source=source, instruct=instruct)

    def _bare_name_form(self, raw: str) -> tuple[str, str] | None:
        """Split ``"Name\\nText"`` into ``(name, text)``, or None.

        None means "not this shape", and the caller then parses the payload
        as a single line -- which is what every payload looked like before
        F14, and is still what a single-line narration looks like.
        """
        lines = _content_lines(raw)
        if len(lines) < 2:
            return None
        name = lines[0]
        body = _normalize_text(" ".join(lines[1:]))
        if not body:
            return None
        if name[-1] in _NAME_LINE_ENDINGS:
            return None
        if self._known.get(name.lower()) is None and self._clean_speaker(name) is None:
            return None
        return name, body

    @staticmethod
    def _clean_speaker(raw: str) -> str | None:
        if not raw:
            return None
        words = raw.split()
        if not words or len(words) > _MAX_SPEAKER_WORDS:
            return None
        if words[0].lower() in _NARRATION_STOPLIST:
            return None
        if not all(_word_passes(w) for w in words):
            return None
        return raw
