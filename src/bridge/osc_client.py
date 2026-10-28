"""OSC client for AbletonOSC (Phase 02, issue #4).

Protocol facts this module relies on (AbletonOSC commit 0ca68214, checked 2026-10-28):

- AbletonOSC listens on UDP 11000 and sends every reply to the *sender's host* on the fixed
  port 11001 (``abletonosc/osc_server.py`` ``process_message``; README "Usage"). The client
  therefore binds 11001 and sends from that same socket.
- A query is answered on the same OSC address it was sent to. There is no request id, so the
  client serialises requests and drains stale datagrams before each one.
- Methods and setters (``/live/song/undo``, ``/live/track/set/mute``) send no reply. To confirm
  that AbletonOSC processed them, the client sends ``/live/test`` afterwards and waits for its
  ``'ok'`` reply; messages are processed in order within one tick (``manager.py`` ``tick``).
- Unknown addresses and exceptions inside a handler are logged at ERROR and relayed as
  ``/live/error <message>`` (``manager.py`` ``LiveOSCErrorLogHandler``).
- Live with no AbletonOSC listening looks the same as Live closed: on Windows the next receive
  raises ``ConnectionResetError`` (ICMP port unreachable); on Linux the request just times out.

Only :class:`AbletonBridge` may be used by other modules. It checks the capability gate
before any network I/O. :class:`OscTransport` is the unchecked wire layer.
"""

from __future__ import annotations

import ipaddress
import logging
import math
import os
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
DEFAULT_RESYNC_GRACE_S = 0.3

ERROR_ADDRESS = "/live/error"
TEST_ADDRESS = "/live/test"

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
    "song.create_audio_track": ("/live/song/create_audio_track",),
}

OscArg = int | float | str

logger = logging.getLogger("abeltongod.bridge.osc")


class BridgeError(Exception):
    """Base class for bridge errors."""


class BridgeUnavailableError(BridgeError):
    """AbletonOSC did not answer. See the subclass for how this was detected."""


class BridgeTimeoutError(BridgeUnavailableError):
    """No reply within the timeout."""


class LiveNotReachableError(BridgeUnavailableError):
    """The OS reported that nothing listens on the send port (Windows ICMP reset)."""


class AbletonOSCError(BridgeError):
    """AbletonOSC reported an error via ``/live/error``."""


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


