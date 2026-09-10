from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pygame

from .config import settings


class EmotionSounds:
    def __init__(self, player: object | None = None) -> None:
        self.dir = Path(settings.emotion_sounds_dir) if hasattr(settings, "emotion_sounds_dir") else Path(r"C:\Piper\emotion_sounds")
        self.map_file = Path(settings.emotion_sound_map_file) if hasattr(settings, "emotion_sound_map_file") else settings.cache_dir.parent / "emotion_sound_map.json"
        self.patterns_file = Path(settings.emotion_patterns_file) if hasattr(settings, "emotion_patterns_file") else settings.cache_dir.parent / "emotion_patterns.json"
        self.aliases_file = Path(settings.emotion_aliases_file) if hasattr(settings, "emotion_aliases_file") else settings.cache_dir.parent / "emotion_aliases.json"
        self._player = player
        self._lock = threading.Lock()
        self.sound_map: dict[str, str] = {}
        self.pattern_defs: list[dict[str, object]] = []
        self.compiled: list[tuple[re.Pattern[str], str | None]] = []
        self.aliases: dict[str, str] = {}
        self._reload()

    def _discover(self) -> dict[str, str]:
        if not self.dir.exists():
            return {}
        out: dict[str, str] = {}
        for p in list(self.dir.glob("*.wav")) + list(self.dir.glob("*.ogg")) + list(self.dir.glob("*.opus")) + list(self.dir.glob("*.mp3")):
            try:
                if p.stat().st_size > 0:
                    out[p.stem.lower()] = p.name
            except OSError:
                continue
        return out

    def _reload(self) -> None:
        avail = self._discover()
        if not self.map_file.exists():
            self.sound_map = avail
            try:
                self.map_file.parent.mkdir(parents=True, exist_ok=True)
                self.map_file.write_text(json.dumps(self.sound_map, indent=2), encoding="utf-8")
            except Exception:
                pass
        else:
            try:
                raw = json.loads(self.map_file.read_text(encoding="utf-8"))
                parsed = {str(k).lower().strip(): str(v).strip() for k, v in raw.items() if str(k).strip()}
                cleaned = {k: v for k, v in parsed.items() if k in avail}
                self.sound_map = cleaned or avail
            except Exception:
                self.sound_map = avail
        try:
            if self.patterns_file.exists():
                data = json.loads(self.patterns_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.pattern_defs = data
            else:
                self.pattern_defs = []
        except Exception:
            pass
        try:
            if self.aliases_file.exists():
                raw2 = json.loads(self.aliases_file.read_text(encoding="utf-8"))
                self.aliases = {str(k).lower().strip(): str(v).lower().strip() for k, v in raw2.items() if str(k).strip() and str(v).strip()}
            else:
                self.aliases = {}
        except Exception:
            self.aliases = {}
        self.compiled = []
        for item in self.pattern_defs:
            if not isinstance(item, dict):
                continue
            pat_obj = item.get("pattern")
            tag_obj = item.get("tag")
            pat = str(pat_obj) if isinstance(pat_obj, str) else None
            tag = str(tag_obj) if isinstance(tag_obj, str) else None
            if not pat:
                continue
            try:
                self.compiled.append((re.compile(pat, re.I), tag))
            except re.error:
                continue

    def reload(self) -> None:
        self._reload()

    def normalize_tag(self, tag: str) -> str:
        base = re.sub(r"[^a-z]", "", tag.lower())
        if not base:
            return ""
        if base in self.sound_map:
            return base
        for cand in [re.sub(r"(.)\1{2,}", r"\1\1", base), base.rstrip("m"), base.rstrip("s"), base.rstrip("ms")]:
            if cand and cand in self.sound_map:
                return cand
        for k in sorted(self.sound_map.keys(), key=len, reverse=True):
            if base.startswith(k):
                return k
        return base

    def extract(self, text: str) -> tuple[str, list[tuple[int, str]]]:
        pats: list[tuple[re.Pattern[str], str | None]] = []
        for expr, tag in self.aliases.items():
            esc = re.escape(expr)
            pats.append((re.compile(rf"\*{esc}\*", re.I), tag))
            pats.append((re.compile(rf"\b{esc}\b", re.I), tag))
        pats.extend(self.compiled)
        raw: list[tuple[int, int, str | None]] = []
        for pat, t in pats:
            for m in pat.finditer(text):
                raw.append((m.start(), m.end(), t))
        raw.sort(key=lambda x: x[0])
        parts: list[str] = []
        positions: list[tuple[int, str]] = []
        removed = 0
        last = 0
        for s, e, tag_opt in raw:
            if s < last:
                continue
            parts.append(text[last:s])
            if tag_opt is not None:
                positions.append((s - removed, str(tag_opt)))
            last = e
            removed += e - s
        parts.append(text[last:])
        cleaned = "".join(parts).replace("*", "")
        return cleaned, positions

    def resolve_path(self, tag: str) -> Path | None:
        norm = self.normalize_tag(tag)
        fname = self.sound_map.get(norm)
        if not fname:
            return None
        base = Path(fname).stem if Path(fname).suffix else fname
        for ext in [".wav", ".ogg", ".opus", ".mp3", ""]:
            p = self.dir / (base + ext) if ext else self.dir / fname
            if p.exists():
                return p
        cand2 = self.dir / fname
        if cand2.exists():
            return cand2
        return None

    def play(self, tag: str) -> bool:
        cand = self.resolve_path(tag)
        if cand is None:
            return False
        if self._player is not None:
            try:
                enqueue = getattr(self._player, "enqueue", None)
                if callable(enqueue):
                    enqueue(cand)
                    return True
            except Exception:
                pass
        try:
            pygame.mixer.music.load(str(cand))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            return True
        except Exception:
            return False

    def enqueue(self, tag: str) -> bool:
        cand = self.resolve_path(tag)
        if cand is None:
            return False
        if self._player is not None:
            try:
                enqueue = getattr(self._player, "enqueue", None)
                if callable(enqueue):
                    enqueue(cand)
                    return True
            except Exception:
                pass
        return self.play(tag)

    def to_dict(self) -> dict[str, object]:
        return {"dir": str(self.dir), "sounds": len(self.sound_map), "map": self.sound_map, "aliases": self.aliases, "patterns": len(self.pattern_defs)}
