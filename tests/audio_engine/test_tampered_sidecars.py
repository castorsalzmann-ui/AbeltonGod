"""Tampered sidecars must be rejected by ``rerender_from_sidecar`` before anything renders (#70).

QA report #69, gap 5.1: removing the sample-metadata validation in ``rerender_from_sidecar``
left the whole suite green, because every test fed it a sidecar the engine had just written.
Here a real sidecar (current engine, so no ``EngineVersionMismatch`` hides the check) is
changed by hand and re-rendered. Each case expects a ``jsonschema`` ``ValidationError``, no
render call and an unchanged folder: ``rerender_from_sidecar`` returns bytes and must never
write. Which fields are allowed which JSON types is written out here by hand from the
contract, not derived from the schema file.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

import audio_engine.io as io_mod
from audio_engine import ENGINE_NAME, ENGINE_VERSION
from audio_engine.io import rerender_from_sidecar, write_kick
from audio_engine.params import KickParamsError

PARAMS = {"schema_version": "0.2", "seed": 70, "length_ms": 120}


@pytest.fixture(scope="module")
def sidecar_meta(tmp_path_factory) -> dict:
    """A sidecar written by the running engine, plus the sha256 of its WAV."""
    _, json_path = write_kick(PARAMS, tmp_path_factory.mktemp("written"), name="t70")
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    assert meta["engine"] == {"name": ENGINE_NAME, "version": ENGINE_VERSION}
    return meta


def _copy(meta: dict) -> dict:
    return json.loads(json.dumps(meta))


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


def _expect_rejected(folder: Path, doc, monkeypatch, error=ValidationError) -> None:
    """Write ``doc`` as a sidecar, re-render it, expect ``error`` before any render and no
    change to the folder."""
    path = folder / "t70.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    before = _snapshot(folder)
    if error is ValidationError:

        def no_render(params):
            raise AssertionError("rendered a sidecar that does not match the contract")

        monkeypatch.setattr(io_mod, "render_kick_wav", no_render)
    with pytest.raises(error):
        rerender_from_sidecar(path)
    with pytest.raises(error):
        rerender_from_sidecar(path, allow_engine_mismatch=True)
    assert _snapshot(folder) == before


# --- positive control ------------------------------------------------------------------------


def test_untampered_sidecar_rerenders_its_wav(sidecar_meta, tmp_path) -> None:
    path = tmp_path / "t70.json"
    path.write_text(json.dumps(sidecar_meta), encoding="utf-8")
    before = _snapshot(tmp_path)
    wav = rerender_from_sidecar(path)
    assert hashlib.sha256(wav).hexdigest() == sidecar_meta["sha256"]
    assert _snapshot(tmp_path) == before


# --- curated tampering -----------------------------------------------------------------------


def _tamper(meta: dict, case: str):
    m = _copy(meta)
    match case:
        case "missing engine":
            del m["engine"]
        case "missing parameters":
            del m["parameters"]
        case "missing schema_version":
            del m["schema_version"]
        case "engine is a string":
            m["engine"] = f"{ENGINE_NAME} {ENGINE_VERSION}"
        case "engine is a list":
            m["engine"] = [ENGINE_NAME, ENGINE_VERSION]
        case "engine is null":
            m["engine"] = None
        case "engine without version":
            del m["engine"]["version"]
        case "engine version is a number":
            m["engine"]["version"] = 0.1
        case "engine unknown field":
            m["engine"]["build"] = "x"
        case "parameters is a string":
            m["parameters"] = json.dumps(m["parameters"])
        case "parameters is null":
            m["parameters"] = None
        case "unknown top-level field":
            m["seed_override"] = 1
        case "schema_version 0.2":
            m["schema_version"] = "0.2"
        case "schema_version 0.0":
            m["schema_version"] = "0.0"
        case "schema_version as number":
            m["schema_version"] = 0.1
        case "category snare":
            m["category"] = "snare"
        case "file without .wav":
            m["file"] = "t70.json"
        case "features unknown field":
            m["features"]["loudness_lufs"] = -8.0
        case "features without length_ms":
            del m["features"]["length_ms"]
        case "sha256 not hex":
            m["sha256"] = "z" * 64
        case "bpm as string":
            m["bpm"] = "128"
        case "root is a list":
            m = [m]
        case "root is a string":
            m = "t70.wav"
        case _:
            raise AssertionError(case)
    return m


CURATED = (
    "missing engine", "missing parameters", "missing schema_version", "engine is a string",
    "engine is a list", "engine is null", "engine without version", "engine version is a number",
    "engine unknown field", "parameters is a string", "parameters is null",
    "unknown top-level field", "schema_version 0.2", "schema_version 0.0",
    "schema_version as number", "category snare", "file without .wav", "features unknown field",
    "features without length_ms", "sha256 not hex", "bpm as string", "root is a list",
    "root is a string",
)


@pytest.mark.parametrize("case", CURATED)
def test_tampered_sidecar_is_rejected_before_rendering(
    sidecar_meta, tmp_path, monkeypatch, case
) -> None:
    _expect_rejected(tmp_path, _tamper(sidecar_meta, case), monkeypatch)


def test_invalid_parameters_inside_a_valid_sidecar_are_rejected(
    sidecar_meta, tmp_path, monkeypatch
) -> None:
    """The metadata contract leaves ``parameters`` open; the kick-params check behind it must
    still reject the tampered object, and nothing is written."""
    m = _copy(sidecar_meta)
    m["parameters"]["pitch_end_hz"] = 5  # below the kick-params minimum
    _expect_rejected(tmp_path, m, monkeypatch, error=KickParamsError)
    m = _copy(sidecar_meta)
    m["parameters"]["wobble"] = 1
    _expect_rejected(tmp_path, m, monkeypatch, error=KickParamsError)


# --- seeded random tampering -----------------------------------------------------------------

# JSON types each field accepts, written from the contract by hand. "integer" counts as number.
ROOT_TYPES = {
    "schema_version": set(),  # const "0.1": every replacement below differs from it
    "file": {"string"},  # pattern \.wav$ — the random strings below never end in .wav
    "category": set(),  # enum ["kick"]
    "description": {"string"},
    "engine": {"object"},
    "parameters": {"object"},
    "features": {"object"},
    "bpm": {"number", "null"},
    "key": {"string", "null"},
    "sha256": set(),  # pattern ^[0-9a-f]{64}$ — no random value below matches
    "created_at": {"string"},
}
ROOT_REQUIRED = ("schema_version", "file", "category", "engine", "parameters", "features",
                 "created_at")
ENGINE_TYPES = {"name": {"string"}, "version": {"string"}}
FEATURE_TYPES = {
    "peak_dbfs": {"number"},
    "length_ms": {"number"},
    "fundamental_hz": {"number", "null"},
    "decay_20db_ms": {"number", "null"},
    "decay_40db_ms": {"number", "null"},
    "dc_offset": {"number", "null"},
}
FEATURE_REQUIRED = ("peak_dbfs", "length_ms")
VALUES = {
    "null": [None],
    "boolean": [True, False],
    "number": [0, -1, 128, 0.1, -0.3, 1e9],
    # Never "0.1" or "kick": those would satisfy the const / enum fields above.
    "string": ["", "0.1 ", "Kick", "t70.wav ", "128"],
    "array": [[], ["kick"], [0.1]],
    "object": [{}, {"name": "x"}],
}
SEEDS = range(200)


def _wrong_value(rng: random.Random, allowed: set[str]):
    kinds = [k for k in VALUES if k not in allowed]
    return rng.choice(VALUES[rng.choice(kinds)])


def _random_tamper(meta: dict, rng: random.Random) -> tuple[dict, str]:
    m = _copy(meta)
    m.setdefault("description", "random tamper test")
    where = rng.choice(("root", "engine", "features"))
    target, types, required = {
        "root": (m, ROOT_TYPES, ROOT_REQUIRED),
        "engine": (m["engine"], ENGINE_TYPES, tuple(ENGINE_TYPES)),
        "features": (m["features"], FEATURE_TYPES, FEATURE_REQUIRED),
    }[where]
    action = rng.choice(("delete", "unknown", "wrong type"))
    if action == "delete":
        key = rng.choice(required)
        del target[key]
    elif action == "unknown":
        key = rng.choice(("seed", "Engine", "extra", "version_", "_"))
        target[key] = rng.choice([v for vs in VALUES.values() for v in vs])
    else:
        key = rng.choice(sorted(types))
        target[key] = _wrong_value(rng, types[key])
    return m, f"{where}.{key} {action}"


def test_random_tampered_sidecars_are_rejected(sidecar_meta, tmp_path, monkeypatch) -> None:
    """200 seeded single-field tamperings: a deleted required field, an unknown field or a
    value of a JSON type the contract does not allow, at the root, in ``engine`` or in
    ``features``."""
    seen = set()
    for seed in SEEDS:
        doc, label = _random_tamper(sidecar_meta, random.Random(seed))
        seen.add(label.split()[-1])
        folder = tmp_path / f"s{seed}"
        folder.mkdir()
        with monkeypatch.context() as mp:
            try:
                _expect_rejected(folder, doc, mp)
            except BaseException as exc:
                raise AssertionError(f"seed {seed}: {label} was not rejected: {exc!r}") from exc
    assert seen == {"delete", "unknown", "type"}
