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
    # --- Streaming (pcm direct van tts-server, zonder WAV-omweg) ---
    # Clipboard-regels gaan per chunk naar de luidspreker zodra de engine ze
    # oplevert, in plaats van pas na de volledige synthese. Scheelt bij lange
    # zinnen seconden time-to-first-audio (anders sneed RenPy-autoforward de
    # lijn af voor hij begon). /speak, previews en de OpenAI-route blijven
    # files gebruiken; bij een onbeschikbaar audio-device valt de worker
    # stilzwijgend terug op het file-pad.
    streaming_enabled: bool = True
    # Start de weergave zodra zoveel audio gebufferd is (of de stream eindigt
    # met minder). Hoger = minder kans op haperen, lager = sneller starten.
    stream_prebuffer_sec: float = 0.4
    # Vaste lift op de live stream: peak-normalize kent het piekniveau pas
    # achteraf en kan hier dus niet draaien. 2.0 tilt de gemeten mediane
    # ruwe piek (~0.39) naar het 0.89-doel; een tanh-limiter vangt clipping af.
    stream_gain: float = 2.0
    # Houd het output-device wakker met onhoorbare stilte terwijl de backend
    # draait. Draadloze headsets (en DSP-stacks) slapen na idle in; de eerste
    # seconden daarna klinken dan krakend tot de link/DSP is bijgetrokken --
    # op beide afspeelpaden, want het zit niet in onze audio. Uit = bespaar
    # headset-batterij; het device slaapt dan weer in bij stilte.
    keep_warm_enabled: bool = True
    # --- Sampling ---
    # Sent on every request so a change in qwentts.cpp's own defaults cannot
    # silently alter the voice. The values ARE the upstream defaults
    # (qwen.h:296-315) -- do not "improve" them without measuring first:
    #
    # * Narrowing top_p/top_k measurably dulls the delivery. On the
    #   EldernNaratorToLateNow clone, temp 0.7 / top_p 0.8 / top_k 20 cost 19%
    #   of the syllable rate (2.38 vs 2.94 syllables/s, 8 samples, non-
    #   overlapping) and lengthened the line by 0.43s. A gentler 0.8 / 0.9 / 40
    #   was no better (-18%), so there is no useful middle setting.
    # * It buys nothing. Trailing silence is 51-181ms either way, so closing
    #   the candidate set does NOT stop a line from ending in a breath or hic.
    # * Going lower is actively dangerous: below ~0.5 the model stops
    #   terminating and runs to max_new_tokens -- 163.84s (2048 tokens at
    #   12.5Hz), measured 3 times out of 3 at temperature 0.
    #
    # The seed does NOT make a line repeatable. The GPU is not deterministic,
    # so a fixed seed still yields different audio every call (measured, never
    # byte-identical). It only fixes the RNG stream, nothing more.
    qwen_seed: int = 1234
    qwen_temperature: float = 0.9
    qwen_top_p: float = 0.9
    qwen_top_k: int = 50
    qwen_repetition_penalty: float = 1.05
    # Hard bound on one request, 1024 tokens = 82s at the codec's 12.5Hz.
    # qwentts.cpp otherwise runs to 2048 tokens (163.84s) when the model stops
    # terminating. Deliberately generous, because the two failures are not
    # symmetric: truncating real speech loses words silently, whereas a long
    # pathological clip is merely ugly. Measured token need for real lines --
    # 1 word 8, 17 words 83, 54 words 201, 148 words 555 -- so 1024 leaves
    # ~1.8x headroom over the longest line tested. At the temperatures above
    # nothing runs away (163.84s measured only at temperature 0, 3 of 3), so
    # this is a sanity bound, not something that fires in normal use.
    qwen_max_new_tokens: int = 1024
    # qwen-codec.exe binary for pre-extracting .spk/.rvq voice references.
    # Leeg = auto-detect als sibling van NOVATTS_QWEN_BIN.
    qwen_codec_bin: str = ""
    # Voice-design (experimenteel): apart 1.7B voicedesign-model + qwen-tts CLI.
    # qwen_tts_bin leeg = auto-detect als sibling van NOVATTS_QWEN_BIN (qwen-tts.exe).
    qwen_voicedesign_model: str = r"E:\LLM's\Qwen3TTS\qwen-talker-1.7b-voicedesign-Q8_0.gguf"
    qwen_tts_bin: str = ""
    voice_design_dir: Path = DATA_DIR / "voice_design"
    # Opt-in voor eindgebruik: uit = geen Voice Design-tab, generate/promote
    # geven een duidelijke melding. Alles buiten voice-design blijft werken.
    voice_design_enabled: bool = False
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

    # --- Emotions: speak instead of swap ---
    # Test mode: keep emotion words as speakable text ("haaa", "hehe",
    # "*laughs*") instead of stripping them or swapping in a pre-recorded
    # .wav clip. Qwen renders short sounds well on its own; this measures
    # how far that stretches before filtering earns its keep. Off = current
    # behavior (strip + wav clips). Needs a backend restart to toggle.
    emotion_speak_words: bool = False

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
