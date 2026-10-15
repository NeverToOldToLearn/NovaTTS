"""Tests for emotion speak-through mode (settings.emotion_speak_words).

Off (default): emotion words are stripped / swapped for .wav clips.
On (test mode): they stay as speakable text so Qwen renders them itself.
"""

from novatts.emotions import EmotionSounds
from novatts.text_clean import clean_emotion_text


def test_clean_keeps_words_in_speak_mode():
    assert clean_emotion_text("haaa, really?", speak_words=True) == "haaa, really?"
    assert clean_emotion_text("hehe, nice!", speak_words=True) == "hehe, nice!"
    assert clean_emotion_text("*laughs* Oh no.", speak_words=True) == "laughs Oh no."
    assert clean_emotion_text("aaah ooh", speak_words=True) == "aaah ooh"


def test_clean_strips_by_default():
    assert "haaa" not in clean_emotion_text("haaa, really?")
    assert clean_emotion_text("*laughs* Oh no.") == "Oh no."


def test_extract_returns_no_sounds_in_speak_mode():
    es = EmotionSounds(player=None, speak_words=True)
    cleaned, emo = es.extract("*Laughs * Oh no, hahaha!")
    assert emo == []
    assert "*" not in cleaned
    assert "Laughs" in cleaned
    assert "hahaha" in cleaned


def test_extract_default_still_finds_sounds():
    es = EmotionSounds(player=None)
    _, emo = es.extract("*Laughs* Oh no.")
    assert [tag for _, tag in emo] == ["laugh"]
