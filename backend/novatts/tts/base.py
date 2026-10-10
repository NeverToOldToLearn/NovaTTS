"""TTS backend interface."""

from __future__ import annotations

import abc
from collections.abc import Callable, Iterator
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
        wav_bytes: bytes | None = None,
        *,
        ref_text: str = "",
        spk_bytes: bytes | None = None,
        rvq_bytes: bytes | None = None,
    ) -> None:
        """Clone a voice on the backend (no-op by default).

        Either ``wav_bytes`` (server-side extraction) or the pre-extracted
        ``spk_bytes`` + ``rvq_bytes`` pair must be provided.
        """
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

    def synthesize_stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        instruct: str | None = None,
        emotion: str | None = None,
        params: dict[str, object] | None = None,
        chunk_size: int = 65536,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Iterator[bytes]:
        """Yield s16le 24 kHz mono PCM blocks as they are generated.

        The default implementation synthesizes to a temp WAV and replays it
        in chunks, so backends without true streaming still work (without
        the latency win). Must be closed by the caller; may raise
        NotImplementedError only when even the fallback cannot run.
        """
        import tempfile

        from .pcm import file_to_pcm24

        with tempfile.TemporaryDirectory(prefix="novatts-stream-") as tmp:
            out = Path(tmp) / "full.wav"
            self.synthesize(text, out, voice=voice, instruct=instruct, emotion=emotion, params=params)
            pcm = file_to_pcm24(out)
            if pcm is None:
                raise RuntimeError("stream fallback could not decode its own synthesis")
            for off in range(0, len(pcm), chunk_size):
                if is_cancelled is not None and is_cancelled():
                    break
                yield pcm[off : off + chunk_size]
