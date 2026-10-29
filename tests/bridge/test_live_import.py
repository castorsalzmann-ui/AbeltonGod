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
from conftest import registry_with_status
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
    # test set, target 0, run, undo now (no listening question follows)
    code, out, prompts = run(fake, tmp_path, ["y", "0", "y", "y"], path=p)
    assert code == 0, out
    assert writes(fake) == [(CREATE_CLIP, (0, 1, p)), (UNDO, ())]
    assert fake.tracks[0]["slots"] == ["C:\\old.wav", None, None, None]
    b = block(out)
    assert b["clip_slot.create_audio_clip"] == "PASS"
    assert b["clip_file_path_read"] == repr(p)
    assert b["user_hears_kick"] == "not asked (undo chosen before listening)"
    assert not any("Spielt der Kick" in q for q in prompts)
    assert b["song.undo"].startswith("PASS (clip removed")
    assert b["extension"] == "PRESENT"
    assert b["target"] == "track 0 '1-Audio', slot 1"
    # song.undo (#42) and clip_slot.create_audio_clip (#50) are tested in the committed
    # registry, so an existing-track import needs no override.
    assert b["capability_overrides_used"] == "-"
    assert b["capability_overrides_reads_only"] == "-"
    assert "Geplante Änderungen" in out and p in out
    assert [e["action"] + ":" + e["status"] for e in log_entries(tmp_path)] == [
        "create_audio_clip:planned", "create_audio_clip:read_back",
        "undo_clip:planned", "undo_clip:read_back"]


def test_full_run_new_track_without_undo(fake, tmp_path):
    # test set, new track, run, no undo, plays: yes
    code, out, _ = run(fake, tmp_path, ["y", "n", "y", "", "y"])
    assert code == 0, out
    assert [a for a, _ in writes(fake)] == [CREATE_TRACK, CREATE_CLIP]
    assert len(fake.tracks) == 3 and fake.tracks[2]["slots"][0] is not None
    b = block(out)
    assert b["song.undo"] == "SKIPPED (user answered no)"
    assert b["user_hears_kick"] == "yes"
    assert "song.create_audio_track" in b["capability_overrides_used"]
    assert ("  - Clip: in Spur 2 '3-Audio' die Zelle 0 anklicken, Entf drücken.\n"
            "  - die neue Spur: Kopf von Spur 2 '3-Audio' anklicken, Entf drücken.") in out


def test_new_track_two_undos(fake, tmp_path):
    code, out, _ = run(fake, tmp_path, ["y", "n", "y", "y"])
    assert code == 0, out
    assert [a for a, _ in writes(fake)] == [CREATE_TRACK, CREATE_CLIP, UNDO, UNDO]
    assert [t["name"] for t in fake.tracks] == ["1-Audio", "2-MIDI"]
    assert block(out)["song.undo"].startswith("PASS (clip removed, track removed")
    assert block(out)["user_hears_kick"] == "not asked (undo chosen before listening)"


def test_undo_question_comes_before_the_listening_question(fake, tmp_path):
    """#50 runs 2 and 3: the script must not ask the user to play the clip in Live and then
    offer undo. Undo prompt first; the listening prompt only after 'no undo'."""
    code, out, prompts = run(fake, tmp_path, ["y", "0", "y", "n", "y"])
    assert code == 0, out
    undo_at = next(i for i, q in enumerate(prompts) if "per Undo zurücknehmen" in q)
    hear_at = next(i for i, q in enumerate(prompts) if "Spielt der Kick" in q)
    assert undo_at < hear_at == len(prompts) - 1
    assert UNDO not in [a for a, _ in writes(fake)]
    assert out.index(live_import.UNDO_CHOICE) < out.index("Kein Undo. Der Clip bleibt im Set.")
    b = block(out)
    assert b["song.undo"] == "SKIPPED (user answered no)"
    assert b["user_hears_kick"] == "yes"
    assert "  - Clip: in Spur 0 '1-Audio' die Zelle 1 anklicken, Entf drücken." in out
    assert "die neue Spur" not in out


def test_undo_hint_names_the_live_12_menus():
    """Live 12 manual (checked 2026-10-29): View -> Undo History, German Ansicht ->
    Widerrufen-Historie, Ctrl+Alt+Z; a click on an entry undoes back to it."""
    hint = live_import.UNDO_HINT
    for part in ("Strg+Alt+Z", "Ansicht -> Widerrufen-Historie", "View -> Undo History",
                 "keinen Eintrag anklicken"):
        assert part in hint, part


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


