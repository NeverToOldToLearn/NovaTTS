"""LunaTranslator hook parser.

LunaTranslator's built-in web server (default port 2333) exposes
``/api/ws/text/origin``: a websocket that pushes every line Luna captured
from the game, after Luna's own post-processing. For RPG Maker MV games the
payload keeps the hook's inline markup, e.g.::

    <WordWrap>\\n<\\c[2]Man>\\c[0]\\sa[10]Tch! If I ever see you ...\\n<WordWrap>\\da[10]

The ``<\\c[2]Man>`` tag is the game's own speaker marker, making it a much
better speaker source than splitting on a colon. The same payload can also
carry a second, duplicated rendering of the line and, when several hooks are
selected in Luna, unrelated JavaScript file paths; the parser keeps the first
usable dialogue segment and drops the rest.

RPG Maker also stores some names as numeric placeholders: ``\\n[1]`` (or the
upper-case ``\\N[1]``) is actor 1's name, both inside a speaker tag
(``<\\c[14]\\n[1]>``) and mid-sentence (``I'm not leaving \\n[1]'s side.``).
The resolved spelling is game-specific, so it comes from ``actor_names``
(``"1=Rick,2=Otsu"``); without a mapping the placeholder is dropped and a
tagged line simply has no speaker.

When no speaker tag is present (another hook engine, or a Luna config that
strips angle brackets) the parser falls back to the loose ``Name: text`` form
and, only for names already in the speaker registry, ``Name text``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..models import Dialogue

# ``<c[2]Man>`` and ``<\c[2]Man>``. The colour index itself is irrelevant;
# the text between the bracket and ``>`` is the speaker.
_SPEAKER_TAG = re.compile(r"<\s*\\?[cC]\[\d+\]\s*(?P<name>[^<>]{1,40}?)\s*>")
# The same marker rendered as an ANSI sequence: ESC + ``c[2]Man``.
_ESC_SPEAKER_TAG = re.compile(r"\x1b[cC]\[\d+\]\s*(?P<name>[^\\\x1b<>\n]{1,40})")

# RPG Maker name placeholders: \n[1] / \N[1] (actor) and \p[1] / \P[1]
# (party member). Must be handled BEFORE literal ``\n`` becomes a newline.
_NAME_CODE = re.compile(r"\\+[nNpP]\[(?P<num>\d+)\]")
# Any angle-bracketed hook tag (<WordWrap>, <c[2]Man>, <br>, ...).
_ANGLE_TAG = re.compile(r"<[^<>]*>")
# RPG Maker / hook control codes: \c[2], \sa[10], \fs[25], \ow[4], \fb,
# \N[1], and doubled escapes.
_CONTROL_CODE = re.compile(r"\\+[A-Za-z]+(?:\[[^\]]*\])?")
# ANSI escapes, including the ``\x1bc[2]`` form LunaHook emits.
_ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-9;]*[A-Za-z]|[A-Za-z]+(?:\[[^\]]*\])?)")
# An unresolved placeholder leaves an orphan possessive: "leaving 's side".
_ORPHAN_POSSESSIVE = re.compile(r"\s+'[sS]\b")

# Loose colon form: "Rick: Hi all." -> speaker Rick. Deliberately conservative.
_NAME_LINE = re.compile(r"^\s*(?P<name>[A-Z][A-Za-z0-9 .'\-]{0,29}?)\s*:\s*(?P<line>\S.*)$")

_MAX_NAME_WORDS = 3
_MAX_NAME_LEN = 30

# Sentence starters that must never become a speaker in the loose forms.
_NAME_STOPWORDS = frozenset(
    {
        "a",
        "all",
        "almost",
        "an",
        "and",
        "are",
        "as",
        "at",
        "back",
        "because",
        "beside",
        "besides",
        "but",
        "by",
        "can",
        "chapter",
        "come",
        "day",
        "did",
        "do",
        "either",
        "even",
        "for",
        "from",
        "get",
        "go",
        "good",
        "got",
        "great",
        "had",
        "hairs",
        "has",
        "have",
        "he",
        "hello",
        "her",
        "here",
        "hey",
        "hi",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "just",
        "let",
        "like",
        "look",
        "maybe",
        "me",
        "men",
        "meanwhile",
        "my",
        "next",
        "nice",
        "no",
        "not",
        "now",
        "of",
        "ok",
        "okay",
        "on",
        "one",
        "or",
        "our",
        "out",
        "please",
        "problems",
        "right",
        "said",
        "say",
        "see",
        "seeing",
        "she",
        "so",
        "some",
        "something",
        "sorry",
        "sure",
        "than",
        "thank",
        "thanks",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "too",
        "up",
        "us",
        "walking",
        "was",
        "we",
        "well",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "yes",
        "you",
        "your",
    }
)

# "Name <verb> ..." reads as narration about the name, not speech by it.
_MENTION_VERBS = frozenset(
    {
        "answered",
        "appeared",
        "are",
        "asked",
        "came",
        "can",
        "could",
        "did",
        "do",
        "does",
        "felt",
        "gets",
        "got",
        "had",
        "has",
        "have",
        "is",
        "knew",
        "know",
        "looked",
        "made",
        "makes",
        "may",
        "might",
        "must",
        "noticed",
        "replied",
        "said",
        "says",
        "seemed",
        "should",
        "thought",
        "told",
        "was",
        "watched",
        "went",
        "were",
        "will",
        "would",
    }
)

_UI_LINE = re.compile(
    r"^(?:"
    r"(?:save|load)\s*(?:game|file|slot|state|data)?\s*#?\s*\d*"
    r"|(?:quick|auto|manual)\s*(?:save|load)"
    r"|(?:start|new|continue|resume|back|return|exit|quit|confirm|cancel"
    r"|settings|options|preferences|gallery|history|skip|auto\s*forward)"
    r"|end of line"
    r")(?:\s|:|$)",
    re.IGNORECASE,
)

# Markers that identify a Luna/Textractor hook payload rather than a clean
# ``Name: text`` clipboard line.
_MARKUP_HINTS = (
    "<WordWrap>",
    "<\\c[",
    "<c[",
    "\\c[",
    "\\sa[",
    "\\da[",
    "\x1b",
)

# Punctuation that, directly after a speaker name, still reads as the start
# of a spoken line ("Otsu...I've been looking for you").
_DIALOGUE_PUNCT = ".,!?…—-\"'(*_"


def has_hook_markup(raw: str) -> bool:
    """True when ``raw`` carries Luna/Textractor inline markup."""
    return any(hint in raw for hint in _MARKUP_HINTS)


def parse_actor_names(value: object) -> dict[int, str]:
    """Turn ``"1=Rick,2=Otsu"`` (or a mapping) into ``{1: "Rick", ...}``."""
    if not value:
        return {}
    if isinstance(value, Mapping):
        items: Iterable[tuple[Any, Any]] = value.items()
    else:
        items = []
        for chunk in re.split(r"[;,\n]+", str(value)):
            if "=" not in chunk:
                continue
            code, name = chunk.split("=", 1)
            items.append((code, name))

    out: dict[int, str] = {}
    for code, name in items:
        try:
            number = int(str(code).strip())
        except ValueError:
            continue
        cleaned = " ".join(str(name).split())
        if cleaned:
            out[number] = cleaned
    return out


def _clean_name(candidate: str) -> str | None:
    """Validate a speaker candidate; return its canonical spelling or None."""
    name = " ".join(candidate.split())
    if not name or len(name) > _MAX_NAME_LEN:
        return None
    words = name.split()
    if len(words) > _MAX_NAME_WORDS:
        return None
    if not re.match(r"^[A-Z]", words[0]):
        return None
    if not re.fullmatch(r"[A-Za-z0-9 .'\-]+", name):
        return None
    return name


def _clean_loose_name(candidate: str) -> str | None:
    """Like :func:`_clean_name`, but reject sentence starters in loose forms."""
    name = _clean_name(candidate)
    if name is None or name.split()[0].lower() in _NAME_STOPWORDS:
        return None
    return name


def is_plausible_character_name(name: str) -> bool:
    """Whether a loose space-form token could be a character name."""
    return _clean_loose_name(name) is not None and not _UI_LINE.match(name.strip())


def _tag_name(raw_name: str, resolve_code: Any) -> str | None:
    """Validate a tag's name, resolving an RPG Maker name placeholder."""
    stripped = raw_name.strip()
    code = _NAME_CODE.fullmatch(stripped)
    if code is not None:
        resolved = resolve_code(int(code.group("num")))
        return _clean_name(resolved) if resolved else None
    return _clean_name(stripped)


