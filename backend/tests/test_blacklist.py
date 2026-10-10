"""Tests for the blacklist filter, in both spoken-body and raw-line modes."""

import json

import pytest

from novatts.blacklist import Blacklist, is_renpy_exception


@pytest.fixture
def bl(tmp_path, monkeypatch):
    monkeypatch.setattr("novatts.config.settings.blacklist_file", tmp_path / "blacklist.json", raising=False)
    return Blacklist()


def _custom(bl: Blacklist, *words: str) -> None:
    bl.set(custom_words=list(words), enabled_presets=[])


# -- raw pre-parse mode ------------------------------------------------------


def test_raw_mode_strips_hud_in_front_of_a_speaker(bl):
    _custom(bl, "250 $")
    assert bl.filter_text("250 $: Thoughts: I have to go.", preserve_prefix=False) == "Thoughts: I have to go."


def test_raw_mode_drops_a_fully_blacklisted_line(bl):
    _custom(bl, "250 $")
    assert bl.filter_text("250 $", preserve_prefix=False) == ""


def test_raw_mode_keeps_the_speaker_anchor_colon(bl):
    _custom(bl, "250 $")
    out = bl.filter_text("250 $: Rick: Move it!", preserve_prefix=False)
    assert out == "Rick: Move it!"


def test_raw_mode_strips_a_blacklisted_name_label(bl):
    _custom(bl, "Settings")
    assert bl.filter_text("Settings: Choose a slot", preserve_prefix=False) == "Choose a slot"


def test_raw_mode_keeps_a_protected_speaker_name(bl):
    # "Save" is both a custom word and a registered speaker: with the
    # prefix protected the name survives and still resolves to a voice.
    _custom(bl, "save")
    out = bl.filter_text("Save: Are you sure?", preserve_prefix=True)
    assert out == "Save: Are you sure?"


def test_raw_mode_keeps_slash_prefix_intact(bl):
    # The prefix regex cannot match "/ Rick: ", so the speaker anchor must
    # not be colon-stripped either.
    _custom(bl, "save")
    assert bl.filter_text("/ Rick: Move it!", preserve_prefix=True) == "/ Rick: Move it!"


def test_raw_mode_presets_do_not_eat_a_longer_entry(bl):
    bl.set(custom_words=[], enabled_presets=["Common UI"])
    # "Auto Forward selected" must go before the shorter "Auto Forward",
    # otherwise only the first two words are removed.
    out = bl.filter_text("Auto Forward selected: click to continue.", preserve_prefix=False)
    assert "auto forward" not in out.lower()


# -- spoken-body mode (unchanged behaviour) ----------------------------------


def test_body_mode_strips_words(bl):
    _custom(bl, "save")
    assert bl.filter_text("I want to save you") == "I want to you"


def test_body_mode_protects_the_speaker_prefix(bl):
    _custom(bl, "save")
    assert bl.filter_text("Save: Are you sure?") == "Save: Are you sure?"


def test_body_mode_keeps_a_bracketed_tag(bl):
    _custom(bl, "save")
    assert bl.filter_text("[Save]: Are you sure?") == "[Save]: Are you sure?"


# -- persistence -------------------------------------------------------------


def test_persists_and_reloads(tmp_path, monkeypatch):
    path = tmp_path / "blacklist.json"
    monkeypatch.setattr("novatts.config.settings.blacklist_file", path, raising=False)
    Blacklist().set(custom_words=["250 $"], enabled_presets=["Common UI"])
    assert json.loads(path.read_text(encoding="utf-8"))["custom_words"] == ["250 $"]
    reloaded = Blacklist()
    assert reloaded.custom_words == ["250 $"]
    assert reloaded.enabled_presets == ["Common UI"]


# -- renpy exception dumps ---------------------------------------------------


def test_detects_renpy_exception():
    assert is_renpy_exception("An exception has occurred while running game code")
    assert is_renpy_exception("Full traceback:\n  File \"game.rpy\", line 3")
    assert not is_renpy_exception("Rick: I saved you.")
    assert not is_renpy_exception("")
