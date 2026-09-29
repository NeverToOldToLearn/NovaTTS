"""Tests for DialogueGate -- admission control for the dialogue pipeline.

The gate is the only shared decision point between the RenPy clipboard
route, the LunaHook websocket route and (F5) the file-watch route, so
these tests are deliberately about *decisions* rather than about any one
adapter: what may speak, what may be remembered, and what must be thrown
away. Every case here was previously an untested branch inside
``NovaApp.on_dialogue``.
"""

from __future__ import annotations

import threading

import pytest

from novatts.adapters.luna import HookTextProcessor
from novatts.blacklist import Blacklist
from novatts.config import settings
from novatts.gate import (
    REASON_BLACKLIST,
    REASON_DUPLICATE,
    REASON_EMPTY,
    REASON_EXCEPTION,
    DialogueGate,
)
from novatts.models import Dialogue
from novatts.registry.speakers import SpeakerRegistry

# --- fixtures ---------------------------------------------------------------


class FakeClock:
    """A clock the test moves by hand, so no test sleeps for a window."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms / 1000.0


@pytest.fixture()
def registry(tmp_path) -> SpeakerRegistry:
    return SpeakerRegistry(tmp_path / "speakers.json", auto_save_interval=0.0)


@pytest.fixture()
def blacklist(tmp_path, monkeypatch) -> Blacklist:
    # Point the blacklist at the tmp dir *before* constructing it: the
    # constructor reads settings.blacklist_file, and a test that edits the
    # developer's real blacklist.json is not a test anyone will keep.
    monkeypatch.setattr(settings, "blacklist_file", tmp_path / "blacklist.json")
    bl = Blacklist()
    bl.set(custom_words=["Skip"])
    return bl


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def gate(registry, blacklist, clock) -> DialogueGate:
    return DialogueGate(
        registry=registry,
        blacklist=blacklist,
        dedup_window_ms=500,
        clock=clock,
    )


def line(text: str, speaker: str | None = None, **kw: object) -> Dialogue:
    kw.setdefault("source", "luna")
    return Dialogue(speaker=speaker, text=text, **kw)  # type: ignore[arg-type]


# --- the happy path ---------------------------------------------------------


def test_plain_line_is_admitted(gate: DialogueGate) -> None:
    admission = gate.admit(line("Hello there", speaker="Rick"))
    assert admission.accepted
    assert admission.dialogue is not None
    assert admission.dialogue.text == "Hello there"
    assert admission.reason == ""


def test_admission_is_falsy_when_rejected(gate: DialogueGate) -> None:
    assert bool(gate.admit(line("   "))) is False
    assert bool(gate.admit(line("Hello", speaker="Rick"))) is True


# --- garbage ----------------------------------------------------------------


def test_renpy_exception_dump_is_rejected(gate: DialogueGate) -> None:
    dump = 'Traceback (most recent call last):\n  File "game.rpy", line 3 in <module>\nNameError: name \'x\' is not defined'
    admission = gate.admit(line(dump))
    assert not admission.accepted
    assert admission.reason == REASON_EXCEPTION


def test_blank_line_is_rejected(gate: DialogueGate) -> None:
    admission = gate.admit(line("   "))
    assert admission.reason == REASON_EMPTY


def test_line_the_blacklist_empties_is_rejected(gate: DialogueGate) -> None:
    """A line that is nothing but blacklisted noise is not narration."""
    admission = gate.admit(line("Skip", speaker="Rick"))
    assert not admission.accepted
    assert admission.reason == REASON_BLACKLIST


def test_blacklist_rebuild_preserves_the_raw_record(gate: DialogueGate) -> None:
    """Regression: the filter path used to rebuild the Dialogue and drop
    `raw`, so the forensic record from F1/F2 vanished exactly when a
    filter applied -- the moment it is most useful for tuning."""
    original = Dialogue(
        speaker="Rick",
        text="Hello Skip there",
        raw="Rick Hello Skip there",
        source="luna",
    )
    admission = gate.admit(original)
    assert admission.dialogue is not None
    assert admission.dialogue.raw == "Rick Hello Skip there"
    assert admission.dialogue.text == "Hello there"


def test_blacklist_rebuild_preserves_provenance(gate: DialogueGate) -> None:
    """Filtering changes the text, never the line's identity: the source
    and the guess flag describe where the line came from, not how it was
    cleaned."""
    original = Dialogue(
        speaker="Rick",
        text="Hello Skip",
        raw="Rick Hello Skip",
        source="luna",
        speaker_is_guess=True,
    )
    admission = gate.admit(original)
    assert admission.dialogue is not None
    assert admission.dialogue.source == "luna"
    assert admission.dialogue.speaker_is_guess is True


def test_unfiltered_line_is_passed_through_unchanged(gate: DialogueGate) -> None:
    """No rebuild when nothing changed: the caller's object is the one
    the app goes on to use, so identity is observable."""
    original = line("Nothing to filter", speaker="Rick")
    admission = gate.admit(original)
    assert admission.dialogue is original


# --- repeats ----------------------------------------------------------------


def test_same_line_twice_speaks_once(gate: DialogueGate) -> None:
    """Textractor re-emits the same line on a window change and re-focus."""
    assert gate.admit(line("Answer the door.", speaker="Rick")).accepted
    again = gate.admit(line("Answer the door.", speaker="Rick"))
    assert not again.accepted
    assert again.reason == REASON_DUPLICATE


def test_repeat_after_the_window_is_admitted(gate: DialogueGate, clock: FakeClock) -> None:
    assert gate.admit(line("Answer the door.", speaker="Rick")).accepted
    clock.advance(600)
    assert gate.admit(line("Answer the door.", speaker="Rick")).accepted


def test_window_edge_is_inclusive(gate: DialogueGate, clock: FakeClock) -> None:
    gate.admit(line("Answer the door.", speaker="Rick"))
    clock.advance(500)
    assert gate.admit(line("Answer the door.", speaker="Rick")).reason == REASON_DUPLICATE


def test_zero_window_disables_dedup(registry: SpeakerRegistry, blacklist: Blacklist, clock: FakeClock) -> None:
    g = DialogueGate(registry=registry, blacklist=blacklist, dedup_window_ms=0, clock=clock)
    assert g.admit(line("Hi", speaker="Rick")).accepted
    assert g.admit(line("Hi", speaker="Rick")).accepted


def test_different_speakers_saying_the_same_thing_both_speak(gate: DialogueGate) -> None:
    """Dedup is on (speaker, line), not on the line alone: two characters
    answering "No." in the same half second are two lines."""
    assert gate.admit(line("No.", speaker="Rick")).accepted
    assert gate.admit(line("No.", speaker="Anne")).accepted


def test_clipboard_and_hook_copies_are_one_utterance(gate: DialogueGate) -> None:
    """In hook_mode=both the same game line arrives from both adapters.
    The user should hear it once."""
    hook = Dialogue(speaker="Rick", text="Answer the door.", source="luna")
    clipboard = Dialogue(speaker="Rick", text="Answer the door.", source="renpy")
    assert gate.admit(hook).accepted
    assert gate.admit(clipboard).reason == REASON_DUPLICATE


def test_differing_raw_text_defeats_dedup_today(gate: DialogueGate) -> None:
    """Documented limit, deliberately pinned rather than papered over.

    The key is the raw arrival, because that is what makes two deliveries
    recognisably the same utterance. Two deliveries whose raw text differs
    (the hook sending "Rick Answer the door." while the clipboard holds
    "Rick: Answer the door.") therefore both speak. Comparing parsed text
    instead would need the parser inside a 500 ms guard, which places the
    decision in the wrong layer. Pinned so a future change is deliberate.
    """
    hook = Dialogue(speaker="Rick", text="Answer the door.", raw="Rick Answer the door.", source="luna")
    clipboard = Dialogue(speaker="Rick", text="Answer the door.", raw="Rick: Answer the door.", source="renpy")
    assert gate.admit(hook).accepted
    assert gate.admit(clipboard).accepted


def test_dedup_memory_is_pruned_to_the_window(gate: DialogueGate, clock: FakeClock) -> None:
    """The dict must not accumulate every line of a long session."""
    for i in range(50):
        gate.admit(line(f"Line {i}", speaker="Rick"))
        clock.advance(100)
    # 100 ms apart with a 500 ms window: the six most recent keys live.
    assert gate.seen_count <= 6


def test_forget_clears_the_dedup_memory(gate: DialogueGate) -> None:
    gate.admit(line("Hello", speaker="Rick"))
    gate.forget()
    assert gate.admit(line("Hello", speaker="Rick")).accepted


# --- auto-registration: stated names vs inferred names ----------------------


def test_stated_speaker_is_registered(gate: DialogueGate, registry: SpeakerRegistry) -> None:
    """The RenPy route: the game itself put "Rick: ..." on the clipboard."""
    admission = gate.admit(Dialogue(speaker="Rick", text="Hello", source="renpy"))
    assert admission.new_speaker is True
    assert "Rick" in registry.names()


def test_guessed_speaker_is_not_registered(gate: DialogueGate, registry: SpeakerRegistry) -> None:
    """The hook's space form guessed the name; it may speak, but it may
    not become a permanent row in a file the user maintains by hand."""
    admission = gate.admit(
        Dialogue(speaker="Hello", text="there", source="luna", speaker_is_guess=True)
    )
    assert admission.accepted
    assert admission.new_speaker is False
    assert admission.guess_only is True
    assert "Hello" not in registry.names()


def test_guessed_speaker_still_speaks_on_the_default_voice(
    gate: DialogueGate, registry: SpeakerRegistry
) -> None:
    """Refusing to register must not refuse to speak. An unregistered
    speaker resolves to the model's built-in voice, exactly like
    narration."""
    admission = gate.admit(
        Dialogue(speaker="Hello", text="there", source="luna", speaker_is_guess=True)
    )
    assert admission.dialogue is not None
    assert registry.lookup_voice(admission.dialogue.speaker) == ""


def test_known_speaker_is_never_reported_new(gate: DialogueGate, registry: SpeakerRegistry) -> None:
    registry.register("Rick")
    admission = gate.admit(Dialogue(speaker="Rick", text="Hello", source="renpy"))
    assert admission.new_speaker is False
    assert admission.guess_only is False


def test_a_registered_name_outranks_the_guess_flag(
    gate: DialogueGate, registry: SpeakerRegistry
) -> None:
    """If the user has explicitly registered the name, the line is not a
    guess any more -- whatever flag a caller passes. Pins the order of the
    checks in _resolve_speaker."""
    registry.register("Passenger 1")
    admission = gate.admit(
        Dialogue(speaker="Passenger 1", text="Hello", source="luna", speaker_is_guess=True)
    )
    assert admission.new_speaker is False
    assert admission.guess_only is False


def test_narration_registers_nothing(gate: DialogueGate, registry: SpeakerRegistry) -> None:
    admission = gate.admit(Dialogue(speaker=None, text="The room was empty.", source="renpy"))
    assert admission.accepted
    assert admission.new_speaker is False
    assert registry.names() == ["Narrator"]


def test_the_gate_does_not_write_the_registry_to_disk(
    gate: DialogueGate, registry: SpeakerRegistry
) -> None:
    """Registering is an in-memory insert; persistence is the app's call,
    so the gate stays usable without touching the filesystem."""
    before = registry.file_path.read_bytes() if registry.file_path.exists() else b""
    gate.admit(Dialogue(speaker="Rick", text="Hello", source="renpy"))
    after = registry.file_path.read_bytes() if registry.file_path.exists() else b""
    assert after == before


# --- concurrency ------------------------------------------------------------


def test_concurrent_admits_do_not_race(gate: DialogueGate) -> None:
    """Three adapters can call this from three threads at once."""
    results: list[bool] = []
    lock = threading.Lock()

    def worker(worker_id: int) -> None:
        for i in range(20):
            admission = gate.admit(line(f"Line {worker_id}-{i}", speaker=f"Speaker {worker_id}"))
            with lock:
                results.append(admission.accepted)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 80
    assert all(results)


# --- the seam with the hook processor --------------------------------------


class TestTheHookProcessorSeam:
    """``push()`` and ``admit()`` are each well covered; their seam was not.

    Everything above builds its ``Dialogue`` by hand, and every processor
    test looked only at the text. So nothing noticed that ``push()``
    dropped ``speaker_is_guess`` on its rebuild -- and the trust gate, the
    one thing that reads the flag, then registered every space-form
    speaker. That is the single thing D15 says it must not do. These two
    tests run the real processor into the real gate, which is what makes
    the pair meaningful: each half can be green while the wire between
    them is cut.
    """

    def test_a_space_form_guess_is_not_registered(
        self, gate: DialogueGate, registry: SpeakerRegistry
    ) -> None:
        processor = HookTextProcessor(min_text_length=3)
        (dialogue,) = processor.push("Rick Hello there")

        admission = gate.admit(dialogue)

        assert admission.accepted
        assert admission.new_speaker is False
        assert admission.guess_only is True
        assert "Rick" not in registry.names()

    def test_a_colon_form_name_is_registered(
        self, gate: DialogueGate, registry: SpeakerRegistry
    ) -> None:
        processor = HookTextProcessor(min_text_length=3)
        (dialogue,) = processor.push("Rick: Hello there")

        admission = gate.admit(dialogue)

        assert admission.new_speaker is True
        assert "Rick" in registry.names()
