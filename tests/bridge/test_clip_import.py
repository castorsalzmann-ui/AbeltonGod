"""Clip import (#50): bridge calls and ``bridge.clip_import`` against the fake AbletonOSC.

CI only: nothing here talks to Ableton Live. The fake mirrors AbletonOSC's reply semantics and
a small song model; whether Live behaves the same is what the user's run in #50 shows.
Expected wire traffic and states are written out by hand, not taken from the module.
"""

from __future__ import annotations

import json
import random
import struct

import pytest
from conftest import TEST_TIMEOUT_S, registry_with

from bridge.capabilities import CapabilityGate
from bridge.clip_import import (
    ActionLog,
    ActionLogError,
    ClipImporter,
    ImportAborted,
    ImportInterrupted,
    ImportPathError,
    SlotState,
    first_empty_slot,
    read_state,
    same_file_path,
    validate_wav_path,
)
from bridge.osc_client import (
    ADDRESSES,
    AbletonBridge,
    AbletonOSCError,
    BridgeProtocolError,
    BridgeTimeoutError,
    ExtensionMissingError,
)

IMPORT_CAPS = ("clip_slot.create_audio_clip", "song.create_audio_track", "song.undo")
CREATE_CLIP = "/live/clip_slot/create_audio_clip"
CREATE_TRACK = "/live/song/create_audio_track"
UNDO = "/live/song/undo"


def wav_file(path, frames: int = 4) -> str:
    """A minimal valid 16-bit mono WAV, written by hand."""
    data = b"\x00\x00" * frames
    fmt = struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack(
        "<I", len(data)) + data
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


@pytest.fixture
def ibridge(fake, transport, tmp_path):
    """Bridge as the check script builds it: tested reads + explicit import override."""
    gate = CapabilityGate(registry_with(tmp_path, set(ADDRESSES) - {"song.create_audio_track"}),
                          allow_untested=IMPORT_CAPS)
    return AbletonBridge(transport, gate)


@pytest.fixture
def audio_set(fake):
    fake.tracks = [
        {"name": "1-Audio", "mute": False, "audio": True, "slots": [None] * 4},
        {"name": "2-MIDI", "mute": False, "slots": [None] * 4},
        {"name": "3-Audio", "mute": False, "audio": True,
         "slots": ["C:\\old.wav", None, None, None]},
    ]
    return fake


@pytest.fixture
def log(tmp_path):
    return ActionLog(tmp_path / "logs" / "actions.jsonl", clock=lambda: "T")


def log_lines(log: ActionLog) -> list[dict]:
    return [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]


# -- path validation -------------------------------------------------------------------------


def test_validate_accepts_absolute_wav(tmp_path):
    p = wav_file(tmp_path / "Kick.WAV")
    assert validate_wav_path(p) == p


@pytest.mark.parametrize("case", ["relative", "missing", "suffix", "dir", "not_riff", "rifx",
                                  "not_wave", "short", "nul", "empty"])
def test_validate_rejects(tmp_path, case):
    good = wav_file(tmp_path / "k.wav")
    if case == "relative":
        p = "k.wav"
    elif case == "missing":
        p = str(tmp_path / "nope.wav")
    elif case == "suffix":
        p = str(tmp_path / "k.aif")
        (tmp_path / "k.aif").write_bytes((tmp_path / "k.wav").read_bytes())
    elif case == "dir":
        (tmp_path / "d.wav").mkdir()
        p = str(tmp_path / "d.wav")
    elif case == "not_riff":
        (tmp_path / "x.wav").write_bytes(b"RIFX" + b"\x00" * 40)
        p = str(tmp_path / "x.wav")
    elif case in ("rifx", "not_wave"):
        data = bytearray((tmp_path / "k.wav").read_bytes())
        if case == "rifx":
            data[:4] = b"RIFX"  # big-endian RIFF: WAVE field stays valid
        else:
            data[8:12] = b"AVI "
        (tmp_path / "y.wav").write_bytes(bytes(data))
        p = str(tmp_path / "y.wav")
    elif case == "short":
        (tmp_path / "s.wav").write_bytes(b"RIFF\x00")
        p = str(tmp_path / "s.wav")
    elif case == "nul":
        p = good + "\x00"
    else:
        p = ""
    with pytest.raises(ImportPathError):
        validate_wav_path(p)


