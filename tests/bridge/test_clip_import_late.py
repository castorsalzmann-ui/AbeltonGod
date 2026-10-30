"""Timed-out import writes settled by read-back (#166). CI only, against the fake server.

Same rule as ``arrangement_check`` since #140 (``test_arrangement_late.py``): a timed-out
``create_audio_track`` / ``create_audio_clip`` counts as done only if a later read-back shows
exactly the intended change. Everything else stays an unknown outcome: no undo, nothing more
sent. Nothing here shows how Live behaves.
"""

from __future__ import annotations

import time

import pytest
from conftest import TEST_TIMEOUT_S, registry_with
from test_clip_import import (
    CREATE_CLIP,
    CREATE_TRACK,
    IMPORT_CAPS,
    UNDO,
    expected_state,
    log_lines,
    wav_file,
    writes,
)

from bridge.capabilities import CapabilityGate
from bridge.clip_import import (
    READBACK_AFTER_TIMEOUT_FACTOR,
    ActionLog,
    ClipImporter,
    ImportAborted,
    ImportInterrupted,
    SlotState,
)
from bridge.osc_client import ADDRESSES, AbletonBridge


@pytest.fixture
def ibridge(fake, transport, tmp_path):
    gate = CapabilityGate(registry_with(tmp_path, set(ADDRESSES) - {"song.create_audio_track"}),
                          allow_untested=IMPORT_CAPS)
    return AbletonBridge(transport, gate)


@pytest.fixture
def audio_set(fake):
    """Same set as in test_clip_import.py."""
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


LABEL = {CREATE_TRACK: "create_audio_track", CREATE_CLIP: "create_audio_clip"}
NAMES = ("1-Audio", "2-MIDI", "3-Audio")
WINDOW_S = 0.3  # read-back window for cases that never match


def run_new_track(imp, path):
    """New-track import: both writes are sent (create_audio_track, then create_audio_clip)."""
    return imp.run(path=path, track_index=None, slot_index=0, num_slots=4,
                   expected_before=SlotState(NAMES, ()))


def hold_inside(fake, seconds):
    """hold() from inside a handler (the fake's lock is already held there)."""
    fake._held = []
    fake.released.clear()
    fake.release_after(seconds)


def patch_handler(fake, address, fn):
    attr = "_create_audio_track" if address == CREATE_TRACK else "_create_audio_clip"
    real = getattr(fake, attr)
    setattr(fake, attr, lambda p: fn(real, p))


def assert_stopped_without_undo(imp, fake, address, outcome="timeout"):
    out = imp.last_outcome
    assert out.outcome_unknown and not out.done
    assert out.steps[-1].label == LABEL[address] and out.steps[-1].outcome == outcome
    sent = writes(fake)
    assert UNDO not in sent and sent[-1] == address  # nothing sent after the write
    with pytest.raises(ImportAborted, match="unknown outcome"):
        imp.undo_step(out, expect_now=out.before, expect_after=out.before, label="undo_x")
    assert UNDO not in writes(fake)


# -- settled ----------------------------------------------------------------------------------

@pytest.mark.parametrize("mechanism", ["busy", "lost"])
@pytest.mark.parametrize("address", [CREATE_TRACK, CREATE_CLIP])
def test_settled_write_logs_the_late_reply_and_allows_undo(ibridge, audio_set, log, tmp_path,
                                                           address, mechanism):
    if mechanism == "busy":
        audio_set.stall_after[address] = 2 * TEST_TIMEOUT_S
    else:
        audio_set.drop_next_marker_after.add(address)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = run_new_track(imp, wav_file(tmp_path / "k.wav"))
    assert out.done and not out.outcome_unknown
    step = next(s for s in out.steps if s.label == LABEL[address])
    assert step.outcome == "confirmed" and step.detail.startswith(
        f"late: no confirmation within {TEST_TIMEOUT_S:g} s; read-back matched (1 read(s)); ")
    assert step.detail.endswith("end echo not seen") if mechanism == "lost" else (
        "; end echo after 0." in step.detail)
    entry = [e for e in log_lines(log) if e["action"] == LABEL[address]][-1]
    assert entry["status"] == "read_back" and entry["ok"] is True
    assert entry["note"] == "confirmation timed out; settled by read-back"
    assert entry["late_reply"]["end_seen"] is (mechanism == "busy")
    assert entry["late_reply"]["errors"] == []
    # undo of both writes is allowed and restores the set
    assert imp.undo_step(out, expect_now=out.after, expect_after=out.after_track,
                         label="undo_clip")
    assert imp.undo_step(out, expect_now=out.after_track, expect_after=SlotState(NAMES, ()),
                         label="undo_track")
    assert tuple(t["name"] for t in audio_set.tracks) == NAMES


