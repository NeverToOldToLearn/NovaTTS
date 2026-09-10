"""Luna Hook parser (V2 placeholder).

Luna emits ``Name text`` without a colon — no reliable speaker anchor.
The V2 parser will use a registry whitelist instead of splitting on
colons. Not implemented in V1.
"""

from __future__ import annotations

from ..models import Dialogue


class LunaParser:
    """Placeholder for the Luna-style loose-format parser (V2)."""

    def parse(self, raw: str, source: str = "luna") -> Dialogue:
        raise NotImplementedError("Luna pipeline lands in V2")
