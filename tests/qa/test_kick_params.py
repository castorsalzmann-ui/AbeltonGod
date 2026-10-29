"""Tests for the shared kick-params generator ``tests/support/kick_params.py`` (#105).

- **Pinned default draws.** The expected hashes were computed from the five *former* copies
  (``test_kick.random_params``, ``test_shaping._draw``, ``test_drive_continuity._draw``,
  ``test_contract_semantics._random_params``, ``test_drive_aliasing._random_params`` at
  origin/main 61088d1), not from the shared generator, so they are an independent
  reference. They cover values, Python types and key order. ``schema_version`` is left out:
  it is read from the contract and changes with every schema version.
- **Coverage against the contract.** Ranges are read here from the schema JSON and checked
  per field; a field added to the schema gets its own case automatically.
- **Fresh seeds.** ``--fresh-seeds`` must reach the generator in a real pytest process.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from support import kick_params as kp

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA = json.loads((ROOT / "contracts" / "kick-params.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
N_DRAWS = 4000
MIN_SPAN = 0.99  # drawn min..max must cover this share of the allowed range


def _encode(draws: list[dict]) -> str:
    rows = [
        [[k, type(v).__name__, repr(v)] for k, v in d.items() if k != "schema_version"]
        for d in draws
    ]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


# 2000 draws each, seeds 0..1999, from the former copies (see module docstring).
PINNED = {
    "render": ("random", "d18c4cec74112f9f0ea4fd5b59b79a094822d2b6e958e51de3d68e1c5aa3cf0c"),
    "no_drive": ("random", "5296ef35b83f4188de7d788d6ec4a28f12d21562c91df7f0ad75aed9a8530dff"),
    "settle": ("random", "748cbf0e834ea8ab18e910a2f7777ee423ef2899429408f9c632de6e26cca10e"),
    "aliasing": ("numpy", "9fa6fbffbf2d3e6fd388bb1eafffd9476187b6301aa76965f5d8c44970cc3150"),
}


@pytest.mark.parametrize("name", sorted(PINNED))
def test_default_draws_are_byte_identical_to_the_former_copies(name: str) -> None:
    source, expected = PINNED[name]
    make = random.Random if source == "random" else np.random.default_rng
    draws = [kp.draw(make(s), kp.PROFILES[name]) for s in range(2000)]
    assert _encode(draws) == expected


# --- coverage against the contract -----------------------------------------------------------


def _draws(profile: kp.Profile, base: int) -> list[dict]:
    make = kp.np_rng if profile is kp.ALIASING else kp.rng
    return [kp.draw(make(base + i), profile) for i in range(N_DRAWS)]


ALL_DRAWS = _draws(kp.ALL, 900_000)
PROFILE_DRAWS = {name: _draws(p, 910_000) for name, p in kp.PROFILES.items() if p is not kp.ALL}


def _schema_fields() -> list[str]:
    # schema_version is not a drawn field (const up to v0.2, enum since v0.3; #137).
    return [n for n, s in SCHEMA["properties"].items() if n != "schema_version"]


def _check_field(field: str, values: list, lo=None, hi=None) -> None:
    spec = SCHEMA["properties"][field]
    if "enum" in spec:
        assert set(values) == set(spec["enum"]), (field, set(values))
        assert all(type(v) is type(spec["enum"][0]) for v in values), field
        return
    if spec["type"] == "string":
        lengths = {len(v) for v in values}
        assert min(lengths) == spec.get("minLength", 0) and max(lengths) == spec["maxLength"]
        return
    lo = spec["minimum"] if lo is None else lo
    hi = spec["maximum"] if hi is None else hi
    want = int if spec["type"] == "integer" else float
    assert all(type(v) is want for v in values), field
    assert lo <= min(values) and max(values) <= hi, (field, min(values), max(values))
    if spec["type"] == "integer" and hi - lo < 100:
        assert set(values) == set(range(lo, hi + 1)), (field, sorted(set(values)))
    else:
        assert max(values) - min(values) >= MIN_SPAN * (hi - lo), (field, min(values), max(values))


@pytest.mark.parametrize("field", _schema_fields())
def test_all_profile_draws_every_schema_field_over_its_full_range(field: str) -> None:
    values = [d[field] for d in ALL_DRAWS]
    _check_field(field, values)


def test_all_profile_draws_bpm_over_60_to_200() -> None:
    """Named in #105: no former copy drew bpm."""
    bpm = [d["bpm"] for d in ALL_DRAWS]
    assert 60 <= min(bpm) < 60.2 and 199.8 < max(bpm) <= 200


