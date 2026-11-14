"""Per-game auto-forward target persistence.

A captured game window belongs to one game, not to the machine: it is kept
in the same folder as that game's speakers.json, so switching games restores
the right window and the file disappears with the game folder.
"""

from __future__ import annotations

import json

import pytest

from novatts.config import settings
from novatts.games import GameManager


@pytest.fixture
def gm(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "games_dir", tmp_path / "games", raising=False)
    monkeypatch.setattr(settings, "speakers_file", tmp_path / "speakers.json", raising=False)
    return GameManager()


def test_no_active_game_keeps_no_per_game_window(gm):
    assert gm.active() == ""
    assert gm.autoforward_path() is None
    assert gm.auto_forward_window() is None


def test_window_saved_beside_speakers_in_data_dir(gm):
    gm.set_active("MyGame")
    path = gm.set_auto_forward_window("My Game — RenPy")
    assert path == gm.speakers_path().parent / "autoforward.json"
    assert json.loads(path.read_text(encoding="utf-8"))["window"] == "my game — renpy"
    assert gm.auto_forward_window() == "my game — renpy"


def test_window_saved_in_linked_game_folder(gm, tmp_path):
    root = tmp_path / "SomeGame"
    (root / "game").mkdir(parents=True)
    gm.set_link("SomeGame", str(root))
    gm.set_active("SomeGame")
    path = gm.set_auto_forward_window("SomeWindow")
    assert path == (root / "novatts" / "autoforward.json").resolve()
    assert gm.auto_forward_window() == "somewindow"


def test_linking_migrates_an_existing_window(gm, tmp_path):
    gm.set_active("Migrating")
    old = gm.set_auto_forward_window("Old Window")
    assert old is not None and old.exists()

    root = tmp_path / "MigratingRoot"
    (root / "game").mkdir(parents=True)
    gm.set_link("Migrating", str(root))

    new = (root / "novatts" / "autoforward.json").resolve()
    assert new.exists()
    assert not old.exists()
    assert json.loads(new.read_text(encoding="utf-8"))["window"] == "old window"


def test_switching_games_returns_each_window(gm, tmp_path):
    root = tmp_path / "LinkedGame"
    (root / "game").mkdir(parents=True)
    gm.set_link("LinkedGame", str(root))

    gm.set_active("LinkedGame")
    gm.set_auto_forward_window("Linked Window")

    gm.set_active("OtherGame")
    gm.set_auto_forward_window("Other Window")
    assert gm.auto_forward_window() == "other window"

    gm.set_active("LinkedGame")
    assert gm.auto_forward_window() == "linked window"