def test_validate_library_root(tmp_path):
    inside = tmp_path / "lib"
    inside.mkdir()
    p = wav_file(inside / "k.wav")
    outside = wav_file(tmp_path / "o.wav")
    assert validate_wav_path(p, library_root=inside) == p
    with pytest.raises(ImportPathError, match="outside"):
        validate_wav_path(outside, library_root=inside)


def test_same_file_path():
    assert same_file_path("/a/b/../c.wav", "/a/c.wav")
    assert not same_file_path("/a/c.wav", "/a/d.wav")


# -- bridge calls: wire format ---------------------------------------------------------------


def test_create_audio_clip_sends_exact_address_and_args(ibridge, audio_set, tmp_path):
    p = wav_file(tmp_path / "k.wav")
    ibridge.create_audio_clip(0, 1, p)
    assert audio_set.payload() == [(CREATE_CLIP, (0, 1, p))]
    assert audio_set.tracks[0]["slots"][1] == p


def test_create_audio_clip_keeps_non_ascii_path(ibridge, audio_set, tmp_path):
    p = wav_file(tmp_path / "Kick äöü ß 東京.wav")
    ibridge.create_audio_clip(0, 0, p)
    assert audio_set.tracks[0]["slots"][0] == p
    assert ibridge.get_clip_file_path(0, 0) == p


@pytest.mark.parametrize("bad", [("x", 0), (0, -1), (True, 0), (0, 1.0)])
def test_create_audio_clip_rejects_bad_indices(ibridge, fake, tmp_path, bad):
    with pytest.raises(ValueError):
        ibridge.create_audio_clip(bad[0], bad[1], wav_file(tmp_path / "k.wav"))
    assert fake.payload() == []


@pytest.mark.parametrize("path", ["k.wav", "", "rel/k.wav", 5, "/abs/k\x00.wav"])
def test_create_audio_clip_rejects_relative_path(ibridge, fake, path):
    with pytest.raises(ValueError):
        ibridge.create_audio_clip(0, 0, path)
    ibridge.ping()
    fake.wait_received(2)
    assert fake.payload() == []


def test_create_audio_clip_on_midi_track_is_abletonosc_error(ibridge, audio_set, tmp_path):
    with pytest.raises(AbletonOSCError) as err:
        ibridge.create_audio_clip(1, 0, wav_file(tmp_path / "k.wav"))
    assert not isinstance(err.value, ExtensionMissingError)
    assert "audio track" in str(err.value)


def test_create_audio_clip_without_extension(ibridge, audio_set, tmp_path):
    audio_set.extension_installed = False
    with pytest.raises(ExtensionMissingError, match="install_abletonosc_extension"):
        ibridge.create_audio_clip(0, 0, wav_file(tmp_path / "k.wav"))
    assert audio_set.tracks[0]["slots"] == [None] * 4


def test_probe_extension(ibridge, audio_set):
    assert ibridge.probe_audio_clip_extension() is True
    assert audio_set.payload() == [(CREATE_CLIP, ())]
    assert all(s is None for t in audio_set.tracks[:2] for s in t["slots"])
    audio_set.extension_installed = False
    assert ibridge.probe_audio_clip_extension() is False


def test_probe_extension_handler_without_error_is_protocol_error(ibridge, fake):
    fake.extension_installed = True
    fake._create_audio_clip = lambda p: None  # some other handler that accepts no args
    with pytest.raises(BridgeProtocolError):
        ibridge.probe_audio_clip_extension()


def test_other_unknown_address_is_not_reported_as_missing_extension():
    from bridge.osc_client import _as_extension_missing
    exc = AbletonOSCError("AbletonOSC reported an error: Unknown OSC address: /live/other")
    assert _as_extension_missing(exc, CREATE_CLIP) is exc


