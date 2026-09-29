"""RenPy clipboard adapter — LEGACY, kept as a fallback.

Polls the system clipboard for Ren'Py ``copy_voice_to_clipboard`` output
(``Name: Text``) and forwards normalized dialogue to the callback.

DEPRECATED as the *primary* input route (F8, decision D1). It still works,
is still tested, and is still reachable — ``hook_mode=clipboard`` and
``hook_mode=both`` both start it. What changed is only which route is the
default; ``NOVATTS_HOOK_MODE`` now defaults to ``websocket``.

The filename says "legacy" so that a future agent reading ``main.py`` finds
the word instead of having to know the history. It is not a second
implementation: the gate, the registry, the blacklist and synthesis are all
downstream and shared. The only thing that differs is how the raw line is
obtained.

What the hook route does that this one cannot, and the reason the default
moved:

  * A speaker per turn. ``Anne Hallo! Rick Mooi.`` is two turns with two
    voices here; the hook splits it. The clipboard carries one line, so the
    split is information the format already threw away.
  * Live rather than polled. This polls every ``poll_interval`` seconds; the
    hook pushes on arrival.
  * A bare name on its own line is recoverable here only with
    ``NOVATTS_HOOK_DUAL_HOOK=1``; the hook sees both lines arrive.

What it still does better, and why it was not deleted: it works with no
LunaTranslator, no extension and no extra process. If your game has no hook,
this is the route. Do not remove it on the grounds that the hook is newer.
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
from .rawclipboard import RawClipboardLogger

log = logging.getLogger(__name__)


class ClipboardAdapter(InputAdapter):
    """Poll-based adapter for the RenPy clipboard pipeline.

    The class name is unchanged on purpose: renaming it would touch
    ``main.py``, the test suite and every import for no gain, and a class
    name that no longer matches its file is worse than a module whose name
    says "legacy" and a class that says what it is. The *file* carries the
    status; this docstring carries the reason.
    """

    def __init__(self, on_dialogue: DialogueCallback) -> None:
        super().__init__(on_dialogue)
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_clipboard: str = ""
        self.parser = RenPyParser()
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
        # "Clipboard adapter started" is kept verbatim as a prefix so an
        # existing grep still finds it; the legacy status is appended
        # instead of replacing it. See D30.
        log.info(
            "Clipboard adapter started (poll %.2fs) -- legacy RenPy route, "
            "not the default input since F8",
            settings.poll_interval,
        )

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
                return

            if len(current) < settings.min_text_length:
                self.raw_log.log_entry(current, "BLOCKED:too_short")
                return
            if self._is_garbage(current):
                self.raw_log.log_entry(current, "BLOCKED:garbage")
                log.debug("Skipping non-dialogue clipboard: %r", current[:60])
                return

            dialogue = self.parser.parse(current, source=self.name)
            if not dialogue.is_voiceable:
                self.raw_log.log_entry(current, "BLOCKED:not_voiceable")
                return
            self.raw_log.log_entry(current, "OK")
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
