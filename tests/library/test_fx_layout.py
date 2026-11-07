"""FX library folder (#482, contract step): Samples/FX/Transitions, configurable; nothing is
written for fx until the engine registers the category."""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_engine.categories import CategoryUnavailable
from library import place_sample
from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError


def test_fx_folder_is_samples_fx_transitions() -> None:
    assert DEFAULT_LAYOUT.parts_for("fx") == ("Samples", "FX", "Transitions")
    assert LibraryLayout(fx="X\\Y").parts_for("fx") == ("X", "Y")
    # next to the lasers, the other folders unchanged
    assert DEFAULT_LAYOUT.parts_for("laser") == ("Samples", "FX", "Lasers")
    assert DEFAULT_LAYOUT.parts_for("perc") == ("Samples", "Drums", "Percs")
    with pytest.raises(LibraryPathError):
        LibraryLayout(fx="../x")
    with pytest.raises(LibraryPathError):
        LibraryLayout(fx="Samples/AUX")


def test_fx_placement_is_refused_before_any_folder_exists(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    with pytest.raises(CategoryUnavailable, match="fx"):
        place_sample("fx", {"schema_version": "0.1", "seed": 1, "bpm": 135}, project)
    assert list(project.iterdir()) == []
