"""OSC client for AbletonOSC (Phase 02, issue #4).

Protocol facts this module relies on (AbletonOSC commit 0ca68214, checked 2026-10-28; see
``docs/research/2026-10-28_abletonosc-protocol-and-create-audio-clip.md``):

- AbletonOSC listens on UDP 11000 and sends every reply to the *sender's host* on the fixed
  port 11001 (``abletonosc/osc_server.py`` ``process_message``; README "Usage"). The client
  therefore binds 11001 and sends from that same socket.
- A query is answered on the same OSC address. Messages carry no request id.
- Song property getters echo any extra arguments after the value (``handler.py``
  ``_get_property`` returns ``(value, *params)``).
- Methods and setters (``/live/song/undo``, ``/live/track/set/mute``) send no reply.
- Unknown addresses and exceptions inside a handler are relayed as ``/live/error <message>``
  (``manager.py`` ``LiveOSCErrorLogHandler``).
- Datagrams are processed in arrival order on Live's main thread, once per ~100 ms tick
  (``manager.py`` ``tick``, ``osc_server.py`` ``process``).
- Live with no AbletonOSC listening looks the same as Live closed: on Windows the next receive
  raises ``ConnectionResetError`` (ICMP port unreachable); on Linux the request times out.

Request correlation. Every request is sent as ``marker(start) + payload + marker(end)``, where a
marker is ``/live/song/get/tempo <nonce>`` and each nonce is new. Because AbletonOSC processes
in order, exactly the messages that arrive between the echo of ``start`` and the echo of
``end`` belong to this request. Anything before ``start`` (late replies or errors from an
earlier, timed-out request) is discarded. A write counts as confirmed only when ``end`` comes
back with no ``/live/error`` in between. Assumption: loopback UDP keeps datagram order; the
OS does not guarantee this, but no reordering is known on loopback.

Only :class:`AbletonBridge` may be used by other modules (enforced by
``tests/bridge/test_capabilities.py::test_only_osc_client_uses_the_transport``). It checks
the capability gate before any network I/O.
"""

from __future__ import annotations

import ipaddress
import itertools
import logging
import math
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

from bridge.capabilities import CapabilityGate, CapabilityRegistry

DEFAULT_HOST = "127.0.0.1"
DEFAULT_SEND_PORT = 11000
DEFAULT_RECEIVE_PORT = 11001
# AbletonOSC polls its socket once per 100 ms tick; Live's GUI thread can add delay.
DEFAULT_TIMEOUT_S = 1.0

ERROR_ADDRESS = "/live/error"
# Marker for request bracketing: a harmless read whose handler echoes extra arguments.
MARKER_ADDRESS = "/live/song/get/tempo"

# Capability id -> OSC address(es). Cited from the AbletonOSC README tables and source.
ADDRESSES: dict[str, tuple[str, ...]] = {
    # -- Arrangement capability check (#140): registry status `unknown` until the user's run.
    # File:line at AbletonOSC commit 0ca68214 (re-read 2026-10-29 from raw.githubusercontent).
    # song.py:25 (method list), :47-48 (``partial(self._call_method, self.song, method)``);
    # README "Song API": ``/live/song/create_midi_track index`` (-1 = end). No reply.
    "song.create_midi_track": ("/live/song/create_midi_track",),
    # track.py:41 (``properties_r``), :66-68 (``_get_property``) -> ``track_id, value``.
    "track.has_midi_input.get": ("/live/track/get/has_midi_input",),
    # track.py:123-127, :136-137: ``track_id, *start_times`` / ``track_id, *lengths``.
    "track.arrangement_clips.get": ("/live/track/get/arrangement_clips/start_time",
                                    "/live/track/get/arrangement_clips/length"),
    # song.py:84 (``properties_r``), :89-90 -> ``is_playing``.
    "song.is_playing.get": ("/live/song/get/is_playing",),
    # song.py:57 (``properties_rw``), :89-90 get, :93-94 set (``setattr``, no reply). Beats.
    "song.current_song_time.get": ("/live/song/get/current_song_time",),
    "song.current_song_time.set": ("/live/song/set/current_song_time",),
    # song.py:241-245: flat ``name, time, name, time, ...``.
    "song.cue_points.get": ("/live/song/get/cue_points",),
    # song.py:258: ``Song.set_or_delete_cue()``, a TOGGLE at the current song time (an existing
    # locator there is deleted). Callers must read the cue points first. No reply.
    "song.cue_point.add_or_delete": ("/live/song/cue_point/add_or_delete",),
    # song.py:259-264: ``song.cue_points[index].name = name``. No reply.
    "song.cue_point.set_name": ("/live/song/cue_point/set/name",),
    # -- end of #140 entries
    "app.version": ("/live/application/get/version",),
    "song.tempo.get": ("/live/song/get/tempo",),
    "song.signature.get": (
        "/live/song/get/signature_numerator",
        "/live/song/get/signature_denominator",
    ),
    "song.track_names.get": ("/live/song/get/track_names",),
    "track.mute.set": ("/live/track/set/mute",),
    # README "Track API": ``/live/track/get/mute track_id`` -> ``track_id, mute``; source
    # ``abletonosc/track.py`` ``properties_rw`` contains "mute". Own registry entry since #42.
    "track.mute.get": ("/live/track/get/mute",),
    "song.undo": ("/live/song/undo",),
    # README "Song API": ``/live/song/create_audio_track index`` (-1 = end); source
    # ``abletonosc/song.py`` line 24 (method list, generic ``_call_method``, no reply).
    "song.create_audio_track": ("/live/song/create_audio_track",),
    # The four reads below are the pre-checks and read-backs of the clip import (#50). Until
    # #143 they borrowed the clip_slot.create_audio_clip gate; now each has its own entry.
    # README "Track API": ``/live/track/get/has_audio_input track_id`` -> ``track_id,
    # has_audio_input``; source ``abletonosc/track.py`` line 39 (``properties_r``).
    "track.has_audio_input.get": ("/live/track/get/has_audio_input",),
    # README "Clip Slot API": ``/live/clip_slot/get/has_clip track_index, clip_index`` ->
    # ``track_index, clip_index, has_clip``; source ``abletonosc/clip_slot.py`` line 34.
    "clip_slot.has_clip.get": ("/live/clip_slot/get/has_clip",),
    # README "Clip API": ``/live/clip/get/file_path track_id, clip_id`` -> ``track_id,
    # clip_id, file_path``; source ``abletonosc/clip.py`` line 74 (``properties_r``).
    "clip.file_path.get": ("/live/clip/get/file_path",),
    # README "Song API": ``/live/song/get/num_scenes`` -> ``num_scenes``; source
    # ``abletonosc/song.py`` line 228.
    "song.num_scenes.get": ("/live/song/get/num_scenes",),
}

