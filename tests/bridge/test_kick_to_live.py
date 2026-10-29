"""scripts/kick_to_live.py: render -> library.place_kick -> live_import flow (#129).

CI only, against the fake AbletonOSC server: nothing here talks to Ableton Live. These tests
show what the script writes to disk, sends, prints and logs; whether Live behaves like the
fake is what the user's run in #129 shows.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import random
import socket
import sys
from pathlib import Path

import pytest
from fake_abletonosc import FakeAbletonOSC

from audio_engine import cli as kick_cli
from audio_engine.presets import preset_names

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("kick_to_live", ROOT / "scripts" / "kick_to_live.py")
k2l = importlib.util.module_from_spec(spec)
sys.modules["kick_to_live"] = k2l
spec.loader.exec_module(k2l)

CREATE_CLIP = "/live/clip_slot/create_audio_clip"
CREATE_TRACK = "/live/song/create_audio_track"
UNDO = "/live/song/undo"
WRITES = (CREATE_CLIP, CREATE_TRACK, UNDO)
PROBE = (CREATE_CLIP, ())
KICKS = ("Samples", "Drums", "Kicks")  # library default layout (#64)
REAL_REFUSED_ROOTS = k2l.REFUSED_ROOTS


@pytest.fixture(autouse=True)
def repo_root_elsewhere(tmp_path, monkeypatch):
    """pytest's tmp folder lies inside the checkout (--basetemp=.pytest_tmp), which the
    script refuses as a project. Tests point the refused root elsewhere; the real roots are
    checked in test_project_inside_the_abeltongod_checkout_is_refused."""
    monkeypatch.setattr(k2l, "REFUSED_ROOTS", ((tmp_path / "not-the-repo").resolve(),))


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
        {"name": "1-Audio", "mute": False, "audio": True, "slots": ["C:\\old.wav", None,
                                                                    None, None]},
        {"name": "2-MIDI", "mute": False, "slots": [None] * 4},
    ]
    yield server
    server.close()


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "My Project"
    p.mkdir()
    (p / "My Project.als").write_bytes(b"")
    return p


def kick_dir(project: Path) -> Path:
    return project.joinpath(*KICKS)


def run(fake, tmp_path, project, answers, extra=(), preset="dense", send_port=None):
    receive = free_udp_port()
    if fake is not None:
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
    port = send_port if send_port is not None else fake.port
    try:
        code = k2l.main(
            ["--preset", preset, "--project", str(project), "--send-port", str(port),
             "--receive-port", str(receive), "--timeout", "0.3",
             "--log", str(tmp_path / "actions.jsonl"), *extra],
            input_fn=input_fn, out=out)
    except KeyboardInterrupt:  # would end the whole pytest session instead of failing
        pytest.fail("Ctrl+C escaped kick_to_live.main():\n" + out.getvalue())
    return code, out.getvalue(), prompts


def block(text: str) -> dict:
    body = text.split("```text\n", 1)[1].split("```", 1)[0]
    result = {}
    for line in body.splitlines():
        if ": " in line and not line.startswith("  "):
            k, v = line.split(": ", 1)
            assert k not in result, f"duplicate key {k}"
            result[k] = v
    return result


def writes(fake):
    return [(a, p) for a, p in fake.payload() if a in WRITES and (a, p) != PROBE]


def files(project: Path) -> list[str]:
    return sorted(str(p.relative_to(project)).replace("\\", "/")
                  for p in project.rglob("*") if p.is_file())


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cli_render(tmp_path: Path, preset: str, extra=()) -> Path:
    """Independent reference: the engine's own CLI (write_kick, no library, no bridge)."""
    out = tmp_path / "cli-ref"
    code = kick_cli.main(["--preset", preset, "--out", str(out), *extra],
                         stdout=io.StringIO(), stderr=io.StringIO())
    assert code == 0
    (wav,) = sorted(out.glob("*.wav"))
    return wav


# -- render -> place -> import -> read-back ----------------------------------------------------

