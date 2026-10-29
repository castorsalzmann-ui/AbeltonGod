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
        # Clip import (#50). Tracks without "audio" are MIDI tracks; "slots" holds a file path
        # or None per scene. ``extension_installed`` = the AbeltonGod patch is in AbletonOSC.
        self.num_scenes = 4
        self.extension_installed = True
        self.clip_undoable = True  # False: Live does not record create_audio_clip as undo step
        # Read-back timing (#50 user run 1). All simulated; Live's real timing is not known.
        self.clip_delay_s = 0.0  # the clip appears in the slot this long after the call
        self.rename_on_clip: str | None = None  # Live renames the target track to this
        self.file_path_delay_s = 0.0  # file_path reads as None (OSC nil) this long after
        self.undo_reverts_rename = True  # undo of the clip also restores the old track name
        self._clip_made_at: dict[tuple[int, int], float] = {}

        self._held: list[tuple[bytes, tuple[str, int]]] | None = None
        self.released = threading.Event()  # set by release(); lets tests check ordering
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
            "/live/song/get/num_scenes": lambda p: (self.num_scenes,),
            "/live/song/create_audio_track": self._create_audio_track,
            "/live/track/get/has_audio_input": lambda p: (int(p[0]),
                                                          bool(self.tracks[int(p[0])].get(
                                                              "audio", False))),
            "/live/clip_slot/get/has_clip": lambda p: (int(p[0]), int(p[1]),
                                                       self._slots(int(p[0]))[int(p[1])]
                                                       is not None),
            "/live/clip/get/file_path": self._get_file_path,
            **({"/live/clip_slot/create_audio_clip": self._create_audio_clip}
               if self.extension_installed else {}),
        }

    # -- clip import model -------------------------------------------------------------------

    def _slots(self, idx: int) -> list:
        track = self.tracks[idx]  # IndexError for a bad track index, as in AbletonOSC
        slots = track.setdefault("slots", [None] * self.num_scenes)
        return slots

    def _create_audio_track(self, p: tuple) -> None:
        index = int(p[0])
        track = {"name": f"{len(self.tracks) + 1}-Audio", "mute": False, "audio": True,
                 "slots": [None] * self.num_scenes}
        pos = len(self.tracks) if index == -1 else index
        self.tracks.insert(pos, track)
        self.undo_stack.append(("track", pos))

    def _create_audio_clip(self, p: tuple) -> None:
        # AbletonOSC clip_slot.py line 12: int(params[0]), int(params[1]); IndexError when
        # called without arguments (the probe).
        track_index, slot_index = int(p[0]), int(p[1])
        slots = self._slots(track_index)
        track = self.tracks[track_index]
        path = p[2]
        if not track.get("audio", False) or track.get("frozen", False):
            raise RuntimeError("Clip slot does not belong to an audio track or track is frozen")
        if slots[slot_index] is not None:
            raise RuntimeError("Clip slot is not empty")  # LOM behaviour here: not verified

        def apply() -> None:
            slots[slot_index] = path
            self._clip_made_at[(track_index, slot_index)] = time.monotonic()
            old_name = track["name"]
            if self.rename_on_clip is not None:
                track["name"] = self.rename_on_clip
            if self.clip_undoable:
                self.undo_stack.append(("clip", track_index, slot_index, old_name))

        if self.clip_delay_s > 0:
            def later() -> None:
                with self._lock:
                    apply()
            timer = threading.Timer(self.clip_delay_s, later)
            timer.daemon = True
            timer.start()
        else:
            apply()

    def _get_file_path(self, p: tuple) -> tuple:
        idx, slot = int(p[0]), int(p[1])
        path = self._slots(idx)[slot]
        if path is None:  # AbletonOSC: getattr(None, "file_path") -> AttributeError
            raise AttributeError("'NoneType' object has no attribute 'file_path'")
        made = self._clip_made_at.get((idx, slot))
        if made is not None and time.monotonic() - made < self.file_path_delay_s:
            return (idx, slot, None)  # _get_property: RuntimeError -> None -> OSC nil
        return (idx, slot, path)

    def _get_mute(self, p: tuple) -> tuple:
        idx = int(p[0])
        return (idx, self.tracks[idx]["mute"])  # Live returns a bool -> OSC T/F

    def _set_mute(self, p: tuple) -> None:
        idx = int(p[0])  # IndexError for a bad track index, as with Live's track list
        self.undo_stack.append((idx, self.tracks[idx]["mute"]))
        self.tracks[idx]["mute"] = bool(p[1])

    def _undo(self, p: tuple) -> None:
        if not self.undo_stack:
            return
        entry = self.undo_stack.pop()
        if entry[0] == "track":
            del self.tracks[entry[1]]
        elif entry[0] == "clip":
            self.tracks[entry[1]]["slots"][entry[2]] = None
            if self.undo_reverts_rename:
                self.tracks[entry[1]]["name"] = entry[3]
        else:
            idx, before = entry
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
            self.released.clear()

    def release(self) -> None:
        with self._lock:
            held, self._held = self._held or [], None
            self.released.set()
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
