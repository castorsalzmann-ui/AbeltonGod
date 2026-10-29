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


def backup_of(osc):
    return target(osc).with_name("clip_slot.py.abeltongod-orig")


def test_foreign_backup_is_neither_overwritten_nor_trusted(osc):
    """A backup that is not the pinned original stops the install (review of PR #87)."""
    backup_of(osc).write_bytes(b"older backup")
    code, out = run(osc)
    assert code == inst.EXIT_REFUSED and "NICHT das Original" in out
    assert backup_of(osc).read_bytes() == b"older backup"
    assert target(osc).read_bytes() == ORIGINAL


CRLF = ORIGINAL.replace(b"\n", b"\r\n")


@pytest.mark.parametrize("current", [ORIGINAL, CRLF], ids=["LF", "CRLF"])
def test_byte_identical_backup_is_reused_and_uninstall_restores_exactly(osc, current):
    target(osc).write_bytes(current)
    backup_of(osc).write_bytes(current)
    code, out = run(osc)
    assert code == 0, out
    assert backup_of(osc).read_bytes() == current
    assert "create_audio_clip" in methods_of(target(osc).read_bytes())
    code, out = run(osc, uninstall=True)
    assert code == 0, out
    assert target(osc).read_bytes() == current


@pytest.mark.parametrize("current,backup", [(ORIGINAL, CRLF), (CRLF, ORIGINAL)],
                         ids=["file-LF-backup-CRLF", "file-CRLF-backup-LF"])
def test_backup_with_other_line_endings_is_refused(osc, current, backup):
    """Review round 2 of PR #87: a backup that is the same text but other bytes would make
    --uninstall restore something else than the user's pre-install file."""
    target(osc).write_bytes(current)
    backup_of(osc).write_bytes(backup)
    code, out = run(osc)
    assert code == inst.EXIT_REFUSED and "nicht byte-gleich" in out
    assert target(osc).read_bytes() == current and backup_of(osc).read_bytes() == backup


@pytest.mark.parametrize("current", [ORIGINAL, CRLF], ids=["LF", "CRLF"])
def test_fresh_backup_is_byte_identical_to_the_file(osc, current):
    target(osc).write_bytes(current)
    assert run(osc)[0] == 0
    assert backup_of(osc).read_bytes() == current
    assert run(osc, uninstall=True)[0] == 0
    assert target(osc).read_bytes() == current


@pytest.mark.parametrize("which", ["backup", "target"])
@pytest.mark.parametrize("mode", ["install", "uninstall", "check"])
def test_directory_instead_of_file_is_a_clean_error(osc, which, mode):
    if mode == "uninstall":
        run(osc)  # installed first
    path = backup_of(osc) if which == "backup" else target(osc)
    if path.exists():
        path.unlink()
    path.mkdir()
    code, out = run(osc, uninstall=mode == "uninstall", check=mode == "check")
    if which == "backup" and mode == "check":
        assert code == 0  # --check does not read the backup
        return
    assert code == inst.EXIT_REFUSED and "Datei nicht lesbar" in out
    assert path.is_dir()


def test_unreadable_backup_is_a_clean_error(osc, monkeypatch):
    real = Path.read_bytes

    def denied(self):
        if self.name.endswith(".abeltongod-orig"):
            raise PermissionError(13, "Access is denied")
        return real(self)

    backup_of(osc).write_bytes(ORIGINAL)
    monkeypatch.setattr(Path, "read_bytes", denied)
    code, out = run(osc)
    assert code == inst.EXIT_REFUSED and "PermissionError" in out
    assert target(osc).read_bytes() == ORIGINAL


