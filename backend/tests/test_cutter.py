"""Tests for the Perfect Cut backend (config, tool resolution, export, batch preflight)."""

import array
import json
import math
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from novatts import cutter
from novatts.cutter import (
    CutterConfig,
    _downmix_mono,
    _linear_resample,
    _wav_fallback_cut,
    export_cut,
    probe_tool,
)
from novatts.cutter_batch import BatchJob, collect_inputs, preflight


def make_stereo_wav(path: Path, *, seconds: float = 2.0, rate: int = 44100) -> Path:
    """A 440 Hz left / 880 Hz right 16-bit stereo tone."""
    n = int(rate * seconds)
    samples = array.array("h")
    for i in range(n):
        samples.append(int(20000 * math.sin(2 * math.pi * 440 * i / rate)))
        samples.append(int(12000 * math.sin(2 * math.pi * 880 * i / rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


def read_info(path: Path) -> tuple[int, int, float]:
    with wave.open(str(path), "rb") as w:
        return w.getframerate(), w.getnchannels(), w.getnframes() / w.getframerate()


# --- export -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "rate", "channels"),
    [("qwen", 24000, 1), ("native", 24000, 1), ("keep", 44100, 2)],
)
def test_export_cut_modes(tmp_path, mode, rate, channels):
    src = make_stereo_wav(tmp_path / "tone.wav")
    out = tmp_path / f"cut_{mode}.wav"
    result = export_cut(src=str(src), out=str(out), start=0.5, end=1.25, mode=mode)
    assert result["duration"] == pytest.approx(0.75, abs=0.01)
    assert (read_info(out)[0], read_info(out)[1]) == (rate, channels)


def test_export_cut_creates_parent_dirs(tmp_path):
    src = make_stereo_wav(tmp_path / "tone.wav")
    out = tmp_path / "deep" / "nested" / "cut.wav"
    export_cut(src=str(src), out=str(out), start=0.0, end=0.5, mode="keep")
    assert out.is_file()


def test_export_cut_falls_back_to_stdlib(tmp_path):
    """No ffmpeg at that path — the stdlib cutter must still produce the cut."""
    src = make_stereo_wav(tmp_path / "tone.wav")
    out = tmp_path / "cut.wav"
    result = export_cut(src=str(src), out=str(out), start=0.5, end=1.25, mode="qwen", ffmpeg="C:/nope/ffmpeg.exe")
    assert result["via"] == "stdlib"
    assert result["duration"] == pytest.approx(0.75, abs=0.01)
    assert (read_info(out)[0], read_info(out)[1]) == (24000, 1)


def test_export_cut_rejects_bad_input(tmp_path):
    src = make_stereo_wav(tmp_path / "tone.wav")
    with pytest.raises(ValueError):
        export_cut(src=str(src), out=str(tmp_path / "o.wav"), start=1.0, end=0.5)
    with pytest.raises(FileNotFoundError):
        export_cut(src=str(tmp_path / "gone.wav"), out=str(tmp_path / "o.wav"), start=0.0, end=0.5)
    with pytest.raises(ValueError):
        export_cut(src=str(src), out=str(tmp_path / "o.wav"), start=0.0, end=0.5, mode="bogus")


def test_export_cut_clamps_to_file_bounds(tmp_path):
    src = make_stereo_wav(tmp_path / "tone.wav", seconds=1.0)
    out = tmp_path / "cut.wav"
    result = export_cut(src=str(src), out=str(out), start=0.5, end=99.0, mode="keep")
    assert result["duration"] == pytest.approx(0.5, abs=0.01)


# --- stdlib helpers ---------------------------------------------------------


def test_downmix_mono_averages_channels():
    stereo = array.array("h", [100, 300, -200, 200, 400, 0])
    assert _downmix_mono(stereo, 2).tolist() == [200, 0, 200]


def test_downmix_mono_saturates_instead_of_wrapping():
    stereo = array.array("h", [32767, 32767, -32768, -32768])
    assert _downmix_mono(stereo, 2).tolist() == [32767, -32768]


def test_linear_resample_changes_length():
    src = array.array("h", [0, 100, 200, 300])
    # int(n * dst/src): 4*24000/44100 -> 2, 4*44100/24000 -> 7
    assert len(_linear_resample(src, 44100, 24000)) == 2
    assert len(_linear_resample(src, 24000, 44100)) == 7


def test_linear_resample_is_identity_at_same_rate():
    src = array.array("h", [1, 2, 3, 4])
    assert _linear_resample(src, 24000, 24000) is src


def test_wav_fallback_keep_mode_preserves_channels(tmp_path):
    src = make_stereo_wav(tmp_path / "tone.wav")
    out = tmp_path / "cut.wav"
    _wav_fallback_cut(src, out, 0.1, 0.6, "keep")
    assert (read_info(out)[0], read_info(out)[1]) == (44100, 2)


# --- tool resolution --------------------------------------------------------


def test_first_existing_prefers_disk_over_path(monkeypatch, tmp_path):
    exe = tmp_path / "ffmpeg.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(cutter.shutil, "which", lambda _n: r"C:\somewhere\else\ffmpeg.exe")
    assert cutter._first_existing([str(exe)], "ffmpeg") == str(exe)


def test_first_existing_falls_back_to_which(monkeypatch):
    monkeypatch.setattr(cutter.shutil, "which", lambda _n: r"C:\path\ffmpeg.exe")
    assert cutter._first_existing([r"C:\missing\ffmpeg.exe"], "ffmpeg") == r"C:\path\ffmpeg.exe"


def test_first_existing_returns_last_when_nothing_found(monkeypatch):
    monkeypatch.setattr(cutter.shutil, "which", lambda _n: None)
    assert cutter._first_existing([r"C:\a\ffmpeg.exe", r"C:\b\ffmpeg.exe"], "ffmpeg") == r"C:\b\ffmpeg.exe"


def test_probe_tool_missing_binary():
    ok, message = probe_tool("C:/nope/ffmpeg.exe", ["-version"])
    assert ok is False
    assert "not found" in message


def test_probe_tool_reports_version(tmp_path):
    fake = tmp_path / "ffmpeg.exe"
    fake.write_bytes(b"MZ")
    ok, message = probe_tool(str(fake), ["-version"])
    # A non-executable stub exits non-zero on Windows; either way we get a message.
    assert isinstance(ok, bool)
    assert message


# --- config -----------------------------------------------------------------


def test_config_load_fills_missing_paths(tmp_path, monkeypatch):
    path = tmp_path / "perfect_cut.json"
    path.write_text(json.dumps({"input_dir": "D:/in", "lang": "nl"}), encoding="utf-8")
    monkeypatch.setattr(cutter.settings, "perfect_cut_config", path)
    cfg = CutterConfig.load()
    assert cfg.input_dir == "D:/in"
    assert cfg.lang == "nl"
    # Never set in the file — auto-detected instead.
    assert cfg.ffmpeg
    assert cfg.whisper_exe
    assert cfg.whisper_model


def test_config_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "perfect_cut.json"
    monkeypatch.setattr(cutter.settings, "perfect_cut_config", path)
    cfg = CutterConfig(input_dir="D:/a", output_dir="E:/b", lang="de", snap=True)
    cfg.save()
    assert json.loads(path.read_text(encoding="utf-8"))["input_dir"] == "D:/a"
    assert CutterConfig.load().lang == "de"
    assert CutterConfig.load().snap is True


def test_config_keeps_unknown_keys(tmp_path, monkeypatch):
    path = tmp_path / "perfect_cut.json"
    path.write_text(json.dumps({"input_dir": "D:/in", "future_flag": True}), encoding="utf-8")
    monkeypatch.setattr(cutter.settings, "perfect_cut_config", path)
    cfg = CutterConfig.load()
    assert cfg.extras == {"future_flag": True}
    cfg.save()
    assert json.loads(path.read_text(encoding="utf-8"))["future_flag"] is True


def test_config_survives_corrupt_file(tmp_path, monkeypatch):
    path = tmp_path / "perfect_cut.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(cutter.settings, "perfect_cut_config", path)
    assert CutterConfig.load().input_dir == ""


# --- batch ------------------------------------------------------------------


def test_collect_inputs_skips_clean_intermediates(tmp_path):
    for name in ("a.wav", "b.wav", "b_clean.wav", "notes.txt"):
        (tmp_path / name).write_bytes(b"RIFF")
    assert [p.name for p in collect_inputs(tmp_path)] == ["a.wav", "b.wav"]


def test_preflight_reports_missing_paths(tmp_path):
    ok, lines = preflight(
        str(tmp_path / "nope"), "", "", "",
    )
    assert ok is False
    joined = "\n".join(lines)
    assert "input dir not found" in joined
    assert "output dir is empty" in joined
    assert "whisper-cli not found" in joined
    assert "whisper model not found" in joined


def test_preflight_counts_wavs(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"RIFF")
    (tmp_path / "a_clean.wav").write_bytes(b"RIFF")
    _, lines = preflight(str(tmp_path), str(tmp_path), "", "")
    assert any("1 wav(s)" in line for line in lines)


def test_preflight_ok_when_everything_present(tmp_path, monkeypatch):
    for name in ("ffmpeg.exe", "whisper-cli.exe", "model.bin"):
        (tmp_path / name).write_bytes(b"MZ")
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr("novatts.cutter_batch.resolve_ffmpeg", lambda: str(tmp_path / "ffmpeg.exe"))
    monkeypatch.setattr("novatts.cutter_batch.subprocess.run", lambda *a, **k: _Completed())
    ok, lines = preflight(
        str(tmp_path), str(tmp_path),
        str(tmp_path / "whisper-cli.exe"), str(tmp_path / "model.bin"),
    )
    assert ok is True
    assert "— preflight OK —" in lines


class _Completed:
    returncode = 0
    stdout = "ffmpeg version 7.0"
    stderr = ""


# --- HTTP layer -------------------------------------------------------------
#
# The tool window talks to /cutter/* and nothing else, so the wire contract is
# the part worth pinning down. These build a bare app around the router instead
# of importing novatts.main, so no TTS runtime is started and the module-level
# singletons are swapped for isolated ones.


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from fastapi import FastAPI

    from novatts import cutter_api

    cfg_path = tmp_path / "perfect_cut.json"
    monkeypatch.setattr(cutter.settings, "perfect_cut_config", cfg_path)
    # CutterConfig reads/writes `settings.perfect_cut_config`, so redirecting
    # that is what isolates it; the singletons then need replacing too.
    monkeypatch.setattr(cutter_api, "_config", CutterConfig.load())
    monkeypatch.setattr(cutter_api, "_job", BatchJob())
    app = FastAPI()
    app.include_router(cutter_api.router)
    return TestClient(app)


def test_api_config_returns_every_field_the_ui_binds(client: TestClient) -> None:
    """`CutterConfig` in TS is hand-written — a new key must break a test."""
    body = client.get("/cutter/config").json()
    assert set(body["config"]) == {
        "input_dir",
        "output_dir",
        "whisper_exe",
        "whisper_model",
        "ffmpeg",
        "lang",
        "qwen_preset",
        "keep_sr",
        "snap",
    }


def test_api_config_post_merges_and_persists(client: TestClient, tmp_path: Path) -> None:
    r = client.post("/cutter/config", json={"input_dir": str(tmp_path / "in")})
    assert r.status_code == 200
    assert r.json()["config"]["input_dir"] == str(tmp_path / "in")
    # Untouched keys survive the round-trip.
    assert r.json()["config"]["lang"] == "en"
    assert json.loads((tmp_path / "perfect_cut.json").read_text(encoding="utf-8"))["input_dir"]


def test_api_config_post_ignores_nulls(client: TestClient) -> None:
    """The debounced save sends a whole patch; nulls must not clear values."""
    client.post("/cutter/config", json={"output_dir": "D:/out"})
    r = client.post("/cutter/config", json={"input_dir": None, "output_dir": "D:/other"})
    assert r.json()["config"]["output_dir"] == "D:/other"


def test_api_config_post_rejects_empty_string_paths(client: TestClient) -> None:
    """min_length=1 on the export body; config paths are plain strings."""
    r = client.post("/cutter/config", json={"input_dir": ""})
    assert r.status_code == 200
    assert r.json()["config"]["input_dir"] == ""


def test_api_tools_reports_existence_flags(client: TestClient, tmp_path: Path) -> None:
    body = client.get("/cutter/tools").json()
    assert set(body) == {
        "ffmpeg",
        "whisper_exe",
        "whisper_model",
        "ffmpeg_exists",
        "whisper_exe_exists",
        "whisper_model_exists",
    }
    assert all(isinstance(body[k], bool) for k in body if k.endswith("_exists"))


def test_api_tools_existence_tracks_the_configured_path(
    client: TestClient, tmp_path: Path
) -> None:
    """Auto-detection finds real tools on the dev machine, so pin the path."""
    missing = str(tmp_path / "definitely-not-ffmpeg.exe")
    client.post("/cutter/config", json={"ffmpeg": missing})
    body = client.get("/cutter/tools").json()
    assert body["ffmpeg"] == missing
    assert body["ffmpeg_exists"] is False


def test_api_tools_test_reports_a_missing_binary(client: TestClient, tmp_path: Path) -> None:
    missing = str(tmp_path / "nope.exe")
    client.post("/cutter/config", json={"ffmpeg": missing})
    r = client.post("/cutter/tools/test?tool=ffmpeg")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["tool"] == "ffmpeg"
    assert body["path"] == missing
    assert body["message"]  # something the status bar can show


def test_api_export_cuts_a_real_file(client: TestClient, tmp_path: Path) -> None:
    src = make_stereo_wav(tmp_path / "src.wav", seconds=2.0)
    out = tmp_path / "nested" / "cut.wav"
    r = client.post(
        "/cutter/export",
        json={"src": str(src), "out": str(out), "start": 0.25, "end": 1.0, "mode": "native"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["via"] in {"ffmpeg", "stdlib"}
    rate, channels, duration = read_info(out)
    assert (rate, channels) == (24000, 1)
    assert duration == pytest.approx(0.75, abs=0.02)


def test_api_export_missing_source_is_a_400_with_a_readable_detail(
    client: TestClient, tmp_path: Path
) -> None:
    r = client.post(
        "/cutter/export",
        json={
            "src": str(tmp_path / "nope.wav"),
            "out": str(tmp_path / "cut.wav"),
            "start": 0.0,
            "end": 1.0,
            "mode": "qwen",
        },
    )
    assert r.status_code == 400
    # The UI shows `detail` verbatim in the status bar.
    assert "nope.wav" in r.json()["detail"]


def test_api_export_rejects_an_empty_src(client: TestClient) -> None:
    r = client.post("/cutter/export", json={"src": "", "out": "x.wav", "start": 0, "end": 1})
    assert r.status_code == 422


def test_api_batch_preflight_lists_problems(client: TestClient, tmp_path: Path) -> None:
    r = client.post(
        "/cutter/batch/preflight",
        json={
            "input_dir": str(tmp_path / "missing"),
            "output_dir": "",
            "whisper_exe": "",
            "whisper_model": "",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert len(r.json()["lines"]) >= 4


def test_api_batch_start_refuses_when_preflight_fails(client: TestClient) -> None:
    r = client.post(
        "/cutter/batch/start",
        json={"input_dir": "", "output_dir": "", "whisper_exe": "", "whisper_model": ""},
    )
    assert r.status_code == 400


def test_api_batch_status_is_idle_and_stop_is_a_noop(client: TestClient) -> None:
    """Polling runs for the whole life of the tab, so idle must not error."""
    body = client.get("/cutter/batch/status").json()
    assert body["running"] is False
    assert body["finished"] is False
    assert body["lines"] == []
    assert client.post("/cutter/batch/stop").json() == {"stopping": False}


def test_api_batch_start_conflicts_when_one_is_already_running(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Single-flight: a second Start must 409 rather than run twice."""
    from novatts import cutter_api

    monkeypatch.setattr(cutter_api, "preflight", lambda *_a, **_k: (True, ["ok"]))
    monkeypatch.setattr(cutter_api, "_job", _AlwaysRunningJob())
    r = client.post(
        "/cutter/batch/start",
        json={"input_dir": "a", "output_dir": "b", "whisper_exe": "c", "whisper_model": "d"},
    )
    assert r.status_code == 409


class _AlwaysRunningJob:
    """Stands in for a live BatchJob so no real thread is started."""

    def start(self, **_kwargs: object) -> bool:
        return False

    def stop(self) -> bool:
        return True

    def status(self) -> dict[str, object]:
        return {"running": True, "lines": []}

