"""Auto-forward fires for lines that produce no audio.

Auto-forward is driven by playback finishing: the last file of a line,
or a drained stream, is the signal that Ren'Py may take the next line.
A line that strips to nothing -- a stage direction in asterisks --
plays nothing, so that callback never runs and the game stalls waiting
for a click. The worker has to advance the game on its own -- after a
couple of seconds, so the pause the line was written for still lands.
"""

from __future__ import annotations

import threading

from novatts.auto_forward import AutoForward
from novatts.emotions import EmotionSounds
from novatts.main import NovaApp


def _plan(text: str) -> list[tuple[str, str]]:
    emotions = EmotionSounds()
    cleaned, positions = emotions.extract(text)
    return emotions.plan(cleaned, positions)


def test_starred_stage_direction_is_inert() -> None:
    """The lines the user reports: nothing left to speak, nothing to play."""
    assert _plan("*laughs*") == []
    assert _plan("*she looks away*") == []
    assert _plan("*blushes* ...") == []


class _Worker:
    """The two NovaApp methods the silent-line path needs, borrowed whole."""

    _is_stale = NovaApp._is_stale
    _notify_silent_line = NovaApp._notify_silent_line

    def __init__(self, seq: int, enabled: bool, *, delay: float = 0.5, silent_delay: float = 2.5) -> None:
        self._pending_seq = seq
        self._pending_lock = threading.Lock()
        self.auto_forward = AutoForward(delay=delay, silent_delay=silent_delay)
        self.auto_forward.enabled = enabled


def test_silent_line_advances_the_game() -> None:
    worker = _Worker(seq=7, enabled=True)
    worker._notify_silent_line(7)
    timer = worker.auto_forward._timer
    assert timer is not None
    timer.cancel()
    worker.auto_forward._timer = None


def test_silent_line_gets_its_own_pause() -> None:
    """Nothing is spoken, so the written pause is all the line gets."""
    worker = _Worker(seq=7, enabled=True)
    waits: list[float] = []
    worker.auto_forward._schedule = waits.append  # type: ignore[assignment]
    worker._notify_silent_line(7)
    assert waits == [2.5]


def test_silent_line_never_shortens_the_normal_delay() -> None:
    worker = _Worker(seq=7, enabled=True, delay=5.0)
    waits: list[float] = []
    worker.auto_forward._schedule = waits.append  # type: ignore[assignment]
    worker._notify_silent_line(7)
    assert waits == [5.0]


def test_silent_line_is_ignored_when_auto_forward_is_off() -> None:
    worker = _Worker(seq=3, enabled=False)
    worker._notify_silent_line(3)
    assert worker.auto_forward._timer is None


def test_superseded_line_does_not_fire() -> None:
    """A newer clipboard line owns the keystroke, not a stale one."""
    worker = _Worker(seq=3, enabled=True)
    worker._pending_seq = 4
    worker._notify_silent_line(3)
    assert worker.auto_forward._timer is None


def test_a_real_line_still_drives_playback() -> None:
    """The fix must not swallow lines that do have audio."""
    assert _plan("Hello *sighs* world") == [("text", "Hello"), ("sound", "sigh"), ("text", "world")]
