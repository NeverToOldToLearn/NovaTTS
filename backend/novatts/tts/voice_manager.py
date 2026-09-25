"""Voice orchestration for NovaTTS.

Bridges the speaker registry (``speaker → voice``) to the Qwen backend
and caches generated audio on disk by content hash. The cache key
includes text, voice, instruct and emotion so changing a mapping
produces fresh audio without interfering with existing speakers.

This module never holds mutable voice state across calls — the historic
"Qwen couples voices on the GPU and the override slowly leaks" bug is
structurally impossible here.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from ..config import settings
from ..models import Dialogue, SpeakRequest
from ..registry.speakers import SpeakerRegistry
from ..text_clean import clean_emotion_text
from .base import TTSBackend

log = logging.getLogger(__name__)


class VoiceManager:
    def __init__(
        self,
        backend: TTSBackend,
        registry: SpeakerRegistry,
        cache_dir: str | Path = "",
    ) -> None:
        self.backend = backend
        self.registry = registry
        self.cache_dir = Path(cache_dir or settings.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

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
        """Synthesize a line, returning the WAV path (cache hit when possible)."""
        text = dialogue.text.strip()
        if not text:
            raise ValueError("Cannot synthesize empty text")

        speaker = getattr(dialogue, "speaker", None)
        instruct = getattr(dialogue, "instruct", "") or ""
        emotion = getattr(dialogue, "emotion", "") or ""

        voice = self.resolve_voice(speaker, voice_override)
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
        )
        log.info("Synthesized %s -> %s (voice=%s)", text[:40], path.name, voice)
        return path

    def is_cached(self, dialogue: Dialogue | SpeakRequest) -> bool:
        text = dialogue.text.strip()
        if not text:
            return False
        speaker = getattr(dialogue, "speaker", None)
        instruct = getattr(dialogue, "instruct", "") or ""
        emotion = getattr(dialogue, "emotion", "") or ""
        voice = self.resolve_voice(speaker, None)
        return self._cache_path(text, voice, instruct, emotion).exists()

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
        """Remove all cached synthesis output.

        The cache is an ephemeral, session-scoped dedup store: it exists to
        avoid re-synthesizing a line that plays repeatedly within one run.
        Clearing it on clean shutdown keeps it from growing unboundedly
        across sessions (a voice mapping change would otherwise force a full
        rebuild anyway).
        """
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
