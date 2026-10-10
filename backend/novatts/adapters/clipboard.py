"""RenPy clipboard adapter.

Polls the system clipboard for Ren'Py ``copy_voice_to_clipboard`` output
(``Name: Text``) and forwards normalized dialogue to the callback.

Gate order matters: the blacklist runs on the RAW clipboard string, before
the parser picks a speaker. A game that keeps its HUD visible pushes lines
like ``250 $: Rick: Hi``; filtering the raw line removes the HUD value and
leaves the real speaker, instead of handing the leftover to the narrator.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable

import pyperclip

from ..blacklist import Blacklist, is_renpy_exception
from ..config import settings
from ..parser.renpy import RenPyParser
from .base import DialogueCallback, FilteredCallback, InputAdapter
from .rawclipboard import RawClipboardLogger

log = logging.getLogger(__name__)


class ClipboardAdapter(InputAdapter):
    """Poll-based adapter for the RenPy clipboard pipeline."""

    def __init__(self, on_dialogue: DialogueCallback, blacklist: Blacklist | None = None, on_filtered: FilteredCallback | None = None) -> None:
        super().__init__(on_dialogue, on_filtered)
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_clipboard: str = ""
        self.parser = RenPyParser()
        self.blacklist = blacklist
        self.raw_log = RawClipboardLogger(
            settings.clipboard_raw_log,
            enabled=settings.log_raw_clipboard,
        )

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
            # Raw capture logged before ANY preprocessing so the exact source
            # text is available for regex/filter tuning.
            if is_renpy_exception(current):
                self.raw_log.log_entry(current, "BLOCKED:renpy_exception")
                log.debug("Skipping RenPy exception dump: %r", current[:80])
                self.notify_filtered("renpy_exception", current)
                return

            if len(current) < settings.min_text_length:
                self.raw_log.log_entry(current, "BLOCKED:too_short")
                return
            if self._is_garbage(current):
                self.raw_log.log_entry(current, "BLOCKED:garbage")
                log.debug("Skipping non-dialogue clipboard: %r", current[:60])
                self.notify_filtered("garbage", current)
                return

            # Blacklist BEFORE parsing: the whole raw line is filtered, so
            # UI junk in front of a real speaker is removed and only the
            # dialogue is left to pick a voice from. A registered speaker
            # name is protected so a blacklisted word that happens to be a
            # character name cannot swallow it.
            raw = current
            current = self._apply_blacklist(raw)
            if not current:
                return

            dialogue = self.parser.parse(current, source=self.name)
            if not dialogue.is_voiceable:
                self.raw_log.log_entry(raw, "BLOCKED:not_voiceable")
                return
            self.raw_log.log_entry(raw, "OK" if current == raw else f"OK:filtered -> {current[:80]}")
            log.debug("Clipboard -> %s: %s", dialogue.speaker, dialogue.text[:60])
            try:
                self.on_dialogue(dialogue)
            except Exception:
                log.exception("on_dialogue callback failed (swallowed)")

    def _apply_blacklist(self, raw: str) -> str:
        """Blacklist a raw capture, returning the text to parse ("" = drop)."""
        if self.blacklist is None:
            return raw
        try:
            preserve = self.parser.has_known_speaker_prefix(raw)
            filtered = self.blacklist.filter_text(raw, preserve_prefix=preserve)
        except Exception:
            log.exception("Blacklist pass failed (swallowed)")
            return raw
        if not filtered:
            self.raw_log.log_entry(raw, "BLOCKED:blacklist")
            log.debug("Blacklisted clipboard line: %r", raw[:80])
            self.notify_filtered("blacklist", raw)
        return filtered

    @staticmethod
    def _is_garbage(text: str) -> bool:
        """Reject obvious non-dialogue noise; RenPy dumps handled above."""
        lowered = text.lower()
        return (
            "traceback" in lowered
            or "exception" in lowered
            or text.startswith(("Traceback", "  File ", "RuntimeError"))
        )