def test_create_audio_track_wire(ibridge, audio_set):
    ibridge.create_audio_track()
    assert audio_set.payload() == [(CREATE_TRACK, (-1,))]
    assert audio_set.tracks[-1]["audio"] is True
    with pytest.raises(ValueError):
        ibridge.create_audio_track(-2)


def test_reads_wire_and_values(ibridge, audio_set):
    assert ibridge.get_num_scenes() == 4
    assert [ibridge.get_track_has_audio_input(i) for i in range(3)] == [True, False, True]
    assert ibridge.get_clip_slot_has_clip(2, 0) is True
    assert ibridge.get_clip_slot_has_clip(2, 1) is False
    assert ibridge.get_clip_file_path(2, 0) == "C:\\old.wav"
    assert audio_set.payload() == [
        ("/live/song/get/num_scenes", ()),
        ("/live/track/get/has_audio_input", (0,)),
        ("/live/track/get/has_audio_input", (1,)),
        ("/live/track/get/has_audio_input", (2,)),
        ("/live/clip_slot/get/has_clip", (2, 0)),
        ("/live/clip_slot/get/has_clip", (2, 1)),
        ("/live/clip/get/file_path", (2, 0)),
    ]


def test_file_path_of_empty_slot_is_error(ibridge, audio_set):
    with pytest.raises(AbletonOSCError):
        ibridge.get_clip_file_path(0, 0)


@pytest.mark.parametrize("raw", [(), ("x",), (2,), (1.0,), (True, True)])
def test_bool_reply_rejects_malformed(ibridge, raw):
    with pytest.raises(BridgeProtocolError):
        ibridge._bool_reply(raw, "x")


@pytest.mark.parametrize("value", [-1, "4", True, 2.0])
def test_num_scenes_rejects_malformed(ibridge, fake, value):
    fake.num_scenes = value
    with pytest.raises(BridgeProtocolError):
        ibridge.get_num_scenes()


def test_mismatched_prefix_is_protocol_error(ibridge, fake):
    orig = fake._handlers
    fake._handlers = lambda: {**orig(), "/live/clip_slot/get/has_clip": lambda p: (9, 9, True)}
    with pytest.raises(BridgeProtocolError):
        ibridge.get_clip_slot_has_clip(0, 0)


# -- importer: happy paths -------------------------------------------------------------------


def expected_state(fake, track):
    names = tuple(t["name"] for t in fake.tracks)
    if track is None or track >= len(fake.tracks):
        return SlotState(names, ())
    return SlotState(names, tuple(s is not None for s in fake.tracks[track]["slots"]))


def test_import_into_existing_audio_track_and_undo(ibridge, audio_set, log, tmp_path):
    p = wav_file(tmp_path / "k.wav")
    before = expected_state(audio_set, 2)
    assert before == SlotState(("1-Audio", "2-MIDI", "3-Audio"), (True, False, False, False))
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=p, track_index=2, slot_index=1, num_slots=4, expected_before=before)
    assert out.done and out.file_path_read == p
    assert audio_set.tracks[2]["slots"] == ["C:\\old.wav", p, None, None]
    assert [(s.label, s.outcome) for s in out.steps] == [("create_audio_clip", "confirmed")]
    entries = log_lines(log)
    assert [(e["action"], e["status"]) for e in entries] == [
        ("create_audio_clip", "planned"), ("create_audio_clip", "read_back")]
    assert entries[0]["params"] == {"track_index": 2, "slot_index": 1, "path": p}
    assert entries[0]["before"] == {"track_names": ["1-Audio", "2-MIDI", "3-Audio"],
                                    "has_clip": [1, 0, 0, 0]}
    assert entries[1]["ok"] is True and entries[1]["file_path"] == p

    assert imp.undo_step(out, expect_now=out.after, expect_after=before, label="undo_clip")
    assert audio_set.tracks[2]["slots"] == ["C:\\old.wav", None, None, None]
    assert out.undos_sent == 1
    # Never more undos than confirmed writes.
    with pytest.raises(ImportAborted, match="undone already"):
        imp.undo_step(out, expect_now=before, expect_after=before, label="undo_again")
    assert sum(1 for a, _ in audio_set.payload() if a == UNDO) == 1