@pytest.mark.parametrize("name", ["all", *sorted(PROFILE_DRAWS)])
def test_every_draw_is_a_valid_parameter_set(name: str) -> None:
    draws = ALL_DRAWS if name == "all" else PROFILE_DRAWS[name]
    for d in draws:
        errors = [e.message for e in VALIDATOR.iter_errors(d)]
        assert not errors, (d, errors)
        assert d["pitch_end_hz"] <= d["pitch_start_hz"], d
        assert list(d) == ["schema_version", *(kp.PROFILES[name].keys or kp.PROFILES[name].fields)]


# What each profile leaves out of the render fields, written here from QA report #69 (3.5).
OMITTED = {
    "render": set(),
    "no_drive": {"drive"},
    "settle": {"bit_depth", "pitch_decay_ms"},
    "aliasing": {"bit_depth", "peak_ceiling_dbfs"},
}
NARROWED = {"aliasing": {"drive": (0.01, 1)}}
ZERO_SPIKE = {"no_drive": {"amp_attack_ms"}, "aliasing": {"amp_attack_ms"}}
V02_RENDER_FIELDS = {
    "seed", "sample_rate", "bit_depth", "length_ms", "pitch_start_hz", "pitch_end_hz",
    "pitch_decay_ms", "amp_attack_ms", "amp_decay_ms", "click_level", "click_tone_hz", "drive",
    "tone", "peak_ceiling_dbfs",
}


def test_render_profile_draws_the_v02_render_fields() -> None:
    assert set(kp.RENDER.fields) == V02_RENDER_FIELDS
    assert set(kp.NOT_RENDER_DRAWN) == {"variants", "bpm", "preset"}
    assert not set(kp.NOT_RENDER_DRAWN) & set(kp.RENDER.fields)
    assert set(kp.ALL.fields) == set(_schema_fields())


@pytest.mark.parametrize("name", sorted(PROFILE_DRAWS))
def test_profile_fields_ranges_and_zero_share(name: str) -> None:
    draws = PROFILE_DRAWS[name]
    assert set(kp.PROFILES[name].fields) == V02_RENDER_FIELDS - OMITTED[name]
    for field in kp.PROFILES[name].fields:
        values = [d[field] for d in draws]
        lo, hi = NARROWED.get(name, {}).get(field, (None, None))
        if field == "pitch_end_hz":
            assert all(d["pitch_end_hz"] <= d["pitch_start_hz"] for d in draws)
        zeros = sum(v == 0 for v in values) / len(values)
        if field in ZERO_SPIKE.get(name, ()):
            assert 0.45 <= zeros <= 0.55, (field, zeros)
            values = [v for v in values if v != 0]
        elif SCHEMA["properties"][field].get("type") == "number":
            assert zeros == 0, (field, zeros)
        _check_field(field, values, lo, hi)


def test_profile_definitions_are_checked() -> None:
    with pytest.raises(ValueError, match="not in the kick-params schema"):
        kp.Profile("x", ("seed", "nope"))
    with pytest.raises(ValueError, match="outside"):
        kp.Profile("x", ("drive",), ranges={"drive": (0.0, 1.5)})
    with pytest.raises(ValueError, match="before"):
        kp.Profile("x", ("pitch_end_hz", "pitch_start_hz"))
    with pytest.raises(ValueError, match="permutation"):
        kp.Profile("x", ("seed", "drive"), keys=("seed",))
    with pytest.raises(TypeError):
        kp.draw(7)


# --- fresh seeds ------------------------------------------------------------------------------


