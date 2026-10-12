"""Tests for space-padded asterisk tokens (`*laughs *`).

Some novels put a space before the closing asterisk. Emotion patterns match
the tight form, so without normalization the token slips through: no emotion
sound plays and stray asterisks reach the TTS model.
"""

from novatts.emotions import EmotionSounds
from novatts.text_clean import clean_emotion_text, normalize_asterisk_tokens


def test_normalize_folds_padding():
    assert normalize_asterisk_tokens("*laughs *") == "*laughs*"
    assert normalize_asterisk_tokens("* laughs*") == "*laughs*"
    assert normalize_asterisk_tokens("* laughs *") == "*laughs*"
    assert normalize_asterisk_tokens("*a* b *c*") == "*a* b *c*"


def test_normalize_leaves_others_alone():
    assert normalize_asterisk_tokens("**bold**") == "**bold**"
    assert normalize_asterisk_tokens("no asterisks here") == "no asterisks here"
    assert normalize_asterisk_tokens("") == ""


def test_extract_finds_padded_emotion():
    es = EmotionSounds(player=None)
    cleaned, emo = es.extract("*Giggles * No, um... I knew a bit.")
    assert [tag for _, tag in emo] == ["giggle"]
    assert "*" not in cleaned
    assert "No, um" in cleaned


def test_padded_matches_tight_form():
    es = EmotionSounds(player=None)
    tight = es.extract("*Laughs* H-How is my French?")
    padded = es.extract("*Laughs * H-How is my French?")
    assert [tag for _, tag in padded[1]] == [tag for _, tag in tight[1]]
    assert "*" not in padded[0]


def test_clean_emotion_text_handles_padding():
    assert "*" not in clean_emotion_text("*Giggles * No, um... I knew a bit.")
    assert "No, um" in clean_emotion_text("*Giggles * No, um... I knew a bit.")
    assert clean_emotion_text("*laughs *") == ""
