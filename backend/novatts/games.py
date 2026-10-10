from __future__ import annotations

import contextlib
import json
import logging
import re
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

def _sanitize(name: str) -> str:
    name = name.strip()
    if not name:
        return "_default"
    s = _SAFE_RE.sub("_", name)[:60].strip("_")
    return s or "_default"

class GameManager:
    def __init__(self) -> None:
        self.games_dir = Path(settings.games_dir) if hasattr(settings, "games_dir") else settings.cache_dir.parent / "games"
        self.games_dir.mkdir(parents=True, exist_ok=True)
        self.active_file = self.games_dir.parent / "active_game.json"
        self.links_file = self.games_dir.parent / "game_links.json"
        self._active: str = self._load_active()
        self._links: dict[str, str] = self._load_links()

    def _load_active(self) -> str:
        try:
            if self.active_file.exists():
                data = json.loads(self.active_file.read_text(encoding="utf-8"))
                name = str(data.get("active", "")).strip()
                if name:
                    return _sanitize(name)
        except Exception:
            pass
        return ""

    def _save_active(self) -> None:
        with contextlib.suppress(Exception):
            self.active_file.write_text(json.dumps({"active": self._active}, indent=2), encoding="utf-8")

    def _load_links(self) -> dict[str, str]:
        try:
            if self.links_file.exists():
                raw = json.loads(self.links_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return {str(k): str(v) for k, v in raw.items() if str(k) and str(v)}
        except Exception:
            pass
        return {}

    def _save_links(self) -> None:
        with contextlib.suppress(Exception):
            self.links_file.write_text(json.dumps(self._links, indent=2, sort_keys=True), encoding="utf-8")

    def links(self) -> dict[str, str]:
        """Linked game folders, pruned of roots that no longer exist."""
        live = {name: folder for name, folder in self._links.items() if Path(folder).is_dir()}
        if len(live) != len(self._links):
            self._links = live
            self._save_links()
        return dict(live)

    def linked_folder(self, game: str | None = None) -> Path | None:
        """Game root for a linked game, or None (legacy data-dir storage)."""
        g = _sanitize(game) if game is not None else self._active
        folder = self.links().get(g)
        if not folder:
            return None
        from .game_link import find_game_root

        return find_game_root(folder)

    def set_link(self, game: str, folder: str) -> dict[str, object]:
        """Link a game to its folder: install helper, migrate speakers.

        Returns a status dict. Raises ValueError when the folder is not a
        RenPy game root. A foreign ``novatts_helper.rpy`` is never
        overwritten -- the link still lands, the helper reports "foreign".
        """
        from .game_link import (
            HELPER_FILENAME,
            helper_path,
            install_helper,
            speakers_path_for,
        )

        name = _sanitize(game)
        if not name:
            raise ValueError("Game name required")
        from .game_link import find_game_root

        root = find_game_root(folder)
        if root is None:
            raise ValueError(f"Not a RenPy game folder (no game/ subdir): {folder}")
        self._links[name] = str(root)
        self._save_links()

        helper = install_helper(root)
        if helper in ("foreign", "unwritable"):
            log.warning("Game link %s: helper %s (%s)", name, helper, helper_path(root))

        migrated = False
        target = speakers_path_for(root)
        legacy = self.games_dir / name / "speakers.json"
        if not target.exists() and legacy.exists():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                legacy.replace(target)
                migrated = True
            except OSError:
                pass
        if not target.exists():
            self._write_default_speakers(target)
        return {
            "game": name,
            "folder": str(root),
            "helper": helper,
            "helper_file": HELPER_FILENAME,
            "speakers": str(target),
            "migrated": migrated,
        }

    def remove_link(self, game: str) -> str:
        name = _sanitize(game)
        self._links.pop(name, None)
        self._save_links()
        return name

    def _write_default_speakers(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"versions": 1, "speakers": {"Narrator": {"name": "Narrator", "voice": "", "instruct": "", "emotion": "neutral"}}}, indent=2), encoding="utf-8")
        except OSError:
            pass

    def active(self) -> str:
        return self._active

    def set_active(self, name: str) -> str:
        name = _sanitize(name) if name.strip() else ""
        if name and name != "_default":
            linked = self.linked_folder(name)
            if linked is not None:
                from .game_link import speakers_path_for

                speakers_path_for(linked).parent.mkdir(parents=True, exist_ok=True)
            else:
                (self.games_dir / name).mkdir(parents=True, exist_ok=True)
        self._active = name
        self._save_active()
        return self._active

    def list_games(self) -> list[str]:
        games: list[str] = []
        if self.games_dir.exists():
            for p in self.games_dir.iterdir():
                if p.is_dir():
                    games.append(p.name)
        for name in self.links():
            if name not in games:
                games.append(name)
        return sorted(games)

    def speakers_path(self, game: str | None = None) -> Path:
        g = _sanitize(game) if game is not None else self._active
        if not g:
            return Path(settings.speakers_file)
        linked = self.linked_folder(g)
        if linked is not None:
            from .game_link import speakers_path_for

            return speakers_path_for(linked)
        return self.games_dir / g / "speakers.json"

    def ensure_game(self, name: str) -> str:
        s = _sanitize(name)
        if not s:
            raise ValueError("Game name required")
        sp = self.speakers_path(s)
        if not sp.exists():
            self._write_default_speakers(sp)
        return s
