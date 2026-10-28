"""A fake AbletonOSC server for CI. No Ableton involved; never evidence for Live behaviour.

Mirrors the reply semantics of AbletonOSC commit 0ca68214 (``abletonosc/osc_server.py``,
``handler.py``, ``manager.py``):
- a handler that returns a tuple gets a reply on the same address, sent to the sender's
  host on ``response_port`` (fixed, not the sender's port);
- property getters echo extra arguments after the value (``_get_property``);
- methods and setters send nothing;
- an unknown address gives ``/live/error "Unknown OSC address: <addr>"``; an exception in a
  handler gives ``/live/error "Error handling OSC message: <exc>"``;
- messages are processed and answered in arrival order.

It holds a tiny song model (tempo, signature, tracks with mute, an undo stack) for
write -> read -> undo flows. Fault switches:
- ``drop``: never answer these addresses (the message is still processed);
- ``hold()`` / ``release()``: keep processing in order but hold every outgoing datagram until
  release, like Live's GUI thread being blocked by a dialog;
- ``extra_before``: unrelated messages sent before each reply (like ``/live/startup``);
- ``raw_reply``: hand-made bytes instead of the normal reply for an address.
"""

from __future__ import annotations

import socket
import threading
import time

from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

MARKER = "/live/song/get/tempo"


def build(address: str, args: tuple = ()) -> bytes:
    b = OscMessageBuilder(address=address)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


def is_marker(address: str, params: tuple) -> bool:
    return address == MARKER and len(params) == 1


class FakeAbletonOSC:
    def __init__(self, response_port: int = 0) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port: int = self.sock.getsockname()[1]
        self.response_port = response_port
        self.received: list[tuple[str, tuple]] = []
        self.drop: set[str] = set()
        self.extra_before: list[tuple[str, tuple]] = []
        self.raw_reply: dict[str, bytes] = {}

        self.version: tuple = (12, 3)
        self.tempo = 136.0
        self.signature = (4, 4)
        self.tracks: list[dict] = [
            {"name": "1-Kick", "mute": False},
            {"name": "2-Bass", "mute": False},
        ]
        self.undo_stack: list = []

        self._held: list[tuple[bytes, tuple[str, int]]] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # -- handlers (params tuple -> reply tuple or None) --------------------------------------

    def _handlers(self) -> dict:
        return {
            "/live/test": lambda p: ("ok",),
            "/live/application/get/version": lambda p: self.version,  # ignores params
            MARKER: lambda p: (self.tempo, *p),
            "/live/song/get/signature_numerator": lambda p: (self.signature[0], *p),
            "/live/song/get/signature_denominator": lambda p: (self.signature[1], *p),
            "/live/song/get/track_names": lambda p: tuple(t["name"] for t in self.tracks),
            "/live/track/get/mute": self._get_mute,
            "/live/track/set/mute": self._set_mute,
            "/live/song/undo": self._undo,
        }

    def _get_mute(self, p: tuple) -> tuple:
        idx = int(p[0])
        return (idx, self.tracks[idx]["mute"])  # Live returns a bool -> OSC T/F

    def _set_mute(self, p: tuple) -> None:
        idx = int(p[0])  # IndexError for a bad track index, as with Live's track list
        self.undo_stack.append((idx, self.tracks[idx]["mute"]))
        self.tracks[idx]["mute"] = bool(p[1])

    def _undo(self, p: tuple) -> None:
        if self.undo_stack:
            idx, before = self.undo_stack.pop()
            self.tracks[idx]["mute"] = before

    # -- sending -----------------------------------------------------------------------------

    def _emit(self, data: bytes, host: str) -> None:
        target = (host, self.response_port)
        if self._held is not None:
            self._held.append((data, target))
            return
        try:
            self.sock.sendto(data, target)
        except OSError:
            pass

    def _send(self, host: str, address: str, args: tuple) -> None:
        self._emit(build(address, args), host)

    def hold(self) -> None:
        with self._lock:
            self._held = []

    def release(self) -> None:
        with self._lock:
            held, self._held = self._held or [], None
            for data, target in held:
                try:
                    self.sock.sendto(data, target)
                except OSError:
                    pass

    def release_after(self, seconds: float) -> threading.Timer:
        timer = threading.Timer(seconds, self.release)
        timer.daemon = True
        timer.start()
        return timer

    # -- server loop -------------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, (host, _port) = self.sock.recvfrom(65536)
            except (TimeoutError, ConnectionResetError):
                continue
            except OSError:
                return
            msg = OscMessage(data)
            address, params = msg.address, tuple(msg.params)
            with self._lock:
                self.received.append((address, params))
                handlers = self._handlers()
                if address not in handlers:
                    self._send(host, "/live/error", (f"Unknown OSC address: {address}",))
                    continue
                try:
                    rv = handlers[address](params)
                except Exception as exc:
                    self._send(host, "/live/error", (f"Error handling OSC message: {exc}",))
                    continue
                if is_marker(address, params):
                    if address not in self.drop:
                        self._send(host, address, rv)
                    continue
                if address in self.drop:
                    continue
                for extra in self.extra_before:
                    self._send(host, *extra)
                if address in self.raw_reply:
                    self._emit(self.raw_reply[address], host)
                elif rv is not None:
                    self._send(host, address, rv)

    def payload(self) -> list[tuple[str, tuple]]:
        """Received messages without the client's bracketing markers."""
        with self._lock:
            return [(a, p) for a, p in self.received if not is_marker(a, p)]

    def wait_received(self, count: int, timeout: float = 2.0) -> None:
        """Wait until ``count`` messages (markers included) have been processed."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if len(self.received) >= count:
                    return
            time.sleep(0.005)
        raise AssertionError(f"fake server got {len(self.received)} messages, expected {count}")

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.release()
        self.sock.close()
