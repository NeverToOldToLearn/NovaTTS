"""Adapter interface for dialogue input pipelines."""

from __future__ import annotations

import abc
import logging
from collections.abc import Callable

from ..models import Dialogue

log = logging.getLogger(__name__)

DialogueCallback = Callable[[Dialogue], None]
FilteredCallback = Callable[[str, str], None]
"""Notified with ``(reason, raw_text)`` when a capture is dropped."""


class InputAdapter(abc.ABC):
    """Base class for all input pipelines.

    Implementations poll or listen for dialogue and invoke ``on_dialogue``
    with a normalized :class:`Dialogue` object. Adapters must never crash
    the host process; all internal errors are caught and logged.
    """

    def __init__(self, on_dialogue: DialogueCallback, on_filtered: FilteredCallback | None = None) -> None:
        self.on_dialogue = on_dialogue
        self._on_filtered = on_filtered

    def notify_filtered(self, reason: str, raw: str) -> None:
        """Report a dropped capture; never propagates callback errors."""
        if self._on_filtered is None:
            return
        try:
            self._on_filtered(reason, raw)
        except Exception:
            log.exception("on_filtered callback failed (swallowed)")

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Pipeline identifier, e.g. "clipboard" or "luna"."""

    @abc.abstractmethod
    def start(self) -> None:
        """Start the background polling/listening loop."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop the loop and release resources."""

    @abc.abstractmethod
    def is_running(self) -> bool:
        """Whether the loop is currently active."""
