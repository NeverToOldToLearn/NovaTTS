"""Per-game folder links and the RenPy helper mod.

One conscious moment per game: the user points NovaTTS at a game folder.
That single link then covers two things:

- The helper mod (``game/novatts_helper.rpy``, URM-style distribution: one
  file dropped into the game's ``game`` directory) enables clipboard
  voicing automatically and hides Ren'Py's native
  "Clipboard voicing enabled" banner every interaction. The banner text is
  Ren'Py's own, not the game's, and the user already chose NovaTTS for TTS.
- The game's ``speakers.json`` moves into ``<game-root>/novatts/`` so it is
  deleted *with* the game instead of orphaning in our data dir.

Only files carrying our marker are ever overwritten; a foreign file with
the same name is left alone and reported.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

HELPER_VERSION = 1
HELPER_FILENAME = "novatts_helper.rpy"
HELPER_MARKER = "# NovaTTS helper"
HELPER_SPEAKERS_SUBDIR = "novatts"
HELPER_SPEAKERS_FILE = "speakers.json"

HELPER_TEMPLATE = """\
# NovaTTS helper v{version} -- managed by NovaTTS, safe to overwrite on reinstall.
# - Enables clipboard voicing automatically (same as Shift+C / the
#   "clipboard voicing" preference).
# - Hides Ren'Py's native "Clipboard voicing enabled" banner every
#   interaction, so it never covers game UI.
init python:
    _preferences.self_voicing = "clipboard"
    config.interact_callbacks.append(lambda: renpy.hide_screen("_self_voicing"))
"""


def helper_source(*, version: int = HELPER_VERSION) -> str:
    """Render the snippet (LF endings; RenPy accepts them on all platforms)."""
    return HELPER_TEMPLATE.format(version=version).replace("\r\n", "\n").replace("\r", "\n")


def find_game_root(folder: str | Path) -> Path | None:
    """Resolve a user-picked folder to a RenPy game root, or None.

    Accepts the root (containing ``game/``) or the ``game/`` dir itself.
    """
    p = Path(folder).expanduser()
    if not p.is_dir():
        return None
    if (p / "game").is_dir():
        return p.resolve()
    if p.name.lower() == "game" and p.parent.is_dir():
        return p.parent.resolve()
    return None


def helper_path(root: str | Path) -> Path:
    return Path(root) / "game" / HELPER_FILENAME


def speakers_path_for(root: str | Path) -> Path:
    return Path(root) / HELPER_SPEAKERS_SUBDIR / HELPER_SPEAKERS_FILE


def helper_status(root: str | Path) -> str:
    """One of: current, outdated, missing, foreign, unwritable."""
    target = helper_path(root)
    if not target.exists():
        return "missing"
    try:
        content = target.read_text(encoding="utf-8")
    except OSError:
        return "unwritable"
    if HELPER_MARKER not in content:
        return "foreign"
    if f"v{HELPER_VERSION} " in content or f"v{HELPER_VERSION}\n" in content:
        return "current"
    return "outdated"


def install_helper(root: str | Path) -> str:
    """Write the snippet unless a foreign file blocks the name.

    Returns the resulting status (see :func:`helper_status`). Never
    overwrites a file without our marker.
    """
    status = helper_status(root)
    if status in ("current", "foreign", "unwritable"):
        return status
    target = helper_path(root)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(helper_source(), encoding="utf-8")
    except OSError as exc:
        log.warning("Helper install failed for %s: %s", target, exc)
        return "unwritable"
    log.info("Helper %s installed in %s", HELPER_FILENAME, target.parent)
    return "current"
