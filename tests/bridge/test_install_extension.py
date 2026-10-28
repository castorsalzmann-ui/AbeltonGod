"""scripts/install_abletonosc_extension.py on a synthetic AbletonOSC folder (#50).

The real ``clip_slot.py`` of AbletonOSC is not in this repo (licence note in the research
note: used as an external dependency, not copied). The tests build a stand-in with the same
methods-list ending and pass its hash as ``known_original``; the pinned hash itself was
checked by hand against commit 0ca68214 (see the PR).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("install_ext",
                                              ROOT / "scripts" / "install_abletonosc_extension.py")
inst = importlib.util.module_from_spec(spec)
sys.modules["install_ext"] = inst
spec.loader.exec_module(inst)

ORIGINAL = (
    b"class ClipSlotHandler:\n"
    b"    def init_api(self):\n"
    b"        methods = [\n"
    b'            "fire",\n'
    b'            "stop",\n'
    b'            "create_clip",\n'
    b'            "delete_clip"\n'
    b"        ]\n"
    b"        self.methods = methods\n"
)
SHA = hashlib.sha256(ORIGINAL).hexdigest()


@pytest.fixture
def osc(tmp_path):
    root = tmp_path / "AbletonOSC"
    (root / "abletonosc").mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (root / "abletonosc" / "clip_slot.py").write_bytes(ORIGINAL)
    return root


def run(osc, answers=("y",), uninstall=False, check=False, known=SHA):
    q = list(answers)
    out = io.StringIO()
    code = inst.run(osc, uninstall=uninstall, check_only=check,
                    input_fn=lambda p: q.pop(0) if q else (_ for _ in ()).throw(EOFError()),
                    out=out, known_original=known)
    return code, out.getvalue()


def target(osc):
    return osc / "abletonosc" / "clip_slot.py"


def methods_of(data: bytes) -> list[str]:
    ns: dict = {}
    exec(compile(data, "clip_slot", "exec"), ns)
    obj = ns["ClipSlotHandler"]()
    obj.init_api()
    return obj.methods


def test_pinned_hash_is_the_one_checked_by_hand():
    assert inst.KNOWN_ORIGINAL_SHA256 == (
        "989f9f6a6631fd04598fff0b278b9d844e03b3e211ae9b23d293e985b22d4aed")
    assert inst.PINNED_COMMIT.startswith("0ca68214")


def test_install_then_uninstall(osc):
    code, out = run(osc)
    assert code == 0, out
    new = target(osc).read_bytes()
    assert methods_of(new) == ["fire", "stop", "create_clip", "delete_clip",
                               "create_audio_clip"]
    assert (target(osc).with_name("clip_slot.py.abeltongod-orig")).read_bytes() == ORIGINAL
    code, out = run(osc, check=True)
    assert code == 0 and "Zustand: patched" in out
    code, out = run(osc)
    assert code == 0 and "schon installiert" in out
    code, out = run(osc, uninstall=True)
    assert code == 0, out
    assert target(osc).read_bytes() == ORIGINAL


def test_crlf_original_is_recognised(osc):
    target(osc).write_bytes(ORIGINAL.replace(b"\n", b"\r\n"))
    code, out = run(osc)
    assert code == 0, out
    assert "create_audio_clip" in methods_of(target(osc).read_bytes())


@pytest.mark.parametrize("answer", ["", "n", "nein"])
def test_default_no_changes_nothing(osc, answer):
    code, out = run(osc, answers=[answer])
    assert code == inst.EXIT_REFUSED
    assert target(osc).read_bytes() == ORIGINAL
    assert not target(osc).with_name("clip_slot.py.abeltongod-orig").exists()


def test_eof_changes_nothing(osc):
    code, _ = run(osc, answers=[])
    assert code == inst.EXIT_REFUSED and target(osc).read_bytes() == ORIGINAL


def test_unknown_version_is_refused(osc):
    changed = ORIGINAL.replace(b'"stop",', b'"stop", "x",')
    target(osc).write_bytes(changed)
    code, out = run(osc)
    assert code == inst.EXIT_REFUSED and "unbekannt" in out
    assert target(osc).read_bytes() == changed


def test_missing_folder_and_file(tmp_path, osc):
    code, out = run(tmp_path / "nothing")
    assert code == inst.EXIT_REFUSED and "__init__.py" in out
    target(osc).unlink()
    code, out = run(osc)
    assert code == inst.EXIT_REFUSED and "fehlt" in out


def test_existing_backup_is_never_overwritten(osc):
    backup = target(osc).with_name("clip_slot.py.abeltongod-orig")
    backup.write_bytes(b"older backup")
    code, _ = run(osc)
    assert code == 0
    assert backup.read_bytes() == b"older backup"


def test_uninstall_without_valid_backup_refuses(osc):
    run(osc)
    backup = target(osc).with_name("clip_slot.py.abeltongod-orig")
    backup.write_bytes(b"garbage")
    patched = target(osc).read_bytes()
    code, out = run(osc, uninstall=True)
    assert code == inst.EXIT_REFUSED
    assert target(osc).read_bytes() == patched


def test_uninstall_of_original_is_noop(osc):
    code, out = run(osc, uninstall=True)
    assert code == 0 and "nicht installiert" in out


def test_write_failure_keeps_original(osc, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(inst.os, "replace", boom)
    code, out = run(osc)
    assert code == inst.EXIT_ERROR and "disk full" in out
    assert target(osc).read_bytes() == ORIGINAL
    leftovers = [p for p in os.listdir(target(osc).parent) if p.endswith(".tmp")]
    assert leftovers == []


def test_patch_text_requires_unique_anchor():
    with pytest.raises(ValueError):
        inst.patched_text(b"nothing here\n")
