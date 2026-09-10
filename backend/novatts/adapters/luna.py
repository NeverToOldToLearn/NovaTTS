"""Luna Hook / Textractor adapter (V2 placeholder).

Pipeline B connects to a Luna Hook / Textractor websocket (default
``ws://127.0.0.1:6677``) for games that do not support the RenPy
clipboard format (Unity, Unreal, ...). Not implemented in V1.
"""

from __future__ import annotations

import logging

from ..models import Dialogue
from .base import DialogueCallback, InputAdapter

log = logging.getLogger(__name__)


class LunaAdapter(InputAdapter):
    """Placeholder for the Luna Hook websocket pipeline (V2)."""

    def __init__(
        self, on_dialogue: DialogueCallback, host: str = "127.0.0.1", port: int = 6677
    ) -> None:
        super().__init__(on_dialogue)
        self.host = host
        self.port = port

    @property
    def name(self) -> str:
        return "luna"

    def start(self) -> None:
        log.warning("LunaAdapter is a V2 placeholder - not started")

    def stop(self) -> None:
        pass

    def is_running(self) -> bool:
        return False

    def _handle_hook_text(self, raw: str) -> Dialogue | None:
        """Reserved: normalize raw hook text into a Dialogue (V2)."""
        raise NotImplementedError("Luna pipeline lands in V2")
