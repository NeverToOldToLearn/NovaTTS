"""Adapter interface for dialogue input pipelines."""

from __future__ import annotations

import abc
from collections.abc import Callable

from ..models import Dialogue

DialogueCallback = Callable[[Dialogue], None]


class InputAdapter(abc.ABC):
    """Base class for all input pipelines.

    Implementations poll or listen for dialogue and invoke ``on_dialogue``
    with a normalized :class:`Dialogue` object. Adapters must never crash
    the host process; all internal errors are caught and logged.
    """

    def __init__(self, on_dialogue: DialogueCallback) -> None:
        self.on_dialogue = on_dialogue

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
