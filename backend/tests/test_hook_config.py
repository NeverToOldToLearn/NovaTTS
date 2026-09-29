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
from helpers import make_settings

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
    s = make_settings()
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
    assert make_settings().hook_mode == "websocket"
    assert make_settings(hook_mode="cliboard").hook_mode == "both"  # noqa: FBT003
    assert make_settings(hook_mode="").hook_mode == "both"


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
    assert make_settings(hook_mode=raw).hook_mode == raw


@pytest.mark.parametrize("raw", ["  WebSocket  ", "BOTH", "Clipboard"])
def test_hook_mode_is_case_and_whitespace_insensitive(raw: str) -> None:
    assert make_settings(hook_mode=raw).hook_mode == raw.strip().lower()


@pytest.mark.parametrize("raw", ["websockets", "ws", "", "luna", None, 42, True])
def test_bad_hook_mode_falls_back_to_both_instead_of_crashing(raw: object) -> None:
    """A typo in .env must not make the backend unstartable.

    Without the validator, pydantic raises a ValidationError at import time
    and NovaTTS dies with no server at all. B did the same fallback by hand;
    here the type does it.
    """
    assert make_settings(hook_mode=raw).hook_mode == "both"

# --- luna_ws_url validator (F14) --------------------------------------------
# Measured: this machine's backend/.env held
#   NOVATTS_LUNA_WS_URL=NOVATTS_LUNA_WS_URL=ws://127.0.0.1:6677
# A whole KEY=value line typed into a field that already carried the key.
# The consequence was not cosmetic: a non-empty luna_ws_url selects client
# mode, so a typo in one field silently stopped the hook from ever binding.


def test_a_pasted_assignment_prefix_is_repaired() -> None:
    assert make_settings(luna_ws_url="NOVATTS_LUNA_WS_URL=ws://127.0.0.1:6677").luna_ws_url == (
        "ws://127.0.0.1:6677"
    )


def test_a_repeated_assignment_prefix_is_repaired() -> None:
    """The measured value is doubled; a triple is the same paste twice more."""
    raw = "NOVATTS_LUNA_WS_URL=NOVATTS_LUNA_WS_URL=ws://127.0.0.1:6677"
    assert make_settings(luna_ws_url=raw).luna_ws_url == "ws://127.0.0.1:6677"


def test_a_prefix_only_value_becomes_server_mode() -> None:
    assert make_settings(luna_ws_url="NOVATTS_LUNA_WS_URL=").luna_ws_url == ""


def test_an_unusable_url_falls_back_to_server_mode_not_to_a_dead_end() -> None:
    """Same principle as D29, applied to the other mode switch.

    "websocket" is a typo that would leave the hook dialling nothing; the
    fallback has to be the route that needs nothing external, so it is ""
    -- server mode -- and not an error, because a ValidationError at import
    time takes the whole backend down.
    """
    for raw in ("localhost:6677", "http://127.0.0.1:6677", "6677", "ws:/127.0.0.1"):
        assert make_settings(luna_ws_url=raw).luna_ws_url == "", raw


@pytest.mark.parametrize("raw", ["ws://127.0.0.1:6677", "wss://hook.example/ws", "  ws://a  "])
def test_a_valid_url_is_kept(raw: str) -> None:
    assert make_settings(luna_ws_url=raw).luna_ws_url == raw.strip()


def test_a_url_with_a_query_string_is_not_mistaken_for_an_assignment() -> None:
    """The repair splits on "=", so it must not eat a legitimate "="."""
    raw = "ws://127.0.0.1:6677/?token=a=b"
    assert make_settings(luna_ws_url=raw).luna_ws_url == raw


@pytest.mark.parametrize("raw", [None, 42, True, b"ws://x"])
def test_a_non_string_url_becomes_server_mode(raw: object) -> None:
    assert make_settings(luna_ws_url=raw).luna_ws_url == ""


def test_the_wrong_field_name_is_not_stripped() -> None:
    """Only NOVATTS_LUNA_WS_URL is unwrapped.

    A different key means the value really is a typo rather than a paste,
    and stripping it would hide the mistake instead of reporting it.
    """
    assert make_settings(luna_ws_url="NOVATTS_HOOK_PORT=ws://127.0.0.1:6677").luna_ws_url == ""


# --- test isolation (F14) ---------------------------------------------------


def test_the_suite_does_not_see_the_developers_env() -> None:
    """The verdict belongs to the code, not to one desktop.

    Nine tests in test_luna_adapter.py failed on an untouched commit because
    this machine's .env held the doubled NOVATTS_LUNA_WS_URL above. Two
    tests in this file failed for the same reason via NOVATTS_HOOK_MODE.
    conftest pins the shared ``settings`` object for every test, so if this
    ever fails, that pinning stopped working -- which is a gate failure, not
    a test to be updated.
    """
    from novatts.config import settings

    assert settings.luna_ws_url == ""
    assert settings.hook_mode == "websocket"
    assert settings.hook_port == 6677


def test_the_isolation_actually_hides_an_ambient_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative case, so the positive case above is not vacuous (D43).

    This machine's .env proves the ambient value is real. If the fixture
    stopped working, the two assertions in the test above would pass for the
    wrong reason -- the .env no longer containing anything -- and nobody
    would notice until a developer's desktop broke the suite again.
    """
    from novatts.config import settings

    monkeypatch.setattr(settings, "luna_ws_url", "ws://127.0.0.1:9999", raising=False)
    assert settings.luna_ws_url == "ws://127.0.0.1:9999"
    # And the fixture puts it back for the next test, which is the other
    # half of "isolation": leaking would be just as wrong as not hiding.
    assert make_settings().luna_ws_url == ""


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
    assert getattr(make_settings(), field) == expected


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