def test_full_run_existing_track_with_undo(fake, tmp_path, project):
    code, out, prompts = run(fake, tmp_path, project, ["y", "0", "y", "y"])
    assert code == 0, out
    wav = kick_dir(project) / "dense_s1001_v0.wav"
    # Exactly this one absolute path went to Live, after the probe, then one undo.
    assert writes(fake) == [(CREATE_CLIP, (0, 1, str(wav))), (UNDO, ())]
    assert fake.tracks[0]["slots"] == ["C:\\old.wav", None, None, None]
    assert files(project) == ["My Project.als", "Samples/Drums/Kicks/dense_s1001_v0.json",
                              "Samples/Drums/Kicks/dense_s1001_v0.wav"]
    b = block(out)
    assert b["kick_written"] == "yes"
    assert b["kick_wav"] == str(wav) and b["wav"] == str(wav)
    assert b["kick_sidecar"] == str(wav.with_suffix(".json"))
    assert b["clip_slot.create_audio_clip"] == "PASS"
    assert b["clip_file_path_read"] == repr(str(wav))
    assert b["song.undo"] == "PASS (clip removed; read back)"
    assert b["kick_in_live"] == "removed by undo (read back)"
    assert b["preset"] == "dense" and b["seed"] == "1001" and b["custom_values"] == "-"
    assert b["live_import_version"] == "0.3.0" and b["kick_to_live_version"] == "0.1.0"
    assert b["project"] == str(project)
    assert "Issue #129" in out
    # The files stay after the undo; the script says so and where they are.
    assert wav.is_file() and "das Script löscht nichts" in out and f"    {wav}" in out
    assert "Hinweis: In" not in out  # the project has an .als file
    log = [json.loads(x) for x in (tmp_path / "actions.jsonl").read_text("utf-8").splitlines()]
    assert [e["action"] + ":" + e["status"] for e in log] == [
        "create_audio_clip:planned", "create_audio_clip:read_back",
        "undo_clip:planned", "undo_clip:read_back"]
    assert log[1]["file_path"] == str(wav) and log[1]["ok"] is True


def test_full_run_without_undo_leaves_clip_on_the_project_file(fake, tmp_path, project):
    code, out, prompts = run(fake, tmp_path, project, ["y", "0", "y", "", "y"])
    assert code == 0, out
    wav = kick_dir(project) / "dense_s1001_v0.wav"
    assert fake.tracks[0]["slots"][1] == str(wav)
    b = block(out)
    assert b["kick_in_live"] == "in Live (track 0, slot 1)"
    assert b["user_hears_kick"] == "yes"
    assert b["song.undo"] == "SKIPPED (user answered no)"
    assert "der Clip ist im Set und verweist auf die Datei unten" in out
    assert "Von Hand importieren" not in out
    assert "  - Clip: in Spur 0 '1-Audio' die Zelle 1 anklicken, Entf drücken." in out
    # live_import 0.3.0 order: undo question before the listening question
    assert [i for i, q in enumerate(prompts) if "per Undo" in q] == [3]
    assert "Spielt der Kick" in prompts[4]


def test_new_track_two_undos(fake, tmp_path, project):
    code, out, _ = run(fake, tmp_path, project, ["y", "n", "y", "y"])
    assert code == 0, out
    assert [a for a, _ in writes(fake)] == [CREATE_TRACK, CREATE_CLIP, UNDO, UNDO]
    b = block(out)
    assert b["song.undo"] == "PASS (clip removed, track removed; read back)"
    assert b["kick_in_live"] == "removed by undo (read back)"
    # Writes sent: track + clip (+ undo). An override is reported for each one that is not
    # `tested` in the committed registry (#124 changes clip_slot.create_audio_clip).
    status = {c["id"]: c["status"] for c in json.loads(
        (ROOT / "contracts" / "capabilities.json").read_text("utf-8"))["capabilities"]}
    expected = sorted(c for c in ("song.create_audio_track", "clip_slot.create_audio_clip",
                                  "song.undo") if status[c] != "tested")
    assert "song.create_audio_track" in expected
    assert b["capability_overrides_used"] == ", ".join(expected)


