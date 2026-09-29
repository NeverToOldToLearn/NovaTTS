"""LunaHook/Textractor dialogue parser.

Textractor has no speaker anchor. Where RenPy emits ``Name: Text`` and we
can split on the colon, Textractor emits ``Rick It's 2 parts.`` — the
speaker is just the first capitalised word, and that word is sometimes
narration, sometimes a scene label, sometimes the UI.

So the whole job of this module is to decide, case by case, whether a
leading capitalised word is a *character* or just a word. Three guards do
that work, and each exists because the naive version mis-assigns a voice:

- a stopword / function-word set ("You have your shower." is not You),
- a mention-verb guard ("Anne has been quiet." is narration *about*
  Anne, not Anne speaking — this is the single most common false
  positive, because the sentence genuinely starts with a character name),
- a fresh-sentence guard, so a known name mid-line ("Rick totally
  agrees") does not hijack the voice from whoever is already speaking.

Everything is deliberately case-sensitive on the first letter: Textractor
only ever capitalises, and a lowercased name is narration.

Entry points:
- :func:`parse_luna` — one hook line to at most one :class:`Dialogue`.
- :func:`parse_luna_turns` — one hook line to several, for the
  ``Anne Hallo! Rick Mooi.`` shape where one line carries two speakers.
  Every turn shares the same ``raw``, so the original stays reconstructable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import Dialogue

# ---------------------------------------------------------------------------
# Word sets
# ---------------------------------------------------------------------------
#
# Ported verbatim from the donor project (NovaTTSLuna parser/luna.py), which
# accumulated them against real games. They are heuristic, not derived, so
# they are data, not logic -- treat edits as tuning and expect a test to
# disagree.

#: Words that start a sentence but are never a speaker. ``You have your
#: shower.`` and ``Good night babe!`` are the two shapes this exists for.
_SPACE_FORM_STOPWORDS = frozenset(
    {
        "you",
        "good",
        "well",
        "ya",
        "yes",
        "no",
        "yeah",
        "yep",
        "nope",
        "this",
        "that",
        "there",
        "these",
        "those",
        "here",
        "he",
        "she",
        "they",
        "it",
        "the",
        "a",
        "an",
        "we",
        "i",
        "skip",
        "part",
        "maybe",
        "sure",
        "right",
        "left",
        "hi",
        "hey",
        "oh",
        "hmm",
        "umm",
        "uh",
        "so",
        "but",
        "and",
        "or",
        "if",
        "then",
        "when",
        "where",
        "why",
        "how",
        "what",
        "who",
        "go",
        "come",
        "do",
        "did",
        "get",
        "got",
        "let",
        "look",
        "see",
        "please",
        "thanks",
        "thank",
        "sorry",
        "ugh",
        "wow",
        "great",
        "nice",
        "bad",
        "ok",
        "okay",
        "huh",
        "ah",
        "bye",
        "lol",
        "haha",
        "me",
        "day",
        "chapter",
        "level",
        "route",
        "episode",
        "scene",
        "today",
        "tomorrow",
        "tonight",
        "morning",
        "afternoon",
        "evening",
        "night",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
        "damn",
        "shit",
        "fuck",
        "mr",
        "ms",
        "mrs",
        "dr",
    }
)

#: Prepositions, scene furniture, UI verbs: words that are often
#: capitalised mid-sentence by a game engine and must never become a
#: character. Overlaps the stopword set on purpose; both are consulted.
_NON_CHARACTER_NAME_TOKENS = frozenset(
    {
        "in",
        "for",
        "my",
        "to",
        "after",
        "just",
        "with",
        "is",
        "try",
        "skipping",
        "clever",
        "virtual",
        "clipboard",
        "got",
        "selected",
        "the",
        "a",
        "an",
        "at",
        "on",
        "of",
        "by",
        "from",
        "as",
        "into",
        "onto",
        "over",
        "under",
        "about",
        "before",
        "during",
        "while",
        "because",
        "although",
        "though",
        "your",
        "our",
        "their",
        "his",
        "her",
        "its",
        "this",
        "that",
        "these",
        "those",
        "all",
        "some",
        "any",
        "each",
        "both",
        "more",
        "most",
        "other",
        "than",
        "then",
        "once",
        "now",
        "still",
        "very",
        "too",
        "also",
        "not",
        "end",
        "line",
        "menu",
        "select",
        "continue",
        "back",
        "next",
        "start",
        "exit",
        "save",
        "load",
        "settings",
        "options",
        "yes",
        "no",
        "meanwhile",
        "later",
        "outside",
        "inside",
        "kitchen",
        "school",
        "classroom",
        "bedroom",
        "living",
        "room",
        "hallway",
        "garden",
        "street",
        "house",
        "home",
        "morning",
        "evening",
        "afternoon",
        "night",
        "dawn",
        "dusk",
        "day",
        "today",
        "tomorrow",
        "yesterday",
        "suddenly",
        "finally",
        "eventually",
        "soon",
        "somewhere",
        "elsewhere",
        "nearby",
        "away",
        "front",
        "top",
        "bottom",
        "chapter",
        "scene",
        "act",
        "interlude",
        "flashback",
        "present",
        "past",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
)

#: Verbs that turn "Name ..." into narration *about* that name.
#: "Anne has been quiet." must not become Anne speaking.
_MENTION_VERBS = frozenset(
    {
        "has",
        "have",
        "had",
        "is",
        "are",
        "was",
        "were",
        "been",
        "being",
        "does",
        "did",
        "do",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "must",
        "got",
        "gets",
        "went",
        "came",
        "said",
        "says",
        "told",
        "asked",
        "answered",
        "replied",
        "noticed",
        "watched",
        "looked",
        "seemed",
        "appeared",
        "felt",
        "thought",
        "knew",
        "know",
        "made",
        "makes",
    }
)

#: A single capitalised word: the only shape Textractor ever uses for a
#: speaker. Multi-word names (``Miss Brooks``) are reachable through
#: :func:`is_plausible_character_name` in the colon form, not here.
_SPACE_FORM_NAME = re.compile(r"^[A-Z][A-Za-z]+$")

#: A name as it may appear in a hook line, more permissive than
#: ``_SPACE_FORM_NAME``: spaces, digits, apostrophes and hyphens.
_LOOSE_NAME = re.compile(r"^[A-Z][A-Za-z0-9 .'-]+$")

#: A candidate name at the head of a line, used by the multi-turn splitter.
_NAME_TOKEN_SPACE = re.compile(r"(?:^|(?<=[.!?\u2026]\s))([A-Z][A-Za-z]+)\s+")

#: ``Name: text``, the RenPy form. The Luna path still has to accept it,
#: because plenty of games route hook text through a RenPy-style prefix.
_COLON_LINE = re.compile(r"^\s*(?P<speaker>[^:]+)\s*:\s*(?P<line>.+?)\s*$")

#: The next real word after a candidate name, for the mention-verb guard.
_NEXT_WORD = re.compile(r"([A-Za-z']+)")

#: The next word only if it starts a fresh sentence (capitalised).
_NEXT_SENTENCE_WORD = re.compile(r"([A-Z][A-Za-z']+)")

#: Longest plausible speaker name. "Bartholomew Fitzgerald III" is
#: narration until proven otherwise.
_MAX_NAME_LEN = 20

# ---------------------------------------------------------------------------
# UI-line rejection
# ---------------------------------------------------------------------------
#
# Sixteen anchored patterns (not the fifteen the plan estimated). Games
# emit UI text through the same hook as dialogue, and a "Save Game 3" that
# reaches the voice picks a random cloned character -- which is far more
# annoying than a line that got dropped.

_VN_UI_BLACKLIST_RAW: tuple[str, ...] = (
    r"(?:Save|Load)\s*(?:Game|File|Slot|State|Data)?\s*#?\s*\d*",
    r"(?:Save|Load)\s*#\s*\d+",
    r"(?:Quick|Auto|Manual)\s*(?:Save|Load)",
    r"(?:Overwrite|Confirm|Erase)\s*(?:Save|File|Slot)?",
    r"\bSave\s*File\b",
    r"\bLoad\s*File\b",
    (
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
        r"\s+\d{1,2}\s*"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
        r"|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{4})?"
    ),
    r"\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}",
    r"\bDay\s*#?\s*\d+",
    r"\bChapter\s*#?\s*\d+",
    r"\bLevel\s*#?\s*\d+",
    r"\bRoute\s*#?\s*\d+",
    r"\bEpisode\s*#?\s*\d+",
    r"\bScene\s*#?\s*\d+",
    (
        r"(?:Start|New|Continue|Resume|Back|Return|Exit|Quit|Confirm|Cancel"
        r"|Settings|Options|Preferences|Config|Extras|Bonus"
        r"|Gallery|Music\s*Room|Scene\s*Select|CG\s*Gallery"
        r"|Auto\s*Forward|Skip|History|Log| backlog)(?:\s|$)"
    ),
    (
        r"(?:Narrator|Narration|System|Announcer|Voice\s*Actor|Inner\s*Monologue|Thought"
        r"|Narrator's?\s*Voice)(?:\s*:\s*|$)"
    ),
)


def _compile_anchored(patterns: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    """Anchor each UI pattern to the whole string, case-insensitively.

    A pattern that fails to compile is skipped rather than crashing the
    import: one bad regex in a list of heuristics should not take the
    whole backend down at startup.
    """
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(r"^(?:" + pattern + r")$", re.IGNORECASE))
        except re.error:  # pragma: no cover - defensive
            continue
    return tuple(compiled)


_VN_UI_BLACKLIST: tuple[re.Pattern[str], ...] = _compile_anchored(_VN_UI_BLACKLIST_RAW)

#: Games append this to whatever the player has selected.
_UI_SUFFIX = re.compile(r"\s*(?:selected|got\s+it)\s*$", re.IGNORECASE)

_NON_CHARACTER_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^END OF LINE$", re.IGNORECASE),
    re.compile(r"END OF LINE", re.IGNORECASE),
    re.compile(r"\b(?:selected|got it)\b", re.IGNORECASE),
    re.compile(r"^\s*$"),
)


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def is_plausible_character_name(name: str) -> bool:
    """True if ``name`` looks like a character rather than ordinary words.

    The check is deliberately conservative: a false negative costs a
    narration line, a false positive costs a wrong cloned voice on
    narration, which is the failure the user actually notices.
    """
    if not name:
        return False
    if len(name) > _MAX_NAME_LEN:
        return False
    if not _LOOSE_NAME.match(name):
        return False
    lowered = name.lower()
    if lowered in _SPACE_FORM_STOPWORDS or lowered in _NON_CHARACTER_NAME_TOKENS:
        return False
    if any(p.search(name) for p in _NON_CHARACTER_NAME_PATTERNS):
        return False
    return not any(p.match(name) for p in _VN_UI_BLACKLIST)


def reject_ui_line(text: str) -> bool:
    """True if ``text`` is game chrome rather than dialogue.

    Checked both as-is and with a trailing "selected" / "got it" peeled
    off, because that is how the engine reports whatever the player just
    moved the cursor onto.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if "END OF LINE" in stripped.upper():
        return True
    for pattern in _VN_UI_BLACKLIST:
        if pattern.match(stripped):
            return True
        without_suffix = _UI_SUFFIX.sub("", stripped)
        if without_suffix != stripped and pattern.match(without_suffix):
            return True
    return False


