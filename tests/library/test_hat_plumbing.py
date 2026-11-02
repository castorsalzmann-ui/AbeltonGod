"""Hat category plumbing (#252): folder, CLI refusal and place_sample refusal until the voice
(#270) registers. Nothing renders."""

from __future__ import annotations

import io

import pytest

from audio_engine import cli
from audio_engine.categories import CategoryUnavailable, registered_categories
from library import place_sample
from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError


def test_hat_folder_is_samples_drums_hats() -> None:
    assert DEFAULT_LAYOUT.parts_for("hat") == ("Samples", "Drums", "Hats")
    assert LibraryLayout(hats="X/Y").parts_for("hat") == ("X", "Y")
    assert DEFAULT_LAYOUT.parts_for("kick") == ("Samples", "Drums", "Kicks")
    assert DEFAULT_LAYOUT.parts_for("clap") == ("Samples", "Drums", "Claps")
    with pytest.raises(LibraryPathError):
        LibraryLayout(hats="../x")


def test_hat_is_not_registered_yet() -> None:
    assert "hat" not in registered_categories()  # H4 (#270) registers it; then drop these tests


def test_place_sample_hat_raises_before_any_folder(tmp_path, monkeypatch) -> None:
    from library import layout

    def no_mkdir(*a, **k):  # clean-up would hide a folder that was made and removed
        raise AssertionError("a folder was about to be created")

    monkeypatch.setattr(layout, "_make_folders", no_mkdir)
    with pytest.raises(CategoryUnavailable, match="hat"):
        place_sample("hat", {"schema_version": "0.1", "seed": 1}, tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("extra", [["--preset", "x"], ["--list-presets"], ["--prompt", "sub"]])
def test_cli_accepts_hat_and_refuses_with_category_text(tmp_path, extra) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "hat", "--out", str(tmp_path / "o"), *extra], out, err)
    assert code == cli.EXIT_USAGE
    assert "error:" in err.getvalue() and "'hat'" in err.getvalue()
    assert "no renderer" in err.getvalue()
    assert out.getvalue() == "" and list(tmp_path.iterdir()) == []
