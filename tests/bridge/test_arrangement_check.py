"""scripts/arrangement_check.py against the fake AbletonOSC server (#140).

CI only: nothing here talks to Ableton Live. These tests show what the script sends, prints and
logs; whether Live behaves like the fake (which writes are undo steps, how locators are
ordered, what Live names a new locator) is what the user's run in #140 shows.
"""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import random
import socket
import sys
from pathlib import Path

import pytest
from fake_abletonosc import FakeAbletonOSC

import bridge.arrangement_check as arr

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("arrangement_check",
                                              ROOT / "scripts" / "arrangement_check.py")
script = importlib.util.module_from_spec(spec)
sys.modules["arrangement_check"] = script
spec.loader.exec_module(script)

SONG_TIME_SET = "/live/song/set/current_song_time"
CREATE_TRACK = "/live/song/create_midi_track"
CREATE_CLIP = "/live/track/create_midi_clip"
ADD_NOTES = "/live/track/arrangement_clip/add/notes"
GET_NOTES = "/live/track/arrangement_clip/get/notes"
TOGGLE_CUE = "/live/song/cue_point/add_or_delete"
CUE_NAME = "/live/song/cue_point/set/name"
UNDO = "/live/song/undo"
WRITES = (SONG_TIME_SET, CREATE_TRACK, CREATE_CLIP, ADD_NOTES, TOGGLE_CUE, CUE_NAME, UNDO)
PROBES = [(CREATE_CLIP, ()), (ADD_NOTES, ()), (GET_NOTES, ())]


def test_imports_come_from_this_tree():
    assert Path(arr.__file__).resolve().is_relative_to(ROOT)


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def fake():
    server = FakeAbletonOSC()
    server.tracks = [
        {"name": "1-Audio", "mute": False, "audio": True, "slots": [None] * 4},
        {"name": "2-MIDI", "mute": False, "midi": True, "slots": [None] * 4},
    ]
    server.cue_points = [["Drop", 64.0]]
    yield server
    server.close()


def snapshot(fake):
    return copy.deepcopy((fake.tracks, fake.cue_points))


