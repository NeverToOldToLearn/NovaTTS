"""LunaHook / Textractor websocket adapter.

Textractor has no speaker anchor and no clipboard contract, so the game
engine pushes each line at us over a websocket and we have to guess who
is talking. The guessing lives in :mod:`novatts.parser.luna`; this
module is only transport plus the small amount of state that transport
needs.

Topology, because it is the opposite of what most hook docs assume:
NovaTTS **serves** the websocket on ``127.0.0.1:6677`` by default and
the hook *connects* to it. Translation stays off; we only want the raw
line.

The hook is not always the client, though, and that is measured rather
than hedged (D39): the ``textractor_websocket`` extension opens a
websocket locally and sends the text to every connected client, so *it*
is the server there and NovaTTS has to dial out. That is the other half
of this module -- :meth:`LunaAdapter._client_loop` -- and it is what
``NOVATTS_LUNA_WS_URL`` / :attr:`LunaAdapter.ws_url` selects. Both
directions are supported; neither is a fallback, and the docs
describe both instead of presenting one as the real one.

LunaTranslator also serves this direction itself, which needs no
Textractor install at all. Its own network service publishes two
endpoints on ``networktcpport`` (default 2333) --
``/api/ws/text/origin`` and ``/api/ws/text/trans`` -- and sends the
translated text as a bare text frame, which
:func:`decode_wire_message` already accepts unchanged. So
``NOVATTS_LUNA_WS_URL=ws://127.0.0.1:2333/api/ws/text/trans`` is a
complete client-mode configuration. That endpoint's format and default
port were read from LunaTranslator's own source rather than measured
against a running instance, so the port is configurable and the claim
is version-bound; see ``docs/LUNATRANSLATOR_HOOK.md`` for the setup.
Note that LunaTranslator binds ``0.0.0.0`` there, not loopback, so the
service is reachable from the local network while it runs.

The module is split so that the interesting half is testable without an
event loop:

- :func:`decode_wire_message` and :func:`check_and_fix_proxy` are pure
  functions over a single message.
- :class:`HookTextProcessor` holds all the mutable state (the dual-hook
  name buffer) and turns a raw line into zero or more
  :class:`~novatts.models.Dialogue` objects. No I/O, no threads.
- :class:`LunaAdapter` owns the event loop, the socket, and the dispatch
  worker. It moves bytes and nothing else.

That split exists because of one hard-won lesson. The donor project calls
``on_dialogue`` from inside ``async for msg in ws``, which means the
entire TTS call — ``qwen_timeout`` is 300 seconds — runs on the event
loop thread, and a single slow synthesis freezes every connected client.
Here the event loop only decodes and enqueues; ``on_dialogue`` runs on a
separate dispatch thread, and a full queue drops the line instead of
growing without bound.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import replace

import websockets
import websockets.asyncio.client
import websockets.asyncio.server
from websockets.asyncio.server import ServerConnection

from ..blacklist import is_renpy_exception
from ..config import settings
from ..models import Dialogue
from ..parser.luna import LunaParser, is_plausible_character_name
from ..parser.markup import strip_markup
from .base import DialogueCallback, InputAdapter

log = logging.getLogger(__name__)

#: Payload keys that may carry the speaker, in priority order. The donor
#: only unwrapped ``text``/``sentence``/``message`` and so silently dropped
#: the speaker on any hook that sent a name field separately; VN_Suite.py
#: reads these same four keys and rebuilds "Name: body" (G3.1).
_NAME_KEYS: tuple[str, ...] = ("name", "speaker", "character")

#: Payload keys that may carry the spoken body, in priority order.
_BODY_KEYS: tuple[str, ...] = ("text", "sentence", "content", "message")

#: A "name-only" line for dual-hook engines, with or without a trailing
#: colon. Ported from VN_Suite.py:3690-3693. One or two words, so short
#: sentences like "Go on" are not mistaken for a name at the regex level;
#: the guards below then reject the rest.
_NAME_ONLY = re.compile(r"^[A-Za-z][A-Za-z0-9'._-]*(?:\s+[A-Za-z][A-Za-z0-9'._-]*)?:?\s*$")

#: Terminal punctuation means it was a sentence, not a name: "Yes." and
#: "Huh?" are dialogue that happens to be one word (VN_Suite.py:3702).
_TERMINAL_PUNCT = re.compile(r"[.!?]$")

#: How long a buffered dual-hook name survives without a body line
#: following it. The next line is expected immediately, so a stale buffer
#: is not worth waiting for -- and leaving it set would prepend a name to
#: an unrelated line minutes later.
_PENDING_NAME_TTL = 0.6

#: Lines waiting for the dispatch thread before we start dropping. Sized
#: so a normal burst (Textractor re-emitting on window change) never
#: touches it, while a stuck TTS call cannot grow memory without bound.
_DISPATCH_QUEUE_SIZE = 64

# How long ``start`` waits for the event loop to reach a definitive state
# before it reports that the hook is not coming up. Paid only on failure: a
# loopback bind is milliseconds. F14, because "started" used to be logged
# before the loop had done anything, which made a hook that never bound
# indistinguishable from one that is merely idle.
_STARTUP_TIMEOUT = 5.0


def _dialable_ws_url(raw: str) -> str:
    """The outbound URL, or "" when it cannot be dialled.

    ``Settings`` already repairs and validates this, so an empty result here
    means the value arrived without passing the validator. The failure it
    prevents is the one F14 ran into: a non-empty ``ws_url`` selects client
    mode, so an unusable URL quietly turns a listening server into a dialling
    client that neither listens nor connects. Defence in depth, not
    redundancy -- the adapter is constructed from ``settings`` by a test, by
    the app, and potentially by future code that does not go through the
    validator.
    """
    url = raw.strip()
    if url and not url.startswith(("ws://", "wss://")):
        log.error(
            "Ignoring unusable NOVATTS_LUNA_WS_URL=%r; starting in server mode "
            "on %s:%s instead",
            raw,
            settings.hook_host,
            settings.hook_port,
        )
        return ""
    return url


# ---------------------------------------------------------------------------
# Wire decoding (pure)
# ---------------------------------------------------------------------------


def decode_wire_message(msg: str | bytes) -> tuple[str, str | None]:
    """Turn one websocket frame into text.

    Returns ``(text, json_keys)``, where ``json_keys`` is the comma-joined
    sorted key list when the frame was a JSON object and ``None`` when it
    was plain text. The key list is only there for one log line: when a
    hook line does not arrive the way the docs claim, the difference
    between ``{"text": "..."}`` and ``{"content": "..."}`` is the entire
    bug, and guessing from the parsed result hides it.

    A JSON object with no recognised body key yields empty text rather
    than the raw JSON. Speaking ``{"foo": 1}`` out loud is never right,
    and passing it on would make the garbage guards guess.
    """
    text = msg.decode("utf-8", errors="ignore") if isinstance(msg, bytes) else msg
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return text, None
    if not isinstance(obj, dict):
        return text, None

    keys = ",".join(sorted(str(k) for k in obj))
    name = next((obj[k] for k in _NAME_KEYS if obj.get(k)), None)
    body = next((obj[k] for k in _BODY_KEYS if obj.get(k)), None)
    if body is not None:
        body_text = str(body)
        if name:
            # Reconstructed into the RenPy "Name: body" form, which the
            # parser already understands, so a JSON hook and a plain-text
            # hook take exactly the same path from here on.
            return f"{name}: {body_text}", keys
        return body_text, keys
    if isinstance(obj.get("data"), str):
        return obj["data"], keys
    return "", keys


def check_and_fix_proxy() -> list[str]:
    """Guard against a proxy swallowing the loopback connection.

    A Windows proxy that does not bypass 127.0.0.1 answers the websocket
    handshake with a ``CONNECT`` request, and the symptom is
    ``got CONNECT`` plus a connection that never establishes. The fix is
    environmental, so this reports rather than raises: a warning the user
    can act on beats an adapter that refuses to start.

    Returns the list of warnings found. Also sets ``NO_PROXY`` for this
    process, because we can fix that half ourselves.
    """
    warnings: list[str] = []
    proxy_vars = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    active = [v for v in proxy_vars if os.environ.get(v)]
    no_proxy = (os.environ.get("NO_PROXY", "") or os.environ.get("no_proxy", "")).lower()

    if any("127.0.0.1" in os.environ[v] or "localhost" in os.environ[v] for v in active):
        warnings.append(
            f"Proxy environment variable(s) {', '.join(active)} point at localhost; "
            "the hook connection will fail. Remove 127.0.0.1/localhost from them."
        )
    elif active and "127.0.0.1" not in no_proxy and "localhost" not in no_proxy:
        warnings.append(
            "A system/environment proxy is active and localhost is not in NO_PROXY. "
            "The hook handshake will be answered with CONNECT. "
            "Set NO_PROXY=127.0.0.1,localhost (done for this process)."
        )
        merged = f"{no_proxy},127.0.0.1,localhost".strip(",")
        os.environ["NO_PROXY"] = merged
        os.environ["no_proxy"] = merged

    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["netsh", "winhttp", "show", "proxy"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        if out and "Proxy Server" in out and "Direct access" not in out:
            warnings.append(
                "A WinHTTP proxy is active and can intercept localhost. "
                f"Fix with 'netsh winhttp reset proxy' (admin) or add 127.0.0.1 to the bypass.\n{out.strip()}"
            )
    return warnings


# ---------------------------------------------------------------------------
# Line handling (pure, but stateful)
# ---------------------------------------------------------------------------


class HookTextProcessor:
    """Turns raw hook lines into :class:`Dialogue` objects.

    Holds the dual-hook name buffer, which is the only mutable state in
    the Luna path. Every method here is synchronous and I/O-free, so the
    whole decision chain can be tested by calling ``push`` in a loop with
    no server, no client, and no threads.

    One instance serves one connection. Textractor interleaves lines
    across clients (a second hook for a second frame), and a shared buffer
    would then merge a name from one game with a line from another.
    """

    def __init__(
        self,
        *,
        min_text_length: int,
        space_form: bool = True,
        dual_hook: bool = False,
        known_names: Iterable[str] = (),
        source: str = "luna",
    ) -> None:
        self.min_text_length = min_text_length
        self.dual_hook = dual_hook
        self.source = source
        self.parser = LunaParser(known_names=known_names, space_form=space_form)
        self._pending_name: str | None = None
        self._pending_since = 0.0

    def set_known_names(self, names: Iterable[str]) -> None:
        """Sync the parser's registry-backed name set (case-insensitive)."""
        self.parser.set_known_names(names)

    @property
    def known_names(self) -> tuple[str, ...]:
        return self.parser.known_names

    @property
    def pending_name(self) -> str | None:
        """The buffered dual-hook name, for diagnostics and tests."""
        return self._pending_name

    def is_name_only(self, text: str) -> bool:
        """True if ``text`` is a bare speaker name rather than dialogue.

        A line without a colon is ambiguous. "Lina" alone is a name;
        "Rick Hello" is two words of space-form dialogue, and "Hello
        there" is a sentence. There is no way to tell those apart from
        the line alone, so the rule is *positive evidence*: a colon is
        explicit ("Rick:"), a single plausible word is unambiguous enough
        on its own, and a bare multi-word line has to be a registered
        name or it is treated as dialogue.

        That last rule is the one that matters. Guessing on multi-word
        lines means "Rick Hello" gets buffered as a name, the *body* line
        arrives and is buffered as a name too, and the merge never fires:
        every line silently disappears instead of being misattributed.
        Requiring the registry keeps the two-word-name case working
        ("Miss Brooks", once registered) without eating dialogue.

        Terminal punctuation ("Yes." is a sentence), a lowercase start
        ("yes" is a reply) and length are rejected outright.
        """
        has_colon = text.rstrip().endswith(":")
        candidate = text.rstrip().rstrip(":").strip()
        if not candidate or len(candidate) > 20:
            return False
        if _TERMINAL_PUNCT.search(candidate):
            return False
        if not candidate[:1].isupper():
            return False
        if not _NAME_ONLY.match(candidate):
            return False
        words = candidate.split()
        registered = self._registered(candidate)
        if len(words) > 1 and not has_colon and registered is None:
            return False
        if not all(self._word_is_a_name(w) for w in words):
            return False
        # Ask the parser whether "Name: x" would come back with that name
        # as the speaker. It returns None for a stopword or a UI pattern,
        # and a mismatch when the registry or heuristics disagree.
        parsed = self.parser.parse(f"{candidate}: x")
        return parsed is not None and parsed.speaker == (registered or candidate)

    def _registered(self, name: str) -> str | None:
        """The registry spelling of ``name``, or None if it is not known."""
        known = {n.lower(): n for n in self.parser.known_names}
        return known.get(name.lower())

    def _word_is_a_name(self, word: str) -> bool:
        """True if ``word`` alone could be a speaker name.

        A registered name counts even where the heuristic would refuse it,
        same contract as the parser: the user overriding the word lists
        is the one signal that beats them.
        """
        if self._registered(word) is not None:
            return True
        return is_plausible_character_name(word)

    def push(self, raw: str) -> list[Dialogue]:
        """Process one decoded line. Returns the dialogues to speak (0..n).

        ``raw`` is kept untouched on every Dialogue it returns, so stripping
        here costs the forensic record nothing.
        """
        # Rich text first, and before the length gate: "<b>Tatsuo</b>" is 15
        # characters of which 6 are the name, and the tags must be gone
        # before is_name_only or the parser can see the name. Measured F14:
        # 16 of the 90 multiline payloads in the user's log were this shape
        # and all 16 were read aloud as narration without this line.
        text = strip_markup(raw).strip()
        if not text or len(text) < self.min_text_length:
            return []
        # A RenPy traceback is a crash dump, not dialogue. Checked first and
        # always on: some games route their error log through the same hook
        # as their dialogue, and a traceback read aloud is unmissable.
        if is_renpy_exception(text):
            log.debug("Skipping RenPy exception dump on the hook: %r", text[:80])
            return []

        name_only = self.is_name_only(text)
        if self.dual_hook:
            if name_only:
                self._pending_name = text.rstrip().rstrip(":").strip()
                self._pending_since = time.monotonic()
                log.debug("Hook dual-hook: buffered name %r", self._pending_name)
                return []
            if self._pending_name is not None:
                if time.monotonic() - self._pending_since <= _PENDING_NAME_TTL:
                    text = f"{self._pending_name}: {text}"
                self._pending_name = None
        elif name_only:
            # A bare name is a name with no dialogue attached, so there is
            # nothing to speak. The parser would otherwise read "Rick:" as
            # narration and say the word "Rick" out loud, and "Rick" with a
            # space form would read as a line of its own. Dropping it is
            # right whether or not the merge is enabled: without dual_hook
            # the body is coming as a separate unnamed line anyway, and
            # speaking the name alone is never what the user wants.
            log.debug("Dropping name-only hook line %r (dual_hook is off)", text)
            return []

        # parse_turns handles the colon form, the space form, and the
        # multi-speaker line, and returns [] for a line that is not
        # dialogue at all (game chrome). The donor ran parse_renpy first
        # and fell back to parse_luna; that ordering drops space-form
        # lines that happen to contain a colon, and the RenPy parser is
        # the stricter of the two, so the fallback never recovered them.
        # replace(), not a hand rebuild. A hand rebuild here silently
        # dropped `speaker_is_guess`, which made the F4 trust gate inert
        # on this -- the only path the hook actually uses. replace() copies
        # every field, so the next field added to Dialogue is carried too.
        return [
            replace(d, source=self.source, raw=raw)
            for d in self.parser.parse_turns(text)
            if d.is_voiceable
        ]


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class LunaAdapter(InputAdapter):
    """Websocket input adapter for LunaTranslator / Textractor.

    Owns a private event loop on a daemon thread and, separately, a
    dispatch thread. Nothing slow runs on the event loop: see the module
    docstring for why that is the whole point of this class.

    In server mode (the default) NovaTTS listens and the hook connects.
    Setting ``luna_ws_url`` inverts that: NovaTTS connects out to a hook
    that listens itself, which is what the ``textractor_websocket``
    extension does (D39). Both directions are supported, and neither is
    deprecated or rare.
    """

    def __init__(self, on_dialogue: DialogueCallback) -> None:
        super().__init__(on_dialogue)
        self.host = settings.hook_host
        self.port = settings.hook_port
        self.ws_url = _dialable_ws_url(settings.luna_ws_url)
        self.space_form = settings.hook_space_form
        self.dual_hook = settings.hook_dual_hook
        self.min_text_length = settings.min_text_length

        self._running = False
        #: Set by the event loop once the adapter is really up: the socket is
        #: bound in server mode, the loop has entered client mode otherwise.
        #: ``start`` waits on this so the "started" line cannot be written
        #: for an adapter that never came up.
        self._ready = threading.Event()
        #: Why the loop failed, if it did. Empty means "no reason reported".
        self._startup_error = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: websockets.asyncio.server.Server | None = None
        self._stop: asyncio.Event | None = None
        self._thread: threading.Thread | None = None
        self._dispatch_thread: threading.Thread | None = None
        self._queue: queue.Queue[Dialogue] = queue.Queue(maxsize=_DISPATCH_QUEUE_SIZE)
        #: One processor per connection, keyed by connection identity.
        #: See :class:`HookTextProcessor` for why this is not a single
        #: shared object.
        self._processors: dict[int, HookTextProcessor] = {}
        self._client_lock = threading.Lock()
        self._clients = 0
        #: Counts lines dropped because the dispatch queue was full. Non-
        #: zero means synthesis is falling behind the hook, which is a
        #: different problem from a hook that is not arriving.
        self.dropped = 0
        #: The last line the hook delivered, before any parsing. Kept
        #: because "nothing arrives" and "arrives and is misparsed" look
        #: identical from the outside.
        self.last_raw = ""

    # -- InputAdapter ----------------------------------------------------

    @property
    def name(self) -> str:
        return "luna"

    @property
    def client_count(self) -> int:
        with self._client_lock:
            return self._clients

    def is_running(self) -> bool:
        return self._running

    def set_known_speakers(self, names: Iterable[str]) -> None:
        """Sync every connected processor's registry-backed name set.

        Each client has its own :class:`HookTextProcessor`, so a speaker
        added while three games are connected has to reach all three --
        otherwise a newly registered character stays unrecognised on the
        games that were already attached.
        """
        for proc in self._processors.values():
            proc.set_known_names(names)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for warning in check_and_fix_proxy():
            log.warning("Hook proxy warning: %s", warning)

        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, name="luna-dispatch", daemon=True
        )
        self._dispatch_thread.start()

        self._ready.clear()
        self._startup_error = ""
        self._thread = threading.Thread(target=self._run, name="luna-adapter", daemon=True)
        self._thread.start()

        # The mode is known here; whether the adapter *works* is only known
        # in the loop. F14 logged "started" before the loop had done anything
        # at all, so a hook that never bound looked exactly like a healthy
        # one in every field the UI shows. Not fatal either way -- in "both"
        # mode the clipboard still delivers text -- so it is reported loudly
        # rather than raised.
        mode = "client" if self.ws_url else "server"
        came_up = self._ready.wait(timeout=_STARTUP_TIMEOUT) and not self._startup_error
        if came_up:
            log.info("Luna hook adapter started (%s %s:%s)", mode, self.host, self.port)
        else:
            log.error(
                "Luna hook adapter did not come up in %s mode within %.1fs (%s); "
                "the hook will not deliver text",
                mode,
                _STARTUP_TIMEOUT,
                self._startup_error or "no reason reported",
            )

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        # Resolve the stop event from inside the loop: the loop is parked
        # on it, so poking it from this thread is what makes shutdown
        # prompt instead of waiting for the next wakeup.
        if self._loop is not None and self._stop is not None:
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._dispatch_thread is not None:
            self._dispatch_thread.join(timeout=2.0)
            self._dispatch_thread = None
        self._loop = None
        self._server = None
        self._stop = None
        log.info("Luna hook adapter stopped")

    # -- Event loop ------------------------------------------------------

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stop = asyncio.Event()
        try:
            if self.ws_url:
                loop.run_until_complete(self._client_loop())
            else:
                loop.run_until_complete(self._server_loop())
        except Exception as exc:
            # The adapter must never take the host process down; the
            # contract is in InputAdapter's docstring. The reason is kept
            # so ``start`` can say *why* instead of only that it timed out.
            self._startup_error = f"{type(exc).__name__}: {exc}"
            self._ready.set()
            log.exception("Luna hook loop failed (swallowed)")
        finally:
            with contextlib.suppress(Exception):
                loop.close()

    async def _server_loop(self) -> None:
        assert self._stop is not None
        server = await websockets.asyncio.server.serve(self._handle_client, self.host, self.port)
        self._server = server
        # Only now is the socket really accepting connections. This is the
        # point ``start`` waits for.
        self._ready.set()
        log.info("Hook server listening on ws://%s:%s", self.host, self.port)
        await self._stop.wait()
        server.close()
        await server.wait_closed()

    async def _client_loop(self) -> None:
        assert self._stop is not None
        # Signalled on entry, not on first connect: whether the hook is
        # actually reachable is a different question, answered by
        # ``client_count`` in the status endpoint, and blocking ``start`` on
        # a dial to a hook that may not be running yet would be wrong.
        self._ready.set()
        while self._running:
            try:
                async with websockets.asyncio.client.connect(self.ws_url) as ws:
                    # Client mode has no _handle_client, so the processor
                    # that a server connection would have built is made
                    # here, with the same settings -- and registered in
                    # _processors, because that dict is what
                    # set_known_speakers() walks. Leaving it out is silent:
                    # a speaker added in the GUI then never reaches the
                    # parser and every character name stays a guess.
                    proc = HookTextProcessor(
                        min_text_length=self.min_text_length,
                        space_form=self.space_form,
                        dual_hook=self.dual_hook,
                    )
                    self._processors[id(ws)] = proc
                    # client_count answers "how many hook connections are
                    # open", and here there is exactly one. Between retry
                    # attempts it is 0 again, because then there is none --
                    # which is the whole point of the number: the Hook card
                    # has to be able to say the link is up.
                    with self._client_lock:
                        self._clients = 1
                    log.info("Hook client connected to %s", self.ws_url)
                    try:
                        await self._pump_until_stopped(ws, proc)
                    finally:
                        self._processors.pop(id(ws), None)
                        with self._client_lock:
                            self._clients = 0
                        log.info("Hook client disconnected from %s", self.ws_url)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    return
                # A hook that is not up yet is the normal startup state,
                # so this is a debug line and not a warning; a proxy is
                # the likely cause and check_and_fix_proxy() already said
                # so at start.
                log.debug("Hook client %s not connected: %s", self.ws_url, exc)
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)

    async def _handle_client(self, websocket: ServerConnection) -> None:
        # One processor per connection: Textractor interleaves lines across
        # clients, and a shared dual-hook buffer would merge a name from
        # one game with a line from another.
        proc = HookTextProcessor(
            min_text_length=self.min_text_length,
            space_form=self.space_form,
            dual_hook=self.dual_hook,
        )
        with self._client_lock:
            self._clients += 1
            count = self._clients
        self._processors[id(websocket)] = proc
        log.info("Hook client connected (%d total)", count)
        try:
            await self._pump(websocket, proc)
        except Exception as exc:
            log.debug("Hook client error: %s", exc)
        finally:
            with self._client_lock:
                self._clients = max(0, self._clients - 1)
                remaining = self._clients
            self._processors.pop(id(websocket), None)
            log.info("Hook client disconnected (%d left)", remaining)

    async def _pump_until_stopped(
        self, websocket: object, proc: HookTextProcessor
    ) -> None:
        """Pump frames until the peer closes **or** ``stop()`` was called.

        ``_pump`` parks in ``async for message in websocket``, which never
        looks at the stop event: with the connection open and quiet the
        event is set and nothing reads it, so ``stop()`` waits out its
        whole join timeout, gives up, and returns while the adapter thread
        is still alive and ``is_running()`` already says otherwise.

        Racing the pump against the event is what makes shutdown prompt.
        The server path does not need this -- ``_server_loop`` parks on the
        event itself -- so this stays a client-mode concern.
        """
        assert self._stop is not None
        pump = asyncio.ensure_future(self._pump(websocket, proc))
        stopper = asyncio.ensure_future(self._stop.wait())
        try:
            await asyncio.wait({pump, stopper}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (pump, stopper):
                task.cancel()
            await asyncio.gather(pump, stopper, return_exceptions=True)
        # _pump's errors still have to reach _client_loop's handler, which
        # logs them and backs off before the next attempt.
        exc = None if pump.cancelled() else pump.exception()
        if exc is not None:
            raise exc

    async def _pump(self, websocket: object, proc: HookTextProcessor) -> None:
        """Read frames until the peer closes, decoding and enqueueing.

        Runs on the event loop, so it must stay short: decode, filter,
        enqueue, return. The dispatch thread does everything else.
        """
        async for message in websocket:  # type: ignore[attr-defined]
            if not self._running:
                break
            text, keys = decode_wire_message(message)
            if keys is None:
                log.debug("Hook raw: text -> %r", text[:90])
            else:
                log.debug("Hook raw: JSON keys=%s -> %r", keys, text[:90])
            if not text.strip():
                continue
            self.last_raw = text
            for dialogue in proc.push(text):
                self._enqueue(dialogue)

    # -- Dispatch --------------------------------------------------------

    def _enqueue(self, dialogue: Dialogue) -> None:
        try:
            self._queue.put_nowait(dialogue)
        except queue.Full:
            # Dropping is the right failure here. Blocking would stop the
            # event loop, which is the bug this design exists to avoid;
            # growing without bound would trade a dropped line for an
            # out-of-memory hours later.
            self.dropped += 1
            log.warning(
                "Hook dispatch queue full, dropped %d line(s) so far. "
                "Synthesis is not keeping up with the hook.",
                self.dropped,
            )

    def _dispatch_loop(self) -> None:
        while self._running:
            try:
                dialogue = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.on_dialogue(dialogue)
            except Exception:
                log.exception("on_dialogue callback failed (swallowed)")
