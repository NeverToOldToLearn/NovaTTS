"""Tests for the file-watch route (F5).

This is the last-resort input path, and a fallback that fails silently is
worse than no fallback, so the effort here goes to the two places it can
go quiet: deciding which part of a file is new, and feeding that through
the same processor the websocket route uses.

The tick is called directly for determinism; one test drives the real
poll thread to prove the loop itself is wired up.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from novatts.adapters.file_monitor import FileMonitorAdapter, new_file_text
from novatts.config import settings
from novatts.models import Dialogue


class Recorder:
    """Records every dialogue the adapter hands to the app."""

    def __init__(self) -> None:
        self.seen: list[Dialogue] = []

    def __call__(self, dialogue: Dialogue) -> None:
        self.seen.append(dialogue)

    @property
    def spoken(self) -> list[tuple[str | None, str]]:
        return [(d.speaker, d.text) for d in self.seen]


def _adapter(path: Path) -> tuple[FileMonitorAdapter, Recorder]:
    rec = Recorder()
    return FileMonitorAdapter(rec, path=path), rec


# --- which part of the file is new ------------------------------------------


class TestNewFileText:
    def test_first_read_is_the_whole_file(self) -> None:
        assert new_file_text("", "Rick Hello") == "Rick Hello"

    def test_unchanged_content_is_nothing(self) -> None:
        assert new_file_text("Rick Hello", "Rick Hello") == ""

    def test_trailing_newline_is_not_a_change(self) -> None:
        assert new_file_text("Rick Hello", "Rick Hello\n") == ""

    def test_an_appended_line_is_only_the_suffix(self) -> None:
        assert new_file_text("Rick Hello", "Rick Hello\nAnne Bye") == "Anne Bye"

    def test_two_appended_lines_are_both_new(self) -> None:
        assert new_file_text("Line one", "Line one\nLine two\nLine three") == (
            "Line two\nLine three"
        )

    def test_replaced_content_is_the_whole_file(self) -> None:
        assert new_file_text("Rick Hello", "Anne Bye") == "Anne Bye"

    def test_truncate_then_write_is_a_replacement(self) -> None:
        assert new_file_text("Rick Hello there", "Anne Bye") == "Anne Bye"

    def test_an_emptied_file_is_nothing(self) -> None:
        assert new_file_text("Rick Hello", "") == ""

    def test_growth_without_a_line_boundary_is_a_replacement(self) -> None:
        """Prefix matching alone would eat the name.

        ``"Rick"`` followed by ``"Rick Hello"`` is a writer replacing its
        content, not ``"Hello"`` appended to a bare name, so the whole line
        has to survive.
        """
        assert new_file_text("Rick", "Rick Hello") == "Rick Hello"

    def test_growth_at_a_carriage_return_is_an_append(self) -> None:
        assert new_file_text("Rick Hello", "Rick Hello\r\nAnne Bye") == "Anne Bye"


# --- what one tick delivers -------------------------------------------------


class TestDelivery:
    def test_the_first_line_is_delivered_with_source_file(self, tmp_path: Path) -> None:
        path = tmp_path / "out.txt"
        path.write_text("Rick Hello there", encoding="utf-8")
        adapter, rec = _adapter(path)

        adapter._tick()

        assert rec.spoken == [("Rick", "Hello there")]
        assert rec.seen[0].source == "file"
        assert rec.seen[0].raw == "Rick Hello there"

    def test_an_unchanged_file_delivers_nothing_again(self, tmp_path: Path) -> None:
        path = tmp_path / "out.txt"
        path.write_text("Rick Hello there", encoding="utf-8")
        adapter, rec = _adapter(path)

        adapter._tick()
        adapter._tick()

        assert len(rec.seen) == 1

    def test_an_appended_line_is_delivered_on_its_own(self, tmp_path: Path) -> None:
        path = tmp_path / "out.txt"
        path.write_text("Rick Hello there", encoding="utf-8")
        adapter, rec = _adapter(path)
        adapter._tick()

        path.write_text("Rick Hello there\nAnne Bye now", encoding="utf-8")
        adapter._tick()

        assert rec.spoken == [("Rick", "Hello there"), ("Anne", "Bye now")]

    def test_two_lines_arriving_at_once_are_two_dialogues(self, tmp_path: Path) -> None:
        """Fed as one blob, the parser reads the second line as the first
        line's text -- "Rick Hello there" would swallow "Anne Bye now"."""
        path = tmp_path / "out.txt"
        adapter, rec = _adapter(path)

        path.write_text("Rick Hello there\nAnne Bye now", encoding="utf-8")
        adapter._tick()

        assert rec.spoken == [("Rick", "Hello there"), ("Anne", "Bye now")]

    def test_a_replacement_is_delivered_whole(self, tmp_path: Path) -> None:
        path = tmp_path / "out.txt"
        path.write_text("Rick Hello there", encoding="utf-8")
        adapter, rec = _adapter(path)
        adapter._tick()

        path.write_text("Anne Bye now", encoding="utf-8")
        adapter._tick()

        assert rec.spoken == [("Rick", "Hello there"), ("Anne", "Bye now")]

    def test_an_emptied_file_then_a_new_line(self, tmp_path: Path) -> None:
        path = tmp_path / "out.txt"
        path.write_text("Rick Hello there", encoding="utf-8")
        adapter, rec = _adapter(path)
        adapter._tick()

        path.write_text("", encoding="utf-8")
        adapter._tick()
        path.write_text("Anne Bye now", encoding="utf-8")
        adapter._tick()

        assert rec.spoken == [("Rick", "Hello there"), ("Anne", "Bye now")]

    def test_a_missing_file_is_not_an_error(self, tmp_path: Path) -> None:
        adapter, rec = _adapter(tmp_path / "nope.txt")

        adapter._tick()  # must not raise

        assert rec.seen == []
        assert adapter.last_raw == ""

    def test_a_file_appearing_later_is_picked_up(self, tmp_path: Path) -> None:
        path = tmp_path / "out.txt"
        adapter, rec = _adapter(path)
        adapter._tick()

        path.write_text("Rick Hello there", encoding="utf-8")
        adapter._tick()

        assert rec.spoken == [("Rick", "Hello there")]


