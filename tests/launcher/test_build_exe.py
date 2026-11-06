"""Size report and Qt pruning of scripts/build_exe.py (#435). The real proof that the pruned
bundle still works is the "Build exe" smoke on Windows; this checks the file handling."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def build_exe():
    spec = importlib.util.spec_from_file_location("build_exe", ROOT / "scripts" / "build_exe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_bundle(tmp_path: Path, names) -> Path:
    folder = tmp_path / "AbeltonGod"
    qt = folder / "_internal" / "PySide6"
    for rel in names:
        p = qt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 1000)
    return folder


def test_prune_removes_listed_files_and_keeps_the_rest(build_exe, tmp_path):
    keep = build_exe.QT_REQUIRED + ("plugins/styles/qmodernwindowsstyle.dll",)
    gone = ("opengl32sw.dll", "translations/qtbase_de.qm", "plugins/imageformats/qjpeg.dll",
            "plugins/platforms/qminimal.dll", "Qt6Network.dll")
    folder = _fake_bundle(tmp_path, keep + gone)
    freed, lines = build_exe.prune_qt(folder)
    qt = folder / "_internal" / "PySide6"
    assert freed == 5000
    assert all((qt / rel).is_file() for rel in keep)
    assert not any((qt / rel).exists() for rel in gone)
    assert not (qt / "translations").exists()
    assert "prune: plugins/tls not present" in lines


def test_prune_fails_when_a_required_file_is_missing(build_exe, tmp_path):
    required = tuple(r for r in build_exe.QT_REQUIRED if "qwindows" not in r)
    folder = _fake_bundle(tmp_path, required)
    with pytest.raises(FileNotFoundError, match="qwindows"):
        build_exe.prune_qt(folder)


def test_prune_list_never_touches_what_the_gui_needs(build_exe):
    for rel in build_exe.QT_PRUNE:
        assert not any(req == rel or req.startswith(rel.rstrip("/") + "/")
                       for req in build_exe.QT_REQUIRED), rel


def test_spec_builds_a_windowed_and_a_console_exe_in_one_folder(build_exe, tmp_path):
    import ast

    text = build_exe.spec_text(tmp_path / "build_info.json")
    tree = ast.parse(text)
    calls = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.setdefault(node.func.id, []).append(
                {k.arg: ast.literal_eval(k.value) for k in node.keywords
                 if isinstance(k.value, ast.Constant)})
    exes = {c["name"]: c["console"] for c in calls["EXE"]}
    assert exes == {"AbeltonGod": False, "AbeltonGod-cli": True}
    assert len(calls["COLLECT"]) == 1 and calls["COLLECT"][0]["name"] == "AbeltonGod"
    assert "exe_entry.py" in text and "PySide6.QtWebEngineCore" not in text


def _pe(subsystem: int) -> bytes:
    data = bytearray(512)
    data[:2] = b"MZ"
    data[0x3C:0x40] = (0x80).to_bytes(4, "little")
    data[0x80:0x84] = b"PE\0\0"
    data[0x80 + 24 + 68:0x80 + 24 + 70] = subsystem.to_bytes(2, "little")
    return bytes(data)


def test_pe_subsystem_reads_the_header(build_exe, tmp_path):
    for value in (2, 3):
        p = tmp_path / f"{value}.exe"
        p.write_bytes(_pe(value))
        assert build_exe.pe_subsystem(p) == value
    (tmp_path / "x.exe").write_bytes(b"not a pe")
    with pytest.raises(ValueError):
        build_exe.pe_subsystem(tmp_path / "x.exe")


def test_pe_subsystem_of_a_real_windows_exe(build_exe):
    """Independent reference on Windows: CPython's ``python.exe`` is a console program (3),
    ``pythonw.exe`` the windowed one (2). (setuptools' ``gui-64.exe`` read 3 in CI run
    42219721439, so it is not used as a reference; why is not established.)"""
    import sys

    base = Path(sys.base_prefix)
    console, windowed = base / "python.exe", base / "pythonw.exe"
    if not (console.is_file() and windowed.is_file()):
        pytest.skip("no Windows CPython install (python.exe / pythonw.exe)")
    assert build_exe.pe_subsystem(console) == 3
    assert build_exe.pe_subsystem(windowed) == 2


def test_size_report_lists_folders_and_largest_files(build_exe, tmp_path):
    folder = _fake_bundle(tmp_path, ("Qt6Core.dll",))
    (folder / "_internal" / "big.bin").write_bytes(b"x" * 3 * 1024 * 1024)
    text = build_exe.size_report(folder)
    assert text.startswith("total: 3.0 MB")
    assert "3.0 MB  big.bin" in text and "_internal" in text
    assert "-- largest files" in text
