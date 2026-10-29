"""Installer 0.2.0: the second pinned file ``abletonosc/track.py`` (#140).

AbletonOSC itself is not in this repo. A stand-in with the same anchors and the same
``create_track_callback`` logic as track.py lines 11-30 at commit 0ca68214 is patched, then
executed with a fake OSC server, fake Live objects and a fake ``Live`` module, so the inserted
handler code really runs here. The patch on the REAL files was checked by hand (hashes in
``test_pinned_hashes_checked_by_hand``; the real files were parsed, not executed).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("install_ext_track",
                                              ROOT / "scripts" / "install_abletonosc_extension.py")
inst = importlib.util.module_from_spec(spec)
sys.modules["install_ext_track"] = inst
spec.loader.exec_module(inst)

CLIP_SLOT = (
    b"class ClipSlotHandler:\n"
    b"    def init_api(self):\n"
    b"        methods = [\n"
    b'            "fire",\n'
    b'            "delete_clip"\n'
    b"        ]\n"
    b"        self.methods = methods\n"
)

# Stand-in for track.py: lines 1, 10-35, 62-64, 105-109 of the real file, verbatim in what
# matters (the callback logic and both anchors).
TRACK = b'''from typing import Tuple, Any, Callable, Optional


class TrackHandler:
    def __init__(self, song, osc_server):
        self.song = song
        self.osc_server = osc_server

    def _call_method(self, target, method, params=()):
        getattr(target, method)(*params)

    def init_api(self):
        def create_track_callback(func: Callable,
                                  *args,
                                  include_track_id: bool = False):
            def track_callback(params: Tuple[Any]):
                if params[0] == "*":
                    track_indices = list(range(len(self.song.tracks)))
                else:
                    track_indices = [int(params[0])]

                for track_index in track_indices:
                    track = self.song.tracks[track_index]
                    if include_track_id:
                        rv = func(track, *args, tuple([track_index] + params[1:]))
                    else:
                        rv = func(track, *args, tuple(params[1:]))

                    if rv is not None:
                        return (track_index, *rv)

            return track_callback

        methods = [
            "delete_device",
            "stop_all_clips"
        ]

        for method in methods:
            self.osc_server.add_handler("/live/track/%s" % method,
                                        create_track_callback(self._call_method, method))

        def track_delete_clip(track, params: Tuple[Any]):
            clip_index, = params
            track.clip_slots[clip_index].delete_clip()

''' + (b'        self.osc_server.add_handler("/live/track/delete_clip", '
       b'create_track_callback(track_delete_clip))\n')  # track.py line 109, one line

CLIP_SHA = hashlib.sha256(CLIP_SLOT).hexdigest()
TRACK_SHA = hashlib.sha256(TRACK).hexdigest()


def specs():
    a, b = inst.PATCHES
    return (inst.PatchSpec(a.relative, CLIP_SHA, a.replacements, a.summary),
            inst.PatchSpec(b.relative, TRACK_SHA, b.replacements, b.summary))


@pytest.fixture
def osc(tmp_path):
    root = tmp_path / "AbletonOSC"
    (root / "abletonosc").mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (root / "abletonosc" / "clip_slot.py").write_bytes(CLIP_SLOT)
    (root / "abletonosc" / "track.py").write_bytes(TRACK)
    return root


def run(osc, answers=("y",), uninstall=False, check=False):
    q = list(answers)

    def input_fn(prompt):
        if not q:
            raise EOFError
        a = q.pop(0)
        if a is KeyboardInterrupt:
            raise KeyboardInterrupt
        return a

    out = io.StringIO()
    code = inst.run(osc, uninstall=uninstall, check_only=check, input_fn=input_fn, out=out,
                    specs=specs())
    return code, out.getvalue()


def clip(osc):
    return osc / "abletonosc" / "clip_slot.py"


def track(osc):
    return osc / "abletonosc" / "track.py"


def backup(path):
    return path.with_name(path.name + ".abeltongod-orig")


def no_tmp(osc):
    return [p for p in os.listdir(osc / "abletonosc") if p.endswith(".tmp")] == []


# -- pinned facts ----------------------------------------------------------------------------

def test_pinned_hashes_checked_by_hand():
    """Computed 2026-10-29 from raw.githubusercontent.com at 0ca68214 (files parsed with
    ast/compile, not executed): track.py 15550 bytes; patched clip_slot.py equals the output
    of script 0.1.0 byte for byte (sha 7ff30f46...), patched track.py sha 9518ac70...."""
    assert inst.TRACK_KNOWN_ORIGINAL_SHA256 == (
        "512a92ff0a08c7ba8276c3b5f06fbff3f55863b18a51bef3ee0837eceb55ed4a")
    assert inst.KNOWN_ORIGINAL_SHA256 == (
        "989f9f6a6631fd04598fff0b278b9d844e03b3e211ae9b23d293e985b22d4aed")
    assert [str(p.relative).replace("\\", "/") for p in inst.PATCHES] == [
        "abletonosc/clip_slot.py", "abletonosc/track.py"]
    assert inst.SCRIPT_VERSION == "0.2.0"


def test_clip_slot_patch_text_is_unchanged_from_0_1_0():
    """An install made by script 0.1.0 must classify as patched (the user has one, #50)."""
    old_patched = CLIP_SLOT.replace(
        b'            "delete_clip"\n        ]\n',
        b'            "delete_clip",\n'
        b'            "create_audio_clip"  # added by AbeltonGod (#50)\n'
        b'        ]\n')
    assert inst.classify_spec(old_patched, specs()[0]) == inst.STATE_PATCHED


# -- the inserted code runs ------------------------------------------------------------------

class FakeSpec:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__dict__.update(kwargs)


class FakeClip:
    def __init__(self):
        self.notes = []
        self.ranges = []

    def add_new_notes(self, notes):
        assert isinstance(notes, tuple)
        self.notes += list(notes)

    def get_notes_extended(self, *rng):
        self.ranges.append(rng)
        return list(self.notes)


class FakeTrack:
    def __init__(self):
        self.arrangement_clips = []
        self.calls = []

    def create_midi_clip(self, start, length):
        self.calls.append((start, length))
        self.arrangement_clips.append(FakeClip())
        return self.arrangement_clips[-1]


@pytest.fixture
def handlers(monkeypatch):
    live = types.ModuleType("Live")
    live.Clip = types.SimpleNamespace(MidiNoteSpecification=FakeSpec)
    monkeypatch.setitem(sys.modules, "Live", live)
    patched = inst.apply_patch(TRACK, specs()[1].replacements)
    ns: dict = {}
    exec(compile(patched, "track.py", "exec"), ns)
    registered = {}
    server = types.SimpleNamespace(add_handler=lambda a, cb: registered.__setitem__(a, cb))
    tracks = [FakeTrack(), FakeTrack()]
    ns["TrackHandler"](types.SimpleNamespace(tracks=tracks), server).init_api()
    return registered, tracks


def test_patched_track_registers_the_three_addresses(handlers):
    registered, _ = handlers
    assert {"/live/track/create_midi_clip", "/live/track/arrangement_clip/add/notes",
            "/live/track/arrangement_clip/get/notes"} <= set(registered)
    assert "/live/track/delete_clip" in registered  # the anchor line still works


@pytest.mark.parametrize("address", ["/live/track/create_midi_clip",
                                     "/live/track/arrangement_clip/add/notes",
                                     "/live/track/arrangement_clip/get/notes"])
def test_probe_without_arguments_fails_before_touching_a_track(handlers, address):
    """The bridge's probe sends no arguments; AbletonOSC passes message.params, a list."""
    registered, tracks = handlers
    with pytest.raises(IndexError, match="list index out of range"):
        registered[address]([])
    assert all(t.calls == [] and t.arrangement_clips == [] for t in tracks)


def test_create_add_get_round_trip_through_track_callback(handlers):
    registered, tracks = handlers
    assert registered["/live/track/create_midi_clip"]([1, 16.0, 8.0]) is None  # no reply
    assert tracks[1].calls == [(16.0, 8.0)] and tracks[0].calls == []
    rv = registered["/live/track/arrangement_clip/add/notes"](
        [1, 0, 36, 0.0, 0.25, 100, 0, 38, 1.5, 0.5, 90, 1])
    assert rv is None
    specs_made = tracks[1].arrangement_clips[0].notes
    assert [s.kwargs for s in specs_made] == [
        {"start_time": 0.0, "duration": 0.25, "pitch": 36, "velocity": 100.0, "mute": False},
        {"start_time": 1.5, "duration": 0.5, "pitch": 38, "velocity": 90.0, "mute": True}]
    assert [type(v) for v in specs_made[0].kwargs.values()] == [float, float, int, float, bool]
    rv = registered["/live/track/arrangement_clip/get/notes"]([1, 0])
    assert rv == (1, 0, 36, 0.0, 0.25, 100.0, False, 38, 1.5, 0.5, 90.0, True)
    assert tracks[1].arrangement_clips[0].ranges == [(0, 127, -8192, 16384)]


@pytest.mark.parametrize("params", [[0, 0], [0, 0, 36, 0.0, 0.25, 100],
                                    [0, 0, 36, 0.0, 0.25, 100, 0, 1]])
def test_add_notes_refuses_incomplete_groups_without_writing(handlers, params):
    registered, tracks = handlers
    registered["/live/track/create_midi_clip"]([0, 0.0, 4.0])
    with pytest.raises(ValueError, match="groups of 5"):
        registered["/live/track/arrangement_clip/add/notes"](params)
    assert tracks[0].arrangement_clips[0].notes == []


def test_get_notes_of_a_missing_clip_is_an_error(handlers):
    registered, _ = handlers
    with pytest.raises(IndexError):
        registered["/live/track/arrangement_clip/get/notes"]([0, 0])


# -- two files: install / uninstall ----------------------------------------------------------

def test_install_both_then_uninstall_restores_both_exactly(osc):
    code, out = run(osc)
    assert code == 0, out
    assert backup(clip(osc)).read_bytes() == CLIP_SLOT
    assert backup(track(osc)).read_bytes() == TRACK
    assert b"create_midi_clip" in track(osc).read_bytes()
    assert b"create_audio_clip" in clip(osc).read_bytes()
    code, out = run(osc, check=True)
    assert code == 0 and out.count("Zustand: patched") == 2
    code, out = run(osc)
    assert code == 0 and "schon installiert" in out
    code, out = run(osc, uninstall=True)
    assert code == 0, out
    assert clip(osc).read_bytes() == CLIP_SLOT and track(osc).read_bytes() == TRACK
    assert no_tmp(osc)


def test_existing_0_1_0_install_gets_only_track_patched(osc):
    """The user's state since #50: clip_slot.py patched by 0.1.0, track.py original."""
    assert run(osc, answers=["y"])[0] == 0
    track(osc).write_bytes(TRACK)
    backup(track(osc)).unlink()
    clip_bytes, clip_backup = clip(osc).read_bytes(), backup(clip(osc)).read_bytes()
    code, out = run(osc)
    assert code == 0, out
    assert "clip_slot.py: schon installiert, bleibt unverändert" in out
    assert clip(osc).read_bytes() == clip_bytes and backup(clip(osc)).read_bytes() == clip_backup
    assert backup(track(osc)).read_bytes() == TRACK
    assert "Installiert: track.py." in out


@pytest.mark.parametrize("which", ["clip", "track"])
def test_one_unknown_file_blocks_both(osc, which):
    path = clip(osc) if which == "clip" else track(osc)
    changed = path.read_bytes() + b"# local edit\n"
    path.write_bytes(changed)
    code, out = run(osc)
    assert code == inst.EXIT_REFUSED and "unbekannt" in out and "Issue #140" in out
    assert path.read_bytes() == changed
    other = track(osc) if which == "clip" else clip(osc)
    assert other.read_bytes() == (TRACK if which == "clip" else CLIP_SLOT)
    assert not backup(clip(osc)).exists() and not backup(track(osc)).exists()


def test_missing_track_file_blocks_both(osc):
    track(osc).unlink()
    code, out = run(osc)
    assert code == inst.EXIT_REFUSED and "track.py fehlt" in out
    assert clip(osc).read_bytes() == CLIP_SLOT and not backup(clip(osc)).exists()


def test_foreign_track_backup_blocks_both_before_any_write(osc):
    backup(track(osc)).write_bytes(b"older")
    code, out = run(osc)
    assert code == inst.EXIT_REFUSED and "NICHT das Original" in out
    assert clip(osc).read_bytes() == CLIP_SLOT and not backup(clip(osc)).exists()
    assert backup(track(osc)).read_bytes() == b"older"


def test_write_failure_on_second_file_leaves_first_patched_and_rerun_completes(osc, monkeypatch):
    real = inst.atomic_write

    def fail_track(path, data):
        if path.name == "track.py":
            raise OSError(28, "No space left on device")
        real(path, data)

    monkeypatch.setattr(inst, "atomic_write", fail_track)
    code, out = run(osc)
    assert code == inst.EXIT_ERROR
    assert "track.py" in out and "Schon installiert in diesem Lauf: clip_slot.py" in out
    assert track(osc).read_bytes() == TRACK
    assert b"create_audio_clip" in clip(osc).read_bytes()
    assert backup(track(osc)).read_bytes() == TRACK  # backup written before the failed patch
    monkeypatch.setattr(inst, "atomic_write", real)
    code, out = run(osc, check=True)
    assert "Zustand: patched" in out and "Zustand: original" in out
    code, out = run(osc)
    assert code == 0, out
    assert b"create_midi_clip" in track(osc).read_bytes()
    assert run(osc, uninstall=True)[0] == 0
    assert clip(osc).read_bytes() == CLIP_SLOT and track(osc).read_bytes() == TRACK


def test_ctrl_c_between_the_two_files_leaves_a_consistent_state(osc, monkeypatch):
    real = inst.atomic_write

    def interrupt_track(path, data):
        if path.name == "track.py.abeltongod-orig":
            raise KeyboardInterrupt
        real(path, data)

    monkeypatch.setattr(inst, "atomic_write", interrupt_track)
    monkeypatch.setattr(inst, "PATCHES", specs())
    out = io.StringIO()
    code = inst.main(["--abletonosc-dir", str(osc)], input_fn=lambda p: "y", out=out)
    assert code == inst.EXIT_INTERRUPTED and "Strg+C" in out.getvalue()
    assert b"create_audio_clip" in clip(osc).read_bytes()
    assert track(osc).read_bytes() == TRACK and not backup(track(osc)).exists()
    assert no_tmp(osc)
    monkeypatch.setattr(inst, "atomic_write", real)
    assert inst.main(["--abletonosc-dir", str(osc)], input_fn=lambda p: "y",
                     out=io.StringIO()) == 0
    assert b"create_midi_clip" in track(osc).read_bytes()


@pytest.mark.parametrize("answer", ["", "n", EOFError, KeyboardInterrupt])
def test_no_at_the_prompt_changes_nothing(osc, monkeypatch, answer):
    monkeypatch.setattr(inst, "PATCHES", specs())

    def input_fn(prompt):
        assert "Live ist geschlossen" in prompt
        if isinstance(answer, type):
            raise answer
        return answer

    out = io.StringIO()
    code = inst.main(["--abletonosc-dir", str(osc)], input_fn=input_fn, out=out)
    assert code == (inst.EXIT_INTERRUPTED if answer is KeyboardInterrupt else inst.EXIT_REFUSED)
    assert clip(osc).read_bytes() == CLIP_SLOT and track(osc).read_bytes() == TRACK
    assert sorted(os.listdir(osc / "abletonosc")) == ["clip_slot.py", "track.py"]


def test_uninstall_with_one_invalid_backup_changes_nothing(osc):
    assert run(osc)[0] == 0
    backup(track(osc)).write_bytes(b"garbage")
    before = (clip(osc).read_bytes(), track(osc).read_bytes())
    code, out = run(osc, uninstall=True)
    assert code == inst.EXIT_REFUSED and "Keine gültige Sicherung track.py" in out
    assert (clip(osc).read_bytes(), track(osc).read_bytes()) == before


def test_uninstall_of_a_partial_install_restores_only_the_patched_file(osc, monkeypatch):
    real = inst.atomic_write
    monkeypatch.setattr(inst, "atomic_write", lambda p, d: (_ for _ in ()).throw(OSError("x"))
                        if p.name == "track.py.abeltongod-orig" else real(p, d))
    assert run(osc)[0] == inst.EXIT_ERROR
    monkeypatch.setattr(inst, "atomic_write", real)
    code, out = run(osc, uninstall=True)
    assert code == 0 and "Deinstalliert: clip_slot.py" in out
    assert clip(osc).read_bytes() == CLIP_SLOT and track(osc).read_bytes() == TRACK


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"], ids=["LF", "CRLF"])
def test_line_endings_kept_by_backup_and_uninstall(osc, eol):
    raw = TRACK.replace(b"\n", eol)
    track(osc).write_bytes(raw)
    assert run(osc)[0] == 0
    assert backup(track(osc)).read_bytes() == raw
    assert run(osc, uninstall=True)[0] == 0
    assert track(osc).read_bytes() == raw


def test_patched_track_with_a_foreign_edit_is_unknown(osc):
    assert run(osc)[0] == 0
    data = track(osc).read_bytes().replace(b'"delete_device",', b'"delete_device", "x",')
    track(osc).write_bytes(data)
    code, out = run(osc, check=True)
    assert code == inst.EXIT_REFUSED and "Zustand: unknown" in out
    code, out = run(osc, uninstall=True)
    assert code == inst.EXIT_REFUSED and track(osc).read_bytes() == data


@pytest.mark.parametrize("mangle", ["only_methods", "only_handlers", "handlers_twice"])
def test_half_or_double_patched_track_is_unknown(mangle):
    spec_ = specs()[1]
    (m_old, m_new), (a_old, a_new) = spec_.replacements
    if mangle == "only_methods":
        data = TRACK.decode().replace(m_old, m_new)
    elif mangle == "only_handlers":
        data = TRACK.decode().replace(a_old, a_new)
    else:
        data = TRACK.decode().replace(m_old, m_new).replace(a_old, a_new + inst.TRACK_NOTE_HANDLERS)
    assert inst.classify_spec(data.encode(), spec_) == inst.STATE_UNKNOWN


def test_patched_track_compiles_and_classifies(osc):
    patched = inst.apply_patch(TRACK, specs()[1].replacements)
    compile(patched, "track.py", "exec")
    assert inst.classify_spec(patched, specs()[1]) == inst.STATE_PATCHED
    assert inst.classify_spec(patched.replace(b"\n", b"\r\n"), specs()[1]) == inst.STATE_PATCHED
    with pytest.raises(ValueError, match="exactly once"):
        inst.apply_patch(TRACK + TRACK, specs()[1].replacements)
