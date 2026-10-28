"""scripts/bridge_check.py against the fake AbletonOSC server (issue #5).

CI only: nothing here talks to Ableton Live. These tests show what the script sends and prints;
whether Live behaves like the fake is what the user's run in #5 shows.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import socket
import sys
from pathlib import Path

import pytest
from fake_abletonosc import FakeAbletonOSC

from bridge.capabilities import CAPABILITIES_FILE

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bridge_check.py"

spec = importlib.util.spec_from_file_location("bridge_check", SCRIPT)
bridge_check = importlib.util.module_from_spec(spec)
sys.modules["bridge_check"] = bridge_check  # dataclasses look the module up by name
spec.loader.exec_module(bridge_check)

TIMEOUT = "0.3"

# Expected wire traffic, written out by hand (independent of the script's own constants).
READS = [
    ("/live/application/get/version", ()),
    ("/live/song/get/tempo", ()),
    ("/live/song/get/signature_numerator", ()),
    ("/live/song/get/signature_denominator", ()),
    ("/live/song/get/track_names", ()),
]


def get_mute(i):
    return ("/live/track/get/mute", (i,))


def set_mute(i, v):
    return ("/live/track/set/mute", (i, v))


UNDO = ("/live/song/undo", ())


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run(fake, answers, extra_args=()):
    """Run the script's main() against ``fake``; return (exit code, output, prompts)."""
    receive = free_udp_port()
    fake.response_port = receive
    prompts: list[str] = []
    queue = list(answers)

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        if not queue:
            raise EOFError  # more prompts than the test expected: treated as empty answer
        return queue.pop(0)

    out = io.StringIO()
    code = bridge_check.main(
        ["--send-port", str(fake.port), "--receive-port", str(receive), "--timeout", TIMEOUT,
         *extra_args],
        input_fn=input_fn, out=out,
    )
    return code, out.getvalue(), prompts


def writes(payload):
    return [m for m in payload if m[0] in ("/live/track/set/mute", "/live/song/undo")]


def result_block(output: str) -> dict[str, str]:
    m = re.search(r"```text\n(.*?)\n```", output, re.S)
    assert m, output
    fields = {}
    for line in m.group(1).splitlines()[1:]:
        if ": " in line and not line.startswith("  "):
            key, value = line.split(": ", 1)
            fields[key] = value
    return fields


@pytest.fixture
def fake():
    server = FakeAbletonOSC()
    yield server
    server.close()


# -- read-only path --------------------------------------------------------------------------


def test_read_only_happy_path_prints_values_and_sends_no_write(fake):
    fake.tempo, fake.signature = 128.0, (7, 8)
    code, out, prompts = run(fake, ["n"])
    assert code == 0
    assert "Live-Version (laut API, nur Haupt.Neben): 12.3" in out
    assert "Tempo: 128 BPM" in out
    assert "Taktart: 7/8" in out
    assert "  0: 1-Kick" in out and "  1: 2-Bass" in out
    assert fake.payload() == READS
    assert len(prompts) == 1 and "TEST-Set" in prompts[0]
    block = result_block(out)
    for cap in ("app.version", "song.tempo.get", "song.signature.get", "song.track_names.get"):
        assert block[cap].startswith("PASS raw="), block[cap]
    assert block["app.version"] == "PASS raw=(12, 3)"
    assert block["song.signature.get"] == "PASS raw=(7, 8)"
    assert block["song.track_names.get"] == "PASS raw=('1-Kick', '2-Bass')"
    assert block["track.mute.set"].startswith("SKIPPED")
    assert block["song.undo"].startswith("SKIPPED")


@pytest.mark.parametrize("answers", [
    ["n"], [""], ["nein"], ["yes please"],  # anything but y/yes/j/ja is "no" on test set
    ["y", "", "n"], ["y", "1", ""], ["j", "0", "N"],  # test set yes, final confirmation no
    ["y", "x", "9", "-1"],  # three invalid track indices
    [],  # EOF at the first prompt (e.g. stdin closed)
    ["y", "0"],  # EOF / Ctrl+C at the final confirmation
])
def test_any_non_yes_answer_makes_zero_writes(fake, answers):
    code, out, _ = run(fake, answers)
    assert code == 0
    assert writes(fake.payload()) == []
    assert [t["mute"] for t in fake.tracks] == [False, False]


