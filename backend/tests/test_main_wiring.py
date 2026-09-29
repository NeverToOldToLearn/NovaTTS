"""Tests for the NovaApp wiring that F4 added.

``NovaApp`` is normally built by the server's lifespan hook, and building
a real one pulls in the TTS backend, the audio player and the on-disk
speaker registry. None of that is needed to answer the two questions this
file asks, so the app is created with ``__new__`` and given doubles: which
adapters start for a given ``hook_mode``, and in what order shutdown
happens.

Both questions matter more than they look. If ``_start_adapters`` picks
the wrong branch, ``hook_mode=both`` is indistinguishable from a hook that
silently never bound -- the same class of silent failure F3 spent a phase
hunting. And if the hook is not stopped before the synthesis backend, a
dispatch thread blocked in a request wakes up to a dead backend on every
shutdown.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from novatts import main as main_mod
from novatts.config import settings
from novatts.models import Dialogue
from novatts.registry.speakers import SpeakerRegistry


class FakeAdapter:
    """Stands in for ClipboardAdapter / LunaAdapter on the app side."""

    def __init__(self, kind: str, order: list[str], on_dialogue: Any) -> None:
        self.kind = kind
        self.order = order
        self.on_dialogue = on_dialogue
        self.known_speakers: list[str] = []
        self.known_at_start: list[str] = []
        self.started = False
        self.raw_log: list[str] = []

    def set_known_speakers(self, names: list[str]) -> None:
        self.known_speakers = list(names)

    def start(self) -> None:
        self.started = True
        self.known_at_start = list(self.known_speakers)
        self.order.append(f"start:{self.kind}")

    def stop(self) -> None:
        self.order.append(f"stop:{self.kind}")

    def is_running(self) -> bool:
        return self.started


class FakeRegistry:
    def __init__(self, order: list[str], *names: str) -> None:
        self.order = order
        self._names = list(names) or ["Narrator"]

    def names(self) -> list[str]:
        return list(self._names)

    def maybe_autosave(self) -> None:
        self.order.append("autosave:registry")


class Recorder:
    """A double that records each lifecycle call it receives."""

    def __init__(self, name: str, order: list[str]) -> None:
        self.name = name
        self.order = order

    def stop(self) -> None:
        self.order.append(f"stop:{self.name}")

    def clear_cache(self) -> None:
        self.order.append(f"clear_cache:{self.name}")

    def forget(self) -> None:
        self.order.append(f"forget:{self.name}")


def _install_adapters(monkeypatch: pytest.MonkeyPatch, order: list[str]) -> dict[str, list[FakeAdapter]]:
    made: dict[str, list[FakeAdapter]] = {"clipboard": [], "luna": []}

    def factory(kind: str) -> Any:
        def make(*, on_dialogue: Any) -> FakeAdapter:
            adapter = FakeAdapter(kind, order, on_dialogue)
            made[kind].append(adapter)
            return adapter

        return make

    monkeypatch.setattr(main_mod, "ClipboardAdapter", factory("clipboard"))
    monkeypatch.setattr(main_mod, "LunaAdapter", factory("luna"))
    return made


def _shell(order: list[str], registry: Any = None) -> Any:
    """A NovaApp with no __init__ side effects and only the attributes
    _start_adapters/stop touch."""
    app = main_mod.NovaApp.__new__(main_mod.NovaApp)
    app.clipboard = None
    app.luna = None
    app.registry = registry if registry is not None else FakeRegistry(order, "Rick")
    app.on_dialogue = lambda dialogue: None
    app._running = True
    app._wake = threading.Event()
    app._worker = None
    app.player = Recorder("player", order)
    app.qwen_mgr = Recorder("qwen_mgr", order)
    app.voices = Recorder("voices", order)
    app.gate = Recorder("gate", order)
    return app


# --- adapter selection ------------------------------------------------------


def test_clipboard_mode_starts_only_the_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    made = _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "clipboard")
    app = _shell(order)

    app._start_adapters()

    assert len(made["clipboard"]) == 1
    assert made["clipboard"][0].started is True
    assert made["luna"] == []
    assert app.luna is None


def test_websocket_mode_starts_only_the_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    made = _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "websocket")
    app = _shell(order)

    app._start_adapters()

    assert made["clipboard"] == []
    assert app.clipboard is None
    assert len(made["luna"]) == 1
    assert made["luna"][0].started is True


def test_both_mode_starts_both(monkeypatch: pytest.MonkeyPatch) -> None:
    """The F1 default. Both must run, because the hook is proven against a
    route that already works."""
    order: list[str] = []
    made = _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "both")
    app = _shell(order)

    app._start_adapters()

    assert made["clipboard"][0].started is True
    assert made["luna"][0].started is True


def test_both_adapters_feed_the_same_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """One gate, one worker, one synthesis path -- regardless of source."""
    order: list[str] = []
    _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "both")
    app = _shell(order)

    app._start_adapters()

    assert app.clipboard.on_dialogue == app.on_dialogue
    assert app.luna.on_dialogue == app.on_dialogue


def test_adapters_receive_the_registered_speakers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The parser trusts registry names over its heuristics, so both
    adapters must be told which names the user has already registered."""
    order: list[str] = []
    _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "both")
    app = _shell(order)

    app._start_adapters()

    assert app.clipboard.known_speakers == ["Rick"]
    assert app.luna.known_speakers == ["Rick"]


