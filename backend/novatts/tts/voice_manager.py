"""Voice orchestration for NovaTTS.

Bridges the speaker registry (``speaker → voice``) to the Qwen backend.
The content-hash cache inherited from the source project is off by default
(``NOVATTS_CACHE_ENABLED``): it existed when a synthesis was expensive
enough to deduplicate, and replaying a stored take also replays whatever
emotion the model happened to put in it that one time. With it off every
line is synthesized fresh into a throwaway file that is deleted once it has
been played. When it is switched on, the key includes text, voice, instruct
and emotion so changing a mapping produces fresh audio without interfering
with existing speakers.

This module never holds mutable voice state across calls — the historic
"Qwen couples voices on the GPU and the override slowly leaks" bug is
structurally impossible here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from pathlib import Path

from ..config import settings
from ..models import Dialogue, SpeakRequest
from ..registry.speakers import SpeakerRegistry
from ..text_clean import clean_emotion_text
from .base import TTSBackend

log = logging.getLogger(__name__)


def default_voice_for_new_speaker(voices: list[str], used: set[str] | None = None) -> str:
    """Pick a default voice for a newly discovered character.

    Most samples are female and male samples are prefixed ``M-`` (or
    ``M_``), so a new character — statistically most likely female — gets
    an *unused* female voice first (alphabetically). Only when every female
    voice is taken does it fall back to an unused male voice, then to a
    reused female voice, and finally to ``""`` (model default) when there
    are no voices at all (e.g. engine offline). Always overridable in
    the GUI.
    """
    candidates = sorted({v for v in voices if v})
    if not candidates:
        return ""
    is_female = lambda v: not v.lower().startswith(("m-", "m_"))
    female = [v for v in candidates if is_female(v)]
    used_set = {u for u in (used or set()) if u}
    unused = [v for v in candidates if v not in used_set]
    unused_female = [v for v in unused if is_female(v)]
    if unused_female:
        return unused_female[0]
    if unused:
        return unused[0]
    if female:
        return female[0]
    return candidates[0]


class VoiceManager:
    def __init__(
        self,
        backend: TTSBackend,
        registry: SpeakerRegistry,
        cache_dir: str | Path = "",
        cache_enabled: bool | None = None,
    ) -> None:
        self.backend = backend
        self.registry = registry
        self.cache_dir = Path(cache_dir or settings.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_enabled = settings.cache_enabled if cache_enabled is None else cache_enabled
        # Throwaway files created while the cache is off, waiting to be deleted
        # after playback. A lock because synthesis runs on the clipboard worker
        # while /speak and voice previews arrive on request threads.
        self._ephemeral: set[Path] = set()
        self._ephemeral_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_voice(self, speaker: str | None, override: str | None = None) -> str:
        """Determine the voice id for a speaker, preferring an explicit
        request-level override. Unknown speakers resolve to the
        registry fallback voice — never a new slot."""
        if override:
            return override
        return self.registry.lookup_voice(speaker)

    def synthesize(
        self,
        dialogue: Dialogue | SpeakRequest,
        *,
        voice_override: str | None = None,
    ) -> Path:
        """Synthesize a line, returning the WAV path (cache hit when enabled)."""
        text = dialogue.text.strip()
        if not text:
            raise ValueError("Cannot synthesize empty text")

        speaker = getattr(dialogue, "speaker", None)
        instruct = getattr(dialogue, "instruct", "") or ""
        emotion = getattr(dialogue, "emotion", "") or ""

        voice = self.resolve_voice(speaker, voice_override)
        if not self.cache_enabled:
            # No dedup: a fresh file every time, keyed by nothing. release()
            # removes it again once the player is done with it.
            path = self._throwaway_path()
        else:
            path = self._cache_path(text, voice, instruct, emotion)
            if path.exists():
                log.debug("Cache hit: %s", path.name)
                return path

        self.backend.synthesize(
            text,
            path,
            voice=voice,
            instruct=instruct,
            emotion=emotion,
            params=self._sampling_params(),
        )
        self._ensure_level(path)
        log.info("Synthesized %s -> %s (voice=%s)", text[:40], path.name, voice)
        return path

    def release(self, path: Path | str | None) -> None:
        """Delete a throwaway file after it finished playing.

        Only ever touches files this manager created with the cache off: an
        emotion sound or a cached take must survive. Never raises -- a failed
        cleanup must not interrupt playback bookkeeping.
        """
        if path is None:
            return
        p = Path(path)
        with self._ephemeral_lock:
            if p not in self._ephemeral:
                return
            self._ephemeral.discard(p)
        try:
            p.unlink(missing_ok=True)
        except Exception as exc:
            log.warning("Could not remove throwaway file %s: %s", p.name, exc)

    def is_cached(self, dialogue: Dialogue | SpeakRequest) -> bool:
        text = dialogue.text.strip()
        if not text or not self.cache_enabled:
            return False
        speaker = getattr(dialogue, "speaker", None)
        instruct = getattr(dialogue, "instruct", "") or ""
        emotion = getattr(dialogue, "emotion", "") or ""
        voice = self.resolve_voice(speaker, None)
        return self._cache_path(text, voice, instruct, emotion).exists()

    def _ensure_level(self, path: Path) -> None:
        """Peak-normalize one file to the configured target, if enabled.

        Runs on fresh syntheses and -- via synthesize() -- on every file the
        cache serves: a quiet line cached before this existed must not play
        quietly forever behind its hash. Never raises; a loudness fix that
        breaks playback is worse than a quiet line.
        """
        if not settings.normalize_audio:
            return
        try:
            from .normalize import normalize_wav

            gain = normalize_wav(path, target_peak=settings.normalize_target_peak)
            if gain != 1.0:
                log.debug("Normalized %s (gain %.2f)", path.name, gain)
        except Exception as exc:
            log.warning("Normalization skipped for %s: %s", path.name, exc)

    def voice_options(self) -> list[str]:
        """Voices the GUI can pick from, prefixed with an explicit default."""
        return self.backend.list_voices()

    def register_voice(
        self,
        name: str,
        wav_bytes: bytes | None = None,
        *,
        ref_text: str = "",
        spk_bytes: bytes | None = None,
        rvq_bytes: bytes | None = None,
    ) -> None:
        """Clone a voice on the TTS backend from a WAV sample or a
        pre-extracted .spk/.rvq pair (see ``Qwen3Backend.register_voice``)."""
        self.backend.register_voice(
            name,
            wav_bytes,
            ref_text=ref_text,
            spk_bytes=spk_bytes,
            rvq_bytes=rvq_bytes,
        )

    def delete_voice(self, name: str) -> None:
        del_fn = getattr(self.backend, "delete_voice", None)
        if callable(del_fn):
            del_fn(name)

    def clear_cache(self) -> None:
        """Remove every synthesis output this manager wrote.

        Both cache modes land in the same directory: hashed takes when the
        cache is on, throwaway ``live-`` files when it is off. Either way it is
        ephemeral and session-scoped, so clearing it on clean shutdown keeps it
        from growing unboundedly (a voice mapping change would otherwise force
        a full rebuild anyway). Throwaway files still queued for playback are
        released too, so release() cannot try to delete them twice.
        """
        with self._ephemeral_lock:
            self._ephemeral.clear()
        if not self.cache_dir.exists():
            return
        try:
            removed = 0
            for p in self.cache_dir.iterdir():
                if p.is_file():
                    p.unlink()
                    removed += 1
            if removed:
                log.info("Cache cleared: removed %d file(s) from %s", removed, self.cache_dir)
        except Exception as exc:
            log.warning("Failed to clear cache %s: %s", self.cache_dir, exc)

    def clean_dialogue(self, dialogue: Dialogue) -> Dialogue:
        cleaned = clean_emotion_text(dialogue.text)
        if cleaned == dialogue.text:
            return dialogue
        return Dialogue(speaker=dialogue.speaker, text=cleaned, source=dialogue.source, instruct=dialogue.instruct)

    def health(self) -> bool:
        return self.backend.is_available()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.strip().split())

    def _throwaway_path(self) -> Path:
        """Reserve an unused filename for a line that is never deduplicated."""
        path = self.cache_dir / f"live-{uuid.uuid4().hex}.wav"
        with self._ephemeral_lock:
            self._ephemeral.add(path)
        return path

    @staticmethod
    def _sampling_params() -> dict[str, object]:
        """Explicit sampling values, so no request runs on a random draw.

        qwentts.cpp leaves every one of these unset by default and then samples
        at temperature 0.9 with top_p 1.0 under a fresh hardware seed. That is
        why the same sentence could come out clean once and, the next time,
        trail off past its own full stop into a breath or a hic. Sent on every
        call, they also make a line repeatable -- which the disk cache used to
        provide, only without writing anything to disk.
        """
        return {
            "seed": settings.qwen_seed,
            "temperature": settings.qwen_temperature,
            "top_p": settings.qwen_top_p,
            "top_k": settings.qwen_top_k,
            "repetition_penalty": settings.qwen_repetition_penalty,
        }

    def _cache_path(
        self,
        text: str,
        voice: str,
        instruct: str,
        emotion: str,
    ) -> Path:
        payload = json.dumps(
            {
                "engine": "qwen3",
                "text": self._normalize(text),
                "voice": voice,
                "instruct": self._normalize(instruct),
                "emotion": emotion,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
        key = hashlib.md5(payload).hexdigest()
        return self.cache_dir / f"{key}.wav"
