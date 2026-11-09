"""Category `atmos` in sample-metadata v0.2 (#529 step 0, D-034).

The atmos-only features (loop_samples, loop_samples_exact, seamless, preroll_loops, and the
optional tuning_error_cents / realised_detune_cents) are written out here by hand, not read
from the schema, so a changed rule in the contract turns a test red.
"""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parent.parent
META = json.loads((ROOT / "contracts/sample-metadata.schema.json").read_text(encoding="utf-8"))
META_V = Draft202012Validator(META)

ATMOS_DOC = {
    "schema_version": "0.2", "file": "atmos.wav", "category": "atmos",
    "engine": {"name": "abeltongod-audio-engine-atmos", "version": "0.1.0"},
    "parameters": {"schema_version": "0.1", "seed": 7, "bpm": 140, "kind": "noise_bed"},
    "features": {
        "peak_dbfs": -1.0, "length_ms": 13714.3, "spectral_centroid_hz": 2000.0,
        # 8 bars at 140 BPM and 48 kHz: 240 * 8 * 48000 / 140 = 658285.714...
        "loop_samples": 658286, "loop_samples_exact": 658285.7142857143, "seamless": True,
        "preroll_loops": {"filter": 1, "reverb": 2},
        "tuning_error_cents": None, "realised_detune_cents": None,
    },
    "created_at": "2026-11-09T12:00:00+00:00",
}
ATMOS_ONLY = ("loop_samples", "loop_samples_exact", "seamless", "preroll_loops",
              "tuning_error_cents", "realised_detune_cents")
REQUIRED = ("loop_samples", "loop_samples_exact", "seamless", "preroll_loops")
OTHER_ENGINES = {
    "clap": "abeltongod-audio-engine-clap", "hat": "abeltongod-audio-engine-hat",
    "snare": "abeltongod-audio-engine-snare", "rim": "abeltongod-audio-engine-rim",
    "bass": "abeltongod-audio-engine-bass", "laser": "abeltongod-audio-engine-laser",
    "perc": "abeltongod-audio-engine-perc",
}


def _changed(path: str, value, base: dict = ATMOS_DOC) -> dict:
    doc = copy.deepcopy(base)
    node = doc
    *parents, last = path.split(".")
    for key in parents:
        node = node[key]
    if value is ...:
        del node[last]
    else:
        node[last] = value
    return doc


def test_metadata_category_enum_ends_with_atmos() -> None:
    assert META["properties"]["category"]["enum"] == [
        "kick", "clap", "hat", "snare", "rim", "bass", "laser", "perc", "fx", "atmos"]


def test_metadata_atmos_valid_instances() -> None:
    META_V.validate(ATMOS_DOC)
    for kind in ("noise_bed", "drone", "resonant", "granular"):
        META_V.validate(_changed("parameters.kind", kind))
    META_V.validate(_changed("features.seamless", False))
    META_V.validate(_changed("features.preroll_loops", {"filter": 0, "reverb": 0}))
    META_V.validate(_changed("features.tuning_error_cents", -10.79))
    META_V.validate(_changed("features.realised_detune_cents", 3.2))
    META_V.validate(_changed("features.tuning_error_cents", ...))  # optional
    META_V.validate(_changed("features.realised_detune_cents", ...))
    META_V.validate(_changed("features.loop_samples_exact", 57600))  # integer N is a number
    # the other categories still validate, including the kick v0.1 fixture
    META_V.validate(json.loads((ROOT / "tests/fixtures/sidecars/kick-v01.json").read_text("utf-8")))
    for category, engine in OTHER_ENGINES.items():
        doc = copy.deepcopy(ATMOS_DOC)
        doc.update(category=category, file=f"{category}.wav")
        doc["engine"]["name"] = engine
        for field in ATMOS_ONLY:
            del doc["features"][field]
        META_V.validate(doc)