def test_rendered_file_equals_the_engine_cli_render(fake, tmp_path, project):
    """Same preset through the engine CLI (write_kick, no library): byte-identical WAV, same
    file name, same sidecar parameters (not compared against this script's own helpers)."""
    run(fake, tmp_path, project, ["n"])
    ref = cli_render(tmp_path, "dense")
    mine = kick_dir(project) / ref.name
    assert ref.name == "dense_s1001_v0.wav"
    assert mine.read_bytes() == ref.read_bytes()
    a = json.loads(mine.with_suffix(".json").read_text("utf-8"))
    r = json.loads(ref.with_suffix(".json").read_text("utf-8"))
    assert a["parameters"] == r["parameters"]
    assert a["parameters"]["drive"] == 0.45 and a["parameters"]["preset"] == "dense"


def test_every_preset_with_random_seed_and_set_matches_the_cli(fake, tmp_path):
    """All shipped presets, each with a seeded-random --seed and --set tone: bytes and file
    names equal the engine CLI's."""
    rng = random.Random(129)
    for i, name in enumerate(preset_names()):
        seed = rng.randrange(0, 2**31)
        tone = round(rng.uniform(-0.9, 0.9), 3)
        extra = ["--seed", str(seed), "--set", f"tone={tone}"]
        proj = tmp_path / f"p{i}"
        proj.mkdir()
        (proj / "p.als").write_bytes(b"")
        fake.received.clear()
        code, out, _ = run(fake, tmp_path, proj, [""], extra=extra, preset=name)
        assert code == 0, out
        ref = cli_render(tmp_path / f"ref{i}", name, extra)
        assert ref.name == f"{name}_s{seed}_v0_custom.wav"
        mine = kick_dir(proj) / ref.name
        assert mine.read_bytes() == ref.read_bytes(), name
        b = block(out)
        assert b["seed"] == str(seed) and b["custom_values"] == f"tone={tone}"
        assert writes(fake) == []


def test_second_run_never_overwrites(fake, tmp_path, project):
    code1, out1, _ = run(fake, tmp_path, project, ["y", "0", "y", "", "y"])
    first = kick_dir(project) / "dense_s1001_v0.wav"
    first_json = first.with_suffix(".json")
    h_wav, h_json = sha(first), sha(first_json)
    code2, out2, _ = run(fake, tmp_path, project, ["y", "0", "y", "", "y"])
    assert code1 == code2 == 0, out2
    second = kick_dir(project) / "dense_s1001_v0_002.wav"
    assert sha(first) == h_wav and sha(first_json) == h_json  # untouched
    assert second.read_bytes() == first.read_bytes()  # same params + seed, new name
    assert fake.tracks[0]["slots"][1:3] == [str(first), str(second)]  # next free slot
    assert block(out2)["kick_wav"] == str(second)
    assert block(out2)["target"] == "track 0 '1-Audio', slot 2"
    assert len(files(project)) == 5


# -- refusal paths: no clip, and the WAV location is stated ------------------------------------

def assert_no_clip_and_wav_stated(fake, out, project):
    wav = kick_dir(project) / "dense_s1001_v0.wav"
    assert writes(fake) == []
    assert wav.is_file() and wav.with_suffix(".json").is_file()
    assert f"    {wav}" in out
    assert "Live: kein Clip, in Live wurde nichts geändert." in out
    assert f'explorer "{kick_dir(project)}"' in out
    b = block(out)
    assert b["kick_in_live"] == "none (nothing sent to Live)"
    assert b["kick_written"] == "yes" and b["kick_wav"] == str(wav)


@pytest.mark.parametrize("answers, error", [
    ([], "user: not a test set"), ([""], "user: not a test set"),
    (["n"], "user: not a test set"), (["y", ""], "no target chosen"),
    (["y", "0", ""], "user answered no"), (["y", "0", "n"], "user answered no"),
    (["y", "1", "1", "1"], "no target chosen")])
def test_refusals_leave_no_clip_and_say_where_the_wav_is(fake, tmp_path, project, answers,
                                                         error):
    code, out, _ = run(fake, tmp_path, project, answers)
    assert code == 0, out
    assert_no_clip_and_wav_stated(fake, out, project)
    assert not (tmp_path / "actions.jsonl").exists()
    assert block(out)["error"] == error  # the block is the user's evidence (review R04)


