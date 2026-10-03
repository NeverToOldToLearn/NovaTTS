"""Emotion / primal-sound filter for dialogue text.

VN_Suite.py extracts emotions via regex and plays separate .wav clips.
NovaTTS has no emotion-sound playback, so those tokens must be stripped
before TTS - otherwise Qwen speaks "haha", "aaaaaaaaah", "*laughs*", "..."
literally, which breaks immersion.

Rule of thumb from notes:
- ``*...*`` with 1 word inside  -> emotion  -> remove entirely.
- ``*...*`` with 2+ words        -> thought -> keep inner text sans asterisks.
- ``...`` on its own             -> an emotional pause, nothing to say -> drop.
- ``...`` between words         -> prosody Qwen3 renders as real silence -> KEEP.
- Bare primal sounds (haha, hehe, aah, aaaaaaaaaah, etc.) -> remove.
- Catches leftover ``*word*`` blocks via fallback ``\\*[^*]+\\*``.

Patterns are loaded from ``data/emotion_patterns.json`` when present
(so the GUI can edit them later); otherwise a compact builtin set
derived from VN_Suite.py is used. Patterns whose ``tag`` is ``None``
or not ``None`` are both stripped — NovaTTS does not play emotion sounds.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_BUILTIN = [
    r"\b(ha){3,}\b",
    r"\bhaha\b",
    r"\b(he){3,}\b",
    r"\bhehe\b",
    r"\bhe-he\b",
    r"\ba+h+\b",
    r"\baah+\b",
    r"\bahh+\b",
    r"\bahem\b",
    r"\bmmm+\b",
    r"\bhmm\b",
    r"\bha\b",
    r"\bsh+\b",
    r"\bhmpf\b",
    r"\bphew\b",
    r"\bargh\b",
    r"\bsigh(?:ing|ed)?s?\b",
    r"\bgroan(?:ing|s)?\b",
    r"\byawn(?:ing|s)?\b",
    r"\bsniff(?:le|s)?\b",
    r"\bsobs\b",
    r"\b([a-zA-Z])\1{2,}\b",
    r"\b[mnhaeou]+[mngh][mnhaeou]{2,}\b",
    r"\b([mngh]){3,}([aouh]{1}[mngh]*)+\b",
    r"\b[mn]{3,}[aouh][mngh]+\b",
    r"\b([mnh])\1{2,}[ao]+[mgh]+\b",
]

_ASTERISK_TOKEN_RE = re.compile(r"\*([^*]{1,80})\*")
_ELLIPSIS_RE = re.compile(r"\.{2,}|…+")
_WS_RE = re.compile(r"\s+")

# A TTS model cannot pronounce punctuation. Once the emotion words are
# stripped, what is often left is only the "." or "," that used to follow
# them: "Aah!" -> "!", "Mm-hm." -> ".". Handing that to Qwen spends a
# synthesis request on it and returns a garbled blip or an invented
# syllable, so punctuation on its own counts as no text at all.
_SPEAKABLE_RE = re.compile(r"[^\W_]", re.UNICODE)
_LEADING_PUNCT_RE = re.compile(r"^[\s\W_]+", re.UNICODE)

_compiled: list[re.Pattern[str]] | None = None


def has_speakable_text(text: str) -> bool:
    """True when `text` holds at least one letter or digit to pronounce."""
    return bool(_SPEAKABLE_RE.search(text or ""))


def strip_leading_punctuation(text: str) -> str:
    """Drop punctuation left stranded at the start by an emotion removal.

    Only the leading edge is touched: a trailing "..." on a real sentence is
    deliberate prosody and must survive.
    """
    return _LEADING_PUNCT_RE.sub("", text or "")


def strip_trailing_stray_punctuation(text: str) -> str:
    """Tidy the line's ending without flattening its cadence.

    Qwen3 reads punctuation, so what ends up in front of the model is not a
    cosmetic detail:

    - "Yes..." keeps its dots and "Really?!" keeps both marks. Glued to the
      last word they are prosody, and a pause Qwen3 turns into silence is
      exactly the timing the line wants.
    - "Zij zei slurp." keeps its full stop once "slurp" is gone. The mark ends
      up detached by a space, but it is still the sentence's own ending, so
      it is glued back on.
    - "I love it, ." loses its tail: a full stop after a comma is what an
      emotion word removed from between two marks leaves behind, and no voice
      can pronounce it.
    """
    s = (text or "").rstrip()
    if not s or s[-1].isalnum():
        return s
    # Walk back over the trailing marks to what they are attached to: the last
    # word, or a gap. Meeting the word first means the run is glued to it and
    # is prosody. Meeting a gap first means it stands on its own.
    last_ws = -1
    word_end = -1
    for i in range(len(s) - 1, -1, -1):
        ch = s[i]
        if ch.isspace():
            last_ws = i
            break
        if ch.isalnum():
            word_end = i + 1
            break
    if word_end > 0:
        run = s[word_end:]
        # A run mixing in a comma or semicolon cannot close a sentence, so it
        # is stranded: "I love it,." drops to "I love it."
        if any(ch in ",;" for ch in run):
            return s[:word_end] + run[-1]
        return s
    if last_ws <= 0:
        return s  # nothing but punctuation; the caller decides what that means
    head = s[:last_ws].rstrip()
    chunk = s[last_ws + 1 :]
    # A lone terminator detached by the removal is the sentence's own ending,
    # so it goes back on -- unless what it would join is a comma or a pause,
    # which would only weld two runs into one the text never wrote.
    if len(chunk) == 1 and chunk in ".?!" and head and head[-1] not in ",;:.…":
        return head + chunk
    return head


def _close_up(m: re.Match[str]) -> str:
    """Remove the space in front of a stranded mark: "Hello , world" -> "Hello,".

    Not next to a pause though. After an emotion is removed, "Yes... ." is
    what is left of "Yes... aah." and the space there is all that keeps the
    sentence's full stop from welding onto the ellipsis, making one run of
    four dots that says something the text never did.
    """
    return m.group(1)


def _load_patterns() -> list[re.Pattern[str]]:
    global _compiled
    if _compiled is not None:
        return _compiled
    raw: list[str] = list(_BUILTIN)
    cand = Path(__file__).resolve().parent.parent.parent / "data" / "emotion_patterns.json"
    if cand.exists():
        try:
            data = json.loads(cand.read_text(encoding="utf-8"))
            if isinstance(data, list):
                extra: list[str] = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    pat = item.get("pattern")
                    if isinstance(pat, str) and pat and pat != r"\*[^*]+\*":
                        extra.append(pat)
                if extra:
                    raw = extra
        except Exception:
            pass
    out: list[re.Pattern[str]] = []
    for pat in raw:
        try:
            out.append(re.compile(pat, re.I))
        except re.error:
            continue
    _compiled = out
    return out


def _alias_patterns(aliases: dict[str, str] | None) -> list[re.Pattern[str]]:
    """Bare and starred forms of the user's own aliases.

    Same two shapes EmotionSounds.extract() builds, so a word means the same
    thing on the /speak route as it does on the clipboard route.
    """
    if not aliases:
        return []
    out: list[re.Pattern[str]] = []
    for expr in aliases:
        esc = re.escape(expr.strip("*"))
        if not esc:
            continue
        for pat in (rf"\b{esc}\b", rf"\*{esc}\*"):
            try:
                out.append(re.compile(pat, re.I))
            except re.error:
                continue
    return out


def clean_emotion_text(text: str, aliases: dict[str, str] | None = None) -> str:
    """Strip emotion words from `text` for the /speak and preview routes.

    These routes play no sound, so an emotion word is removed rather than
    spoken -- Qwen reads "spluuuurt" as gibberish. `aliases` is the user's own
    phrase-to-tag mapping; without it those phrases were spoken here while the
    clipboard route quietly removed them.
    """
    if not text or not text.strip():
        return ""
    pats = _alias_patterns(aliases) + _load_patterns()
    t = text

    def _asterisk_replace(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if not inner:
            return ""
        words = inner.split()
        if len(words) == 1:
            return ""
        return f" {inner} "

    t = _ASTERISK_TOKEN_RE.sub(_asterisk_replace, t)
    t = t.replace("*", "")
    for pat in pats:
        t = pat.sub(" ", t)
    # "..." is an emotional pause only when it is all the line has left. Between
    # words it is prosody that Qwen3 renders as real silence, and dropping it is
    # what turned "if you want... I... ehm" into one flat run-on sentence.
    if not has_speakable_text(t):
        t = _ELLIPSIS_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    t = re.sub(r"(?<![.…])\s+([,.!?;:])", _close_up, t)
    t = strip_leading_punctuation(t)
    t = strip_trailing_stray_punctuation(t)
    return t.strip()


def reload_patterns() -> None:
    global _compiled
    _compiled = None