def test_empty_set_skips_writes_without_prompting(fake):
    fake.tracks = []
    code, out, prompts = run(fake, [])
    assert code == 0 and prompts == []
    assert writes(fake.payload()) == []
    assert "keine Spuren im Set" in out


# -- write path ------------------------------------------------------------------------------


def test_yes_path_sends_exactly_the_announced_writes_in_order(fake):
    code, out, _ = run(fake, ["y", "1", "y"])
    assert code == 0, out
    snapshot = [("/live/song/get/track_names", ()), get_mute(0), get_mute(1)]
    assert fake.payload() == READS + [
        get_mute(1),  # R0, shown in the plan
        *snapshot,  # S0, after the confirmation
        set_mute(1, 1), get_mute(1),
        set_mute(1, 0), get_mute(1),
        set_mute(1, 1), get_mute(1),
        UNDO, get_mute(1),
        *snapshot,  # S1
    ]
    assert [t["mute"] for t in fake.tracks] == [False, False]  # set left as it was
    block = result_block(out)
    assert block["track.mute.set"].startswith("PASS raw=R1=(True,); R2=(False,); R3=(True,)")
    assert block["song.undo"] == "PASS raw=R4=(False,); S1=['1-Kick':0, '2-Bass':0]"
    assert block["test_track"] == "1 '2-Bass'"
    assert block["error"] == "-"
    assert "Geplante Änderungen an Spur 1 '2-Bass'" in out


def test_yes_path_on_an_already_muted_track_ends_muted(fake):
    fake.tracks[0]["mute"] = True
    code, out, _ = run(fake, ["y", "", "y"])  # Enter = default track 0
    assert code == 0, out
    assert writes(fake.payload()) == [set_mute(0, 0), set_mute(0, 1), set_mute(0, 0), UNDO]
    assert [t["mute"] for t in fake.tracks] == [True, False]


def test_announcement_comes_before_the_first_write(fake):
    """The plan is printed and confirmed before anything changes in Live."""
    seen_at_confirm = []

    def snapshot(answer):
        def f():
            seen_at_confirm.append(list(writes(fake.payload())))
            return answer
        return f

    answers = iter([lambda: "y", lambda: "0", snapshot("y")])
    receive = free_udp_port()
    fake.response_port = receive
    out = io.StringIO()
    code = bridge_check.main(
        ["--send-port", str(fake.port), "--receive-port", str(receive), "--timeout", TIMEOUT],
        input_fn=lambda _p: next(answers)(), out=out,
    )
    assert code == 0
    assert seen_at_confirm == [[]]
    assert out.getvalue().index("Geplante Änderungen") < out.getvalue().index("R1:")


class _NoopUndoFake(FakeAbletonOSC):
    def _undo(self, p):  # undo accepted but changes nothing
        return None


def test_undo_that_does_not_revert_is_fail_and_state_is_restored_without_second_undo():
    fake = _NoopUndoFake()
    try:
        code, out, _ = run(fake, ["y", "0", "y"])
        assert code == 1
        w = writes(fake.payload())
        assert w == [set_mute(0, 1), set_mute(0, 0), set_mute(0, 1), UNDO, set_mute(0, 0)]
        assert w.count(UNDO) == 1
        assert fake.tracks[0]["mute"] is False
        block = result_block(out)
        assert block["song.undo"].startswith("FAIL raw=R4=(True,)")
        assert block["track.mute.set"].startswith("PASS")
    finally:
        fake.close()


class _IgnoringMuteFake(FakeAbletonOSC):
    def _set_mute(self, p):  # write accepted, state unchanged
        return None


def test_readback_mismatch_stops_before_undo():
    fake = _IgnoringMuteFake()
    try:
        code, out, _ = run(fake, ["y", "0", "y"])
        assert code == 1
        assert writes(fake.payload()) == [set_mute(0, 1)]  # no further write, no undo
        block = result_block(out)
        assert block["track.mute.set"].startswith("FAIL")
        assert block["song.undo"].startswith("SKIPPED")
        assert "KEIN Undo" in out
    finally:
        fake.close()


class _HangAfterFirstMuteFake(FakeAbletonOSC):
    """After the first mute write, hold every reply (like Live blocked by a dialog)."""

    def _set_mute(self, p):
        super()._set_mute(p)
        self._held = []  # called under the server lock; hold() would deadlock


