"""Central configuration for NovaTTS."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # --- Sampling ---
    # Sent on every request. Left out, qwentts.cpp samples with a fresh random
    # seed at temperature 0.9 / top_p 1.0 / top_k 50, so the same line comes
    # out differently every time and sometimes runs past its own full stop into
    # a breath or a hic the text never asked for -- a sentence that ends as if
    # it has more to say. These are the upstream defaults with the long tail
    # closed off; the seed makes a line repeatable without a disk cache.
    qwen_seed: int = 1234
    qwen_temperature: float = 0.7
    qwen_top_p: float = 0.8
    qwen_top_k: int = 20
    qwen_repetition_penalty: float = 1.05
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

    # --- Audio ---
    audio_sample_rate: int = 22050
    # Level every synthesized line to one peak (F19, ported from Luna-Hook).
    # Qwen's output varies per voice and per line, so without this a quiet
    # line drowns in the game mix. Runs on fresh syntheses and on cache hits;
    # switching it off restores old behavior.
    normalize_audio: bool = True
    normalize_target_peak: float = 0.89

    # --- Cache ---
    cache_dir: Path = DATA_DIR / "cache"
    # The content-hash cache is inherited from the source project, where a
    # synthesis cost enough to be worth deduplicating. Qwen3 is fast enough
    # that a repeat costs nothing worth saving, and replaying a stored take
    # also replays the emotion the model put in it that one time. Off by
    # default; each line then gets a throwaway file, removed once it played.
    cache_enabled: bool = False

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


settings = Settings()