class OscTransport:
    """Serialised request/response over one localhost UDP socket. Not capability-checked."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        send_port: int = DEFAULT_SEND_PORT,
        receive_port: int = DEFAULT_RECEIVE_PORT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        resync_grace_s: float = DEFAULT_RESYNC_GRACE_S,
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
        for name, value in (("timeout_s", timeout_s), ("resync_grace_s", resync_grace_s)):
            if not (isinstance(value, int | float) and math.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be a positive finite number (got {value!r})")

        self.host = host
        self.send_port = send_port
        self.timeout_s = float(timeout_s)
        self.resync_grace_s = float(resync_grace_s)
        self._clock = clock
        self._lock = threading.Lock()
        self._needs_resync = False

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # No SO_REUSEADDR: a second client on 11001 must fail loudly, not steal replies.
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

    # -- public requests ---------------------------------------------------------------------

    def query(
        self,
        address: str,
        params: Sequence[OscArg] = (),
        *,
        expect_prefix: Sequence[OscArg] = (),
        timeout_s: float | None = None,
    ) -> tuple:
        """Send ``address`` and return the reply arguments (without ``expect_prefix``)."""
        prefix = tuple(expect_prefix)
        with self._lock:
            deadline = self._begin(timeout_s)
            self._send(address, params)
            reply = self._await(address, lambda args: args[: len(prefix)] == prefix, deadline)
            return reply[len(prefix):]

    def send(self, address: str, params: Sequence[OscArg] = ()) -> None:
        """Fire and forget. Use :meth:`send_confirmed` when the result matters."""
        with self._lock:
            self._begin(None)
            self._send(address, params)

    def send_confirmed(
        self, address: str, params: Sequence[OscArg] = (), *, timeout_s: float | None = None
    ) -> None:
        """Send, then wait until AbletonOSC has processed it (``/live/test`` round trip).

        Raises :class:`AbletonOSCError` if ``/live/error`` arrives first. This proves the
        message was processed without an error AbletonOSC reported; it does not prove that
        Live's state changed as intended. Side effect: Live shows "Received OSC OK".
        """
        with self._lock:
            deadline = self._begin(timeout_s)
            self._send(address, params)
            self._send(TEST_ADDRESS, ())
            self._await(TEST_ADDRESS, lambda args: args == ("ok",), deadline)

    def ping(self, *, timeout_s: float | None = None) -> None:
        """Round trip to ``/live/test``. Raises a :class:`BridgeUnavailableError` on failure."""
        with self._lock:
            deadline = self._begin(timeout_s)
            self._send(TEST_ADDRESS, ())
            self._await(TEST_ADDRESS, lambda args: args == ("ok",), deadline)

    # -- internals ---------------------------------------------------------------------------

    def _begin(self, timeout_s: float | None) -> float:
        timeout = self.timeout_s if timeout_s is None else timeout_s
        if not (isinstance(timeout, int | float) and math.isfinite(timeout) and timeout > 0):
            raise ValueError(f"timeout_s must be a positive finite number (got {timeout!r})")
        if self._needs_resync:
            # A late reply to a timed-out request may still be on its way. Discard everything
            # that arrives during the grace period so it cannot answer the next request.
            self._discard_for(self.resync_grace_s)
            self._needs_resync = False
        self._drain()
        return self._clock() + timeout

    def _send(self, address: str, params: Sequence[OscArg]) -> None:
        if not isinstance(address, str) or not address.startswith("/"):
            raise ValueError(f"OSC address must be a string starting with '/' (got {address!r})")
        builder = OscMessageBuilder(address=address)
        for p in params:
            # bool is an int subclass but python-osc encodes it as T/F, which AbletonOSC
            # setters do not expect. Callers convert to 0/1.
            if isinstance(p, bool) or not isinstance(p, int | float | str):
                raise ValueError(f"unsupported OSC argument {p!r} ({type(p).__name__})")
            if isinstance(p, float) and not math.isfinite(p):
                raise ValueError(f"non-finite OSC argument {p!r}")
            builder.add_arg(p)
        try:
            self._sock.sendto(builder.build().dgram, (self.host, self.send_port))
        except ConnectionResetError as exc:
            raise LiveNotReachableError(_hint(self.host, self.send_port)) from exc

    def _decode(self, data: bytes) -> list[tuple[str, tuple]]:
        try:
            if OscBundle.dgram_is_bundle(data):
                return self._flatten(OscBundle(data))
            msg = OscMessage(data)
            return [(msg.address, tuple(msg.params))]
        except Exception as exc:  # python-osc raises several parse error types
            logger.warning("ignoring malformed OSC datagram (%d bytes): %s", len(data), exc)
            return []

    def _flatten(self, bundle: OscBundle) -> list[tuple[str, tuple]]:
        out: list[tuple[str, tuple]] = []
        for item in bundle:
            if isinstance(item, OscBundle):
                out.extend(self._flatten(item))
            else:
                out.append((item.address, tuple(item.params)))
        return out

    def _await(
        self, address: str, matches: Callable[[tuple], bool], deadline: float
    ) -> tuple:
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                self._needs_resync = True
                raise BridgeTimeoutError(
                    f"no reply to {address} within the timeout. " + _hint(self.host, self.send_port)
                )
            self._sock.settimeout(remaining)
            try:
                data, _ = self._sock.recvfrom(65536)
            except TimeoutError:
                continue
            except ConnectionResetError as exc:
                self._needs_resync = True
                raise LiveNotReachableError(_hint(self.host, self.send_port)) from exc
            for msg_address, args in self._decode(data):
                if msg_address == ERROR_ADDRESS:
                    self._needs_resync = True
                    detail = args[0] if args else "<no message>"
                    raise AbletonOSCError(f"AbletonOSC reported an error: {detail}")
                if msg_address == address and matches(args):
                    return args
                logger.debug("ignoring unrelated OSC message %s %r", msg_address, args)

    def _drain(self) -> None:
        self._sock.setblocking(False)
        try:
            while True:
                try:
                    self._sock.recvfrom(65536)
                except (BlockingIOError, InterruptedError):
                    return
                except ConnectionResetError:
                    continue  # stale ICMP from an earlier send; the next request reports anew
        finally:
            self._sock.setblocking(True)

    def _discard_for(self, seconds: float) -> None:
        end = self._clock() + seconds
        while (remaining := end - self._clock()) > 0:
            self._sock.settimeout(remaining)
            try:
                self._sock.recvfrom(65536)
            except (TimeoutError, ConnectionResetError):
                continue


def _require_int(value: object, name: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int (got {value!r})")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum} (got {value})")
    return value


class AbletonBridge:
    """Capability-checked access to Live. The only entry point for other modules."""

    def __init__(self, transport: OscTransport, gate: CapabilityGate) -> None:
        self.transport = transport
        self.gate = gate

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
        gate = CapabilityGate(registry or CapabilityRegistry.from_file(), allow_untested)
        return cls(OscTransport(host, send_port, receive_port, timeout_s=timeout_s), gate)

    @classmethod
    def from_env(cls, *, allow_untested: Iterable[str] = ()) -> AbletonBridge:
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
            allow_untested=allow_untested,
        )

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> AbletonBridge:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # Connectivity check only; not a Live Object Model capability.
    def ping(self) -> None:
        self.transport.ping()

    # -- reads -------------------------------------------------------------------------------

    def get_version(self) -> tuple[int, int]:
        """(major, minor). AbletonOSC does not expose the patch level."""
        self.gate.check("app.version")
        reply = self.transport.query(ADDRESSES["app.version"][0])
        if len(reply) != 2 or not all(type(v) is int for v in reply):
            raise BridgeProtocolError(f"version reply must be two ints, got {reply!r}")
        return reply[0], reply[1]

    def get_tempo(self) -> float:
        self.gate.check("song.tempo.get")
        reply = self.transport.query(ADDRESSES["song.tempo.get"][0])
        if len(reply) != 1 or isinstance(reply[0], bool) or not isinstance(reply[0], int | float):
            raise BridgeProtocolError(f"tempo reply must be one number, got {reply!r}")
        tempo = float(reply[0])
        if not (math.isfinite(tempo) and 20.0 <= tempo <= 999.0):  # Live's tempo range
            raise BridgeProtocolError(f"tempo {tempo!r} outside Live's range 20..999 BPM")
        return tempo

    def get_signature(self) -> tuple[int, int]:
        self.gate.check("song.signature.get")
        num_addr, den_addr = ADDRESSES["song.signature.get"]
        values = []
        for addr in (num_addr, den_addr):
            reply = self.transport.query(addr)
            if len(reply) != 1 or type(reply[0]) is not int or reply[0] < 1:
                raise BridgeProtocolError(f"{addr} reply must be one positive int, got {reply!r}")
            values.append(reply[0])
        return values[0], values[1]

    def get_track_names(self) -> list[str]:
        self.gate.check("song.track_names.get")
        reply = self.transport.query(ADDRESSES["song.track_names.get"][0])
        if not all(isinstance(n, str) for n in reply):
            raise BridgeProtocolError(f"track names must be strings, got {reply!r}")
        return list(reply)

    # -- writes (each one is a Live change; callers apply approval levels) -------------------

    def set_track_mute(self, track_index: int, mute: bool) -> None:
        _require_int(track_index, "track_index", minimum=0)
        if not isinstance(mute, bool):
            raise ValueError(f"mute must be a bool (got {mute!r})")
        self.gate.check("track.mute.set")
        self.transport.send_confirmed(ADDRESSES["track.mute.set"][0], (track_index, int(mute)))

    def undo(self) -> None:
        self.gate.check("song.undo")
        self.transport.send_confirmed(ADDRESSES["song.undo"][0])

    def create_audio_track(self, index: int = -1) -> None:
        _require_int(index, "index", minimum=-1)
        self.gate.check("song.create_audio_track")
        self.transport.send_confirmed(ADDRESSES["song.create_audio_track"][0], (index,))
