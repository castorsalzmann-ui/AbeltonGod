"""``--fresh-seeds`` reaches every listed property test: checked by behaviour (#119).

Replaces the text check of #105 (no ``random.Random(`` in five files), which missed any other
spelling and every file it did not list. Here two real pytest processes, at
``--fresh-seeds=0`` and ``--fresh-seeds=1``, run with the probe plugin
``tests/support/seed_probe.py`` and are compared by ``scripts/qa/seed_reach.py``:

- **Seedings.** Every RNG seeding made by the listed modules at collection (module level,
  parametrize) and in the bodies of :data:`BODY_SITES` must take new seed values at fresh 1.
- **Parametrize values.** Each random-derived parametrize value (:data:`RANDOM_PARAMS`,
  written here from the modules) must change. Curated values are not required to stay; the
  default run pins them.
- **A planted bypass is caught.** A throwaway test tree with one bypass of each kind
  (module level, parametrize, test body) must be reported, its routed twin must not.

Boundary: a body seeding in a test not listed in :data:`BODY_SITES` is not seen here; the
whole-suite audit ``python scripts/qa/seed_reach.py --run tests`` sees those.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("qa_seed_reach", ROOT / "scripts/qa/seed_reach.py")
seed_reach = importlib.util.module_from_spec(_spec)
sys.modules["qa_seed_reach"] = seed_reach
_spec.loader.exec_module(seed_reach)

AE, LIB = "tests/audio_engine", "tests/library"
MODULES = [
    f"{AE}/test_kick.py", f"{AE}/test_shaping.py", f"{AE}/test_drive_continuity.py",
    f"{AE}/test_contract_semantics.py", f"{AE}/test_drive_aliasing.py",
    f"{AE}/test_presets_variants.py", f"{AE}/test_wav_sidecar_robustness.py",
    f"{AE}/test_tampered_sidecars.py", f"{LIB}/test_layout.py",
]

# Tests that seed inside their body (node-id prefixes; for a parametrized one the first case
# is enough: every case runs the same seeding line).
BODY_SITES = [
    f"{AE}/test_drive_aliasing.py::test_oversampled_matches_direct_convolution[1-1]",
    f"{AE}/test_drive_aliasing.py::test_spectrum_cache_separates_factors",
    f"{AE}/test_presets_variants.py::test_random_variant_renders_are_deterministic_and_clean",
    f"{AE}/test_wav_sidecar_robustness.py::test_wav_chunks_are_word_aligned_for_any_sample_count[0-16]",
    f"{AE}/test_wav_sidecar_robustness.py::test_even_sample_counts_keep_the_previous_bytes",
    f"{AE}/test_wav_sidecar_robustness.py::test_random_kicks_are_always_word_aligned",
    f"{AE}/test_tampered_sidecars.py::test_random_tampered_sidecars_are_rejected",
    f"{LIB}/test_layout.py::test_windows_name_rules_agree_with_ntpath_isreserved[0]",
    f"{LIB}/test_layout.py::test_random_placements_keep_every_rule[0]",
    f"{LIB}/test_layout.py::test_random_placements_rerender_byte_identically[0]",
]

# function -> (argument name, regex of the ids whose value is drawn). Written from the modules.
_ALL_SETS = ("p", r"random-\d+")
RANDOM_PARAMS = {
    **{f"{AE}/test_kick.py::{fn}": _ALL_SETS for fn in (
        "test_same_params_and_seed_give_identical_wav", "test_signal_properties",
        "test_quantised_file_peak_never_exceeds_ceiling",
        "test_measured_tail_pitch_matches_parameters",
        "test_analysis_measures_the_real_signal",
        "test_dc_correction_is_small_so_real_dc_faults_stay_visible",
        "test_sidecar_validates_and_rerenders_identical_wav",
    )},
    f"{AE}/test_kick.py::test_first_sample_is_zero_for_any_seed": ("seed", r".*"),
    f"{AE}/test_kick.py::test_fast_decay_short_kicks_are_measured_correctly_or_reported_unmeasurable":
        ("p", r"p[1-9]\d*"),  # p0 is the curated review case
    **{f"{AE}/test_shaping.py::{fn}": _ALL_SETS for fn in (
        "test_amp_decay_sets_the_decay_rate", "test_decay_20db_is_a_third_of_amp_decay",
        "test_drive_lowers_crest_factor",
        "test_drive_moves_the_sound_further_from_the_clean_render",
        "test_full_drive_lowers_crest_factor_with_click_and_dark_tone",
        "test_time_to_envelope_peak_follows_amp_attack", "test_tone_brightens_at_every_step",
        "test_tone_extremes_have_the_expected_size",
    )},
    f"{AE}/test_shaping.py::test_drive_adds_third_harmonic_at_every_step": ("p", r"steady-\d+"),
    f"{AE}/test_drive_continuity.py::test_change_from_clean_is_small_and_grows_monotonically":
        _ALL_SETS,
    f"{AE}/test_drive_continuity.py::test_change_near_zero_matches_first_order_reference":
        ("p", r".*-random-\d+"),
    f"{AE}/test_drive_aliasing.py::test_random_case_aliasing_is_bounded": ("params", r".*"),
}


@pytest.fixture(scope="module")
def probes() -> tuple[dict, dict]:
    return seed_reach.probe_pair(MODULES, 1, run_only=BODY_SITES)


def test_every_seeding_in_the_listed_modules_shifts(probes) -> None:
    seeds = seed_reach.compare_seeds(*probes)
    assert seeds, "the probe saw no seeding at all"
    bad = seed_reach.unshifted(seeds)
    assert not bad, bad
    one_sided = {k: v for k, v in seeds.items() if "only_in" in v}
    assert not one_sided, one_sided
    unseeded = [k for k, v in seeds.items() if v.get("unseeded")]
    assert not unseeded, unseeded  # an unseeded stream is not reproducible at all


def test_every_body_site_was_run_and_seeded(probes) -> None:
    """A renamed or moved test would otherwise drop out of the check silently."""
    for doc in probes:
        phases = {s["phase"] for s in doc["seeds"]}
        for site in BODY_SITES:
            if any(n.startswith(site) for n in doc["skipped"]):
                continue  # e.g. the ntpath reference test before Python 3.13
            assert any(p.startswith(site) for p in phases), (doc["fresh"], site)


def test_every_random_parametrize_value_changes(probes) -> None:
    stuck = seed_reach.stuck(seed_reach.compare_params(*probes), RANDOM_PARAMS)
    assert not stuck, stuck


# --- the comparison catches a planted bypass ---------------------------------------------------

PLANTED_CONFTEST = """
import importlib.util
_s = importlib.util.spec_from_file_location("_root_conftest", {conftest!r})
_m = importlib.util.module_from_spec(_s)
_s.loader.exec_module(_m)
pytest_addoption, pytest_configure = _m.pytest_addoption, _m.pytest_configure
"""

PLANTED_TEST = '''
import random

import pytest
from support import kick_params as kp

ROUTED = [kp.rng(10 + i).random() for i in range(3)]
BYPASS = [random.Random(20 + i).random() for i in range(3)]


@pytest.mark.parametrize("x", ROUTED)
def test_routed_values(x):
    pass


@pytest.mark.parametrize("x", BYPASS)
def test_bypassed_values(x):
    pass


@pytest.mark.parametrize("seed", [kp.kick_seed(s) for s in range(3)])
def test_routed_kick_seeds(seed):
    pass


@pytest.mark.parametrize("seed", range(3))
def test_bypassed_kick_seeds(seed):
    pass


def test_routed_body():
    kp.np_rng(30).random()


def test_bypassed_body():
    __import__("numpy").random.default_rng(40).random()


def test_tmp_path_works(tmp_path):
    assert tmp_path.is_dir()  # the probe's basetemp parent did not exist in this tree
'''


def test_planted_bypass_is_reported_and_routed_twin_is_not(tmp_path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text(
        PLANTED_CONFTEST.format(conftest=str(ROOT / "tests" / "conftest.py")), encoding="utf-8")
    (tests / "test_planted.py").write_text(textwrap.dedent(PLANTED_TEST), encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    a, b = seed_reach.probe_pair(["tests"], 1, run=True, root=tmp_path)
    assert a["exit"] == b["exit"] == 0
    seeds = seed_reach.compare_seeds(a, b)
    assert set(seed_reach.unshifted(seeds)) == {
        "tests/test_planted.py:8 @ collect",
        "tests/test_planted.py:36 @ tests/test_planted.py::test_bypassed_body",
    }, seeds
    assert "tests/test_planted.py:7 @ collect" in seeds  # the routed twin was seen, and shifted
    assert "tests/test_planted.py:32 @ tests/test_planted.py::test_routed_body" in seeds
    spec = {f"tests/test_planted.py::{fn}": (arg, r".*") for fn, arg in (
        ("test_routed_values", "x"), ("test_bypassed_values", "x"),
        ("test_routed_kick_seeds", "seed"), ("test_bypassed_kick_seeds", "seed"),
        ("test_renamed_away", "x"),
    )}
    stuck = seed_reach.stuck(seed_reach.compare_params(a, b), spec)
    assert set(stuck) == {f"tests/test_planted.py::{fn}" for fn in (
        "test_bypassed_values", "test_bypassed_kick_seeds", "test_renamed_away")}, stuck
    assert len(stuck["tests/test_planted.py::test_bypassed_kick_seeds"]) == 3
    assert stuck["tests/test_planted.py::test_renamed_away"].startswith("no case")
