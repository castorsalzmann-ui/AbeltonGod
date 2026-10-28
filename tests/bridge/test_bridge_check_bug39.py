"""bridge_check.py fixes for #39 (review of PR #37), against the fake AbletonOSC server.

CI only. Each test names the #39 item it covers. The E9 case (undo deletes a track and the
script still said PASS) lives in ``tests/regressions/test_bug_39_undo_false_pass.py``.
"""

from __future__ import annotations

import io
import re
import threading

import pytest
from fake_abletonosc import FakeAbletonOSC
from test_bridge_check import (
    UNDO,
    bridge_check,
    free_udp_port,
    result_block,
    run,
    set_mute,
    writes,
)

from bridge.osc_client import AbletonBridge, BridgeProtocolError


@pytest.fixture
def fake():
    server = FakeAbletonOSC()
    yield server
    server.close()


def closing(server_cls, *args):
    """Context helper for one-off fake subclasses."""
    server = server_cls(*args)

    class _Ctx:
        def __enter__(self):
            return server

        def __exit__(self, *exc):
            server.close()

    return _Ctx()


# -- item 1: undo that reverts something else -------------------------------------------------


class _UndoRevertsRename(FakeAbletonOSC):
    """Review E5: mute is not undoable; the user's last action was renaming track 1."""

    def __init__(self) -> None:
        super().__init__()
        self.undo_stack = [("rename", 1, "2-Bass-OLD")]

    def _set_mute(self, p):
        self.tracks[int(p[0])]["mute"] = bool(p[1])

    def _undo(self, p):
        if self.undo_stack:
            _, idx, old = self.undo_stack.pop()
            self.tracks[idx]["name"] = old


def test_undo_reverting_a_rename_is_fail_lists_the_change_and_writes_nothing_more():
    with closing(_UndoRevertsRename) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert writes(fake.payload()) == [set_mute(0, 1), set_mute(0, 0), set_mute(0, 1), UNDO]
    block = result_block(out)
    assert block["song.undo"].startswith(
        "FAIL raw=R4=(True,); S1=tempo=136 sig=4/4 tracks=['1-Kick':1, '2-Bass-OLD':0]")
    assert "reverted another action" in block["song.undo"]
    assert block["error"] != "-"
    assert "Spurnamen oder Reihenfolge haben sich geändert." in out
    assert "'2-Bass-OLD'" in out and "Undo-Verlauf" in out
    assert "Ursprünglich war Spur 0 '1-Kick' nicht stumm." in out
    assert "Das Set ist wie vorher" not in out


class _UndoUnmutesAnotherTrack(FakeAbletonOSC):
    """Undo reverts the user's earlier mute of track 1; the test mute is not undoable."""

    def __init__(self) -> None:
        super().__init__()
        self.tracks[1]["mute"] = True
        self.undo_stack = [(1, False)]

    def _set_mute(self, p):
        self.tracks[int(p[0])]["mute"] = bool(p[1])


def test_undo_changing_another_tracks_mute_is_fail():
    with closing(_UndoUnmutesAnotherTrack) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert writes(fake.payload()).count(UNDO) == 1
    assert writes(fake.payload())[-1] == UNDO  # no restore after an unexplained change
    assert "Spur 1 '2-Bass': vorher stumm, jetzt nicht stumm" in out
    assert result_block(out)["song.undo"].startswith("FAIL")


class _UndoAppendsTrack(FakeAbletonOSC):
    """Undo of a deletion at the end brings a track back: count changes, test index does not."""

    def _set_mute(self, p):
        self.tracks[int(p[0])]["mute"] = bool(p[1])

    def _undo(self, p):
        self.tracks.append({"name": "3-Deleted", "mute": False})


def test_undo_changing_the_track_count_is_fail():
    with closing(_UndoAppendsTrack) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert "Die Spuranzahl hat sich geändert: 2 -> 3." in out
    assert result_block(out)["song.undo"].startswith("FAIL")