# --- the name set -----------------------------------------------------------


class TestKnownSpeakers:
    def test_a_registered_name_stops_being_a_guess(self, tmp_path: Path) -> None:
        """The app primes every adapter, so this route must honour the
        registry just like the clipboard and the hook do."""
        path = tmp_path / "out.txt"
        adapter, rec = _adapter(path)
        adapter.set_known_speakers(["Rick"])

        path.write_text("Rick Hello there", encoding="utf-8")
        adapter._tick()

        assert rec.seen[0].speaker_is_guess is False

    def test_an_unregistered_name_is_a_guess(self, tmp_path: Path) -> None:
        path = tmp_path / "out.txt"
        adapter, rec = _adapter(path)

        path.write_text("Rick Hello there", encoding="utf-8")
        adapter._tick()

        assert rec.seen[0].speaker_is_guess is True


# --- the documented limitation ----------------------------------------------


class TestTheNameOnItsOwnLine:
    """Pinned, not hidden.

    The route delivers one line at a time, so a writer that puts a name and
    its text on separate lines gives the name no body to attach to. This is
    exactly the shape ``hook_dual_hook`` buffers a bare name for, so the
    two tests together say what happens and how to get the other outcome.
    """

    def test_the_name_is_lost_without_dual_hook(self, tmp_path: Path) -> None:
        path = tmp_path / "out.txt"
        adapter, rec = _adapter(path)

        path.write_text("Rick\nAnswer the door.", encoding="utf-8")
        adapter._tick()

        # "Rick" is dropped as a bare name, and the body line is then read
        # as a space-form line -- so a plausible word becomes the speaker.
        assert rec.spoken == [("Answer", "the door.")]

    def test_dual_hook_rejoins_the_two_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "hook_dual_hook", True)
        path = tmp_path / "out.txt"
        adapter, rec = _adapter(path)

        path.write_text("Rick\nAnswer the door.", encoding="utf-8")
        adapter._tick()

        assert rec.spoken == [("Rick", "Answer the door.")]


# --- the poll thread --------------------------------------------------------


def test_the_poll_thread_delivers_and_stops(tmp_path: Path) -> None:
    """The tick is called directly everywhere else, so one test drives the
    real thread: a loop that never starts looks identical to a file that
    never changes."""
    path = tmp_path / "out.txt"
    path.write_text("Rick Hello there", encoding="utf-8")
    rec = Recorder()
    adapter = FileMonitorAdapter(rec, path=path, poll_interval=0.01)

    adapter.start()
    try:
        assert adapter.is_running() is True
        deadline = time.monotonic() + 5.0
        while not rec.seen and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        adapter.stop()

    assert rec.spoken == [("Rick", "Hello there")]
    assert adapter.is_running() is False
