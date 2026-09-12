"""RenPy clipboard adapter.

Polls the system clipboard for Ren'Py ``copy_voice_to_clipboard`` output
(``Name: Text``) and forwards normalized dialogue to the callback.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable

import pyperclip

from ..blacklist import is_renpy_exception
from ..config import settings
from ..parser.renpy import RenPyParser
from .base import DialogueCallback, InputAdapter

log = logging.getLogger(__name__)


class ClipboardAdapter(InputAdapter):
    """Poll-based adapter for the RenPy clipboard pipeline."""

    def __init__(self, on_dialogue: DialogueCallback) -> None:
        super().__init__(on_dialogue)
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_clipboard: str = ""
        self.parser = RenPyParser()

    @property
    def name(self) -> str:
        return "clipboard"

    def set_known_speakers(self, names: Iterable[str]) -> None:
        """Sync the parser's registry-backed name set (case-insensitive)."""
        self.parser.set_known_names(names)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="clipboard-adapter", daemon=True)
        self._thread.start()
        log.info("Clipboard adapter started (poll %.2fs)", settings.poll_interval)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("Clipboard adapter stopped")

    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception:
                log.exception("Clipboard poll error (swallowed)")
            time.sleep(settings.poll_interval)

    def _tick(self) -> None:
        current = pyperclip.paste().strip()
        if not current or current == self._last_clipboard:
            return
        self._last_clipboard = current
        if is_renpy_exception(current):
            log.debug("Skipping RenPy exception dump: %r", current[:80])
            return

        if len(current) < settings.min_text_length:
            return
        if self._is_garbage(current):
            log.debug("Skipping non-dialogue clipboard: %r", current[:60])
            return

        dialogue = self.parser.parse(current, source=self.name)
        if not dialogue.is_voiceable:
            return
        log.debug("Clipboard -> %s: %s", dialogue.speaker, dialogue.text[:60])
        try:
            self.on_dialogue(dialogue)
        except Exception:
            log.exception("on_dialogue callback failed (swallowed)")

    @staticmethod
    def _is_garbage(text: str) -> bool:
        """Reject obvious non-dialogue noise; RenPy dumps handled above."""
        lowered = text.lower()
        return (
            "traceback" in lowered
            or "exception" in lowered
            or text.startswith(("Traceback", "  File ", "RuntimeError"))
        )
