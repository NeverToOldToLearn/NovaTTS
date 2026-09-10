"""Emotion / primal-sound filter for dialogue text.

VN_Suite.py extracts emotions via regex and plays separate .wav clips.
NovaTTS has no emotion-sound playback, so those tokens must be stripped
before TTS - otherwise Qwen speaks "haha", "aaaaaaaaah", "*laughs*", "..."
literally, which breaks immersion.

Rule of thumb from notes:
- ``*...*`` with 1 word inside  -> emotion  -> remove entirely.
- ``*...*`` with 2+ words        -> thought -> keep inner text sans asterisks.
- ``...`` / ``...`` (ellipsis)    -> always an emotion pause -> strip.
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

_compiled: list[re.Pattern[str]] | None = None


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


def clean_emotion_text(text: str) -> str:
    if not text or not text.strip():
        return ""
    pats = _load_patterns()
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
    t = _ELLIPSIS_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    return t


def reload_patterns() -> None:
    global _compiled
    _compiled = None