METADATA_INVALID = {
    "atmos with schema_version 0.1": _changed("schema_version", "0.1"),
    "atmos with the kick engine name": _changed("engine.name", "abeltongod-audio-engine"),
    "atmos with the fx engine name": _changed("engine.name", "abeltongod-audio-engine-fx"),
    **{f"atmos with the {c} engine name": _changed("engine.name", e)
       for c, e in OTHER_ENGINES.items()},
    "atmos parameters without seed": _changed("parameters.seed", ...),
    "atmos parameters without bpm": _changed("parameters.bpm", ...),
    "atmos parameters without schema_version": _changed("parameters.schema_version", ...),
    "atmos parameters with version 0.2": _changed("parameters.schema_version", "0.2"),
    **{f"atmos without {f}": _changed(f"features.{f}", ...) for f in REQUIRED},
    "loop_samples 0": _changed("features.loop_samples", 0),
    "loop_samples fractional": _changed("features.loop_samples", 658285.5),
    "loop_samples as string": _changed("features.loop_samples", "658286"),
    "loop_samples_exact 0": _changed("features.loop_samples_exact", 0),
    "seamless as string": _changed("features.seamless", "true"),
    "seamless as 1": _changed("features.seamless", 1),
    "preroll without reverb": _changed("features.preroll_loops", {"filter": 1}),
    "preroll without filter": _changed("features.preroll_loops", {"reverb": 1}),
    "preroll negative": _changed("features.preroll_loops", {"filter": -1, "reverb": 0}),
    "preroll fractional": _changed("features.preroll_loops", {"filter": 1.5, "reverb": 0}),
    "preroll unknown stage": _changed("features.preroll_loops",
                                      {"filter": 1, "reverb": 0, "echo": 0}),
    "preroll as integer": _changed("features.preroll_loops", 3),
    "tuning error as string": _changed("features.tuning_error_cents", "5"),
    "atmos with fx boundary_frame": _changed("features.boundary_frame", 658286),
    "atmos with fx anchor": _changed("features.anchor", "start"),
    "category drone (a kind, not a category)": _changed("category", "drone"),
    "category Atmos": _changed("category", "Atmos"),
}


@pytest.mark.parametrize("doc", METADATA_INVALID.values(), ids=METADATA_INVALID)
def test_metadata_atmos_invalid_instances(doc) -> None:
    with pytest.raises(ValidationError):
        META_V.validate(doc)


@pytest.mark.parametrize("category", [*sorted(OTHER_ENGINES), "fx"])
@pytest.mark.parametrize("field", ATMOS_ONLY)
def test_atmos_features_are_refused_for_other_categories(category: str, field: str) -> None:
    doc = copy.deepcopy(ATMOS_DOC)
    doc.update(category=category, file=f"{category}.wav")
    doc["engine"]["name"] = OTHER_ENGINES.get(category, "abeltongod-audio-engine-fx")
    keep = doc["features"][field]
    for name in ATMOS_ONLY:
        del doc["features"][name]
    if category == "fx":
        doc["features"].update(boundary_frame=1, anchor="start")
    META_V.validate(doc)  # without the atmos field the document is valid
    doc["features"][field] = keep if keep is not None else 1.0
    with pytest.raises(ValidationError):
        META_V.validate(doc)


def test_atmos_engine_name_is_refused_for_other_categories() -> None:
    for category, engine in OTHER_ENGINES.items():
        doc = copy.deepcopy(ATMOS_DOC)
        doc.update(category=category, file=f"{category}.wav")
        for name in ATMOS_ONLY:
            del doc["features"][name]
        with pytest.raises(ValidationError):  # atmos engine name on another category
            META_V.validate(doc)
        doc["engine"]["name"] = engine
        META_V.validate(doc)


def test_atmos_is_a_contract_category() -> None:
    from audio_engine.categories import CONTRACT_CATEGORIES

    assert CONTRACT_CATEGORIES[-1] == "atmos"
