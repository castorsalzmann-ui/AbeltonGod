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
from support import kick_params as kp

import audio_engine.io as io_mod
from audio_engine import ENGINE_NAME, ENGINE_VERSION
from audio_engine.io import rerender_from_sidecar, write_kick
from audio_engine.params import KickParamsError

PARAMS = {"schema_version": "0.2", "seed": 70, "length_ms": 120}


@pytest.fixture(scope="module")
def sidecar_meta(tmp_path_factory) -> dict:
    """The metadata of a sidecar written by the running engine (its ``sha256`` names the WAV)."""
    _, json_path = write_kick(PARAMS, tmp_path_factory.mktemp("written"), name="t70")
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    assert meta["engine"] == {"name": ENGINE_NAME, "version": ENGINE_VERSION}
    return meta


def _copy(meta: dict) -> dict:
    return json.loads(json.dumps(meta))


def _snapshot(root: Path) -> dict[str, bytes | None]:
    """Every file (its bytes) and every folder (``None``) below ``root``."""
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in root.rglob("*")
    }


def _expect_rejected(
    root: Path, doc, monkeypatch, error=ValidationError, sub: str = "case"
) -> None:
    """Write ``doc`` as ``root/<sub>/t70.json``, re-render it, expect ``error`` before any
    render and no change anywhere below ``root``.

    ``root`` is the test's own ``tmp_path`` (never shared between xdist workers), and the
    sidecar sits one folder below it, so a write next to the sidecar, into its parent folder
    or a new folder all show up in the snapshot (review of PR #84, mutant W4)."""
    folder = root / sub
    folder.mkdir(exist_ok=True)
    path = folder / "t70.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    before = _snapshot(root)
    if error is ValidationError:

        def no_render(params):
            raise AssertionError("rendered a sidecar that does not match the contract")

        monkeypatch.setattr(io_mod, "render_kick_wav", no_render)
    with pytest.raises(error):
        rerender_from_sidecar(path)
    with pytest.raises(error):
        rerender_from_sidecar(path, allow_engine_mismatch=True)
    assert _snapshot(root) == before


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


SECTIONS = {
    "root": (ROOT_TYPES, ROOT_REQUIRED),
    "engine": (ENGINE_TYPES, tuple(ENGINE_TYPES)),
    "features": (FEATURE_TYPES, FEATURE_REQUIRED),
}
UNKNOWN_KEYS = ("seed", "Engine", "extra", "version_", "_")
ALL_VALUES = [v for vs in VALUES.values() for v in vs]


def _apply(meta: dict, where: str, key: str, action: str, value=None) -> dict:
    """One tampering: ``delete`` a field, add an ``unknown`` one, or set a ``wrong type``."""
    m = _copy(meta)
    m.setdefault("description", "tamper test")
    target = m if where == "root" else m[where]
    if action == "delete":
        del target[key]
    else:
        target[key] = value
    return m


# Exhaustive (review of PR #84): every required field deleted, an unknown field in every
# section, and every field set to one value of every JSON kind it does not allow.
EXHAUSTIVE = [
    *((where, key, "delete", None) for where, (_, req) in SECTIONS.items() for key in req),
    *((where, "extra", "unknown", 1) for where in SECTIONS),
    *(
        (where, key, "wrong type", VALUES[kind][0])
        for where, (types, _) in SECTIONS.items()
        for key in types
        for kind in VALUES
        if kind not in types[key]
    ),
]
EXHAUSTIVE_IDS = [
    f"{w}.{k} {a}" + (f" {type(v).__name__}" if a == "wrong type" else "")
    for w, k, a, v in EXHAUSTIVE
]


def test_exhaustive_set_covers_every_field_and_action() -> None:
    """Coverage is asserted, not hoped for from the random seeds."""
    deleted = {(w, k) for w, k, a, _ in EXHAUSTIVE if a == "delete"}
    assert deleted == {(w, k) for w, (_, req) in SECTIONS.items() for k in req}
    assert {w for w, _, a, _ in EXHAUSTIVE if a == "unknown"} == set(SECTIONS)
    retyped = {(w, k, _kind(v)) for w, k, a, v in EXHAUSTIVE if a == "wrong type"}
    expected = {
        (w, k, kind)
        for w, (types, _) in SECTIONS.items()
        for k in types
        for kind in VALUES
        if kind not in types[k]
    }
    assert retyped == expected
    # Every field of the contract gets a wrong type, root.file and root.bpm included.
    assert {(w, k) for w, k, _ in retyped} == {
        *(("root", k) for k in ROOT_TYPES),
        *(("engine", k) for k in ENGINE_TYPES),
        *(("features", k) for k in FEATURE_TYPES),
    }
    assert {("root", "file"), ("root", "bpm")} <= {(w, k) for w, k, _ in retyped}
    assert len(ROOT_TYPES) == 11 and len(ENGINE_TYPES) == 2 and len(FEATURE_TYPES) == 6


def _kind(value) -> str:
    if value is None:
        return "null"
    for kind, py in (("boolean", bool), ("number", int | float), ("string", str),
                     ("array", list), ("object", dict)):
        if isinstance(value, py):
            return kind
    raise AssertionError(value)


@pytest.mark.parametrize(("where", "key", "action", "value"), EXHAUSTIVE, ids=EXHAUSTIVE_IDS)
def test_every_field_tampering_is_rejected(
    sidecar_meta, tmp_path, monkeypatch, where, key, action, value
) -> None:
    _expect_rejected(tmp_path, _apply(sidecar_meta, where, key, action, value), monkeypatch)


def _random_tamper(meta: dict, rng: random.Random) -> tuple[dict, str]:
    where = rng.choice(sorted(SECTIONS))
    types, required = SECTIONS[where]
    action = rng.choice(("delete", "unknown", "wrong type"))
    value = None
    if action == "delete":
        key = rng.choice(required)
    elif action == "unknown":
        key = rng.choice(UNKNOWN_KEYS)
        value = rng.choice(ALL_VALUES)
    else:
        key = rng.choice(sorted(types))
        value = rng.choice(VALUES[rng.choice([k for k in VALUES if k not in types[key]])])
    return _apply(meta, where, key, action, value), f"{where}.{key} {action}"


def test_random_tampered_sidecars_are_rejected(sidecar_meta, tmp_path, monkeypatch) -> None:
    """200 seeded single-field tamperings with random values (the exhaustive set above uses
    one value per JSON kind). The whole ``tmp_path`` is the snapshot root for every seed."""
    seen = set()
    for seed in SEEDS:
        doc, label = _random_tamper(sidecar_meta, kp.rng(seed))
        seen.add(label.split(" ", 1)[1])
        with monkeypatch.context() as mp:
            try:
                _expect_rejected(tmp_path, doc, mp, sub=f"s{seed}")
            except BaseException as exc:
                raise AssertionError(f"seed {seed}: {label} was not rejected: {exc!r}") from exc
    assert seen == {"delete", "unknown", "wrong type"}
