"""Adapter interface for dialogue input pipelines."""

from __future__ import annotations

import abc
from collections.abc import Callable, Iterable

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
    def set_known_speakers(self, names: Iterable[str]) -> None:
        """Sync the registry-backed name set this adapter's parser trusts.

        ``NovaApp`` primes every adapter from one place, because a parser
        holding a stale set keeps guessing names the user has already
        registered. Declared here rather than left to each adapter: a
        source added later cannot silently skip the priming, and the loop
        that does it stays type-checked instead of duck-typed.
        """

    @abc.abstractmethod
    def start(self) -> None:
        """Start the background polling/listening loop."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop the loop and release resources."""

    @abc.abstractmethod
    def is_running(self) -> bool:
        """Whether the loop is currently active."""
