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
- ``raw_reply``: hand-made bytes instead of the normal reply for an address;
- ``stall_after``: after an address was handled without an error, process and answer nothing
  for that many seconds (Live's GUI thread busy after a call; incoming datagrams queue up,
  #140; a failing call such as the extension probe does not stall);
- ``drop_next_marker_after``: after an address (also a failing call), drop the next marker
  echo (the request's end marker: a lost reply datagram, #140).
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
        self.stall_after: dict[str, float] = {}
        self.drop_next_marker_after: set[str] = set()
        self._drop_next_marker = False

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
        # Arrangement check (#140). Tracks may hold "arrangement": [{"start", "length",
        # "notes"}]. All simulated; which writes Live records as undo steps is NOT known.
        self.song_time = 0.0
        self.is_playing = False
        self.cue_points: list[list] = []  # [name, time] in Live's (here: insertion) order
        self.arrangement_extension_installed = True
        self.cue_default_name = "1"
        self.cue_time_offset = 0.0  # a locator lands this far from the song time
        self.not_undoable: set[str] = {"song_time"}  # kinds Live does not record (simulated)
        self.undo_batch = 1  # undo entries one /live/song/undo reverts (simulated grouping)
        self.undo_noop = False  # /live/song/undo changes nothing (like #50 run 2, cause open)
        self.drop_notes_on_add = 0  # add/notes stores this many notes fewer (fault)

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
            # Arrangement check (#140)
            "/live/song/create_midi_track": self._create_midi_track,
            "/live/track/get/has_midi_input": lambda p: (int(p[0]), self._is_midi(int(p[0]))),
            "/live/track/get/arrangement_clips/start_time": lambda p: (
                int(p[0]), *[c["start"] for c in self._arr(int(p[0]))]),
            "/live/track/get/arrangement_clips/length": lambda p: (
                int(p[0]), *[c["length"] for c in self._arr(int(p[0]))]),
            "/live/song/get/is_playing": lambda p: (self.is_playing, *p),
            "/live/song/get/current_song_time": lambda p: (self.song_time, *p),
            "/live/song/set/current_song_time": self._set_song_time,
            "/live/song/get/cue_points": lambda p: tuple(v for c in self.cue_points for v in c),
            "/live/song/cue_point/add_or_delete": self._toggle_cue,
            "/live/song/cue_point/set/name": self._set_cue_name,
            **({"/live/track/create_midi_clip": self._create_midi_clip,
                "/live/track/arrangement_clip/add/notes": self._add_notes,
                "/live/track/arrangement_clip/get/notes": self._get_notes}
               if self.arrangement_extension_installed else {}),
        }

    # -- arrangement model (#140) ------------------------------------------------------------

    def _is_midi(self, idx: int) -> bool:
        track = self.tracks[idx]
        return bool(track.get("midi", not track.get("audio", False)))

    def _arr(self, idx: int) -> list:
        return self.tracks[idx].setdefault("arrangement", [])

    def _record(self, kind: str, *entry) -> None:
        if kind not in self.not_undoable:
            self.undo_stack.append((kind, *entry))

    def _create_midi_track(self, p: tuple) -> None:
        index = int(p[0])
        track = {"name": f"{len(self.tracks) + 1}-MIDI", "mute": False, "midi": True,
                 "slots": [None] * self.num_scenes, "arrangement": []}
        pos = len(self.tracks) if index == -1 else index
        self.tracks.insert(pos, track)
        self._record("track", pos)

    def _create_midi_clip(self, p: tuple) -> None:
        # track.py:15/18: params[0] first (IndexError for the no-argument probe).
        if p[0] == "*":
            raise ValueError("'*' not used here")
        idx = int(p[0])
        start, length = float(p[1]), float(p[2])
        if not self._is_midi(idx):
            raise RuntimeError("Track.create_midi_clip: not a MIDI track")
        clips = self._arr(idx)
        clips.append({"start": start, "length": length, "notes": []})
        clips.sort(key=lambda c: c["start"])
        self._record("arr_clip", idx, start)

    def _add_notes(self, p: tuple) -> None:
        idx = int(p[0])
        clip = self._arr(idx)[int(p[1])]
        values = p[2:]
        if not values or len(values) % 5:
            raise ValueError("notes must be groups of 5")
        notes = [tuple(values[i:i + 5]) for i in range(0, len(values), 5)]
        if self.drop_notes_on_add:
            notes = notes[:-self.drop_notes_on_add]
        old = list(clip["notes"])
        clip["notes"] += [(int(a), float(b), float(c), float(d), bool(e))
                          for a, b, c, d, e in notes]
        self._record("notes", idx, int(p[1]), old)

    def _get_notes(self, p: tuple) -> tuple:
        idx, ci = int(p[0]), int(p[1])
        clip = self._arr(idx)[ci]
        return (idx, ci, *[v for n in clip["notes"] for v in n])

    def _set_song_time(self, p: tuple) -> None:
        old = self.song_time
        self.song_time = float(p[0])
        self._record("song_time", old)

    def _toggle_cue(self, p: tuple) -> None:
        at = self.song_time + self.cue_time_offset
        for i, (_name, t) in enumerate(self.cue_points):
            if abs(t - at) < 1e-9:
                removed = self.cue_points.pop(i)
                self._record("cue_del", i, removed)
                return
        self.cue_points.append([self.cue_default_name, at])
        self._record("cue_add", len(self.cue_points) - 1)

    def _set_cue_name(self, p: tuple) -> None:
        i = p[0]
        old = self.cue_points[i][0]
        self.cue_points[i][0] = p[1]
        self._record("cue_name", i, old)

    def _undo_entry(self, entry: tuple) -> None:
        kind = entry[0]
        if kind == "arr_clip":
            clips = self._arr(entry[1])
            clips[:] = [c for c in clips if c["start"] != entry[2]]
        elif kind == "notes":
            self._arr(entry[1])[entry[2]]["notes"] = entry[3]
        elif kind == "song_time":
            self.song_time = entry[1]
        elif kind == "cue_add":
            del self.cue_points[entry[1]]
        elif kind == "cue_del":
            self.cue_points.insert(entry[1], entry[2])
        elif kind == "cue_name":
            self.cue_points[entry[1]][0] = entry[2]

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
        if self.undo_noop:
            return
        for _ in range(self.undo_batch):
            if not self.undo_stack:
                return
            self._undo_one(self.undo_stack.pop())

    def _undo_one(self, entry: tuple) -> None:
        if entry[0] in ("arr_clip", "notes", "song_time", "cue_add", "cue_del", "cue_name"):
            self._undo_entry(entry)
        elif entry[0] == "track":
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
            handled = self._process(host, address, params)
            stall = self.stall_after.get(address, 0.0)
            if stall > 0 and handled:  # a failed call (e.g. a probe) did not touch the song
                time.sleep(stall)  # busy: nothing is read, processed or answered meanwhile

    def _process(self, host: str, address: str, params: tuple) -> bool:
        """Handle one message; False if the handler is missing or raised."""
        with self._lock:
            self.received.append((address, params))
            handlers = self._handlers()
            if address not in handlers:
                self._send(host, "/live/error", (f"Unknown OSC address: {address}",))
                return False
            try:
                rv = handlers[address](params)
            except Exception as exc:
                self._send(host, "/live/error", (f"Error handling OSC message: {exc}",))
                return False
            finally:
                if address in self.drop_next_marker_after:
                    self._drop_next_marker = True
            if is_marker(address, params):
                if self._drop_next_marker:
                    self._drop_next_marker = False
                elif address not in self.drop:
                    self._send(host, address, rv)
                return True
            if address in self.drop:
                return True
            for extra in self.extra_before:
                self._send(host, *extra)
            if address in self.raw_reply:
                self._emit(self.raw_reply[address], host)
            elif rv is not None:
                self._send(host, address, rv)
            return True

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