def _next_word_is_mention(text: str) -> bool:
    """True if the line continues "... <name> <verb> ...", i.e. narration."""
    match = _NEXT_WORD.match(text)
    if match is None:
        return False
    return match.group(1).lower() in _MENTION_VERBS


def _starts_fresh_sentence(text: str) -> bool:
    """True if ``text`` begins a capitalised sentence rather than continuing one.

    This is the guard that stops a known name mid-line from stealing the
    voice: in "Rick totally agrees" the text after Rick starts lowercase.
    """
    return _NEXT_SENTENCE_WORD.match(text) is not None


def _resolve_known(candidate: str, known: dict[str, str]) -> str | None:
    """Return the canonical registry spelling if ``candidate`` is a known speaker.

    Case-insensitive, so "rick" resolves to the registered "Rick". Returns
    ``None`` for anything not already in the registry — the splitter
    consults the plausibility heuristic separately for unknown names.
    """
    return known.get(candidate.strip().lower())


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _normalize(raw: str) -> str:
    """Collapse whitespace and peel the quotes some engines wrap lines in."""
    collapsed = " ".join(raw.split())
    return collapsed.strip().strip('"').strip("'").strip()


def _name_map(known_names: Iterable[str]) -> dict[str, str]:
    """Build the lowercased-key -> canonical-spelling lookup from the registry.

    Spelled out rather than shared with :class:`LunaParser` so the module
    functions stay usable on their own; the class builds one of these once
    in ``__init__`` rather than per line.
    """
    return {
        name.strip().lower(): name.strip() for name in known_names if name and name.strip()
    }


