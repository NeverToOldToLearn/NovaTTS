"""Shared data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dialogue:
    """A single line of dialogue, normalized from any input pipeline."""

    speaker: str | None
    """Speaker name, or None for narator/unknown. Case preserved."""

    text: str
    """The spoken line, stripped and normalized."""

    source: str = "renpy"
    """Pipeline origin: "renpy", "luna", or "api"."""

    instruct: str = ""
    """Optional voice-design instruction hint for the TTS model."""

    @property
    def is_voiceable(self) -> bool:
        return bool(self.text.strip())


@dataclass
class SpeakResult:
    """Result of a speak request."""

    status: str = "queued"
    """One of: queued, playing, done, error, skipped."""

    speaker: str | None = None
    voice: str = ""
    cache_hit: bool = False
    output_path: str | None = None
    error: str | None = None


@dataclass
class Speaker:
    name: str
    voice: str = ""
    instruct: str = ""
    emotion: str = "neutral"

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "voice": self.voice, "instruct": self.instruct, "emotion": self.emotion}


@dataclass
class SpeakRequest:
    """API request body for POST /speak."""

    text: str = ""
    speaker: str | None = None
    instruct: str = ""
    emotion: str = "neutral"
    voice: str | None = None
    """Manual voice override; bypasses the registry lookup."""

    def is_valid(self) -> bool:
        return bool(self.text.strip())


@dataclass
class Event:
    """Event emitted on the websocket channel."""

    type: str
    payload: dict[str, object] = field(default_factory=dict)
