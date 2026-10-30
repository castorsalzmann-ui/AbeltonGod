"""Timed-out writes settled by read-back (#140 user run 1). CI only, against the fake server.

The fake models two mechanisms that both give the user's 0.1.0 result (``stall_after``: Live
busy after the call; ``drop_next_marker_after``: the end-marker echo lost). Which one happened
in Live is not established; these tests show what the script does in each, and that every
other timed-out case stays an unknown outcome without undo.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest
from conftest import TEST_TIMEOUT_S
from fake_abletonosc import MARKER, build
from test_arrangement_check import (
    ADD_NOTES,
    CREATE_CLIP,
    CREATE_TRACK,
    CUE_NAME,
    SONG_TIME_SET,
    TOGGLE_CUE,
    UNDO,
    block,
    block_list,
    log_entries,
    run,
    script,
    snapshot,
    writes,
)

import bridge.arrangement_check as arr
from bridge.clip_import import ActionLog
from bridge.osc_client import LATE_TRACKED, AbletonOSCError, BridgeTimeoutError, LateReply

RUN_TIMEOUT_S = 0.3  # the --timeout run() passes to the script
LABELS = {SONG_TIME_SET: "set_song_time", CREATE_TRACK: "create_midi_track",
          CREATE_CLIP: "create_midi_clip", ADD_NOTES: "add_notes", TOGGLE_CUE: "add_cue",
          CUE_NAME: "set_cue_name"}
CAPS = {label: cap for cap, label in script.CAPABILITY_STEPS}


def fault(fake, address, mechanism, stall=2 * RUN_TIMEOUT_S):
    if mechanism == "busy":
        fake.stall_after[address] = stall
    else:
        fake.drop_next_marker_after.add(address)


def step_line(out, label):
    return next(s for s in block_list(out, "steps") if s.startswith(f"{label}: "))


# -- the transport records late echoes -------------------------------------------------------

def test_late_end_echo_is_recorded_with_its_delay(bridge, fake, transport):
    fake.stall_after["/live/track/set/mute"] = 3 * TEST_TIMEOUT_S
    with pytest.raises(BridgeTimeoutError) as info:
        bridge.set_track_mute(0, True)
    rid = info.value.request_id
    assert rid is not None
    # The start echo came before the stall; the end echo not yet.
    assert bridge.late_reply(rid) == LateReply(True, False, (), None)
    transport.timeout_s = 1.0
    assert bridge.get_track_mute(0) is True  # a later request (waits for the fake)
    late = bridge.late_reply(rid)
    assert late.start_seen and late.end_seen and late.errors == ()
    assert 3 * TEST_TIMEOUT_S - 0.05 <= late.end_after_s < 3 * TEST_TIMEOUT_S + 0.5


def test_late_error_of_a_timed_out_write_is_recorded(bridge, fake, transport):
    fake.hold()
    with pytest.raises(BridgeTimeoutError) as info:
        bridge.set_track_mute(9, True)  # IndexError in the fake -> /live/error
    fake.release_after(0.1)
    transport.timeout_s = 1.0
    assert bridge.get_tempo() == 136.0  # the error is not raised on the next request
    late = bridge.late_reply(info.value.request_id)
    assert late.end_seen and len(late.errors) == 1 and "index out of range" in late.errors[0]


def test_lost_end_echo_closes_at_the_next_start_and_takes_no_later_error(bridge, fake,
                                                                        transport):
    fake.drop_next_marker_after.add("/live/track/set/mute")
    with pytest.raises(BridgeTimeoutError) as info:
        bridge.set_track_mute(0, True)
    with pytest.raises(AbletonOSCError):
        bridge.set_track_mute(9, True)  # its error must not be booked on the first request
    late = bridge.late_reply(info.value.request_id)
    assert late.start_seen and not late.end_seen and late.errors == ()
    assert late.end_after_s is None


def test_late_echo_waiting_in_the_socket_is_read_while_draining(bridge, fake, transport):
    fake.stall_after["/live/track/set/mute"] = 2 * TEST_TIMEOUT_S
    with pytest.raises(BridgeTimeoutError) as info:
        bridge.set_track_mute(0, True)
    fake.wait_received(3)  # start, mute, end processed: the end echo is in our socket
    time.sleep(0.05)
    assert bridge.get_tempo() == 136.0
    assert bridge.late_reply(info.value.request_id).end_seen


def test_a_later_start_echo_closes_an_earlier_window(bridge, fake, transport):
    """Request 1 loses its end echo; request 2 times out and its error comes late: the error
    is booked on request 2 only (request 2's start echo ends request 1's window)."""
    fake.drop_next_marker_after.add("/live/track/set/mute")
    with pytest.raises(BridgeTimeoutError) as first:
        bridge.set_track_mute(0, True)
    fake.drop_next_marker_after.clear()
    fake.hold()
    with pytest.raises(BridgeTimeoutError) as second:
        bridge.set_track_mute(9, True)
    fake.release_after(0.1)
    transport.timeout_s = 1.0
    assert bridge.get_tempo() == 136.0
    assert bridge.late_reply(first.value.request_id).errors == ()
    late = bridge.late_reply(second.value.request_id)
    assert late.end_seen and len(late.errors) == 1


def test_own_start_echo_closes_every_earlier_window(bridge, fake, transport):
    """A stray error arriving after a completed request is not booked on an older one."""
    fake.drop_next_marker_after.add("/live/track/set/mute")
    with pytest.raises(BridgeTimeoutError) as info:
        bridge.set_track_mute(0, True)
    fake.drop_next_marker_after.clear()
    assert bridge.get_tempo() == 136.0  # its own start echo closes request 1
    stray = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stray.sendto(build("/live/error", ("stray",)), ("127.0.0.1", transport.receive_port))
    stray.close()
    time.sleep(0.05)
    assert bridge.get_tempo() == 136.0  # drains the stray error
    assert bridge.late_reply(info.value.request_id).errors == ()


def test_error_before_the_start_echo_is_not_booked(bridge, fake, transport):
    """Only what comes between a request's own two echoes belongs to it."""
    fake.hold()
    with pytest.raises(BridgeTimeoutError) as info:
        bridge.set_track_mute(0, True)
    stray = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stray.sendto(build("/live/error", ("stray",)), ("127.0.0.1", transport.receive_port))
    stray.close()
    time.sleep(0.05)
    fake.release_after(0.1)
    transport.timeout_s = 1.0
    assert bridge.get_tempo() == 136.0
    late = bridge.late_reply(info.value.request_id)
    assert late.end_seen and late.errors == ()