@pytest.mark.parametrize("case", ["occupied", "no_free_slot", "out_of_range", "no_scene"])
def test_slot_refusals(fake, tmp_path, project, case):
    extra: tuple[str, ...] = ()
    if case == "occupied":
        extra = ("--slot", "0")
    elif case == "no_free_slot":
        fake.tracks[0]["slots"] = ["C:\\a.wav"] * 4
    elif case == "out_of_range":
        extra = ("--slot", "9")
    else:
        fake.num_scenes = 0
        for t in fake.tracks:
            t["slots"] = []
    code, out, _ = run(fake, tmp_path, project, ["y", "0"], extra=extra)
    assert code == k2l.EXIT_CHECK_FAILED, out
    assert_no_clip_and_wav_stated(fake, out, project)


def test_extension_missing(fake, tmp_path, project):
    fake.extension_installed = False
    code, out, prompts = run(fake, tmp_path, project, ["y", "0", "y"])
    assert code == k2l.EXIT_EXTENSION_MISSING and prompts == []
    assert "SAMPLE_IMPORT_FALLBACK.md" in out
    assert_no_clip_and_wav_stated(fake, out, project)


def test_live_closed(tmp_path, project):
    code, out, _ = run(None, tmp_path, project, ["y"], send_port=free_udp_port())
    assert code == k2l.EXIT_NO_CONNECTION
    assert "antwortet nicht" in out and "Es wurde nichts in Live geändert." in out
    wav = kick_dir(project) / "dense_s1001_v0.wav"
    assert wav.is_file() and f"    {wav}" in out
    assert block(out)["kick_in_live"] == "none (nothing sent to Live)"


def test_port_in_use(fake, tmp_path, project):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 0))
    try:
        out = io.StringIO()
        code = k2l.main(["--preset", "dense", "--project", str(project), "--send-port",
                         str(fake.port), "--receive-port", str(blocker.getsockname()[1]),
                         "--log", str(tmp_path / "a.jsonl")], input_fn=lambda p: "y", out=out)
    finally:
        blocker.close()
    assert code == k2l.EXIT_PORT_IN_USE
    assert_no_clip_and_wav_stated(fake, out.getvalue(), project)


# -- Ctrl+C at each prompt ---------------------------------------------------------------------

@pytest.mark.parametrize("answers, sent, in_live", [
    ([KeyboardInterrupt], [], "none (nothing sent to Live)"),                       # test set
    (["y", KeyboardInterrupt], [], "none (nothing sent to Live)"),                  # target
    (["y", "0", KeyboardInterrupt], [], "none (nothing sent to Live)"),             # plan
    (["y", "0", "y", KeyboardInterrupt], [CREATE_CLIP], "in Live (track 0, slot 1)"),  # undo
    (["y", "0", "y", "", KeyboardInterrupt], [CREATE_CLIP], "in Live (track 0, slot 1)"),
])
def test_ctrl_c_at_each_prompt(fake, tmp_path, project, answers, sent, in_live):
    code, out, prompts = run(fake, tmp_path, project, answers)
    assert code == 130, out
    assert len(prompts) == len(answers)
    assert [a for a, _ in writes(fake)] == sent  # never an undo after Ctrl+C
    wav = kick_dir(project) / "dense_s1001_v0.wav"
    assert wav.is_file() and f"    {wav}" in out
    b = block(out)
    assert b["kick_in_live"] == in_live
    assert b["kick_written"] == "yes"
    if sent:
        assert "Der Import war schon fertig; der Clip bleibt im Set." in out
        assert "  - Clip: in Spur 0 '1-Audio' die Zelle 1 anklicken, Entf drücken." in out
    else:
        assert "ABGEBROCHEN mit Strg+C. Es wurde nichts in Live geändert." in out


def test_ctrl_c_while_connecting(fake, tmp_path, project, monkeypatch):
    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(k2l.AbletonBridge, "connect", interrupted)
    try:
        code, out, _ = run(fake, tmp_path, project, ["y"])
    except KeyboardInterrupt:  # would end the whole pytest session
        pytest.fail("Ctrl+C while connecting escaped main()")
    assert code == 130
    assert "ABGEBROCHEN mit Strg+C. Es wurde nichts in Live geändert." in out
    assert fake.received == []
    assert block(out)["kick_in_live"] == "none (nothing sent to Live)"
    assert (kick_dir(project) / "dense_s1001_v0.wav").is_file()