def _speaker_from_tags(raw: str, resolve_code: Any) -> str | None:
    """Pull the game's own speaker marker out of the hook payload."""
    for pattern in (_SPEAKER_TAG, _ESC_SPEAKER_TAG):
        for match in pattern.finditer(raw):
            name = _tag_name(match.group("name"), resolve_code)
            if name is not None:
                return name
    return None


def _has_speaker_tag(raw: str) -> bool:
    """True when the payload carries a speaker marker, even an unnamed one.

    A tag such as ``<c[2]???>`` proves the game *did* name the speaker; when
    that name cannot be validated we must not fall back to splitting the line
    on its first word, or narration would invent characters.
    """
    return any(pattern.search(raw) for pattern in (_SPEAKER_TAG, _ESC_SPEAKER_TAG))


def _strip_markup(raw: str, resolve_code: Any = None) -> str:
    """Drop hook tags/control codes and turn literal ``\\n`` into newlines."""
    text = _ANSI_ESCAPE.sub("", raw)
    unresolved = False

    def _replace_code(match: re.Match[str]) -> str:
        nonlocal unresolved
        resolved = resolve_code(int(match.group("num"))) if resolve_code else None
        if not resolved:
            unresolved = True
            return ""
        return str(resolved)

    text = _NAME_CODE.sub(_replace_code, text)
    # Only now may a literal \n become a line break: doing it first split
    # "\n[1]" into a newline plus a stray "[1]" and truncated the sentence.
    text = text.replace("\\n", "\n")
    # Tags separate words, so replace them with a break instead of deleting.
    text = _ANGLE_TAG.sub("\n", text)
    text = _CONTROL_CODE.sub("", text)
    if unresolved:
        # "leaving \n[1]'s side." lost its name: drop the orphan possessive.
        text = _ORPHAN_POSSESSIVE.sub("", text)
    return text


