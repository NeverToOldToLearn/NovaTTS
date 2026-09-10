from __future__ import annotations

import json
import re
from pathlib import Path

from .config import settings

PRESETS: dict[str, list[str]] = {
    "Days of Week": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "Months": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "Time of Day": ["Morning", "Afternoon", "Evening", "Night", "Midnight", "Noon", "Dawn", "Dusk", "Sunrise", "Sunset"],
    "Hours (12h)": [f"{h} AM" for h in range(1, 13)] + [f"{h} PM" for h in range(1, 13)],
    "Hours (24h)": [f"{h:02d}:00" for h in range(24)],
    "Date Formats": [r"\bDay\s+\d+\b", r"\bChapter\s+\d+\b", r"\bLevel\s+\d+\b", r"\b(Save|Load)\s+(slot|\d+)", r"\b(Save|Load)#\d+", r"\bDay\s+#\s*\d+\b", r"\d{1,2}/\d{1,2}/\d{2,4}", r"\d{1,2}-\d{1,2}-\d{2,4}", r"\d{4}-\d{2}-\d{2}"],
    "Common UI": ["Inventory", "Menu", "Settings", "Options", "Save", "Load", "Quit", "Exit", "Back", "Continue", "Next", "Previous", "Close", "Open", "Auto Forward", "Auto Forward selected"],
}

_RENPY_STRONG = [re.compile(p, re.I) for p in [r"An exception has occurred", r"Full traceback\s*:", r"Ignores the exception, allowing you to continue", r"Traceback \(most recent call last\)"]]
_RENPY_ALL = [re.compile(p, re.I) for p in [r"An exception has occurred", r"Full traceback\s*:", r"While running game code", r"Ignores the exception, allowing you to continue", r"NameError:\s*name\s+'[^']+'\s+is not defined", r"Traceback \(most recent call last\)", r'File\s+"[^"]+\.rpy",\s*line\s+\d+', r'File\s+"renpy/[^"]+",\s*line\s+\d+']]


def is_renpy_exception(text: str) -> bool:
    if not text or not text.strip():
        return False
    if any(p.search(text) for p in _RENPY_STRONG):
        return True
    return sum(1 for p in _RENPY_ALL if p.search(text)) >= 2


class Blacklist:
    def __init__(self) -> None:
        self.path = Path(settings.blacklist_file)
        self.custom_words: list[str] = []
        self.enabled_presets: list[str] = []
        self._word_set: set[str] = set()
        self._patterns: list[re.Pattern[str]] = []
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.custom_words = list(data.get("custom_words", []))
                self.enabled_presets = [p for p in data.get("enabled_presets", []) if p in PRESETS]
        except Exception:
            pass
        self._rebuild()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"custom_words": self.custom_words, "enabled_presets": self.enabled_presets}, indent=2), encoding="utf-8")

    def set(self, custom_words: list[str] | None = None, enabled_presets: list[str] | None = None) -> None:
        if custom_words is not None:
            self.custom_words = [str(w).strip() for w in custom_words if str(w).strip()]
        if enabled_presets is not None:
            self.enabled_presets = [p for p in enabled_presets if p in PRESETS]
        self._rebuild()
        self.save()

    def _rebuild(self) -> None:
        self._word_set = {w.lower() for w in self.custom_words}
        self._patterns = []
        for preset in self.enabled_presets:
            for item in PRESETS.get(preset, []):
                if item.startswith("\\") or re.match(r"\d", item) or "/" in item or "-" in item:
                    try:
                        self._patterns.append(re.compile(item, re.I))
                    except re.error:
                        continue
                else:
                    try:
                        self._patterns.append(re.compile(r"\b" + re.escape(item.lower()) + r"\b", re.I))
                    except re.error:
                        continue

    def filter_text(self, text: str) -> str:
        if not text or not text.strip():
            return ""
        m = re.match(r"^(\[[^\]]+\]:\s*|[A-Za-z][A-Za-z0-9 ._\-]{0,29}:\s+)", text)
        prefix = m.group(0) if m else ""
        content = text[len(prefix):] if prefix else text
        filtered = content
        for word in self._word_set:
            if " " not in word:
                filtered = re.compile(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])[:\s]*", re.I).sub("", filtered)
        for word in self._word_set:
            if " " in word:
                filtered = re.compile(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])[:\s]*", re.I).sub("", filtered)
        for pat in self._patterns:
            filtered = pat.sub("", filtered)
        filtered = re.sub(r"\s*:\s*(?=\s|$)", "", filtered)
        filtered = re.sub(r"\s+", " ", filtered).strip()
        if not filtered:
            return ""
        return prefix + filtered

    def is_blacklisted(self, text: str) -> bool:
        return not self.filter_text(text).strip()

    def to_dict(self) -> dict[str, object]:
        return {"custom_words": self.custom_words, "enabled_presets": self.enabled_presets, "presets": list(PRESETS.keys())}
