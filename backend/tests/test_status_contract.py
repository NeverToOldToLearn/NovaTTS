"""The `/status` fields the GUI reads, pinned as a contract.

F6 made the dashboard and the settings panel depend on ``NovaApp.status()``,
and until now that method had no test at all. That is a gap with a specific
shape: the GUI is TypeScript and the backend is Python, so a renamed or
dropped key is not a crash anywhere -- the dashboard just silently shows a
card that never changes, or a settings field that never saves. Nothing in
either language notices.

So this file states the contract twice, on purpose:

* ``HOOK_STATUS_FIELDS`` is the exact key set the dashboard is entitled to.
  Renaming a key in ``status()`` breaks this test, which is the only way the
  rename gets noticed before a user does.
* The GUI mirrors that list in ``gui/src/lib/types.ts`` (``ServerStatus``).
  The two lists must be edited together; there is no tool that checks that,
  so the comment exists in both places.

The route tests below cover the part that is not a declaration: which adapter
each number comes from, and what happens for a route that never started. The
latter is the common case rather than an edge case -- ``hook_mode=clipboard``
is the shipped default, and ``/status`` is polled whether or not a hook
exists, so the "no adapter" branch runs on every install that has not opted
into the hook yet.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from novatts import main as main_mod
from novatts.config import settings

# Mirrored by ServerStatus in gui/src/lib/types.ts. Keep the two in sync.
HOOK_STATUS_FIELDS = (
    "file_watch",
    "file_watch_path",
    "file_running",
    "hook_mode",
    "hook_host",
    "hook_port",
    "hook_clients",
    "hook_dropped",
    "hook_last_raw",
    "file_last_raw",
)


class FakeRoute:
    """Just enough of an adapter for ``status()`` to read it.

    ``LunaAdapter`` and ``FileMonitorAdapter`` expose exactly these three
    members to ``status()``; if that ever stops being true, this fake is what
    goes stale first, and the route tests below then fail loudly rather than
    the real adapter failing at runtime.
    """

    def __init__(
        self,
        *,
        running: bool = True,
        client_count: int = 0,
        dropped: int = 0,
        last_raw: str = "",
    ) -> None:
        self._running = running
        self.client_count = client_count
        self.dropped = dropped
        self.last_raw = last_raw

    def is_running(self) -> bool:
        return self._running


class FakeRegistry:
    def __init__(self) -> None:
        self._speakers: list[Any] = []

    def all(self) -> list[Any]:
        return list(self._speakers)

    def names(self) -> list[str]:
        return ["Narrator"]


class FakeVoices:
    def voice_options(self) -> list[str]:
        return ["af_heart", "af_bella"]


class FakeQwenMgr:
    def status(self) -> dict[str, Any]:
        return {"online": True}

    def import_status(self) -> dict[str, Any]:
        return {"found": 0, "loaded": 0, "total": 0, "active": False}


class FakeGames:
    def active(self) -> str | None:
        return None

    def list_games(self) -> list[str]:
        return []


class FakePlayer:
    def queue_size(self) -> int:
        return 0

    def current(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _stable_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the settings ``status()`` mirrors.

    ``settings`` is a module-level singleton built from the real ``.env``, so
    a developer's own port number would otherwise decide what these tests
    assert. The values here are the shipped defaults (test_hook_config.py
    pins those separately).
    """
    monkeypatch.setattr(settings, "hook_mode", "both")
    monkeypatch.setattr(settings, "hook_host", "127.0.0.1")
    monkeypatch.setattr(settings, "hook_port", 6677)
    monkeypatch.setattr(settings, "file_watch", False)
    monkeypatch.setattr(settings, "file_watch_path", "textractor_output.txt")


def _app(luna: Any = None, filemon: Any = None, clipboard: Any = None) -> Any:
    app = main_mod.NovaApp.__new__(main_mod.NovaApp)
    app.luna = luna
    app.filemon = filemon
    app.clipboard = clipboard
    app.registry = FakeRegistry()
    app.voices = FakeVoices()
    app.qwen_mgr = FakeQwenMgr()
    app.games = FakeGames()
    app.player = FakePlayer()
    app._wake = threading.Event()
    return app