def test_writer_marks_an_unsettled_timeout_unknown_and_refuses_undo(bridge, fake, tmp_path):
    fake._create_midi_track = lambda p: None  # the write never happens
    fake.drop_next_marker_after.add(CREATE_TRACK)
    writer = arr.ArrangementWriter(bridge, ActionLog(tmp_path / "a.jsonl"),
                                   timeout_s=TEST_TIMEOUT_S, readback_window_s=0.2)
    before = arr.read_arrangement_state(bridge, len(fake.tracks))
    with pytest.raises(arr.ImportAborted, match="timed out; outcome unknown"):
        writer.run(arr.make_plan(5, 1, "X"), before)
    assert writer.last_outcome.outcome_unknown is True
    writer.last_outcome.done = True  # even then
    with pytest.raises(arr.ImportAborted, match="unknown outcome"):
        writer.undo_all(writer.last_outcome)


def test_unknown_or_pushed_out_request_ids_give_none(bridge, fake, transport):
    assert bridge.late_reply(None) is None and bridge.late_reply("abg-nope") is None
    fake.drop.add(MARKER)
    ids = []
    for _ in range(LATE_TRACKED + 1):
        with pytest.raises(BridgeTimeoutError) as info:
            bridge.ping()
        ids.append(info.value.request_id)
    assert bridge.late_reply(ids[0]) is None
    assert all(bridge.late_reply(i) is not None for i in ids[1:])


# -- the writer settles a late write by read-back -------------------------------------------

@pytest.mark.parametrize("mechanism", ["busy", "lost"])
@pytest.mark.parametrize("address", list(LABELS))
def test_each_timed_out_write_that_reads_back_as_intended_is_settled(fake, tmp_path, address,
                                                                     mechanism):
    before = snapshot(fake)
    fault(fake, address, mechanism)
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_OK, out
    label = LABELS[address]
    b = block(out)
    assert b[CAPS[label]] == "PASS (late: read-back after timeout)"
    line = step_line(out, label)
    assert line.startswith(f"{label}: confirmed (late: no confirmation within 0.3 s; "
                           "read-back matched (1 read(s)); "), line
    assert ("end echo after 0." in line) if mechanism == "busy" else line.endswith(
        "end echo not seen)"), line
    assert b["song.undo"] == "PASS (5 undo(s) for 5 write(s); read back)"
    assert snapshot(fake) == before
    entry = [e for e in log_entries(tmp_path) if e["action"] == label][-1]
    assert entry["status"] == "read_back" and entry["ok"] is True
    assert entry["late_reply"]["end_seen"] is (mechanism == "busy")


def test_late_error_after_the_timeout_stops_without_undo(fake, tmp_path):
    """The write timed out and AbletonOSC then reported an error for it: never a success,
    even though the read-back shows the change (the fake applies it, then raises)."""
    real = fake._create_midi_track

    def create_then_raise(p):
        real(p)
        fake._held, _ = [], fake.released.clear()  # hold() without the lock we are under
        fake.release_after(2 * RUN_TIMEOUT_S)
        raise RuntimeError("late failure")

    fake._create_midi_track = create_then_raise
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert (UNDO, ()) not in writes(fake) and len(prompts) == 2
    b = block(out)
    assert b["song.create_midi_track"] == "FAIL (AbletonOSC error after the timeout)"
    assert "late failure" in step_line(out, "create_midi_track")
    assert "UNBEKANNT" in out
    assert log_entries(tmp_path)[-1]["status"] == "timeout"