def parse_luna(
    text: str,
    source: str = "luna",
    instruct: str = "",
    *,
    known_names: Iterable[str] = (),
) -> Dialogue | None:
    """Parse one hook line into a single :class:`Dialogue`.

    Returns ``None`` when the line is not dialogue at all (empty, or
    rejected game chrome) — that is a different answer from "dialogue with
    no speaker", which comes back as a :class:`Dialogue` with
    ``speaker=None``. Dropping and narrating are not the same thing.

    ``raw`` is set to the *unmodified* argument, not the normalised text:
    it is the forensic record of what the hook actually sent.

    ``known_names`` are registry speakers, and a registered name wins over
    every heuristic here — same contract as
    :class:`~novatts.parser.renpy.RenPyParser`, so "Dr" (a stopword) or
    "Passenger 1" (too long to be a space-form name) still speaks when
    the user has registered them.
    """
    normalized = _normalize(text)
    if not normalized or reject_ui_line(normalized):
        return None
    known = _name_map(known_names)

    # Colon form first: RenPy-shaped text is unambiguous, and plenty of
    # games emit it through the hook. Splitting this later would risk
    # breaking a name that legitimately contains a colon-free space.
    if ":" in normalized:
        match = _COLON_LINE.match(normalized)
        if match:
            speaker = match.group("speaker").strip()
            line = match.group("line").strip()
            looks_named = bool(speaker) and bool(line) and speaker[0].isupper() and len(speaker) <= 30
            registered = _resolve_known(speaker, known)
            if looks_named and registered is not None:
                return Dialogue(
                    speaker=registered, text=line, source=source, raw=text, instruct=instruct
                )
            if (
                looks_named
                and speaker.lower() not in _SPACE_FORM_STOPWORDS
                and not any(p.match(speaker) for p in _VN_UI_BLACKLIST)
            ):
                return Dialogue(speaker=speaker, text=line, source=source, raw=text, instruct=instruct)
            # Colon present but the prefix is not a name: fall through and
            # let the space form try, so "Note: Rick looks up." still works.

    parts = normalized.split(None, 1)
    if len(parts) == 2:
        candidate, rest = parts[0].strip(), parts[1].strip()
        if rest:
            # A registry hit is accepted without the plausibility check;
            # the mention/comma guards still apply, because "Dr is not
            # here" is narration about Dr even when Dr is registered.
            registered = _resolve_known(candidate, known)
            accepted = registered is not None or is_plausible_character_name(candidate)
            if accepted and not _next_word_is_mention(rest) and rest[:1] != ",":
                return Dialogue(
                    speaker=registered or candidate,
                    text=rest,
                    source=source,
                    raw=text,
                    instruct=instruct,
                    # "Rick Hello" names Rick by inference; "Rick: Hello"
                    # states him. A registered name is the user overriding
                    # the heuristic, so that is not a guess.
                    speaker_is_guess=registered is None,
                )

    return Dialogue(speaker=None, text=normalized, source=source, raw=text, instruct=instruct)


