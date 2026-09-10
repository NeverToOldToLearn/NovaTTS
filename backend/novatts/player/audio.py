"""Queue-based audio player built on pygame.mixer.

Plays WAV files one at a time in FIFO order; overlapping playback is
impossible by construction (single mixer channel + locked deque).
"""

from __future__ import annotations

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
            self._queue.clear()
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self._queue.append(path)
            self._condition.notify_all()
        log.debug("Audio interrupt queued: %s", path.name)

    def stop_current(self) -> None:
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        with self._condition:
            self._queue.clear()

    def clear(self) -> None:
        with self._condition:
            self._queue.clear()
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

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

    def _loop(self) -> None:
        while self._running:
            with self._condition:
                while self._running and not self._queue:
                    self._condition.wait(timeout=0.5)
                if not self._running:
                    return
                self._current = self._queue.popleft()

            self._play(self._current)

            with self._lock:
                finished = self._current
                self._current = None
            if finished is not None and self.on_finished is not None:
                try:
                    self.on_finished(finished)
                except Exception:
                    log.exception("on_finished callback failed (swallowed)")

    def _play(self, path: Path) -> None:
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and self._running:
                time.sleep(0.05)
        except Exception as exc:
            log.error("Playback failed for %s: %s", path.name, exc)
            time.sleep(0.05)
