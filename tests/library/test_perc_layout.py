"""Perc library folder (#475 step 1): Samples/Drums/Percs, configurable; nothing is written for
perc until the engine registers the category (step 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_engine.categories import CategoryUnavailable
from library import place_sample
from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError


def test_perc_folder_is_samples_drums_percs() -> None:
    assert DEFAULT_LAYOUT.parts_for("perc") == ("Samples", "Drums", "Percs")
    assert LibraryLayout(percs="X\\Y").parts_for("perc") == ("X", "Y")
    # the other folders are unchanged
    assert DEFAULT_LAYOUT.parts_for("rim") == ("Samples", "Drums", "Rims")
    assert DEFAULT_LAYOUT.parts_for("bass") == ("Samples", "Bass")
    with pytest.raises(LibraryPathError):
        LibraryLayout(percs="../x")
    with pytest.raises(LibraryPathError):
        LibraryLayout(percs="Samples/CON")


def test_perc_placement_is_refused_before_any_folder_exists(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    with pytest.raises(CategoryUnavailable, match="perc"):
        place_sample("perc", {"schema_version": "0.1", "seed": 1}, project)
    assert list(project.iterdir()) == []