def test_write_timeout_sends_no_undo_and_reports_unknown_outcome():
    fake = _HangAfterFirstMuteFake()
    try:
        code, out, _ = run(fake, ["y", "0", "y"])
        assert code == 1
        assert writes(fake.payload()) == [set_mute(0, 1)]
        assert "UNBEKANNT" in out and "KEIN Undo" in out
        assert "Ursprünglicher Zustand: Spur 0 '1-Kick' war nicht stumm." in out
        assert "after-abort read failed" in out  # replies still held
        assert "von Hand auf nicht stumm stellen" in out
        block = result_block(out)
        assert "W1 timed out" in block["error"]
        assert block["song.undo"].startswith("SKIPPED")
    finally:
        fake.close()


# -- errors ----------------------------------------------------------------------------------


def test_live_not_running_gives_german_error_and_nonzero_exit():
    nobody = free_udp_port()
    out = io.StringIO()
    code = bridge_check.main(
        ["--send-port", str(nobody), "--receive-port", str(free_udp_port()),
         "--timeout", TIMEOUT],
        input_fn=lambda _p: pytest.fail("must not prompt"), out=out,
    )
    text = out.getvalue()
    assert code == 2
    assert "FEHLER: AbletonOSC antwortet nicht" in text
    assert "Ableton Live ist nicht geöffnet" in text
    assert "'AbletonOSC' ist nicht als Control Surface ausgewählt" in text
    assert "Es wurde nichts in Live geändert." in text
    block = result_block(text)
    assert block["bridge.marker_echo"].startswith("FAIL")
    assert block["app.version"].startswith("SKIPPED")


def test_receive_port_in_use_gives_german_error(fake):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 0))
    port = blocker.getsockname()[1]
    try:
        out = io.StringIO()
        code = bridge_check.main(
            ["--send-port", str(fake.port), "--receive-port", str(port)],
            input_fn=lambda _p: pytest.fail("must not prompt"), out=out,
        )
    finally:
        blocker.close()
    assert code == 3
    assert f"FEHLER: Port {port} (127.0.0.1) ist schon belegt." in out.getvalue()
    assert fake.received == []


def test_protocol_error_in_a_read_is_fail_with_raw_value(fake):
    fake.version = (12,)
    code, out, _ = run(fake, ["n"])
    assert code == 1
    block = result_block(out)
    assert block["app.version"].startswith("FAIL raw=(12,)")
    assert block["song.tempo.get"].startswith("PASS")


# -- result block and registry ---------------------------------------------------------------


def test_result_block_format(fake):
    code, out, _ = run(fake, ["y", "0", "y"])
    assert code == 0
    m = re.search(r"```text\n(.*?)\n```", out, re.S)
    lines = m.group(1).splitlines()
    assert lines[0] == "AbeltonGod bridge_check result"
    keys = [ln.split(": ", 1)[0] for ln in lines[1:] if not ln.startswith("  ")]
    assert keys == [
        "script_version", "python", "started_at", "finished_at", "live_version_api",
        "capability_overrides_used", "test_track", "bridge.marker_echo", "app.version",
        "song.tempo.get", "song.signature.get", "song.track_names.get", "track.mute.set",
        "song.undo", "write_sequence:", "error",
    ]
    block = result_block(out)
    assert re.fullmatch(r"\d+\.\d+\.\d+", block["script_version"])
    assert re.match(r"3\.\d+\.\d+ ", block["python"])
    iso = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d"
    assert re.fullmatch(iso, block["started_at"]) and re.fullmatch(iso, block["finished_at"])
    assert block["live_version_api"] == "12.3 (API reports major.minor only)"
    assert block["capability_overrides_used"] == (
        "app.version, song.signature.get, song.tempo.get, song.track_names.get, "
        "song.undo, track.mute.set"
    )
    for line in lines:
        if re.match(r"^[a-z_.]+: (PASS|FAIL|SKIPPED)", line):
            assert re.fullmatch(r"[a-z_.]+: (PASS|FAIL|SKIPPED) raw=.+", line), line


def test_script_does_not_change_the_registry(fake):
    before = CAPABILITIES_FILE.read_bytes()
    run(fake, ["y", "0", "y"])
    assert CAPABILITIES_FILE.read_bytes() == before
    statuses = {c["id"]: c["status"] for c in json.loads(before)["capabilities"]}
    assert "tested" not in statuses.values()
