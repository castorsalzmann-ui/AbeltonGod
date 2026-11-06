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


def test_size_report_lists_folders_and_largest_files(build_exe, tmp_path):
    folder = _fake_bundle(tmp_path, ("Qt6Core.dll",))
    (folder / "_internal" / "big.bin").write_bytes(b"x" * 3 * 1024 * 1024)
    text = build_exe.size_report(folder)
    assert text.startswith("total: 3.0 MB")
    assert "3.0 MB  big.bin" in text and "_internal" in text
    assert "-- largest files" in text