def _is_noise(segment: str) -> bool:
    """Drop URLs, file paths and JS hook noise from the candidate segments."""
    lowered = segment.lower()
    if "://" in segment or "chrome-extension:" in lowered:
        return True
    if re.match(r"^(?:[a-z]:[\\/]|\\\\)", segment, re.IGNORECASE):
        return True
    return lowered.count(".js") >= 2


def _pick_dialogue(raw: str, resolve_code: Any = None) -> str:
    """Return the first usable dialogue segment of a hook payload."""
    segments = [
        " ".join(segment.split())
        for segment in re.split(r"[\r\n]+", _strip_markup(raw, resolve_code))
    ]
    segments = [segment for segment in segments if segment and not _is_noise(segment)]
    if not segments:
        return ""
    # Prefer something that reads like a sentence over a lone fragment left
    # behind by a duplicated word-wrapped rendering ("Man", " If", " I", ...).
    for segment in segments:
        if len(segment.split()) >= 2 or re.search(r"[.!?…]$", segment):
            return segment
    return segments[0]


def _starts_like_dialogue(rest: str) -> bool:
    """Whether text after a candidate name starts like speech, not narration."""
    if not rest:
        return False
    if rest[0].isupper():
        return True
    if rest[0] in _DIALOGUE_PUNCT:
        tail = rest.lstrip(_DIALOGUE_PUNCT)
        return bool(tail) and tail[0].isupper()
    return False


