"""Library page choice log (#110 step 2): "Favorit", "Passt nicht", note, "nur Favoriten",
log view. Offscreen; the log file is read back with plain json, not with gui_core.choices."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gui.app import create_app  # noqa: E402
from gui.drag import PATH_ROLE  # noqa: E402
from gui.library_panel import LibraryPanel  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui_core.choices import ChoiceLog  # noqa: E402
from gui_core.settings import SettingsStore  # noqa: E402

SIDECAR = Path(__file__).resolve().parents[1] / "fixtures" / "sidecars" / "kick-v01.json"


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


@pytest.fixture
def out(tmp_path: Path) -> Path:
    d = tmp_path / "out"
    (d / "Samples").mkdir(parents=True)
    for i in range(3):
        (d / "Samples" / f"k{i}.wav").write_bytes(b"RIFF" + bytes([i]) * 64)
        meta = json.loads(SIDECAR.read_text(encoding="utf-8"))
        meta["file"] = f"k{i}.wav"
        (d / "Samples" / f"k{i}.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


def panel_for(out: Path, log: Path) -> LibraryPanel:
    p = LibraryPanel(ChoiceLog(log))
    p.set_folder(out)
    return p


def select(panel: LibraryPanel, name: str) -> None:
    for i in range(panel.list.count()):
        if Path(panel.list.item(i).data(PATH_ROLE)).name == name:
            panel.list.setCurrentRow(i)
            return
    raise AssertionError(f"{name} not listed")


def rows(panel: LibraryPanel) -> list[str]:
    return [panel.list.item(i).text().split("\n")[0] for i in range(panel.list.count())]


def logged(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_buttons_need_a_selection(qapp, out, tmp_path):
    p = panel_for(out, tmp_path / "choices.jsonl")
    assert not p.favourite_button.isEnabled() and not p.reject_button.isEnabled()
    assert p.judge("favourite") is False and not (tmp_path / "choices.jsonl").exists()
    select(p, "k1.wav")
    assert p.favourite_button.isEnabled() and p.reject_button.isEnabled()


def test_favourite_with_note_is_logged_marked_and_filtered(qapp, out, tmp_path):
    log = tmp_path / "cfg" / "choices.jsonl"
    p = panel_for(out, log)
    select(p, "k1.wav")
    p.note.setText("genau der Biss")
    p.favourite_button.click()
    (entry,) = logged(log)
    assert entry["verdict"] == "favourite" and entry["note"] == "genau der Biss"
    assert entry["sample"]["path"] == "Samples/k1.wav"
    assert entry["sidecar"]["parameters"]["seed"] == 5
    assert p.note.text() == ""  # the note belongs to that one verdict
    assert p.current_path().name == "k1.wav"  # selection kept after the list is rebuilt
    assert [r.split()[1] for r in rows(p) if r.startswith("★ ")] == ["k1.wav"]
    assert "1 Einträge" in p.choice_info.text() and "Favorit: k1.wav" in p.choice_info.text()
    assert p.log_view.count() == 1 and "Favorit · k1.wav · genau der Biss" in \
        p.log_view.item(0).text()

    p.only_favourites.setChecked(True)
    assert [r.split()[1] for r in rows(p)] == ["k1.wav"]
    p.only_favourites.setChecked(False)
    assert p.list.count() == 3


def test_reject_replaces_the_favourite_and_leaves_the_filter(qapp, out, tmp_path):
    log = tmp_path / "choices.jsonl"
    p = panel_for(out, log)
    select(p, "k2.wav")
    p.favourite_button.click()
    p.reject_button.click()
    assert [e["verdict"] for e in logged(log)] == ["favourite", "reject"]  # append-only
    assert any(r.startswith("✗ k2.wav") for r in rows(p))
    p.only_favourites.setChecked(True)
    assert p.list.count() == 0
    assert p.log_view.item(0).text().split(" · ")[1] == "Passt nicht"  # newest first


def test_log_survives_a_new_panel_and_bad_lines_are_counted(qapp, out, tmp_path):
    log = tmp_path / "choices.jsonl"
    p = panel_for(out, log)
    select(p, "k0.wav")
    p.favourite_button.click()
    with open(log, "ab") as f:
        f.write(b"{kaputt\n")
    q = panel_for(out, log)
    assert any(r.startswith("★ k0.wav") for r in rows(q))
    assert "1 fehlerhafte Zeilen übersprungen" in q.choice_info.text()


def test_write_failure_is_shown_not_raised(qapp, out, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    p = panel_for(out, blocker / "choices.jsonl")  # parent is a file: cannot be created
    select(p, "k0.wav")
    assert p.judge("favourite") is False
    assert p.choice_info.text().startswith("Nicht gespeichert")
    assert not any(r.startswith("★") for r in rows(p))


class SilentBackend:
    available = True

    def play(self, wav_path):
        pass

    def stop(self):
        pass


def test_main_window_keeps_the_log_beside_the_settings(qapp, tmp_path, out):
    w = MainWindow(out_dir=out, settings_store=SettingsStore(path=tmp_path / "settings.json"),
                   backend=SilentBackend(), opener=lambda p: True)
    try:
        assert w.library.choices.path == tmp_path / "choices.jsonl"
    finally:
        w.close()
    m = MainWindow(out_dir=out, backend=SilentBackend(), opener=lambda p: True)
    try:
        assert m.library.choices.path is None  # no settings file: the log is in memory
    finally:
        m.close()
