"""Qwen3-TTS HTTP backend (qwentts.cpp server).

A stateless HTTP client for the local Qwen3-TTS engine at
``http://127.0.0.1:8080``. Statelessness is deliberate: every request
carries its own ``voice`` so a speaker switch can never leak a
previous voice onto the next line (the historic GPU-leak bug).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import requests

from ..config import settings
from .base import TTSBackend

log = logging.getLogger(__name__)

_SPEECH_PARAM_KEYS = ("seed", "temperature", "top_p", "top_k", "repetition_penalty")


class Qwen3Backend(TTSBackend):
    def __init__(
        self,
        base_url: str = "",
        timeout: float = 0.0,
        default_voice: str = "",
    ) -> None:
        self.base_url = (base_url or settings.qwen_url).rstrip("/")
        self.timeout = timeout or settings.qwen_timeout
        self.default_voice = default_voice or settings.qwen_default_voice
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # TTSBackend
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        try:
            r = self._session.get(f"{self.base_url}/health", timeout=3)
            return r.status_code == 200 and r.json().get("status") == "ok"
        except Exception:
            return False

    def list_voices(self) -> list[str]:
        try:
            r = self._session.get(f"{self.base_url}/v1/audio/voices", timeout=5)
            r.raise_for_status()
            raw = r.json().get("voices", [])
            names: list[str] = []
            for entry in raw:
                if isinstance(entry, str):
                    names.append(entry)
                elif isinstance(entry, dict):
                    for key in ("name", "voice", "voice_name", "id"):
                        val = entry.get(key)
                        if val:
                            names.append(str(val))
                            break
                    else:
                        names.append(str(entry))
            return names
        except Exception as exc:
            log.warning("Could not list Qwen voices: %s", exc)
            return []

    def register_voice(
        self,
        name: str,
        wav_bytes: bytes | None = None,
        *,
        ref_text: str = "",
        spk_bytes: bytes | None = None,
        rvq_bytes: bytes | None = None,
    ) -> None:
        """Clone a voice on the qwentts.cpp server.

        The server accepts either a raw WAV sample (``wav_b64`` — the
        reference latents are extracted server side on the GPU) or the
        pre-extracted pair (``spk_b64`` + ``rvq_b64`` — taken verbatim,
        no GPU work at registration). Pass exactly one form; ``ref_text``
        enables ICL clone mode when present (per tts-server.h).
        """
        import base64

        payload: dict[str, Any] = {"name": name}
        if spk_bytes is not None and rvq_bytes is not None:
            payload["spk_b64"] = base64.b64encode(spk_bytes).decode("ascii")
            payload["rvq_b64"] = base64.b64encode(rvq_bytes).decode("ascii")
        elif wav_bytes is not None:
            payload["wav_b64"] = base64.b64encode(wav_bytes).decode("ascii")
        else:
            raise ValueError("register_voice requires wav_bytes or the spk_bytes+rvq_bytes pair")
        if ref_text:
            payload["ref_text"] = ref_text
        r = self._session.post(
            f"{self.base_url}/v1/audio/voices",
            json=payload,
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Voice registration failed ({r.status_code}): {r.text[:200]}")
        log.info("Registered cloned voice '%s'", name)

    def delete_voice(self, name: str) -> None:
        r = self._session.delete(
            f"{self.base_url}/v1/audio/voices/{name}",
            timeout=10,
        )
        if r.status_code not in (200, 204, 404):
            raise RuntimeError(f"Voice delete failed ({r.status_code}): {r.text[:200]}")
        log.info("Deleted cloned voice '%s'", name)

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
        output_path = Path(output_path)
        payload: dict[str, Any] = {
            "input": text,
            "response_format": "wav",
        }
        chosen = voice or self.default_voice
        if chosen:
            # Only send a real registered voice; empty leaves the model
            # default active (qwentts.cpp rejects unknown voice names).
            payload["voice"] = chosen
        if instruct:
            payload["instruct"] = instruct
        if emotion:
            payload["emotion"] = emotion
        if params:
            for key in _SPEECH_PARAM_KEYS:
                if key in params:
                    payload[key] = params[key]

        log.debug("Qwen synth: voice=%s chars=%d", chosen, len(text))
        r = self._session.post(
            f"{self.base_url}/v1/audio/speech",
            json=payload,
            timeout=self.timeout,
        )
        if r.status_code != 200 and chosen and "unknown voice" in r.text.lower():
            log.warning("Unknown voice '%s' — retrying with model default", chosen)
            payload.pop("voice", None)
            r = self._session.post(
                f"{self.base_url}/v1/audio/speech",
                json=payload,
                timeout=self.timeout,
            )
        if r.status_code != 200:
            raise RuntimeError(f"Qwen synthesis failed ({r.status_code}): {r.text[:200]}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(r.content)
        return output_path

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
        """Yield raw s16le 24 kHz mono PCM blocks as the engine makes them.

        Same request as :meth:`synthesize` but with ``response_format`` pcm,
        which the server sends chunked per generated frame instead of as one
        RIFF file at the end. Closing the generator (or ``is_cancelled``
        turning true) drops the connection, and the server aborts generation
        on its side instead of finishing a stream nobody reads.

        Yields are sample-aligned (even byte counts). The caller MUST close
        the generator (exhaust it, break out and ``close()`` it, or let the
        ``finally`` below run) to release the HTTP connection back to the
        pool. Mid-stream transport errors propagate to the caller, which
        should play whatever arrived so far: the server documents that a
        failure after streaming started surfaces as a truncated stream.
        """
        payload: dict[str, Any] = {
            "input": text,
            "response_format": "pcm",
        }
        chosen = voice or self.default_voice
        if chosen:
            payload["voice"] = chosen
        if instruct:
            payload["instruct"] = instruct
        if emotion:
            payload["emotion"] = emotion
        if params:
            for key in _SPEECH_PARAM_KEYS:
                if key in params:
                    payload[key] = params[key]

        log.debug("Qwen stream: voice=%s chars=%d", chosen, len(text))
        first = self._session.post(
            f"{self.base_url}/v1/audio/speech",
            json=payload,
            timeout=self.timeout,
            stream=True,
        )
        if first.status_code != 200 and chosen and "unknown voice" in first.text.lower():
            log.warning("Unknown voice '%s' — retrying stream with model default", chosen)
            first.close()
            payload.pop("voice", None)
            first = self._session.post(
                f"{self.base_url}/v1/audio/speech",
                json=payload,
                timeout=self.timeout,
                stream=True,
            )
        if first.status_code != 200:
            detail = first.text[:200]
            first.close()
            raise RuntimeError(f"Qwen streaming failed ({first.status_code}): {detail}")
        return self._read_stream(first, chunk_size=chunk_size, is_cancelled=is_cancelled)

    def _read_stream(
        self,
        response: Any,
        *,
        chunk_size: int,
        is_cancelled: Callable[[], bool] | None,
    ) -> Iterator[bytes]:
        carry = b""
        try:
            for http_chunk in response.iter_content(chunk_size=chunk_size):
                if is_cancelled is not None and is_cancelled():
                    break
                if not http_chunk:
                    continue
                data = carry + bytes(http_chunk)
                # Keep sample alignment: a chunk may split an s16 sample.
                if len(data) & 1:
                    carry = data[-1:]
                    data = data[:-1]
                else:
                    carry = b""
                if data:
                    yield data
        finally:
            response.close()
