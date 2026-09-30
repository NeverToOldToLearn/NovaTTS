"""Tests for the LunaHook websocket adapter.

The module is split so the decisions (decode, guards, dual-hook merge)
are testable without a socket, and the plumbing is testable without a
game. Both halves are covered here, and the one test that matters most
is the last group: the dispatch design exists so a slow synthesis cannot
block the event loop, and nothing short of a real server and a real slow
callback proves that.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import queue
import socket
import threading
import time
from collections.abc import Callable

import pytest
import websockets.asyncio.client
import websockets.asyncio.server

from novatts.adapters.luna import (
    HookTextProcessor,
    LunaAdapter,
    check_and_fix_proxy,
    decode_wire_message,
)


def _free_port() -> int:
    """Ask the OS for a port, then release it.

    Binding to 0 avoids the fixed 6677, so a parallel test run or a
    LunaTranslator already attached to the real port cannot make these
    tests fail for a reason that has nothing to do with the code.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _send(url: str, *frames: str) -> None:
    """Connect, send every frame, disconnect."""
    async with websockets.asyncio.client.connect(url) as ws:
        for frame in frames:
            await ws.send(frame)


def _wait_for(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    """Poll ``predicate`` until it is true or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _port_is_free(port: int) -> bool:
    """True when nothing is listening on ``port``.

    Used to prove a *negative*: that the adapter in client mode never binds.
    Asserting "I did nothing" is the only way to show that, because a test
    that merely checks a line arrived cannot tell a client that connects
    from a server that happened to receive.
    """
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class _FakeHook:
    """A stand-in for a hook that is the *server*, which is the real case.

    ``textractor_websocket`` -- the extension the docs point at -- "opens a
    WebSocket locally on port 6677 and sends the text from Textractor to all
    the connected clients", so Textractor listens and NovaTTS dials in. That
    is the opposite of this adapter's default, and it is the only way to
    exercise the client path.

    One frame per connection, then the connection is closed. That is not
    decoration: a closed connection is what makes the adapter's retry loop
    observable, because a hook that stays up forever never leaves it.
    """

    def __init__(self, port: int, sluit_na_frame: bool = True) -> None:
        self.port = port
        #: False keeps the connection open after the frame, which is what a
        #: running-but-silent hook looks like. Both outcomes have to be
        #: reachable from a test double, because the one that hides a defect
        #: is the one you will not think to test.
        self.sluit_na_frame = sluit_na_frame
        self.connections = 0
        self.ready = threading.Event()
        self._frames: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def send(self, frame: str) -> None:
        """Queue a frame for the next (or current) connection."""
        self._frames.put(frame)

    def start(self) -> None:
        self._thread.start()
        assert self.ready.wait(5.0), "the stand-in hook did not start listening"

    def stop(self) -> None:
        self._stop.set()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(lambda: None)
        self._thread.join(timeout=5.0)

    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._serve())
        finally:
            with contextlib.suppress(Exception):
                loop.close()

    async def _serve(self) -> None:
        server = await websockets.asyncio.server.serve(
            self._handle, "127.0.0.1", self.port
        )
        self.ready.set()
        await asyncio.to_thread(self._stop.wait)
        server.close()
        await server.wait_closed()

    async def _handle(self, websocket: object) -> None:
        self.connections += 1
        # The wait is bounded and re-checks the stop flag. An unbounded
        # ``Queue.get`` looks simpler and deadlocks: ``server.close()``
        # waits for the handlers, so a handler parked on an empty queue
        # makes stop() hang instead of end.
        while not self._stop.is_set():
            try:
                frame = await asyncio.to_thread(self._frames.get, True, 0.25)
            except queue.Empty:
                continue
            await websocket.send(frame)  # type: ignore[attr-defined]
            if not self.sluit_na_frame:
                # Stay connected and quiet. The adapter's client loop parks
                # in `async for` here, which is what the stop() gap is about.
                await asyncio.to_thread(self._stop.wait)
                return
            await websocket.close()  # type: ignore[attr-defined]
            return


class TestDecodeWireMessage:
    """The wire format is not what the docs say it is, so read it wide."""

    def test_plain_text_passes_through(self) -> None:
        text, keys = decode_wire_message("Rick Hello there")
        assert text == "Rick Hello there"
        assert keys is None

    def test_bytes_are_decoded(self) -> None:
        text, keys = decode_wire_message(b"Rick Hello")
        assert text == "Rick Hello"
        assert keys is None

    def test_json_body_without_name(self) -> None:
        assert decode_wire_message('{"text": "Anne Hello"}') == ("Anne Hello", "text")

    @pytest.mark.parametrize("name_key", ["name", "speaker", "character"])
    def test_json_name_key_is_rebuilt_into_colon_form(self, name_key: str) -> None:
        """G3.1: the donor dropped the speaker on any JSON hook that carried
        a name separately, so every line played on the narrator voice."""
        frame = json.dumps({name_key: "Lina", "text": "Hoi"})
        text, _ = decode_wire_message(frame)
        assert text == "Lina: Hoi"

    @pytest.mark.parametrize("body_key", ["text", "sentence", "content", "message"])
    def test_every_documented_body_key_is_read(self, body_key: str) -> None:
        frame = json.dumps({"name": "Lina", body_key: "Hoi"})
        text, _ = decode_wire_message(frame)
        assert text == "Lina: Hoi"

    def test_data_key_is_a_body(self) -> None:
        """G3.7: some hook builds put the line under "data"."""
        assert decode_wire_message('{"data": "raw line"}')[0] == "raw line"

    def test_name_key_priority_order(self) -> None:
        """First key in _NAME_KEYS wins, so a frame with several is stable."""
        frame = json.dumps({"name": "First", "speaker": "Second", "text": "x"})
        assert decode_wire_message(frame)[0] == "First: x"

    def test_body_key_priority_order(self) -> None:
        frame = json.dumps({"text": "First", "message": "Second"})
        assert decode_wire_message(frame)[0] == "First"

    def test_unrecognised_json_object_yields_nothing(self) -> None:
        """Speaking {"foo": 1} out loud is never right."""
        text, keys = decode_wire_message('{"foo": 1}')
        assert text == ""
        assert keys == "foo"

    def test_non_numeric_text_is_coerced(self) -> None:
        assert decode_wire_message('{"text": 123}')[0] == "123"

    def test_json_list_is_not_an_object(self) -> None:
        """A list is not a hook payload; leave it for the guards."""
        text, keys = decode_wire_message("[1, 2, 3]")
        assert text == "[1, 2, 3]"
        assert keys is None

    def test_malformed_json_passes_through(self) -> None:
        assert decode_wire_message('{"text": "oops')[0] == '{"text": "oops'

    def test_keys_are_reported_for_diagnostics(self) -> None:
        """The whole point of the second element: a hook that sends an
        unexpected key is otherwise indistinguishable from a parse bug."""
        _, keys = decode_wire_message('{"content": "x", "name": "y"}')
        assert keys == "content,name"


class TestProxyGuard:
    def test_no_proxy_needed_when_nothing_is_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        assert check_and_fix_proxy() == []

    def test_proxy_pointing_at_loopback_is_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:8080")
        warnings = check_and_fix_proxy()
        assert warnings
        assert "localhost" in warnings[0]

    def test_no_proxy_is_extended_when_a_proxy_is_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """We can fix this half ourselves, so we do instead of only warning."""
        import os

        monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:3128")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        warnings = check_and_fix_proxy()
        assert warnings
        assert "127.0.0.1" in os.environ["NO_PROXY"]
        assert os.environ["no_proxy"] == os.environ["NO_PROXY"]

    def test_existing_no_proxy_is_left_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import os

        monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:3128")
        monkeypatch.setenv("NO_PROXY", "example.com")
        check_and_fix_proxy()
        assert "example.com" in os.environ["NO_PROXY"]


class TestHookTextProcessor:
    def test_space_form(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        out = p.push("Rick Hello there")
        assert [(d.speaker, d.text) for d in out] == [("Rick", "Hello there")]

    def test_narration_has_no_speaker(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        out = p.push("You have your shower.")
        assert out and out[0].speaker is None

    def test_game_chrome_is_dropped(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        assert p.push("Save Game 3") == []

    def test_too_short_is_dropped(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        assert p.push("ab") == []

    def test_renpy_exception_is_dropped(self) -> None:
        """Some games route their crash log through the same hook."""
        p = HookTextProcessor(min_text_length=3)
        assert p.push("Traceback (most recent call last):\n  File x") == []

    def test_multi_speaker_line_becomes_two_dialogues(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        out = p.push("Anne Hallo! Rick Mooi.")
        assert [(d.speaker, d.text) for d in out] == [("Anne", "Hallo!"), ("Rick", "Mooi.")]

    def test_raw_is_preserved_for_forensics(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        out = p.push("  Anne   Hallo!  Rick Mooi.  ")
        assert {d.raw for d in out} == {"  Anne   Hallo!  Rick Mooi.  "}

    def test_source_is_luna(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        assert p.push("Rick Hello there")[0].source == "luna"

    @pytest.mark.parametrize(
        ("text", "guess"),
        [
            ("Rick: Hello there", False),  # the colon states the name
            ("Rick Hello there", True),  # space form infers it
            ("Anne Hallo! Rick Mooi.", True),  # both turns are inferences
        ],
    )
    def test_provenance_survives_the_rebuild(self, text: str, guess: bool) -> None:
        """push() rebuilds each Dialogue to stamp source and raw.

        The parser sets ``speaker_is_guess``; a hand rebuild dropped it.
        Because every gate test built its Dialogue directly, both layers
        stayed green over a trust gate that was inert on this, the only
        path the hook actually uses.
        """
        p = HookTextProcessor(min_text_length=3)
        out = p.push(text)
        assert out and all(d.speaker_is_guess is guess for d in out)

    def test_registered_name_is_stated_not_guessed(self) -> None:
        """A registry hit is the user overruling the heuristic."""
        p = HookTextProcessor(min_text_length=3, known_names=["Rick"])
        (dialogue,) = p.push("Rick Hello there")
        assert dialogue.speaker_is_guess is False

    def test_known_names_reach_the_parser(self) -> None:
        p = HookTextProcessor(min_text_length=3, known_names=["Dr"])
        out = p.push("Dr Watts is in.")
        assert out and out[0].speaker == "Dr"

    def test_set_known_names_after_construction(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        p.set_known_names(["Watts"])
        out = p.push("Watts The door is open.")
        assert out and out[0].speaker == "Watts"

    def test_known_name_does_not_override_the_mention_guard(self) -> None:
        """"Watts is in." is narration *about* Watts, not Watts speaking.

        Being registered wins over the stopword and UI word lists, but not
        over the grammar: the mention guard exists to stop every sentence
        that happens to start with a character's name from stealing their
        voice, and a registered name does not change that.
        """
        p = HookTextProcessor(min_text_length=3, known_names=["Watts"])
        out = p.push("Watts is in.")
        assert out and out[0].speaker is None

    def test_greeting_is_not_a_speaker(self) -> None:
        """Space-form greetings start with a capitalised word that is not
        in the stopword set, so the parser reads it as a character.

        Pinned as a gap on purpose: the fix is a data change in the
        parser's word lists, and tuning those wants real game captures
        rather than a guess made inside the adapter. See
        ``test_known_gap_hello_is_not_in_the_stopword_set``.
        """
        p = HookTextProcessor(min_text_length=3)
        out = p.push("Hello there")
        assert out and out[0].speaker == "Hello"


class TestDualHook:
    """D3/G3.4: the donor never wired hook_dual_hook at all."""

    def test_off_by_default(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        assert p.push("Rick:") == []
        assert p.pending_name is None

    def test_name_is_buffered_then_merged(self) -> None:
        p = HookTextProcessor(min_text_length=3, dual_hook=True)
        assert p.push("Rick:") == []
        assert p.pending_name == "Rick"
        out = p.push("Hello there")
        assert [(d.speaker, d.text) for d in out] == [("Rick", "Hello there")]

    def test_bare_name_without_colon_also_merges(self) -> None:
        """The LunaHook/Textractor shape, which has no colon at all."""
        p = HookTextProcessor(min_text_length=3, dual_hook=True)
        assert p.push("Lina") == []
        assert p.pending_name == "Lina"
        out = p.push("Hoi daar")
        assert [(d.speaker, d.text) for d in out] == [("Lina", "Hoi daar")]

    def test_merge_is_consumed(self) -> None:
        """The buffered name applies to exactly one line.

        Uses a stopword lead ("then") so the assertion is about the merge
        and not about whether the parser reads a capitalised first word
        as a character.
        """
        p = HookTextProcessor(min_text_length=3, dual_hook=True)
        p.push("Rick:")
        p.push("First line here")
        assert p.pending_name is None
        out = p.push("then the second line")
        assert out[0].speaker is None, "the buffered name was applied twice"

    def test_stale_name_is_not_prepended(self) -> None:
        """A name left pending would be prepended to an unrelated line."""
        p = HookTextProcessor(min_text_length=3, dual_hook=True)
        p.push("Rick:")
        p._pending_since = time.monotonic() - 99.0  # noqa: SLF001
        out = p.push("then something else entirely")
        assert out[0].speaker is None, "a stale name was prepended"

    @pytest.mark.parametrize(
        "text",
        [
            "Yes.",  # terminal punctuation: a sentence
            "Yes",  # stopword
            "ok",
            "You",
            "go",
            "Save Game 3",  # UI pattern
            "lower case",
            "a" * 21,
        ],
    )
    def test_not_a_name(self, text: str) -> None:
        p = HookTextProcessor(min_text_length=3, dual_hook=True)
        assert not p.is_name_only(text)

    def test_two_word_sentence_is_not_a_name(self) -> None:
        """The guard that makes the whole feature work.

        "Hello there" matches the name shape, but if it were buffered the
        *body* line would be buffered next and the merge would never fire:
        every line would silently vanish instead of being misattributed.
        """
        p = HookTextProcessor(min_text_length=3, dual_hook=True)
        assert not p.is_name_only("Hello there")
        assert not p.is_name_only("Good night")

    def test_real_two_word_name_is_accepted_with_a_colon(self) -> None:
        """A colon is positive evidence, so no registry needed."""
        p = HookTextProcessor(min_text_length=3, dual_hook=True)
        assert p.is_name_only("Miss Brooks:")

    def test_real_two_word_name_is_accepted_once_registered(self) -> None:
        p = HookTextProcessor(min_text_length=3, dual_hook=True, known_names=["Miss Brooks"])
        assert p.is_name_only("Miss Brooks")

    def test_registered_stopword_name_is_accepted(self) -> None:
        p = HookTextProcessor(min_text_length=3, dual_hook=True, known_names=["Dr"])
        assert p.is_name_only("Dr")

    def test_name_only_line_is_dropped_when_dual_hook_is_off(self) -> None:
        """A bare name has no dialogue attached, so there is nothing to say.

        The parser would otherwise read "Rick:" as narration and speak the
        word "Rick" out loud.
        """
        p = HookTextProcessor(min_text_length=3, dual_hook=False)
        assert p.push("Rick:") == []


class TestServerRoundTrip:
    """A real server, a real client, real frames on a real socket."""

    def test_line_arrives_as_a_dialogue(self) -> None:
        port = _free_port()
        got: list[object] = []
        event = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            got.append(dialogue)
            event.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.port = port
        adapter.start()
        try:
            assert adapter.is_running()
            asyncio.run(_send(f"ws://127.0.0.1:{port}", "Rick Hello there"))
            assert event.wait(5.0), "no dialogue arrived within 5s"
        finally:
            adapter.stop()
        assert got[0].speaker == "Rick"  # type: ignore[attr-defined]
        assert got[0].text == "Hello there"  # type: ignore[attr-defined]
        assert got[0].source == "luna"  # type: ignore[attr-defined]
        assert got[0].raw == "Rick Hello there"  # type: ignore[attr-defined]

    def test_json_frame_reconstructs_the_speaker(self) -> None:
        """G3.1 end to end: name + text on the wire becomes "Name: text"."""
        port = _free_port()
        got: list[object] = []
        event = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            got.append(dialogue)
            event.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.port = port
        adapter.start()
        try:
            asyncio.run(
                _send(f"ws://127.0.0.1:{port}", json.dumps({"name": "Lina", "text": "Hoi"}))
            )
            assert event.wait(5.0)
        finally:
            adapter.stop()
        assert got[0].speaker == "Lina"  # type: ignore[attr-defined]
        assert got[0].text == "Hoi"  # type: ignore[attr-defined]

    def test_multi_speaker_line_yields_two_callbacks(self) -> None:
        port = _free_port()
        got: list[object] = []
        event = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            got.append(dialogue)
            if len(got) >= 2:
                event.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.port = port
        adapter.start()
        try:
            asyncio.run(_send(f"ws://127.0.0.1:{port}", "Anne Hallo! Rick Mooi."))
            assert event.wait(5.0)
        finally:
            adapter.stop()
        assert [(d.speaker, d.text) for d in got] == [("Anne", "Hallo!"), ("Rick", "Mooi.")]  # type: ignore[attr-defined]

    def test_client_count_tracks_connections(self) -> None:
        port = _free_port()
        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.port = port
        adapter.start()
        seen: list[int] = []
        try:
            assert _wait_for(lambda: adapter.client_count == 0)
            asyncio.run(self._connect_and_hold(f"ws://127.0.0.1:{port}", adapter, seen))
        finally:
            adapter.stop()
        # Asserting 0 before and 0 after is not enough: a counter that
        # never counts passes that, and mutating `self._clients += 1` to
        # `+= 0` did exactly that. So the count has to be observed *while*
        # the connection is open, not only around it.
        assert 1 in seen, (
            f"the counter never showed a connected client, only {sorted(set(seen))}"
        )
        # Closed again, so back to zero -- and never negative.
        assert adapter.client_count == 0

    @staticmethod
    async def _connect_and_hold(
        url: str, adapter: LunaAdapter, seen: list[int]
    ) -> None:
        async with websockets.asyncio.client.connect(url) as ws:
            await ws.send("Rick Hello there")
            # Poll from inside the connection: the counter is maintained by
            # the adapter's own thread, so the reading has to be taken while
            # the socket is demonstrably open.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                seen.append(adapter.client_count)
                if seen[-1] > 0:
                    return
                await asyncio.sleep(0.05)

    def test_last_raw_is_recorded(self) -> None:
        """D9 groundwork: "nothing arrives" and "arrives and is misparsed"
        look identical from outside unless the raw line is kept."""
        port = _free_port()
        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.port = port
        adapter.start()
        try:
            asyncio.run(_send(f"ws://127.0.0.1:{port}", "Save Game 3"))
            assert _wait_for(lambda: adapter.last_raw == "Save Game 3")
        finally:
            adapter.stop()

    def test_set_known_speakers_reaches_connected_processors(self) -> None:
        p = HookTextProcessor(min_text_length=3)
        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter._processors = {1: p}  # noqa: SLF001
        adapter.set_known_speakers(["Watts"])
        assert p.known_names == ("Watts",)


class TestClientRoundTrip:
    """The adapter as a client: it dials out instead of listening.

    This is the path ``NOVATTS_LUNA_WS_URL`` selects, and until now it had
    no test at all -- only the config parsing was covered, never the
    connecting. It is the path the documented extension actually needs,
    because that extension is a server and this adapter's default is not.
    """

    def test_line_arrives_as_a_dialogue(self) -> None:
        port = _free_port()
        hook = _FakeHook(port)
        hook.start()
        got: list[object] = []
        event = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            got.append(dialogue)
            event.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.ws_url = hook.url()
        adapter.start()
        try:
            hook.send("Rick Hello there")
            assert event.wait(5.0), "no dialogue arrived within 5s"
        finally:
            adapter.stop()
            hook.stop()
        assert got[0].speaker == "Rick"  # type: ignore[attr-defined]
        assert got[0].text == "Hello there"  # type: ignore[attr-defined]
        assert got[0].source == "luna"  # type: ignore[attr-defined]

    def test_json_frame_reconstructs_the_speaker(self) -> None:
        """The wire format is the same in both directions, so it is proven
        here too: name + text on the wire becomes "Name: text"."""
        port = _free_port()
        hook = _FakeHook(port)
        hook.start()
        got: list[object] = []
        event = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            got.append(dialogue)
            event.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.ws_url = hook.url()
        adapter.start()
        try:
            hook.send(json.dumps({"name": "Lina", "text": "Hoi"}))
            assert event.wait(5.0)
        finally:
            adapter.stop()
            hook.stop()
        assert got[0].speaker == "Lina"  # type: ignore[attr-defined]
        assert got[0].text == "Hoi"  # type: ignore[attr-defined]

    def test_it_reconnects_when_the_hook_drops_the_connection(self) -> None:
        """A hook that restarts is the normal case, not an edge case.

        The stand-in sends one frame and closes, so the retry loop is the
        only thing that can deliver the second line. Without this test a
        regression that turns the retry into a single attempt would still
        pass every other test in this file.
        """
        port = _free_port()
        hook = _FakeHook(port)
        hook.start()
        got: list[object] = []
        both = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            got.append(dialogue)
            if len(got) >= 2:
                both.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.ws_url = hook.url()
        adapter.start()
        try:
            hook.send("Rick First line")
            assert _wait_for(lambda: len(got) >= 1), "the first line never arrived"
            hook.send("Rick Second line")
            assert both.wait(5.0), "the adapter did not reconnect for the second line"
        finally:
            adapter.stop()
            hook.stop()
        assert hook.connections >= 2, (
            f"expected a second connection, the hook saw {hook.connections}"
        )
        assert [d.text for d in got] == ["First line", "Second line"]  # type: ignore[attr-defined]

    def test_registered_names_survive_a_reconnect(self) -> None:
        """A re-hooked game must not lose the registry. Measured F18, live.

        The stand-in closes after every frame, so each frame reconnects --
        exactly what re-hooking the game in LunaTranslator does. The GUI
        registration between frames primes whatever processor is live; the
        throwaway second frame then forces one more reconnect, so the
        asserted third frame is parsed by a processor built after the last
        prime. Without the fix that processor starts empty and
        "Work Inspector" parses as speaker "Work" with "Inspector ..." as
        dialogue: the F15 bug back without a single line of F15 code
        changing.

        The connections assertion is load-bearing, not decoration: without
        it the test could pass vacuously on a stale connection that never
        reconnected.
        """
        port = _free_port()
        hook = _FakeHook(port)
        hook.start()
        got: list[object] = []
        done = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            got.append(dialogue)
            if len(got) >= 3:
                done.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.ws_url = hook.url()
        adapter.start()
        try:
            hook.send("Tatsuo First line")
            assert _wait_for(lambda: len(got) >= 1), "the first line never arrived"
            # The GUI registration, while connected: primes the live processor.
            adapter.set_known_speakers(["Tatsuo", "Work Inspector"])
            # Throwaway: parsed fine either way, and its close forces the
            # reconnect the asserted frame must arrive on.
            hook.send("Tatsuo Second line")
            assert _wait_for(lambda: len(got) >= 2), "the second line never arrived"
            assert _wait_for(lambda: hook.connections >= 3), (
                f"expected a second reconnect, the hook saw {hook.connections}"
            )
            hook.send("Work Inspector\nCut the corporate talk.")
            assert done.wait(10.0), "the third line never arrived"
        finally:
            adapter.stop()
            hook.stop()
        assert got[2].speaker == "Work Inspector"  # type: ignore[attr-defined]
        assert got[2].text == "Cut the corporate talk."  # type: ignore[attr-defined]


    def test_client_mode_does_not_bind_a_port(self) -> None:
        """The two modes are exclusive, and this is how that is shown.

        Asserting a positive (a line arrived) cannot tell a client that
        connected from a server that received. Binding is the difference,
        so the difference is what gets asserted.
        """
        listen_port = _free_port()
        hook = _FakeHook(_free_port())
        hook.start()
        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.ws_url = hook.url()
        adapter.port = listen_port
        adapter.start()
        try:
            assert _wait_for(lambda: hook.connections >= 1), "never connected"
            assert _port_is_free(listen_port), (
                "client mode bound its own port, so it is really a server"
            )
        finally:
            adapter.stop()
            hook.stop()


    def test_client_count_is_one_while_connected(self) -> None:
        """The Hook card reads this number, and D25 made it one of three
        states instead of one flag.

        ``client_count`` was only ever maintained in ``_handle_client``,
        which is the server path, so in client mode it stayed 0 for the
        whole run. The card then showed the red *not connected* light
        while lines were arriving and being spoken -- the exact failure
        the three states exist to rule out. Asserted while the connection
        is open, because afterwards 0 is correct for both modes.
        """
        port = _free_port()
        hook = _FakeHook(port, sluit_na_frame=False)
        hook.start()
        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.ws_url = hook.url()
        adapter.start()
        try:
            assert _wait_for(lambda: adapter.client_count == 1), (
                "the client never counted itself, so the Hook card stays red "
                "while the hook is connected"
            )
        finally:
            adapter.stop()
            hook.stop()
        assert adapter.client_count == 0, "the count outlived the connection"

    def test_set_known_speakers_reaches_the_client_side_processor(self) -> None:
        """A speaker added in the GUI has to reach the parser in both modes.

        ``set_known_speakers`` walks ``_processors``, and only
        ``_handle_client`` used to fill that dict. In client mode it stayed
        empty, so the priming ``main.py`` does at start, on a game switch
        and on a room change never arrived and every character name stayed
        a guess. No exception, no log line: the names were simply ignored.
        """
        port = _free_port()
        hook = _FakeHook(port, sluit_na_frame=False)
        hook.start()
        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.ws_url = hook.url()
        adapter.start()
        try:
            assert _wait_for(lambda: len(adapter._processors) == 1), (  # noqa: SLF001
                "the client loop built no processor to prime"
            )
            adapter.set_known_speakers(["Watts"])
            assert _wait_for(
                lambda: any(
                    proc.known_names == ("Watts",)
                    for proc in adapter._processors.values()  # noqa: SLF001
                )
            ), "the name never reached the parser the client loop is using"
        finally:
            adapter.stop()
            hook.stop()

    def test_stop_is_prompt_with_a_silent_connection_open(self) -> None:
        """The case a hook that closes after each line cannot show.

        ``_pump`` parks in ``async for message in websocket`` and never
        reads the stop event, so with the link up and idle ``stop()`` spent
        its entire 5 second join timeout, gave up, and returned while the
        thread lived on. Measured: 5.00 s, exactly the timeout, with
        ``is_running()`` already reporting False.

        Only a *silent* connection shows it, which is why the stand-in
        hook has to be able to stay open. With one that closes after every
        frame ``_pump`` returns by itself, ``stop()`` looks instant and
        correct, and the defect is invisible.
        """
        port = _free_port()
        hook = _FakeHook(port, sluit_na_frame=False)
        hook.start()
        got: list[object] = []
        event = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            got.append(dialogue)
            event.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.ws_url = hook.url()
        adapter.start()
        try:
            hook.send("Rick Hello there")
            assert event.wait(5.0), "no dialogue arrived, so the loop never reached _pump"
            thread = adapter._thread  # noqa: SLF001
            assert thread is not None
            start = time.monotonic()
            adapter.stop()
            elapsed = time.monotonic() - start
            assert elapsed < 2.0, (
                f"stop() took {elapsed:.2f}s with a silent connection open; "
                "the join timeout is being spent on nothing"
            )
            assert not thread.is_alive(), (
                "stop() returned but the client loop is still running, so "
                "is_running() is lying to the dashboard"
            )
        finally:
            adapter.stop()
            hook.stop()


class TestNonBlocking:
    """The reason this module is split the way it is.

    The donor called on_dialogue from inside `async for msg in ws`, so the
    whole TTS call -- qwen_timeout is 300 seconds -- ran on the event
    loop and one slow synthesis froze every connected client. These tests
    are the guard against that coming back.
    """

    def test_a_slow_callback_does_not_stall_the_event_loop(self) -> None:
        port = _free_port()
        started = threading.Event()
        release = threading.Event()
        delivered = threading.Event()
        calls: list[str] = []

        def on_dialogue(dialogue: object) -> None:
            calls.append(dialogue.text)  # type: ignore[attr-defined]
            started.set()
            if len(calls) == 1:
                # Block the dispatch thread the way a real synthesis does.
                release.wait(10.0)
            else:
                delivered.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.port = port
        adapter.start()
        received = lambda: adapter.last_raw == "Anne Second line here"  # noqa: E731
        assert received() is False
        try:
            # One connection held open across both lines, so the assertion
            # is about the loop staying responsive and not about the
            # client having disconnected.
            asyncio.run(self._send_and_hold(f"ws://127.0.0.1:{port}", started, received, adapter))
            # The second line was queued while the worker was stuck. Release
            # it and wait, before stop(): stopping clears the queue by
            # design, so asserting after stop() would be asserting on a
            # different thing.
            release.set()
            assert delivered.wait(5.0), "the queued line was never delivered"
        finally:
            release.set()
            adapter.stop()
        assert calls == ["First line here", "Second line here"], f"got {calls}"

    @staticmethod
    async def _send_and_hold(
        url: str,
        started: threading.Event,
        received: Callable[[], bool],
        adapter: LunaAdapter,
    ) -> None:
        async with websockets.asyncio.client.connect(url) as ws:
            await ws.send("Rick First line here")
            # The dispatch thread is now stuck in the callback, exactly
            # where a real synthesis would sit for up to qwen_timeout.
            # A blocking wait here would deadlock the test itself, so poll.
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.05)
            assert started.is_set(), "first line never reached the callback"

            # The event loop must still be free: this frame has to be
            # received, decoded and enqueued while the worker is blocked.
            await ws.send("Anne Second line here")
            for _ in range(200):
                if received():
                    break
                await asyncio.sleep(0.05)
            assert received(), "the event loop never processed the second frame"
            # Asserted here, while the connection is still open: after the
            # client disconnects the count is legitimately back to zero, and
            # checking afterwards would pass whatever happened in between.
            assert adapter.client_count == 1, "the connection died with the callback"

    def test_a_raising_callback_does_not_kill_the_dispatch_thread(self) -> None:
        port = _free_port()
        survived = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            if dialogue.text == "Rick Boom":  # type: ignore[attr-defined]
                raise RuntimeError("synthesis exploded")
            survived.set()

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.port = port
        adapter.start()
        try:
            asyncio.run(_send(f"ws://127.0.0.1:{port}", "Rick Boom"))
            assert _wait_for(lambda: adapter.dropped == 0)
            asyncio.run(_send(f"ws://127.0.0.1:{port}", "Anne Still working"))
            assert survived.wait(5.0)
        finally:
            adapter.stop()

    def test_a_full_queue_drops_instead_of_growing(self) -> None:
        """Dropping is the right failure. Blocking would reintroduce the
        event-loop stall; growing would trade a dropped line for an
        out-of-memory hours later."""
        port = _free_port()
        release = threading.Event()
        blocked = threading.Event()

        def on_dialogue(dialogue: object) -> None:
            blocked.set()
            release.wait(10.0)

        adapter = LunaAdapter(on_dialogue=on_dialogue)
        adapter.port = port
        adapter.start()
        try:
            frames = [f"Rick Line {i}" for i in range(200)]
            asyncio.run(_send(f"ws://127.0.0.1:{port}", *frames))
            assert blocked.wait(5.0)
            assert _wait_for(lambda: adapter.dropped > 0), "expected drops, queue never filled"
            assert adapter._queue.qsize() <= 64  # noqa: SLF001
        finally:
            release.set()
            adapter.stop()


class TestLifecycle:
    def test_start_is_idempotent(self) -> None:
        port = _free_port()
        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.port = port
        adapter.start()
        try:
            adapter.start()
            assert adapter.is_running()
        finally:
            adapter.stop()

    def test_stop_is_idempotent(self) -> None:
        port = _free_port()
        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.port = port
        adapter.start()
        adapter.stop()
        adapter.stop()
        assert not adapter.is_running()

    def test_stop_releases_the_port(self) -> None:
        """A restart on the same port has to work, or the GUI's
        start/stop button would need two restarts to recover."""
        port = _free_port()
        for _ in range(2):
            adapter = LunaAdapter(on_dialogue=lambda d: None)
            adapter.port = port
            adapter.start()
            adapter.stop()

    def test_stop_returns_promptly(self) -> None:
        """The dispatch thread is parked in on_dialogue; stop() must not
        wait for a 300-second synthesis to finish."""
        port = _free_port()
        entered = threading.Event()
        adapter = LunaAdapter(on_dialogue=lambda d: entered.set())
        adapter.port = port
        adapter.start()
        try:
            asyncio.run(_send(f"ws://127.0.0.1:{port}", "Rick Hello"))
            assert entered.wait(5.0)
            start = time.monotonic()
            adapter.stop()
            assert time.monotonic() - start < 8.0
        finally:
            adapter.stop()

    def test_name_property(self) -> None:
        assert LunaAdapter(on_dialogue=lambda d: None).name == "luna"

    def test_is_an_input_adapter(self) -> None:
        from novatts.adapters.base import InputAdapter

        assert isinstance(LunaAdapter(on_dialogue=lambda d: None), InputAdapter)


# -- F14: the two adapter-side defences ------------------------------------


class TestUnusableWsUrl:
    """Settings validates luna_ws_url; the adapter must not depend on that.

    Defence in depth, and the second layer is the one that mattered when
    this was measured: the adapter picks client mode with ``if self.ws_url``,
    so a value it cannot dial turns a listening server into a dialling
    client that neither listens nor connects -- and every status field still
    looks healthy.
    """

    def test_an_unusable_url_does_not_silently_switch_to_client_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from novatts.config import settings

        monkeypatch.setattr(
            settings, "luna_ws_url", "NOVATTS_LUNA_WS_URL=ws://127.0.0.1:6677"
        )
        adapter = LunaAdapter(on_dialogue=lambda d: None)
        assert adapter.ws_url == "", "a URL it cannot dial must not select client mode"

    @pytest.mark.parametrize("raw", ["localhost:6677", "http://127.0.0.1:6677", "6677"])
    def test_unusable_urls_are_all_refused(
        self, raw: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from novatts.config import settings

        monkeypatch.setattr(settings, "luna_ws_url", raw)
        assert LunaAdapter(on_dialogue=lambda d: None).ws_url == ""

    def test_a_valid_url_still_selects_client_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from novatts.config import settings

        monkeypatch.setattr(settings, "luna_ws_url", "ws://127.0.0.1:6678")
        assert LunaAdapter(on_dialogue=lambda d: None).ws_url == "ws://127.0.0.1:6678"


class TestStartMeansBound:
    """``start()`` used to log "started" before the loop had done anything.

    Measured consequence: a hook that never bound produced the same log
    line, the same is_running() and the same /status as a healthy idle
    hook. The only difference was invisible. Now the loop reports when it is
    really up, and ``start`` says what happened.
    """

    def test_a_loop_that_never_comes_up_is_reported_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import asyncio
        import logging

        from novatts.adapters import luna as luna_mod

        async def park(self: LunaAdapter) -> None:
            # Reachable by stop() through _stop, so the test leaves no
            # thread behind, but it never sets _ready: this is the
            # "server that never bound" case.
            assert self._stop is not None
            await self._stop.wait()

        monkeypatch.setattr(luna_mod, "_STARTUP_TIMEOUT", 0.2)
        monkeypatch.setattr(LunaAdapter, "_server_loop", park)

        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.port = _free_port()
        with caplog.at_level(logging.INFO, logger="novatts.adapters.luna"):
            adapter.start()
        try:
            assert "did not come up" in caplog.text
            assert "adapter started" not in caplog.text
            assert asyncio.get_event_loop_policy() is not None  # keeps the import used
        finally:
            adapter.stop()

    def test_a_real_server_still_reports_started(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.port = _free_port()
        with caplog.at_level(logging.INFO, logger="novatts.adapters.luna"):
            adapter.start()
        try:
            assert adapter.is_running()
            assert "adapter started (server" in caplog.text
            assert "listening on ws://" in caplog.text
            assert "did not come up" not in caplog.text
        finally:
            adapter.stop()

    def test_a_loop_that_dies_reports_why(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A bind that fails is not a timeout: the reason has to survive."""
        import logging

        from novatts.adapters import luna as luna_mod

        async def explode(self: LunaAdapter) -> None:
            raise OSError("address already in use")

        monkeypatch.setattr(luna_mod, "_STARTUP_TIMEOUT", 2.0)
        monkeypatch.setattr(LunaAdapter, "_server_loop", explode)

        adapter = LunaAdapter(on_dialogue=lambda d: None)
        adapter.port = _free_port()
        with caplog.at_level(logging.ERROR, logger="novatts.adapters.luna"):
            adapter.start()
        try:
            assert "did not come up" in caplog.text
            assert "address already in use" in caplog.text
            assert "adapter started" not in caplog.text
        finally:
            adapter.stop()


class TestKnownGaps:
    def test_known_gap_hello_is_not_in_the_stopword_set(self) -> None:
        """A parser word-list gap, pinned here so it stays visible.

        "hello" is missing from the stopword set, so the space form reads
        it as a character: "Hello there" speaks with a cloned "Hello".
        The fix is one word in novatts/parser/luna.py, but tuning that list
        properly wants real captures from real games -- the same reason the
        other pinned gaps were not fixed in place. Recorded rather than
        patched here because this phase is the adapter, and a wrong-voice
        bug in a word list deserves its own tested change.
        """
        p = HookTextProcessor(min_text_length=3)
        out = p.push("Hello there")
        assert out and out[0].speaker == "Hello", (
            "gaplijst gesloten: verwijder of pas deze test aan, "
            "de 'hello'-stopword fix zit nog niet in de parser"
        )


class TestRealLunaTranslatorFrames:
    """Bytes captured from a LunaTranslator that was actually running.

    Everything else in this file is hand-written. These are the frames a live
    service sent on 2026-09-30, recorded while the game "Chrono Ecstasy" was
    attached to ``/api/ws/text/origin``: plain text frames (no JSON wrapper), a
    bare speaker name on its own line, a trailing newline, and nothing else.

    They earn their place here because the hand-written cases missed a real
    defect. F14 covered the newline bare-name shape, but against payloads
    replayed out of a clipboard log -- a simulation of a frame, not a frame.
    The first frame the live service sent had a two-word speaker name, and the
    boundary finder cut it in half: speaker "Work", dialogue "Inspector Cut the
    corporate talk." So the fixture is the capture, not the hand-written shape
    the capture resembled.

    All thirteen frames are replayed, not a representative few. They are free
    to run, and a subset picked by someone who already knows which frames look
    odd is not a sample.

    The names are registered here for the same reason they would be in a real
    game: the module's rule is that a multi-word speaker name has to be in the
    registry before it is treated as one. That is a setup step, not a parser
    quirk, and ``test_an_unregistered_multi_word_name_is_still_cut_at_its_first_word``
    in test_luna_parser.py pins the other side of it.
    """

    #: Verbatim, trailing newline and all. Curly quotes kept as sent.
    FRAMES: tuple[tuple[str, str, str], ...] = (
        (
            "Tatsuo",
            "Yes ma\u2019am, I\u2019m trying to target a very specific audience in a "
            "very specific niche.",
            "Tatsuo\nYes ma\u2019am, I\u2019m trying to target a very specific audience "
            "in a very specific niche.\n",
        ),
        (
            "Tatsuo",
            "My services are aimed towards those looking for a novel intimate "
            "experience without much effort or social connection on the client\u2019s side.",
            "Tatsuo\nMy services are aimed towards those looking for a novel intimate "
            "experience without much effort or social connection on the client\u2019s side.\n",
        ),
        (
            "Work Inspector",
            "Cut the corporate talk.",
            "Work Inspector\nCut the corporate talk.\n",
        ),
        (
            "Work Inspector",
            "What do you do exactly?",
            "Work Inspector\nWhat do you do exactly?\n",
        ),
        (
            "Tatsuo",
            "Not to imply anything but I think I\u2019ve sent an example of the Request "
            "form for my services.",
            "Tatsuo\nNot to imply anything but I think I\u2019ve sent an example of the "
            "Request form for my services.\n",
        ),
        (
            "Tatsuo",
            "I think everything should be already covered in that \u201crequest form\u201d.",
            "Tatsuo\nI think everything should be already covered in that "
            "\u201crequest form\u201d.\n",
        ),
        (
            "Work Inspector",
            "Yes I received it.",
            "Work Inspector\nYes I received it.\n",
        ),
        (
            "Work Inspector",
            "It says in there that you can have sexual intercourse with the "
            "requester while \u201ctime is stopped\u201d.",
            "Work Inspector\nIt says in there that you can have sexual intercourse "
            "with the requester while \u201ctime is stopped\u201d.\n",
        ),
        (
            "Work Inspector",
            "Can you detail how you can \u201cstop time\u201d?",
            "Work Inspector\nCan you detail how you can \u201cstop time\u201d?\n",
        ),
        (
            "Tatsuo",
            "I\u2019d be glad to, but unfortunately it\u2019s a secret technique I cannot "
            "reveal.",
            "Tatsuo\nI\u2019d be glad to, but unfortunately it\u2019s a secret technique "
            "I cannot reveal.\n",
        ),
        (
            "Tatsuo",
            "My whole business depends on this technique and I can\u2019t afford to "
            "sabotage myself like this, I hope you can be understanding from this "
            "point of view. . .",
            "Tatsuo\nMy whole business depends on this technique and I can\u2019t "
            "afford to sabotage myself like this, I hope you can be understanding "
            "from this point of view. . .\n",
        ),
        (
            "Work Inspector",
            "Hm. . . interesting.",
            "Work Inspector\nHm. . . interesting.\n",
        ),
        (
            "Work Inspector",
            "And you need all these approvals from your clients to perform your "
            "\u201ctechnique\u201d?",
            "Work Inspector\nAnd you need all these approvals from your clients to "
            "perform your \u201ctechnique\u201d?\n",
        ),
    )

    NAMES = ["Tatsuo", "Work Inspector"]

    def _push(self, frame: str) -> list[tuple[str | None, str]]:
        p = HookTextProcessor(min_text_length=4, known_names=self.NAMES)
        return [(d.speaker, d.text) for d in p.push(frame)]

    def test_every_captured_frame_yields_its_own_speaker_and_body(self) -> None:
        for want_speaker, want_text, frame in self.FRAMES:
            assert self._push(frame) == [(want_speaker, want_text)], repr(frame)

    def test_the_two_word_name_survives_every_frame_it_appears_in(self) -> None:
        """The defect this file exists to pin: "Work" used to eat "Inspector".

        Counted rather than asserted once, because the failure was not that the
        first frame was wrong but that it was wrong for a speaker who says a
        lot: seven of thirteen frames carry that name, so a single sample would
        have looked like a one-off.
        """
        two_word = [(s, t, f) for s, t, f in self.FRAMES if s == "Work Inspector"]
        assert len(two_word) == 7, f"verwachtte 7, vond {len(two_word)}"
        for want_speaker, want_text, frame in two_word:
            assert self._push(frame) == [(want_speaker, want_text)], repr(frame)

    def test_the_trailing_newline_is_harmless(self) -> None:
        """The service ends every frame with a newline; the frame is one turn.

        Checked with and without rather than assumed, because a trailing
        newline could equally have produced an empty second turn.
        """
        for _speaker, _text, frame in self.FRAMES:
            assert self._push(frame) == self._push(frame.rstrip("\n"))

    def test_raw_keeps_the_newline_the_service_sent(self) -> None:
        """Forensics first: what arrives is what is recorded, unstripped."""
        _speaker, _text, frame = self.FRAMES[2]
        out = HookTextProcessor(min_text_length=4, known_names=self.NAMES).push(frame)
        assert [d.raw for d in out] == [frame]
        assert [d.text for d in out] != [frame], "de body hoort gestript te zijn"
