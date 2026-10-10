"""Tests for the live-stream player wiring with a stubbed audio device.

sounddevice is replaced in ``sys.modules`` while each test runs, so no real
output device is touched: one persistent fake output serves every session and
the test drives its callback manually, like the PortAudio thread would.
"""

import array
import sys
import threading
import types
from contextlib import contextmanager

import numpy as np

from novatts.player.audio import AudioPlayer


class FakeOutput:
    """Persistent fake output: records the callback, plays nothing."""

    def __init__(self, *, samplerate=None, channels=None, dtype=None, callback, **kwargs):
        assert samplerate == 24000
        assert channels == 1
        assert dtype == "int16"
        self.callback = callback
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeSD(types.ModuleType):
    OutputStream = FakeOutput


@contextmanager
def stubbed_device():
    old = sys.modules.get("sounddevice")
    sys.modules["sounddevice"] = FakeSD("sounddevice")
    try:
        yield
    finally:
        if old is not None:
            sys.modules["sounddevice"] = old
        else:
            del sys.modules["sounddevice"]


def _bare_player() -> AudioPlayer:
    # Bypass __init__ (which inits the pygame mixer): the stream path only
    # touches _stream / _stream_lock / _output.
    player = AudioPlayer.__new__(AudioPlayer)
    player._stream = None
    player._stream_lock = threading.Lock()
    player._output = None
    return player


def _s16(samples: list[int]) -> bytes:
    return array.array("h", samples).tobytes()


def _drive(player: AudioPlayer, frames: int = 512) -> np.ndarray:
    out = np.zeros((frames, 1), dtype=np.int16)
    player._output_callback(out, frames, None, None)
    return out


def test_output_opened_once_for_many_lines():
    with stubbed_device():
        player = _bare_player()
        first = player.begin_stream(prebuffer_sec=0.1, gain=1.0)
        out1 = player._output
        assert isinstance(out1, FakeOutput)
        assert out1.started
        second = player.begin_stream(prebuffer_sec=0.1, gain=1.0)
        # Same device handle, previous session retired: no renegotiation.
        assert player._output is out1
        assert not out1.closed
        assert first.aborted
        assert first.drained.is_set()
        assert player._stream is second


def test_stream_starts_after_prebuffer_and_drains():
    with stubbed_device():
        player = _bare_player()
        session = player.begin_stream(prebuffer_sec=0.1, gain=1.0)  # 2400 samples

        assert player.feed_stream(session, _s16([1000] * 1000))
        out = _drive(player)
        assert out[:, 0].tolist() == [0] * 512  # still prebuffering: silence

        assert player.feed_stream(session, _s16([2000] * 2000))
        out = _drive(player)
        assert out[:, 0].tolist() == [1000] * 512
        assert session.buffered == 3000 - 512

        player.finish_stream(session)
        for _ in range(20):
            _drive(player)
            if session.drained.is_set():
                break
        assert session.drained.is_set()
        assert player._stream is None
        # Output survives the line: the next line needs no device reopen.
        assert player._output is not None
        assert not player._output.closed


def test_stream_abort_cuts_and_releases_session_not_device():
    with stubbed_device():
        player = _bare_player()
        session = player.begin_stream(prebuffer_sec=10.0, gain=1.0)
        assert player.feed_stream(session, _s16([500] * 100))
        player.abort_stream(session)
        assert session.aborted
        assert session.drained.is_set()
        assert player._stream is None
        assert player._output is not None  # device stays open
        assert not player.feed_stream(session, _s16([500] * 10))


def test_idle_callback_is_silence():
    with stubbed_device():
        player = _bare_player()
        player.begin_stream(prebuffer_sec=0.1, gain=1.0)
        player.abort_stream()
        out = _drive(player)
        assert out[:, 0].tolist() == [0] * 512


def test_keep_warm_opens_output_and_stops():
    with stubbed_device():
        player = _bare_player()
        player._start_keep_warm()
        assert player.keep_warm_active()
        assert isinstance(player._output, FakeOutput)
        player._stop_keep_warm()
        assert not player.keep_warm_active()
        assert player._output is None
