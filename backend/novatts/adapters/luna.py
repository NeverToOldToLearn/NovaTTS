"""LunaTranslator websocket adapter.

LunaTranslator runs a small HTTP/websocket server on its configured
listening port (default 2333) while the application is open. The endpoint
``/api/ws/text/origin`` streams every freshly captured line as a plain
UTF-8 text frame. Simply connecting is enough to enable Luna's websocket
outputer, so no extra Luna configuration is required beyond keeping the
server reachable (``networktcpenable``).

The server may not be running (Luna closed, another port, or the user still
on the clipboard route), so this adapter reconnects quietly with backoff and
never lets an error escape into the host process.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable

from ..blacklist import is_renpy_exception
from ..config import settings
from ..models import Dialogue
from ..parser.luna import LunaParser, has_hook_markup
from .base import DialogueCallback, FilteredCallback, InputAdapter

log = logging.getLogger(__name__)


class LunaAdapter(InputAdapter):
    """Client for LunaTranslator's ``/api/ws/text/origin`` stream."""

    def __init__(
        self,
        on_dialogue: DialogueCallback,
        on_filtered: FilteredCallback | None = None,
        url: str = "",
    ) -> None:
        super().__init__(on_dialogue, on_filtered)
        self.url = (url or settings.luna_ws_url).strip()
        self.parser = LunaParser(name_codes=settings.actor_names)
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False
        self._last_key: tuple[str | None, str] | None = None
        self._last_raw = ""
        self.client_count = 0

    @property
    def name(self) -> str:
        return "luna"

    @property
    def connected(self) -> bool:
        return self._connected

    def set_known_speakers(self, names: Iterable[str]) -> None:
        """Sync the parser's registry-backed name set (case-insensitive)."""
        self.parser.set_known_names(names)

    def set_name_codes(self, value: object) -> None:
        """Update the game's ``actor_names`` placeholder mapping."""
        self.parser.set_name_codes(value)

    def set_url(self, url: str) -> None:
        """Point the adapter at another endpoint (takes effect on next start)."""
        self.url = (url or settings.luna_ws_url).strip()

    def start(self) -> None:
        if self._running:
            return
        if not self.url:
            log.warning("Luna adapter has no websocket URL - not started")
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="luna-adapter", daemon=True)
        self._thread.start()
        log.info("Luna adapter started (%s)", self.url)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._connected = False
        self.client_count = 0
        log.info("Luna adapter stopped")

    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Connection loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        from websockets.sync.client import connect

        backoff = 1.0
        while self._running:
            try:
                with connect(self.url, open_timeout=5) as websocket:
                    self._connected = True
                    self.client_count = 1
                    backoff = 1.0
                    log.info("Luna websocket connected (%s)", self.url)
                    while self._running:
                        try:
                            message = websocket.recv(timeout=0.5)
                        except TimeoutError:
                            continue
                        self._handle_frame(message)
            except Exception as exc:
                self._connected = False
                self.client_count = 0
                if not self._running:
                    break
                log.debug("Luna websocket unavailable (%s): %s", self.url, exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 10.0)
            finally:
                self._connected = False
                self.client_count = 0

    # ------------------------------------------------------------------
    # Frame handling
    # ------------------------------------------------------------------

    def _handle_frame(self, message: str | bytes) -> None:
        raw = message if isinstance(message, str) else message.decode("utf-8", errors="ignore")
        raw = raw.strip()
        if not raw or raw == self._last_raw:
            return
        self._last_raw = raw
        self._handle_text(raw)

    def _handle_text(self, raw: str) -> None:
        if is_renpy_exception(raw):
            self.notify_filtered("renpy_exception", raw)
            return
        try:
            dialogue = self.parser.parse(raw, source=self.name)
        except Exception:
            log.exception("Luna parse error (swallowed)")
            self.notify_filtered("parse_error", raw)
            return

        if not dialogue.is_voiceable:
            reason = "garbage" if has_hook_markup(raw) else "not_voiceable"
            self.notify_filtered(reason, raw)
            return
        if len(dialogue.text) < settings.min_text_length:
            self.notify_filtered("too_short", raw)
            return

        key = (dialogue.speaker, dialogue.text.casefold())
        if key == self._last_key:
            return
        self._last_key = key

        log.debug("Luna -> %s: %s", dialogue.speaker, dialogue.text[:60])
        try:
            self.on_dialogue(dialogue)
        except Exception:
            log.exception("on_dialogue callback failed (swallowed)")

    def _handle_hook_text(self, raw: str) -> Dialogue | None:
        """Normalize one hook payload; exposed for tests and diagnostics."""
        dialogue = self.parser.parse(raw, source=self.name)
        return dialogue if dialogue.is_voiceable else None
