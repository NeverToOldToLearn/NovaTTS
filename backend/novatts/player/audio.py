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
from typing import Any

import pygame

log = logging.getLogger(__name__)

_STREAM_RATE = 24000
"""Sample rate of the live pcm stream (tts-server emits 24 kHz mono s16le)."""


class StreamUnavailable(Exception):
    """Live streaming cannot start (no sounddevice lib or no output device)."""


class _LiveStream:
    """One streamed line: fed with s16le bytes, played as they arrive."""

    def __init__(self, *, prebuffer_samples: int, gain: float) -> None:
        self.prebuffer = prebuffer_samples
        self.gain = gain
        self.chunks: deque[bytes] = deque()
        self.buffered = 0  # samples waiting
        self.lock = threading.Lock()
        self.input_done = False
        self.aborted = False
        self.started = False
        self.drained = threading.Event()
        self.underruns = 0

    def _take_locked(self, frames: int) -> tuple[Any, int]:
        """Pop up to ``frames`` samples; returns (int16 array, count)."""
        import numpy as np

        if self.aborted:
            return None, 0
        need = frames
        parts: list[bytes] = []
        while need > 0 and self.chunks:
            head = self.chunks[0]
            have = len(head) // 2
            if have <= need:
                parts.append(self.chunks.popleft())
                self.buffered -= have
                need -= have
            else:
                parts.append(head[: need * 2])
                self.chunks[0] = head[need * 2 :]
                self.buffered -= need
                need = 0
        if not parts:
            return None, 0
        arr = np.frombuffer(b"".join(parts), dtype=np.int16)
        return arr, len(arr)


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
        self._stream: _LiveStream | None = None
        self._stream_lock = threading.Lock()
        self._output: Any = None  # persistent sounddevice OutputStream (never per-line)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._player_thread = threading.Thread(target=self._loop, name="audio-player", daemon=True)
        self._player_thread.start()
        self._start_keep_warm()

    def stop(self) -> None:
        self.abort_stream()
        self._stop_keep_warm()
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
        self.abort_stream()

    def clear(self) -> None:
        with self._condition:
            self._announce(self._halt_locked())
        self.abort_stream()

    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    # ------------------------------------------------------------------
    # Live streaming (pcm chunks straight from tts-server, no WAV file)
    #
    # One persistent output serves every line. Opening a device stream per
    # line renegotiates the link on each start -- an audible cold-start
    # burst on wireless headsets, on EVERY line -- while pygame simply holds
    # its own device open for the whole session. Sessions are therefore just
    # packet queues: the callback only ever pulls from the current one and
    # emits silence otherwise, which doubles as keep-warm (see
    # settings.keep_warm_enabled). Lock order is always _stream_lock ->
    # session.lock, never reversed.
    # ------------------------------------------------------------------

    def begin_stream(self, *, prebuffer_sec: float = 0.4, gain: float = 2.0) -> _LiveStream:
        """Open a live session. Raises StreamUnavailable without audio device.

        Ensuring the (persistent) output here instead of at first feed fails
        fast, so the caller can fall back to the file path before any GPU
        work starts. Any previous session is aborted first: one live line
        at a time.
        """
        session = _LiveStream(prebuffer_samples=int(_STREAM_RATE * prebuffer_sec), gain=gain)
        with self._stream_lock:
            self._abort_locked()
            try:
                self._ensure_output_locked()
            except StreamUnavailable:
                self._stream = None
                raise
            self._stream = session
        return session

    def _ensure_output_locked(self) -> None:
        """Open the persistent output. Caller must hold ``_stream_lock``."""
        if self._output is not None:
            return
        try:
            import sounddevice as sd
        except Exception as exc:
            raise StreamUnavailable(f"sounddevice unavailable: {exc}") from exc
        try:
            # Device-default latency: this stream never closes, so there is
            # no renegotiation to hide behind "low" -- stability first.
            out = sd.OutputStream(
                samplerate=_STREAM_RATE,
                channels=1,
                dtype="int16",
                callback=self._output_callback,
            )
            out.start()
        except Exception as exc:
            raise StreamUnavailable(f"no output device: {exc}") from exc
        self._output = out
        log.info("Stream output open (persistent)")

    def _output_callback(self, outdata: Any, frames: int, time_info: Any, status: Any) -> None:
        with self._stream_lock:
            session = self._stream
        if session is None:
            outdata.fill(0)
            return
        with session.lock:
            gated = not session.started or session.aborted
            terminal = session.aborted or session.input_done
        if gated:
            # Prebuffering (or cut): silence. A terminal gated session
            # releases quietly; drain logging is for audible lines.
            outdata.fill(0)
            if terminal:
                self._clear_if_current(session)
            return
        view, count = session._take_locked(frames)
        if view is None:
            outdata.fill(0)
            with session.lock:
                done = session.input_done
                if not done:
                    session.underruns += 1
            if done:
                self._clear_if_current(session, log_drain=True)
            return
        outdata[:count, 0] = view
        if count < frames:
            outdata[count:, 0] = 0
            with session.lock:
                done = session.input_done
                if not done:
                    session.underruns += 1
            if done:
                self._clear_if_current(session, log_drain=True)

    def _clear_if_current(self, session: _LiveStream, *, log_drain: bool = False) -> None:
        with self._stream_lock:
            if self._stream is not session:
                return
            self._stream = None
        if log_drain:
            log.debug("Stream drained (%d underruns)", session.underruns)
        session.drained.set()

    @staticmethod
    def _maybe_start(session: _LiveStream) -> None:
        """Mark audible once prebuffered. No device op: output runs already."""
        with session.lock:
            if (
                not session.started
                and not session.aborted
                and (session.buffered >= session.prebuffer or (session.input_done and session.buffered > 0))
            ):
                session.started = True

    def feed_stream(self, session: _LiveStream, pcm: bytes) -> bool:
        """Append s16le bytes; False when superseded/aborted (stop feeding)."""
        if not pcm:
            return not session.aborted
        from ..tts.pcm import apply_stream_gain

        ready = apply_stream_gain(pcm, session.gain)
        if len(ready) & 1:
            ready = ready[:-1]
        if not ready:
            return not session.aborted
        with self._stream_lock:
            if self._stream is not session:
                return False
        with session.lock:
            if session.aborted or session.input_done:
                return False
            session.chunks.append(ready)
            session.buffered += len(ready) // 2
        self._maybe_start(session)
        return True

    def finish_stream(self, session: _LiveStream) -> None:
        """No more input: play out the buffer, then release (non-blocking)."""
        with session.lock:
            session.input_done = True
            empty = session.buffered == 0 and not session.started
        if empty:
            session.drained.set()
            self._clear_if_current(session)
            return
        self._maybe_start(session)

    def abort_stream(self, session: _LiveStream | None = None) -> None:
        """Cut a live session immediately (idempotent). None = current."""
        with self._stream_lock:
            target = session if session is not None else self._stream
            if target is not None and self._stream is target:
                self._stream = None
        if target is None:
            return
        with target.lock:
            target.aborted = True
            target.chunks.clear()
            target.buffered = 0
        target.drained.set()

    def _abort_locked(self) -> None:
        """Abort the current session. Caller must hold ``_stream_lock``."""
        target, self._stream = self._stream, None
        if target is None:
            return
        with target.lock:
            target.aborted = True
            target.chunks.clear()
            target.buffered = 0
        target.drained.set()

    def is_streaming(self) -> bool:
        with self._stream_lock:
            return self._stream is not None and not self._stream.drained.is_set()

    # ------------------------------------------------------------------
    # Keep-warm: the persistent output doubles as the silence holder
    # ------------------------------------------------------------------

    def _start_keep_warm(self) -> None:
        """Open the persistent output at startup so the device never sleeps.

        Non-fatal by design: without sounddevice or without a device this
        logs once and playback proceeds exactly as before. Guarded by
        ``settings.keep_warm_enabled``; when off, the output opens lazily on
        the first streamed line instead.
        """
        try:
            from ..config import settings as _settings

            if not _settings.keep_warm_enabled:
                return
        except Exception:
            return
        with self._stream_lock:
            try:
                self._ensure_output_locked()
            except StreamUnavailable as exc:
                log.debug("Keep-warm off (%s)", exc)

    def _stop_keep_warm(self) -> None:
        with self._stream_lock:
            out, self._output = self._output, None
            live, self._stream = self._stream, None
        if live is not None:
            with live.lock:
                live.aborted = True
                live.chunks.clear()
                live.buffered = 0
            live.drained.set()
        if out is not None:
            with contextlib.suppress(Exception):
                out.stop()
            with contextlib.suppress(Exception):
                out.close()

    def keep_warm_active(self) -> bool:
        with self._stream_lock:
            return self._output is not None

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