def test_known_speakers_are_set_before_the_threads_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordering invariant, not a preference.

    Both adapters read the known-name set from inside their polling
    thread, and the thread is live the moment ``start()`` returns. If the
    priming moves after the start calls, the first line of the session can
    be parsed against an empty name set -- which turns a registered
    speaker into narration or a guess, once, at startup.
    """
    order: list[str] = []
    _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "both")
    app = _shell(order)

    app._start_adapters()

    assert app.clipboard.known_at_start == ["Rick"]
    assert app.luna.known_at_start == ["Rick"]


# --- shutdown ordering ------------------------------------------------------


def test_stop_shuts_the_hook_down_before_the_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "both")
    app = _shell(order)
    app._start_adapters()

    app.stop()

    assert order.index("stop:luna") < order.index("stop:qwen_mgr")
    assert order.index("stop:clipboard") < order.index("stop:qwen_mgr")
    assert order.index("stop:player") < order.index("stop:qwen_mgr")
    # The ephemeral state is discarded last.
    assert order.index("forget:gate") > order.index("stop:qwen_mgr")
    assert order.index("autosave:registry") == len(order) - 1


def test_stop_is_safe_with_the_hook_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """hook_mode=clipboard leaves self.luna None; shutdown must not care."""
    order: list[str] = []
    _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "clipboard")
    app = _shell(order)
    app._start_adapters()

    app.stop()

    assert "stop:clipboard" in order
    assert "stop:qwen_mgr" in order
    assert not any(entry == "stop:luna" for entry in order)


def test_stop_turns_off_accepting_new_work_first(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "both")
    app = _shell(order)
    app._start_adapters()
    observed: list[bool] = []
    app.luna.stop = lambda: observed.append(app._running)  # type: ignore[method-assign]

    app.stop()

    assert observed == [False]


def test_stop_clears_the_dedup_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """A restart must not inherit the previous session's 500 ms window."""
    order: list[str] = []
    _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "both")
    app = _shell(order)
    app._start_adapters()

    app.stop()

    assert "forget:gate" in order


# --- per-game registry swap -------------------------------------------------


class FakeGames:
    def __init__(self, path: Path) -> None:
        self.path = path

    def set_active(self, name: str) -> str:
        return name

    def speakers_path(self, name: str) -> Path:
        return self.path


def test_switching_game_reprimes_the_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A per-game registry swap must reach the hook too, or the hook keeps
    trusting the previous game's cast while the clipboard moves on."""
    order: list[str] = []
    _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "both")
    app = _shell(order)
    app._start_adapters()
    assert app.luna.known_speakers == ["Rick"]
    app.games = FakeGames(tmp_path / "speakers.json")
    app._emit = lambda event: None

    app.switch_game("Another Game")

    # The fresh per-game registry knows only the fallback speaker, and
    # both adapters must have been told that.
    assert app.luna.known_speakers == ["Narrator"]
    assert app.clipboard.known_speakers == ["Narrator"]


# --- manual registration (the remedy the trust gate points at) --------------


def test_registering_a_speaker_by_hand_reaches_the_hook(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The end-to-end shape of the trust gate's remedy.

    The gate refuses to persist a guessed name, so the documented fix is
    for the user to register it themselves. That registration arrives
    through ``POST /speakers``, and if it does not reach the hook the user
    has done the right thing and seen nothing change.

    Uses a real SpeakerRegistry, because the point is the wiring between
    three real pieces -- the route, the registry and the adapters.
    """
    order: list[str] = []
    _install_adapters(monkeypatch, order)
    monkeypatch.setattr(settings, "hook_mode", "both")
    registry = SpeakerRegistry(tmp_path / "speakers.json", auto_save_interval=0.0)
    app = _shell(order, registry=registry)
    app._start_adapters()
    assert app.luna.known_speakers == ["Narrator"]
    monkeypatch.setattr(main_mod, "_runtime", app)

    asyncio.run(main_mod.create_speaker(main_mod.SpeakerCreateBody(name="Rick")))

    assert "Rick" in registry.names()
    assert "Rick" in app.luna.known_speakers
    assert app.clipboard.known_speakers == app.luna.known_speakers


# --- emotion segmentation ---------------------------------------------------


def test_emotion_segments_keep_the_source_line_intact() -> None:
    """A segment differs from its parent only in the text it speaks.

    Splitting a line on emotion tags used to rebuild the Dialogue by hand,
    so ``raw`` vanished precisely when an emotion tag was present -- the
    forensic record lost in the one case where the text had been altered.
    ``replace`` carries the source line and the provenance flag.
    """
    parent = Dialogue(
        speaker="Rick",
        text="[angry] Get out.",
        source="luna",
        raw="Rick Get out.",
        speaker_is_guess=True,
    )

    segment = main_mod.NovaApp._segment_dialogue(parent, "Get out.")

    assert segment.text == "Get out."
    assert segment.speaker == "Rick"
    assert segment.raw == "Rick Get out."
    assert segment.speaker_is_guess is True
