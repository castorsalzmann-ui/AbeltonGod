"""Tests for the opt-in render cache ``tests/support/render_cache.py`` (#77).

The reference is always a direct ``render_kick`` call (the engine itself, no cache code), and
the comparison is byte for byte on the samples plus equality of the resolved parameters.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from support import render_cache as rc

import audio_engine.io as io_mod
import audio_engine.kick as kick_mod

ROOT = Path(__file__).resolve().parent.parent.parent

BASE = {"schema_version": "0.2", "seed": 7}


def _draw(rng: random.Random) -> dict:
    """Own uniform draw over the kick-params range (independent of the test modules)."""
    p = {
        "schema_version": "0.2",
        "seed": rng.randrange(2**32),
        "sample_rate": rng.choice([44100, 48000]),
        "bit_depth": rng.choice([16, 24]),
        "length_ms": rng.uniform(80, 400),
        "pitch_start_hz": rng.uniform(60, 600),
        "pitch_decay_ms": rng.uniform(2, 300),
        "amp_attack_ms": rng.uniform(0, 20),
        "amp_decay_ms": rng.uniform(20, 2000),
        "click_level": rng.uniform(0, 1),
        "click_tone_hz": rng.uniform(500, 12000),
        "drive": rng.uniform(0, 1),
        "tone": rng.uniform(-1, 1),
        "peak_ceiling_dbfs": rng.uniform(-12, -0.1),
    }
    p["pitch_end_hz"] = rng.uniform(30, min(120, p["pitch_start_hz"]))
    return p


SAMPLE = [dict(BASE), {**BASE, "drive": 0.0, "click_level": 0.0}] + [
    _draw(random.Random(77_000 + i)) for i in range(10)
]


@pytest.fixture(autouse=True)
def _fresh_cache():
    rc.clear()
    yield
    rc.clear()


def _same(a: tuple, b: tuple) -> bool:
    return a[0].dtype == b[0].dtype and a[0].tobytes() == b[0].tobytes() and a[1] == b[1]


def test_cache_on_equals_cache_off() -> None:
    """Interleaved: every set is stored first, then each hit is compared with a fresh direct
    render, so a hit that returns another set's render (stale or wrong key) fails here."""
    for p in SAMPLE:
        rc.cached_render_kick(p)
    assert rc.stats == {"hits": 0, "misses": len(SAMPLE), "bypassed": 0}
    for p in reversed(SAMPLE):
        assert _same(rc.cached_render_kick(p), kick_mod.render_kick(p)), p
    assert rc.stats["hits"] == len(SAMPLE)


def test_hits_are_read_only_and_isolated() -> None:
    """Miss and hit results: the array cannot be written, and editing a returned dict does
    not change what the next call gets."""
    reference = kick_mod.render_kick(BASE)
    for expected_hits in (1, 2, 3):
        audio, resolved = rc.cached_render_kick(BASE)
        assert not audio.flags.writeable
        with pytest.raises(ValueError):
            audio[0] = 1.0
        resolved["drive"] = 99.0
        again, resolved_again = rc.cached_render_kick(BASE)
        assert rc.stats["hits"] == expected_hits * 2 - 1
        assert _same((again, resolved_again), reference)
        resolved_again["seed"] = -1


def test_planted_stale_entry_is_refused() -> None:
    """Fault injection inside the store: the entry for BASE holds the render of seed 8. A hit
    must raise, never hand out the other render."""
    rc.cached_render_kick({**BASE, "seed": 8})
    rc._store[rc.cache_key(BASE)] = rc._store[rc.cache_key({**BASE, "seed": 8})]
    with pytest.raises(rc.StaleRenderError):
        rc.cached_render_kick(BASE)
    assert rc.stats["hits"] == 0


def test_hit_check_ignores_batch_only_params() -> None:
    p = {**BASE, "variants": 3}
    rc.cached_render_kick(p)
    assert _same(rc.cached_render_kick(p), kick_mod.render_kick(p))
    assert rc.stats["hits"] == 1


def test_input_dict_is_not_stored_by_reference() -> None:
    p = dict(BASE)
    rc.cached_render_kick(p)
    p["seed"] = 8
    assert _same(rc.cached_render_kick({**BASE, "seed": 8}), kick_mod.render_kick(p))
    assert rc.stats["hits"] == 0


@pytest.mark.parametrize(
    "value",
    [np.float64(0.5), np.int64(3), [1], {"a": 1}],
    ids=["np.float64", "np.int64", "list", "dict"],
)
def test_non_plain_values_bypass_the_cache(value) -> None:
    assert rc.cache_key({**BASE, "drive": value}) is None
    assert rc.cache_key(["not", "a", "dict"]) is None


def test_int_and_float_are_different_keys() -> None:
    assert rc.cache_key({**BASE, "seed": 7}) != rc.cache_key({**BASE, "seed": 7.0})
    assert rc.cache_key({"b": 1, "a": 2}) == rc.cache_key({"a": 2, "b": 1})


def test_patched_engine_bypasses_the_cache(monkeypatch) -> None:
    """A primed entry must not be served while any engine module attribute is replaced, and
    a render made while patched must not be stored."""
    clean = rc.cached_render_kick(BASE)
    monkeypatch.setattr(kick_mod, "_remove_mean", lambda x: x)
    assert not rc.engine_untouched()
    patched = rc.cached_render_kick(BASE)
    assert _same(patched, kick_mod.render_kick(BASE))  # really rendered with the patch
    assert not _same(patched, clean)
    assert rc.stats == {"hits": 0, "misses": 1, "bypassed": 1}
    monkeypatch.undo()
    assert rc.engine_untouched()
    assert _same(rc.cached_render_kick(BASE), clean)
    assert rc.stats["hits"] == 1


