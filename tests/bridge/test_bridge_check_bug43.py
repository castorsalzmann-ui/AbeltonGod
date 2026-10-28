"""bridge_check.py items of #43 (review of PR #45), against the fake AbletonOSC server.

CI only: the fakes model possible Live behaviour (tempo drift, Ctrl+C); none of it is observed
in Live.
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
    writes,
)
from test_bridge_check_bug39 import closing

# -- item 3: a FAIL where only tempo / signature changed is worded neutrally -------------------

NEUTRAL_HEAD = ("FAIL: Nach dem Undo unterscheiden sich nur Tempo und/oder Taktart vom Stand "
                "vor dem Test.")
DRIFT_CAUSE = "Tempo-Automation, Ableton Link oder eine externe MIDI-Clock (Sync)"
REVERT_CAUSE = "Undo hat eine frühere Tempo- oder Taktart-Änderung zurückgenommen."
BLAME_UNDO_TEXT = "offenbar nicht (nur) die Mute-Änderung des Scripts zurückgenommen"


class _TempoDrift(FakeAbletonOSC):
    """Undo works; meanwhile the tempo drifts by a tiny amount (e.g. Link).

    136 + 1/128 is exact in float32 (OSC 'f'), so it survives the wire unchanged, and ``:g``
    would print it as '136.008' - not the real value.
    """

    def _undo(self, p):
        super()._undo(p)
        self.tempo = 136.0078125


class _SignatureOnly(FakeAbletonOSC):
    def _undo(self, p):
        super()._undo(p)
        self.signature = (7, 8)


@pytest.mark.parametrize("fake_cls, diff_line", [
    (_TempoDrift, "Tempo: vorher 136 BPM, jetzt 136.0078125 BPM"),
    (_SignatureOnly, "Taktart: vorher 4/4, jetzt 7/8"),
])
def test_tempo_or_signature_only_change_is_neutral_fail(fake_cls, diff_line):
    with closing(fake_cls) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
        wire = writes(fake.payload())
    assert code == 1
    block = result_block(out)
    assert block["song.undo"].startswith("FAIL")
    assert block["song.undo"].endswith(
        " note=only tempo/signature differ after undo: possible drift (automation, Link, "
        "external clock) or an undone tempo/signature edit")
    assert block["error"] == "only tempo/signature changed across undo; nothing more written"
    assert NEUTRAL_HEAD in out
    assert f"  - {diff_line}" in out
    assert DRIFT_CAUSE in out and REVERT_CAUSE in out
    assert BLAME_UNDO_TEXT not in out  # not blamed on undo
    assert "Undo hat die letzte Mute-Änderung zurückgenommen" not in out  # not a PASS
    assert wire[-1] == UNDO  # nothing written after the undo


def test_exact_tempo_compare_has_no_tolerance():
    """1/128 BPM is still a difference: the compare is exact."""
    with closing(_TempoDrift) as fake:
        _, out, _ = run(fake, ["y", "0", "y"])
    assert "tempo=136.0078125" in result_block(out)["song.undo"]
    assert result_block(out)["song.undo"].startswith("FAIL")


def test_tempo_plus_track_change_keeps_the_undo_blaming_message():
    """Not tempo-only: a rename alongside the tempo goes to the 'reverted another action' path."""

    class _TempoAndRename(FakeAbletonOSC):
        def _undo(self, p):
            super()._undo(p)
            self.tempo = 120.0
            self.tracks[1]["name"] = "2-Bass-OLD"

    with closing(_TempoAndRename) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert NEUTRAL_HEAD not in out
    assert BLAME_UNDO_TEXT in out
    assert "reverted another action" in result_block(out)["song.undo"]


def test_tempo_plus_unreverted_test_mute_is_not_neutral():
    """Mute not undone and tempo changed: mutes differ, so not the tempo-only path."""

    class _MuteNotUndoableTempoDrift(FakeAbletonOSC):
        def _set_mute(self, p):
            self.tracks[int(p[0])]["mute"] = bool(p[1])

        def _undo(self, p):
            self.tempo = 140.0

    with closing(_MuteNotUndoableTempoDrift) as fake:
        code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 1
    assert NEUTRAL_HEAD not in out
    assert "Spur 0 '1-Kick': vorher nicht stumm, jetzt stumm" in out


# -- item 4: Ctrl+C at any prompt exits 130 with the result block -----------------------------


def _run_ctrl_c_at(fake, prompt_start: str):
    calls: list[str] = []

    def input_fn(prompt: str) -> str:
        calls.append(prompt)
        if prompt.startswith(prompt_start):
            raise KeyboardInterrupt
        return "0" if prompt.startswith("Welche Spur") else "y"

    receive = free_udp_port()
    fake.response_port = receive
    out = io.StringIO()
    code = bridge_check.main(["--send-port", str(fake.port), "--receive-port", str(receive),
                              "--timeout", "0.3"], input_fn=input_fn, out=out)
    return code, out.getvalue(), calls


@pytest.mark.parametrize("prompt_start, n_prompts", [
    ("Ist das", 1),
    ("Welche Spur", 2),
    ("Diese Änderungen", 3),
])
def test_ctrl_c_at_any_prompt_exits_130_and_writes_nothing(fake, prompt_start, n_prompts):
    code, out, calls = _run_ctrl_c_at(fake, prompt_start)
    assert code == 130
    assert len(calls) == n_prompts
    assert "ABGEBROCHEN mit Strg+C. Es wurde nichts in Live geändert." in out
    block = result_block(out)
    assert block["error"] == "interrupted by user (Ctrl+C) before any write"
    assert "no valid track index" not in out
    assert writes(fake.payload()) == []


def test_eof_at_track_prompt_note_says_abort_not_invalid_input(fake):
    code, out, _ = run(fake, ["y"])  # EOF at the track prompt
    assert code == 0
    assert "Abgebrochen. Teil 2 übersprungen, es wurde nichts geändert." in out
    assert "Keine gültige Spur gewählt." not in out
    block = result_block(out)
    assert block["song.undo"] == "SKIPPED raw=- note=user aborted at the track prompt (EOF)"
    assert "no valid track index" not in out


def test_three_invalid_answers_note_says_invalid(fake):
    code, out, _ = run(fake, ["y", "x", "x", "x"])
    assert code == 0
    assert "Keine gültige Spur gewählt. Teil 2 übersprungen." in out
    assert result_block(out)["track.mute.set"] == (
        "SKIPPED raw=- note=no valid track index after 3 attempts")


# -- item 5: plan text line breaks ------------------------------------------------------------


def test_plan_text_has_no_short_orphan_lines():
    text = bridge_check.plan_text(0, "1-Kick", False)
    body = [line for line in text.splitlines() if line and not line.startswith("  ")]
    short = [line for line in body[1:] if len(line) < 40 and not line.endswith(".")]
    assert short == [], short
    assert "Mute-Zuständen, meldet es Undo als FAIL" in text
