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
    "app.version": ("/live/application/get/version",),
    "song.tempo.get": ("/live/song/get/tempo",),
    "song.signature.get": (
        "/live/song/get/signature_numerator",
        "/live/song/get/signature_denominator",
    ),
    "song.track_names.get": ("/live/song/get/track_names",),
    "track.mute.set": ("/live/track/set/mute",),
    "song.undo": ("/live/song/undo",),
}

# Addresses the bridge sends that have no registry entry of their own YET, with the capability
# whose gate they borrow. Each must get its own entry in the contract-change PR that follows the
# user's #5 run (then it moves into ADDRESSES; ``test_capabilities.py`` fails until it does).
#
# track.mute.get: read-back for the mute write (#5). README "Track API":
# ``/live/track/get/mute track_id`` -> ``track_id, mute``; source ``abletonosc/track.py``
# ``properties_rw`` contains "mute". Gated as ``track.mute.set`` (review of PR #37, #39 item 6).
PENDING_REGISTRY: dict[str, tuple[tuple[str, ...], str]] = {
    "track.mute.get": (("/live/track/get/mute",), "track.mute.set"),
}
TRACK_MUTE_READBACK_ADDRESS = PENDING_REGISTRY["track.mute.get"][0][0]

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
    """


class LiveNotReachableError(BridgeUnavailableError):
    """The OS reported that nothing listens on the send port (Windows ICMP reset)."""


class AbletonOSCError(BridgeError):
    """AbletonOSC reported an error via ``/live/error`` for this request."""


class BridgeProtocolError(BridgeError):
    """A reply arrived but its content is not what the protocol promises."""


class ReceivePortInUseError(BridgeError):
    """The reply port is already bound by another program."""


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

            started = False
            between: list[Message] = []
            while True:
                for msg_address, args in self._receive(deadline):
                    if msg_address == MARKER_ADDRESS and len(args) == 2:
                        if args[1] == start:
                            started = True
                            continue
                        if args[1] == end:
                            if not started:
                                raise BridgeProtocolError("end marker arrived before start marker")
                            return between
                    if not started:
                        logger.debug("discarding stale OSC message %s %r", msg_address, args)
                        continue
                    if msg_address == ERROR_ADDRESS:
                        detail = args[0] if args else "<no message>"
                        raise AbletonOSCError(f"AbletonOSC reported an error: {detail}")
                    between.append((msg_address, args))

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
                    self._sock.recvfrom(65536)
                except (BlockingIOError, InterruptedError):
                    return
                except ConnectionResetError:
                    continue
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

    def _query(self, address: str, params: tuple = (), expect_prefix: tuple = ()) -> tuple:
        self._set_last_reply(None)
        reply = self._transport.query(address, params, expect_prefix=expect_prefix)
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

    def get_track_names(self) -> list[str]:
        """All track names in one reply. Very large sets may exceed one UDP datagram."""
        self.gate.check("song.track_names.get")
        reply = self._query(ADDRESSES["song.track_names.get"][0])
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

        Gated as ``track.mute.set``: it is the read-back that verifies that write (#5); the
        registry has no separate mute-read entry yet. AbletonOSC replies
        ``track_id, mute`` (README "Track API"); Live's bool arrives as OSC T/F, a 0/1 int is
        accepted too.
        """
        _require_int(track_index, "track_index", minimum=0)
        self.gate.check(PENDING_REGISTRY["track.mute.get"][1])
        reply = self._query(
            TRACK_MUTE_READBACK_ADDRESS, (track_index,), expect_prefix=(track_index,)
        )
        if len(reply) != 1 or not (type(reply[0]) is bool or (type(reply[0]) is int
                                                              and reply[0] in (0, 1))):
            raise BridgeProtocolError(f"mute reply must be one bool or 0/1, got {reply!r}")
        return bool(reply[0])

    def undo(self) -> None:
        self.gate.check("song.undo")
        self._transport.send_confirmed(ADDRESSES["song.undo"][0])