def run(fake, tmp_path, answers, extra=(), send_port=None, on_prompt=None):
    receive = free_udp_port()
    fake.response_port = receive
    queue = list(answers)
    prompts: list[str] = []

    def input_fn(prompt):
        prompts.append(prompt)
        if on_prompt is not None:
            on_prompt(len(prompts), prompt)
        if not queue:
            raise EOFError
        a = queue.pop(0)
        if a is KeyboardInterrupt:
            raise KeyboardInterrupt
        return a

    out = io.StringIO()
    code = script.main(
        ["--send-port", str(send_port or fake.port), "--receive-port", str(receive),
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


def block_list(text: str, key: str) -> list[str]:
    body = text.split("```text\n", 1)[1].split("```", 1)[0].splitlines()
    i = body.index(f"{key}:")
    out = []
    for line in body[i + 1:]:
        if not line.startswith("  "):
            break
        out.append(line.strip())
    return out


def writes(fake):
    return [(a, p) for a, p in fake.payload() if a in WRITES and (a, p) not in PROBES]


def log_entries(tmp_path):
    f = tmp_path / "actions.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]


def expected_writes(start=16.0, length=16.0, target=2, cue_index=1, name="AbeltonGod Test",
                    song_time=True):
    notes = []
    for b in range(int(length)):
        notes += [36, float(b), 0.25, 100, 0]
    w = [(SONG_TIME_SET, (start,))] if song_time else []
    return w + [(CREATE_TRACK, (-1,)), (CREATE_CLIP, (target, start, length)),
                (ADD_NOTES, (target, 0, *notes)), (TOGGLE_CUE, ()), (CUE_NAME, (cue_index, name))]


# -- the happy paths -------------------------------------------------------------------------

def test_full_run_with_undo_restores_the_set(fake, tmp_path):
    before = snapshot(fake)
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == 0, out
    assert writes(fake) == expected_writes() + [(UNDO, ())] * 5
    assert snapshot(fake) == before
    assert fake.song_time == 16.0  # the position is reported, not restored
    b = block(out)
    for cap in ("song.current_song_time.set", "song.create_midi_track", "track.create_midi_clip",
                "arrangement_clip.notes.add", "song.cue_point.add_or_delete",
                "song.cue_point.set_name"):
        assert b[cap] == "PASS", cap
    assert b["song.undo"] == "PASS (5 undo(s) for 5 write(s); read back)"
    assert block_list(out, "undo_chain") == [
        "undo_1: 'after set_cue_name' -> 'after add_cue'",
        "undo_2: 'after add_cue' -> 'after add_notes'",
        "undo_3: 'after add_notes' -> 'after create_midi_clip'",
        "undo_4: 'after create_midi_clip' -> 'after create_midi_track'",
        "undo_5: 'after create_midi_track' -> 'before'"]
    assert b["arrangement_clips_read"] == "[(16.0, 16.0)]"
    assert b["notes_read"].startswith("16 notes; first [(36, 0.0, 0.25, 100.0, False)")
    assert b["cue_default_name"] == "'1'"
    assert b["target_track_name"] == "'3-MIDI'"
    assert b["song_time_before"] == "0" and b["song_time_after"] == "16"
    assert b["extension"] == "PRESENT" and b["signature"] == "4/4"
    assert b["user_sees_result"] == "not asked (undo chosen before looking)"
    assert b["capability_overrides_used"] == ", ".join(sorted(script.ALLOW_UNREGISTERED))
    assert not any("Siehst du" in p for p in prompts)
    assert [e["action"] + ":" + e["status"] for e in log_entries(tmp_path)] == [
        f"{a}:{s}" for a in ("set_song_time", "create_midi_track", "create_midi_clip",
                             "add_notes", "add_cue", "set_cue_name",
                             "undo_1", "undo_2", "undo_3", "undo_4", "undo_5")
        for s in ("planned", "read_back")]


def test_probes_are_sent_once_each_and_without_arguments(fake, tmp_path):
    run(fake, tmp_path, ["n"])
    sent = [m for m in fake.payload() if m[0] in (CREATE_CLIP, ADD_NOTES, GET_NOTES)]
    assert sent == PROBES


def test_full_run_without_undo_keeps_everything_and_explains_removal(fake, tmp_path):
    code, out, prompts = run(fake, tmp_path, ["y", "y", "", "y"])
    assert code == 0, out
    assert writes(fake) == expected_writes()
    assert [t["name"] for t in fake.tracks] == ["1-Audio", "2-MIDI", "3-MIDI"]
    assert fake.tracks[2]["arrangement"][0]["start"] == 16.0
    assert len(fake.tracks[2]["arrangement"][0]["notes"]) == 16
    assert fake.cue_points == [["Drop", 64.0], ["AbeltonGod Test", 16.0]]
    b = block(out)
    assert b["song.undo"] == "SKIPPED (user answered no)"
    assert b["user_sees_result"] == "yes"
    assert "Spur 2 '3-MIDI'" in out and "Locator 'AbeltonGod Test' bei Takt 5" in out
    assert "Siehst du" in prompts[-1]


def test_song_time_already_at_the_start_is_not_written(fake, tmp_path):
    fake.song_time = 16.0
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == 0, out
    assert writes(fake) == expected_writes(song_time=False) + [(UNDO, ())] * 5
    assert block(out)["song.current_song_time.set"].startswith("SKIPPED")
    assert "Abspielposition auf" not in out


def test_bar_bars_and_name_options(fake, tmp_path):
    fake.cue_points = [["Late", 200.0], ["Early", 8.0]]  # Live's order is not time order
    code, out, _ = run(fake, tmp_path, ["y", "y", ""],
                       extra=["--bar", "9", "--bars", "2", "--name", "Intro"])
    assert code == 0, out
    assert writes(fake) == expected_writes(start=32.0, length=8.0, cue_index=2, name="Intro")
    assert fake.cue_points[2] == ["Intro", 32.0]


def test_locator_name_equal_to_lives_default_is_not_written(fake, tmp_path):
    fake.cue_default_name = "Intro"
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"], extra=["--name", "Intro"])
    assert code == 0, out
    assert CUE_NAME not in [a for a, _ in writes(fake)]
    assert block(out)["song.cue_point.set_name"].startswith("SKIPPED")
    assert block(out)["song.undo"] == "PASS (4 undo(s) for 4 write(s); read back)"


# -- undo: what Live might do (all simulated) ------------------------------------------------

def test_one_undo_reverting_everything_is_recognised(fake, tmp_path):
    fake.undo_batch = 5
    before = snapshot(fake)
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == 0, out
    assert writes(fake).count((UNDO, ())) == 1
    assert block_list(out, "undo_chain") == ["undo_1: 'after set_cue_name' -> 'before'"]
    assert snapshot(fake) == before


@pytest.mark.parametrize("not_undoable,undos", [
    ({"song_time", "cue_name"}, 4),  # undo 1 removes the locator with its name
    ({"song_time", "arr_clip"}, 4),  # the track undo takes the clip with it
    (set(), 5),  # the song position IS an undo step: never reached (it was step 0)
])
def test_writes_that_are_no_undo_step(fake, tmp_path, not_undoable, undos):
    fake.not_undoable = not_undoable
    before = snapshot(fake)
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == 0, out
    assert writes(fake).count((UNDO, ())) == undos
    assert snapshot(fake) == before


def test_undo_without_visible_change_stops_the_chain(fake, tmp_path):
    fake.undo_noop = True  # like #50 run 2 (cause not established there)
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert writes(fake).count((UNDO, ())) == 1
    b = block(out)
    assert b["song.undo"].startswith("FAIL (after undo_1 the set shows no visible change")
    assert block_list(out, "undo_chain") == ["undo_1: 'after set_cue_name' -> no visible change"]
    assert "Von Hand entfernen" in out and "Spur 2 '3-MIDI'" in out


def test_foreign_change_before_undo_is_refused_and_nothing_sent(fake, tmp_path):
    def touch(n, prompt):
        if "Undo" in prompt and "OHNE" in prompt:
            fake.cue_points.append(["user", 4.0])  # the user adds a locator in Live

    code, out, _ = run(fake, tmp_path, ["y", "y", "y"], on_prompt=touch)
    assert code == script.EXIT_CHECK_FAILED, out
    assert (UNDO, ()) not in writes(fake)
    assert "KEIN Undo gesendet" in out
    assert block(out)["song.undo"].startswith("FAIL (ImportAborted: the set is not as")


def test_invisible_foreign_undo_step_stops_after_one_undo(fake, tmp_path):
    """Blind spot: a mute is not in the read-back. Its undo step is reverted instead of ours;
    the read-back then shows no change and the chain stops (no second undo)."""
    def touch(n, prompt):
        if "Undo" in prompt and "OHNE" in prompt:
            fake.undo_stack.append((0, False))
            fake.tracks[0]["mute"] = True

    code, out, _ = run(fake, tmp_path, ["y", "y", "y"], on_prompt=touch)
    assert code == script.EXIT_CHECK_FAILED, out
    assert writes(fake).count((UNDO, ())) == 1
    assert fake.tracks[0]["mute"] is False and len(fake.tracks) == 3


def test_undo_that_reaches_an_unknown_state_stops(fake, tmp_path):
    fake.undo_batch = 2  # S5 -> S3 would be fine; make it land somewhere new instead

    def touch(n, prompt):
        if "Undo" in prompt and "OHNE" in prompt:
            fake.undo_stack.insert(-1, ("cue_del", 0, ["Ghost", 100.0]))

    code, out, _ = run(fake, tmp_path, ["y", "y", "y"], on_prompt=touch)
    assert code == script.EXIT_CHECK_FAILED, out
    assert block_list(out, "undo_chain") == [
        "undo_1: 'after set_cue_name' -> a state this run never had"]


def test_target_renamed_by_live_is_tolerated_but_a_foreign_rename_is_not(fake, tmp_path):
    def rename(n, prompt):
        if "Undo" in prompt and "OHNE" in prompt:
            fake.tracks[2]["name"] = "renamed by user"

    code, out, _ = run(fake, tmp_path, ["y", "y", "y"], on_prompt=rename)
    assert code == script.EXIT_CHECK_FAILED and (UNDO, ()) not in writes(fake)


# -- refusals before anything is sent --------------------------------------------------------

def test_extension_missing(fake, tmp_path):
    fake.arrangement_extension_installed = False
    code, out, prompts = run(fake, tmp_path, ["y", "y"])
    assert code == script.EXIT_EXTENSION_MISSING
    assert writes(fake) == [] and prompts == []
    assert block(out)["extension"].startswith("MISSING (/live/track/create_midi_clip, ")
    assert "install_abletonosc_extension.py" in out


@pytest.mark.parametrize("change,error", [
    (lambda f: setattr(f, "signature", (3, 4)), "signature 3/4, only 4/4 supported"),
    (lambda f: setattr(f, "is_playing", True), "Live is playing"),
    (lambda f: f.cue_points.append(["mine", 16.0]), "a locator exists at beat 16"),
])
def test_refusals_before_any_prompt(fake, tmp_path, change, error):
    change(fake)
    before = snapshot(fake)
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED
    assert writes(fake) == [] and prompts == [] and snapshot(fake) == before
    assert block(out)["error"] == error
    assert log_entries(tmp_path) == []


@pytest.mark.parametrize("answers", [["n"], [""], [], ["y", "n"], ["y", ""], ["y"]])
def test_no_or_eof_at_the_first_two_prompts_sends_nothing(fake, tmp_path, answers):
    code, out, _ = run(fake, tmp_path, answers)
    assert code == 0
    assert writes(fake) == [] and log_entries(tmp_path) == []
    assert block(out)["plan_confirmed"] == "no"


def test_set_changed_between_plan_and_confirmation(fake, tmp_path):
    def touch(n, prompt):
        if "ausführen" in prompt:
            fake.tracks.append({"name": "new", "mute": False, "midi": True})

    code, out, _ = run(fake, tmp_path, ["y", "y"], on_prompt=touch)
    assert code == script.EXIT_CHECK_FAILED
    assert writes(fake) == [] and "nichts in Live geändert" in out


@pytest.mark.parametrize("args", [["--bar", "0"], ["--bars", "0"], ["--bars", "17"],
                                  ["--name", ""], ["--name", "x" * 65], ["--name", "a\nb"],
                                  ["--bar", "394200"]])
def test_bad_arguments_are_refused_before_connecting(fake, tmp_path, args):
    code, out, _ = run(fake, tmp_path, ["y", "y"], extra=args)
    assert code == script.EXIT_SETUP_ERROR
    assert fake.payload() == []


def test_no_abletonosc(tmp_path):
    receive = free_udp_port()
    out = io.StringIO()
    code = script.main(["--send-port", str(free_udp_port()), "--receive-port", str(receive),
                        "--timeout", "0.2", "--log", str(tmp_path / "a.jsonl")],
                       input_fn=lambda p: "y", out=out)
    assert code == script.EXIT_NO_CONNECTION
    assert "antwortet nicht" in out.getvalue() and "nichts in Live geändert" in out.getvalue()


def test_port_in_use(fake, tmp_path):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 0))
    try:
        out = io.StringIO()
        code = script.main(["--send-port", str(fake.port), "--receive-port",
                            str(blocker.getsockname()[1]), "--log", str(tmp_path / "a.jsonl")],
                           input_fn=lambda p: "y", out=out)
    finally:
        blocker.close()
    assert code == script.EXIT_PORT_IN_USE and fake.payload() == []


