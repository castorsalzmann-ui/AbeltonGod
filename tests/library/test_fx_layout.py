"""FX library folder (#482): Samples/FX/Transitions, configurable; the engine places fx there."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from library import place_sample
from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError

ROOT = Path(__file__).resolve().parents[2]


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


def test_place_sample_fx_writes_a_valid_sidecar_into_transitions(tmp_path: Path) -> None:
    params = {"schema_version": "0.1", "seed": 3, "bpm": 140, "kind": "reverse_crash",
              "length_beats": 1}
    wav = place_sample("fx", params, tmp_path)
    assert wav.relative_to(tmp_path).parts[:-1] == ("Samples", "FX", "Transitions")
    assert wav.name.startswith("fx") and wav.suffix == ".wav"
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "contracts/sample-metadata.schema.json").read_text("utf-8"))
    Draft202012Validator(schema).validate(meta)
    assert meta["category"] == "fx"
    assert meta["engine"] == {"name": "abeltongod-audio-engine-fx", "version": "0.1.0"}
    # 1 beat at 140 BPM, 48 kHz = 20571.43 -> 20571 frames; reverse_crash: boundary = N
    assert meta["features"]["anchor"] == "end"
    assert meta["features"]["boundary_frame"] == 20571
    assert meta["parameters"]["tail_beats"] == 0  # the resolved form is stored
    assert len(wav.read_bytes()) == 44 + 20571 * 2 * 3