# Capabilities that AbletonOSC does not expose itself and that the AbeltonGod extension adds
# (``scripts/install_abletonosc_extension.py``, #50): {cap_id: (addresses, registry target)}.
# The registry still records the LOM call as target; a later contract-change PR may switch it
# to the OSC address (then the entry moves into ADDRESSES).
#
# ``/live/clip_slot/create_audio_clip track_index, clip_index, path``: the extension adds
# "create_audio_clip" to the ``methods`` list of ``abletonosc/clip_slot.py`` (lines 27-32 at
# commit 0ca68214). Lines 46-48 register ``/live/clip_slot/<method>`` with
# ``create_clip_slot_callback(self._call_method, method)``; lines 12-14 resolve
# ``song.tracks[track_index].clip_slots[clip_index]``; line 19 passes ``params[2:]``, so
# ``handler.py`` ``_call_method`` (lines 27-29) calls ``clip_slot.create_audio_clip(path)``
# and sends no reply. LOM: "Given an absolute path to a valid audio file in a supported
# format, creates an audio clip that references the file in the clip slot. Throws an error if
# the clip slot doesn't belong to an audio track or if the track is frozen."
# (docs.cycling74.com/apiref/lom/clipslot/, checked 2026-10-28).
EXTENSION_ADDRESSES: dict[str, tuple[tuple[str, ...], str]] = {
    "clip_slot.create_audio_clip": (
        ("/live/clip_slot/create_audio_clip",),
        "LOM ClipSlot.create_audio_clip(path)",
    ),
    # #140, extension 0.2.0 (patch of abletonosc/track.py): "create_midi_clip" in the
    # ``methods`` list (track.py:32-35), registered at :62-64 with
    # ``create_track_callback(self._call_method, method)``; :18-25 resolve
    # ``song.tracks[int(params[0])]`` and pass ``params[1:]``, so handler.py:27-29 calls
    # ``track.create_midi_clip(start_time, length)``. No reply. LOM Track.create_midi_clip:
    # errors on non-MIDI or frozen tracks and outside [0, 1576800].
    "track.create_midi_clip": (
        ("/live/track/create_midi_clip",),
        "LOM Track.create_midi_clip(start_time, length)",
    ),
    # #140: own handlers in track.py (after :109), because every /live/clip/* handler resolves
    # ``track.clip_slots[i].clip`` (clip.py:53-55): Session clips only. They use
    # ``track.arrangement_clips[i]`` and the same calls as clip.py:139 and :145-155.
    "arrangement_clip.notes.add": (
        ("/live/track/arrangement_clip/add/notes",),
        "AbeltonGod extension: Clip.add_new_notes on track.arrangement_clips[i]",
    ),
    "arrangement_clip.notes.get": (
        ("/live/track/arrangement_clip/get/notes",),
        "AbeltonGod extension: Clip.get_notes_extended on track.arrangement_clips[i]",
    ),
}

# Addresses the bridge sends that have no registry entry of their own YET, with the capability
# whose gate they borrow: {cap_id: (addresses, borrowed_cap_id)}. Each must get its own entry
# in a contract-change PR (then it moves into ADDRESSES; ``test_capabilities.py`` fails until
# it does). Empty since #143 (the four clip-import reads of #50 moved into ADDRESSES).
PENDING_REGISTRY: dict[str, tuple[tuple[str, ...], str]] = {}

# The three addresses the track.py extension adds (probe: all must answer).
ARRANGEMENT_EXTENSION = ("track.create_midi_clip", "arrangement_clip.notes.add",
                         "arrangement_clip.notes.get")

# LOM Track.create_midi_clip / create_audio_clip: "start_time ... in [0, 1576800]" (beats).
ARRANGEMENT_MAX_BEATS = 1576800.0

# Text AbletonOSC puts in ``/live/error`` for an address without a handler: ``osc_server.py``
# line 125 logs "AbletonOSC: Unknown OSC address: <addr>" at ERROR, and ``manager.py`` lines
# 55-58 relay the text after the first ": ".
UNKNOWN_ADDRESS_ERROR = "Unknown OSC address"

OscArg = int | float | str
Message = tuple[str, tuple]

logger = logging.getLogger("abeltongod.bridge.osc")


class BridgeError(Exception):
    """Base class for bridge errors."""


class BridgeUnavailableError(BridgeError):
    """AbletonOSC did not answer. See the subclass for how this was detected."""


class BridgeTimeoutError(BridgeUnavailableError):
    """No complete answer within the timeout.

    For a write, the outcome is **unknown**: the message may still be queued in Live (for
    example behind a dialog) and be applied later. Read the state back before acting on the
    assumption that nothing happened — in particular before sending an undo.

    ``request_id`` (set by :class:`OscTransport`) names the timed-out request for
    :meth:`OscTransport.late_reply`.
    """

    request_id: str | None = None


