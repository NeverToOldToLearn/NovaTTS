"""NovaTTS FastAPI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .adapters import ClipboardAdapter, InputAdapter
from .adapters.file_monitor import FileMonitorAdapter
from .adapters.luna import LunaAdapter
from .blacklist import Blacklist
from .config import settings
from .cutter_api import router as cutter_router
from .emotions import EmotionSounds
from .games import GameManager
from .gate import DialogueGate
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
    qwen_codec_bin: str | None = None
    emotion_sounds_dir: str | None = None
    qwen_timeout: float | None = None
    qwen_extra_args: str | None = None
    poll_interval: float | None = None
    # Hook input (LunaHook/Textractor).
    hook_mode: str | None = None
    """One of: clipboard, websocket, both. Unrecognised values fall back
    to "both" via the Settings validator, not via an HTTP 422."""
    hook_port: int | None = None
    hook_space_form: bool | None = None
    hook_dual_hook: bool | None = None
    luna_ws_url: str | None = None
    file_watch: bool | None = None
    file_watch_path: str | None = None
    dedup_window_ms: int | None = None
    # hook_host is intentionally absent: it is the websocket bind address,
    # and changing it live would need the server restarted to take effect.


class OpenAISpeechBody(BaseModel):
    """OpenAI-compatible /v1/audio/speech request."""

    model: str = Field(..., min_length=1)
    """Model identifier (nova-fast, nova-balanced, nova-expressive)."""
    input: str = Field(..., min_length=1, max_length=4096)
    """Text to synthesize."""
    voice: str = Field(..., min_length=1)
    """Voice name."""
    response_format: str = "mp3"
    """Output format: mp3, opus, aac, flac, wav, pcm."""
    speed: float = 1.0
    """Playback speed (0.25–4.0)."""
    instructions: str = ""
    """Voice design instructions."""


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
        self.gate = DialogueGate(
            registry=self.registry,
            blacklist=self.blacklist,
            dedup_window_ms=settings.dedup_window_ms,
        )
        self.player.on_finished = lambda _p: None  # reserved for event emit
        self.clipboard: ClipboardAdapter | None = None
        self.luna: LunaAdapter | None = None
        self.filemon: FileMonitorAdapter | None = None
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
        self._start_adapters()
        log.info(
            "NovaTTS started (qwen_online=%s, hook_mode=%s)",
            self.qwen.is_available(),
            settings.hook_mode,
        )

    def _start_adapters(self) -> None:
        """Start the raw_text sources enabled by ``settings.hook_mode``.

        ``clipboard`` is the RenPy route, ``websocket`` the LunaHook route,
        and ``both`` -- the default -- runs them side by side so the hook
        can be proven against a route that already works.

        The mode is read once, here. Switching it later takes a restart:
        the websocket cannot be re-bound without dropping LunaTranslator's
        connection, and a restart the user is told about is better than a
        silently dropped hook mid-scene.
        """
        mode = settings.hook_mode
        if mode in ("clipboard", "both"):
            self.clipboard = ClipboardAdapter(on_dialogue=self.on_dialogue)
        else:
            log.info("hook_mode=%r: RenPy clipboard adapter not started", mode)
        if mode in ("websocket", "both"):
            self.luna = LunaAdapter(on_dialogue=self.on_dialogue)
        else:
            log.info("hook_mode=%r: LunaHook websocket adapter not started", mode)
        # The file route is not part of hook_mode: it is not a source the
        # user picks *between*, it is the last resort for when the other
        # two cannot run at all. Its own flag keeps it off unless asked for.
        if settings.file_watch:
            self.filemon = FileMonitorAdapter(on_dialogue=self.on_dialogue)
        else:
            log.info("NOVATTS_FILE_WATCH is off: file adapter not started")
        # Names before threads. Every adapter parses inside a worker that is
        # already polling when start() returns, and the known-name set is
        # what lets a parser trust a speaker it would otherwise reject or
        # guess. Priming after start would leave a window where the first
        # line of the session is misread -- and "the first line is wrong" is
        # the hardest kind of bug to reproduce.
        self._refresh_known_speakers()
        for adapter in self._adapters():
            adapter.start()

    def _adapters(self) -> tuple[InputAdapter, ...]:
        """Every configured raw_text source, in lifecycle order.

        Read from one place on purpose. Three call sites need the list --
        priming, starting and stopping -- and when the hook route was added
        it was missed by two of the three (F4). A tuple built from the
        attributes means a new route cannot half-exist.
        """
        return tuple(
            adapter
            for adapter in (self.clipboard, self.luna, self.filemon)
            if adapter is not None
        )

    def _refresh_known_speakers(self) -> None:
        """Re-prime every running adapter with the current registry.

        Every adapter must hold the same name set, because the parser
        trusts a registered name over all of its heuristics. An adapter
        left holding a stale set keeps guessing names the user has already
        assigned.

        That is not a rare corner for the hook route: the trust gate
        deliberately refuses to persist a guessed name, so registering
        the name by hand is the remedy it asks for. If that registration
        does not reach the adapter, the fix the gate points at does
        nothing.

        One place, so the next adapter added cannot be missed in three.
        """
        names = self.registry.names()
        for adapter in self._adapters():
            adapter.set_known_speakers(names)

    def stop(self) -> None:
        # Adapters first, and before the worker and the backend. A luna
        # dispatch thread can be inside on_dialogue, and stopping the
        # synthesis backend under it turns a clean shutdown into a pile of
        # errors from work that no longer matters. Each adapter joins its
        # own threads, so this also guarantees nothing new arrives after.
        self._running = False
        for adapter in self._adapters():
            adapter.stop()
        with suppress(Exception):
            self._wake.set()
        if self._worker:
            with suppress(Exception):
                self._worker.join(timeout=2.0)
            self._worker = None
        self.player.stop()
        with suppress(Exception):
            self.qwen_mgr.stop()
        with suppress(Exception):
            # Ephemeral audio cache: discard on clean shutdown so it can't
            # grow unboundedly across sessions.
            self.voices.clear_cache()
        with suppress(Exception):
            # Ephemeral raw clipboard log: same policy — nothing persists.
            if self.clipboard:
                self.clipboard.raw_log.clear()
        self.gate.forget()
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
                    path = self.voices.synthesize(self._segment_dialogue(dialogue, seg))
                    paths.append(path)
                except Exception as exc:
                    log.error("Synthesis failed: %s", exc)
                    self._emit(Event("error", {"source": dialogue.source, "error": str(exc)}))
            ep = self.emotions.resolve_path(tag)
            if ep is not None:
                paths.append(ep)
            last = pos
        seg2 = text[last:].strip()
        if seg2:
            try:
                path2 = self.voices.synthesize(self._segment_dialogue(dialogue, seg2))
                paths.append(path2)
            except Exception as exc:
                log.error("Synthesis failed: %s", exc)
                self._emit(Event("error", {"source": dialogue.source, "error": str(exc)}))
        if not paths and cleaned.strip():
            try:
                paths.append(self.voices.synthesize(dialogue))
            except Exception as exc:
                log.error("Synthesis failed: %s", exc)
                self._emit(Event("error", {"source": dialogue.source, "error": str(exc)}))
        return paths

    @staticmethod
    def _segment_dialogue(dialogue: Dialogue, text: str) -> Dialogue:
        """One emotion-delimited segment of ``dialogue``.

        A segment differs from its parent only in the text it speaks.
        ``raw`` and ``speaker_is_guess`` describe the source line, not the
        segment, so they must survive the split -- and a hand rebuild is
        exactly where each of them was dropped once. ``replace`` copies
        every field, so the next field added to Dialogue is carried too.
        """
        return replace(dialogue, text=text)

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
                self._emit(Event("error", {"source": dialogue.source, "error": str(exc)}))
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

    def on_dialogue(self, dialogue: Dialogue) -> None:
        """Accept a line from any adapter, or report why it was refused.

        This is the single entry point shared by the clipboard, websocket
        and (F5) file-watch routes, so everything that decides whether a
        line speaks lives behind it. The decisions themselves are in
        :class:`~novatts.gate.DialogueGate`; what stays here is the part
        that is genuinely about *this* app: emitting events, and handing
        the line to the dialogue worker, which is still the only path to
        synthesis.
        """
        admission = self.gate.admit(dialogue)
        if not admission.accepted:
            self._emit(
                Event(
                    "filtered",
                    {
                        "reason": admission.reason,
                        "source": dialogue.source,
                        "speaker": dialogue.speaker,
                        "text": (dialogue.raw or dialogue.text)[:120],
                    },
                )
            )
            return
        line = admission.dialogue
        if line is None:
            return
        if admission.new_speaker:
            with suppress(Exception):
                self.registry.save()
            self._emit(Event("speaker_discovered", {"speaker": line.speaker, "source": line.source}))
        elif admission.guess_only:
            # The name is our inference, so it is not persisted -- but the
            # user should be able to see that the guess happened, because
            # otherwise the only evidence is a voice that sounds wrong.
            self._emit(
                Event(
                    "speaker_guessed",
                    {"speaker": line.speaker, "source": line.source, "text": line.text[:80]},
                )
            )
        voice = self.registry.lookup_voice(line.speaker) if line.speaker else ""
        if line.speaker and not voice:
            self._emit(
                Event(
                    "unassigned_speaker",
                    {"speaker": line.speaker, "source": line.source, "text": line.text[:80]},
                )
            )
        self._emit(
            Event(
                "dialogue",
                {
                    "speaker": line.speaker,
                    "text": line.text[:120],
                    "source": line.source,
                    "new": admission.new_speaker,
                    "guess": line.speaker_is_guess,
                },
            )
        )
        with self._pending_lock:
            self._pending_seq += 1
            self._pending_dialogue = line
        with suppress(Exception):
            self.player.stop_current()
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
        self._refresh_known_speakers()
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
            "hook_mode": settings.hook_mode,
            "hook_clients": self.luna.client_count if self.luna else 0,
            "hook_dropped": self.luna.dropped if self.luna else 0,
            # D9: the last raw line the hook delivered, before parsing.
            # "Nothing is arriving" and "it arrives and is misparsed" look
            # identical from every other field here, and this is the only
            # one that tells them apart.
            "hook_last_raw": self.luna.last_raw if self.luna else "",
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
app.include_router(cutter_router)
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
    rt._refresh_known_speakers()
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
    from .tts.spk_rvq import collect_pairs, collect_wavs, register_pair, register_sample

    src = Path(_s.qwen_samples_dir)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Samples dir not found: {src}")
    qb = _QB()
    existing = set(qb.list_voices())
    # Pairs register verbatim even when the source .wav is gone; wavs
    # without a pair fall back to server-side extraction.
    pairs = [ref for ref in collect_pairs(src) if ref.name not in existing]
    wavs = [w for w in collect_wavs(src) if w.stem not in existing]
    ok = 0
    failed: list[str] = []
    for ref in pairs:
        try:
            register_pair(qb, ref)
            ok += 1
        except Exception as exc:
            failed.append(f"{ref.name}: {exc}")
    for wav in wavs:
        try:
            register_sample(qb, wav)
            ok += 1
        except Exception as exc:
            failed.append(f"{wav.stem}: {exc}")
    return {
        "imported": ok,
        "pairs": len(pairs),
        "wavs": len(wavs),
        "failed": failed,
        "total": len(pairs) + len(wavs),
    }


@app.post("/qwen/convert-samples")
async def qwen_convert_samples(force: bool = False) -> dict[str, Any]:
    """Pre-extract .spk/.rvq voice references for the samples dir.

    Runs qwen-codec.exe for every wav that lacks a complete pair (or all
    wavs with ``?force=1``). Registration at the next engine start then
    uploads the latents verbatim instead of re-extracting them on the GPU.
    """
    from .tts.spk_rvq import convert_samples_dir

    src = Path(settings.qwen_samples_dir)
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Samples dir not found: {src}")
    summary = convert_samples_dir(src, force=force)
    summary["dir"] = str(src)
    if summary["errors"]:
        log.warning("qwen/convert-samples errors: %s", summary["errors"])
    summary["import_status"] = get_runtime().qwen_mgr.import_status()
    return summary


@app.post("/shutdown")
async def shutdown() -> dict[str, Any]:
    import contextlib
    import os
    import threading
    import time

    rt = get_runtime()

    def _graceful() -> None:
        # Events/worker teardown + cache clear, then hard-exit.
        # (This ran in a worker thread and called asyncio.get_event_loop(),
        #  which raises "no current event loop in thread" on py>=3.12, so
        #  os._exit never fired and the process stayed alive after the GUI
        #  closed. Teardown first, a short grace period so the HTTP response
        #  can flush, then os._exit guarantees the process dies.)
        with contextlib.suppress(Exception):
            rt.qwen_mgr.stop()
        if rt._running:
            rt.stop()
        time.sleep(0.3)
        os._exit(0)

    threading.Thread(target=_graceful, daemon=True).start()
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


@app.post("/clipboard-log/open")
async def open_clipboard_log() -> dict[str, Any]:
    """Open the raw clipboard log file in the OS default viewer."""
    import os
    import subprocess
    import sys

    rt = get_runtime()
    if not rt.clipboard:
        return {"status": "noop", "path": ""}
    log_path = rt.clipboard.raw_log.path
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"No clipboard log yet at {log_path}")
    try:
        if sys.platform == "win32":
            os.startfile(str(log_path))  # type: ignore[attr-defined, unused-ignore]
        else:
            subprocess.Popen(["xdg-open", str(log_path)])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to open log: {exc}") from exc
    return {"status": "ok", "path": str(log_path)}


@app.post("/clipboard-log/clear")
async def clear_clipboard_log() -> dict[str, Any]:
    """Delete the raw clipboard log (GUI action, no server shutdown needed)."""
    rt = get_runtime()
    if not rt.clipboard:
        return {"status": "noop"}
    rt.clipboard.raw_log.clear()
    return {"status": "cleared"}


# ----------------------------------------------------------------------
# OpenAI-compatible TTS endpoint (for Open-WebUI integration)
# ----------------------------------------------------------------------

# Model→profiel mapping: model name → (emotion, instruct_hint)
_OPENAI_MODEL_PROFILES = {
    "nova-fast": {"emotion": "neutral", "instruct": ""},
    "nova-balanced": {"emotion": "neutral", "instruct": "Speak naturally and clearly."},
    "nova-expressive": {"emotion": "default", "instruct": "Speak with emotion and expression."},
}


def _resolve_openai_profile(model: str) -> dict[str, str]:
    """Map OpenAI model name to emotion/instruct profile."""
    profile = _OPENAI_MODEL_PROFILES.get(model.lower(), _OPENAI_MODEL_PROFILES["nova-balanced"])
    return profile


@app.post("/v1/audio/speech")
async def openai_speech(body: OpenAISpeechBody) -> Any:
    """OpenAI-compatible text-to-speech endpoint.

    Accepts the same request format as OpenAI's /v1/audio/speech API.
    Returns audio data in the requested format (mp3, opus, aac, flac, wav, pcm).

    Example:
        POST /v1/audio/speech
        {
            "model": "nova-balanced",
            "input": "Hello, world!",
            "voice": "default",
            "response_format": "mp3"
        }
    """
    from fastapi.responses import StreamingResponse

    from .audio_convert import convert_audio, get_mime_type

    rt = get_runtime()

    # Validate text length
    text = body.input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="input cannot be empty")
    if len(text) > 4096:
        raise HTTPException(status_code=400, detail="input exceeds 4096 characters")

    # Validate response format
    format_name = body.response_format.lower().strip()
    supported_formats = ["mp3", "opus", "aac", "flac", "wav", "pcm"]
    if format_name not in supported_formats:
        raise HTTPException(
            status_code=400,
            detail=f"response_format '{format_name}' not supported. Supported: {', '.join(supported_formats)}",
        )

    # Validate speed
    if not 0.25 <= body.speed <= 4.0:
        raise HTTPException(status_code=400, detail="speed must be between 0.25 and 4.0")

    # Resolve model profile (emotion, instruct hint)
    profile = _resolve_openai_profile(body.model)
    instruct = body.instructions or profile["instruct"]

    # Synthesize
    try:
        dialogue = Dialogue(
            speaker=None,
            text=text,
            source="openai-api",
            instruct=instruct,
        )
        # Synthesize with the voice override
        path = rt.voices.synthesize(dialogue, voice_override=body.voice)
    except Exception as exc:
        log.error("OpenAI TTS synthesis failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Synthesis failed: {exc}") from exc

    # Convert to requested format if not WAV
    try:
        audio_data = path.read_bytes() if format_name == "wav" else convert_audio(path, format_name)
    except Exception as exc:
        log.error("Audio format conversion failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Format conversion failed: {exc}") from exc

    # Return audio stream
    mime_type = get_mime_type(format_name)
    return StreamingResponse(
        iter([audio_data]),
        media_type=mime_type,
        headers={"Content-Disposition": f"attachment; filename=speech.{format_name}"},
    )


# ----------------------------------------------------------------------
# Settings (paths configurable from GUI)
# ----------------------------------------------------------------------


_SETTINGS_ENV_MAP: dict[str, str] = {
    "qwen_bin": "NOVATTS_QWEN_BIN",
    "qwen_model": "NOVATTS_QWEN_MODEL",
    "qwen_codec": "NOVATTS_QWEN_CODEC",
    "qwen_codec_bin": "NOVATTS_QWEN_CODEC_BIN",
    "qwen_url": "NOVATTS_QWEN_URL",
    "qwen_default_voice": "NOVATTS_QWEN_DEFAULT_VOICE",
    "qwen_samples_dir": "NOVATTS_QWEN_SAMPLES_DIR",
    "qwen_samples_dirs_extra": "NOVATTS_QWEN_SAMPLES_DIRS_EXTRA",
    "emotion_sounds_dir": "NOVATTS_EMOTION_SOUNDS_DIR",
    "qwen_timeout": "NOVATTS_QWEN_TIMEOUT",
    "qwen_extra_args": "NOVATTS_QWEN_EXTRA_ARGS",
    "poll_interval": "NOVATTS_POLL_INTERVAL",
    "hook_mode": "NOVATTS_HOOK_MODE",
    "hook_port": "NOVATTS_HOOK_PORT",
    "hook_space_form": "NOVATTS_HOOK_SPACE_FORM",
    "hook_dual_hook": "NOVATTS_HOOK_DUAL_HOOK",
    "luna_ws_url": "NOVATTS_LUNA_WS_URL",
    "file_watch": "NOVATTS_FILE_WATCH",
    "file_watch_path": "NOVATTS_FILE_WATCH_PATH",
    "dedup_window_ms": "NOVATTS_DEDUP_WINDOW_MS",
}


def _env_bool(value: Any) -> bool:
    """Coerce a GUI/.env value to bool.

    The obvious `bool(value)` is a trap here: `bool("False")` is True, so
    toggling a boolean off through /settings would store the string
    "False", which is truthy, and the setting would appear to ignore the
    user. Nothing in the current field set is a bool, which is why this
    has never bitten before -- the hook booleans are the first.
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