def split_speaker_turns(
    text: str,
    *,
    known_names: Iterable[str] = (),
    space_form: bool = True,
) -> list[str]:
    """Split one hook line into per-speaker segments, in ``Name: text`` form.

    Textractor sometimes packs two speakers into one line, as in
    ``Anne Hallo! Rick Mooi.`` or ``Rick\\nAnswer the door.``; the
    newline-bare-name form is the worst case, because the name arrives as
    a whole line of its own with nothing to attach it to.

    Output is deliberately colon-normalised rather than pre-parsed, so the
    caller can run each segment through :func:`parse_luna` and get the
    same speaker rules as a single line — one place decides what a name is.

    ``known_names`` are the speakers already in the registry. A *known*
    name may open a turn even where the heuristic would refuse it; an
    *unknown* name must clear the full plausibility check, so the splitter
    never invents a character out of a scene label like "Kitchen".
    """
    if not text or not text.strip():
        return []
    if not space_form:
        return [text.strip()]

    return [segment for segment, _guessed in _split_turns(text, known_names=known_names, space_form=space_form)]


def _split_turns(
    text: str,
    *,
    known_names: Iterable[str] = (),
    space_form: bool = True,
) -> list[tuple[str, bool]]:
    """:func:`split_speaker_turns`, plus a per-segment "was that name guessed?" flag.

    The flag is ``True`` when the turn was opened by a name the *heuristic*
    accepted, and ``False`` when it was opened by a name already in the
    registry -- or when the line was not split at all, in which case
    :func:`parse_luna` decides the shape itself from the original text.

    Keeping it here rather than re-deriving it at the call site is not
    tidiness. The split rewrites the line into colon form before the
    per-turn parse, so "Rick Hello" (a guess) and "Rick: Hello" (stated)
    are indistinguishable by the time a caller sees the result. This is
    the only place that still knows which one it was.
    """
    if not text or not text.strip():
        return []
    if not space_form:
        return [(text.strip(), False)]

    known = _name_map(known_names)

    # 1) Newline-separated bare name: rejoin "Rick\nAnswer the door." into
    #    "Rick: Answer the door." so the normal path can see it. A bare
    #    capitalised line is only merged when it is already a known
    #    speaker -- otherwise "Kitchen." on its own line is a scene label
    #    and attaching a line to it would invent a character.
    #
    #    The whole line is looked up in the registry, not just a
    #    single-word match, so a registered "Passenger 1" merges too. That
    #    lookup is the only gate here: a bare line is accepted purely
    #    because the user registered that exact name.
    merged: list[str] = []
    pending: str | None = None
    for line in text.split("\n"):
        candidate_line = line.strip()
        if not candidate_line:
            continue
        resolved = _resolve_known(candidate_line, known)
        if resolved is not None:
            pending = resolved
            continue
        bare_name = _SPACE_FORM_NAME.match(candidate_line)
        if bare_name and len(candidate_line) <= _MAX_NAME_LEN:
            resolved = _resolve_known(bare_name.group(0), known)
            if resolved is not None:
                pending = resolved
                continue
        if pending is not None:
            candidate_line = f"{pending}: {candidate_line}"
            pending = None
        # Collapse inner whitespace runs here, not after the join: the
        # bound-finder's lookbehind needs exactly one space after sentence
        # punctuation, so "Hallo!  Rick Mooi." (two spaces, which games do
        # emit) would otherwise fail to find Rick at all. parse_luna()
        # normalises the same way, and the two must agree.
        merged.append(" ".join(candidate_line.split()))
    joined = " ".join(merged)

    # 2) Find validated speaker boundaries inside the joined line.
    #    Each bound records whether the name was looked up in the registry
    #    or accepted by the heuristic; that difference is the "guessed" flag.
    bounds: list[tuple[int, int, str, bool]] = []
    for match in _NAME_TOKEN_SPACE.finditer(joined):
        candidate = match.group(1)
        after = joined[match.end(0) :].strip()
        if after[:1].isdigit():
            continue
        if _next_word_is_mention(after):
            continue
        resolved = _resolve_known(candidate, known)
        if resolved is not None:
            # A known character still may not interrupt: only a fresh
            # capitalised sentence starts a new turn, never a lowercase
            # continuation ("Rick totally agrees").
            if not _starts_fresh_sentence(after):
                continue
        else:
            if not is_plausible_character_name(candidate):
                continue
            # A comma means a scene label ("Meanwhile, back at the...").
            if after[:1] == "," or after[:1] in "\"'(":
                continue
            if not _starts_fresh_sentence(after):
                continue
        bounds.append((match.start(1), match.end(1), candidate, resolved is None))

    if not bounds:
        return [(joined, False)]

    # 3) Cut at the recorded boundaries and colon-normalise each cut turn.
    #
    #    The cut happens on `joined` and the colon goes in afterwards, so
    #    there is exactly one coordinate system in play. Doing it the
    #    other way round -- inserting every colon first and then slicing
    #    -- puts the cuts in `joined`'s coordinates while indexing
    #    `normalized`, and every inserted colon silently shifts the
    #    bounds after it by one. That reads as a dropped full stop at the
    #    end of a turn, which is exactly the kind of defect that looks
    #    like a parsing bug and gets "fixed" in the wrong place.
    #
    #    Only the turns opened by a bound get a colon. The first turn keeps
    #    the shape the original line had, so parse_luna() reads it directly
    #    and decides its own provenance instead of having one imposed.
    out: list[tuple[str, bool]] = []
    for index in range(len(bounds) + 1):
        start = 0 if index == 0 else bounds[index - 1][0]
        end = len(joined) if index == len(bounds) else bounds[index][0]
        segment = joined[start:end].strip()
        if not segment:
            continue
        if index == 0:
            out.append((segment, False))
            continue
        _, name_end, name, guessed = bounds[index - 1]
        body = segment[name_end - start :].strip()
        out.append((f"{name}: {body}" if body else f"{name}:", guessed))
    return out


