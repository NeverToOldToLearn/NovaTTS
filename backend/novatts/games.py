from __future__ import annotations

import json
import re
from pathlib import Path

from .config import settings

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
        self._active: str = self._load_active()

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
        try:
            self.active_file.write_text(json.dumps({"active": self._active}, indent=2), encoding="utf-8")
        except Exception:
            pass

    def active(self) -> str:
        return self._active

    def set_active(self, name: str) -> str:
        name = _sanitize(name) if name.strip() else ""
        if name and name != "_default":
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
        return sorted(games)

    def speakers_path(self, game: str | None = None) -> Path:
        g = _sanitize(game) if game is not None else self._active
        if not g:
            return Path(settings.speakers_file)
        return self.games_dir / g / "speakers.json"

    def ensure_game(self, name: str) -> str:
        s = _sanitize(name)
        if not s:
            raise ValueError("Game name required")
        (self.games_dir / s).mkdir(parents=True, exist_ok=True)
        sp = self.speakers_path(s)
        if not sp.exists():
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(json.dumps({"versions": 1, "speakers": {"Narrator": {"name": "Narrator", "voice": "", "instruct": "", "emotion": "neutral"}}}, indent=2), encoding="utf-8")
        return s
