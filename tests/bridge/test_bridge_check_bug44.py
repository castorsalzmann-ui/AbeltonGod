"""bridge_check.py gaps from the re-review of PR #41 (#44), against the fake AbletonOSC server.

CI only: the fakes model possible Live behaviour; none of it is observed in Live.
"""

from __future__ import annotations

import io

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
from test_bridge_check_bug39 import closing

from bridge.osc_client import AbletonBridge, AbletonOSCError, BridgeTimeoutError

# -- item 1: undo that times out or errors ----------------------------------------------------


class _HoldAtUndo(FakeAbletonOSC):
    """Review E2: undo is processed, then every reply is held (dialog-like)."""

    def _undo(self, p):
        super()._undo(p)
        self._held = []  # under the server lock; hold() would deadlock


def test_undo_timeout_is_fail_says_it_may_have_been_sent_and_sends_nothing_more():
    with closing(_HoldAtUndo) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
        wire = writes(fake.payload())
    assert code == 1
    assert wire == [set_mute(0, 1), set_mute(0, 0), set_mute(0, 1), UNDO]  # no W4, one undo
    block = result_block(out)
    assert block["song.undo"].startswith("FAIL")
    assert "undo: BridgeTimeoutError" in block["song.undo"]
    assert block["track.mute.set"].startswith("PASS")
    assert "Das Undo wurde (eventuell) schon gesendet." in out
    assert "Undo-Verlauf" in out
    assert "not sent" not in block["song.undo"]


@pytest.mark.parametrize("exc", [AbletonOSCError("boom"), BridgeTimeoutError("late")])
def test_undo_error_is_fail_with_hint(fake, monkeypatch, exc):
    orig = AbletonBridge.undo

    def failing(self):
        orig(self)  # the undo reaches Live, then the client sees an error
        raise exc

    monkeypatch.setattr(AbletonBridge, "undo", failing)
    code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert writes(fake.payload()).count(UNDO) == 1
    block = result_block(out)
    assert block["song.undo"].startswith("FAIL")
    assert f"undo: {type(exc).__name__}" in block["error"]
    assert "Das Undo wurde (eventuell) schon gesendet." in out


# -- item 2: tempo / signature in the undo comparison -----------------------------------------


class _UndoAlsoRevertsTempo(FakeAbletonOSC):
    """Re-review case: Live groups the user's tempo change (120 -> 136) with W3."""

    def _undo(self, p):
        super()._undo(p)
        self.tempo = 120.0


def test_undo_that_also_reverts_tempo_is_fail():
    with closing(_UndoAlsoRevertsTempo) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
        wire = writes(fake.payload())
    assert code == 1
    block = result_block(out)
    assert block["song.undo"].startswith("FAIL")
    assert "tempo=120" in block["song.undo"]
    assert "Tempo: vorher 136 BPM, jetzt 120 BPM" in out
    assert wire[-1] == UNDO  # nothing written after an unexplained change
    assert "Spuranzahl, Spurnamen und Mute-Zustand aller Spuren sind wie vorher" not in out


class _UndoAlsoRevertsSignature(FakeAbletonOSC):
    def _undo(self, p):
        super()._undo(p)
        self.signature = (3, 4)


def test_undo_that_also_reverts_signature_is_fail():
    with closing(_UndoAlsoRevertsSignature) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert "Taktart: vorher 4/4, jetzt 3/4" in out
    assert result_block(out)["song.undo"].startswith("FAIL")


class _UndoRevertsOnlyTempo(FakeAbletonOSC):
    """Mute not undoable; undo reverts a tempo change only -> not the 'only test mute' path."""

    def _set_mute(self, p):
        self.tracks[int(p[0])]["mute"] = bool(p[1])

    def _undo(self, p):
        self.tempo = 120.0


def test_tempo_change_plus_unreverted_mute_does_not_restore():
    with closing(_UndoRevertsOnlyTempo) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
        wire = writes(fake.payload())
    assert code == 1
    assert wire[-1] == UNDO  # no W4: the change is not only the test mute
    assert "Tempo: vorher 136 BPM, jetzt 120 BPM" in out
    assert "Spur 0 '1-Kick': vorher nicht stumm, jetzt stumm" in out


class _UndoRevertsTempoAndRename(FakeAbletonOSC):
    """Undo changes both the tempo and a track name: both must be listed."""

    def _undo(self, p):
        super()._undo(p)
        self.tempo = 120.0
        self.tracks[1]["name"] = "2-Bass-OLD"


def test_tempo_and_track_changes_are_both_listed():
    with closing(_UndoRevertsTempoAndRename) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert "Tempo: vorher 136 BPM, jetzt 120 BPM" in out
    assert "Spurnamen oder Reihenfolge haben sich geändert." in out


def test_pass_states_its_scope_in_output_and_block(fake):
    code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 0
    assert ("Undo hat die letzte Mute-Änderung zurückgenommen. Tempo, Taktart, Spuranzahl, "
            "Spurnamen und Mute-Zustand aller Spuren sind wie vorher.") in out
    assert ("(Nicht prüfen kann das Script: Clips, Geräte, Automation sowie Return- und "
            "Master-Spuren.)") in out
    undo = result_block(out)["song.undo"]
    assert undo.startswith("PASS ")
    assert undo.endswith(
        " note=checked: tempo, signature, track count/names/order, all track mutes; "
        "not checked: clips, devices, automation, return/master tracks")


# -- item 5: EOF / Ctrl+C at the track prompt -------------------------------------------------


@pytest.mark.parametrize("answers", [
    ["y"],  # EOF right at the track prompt
    ["y", "²"],  # one invalid answer, then EOF
    ["y", "x", "9"],  # two invalid answers, then EOF
])
def test_eof_at_track_prompt_aborts_without_plan(fake, answers):
    code, out, prompts = run(fake, answers)
    assert code == 0
    assert "Abgebrochen." in out
    assert "Geplante Änderungen" not in out
    assert not any(p.startswith("Diese Änderungen") for p in prompts)
    assert writes(fake.payload()) == []


def test_ctrl_c_at_track_prompt_aborts_without_plan(fake):
    calls = []

    def input_fn(prompt):
        calls.append(prompt)
        if prompt.startswith("Welche Spur"):
            raise KeyboardInterrupt
        return "y"

    receive = free_udp_port()
    fake.response_port = receive
    out = io.StringIO()
    code = bridge_check.main(["--send-port", str(fake.port), "--receive-port", str(receive),
                              "--timeout", "0.3"], input_fn=input_fn, out=out)
    assert code == 0
    assert len(calls) == 2
    assert "Geplante Änderungen" not in out.getvalue()
    assert writes(fake.payload()) == []


def test_enter_at_track_prompt_still_selects_track_0(fake):
    code, out, _ = run(fake, ["y", "", "n"])
    assert code == 0
    assert "Geplante Änderungen an Spur 0 '1-Kick'" in out
