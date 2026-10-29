"""Regression for #50 user run 1 (fixed in PR #97): ``live_import.py`` 0.1.0 reported
``clip_slot.create_audio_clip: FAIL`` although Live had created the clip.

The JSON corpus in this folder only describes kick renders (``test_regressions.py``), so this
bridge case is a plain pytest module, like ``test_bug_39_undo_false_pass.py``. CI only: the
fake AbletonOSC server stands in for Live.

Scenario, from the user's action log (#50, 2026-10-29 09:58, Live 12.4.5): a set with two
MIDI tracks, target "new audio track". At the first read-back after the clip, slot 0 already
had the clip (no delay) and Live had renamed the new track ``3-Audio`` ->
``3-centre_s1001_v0``. The old read-back compared all track names, so it never read the file
path. Before the fix (commit dbafc1e): ``FAIL``, ``ImportAborted: read-back after the import
does not show exactly the new clip with this file (file_path=None)``, exit 1.
"""

from __future__ import annotations

import importlib.util
import io
import re
import socket
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "bridge"))

from fake_abletonosc import FakeAbletonOSC  # noqa: E402

_spec = importlib.util.spec_from_file_location("live_import_bug50",
                                               ROOT / "scripts" / "live_import.py")
live_import = importlib.util.module_from_spec(_spec)
sys.modules["live_import_bug50"] = live_import
_spec.loader.exec_module(live_import)

RENAMED = "3-centre_s1001_v0"  # Live's name for the new track, as read back in run 1


class RunOneSet(FakeAbletonOSC):
    """Two MIDI tracks, 8 scenes; Live renames the target track when the clip is made."""

    def __init__(self) -> None:
        super().__init__()
        self.num_scenes = 8
        self.tracks = [{"name": "1-MIDI", "mute": False, "slots": [None] * 8},
                       {"name": "2-MIDI", "mute": False, "slots": [None] * 8}]

    def _create_audio_clip(self, p):
        super()._create_audio_clip(p)  # no delay: visible at once, as in the user's log
        self.tracks[int(p[0])]["name"] = RENAMED


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wav(path: Path) -> str:
    data = b"\x00\x00" * 4
    fmt = struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data"
            + struct.pack("<I", len(data)) + data)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


def test_bug_50_renamed_target_track_is_not_a_failed_import(tmp_path) -> None:
    p = _wav(tmp_path / "centre_s1001_v0.wav")
    fake = RunOneSet()
    try:
        receive = _free_port()
        fake.response_port = receive
        # test set: yes; target: new track; run: yes; plays: yes; undo: no
        answers = iter(["y", "n", "y", "y", "n"])
        out = io.StringIO()
        code = live_import.main(
            [p, "--send-port", str(fake.port), "--receive-port", str(receive),
             "--timeout", "0.3", "--log", str(tmp_path / "actions.jsonl")],
            input_fn=lambda _p: next(answers, ""), out=out,
        )
    finally:
        fake.close()
    text = out.getvalue()
    line = re.search(r"^clip_slot\.create_audio_clip: .*$", text, re.M).group(0)
    assert line == "clip_slot.create_audio_clip: PASS", text
    assert re.search(r"^clip_file_path_read: (.*)$", text, re.M).group(1) == repr(p)
    assert code == 0, text
    assert [t["name"] for t in fake.tracks] == ["1-MIDI", "2-MIDI", RENAMED]
