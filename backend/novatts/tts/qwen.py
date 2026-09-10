"""Qwen3-TTS HTTP backend (qwentts.cpp server).

A stateless HTTP client for the local Qwen3-TTS engine at
``http://127.0.0.1:8080``. Statelessness is deliberate: every request
carries its own ``voice`` so a speaker switch can never leak a
previous voice onto the next line (the historic GPU-leak bug).
"""

from __future__ import annotations

import logging
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
        wav_bytes: bytes,
        *,
        ref_text: str = "",
    ) -> None:
        """Clone a voice on the qwentts.cpp server from a WAV sample.

        The sample is sent as base64 in ``wav_b64`` (per tts-server.h).
        """
        import base64

        payload: dict[str, Any] = {
            "name": name,
            "wav_b64": base64.b64encode(wav_bytes).decode("ascii"),
        }
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