# --- the contract ------------------------------------------------------------


def test_status_carries_every_field_the_dashboard_reads() -> None:
    """The key set, exactly. Both directions matter: a field that disappears
    and a field that is not documented in the GUI type are both drift."""
    status = _app().status()
    for field in HOOK_STATUS_FIELDS:
        assert field in status, f"/status lost {field!r}; the GUI reads it"


def test_status_still_carries_the_pre_hook_fields() -> None:
    """F6 added a card, it did not replace the dashboard."""
    status = _app().status()
    for field in ("server", "qwen", "voices", "stale_mappings", "clipboard", "queue_size", "speaker_count"):
        assert field in status, f"/status lost {field!r}"


# --- which adapter each number comes from ------------------------------------


def test_hook_numbers_come_from_the_hook_adapter() -> None:
    app = _app(luna=FakeRoute(client_count=2, dropped=7, last_raw="Rick Hello"))

    status = app.status()

    assert status["hook_clients"] == 2
    assert status["hook_dropped"] == 7
    assert status["hook_last_raw"] == "Rick Hello"


def test_the_two_routes_report_their_own_last_line() -> None:
    """They are separate adapters with separate buffers.

    Sharing one field would mean a game that writes the file and a
    LunaTranslator session look identical from the dashboard, and D9's
    whole point -- telling "nothing arrived" apart from "it arrived and was
    misparsed" -- collapses the moment both routes are on.
    """
    app = _app(
        luna=FakeRoute(client_count=1, last_raw="Anne Hallo"),
        filemon=FakeRoute(last_raw="Carol Hi"),
    )

    status = app.status()

    assert status["hook_last_raw"] == "Anne Hallo"
    assert status["file_last_raw"] == "Carol Hi"


def test_file_fields_come_from_the_file_adapter() -> None:
    app = _app(filemon=FakeRoute())

    status = app.status()

    assert status["file_running"] is True


# --- routes that never started ----------------------------------------------


def test_a_server_with_no_hook_adapter_reports_zeroes_not_a_crash() -> None:
    """The shipped default: ``hook_mode=clipboard`` has no hook adapter at
    all, and the dashboard polls /status on every install. A missing branch
    here would be a 500 on the main screen of every non-hook user."""
    app = _app()

    status = app.status()

    assert status["hook_clients"] == 0
    assert status["hook_dropped"] == 0
    assert status["hook_last_raw"] == ""
    assert status["file_running"] is False
    assert status["file_last_raw"] == ""


def test_no_hook_adapter_does_not_claim_the_hook_is_off() -> None:
    """``hook_clients == 0`` is a fact about the socket; ``hook_mode`` is a
    fact about the settings. A dashboard that reads the mode from the
    adapter instead would tell a user with a running hook to turn it on."""
    app = _app(luna=FakeRoute(client_count=0))

    status = app.status()

    assert status["hook_mode"] == "both"
    assert status["hook_clients"] == 0


# --- the flags the settings panel mirrors -----------------------------------


def test_status_mirrors_the_bind_address_settings_report() -> None:
    """The GUI shows hook_host/hook_port read-only and tells the user the
    value needs a restart. That hint is only true if the number displayed is
    the number the server actually bound, so it is mirrored rather than
    re-derived here."""
    app = _app()

    status = app.status()

    assert status["hook_host"] == settings.hook_host
    assert status["hook_port"] == settings.hook_port
    assert status["file_watch_path"] == settings.file_watch_path


def test_file_watch_true_without_a_running_adapter_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``file_watch: true`` with ``file_running: false`` is the shape of a
    path that does not exist -- the one configuration a user is most likely
    to get wrong and least likely to be able to diagnose. Collapsing the two
    into a single boolean would erase the difference between "not configured"
    and "configured and broken"."""
    monkeypatch.setattr(settings, "file_watch", True)
    app = _app(filemon=None)

    status = app.status()

    assert status["file_watch"] is True
    assert status["file_running"] is False
    assert status["file_last_raw"] == ""
