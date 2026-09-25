"""HTTP surface for the Perfect Cut tool window.

Kept out of ``main.py`` on purpose: this is a standalone tool's API, and
``main.py`` is already the app's single endpoint surface. Registered from
``main.py`` with ``app.include_router(cutter_router)``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .cutter import (
    CutterConfig,
    export_cut,
    probe_tool,
    resolve_ffmpeg,
    resolve_whisper_exe,
    resolve_whisper_model,
)
from .cutter_batch import BatchJob, preflight

log = logging.getLogger(__name__)

router = APIRouter(prefix="/cutter", tags=["cutter"])

_job = BatchJob()
_config = CutterConfig.load()


def _cfg() -> CutterConfig:
    return _config


class ExportBody(BaseModel):
    src: str = Field(..., min_length=1)
    out: str = Field(..., min_length=1)
    start: float = 0.0
    end: float = 0.0
    mode: str = "qwen"
    """qwen (24 kHz mono + loudnorm) | native (24 kHz mono) | keep (original)."""


class ConfigBody(BaseModel):
    input_dir: str | None = None
    output_dir: str | None = None
    whisper_exe: str | None = None
    whisper_model: str | None = None
    ffmpeg: str | None = None
    lang: str | None = None
    qwen_preset: bool | None = None
    keep_sr: bool | None = None
    snap: bool | None = None


class BatchBody(BaseModel):
    input_dir: str = ""
    output_dir: str = ""
    whisper_exe: str = ""
    whisper_model: str = ""
    lang: str = "en"


@router.get("/config")
async def get_config() -> dict[str, Any]:
    return {"config": _cfg().to_dict()}


@router.post("/config")
async def set_config(body: ConfigBody) -> dict[str, Any]:
    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        setattr(_config, key, value)
    _config.save()
    return {"config": _cfg().to_dict()}


@router.get("/tools")
async def get_tools() -> dict[str, Any]:
    cfg = _cfg()
    return {
        "ffmpeg": cfg.ffmpeg,
        "whisper_exe": cfg.whisper_exe,
        "whisper_model": cfg.whisper_model,
        "ffmpeg_exists": Path(cfg.ffmpeg).is_file() if cfg.ffmpeg else False,
        "whisper_exe_exists": Path(cfg.whisper_exe).is_file() if cfg.whisper_exe else False,
        "whisper_model_exists": Path(cfg.whisper_model).is_file() if cfg.whisper_model else False,
    }


@router.post("/tools/auto")
async def auto_tools() -> dict[str, Any]:
    """Re-detect ffmpeg / whisper and persist whatever was found."""
    cfg = _cfg()
    cfg.ffmpeg = resolve_ffmpeg()
    cfg.whisper_exe = resolve_whisper_exe()
    cfg.whisper_model = resolve_whisper_model()
    cfg.save()
    return await get_tools()


@router.post("/tools/test")
async def test_tool(tool: str = "ffmpeg") -> dict[str, Any]:
    cfg = _cfg()
    target = {"ffmpeg": cfg.ffmpeg, "whisper_exe": cfg.whisper_exe}.get(tool, cfg.ffmpeg)
    args = ["-version"] if tool == "ffmpeg" else ["--help"]
    ok, message = probe_tool(target, args)
    return {"ok": ok, "tool": tool, "path": target, "message": message}


@router.post("/export")
async def export(body: ExportBody) -> dict[str, Any]:
    """Cut a selection out of a WAV via ffmpeg (stdlib cutter as fallback)."""
    try:
        return export_cut(
            src=body.src,
            out=body.out,
            start=body.start,
            end=body.end,
            mode=body.mode,
            ffmpeg=_cfg().ffmpeg,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("Perfect Cut export failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/batch/preflight")
async def batch_preflight(body: BatchBody) -> dict[str, Any]:
    ok, lines = preflight(body.input_dir, body.output_dir, body.whisper_exe, body.whisper_model)
    return {"ok": ok, "lines": lines}


@router.post("/batch/start")
async def batch_start(body: BatchBody) -> dict[str, Any]:
    ok, lines = preflight(body.input_dir, body.output_dir, body.whisper_exe, body.whisper_model)
    if not ok:
        raise HTTPException(status_code=400, detail="preflight failed")
    if not _job.start(
        input_dir=body.input_dir,
        output_dir=body.output_dir,
        whisper_exe=body.whisper_exe,
        whisper_model=body.whisper_model,
        lang=body.lang,
    ):
        raise HTTPException(status_code=409, detail="a batch is already running")
    return {"status": "started", "lines": lines}


@router.get("/batch/status")
async def batch_status() -> dict[str, Any]:
    return _job.status()


@router.post("/batch/stop")
async def batch_stop() -> dict[str, Any]:
    return {"stopping": _job.stop()}
