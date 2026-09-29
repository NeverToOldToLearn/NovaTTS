"""End-to-end proof for the route that actually delivers text today.

The clipboard route is the only input route that needs no second hook engine
and no extension, so it is the one that has to keep working. F14 measured the
real payload -- a bare name on its own line, sometimes wrapped in ``<b>`` --
coming out of a live game, and the defect was not in the parser alone: the
whole route delivered "Tatsuo" as narration to be read out loud.

These tests drive ``ClipboardAdapter._tick()`` directly with a double for
``pyperclip.paste``. Calling the private tick on purpose: the thread loop
would make every test sleep, and the tick is the whole route minus the
``time.sleep``. Nothing here touches the real clipboard or the real
``data/logs/clipboard_raw.log`` -- the fixture redirects both.

Payload strings are verbatim copies from that log.
"""

from __future__ import annotations

import pytest

from novatts.adapters import legacy_clipboard
from novatts.adapters.legacy_clipboard import ClipboardAdapter
from novatts.models import Dialogue

REAL_HTML = (
    "<b>Tatsuo</b>\n"
    "The girl with the bag of groceries says something about how healthy she eats."
)
REAL_PLAIN = "Tatsuo\nEach pawn has a story half concealed."


class _FakeClipboard:
    """Stands in for ``pyperclip``: the route only ever calls ``paste``."""

    def __init__(self) -> None:
        self.value = ""

    def paste(self) -> str:
        return self.value


class _Env:
    def __init__(self) -> None:
        self.box = _FakeClipboard()
        self.seen: list[Dialogue] = []
        self.adapter = ClipboardAdapter(self.seen.append)
        self.adapter.set_known_speakers(["Tatsuo"])


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> _Env:
    e = _Env()
    # The real log is the evidence for F14; a test run must not append to it.
    monkeypatch.setattr(legacy_clipboard.settings, "log_raw_clipboard", False)
    monkeypatch.setattr(
        legacy_clipboard.settings, "clipboard_raw_log", tmp_path / "clipboard_raw.log"
    )
    monkeypatch.setattr(legacy_clipboard.settings, "min_text_length", 4)
    monkeypatch.setattr(legacy_clipboard.pyperclip, "paste", e.box.paste)
    return e


def test_html_payload_arrives_as_a_named_turn(env: _Env) -> None:
    env.box.value = REAL_HTML
    env.adapter._tick()
    assert len(env.seen) == 1
    assert env.seen[0].speaker == "Tatsuo"
    assert env.seen[0].text == (
        "The girl with the bag of groceries says something about how healthy she eats."
    )


def test_plain_payload_arrives_as_a_named_turn(env: _Env) -> None:
    env.box.value = REAL_PLAIN
    env.adapter._tick()
    assert [d.speaker for d in env.seen] == ["Tatsuo"]
    assert env.seen[0].text == "Each pawn has a story half concealed."


def test_narration_without_a_name_stays_narration(env: _Env) -> None:
    env.box.value = "What will be your next move?"
    env.adapter._tick()
    assert len(env.seen) == 1
    assert env.seen[0].speaker is None
    assert env.seen[0].text == "What will be your next move?"


def test_a_parsed_name_is_not_registered_automatically(env: _Env) -> None:
    """The parser proposes a speaker; it does not write to the registry.

    The registry belongs to the user. Auto-registering a proposed name would
    give every one-word line its own voice. Wiring proposals into the
    registry is main.py's job and is deliberately not done in the adapter.

    The colon form is used on purpose: it reaches the same registry without
    going through the bare-name branch, so this stays a pure registry test.
    """
    env.box.value = "Anna: Move it!"
    env.adapter._tick()
    assert env.seen[0].speaker == "Anna"
    assert env.adapter.parser._known == {"tatsuo": "Tatsuo"}


def test_a_bare_name_is_not_registered_automatically(env: _Env) -> None:
    """Same guarantee for the F14 form, which is the one that gets used."""
    env.box.value = "Anna\nMove it!"
    env.adapter._tick()
    assert env.seen[0].speaker == "Anna"
    assert env.adapter.parser._known == {"tatsuo": "Tatsuo"}


def test_identical_clipboard_is_not_delivered_twice(env: _Env) -> None:
    env.box.value = REAL_PLAIN
    env.adapter._tick()
    env.adapter._tick()
    assert len(env.seen) == 1


def test_rich_text_noise_is_still_blocked(env: _Env) -> None:
    # The garbage filter runs before the parser, so the new markup handling
    # cannot have opened the door for a stack trace.
    env.box.value = "Traceback (most recent call last):\n  File \"game/script.rpy\""
    env.adapter._tick()
    assert env.seen == []
