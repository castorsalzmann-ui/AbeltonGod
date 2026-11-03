"""Snare category plumbing (#308): folder, registry, place_sample, re-render and the CLI render
snares; kick, clap and hat placement is unchanged."""

from __future__ import annotations

import io
import json

import pytest

from audio_engine import cli
from audio_engine.categories import get_category
from audio_engine.io import rerender_from_sidecar
from library import place_sample
from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError


def test_snare_folder_is_samples_drums_snares() -> None:
    assert DEFAULT_LAYOUT.parts_for("snare") == ("Samples", "Drums", "Snares")
    assert LibraryLayout(snares="X/Y").parts_for("snare") == ("X", "Y")
    assert DEFAULT_LAYOUT.parts_for("hat") == ("Samples", "Drums", "Hats")
    with pytest.raises(LibraryPathError):
        LibraryLayout(snares="../x")


def test_snare_is_registered_with_its_own_engine_identity() -> None:
    cat = get_category("snare")
    assert cat.engine == {"name": "abeltongod-audio-engine-snare", "version": "0.1.0"}
    assert cat.metadata_schema_version == "0.2" and cat.default_stem == "snare"


def test_place_sample_snare_writes_a_sidecar_that_rerenders_the_same_bytes(tmp_path) -> None:
    wav = place_sample("snare", {"schema_version": "0.1", "seed": 1}, tmp_path)
    assert wav.relative_to(tmp_path).parts[:-1] == ("Samples", "Drums", "Snares")
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "snare" and meta["schema_version"] == "0.2"
    assert meta["engine"]["name"] == "abeltongod-audio-engine-snare"
    assert rerender_from_sidecar(wav.with_suffix(".json")) == wav.read_bytes()


def test_place_sample_snare_rejects_a_bad_cross_field_before_any_folder(tmp_path) -> None:
    from audio_engine.snare import SnareParamsError

    bad = {"schema_version": "0.1", "seed": 1, "noise_hp_hz": 5000, "noise_lp_hz": 5500}
    with pytest.raises(SnareParamsError, match="noise_lp_hz"):
        place_sample("snare", bad, tmp_path)
    assert not any(p.suffix == ".wav" for p in tmp_path.rglob("*"))


def test_cli_lists_and_renders_snare_presets(tmp_path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert cli.main(["--category", "snare", "--list-presets"], out, err) == 0
    assert [ln.split()[0] for ln in out.getvalue().splitlines()] == [
        "bright", "default", "long", "tight", "tonal"]
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "snare", "--preset", "tight", "--variants", "3",
                     "--out", str(tmp_path)], out, err)
    assert code == 0 and err.getvalue() == ""
    names = [f"tight_s1_v{i}.wav" for i in range(3)]
    assert sorted(p.name for p in tmp_path.glob("*.wav")) == names
    for js in sorted(tmp_path.glob("*.json")):
        meta = json.loads(js.read_text(encoding="utf-8"))
        assert meta["category"] == "snare" and meta["parameters"]["preset"] == "tight"
        assert rerender_from_sidecar(js) == js.with_suffix(".wav").read_bytes()


@pytest.mark.parametrize("argv", [
    ["--preset", "default", "--set", "noise_hp_hz=5000", "--set", "noise_lp_hz=5500"],
    ["--preset", "default", "--set", "gate_ms=40"],  # not in v0.1
    ["--preset", "centre"],  # a kick preset name
    ["--prompt", "sub"],
])
def test_cli_snare_errors_write_nothing(tmp_path, argv) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "snare", *argv, "--out", str(tmp_path / "o")], out, err)
    assert code == cli.EXIT_USAGE and err.getvalue().startswith("error:")
    assert out.getvalue() == "" and list(tmp_path.iterdir()) == []
