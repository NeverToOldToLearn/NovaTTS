"""Tests for the contraction guard in emotion filtering.

The primal-sound pattern ``\\b[aeiou]{2,}[mngh]{1,3}\\b`` sees the "ain" in
"ain't" as a moan (word boundary before the apostrophe) and stripped it,
leaving "'t" for the TTS model. Contraction-glued matches must survive on
both the clipboard route (extract) and the /speak route (clean).
"""

from novatts.emotions import EmotionSounds
from novatts.text_clean import clean_emotion_text


def test_aint_survives_clean():
    assert clean_emotion_text("I ain't going.") == "I ain't going."
    assert clean_emotion_text("It ain't broke.") == "It ain't broke."
    assert clean_emotion_text("ain't") == "ain't"


def test_curly_apostrophe_contraction_survives():
    assert clean_emotion_text("I ain\u2019t going.") == "I ain\u2019t going."
    assert clean_emotion_text("y\u2019all come back.") == "y\u2019all come back."


def test_other_contractions_untouched():
    for line in ["rock 'n' roll", "ma'am", "o'clock", "y'all", "don't stop"]:
        assert clean_emotion_text(line) == line, line


def test_aint_survives_extract():
    es = EmotionSounds(player=None)
    cleaned, emo = es.extract("I ain't going.")
    assert "ain't" in cleaned
    assert emo == []


def test_real_moans_still_stripped():
    assert clean_emotion_text("aaah ooh") == ""
    assert clean_emotion_text("Well aaah, yes.") == "Well, yes."
    es = EmotionSounds(player=None)
    cleaned, emo = es.extract("*sighs* Well, yes.")
    assert "*" not in cleaned
    assert [tag for _, tag in emo] == ["sigh"]
