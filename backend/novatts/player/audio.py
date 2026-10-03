"""Queue-based audio player built on pygame.mixer.

Plays WAV files one at a time in FIFO order; overlapping playback is
impossible by construction (single mixer channel + locked deque).

Two details matter for how a line *ends*, because a line that sounds
unfinished is the loudest bug there is:

- A clip is loaded and started while the lock is held. A stop arriving in
  between the pop and the play used to be swallowed, and the line it was
  meant to cancel started playing anyway.
- Interrupting reports the clip it cut off, so its file is not stranded.
  With the audio cache off every line is a disposable file that has to be
  cleaned up exactly once, whether it played out or was cut short.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import pygame

log = logging.getLogger(__name__)


class AudioPlayer:
    def __init__(self) -> None:
        pygame.mixer.init()
        pygame.init()
        self._queue: deque[Path] = deque()
        self._lock = threading.Lock()
        self._current: Path | None = None
        self._condition = threading.Condition(self._lock)
        self._player_thread: threading.Thread | None = None
        self._running = False
        self.on_finished: Callable[[Path], None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._player_thread = threading.Thread(target=self._loop, name="audio-player", daemon=True)
        self._player_thread.start()

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()
        if self._player_thread:
            self._player_thread.join(timeout=3.0)
            self._player_thread = None
        pygame.mixer.quit()
        log.info("Audio player stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, wav_path: str | Path) -> None:
        path = Path(wav_path)
        if not path.exists():
            log.warning("enqueue: missing file %s", path)
            return
        with self._condition:
            self._queue.append(path)
            self._condition.notify_all()
        log.debug("Audio queued: %s (queue=%d)", path.name, len(self._queue))

    def enqueue_interrupt(self, wav_path: str | Path) -> None:
        path = Path(wav_path)
        if not path.exists():
            log.warning("enqueue_interrupt: missing file %s", path)
            return
        with self._condition:
            self._announce(self._halt_locked())
            self._queue.append(path)
            self._condition.notify_all()
        log.debug("Audio interrupt queued: %s", path.name)

    def stop_current(self) -> None:
        """Cut playback the moment a new line arrives.

        Deliberately called on arrival rather than after synthesis: an emotion
        sound from the previous line must not still be sitting in the backlog
        when the new line starts, or it is heard as trailing off the end.
        """
        with self._condition:
            self._announce(self._halt_locked())

    def clear(self) -> None:
        with self._condition:
            self._announce(self._halt_locked())

    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def is_idle(self) -> bool:
        with self._lock:
            return self._current is None and not self._queue

    def current(self) -> Path | None:
        with self._lock:
            return self._current

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _halt_locked(self) -> Path | None:
        """Stop the mixer, drop the backlog, forget the current clip.

        Returns the clip that was cut off (or None) so the caller can release
        its file. Caller must hold ``_condition``.
        """
        with contextlib.suppress(Exception):
            pygame.mixer.music.stop()
        self._queue.clear()
        interrupted, self._current = self._current, None
        return interrupted

    def _announce(self, path: Path | None) -> None:
        if path is None or self.on_finished is None:
            return
        try:
            self.on_finished(path)
        except Exception:
            log.exception("on_finished callback failed (swallowed)")

    def _loop(self) -> None:
        while self._running:
            with self._condition:
                while self._running and not self._queue:
                    self._condition.wait(timeout=0.5)
                if not self._running:
                    return
                current = self._queue.popleft()
                self._current = current
                started = self._start(current)

            if started:
                self._wait_out(current)

            # An interrupt nulls _current and announces the clip itself, so
            # this stays quiet when the line was cut off rather than played.
            with self._condition:
                finished, self._current = self._current, None
            self._announce(finished)

    def _start(self, path: Path) -> bool:
        """Load and start a clip. Caller must hold ``_condition``.

        Starting under the lock is the point: a stop_current() can no longer
        slip between the pop and the play, which is how a line that was
        already cancelled went on to be heard anyway.
        """
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            return True
        except Exception as exc:
            log.error("Playback failed for %s: %s", path.name, exc)
            return False

    def _wait_out(self, path: Path) -> None:
        try:
            while pygame.mixer.music.get_busy() and self._running:
                time.sleep(0.05)
        except Exception as exc:
            log.error("Playback failed for %s: %s", path.name, exc)
