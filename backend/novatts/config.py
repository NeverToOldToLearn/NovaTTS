"""Central configuration for NovaTTS."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

_HOOK_MODES = ("clipboard", "websocket", "both")


def _base_dir() -> Path:
    # Explicit override (launcher/diagnostics).
    if env_base := os.environ.get("NOVATTS_BASE_DIR"):
        return Path(env_base).resolve()

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # Dev layout: the exe lives under <repo>\gui\src-tauri\target\...\resources
        # (or backend\dist). Walk up until we find the repo root (a directory
        # containing both `data` and `backend`). That keeps the frozen exe and
        # the `start_all.cmd` python backend on the SAME data dir, so speakers
        # and games never "split" across a second location depending on which
        # launch method was used.
        cur = exe_dir
        for _ in range(6):
            if (cur / "data").is_dir() and (cur / "backend").is_dir():
                return cur
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
        # Installed-layout fallbacks (no repo root around).
        if exe_dir.name.lower() == "resources":
            return exe_dir.parent
        if (exe_dir / "data").exists() or (exe_dir / "backend").exists():
            return exe_dir
        parent = exe_dir.parent
        if (parent / "data").exists():
            return parent
        return exe_dir
    # Source layout (python run.py in backend/): repo root.
    return Path(__file__).resolve().parent.parent.parent


def _backend_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = _base_dir()
        cand = base / "backend"
        if cand.exists():
            return cand
        return base
    return Path(__file__).resolve().parent.parent


BASE_DIR = _base_dir()
DATA_DIR = BASE_DIR / "data"
BACKEND_DIR = _backend_dir()


class Settings(BaseSettings):
    """Runtime settings, overridable via environment variables or .env."""

    model_config = SettingsConfigDict(
        env_prefix="NOVATTS_",
        env_file=(str(BACKEND_DIR / ".env"), str(BASE_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 8765

    # --- Qwen3-TTS backend (qwentts.cpp server) ---
    # Default 8080 matches qwentts.cpp's tts-server default; override via
    # NOVATTS_QWEN_URL if you run it on 8081 (e.g. docker SearXNG occupies 8080).
    qwen_url: str = "http://127.0.0.1:8080"
    qwen_timeout: float = 300.0
    # Empty voice = let the model use its built-in voice. Set a name here
    # to force every unassigned speaker onto one registered clone.
    qwen_default_voice: str = ""
    # Local tts-server binary + models for one-click / auto-start.
    qwen_bin: str = r"D:\Projects\qwentts.cpp\build\Release\tts-server.exe"
    qwen_model: str = r"E:\LLM's\Qwen3TTS\qwen-talker-1.7b-base-Q8_0.gguf"
    qwen_codec: str = r"E:\LLM's\Qwen3TTS\qwen-tokenizer-12hz-Q8_0.gguf"
    qwen_autostart: bool = True
    qwen_extra_args: str = "--alias qwen3-tts"
    qwen_auto_import_samples: bool = True
    qwen_samples_dir: str = r"D:\!!Scripts!!\Samples_Clone"
    qwen_samples_dirs_extra: str = r""
    # qwen-codec.exe binary for pre-extracting .spk/.rvq voice references.
    # Leeg = auto-detect als sibling van NOVATTS_QWEN_BIN.
    qwen_codec_bin: str = ""
    blacklist_file: Path = DATA_DIR / "blacklist.json"

    # --- Clipboard adapter ---
    poll_interval: float = 0.25
    min_text_length: int = 3
    # Log every raw clipboard capture (before any filtering) to a file so
    # regex/filter tuning can copy the exact source texts.
    log_raw_clipboard: bool = True
    clipboard_raw_log: Path = DATA_DIR / "logs" / "clipboard_raw.log"

    # --- Hook input (LunaTranslator / Textractor) ---
    # Which raw_text source is active. "clipboard" is the RenPy route,
    # "websocket" is the LunaHook route, "both" runs them side by side.
    #
    # Default is "websocket" since F8 (D2). That was the point of the phase:
    # the hook is now the primary source, and RenPy stays reachable as an
    # explicit choice plus as the "both" mode. Note that the *validator*
    # still falls back to "both" on a bad value -- deliberately, and not
    # because it was forgotten. See D29: a typo in the config should land
    # on maximum tolerance, not on the strictest route.
    hook_mode: Literal["clipboard", "websocket", "both"] = "websocket"
    # NovaTTS *serves* the websocket by default, at
    # ws://<hook_host>:<hook_port>, and the hook connects to it. Not every
    # hook does it that way round: the textractor_websocket extension is a
    # server itself, and then NovaTTS connects out -- which is what
    # luna_ws_url below selects. Both directions work, so neither is
    # special. D39. Loopback only, never 0.0.0.0.
    hook_host: str = "127.0.0.1"
    hook_port: int = 6677
    # Textractor sends "Rick It's 2 parts." (space-separated speaker);
    # some games send "Rick: It's 2 parts." (RenPy-style colon).
    # True = space form, which is the Textractor default.
    hook_space_form: bool = True
    # Some games need the hook attached twice (e.g. per-frame hooks) to
    # capture every line. Doubles traffic; off by default.
    hook_dual_hook: bool = False
    # Optional outbound ws client instead of the built-in server.
    # Empty = serve. Non-empty (e.g. ws://127.0.0.1:6678) = connect.
    luna_ws_url: str = ""
    # Tertiary route: tail a Textractor output file. Off by default --
    # only useful when neither clipboard nor ws is reachable.
    file_watch: bool = False
    file_watch_path: str = "textractor_output.txt"
    # Ignore an identical line arriving within this window, in ms.
    # Textractor re-emits the same line on window change and on re-focus.
    dedup_window_ms: int = 500

    # --- Audio ---
    audio_sample_rate: int = 22050
    # Level every synthesized line to one peak (F19). Qwen's output varies
    # per voice and per line (measured peaks 0.16-0.65 on the live cache),
    # so without this a quiet line drowns in the game mix. Runs on fresh
    # syntheses and on cache hits; switching it off restores old behavior.
    normalize_audio: bool = True
    normalize_target_peak: float = 0.89

    # --- Cache ---
    cache_dir: Path = DATA_DIR / "cache"

    # --- Files ---
    speakers_file: Path = DATA_DIR / "speakers.json"
    games_dir: Path = DATA_DIR / "games"
    emotion_patterns_file: Path = DATA_DIR / "emotion_patterns.json"
    emotion_sounds_dir: str = r"C:\Piper\emotion_sounds"
    emotion_sound_map_file: Path = DATA_DIR / "emotion_sound_map.json"
    emotion_aliases_file: Path = DATA_DIR / "emotion_aliases.json"
    # Perfect Cut tool (separate window) — batch dirs + external binaries.
    perfect_cut_config: Path = DATA_DIR / "perfect_cut.json"

    # --- Logging ---
    log_level: str = "INFO"

    @field_validator("hook_mode", mode="before")
    @classmethod
    def _coerce_hook_mode(cls, value: object) -> str:
        """Fall back to "both" on an unrecognised hook_mode.

        Without this, a typo like NOVATTS_HOOK_MODE=websockets makes
        pydantic raise at import time and the backend dies with a
        ValidationError instead of starting. The donor project (B) did
        the same fallback by hand in `_apply_env_overrides`; here the
        type does it. Failing soft is deliberate, but we warn, so the
        typo is still visible in the log rather than silently ignored.
        """
        if isinstance(value, str):
            normalised = value.strip().lower()
            if normalised in _HOOK_MODES:
                return normalised
        log.warning(
            "NOVATTS_HOOK_MODE=%r is not one of %s; falling back to 'both'",
            value,
            "/".join(_HOOK_MODES),
        )
        return "both"

    @field_validator("luna_ws_url", mode="before")
    @classmethod
    def _coerce_luna_ws_url(cls, value: object) -> str:
        """Repair a pasted assignment; refuse a URL that cannot be dialled.

        Measured in F14: backend/.env contained

            NOVATTS_LUNA_WS_URL=NOVATTS_LUNA_WS_URL=ws://127.0.0.1:6677

        because a whole ``KEY=value`` line was typed into a field that
        already carried the key. The stored value is then a string that is
        not a URL -- and a *non-empty* ``luna_ws_url`` is precisely what
        switches LunaAdapter out of server mode and into client mode, so a
        typo in one field silently stopped the hook from ever listening.
        Nothing in the UI said so: /status still reported hook_mode=websocket
        and hook_clients=0, which is what a healthy, merely-idle hook looks
        like.

        Two repairs, in this order:

        * Strip a repeated ``NOVATTS_LUNA_WS_URL=`` prefix. What the user
          meant is unambiguous, and refusing it would be pedantry.
        * Anything still not ``ws://`` or ``wss://`` becomes empty, which is
          server mode. Same reasoning as D29 and the validator above: a typo
          must land on the route that needs nothing external, not on a dead
          end. We warn either way, so the repair is visible rather than
          silent.
        """
        if not isinstance(value, str):
            return ""
        url = value.strip()
        # Repeated, not once: the doubled assignment is what was measured,
        # and a triple is the same mistake pasted twice more.
        while True:
            head, sep, tail = url.partition("=")
            if not sep or head.strip() != "NOVATTS_LUNA_WS_URL":
                break
            url = tail.strip()
        if not url:
            return ""
        if not url.startswith(("ws://", "wss://")):
            log.warning(
                "NOVATTS_LUNA_WS_URL=%r is not a ws:// or wss:// URL; using "
                "server mode instead (NovaTTS listens, the hook connects)",
                value,
            )
            return ""
        return url


settings = Settings()
