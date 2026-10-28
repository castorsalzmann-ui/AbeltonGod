"""scripts/live_import.py against the fake AbletonOSC server (#50).

CI only: nothing here talks to Ableton Live. These tests show what the script sends, prints and
logs; whether Live behaves like the fake is what the user's run in #50 shows.
"""

from __future__ import annotations

import importlib.util
import io
import json
import socket
import struct
import sys
from pathlib import Path

import pytest
from fake_abletonosc import FakeAbletonOSC

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("live_import", ROOT / "scripts" / "live_import.py")
live_import = importlib.util.module_from_spec(spec)
sys.modules["live_import"] = live_import
spec.loader.exec_module(live_import)

CREATE_CLIP = "/live/clip_slot/create_audio_clip"
CREATE_TRACK = "/live/song/create_audio_track"
UNDO = "/live/song/undo"
WRITES = (CREATE_CLIP, CREATE_TRACK, UNDO)


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wav(path: Path) -> str:
    data = b"\x00\x00" * 4
    fmt = struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data"
            + struct.pack("<I", len(data)) + data)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


@pytest.fixture
def fake():
    server = FakeAbletonOSC()
    server.tracks = [
        {"name": "1-Audio", "mute": False, "audio": True, "slots": ["C:\\old.wav", None,
                                                                    None, None]},
        {"name": "2-MIDI", "mute": False, "slots": [None] * 4},
    ]
    yield server
    server.close()


def run(fake, tmp_path, answers, extra=(), path=None, send_port=None):
    receive = free_udp_port()
    fake.response_port = receive
    queue = list(answers)
    prompts: list[str] = []

    def input_fn(prompt):
        prompts.append(prompt)
        if not queue:
            raise EOFError
        a = queue.pop(0)
        if a is KeyboardInterrupt:
            raise KeyboardInterrupt
        return a

    out = io.StringIO()
    p = path if path is not None else wav(tmp_path / "Kick 1.wav")
    code = live_import.main(
        [p, "--send-port", str(send_port or fake.port), "--receive-port", str(receive),
         "--timeout", "0.3", "--log", str(tmp_path / "actions.jsonl"), *extra],
        input_fn=input_fn, out=out)
    return code, out.getvalue(), prompts


def block(text: str) -> dict:
    body = text.split("```text\n", 1)[1].split("```", 1)[0]
    result = {}
    for line in body.splitlines():
        if ": " in line and not line.startswith("  "):
            k, v = line.split(": ", 1)
            result[k] = v
    return result


PROBE = (CREATE_CLIP, ())  # extension probe: no arguments, fails before touching the song


def writes(fake):
    """Real writes; the no-argument probe is excluded (checked separately)."""
    return [(a, p) for a, p in fake.payload() if a in WRITES and (a, p) != PROBE]


def test_probe_is_sent_exactly_once_and_without_arguments(fake, tmp_path):
    run(fake, tmp_path, ["n"])
    assert [m for m in fake.payload() if m[0] == CREATE_CLIP] == [PROBE]


def log_entries(tmp_path):
    f = tmp_path / "actions.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]


def test_full_run_existing_track_with_undo(fake, tmp_path):
    p = wav(tmp_path / "Kick 1.wav")
    code, out, prompts = run(fake, tmp_path, ["y", "0", "y", "y", "y"], path=p)
    assert code == 0, out
    assert writes(fake) == [(CREATE_CLIP, (0, 1, p)), (UNDO, ())]
    assert fake.tracks[0]["slots"] == ["C:\\old.wav", None, None, None]
    b = block(out)
    assert b["clip_slot.create_audio_clip"] == "PASS"
    assert b["clip_file_path_read"] == repr(p)
    assert b["user_hears_kick"] == "yes"
    assert b["song.undo"].startswith("PASS (clip removed")
    assert b["extension"] == "PRESENT"
    assert b["target"] == "track 0 '1-Audio', slot 1"
    # song.undo is tested in the committed registry (#42), so it needs no override.
    assert b["capability_overrides_used"] == "clip_slot.create_audio_clip"
    assert "Geplante Änderungen" in out and p in out
    assert [e["action"] + ":" + e["status"] for e in log_entries(tmp_path)] == [
        "create_audio_clip:planned", "create_audio_clip:read_back",
        "undo_clip:planned", "undo_clip:read_back"]