# -- Ctrl+C at every prompt ------------------------------------------------------------------

@pytest.mark.parametrize("at,sent", [(1, 0), (2, 0), (3, 6), (4, 6)])
def test_ctrl_c_at_each_prompt(fake, tmp_path, at, sent):
    answers = ["y", "y", "", "y"]
    answers[at - 1] = KeyboardInterrupt
    try:
        code, out, prompts = run(fake, tmp_path, answers)
    except KeyboardInterrupt:  # caught so pytest reports a failure, not an abort
        pytest.fail("Ctrl+C escaped main()")
    assert code == script.EXIT_INTERRUPTED
    assert len(prompts) == at
    assert len(writes(fake)) == sent and (UNDO, ()) not in writes(fake)
    assert "ABGEBROCHEN mit Strg+C" in out
    if sent:
        assert "alles bleibt im Set" in out and "Von Hand entfernen" in out
    else:
        assert "Es wurde nichts in Live geändert." in out
    assert "```text" in out


# -- faults during the writes ----------------------------------------------------------------

BRIDGE_WRITES = {
    "set_song_time": "set_song_time",
    "create_midi_track": "create_midi_track",
    "create_midi_clip": "create_arrangement_midi_clip",
    "add_notes": "add_arrangement_clip_notes",
    "add_cue": "toggle_cue_at_song_time",
    "set_cue_name": "set_cue_name",
}