def test_late_error_with_a_lost_end_echo_stops_without_undo(fake, tmp_path):
    """Review #167 finding 1 (mutant R1): Live is slow past the timeout, then reports an
    error for the write, and the end echo is lost. The read-back shows the change (the fake
    applies it before raising); the error alone must keep the outcome unknown."""
    real = fake._create_midi_track

    def create_then_raise(p):
        real(p)
        fake._held, _ = [], fake.released.clear()  # hold() without the lock we are under
        fake.release_after(2 * RUN_TIMEOUT_S)
        raise RuntimeError("late failure")

    fake._create_midi_track = create_then_raise
    fake.drop_next_marker_after.add(CREATE_TRACK)
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert (UNDO, ()) not in writes(fake) and len(prompts) == 2
    assert block(out)["song.create_midi_track"] == "FAIL (AbletonOSC error after the timeout)"
    entry = log_entries(tmp_path)[-1]
    assert entry["status"] == "timeout"
    assert entry["late_reply"]["end_seen"] is False and entry["late_reply"]["errors"]


def test_change_visible_only_at_a_later_poll_is_settled(fake, tmp_path):
    """Review #167 R5: the settlement polls within the window, not just once."""
    real = fake._create_midi_track

    def create_later(p):
        def apply():
            with fake._lock:
                real(p)
        timer = threading.Timer(2 * RUN_TIMEOUT_S, apply)
        timer.daemon = True
        timer.start()

    fake._create_midi_track = create_later
    fake.drop_next_marker_after.add(CREATE_TRACK)
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_OK, out
    line = step_line(out, "create_midi_track")
    assert line.startswith("create_midi_track: confirmed (late:") and "(1 read(s))" not in line


def test_reads_after_a_timeout_wait_three_times_the_timeout(fake, tmp_path):
    """Review #167 R6: Live busy 3x the timeout after the call; the first read waits about
    2x the timeout, which the 3x read timeout covers and a 1.5x one would not."""
    fault(fake, CREATE_TRACK, "busy", stall=3 * RUN_TIMEOUT_S)
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_OK, out
    assert block(out)["song.create_midi_track"] == "PASS (late: read-back after timeout)"


def test_timed_out_write_that_never_happened_stays_unknown(fake, tmp_path):
    """The datagram was lost (the fake does nothing); the read-back never matches."""
    fake._create_midi_track = lambda p: None
    fake.drop_next_marker_after.add(CREATE_TRACK)
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert (UNDO, ()) not in writes(fake) and len(prompts) == 2
    assert step_line(out, "create_midi_track") == "create_midi_track: timeout (outcome unknown)"
    assert block(out)["song.create_midi_track"] == "SKIPPED"
    entry = log_entries(tmp_path)[-1]
    assert entry["status"] == "timeout" and "does not show the change" in entry["note"]
    assert writes(fake)[-1] == (CREATE_TRACK, (-1,))  # nothing sent after it


def test_live_busy_longer_than_the_read_back_allows_stays_unknown(fake, tmp_path):
    fault(fake, CREATE_TRACK, "busy", stall=5 * RUN_TIMEOUT_S)  # reads wait 3x the timeout
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert (UNDO, ()) not in writes(fake) and len(prompts) == 2
    entry = log_entries(tmp_path)[-1]
    assert entry["status"] == "timeout" and entry["readback"].startswith("read-back failed")


def test_ctrl_c_during_the_read_back_after_a_timeout_is_unknown(fake, tmp_path, monkeypatch):
    fake.drop_next_marker_after.add(CREATE_TRACK)
    real_read = script.AbletonBridge.get_cue_points
    state = {"sent": False}
    real_create = script.AbletonBridge.create_midi_track

    def create(self, *a, **k):
        state["sent"] = True
        return real_create(self, *a, **k)

    def read(self, *a, **k):
        if state["sent"]:
            raise KeyboardInterrupt
        return real_read(self, *a, **k)

    monkeypatch.setattr(script.AbletonBridge, "create_midi_track", create)
    monkeypatch.setattr(script.AbletonBridge, "get_cue_points", read)
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_INTERRUPTED, out
    assert (UNDO, ()) not in writes(fake) and len(prompts) == 2
    assert step_line(out, "create_midi_track") == \
        "create_midi_track: interrupted (outcome unknown)"


def test_an_undo_that_times_out_is_never_settled(fake, tmp_path):
    """Undo timeouts keep the old rule: the chain stops, no further undo."""
    fake.stall_after[UNDO] = 2 * RUN_TIMEOUT_S
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert writes(fake).count((UNDO, ())) == 1
    assert block(out)["song.undo"].startswith("FAIL (ImportAborted: undo_1 timed out")
    assert step_line(out, "undo_1") == "undo_1: timeout (outcome unknown)"
