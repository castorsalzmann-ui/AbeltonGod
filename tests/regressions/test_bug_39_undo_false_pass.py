"""Regression for #39 (review E9 of PR #37): bridge_check reported ``song.undo: PASS`` after the
undo had reverted an unrelated user action.

The JSON corpus in this folder only describes kick renders (``test_regressions.py``), so this
bridge case is a plain pytest module. CI only: the fake AbletonOSC server stands in for Live.

Scenario (simulated, not observed in Live): Live does not record the LOM mute change as an
undo step, and the user's last action was "insert track at index 0". ``/live/song/undo`` then
deletes that track, the remaining tracks shift down, and the mute flag at the test index reads
as unmuted. Before the fix (commit bc3809e): ``song.undo: PASS``, "Das Set ist wie vorher.",
exit 0.
"""

from __future__ import annotations

import importlib.util
import io
import re
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "bridge"))

from fake_abletonosc import FakeAbletonOSC  # noqa: E402

_spec = importlib.util.spec_from_file_location("bridge_check_bug39",
                                               ROOT / "scripts" / "bridge_check.py")
bridge_check = importlib.util.module_from_spec(_spec)
sys.modules["bridge_check_bug39"] = bridge_check
_spec.loader.exec_module(bridge_check)


class UndoDeletesInsertedTrack(FakeAbletonOSC):
    """Mute writes are not undoable; the only undo step is the user's track insert at 0."""

    def __init__(self) -> None:
        super().__init__()
        self.tracks = [{"name": "3-New", "mute": False}, {"name": "1-Kick", "mute": False},
                       {"name": "2-Bass", "mute": False}]
        self.undo_stack = [("insert", 0)]

    def _set_mute(self, p):
        self.tracks[int(p[0])]["mute"] = bool(p[1])  # not recorded in the undo history

    def _undo(self, p):
        if self.undo_stack:
            _, idx = self.undo_stack.pop()
            del self.tracks[idx]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_bug_39_undo_reverting_another_action_is_never_pass() -> None:
    fake = UndoDeletesInsertedTrack()
    try:
        receive = _free_port()
        fake.response_port = receive
        answers = iter(["y", "0", "y"])
        out = io.StringIO()
        code = bridge_check.main(
            ["--send-port", str(fake.port), "--receive-port", str(receive), "--timeout", "0.3"],
            input_fn=lambda _p: next(answers, ""), out=out,
        )
    finally:
        fake.close()
    text = out.getvalue()
    undo_line = re.search(r"^song\.undo: .*$", text, re.M).group(0)
    assert undo_line.startswith("song.undo: FAIL"), undo_line
    assert code != 0
    assert "Das Set ist wie vorher." not in text