@dataclass(frozen=True)
class LateReply:
    """What later requests saw of a timed-out request's own reply (#140).

    After a timeout the request's echoes may still arrive; the next requests discard them as
    stale, and record them here. ``end_after_s``: seconds from the send to the moment the
    client read the end-marker echo (an upper bound when it was read while draining).
    A missing echo does not show that the request was not processed (the datagram may be
    lost); an echo does not show that Live's state changed as intended.
    """

    start_seen: bool
    end_seen: bool
    errors: tuple[str, ...]
    end_after_s: float | None


@dataclass
class _Pending:
    start: str
    end: str
    sent_at: float
    started: bool
    finished: bool = False  # the end echo was seen
    closed: bool = False  # nothing more can belong to this request
    errors: list[str] = field(default_factory=list)
    end_after_s: float | None = None

    def snapshot(self) -> LateReply:
        return LateReply(self.started, self.finished, tuple(self.errors), self.end_after_s)


LATE_TRACKED = 8  # timed-out requests whose late echoes are recorded (oldest dropped)


class LiveNotReachableError(BridgeUnavailableError):
    """The OS reported that nothing listens on the send port (Windows ICMP reset)."""


class AbletonOSCError(BridgeError):
    """AbletonOSC reported an error via ``/live/error`` for this request."""


class BridgeProtocolError(BridgeError):
    """A reply arrived but its content is not what the protocol promises."""


class ReceivePortInUseError(BridgeError):
    """The reply port is already bound by another program."""


class ExtensionMissingError(AbletonOSCError):
    """AbletonOSC has no handler for an extension address (the AbeltonGod patch is missing)."""


def _hint(host: str, send_port: int) -> str:
    return (
        f"AbletonOSC on {host}:{send_port} did not answer. Check: (1) Ableton Live is running; "
        "(2) 'AbletonOSC' is selected as Control Surface in Settings > Link, Tempo & MIDI; "
        "(3) no modal dialog is open in Live; (4) the AbletonOSC log "
        "(Remote Scripts\\AbletonOSC\\logs\\abletonosc.log). Live closed and script not "
        "selected cannot be told apart from here."
    )


def _check_timeout(value: object, name: str = "timeout_s") -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a positive finite number (got {value!r})")
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{name} must be a positive finite number (got {value!r})")
    return float(value)