def test_fresh_seeds_shift_every_seed_base_by_n_times_2_to_32() -> None:
    old = kp.fresh_seeds()
    try:
        kp.set_fresh_seeds(0)
        assert kp.rng(5).random() == random.Random(5).random()
        assert kp.np_rng(5).random() == np.random.default_rng(5).random()
        kp.set_fresh_seeds(3)
        assert kp.seed(5) == 5 + 3 * 2**32
        assert kp.rng(5).random() == random.Random(5 + 3 * 2**32).random()
        assert kp.np_rng(5).random() == np.random.default_rng(5 + 3 * 2**32).random()
        assert kp.rng(5).random() != random.Random(5).random()
    finally:
        kp.set_fresh_seeds(old)


@pytest.mark.parametrize("bad", [-1, 1.0, True, "2"])
def test_fresh_seeds_refuse_bad_values(bad) -> None:
    with pytest.raises(ValueError):
        kp.set_fresh_seeds(bad)


def _collect(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")])}
    cmd = [
        sys.executable, "-m", "pytest", "-n", "0", "-p", "no:cacheprovider", "--collect-only",
        "-o", "pythonpath=src", "tests/audio_engine/test_drive_aliasing.py", *args,
    ]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)


def _aliasing_ids(stdout: str) -> list[str]:
    return re.findall(r"test_random_case_aliasing_is_bounded\[(seed\d+)\]", stdout)


def test_fresh_seeds_option_reaches_the_generator() -> None:
    """A real pytest process: the drawn kick seeds (they are the test ids) change, and they are
    exactly the ones of the shifted streams; the header names the shift."""
    default, fresh = _collect(), _collect("--fresh-seeds=2")
    assert default.returncode == 0 and fresh.returncode == 0, fresh.stdout[-2000:]
    old_ids, new_ids = _aliasing_ids(default.stdout), _aliasing_ids(fresh.stdout)
    assert len(old_ids) == len(new_ids) == 32
    assert not set(old_ids) & set(new_ids)
    first = kp.draw(np.random.default_rng(1300 + 2 * 2**32), kp.ALIASING)
    assert new_ids[0] == f"seed{first['seed']}"
    assert "fresh seeds: 2" in fresh.stdout and "fresh seeds" not in default.stdout


def test_negative_fresh_seeds_is_a_usage_error() -> None:
    run = _collect("--fresh-seeds=-1")
    assert run.returncode == 4, run.stdout[-2000:] + run.stderr[-2000:]
    assert "--fresh-seeds must be >= 0" in run.stdout + run.stderr


# --- call sites --------------------------------------------------------------------------------

CALL_SITE_MODULES = [
    "test_kick.py", "test_shaping.py", "test_drive_continuity.py",
    "test_contract_semantics.py", "test_drive_aliasing.py",
]


@pytest.mark.parametrize("module", CALL_SITE_MODULES)
def test_former_copies_seed_only_through_the_shared_generator(module: str) -> None:
    """Every random stream in these modules comes from kp.rng / kp.np_rng, so --fresh-seeds
    reaches all of them."""
    text = (ROOT / "tests" / "audio_engine" / module).read_text(encoding="utf-8")
    assert "kick_params as kp" in text
    assert not re.findall(r"random\.Random\(|default_rng\(|random\.seed\(", text), module


# Generator function per module and the profile it must use (QA report #69, 3.5).
CALL_SITES = [
    ("test_kick.py", "random_params", "render"),
    ("test_shaping.py", "_draw", "render"),
    ("test_drive_continuity.py", "_draw", "no_drive"),
    ("test_contract_semantics.py", "_random_params", "settle"),
    ("test_drive_aliasing.py", "_random_params", "aliasing"),
]


@pytest.mark.parametrize(("module", "function", "profile"), CALL_SITES)
def test_call_site_draws_its_profile(module: str, function: str, profile: str) -> None:
    path = ROOT / "tests" / "audio_engine" / module
    spec = importlib.util.spec_from_file_location(f"_qa105_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    make = np.random.default_rng if profile == "aliasing" else random.Random
    got = [getattr(mod, function)(make(s)) for s in range(200)]
    assert _encode(got) == _encode([kp.draw(make(s), kp.PROFILES[profile]) for s in range(200)])
