from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import pygame

from .config import settings

_EXTENSIONS: tuple[str, ...] = (".wav", ".ogg", ".opus", ".mp3")


def _slug(value: str) -> str:
    """Lowercase alphanumeric key used for fuzzy tag matching."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


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
        self._on_disk: dict[str, str] = {}
        self._slug_index: dict[str, str] = {}
        self._reload()

    # ------------------------------------------------------------------
    # Disk discovery
    # ------------------------------------------------------------------
    def _discover(self) -> dict[str, str]:
        """Every playable file in the folder, keyed by lowercase stem."""
        if not self.dir.exists():
            return {}
        out: dict[str, str] = {}
        try:
            entries = list(self.dir.iterdir())
        except OSError:
            return {}
        for p in entries:
            if not p.is_file() or p.suffix.lower() not in _EXTENSIONS:
                continue
            try:
                if p.stat().st_size > 0:
                    out[p.stem.lower()] = p.name
            except OSError:
                continue
        return out

    def _resolve_file(self, fname: str) -> Path | None:
        """Turn a map value (filename) into a real path, tolerating ext changes."""
        if not fname:
            return None
        base = Path(fname).stem if Path(fname).suffix else fname
        for ext in (*_EXTENSIONS, ""):
            p = self.dir / (base + ext) if ext else self.dir / fname
            if p.exists():
                return p
        return None

    def _read_map(self) -> dict[str, str]:
        if not self.map_file.exists():
            return {}
        try:
            raw = json.loads(self.map_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k).lower().strip(): str(v).strip() for k, v in raw.items() if str(k).strip() and str(v).strip()}

    def _write_map(self, data: dict[str, str]) -> None:
        try:
            self.map_file.parent.mkdir(parents=True, exist_ok=True)
            self.map_file.write_text(json.dumps(dict(sorted(data.items())), indent=4), encoding="utf-8")
        except Exception:
            pass

    def _reload(self) -> None:
        avail = self._discover()
        saved = self._read_map()

        # The folder is the source of truth; the map file is a cache of it plus
        # optional custom keys. A saved entry only survives while the file it
        # points at still exists, so new/renamed/removed files are picked up.
        merged = dict(avail)
        for key, fname in saved.items():
            if key in avail:
                # Tag is discovered too: keep the real filename unless the map
                # deliberately points it at a different existing file.
                if fname.lower() == avail[key].lower():
                    continue
                resolved = self._resolve_file(fname)
                if resolved is not None and resolved.name.lower() != avail[key].lower():
                    merged[key] = fname
                continue
            if self._resolve_file(fname) is not None:
                merged[key] = fname

        self._on_disk = avail
        self.sound_map = merged
        if merged != saved:
            self._write_map(merged)

        self._slug_index = {}
        for key in merged:
            slug = _slug(key)
            if slug and slug not in self._slug_index:
                self._slug_index[slug] = key
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
        raw = tag.lower().strip()
        if not raw:
            return ""
        if raw in self.sound_map:
            return raw
        base = _slug(raw)
        if not base:
            return ""
        if base in self.sound_map:
            return base
        if base in self._slug_index:
            return self._slug_index[base]
        for cand in [re.sub(r"(.)\1{2,}", r"\1\1", base), base.rstrip("m"), base.rstrip("s"), base.rstrip("ms")]:
            hit = self._slug_index.get(cand) if cand else None
            if hit:
                return hit
        for slug in sorted(self._slug_index, key=len, reverse=True):
            if slug and base.startswith(slug):
                return self._slug_index[slug]
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

    def plan(self, cleaned: str, positions: list[tuple[int, str]]) -> list[tuple[str, str]]:
        """Ordered playback plan for a cleaned line.

        Returns ("text", chunk) and ("sound", tag) items in document order, so
        a sound still lands between the words around it. Two things are
        handled here that used to leak into the TTS backend:

        - A chunk with nothing pronounceable in it is dropped. Stripping
          "Aah!" leaves "!", and a lone "." costs a synthesis request and
          comes back as a garbled blip.
        - Every chunk after the first begins exactly where an emotion word
          was removed, so it can start with stranded punctuation
          ("Aah! Yes..." -> "Yes..."). A trailing "..." on real text is
          deliberate prosody and is left alone.
        """
        from .text_clean import has_speakable_text, strip_leading_punctuation

        ordered = sorted(positions)
        out: list[tuple[str, str]] = []
        last = 0
        for pos, tag in ordered:
            chunk = cleaned[last:pos]
            if last > 0:
                chunk = strip_leading_punctuation(chunk)
            chunk = chunk.strip()
            if has_speakable_text(chunk):
                out.append(("text", chunk))
            out.append(("sound", tag))
            last = pos
        tail = strip_leading_punctuation(cleaned[last:]) if ordered else cleaned[last:]
        tail = tail.strip()
        if has_speakable_text(tail):
            out.append(("text", tail))
        return out

    def resolve_path(self, tag: str) -> Path | None:
        norm = self.normalize_tag(tag)
        fname = self.sound_map.get(norm)
        if not fname:
            return None
        return self._resolve_file(fname)

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
        return {
            "dir": str(self.dir),
            "sounds": len(self.sound_map),
            "on_disk": len(self._on_disk),
            "map": self.sound_map,
            "aliases": self.aliases,
            "patterns": len(self.pattern_defs),
        }
