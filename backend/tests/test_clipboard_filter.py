"""Raw-line blacklist vs. the parser: don't rewrite a line the parser nails.

A VN that keeps day/time HUD on the clipboard sends captures like
``0: 45: DAY 1: Tuesday 14 - Morning: 0: CAS: ...``. The parser skips the
junk segments and finds CAS, but the raw-mode blacklist used to run first
and delete the digits, turning ``DAY 1:`` into ``DAY :`` -- a perfectly
valid speaker that then swallowed the real line.
"""

from __future__ import annotations

from novatts.adapters.clipboard import ClipboardAdapter
from novatts.blacklist import Blacklist

USER_PRESETS = ["Digits (0-9)", "Days of Week", "Time of Day"]

HUD = "0: 45: DAY 1: Tuesday 14 - Morning: 0:"


def _adapter(tmp_path, monkeypatch) -> ClipboardAdapter:
    monkeypatch.setattr("novatts.config.settings.blacklist_file", tmp_path / "blacklist.json", raising=False)
    monkeypatch.setattr("novatts.config.settings.clipboard_raw_log", tmp_path / "clipboard_raw.log", raising=False)
    monkeypatch.setattr("novatts.config.settings.log_raw_clipboard", False, raising=False)
    bl = Blacklist()
    bl.set(custom_words=[], enabled_presets=USER_PRESETS)
    return ClipboardAdapter(on_dialogue=lambda dialogue: None, blacklist=bl)


def test_parseable_hud_line_is_left_for_the_parser(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, monkeypatch)
    raw = f"{HUD} CAS: Look for strange behaviors."
    assert adapter._apply_blacklist(raw) == raw
    dialogue = adapter.parser.parse(adapter._apply_blacklist(raw))
    assert dialogue.speaker == "CAS"
    assert dialogue.text == "Look for strange behaviors."


def test_parseable_hud_line_with_jon(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, monkeypatch)
    raw = f"{HUD} Jon: That's vague, to say the least..."
    dialogue = adapter.parser.parse(adapter._apply_blacklist(raw))
    assert dialogue.speaker == "Jon"
    assert dialogue.text == "That's vague, to say the least..."


def test_hud_only_line_does_not_invent_a_day_speaker(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path, monkeypatch)
    filtered = adapter._apply_blacklist("DAY 1: Gallery")
    assert filtered == "Gallery"
    assert adapter.parser.parse(filtered).speaker is None