def test_change_visible_only_at_a_later_poll_is_settled(ibridge, audio_set, log, tmp_path):
    """The settlement polls within the window, not just once (cf. review #167 R5)."""
    audio_set.clip_delay_s = 3 * TEST_TIMEOUT_S  # clip appears after the first reads
    audio_set.drop_next_marker_after.add(CREATE_CLIP)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0, num_slots=4,
                  expected_before=expected_state(audio_set, 0))
    assert out.done
    assert out.steps[-1].outcome == "confirmed" and "(1 read(s))" not in out.steps[-1].detail
    assert log_lines(log)[-1]["polls"] > 1


def test_reads_after_a_timeout_wait_three_times_the_timeout(ibridge, audio_set, log,
                                                            tmp_path):
    """Live busy 3x the timeout after create_audio_track: the first read waits about 2x the
    timeout, which a 3x read timeout covers and a 1.5x one would not (cf. review #167 R6)."""
    assert READBACK_AFTER_TIMEOUT_FACTOR == 3.0
    audio_set.stall_after[CREATE_TRACK] = 3 * TEST_TIMEOUT_S
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = run_new_track(imp, wav_file(tmp_path / "k.wav"))
    assert out.done and out.steps[0].detail.startswith("late:")


@pytest.mark.parametrize("address", [CREATE_TRACK, CREATE_CLIP])
def test_the_last_read_of_a_settlement_gets_the_longer_timeout(ibridge, audio_set, log,
                                                               tmp_path, address):
    """Live stays busy during the read-back: the last read of the check (has_audio_input
    after the track, file_path after the clip) takes 2x the timeout to answer once the write
    is in. Only a read with the 3x timeout (not the bridge default) gets it."""
    attr = "_get_has_audio_input" if address == CREATE_TRACK else "_get_file_path"
    real_read = getattr(audio_set, attr)
    written = {"in": False}

    def slow_read(p):
        if written["in"]:
            time.sleep(2 * TEST_TIMEOUT_S)  # inside the fake's loop: nothing else answered
        return real_read(p)

    def write(real, p):
        real(p)
        written["in"] = True

    def other_write(real, p):  # the next write's normal read-back runs at normal speed
        written["in"] = False
        real(p)

    setattr(audio_set, attr, slow_read)
    patch_handler(audio_set, address, write)
    if address == CREATE_TRACK:
        patch_handler(audio_set, CREATE_CLIP, other_write)
    audio_set.drop_next_marker_after.add(address)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    out = run_new_track(imp, wav_file(tmp_path / "k.wav"))
    assert out.done
    assert next(s for s in out.steps if s.label == LABEL[address]).detail.startswith("late:")


# -- stays unknown ----------------------------------------------------------------------------

@pytest.mark.parametrize("lost_echo", [False, True])
@pytest.mark.parametrize("address", [CREATE_TRACK, CREATE_CLIP])
def test_late_error_stops_without_undo(ibridge, audio_set, log, tmp_path, address, lost_echo):
    """Live is slow past the timeout, then reports an error for the write (with or without
    the end echo). The fake applies the change before raising, so the read-back matches:
    the error alone must keep the outcome unknown."""
    def apply_then_raise(real, p):
        real(p)
        hold_inside(audio_set, 2 * TEST_TIMEOUT_S)
        raise RuntimeError("late failure")

    patch_handler(audio_set, address, apply_then_raise)
    if lost_echo:
        audio_set.drop_next_marker_after.add(address)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="then AbletonOSC reported an error: .*late failure"):
        run_new_track(imp, wav_file(tmp_path / "k.wav"))
    assert_stopped_without_undo(imp, audio_set, address)
    assert "late /live/error" in imp.last_outcome.steps[-1].detail
    entry = log_lines(log)[-1]
    assert entry["status"] == "timeout" and "late /live/error" in entry["note"]
    assert entry["late_reply"]["end_seen"] is (not lost_echo)
    assert "late failure" in entry["late_reply"]["errors"][0]


@pytest.mark.parametrize("address", [CREATE_TRACK, CREATE_CLIP])
def test_write_that_never_happened_stays_unknown(ibridge, audio_set, log, tmp_path, address):
    """The set reads back exactly as before the write: no change, so no match."""
    patch_handler(audio_set, address, lambda real, p: None)
    audio_set.drop_next_marker_after.add(address)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S, readback_window_s=WINDOW_S)
    with pytest.raises(ImportAborted, match="timed out; outcome unknown; read-back"):
        run_new_track(imp, wav_file(tmp_path / "k.wav"))
    assert_stopped_without_undo(imp, audio_set, address)
    entry = log_lines(log)[-1]
    assert entry["status"] == "timeout" and "does not show the change" in entry["note"]