def _is_mention(rest: str) -> bool:
    first_word = re.match(r"[A-Za-z']+", rest)
    return first_word is not None and first_word.group(0).lower() in _MENTION_VERBS


def _split_glued_speaker(text: str, known: Mapping[str, str]) -> tuple[str, str] | None:
    """Split a known name glued to its line: ``RickI only know...``.

    A second hook can render the name without its separating markup, which
    joins it to the dialogue ("OtsuWAIT! ..."). Only names already in the
    registry qualify, and the remainder must look like speech.
    """
    lowered = text.casefold()
    for key in sorted(known, key=len, reverse=True):
        if len(key) < 3 or not lowered.startswith(key):
            continue
        rest = text[len(key) :]
        if rest and _starts_like_dialogue(rest) and not _is_mention(rest):
            return known[key], rest
    return None


class LunaParser:
    """Parse LunaTranslator hook payloads into a :class:`Dialogue`."""

    def __init__(
        self,
        known_names: Iterable[str] = (),
        name_codes: object = None,
    ) -> None:
        self._known: dict[str, str] = {}
        self._name_codes: dict[int, str] = {}
        self.set_known_names(known_names)
        self.set_name_codes(name_codes)

    def set_known_names(self, names: Iterable[str]) -> None:
        """Remember the registry so a tag name maps to its canonical spelling."""
        self._known = {}
        for name in names:
            cleaned = name.strip()
            if cleaned:
                self._known[cleaned.casefold()] = cleaned

    def set_name_codes(self, value: object) -> None:
        """Set the actor-name mapping (``"1=Rick"`` or ``{1: "Rick"}``)."""
        self._name_codes = parse_actor_names(value)

    def _resolve_name_code(self, number: int) -> str | None:
        return self._name_codes.get(number)

    def _canonical(self, name: str) -> str:
        return self._known.get(name.casefold(), name)

    def _split_loose_speaker(self, text: str) -> tuple[str, str] | None:
        """Split ``Name: text`` or a registry-known ``Name text``; else None."""
        glued = _split_glued_speaker(text, self._known)
        if glued is not None:
            return glued

        match = _NAME_LINE.match(text)
        if match is not None:
            name = _clean_loose_name(match.group("name"))
            line = " ".join(match.group("line").split())
            if name is not None and line:
                return self._canonical(name), line

        parts = text.split(None, 1)
        if len(parts) != 2:
            return None
        # The space form is only trusted for a name we already know: narration
        # such as "Because her parents..." or "Seeing her like this..." must
        # never register "Because"/"Seeing" as a character.
        name = self._known.get(parts[0].casefold())
        if name is None:
            return None
        rest = parts[1].strip()
        if not _starts_like_dialogue(rest) or _is_mention(rest):
            return None
        return name, rest

    def parse(self, raw: str, source: str = "luna", instruct: str = "") -> Dialogue:
        if not raw or not raw.strip():
            return Dialogue(speaker=None, text="", source=source, instruct=instruct)

        tagged = _has_speaker_tag(raw)
        speaker = _speaker_from_tags(raw, self._resolve_name_code)
        text = _pick_dialogue(raw, self._resolve_name_code)
        if not text:
            return Dialogue(speaker=None, text="", source=source, instruct=instruct)

        # An unrecognised tag means the speaker is unknown, not "the first
        # word of the line": leave it to the narrator instead of inventing a
        # character from narration.
        if speaker is None and not tagged:
            loose = self._split_loose_speaker(text)
            if loose is not None:
                speaker, text = loose

        if speaker is not None:
            speaker = self._canonical(speaker)
        return Dialogue(speaker=speaker, text=text, source=source, instruct=instruct)
