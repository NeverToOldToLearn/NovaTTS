"""Auto-forward exposes a second, selectable hotkey for capturing the window.

The toggle hotkey and the capture hotkey are independent bindings, so the
user can retarget auto-forward without leaving the game. This covers the
defaults, validation, the conflict flag and the capture callback.
"""

from __future__ import annotations

from novatts.auto_forward import HOTKEY_OPTIONS, AutoForward


def test_capture_hotkey_defaults_to_f11() -> None:
    af = AutoForward()
    assert af.status()["capture_hotkey"] == "F11"
    assert af.status()["capture_hotkey_conflict"] is False


def test_capture_hotkey_accepts_every_advertised_option() -> None:
    af = AutoForward()
    for name in HOTKEY_OPTIONS:
        if name == af.status()["hotkey"]:
            continue
        assert af.set_capture_hotkey(name.lower()) is True
        assert af.status()["capture_hotkey"] == name


def test_capture_hotkey_rejects_unknown_names() -> None:
    af = AutoForward()
    assert af.set_capture_hotkey("F9") is True
    assert af.set_capture_hotkey("NOT-A-KEY") is False
    assert af.status()["capture_hotkey"] == "F9"


def test_invalid_constructor_value_falls_back() -> None:
    af = AutoForward(capture_hotkey="bogus")
    assert af.status()["capture_hotkey"] == "F11"


def test_conflict_flag_when_both_hotkeys_match() -> None:
    af = AutoForward(hotkey="F9", capture_hotkey="F9")
    assert af.status()["capture_hotkey_conflict"] is True


def test_capture_hotkey_runs_the_capture_callback(monkeypatch) -> None:
    captured: list[str] = []
    af = AutoForward(on_capture=captured.append)
    monkeypatch.setattr(af, "capture_foreground", lambda: "My Game")
    af._handle_capture_hotkey()
    assert captured == ["My Game"]


def test_capture_hotkey_without_callback_still_captures(monkeypatch) -> None:
    af = AutoForward()

    def fake_capture() -> str:
        af.target = "renpy window"
        return "RenPy Window"

    monkeypatch.setattr(af, "capture_foreground", fake_capture)
    af._handle_capture_hotkey()
    assert af.target == "renpy window"
