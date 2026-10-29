"""Read-back after create_audio_clip (#50 user run 1, PR for issue #50 follow-up).

User run 1 in Live 12.4.5: Live made the new track and the clip and played it, but the script
reported "read-back ... does not show exactly the new clip (file_path=None)". Live had renamed
the new track after the clip ("3 centre s1001"). The old read-back compared all track names,
so it never asked for the file path. A clip that becomes visible only a moment later would
have failed the same way. CI only: the fake simulates both; Live's real timing is not known.
"""

from __future__ import annotations

import json
import struct

import pytest
from conftest import TEST_TIMEOUT_S, registry_with

from bridge.capabilities import CapabilityGate
from bridge.clip_import import (
    READBACK_POLL_INTERVAL_S,
    READBACK_WINDOW_S,
    ActionLog,
    ClipImporter,
    ImportAborted,
    SlotState,
    same_except_track_name,
)
from bridge.osc_client import ADDRESSES, AbletonBridge

IMPORT_CAPS = ("clip_slot.create_audio_clip", "song.create_audio_track", "song.undo")
CREATE_CLIP = "/live/clip_slot/create_audio_clip"
UNDO = "/live/song/undo"
RENAMED = "3 centre s1001"


def wav_file(path) -> str:
    data = b"\x00\x00" * 4
    fmt = struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data"
            + struct.pack("<I", len(data)) + data)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


@pytest.fixture
def ibridge(fake, transport, tmp_path):
    gate = CapabilityGate(registry_with(tmp_path, set(ADDRESSES) - {"song.create_audio_track"}),
                          allow_untested=IMPORT_CAPS)
    return AbletonBridge(transport, gate)


@pytest.fixture
def midi_set(fake):
    """User run 1: two MIDI tracks, 8 scenes."""
    fake.num_scenes = 8
    fake.tracks = [{"name": "1-MIDI", "mute": False, "slots": [None] * 8},
                   {"name": "2-MIDI", "mute": False, "slots": [None] * 8}]
    return fake


@pytest.fixture
def log(tmp_path):
    return ActionLog(tmp_path / "actions.jsonl", clock=lambda: "T")


def entries(log):
    return [json.loads(x) for x in log.path.read_text(encoding="utf-8").splitlines()]


BEFORE = SlotState(("1-MIDI", "2-MIDI"), ())


def undos(fake):
    return sum(1 for a, _ in fake.payload() if a == UNDO)


# -- the user's run 1, reproduced --------------------------------------------------------------


@pytest.mark.parametrize("delay", [0.0, 0.3], ids=["rename-only", "rename-and-late-clip"])
def test_user_run_1_renamed_track_is_accepted(ibridge, midi_set, log, tmp_path, delay):
    """Regression for #50 run 1: before the fix this raised ImportAborted(file_path=None)."""
    midi_set.rename_on_clip = RENAMED
    midi_set.clip_delay_s = delay
    p = wav_file(tmp_path / "centre_s1001_v0.wav")
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=p, track_index=None, slot_index=0, num_slots=8, expected_before=BEFORE)
    assert out.done and out.file_path_read == p and not out.outcome_unknown
    assert out.target_name_after == RENAMED
    assert out.after.track_names == ("1-MIDI", "2-MIDI", RENAMED)
    last = entries(log)[-1]
    assert last["ok"] is True
    assert last["target_track_name"] == {"before": "3-Audio", "after": RENAMED}
    if delay:
        assert last["polls"] > 1


@pytest.mark.parametrize("reverts_rename", [True, False])
def test_undo_after_rename_restores_set(ibridge, midi_set, log, tmp_path, reverts_rename):
    """Whether Live's undo also reverts the rename is not known: both must pass."""
    midi_set.rename_on_clip = RENAMED
    midi_set.undo_reverts_rename = reverts_rename
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=wav_file(tmp_path / "k.wav"), track_index=None, slot_index=0,
                  num_slots=8, expected_before=BEFORE)
    assert imp.undo_step(out, expect_now=out.after, expect_after=out.after_track,
                         label="undo_clip")
    assert imp.undo_step(out, expect_now=out.after_track, expect_after=BEFORE,
                         label="undo_track")
    assert [t["name"] for t in midi_set.tracks] == ["1-MIDI", "2-MIDI"]
    assert undos(midi_set) == 2


# -- polling ---------------------------------------------------------------------------------


def test_late_clip_on_existing_track(ibridge, fake, log, tmp_path):
    fake.tracks = [{"name": "Kick", "mute": False, "audio": True, "slots": [None] * 4}]
    fake.clip_delay_s = 0.4
    p = wav_file(tmp_path / "k.wav")
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=p, track_index=0, slot_index=2, num_slots=4,
                  expected_before=SlotState(("Kick",), (False,) * 4))
    assert out.done and entries(log)[-1]["polls"] >= 3


def test_file_path_nil_until_ready(ibridge, fake, log, tmp_path):
    """has_clip is already True but file_path reads as nil for a while."""
    fake.tracks = [{"name": "Kick", "mute": False, "audio": True, "slots": [None] * 4}]
    fake.file_path_delay_s = 0.4
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                  num_slots=4, expected_before=SlotState(("Kick",), (False,) * 4))
    assert out.done
    last = entries(log)[-1]
    assert last["polls"] >= 2 and last["file_path_errors"]
    assert "BridgeProtocolError" in last["file_path_errors"][0]