@pytest.mark.parametrize("label", list(BRIDGE_WRITES))
def test_ctrl_c_during_each_write_is_unknown_and_never_undone(fake, tmp_path, monkeypatch,
                                                               label):
    method = BRIDGE_WRITES[label]
    real = getattr(script.AbletonBridge, method)

    def interrupted(self, *a, **k):
        real(self, *a, **k)  # sent, but the confirmation never arrives
        raise KeyboardInterrupt

    monkeypatch.setattr(script.AbletonBridge, method, interrupted)
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y", "y"])
    assert code == script.EXIT_INTERRUPTED, out
    assert (UNDO, ()) not in writes(fake)
    assert len(prompts) == 2  # no undo question
    assert "UNBEKANNT" in out and "KEIN Undo" in out
    statuses = [(e["action"], e["status"]) for e in log_entries(tmp_path)]
    assert statuses[-2:] == [(label, "planned"), (label, "interrupted")]
    assert f"{label}: interrupted (outcome unknown)" in block_list(out, "steps")


@pytest.mark.parametrize("address", [SONG_TIME_SET, CREATE_TRACK, CREATE_CLIP, ADD_NOTES,
                                     TOGGLE_CUE, CUE_NAME])
def test_timeout_during_each_write_is_unknown_and_never_undone(fake, tmp_path, address):
    """The write is applied, then Live stops answering (markers vanish, like a dialog)."""
    real = fake._handlers

    def handlers():
        h = real()
        orig = h[address]

        def then_go_silent(p):
            rv = orig(p)
            fake.drop.add("/live/song/get/tempo")
            return rv
        h[address] = then_go_silent
        return h

    fake._handlers = handlers
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert (UNDO, ()) not in writes(fake) and len(prompts) == 2
    assert "UNBEKANNT" in out
    assert log_entries(tmp_path)[-1]["status"] == "timeout"