def test_disk_full_while_writing_backup_then_rerun(osc, monkeypatch):
    """Regression (review of PR #87, major): run 1 fails while writing the backup (disk full).
    Before the fix the backup was left truncated, run 2 skipped it unchecked and patched, and
    --uninstall then refused. Now run 1 leaves no backup and no patch, run 2 installs with a
    full backup, and --uninstall restores the original byte for byte."""
    real_fdopen = inst.os.fdopen

    class Truncating:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()

        def write(self, data):
            self.fh.write(data[:20])
            self.fh.flush()
            raise OSError(28, "No space left on device")

    real_mkstemp = inst.tempfile.mkstemp
    backup_fds: set[int] = set()

    def mkstemp(*a, prefix="", **k):
        fd, path = real_mkstemp(*a, prefix=prefix, **k)
        if prefix.startswith("clip_slot.py.abeltongod-orig"):
            backup_fds.add(fd)
        return fd, path

    def fdopen(fd, mode="r", *a, **k):
        fh = real_fdopen(fd, mode, *a, **k)
        return Truncating(fh) if fd in backup_fds else fh

    monkeypatch.setattr(inst.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(inst.os, "fdopen", fdopen)
    code, out = run(osc)
    assert code == inst.EXIT_ERROR and "No space left" in out
    assert target(osc).read_bytes() == ORIGINAL
    assert not backup_of(osc).exists()
    assert [p for p in os.listdir(target(osc).parent) if p.endswith(".tmp")] == []

    assert backup_fds, "the fault hook never saw the backup temp file"
    monkeypatch.setattr(inst.os, "fdopen", real_fdopen)
    code, out = run(osc)
    assert code == 0, out
    assert backup_of(osc).read_bytes() == ORIGINAL
    code, out = run(osc, uninstall=True)
    assert code == 0, out
    assert target(osc).read_bytes() == ORIGINAL


def test_truncated_backup_from_an_older_run_blocks_install(osc):
    backup_of(osc).write_bytes(ORIGINAL[:30])  # left behind by script 0.1.0 on a full disk
    code, out = run(osc)
    assert code == inst.EXIT_REFUSED
    assert target(osc).read_bytes() == ORIGINAL and backup_of(osc).read_bytes() == ORIGINAL[:30]


def test_backup_that_does_not_read_back_blocks_patch(osc, monkeypatch):
    real = inst.atomic_write

    def corrupt_backup(path, data):
        real(path, data[:-5] if path.name.endswith(".abeltongod-orig") else data)

    monkeypatch.setattr(inst, "atomic_write", corrupt_backup)
    code, out = run(osc)
    assert code == inst.EXIT_ERROR and "does not read back" in out
    assert target(osc).read_bytes() == ORIGINAL


def test_backup_reading_back_with_other_line_endings_blocks_patch(osc, monkeypatch):
    """Read-back must compare raw bytes: same text with CRLF is not the user's file."""
    real = inst.atomic_write

    def crlf_backup(path, data):
        real(path, data.replace(b"\n", b"\r\n")
             if path.name.endswith(".abeltongod-orig") else data)

    monkeypatch.setattr(inst, "atomic_write", crlf_backup)
    code, out = run(osc)
    assert code == inst.EXIT_ERROR and "does not read back" in out
    assert target(osc).read_bytes() == ORIGINAL


def test_atomic_write_fsyncs_before_rename(tmp_path, monkeypatch):
    events = []
    real_fsync, real_replace = inst.os.fsync, inst.os.replace
    monkeypatch.setattr(inst.os, "fsync", lambda fd: (events.append("fsync"), real_fsync(fd)))
    monkeypatch.setattr(inst.os, "replace",
                        lambda a, b: (events.append("replace"), real_replace(a, b)))
    inst.atomic_write(tmp_path / "f", b"x")
    assert events == ["fsync", "replace"]
    assert (tmp_path / "f").read_bytes() == b"x"


def test_patched_check_rejects_a_foreign_file_with_our_line(osc):
    """A file that contains our patch line but is not the pinned original + patch: unknown."""
    run(osc)
    foreign = target(osc).read_bytes().replace(b'"fire",', b'"fire", "x",')
    target(osc).write_bytes(foreign)
    code, out = run(osc, check=True)
    assert code == inst.EXIT_REFUSED and "Zustand: unknown" in out
    code, out = run(osc, uninstall=True)
    assert code == inst.EXIT_REFUSED and target(osc).read_bytes() == foreign


@pytest.mark.parametrize("answer", ["", "n"])
def test_uninstall_default_no(osc, answer):
    run(osc)
    patched = target(osc).read_bytes()
    code, out = run(osc, answers=[answer], uninstall=True)
    assert code == inst.EXIT_REFUSED and target(osc).read_bytes() == patched


def test_patched_text_that_would_not_compile_is_refused(tmp_path):
    root = tmp_path / "AbletonOSC"
    (root / "abletonosc").mkdir(parents=True)
    (root / "__init__.py").write_text("")
    broken = b"def broken(:\n" + ORIGINAL  # hash-known stand-in that is not valid Python
    (root / "abletonosc" / "clip_slot.py").write_bytes(broken)
    code, out = run(root, known=hashlib.sha256(broken).hexdigest())
    assert code == inst.EXIT_ERROR and "kein gültiges Python" in out
    assert (root / "abletonosc" / "clip_slot.py").read_bytes() == broken
    assert not (root / "abletonosc" / "clip_slot.py.abeltongod-orig").exists()


def test_prompt_mentions_closing_live(osc):
    prompts = []
    out = io.StringIO()
    inst.run(osc, uninstall=False, check_only=False,
             input_fn=lambda p: (prompts.append(p), "n")[1], out=out, known_original=SHA)
    assert "GESCHLOSSEN" in out.getvalue() and "Live ist geschlossen" in prompts[0]


def test_ctrl_c_at_prompt_exits_130_and_changes_nothing(osc, monkeypatch):
    monkeypatch.setattr(inst, "KNOWN_ORIGINAL_SHA256", SHA)
    monkeypatch.setattr(inst.run, "__kwdefaults__", {"known_original": SHA})

    def interrupt(prompt):
        raise KeyboardInterrupt

    out = io.StringIO()
    try:
        code = inst.main(["--abletonosc-dir", str(osc)], input_fn=interrupt, out=out)
    except KeyboardInterrupt:  # caught here so pytest reports a failure, not an abort
        pytest.fail("Ctrl+C escaped main() with a traceback")
    assert code == inst.EXIT_INTERRUPTED
    assert target(osc).read_bytes() == ORIGINAL and not backup_of(osc).exists()


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
