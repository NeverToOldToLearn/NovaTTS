"""Perfect Cut — batch clean + transcribe job (formerly VoiceClonePrep-TTS).

For every ``*.wav`` in the input dir (skipping ``*_clean``) this runs

1. ``ffmpeg -af silenceremove=…,loudnorm -ar 24000 -ac 1 -c:a pcm_s16le`` into a
   temp dir, then
2. ``whisper-cli -m <model> -f <clean.wav> -l <lang> -otxt``,

and moves the pair into the output dir as ``<stem>.wav`` + ``<stem>.txt``.

The job runs on a daemon thread; the tool window polls ``/cutter/batch/status``
so progress survives the window being reopened.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .cutter import BATCH_CLEAN_FILTER, QWEN_SAMPLE_RATE, export_cut, resolve_ffmpeg
from .cutter_segments import DEFAULT_MAX_SEG, DEFAULT_MIN_SEG, plan_segments, read_mono_float

log = logging.getLogger(__name__)

WHISPER_TIMEOUT_S = 300
FFMPEG_TIMEOUT_S = 120
# Cap the in-memory log so a long batch can't grow it without bound.
MAX_LOG_LINES = 400


@dataclass
class BatchResult:
    total: int = 0
    index: int = 0
    name: str = ""
    ok: int = 0
    fail: int = 0
    running: bool = False
    stop_requested: bool = False
    finished: bool = False
    lines: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        pct = int((self.index / self.total) * 100) if self.total else 0
        return {
            "total": self.total,
            "index": self.index,
            "name": self.name,
            "ok": self.ok,
            "fail": self.fail,
            "pct": pct,
            "running": self.running,
            "stop_requested": self.stop_requested,
            "finished": self.finished,
            "lines": list(self.lines[-MAX_LOG_LINES:]),
        }


def collect_inputs(input_dir: Path) -> list[Path]:
    """WAVs to process: top level, excluding the ``*_clean`` intermediates."""
    return [p for p in sorted(input_dir.glob("*.wav"), key=lambda p: p.name.lower()) if "_clean" not in p.name]


def preflight(
    input_dir: str,
    output_dir: str,
    whisper_exe: str,
    whisper_model: str,
    *,
    split: bool = True,
    min_seg: float = DEFAULT_MIN_SEG,
    max_seg: float = DEFAULT_MAX_SEG,
) -> tuple[bool, list[str]]:
    """Validate every path the batch needs. Returns (ok, human-readable log)."""
    lines: list[str] = []
    ok = True

    src = Path(input_dir) if input_dir else None
    if src is None or not src.is_dir():
        lines.append(f"✗ input dir not found: {input_dir or '(empty)'}")
        ok = False
    else:
        wavs = collect_inputs(src)
        lines.append(f"📂 {src} → {len(wavs)} wav(s) (excluding *_clean)")
        if not wavs:
            lines.append("⚠ no wav files in the input dir")
    if not output_dir:
        lines.append("✗ output dir is empty")
        ok = False

    exe = Path(whisper_exe) if whisper_exe else None
    if exe is None or not exe.is_file():
        lines.append(f"✗ whisper-cli not found: {whisper_exe or '(empty)'}")
        ok = False
    else:
        lines.append(f"✓ whisper: {exe}")

    model = Path(whisper_model) if whisper_model else None
    if model is None or not model.is_file():
        lines.append(f"✗ whisper model not found: {whisper_model or '(empty)'}")
        ok = False
    else:
        lines.append(f"✓ model: {model}")

    ffmpeg = resolve_ffmpeg()
    if not Path(ffmpeg).is_file():
        lines.append(f"✗ ffmpeg not found: {ffmpeg}")
        ok = False
    else:
        try:
            subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=10, check=True)
            lines.append(f"✓ ffmpeg: {ffmpeg}")
        except (OSError, subprocess.SubprocessError) as exc:
            lines.append(f"✗ ffmpeg unusable ({ffmpeg}): {exc}")
            ok = False

    if split:
        lines.append(f"✂ utterance split on ({min_seg:.1f}–{max_seg:.1f}s, shorts merged)")
    else:
        lines.append("▬ whole files (utterance split off)")

    lines.append("— preflight OK —" if ok else "⛔ fix the errors above before starting")
    return ok, lines


class _AbortBatch(Exception):
    """Internal control flow: a tool went missing — stop the whole batch."""


class BatchJob:
    """Single-flight batch runner. ``start`` returns False if one is live."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = BatchResult()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- control --------------------------------------------------------

    @property
    def running(self) -> bool:
        with self._lock:
            return self._state.running

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._state.snapshot()

    def start(
        self,
        *,
        input_dir: str,
        output_dir: str,
        whisper_exe: str,
        whisper_model: str,
        lang: str,
        split: bool = True,
        min_seg: float = DEFAULT_MIN_SEG,
        max_seg: float = DEFAULT_MAX_SEG,
    ) -> bool:
        with self._lock:
            if self._state.running:
                return False
            self._stop.clear()
            self._state = BatchResult(running=True)
        # Nonsense ranges must not produce nonsense segments.
        min_seg = max(0.5, float(min_seg or DEFAULT_MIN_SEG))
        max_seg = max(min_seg, float(max_seg or DEFAULT_MAX_SEG))
        self._thread = threading.Thread(
            target=self._run,
            kwargs={
                "input_dir": input_dir,
                "output_dir": output_dir,
                "whisper_exe": whisper_exe,
                "whisper_model": whisper_model,
                "lang": lang or "en",
                "split": bool(split),
                "min_seg": min_seg,
                "max_seg": max_seg,
            },
            name="cutter-batch",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> bool:
        """Request a stop. The current file still finishes."""
        with self._lock:
            if not self._state.running:
                return False
            self._stop.set()
        self._log("⏹ stop requested — finishing the current file…")
        return True

    # -- worker ---------------------------------------------------------

    def _log(self, msg: str) -> None:
        with self._lock:
            self._state.lines.append(msg)
            if len(self._state.lines) > MAX_LOG_LINES * 2:
                del self._state.lines[:MAX_LOG_LINES]
        log.info("cutter batch: %s", msg)

    def _progress(self, index: int, name: str) -> None:
        with self._lock:
            self._state.index = index
            self._state.name = name

    def _plan_file(
        self,
        clean: Path,
        stem: str,
        *,
        split: bool,
        min_seg: float,
        max_seg: float,
    ) -> list[tuple[float, float]]:
        """Utterance spans for one cleaned file (whole-file fallback, never empty)."""
        with wave.open(str(clean), "rb") as w:
            n, rate = w.getnframes(), w.getframerate() or 1
        duration = n / rate
        if not split:
            return [(0.0, duration)]
        try:
            samples, sr = read_mono_float(clean)
        except Exception as exc:
            self._log(f"⚠ {stem}: unreadable cleaned audio ({exc}) — whole file")
            return [(0.0, duration)]
        try:
            return plan_segments(samples, sr, min_seg=min_seg, max_seg=max_seg)
        except Exception as exc:
            self._log(f"⚠ {stem}: segmentation failed ({exc}) — whole file")
            return [(0.0, duration)]

    @staticmethod
    def _clean_duration(clean: Path) -> float:
        with wave.open(str(clean), "rb") as w:
            return w.getnframes() / (w.getframerate() or 1)

    def _transcribe_and_store(
        self,
        *,
        clean_src: Path,
        seg_stem: str,
        tmpdir: Path,
        out_dir: Path,
        whisper_exe: str,
        whisper_model: str,
        lang: str,
    ) -> bool:
        """Whisper-transcribe one (possibly cut) cleaned file, move the pair out."""
        try:
            subprocess.run(
                [whisper_exe, "-m", whisper_model, "-f", str(clean_src), "-l", lang,
                 "-otxt", "-of", str(tmpdir / seg_stem)],
                capture_output=True, text=True, timeout=WHISPER_TIMEOUT_S, check=True,
            )
        except FileNotFoundError:
            self._log("✗ whisper-cli not found — aborting.")
            raise _AbortBatch from None
        except subprocess.TimeoutExpired:
            self._log(f"✗ whisper timeout ({WHISPER_TIMEOUT_S}s) on {seg_stem}")
            return False
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or "")[-300:]
            self._log(f"✗ whisper failed on {seg_stem}: {err}")
            return False

        txt = next(
            (p for p in (
                tmpdir / f"{seg_stem}.txt",
                tmpdir / f"{seg_stem}_clean.wav.txt",
                tmpdir / f"{seg_stem}_clean.txt",
            ) if p.is_file()),
            None,
        )
        if txt is None:
            self._log(f"⚠ no transcript produced for {seg_stem}")
            return False

        try:
            shutil.move(str(clean_src), str(out_dir / f"{seg_stem}.wav"))
            shutil.move(str(txt), str(out_dir / f"{seg_stem}.txt"))
        except OSError as exc:
            self._log(f"✗ could not move results for {seg_stem}: {exc}")
            return False
        return True

    def _run(
        self,
        *,
        input_dir: str,
        output_dir: str,
        whisper_exe: str,
        whisper_model: str,
        lang: str,
        split: bool,
        min_seg: float,
        max_seg: float,
    ) -> None:
        out_dir = Path(output_dir)
        ffmpeg = resolve_ffmpeg()
        files = collect_inputs(Path(input_dir))
        skipped_note = f", lang={lang}"

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._log(f"✗ cannot create output dir: {exc}")
            self._finish()
            return

        with self._lock:
            self._state.total = len(files)
        self._log(f"🚀 batch start: {len(files)} file(s){skipped_note} → {out_dir}")
        if not files:
            self._log("— nothing to do —")
            self._finish()
            return

        with tempfile.TemporaryDirectory(prefix="novatts-cut-") as tmp:
            tmpdir = Path(tmp)
            aborted = False
            for idx, wav in enumerate(files, start=1):
                if self._stop.is_set():
                    self._log("⏹ stopped by user.")
                    break
                stem = wav.stem
                self._progress(idx, stem)
                clean = tmpdir / f"{stem}_clean.wav"

                self._log(f"[{idx}/{len(files)}] cleaning {stem}…")
                try:
                    subprocess.run(
                        [
                            ffmpeg, "-y", "-i", str(wav),
                            "-af", BATCH_CLEAN_FILTER,
                            "-ar", str(QWEN_SAMPLE_RATE), "-ac", "1",
                            "-c:a", "pcm_s16le", str(clean),
                        ],
                        capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_S, check=True,
                    )
                except FileNotFoundError:
                    self._log("✗ ffmpeg not found — aborting.")
                    break
                except subprocess.TimeoutExpired:
                    self._log(f"✗ ffmpeg timeout ({FFMPEG_TIMEOUT_S}s) on {stem}")
                    self._bump(fail=True)
                    continue
                except subprocess.CalledProcessError as exc:
                    self._log(f"✗ ffmpeg failed on {stem}: {(exc.stderr or '')[-300:]}")
                    self._bump(fail=True)
                    continue

                segments = self._plan_file(clean, stem, split=split, min_seg=min_seg, max_seg=max_seg)
                dur = self._clean_duration(clean)
                multi = len(segments) > 1
                if multi:
                    lens = ", ".join(f"{e - s:.1f}s" for s, e in segments)
                    self._log(f"✂ {stem} → {len(segments)} segments ({lens})")
                file_ok = True
                try:
                    for k, (s, e) in enumerate(segments):
                        if self._stop.is_set():
                            self._log("⏹ stopped by user.")
                            aborted = True
                            break
                        seg_stem = f"{stem}_{k + 1:03d}" if multi else stem
                        seg_clean = clean
                        if multi or s > 0.005 or e < dur - 0.005:
                            seg_clean = tmpdir / f"{seg_stem}_clean.wav"
                            self._log(f"[{idx}/{len(files)}] cutting {seg_stem} ({e - s:.1f}s)…")
                            try:
                                export_cut(
                                    src=str(clean), out=str(seg_clean),
                                    start=s, end=e, mode="native", ffmpeg=ffmpeg,
                                )
                            except Exception as exc:
                                self._log(f"✗ cut failed on {seg_stem}: {exc}")
                                file_ok = False
                                continue
                        self._log(f"[{idx}/{len(files)}] transcribing {seg_stem}…")
                        if not self._transcribe_and_store(
                            clean_src=seg_clean, seg_stem=seg_stem, tmpdir=tmpdir,
                            out_dir=out_dir, whisper_exe=whisper_exe,
                            whisper_model=whisper_model, lang=lang,
                        ):
                            file_ok = False
                except _AbortBatch:
                    break
                if aborted:
                    break
                if file_ok:
                    self._log(f"✓ {stem}")
                self._bump(fail=not file_ok)

        with self._lock:
            ok, fail, total = self._state.ok, self._state.fail, self._state.total
        self._log(f"🏁 done — ✓ {ok}  ✗ {fail}  of {total} → {out_dir}")
        if fail == 0 and ok > 0:
            self._log("🚀 all clear")
        self._finish()

    def _bump(self, *, fail: bool = False) -> None:
        with self._lock:
            if fail:
                self._state.fail += 1
            else:
                self._state.ok += 1

    def _finish(self) -> None:
        with self._lock:
            self._state.running = False
            self._state.finished = True
            self._state.stop_requested = self._stop.is_set()
        self._thread = None
