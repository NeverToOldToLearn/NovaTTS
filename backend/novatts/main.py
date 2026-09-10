"""NovaTTS FastAPI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .adapters import ClipboardAdapter
from .blacklist import Blacklist, is_renpy_exception
from .config import settings
from .emotions import EmotionSounds
from .games import GameManager
from .models import Dialogue, Event, SpeakRequest
from .player.audio import AudioPlayer
from .qwen_manager import QwenManager
from .registry.speakers import SpeakerRegistry
from .tts.qwen import Qwen3Backend
from .tts.voice_manager import VoiceManager

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# API schema
# ----------------------------------------------------------------------


class SpeakBody(BaseModel):
    text: str = Field(..., min_length=1)
    speaker: str | None = None
    instruct: str = ""
    emotion: str = "neutral"
    voice: str | None = None
    """Explicit voice override (bypasses registry)."""


class SpeakerPatchBody(BaseModel):
    voice: str | None = None


class SpeakerCreateBody(BaseModel):
    name: str = Field(..., min_length=1)


class SpeakerRenameBody(BaseModel):
    new_name: str = Field(..., min_length=1)


class SpeakerAliasBody(BaseModel):
    alias: str = Field(..., min_length=1)


class GameBody(BaseModel):
    name: str = Field(..., min_length=1)


class BlacklistBody(BaseModel):
    custom_words: list[str] | None = None
    enabled_presets: list[str] | None = None


class EmotionAliasBody(BaseModel):
    expr: str = Field(..., min_length=1)
    tag: str = Field(..., min_length=1)


class VoiceCloneBody(BaseModel):
    name: str = Field(..., min_length=1)
    wav_b64: str = Field(...)
    """Base64-encoded WAV sample of the voice to clone."""
    ref_text: str = ""


class SettingsBody(BaseModel):
    qwen_bin: str | None = None
    qwen_model: str | None = None
    qwen_codec: str | None = None
    qwen_url: str | None = None
    qwen_default_voice: str | None = None
    qwen_samples_dir: str | None = None
    qwen_samples_dirs_extra: str | None = None
    emotion_sounds_dir: str | None = None
    qwen_timeout: float | None = None
    qwen_extra_args: str | None = None
    poll_interval: float | None = None


# ----------------------------------------------------------------------
# Application runtime
# ----------------------------------------------------------------------


class NovaApp:
    def __init__(self) -> None:
        self.games = GameManager()
        self.registry = SpeakerRegistry(self.games.speakers_path())
        self.qwen = Qwen3Backend()
        self.qwen_mgr = QwenManager()
        self.voices = VoiceManager(self.qwen, self.registry, settings.cache_dir)
        self.player = AudioPlayer()
        self.emotions = EmotionSounds(player=self.player)
        self.blacklist = Blacklist()
        self.player.on_finished = lambda _p: None  # reserved for event emit
        self.clipboard: ClipboardAdapter | None = None
        self._event_history: list[Event] = []
        import threading

        self._pending_lock = threading.Lock()
        self._pending_dialogue: Dialogue | None = None
        self._pending_seq = 0
        self._worker_seq = 0
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None
        self._running = False

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        try:
            self.qwen_mgr.maybe_autostart()
        except Exception as exc:
            log.warning("Qwen autostart failed (non-fatal): %s", exc)
        self.player.start()
        import threading

        self._running = True
        self._worker = threading.Thread(target=self._dialogue_worker, name="dialogue-worker", daemon=True)
        self._worker.start()
        self.clipboard = ClipboardAdapter(on_dialogue=self.on_dialogue)
        self.clipboard.start()
        log.info("NovaTTS started (qwen_online=%s)", self.qwen.is_available())

    def stop(self) -> None:
        if self.clipboard:
            self.clipboard.stop()
        self._running = False
        try:
            self._wake.set()
        except Exception:
            pass
        if self._worker:
            try:
                self._worker.join(timeout=2.0)
            except Exception:
                pass
            self._worker = None
        self.player.stop()
        import contextlib

        with contextlib.suppress(Exception):
            self.qwen_mgr.stop()
        self.registry.maybe_autosave()

    def _synth_emotion_aware(self, dialogue: Dialogue) -> list[Path]:
        cleaned, emotions = self.emotions.extract(dialogue.text)
        if not cleaned.strip() and emotions:
            out: list[Path] = []
            for _, tag in sorted(emotions):
                p = self.emotions.resolve_path(tag)
                if p is not None:
                    out.append(p)
            return out
        paths: list[Path] = []
        last = 0
        text = cleaned
        for pos, tag in sorted(emotions):
            seg = text[last:pos].strip()
            if seg:
                try:
                    path = self.voices.synthesize(Dialogue(speaker=dialogue.speaker, text=seg, source=dialogue.source, instruct=dialogue.instruct))
                    paths.append(path)
                except Exception as exc:
                    log.error("Synthesis failed: %s", exc)
                    self._emit(Event("error", {"source": "clipboard", "error": str(exc)}))
            ep = self.emotions.resolve_path(tag)
            if ep is not None:
                paths.append(ep)
            last = pos
        seg2 = text[last:].strip()
        if seg2:
            try:
                path2 = self.voices.synthesize(Dialogue(speaker=dialogue.speaker, text=seg2, source=dialogue.source, instruct=dialogue.instruct))
                paths.append(path2)
            except Exception as exc:
                log.error("Synthesis failed: %s", exc)
                self._emit(Event("error", {"source": "clipboard", "error": str(exc)}))
        if not paths and cleaned.strip():
            try:
                paths.append(self.voices.synthesize(dialogue))
            except Exception as exc:
                log.error("Synthesis failed: %s", exc)
                self._emit(Event("error", {"source": "clipboard", "error": str(exc)}))
        return paths

    def _dialogue_worker(self) -> None:
        import time

        while self._running:
            self._wake.wait(timeout=0.5)
            if not self._running:
                return
            if self._pending_dialogue is None:
                self._wake.clear()
                continue
            self._wake.clear()
            time.sleep(0.12)
            with self._pending_lock:
                dialogue = self._pending_dialogue
                seq = self._pending_seq
                self._pending_dialogue = None
            if dialogue is None:
                continue
            with self._pending_lock:
                latest = self._pending_seq
            if seq != latest:
                log.info("Skipped stale dialogue seq=%d latest=%d", seq, latest)
                self._emit(Event("skipped", {"speaker": dialogue.speaker, "text": dialogue.text[:60]}))
                continue
            voice = self.registry.lookup_voice(dialogue.speaker) if dialogue.speaker else ""
            try:
                paths = self._synth_emotion_aware(dialogue)
                if not paths:
                    continue
            except Exception as exc:
                log.error("Synthesis failed: %s", exc)
                self._emit(Event("error", {"source": "clipboard", "error": str(exc)}))
                continue
            with self._pending_lock:
                latest2 = self._pending_seq
            if seq != latest2:
                log.info("Skipped stale after synth seq=%d latest=%d", seq, latest2)
                self._emit(Event("skipped", {"speaker": dialogue.speaker, "text": dialogue.text[:60]}))
                continue
            self.player.enqueue_interrupt(paths[0])
            for p in paths[1:]:
                self.player.enqueue(p)
            self._emit(Event("queued", {"speaker": dialogue.speaker, "voice": voice or "(default)", "files": len(paths)}))

    # -- dialogue pipeline ---------------------------------------------

    def _check_exception_filter(self, raw_text: str) -> bool:
        if is_renpy_exception(raw_text):
            log.debug("Skipping RenPy exception dump")
            self._emit(Event("filtered", {"reason": "renpy_exception", "text": raw_text[:120]}))
            return True
        return False

    def on_dialogue(self, dialogue: Dialogue) -> None:
        raw = dialogue.text
        if self._check_exception_filter(raw):
            return
        filtered = self.blacklist.filter_text(raw)
        if not filtered.strip():
            self._emit(Event("filtered", {"reason": "blacklist", "speaker": dialogue.speaker, "text": raw[:80]}))
            return
        if filtered != raw:
            dialogue = Dialogue(speaker=dialogue.speaker, text=filtered, source=dialogue.source, instruct=dialogue.instruct)
        if not dialogue.is_voiceable:
            return
        seen_new = False
        if dialogue.speaker:
            try:
                if dialogue.speaker not in self.registry.names():
                    self.registry.register(dialogue.speaker)
                    self.registry.save()
                    seen_new = True
                    self._emit(Event("speaker_discovered", {"speaker": dialogue.speaker}))
            except Exception:
                pass
        voice = self.registry.lookup_voice(dialogue.speaker) if dialogue.speaker else ""
        if dialogue.speaker and not voice:
            self._emit(Event("unassigned_speaker", {"speaker": dialogue.speaker, "text": dialogue.text[:80]}))
        self._emit(Event("dialogue", {"speaker": dialogue.speaker, "text": dialogue.text[:120], "new": seen_new}))
        with self._pending_lock:
            self._pending_seq += 1
            self._pending_dialogue = dialogue
        try:
            self.player.stop_current()
        except Exception:
            pass
        self._wake.set()

    # -- API helpers ----------------------------------------------------

    def speak(self, req: SpeakRequest) -> dict[str, Any]:
        from .text_clean import clean_emotion_text

        cleaned = clean_emotion_text(req.text)
        if not cleaned.strip():
            raise HTTPException(status_code=400, detail="Text empty after emotion filtering")
        dialogue = Dialogue(speaker=req.speaker, text=cleaned, source="api", instruct=req.instruct)
        voice = None if req.voice in (None, "", "default") else req.voice
        try:
            path = self.voices.synthesize(dialogue, voice_override=voice)
        except Exception as exc:
            self._emit(Event("error", {"source": "api", "error": str(exc)}))
            raise HTTPException(status_code=502, detail=f"TTS failed: {exc}") from exc
        self.player.enqueue_interrupt(path)
        self._emit(Event("queued", {"speaker": req.speaker, "file": path.name, "source": "api"}))
        return {"status": "queued", "file": path.name}

    def switch_game(self, name: str) -> dict[str, Any]:
        safe = self.games.set_active(name) if name.strip() else self.games.set_active("")
        new_path = self.games.speakers_path(safe)
        self.registry = SpeakerRegistry(new_path)
        self.voices.registry = self.registry
        self._emit(Event("game_switched", {"game": safe, "speakers": len(self.registry.names())}))
        return {"game": safe, "speakers": self.registry.to_dict(), "path": str(new_path)}

    def status(self) -> dict[str, Any]:
        qm = self.qwen_mgr.status()
        voices = self.voices.voice_options()
        voice_set = set(voices)
        stale = [
            {"speaker": spk.name, "voice": spk.voice}
            for spk in self.registry.all()
            if spk.voice and spk.voice not in voice_set
        ]
        imp = self.qwen_mgr.import_status()
        voice_used: dict[str, list[str]] = {}
        for spk in self.registry.all():
            if spk.voice:
                voice_used.setdefault(spk.voice, []).append(spk.name)
        return {
            "server": "running",
            "qwen": bool(qm["online"]),
            "qwen_mgr": qm,
            "voices": voices,
            "stale_mappings": stale,
            "voice_used_by": voice_used,
            "import_status": imp,
            "game": self.games.active(),
            "games": self.games.list_games(),
            "clipboard": self.clipboard.is_running() if self.clipboard else False,
            "queue_size": self.player.queue_size(),
            "current": str(self.player.current()) if self.player.current() else None,
            "speaker_count": len(self.registry.names()),
        }

    def _emit(self, event: Event) -> None:
        self._event_history.append(event)
        if len(self._event_history) > 200:
            self._event_history = self._event_history[-200:]

    def recent_events(self, limit: int = 100) -> list[dict[str, object]]:
        return [{"type": e.type, "payload": e.payload} for e in self._event_history[-limit:]]


_runtime: NovaApp | None = None


def get_runtime() -> NovaApp:
    if _runtime is None:
        raise RuntimeError("NovaTTS runtime not initialized")
    return _runtime


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _runtime
    _runtime = NovaApp()
    _runtime.start()
    try:
        yield
    finally:
        _runtime.stop()
        _runtime = None


app = FastAPI(title="NovaTTS", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1420", "http://127.0.0.1:1420", "tauri://localhost", "https://tauri.localhost"],
    allow_origin_regex=r"https://.*\.tauri\.local.*",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    rt = get_runtime()
    return {"status": "ok", "qwen": rt.qwen.is_available()}


@app.get("/games")
async def list_games() -> dict[str, Any]:
    rt = get_runtime()
    return {"active": rt.games.active(), "games": rt.games.list_games()}


@app.post("/games")
async def create_game(body: GameBody) -> dict[str, Any]:
    rt = get_runtime()
    name = rt.games.ensure_game(body.name)
    return {"game": name, "games": rt.games.list_games()}


@app.post("/games/active")
async def set_active_game(body: GameBody) -> dict[str, Any]:
    rt = get_runtime()
    if body.name.strip():
        rt.games.ensure_game(body.name)
    return rt.switch_game(body.name)


@app.get("/games/{name}/speakers")
async def game_speakers(name: str) -> dict[str, Any]:

    from .registry.speakers import SpeakerRegistry as _SR

    rt = get_runtime()
    reg = _SR(rt.games.speakers_path(name))
    return {"game": name, "speakers": reg.to_dict()}


@app.get("/blacklist")
async def get_blacklist() -> dict[str, Any]:
    rt = get_runtime()
    return rt.blacklist.to_dict()


@app.post("/blacklist")
async def set_blacklist(body: BlacklistBody) -> dict[str, Any]:
    rt = get_runtime()
    rt.blacklist.set(custom_words=body.custom_words, enabled_presets=body.enabled_presets)
    return rt.blacklist.to_dict()


@app.get("/emotions")
async def get_emotions() -> dict[str, Any]:
    return get_runtime().emotions.to_dict()


@app.post("/emotions/reload")
async def reload_emotions() -> dict[str, Any]:
    rt = get_runtime()
    rt.emotions.reload()
    return rt.emotions.to_dict()


@app.post("/emotions/alias")
async def add_emotion_alias(body: EmotionAliasBody) -> dict[str, Any]:
    import json

    rt = get_runtime()
    rt.emotions.aliases[body.expr.lower().strip()] = body.tag.lower().strip()
    from pathlib import Path as _P

    p = _P(rt.emotions.aliases_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rt.emotions.aliases, indent=2), encoding="utf-8")
    rt.emotions.reload()
    return rt.emotions.to_dict()


@app.delete("/emotions/alias/{expr}")
async def delete_emotion_alias(expr: str) -> dict[str, Any]:
    import json

    rt = get_runtime()
    key = expr.lower().strip()
    if key in rt.emotions.aliases:
        del rt.emotions.aliases[key]
        from pathlib import Path as _P

        p = _P(rt.emotions.aliases_file)
        p.write_text(json.dumps(rt.emotions.aliases, indent=2), encoding="utf-8")
        rt.emotions.reload()
    return rt.emotions.to_dict()


@app.get("/status")
async def status() -> dict[str, Any]:
    return get_runtime().status()


@app.get("/events")
async def events(limit: int = 100) -> list[dict[str, object]]:
    return get_runtime().recent_events(limit)


@app.post("/speak")
async def speak(body: SpeakBody) -> dict[str, Any]:
    return get_runtime().speak(
        SpeakRequest(
            text=body.text,
            speaker=body.speaker,
            instruct=body.instruct,
            emotion=body.emotion,
            voice=body.voice,
        )
    )


@app.get("/speakers")
async def list_speakers() -> dict[str, Any]:
    rt = get_runtime()
    data = rt.registry.to_dict()
    data["fallback"] = rt.registry.fallback_speaker
    return data


@app.post("/speakers")
async def create_speaker(body: SpeakerCreateBody) -> dict[str, Any]:
    rt = get_runtime()
    speaker = rt.registry.register(body.name)
    rt.registry.save()
    return speaker.to_dict()


@app.patch("/speakers/{name}")
async def update_speaker(name: str, body: SpeakerPatchBody) -> dict[str, Any]:
    rt = get_runtime()
    updated = rt.registry.update(name, voice=body.voice)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Speaker {name!r} not found")
    rt.registry.save()
    return updated.to_dict()


@app.delete("/speakers/{name}")
async def delete_speaker(name: str) -> dict[str, Any]:
    rt = get_runtime()
    removed = rt.registry.remove(name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Speaker {name!r} not found")
    rt.registry.save()
    return {"deleted": name}


@app.post("/speakers/{name}/rename")
async def rename_speaker(name: str, body: SpeakerRenameBody) -> dict[str, Any]:
    rt = get_runtime()
    renamed = rt.registry.rename(name, body.new_name)
    if renamed is None:
        raise HTTPException(status_code=400, detail=f"Cannot rename {name!r} to {body.new_name!r}")
    rt.registry.save()
    return renamed.to_dict()


@app.post("/speakers/{name}/alias")
async def alias_speaker(name: str, body: SpeakerAliasBody) -> dict[str, Any]:
    rt = get_runtime()
    spk = rt.registry.alias(name, body.alias)
    if spk is None:
        raise HTTPException(status_code=400, detail=f"Cannot alias {name!r} as {body.alias!r}")
    rt.registry.save()
    return spk.to_dict()


@app.post("/test-tts")
async def test_tts() -> dict[str, Any]:
    """Sanity check: synthesize a short line through the default voice."""
    rt = get_runtime()
    try:
        path = rt.voices.synthesize(
            Dialogue(speaker=None, text="Hello from NovaTTS.", source="api"),
            voice_override=None,
        )
        return {"status": "ok", "file": str(path), "size": path.stat().st_size}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Test TTS failed: {exc}") from exc


@app.get("/voices")
async def list_voices() -> dict[str, Any]:
    rt = get_runtime()
    return {"voices": rt.voices.voice_options(), "qwen_online": rt.qwen.is_available()}


@app.post("/voices")
async def clone_voice(body: VoiceCloneBody) -> dict[str, Any]:
    """Clone a voice on the Qwen engine from a base64 WAV sample."""
    import base64

    rt = get_runtime()
    if not rt.qwen.is_available():
        raise HTTPException(status_code=502, detail="Qwen engine is offline")
    try:
        raw = base64.b64decode(body.wav_b64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 payload") from exc
    rt.voices.register_voice(body.name, raw, ref_text=body.ref_text)
    return {"status": "ok", "voice": body.name, "bytes": len(raw)}


@app.delete("/voices/{name}")
async def delete_voice(name: str) -> dict[str, Any]:
    rt = get_runtime()
    if not rt.qwen.is_available():
        raise HTTPException(status_code=502, detail="Qwen engine is offline")
    try:
        rt.voices.delete_voice(name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "ok", "deleted": name}


@app.get("/qwen/status")
async def qwen_status() -> dict[str, Any]:
    return get_runtime().qwen_mgr.status()


@app.post("/qwen/start")
async def qwen_start() -> dict[str, Any]:
    rt = get_runtime()
    try:
        return rt.qwen_mgr.start()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/qwen/stop")
async def qwen_stop() -> dict[str, Any]:
    return get_runtime().qwen_mgr.stop()


@app.post("/qwen/import-samples")
async def qwen_import_samples() -> dict[str, Any]:
    rt = get_runtime()
    if not rt.qwen.is_available():
        raise HTTPException(status_code=502, detail="Qwen engine is offline")
    from pathlib import Path

    from .config import settings as _s
    from .tts.qwen import Qwen3Backend as _QB

    src = Path(_s.qwen_samples_dir)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Samples dir not found: {src}")
    qb = _QB()
    existing = set(qb.list_voices())
    wavs = sorted(src.glob("*.wav"), key=lambda p: p.name.lower())
    ok = 0
    skipped = 0
    failed: list[str] = []
    for wav in wavs:
        if wav.name == "output_quick_test.wav" or wav.stat().st_size > 5_000_000:
            skipped += 1
            continue
        name = wav.stem
        if name in existing:
            skipped += 1
            continue
        ref = wav.with_suffix(".txt")
        ref_text = ref.read_text(encoding="utf-8", errors="replace").strip() if ref.exists() else ""
        try:
            qb.register_voice(name, wav.read_bytes(), ref_text=ref_text)
            ok += 1
        except Exception as exc:
            failed.append(f"{name}: {exc}")
    return {"imported": ok, "skipped": skipped, "failed": failed, "total": len(wavs)}


@app.post("/shutdown")
async def shutdown() -> dict[str, Any]:
    import contextlib
    import os
    import threading

    def _exit() -> None:
        import time

        time.sleep(0.3)
        os._exit(0)

    rt = get_runtime()
    with contextlib.suppress(Exception):
        rt.qwen_mgr.stop()
    threading.Thread(target=_exit, daemon=True).start()
    return {"status": "shutting_down"}


@app.post("/voices/{name}/preview")
async def preview_voice(name: str, body: SpeakBody) -> dict[str, Any]:
    """Preview a voice without changing any speaker mapping."""
    from .text_clean import clean_emotion_text

    rt = get_runtime()
    text = clean_emotion_text(body.text.strip()) or "Hello from NovaTTS."
    try:
        path = rt.voices.synthesize(Dialogue(speaker=None, text=text, source="api"), voice_override=name)
        rt.player.enqueue_interrupt(path)
        return {"status": "ok", "voice": name, "file": path.name, "size": path.stat().st_size}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ----------------------------------------------------------------------
# Settings (paths configurable from GUI)
# ----------------------------------------------------------------------


_SETTINGS_ENV_MAP: dict[str, str] = {
    "qwen_bin": "NOVATTS_QWEN_BIN",
    "qwen_model": "NOVATTS_QWEN_MODEL",
    "qwen_codec": "NOVATTS_QWEN_CODEC",
    "qwen_url": "NOVATTS_QWEN_URL",
    "qwen_default_voice": "NOVATTS_QWEN_DEFAULT_VOICE",
    "qwen_samples_dir": "NOVATTS_QWEN_SAMPLES_DIR",
    "qwen_samples_dirs_extra": "NOVATTS_QWEN_SAMPLES_DIRS_EXTRA",
    "emotion_sounds_dir": "NOVATTS_EMOTION_SOUNDS_DIR",
    "qwen_timeout": "NOVATTS_QWEN_TIMEOUT",
    "qwen_extra_args": "NOVATTS_QWEN_EXTRA_ARGS",
    "poll_interval": "NOVATTS_POLL_INTERVAL",
}

_SETTINGS_FIELD_TYPES: dict[str, type[Any]] = {
    "qwen_timeout": float,
    "poll_interval": float,
}


def _settings_snapshot() -> dict[str, Any]:
    return {
        "qwen_bin": settings.qwen_bin,
        "qwen_model": settings.qwen_model,
        "qwen_codec": settings.qwen_codec,
        "qwen_url": settings.qwen_url,
        "qwen_default_voice": settings.qwen_default_voice,
        "qwen_samples_dir": settings.qwen_samples_dir,
        "qwen_samples_dirs_extra": settings.qwen_samples_dirs_extra,
        "emotion_sounds_dir": settings.emotion_sounds_dir,
        "qwen_timeout": settings.qwen_timeout,
        "qwen_extra_args": settings.qwen_extra_args,
        "poll_interval": settings.poll_interval,
        "qwen_autostart": settings.qwen_autostart,
        "qwen_auto_import_samples": settings.qwen_auto_import_samples,
    }


def _settings_path_status() -> dict[str, dict[str, Any]]:
    checks: dict[str, Path | str] = {
        "qwen_bin": Path(settings.qwen_bin) if settings.qwen_bin else Path(),
        "qwen_model": Path(settings.qwen_model) if settings.qwen_model else Path(),
        "qwen_codec": Path(settings.qwen_codec) if settings.qwen_codec else Path(),
        "qwen_samples_dir": Path(settings.qwen_samples_dir) if settings.qwen_samples_dir else Path(),
        "emotion_sounds_dir": Path(settings.emotion_sounds_dir) if settings.emotion_sounds_dir else Path(),
    }
    out: dict[str, dict[str, Any]] = {}
    for key, p in checks.items():
        if isinstance(p, Path) and str(p):
            out[key] = {"path": str(p), "exists": p.exists()}
        else:
            out[key] = {"path": str(p) if str(p) else "", "exists": False}
    return out


@app.get("/settings")
async def get_settings() -> dict[str, Any]:
    return {
        "settings": _settings_snapshot(),
        "path_status": _settings_path_status(),
        "env_file": str(Path(settings.qwen_bin).parent.parent / ".env") if settings.qwen_bin else str(Path(__file__).resolve().parent.parent / ".env"),
    }


@app.post("/settings")
async def update_settings(body: SettingsBody) -> dict[str, Any]:
    from .config import BACKEND_DIR

    env_path = BACKEND_DIR / ".env"
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"status": "noop", "settings": _settings_snapshot(), "path_status": _settings_path_status()}

    lines: list[str] = []
    if env_path.exists():
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []

    for field, value in updates.items():
        env_key = _SETTINGS_ENV_MAP.get(field)
        if env_key is None:
            continue
        str_val = str(value)
        cast = _SETTINGS_FIELD_TYPES.get(field)
        if cast is not None:
            try:
                typed: Any = cast(str_val)
                setattr(settings, field, typed)
            except Exception:
                setattr(settings, field, value)
        else:
            setattr(settings, field, str_val)
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(env_key + "=") or stripped.startswith(env_key + " "):
                lines[i] = f"{env_key}={str_val}"
                found = True
                break
        if not found:
            lines.append(f"{env_key}={str_val}")

    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write .env: {exc}") from exc

    return {"status": "saved", "settings": _settings_snapshot(), "path_status": _settings_path_status()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("novatts.main:app", host=settings.host, port=settings.port)
