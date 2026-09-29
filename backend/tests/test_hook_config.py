"""Tests for the hook-input configuration added in F1.

These cover the two pieces of *new logic* F1 introduced, as opposed to new
declarations. Everything else in F1 is a field with a default, which the
value assertions below pin down and which nothing else can silently break.

The bool coercion is worth a test of its own: `bool("False")` is `True` in
Python, so the obvious implementation of the /settings bool path would have
stored the string "False" -- truthy -- and every boolean toggle in the GUI
would have appeared to ignore the user.
"""

from __future__ import annotations

import pytest

from novatts.config import Settings
from novatts.main import _SETTINGS_ENV_MAP, _env_bool, _settings_snapshot
from novatts.models import Dialogue

HOOK_FIELDS = (
    "hook_mode",
    "hook_host",
    "hook_port",
    "hook_space_form",
    "hook_dual_hook",
    "luna_ws_url",
    "file_watch",
    "file_watch_path",
    "dedup_window_ms",
)


# --- defaults ---------------------------------------------------------------


def test_hook_defaults_match_the_agreed_topology() -> None:
    s = Settings()
    # D2: the cutover happened in F8. "websocket" is now the primary source,
    # which is what "replace RenPy" meant. RenPy survives as an explicit
    # choice and as "both" -- so this is a changed primary, not a deletion.
    assert s.hook_mode == "websocket"
    # NovaTTS serves the websocket; LunaTranslator connects to it. Loopback
    # only -- 0.0.0.0 here would expose raw game text to the network.
    assert s.hook_host == "127.0.0.1"
    assert s.hook_port == 6677
    assert s.hook_space_form is True
    assert s.hook_dual_hook is False
    assert s.luna_ws_url == ""
    assert s.file_watch is False
    assert s.file_watch_path == "textractor_output.txt"
    assert s.dedup_window_ms == 500


def test_the_default_is_websocket_but_a_broken_value_still_falls_back_to_both() -> None:
    """The default and the fallback are deliberately DIFFERENT (D29).

    Worth its own test because the instinct is to keep the two in sync: they
    answer different questions. The default is "what should a fresh install
    use", and the answer is the route that is actually better. The fallback is
    "what should happen when this setting is unreadable", and the answer is
    the route that breaks least -- which is "both", because it still delivers
    text if one source is dead. Syncing them would mean a typo in .env
    silently removes the source the user was relying on.
    """
    assert Settings().hook_mode == "websocket"
    assert Settings(hook_mode="cliboard").hook_mode == "both"  # noqa: FBT003
    assert Settings(hook_mode="").hook_mode == "both"


def test_hook_fields_are_exposed_in_the_settings_snapshot() -> None:
    """The GUI reads /settings; a field missing here is invisible in the UI."""
    snapshot = _settings_snapshot()
    for field in HOOK_FIELDS:
        assert field in snapshot, f"{field} missing from _settings_snapshot()"


def test_every_writable_hook_field_has_an_env_mapping() -> None:
    """A field in SettingsBody but not in _SETTINGS_ENV_MAP is silently dropped
    by update_settings -- the POST returns "saved" and nothing changes."""
    for field, env_key in _SETTINGS_ENV_MAP.items():
        if field.startswith("hook_") or field.startswith("file_watch") or field.startswith("dedup_"):
            assert env_key.startswith("NOVATTS_"), f"{field} -> {env_key} breaks the prefix convention"


# --- hook_mode validator ----------------------------------------------------


@pytest.mark.parametrize("raw", ["clipboard", "websocket", "both"])
def test_valid_hook_modes_pass_through(raw: str) -> None:
    assert Settings(hook_mode=raw).hook_mode == raw


@pytest.mark.parametrize("raw", ["  WebSocket  ", "BOTH", "Clipboard"])
def test_hook_mode_is_case_and_whitespace_insensitive(raw: str) -> None:
    assert Settings(hook_mode=raw).hook_mode == raw.strip().lower()


@pytest.mark.parametrize("raw", ["websockets", "ws", "", "luna", None, 42, True])
def test_bad_hook_mode_falls_back_to_both_instead_of_crashing(raw: object) -> None:
    """A typo in .env must not make the backend unstartable.

    Without the validator, pydantic raises a ValidationError at import time
    and NovaTTS dies with no server at all. B did the same fallback by hand;
    here the type does it.
    """
    assert Settings(hook_mode=raw).hook_mode == "both"


# --- env plumbing -----------------------------------------------------------


@pytest.mark.parametrize(
    ("env_key", "env_value", "field", "expected"),
    [
        ("NOVATTS_HOOK_MODE", "websocket", "hook_mode", "websocket"),
        ("NOVATTS_HOOK_HOST", "127.0.0.2", "hook_host", "127.0.0.2"),
        ("NOVATTS_HOOK_PORT", "7777", "hook_port", 7777),
        ("NOVATTS_HOOK_SPACE_FORM", "false", "hook_space_form", False),
        ("NOVATTS_HOOK_DUAL_HOOK", "1", "hook_dual_hook", True),
        ("NOVATTS_LUNA_WS_URL", "ws://127.0.0.1:6678", "luna_ws_url", "ws://127.0.0.1:6678"),
        ("NOVATTS_FILE_WATCH", "yes", "file_watch", True),
        ("NOVATTS_FILE_WATCH_PATH", "/tmp/out.txt", "file_watch_path", "/tmp/out.txt"),
        ("NOVATTS_DEDUP_WINDOW_MS", "1500", "dedup_window_ms", 1500),
    ],
)
def test_hook_env_vars_are_read(
    env_key: str, env_value: str, field: str, expected: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(env_key, env_value)
    assert getattr(Settings(), field) == expected


# --- bool coercion ----------------------------------------------------------


@pytest.mark.parametrize("raw", ["false", "False", "FALSE", "0", "no", "off", "", "  off  ", False])
def test_env_bool_reads_falsey_values(raw: object) -> None:
    assert _env_bool(raw) is False


@pytest.mark.parametrize("raw", ["true", "True", "1", "yes", "on", True])
def test_env_bool_reads_truthy_values(raw: object) -> None:
    assert _env_bool(raw) is True


@pytest.mark.parametrize("raw", ["false", "False", "0", "no", "off"])
def test_env_bool_disagrees_with_builtin_bool(raw: str) -> None:
    """Document exactly why _env_bool exists.

    If a future edit replaces the call sites with the builtin, this test
    still passes -- but the ones above start failing, which is the point.
    """
    assert bool(raw) is True
    assert _env_bool(raw) is False


# --- Dialogue.raw -----------------------------------------------------------


def test_dialogue_raw_defaults_to_empty() -> None:
    assert Dialogue(speaker=None, text="Hello.").raw == ""


def test_dialogue_raw_is_kept_verbatim() -> None:
    d = Dialogue(speaker="Rick", text="It's 2 parts.", source="luna", raw="Rick It's 2 parts.")
    assert d.raw == "Rick It's 2 parts."
    # raw is forensic only: it must not leak into the spoken text.
    assert d.text == "It's 2 parts."


def test_dialogue_keeps_its_existing_default_source() -> None:
    """D1: RenPy stays a valid source and the default until the F8 cutover.

    Changing this default would silently relabel every existing RenPy
    capture in the logs.
    """
    assert Dialogue(speaker=None, text="x").source == "renpy"
    assert Dialogue(speaker=None, text="x", source="luna").source == "luna"
