"""Tertiary input route: tail a Textractor output file.

Neither the clipboard nor the websocket needs a file. This exists for the
game whose text hook cannot be attached through LunaTranslator at all but
which can still be made to write each line to a file (Textractor's own
file output, or a small per-game logger). Off unless
``NOVATTS_FILE_WATCH=1``: no speculative transport runs by default, the
same rule that kept a raw-TCP fallback out (D4).

The route is deliberately thin. It does **not** get its own parser: a line
from a file has the same shape as a line from the hook, so it goes into
the same :class:`~novatts.adapters.luna.HookTextProcessor` the websocket
route uses and inherits every decision from there -- the bare-name guard,
the dual-hook buffer, the multi-speaker split, the UI-chrome rejections.
The only new decision is "which part of the file is new", and that lives
in the pure :func:`new_file_text` so it is testable without a filesystem.

A file, unlike a socket, has no framing: the unit is "the content
changed", and :func:`new_file_text` works out which lines are new. Two
writers are common in practice and both are handled -- a scratch file
rewritten with the current line, and a log that only grows. Each new line
is then delivered on its own, so a growing log parses exactly like a
socket that sent the same lines.

The one shape this route does not recover by itself is a writer that puts
a name and its text on *separate* lines (``Rick`` then ``Answer the
door.``). Those are two deliveries, so the name has no body to attach to
and is dropped. That is the same case ``hook_dual_hook`` exists for -- it
buffers a bare name and merges it into the next line -- and a test pins
both halves rather than leaving it to be discovered.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from pathlib import Path

from ..config import settings
from .base import DialogueCallback, InputAdapter
from .luna import HookTextProcessor

log = logging.getLogger(__name__)

#: Seconds between file reads. The file route is a fallback, so a third of
#: a second of latency is irrelevant next to not being able to run at all.
DEFAULT_POLL_INTERVAL = 0.3


def new_file_text(previous: str, current: str) -> str:
    """The new part of ``current`` relative to ``previous``, as text.

    Both sides are compared stripped, so a writer that adds a trailing
    newline has not changed anything. An append is recognised only when
    the extra text begins at a line boundary, because that is the one form
    that can be told apart from a writer replacing the content with
    something that happens to start the same way -- ``"Rick"`` followed by
    ``"Rick Hello"`` is a replacement, not ``"Hello"`` appended to a name.

    Returns ``""`` when nothing is new. The caller splits the result into
    lines; finding the split point is this function's whole job.
    """
    previous = previous.strip()
    current = current.strip()
    if not previous or not current.startswith(previous):
        # First read, or the content was replaced outright (which is also
        # what truncate-then-write looks like, so it is the normal case and
        # not an error).
        return current
    suffix = current[len(previous) :]
    if not suffix:
        return ""
    if suffix[:1] in ("\n", "\r"):
        return suffix.strip()
    return current


class FileMonitorAdapter(InputAdapter):
    """Poll a file and feed whatever changed through the hook processor."""

    def __init__(
        self,
        on_dialogue: DialogueCallback,
        *,
        path: str | Path | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ) -> None:
        super().__init__(on_dialogue)
        self.path = Path(path if path is not None else settings.file_watch_path)
        self.poll_interval = poll_interval

        # The same processor the hook route uses, with a different source
        # label. Nothing else differs, which is the point: the two routes
        # cannot drift into disagreeing about what a line means.
        self._processor = HookTextProcessor(
            min_text_length=settings.min_text_length,
            space_form=settings.hook_space_form,
            dual_hook=settings.hook_dual_hook,
            source="file",
        )
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_text = ""
        self._missing_warned = False
        #: The last text this route delivered, before parsing. Same reason
        #: as :attr:`LunaAdapter.last_raw`: "the file was never found" and
        #: "found and misparsed" look identical from the outside.
        self.last_raw = ""

    # -- InputAdapter ----------------------------------------------------

    @property
    def name(self) -> str:
        return "file"

    def is_running(self) -> bool:
        return self._running

    def set_known_speakers(self, names: Iterable[str]) -> None:
        """Sync the processor's registry-backed name set (case-insensitive)."""
        self._processor.set_known_names(names)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="file-adapter", daemon=True)
        self._thread.start()
        log.info(
            "File adapter started (watching %s every %.2fs)", self.path, self.poll_interval
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("File adapter stopped")

    # -- Internals -------------------------------------------------------

    def _loop(self) -> None:
        while self._running:
            try:
                self._tick()
            except Exception:
                log.exception("File poll error (swallowed)")
            time.sleep(self.poll_interval)

    def _tick(self) -> None:
        """One poll: read the file and deliver whatever is new.

        The content is read on every tick instead of being gated behind
        ``st_mtime``, which is what the donor did. On a filesystem with
        coarse timestamps a rewrite inside the same tick then compares
        equal to the previous one and is missed entirely -- the worst kind
        of fallback failure, because the route looks alive and silent. The
        file is small, so reading it is cheaper than that class of bug.
        """
        try:
            current = self.path.read_text(encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            if not self._missing_warned:
                self._missing_warned = True
                log.warning("File adapter: %s does not exist yet", self.path)
            return
        except OSError as exc:
            log.warning("File adapter: cannot read %s: %s", self.path, exc)
            return
        self._missing_warned = False

        text = new_file_text(self._last_text, current)
        # Record the new content even when nothing will be spoken, so an
        # emptied file is a change to nothing and not a change replayed
        # against the next write.
        self._last_text = current
        if not text:
            return
        self.last_raw = text
        log.debug("File raw: %r", text[:90])
        # One line, one delivery -- the same unit a socket frame is. Feeding
        # the whole change at once made the parser read the second line as
        # the first line's text ("Rick Hello\nAnne Bye" became Rick saying
        # "Hello Anne Bye"), which is worse than misreading a speaker.
        for line in text.splitlines():
            if not line.strip():
                continue
            for dialogue in self._processor.push(line):
                try:
                    self.on_dialogue(dialogue)
                except Exception:
                    log.exception("on_dialogue callback failed (swallowed)")
