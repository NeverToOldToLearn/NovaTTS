"""Tests for speak-marked vocalizations ("speak": true in emotion_patterns.json).

Vocalizations (haha, mwah) are sounds humans produce, so the word stays as
speakable text. Labels (laugh, sigh, kiss) describe an action -- speaking the
word would miss the effect, so they keep their .wav clip (or drop).
"""

from novatts.emotions import EmotionSounds
from novatts.text_clean import clean_emotion_text, is_speak_span


def test_speak_spans_recognized():
    for span in ["haha", "*haha*", "hehe", "*hehe*", "mwah", "*mwah*",
                 "ha", "argh", "*ugh*", "*ooh*", "*hic*",
                 "hmm", "shh", "phew"]:
        assert is_speak_span(span), span


def test_starred_only_vocalizations_flow():
    # ooh/hic/ugh have starred patterns only; bare they never matched
    # anything, starred the _asterisk_replace keeps them. Both routes:
    for word in ["ooh", "hic", "ugh"]:
        assert clean_emotion_text(word) == word
        assert clean_emotion_text(f"*{word}*") == word
    es = EmotionSounds(player=None)
    cleaned, emo = es.extract("*ooh* really?")
    assert emo == []
    assert cleaned == "ooh really?"


def test_bare_words_without_own_pattern_still_flow():
    # "ugh" has only a starred pattern; bare it never matched anything, so it
    # always reached TTS -- and still does, on both routes.
    assert clean_emotion_text("ugh, that stinks.") == "ugh, that stinks."
    es = EmotionSounds(player=None)
    cleaned, emo = es.extract("ugh, that stinks.")
    assert emo == []
    assert "ugh" in cleaned


def test_dutch_hesitations_and_disgust_flow():
    # eugh/euhm/euh were eaten by the generic moan pattern; they are
    # vocalizations, so speak-marked now. Stretched forms stay blocked.
    for word in ["eugh", "euhm", "euh", "ew", "bah", "uhm"]:
        assert clean_emotion_text(f"zeg {word} maar") == f"zeg {word} maar", word
    es = EmotionSounds(player=None)
    for word in ["eugh", "euhm"]:
        cleaned, emo = es.extract(f"zeg {word} maar")
        assert word in cleaned, word
        assert emo == []
    for stretched in ["ewww", "baaaah", "eughhh"]:
        assert stretched not in clean_emotion_text(f"zeg {stretched} maar").split()


def test_labels_are_not_speak_spans():
    for span in ["laughs", "*laughs*", "*sighs*", "*kiss*", "sigh", "giggles"]:
        assert not is_speak_span(span), span


def test_vocalizations_stay_on_both_routes():
    assert clean_emotion_text("haha, really?") == "haha, really?"
    assert clean_emotion_text("*haha* Really?") == "haha Really?"
    assert clean_emotion_text("say mwah now") == "say mwah now"
    es = EmotionSounds(player=None)
    for line in ["haha, really?", "*haha* Really?", "oh *mwah* bye"]:
        cleaned, emo = es.extract(line)
        assert emo == [], line
        assert "*" not in cleaned, line
    assert "haha" in es.extract("*haha* Really?")[0]


def test_labels_still_clip_or_drop():
    es = EmotionSounds(player=None)
    _, emo = es.extract("*Laughs* Oh no.")
    assert [tag for _, tag in emo] == ["laugh"]
    _, emo = es.extract("*sighs* Well.")
    assert [tag for _, tag in emo] == ["sigh"]
    assert clean_emotion_text("*sighs* Well.") == "Well."
    _, emo = es.extract("*kiss* Bye.")
    assert [tag for _, tag in emo] == ["kiss"]


def test_contractions_still_safe():
    assert clean_emotion_text("I ain't going.") == "I ain't going."
    es = EmotionSounds(player=None)
    cleaned, emo = es.extract("I ain't going.")
    assert "ain't" in cleaned
    assert emo == []