def test_full_run_new_track_without_undo(fake, tmp_path):
    code, out, _ = run(fake, tmp_path, ["y", "n", "y", "y", ""])
    assert code == 0, out
    assert [a for a, _ in writes(fake)] == [CREATE_TRACK, CREATE_CLIP]
    assert len(fake.tracks) == 3 and fake.tracks[2]["slots"][0] is not None
    b = block(out)
    assert b["song.undo"] == "SKIPPED (user answered no)"
    assert "song.create_audio_track" in b["capability_overrides_used"]


def test_new_track_two_undos(fake, tmp_path):
    code, out, _ = run(fake, tmp_path, ["y", "n", "y", "n", "y"])
    assert code == 0, out
    assert [a for a, _ in writes(fake)] == [CREATE_TRACK, CREATE_CLIP, UNDO, UNDO]
    assert [t["name"] for t in fake.tracks] == ["1-Audio", "2-MIDI"]
    assert block(out)["song.undo"].startswith("PASS (clip removed, track removed")
    assert block(out)["user_hears_kick"] == "no"


@pytest.mark.parametrize("answers", [[], [""], ["n"], ["y", ""], ["y", "0", ""],
                                     ["y", "0", "n"]])
def test_default_no_everywhere_sends_nothing(fake, tmp_path, answers):
    code, out, _ = run(fake, tmp_path, answers)
    assert code == 0
    assert writes(fake) == []
    assert log_entries(tmp_path) == []


def test_midi_track_is_refused_at_the_prompt(fake, tmp_path):
    code, out, prompts = run(fake, tmp_path, ["y", "1", "1", "1", "y"])
    # The refusal line, not the "[keine Audiospur]" tag of the track listing.
    assert out.count("Spur 1 '2-MIDI' ist keine Audiospur.") == 3
    assert "Geplante Änderungen" not in out
    assert not any("ausführen" in p for p in prompts)
    assert writes(fake) == []


@pytest.mark.parametrize("answer", ["", "n", "no", "x"])
def test_test_set_prompt_alone_stops(fake, tmp_path, answer):
    """Only an explicit yes at the test-set prompt goes on; later prompts are not reached."""
    code, out, prompts = run(fake, tmp_path, [answer, "0", "y", "y", "y"])
    assert code == 0 and len(prompts) == 1
    assert writes(fake) == []


def test_occupied_slot_is_refused(fake, tmp_path):
    code, out, _ = run(fake, tmp_path, ["y", "0"], extra=["--slot", "0"])
    assert code == 1
    assert "schon belegt" in out and writes(fake) == []


def test_no_empty_slot(fake, tmp_path):
    fake.tracks[0]["slots"] = ["C:\\a.wav"] * 4
    code, out, _ = run(fake, tmp_path, ["y", "0"])
    assert code == 1 and "keine freie Zelle" in out and writes(fake) == []


def test_slot_out_of_range(fake, tmp_path):
    code, out, _ = run(fake, tmp_path, ["y", "0"], extra=["--slot", "9"])
    assert code == 1 and "gibt es nicht" in out and writes(fake) == []


def test_extension_missing(fake, tmp_path):
    fake.extension_installed = False
    code, out, prompts = run(fake, tmp_path, ["y", "0", "y"])
    assert code == live_import.EXIT_EXTENSION_MISSING
    assert "install_abletonosc_extension.py" in out and "SAMPLE_IMPORT_FALLBACK.md" in out
    assert prompts == []  # stops before any question
    assert writes(fake) == [] and block(out)["extension"] == "MISSING"


def test_live_closed(tmp_path):
    dead = free_udp_port()
    receive = free_udp_port()
    out = io.StringIO()
    code = live_import.main([wav(tmp_path / "k.wav"), "--send-port", str(dead),
                             "--receive-port", str(receive), "--timeout", "0.2",
                             "--log", str(tmp_path / "a.jsonl")],
                            input_fn=lambda p: "y", out=out)
    assert code == live_import.EXIT_NO_CONNECTION
    assert "antwortet nicht" in out.getvalue()
    assert "Es wurde nichts in Live geändert." in out.getvalue()


