"""Admission control for the dialogue pipeline.

Every line an adapter produces passes through :meth:`DialogueGate.admit`
before it can reach synthesis. The gate answers one question -- may this
line speak? -- and, if yes, hands back a normalised :class:`Dialogue`.

It is a separate module rather than four more branches in
``NovaApp.on_dialogue`` because that method was already doing exception
filtering, blacklist filtering, auto-registration and event emission.
Adding dedup and a trust gate to it would have produced exactly the
property this port exists to avoid: one function whose behaviour can only
be understood by reading all of it at once. Here each decision is a
named method with its own tests, and ``admit`` reads as the list of
things it checks.

None of this touches I/O beyond the registry's in-memory insert, so the
whole gate runs in tests without a game, a socket or a model.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import replace

from .blacklist import Blacklist, is_renpy_exception
from .models import Dialogue
from .registry.speakers import SpeakerRegistry

log = logging.getLogger(__name__)

#: Why :meth:`DialogueGate.admit` refused a line. These strings are the
#: ``reason`` on the rejection event and on :attr:`Admission.reason`, so
#: they are part of the observable contract rather than log prose.
REASON_EXCEPTION = "renpy_exception"
REASON_DUPLICATE = "duplicate"
REASON_BLACKLIST = "blacklist"
REASON_EMPTY = "empty"


class Admission:
    """The gate's verdict on one line.

    A rejected line has ``dialogue=None`` and a ``reason``. An accepted
    line has the (possibly blacklist-filtered) dialogue and reports
    whether it caused a new speaker to be registered.
    """

    __slots__ = ("dialogue", "guess_only", "new_speaker", "reason")

    def __init__(
        self,
        dialogue: Dialogue | None = None,
        *,
        reason: str = "",
        new_speaker: bool = False,
        guess_only: bool = False,
    ) -> None:
        self.dialogue = dialogue
        self.reason = reason
        self.new_speaker = new_speaker
        self.guess_only = guess_only

    @property
    def accepted(self) -> bool:
        return self.dialogue is not None

    def __bool__(self) -> bool:
        return self.accepted


class DialogueGate:
    """Decides which incoming lines may speak, and how they are stored.

    Three concerns, in the order they are applied:

    1. **Garbage.** A RenPy traceback, a line shorter than nothing, or a
       line the blacklist empties out never reaches the model.
    2. **Repeats.** Textractor re-emits the same line on a window change
       and on re-focus, and in ``hook_mode=both`` the clipboard and the
       hook deliver the same line independently. Identical text within
       ``dedup_window_ms`` speaks once. The window is keyed on the raw
       arrival, so a blacklist edit cannot make a repeat look new.
    3. **Auto-registration.** A speaker the source *stated* is
       registered; a name the parser *inferred* is not.

    The trust rule is the subtle one. ``Dialogue.speaker_is_guess`` is set
    only by the parser's space-form branch, and the RenPy clipboard never
    sets it because "Rick: Hello" names Rick outright. So registering is
    unchanged for the RenPy route -- which is the point, because that
    route is the one with no second opinion available -- while a hook
    guess stays out of ``speakers.json``.

    What that buys is hygiene, and it is worth being exact about it: an
    auto-registered speaker has an empty ``voice``, nothing in the app or
    the GUI assigns one, and an unvoiced speaker speaks on the default
    voice exactly like narration. A wrong guess therefore does not produce
    a wrong voice. It does produce a permanent row in a file the user
    edits by hand, and the registry never prunes.
    """

    def __init__(
        self,
        *,
        registry: SpeakerRegistry,
        blacklist: Blacklist,
        dedup_window_ms: int = 500,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry = registry
        self.blacklist = blacklist
        self.dedup_window = max(0.0, dedup_window_ms / 1000.0)
        self._clock = clock
        # (speaker, raw line) -> when we last spoke it. Guarded because
        # the clipboard thread, the hook dispatch thread and (from F5) the
        # file-watch thread all call admit() concurrently.
        self._seen: dict[tuple[str, str], float] = {}
        self._seen_lock = threading.Lock()

    # -- public ---------------------------------------------------------

    def admit(self, dialogue: Dialogue) -> Admission:
        if is_renpy_exception(dialogue.text):
            return Admission(reason=REASON_EXCEPTION)
        if not dialogue.is_voiceable:
            return Admission(reason=REASON_EMPTY)
        if self._is_duplicate(dialogue):
            return Admission(reason=REASON_DUPLICATE)

        filtered = self.blacklist.filter_text(dialogue.text)
        if not filtered.strip():
            return Admission(reason=REASON_BLACKLIST)
        if filtered != dialogue.text:
            # The filter may change only the text. `raw` is the forensic
            # record of what the source actually sent -- most useful at the
            # exact moment a filter applies -- and `speaker_is_guess` is
            # the provenance the trust gate reads. A hand rebuild dropped
            # each of them once; replace() carries every field.
            dialogue = replace(dialogue, text=filtered)

        new_speaker, guess_only = self._resolve_speaker(dialogue)
        return Admission(dialogue, new_speaker=new_speaker, guess_only=guess_only)

    def forget(self) -> None:
        """Drop the dedup memory. Used by tests and by ``stop()``."""
        with self._seen_lock:
            self._seen.clear()

    @property
    def seen_count(self) -> int:
        with self._seen_lock:
            return len(self._seen)

    # -- steps ----------------------------------------------------------

    def _is_duplicate(self, dialogue: Dialogue) -> bool:
        """True if this exact line spoke within the window.

        Keyed on the raw arrival rather than the parsed text: two
        deliveries of the same line differ in whitespace and speaker
        confidence far more often than in content, and the raw line is
        what makes them recognisably the same utterance.
        """
        if self.dedup_window <= 0:
            return False
        key = (dialogue.speaker or "", dialogue.raw or dialogue.text)
        now = self._clock()
        with self._seen_lock:
            # Prune as we go: the window is short, so the dict only ever
            # holds the last half second, and it cannot outlive a long
            # session by accumulating every line ever seen.
            stale = [k for k, seen_at in self._seen.items() if now - seen_at > self.dedup_window]
            for k in stale:
                del self._seen[k]
            if now - self._seen.get(key, -1e9) <= self.dedup_window:
                return True
            self._seen[key] = now
        return False

    def _resolve_speaker(self, dialogue: Dialogue) -> tuple[bool, bool]:
        """Register the speaker if it can be trusted.

        Returns ``(newly_registered, guess_only)``. ``guess_only`` marks a
        line that speaks under an unregistered, inferred name -- the
        caller surfaces it so an operator can see the guess rather than
        discovering a wrong voice later.
        """
        name = dialogue.speaker
        if not name:
            return False, False
        try:
            known = self.registry.names()
        except Exception:
            return False, True
        if name in known:
            return False, False
        if dialogue.speaker_is_guess:
            log.debug("Not registering inferred speaker %r; it speaks on the default voice", name)
            return False, True
        try:
            self.registry.register(name)
        except Exception:
            log.warning("Could not register speaker %r", name, exc_info=True)
            return False, True
        return True, False