def parse_luna_turns(
    text: str,
    *,
    known_names: Iterable[str] = (),
    space_form: bool = True,
    source: str = "luna",
    instruct: str = "",
) -> list[Dialogue]:
    """Parse one hook line into every speaker turn it contains.

    The multi-speaker half of the pipeline, which the donor project does
    not have. All returned turns share ``raw=text``, so
    ``Anne Hallo! Rick Mooi.`` stays fully reconstructable after the split.

    Returns an empty list only when the line is not dialogue at all.

    ``known_names`` is passed through to :func:`parse_luna` as well as to
    the splitter. Both halves need it: the splitter decides *where* turns
    begin, but it normalises each turn to ``Name: text``, and it is
    ``parse_luna`` that then decides whether that name is a speaker. If
    the registry stopped at the split, a registered "Dr" would be split
    off correctly and then immediately rejected as a stopword.
    """
    dialogues: list[Dialogue] = []
    for segment, guessed in _split_turns(text, known_names=known_names, space_form=space_form):
        parsed = parse_luna(segment, source=source, known_names=known_names)
        if parsed is None:
            continue
        # The segment is normalised, but `raw` must be the line the hook
        # actually sent, or the forensic record is lost.
        dialogues.append(
            Dialogue(
                speaker=parsed.speaker,
                text=parsed.text,
                source=source,
                raw=text,
                instruct=instruct,
                # The segment was rewritten to colon form, so parse_luna
                # sees every name as stated. Only the splitter knows which
                # ones it invented, so its answer wins where it has one.
                speaker_is_guess=parsed.speaker_is_guess or (guessed and parsed.speaker is not None),
            )
        )
    return dialogues