def test_port_in_use(fake, tmp_path):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 0))
    try:
        out = io.StringIO()
        code = live_import.main([wav(tmp_path / "k.wav"), "--send-port", str(fake.port),
                                 "--receive-port", str(blocker.getsockname()[1])],
                                input_fn=lambda p: "y", out=out)
    finally:
        blocker.close()
    assert code == live_import.EXIT_PORT_IN_USE


@pytest.mark.parametrize("bad", ["relative.wav", "MISSING", "TXT"])
def test_bad_file_stops_before_connecting(fake, tmp_path, bad):
    if bad == "MISSING":
        path = str(tmp_path / "nope.wav")
    elif bad == "TXT":
        (tmp_path / "x.wav").write_text("hello")
        path = str(tmp_path / "x.wav")
    else:
        path = bad
    code, out, _ = run(fake, tmp_path, ["y"], path=path)
    assert code == live_import.EXIT_SETUP_ERROR
    assert fake.received == []  # not even a ping


def test_timed_out_import_never_undoes(fake, tmp_path):
    orig = fake._create_audio_clip

    def blocked(p):
        if not p:
            return orig(p)  # the probe: not blocked
        # Runs inside the fake's loop, which already holds its lock: set the hold state
        # directly (fake.hold() would deadlock on the non-reentrant lock).
        fake._held = []
        fake.released.clear()
        fake.release_after(0.45)
        orig(p)

    fake._create_audio_clip = blocked
    code, out, prompts = run(fake, tmp_path, ["y", "0", "y", "y", "y"])
    assert code == 1, out
    assert "UNBEKANNT" in out and "KEIN Undo" in out
    assert UNDO not in [a for a, _ in writes(fake)]
    assert not any("Undo" in p for p in prompts)
    b = block(out)
    assert b["clip_slot.create_audio_clip"] == "FAIL"
    assert [e["status"] for e in log_entries(tmp_path)] == ["planned", "timeout"]


def test_ctrl_c_at_plan_prompt(fake, tmp_path):
    code, out, _ = run(fake, tmp_path, ["y", "0", KeyboardInterrupt])
    assert code == 130 and "nichts in Live geändert" in out and writes(fake) == []


def test_ctrl_c_at_undo_prompt_keeps_clip(fake, tmp_path):
    code, out, _ = run(fake, tmp_path, ["y", "0", "y", "y", KeyboardInterrupt])
    assert code == 130
    assert "Der Import war schon fertig" in out
    assert UNDO not in [a for a, _ in writes(fake)]


def test_undo_refused_when_user_changed_set(fake, tmp_path):
    answers = ["y", "0", "y"]

    def changing_input():
        yield from answers
        fake.tracks[0]["slots"][3] = "C:\\user.wav"  # user adds a clip while listening
        yield "y"
        yield "y"

    gen = changing_input()
    receive = free_udp_port()
    fake.response_port = receive
    out = io.StringIO()
    code = live_import.main([wav(tmp_path / "k.wav"), "--send-port", str(fake.port),
                             "--receive-port", str(receive), "--timeout", "0.3",
                             "--log", str(tmp_path / "actions.jsonl")],
                            input_fn=lambda p: next(gen), out=out)
    assert code == 1
    assert UNDO not in [a for a, _ in writes(fake)]
    assert "undo NOT sent" in block(out.getvalue())["song.undo"]


def test_undo_reverting_other_action_is_fail(fake, tmp_path):
    fake.clip_undoable = False
    fake.undo_stack = [(1, True)]  # last user action: unmute track 1
    fake.tracks[1]["mute"] = False
    code, out, _ = run(fake, tmp_path, ["y", "0", "y", "y", "y"])
    assert code == 1
    assert block(out)["song.undo"].startswith("FAIL")
    assert sum(1 for a, _ in writes(fake) if a == UNDO) == 1  # never a second undo


def test_non_ascii_path_round_trip(fake, tmp_path):
    p = wav(tmp_path / "Kick Ä 東京.wav")
    code, out, _ = run(fake, tmp_path, ["y", "0", "y", "y", ""], path=p)
    assert code == 0, out
    assert fake.tracks[0]["slots"][1] == p
