"""First-run setup must never propose paths from someone else's machine.

``/setup/defaults`` exists so the GUI can suggest the AI-Tools install that
ships with NovaTTS. It has to come from the *compiled* defaults, because a
stale ``.env`` (or a developer checkout) may still contain a path like
``E:\\LLM's\\...`` that does not exist for a new user.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from novatts.config import Settings, settings
from novatts.main import app

PATH_FIELDS = ("qwen_bin", "qwen_model", "qwen_codec", "qwen_codec_bin", "qwen_samples_dir")


def test_every_setup_path_field_is_reported() -> None:
    res = TestClient(app).get("/setup/defaults")
    assert res.status_code == 200
    body = res.json()
    assert set(body["paths"]) == set(PATH_FIELDS)
    for name, info in body["paths"].items():
        assert set(info) == {"suggested", "exists"}, name
        assert isinstance(info["suggested"], str)
        assert isinstance(info["exists"], bool)


def test_suggestions_ignore_the_live_env(monkeypatch) -> None:
    """A machine-specific path in the running config must not be suggested."""
    monkeypatch.setattr(settings, "qwen_bin", r"E:\LLM's\somebody-elses\tts-server.exe", raising=False)

    body = TestClient(app).get("/setup/defaults").json()
    assert body["paths"]["qwen_bin"]["suggested"] != settings.qwen_bin
    assert body["paths"]["qwen_bin"]["suggested"] == str(Settings.model_fields["qwen_bin"].default)


def test_compiled_defaults_are_not_developer_paths() -> None:
    for name in ("qwen_bin", "qwen_model", "qwen_codec"):
        default = str(Settings.model_fields[name].default)
        assert not default.lower().startswith("e:"), f"{name} still points at a drive letter"
        assert "!!scripts!!" not in default.lower()
        assert "\\projects\\qwentts" not in default.lower()


def test_env_file_is_absolute() -> None:
    body = TestClient(app).get("/setup/defaults").json()
    assert Path(body["env_file"]).is_absolute()