@pytest.mark.parametrize("fault,label", [
    (lambda f: setattr(f, "drop_notes_on_add", 1), "add_notes"),
    (lambda f: setattr(f, "cue_time_offset", 1.0), "add_cue"),
])
def test_read_back_mismatch_stops_without_undo(fake, tmp_path, fault, label):
    fault(fake)
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert (UNDO, ()) not in writes(fake) and len(prompts) == 2
    assert "UNBEKANNT" in out and "KEIN Undo" in out
    b = block(out)
    cap = dict((lbl, cap) for cap, lbl in script.CAPABILITY_STEPS)[label]
    assert b[cap] == "FAIL (read-back differs)"
    entry = [e for e in log_entries(tmp_path) if e["action"] == label][-1]
    assert entry["status"] == "read_back" and entry["ok"] is False


def wrap_handler(fake, name, after):
    real = getattr(fake, name)

    def wrapped(p):
        rv = real(p)
        if p:
            after()
        return rv

    setattr(fake, name, wrapped)


@pytest.mark.parametrize("during,last_step", [
    # Live moved the position (e.g. the user): the pre-check of the toggle refuses.
    (lambda f: setattr(f, "song_time", 0.0), "add_cue: refused"),
    # A locator appeared at the clip start: already the notes read-back differs (locators
    # are part of every comparison), so the toggle is never reached.
    (lambda f: f.cue_points.append(["user", 16.0]), "add_notes: confirmed (read-back differs"),
])
def test_cue_toggle_is_not_sent_if_position_or_locators_changed(fake, tmp_path, during,
                                                                 last_step):
    """The toggle would delete a locator at the position, or land somewhere else."""
    wrap_handler(fake, "_add_notes", lambda: during(fake))
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert TOGGLE_CUE not in [a for a, _ in writes(fake)]
    assert (UNDO, ()) not in writes(fake) and len(prompts) == 2
    assert block_list(out, "steps")[-1].startswith(last_step)
    assert "Von Hand entfernen" in out