def test_existing_track_clip_that_never_happened_stays_unknown(ibridge, audio_set, log,
                                                               tmp_path):
    """Target track 2 already has a clip (in slot 0); slot 1 stays empty: no match."""
    patch_handler(audio_set, CREATE_CLIP, lambda real, p: None)
    audio_set.drop_next_marker_after.add(CREATE_CLIP)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S, readback_window_s=WINDOW_S)
    with pytest.raises(ImportAborted, match="timed out; outcome unknown"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=2, slot_index=1, num_slots=4,
                expected_before=expected_state(audio_set, 2))
    assert_stopped_without_undo(imp, audio_set, CREATE_CLIP)


def test_clip_with_another_file_stays_unknown(ibridge, audio_set, log, tmp_path):
    patch_handler(audio_set, CREATE_CLIP, lambda real, p: real((p[0], p[1], "C:\\other.wav")))
    audio_set.drop_next_marker_after.add(CREATE_CLIP)
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S, readback_window_s=WINDOW_S)
    with pytest.raises(ImportAborted, match="timed out; outcome unknown"):
        imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0, num_slots=4,
                expected_before=expected_state(audio_set, 0))
    assert_stopped_without_undo(imp, audio_set, CREATE_CLIP)
    assert log_lines(log)[-1]["file_path"] == "C:\\other.wav"


def test_live_busy_longer_than_the_reads_allow_stays_unknown(ibridge, audio_set, log,
                                                             tmp_path):
    audio_set.stall_after[CREATE_TRACK] = 5 * TEST_TIMEOUT_S  # reads wait 3x the timeout
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportAborted, match="timed out; outcome unknown; read-back failed"):
        run_new_track(imp, wav_file(tmp_path / "k.wav"))
    assert_stopped_without_undo(imp, audio_set, CREATE_TRACK)
    assert log_lines(log)[-1]["readback"] == "read-back failed: BridgeTimeoutError"


@pytest.mark.parametrize("address", [CREATE_TRACK, CREATE_CLIP])
def test_ctrl_c_during_the_read_back_after_a_timeout_is_unknown(ibridge, audio_set, log,
                                                                tmp_path, address):
    audio_set.drop_next_marker_after.add(address)
    real_names = ibridge.get_track_names
    send = {CREATE_TRACK: "create_audio_track", CREATE_CLIP: "create_audio_clip"}[address]
    real_send = getattr(ibridge, send)
    state = {"sent": False}

    def sending(*a, **k):
        state["sent"] = True
        return real_send(*a, **k)

    def names(*a, **k):
        if state["sent"]:
            raise KeyboardInterrupt
        return real_names(*a, **k)

    setattr(ibridge, send, sending)
    ibridge.get_track_names = names
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    with pytest.raises(ImportInterrupted, match="read-back interrupted"):
        run_new_track(imp, wav_file(tmp_path / "k.wav"))
    ibridge.get_track_names = real_names
    assert_stopped_without_undo(imp, audio_set, address, outcome="interrupted")
    assert log_lines(log)[-1]["status"] == "timeout"


@pytest.mark.parametrize("address", [CREATE_TRACK, CREATE_CLIP])
def test_ctrl_c_while_reading_the_late_reply_is_unknown(ibridge, audio_set, log, tmp_path,
                                                        address):
    """Review #177 nit 1: Ctrl+C right after the read-back matched, while the late echoes
    are looked up. Never a raw KeyboardInterrupt with the outcome left 'not unknown'."""
    audio_set.drop_next_marker_after.add(address)
    real = ibridge.late_reply
    calls = {"n": 0}

    def interrupted_once(request_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyboardInterrupt
        return real(request_id)

    ibridge.late_reply = interrupted_once
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    try:
        run_new_track(imp, wav_file(tmp_path / "k.wav"))
    except ImportInterrupted as exc:
        assert "read-back interrupted" in str(exc)
    except KeyboardInterrupt:  # caught so pytest reports a failure, not an abort
        pytest.fail("a raw Ctrl+C escaped the settlement")
    else:
        pytest.fail("no ImportInterrupted")
    assert calls["n"] >= 1
    assert_stopped_without_undo(imp, audio_set, address, outcome="interrupted")


def test_an_undo_that_times_out_is_never_settled(ibridge, audio_set, log, tmp_path):
    audio_set.stall_after[UNDO] = 2 * TEST_TIMEOUT_S
    imp = ClipImporter(ibridge, log, timeout_s=TEST_TIMEOUT_S)
    before = expected_state(audio_set, 0)
    out = imp.run(path=wav_file(tmp_path / "k.wav"), track_index=0, slot_index=0, num_slots=4,
                  expected_before=before)
    with pytest.raises(ImportAborted, match="undo_clip timed out; outcome unknown"):
        imp.undo_step(out, expect_now=out.after, expect_after=before, label="undo_clip")
    assert out.outcome_unknown and out.steps[-1].outcome == "timeout"
    assert writes(audio_set).count(UNDO) == 1
    with pytest.raises(ImportAborted, match="unknown outcome"):
        imp.undo_step(out, expect_now=before, expect_after=before, label="undo_again")
    assert writes(audio_set).count(UNDO) == 1