def test_patch_added_during_a_render_is_not_stored(monkeypatch) -> None:
    real = kick_mod.render_kick

    def patching_render(params):
        monkeypatch.setattr(kick_mod, "_SNEAKY", 1, raising=False)
        return real(params)

    monkeypatch.setattr(rc, "_engine", patching_render)
    rc.cached_render_kick(BASE)
    monkeypatch.undo()
    assert rc.cached_render_kick(BASE) is not None
    assert rc.stats["hits"] == 0


def test_monkeypatch_tests_are_never_cached(monkeypatch) -> None:
    monkeypatch.delenv(rc.ENV_SWITCH, raising=False)  # also valid in a cache-off run
    key = sorted(rc.CACHED_TESTS)[0]
    assert rc.should_cache(key, ["p"])
    assert not rc.should_cache(key, ["p", "monkeypatch"])
    assert not rc.should_cache("tests/audio_engine/test_kick.py::test_unlisted", ["p"])


def test_env_switch_turns_the_cache_off(monkeypatch) -> None:
    key = sorted(rc.CACHED_TESTS)[0]
    monkeypatch.setenv(rc.ENV_SWITCH, "0")
    assert not rc.should_cache(key, [])


def test_memory_bound_drops_oldest_first(monkeypatch) -> None:
    monkeypatch.setattr(rc, "MAX_BYTES", 1)
    rc.cached_render_kick(BASE)
    rc.cached_render_kick({**BASE, "seed": 8})
    assert list(rc._store) == [rc.cache_key({**BASE, "seed": 8})]
    assert rc._bytes == rc._store[rc.cache_key({**BASE, "seed": 8})][0].nbytes


def test_cache_is_not_left_installed_outside_listed_tests() -> None:
    assert io_mod.render_kick is not rc.cached_render_kick
    assert kick_mod.render_kick is not rc.cached_render_kick


DETERMINISM_WORDS = ("identical", "determin", "reproduc", "golden", "byte", "pinned", "same")


def test_allow_list_names_existing_read_only_tests() -> None:
    """Every listed test exists (a rename would silently drop the saving) and none of them is
    a determinism or byte-identity test."""
    for key in rc.CACHED_TESTS:
        path, name = key.split("::")
        assert (ROOT / path).is_file(), key
        assert f"def {name}(" in (ROOT / path).read_text(encoding="utf-8"), key
        assert not any(w in name for w in DETERMINISM_WORDS), key


# --- render counter: determinism and golden tests call the engine directly -------------------

GOLDEN = "tests/audio_engine/test_engine_version.py::test_golden_sha256"
DETERMINISM = "tests/audio_engine/test_kick.py::test_same_params_and_seed_give_identical_wav"
SIGNAL = "tests/audio_engine/test_kick.py::test_signal_properties"
ANALYSIS = "tests/audio_engine/test_kick.py::test_analysis_measures_the_real_signal"
# Three cases of the two cached tests are enough to show the cache is active where listed;
# all 161 would re-render 161 kicks in the subprocess for no extra evidence.
CACHED_CASES = ("defaults", "random-0", "random-1")
COUNTED = [GOLDEN, DETERMINISM] + [f"{t}[{c}]" for t in (SIGNAL, ANALYSIS) for c in CACHED_CASES]


def test_render_counter_shows_direct_engine_calls(tmp_path) -> None:
    """Runs all 5 golden hashes, all 20 determinism cases and three cases of two cached tests
    in one fresh process with the render counter. Golden: 1 real render each, determinism: 2
    real renders each, no cache hit in either (they sit next to cached tests that share their
    inputs: defaults and random-0/1 are among the 20 determinism sets). The cached tests share
    renders (signal_properties renders, analysis_measures only hits)."""
    out = tmp_path / "counter.json"
    # The plugin loads before any conftest, so src/ and tests/ go on PYTHONPATH explicitly.
    path = os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")])
    env = {**os.environ, "RENDER_COUNTER_OUT": str(out), "PYTHONPATH": path}
    env.pop(rc.ENV_SWITCH, None)
    cmd = [
        sys.executable, "-m", "pytest", "-n", "0", "-q", "-p", "no:cacheprovider",
        "-p", "support.render_counter",
        "--basetemp", str(tmp_path / "bt"),
        *COUNTED,
    ]
    run = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    tests = json.loads(out.read_text(encoding="utf-8"))["tests"]

    def rows(prefix: str) -> list[dict]:
        return [r for node, r in tests.items() if node.startswith(prefix + "[")]

    golden = rows(GOLDEN)
    assert len(golden) == 5
    assert all(r["renders"] == 1 and r["cache_hits"] == 0 for r in golden)
    determinism = rows(DETERMINISM)
    assert len(determinism) == 20
    assert all(r["renders"] == 2 and r["cache_hits"] == 0 for r in determinism)
    signal, analysis = rows(SIGNAL), rows(ANALYSIS)
    assert len(signal) == len(analysis) == len(CACHED_CASES)
    # The determinism tests run first and render the same sets, but outside the cache, so
    # signal_properties still renders each once and analysis_measures only gets hits.
    assert all(r["renders"] == 1 and r["cache_hits"] == 0 for r in signal)
    assert all(r["renders"] == 0 and r["cache_hits"] == 1 for r in analysis)
