"""Atmos library folder (#529 step 0): Samples/Atmos, configurable."""

from __future__ import annotations

import pytest

from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError


def test_atmos_folder_is_samples_atmos() -> None:
    assert DEFAULT_LAYOUT.parts_for("atmos") == ("Samples", "Atmos")
    assert LibraryLayout(atmos="X\\Y").parts_for("atmos") == ("X", "Y")
    # the other folders unchanged
    assert DEFAULT_LAYOUT.parts_for("fx") == ("Samples", "FX", "Transitions")
    assert DEFAULT_LAYOUT.parts_for("bass") == ("Samples", "Bass")
    with pytest.raises(LibraryPathError):
        LibraryLayout(atmos="../x")
    with pytest.raises(LibraryPathError):
        LibraryLayout(atmos="Samples/AUX")