_SETTINGS_FIELD_TYPES: dict[str, Callable[[Any], Any]] = {
    "qwen_timeout": float,
    "poll_interval": float,
    "hook_port": int,
    "dedup_window_ms": int,
    "hook_space_form": _env_bool,
    "hook_dual_hook": _env_bool,
    "file_watch": _env_bool,
}


def _settings_snapshot() -> dict[str, Any]:
    return {
        "qwen_bin": settings.qwen_bin,
        "qwen_model": settings.qwen_model,
        "qwen_codec": settings.qwen_codec,
        "qwen_codec_bin": settings.qwen_codec_bin,
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
        # Hook input. hook_host is read-only here (see SettingsBody).
        "hook_mode": settings.hook_mode,
        "hook_host": settings.hook_host,
        "hook_port": settings.hook_port,
        "hook_space_form": settings.hook_space_form,
        "hook_dual_hook": settings.hook_dual_hook,
        "luna_ws_url": settings.luna_ws_url,
        "file_watch": settings.file_watch,
        "file_watch_path": settings.file_watch_path,
        "dedup_window_ms": settings.dedup_window_ms,
    }


def _settings_path_status() -> dict[str, dict[str, Any]]:
    from .tts.spk_rvq import codec_bin_path

    checks: dict[str, Path | str] = {
        "qwen_bin": Path(settings.qwen_bin) if settings.qwen_bin else Path(),
        "qwen_model": Path(settings.qwen_model) if settings.qwen_model else Path(),
        "qwen_codec": Path(settings.qwen_codec) if settings.qwen_codec else Path(),
        "qwen_codec_bin": codec_bin_path() if settings.qwen_bin else Path(),
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

    from novatts.logconf import setup_logging

    setup_logging()
    uvicorn.run("novatts.main:app", host=settings.host, port=settings.port)
