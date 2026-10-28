"""A fake AbletonOSC server for CI. No Ableton involved; never evidence for Live behaviour.

Mirrors the reply semantics of AbletonOSC commit 0ca68214 (``abletonosc/osc_server.py``,
``manager.py``):
- a handler that returns a tuple gets a reply on the same address, sent to the sender's
  host on ``response_port`` (fixed, not the sender's port);
- handlers that return None (methods, setters) send nothing;
- an unknown address or an exception in a handler produces ``/live/error <message>``;
- ``/live/test`` replies ``'ok'``.

It also holds a tiny song model (tempo, signature, tracks with mute, an undo stack) so that
write -> read -> undo flows can be checked, plus fault switches: ``drop`` (never answer an
address), ``delays`` (answer the next requests to an address late, one delay each),
``extra_before`` (send unrelated messages before a reply, like AbletonOSC's unsolicited
``/live/startup``) and ``raw_reply`` (send hand-made bytes instead of the reply).
"""

from __future__ import annotations

import socket
import threading
import time

from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder


def build(address: str, args: tuple = ()) -> bytes:
    b = OscMessageBuilder(address=address)
    for a in args:
        b.add_arg(a)
    return b.build().dgram


class FakeAbletonOSC:
    def __init__(self, response_port: int = 0) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port: int = self.sock.getsockname()[1]
        self.response_port = response_port
        self.received: list[tuple[str, tuple]] = []
        self.drop: set[str] = set()
        self.delays: dict[str, list[float]] = {}
        self.extra_before: list[tuple[str, tuple]] = []
        self.raw_reply: dict[str, bytes] = {}

        self.version = (12, 3)
        self.tempo = 136.0
        self.signature = (4, 4)
        self.tracks: list[dict] = [
            {"name": "1-Kick", "mute": 0},
            {"name": "2-Bass", "mute": 0},
        ]
        self.undo_stack: list = []

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # -- handlers (signature: params tuple -> reply tuple or None) ----------------------------

    def _handlers(self) -> dict:
        return {
            "/live/test": lambda p: ("ok",),
            "/live/application/get/version": lambda p: self.version,
            "/live/song/get/tempo": lambda p: (self.tempo, *p),
            "/live/song/get/signature_numerator": lambda p: (self.signature[0], *p),
            "/live/song/get/signature_denominator": lambda p: (self.signature[1], *p),
            "/live/song/get/track_names": lambda p: tuple(t["name"] for t in self.tracks),
            "/live/track/get/mute": self._get_mute,
            "/live/track/set/mute": self._set_mute,
            "/live/song/create_audio_track": self._create_audio_track,
            "/live/song/undo": self._undo,
        }

    def _get_mute(self, p: tuple) -> tuple:
        idx = int(p[0])
        return (idx, self.tracks[idx]["mute"])

    def _set_mute(self, p: tuple) -> None:
        idx = int(p[0])  # IndexError for a bad track, like Live
        self.undo_stack.append(("mute", idx, self.tracks[idx]["mute"]))
        self.tracks[idx]["mute"] = p[1]

    def _create_audio_track(self, p: tuple) -> None:
        index = int(p[0])
        pos = len(self.tracks) if index == -1 else index
        if not 0 <= pos <= len(self.tracks):
            raise IndexError("track index out of range")
        self.tracks.insert(pos, {"name": f"{pos + 1}-Audio", "mute": 0})
        self.undo_stack.append(("create", pos))

    def _undo(self, p: tuple) -> None:
        if not self.undo_stack:
            return
        entry = self.undo_stack.pop()
        if entry[0] == "mute":
            self.tracks[entry[1]]["mute"] = entry[2]
        else:
            del self.tracks[entry[1]]

    # -- server loop -------------------------------------------------------------------------

    def _send(self, host: str, address: str, args: tuple) -> None:
        try:
            self.sock.sendto(build(address, args), (host, self.response_port))
        except OSError:
            pass  # a delayed reply after close() is dropped, like a reply to a closed client

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
                if address in self.drop:
                    continue
                queue = self.delays.get(address)
                delay = queue.pop(0) if queue else 0.0
                handlers = self._handlers()
                if address not in handlers:
                    self._send(host, "/live/error", (f"Unknown OSC address: {address}",))
                    continue
                try:
                    rv = handlers[address](params)
                except Exception as exc:  # AbletonOSC relays str(exception)
                    self._send(host, "/live/error", (str(exc),))
                    continue
                for extra in self.extra_before:
                    self._send(host, *extra)
                if address in self.raw_reply:
                    self.sock.sendto(self.raw_reply[address], (host, self.response_port))
                    continue
                if rv is not None:
                    if delay:
                        threading.Timer(delay, self._send, (host, address, rv)).start()
                    else:
                        self._send(host, address, rv)

    def addresses(self) -> list[str]:
        with self._lock:
            return [a for a, _ in self.received]

    def wait_received(self, count: int, timeout: float = 2.0) -> None:
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
        self.sock.close()