def test_import_into_new_track_and_two_undos(ibridge, audio_set, log, tmp_path):
    p = wav_file(tmp_path / "k.wav")
    before = SlotState(("1-Audio", "2-MIDI", "3-Audio"), ())
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=p, track_index=None, slot_index=0, num_slots=4, expected_before=before)
    assert out.done and out.track_index == 3 and out.created_track
    assert audio_set.tracks[3]["slots"] == [p, None, None, None]
    assert out.after_track == SlotState(("1-Audio", "2-MIDI", "3-Audio", "4-Audio"),
                                        (False,) * 4)
    assert [e["action"] + ":" + e["status"] for e in log_lines(log)] == [
        "create_audio_track:planned", "create_audio_track:read_back",
        "create_audio_clip:planned", "create_audio_clip:read_back"]
    assert imp.undo_step(out, expect_now=out.after, expect_after=out.after_track,
                         label="undo_clip")
    assert imp.undo_step(out, expect_now=out.after_track, expect_after=before,
                         label="undo_track")
    assert [t["name"] for t in audio_set.tracks] == ["1-Audio", "2-MIDI", "3-Audio"]


# -- importer: refusals before anything is sent ----------------------------------------------


def writes(fake):
    return [a for a, _ in fake.payload() if a in (CREATE_CLIP, CREATE_TRACK, UNDO)]


def test_refuses_midi_track(ibridge, audio_set, log, tmp_path):
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="not an audio track"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=1, slot_index=0, num_slots=4,
                expected_before=expected_state(audio_set, 1))
    assert writes(audio_set) == [] and not log.path.exists()


def test_refuses_occupied_slot(ibridge, audio_set, log, tmp_path):
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="not empty"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=2, slot_index=0, num_slots=4,
                expected_before=expected_state(audio_set, 2))
    assert writes(audio_set) == [] and audio_set.tracks[2]["slots"][0] == "C:\\old.wav"


def test_refuses_slot_out_of_range(ibridge, audio_set, log, tmp_path):
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    for slot in (-1, 4):
        with pytest.raises(ImportAborted, match="does not exist"):
            imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=slot,
                    num_slots=4, expected_before=expected_state(audio_set, 0))
    assert writes(audio_set) == []


def test_refuses_when_set_changed_since_plan(ibridge, audio_set, log, tmp_path):
    plan = expected_state(audio_set, 0)
    audio_set.tracks[0]["slots"][3] = "C:\\user.wav"  # the user added a clip meanwhile
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="changed between"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0, num_slots=4,
                expected_before=plan)
    assert writes(audio_set) == []


def test_unwritable_log_sends_nothing(ibridge, audio_set, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    log = ActionLog(blocker / "actions.jsonl")  # parent is a file -> OSError
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ActionLogError):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0, num_slots=4,
                expected_before=expected_state(audio_set, 0))
    assert writes(audio_set) == []


def test_log_rejects_non_json(log):
    with pytest.raises(ActionLogError):
        log.append({"x": float("nan")})
    with pytest.raises(ActionLogError):
        log.append({"x": object()})


# -- importer: failures after a write --------------------------------------------------------


def test_extension_missing_during_import(ibridge, audio_set, log, tmp_path):
    audio_set.extension_installed = False
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="ExtensionMissingError"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0, num_slots=4,
                expected_before=expected_state(audio_set, 0))
    assert [e["status"] for e in log_lines(log)] == ["planned", "error"]
    assert not imp.last_outcome.outcome_unknown


def test_live_refuses_clip_is_error_and_logged(ibridge, audio_set, log, tmp_path):
    audio_set.tracks[0]["frozen"] = True
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="AbletonOSCError"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0, num_slots=4,
                expected_before=expected_state(audio_set, 0))
    assert log_lines(log)[-1]["status"] == "error"


