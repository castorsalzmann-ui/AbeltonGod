"""Regression for #140 user run 1: ``arrangement_check.py`` 0.1.0 stopped with
``create_midi_track: timeout (outcome unknown)`` although Live had created the track.

The JSON corpus in this folder only describes kick renders (``test_regressions.py``), so this
bridge case is a plain pytest module, like ``test_bug_50_readback_rename.py``. CI only: the
fake AbletonOSC server stands in for Live; nothing here shows how Live behaves.

Scenario, from the user's result block and ``abletonosc.log`` (#140, 2026-10-29 20:02, Live
12.4): set ``1-MIDI, 2-MIDI, 3-Audio, 4-Audio``, no locators, position 0. Live logged
``Calling method for song: create_midi_track (params [-1])`` at 20:02:09.538 and no error; the
script's confirmation did not arrive within its 1 s timeout; the read-back after the timeout
showed ``5-MIDI`` at index 4, a MIDI track, empty. Before the fix (commit 1653ebf):
``ImportAborted: create_midi_track timed out; outcome unknown``, exit 1, no undo offered.

Which of the two mechanisms below happened in Live is NOT established (see the PR); both give
exactly the user's result with 0.1.0, and both must now be recognised by the read-back:

- ``busy``: the fake answers nothing for 2x the timeout after the call (Live's GUI thread
  busy after creating the track; the end-marker echo comes late);
- ``lost``: the end-marker echo of the call never arrives (a lost reply datagram).
"""

from __future__ import annotations

import importlib.util
import io
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "bridge"))

from fake_abletonosc import FakeAbletonOSC  # noqa: E402

_spec = importlib.util.spec_from_file_location("arrangement_check_bug140",
                                               ROOT / "scripts" / "arrangement_check.py")
script = importlib.util.module_from_spec(_spec)
sys.modules["arrangement_check_bug140"] = script
_spec.loader.exec_module(script)

CREATE = "/live/song/create_midi_track"
TIMEOUT_S = 0.3  # the script's --timeout here; the user ran the default 1.0 s
USER_SET = ["1-MIDI", "2-MIDI", "3-Audio", "4-Audio"]


def _user_set() -> FakeAbletonOSC:
    fake = FakeAbletonOSC()
    fake.tracks = [{"name": n, "mute": False, "midi": "MIDI" in n, "audio": "Audio" in n,
                    "slots": [None] * 4} for n in USER_SET]
    return fake


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run(fake: FakeAbletonOSC, tmp_path: Path, answers: list[str]) -> tuple[int, str]:
    fake.response_port = _free_port()
    queue = list(answers)
    out = io.StringIO()
    code = script.main(
        ["--send-port", str(fake.port), "--receive-port", str(fake.response_port),
         "--timeout", str(TIMEOUT_S), "--log", str(tmp_path / "actions.jsonl")],
        input_fn=lambda _p: queue.pop(0) if queue else "", out=out)
    return code, out.getvalue()


def _block(text: str) -> dict[str, str]:
    body = text.split("```text\n", 1)[1].split("```", 1)[0]
    return dict(line.split(": ", 1) for line in body.splitlines()
                if ": " in line and not line.startswith("  "))


def _steps(text: str) -> list[str]:
    body = text.split("```text\n", 1)[1].split("```", 1)[0].splitlines()
    i = body.index("steps:")
    return [ln.strip() for ln in body[i + 1:] if ln.startswith("  ")][:6]


def _fault(fake: FakeAbletonOSC, mechanism: str) -> None:
    if mechanism == "busy":
        fake.stall_after[CREATE] = 2 * TIMEOUT_S
    else:
        fake.drop_next_marker_after.add(CREATE)


@pytest.mark.parametrize("mechanism", ["busy", "lost"])
def test_slow_or_unconfirmed_create_is_recognised_by_read_back(tmp_path, mechanism):
    fake = _user_set()
    try:
        _fault(fake, mechanism)
        code, out = _run(fake, tmp_path, ["y", "y", "y"])  # test set, plan, undo
        b = _block(out)
        assert "timeout (outcome unknown)" not in out, out
        assert code == script.EXIT_OK, out
        assert b["song.create_midi_track"] == "PASS (late: read-back after timeout)", out
        step = _steps(out)[1]
        assert step.startswith("create_midi_track: confirmed (late:"), step
        echo = "end echo after" if mechanism == "busy" else "end echo not seen"
        assert echo in step, step
        assert b["song.undo"].startswith("PASS"), out
        assert [t["name"] for t in fake.tracks] == USER_SET  # undo restored the set
    finally:
        fake.close()
