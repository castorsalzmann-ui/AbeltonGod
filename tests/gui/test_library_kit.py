"""Library page "Kit erstellen" (#498). Offscreen; files are read back with plain json / bytes."""

from __future__ import annotations

import errno
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
from gui_core import kit as kitcore  # noqa: E402
from gui_core.choices import ChoiceLog  # noqa: E402

CATS = {"kick": "kick", "clap_snare": "clap", "closed_hat": "hat", "open_hat": "hat",
        "rim": "rim", "perc": "perc", "bass": "bass"}


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


def sample(folder: Path, stem: str, cat: str, preset: str = "p") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / f"{stem}.wav"
    wav.write_bytes(b"RIFF" + stem.encode() * 40)
    wav.with_suffix(".json").write_text(json.dumps(
        {"category": cat, "created_at": "2026-11-07T10:00:00Z",
         "parameters": {"preset": preset, "seed": 1}}), encoding="utf-8")
    return wav


@pytest.fixture
def out(tmp_path: Path) -> Path:
    d = tmp_path / "out"
    for cat in ("kick", "clap", "rim", "perc", "bass"):
        sample(d / "Samples" / cat, f"{cat}-1", cat)
        sample(d / "Samples" / cat, f"{cat}-2", cat)
    sample(d / "Samples" / "hat", "hat-c", "hat", "closed")
    sample(d / "Samples" / "hat", "hat-o", "hat", "open-long")
    return d


def select(panel: LibraryPanel, wav: Path) -> None:
    for i in range(panel.list.count()):
        if Path(panel.list.item(i).data(PATH_ROLE)) == wav:
            panel.list.setCurrentRow(i)
            return
    raise AssertionError(wav)


def test_section_is_closed_and_boxes_list_only_their_categories(qapp, out):
    p = LibraryPanel(ChoiceLog())
    p.set_folder(out)
    assert not p.kit_section.is_expanded()
    for key, box in p.kit_boxes.items():
        names = [box.itemText(i) for i in range(1, box.count())]
        assert box.itemText(0) == "(keine)" and len(names) == 2
        assert all(n.startswith(CATS[key][:3]) for n in names), (key, names)
        assert box.currentData() is None  # no favourites: nothing prefilled


def test_favourites_prefill_and_export_writes_the_kit(qapp, out):
    p = LibraryPanel(ChoiceLog())
    p.set_folder(out)
    s = out / "Samples"
    for wav in (s / "kick" / "kick-2.wav", s / "hat" / "hat-o.wav", s / "hat" / "hat-c.wav"):
        select(p, wav)
        p.judge("favourite")  # GUI writes now: later clicks are newer or equal (later line)
    # Only the first favourite prefilled by itself (nothing was picked); the button re-fills
    # every slot.
    assert p.kit_picks()["kick"] == s / "kick" / "kick-2.wav"
    assert p.kit_picks()["open_hat"] is None
    p.kit_prefill_button.click()
    picks = p.kit_picks()
    assert picks["kick"] == s / "kick" / "kick-2.wav"
    assert picks["open_hat"] == s / "hat" / "hat-o.wav"
    assert picks["closed_hat"] == s / "hat" / "hat-c.wav"
    assert picks["rim"] is None
    assert p.kit_boxes["kick"].currentText().startswith("★ ")
    p.kit_export_button.click()
    assert p.kit_info.text() == "Kein Kit erstellt: Bitte einen Kit-Namen eingeben."
    p.kit_name.setText("Mein Kit")
    p.kit_export_button.click()
    assert "Kein Kit erstellt" in p.kit_info.text() and "Clap / Snare" in p.kit_info.text()
    assert not (s / "Kits").exists()
    for key in ("clap_snare", "rim", "perc"):
        p.kit_boxes[key].setCurrentIndex(1)
    folder = p.export_kit()
    assert folder == s / "Kits" / "Mein-Kit" and "Kit gespeichert" in p.kit_info.text()
    doc = json.loads((folder / "kit.json").read_text(encoding="utf-8"))
    assert sorted(doc["slots"]) == sorted(["kick", "clap_snare", "closed_hat", "open_hat", "rim",
                                           "perc"])
    assert (folder / doc["slots"]["kick"]["file"]).read_bytes() == \
        (s / "kick" / "kick-2.wav").read_bytes()
    # The copies are listed in the library, but never offered as kit candidates.
    assert any("Kits" in Path(p.list.item(i).data(PATH_ROLE)).parts
               for i in range(p.list.count()))
    assert all("Kits" not in str(p.kit_boxes["kick"].itemData(i))
               for i in range(p.kit_boxes["kick"].count()))
    assert p.kit_picks()["kick"] == s / "kick" / "kick-2.wav"  # picks kept after refresh
    assert p.export_kit() == s / "Kits" / "Mein-Kit_002"


def test_disk_full_shows_a_message_and_leaves_nothing(qapp, out, monkeypatch):
    p = LibraryPanel(ChoiceLog())
    p.set_folder(out)
    for box in p.kit_boxes.values():
        box.setCurrentIndex(1)
    p.kit_name.setText("Voll")

    def full(src, dst):
        Path(dst).write_bytes(b"half")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(kitcore, "_copy_file", full)
    assert p.export_kit() is None
    assert "Kein Kit erstellt (OSError" in p.kit_info.text()
    assert not (out / "Samples" / "Kits").exists()
