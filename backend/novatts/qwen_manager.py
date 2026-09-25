"""Lifecycle for the local tts-server (qwentts.cpp) process."""

from __future__ import annotations

import logging
import shlex
import subprocess
import threading
import time
from pathlib import Path

import requests

from .config import settings

log = logging.getLogger(__name__)


def _port_from_url(url: str) -> int:
    try:
        return int(url.rstrip("/").rsplit(":", 1)[-1])
    except Exception:
        return 8080


class QwenManager:
    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._import_found: int = 0
        self._import_loaded: int = 0
        self._import_total: int = 0
        self._import_active: bool = False
        self._import_error: str | None = None

    def is_managed_running(self) -> bool:
        with self._lock:
            p = self._proc
            return p is not None and p.poll() is None

    def is_external_running(self) -> bool:
        try:
            r = requests.get(f"{settings.qwen_url.rstrip('/')}/health", timeout=2)
            return r.status_code == 200 and r.json().get("status") == "ok"
        except Exception:
            return False

    def import_status(self) -> dict[str, object]:
        src = Path(settings.qwen_samples_dir)
        wavs: list[Path] = []
        pairs = 0
        try:
            if src.exists():
                from .tts.spk_rvq import collect_wavs, voice_ref_for

                wavs = collect_wavs(src)
                pairs = sum(1 for w in wavs if voice_ref_for(w) is not None)
        except Exception:
            pass
        with self._lock:
            return {
                "found": len(wavs) or self._import_found,
                "pairs": pairs,
                "unpaired": max(len(wavs) - pairs, 0),
                "loaded": self._import_loaded,
                "total": self._import_total or len(wavs),
                "active": self._import_active,
                "error": self._import_error,
                "dir": str(src),
            }

    def status(self) -> dict[str, object]:
        managed = self.is_managed_running()
        external = self.is_external_running()
        with self._lock:
            pid: int | None = self._proc.pid if self._proc else None
            err = self._last_error
            bin_path = settings.qwen_bin
            model = settings.qwen_model
            codec = settings.qwen_codec
        imp = self.import_status()
        return {
            "qwen_url": settings.qwen_url,
            "managed_running": managed,
            "external_running": external,
            "online": managed or external,
            "pid": pid,
            "bin": bin_path,
            "model": model,
            "codec": codec,
            "bin_exists": Path(bin_path).exists() if bin_path else False,
            "model_exists": Path(model).exists() if model else False,
            "codec_exists": Path(codec).exists() if codec else False,
            "last_error": err,
            "import_status": imp,
        }

    def start(self) -> dict[str, object]:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return {"status": "already_running", "pid": self._proc.pid}
            self._last_error = None

        bin_path = settings.qwen_bin
        model = settings.qwen_model
        codec = settings.qwen_codec
        if not bin_path or not Path(bin_path).exists():
            msg = f"tts-server binary not found: {bin_path}"
            with self._lock:
                self._last_error = msg
            raise RuntimeError(msg)
        if not model or not Path(model).exists():
            msg = f"model not found: {model}"
            with self._lock:
                self._last_error = msg
            raise RuntimeError(msg)
        if not codec or not Path(codec).exists():
            msg = f"codec not found: {codec}"
            with self._lock:
                self._last_error = msg
            raise RuntimeError(msg)

        port = _port_from_url(settings.qwen_url)
        extra = shlex.split(settings.qwen_extra_args) if settings.qwen_extra_args.strip() else []
        cmd = [bin_path, "--model", model, "--codec", codec, "--host", "127.0.0.1", "--port", str(port)] + extra
        log.info("Starting tts-server: %s", " ".join(cmd))
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            raise

        with self._lock:
            self._proc = proc

        deadline = time.monotonic() + 25
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                msg = f"tts-server exited early (code {proc.returncode})"
                with self._lock:
                    self._last_error = msg
                    self._proc = None
                raise RuntimeError(msg)
            try:
                r = requests.get(f"{settings.qwen_url.rstrip('/')}/health", timeout=2)
                if r.status_code == 200 and r.json().get("status") == "ok":
                    self._auto_import_samples_bg()
                    return {"status": "started", "pid": proc.pid}
            except Exception as exc:
                last_exc = exc
            time.sleep(0.6)

        msg = f"tts-server did not become healthy in time: {last_exc}"
        with self._lock:
            self._last_error = msg
        raise RuntimeError(msg)

    def stop(self) -> dict[str, object]:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._proc = None
                return {"status": "not_running"}
        try:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=4)
        finally:
            with self._lock:
                self._proc = None
        return {"status": "stopped"}

    def maybe_autostart(self) -> None:
        if not settings.qwen_autostart:
            log.info("Qwen autostart disabled (NOVATTS_QWEN_AUTOSTART=0)")
            return
        if self.is_external_running() or self.is_managed_running():
            return
        log.info("Qwen autostart: launching tts-server in background...")
        t = threading.Thread(target=self._autostart_bg, name="qwen-autostart", daemon=True)
        t.start()

    def _autostart_bg(self) -> None:
        try:
            self.start()
            log.info("Qwen autostart: tts-server ready")
        except Exception as exc:
            log.warning("Qwen autostart failed: %s", exc)

    def _collect_candidates(self, src: Path) -> list[Path]:
        from .tts.spk_rvq import collect_wavs

        return collect_wavs(src)

    def _auto_import_samples(self) -> None:
        if not settings.qwen_auto_import_samples:
            return
        src = Path(settings.qwen_samples_dir)
        if not src.exists():
            return
        try:
            from .tts.qwen import Qwen3Backend
            from .tts.spk_rvq import register_sample

            backend = Qwen3Backend()
            existing = set(backend.list_voices())
            all_cands = self._collect_candidates(src)
            candidates = [w for w in all_cands if w.stem not in existing]
            with self._lock:
                self._import_found = len(all_cands)
                self._import_total = len(candidates)
                self._import_loaded = 0
                self._import_active = True
                self._import_error = None
            if not candidates:
                with self._lock:
                    self._import_active = False
                    self._import_loaded = len(existing)
                return
            log.info("Auto-import %d new voice(s) from %s", len(candidates), src)
            imported = 0
            failed = 0
            for idx, wav in enumerate(candidates, 1):
                # Pre-extracted .spk/.rvq pairs register verbatim (no GPU
                # work); wavs without a pair fall back to server-side
                # extraction via wav_b64.
                try:
                    register_sample(backend, wav)
                    imported += 1
                    with self._lock:
                        self._import_loaded = imported
                except Exception as exc:
                    failed += 1
                    log.warning("Auto-import voice %s failed: %s", wav.stem, exc)
                if idx % 25 == 0 or idx == len(candidates):
                    log.info("Auto-import progress %d/%d", idx, len(candidates))
                    time.sleep(0.05)
            with self._lock:
                self._import_active = False
            if imported:
                log.info("Auto-imported %d voice(s) (%d failed)", imported, failed)
        except Exception as exc:
            with self._lock:
                self._import_active = False
                self._import_error = str(exc)
            log.warning("Auto-import samples failed: %s", exc)

    def _auto_import_samples_bg(self) -> None:
        t = threading.Thread(target=self._auto_import_samples, name="qwen-autoimport", daemon=True)
        t.start()