def test_clip_never_visible_is_unknown_and_blocks_undo(ibridge, fake, log, tmp_path):
    fake.tracks = [{"name": "Kick", "mute": False, "audio": True, "slots": [None] * 4}]
    fake.clip_delay_s = 30.0  # never within the window
    before = SlotState(("Kick",), (False,) * 4)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S, readback_window_s=0.5)
    with pytest.raises(ImportAborted, match=r"read-back after \d+ read\(s\) in 0.5 s"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                num_slots=4, expected_before=before)
    out = imp.last_outcome
    assert out.outcome_unknown and not out.done
    assert entries(log)[-1]["ok"] is False and entries(log)[-1]["polls"] >= 3
    with pytest.raises(ImportAborted, match="unknown outcome"):
        imp.undo_step(out, expect_now=before, expect_after=before, label="undo_clip")
    assert undos(fake) == 0


def test_new_track_never_visible_is_unknown(ibridge, midi_set, log, tmp_path):
    midi_set._create_audio_track = lambda p: None  # confirmed, but no track appears
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S, readback_window_s=0.3)
    with pytest.raises(ImportAborted, match="not an empty audio track"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=None, slot_index=0,
                num_slots=8, expected_before=BEFORE)
    assert imp.last_outcome.outcome_unknown
    assert CREATE_CLIP not in [a for a, p in midi_set.payload() if p]


def test_other_track_renamed_is_still_a_mismatch(ibridge, fake, log, tmp_path):
    """Only the target track's name is free; a change elsewhere is not accepted."""
    fake.tracks = [{"name": "Kick", "mute": False, "audio": True, "slots": [None] * 4},
                   {"name": "Bass", "mute": False, "slots": [None] * 4}]
    orig = fake._create_audio_clip

    def and_rename_other(p):
        orig(p)
        fake.tracks[1]["name"] = "Bass 2"

    fake._create_audio_clip = and_rename_other
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S, readback_window_s=0.3)
    with pytest.raises(ImportAborted, match="does not show exactly"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                num_slots=4, expected_before=SlotState(("Kick", "Bass"), (False,) * 4))
    assert imp.last_outcome.outcome_unknown


def test_undo_refused_when_another_track_was_renamed(ibridge, fake, log, tmp_path):
    fake.tracks = [{"name": "Kick", "mute": False, "audio": True, "slots": [None] * 4},
                   {"name": "Bass", "mute": False, "slots": [None] * 4}]
    before = SlotState(("Kick", "Bass"), (False,) * 4)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0,
                  num_slots=4, expected_before=before)
    fake.tracks[1]["name"] = "Bass (user)"
    with pytest.raises(ImportAborted, match="undo NOT sent"):
        imp.undo_step(out, expect_now=out.after, expect_after=before, label="undo_clip")
    assert undos(fake) == 0


# -- _poll and same_except_track_name, without a server --------------------------------------


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make_importer(clock, window=1.0, interval=0.1):
    return ClipImporter(None, None, timeout_s=1.0, readback_window_s=window,
                        poll_interval_s=interval, clock=clock, sleep=clock.sleep)


def test_poll_stops_at_first_match():
    clock = FakeClock()
    results = iter([False, False, True, True])
    value, ok, polls = make_importer(clock)._poll(lambda: ("v", next(results)))
    assert (value, ok, polls) == ("v", True, 3)
    assert clock.sleeps == [0.1, 0.1]


def test_poll_never_reports_a_match_it_did_not_see():
    clock = FakeClock()
    value, ok, polls = make_importer(clock, window=1.0, interval=0.25)._poll(
        lambda: (clock.t, False))
    assert ok is False
    assert polls == 5  # t = 0, 0.25, 0.5, 0.75, 1.0 -> deadline reached at the 5th read
    assert value == pytest.approx(1.0)


def test_poll_reads_at_least_once_with_zero_window():
    clock = FakeClock()
    assert make_importer(clock, window=0.0)._poll(lambda: (1, False)) == (1, False, 1)
    assert clock.sleeps == []


def test_window_constants():
    assert READBACK_WINDOW_S == 2.0 and READBACK_POLL_INTERVAL_S == 0.1


@pytest.mark.parametrize("a,b,idx,expected", [
    ((("A", "B"), (True,)), (("A", "X"), (True,)), 1, True),   # target renamed
    ((("A", "B"), (True,)), (("X", "B"), (True,)), 1, False),  # other renamed
    ((("A", "B"), (True,)), (("A", "B"), (False,)), 1, False),  # slot differs
    ((("A", "B"), ()), (("A", "B", "C"), ()), 2, False),       # count differs
    ((("A", "B"), ()), (("A", "B"), ()), 5, True),             # index beyond: all compared
    ((("A", "B"), ()), (("A", "C"), ()), 5, False),
])
def test_same_except_track_name(a, b, idx, expected):
    assert same_except_track_name(SlotState(*a), SlotState(*b), idx) is expected
