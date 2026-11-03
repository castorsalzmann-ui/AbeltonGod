"""Bass category plumbing (#328): folder, registry, sidecar features, place_sample, re-render and
the CLI render basses; kick, clap and hat placement is unchanged."""

from __future__ import annotations

import io
import json

import pytest

from audio_engine import cli
from audio_engine.categories import get_category
from audio_engine.io import rerender_from_sidecar
from library import place_sample
from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError

SHORT = {"schema_version": "0.1", "seed": 1, "gate_ms": 400}


def test_bass_folder_is_samples_bass_outside_the_drums() -> None:
    assert DEFAULT_LAYOUT.parts_for("bass") == ("Samples", "Bass")
    assert LibraryLayout(bass="X/Y").parts_for("bass") == ("X", "Y")
    assert DEFAULT_LAYOUT.parts_for("hat") == ("Samples", "Drums", "Hats")
    with pytest.raises(LibraryPathError):
        LibraryLayout(bass="../x")


def test_bass_is_registered_with_its_own_engine_identity() -> None:
    cat = get_category("bass")
    assert cat.engine == {"name": "abeltongod-audio-engine-bass", "version": "0.1.0"}
    assert cat.metadata_schema_version == "0.2" and cat.default_stem == "bass"


def test_place_sample_bass_writes_a_sidecar_that_rerenders_the_same_bytes(tmp_path) -> None:
    wav = place_sample("bass", SHORT, tmp_path)
    assert wav.relative_to(tmp_path).parts[:-1] == ("Samples", "Bass")
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "bass" and meta["schema_version"] == "0.2"
    assert meta["engine"]["name"] == "abeltongod-audio-engine-bass"
    assert set(meta["features"]) == {"peak_dbfs", "length_ms", "fundamental_hz", "dc_offset"}
    assert abs(meta["features"]["fundamental_hz"] - 98.0) < 0.5
    assert meta["features"]["length_ms"] == 460.0  # gate 400 + default release 60
    assert rerender_from_sidecar(wav.with_suffix(".json")) == wav.read_bytes()


def test_sidecar_fundamental_is_null_when_the_window_is_too_short(tmp_path) -> None:
    wav = place_sample("bass", {**SHORT, "note": 24, "gate_ms": 100}, tmp_path)
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["features"]["fundamental_hz"] is None


def test_place_sample_bass_rejects_a_bad_cross_field_before_any_folder(tmp_path) -> None:
    from audio_engine.bass import BassParamsError

    with pytest.raises(BassParamsError, match="hp_hz"):
        place_sample("bass", {**SHORT, "note": 31, "hp_hz": 40}, tmp_path)
    assert not any(p.suffix == ".wav" for p in tmp_path.rglob("*"))


def test_cli_lists_and_renders_bass_presets(tmp_path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert cli.main(["--category", "bass", "--list-presets"], out, err) == 0
    assert [ln.split()[0] for ln in out.getvalue().splitlines()] == [
        "bright", "default", "goa-roll-long", "goa-roll-medium", "goa-roll-short", "low",
        "rolling", "sub"]
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "bass", "--preset", "rolling", "--variants", "3",
                     "--out", str(tmp_path)], out, err)
    assert code == 0 and err.getvalue() == ""
    assert sorted(p.name for p in tmp_path.glob("*.wav")) == [
        f"rolling_s1_v{i}.wav" for i in range(3)]
    for js in sorted(tmp_path.glob("*.json")):
        meta = json.loads(js.read_text(encoding="utf-8"))
        assert meta["category"] == "bass" and meta["parameters"]["preset"] == "rolling"
        assert rerender_from_sidecar(js) == js.with_suffix(".wav").read_bytes()


@pytest.mark.parametrize("argv", [
    ["--preset", "default", "--set", "note=31", "--set", "hp_hz=40"],
    ["--preset", "default", "--set", "detune_cents=3"],  # not in v0.1
    ["--preset", "centre"],  # a kick preset name
    ["--prompt", "sub"],
])
def test_cli_bass_errors_write_nothing(tmp_path, argv) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "bass", *argv, "--out", str(tmp_path / "o")], out, err)
    assert code == cli.EXIT_USAGE and err.getvalue().startswith("error:")
    assert out.getvalue() == "" and list(tmp_path.iterdir()) == []
