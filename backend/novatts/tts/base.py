"""TTS backend interface."""

from __future__ import annotations

import abc
from pathlib import Path


class TTSBackend(abc.ABC):
    """Synthesizes text into a WAV file.

    Backends must be independent of any global voice state: every call
    carries its own voice/params so no GPU-side coupling leaks between
    calls for different speakers.
    """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Probe whether the backend can serve requests right now."""

    @abc.abstractmethod
    def list_voices(self) -> list[str]:
        """Return the available voice identifiers."""

    def register_voice(
        self,
        name: str,
        wav_bytes: bytes,
        *,
        ref_text: str = "",
    ) -> None:
        """Clone a voice on the backend from a WAV sample (no-op by default)."""
        raise NotImplementedError(f"{type(self).__name__} does not support voice cloning")

    @abc.abstractmethod
    def synthesize(
        self,
        text: str,
        output_path: str | Path,
        *,
        voice: str | None = None,
        instruct: str | None = None,
        emotion: str | None = None,
        params: dict[str, object] | None = None,
    ) -> Path:
        """Synthesize ``text`` to a WAV at ``output_path``. Raises on failure."""