def test_toggle_read_back_that_deleted_a_locator_is_a_failure(fake, tmp_path):
    """If Live's position were elsewhere and a locator sat there, the toggle deletes it."""
    fake.cue_points.append(["victim", 20.0])
    fake.cue_time_offset = 4.0
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED
    assert block(out)["song.cue_point.add_or_delete"] == "FAIL (read-back differs)"
    assert (UNDO, ()) not in writes(fake)


def test_playing_started_between_plan_and_confirmation(fake, tmp_path):
    def play(n, prompt):
        if "ausführen" in prompt:
            fake.is_playing = True

    code, out, _ = run(fake, tmp_path, ["y", "y"], on_prompt=play)
    assert code == script.EXIT_CHECK_FAILED
    assert writes(fake) == [] and "Live is playing" in out


def test_new_track_that_is_not_midi_fails_the_read_back(fake, tmp_path):
    wrap_handler(fake, "_create_midi_track", lambda: fake.tracks[-1].update(midi=False,
                                                                             audio=True))
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED
    assert block(out)["song.create_midi_track"] == "FAIL (read-back differs)"
    assert CREATE_CLIP not in [a for a, _ in writes(fake)]


@pytest.mark.parametrize("change", [
    lambda c: c.update(start=c["start"] + 4.0),
    lambda c: c.update(length=c["length"] / 2),
    lambda c: c["notes"].append((60, 0.0, 1.0, 64.0, False)),
])
def test_clip_not_as_requested_fails_the_read_back(fake, tmp_path, change):
    wrap_handler(fake, "_create_midi_clip", lambda: change(fake.tracks[-1]["arrangement"][0]))
    code, out, _ = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED
    assert block(out)["track.create_midi_clip"] == "FAIL (read-back differs)"
    assert ADD_NOTES not in [a for a, _ in writes(fake)]


def test_writer_refuses_a_locator_at_the_start_on_its_own(fake, transport, tmp_path):
    """Library callers other than the script get the same protection."""
    from conftest import registry_with

    from bridge.capabilities import CapabilityGate
    from bridge.clip_import import ActionLog
    from bridge.osc_client import ADDRESSES, UNREGISTERED, AbletonBridge

    b = AbletonBridge(transport, CapabilityGate(registry_with(tmp_path, set(ADDRESSES)), (),
                                                tuple(UNREGISTERED)))
    fake.cue_points = [["mine", 16.0]]
    writer = arr.ArrangementWriter(b, ActionLog(tmp_path / "a.jsonl"), timeout_s=0.3)
    state = arr.read_arrangement_state(b, len(fake.tracks))
    with pytest.raises(arr.ImportAborted, match="toggle would delete"):
        writer.run(arr.make_plan(5, 1, "x"), state)
    assert writes(fake) == [] and writer.last_outcome is None


