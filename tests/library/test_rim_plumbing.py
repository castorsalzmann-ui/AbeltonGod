"""Rim category plumbing (#321): folder, registry, place_sample, re-render and the CLI render
rims; kick, clap and hat placement is unchanged."""

from __future__ import annotations

import io
import json

import pytest

from audio_engine import cli
from audio_engine.categories import get_category
from audio_engine.io import rerender_from_sidecar
from library import place_sample
from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError


def test_rim_folder_is_samples_drums_rims() -> None:
    assert DEFAULT_LAYOUT.parts_for("rim") == ("Samples", "Drums", "Rims")
    assert LibraryLayout(rims="X/Y").parts_for("rim") == ("X", "Y")
    assert DEFAULT_LAYOUT.parts_for("hat") == ("Samples", "Drums", "Hats")
    with pytest.raises(LibraryPathError):
        LibraryLayout(rims="../x")


def test_rim_is_registered_with_its_own_engine_identity() -> None:
    cat = get_category("rim")
    assert cat.engine == {"name": "abeltongod-audio-engine-rim", "version": "0.1.0"}
    assert cat.metadata_schema_version == "0.2" and cat.default_stem == "rim"


def test_place_sample_rim_writes_a_sidecar_that_rerenders_the_same_bytes(tmp_path) -> None:
    wav = place_sample("rim", {"schema_version": "0.1", "seed": 1}, tmp_path)
    assert wav.relative_to(tmp_path).parts[:-1] == ("Samples", "Drums", "Rims")
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "rim" and meta["schema_version"] == "0.2"
    assert meta["engine"]["name"] == "abeltongod-audio-engine-rim"
    assert rerender_from_sidecar(wav.with_suffix(".json")) == wav.read_bytes()


def test_place_sample_rim_rejects_a_bad_cross_field_before_any_folder(tmp_path) -> None:
    from audio_engine.rim import RimParamsError

    bad = {"schema_version": "0.1", "seed": 1, "f1_hz": 455, "hp_hz": 400}
    with pytest.raises(RimParamsError, match="hp_hz"):
        place_sample("rim", bad, tmp_path)
    assert not any(p.suffix == ".wav" for p in tmp_path.rglob("*"))


def test_cli_lists_and_renders_rim_presets(tmp_path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert cli.main(["--category", "rim", "--list-presets"], out, err) == 0
    assert [ln.split()[0] for ln in out.getvalue().splitlines()] == [
        "clave", "high", "long", "rim", "tight"]
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "rim", "--preset", "clave", "--variants", "3",
                     "--out", str(tmp_path)], out, err)
    assert code == 0 and err.getvalue() == ""
    names = [f"clave_s1_v{i}.wav" for i in range(3)]
    assert sorted(p.name for p in tmp_path.glob("*.wav")) == names
    for js in sorted(tmp_path.glob("*.json")):
        meta = json.loads(js.read_text(encoding="utf-8"))
        assert meta["category"] == "rim" and meta["parameters"]["preset"] == "clave"
        assert rerender_from_sidecar(js) == js.with_suffix(".wav").read_bytes()


@pytest.mark.parametrize("argv", [
    ["--preset", "rim", "--set", "hp_hz=500"],  # violates hp < 0.8 * 455
    ["--preset", "rim", "--set", "f3_ratio=2"],  # not in v0.1
    ["--preset", "centre"],  # a kick preset name
    ["--prompt", "sub"],
])
def test_cli_rim_errors_write_nothing(tmp_path, argv) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "rim", *argv, "--out", str(tmp_path / "o")], out, err)
    assert code == cli.EXIT_USAGE and err.getvalue().startswith("error:")
    assert out.getvalue() == "" and list(tmp_path.iterdir()) == []
