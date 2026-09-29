"""Thread-safe speaker registry backed by a JSON file.

Single source of truth for speaker → voice/instruct/emotion mappings.

Invariants:
- Unknown speakers NEVER get a new voice slot; they fall back to
  ``Narrator`` at call sites and are never auto-registered from Luna.
- Mutations happen only through this class (lock-protected) and are
  persisted to disk either explicitly or after an auto-save interval.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from ..models import Speaker

log = logging.getLogger(__name__)

_FALLBACK_SPEAKER = "Narrator"


class SpeakerRegistry:
    def __init__(
        self,
        file_path: str | Path,
        auto_save_interval: float = 30.0,
        fallback_speaker: str = _FALLBACK_SPEAKER,
    ) -> None:
        self.file_path = Path(file_path)
        self.auto_save_interval = auto_save_interval
        self.fallback_speaker = fallback_speaker

        self._speakers: dict[str, Speaker] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._last_save = 0.0

        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, name: str | None) -> Speaker:
        """Resolve a speaker by name, falling back to the registered
        fallback speaker when unknown. Never auto-registers."""

        with self._lock:
            if not name:
                return self._get_fallback_locked()
            return self._speakers.get(name, self._get_fallback_locked())

    def lookup_voice(self, name: str | None) -> str:
        """Return the voice id for a speaker (safe default if unknown)."""
        return self.get(name).voice

    def register(self, name: str) -> Speaker:
        """Explicitly register a speaker if absent (RenPy auto-register
        path or GUI). Returns the existing speaker when already known."""
        name = name.strip()
        if not name:
            raise ValueError("Speaker name must not be empty")

        with self._lock:
            existing = self._speakers.get(name)
            if existing is not None:
                return existing
            speaker = Speaker(name=name)
            self._speakers[name] = speaker
            self._mark_dirty_locked()
            log.info("Registered new speaker: %s", name)
            return speaker

    def update(
        self, name: str, *, voice: str | None = None, instruct: str | None = None, emotion: str | None = None,
    ) -> Speaker | None:
        """Set one or more fields on a known speaker. ``None`` means "leave
        this field alone", so an absent key is not a request to clear it.
        Use ``""`` to clear a field.

        ``instruct`` was accepted here and then silently dropped (G5.5): the
        parameter was in the signature and the assignment was simply missing.
        To clear it, send ``""`` -- an empty string is stored as-is, which is
        why ``None`` must not be treated as a clear.

        What the audit called one bug was four, and the extra three are all in
        the chain this method sits in:

        1. this assignment, missing;
        2. ``SpeakerPatchBody`` had no ``instruct``/``emotion`` field at all;
        3. ``update_speaker()`` forwarded only ``voice``;
        4. ``_load()`` read only ``voice`` back, so even a value that reached
           the file was gone again after a restart.

        2, 3 and 4 are why the docstring originally claimed the endpoint
        forwarded ``instruct``: it did not, and the claim was read off a grep
        hit that belonged to ``/speak``. See D33 and D34.

        Tests: ``test_update_stores_the_instruct`` (this method),
        ``test_speaker_patch_api.py`` (the endpoint), and
        ``test_load_restores_the_instruct`` (the restart direction, which
        the other two cannot see).
        """
        with self._lock:
            speaker = self._speakers.get(name)
            if speaker is None:
                log.warning("Cannot update unknown speaker: %s", name)
                return None
            if voice is not None:
                speaker.voice = voice
            if instruct is not None:
                speaker.instruct = instruct
            if emotion is not None:
                speaker.emotion = emotion
            self._mark_dirty_locked()
            return speaker

    def remove(self, name: str) -> bool:
        with self._lock:
            if name not in self._speakers:
                return False
            del self._speakers[name]
            self._mark_dirty_locked()
            log.info("Removed speaker: %s", name)
            return True

    def rename(self, old: str, new: str) -> Speaker | None:
        """Rename a speaker (strip/fix). Returns None if missing or new exists."""
        old = old.strip()
        new = new.strip()
        if not old or not new or old == new:
            return None
        with self._lock:
            if old not in self._speakers or new in self._speakers:
                return None
            spk = self._speakers.pop(old)
            spk.name = new
            self._speakers[new] = spk
            self._mark_dirty_locked()
            log.info("Renamed speaker %r -> %r", old, new)
            return spk

    def alias(self, source: str, alias: str) -> Speaker | None:
        """Create an alias entry copying voice/instruct/emotion from source."""
        source = source.strip()
        alias = alias.strip()
        if not source or not alias or alias in self._speakers:
            return None
        with self._lock:
            src = self._speakers.get(source)
            if src is None:
                return None
            spk = Speaker(name=alias, voice=src.voice, instruct=src.instruct, emotion=src.emotion)
            self._speakers[alias] = spk
            self._mark_dirty_locked()
            log.info("Aliased speaker %r -> %r (voice=%r)", source, alias, src.voice)
            return spk

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._speakers)

    def all(self) -> list[Speaker]:
        with self._lock:
            return [s for s in self._speakers.values()]

    def to_dict(self) -> dict[str, object]:
        with self._lock:
            return {
                "versions": 1,
                "speakers": {name: spk.to_dict() for name, spk in sorted(self._speakers.items())},
            }

    def save(self) -> None:
        """Persist to disk unconditionally (GUI/save action)."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.file_path)
        with self._lock:
            self._dirty = False
            self._last_save = time.monotonic()
        log.debug("Speaker registry saved to %s", self.file_path)

    def maybe_autosave(self) -> None:
        """Persist only when dirty and the interval has elapsed. Call
        periodically from the main server loop."""
        with self._lock:
            if not self._dirty:
                return
            if time.monotonic() - self._last_save < self.auto_save_interval:
                return
            should_save = True
        if should_save:
            self.save()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.file_path.exists():
            self._speakers = {self.fallback_speaker: Speaker(name=self.fallback_speaker)}
            self.save()
            return
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            raw = data.get("speakers", data) if isinstance(data, dict) else {}
            speakers: dict[str, Speaker] = {}
            for name, cfg in raw.items():
                if isinstance(cfg, dict):
                    raw_voice = cfg.get("voice", "")
                    if raw_voice == "default":
                        raw_voice = ""
                    # ``instruct`` and ``emotion`` are written by
                    # ``Speaker.to_dict()`` on every save, and for years this
                    # line threw them away -- only ``voice`` was read back.
                    # So a speaker saved with an instruction came up empty
                    # after a restart, and ``GET /speakers`` then reported
                    # ``""`` for a file that plainly said otherwise. The API
                    # was confidently wrong, which is the same failure class
                    # as the missing assignment in ``update()`` (G5.5), just
                    # one restart later and in the opposite direction.
                    #
                    # ``or ""`` / ``or "neutral"`` also absorb a literal
                    # ``null`` in a hand-edited file, which would otherwise
                    # put a None where the dataclass promises a str.
                    speakers[name] = Speaker(
                        name=name,
                        voice=raw_voice,
                        instruct=cfg.get("instruct") or "",
                        emotion=cfg.get("emotion") or "neutral",
                    )
            if self.fallback_speaker not in speakers:
                speakers[self.fallback_speaker] = Speaker(name=self.fallback_speaker)
            self._speakers = speakers
            log.info("Loaded %d speakers from %s", len(speakers), self.file_path)
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Failed to load speaker registry: %s (using defaults)", exc)
            self._speakers = {self.fallback_speaker: Speaker(name=self.fallback_speaker)}

    def _get_fallback_locked(self) -> Speaker:
        return self._speakers.get(self.fallback_speaker, Speaker(name=self.fallback_speaker))

    def _mark_dirty_locked(self) -> None:
        self._dirty = True
