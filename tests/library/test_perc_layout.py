"""Perc category plumbing (#475): folder Samples/Drums/Percs, registry, place_sample, re-render
and the CLI render percs; the other folders are unchanged."""

from __future__ import annotations

import io
import json

import pytest

from audio_engine import cli
from audio_engine.categories import get_category
from audio_engine.io import rerender_from_sidecar
from library import place_sample
from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError

PRESETS = ["bongo", "clave", "conga", "conga-dry", "cowbell", "hard-groove-tom",
           "hard-groove-tom-low", "shaker", "shaker-long"]


def test_perc_folder_is_samples_drums_percs() -> None:
    assert DEFAULT_LAYOUT.parts_for("perc") == ("Samples", "Drums", "Percs")
    assert LibraryLayout(percs="X\\Y").parts_for("perc") == ("X", "Y")
    assert DEFAULT_LAYOUT.parts_for("rim") == ("Samples", "Drums", "Rims")
    assert DEFAULT_LAYOUT.parts_for("bass") == ("Samples", "Bass")
    with pytest.raises(LibraryPathError):
        LibraryLayout(percs="../x")
    with pytest.raises(LibraryPathError):
        LibraryLayout(percs="Samples/CON")


def test_perc_is_registered_with_its_own_engine_identity() -> None:
    cat = get_category("perc")
    assert cat.engine == {"name": "abeltongod-audio-engine-perc", "version": "0.1.0"}
    assert cat.metadata_schema_version == "0.2" and cat.default_stem == "perc"


@pytest.mark.parametrize("model", ["conga", "tom", "shaker", "cowbell", "clave"])
def test_place_sample_perc_writes_a_sidecar_that_rerenders_the_same_bytes(tmp_path,
                                                                          model) -> None:
    wav = place_sample("perc", {"schema_version": "0.1", "seed": 1, "model": model}, tmp_path)
    assert wav.relative_to(tmp_path).parts[:-1] == ("Samples", "Drums", "Percs")
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "perc" and meta["schema_version"] == "0.2"
    assert meta["engine"]["name"] == "abeltongod-audio-engine-perc"
    assert meta["parameters"]["model"] == model and "length_ms" in meta["parameters"]
    assert rerender_from_sidecar(wav.with_suffix(".json")) == wav.read_bytes()


def test_place_sample_perc_rejects_bad_values_before_any_folder(tmp_path) -> None:
    from audio_engine.perc import PercParamsError

    with pytest.raises(PercParamsError, match="model"):
        place_sample("perc", {"schema_version": "0.1", "seed": 1, "model": "bongo"}, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cli_lists_and_renders_perc_presets(tmp_path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert cli.main(["--category", "perc", "--list-presets"], out, err) == 0
    assert [ln.split()[0] for ln in out.getvalue().splitlines()] == PRESETS
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "perc", "--preset", "shaker", "--variants", "3",
                     "--out", str(tmp_path)], out, err)
    assert code == 0 and err.getvalue() == ""
    assert sorted(p.name for p in tmp_path.glob("*.wav")) == [
        f"shaker_s1_v{i}.wav" for i in range(3)]
    for js in sorted(tmp_path.glob("*.json")):
        meta = json.loads(js.read_text(encoding="utf-8"))
        assert meta["category"] == "perc" and meta["parameters"]["preset"] == "shaker"
        assert rerender_from_sidecar(js) == js.with_suffix(".wav").read_bytes()


@pytest.mark.parametrize("argv", [
    ["--preset", "conga", "--set", "tune_semitones=13"],  # out of range
    ["--preset", "conga", "--set", "pitch_hz=200"],  # not in v0.1
    ["--preset", "centre"],  # a kick preset name
    ["--prompt", "sub"],
])
def test_cli_perc_errors_write_nothing(tmp_path, argv) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "perc", *argv, "--out", str(tmp_path / "o")], out, err)
    assert code == cli.EXIT_USAGE and err.getvalue().startswith("error:")
    assert out.getvalue() == "" and list(tmp_path.iterdir()) == []
