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


def _spec_datas(build_exe, tmp_path) -> dict[str, Path]:
    """``datas`` of the generated spec as {target in the bundle: source folder or file}."""
    import ast

    tree = ast.parse(build_exe.spec_text(tmp_path / "build_info.json"))
    found = [ast.literal_eval(node.value) for node in tree.body
             if isinstance(node, ast.Assign) and node.targets[0].id == "datas"]
    assert len(found) == 1, found
    return {target: Path(source) for source, target in found[0]}


def test_spec_bundles_the_engine_data_folders(build_exe, tmp_path):
    """#542: the exe must carry the preset JSONs and the reference calibration table. The
    folder and file names are written here, not taken from build_exe. This only checks the
    spec; that the built folder really holds the files is checked by the build itself
    (``check_bundle_data``) in the "Build exe" workflow on Windows."""
    datas = _spec_datas(build_exe, tmp_path)
    for target, name in (("audio_engine/presets", "centre.json"),
                         ("audio_engine/calibration", "reference_scales.json")):
        assert target in datas, f"{target} is not in the spec's datas: {sorted(datas)}"
        assert datas[target] == ROOT / "src" / target
        assert (datas[target] / name).is_file(), datas[target] / name


def test_calibration_lands_where_the_engine_looks_for_it(build_exe, tmp_path):
    """The engine resolves the table next to its module; in the onedir bundle ``src/`` becomes
    ``_internal/``, so the target folder must be the module-relative folder."""
    from audio_engine import reference_v2

    rel = reference_v2.CALIBRATION_FILE.relative_to(ROOT / "src")
    assert rel.as_posix() in build_exe.BUNDLE_REQUIRED
    assert rel.parent.as_posix() in _spec_datas(build_exe, tmp_path)


def test_every_required_data_file_is_covered_by_the_spec(build_exe, tmp_path):
    datas = _spec_datas(build_exe, tmp_path)
    for rel in build_exe.BUNDLE_REQUIRED:
        folder, name = rel.rsplit("/", 1)
        assert folder in datas and (datas[folder] / name).is_file(), rel


def _data_bundle(tmp_path: Path, files: dict[str, str]) -> Path:
    folder = tmp_path / "AbeltonGod"
    for rel, text in files.items():
        p = folder / "_internal" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return folder


def test_bundle_check_passes_with_all_data_files(build_exe, tmp_path):
    folder = _data_bundle(tmp_path, {rel: "{}" for rel in build_exe.BUNDLE_REQUIRED})
    lines = build_exe.check_bundle_data(folder)
    assert lines == [f"bundled: {rel} 2 bytes" for rel in build_exe.BUNDLE_REQUIRED]


def test_bundle_check_fails_without_the_calibration_table(build_exe, tmp_path):
    folder = _data_bundle(tmp_path, {"audio_engine/presets/centre.json": "{}"})
    with pytest.raises(FileNotFoundError, match="reference_scales.json"):
        build_exe.check_bundle_data(folder)


def test_bundle_check_fails_on_a_table_that_is_not_json(build_exe, tmp_path):
    folder = _data_bundle(tmp_path, {
        "audio_engine/presets/centre.json": "{}",
        "audio_engine/calibration/reference_scales.json": "{ cut off"})
    with pytest.raises(ValueError, match="reference_scales.json is not valid JSON"):
        build_exe.check_bundle_data(folder)


def test_build_fails_when_the_bundle_lacks_the_data_files(build_exe, tmp_path, monkeypatch,
                                                         capsys):
    """``main`` returns 1 when PyInstaller's output lacks the data files (PyInstaller itself is
    replaced by a stub that writes an empty folder; the real run is the Windows workflow)."""
    import sys
    import types

    dist = tmp_path / "dist"
    stub = types.ModuleType("PyInstaller.__main__")
    stub.run = lambda args: (dist / "AbeltonGod" / "_internal").mkdir(parents=True)
    pkg = types.ModuleType("PyInstaller")
    pkg.__main__ = stub
    monkeypatch.setitem(sys.modules, "PyInstaller", pkg)
    monkeypatch.setitem(sys.modules, "PyInstaller.__main__", stub)
    assert build_exe.main(["--dist", str(dist), "--work", str(tmp_path / "work")]) == 1
    assert "reference_scales.json" in capsys.readouterr().err


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
