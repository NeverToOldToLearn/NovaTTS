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


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


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
        text = _normalize_text(raw)
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