def test_ctrl_c_while_rendering_leaves_project_as_it_was(fake, tmp_path, project, monkeypatch):
    """Ctrl+C inside write_kick: place_kick removes the folders it made; nothing is sent."""
    import library.layout as layout

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(layout, "write_kick", interrupted)
    code, out, prompts = run(fake, tmp_path, project, ["y", "0", "y"])
    assert code == 130 and prompts == []
    assert files(project) == ["My Project.als"] and not (project / "Samples").exists()
    assert fake.received == []
    b = block(out)
    assert b["kick_written"] == "no (interrupted by user, Ctrl+C)"
    assert b["kick_wav"] == "-" and b["kick_in_live"] == "none (nothing sent to Live)"
    assert "ABGEBROCHEN mit Strg+C beim Erzeugen des Kicks" in out


def test_ctrl_c_during_undo(fake, tmp_path, project, monkeypatch):
    def interrupted_undo(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(k2l.AbletonBridge, "undo", interrupted_undo)
    code, out, _ = run(fake, tmp_path, project, ["y", "0", "y", "y"])
    assert code == 130, out
    assert block(out)["kick_in_live"] == "unknown (see the messages above)"
    assert "Live: ob ein Clip im Set ist, ist UNBEKANNT. Erst in Live nachsehen" in out
    assert (kick_dir(project) / "dense_s1001_v0.wav").is_file()


# -- failures before Live and unknown outcomes -------------------------------------------------

@pytest.mark.parametrize("extra, preset", [((), "no-such-preset"),
                                           (("--set", "drive=abc"), "dense"),
                                           (("--set", "drive=7"), "dense"),
                                           (("--set", "seed=3"), "dense")])
def test_bad_kick_values_write_nothing_and_send_nothing(fake, tmp_path, project, extra,
                                                        preset):
    code, out, prompts = run(fake, tmp_path, project, ["y"], extra=extra, preset=preset)
    assert code == k2l.EXIT_SETUP_ERROR, out
    assert files(project) == ["My Project.als"] and not (project / "Samples").exists()
    assert fake.received == [] and prompts == []
    assert "Es wurde nichts geschrieben und nichts in Live geändert." in out
    assert block(out)["kick_written"].startswith("no (")


def test_missing_project_folder_is_not_created(fake, tmp_path):
    missing = tmp_path / "nope"
    code, out, _ = run(fake, tmp_path, missing, ["y"])
    assert code == k2l.EXIT_SETUP_ERROR
    assert not missing.exists() and fake.received == []
    assert f"FEHLER mit dem Projektordner: Den Ordner gibt es nicht: {missing}" in out
    assert block(out)["kick_written"] == "no (project folder refused)"


def refused_project(fake, tmp_path, raw: str, cwd: Path, monkeypatch):
    monkeypatch.chdir(cwd)
    before = files(cwd)
    code, out, prompts = run(fake, tmp_path, raw, ["y", "0", "y"])
    assert code == k2l.EXIT_SETUP_ERROR, out
    assert files(cwd) == before and not (cwd / "Samples").exists()
    assert fake.received == [] and prompts == []
    assert "FEHLER mit dem Projektordner:" in out
    assert "Es wurde nichts geschrieben und nichts in Live geändert." in out
    b = block(out)
    assert b["kick_written"] == "no (project folder refused)" and b["kick_wav"] == "-"
    return out


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_project_is_refused_not_the_current_folder(fake, tmp_path, project, raw,
                                                         monkeypatch):
    """PR #134 review, problem 3: --project "" meant the current folder (the checkout)."""
    (project / "x.als").write_bytes(b"")  # even a cwd that looks like a project
    out = refused_project(fake, tmp_path, raw, project, monkeypatch)
    assert "--project ist leer" in out


def test_relative_project_is_refused(fake, tmp_path, project, monkeypatch):
    out = refused_project(fake, tmp_path, "My Project", tmp_path, monkeypatch)
    assert "--project muss ein voller Pfad sein" in out


def test_project_that_is_a_file_is_refused(fake, tmp_path, project, monkeypatch):
    f = project / "My Project.als"
    out = refused_project(fake, tmp_path, str(f), tmp_path, monkeypatch)
    assert f"Den Ordner gibt es nicht: {f}" in out


def test_project_without_als_is_refused(fake, tmp_path, monkeypatch):
    p = tmp_path / "plain"
    p.mkdir()
    (p / "x.als.txt").write_bytes(b"")
    (p / "sub.als").mkdir()  # a folder named *.als is not a set
    out = refused_project(fake, tmp_path, str(p), p, monkeypatch)
    assert f"In {p} liegt keine .als-Datei" in out
    assert "Datei -> Live-Set speichern unter" in out


def test_als_suffix_case_does_not_matter(fake, tmp_path):
    p = tmp_path / "Upper Project"
    p.mkdir()
    (p / "SET.ALS").write_bytes(b"")
    code, out, _ = run(fake, tmp_path, p, [""])
    assert code == 0, out
    assert (kick_dir(p) / "dense_s1001_v0.wav").is_file()


@pytest.mark.parametrize("name", ["Backup", "backup"])
def test_live_backup_folder_is_refused(fake, tmp_path, project, name, monkeypatch):
    backup = project / name
    backup.mkdir()
    (backup / "My Project [2026-10-29 120000].als").write_bytes(b"")
    out = refused_project(fake, tmp_path, str(backup), tmp_path, monkeypatch)
    assert "ist Lives Backup-Ordner" in out


@pytest.mark.parametrize("sub", ["", "docs", "tests/bridge"])
def test_project_inside_the_abeltongod_checkout_is_refused(fake, tmp_path, sub, monkeypatch):
    """The real refused roots (no fixture override) contain this checkout; the check comes
    before the .als check, so the message names the checkout."""
    monkeypatch.setattr(k2l, "REFUSED_ROOTS", REAL_REFUSED_ROOTS)
    assert ROOT.resolve() in REAL_REFUSED_ROOTS
    target = ROOT / sub if sub else ROOT
    before = files(target) if sub else None
    code, out, _ = run(fake, tmp_path, target, ["y"])
    assert code == k2l.EXIT_SETUP_ERROR, out
    assert "liegt im AbeltonGod-Ordner" in out and fake.received == []
    assert not (target / "Samples").exists()
    if sub:
        assert files(target) == before


def test_too_long_project_path_is_refused_before_writing(fake, tmp_path):
    deep = tmp_path / ("x" * 200) / ("y" * 40)
    deep.mkdir(parents=True)
    (deep / "s.als").write_bytes(b"")
    code, out, _ = run(fake, tmp_path, deep, ["y"])
    assert code == k2l.EXIT_SETUP_ERROR, out
    assert not (deep / "Samples").exists() and fake.received == []
    assert "MAX_PATH" in out


def test_write_failure(fake, tmp_path, project, monkeypatch):
    import library.layout as layout

    def disk_full(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(layout, "write_kick", disk_full)
    code, out, _ = run(fake, tmp_path, project, ["y"])
    assert code == k2l.EXIT_WRITE_FAILED
    assert files(project) == ["My Project.als"] and fake.received == []
    assert "No space left on device" in block(out)["kick_written"]


def test_only_a_file_in_the_project_kick_folder_goes_to_live(fake, tmp_path, project,
                                                             monkeypatch):
    """Guard against a placement that returned a path outside the kick folder: the import
    refuses before connecting (validate_wav_path with library_root)."""
    outside = tmp_path / "outside.wav"
    real_place = k2l.place_kick

    def misplaced(params, project_dir, **kw):
        outside.write_bytes(real_place(params, project_dir, **kw).read_bytes())
        return outside

    monkeypatch.setattr(k2l, "place_kick", misplaced)
    code, out, _ = run(fake, tmp_path, project, ["y", "0", "y"])
    assert code == k2l.EXIT_SETUP_ERROR, out
    assert "outside the sample library" in out
    assert fake.received == []


def test_ctrl_c_after_clip_confirmed_before_step_recorded_is_unknown(fake, tmp_path, project,
                                                                     monkeypatch):
    """PR #134 review, problem 1 (probe rv134/window.py): AbletonOSC confirmed the clip, the
    Ctrl+C lands before ClipImporter records the step. The clip IS in the fake; the script
    must say unknown, never "nothing changed"."""
    import bridge.clip_import as ci

    real_step = ci.Step

    def step(label, outcome, detail=""):
        if label == "create_audio_clip" and outcome == "confirmed":
            raise KeyboardInterrupt
        return real_step(label, outcome, detail)

    monkeypatch.setattr(ci, "Step", step)
    code, out, _ = run(fake, tmp_path, project, ["y", "0", "y"])
    assert code == 130, out
    wav = kick_dir(project) / "dense_s1001_v0.wav"
    assert fake.tracks[0]["slots"][1] == str(wav)  # the clip is there
    assert "Ob schon etwas gesendet wurde oder noch im Set ist, ist unbekannt." in out
    assert "nichts in Live geändert" not in out and "kein Clip" not in out
    b = block(out)
    assert b["kick_in_live"] == "unknown (see the messages above)"
    assert b["error"] == "interrupted by user (Ctrl+C) outside a write"
    assert UNDO not in [a for a, _ in writes(fake)]


@pytest.mark.parametrize("undo, text, in_live", [
    ("", "Der Import war schon fertig; der Clip bleibt im Set.", "in Live (track 0, slot 1)"),
    ("y", "Der Import war schon per Undo zurückgenommen (zurückgelesen).",
     "removed by undo (read back)")])
def test_ctrl_c_right_after_the_import_flow(fake, tmp_path, project, monkeypatch, undo, text,
                                            in_live):
    """PR #134 review, problem 2 (probe rv134/outer.py): Ctrl+C in split_overrides, after
    run() returned. The message follows the importer's record."""
    def interrupted(report, used):
        raise KeyboardInterrupt

    monkeypatch.setattr(k2l.live_import, "split_overrides", interrupted)
    code, out, _ = run(fake, tmp_path, project, ["y", "0", "y", undo, "y"])
    assert code == 130, out
    assert "ABGEBROCHEN mit Strg+C. " + text in out
    assert "Es wurde nichts in Live geändert." not in out
    b = block(out)
    assert b["kick_in_live"] == in_live
    assert b["error"] == "interrupted by user (Ctrl+C) after the import flow"


def test_ctrl_c_between_render_and_import(fake, tmp_path, project, monkeypatch):
    """Ctrl+C after make_kick returned, before import_kick's own handlers: block and WAV."""
    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(k2l, "ActionLog", interrupted)
    code, out, _ = run(fake, tmp_path, project, ["y"])
    assert code == 130 and fake.received == []
    wav = kick_dir(project) / "dense_s1001_v0.wav"
    assert "ABGEBROCHEN mit Strg+C. Es wurde nichts in Live geändert." in out
    assert f"Kick-Datei (bleibt im Projektordner):\n  {wav}" in out and wav.is_file()
    b = block(out)
    assert b["error"] == "interrupted by user (Ctrl+C) between steps"
    assert b["kick_in_live"] == "none (nothing sent to Live)" and b["kick_wav"] == str(wav)


def test_ctrl_c_while_printing_the_summary_still_gives_the_block(fake, tmp_path, project,
                                                                 monkeypatch):
    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(k2l, "summary_text", interrupted)
    code, out, _ = run(fake, tmp_path, project, ["y", "0", "y", "", "y"])
    assert code == 130
    wav = kick_dir(project) / "dense_s1001_v0.wav"
    assert "Der Import war schon fertig; der Clip bleibt im Set." in out
    assert f"  {wav}" in out
    assert block(out)["kick_in_live"] == "in Live (track 0, slot 1)"


def test_ctrl_c_right_after_place_kick_returned(fake, tmp_path, project, monkeypatch):
    """The pair is complete: say so, keep it, send nothing."""
    calls = []
    real = k2l.sidecar_path

    def first_call_interrupted(wav):
        calls.append(wav)
        if len(calls) == 1:
            raise KeyboardInterrupt
        return real(wav)

    monkeypatch.setattr(k2l, "sidecar_path", first_call_interrupted)
    code, out, prompts = run(fake, tmp_path, project, ["y"])
    wav = kick_dir(project) / "dense_s1001_v0.wav"
    assert code == 130 and prompts == [] and fake.received == []
    assert wav.is_file() and wav.with_suffix(".json").is_file()
    assert f"Der Kick war schon geschrieben:\n  {wav}" in out
    b = block(out)
    assert b["kick_written"] == "yes" and b["kick_wav"] == str(wav)


def test_connection_lost_after_the_plan_was_confirmed(fake, tmp_path, project):
    """Fake stops answering right after "ausführen? y": BridgeTimeoutError inside the import
    pre-check. Not "nothing changed": the user is told to look (review R10)."""
    answers = iter(["y", "0"])

    def input_fn(prompt):
        a = next(answers, None)
        if a is not None:
            return a
        fake.hold()  # Live stops answering after the confirmation
        return "y"

    receive = free_udp_port()
    fake.response_port = receive
    out = io.StringIO()
    try:
        code = k2l.main(["--preset", "dense", "--project", str(project), "--send-port",
                         str(fake.port), "--receive-port", str(receive), "--timeout", "0.3",
                         "--log", str(tmp_path / "a.jsonl")], input_fn=input_fn, out=out)
    finally:
        fake.release()
    text = out.getvalue()
    assert code == k2l.EXIT_NO_CONNECTION, text
    assert "Bitte in Live nachsehen, was schon ausgeführt wurde." in text
    assert "Es wurde nichts in Live geändert." not in text
    b = block(text)
    assert b["kick_in_live"] == "unknown (see the messages above)"
    assert b["error"].startswith("BridgeTimeoutError")
    assert writes(fake) == []


def test_bridge_is_closed_once(fake, tmp_path, project, monkeypatch):
    closed = []
    real_close = k2l.AbletonBridge.close

    def close(self):
        closed.append(self)
        real_close(self)

    monkeypatch.setattr(k2l.AbletonBridge, "close", close)
    code, out, _ = run(fake, tmp_path, project, ["y", "0", "y", "y"])
    assert code == 0, out
    assert len(closed) == 1


def test_timed_out_import_is_unknown_and_never_undone(fake, tmp_path, project):
    orig = fake._create_audio_clip

    def blocked(p):
        if not p:
            return orig(p)
        fake._held = []
        fake.released.clear()
        fake.release_after(0.45)
        orig(p)

    fake._create_audio_clip = blocked
    code, out, prompts = run(fake, tmp_path, project, ["y", "0", "y", "y", "y"])
    assert code == 1, out
    assert UNDO not in [a for a, _ in writes(fake)]
    assert block(out)["kick_in_live"] == "unknown (see the messages above)"
    assert (kick_dir(project) / "dense_s1001_v0.wav").is_file()
    assert f'explorer "{kick_dir(project)}"' in out


def test_refused_undo_is_unknown(fake, tmp_path, project):
    answers = iter(["y", "0", "y"])

    def changing(prompt):
        a = next(answers, None)
        if a is not None:
            return a
        fake.tracks[0]["slots"][3] = "C:\\user.wav"  # the user changed the set
        return "y"

    receive = free_udp_port()
    fake.response_port = receive
    out = io.StringIO()
    code = k2l.main(["--preset", "dense", "--project", str(project), "--send-port",
                     str(fake.port), "--receive-port", str(receive), "--timeout", "0.3",
                     "--log", str(tmp_path / "a.jsonl")], input_fn=changing, out=out)
    text = out.getvalue()
    assert code == 1, text
    assert UNDO not in [a for a, _ in writes(fake)]
    assert "darum wurde KEIN Undo gesendet." in text
    assert block(text)["kick_in_live"] == "unknown (see the messages above)"


def test_undo_keeps_live_rename_is_partial(fake, tmp_path, project):
    fake.tracks[0]["slots"] = [None] * 4
    fake.rename_on_clip = "1-dense_s1001_v0"
    fake.undo_reverts_rename = False
    code, out, _ = run(fake, tmp_path, project, ["y", "0", "y", "y"])
    assert code == 1, out
    b = block(out)
    assert b["song.undo"].startswith("PARTIAL")
    assert b["kick_in_live"] == "removed by undo (read back; track names not restored)"


def test_non_ascii_project_path(fake, tmp_path):
    p = tmp_path / "Projekt Ä 東京"
    p.mkdir()
    (p / "x.als").write_bytes(b"")
    code, out, _ = run(fake, tmp_path, p, ["y", "0", "y", "", ""])
    assert code == 0, out
    assert fake.tracks[0]["slots"][1] == str(kick_dir(p) / "dense_s1001_v0.wav")
