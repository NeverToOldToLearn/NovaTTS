"""Rich-text markup removal, shared by every input route.

LunaTranslator copies and forwards the game's dialogue *with* its
formatting, so a name arrives as ``<b>Tatsuo</b>`` instead of ``Tatsuo``
and a line break as ``<br/>``. Measured on the user's own clipboard log
(F14): 23 of 124 accepted payloads carried a tag, 18.5%.

This lives here rather than in one parser because two routes need it and
the F14 gap was precisely that it sat in only one of them. The clipboard
route stripped tags and the websocket route did not, so the same payload
parsed correctly on one and was read aloud as narration on the other.
Any third route that handles raw hook text must strip here too.
"""

from __future__ import annotations

import html
import re

# One tag of a rich-text payload: "<b>", "</b>", "<br/>", "<color=#E0BCE7>".
# Four restrictions, each answering a measured case:
#
#   * The name must start with a letter (optionally after "/"), because
#     "<[^<>]{0,200}>" also matches a comparison -- "5<10 and 10>5" became
#     "5 5". A real tag never starts with a digit or a space.
#   * The attribute run may start with whitespace *or* "=", because game
#     markup writes "<color=#E0BCE7>" with no space. Measured F20, live: the
#     "=" form survived, speaker detection failed on the "<", and Qwen read
#     the color code aloud. Stated tradeoff: "x<y=z>" now strips where it did
#     not -- a letter directly after "<" followed by "=" is indistinguishable
#     from a tag without a space, and real dialogue never looks like that.
#   * The inner class forbids "<" and ">", so one tag cannot span two.
#   * The 200 bound keeps a pathological payload from becoming quadratic.
_TAG_PATTERN = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:[\s=][^<>]{0,200})?/?>")


def strip_markup(raw: str) -> str:
    """Remove rich-text tags and decode entities from one hook payload.

    Tags become a space so ``a<br/>b`` does not become ``ab``, and tags are
    removed *before* entities are decoded so an escaped ``&lt;b&gt;`` stays
    readable text instead of turning into a tag that is then dropped (D51).

    Callers must keep the untouched string as ``raw`` for the forensic
    record; only the text handed to a parser should be stripped.
    """
    return html.unescape(_TAG_PATTERN.sub(" ", raw))