def test_timed_out_write_is_read_back_and_blocks_undo(ibridge, audio_set, log, tmp_path):
    p = wav_file(tmp_path / "k.wav")
    before = expected_state(audio_set, 0)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    orig = ibridge.create_audio_clip

    def held_clip(*a, **k):
        audio_set.hold()  # Live's GUI thread blocked: processed, replies held
        audio_set.release_after(TEST_TIMEOUT_S * 1.5)
        return orig(*a, **k)

    ibridge.create_audio_clip = held_clip
    with pytest.raises(ImportAborted, match="timed out"):
        imp.run(path=p, track_index=0, slot_index=0, num_slots=4, expected_before=before)
    out = imp.last_outcome
    assert out.outcome_unknown
    timeout_entry = log_lines(log)[-1]
    assert timeout_entry["status"] == "timeout"
    # The read-back (3x timeout) sees the late-applied clip.
    assert timeout_entry["readback"]["has_clip"] == [1, 0, 0, 0]
    with pytest.raises(ImportAborted, match="unknown outcome"):
        imp.undo_step(out, expect_now=before, expect_after=before, label="undo_clip")
    assert UNDO not in writes(audio_set)


def test_timed_out_write_with_failed_readback(ibridge, audio_set, log, tmp_path):
    before = expected_state(audio_set, 0)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    orig = ibridge.create_audio_clip

    def held_forever(*a, **k):
        audio_set.hold()
        return orig(*a, **k)

    ibridge.create_audio_clip = held_forever
    with pytest.raises(ImportAborted, match="read-back failed"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                num_slots=4, expected_before=before)
    assert log_lines(log)[-1]["readback"] == "read-back failed: BridgeTimeoutError"


def test_interrupt_during_write_marks_unknown(ibridge, audio_set, log, tmp_path):
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    ibridge.create_audio_clip = interrupted
    with pytest.raises(ImportInterrupted):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                num_slots=4, expected_before=expected_state(audio_set, 0))
    assert imp.last_outcome.outcome_unknown
    assert log_lines(log)[-1]["status"] == "interrupted"


def test_readback_failure_after_confirmed_write_blocks_undo(ibridge, audio_set, log,
                                                            tmp_path):
    before = expected_state(audio_set, 0)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    orig = ibridge.get_clip_file_path

    def broken(*a, **k):
        raise BridgeTimeoutError("simulated")

    ibridge.get_clip_file_path = broken
    with pytest.raises(ImportAborted, match="read-back failed"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                num_slots=4, expected_before=before)
    ibridge.get_clip_file_path = orig
    assert imp.last_outcome.outcome_unknown
    with pytest.raises(ImportAborted):
        imp.undo_step(imp.last_outcome, expect_now=before, expect_after=before, label="u")
    assert UNDO not in writes(audio_set)


def test_wrong_file_path_read_back_is_failure(ibridge, audio_set, log, tmp_path):
    orig = audio_set._get_file_path
    audio_set._get_file_path = lambda p: (*orig(p)[:2], "C:\\other.wav")
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="does not show exactly"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                num_slots=4, expected_before=expected_state(audio_set, 0))
    assert log_lines(log)[-1]["ok"] is False


def test_clip_in_other_slot_is_failure(ibridge, audio_set, log, tmp_path):
    orig = audio_set._create_audio_clip
    audio_set._create_audio_clip = lambda p: orig((p[0], p[1] + 1, p[2]))
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="does not show exactly"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                num_slots=4, expected_before=expected_state(audio_set, 0))


def test_extra_clip_in_other_slot_is_failure(ibridge, audio_set, log, tmp_path):
    """Right slot filled, but another slot of the track changed too: not done."""
    orig = audio_set._create_audio_clip

    def two_clips(p):
        orig(p)
        audio_set.tracks[int(p[0])]["slots"][3] = p[2]

    audio_set._create_audio_clip = two_clips
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="does not show exactly"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                num_slots=4, expected_before=expected_state(audio_set, 0))


def test_new_track_not_audio_stops_before_clip(ibridge, audio_set, log, tmp_path):
    orig = audio_set._create_audio_track

    def midi_track(p):
        orig(p)
        audio_set.tracks[-1]["audio"] = False

    audio_set._create_audio_track = midi_track
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="not an empty audio track"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=None, slot_index=0,
                num_slots=4, expected_before=SlotState(("1-Audio", "2-MIDI", "3-Audio"), ()))
    assert CREATE_CLIP not in writes(audio_set)