def test_plan_warns_about_undo_history_before_the_final_confirmation(fake):
    seen: list[str] = []
    out = io.StringIO()
    answers = iter(["y", "0", "n"])

    def input_fn(prompt: str) -> str:
        if prompt.startswith("Diese Änderungen"):
            seen.append(out.getvalue())
        return next(answers)

    receive = free_udp_port()
    fake.response_port = receive
    bridge_check.main(["--send-port", str(fake.port), "--receive-port", str(receive),
                       "--timeout", "0.3"], input_fn=input_fn, out=out)
    (shown,) = seen
    assert "4. Undo in Live (/live/song/undo), zurücklesen - erwartet: nicht stumm" in shown
    assert "WICHTIG - Undo-Risiko" in shown
    assert "letzte eigene Aktion" in shown
    assert "schließen und neu öffnen" in shown
    assert "Tempo, Taktart, alle Spurnamen und den\nMute-Zustand aller Spuren" in shown
    assert "in diesem\nProjekt ist das noch nicht geprüft" in shown
    assert "nichts anderes verändert" not in out.getvalue()
    assert writes(fake.payload()) == []


def test_set_changed_between_plan_and_confirmation_writes_nothing(fake):
    answers = iter(["y", "0"])

    def input_fn(prompt: str) -> str:
        if prompt.startswith("Diese Änderungen"):
            fake.tracks.append({"name": "late", "mute": False})
            return "y"
        return next(answers)

    receive = free_udp_port()
    fake.response_port = receive
    out = io.StringIO()
    code = bridge_check.main(["--send-port", str(fake.port), "--receive-port", str(receive),
                              "--timeout", "0.3"], input_fn=input_fn, out=out)
    assert code == 1
    assert writes(fake.payload()) == []
    assert "zwischen Plan und Bestätigung" in out.getvalue()


# -- item 2: Ctrl+C at every step of the write sequence ---------------------------------------


class _NoopUndoFake(FakeAbletonOSC):
    def _undo(self, p):
        return None


# Bridge calls after the final confirmation, no-op-undo path (adds W4/R5):
# S0 = tempo + signature + names + 2 mutes (5), W1 R1 W2 R2 W3 R3 (6), U (1), R4 (1),
# S1 (5), W4 R5 (2) = 20.
STEPS_NOOP_UNDO = 20
STEPS_GOOD_UNDO = 18
# Kind of each call on the working-undo path (r = read, w = write or undo).
CALL_KINDS_GOOD = ["r"] * 5 + ["w", "r"] * 3 + ["w", "r"] + ["r"] * 5


def _run_with_interrupt(fake, at: int, when: str, monkeypatch):
    armed = {"on": False, "n": 0, "fired": False}

    def wrap(name):
        orig = getattr(AbletonBridge, name)

        def wrapper(self, *a, **kw):
            if armed["on"] and not armed["fired"]:
                n = armed["n"]
                armed["n"] += 1
                if n == at:
                    armed["fired"] = True
                    if when == "before":
                        raise KeyboardInterrupt
                    orig(self, *a, **kw)
                    raise KeyboardInterrupt
            return orig(self, *a, **kw)

        monkeypatch.setattr(AbletonBridge, name, wrapper)

    for name in ("get_tempo", "get_signature", "get_track_names", "get_track_mute",
                 "set_track_mute", "undo"):
        wrap(name)

    answers = iter(["y", "0", "y"])

    def input_fn(prompt: str) -> str:
        answer = next(answers)
        if prompt.startswith("Diese Änderungen"):
            armed["on"] = True
        return answer

    receive = free_udp_port()
    fake.response_port = receive
    out = io.StringIO()
    code = bridge_check.main(["--send-port", str(fake.port), "--receive-port", str(receive),
                              "--timeout", "0.3"], input_fn=input_fn, out=out)
    return code, out.getvalue(), armed["fired"]


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("at", range(STEPS_NOOP_UNDO))
def test_ctrl_c_at_every_step_prints_block_and_original_state(monkeypatch, at, when):
    with closing(_NoopUndoFake) as fake:
        code, out, fired = _run_with_interrupt(fake, at, when, monkeypatch)
        wire = writes(fake.payload())
    assert fired
    assert code == 130
    assert "ABGEBROCHEN mit Strg+C." in out
    assert "Ursprünglicher Zustand: Spur 0 '1-Kick' war nicht stumm." in out
    block = result_block(out)
    assert block["error"].startswith("write sequence aborted: interrupted by user (Ctrl+C)")
    assert wire.count(UNDO) <= 1
    if wire:
        # After a write was sent the script reads the test track back once and says what to do.
        assert ("wie ursprünglich" in out) or ("von Hand auf nicht stumm stellen" in out)
        assert "after-abort read mute=" in out