class OscTransport:
    """Serialised, bracketed request/response over one loopback UDP socket.

    Not capability-checked. Only :class:`AbletonBridge` and tests may use it.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        send_port: int = DEFAULT_SEND_PORT,
        receive_port: int = DEFAULT_RECEIVE_PORT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except ValueError:
            raise ValueError(
                f"host must be a loopback IP address (got {host!r}); remote Live is out of scope"
            ) from None
        for name, port in (("send_port", send_port), ("receive_port", receive_port)):
            if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
                raise ValueError(f"{name} must be an int in 0..65535 (got {port!r})")
        if send_port == 0:
            raise ValueError("send_port must not be 0")

        self.host = host
        self.send_port = send_port
        self.timeout_s = _check_timeout(timeout_s)
        self._clock = clock
        self._lock = threading.Lock()
        self._counter = itertools.count()
        self._nonce_prefix = f"abg-{os.getpid()}-{secrets.token_hex(4)}"
        self._pending: dict[str, _Pending] = {}  # timed-out requests by end nonce, oldest first

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No SO_REUSEADDR: a second client on 11001 should fail loudly, not share replies.
            sock.bind((host, receive_port))
        except OSError as exc:
            sock.close()
            raise ReceivePortInUseError(
                f"cannot bind reply port {host}:{receive_port} ({exc}). Another OSC client "
                "(or a second copy of this program) is probably using it."
            ) from exc
        self._sock = sock
        self.receive_port: int = sock.getsockname()[1]

    # -- lifecycle ---------------------------------------------------------------------------

    def close(self) -> None:
        self._sock.close()

    def __enter__(self) -> OscTransport:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- requests ----------------------------------------------------------------------------

    def query(
        self,
        address: str,
        params: Sequence[OscArg] = (),
        *,
        expect_prefix: Sequence[OscArg] = (),
        timeout_s: float | None = None,
    ) -> tuple:
        """Send ``address`` and return its reply arguments, without ``expect_prefix``."""
        prefix = tuple(expect_prefix)
        for msg_address, args in self._exchange([(address, tuple(params))], timeout_s):
            if msg_address == address and args[: len(prefix)] == prefix:
                return args[len(prefix):]
        raise BridgeProtocolError(f"AbletonOSC processed {address} but sent no matching reply")

    def send_confirmed(
        self, address: str, params: Sequence[OscArg] = (), *, timeout_s: float | None = None
    ) -> None:
        """Send and wait until AbletonOSC has processed it without reporting an error.

        This does not prove that Live's state changed as intended; read it back if it matters.
        On :class:`BridgeTimeoutError` the write may still be applied later (see there).
        """
        self._exchange([(address, tuple(params))], timeout_s)

    def ping(self, *, timeout_s: float | None = None) -> None:
        """Marker round trip only. Raises a :class:`BridgeUnavailableError` on failure."""
        self._exchange([], timeout_s)

    def late_reply(self, request_id: str | None) -> LateReply | None:
        """What later requests have seen of the timed-out request ``request_id`` so far.

        ``None`` if the id is unknown (never timed out, or one of more than ``LATE_TRACKED``
        newer timeouts pushed it out). Only requests sent after the timeout read the socket,
        so call this after at least one later request.
        """
        with self._lock:
            pending = self._pending.get(request_id) if request_id is not None else None
            return pending.snapshot() if pending is not None else None

    # -- internals ---------------------------------------------------------------------------

    def _exchange(self, payload: list[Message], timeout_s: float | None) -> list[Message]:
        timeout = self.timeout_s if timeout_s is None else _check_timeout(timeout_s)
        for address, params in payload:
            self._validate(address, params)
        with self._lock:
            self._drain()
            deadline = self._clock() + timeout
            start, end = self._nonce(), self._nonce()
            self._send(MARKER_ADDRESS, (start,))
            for address, params in payload:
                self._send(address, params)
            self._send(MARKER_ADDRESS, (end,))
            sent_at = self._clock()

            started = False
            between: list[Message] = []
            try:
                while True:
                    for msg_address, args in self._receive(deadline):
                        if msg_address == MARKER_ADDRESS and len(args) == 2:
                            if args[1] == start:
                                started = True
                                self._close_pending()
                                continue
                            if args[1] == end:
                                if not started:
                                    raise BridgeProtocolError(
                                        "end marker arrived before start marker")
                                return between
                        if not started:
                            logger.debug("discarding stale OSC message %s %r", msg_address, args)
                            self._note_stale(msg_address, args)
                            continue
                        if msg_address == ERROR_ADDRESS:
                            detail = args[0] if args else "<no message>"
                            raise AbletonOSCError(f"AbletonOSC reported an error: {detail}")
                        between.append((msg_address, args))
            except BridgeTimeoutError as exc:
                self._pending[end] = _Pending(start, end, sent_at, started)
                while len(self._pending) > LATE_TRACKED:
                    del self._pending[next(iter(self._pending))]
                exc.request_id = end
                raise

    def _note_stale(self, address: str, args: tuple) -> None:
        """Attribute a stale message to a timed-out request.

        Loopback keeps the order (research note 2026-10-28, assumptions), so a message between
        a request's two marker echoes belongs to that request, and once the start echo of any
        later request has been seen, an earlier request's window is over (its end echo is
        lost); nothing after that is attributed to it.
        """
        if address == MARKER_ADDRESS and len(args) == 2:
            later = False
            for p in reversed(self._pending.values()):  # newest first
                if later:
                    p.closed = True
                elif args[1] == p.start:
                    p.started, later = True, True
                elif args[1] == p.end and not p.closed:
                    p.finished = p.closed = True
                    p.end_after_s = self._clock() - p.sent_at
            return
        if address == ERROR_ADDRESS:
            for p in self._pending.values():
                if p.started and not p.closed:
                    p.errors.append(str(args[0]) if args else "<no message>")

    def _close_pending(self) -> None:
        """The current request's start echo arrived: every earlier window is over."""
        for p in self._pending.values():
            p.closed = True

    def _nonce(self) -> str:
        return f"{self._nonce_prefix}-{next(self._counter)}"

    @staticmethod
    def _validate(address: str, params: Sequence[OscArg]) -> None:
        if not isinstance(address, str) or not address.startswith("/"):
            raise ValueError(f"OSC address must be a string starting with '/' (got {address!r})")
        for p in params:
            # bool is an int subclass but python-osc would encode it as T/F, which AbletonOSC
            # setters do not expect. Callers convert to 0/1.
            if isinstance(p, bool) or not isinstance(p, int | float | str):
                raise ValueError(f"unsupported OSC argument {p!r} ({type(p).__name__})")
            if isinstance(p, float) and not math.isfinite(p):
                raise ValueError(f"non-finite OSC argument {p!r}")

    def _send(self, address: str, params: Sequence[OscArg]) -> None:
        builder = OscMessageBuilder(address=address)
        for p in params:
            builder.add_arg(p)
        try:
            self._sock.sendto(builder.build().dgram, (self.host, self.send_port))
        except ConnectionResetError as exc:
            raise LiveNotReachableError(_hint(self.host, self.send_port)) from exc

    def _receive(self, deadline: float) -> list[Message]:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise BridgeTimeoutError("no complete answer within the timeout. "
                                     + _hint(self.host, self.send_port))
        self._sock.settimeout(remaining)
        try:
            data, _ = self._sock.recvfrom(65536)
        except TimeoutError:
            return []  # the deadline check above raises on the next call
        except ConnectionResetError as exc:
            raise LiveNotReachableError(_hint(self.host, self.send_port)) from exc
        return self._decode(data)

    def _decode(self, data: bytes) -> list[Message]:
        try:
            if OscBundle.dgram_is_bundle(data):
                return self._flatten(OscBundle(data))
            msg = OscMessage(data)
            return [(msg.address, tuple(msg.params))]
        except Exception as exc:  # python-osc raises several parse error types
            logger.warning("ignoring malformed OSC datagram (%d bytes): %s", len(data), exc)
            return []

    def _flatten(self, bundle: OscBundle) -> list[Message]:
        out: list[Message] = []
        for item in bundle:
            if isinstance(item, OscBundle):
                out.extend(self._flatten(item))
            else:
                out.append((item.address, tuple(item.params)))
        return out

    def _drain(self) -> None:
        """Drop queued datagrams and stale ICMP resets before a new request.

        Correctness does not depend on this (bracketing does that), but a stale Windows
        reset from an earlier send would otherwise fail the next, healthy request.
        """
        self._sock.setblocking(False)
        try:
            while True:
                try:
                    data, _ = self._sock.recvfrom(65536)
                except (BlockingIOError, InterruptedError):
                    return
                except ConnectionResetError:
                    continue
                if self._pending:  # late echoes of a timed-out request are recorded
                    for address, args in self._decode(data):
                        self._note_stale(address, args)
        finally:
            self._sock.setblocking(True)


def _require_int(value: object, name: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int (got {value!r})")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum} (got {value})")
    return value


