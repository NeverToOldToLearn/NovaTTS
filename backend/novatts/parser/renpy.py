"""Strict RenPy dialogue parser.

RenPy's ``copy_voice_to_clipboard`` emits ``Name: Text``. We accept a
speaker only when it passes strict rules — otherwise the line is
treated as narration (speaker=None) and never auto-registers.

Strict rules (all must hold):
- At most 2 words, first word starts with an uppercase letter.
- First word is not a common English narration starter ("I said: ...")
  or UI chrome.
- "(narrator)"/"(narrator):" prefixes are narration.

Two robustness rules for visual-novel clipboard noise:
- Decoration around the name is stripped, so ``/ Rick: Hi`` keeps Rick's
  voice instead of falling through to the narrator (which would read the
  slash and the name out loud).
- A leading token that cannot be a speaker (a HUD value, a menu label) is
  treated as noise and skipped, so ``250 $: Rick: Hi`` resolves to Rick.
  This is what keeps a game with a permanently visible UI from sending
  every line to the narrator.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import Dialogue

_COLON_PATTERN = re.compile(r"^\s*(?P<name>[^:]{1,40})\s*:\s*(?P<line>\S.*?)\s*$")
_PAREN_COLON_PATTERN = re.compile(r"^\s*\((?P<name>[^)]+)\)\s*:\s*(?P<line>\S.*?)\s*$")
_PAREN_PATTERN = re.compile(r"^\s*\((?P<name>[^)]+)\)\s*(?P<line>\S.*?)\s*$")
# Candidate speaker tags anywhere in the line, used for history-stripping
# (see _strip_history). Deliberately tight -- at most 2 words, each starting
# with an uppercase letter -- so a stale prefix can never be swallowed into
# the tag itself ("... Caroline gav Samantha:" must yield "Samantha", not
# "Caroline gav Samantha"). Longer / lowercase registered names are handled
# separately via an explicit search in _strip_history.
_HISTORY_TAG_PATTERN = re.compile(r"(?P<name>[A-Z][^:\s]{0,29}(?: [A-Z][^:\s]{0,29})?)\s*:\s+(?P<line>\S)")

_MAX_SPEAKER_WORDS = 2

# Punctuation some VNs put in front of a name ("/ Rick:", "- Rick:",
# "> Rick:", "#Rick:"). Stripped from the name candidate before validation.
# Deliberately narrow: only characters that can never start or end a real
# name, so quoted narration ('Hello: world') keeps staying narration.
_NAME_DECORATION = re.compile(r"^[/\\|>#~•\-–—]+|[\-–—_]+$")

# How many junk prefixes ("250 $:", "Menu:") to skip before giving up.
_MAX_PREFIX_SKIP = 3

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


def _strip_decoration(name: str) -> str:
    """Remove leading/trailing punctuation from a speaker candidate.

    ``"/ Rick"`` -> ``"Rick"``, ``"- Rick -"`` -> ``"Rick"``. The raw
    clipboard string is re-parsed on the stripped name, so the decoration
    is dropped instead of being handed to the TTS engine.
    """
    cleaned = _NAME_DECORATION.sub("", name)
    # A separator between a decoration and the name ("/ Rick") leaves a
    # space behind; collapse it so the name is not seen as "/ Rick".
    return " ".join(cleaned.split())


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

    def has_known_speaker_prefix(self, text: str) -> bool:
        """Whether ``text`` starts with ``Name: `` where ``Name`` is a
        *registered* speaker (decoration ignored, so ``/ Rick:`` counts).

        Callers that rewrite a line in place (the blacklist) use this to
        keep a real speaker name from being filtered away while still
        filtering everything around it.
        """
        text = _normalize_text(text)
        m = _COLON_PATTERN.match(text)
        if m is None:
            return False
        name = _strip_decoration(m.group("name"))
        return bool(name) and self._known.get(name.lower()) is not None

    def parse(self, raw: str, source: str = "renpy", instruct: str = "", _skip: int = 0) -> Dialogue:
        text = _normalize_text(raw)
        if not text:
            return Dialogue(speaker=None, text="", source=source)
        # The game sometimes puts dialogue history on the clipboard ahead of
        # the current line ("<stale fragment>  Name: <current line>"). The
        # stale prefix has no speaker tag of its own, so without this the
        # whole blob falls through to narration and TTS speaks the fragment
        # plus the line back to back -- the "dubbel" from the log. Keep only
        # the segment after the LAST valid speaker tag.
        text = self._strip_history(text)

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
            raw_name = _strip_decoration(m.group("name").strip())
            raw_line = _normalize_text(m.group("line"))
            if not raw_line:
                # "Rick:" with no dialogue — keep the speaker, nothing to say.
                speaker = self._clean_speaker(raw_name)
                return Dialogue(speaker=speaker, text="", source=source, instruct=instruct)
            # A user-registered name always wins over the strict heuristics,
            # and maps to its canonical spelling so the registry matches.
            canonical = self._known.get(raw_name.lower()) if raw_name else None
            if canonical is not None:
                return Dialogue(speaker=canonical, text=raw_line, source=source, instruct=instruct)
            speaker = self._clean_speaker(raw_name)
            if speaker is not None:
                return Dialogue(speaker=speaker, text=raw_line, source=source, instruct=instruct)
            # The prefix cannot be a speaker (a HUD value like "250 $", a
            # menu label, ...). If the rest is itself "Name: text", drop
            # the noise and speak the real line; otherwise keep the whole
            # line as narration.
            if _skip < _MAX_PREFIX_SKIP:
                inner = self.parse(raw_line, source=source, instruct=instruct, _skip=_skip + 1)
                if inner.speaker is not None:
                    return inner
            return Dialogue(speaker=None, text=text, source=source, instruct=instruct)

        # No colon: plain narration.
        return Dialogue(speaker=None, text=text, source=source, instruct=instruct)

    def _strip_history(self, text: str) -> str:
        """Drop stale history ahead of the current line, if any.

        The game sometimes puts dialogue history on the clipboard ahead of
        the current line ("<stale fragment>  Name: <current line>"). The
        stale prefix carries no speaker tag of its own, so the tag of the
        current line sits past position 0 -- which never happens for a
        clean single capture (leading whitespace is already normalized
        away). In that case keep only the segment from the LAST valid tag
        on (a registered name wins, otherwise the strict heuristics).

        Tags that fail validation -- times ("12:00"), narration starters
        ("I said: ...") -- are skipped, so a plain line comes back
        unchanged. Registered names that the tight pattern cannot express
        (3+ words, lowercase start) are searched explicitly. Tradeoff:
        narration with a valid-looking ``Name:`` tag mid-sentence is treated
        as history + line; that shape is rare in VNs while history blobs are
        observed on every affected capture.
        """
        # 0. A clean line starting with a registered tag is returned as-is,
        #    so step 2 can never strip a suffix off a multi-word name
        #    ("Charles Mettador Savieur:" -> "Mettador Savieur:").
        for key in sorted(self._known, key=len, reverse=True):
            if not key:
                continue
            if re.match(re.escape(key) + r"\s*:\s+\S", text, re.IGNORECASE):
                return text
        # 1. Registered names first (longest first so "Ann" never shadows
        #    "Ann Marie"). Case-insensitive, mapped back by parse().
        for key in sorted(self._known, key=len, reverse=True):
            if not key:
                continue
            pat = re.compile(re.escape(key) + r"\s*:\s+\S", re.IGNORECASE)
            found = [m for m in pat.finditer(text) if m.start() > 0]
            if found:
                return text[found[-1].start():].strip()
        # 2. Strict 1-2 word tags: the last one wins, but only when the prefix
        #    ahead of it is longer than any valid single tag (40 chars, the
        #    same cap _COLON_PATTERN uses). That keeps short multi-word
        #    prefixes untouched ("Fred Smith Jones: Hello." stays narration
        #    per the strict rules) while history blobs -- whose stale prefix
        #    is a whole sentence fragment -- are stripped.
        matches = [m for m in _HISTORY_TAG_PATTERN.finditer(text) if m.start("name") > 40]
        for m in reversed(matches):
            if self._clean_speaker(m.group("name").strip()) is not None:
                return text[m.start("name"):].strip()
        return text

    @staticmethod
    def _clean_speaker(raw: str) -> str | None:
        if not raw:
            return None
        words = _strip_decoration(raw).split()
        if not words or len(words) > _MAX_SPEAKER_WORDS:
            return None
        if words[0].lower() in _NARRATION_STOPLIST:
            return None
        if not all(_word_passes(w) for w in words):
            return None
        return " ".join(words)