@pytest.mark.parametrize("at", range(STEPS_GOOD_UNDO))
def test_ctrl_c_with_working_undo_never_writes_after_the_interrupt(monkeypatch, at):
    with closing(FakeAbletonOSC) as fake:
        code, out, fired = _run_with_interrupt(fake, at, "before", monkeypatch)
    assert fired and code == 130
    # Steps 0-4 are S0 reads: no write at all. Afterwards the wire holds exactly the writes
    # that came before the interrupted call.
    assert len(CALL_KINDS_GOOD) == STEPS_GOOD_UNDO
    expected_writes = [set_mute(0, 1), set_mute(0, 0), set_mute(0, 1), UNDO]
    sent_before = CALL_KINDS_GOOD[:at].count("w")
    assert writes(fake.payload()) == expected_writes[:sent_before]


def test_ctrl_c_during_reads_writes_nothing_and_prints_block(fake, monkeypatch):
    def boom(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(AbletonBridge, "get_tempo", boom)
    code, out, prompts = run(fake, [])
    assert code == 130 and prompts == []
    assert "ABGEBROCHEN mit Strg+C. Es wurde nichts in Live geändert." in out
    assert result_block(out)["error"] == "interrupted by user (Ctrl+C) before any write"
    assert writes(fake.payload()) == []


# -- item 3: BridgeProtocolError from a write -------------------------------------------------


def test_protocol_error_from_a_write_takes_the_abort_path(fake, monkeypatch):
    """Review E10: W2 applied, then the client raises a protocol error."""
    orig = AbletonBridge.set_track_mute
    calls = {"n": 0}

    def patched(self, i, v):
        calls["n"] += 1
        orig(self, i, v)
        if calls["n"] == 2:
            raise BridgeProtocolError("end marker arrived before start marker")

    monkeypatch.setattr(AbletonBridge, "set_track_mute", patched)
    code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert writes(fake.payload()) == [set_mute(0, 1), set_mute(0, 0)]
    block = result_block(out)
    assert block["track.mute.set"].startswith("FAIL")
    assert "BridgeProtocolError" in block["error"]
    assert "after-abort read mute=0 expected=0" in out
    assert "Spur 0 ist jetzt nicht stumm - wie ursprünglich." in out


# -- item 4: failed restore -------------------------------------------------------------------


class _NoUndoIgnoreW4(FakeAbletonOSC):
    """Review E3: undo does nothing and the restore write W4 does not land."""

    n = 0

    def _undo(self, p):
        return None

    def _set_mute(self, p):
        self.n += 1
        if self.n == 4:
            return None
        super()._set_mute(p)


def test_failed_restore_is_an_error_with_a_hand_fix_instruction():
    with closing(_NoUndoIgnoreW4) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
        final = fake.tracks[0]["mute"]
    assert code == 1 and final is True
    block = result_block(out)
    assert "R5 read-back mismatch" in block["error"]
    assert block["track.mute.set"].startswith("FAIL")
    assert block["song.undo"].startswith("FAIL")
    assert "Bitte in Live den Mute-Knopf von Spur 0 von Hand auf nicht stumm stellen." in out


def test_noop_undo_restore_is_read_back_as_r5():
    with closing(_NoopUndoFake) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert re.search(r"^  R5 read mute=0 expected=0 ok raw=\(False,\)$", out, re.M), out
    assert result_block(out)["error"] == "-"
    assert writes(fake.payload())[-2:] == [UNDO, set_mute(0, 0)]


# -- item 5: the review's surviving mutants ---------------------------------------------------


class _IgnoreOnlyW3(FakeAbletonOSC):
    n = 0

    def _set_mute(self, p):
        self.n += 1
        if self.n == 3:
            return None
        super()._set_mute(p)


def test_mismatch_at_r3_stops_before_undo():
    with closing(_IgnoreOnlyW3) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert writes(fake.payload()) == [set_mute(0, 1), set_mute(0, 0), set_mute(0, 1)]
    assert "R3 read-back mismatch" in result_block(out)["error"]
    assert result_block(out)["song.undo"].startswith("SKIPPED")


class _MalformedMuteRead(FakeAbletonOSC):
    def _get_mute(self, p):
        return (int(p[0]), "yes")


def test_r0_read_failure_sends_nothing():
    with closing(_MalformedMuteRead) as fake:
        code, out, prompts = run(fake, ["y", "0", "y"])
    assert code == 1
    assert writes(fake.payload()) == []
    assert len(prompts) == 2  # never reached the final confirmation
    block = result_block(out)
    assert block["track.mute.set"].startswith("FAIL raw=('yes',)")
    assert "Keine Änderung gesendet." in out


class _MuteReadTimesOutAfterW1(FakeAbletonOSC):
    def _set_mute(self, p):
        super()._set_mute(p)
        self.drop.add("/live/track/get/mute")


def test_after_abort_read_back_reports_the_current_state():
    """R1 fails (no reply); the after-abort read also fails and says so."""
    with closing(_MuteReadTimesOutAfterW1) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert writes(fake.payload()) == [set_mute(0, 1)]
    assert "R1 read failed" in out
    assert "after-abort read failed" in out
    assert "konnte nicht gelesen werden" in out


# -- item 7: track index parsing --------------------------------------------------------------


@pytest.mark.parametrize("answer", ["²", "١", "1.0", "+1", "-0"])
def test_non_ascii_or_signed_index_is_rejected(fake, answer):
    code, out, prompts = run(fake, ["y", answer, answer, answer])
    assert code == 0
    assert writes(fake.payload()) == []
    assert "Keine gültige Spur gewählt." in out
    assert "Konfiguration" not in out


@pytest.mark.parametrize("answer, idx", [(" 1 ", 1), ("01", 1), ("0", 0)])
def test_ascii_index_variants_select_the_track(fake, answer, idx):
    code, out, _ = run(fake, ["y", answer, "n"])
    assert code == 0
    assert f"Geplante Änderungen an Spur {idx} " in out


# -- item 8: last_reply -----------------------------------------------------------------------


def test_last_reply_of_a_failed_signature_holds_both_replies(fake, tmp_path):
    from conftest import registry_with

    from bridge.capabilities import CapabilityGate
    from bridge.osc_client import ADDRESSES, OscTransport

    fake.signature = (7, 0)
    with OscTransport(send_port=fake.port, receive_port=0, timeout_s=0.3) as t:
        fake.response_port = t.receive_port
        b = AbletonBridge(t, CapabilityGate(registry_with(tmp_path, set(ADDRESSES))))
        with pytest.raises(BridgeProtocolError):
            b.get_signature()
        assert b.last_reply == (7, 0)


def test_last_reply_is_per_thread(fake, tmp_path):
    from conftest import registry_with

    from bridge.capabilities import CapabilityGate
    from bridge.osc_client import ADDRESSES, OscTransport

    with OscTransport(send_port=fake.port, receive_port=0, timeout_s=0.3) as t:
        fake.response_port = t.receive_port
        b = AbletonBridge(t, CapabilityGate(registry_with(tmp_path, set(ADDRESSES))))
        b.get_version()
        seen = []
        th = threading.Thread(target=lambda: (seen.append(b.last_reply), b.get_tempo(),
                                              seen.append(b.last_reply)))
        th.start()
        th.join(5)
        assert seen == [None, (136.0,)]
        assert b.last_reply == (12, 3)  # the other thread's read did not overwrite it