def test_track_number_equal_to_track_count_is_invalid(fake, tmp_path):
    code, out, prompts = run(fake, tmp_path, ["y", "2", ""])  # 2 tracks: valid are 0 and 1
    assert code == 0, out
    assert "Ungültige Eingabe '2'" in out and "Kein Ziel gewählt" in out
    assert writes(fake) == []


@pytest.fixture
def pre50_registry(tmp_path, monkeypatch):
    """The registry as before the #50 contract-change (create_audio_clip `unknown`), so the
    override split is still tested now that the committed entry is `tested`."""
    reg = registry_with_status(tmp_path, {"clip_slot.create_audio_clip": "unknown"})
    monkeypatch.setattr(live_import.CapabilityRegistry, "from_file", classmethod(
        lambda cls, *args, **kwargs: reg))
    return reg


@pytest.mark.parametrize("answers", [["n"], ["y", ""], ["y", "0", "n"]])
def test_no_write_sent_means_no_write_override_reported(fake, tmp_path, answers,
                                                        pre50_registry):
    """Probe and pre-check reads use the import gate, but that is not an import (review #87)."""
    code, out, _ = run(fake, tmp_path, answers)
    b = block(out)
    assert b["capability_overrides_used"] == "-"
    assert b["capability_overrides_reads_only"] == "clip_slot.create_audio_clip"


def test_new_track_import_reports_both_write_overrides(fake, tmp_path, pre50_registry):
    code, out, _ = run(fake, tmp_path, ["y", "n", "y", "y", ""])
    assert code == 0, out
    b = block(out)
    assert b["capability_overrides_used"] == "clip_slot.create_audio_clip, song.create_audio_track"
    assert b["capability_overrides_reads_only"] == "-"


@pytest.mark.parametrize("answers", [["n"], ["y", ""], ["y", "0", "n"]])
def test_committed_registry_no_write_reports_no_override(fake, tmp_path, answers):
    """With the committed registry (#50) the probe and pre-check reads need no override."""
    code, out, _ = run(fake, tmp_path, answers)
    b = block(out)
    assert b["capability_overrides_used"] == "-"
    assert b["capability_overrides_reads_only"] == "-"


def test_committed_registry_new_track_reports_only_the_track_override(fake, tmp_path):
    """song.create_audio_track stays `supported` (#50: its undo is not verified in Live)."""
    code, out, _ = run(fake, tmp_path, ["y", "n", "y", "y", ""])
    assert code == 0, out
    b = block(out)
    assert b["capability_overrides_used"] == "song.create_audio_track"
    assert b["capability_overrides_reads_only"] == "-"


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
    code, out, _ = run(fake, tmp_path, ["y", "0", "y", KeyboardInterrupt])
    assert code == 130
    assert "Der Import war schon fertig" in out
    assert UNDO not in [a for a, _ in writes(fake)]
    # PR #126 review, problem 1: UNDO_CHOICE promises the removal steps here too.
    assert "  - Clip: in Spur 0 '1-Audio' die Zelle 1 anklicken, Entf drücken." in out
    assert "die neue Spur" not in out


def test_ctrl_c_at_listening_prompt_after_no_undo_prints_removal(fake, tmp_path):
    """New track, 'no undo', then Ctrl+C at "Spielt der Kick?": track and clip stay, the
    script says how to remove both (PR #126 review, problem 1)."""
    code, out, prompts = run(fake, tmp_path, ["y", "n", "y", "", KeyboardInterrupt])
    assert code == 130, out
    assert "Spielt der Kick" in prompts[-1]
    assert UNDO not in [a for a, _ in writes(fake)]
    assert "der Clip bleibt im Set, die neue Spur auch." in out
    assert ("  - Clip: in Spur 2 '3-Audio' die Zelle 0 anklicken, Entf drücken.\n"
            "  - die neue Spur: Kopf von Spur 2 '3-Audio' anklicken, Entf drücken.") in out


