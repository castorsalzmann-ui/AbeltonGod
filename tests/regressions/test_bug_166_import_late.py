"""Regression for #166: ``live_import`` stopped as "outcome unknown" when Live applied
``create_audio_track`` or ``create_audio_clip`` but the confirmation came late or not at all.

Side finding of #140 (the same pattern in ``arrangement_check`` 0.1.0 stopped the user's run 1).
Not observed in the user's import runs so far (#143: ``create_audio_track`` confirmed in
time), so the scenario is built from #140's two mechanisms; which of them happened in Live is
not established. CI only: the fake AbletonOSC server stands in for Live.

- ``busy``: the fake answers nothing for 2x the timeout after the call (end echo late);
- ``lost``: the end-marker echo of the call never arrives.

Before the fix (origin/main at f7ca895): ``ImportAborted: <write> timed out; outcome unknown``,
exit 1, no undo offered. After: the step is ``confirmed (late: ...)``, the import passes and
the undo restores the set. A plain pytest module, like ``test_bug_140_*`` (the JSON corpus
only covers kick renders).
"""

from __future__ import annotations

import importlib.util
import io
import socket
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "bridge"))

from fake_abletonosc import FakeAbletonOSC  # noqa: E402

_spec = importlib.util.spec_from_file_location("live_import_bug166",
                                               ROOT / "scripts" / "live_import.py")
script = importlib.util.module_from_spec(_spec)
sys.modules["live_import_bug166"] = script
_spec.loader.exec_module(script)

CREATE_TRACK = "/live/song/create_audio_track"
CREATE_CLIP = "/live/clip_slot/create_audio_clip"
TIMEOUT_S = 0.3  # the script's --timeout here; the default is 1.0 s
SET = ["1-Audio", "2-MIDI"]


def _set() -> FakeAbletonOSC:
    fake = FakeAbletonOSC()
    fake.tracks = [{"name": "1-Audio", "mute": False, "audio": True, "slots": [None] * 4},
                   {"name": "2-MIDI", "mute": False, "midi": True, "slots": [None] * 4}]
    return fake


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


def _run(fake: FakeAbletonOSC, tmp_path: Path, answers: list[str]) -> tuple[int, str]:
    fake.response_port = _free_port()
    queue = list(answers)
    out = io.StringIO()
    code = script.main(
        [_wav(tmp_path / "kick.wav"), "--send-port", str(fake.port), "--receive-port",
         str(fake.response_port), "--timeout", str(TIMEOUT_S),
         "--log", str(tmp_path / "actions.jsonl")],
        input_fn=lambda _p: queue.pop(0) if queue else "", out=out)
    return code, out.getvalue()


def _block(text: str) -> dict[str, str]:
    body = text.split("```text\n", 1)[1].split("```", 1)[0]
    return dict(line.split(": ", 1) for line in body.splitlines()
                if ": " in line and not line.startswith("  "))


def _step(text: str, label: str) -> str:
    body = text.split("```text\n", 1)[1].split("```", 1)[0].splitlines()
    return next(ln.strip() for ln in body if ln.startswith(f"  {label}: "))


def _fault(fake: FakeAbletonOSC, address: str, mechanism: str) -> None:
    if mechanism == "busy":
        fake.stall_after[address] = 2 * TIMEOUT_S  # the probe fails, so it never stalls
        return
    if address == CREATE_TRACK:
        fake.drop_next_marker_after.add(address)
        return
    real = fake._create_audio_clip

    def create_and_lose_echo(p):  # not for the argument-less extension probe
        real(p)
        fake.drop_next_marker_after.add(CREATE_CLIP)

    fake._create_audio_clip = create_and_lose_echo


@pytest.mark.parametrize("mechanism", ["busy", "lost"])
@pytest.mark.parametrize("address,label", [(CREATE_TRACK, "create_audio_track"),
                                           (CREATE_CLIP, "create_audio_clip")])
def test_slow_or_unconfirmed_import_write_is_recognised_by_read_back(tmp_path, address, label,
                                                                    mechanism):
    fake = _set()
    try:
        _fault(fake, address, mechanism)
        code, out = _run(fake, tmp_path, ["y", "n", "y", "y"])  # test set, new track, plan, undo
        b = _block(out)
        assert "timeout (outcome unknown)" not in out, out
        assert code == script.EXIT_OK, out
        step = _step(out, label)
        assert step.startswith(f"{label}: confirmed (late: no confirmation within 0.3 s; "
                               "read-back matched ("), step
        echo = "end echo after" if mechanism == "busy" else "end echo not seen"
        assert echo in step, step
        assert b["clip_slot.create_audio_clip"] == "PASS", out
        assert b["song.undo"] == "PASS (clip removed, track removed; read back)", out
        assert [t["name"] for t in fake.tracks] == SET  # the undos restored the set
    finally:
        fake.close()
