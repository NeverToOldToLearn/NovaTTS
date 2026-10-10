"""Tests for per-game folder links and the RenPy helper mod."""

import json
from pathlib import Path

from novatts import game_link
from novatts.game_link import (
    HELPER_FILENAME,
    HELPER_MARKER,
    find_game_root,
    helper_status,
    install_helper,
)
from novatts.games import GameManager


def _game_root(tmp_path: Path, name: str = "SomeGame") -> Path:
    root = tmp_path / name
    (root / "game").mkdir(parents=True)
    return root


def _manager(tmp_path: Path, monkeypatch=None) -> GameManager:
    from novatts import config as _config

    data = tmp_path / "data"
    (data / "games").mkdir(parents=True)
    monkeypatch.setattr(_config.settings, "games_dir", data / "games")
    monkeypatch.setattr(_config.settings, "speakers_file", data / "speakers.json")
    monkeypatch.setattr(_config.settings, "cache_dir", data / "cache")
    return GameManager()


def test_find_game_root_accepts_root_and_gamedir(tmp_path):
    root = _game_root(tmp_path)
    assert find_game_root(root) == root.resolve()
    assert find_game_root(root / "game") == root.resolve()
    assert find_game_root(tmp_path / "nope") is None
    plain = tmp_path / "plain"
    plain.mkdir()
    assert find_game_root(plain) is None


def test_install_helper_fresh_and_idempotent(tmp_path):
    root = _game_root(tmp_path)
    assert helper_status(root) == "missing"
    assert install_helper(root) == "current"
    target = root / "game" / HELPER_FILENAME
    assert HELPER_MARKER in target.read_text(encoding="utf-8")
    assert helper_status(root) == "current"
    assert install_helper(root) == "current"


def test_install_helper_never_overwrites_foreign(tmp_path):
    root = _game_root(tmp_path)
    target = root / "game" / HELPER_FILENAME
    target.write_text("A totally different mod.\n", encoding="utf-8")
    assert helper_status(root) == "foreign"
    assert install_helper(root) == "foreign"
    assert target.read_text(encoding="utf-8") == "A totally different mod.\n"


def test_install_helper_upgrades_outdated(tmp_path):
    root = _game_root(tmp_path)
    target = root / "game" / HELPER_FILENAME
    target.write_text(f"{HELPER_MARKER} v0 -- managed\ninit python:\n    pass\n", encoding="utf-8")
    assert helper_status(root) == "outdated"
    assert install_helper(root) == "current"


def test_snippet_enables_clipboard_and_hides_banner():
    src = game_link.helper_source()
    assert '_preferences.self_voicing = "clipboard"' in src
    assert 'renpy.hide_screen("_self_voicing")' in src
    assert "\r" not in src


def test_set_link_installs_and_migrates(tmp_path, monkeypatch):
    gm = _manager(tmp_path, monkeypatch)
    gm.ensure_game("My Game")
    legacy = tmp_path / "data" / "games" / "My_Game" / "speakers.json"
    assert legacy.exists()
    root = _game_root(tmp_path)
    result = gm.set_link("My Game", str(root))
    assert result["game"] == "My_Game"
    assert result["folder"] == str(root.resolve())
    assert result["helper"] == "current"
    assert result["migrated"] is True
    assert not legacy.exists()
    assert gm.speakers_path("My Game") == root.resolve() / "novatts" / "speakers.json"
    assert gm.links() == {"My_Game": str(root.resolve())}


def test_set_link_keeps_existing_target_speakers(tmp_path, monkeypatch):
    gm = _manager(tmp_path, monkeypatch)
    gm.ensure_game("My Game")
    root = _game_root(tmp_path)
    target = root.resolve() / "novatts" / "speakers.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"versions": 1, "speakers": {}}), encoding="utf-8")
    result = gm.set_link("My Game", str(root))
    assert result["migrated"] is False
    assert gm.speakers_path("My Game") == target


def test_set_link_rejects_non_game_folder(tmp_path, monkeypatch):
    import pytest

    gm = _manager(tmp_path, monkeypatch)
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ValueError):
        gm.set_link("My Game", str(plain))
    with pytest.raises(ValueError):
        gm.set_link("My Game", str(tmp_path / "missing"))


def test_unlink_falls_back_to_legacy(tmp_path, monkeypatch):
    gm = _manager(tmp_path, monkeypatch)
    root = _game_root(tmp_path)
    gm.set_link("My Game", str(root))
    assert gm.remove_link("My Game") == "My_Game"
    assert gm.links() == {}
    assert gm.speakers_path("My Game") == tmp_path / "data" / "games" / "My_Game" / "speakers.json"


def test_prunes_dead_links(tmp_path, monkeypatch):
    gm = _manager(tmp_path, monkeypatch)
    root = _game_root(tmp_path)
    gm.set_link("My Game", str(root))
    import shutil

    shutil.rmtree(root)
    assert gm.links() == {}
    assert gm.speakers_path("My Game") == tmp_path / "data" / "games" / "My_Game" / "speakers.json"