def test_new_track_not_at_end_stops_before_clip(ibridge, audio_set, log, tmp_path):
    # The last old track is an empty audio track, so after an insert at index 0 the target
    # index points at an empty audio track: only the track-order check can catch it.
    audio_set.tracks[2]["slots"] = [None] * 4
    orig = audio_set._create_audio_track
    audio_set._create_audio_track = lambda p: orig((0,))
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="not an empty audio track"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=None, slot_index=0,
                num_slots=4, expected_before=SlotState(("1-Audio", "2-MIDI", "3-Audio"), ()))
    assert CREATE_CLIP not in writes(audio_set)


# -- undo guards -----------------------------------------------------------------------------


def test_undo_refused_when_set_changed_after_import(ibridge, audio_set, log, tmp_path):
    before = expected_state(audio_set, 0)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                  num_slots=4, expected_before=before)
    audio_set.tracks[0]["slots"][2] = "C:\\user.wav"  # user action after the import
    with pytest.raises(ImportAborted, match="undo NOT sent"):
        imp.undo_step(out, expect_now=out.after, expect_after=before, label="undo_clip")
    assert UNDO not in writes(audio_set)
    assert log_lines(log)[-1]["status"] == "refused"


def test_undo_that_reverts_something_else_is_reported(ibridge, audio_set, log, tmp_path):
    audio_set.clip_undoable = False  # Live does not record the clip as an undo step
    audio_set.undo_stack = [(1, True)]  # the user's last action: unmute of track 1
    before = expected_state(audio_set, 0)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                  num_slots=4, expected_before=before)
    assert imp.undo_step(out, expect_now=out.after, expect_after=before,
                         label="undo_clip") is False
    assert log_lines(log)[-1]["ok"] is False
    assert "read-back differs" in out.steps[-1].detail


# -- property test over the input range ------------------------------------------------------


def test_random_sets_import_lands_exactly_and_undo_restores(fake, transport, tmp_path):
    """Seeded random sets: any audio track, any empty slot; the import changes exactly that
    slot and one undo restores the state read before."""
    gate = CapabilityGate(registry_with(tmp_path, set(ADDRESSES) - {"song.create_audio_track"}),
                          allow_untested=IMPORT_CAPS)
    bridge = AbletonBridge(transport, gate)
    p = wav_file(tmp_path / "k.wav")
    rng = random.Random(5050)
    cases = 0
    for i in range(25):
        scenes = rng.randint(1, 6)
        fake.num_scenes = scenes
        fake.undo_stack = []
        fake.tracks = [{"name": f"T{j}", "mute": False, "audio": rng.random() < 0.6,
                        "slots": [("C:\\x.wav" if rng.random() < 0.4 else None)
                                  for _ in range(scenes)]}
                       for j in range(rng.randint(1, 5))]
        candidates = [(t, s) for t, tr in enumerate(fake.tracks) if tr["audio"]
                      for s in range(scenes) if tr["slots"][s] is None]
        if not candidates:
            continue
        track, slot = rng.choice(candidates)
        log = ActionLog(tmp_path / f"log{i}.jsonl", clock=lambda: "T")
        imp = ClipImporter(bridge, log, timeout_s=TEST_TIMEOUT_S)
        before = read_state(bridge, track, scenes)
        assert before == expected_state(fake, track)
        snapshot = json.dumps(fake.tracks, sort_keys=True)
        out = imp.run(path=p, track_index=track, slot_index=slot, num_slots=scenes,
                      expected_before=before)
        want = [s is not None for s in json.loads(snapshot)[track]["slots"]]
        want[slot] = True
        assert [s is not None for s in fake.tracks[track]["slots"]] == want
        assert imp.undo_step(out, expect_now=out.after, expect_after=before, label="u")
        assert json.dumps(fake.tracks, sort_keys=True) == snapshot
        cases += 1
    assert cases >= 15


def test_first_empty_slot():
    assert first_empty_slot(SlotState((), (True, False, True))) == 1
    assert first_empty_slot(SlotState((), (True, True))) is None
    assert first_empty_slot(SlotState((), ())) is None