def test_ctrl_c_during_undo_prints_removal(fake, tmp_path, monkeypatch):
    """Ctrl+C while the undo is being sent: outcome unknown, nothing more is sent, removal
    steps from the newest read-back (PR #126 review, R1)."""
    def interrupted_undo(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(live_import.AbletonBridge, "undo", interrupted_undo)
    code, out, _ = run(fake, tmp_path, ["y", "0", "y", "y"])
    assert code == 130, out
    assert "ABGEBROCHEN mit Strg+C während des Undo" in out
    assert block(out)["song.undo"].startswith("FAIL (interrupted")
    assert "  - Clip: in Spur 0 '1-Audio' die Zelle 1 anklicken, Entf drücken." in out
    assert UNDO not in [a for a, _ in writes(fake)]


def test_second_undo_differs_prints_removal_for_the_track(fake, tmp_path):
    """New track; Live does not record the track creation as an undo step (fake), so undo 1
    removes the clip and undo 2 changes nothing. FAIL, no third undo, removal steps say the
    clip is gone and the track must go by hand (PR #126 review, R2)."""
    orig = fake._create_audio_track

    def track_not_undoable(p):
        orig(p)
        fake.undo_stack.pop()

    fake._create_audio_track = track_not_undoable
    code, out, _ = run(fake, tmp_path, ["y", "n", "y", "y"])
    assert code == 1, out
    assert block(out)["song.undo"].startswith("FAIL (after undo_track")
    assert sum(1 for a, _ in writes(fake) if a == UNDO) == 2
    assert "FEHLER: Nach dem zweiten Undo" in out
    assert ("  - Clip: laut letztem Zurücklesen nicht mehr in Spur 2, Zelle 0.\n"
            "  - die neue Spur: Kopf von Spur 2 '3-Audio' anklicken, Entf drücken.") in out


def test_refused_undo_on_an_already_reverted_set_says_clip_is_gone(fake, tmp_path):
    """#50 run 3: before the undo the set was already back to the pre-import state. The
    refusal names the newest read-back, not the import's (PR #126 review, nit 3)."""
    answers = iter(["y", "0", "y"])

    def reverting_input(prompt):
        a = next(answers, None)
        if a is not None:
            return a
        fake.tracks[0]["slots"][1] = None  # reverted in Live before the undo answer
        return "y"

    receive = free_udp_port()
    fake.response_port = receive
    out = io.StringIO()
    code = live_import.main([wav(tmp_path / "k.wav"), "--send-port", str(fake.port),
                             "--receive-port", str(receive), "--timeout", "0.3",
                             "--log", str(tmp_path / "actions.jsonl")],
                            input_fn=reverting_input, out=out)
    text = out.getvalue()
    assert code == 1, text
    assert UNDO not in [a for a, _ in writes(fake)]
    assert "darum wurde KEIN Undo gesendet." in text
    assert "  - Clip: laut letztem Zurücklesen nicht mehr in Spur 0, Zelle 1." in text
    assert "die Zelle 1 anklicken" not in text


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
    text = out.getvalue()
    assert "undo NOT sent" in block(text)["song.undo"]
    # #50 run 3: a refused undo tells the user why and how to remove the import by hand.
    assert "darum wurde KEIN Undo gesendet." in text
    assert "  - Clip: in Spur 0 '1-Audio' die Zelle 1 anklicken, Entf drücken." in text
    assert "Ansicht -> Widerrufen-Historie" in text


def test_undo_reverting_other_action_is_fail(fake, tmp_path):
    fake.clip_undoable = False
    fake.undo_stack = [(1, True)]  # last user action: unmute track 1
    fake.tracks[1]["mute"] = False
    code, out, _ = run(fake, tmp_path, ["y", "0", "y", "y", "y"])
    assert code == 1
    assert block(out)["song.undo"].startswith("FAIL")
    assert sum(1 for a, _ in writes(fake) if a == UNDO) == 1  # never a second undo
    # #50 run 2: undo sent, clip still there. No cause claimed; manual removal offered.
    assert "Was das Undo zurückgenommen hat, ist unbekannt" in out
    assert "  - Clip: in Spur 0 '1-Audio' die Zelle 1 anklicken, Entf drücken." in out
    assert "darum wurde KEIN Undo gesendet" not in out


@pytest.mark.parametrize("reverts_rename", [True, False])
def test_user_run_1_two_midi_tracks_new_track_renamed(fake, tmp_path, reverts_rename):
    """#50 user run 1 (Live 12.4.5): set with two MIDI tracks, target 'n'. The user's action
    log shows the clip at the first read and the new track renamed '3-Audio' ->
    '3-centre_s1001_v0'; no delay. Script 0.1.0 reported FAIL (file_path=None) although the
    clip was there. Now: PASS, rename reported, two undos, set as before."""
    fake.num_scenes = 8
    fake.tracks = [{"name": "1-MIDI", "mute": False, "slots": [None] * 8},
                   {"name": "2-MIDI", "mute": False, "slots": [None] * 8}]
    fake.rename_on_clip = "3-centre_s1001_v0"
    fake.clip_delay_s = 0.0
    fake.undo_reverts_rename = reverts_rename
    p = wav(tmp_path / "centre_s1001_v0.wav")
    code, out, _ = run(fake, tmp_path, ["y", "n", "y", "y", "y"], path=p)
    assert code == 0, out
    b = block(out)
    assert b["clip_slot.create_audio_clip"] == "PASS"
    assert b["clip_file_path_read"] == repr(p)
    assert b["target_track_name_after_import"] == "'3-centre_s1001_v0'"
    assert "Live hat die Spur umbenannt: '3-Audio' -> '3-centre_s1001_v0'" in out
    assert b["song.undo"] == "PASS (clip removed, track removed; read back)"
    assert "Das Set ist wieder wie vor dem Import" in out
    assert [t["name"] for t in fake.tracks] == ["1-MIDI", "2-MIDI"]
    clip_rb = [e for e in log_entries(tmp_path)
               if e["action"] == "create_audio_clip" and e["status"] == "read_back"]
    assert [e["polls"] for e in clip_rb] == [1]  # matched at the first read, as in run 1


@pytest.mark.parametrize("reverts_rename", [True, False])
def test_existing_track_renamed_by_live_undo_result(fake, tmp_path, reverts_rename):
    """Review of #97, Problem 1: an existing default-named audio track renamed by Live after
    the clip. If undo keeps the new name, the set is not as before: PARTIAL, exit 1, never
    "Das Set ist wieder wie vor dem Import"."""
    fake.tracks[0]["slots"] = [None] * 4
    fake.rename_on_clip = "1-Kick 1"
    fake.undo_reverts_rename = reverts_rename
    code, out, _ = run(fake, tmp_path, ["y", "0", "y", "y", "y"])
    b = block(out)
    assert b["clip_slot.create_audio_clip"] == "PASS"
    assert "Live hat die Spur umbenannt: '1-Audio' -> '1-Kick 1'" in out
    assert fake.tracks[0]["slots"] == [None] * 4
    assert sum(1 for a, _ in writes(fake) if a == UNDO) == 1
    if reverts_rename:
        assert code == 0, out
        assert b["song.undo"] == "PASS (clip removed; read back)"
        assert "Das Set ist wieder wie vor dem Import" in out
    else:
        assert code == 1, out
        assert b["song.undo"] == ("PARTIAL (clip removed; read back; track names not "
                                  "restored: '1-Audio' -> '1-Kick 1')")
        assert "Das Set ist wieder wie vor dem Import" not in out
        assert "ACHTUNG: Undo hat den Import zurückgenommen" in out
        assert "'1-Audio' -> '1-Kick 1'. Das Set ist NICHT ganz wie vorher." in out
        assert [t["name"] for t in fake.tracks] == ["1-Kick 1", "2-MIDI"]


def test_undo_that_also_renames_another_track_is_fail(fake, tmp_path):
    """Review of #97, R6, at script level: the undo removes the clip but also renames another
    track. FAIL, no second undo, no "set restored" line."""
    orig = fake._undo

    def undo_and_rename(p):
        orig(p)
        fake.tracks[1]["name"] = "2-MIDI (renamed)"

    fake._undo = undo_and_rename
    code, out, _ = run(fake, tmp_path, ["y", "0", "y", "y", "y"])
    assert code == 1, out
    assert block(out)["song.undo"].startswith("FAIL (after undo_clip")
    assert "Das Set ist wieder wie vor dem Import" not in out
    assert sum(1 for a, _ in writes(fake) if a == UNDO) == 1


def test_readback_that_never_matches_is_reported_as_unknown(fake, tmp_path):
    fake.clip_delay_s = 30.0  # the clip never shows within the 2 s window
    code, out, prompts = run(fake, tmp_path, ["y", "0", "y", "y", "y"])
    assert code == 1
    assert "zeigt nicht das erwartete Ergebnis" in out and "KEIN Undo" in out
    assert not any("Undo" in p for p in prompts)
    assert UNDO not in [a for a, _ in writes(fake)]


def test_non_ascii_path_round_trip(fake, tmp_path):
    p = wav(tmp_path / "Kick Ä 東京.wav")
    code, out, _ = run(fake, tmp_path, ["y", "0", "y", "", ""], path=p)
    assert code == 0, out
    assert fake.tracks[0]["slots"][1] == p