def test_live_error_on_a_write_stops_without_undo(fake, tmp_path):
    real = fake._create_midi_clip

    def refuse(p):
        if p:
            raise RuntimeError("frozen track")
        return real(p)

    fake._create_midi_clip = refuse
    code, out, prompts = run(fake, tmp_path, ["y", "y", "y"])
    assert code == script.EXIT_CHECK_FAILED, out
    assert (UNDO, ()) not in writes(fake) and len(prompts) == 2
    assert "create_midi_clip: error (AbletonOSCError" in block_list(out, "steps")[2]
    assert "Bereits ausgeführt: set_song_time, create_midi_track" in out


# -- seeded property run over the input range ------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_random_sets_round_trip(tmp_path, seed):
    rnd = random.Random(1400 + seed)
    server = FakeAbletonOSC()
    try:
        server.tracks = [{"name": f"{i + 1}-T{rnd.randint(0, 99)}", "mute": rnd.random() < .5,
                          "audio": rnd.random() < .5} for i in range(rnd.randint(0, 6))]
        bar = rnd.choice([1, 2, rnd.randint(1, 300), rnd.randint(1, 394000)])
        bars = rnd.randint(1, 16)
        start = (bar - 1) * 4.0
        times = {rnd.choice([0, 4, 8, 400, 12.5]) * rnd.randint(0, 9) for _ in range(4)}
        server.cue_points = [[f"c{i}", float(t)] for i, t in enumerate(times) if t != start]
        rnd.shuffle(server.cue_points)
        server.song_time = rnd.choice([0.0, start, 3.5])
        server.undo_batch = rnd.choice([1, 1, 2, 5])
        before = snapshot(server)
        code, out, _ = run(server, tmp_path, ["y", "y", "y"],
                           extra=["--bar", str(bar), "--bars", str(bars)])
        assert code == 0, (seed, out)
        assert snapshot(server) == before, seed
        sent = writes(server)
        assert sent[sent.index((CREATE_TRACK, (-1,))) + 1] == (
            CREATE_CLIP, (len(before[0]), start, bars * 4.0))
    finally:
        server.close()


# -- writer invariants (white box) -----------------------------------------------------------

def test_undo_refused_for_unknown_or_unfinished_outcomes():
    plan = arr.make_plan(5, 4, "x")
    empty = arr.ArrangementState((), 0, None, (), None, (), 0.0)
    writer = arr.ArrangementWriter(bridge=None, log=None, timeout_s=0.1)  # type: ignore[arg-type]
    outcome = arr.ArrangementOutcome(plan=plan, target_index=0, before=empty)
    with pytest.raises(arr.ImportAborted, match="did not all finish"):
        writer.undo_all(outcome)
    outcome.outcome_unknown = True
    with pytest.raises(arr.ImportAborted, match="unknown outcome"):
        writer.undo_all(outcome)


def test_state_key_ignores_only_the_target_name_and_the_position():
    a = arr.ArrangementState(("A", "B"), 1, True, ((0.0, 4.0),), (), (("x", 0.0),), 0.0)
    assert a.key() == arr.ArrangementState(("A", "C"), 1, True, ((0.0, 4.0),), (),
                                           (("x", 0.0),), 9.0).key()
    for other in (arr.ArrangementState(("Z", "B"), 1, True, ((0.0, 4.0),), (), (("x", 0.0),), 0),
                  arr.ArrangementState(("A", "B"), 1, False, ((0.0, 4.0),), (), (("x", 0.0),), 0),
                  arr.ArrangementState(("A", "B"), 1, True, ((0.0, 8.0),), (), (("x", 0.0),), 0),
                  arr.ArrangementState(("A", "B"), 1, True, ((0.0, 4.0),), None, (("x", 0.0),),
                                       0),
                  arr.ArrangementState(("A", "B"), 1, True, ((0.0, 4.0),), (), (("y", 0.0),), 0),
                  arr.ArrangementState(("A", "B", "C"), 1, True, ((0.0, 4.0),), (),
                                       (("x", 0.0),), 0)):
        assert a.key() != other.key(), other


def test_plan_notes_one_per_beat_in_clip_time():
    plan = arr.make_plan(3, 2, "Intro")
    assert (plan.start, plan.length) == (8.0, 8.0)
    assert plan.notes() == tuple((36, float(b), 0.25, 100, False) for b in range(8))