class AbletonBridge:
    """Capability-checked access to Live. The only entry point for other modules."""

    def __init__(self, transport: OscTransport, gate: CapabilityGate) -> None:
        self._transport = transport
        self.gate = gate
        self._local = threading.local()

    @property
    def last_reply(self) -> tuple | None:
        """Reply arguments of this thread's last read, exactly as received (for reports).

        Per thread, so concurrent callers never see each other's replies. ``None`` if the last
        read got no reply. For ``get_signature`` it holds the numerator and denominator
        replies together, also when one of them was malformed.
        """
        return getattr(self._local, "reply", None)

    def _set_last_reply(self, reply: tuple | None) -> None:
        self._local.reply = reply

    def _query(self, address: str, params: tuple = (), expect_prefix: tuple = (),
               timeout_s: float | None = None) -> tuple:
        self._set_last_reply(None)
        reply = self._transport.query(address, params, expect_prefix=expect_prefix,
                                      timeout_s=timeout_s)
        self._set_last_reply(reply)
        return reply

    @classmethod
    def connect(
        cls,
        host: str = DEFAULT_HOST,
        send_port: int = DEFAULT_SEND_PORT,
        receive_port: int = DEFAULT_RECEIVE_PORT,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        registry: CapabilityRegistry | None = None,
        allow_untested: Iterable[str] = (),
    ) -> AbletonBridge:
        if registry is None:
            registry = CapabilityRegistry.from_file()
        gate = CapabilityGate(registry, allow_untested)
        return cls(OscTransport(host, send_port, receive_port, timeout_s=timeout_s), gate)

    @classmethod
    def from_env(
        cls,
        *,
        registry: CapabilityRegistry | None = None,
        allow_untested: Iterable[str] = (),
    ) -> AbletonBridge:
        """Read ``ABLETON_OSC_HOST`` / ``_SEND_PORT`` / ``_RECEIVE_PORT`` (see ``.env.example``)."""

        def port(name: str, default: int) -> int:
            raw = os.environ.get(name, "").strip()
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                raise ValueError(f"{name} must be an integer port (got {raw!r})") from None

        return cls.connect(
            os.environ.get("ABLETON_OSC_HOST", "").strip() or DEFAULT_HOST,
            port("ABLETON_OSC_SEND_PORT", DEFAULT_SEND_PORT),
            port("ABLETON_OSC_RECEIVE_PORT", DEFAULT_RECEIVE_PORT),
            registry=registry,
            allow_untested=allow_untested,
        )

    @property
    def endpoint(self) -> tuple[str, int, int]:
        """(host, send port, receive port) — read-only, for messages and logs."""
        t = self._transport
        return t.host, t.send_port, t.receive_port

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> AbletonBridge:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # Connectivity check only (marker round trip); not a Live Object Model capability.
    def ping(self) -> None:
        self._transport.ping()

    # -- reads -------------------------------------------------------------------------------

    def get_version(self) -> tuple[int, int]:
        """(major, minor). AbletonOSC does not expose the patch level."""
        self.gate.check("app.version")
        reply = self._query(ADDRESSES["app.version"][0])
        if len(reply) != 2 or not all(type(v) is int for v in reply):
            raise BridgeProtocolError(f"version reply must be two ints, got {reply!r}")
        return reply[0], reply[1]

    def get_tempo(self) -> float:
        self.gate.check("song.tempo.get")
        reply = self._query(ADDRESSES["song.tempo.get"][0])
        if len(reply) != 1 or isinstance(reply[0], bool) or not isinstance(reply[0], int | float):
            raise BridgeProtocolError(f"tempo reply must be one number, got {reply!r}")
        tempo = float(reply[0])
        if not (math.isfinite(tempo) and 20.0 <= tempo <= 999.0):  # Live's tempo range
            raise BridgeProtocolError(f"tempo {tempo!r} outside Live's range 20..999 BPM")
        return tempo

    def get_signature(self) -> tuple[int, int]:
        self.gate.check("song.signature.get")
        values = []
        raw: list = []
        for addr in ADDRESSES["song.signature.get"]:
            reply = self._query(addr)
            raw.extend(reply)
            self._set_last_reply(tuple(raw))  # numerator reply (+ denominator reply)
            if len(reply) != 1 or type(reply[0]) is not int or reply[0] < 1:
                raise BridgeProtocolError(f"{addr} reply must be one positive int, got {reply!r}")
            values.append(reply[0])
        return values[0], values[1]

    def get_track_names(self, *, timeout_s: float | None = None) -> list[str]:
        """All track names in one reply. Very large sets may exceed one UDP datagram."""
        self.gate.check("song.track_names.get")
        reply = self._query(ADDRESSES["song.track_names.get"][0], timeout_s=timeout_s)
        if not all(isinstance(n, str) for n in reply):
            raise BridgeProtocolError(f"track names must be strings, got {reply!r}")
        return list(reply)

    # -- writes (each one is a Live change; callers apply approval levels) -------------------

    def set_track_mute(self, track_index: int, mute: bool) -> None:
        _require_int(track_index, "track_index", minimum=0)
        if not isinstance(mute, bool):
            raise ValueError(f"mute must be a bool (got {mute!r})")
        self.gate.check("track.mute.set")
        self._transport.send_confirmed(ADDRESSES["track.mute.set"][0], (track_index, int(mute)))

    def get_track_mute(self, track_index: int) -> bool:
        """Read back a track's mute state.

        Gated as ``track.mute.get`` (own registry entry since #42; before, it borrowed the
        ``track.mute.set`` gate). AbletonOSC replies ``track_id, mute`` (README "Track API");
        Live's bool arrives as OSC T/F, a 0/1 int is accepted too.
        """
        _require_int(track_index, "track_index", minimum=0)
        self.gate.check("track.mute.get")
        reply = self._query(
            ADDRESSES["track.mute.get"][0], (track_index,), expect_prefix=(track_index,)
        )
        if len(reply) != 1 or not (type(reply[0]) is bool or (type(reply[0]) is int
                                                              and reply[0] in (0, 1))):
            raise BridgeProtocolError(f"mute reply must be one bool or 0/1, got {reply!r}")
        return bool(reply[0])

    def undo(self) -> None:
        self.gate.check("song.undo")
        self._transport.send_confirmed(ADDRESSES["song.undo"][0])

    # -- clip import (#50) -------------------------------------------------------------------
    # The reads below are gated by their own registry entries since #143 (before, they
    # borrowed the clip_slot.create_audio_clip gate).

    @staticmethod
    def _bool_reply(reply: tuple, what: str) -> bool:
        if len(reply) != 1 or not (type(reply[0]) is bool or (type(reply[0]) is int
                                                              and reply[0] in (0, 1))):
            raise BridgeProtocolError(f"{what} reply must be one bool or 0/1, got {reply!r}")
        return bool(reply[0])

    def get_num_scenes(self) -> int:
        """Number of scenes = number of clip slots per track."""
        self.gate.check("song.num_scenes.get")
        reply = self._query(ADDRESSES["song.num_scenes.get"][0])
        if len(reply) != 1 or type(reply[0]) is not int or reply[0] < 0:
            raise BridgeProtocolError(f"num_scenes reply must be one int >= 0, got {reply!r}")
        return reply[0]

    def get_track_has_audio_input(self, track_index: int, *,
                                  timeout_s: float | None = None) -> bool:
        """LOM ``Track.has_audio_input``: "1 for audio tracks"."""
        _require_int(track_index, "track_index", minimum=0)
        self.gate.check("track.has_audio_input.get")
        reply = self._query(ADDRESSES["track.has_audio_input.get"][0], (track_index,),
                            expect_prefix=(track_index,), timeout_s=timeout_s)
        return self._bool_reply(reply, "has_audio_input")

    def get_clip_slot_has_clip(self, track_index: int, slot_index: int, *,
                               timeout_s: float | None = None) -> bool:
        _require_int(track_index, "track_index", minimum=0)
        _require_int(slot_index, "slot_index", minimum=0)
        self.gate.check("clip_slot.has_clip.get")
        reply = self._query(ADDRESSES["clip_slot.has_clip.get"][0],
                            (track_index, slot_index), expect_prefix=(track_index, slot_index),
                            timeout_s=timeout_s)
        return self._bool_reply(reply, "has_clip")

    def get_clip_file_path(self, track_index: int, slot_index: int, *,
                           timeout_s: float | None = None) -> str:
        """LOM ``Clip.file_path`` of the clip in this slot ("only available for audio clips").

        An empty slot makes AbletonOSC's handler fail (``clip.py`` line 55 resolves
        ``clip_slots[i].clip``, which is empty) and comes back as :class:`AbletonOSCError`.
        """
        _require_int(track_index, "track_index", minimum=0)
        _require_int(slot_index, "slot_index", minimum=0)
        self.gate.check("clip.file_path.get")
        reply = self._query(ADDRESSES["clip.file_path.get"][0],
                            (track_index, slot_index), expect_prefix=(track_index, slot_index),
                            timeout_s=timeout_s)
        if len(reply) != 1 or not isinstance(reply[0], str):
            raise BridgeProtocolError(f"file_path reply must be one string, got {reply!r}")
        return reply[0]

    def create_audio_track(self, index: int = -1, *, timeout_s: float | None = None) -> None:
        """LOM ``Song.create_audio_track(index)``; -1 appends at the end. No reply.

        Confirmation only means AbletonOSC processed it without an error; read the track
        names back to see the new track.
        """
        _require_int(index, "index", minimum=-1)
        self.gate.check("song.create_audio_track")
        self._transport.send_confirmed(ADDRESSES["song.create_audio_track"][0], (index,),
                                       timeout_s=timeout_s)

    def create_audio_clip(self, track_index: int, slot_index: int, path: str, *,
                          timeout_s: float | None = None) -> None:
        """LOM ``ClipSlot.create_audio_clip(path)`` through the AbeltonGod extension.

        ``path`` must be an absolute path string (checked here; existence and format are the
        caller's job, see ``bridge.clip_import.validate_wav_path``). Raises
        :class:`ExtensionMissingError` if AbletonOSC has no handler for the address, and
        :class:`AbletonOSCError` if Live refused (e.g. MIDI or frozen track).
        """
        _require_int(track_index, "track_index", minimum=0)
        _require_int(slot_index, "slot_index", minimum=0)
        if not isinstance(path, str) or not path or "\x00" in path or not os.path.isabs(path):
            raise ValueError(f"path must be an absolute path string (got {path!r})")
        self.gate.check("clip_slot.create_audio_clip")
        address = EXTENSION_ADDRESSES["clip_slot.create_audio_clip"][0][0]
        try:
            self._transport.send_confirmed(address, (track_index, slot_index, path),
                                           timeout_s=timeout_s)
        except AbletonOSCError as exc:
            raise _as_extension_missing(exc, address) from exc

    def probe_audio_clip_extension(self) -> bool:
        """True if AbletonOSC has a handler for the import address, False if not.

        Sends the address with **no arguments**. With the extension installed, AbletonOSC's
        callback fails at ``int(params[0])`` (``clip_slot.py`` line 12) before it touches the
        song, so nothing changes in Live. AbletonOSC passes ``message.params``, a list
        (``osc_server.py`` line 90), so the text is ``list index out of range``; it comes back
        as ``/live/error "Error handling OSC message: list index out of range"``
        (``osc_server.py`` line 187) and is also written to ``abletonosc.log``. Without the
        extension the reply is ``Unknown OSC address`` (``osc_server.py`` line 125).
        """
        self.gate.check("clip_slot.create_audio_clip")
        address = EXTENSION_ADDRESSES["clip_slot.create_audio_clip"][0][0]
        try:
            self._transport.send_confirmed(address, ())
        except AbletonOSCError as exc:
            return not isinstance(_as_extension_missing(exc, address), ExtensionMissingError)
        raise BridgeProtocolError(
            f"{address} without arguments was processed without an error; the installed "
            "handler does not look like the AbeltonGod extension"
        )

    # -- arrangement capability check (#140) -------------------------------------------------
    # All of these are registry status `unknown` until the user's run: each call needs the
    # caller's explicit allow_untested override, or it is refused before any network I/O.

    def _gated(self, cap_id: str) -> str:
        """Gate check, then the (first) address of ``cap_id``."""
        self.gate.check(cap_id)
        if cap_id in EXTENSION_ADDRESSES:
            return EXTENSION_ADDRESSES[cap_id][0][0]
        return ADDRESSES[cap_id][0]

    def late_reply(self, request_id: str | None) -> LateReply | None:
        """See :meth:`OscTransport.late_reply` (no network I/O, not capability-gated)."""
        return self._transport.late_reply(request_id)

    def create_midi_track(self, index: int = -1, *, timeout_s: float | None = None) -> None:
        """LOM ``Song.create_midi_track(index)``; -1 appends at the end. No reply."""
        _require_int(index, "index", minimum=-1)
        address = self._gated("song.create_midi_track")
        self._transport.send_confirmed(address, (index,), timeout_s=timeout_s)

    def get_track_has_midi_input(self, track_index: int, *,
                                 timeout_s: float | None = None) -> bool:
        _require_int(track_index, "track_index", minimum=0)
        address = self._gated("track.has_midi_input.get")
        reply = self._query(address, (track_index,), expect_prefix=(track_index,),
                            timeout_s=timeout_s)
        return self._bool_reply(reply, "has_midi_input")

    def get_arrangement_clips(self, track_index: int, *, timeout_s: float | None = None
                              ) -> tuple[tuple[float, float], ...]:
        """((start_time, length), ...) of the track's Arrangement clips, in Live's order."""
        _require_int(track_index, "track_index", minimum=0)
        self.gate.check("track.arrangement_clips.get")
        starts_addr, lengths_addr = ADDRESSES["track.arrangement_clips.get"]
        starts = self._query(starts_addr, (track_index,), expect_prefix=(track_index,),
                             timeout_s=timeout_s)
        lengths = self._query(lengths_addr, (track_index,), expect_prefix=(track_index,),
                              timeout_s=timeout_s)
        if len(starts) != len(lengths) or not all(_is_number(v) for v in (*starts, *lengths)):
            raise BridgeProtocolError(f"arrangement clip lists must be numbers of equal length, "
                                      f"got start_time={starts!r} length={lengths!r}")
        return tuple((float(s), float(n)) for s, n in zip(starts, lengths, strict=True))

    def get_arrangement_clip_notes(self, track_index: int, clip_index: int, *,
                                   timeout_s: float | None = None
                                   ) -> tuple[tuple[int, float, float, float, bool], ...]:
        """Notes of Arrangement clip ``clip_index`` as (pitch, start, duration, velocity, mute).

        Through the AbeltonGod extension; it reads ``get_notes_extended(0, 127, -8192, 16384)``,
        the same range as AbletonOSC's ``/live/clip/get/notes`` (clip.py:136). If
        ``pitch_span`` is a count, pitch 127 is outside that range (research note Q1).
        """
        _require_int(track_index, "track_index", minimum=0)
        _require_int(clip_index, "clip_index", minimum=0)
        address = self._gated("arrangement_clip.notes.get")
        try:
            flat = self._query(address, (track_index, clip_index),
                               expect_prefix=(track_index, clip_index), timeout_s=timeout_s)
        except AbletonOSCError as exc:
            raise _as_extension_missing(exc, address) from exc
        if len(flat) % 5:
            raise BridgeProtocolError(f"notes reply must be groups of 5, got {flat!r}")
        notes = []
        for i in range(0, len(flat), 5):
            pitch, start, duration, velocity, mute = flat[i:i + 5]
            if (type(pitch) is not int or not all(_is_number(v) for v in
                                                  (start, duration, velocity))
                    or not (type(mute) is bool or (type(mute) is int and mute in (0, 1)))):
                raise BridgeProtocolError(f"malformed note {flat[i:i + 5]!r}")
            notes.append((pitch, float(start), float(duration), float(velocity), bool(mute)))
        return tuple(notes)

    def get_is_playing(self) -> bool:
        reply = self._query(self._gated("song.is_playing.get"))
        return self._bool_reply(reply, "is_playing")

    def get_song_time(self, *, timeout_s: float | None = None) -> float:
        """``Song.current_song_time`` in beats."""
        reply = self._query(self._gated("song.current_song_time.get"),
                            timeout_s=timeout_s)
        if len(reply) != 1 or not _is_number(reply[0]):
            raise BridgeProtocolError(f"current_song_time reply must be one number, got {reply!r}")
        return float(reply[0])

    def get_cue_points(self, *, timeout_s: float | None = None) -> tuple[tuple[str, float], ...]:
        """((name, time), ...) in Live's order (whether that is time order: not verified)."""
        flat = self._query(self._gated("song.cue_points.get"), timeout_s=timeout_s)
        if len(flat) % 2:
            raise BridgeProtocolError(f"cue_points reply must be name/time pairs, got {flat!r}")
        pairs = []
        for i in range(0, len(flat), 2):
            name, time_ = flat[i], flat[i + 1]
            if not isinstance(name, str) or not _is_number(time_):
                raise BridgeProtocolError(f"malformed cue point {flat[i:i + 2]!r}")
            pairs.append((name, float(time_)))
        return tuple(pairs)

    def set_song_time(self, beats: float, *, timeout_s: float | None = None) -> None:
        beats = _require_beats(beats, "beats")
        address = self._gated("song.current_song_time.set")
        self._transport.send_confirmed(address, (beats,), timeout_s=timeout_s)

    def toggle_cue_at_song_time(self, *, timeout_s: float | None = None) -> None:
        """LOM ``Song.set_or_delete_cue()``: adds a locator at the current song time, or
        DELETES the one that is there. Callers must check the cue points first."""
        address = self._gated("song.cue_point.add_or_delete")
        self._transport.send_confirmed(address, (), timeout_s=timeout_s)

    def set_cue_name(self, cue_index: int, name: str, *, timeout_s: float | None = None) -> None:
        _require_int(cue_index, "cue_index", minimum=0)
        if not isinstance(name, str) or not name or "\x00" in name:
            raise ValueError(f"name must be a non-empty string (got {name!r})")
        address = self._gated("song.cue_point.set_name")
        self._transport.send_confirmed(address, (cue_index, name), timeout_s=timeout_s)

    def create_arrangement_midi_clip(self, track_index: int, start_beats: float,
                                     length_beats: float, *,
                                     timeout_s: float | None = None) -> None:
        """LOM ``Track.create_midi_clip(start_time, length)`` through the AbeltonGod extension.

        Raises :class:`ExtensionMissingError` if AbletonOSC has no handler for the address.
        """
        _require_int(track_index, "track_index", minimum=0)
        start = _require_beats(start_beats, "start_beats")
        length = _require_beats(length_beats, "length_beats")
        if length <= 0 or start + length > ARRANGEMENT_MAX_BEATS:
            raise ValueError(f"clip {start}+{length} beats must have length > 0 and end by "
                             f"{ARRANGEMENT_MAX_BEATS:g}")
        address = self._gated("track.create_midi_clip")
        try:
            self._transport.send_confirmed(address, (track_index, start, length),
                                           timeout_s=timeout_s)
        except AbletonOSCError as exc:
            raise _as_extension_missing(exc, address) from exc

    def add_arrangement_clip_notes(self, track_index: int, clip_index: int,
                                   notes: Sequence[tuple[int, float, float, int, bool]], *,
                                   timeout_s: float | None = None) -> None:
        """Add notes (pitch, start, duration, velocity, mute) to an Arrangement clip, through
        the AbeltonGod extension (one ``Clip.add_new_notes`` call, as clip.py:145-155)."""
        _require_int(track_index, "track_index", minimum=0)
        _require_int(clip_index, "clip_index", minimum=0)
        if not 1 <= len(notes) <= MAX_NOTES_PER_MESSAGE:
            raise ValueError(f"1..{MAX_NOTES_PER_MESSAGE} notes per message (got {len(notes)})")
        flat: list[OscArg] = []
        for note in notes:
            if len(note) != 5:
                raise ValueError(f"a note is (pitch, start, duration, velocity, mute): {note!r}")
            pitch, start, duration, velocity, mute = note
            _require_int(pitch, "pitch", minimum=0)
            _require_int(velocity, "velocity", minimum=1)
            if pitch > 126 or velocity > 127:  # 127: outside the read-back range (Q1)
                raise ValueError(f"pitch must be 0..126 and velocity 1..127 (got {note!r})")
            start = _require_beats(start, "note start")
            duration = _require_beats(duration, "note duration")
            if duration <= 0 or not isinstance(mute, bool):
                raise ValueError(f"duration must be > 0 and mute a bool (got {note!r})")
            flat += [pitch, start, duration, velocity, int(mute)]
        address = self._gated("arrangement_clip.notes.add")
        try:
            self._transport.send_confirmed(address, (track_index, clip_index, *flat),
                                           timeout_s=timeout_s)
        except AbletonOSCError as exc:
            raise _as_extension_missing(exc, address) from exc

    def probe_arrangement_extension(self) -> list[str]:
        """Addresses of the track.py extension that AbletonOSC does NOT know; [] = installed.

        Each address is sent with **no arguments**: with the extension, the callback fails at
        ``params[0]`` (track.py:15) before it touches the song, so nothing changes in Live; the
        error comes back as ``/live/error`` (osc_server.py:186-187) and is written to
        ``abletonosc.log``. Without it the reply is ``Unknown OSC address`` (osc_server.py:125).
        """
        missing = []
        for cap_id in ARRANGEMENT_EXTENSION:
            address = self._gated(cap_id)
            try:
                self._transport.send_confirmed(address, ())
            except AbletonOSCError as exc:
                if isinstance(_as_extension_missing(exc, address), ExtensionMissingError):
                    missing.append(address)
                continue
            raise BridgeProtocolError(
                f"{address} without arguments was processed without an error; the installed "
                "handler does not look like the AbeltonGod extension")
        return missing


# One UDP datagram must hold the whole note list (5 values per note).
MAX_NOTES_PER_MESSAGE = 64


def _is_number(value: object) -> bool:
    return (not isinstance(value, bool) and isinstance(value, int | float)
            and math.isfinite(value))


def _require_beats(value: object, name: str) -> float:
    if not _is_number(value) or not 0 <= value <= ARRANGEMENT_MAX_BEATS:
        raise ValueError(f"{name} must be a number of beats in 0..{ARRANGEMENT_MAX_BEATS:g} "
                         f"(got {value!r})")
    return float(value)


def _as_extension_missing(exc: AbletonOSCError, address: str) -> AbletonOSCError:
    """Turn AbletonOSC's 'Unknown OSC address: <address>' into :class:`ExtensionMissingError`."""
    if f"{UNKNOWN_ADDRESS_ERROR}: {address}" in str(exc):
        return ExtensionMissingError(
            f"AbletonOSC has no handler for {address}: the AbeltonGod extension is not "
            "installed (scripts/install_abletonosc_extension.py), or Live was not restarted"
        )
    return exc