class LunaParser:
    """Registry-aware wrapper around the module-level functions.

    Mirrors :class:`~novatts.parser.renpy.RenPyParser` so both input
    sources present the same shape to the adapters, and keeps the same
    contract: a registered speaker wins over the heuristics.
    ``set_known_names`` lets a name such as "Dr" (a stopword) or
    "Passenger 1" (not a shape any heuristic would accept) still speak,
    and maps it back to the exact registered spelling.

    One shape the registry does *not* rescue: a registered multi-word name
    cannot open a turn in the middle of a space-form line, because the
    bound-finder only ever matches a single capitalised word. It does work
    when the name arrives on a line of its own. See
    ``test_known_gap_multi_word_names_cannot_open_a_space_form_turn``.
    """

    def __init__(self, known_names: Iterable[str] = (), *, space_form: bool = True) -> None:
        self.space_form = space_form
        self.set_known_names(known_names)

    def set_known_names(self, names: Iterable[str]) -> None:
        """Replace the set of case-insensitive names treated as known speakers."""
        self._known: dict[str, str] = {}
        for name in names:
            if name and name.strip():
                self._known[name.strip().lower()] = name.strip()

    @property
    def known_names(self) -> tuple[str, ...]:
        return tuple(self._known.values())

    def parse(self, raw: str, source: str = "luna", instruct: str = "") -> Dialogue | None:
        """Parse a single line. See :func:`parse_luna` for the rules."""
        return parse_luna(raw, source=source, instruct=instruct, known_names=self.known_names)

    def parse_turns(self, raw: str, source: str = "luna", instruct: str = "") -> list[Dialogue]:
        """Parse every speaker turn in a line. See :func:`parse_luna_turns`."""
        return parse_luna_turns(
            raw,
            known_names=self.known_names,
            space_form=self.space_form,
            source=source,
            instruct=instruct,
        )
