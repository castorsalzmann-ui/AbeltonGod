"""Issue #3 (Phase 01b): presets and variants.

Independent references: preset values, derived seeds and the spread widths are written here as
literals (from the accepted design, issue #3 comment 6475695833), not read from the code under
test. Signal checks reuse the Phase 01a reference helpers of ``test_kick.py`` (closed-form
pitch mean, WAV decoding with the stdlib ``wave`` module).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from datetime import UTC, datetime

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from support import kick_params as kp
from test_kick import (
    FUNDAMENTAL_TOLERANCE,
    FUNDAMENTAL_TOLERANCE_SHORT,
    SHORT_WINDOW_MS,
    analytic_signal_frequency,
    crossing_interval,
    decode_wav,
    random_params,
    theoretical_mean_frequency,
)

from audio_engine.analysis import analyse, tail_window
from audio_engine.io import render_kick_wav, rerender_from_sidecar, write_kick
from audio_engine.kick import render_kick
from audio_engine.params import (
    KICK_SCHEMA_FILE,
    METADATA_SCHEMA_FILE,
    load_schema,
    max_settled_pitch_decay_ms,
    pitch_settles,
    resolve_kick_params,
)
from audio_engine.presets import (
    DESCRIPTIONS,
    PRESETS_DIR,
    UnknownPresetError,
    describe,
    load_preset,
    preset_names,
)
from audio_engine.variants import VariantError, derived_seed, make_variant, make_variants

FIXED_TIME = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
COMMON = {"schema_version": "0.2", "sample_rate": 48000, "bit_depth": 24,
          "peak_ceiling_dbfs": -0.3}
# The accepted design (issue #3), written out: seed, length, start, end, tau, attack, decay,
# click level, click tone, drive, tone. centre's tau is 40 ms since #59 (was 8; the user chose
# 40 by ear in the #3 listening test).
EXPECTED_PRESETS = {
    "centre": (1001, 480, 200, 52, 40, 0.5, 560, 0.35, 3500, 0.0, 0.0),
    "dark-dry": (1002, 450, 160, 47, 9, 0.5, 500, 0.12, 2500, 0.0, -0.4),
    # #116: centre + drive 0.45, the user's pick in listening tests 1 and 2 (#103). Same seed
    # as centre on purpose: it must render the exact file the user chose.
    "dense": (1001, 480, 200, 52, 40, 0.5, 560, 0.35, 3500, 0.45, 0.0),
    "punchy": (1003, 400, 260, 56, 6, 0.3, 420, 0.6, 4500, 0.15, 0.3),
    "rumble-ready": (1004, 750, 180, 49, 10, 1.0, 800, 0.2, 3000, 0.0, -0.2),
    "driven": (1005, 420, 300, 58, 6, 0.2, 380, 1.0, 5000, 0.45, 0.6),
}
FIELDS = ("seed", "length_ms", "pitch_start_hz", "pitch_end_hz", "pitch_decay_ms",
          "amp_attack_ms", "amp_decay_ms", "click_level", "click_tone_hz", "drive", "tone")
NAMES = sorted(EXPECTED_PRESETS)
DC_THRESHOLD = 1e-9

# Spread widths of the accepted design, written here: (kind, half width).
SPREAD_SPEC = {
    "click_level": ("abs", 0.12),
    "click_tone_hz": ("oct", 0.5),
    "pitch_end_hz": ("rel", 0.04),
    "pitch_start_hz": ("rel", 0.10),
    "pitch_decay_ms": ("rel", 0.20),
    "amp_decay_ms": ("rel", 0.10),
    "drive": ("abs", 0.05),
    "tone": ("abs", 0.10),
}
FIXED_FIELDS = ("length_ms", "amp_attack_ms", "sample_rate", "bit_depth", "peak_ceiling_dbfs",
                "schema_version")


def preset(name: str) -> dict:
    return load_preset(name)


def box(kind: str, w: float, x: float) -> tuple[float, float]:
    if kind == "abs":
        return x - w, x + w
    if kind == "rel":
        return x * (1 - w), x * (1 + w)
    return x / 2**w, x * 2**w


# --- presets ---------------------------------------------------------------------------------


def test_exactly_the_accepted_presets_ship() -> None:
    assert preset_names() == NAMES
    assert sorted(DESCRIPTIONS) == NAMES
    assert sorted(p.name for p in PRESETS_DIR.glob("*.json")) == [f"{n}.json" for n in NAMES]


@pytest.mark.parametrize("name", NAMES)
def test_preset_description_states_no_number(name: str) -> None:
    """#63: ``--set`` can override every value, so a number in the description (``tau 40 ms``)
    would contradict a custom render's own sidecar parameters. No digit at all is allowed."""
    text = describe(name)
    assert text and text == DESCRIPTIONS[name]
    assert not any(ch.isdigit() for ch in text), (name, text)


@pytest.mark.parametrize("name", NAMES)
def test_preset_has_the_accepted_values(name: str) -> None:
    p = preset(name)
    assert p == {**COMMON, "preset": name, **dict(zip(FIELDS, EXPECTED_PRESETS[name],
                                                       strict=True))}


@pytest.mark.parametrize("name", NAMES)
def test_preset_file_is_a_valid_kick_params_object(name: str) -> None:
    p = json.loads((PRESETS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(load_schema(KICK_SCHEMA_FILE)).iter_errors(p))
    assert errors == []
    resolve_kick_params(p)  # also the pitch_end <= pitch_start rule


@pytest.mark.parametrize("name", NAMES)
def test_preset_follows_the_pitch_settle_guideline(name: str) -> None:
    p = preset(name)
    assert pitch_settles(p)
    # Independent re-derivation from the contract text: within 5 % of pitch_end_hz once the
    # level is 20 dB down (attack + decay/3), tau <= t / ln(drop / (0.05 * end)).
    t = min(p["amp_attack_ms"] + p["amp_decay_ms"] / 3, p["length_ms"])
    tau_max = t / math.log((p["pitch_start_hz"] - p["pitch_end_hz"]) / (0.05 * p["pitch_end_hz"]))
    assert p["pitch_decay_ms"] <= tau_max
    assert abs(max_settled_pitch_decay_ms(p) - tau_max) < 1e-9


def test_centre_has_the_pitch_decay_the_user_chose() -> None:
    """#59 (user decision, option c): centre uses tau 40 ms; the schema default stays 15 ms.
    Its guideline limit, worked by hand from the contract text: t = 0.5 + 560 / 3 = 187.1667 ms,
    tau_max = t / ln((200 - 52) / (0.05 * 52)) = 187.1667 / ln(56.9231) = 46.3089 ms."""
    p = preset("centre")
    assert p["pitch_decay_ms"] == 40
    assert load_schema(KICK_SCHEMA_FILE)["properties"]["pitch_decay_ms"]["default"] == 15
    assert abs(max_settled_pitch_decay_ms(p) - 46.3089) < 1e-4
    assert pitch_settles(p)


def test_dense_is_centre_with_drive() -> None:
    """#116: dense differs from centre only in its name and drive, so it renders the bytes of
    ``--preset centre --set drive=0.45`` (the file the user chose, #103). The SHA-256 of that
    file is pinned in test_engine_version.py (golden case preset-dense)."""
    dense, centre = preset("dense"), preset("centre")
    assert {k for k in dense if dense[k] != centre[k]} == {"preset", "drive"}
    assert dense["drive"] == 0.45
    assert render_kick_wav(dense)[0] == render_kick_wav({**centre, "drive": 0.45})[0]


@pytest.mark.parametrize("name", NAMES)
def test_every_preset_variant_follows_the_pitch_settle_guideline(name: str) -> None:
    """Variants 1-8 of every preset settle, re-derived here from the contract text (the
    limit moves with each variant's own amp_decay_ms, pitch_start_hz and pitch_end_hz)."""
    for v in make_variants(preset(name), 9)[1:]:
        t = min(v["amp_attack_ms"] + v["amp_decay_ms"] / 3, v["length_ms"])
        drop = v["pitch_start_hz"] - v["pitch_end_hz"]
        tau_max = t / math.log(drop / (0.05 * v["pitch_end_hz"]))
        assert v["pitch_decay_ms"] <= tau_max, (name, v["seed"], v["pitch_decay_ms"], tau_max)
        assert pitch_settles(v)


def test_unknown_preset_lists_valid_names() -> None:
    with pytest.raises(UnknownPresetError) as info:
        load_preset("hard-trance")
    assert all(n in str(info.value) for n in NAMES)
    with pytest.raises(UnknownPresetError):
        load_preset("../presets/centre")  # only listed names, no paths


def _check_01a(params: dict) -> None:
    """The Phase 01a checks on one render (peak, finite, DC, ends, length, pitch)."""
    wav, audio, r = render_kick_wav(params)
    assert np.all(np.isfinite(audio))
    assert abs(float(np.mean(audio))) < DC_THRESHOLD
    assert audio[0] == 0.0 and audio[-1] == 0.0
    assert abs(len(audio) / r["sample_rate"] * 1000 - r["length_ms"]) <= 1.0
    ints, sr, bits = decode_wav(wav)
    assert (sr, bits) == (48000, 24)
    full = 2**23 - 1
    peak = int(np.max(np.abs(ints)))
    assert ceiling_lsb(r) - 1 <= peak <= ceiling_lsb(r)
    assert peak < full
    measured = analyse(audio, sr)["fundamental_hz"]
    assert measured is not None
    start, end = tail_window(audio, sr)
    t1, t2 = crossing_interval(audio, sr, start, end)
    window_ms = (end - start) / sr * 1000
    tol = FUNDAMENTAL_TOLERANCE if window_ms >= SHORT_WINDOW_MS else FUNDAMENTAL_TOLERANCE_SHORT
    expected = theoretical_mean_frequency(r, t1, t2)
    assert abs(measured - expected) <= tol * expected
    assert abs(measured - analytic_signal_frequency(audio, sr, t1, t2)) <= 0.01 * measured


def ceiling_lsb(r: dict) -> float:
    return 10 ** (r["peak_ceiling_dbfs"] / 20) * (2 ** (r["bit_depth"] - 1) - 1)


@pytest.mark.parametrize("name", NAMES)
def test_every_preset_renders_and_passes_the_01a_checks(name: str) -> None:
    _check_01a(preset(name))


@pytest.mark.parametrize("name", NAMES)
def test_preset_sidecar_validates_and_rerenders_identically(name: str, tmp_path) -> None:
    wav_path, json_path = write_kick(preset(name), tmp_path, name=name, created_at=FIXED_TIME)
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    Draft202012Validator(load_schema(METADATA_SCHEMA_FILE)).validate(meta)
    assert meta["parameters"]["preset"] == name
    digest = hashlib.sha256(wav_path.read_bytes()).hexdigest()
    assert meta["sha256"] == digest
    assert hashlib.sha256(rerender_from_sidecar(json_path)).hexdigest() == digest


# --- variant seeds and determinism -----------------------------------------------------------

# Literal values from the design proposal on issue #3 (computed there by separate scratch
# code). A salt, byte-order or format change turns these red.
PINNED_SEEDS = {
    (1003, 1): 2022732847,
    (1003, 2): 2606410306,
    (1003, 3): 1833610462,
}


@pytest.mark.parametrize(("key", "expected"), PINNED_SEEDS.items())
def test_derived_seeds_are_pinned(key: tuple[int, int], expected: int) -> None:
    assert derived_seed(*key) == expected


# Pinned variant VALUES (#55). Recorded from main 05fbb96, i.e. the values the user hears in
# the #3 listening test. They are literals on purpose: if the offset derivation (salt, hash
# bytes, mapping, rounding, field order) changes, these turn red, even though the engine's
# golden hashes stay green. Changing them needs a reason in the PR (the listening test would
# then be stale for the changed variants).
# #59: centre's pitch_decay_ms re-recorded after the preset moved from tau 8 to 40 ms (was
# 7.4577 and 8.6142); every other centre value is unchanged. For tau 40 the guideline caps the
# box [32, 48] (v1: limit 42.6559, v2: 44.8819), so the draw lands in [32, limit].
PINNED_VARIANTS = {
    ("centre", 1): {"seed": 1149790815, "click_level": 0.3003, "click_tone_hz": 3209.9477,
                    "pitch_end_hz": 52.9918, "pitch_start_hz": 215.3134,
                    "amp_decay_ms": 525.1091, "drive": 0.0, "tone": 0.0216,
                    "pitch_decay_ms": 35.5223},
    ("centre", 2): {"seed": 1271935609, "click_level": 0.4252, "click_tone_hz": 3138.6539,
                    "pitch_end_hz": 52.6428, "pitch_start_hz": 181.3576,
                    "amp_decay_ms": 522.2453, "drive": 0.0, "tone": -0.0047,
                    "pitch_decay_ms": 40.9136},
    ("driven", 1): {"seed": 3111738165, "click_level": 0.9906, "click_tone_hz": 6520.14,
                    "pitch_end_hz": 57.6889, "pitch_start_hz": 310.4722,
                    "amp_decay_ms": 391.6256, "drive": 0.4653, "tone": 0.5331,
                    "pitch_decay_ms": 7.0699},
    ("driven", 2): {"seed": 498398891, "click_level": 0.8826, "click_tone_hz": 6202.2226,
                    "pitch_end_hz": 55.8518, "pitch_start_hz": 299.6949,
                    "amp_decay_ms": 348.0486, "drive": 0.4889, "tone": 0.5508,
                    "pitch_decay_ms": 5.0622},
}


@pytest.mark.parametrize("key", list(PINNED_VARIANTS), ids=lambda k: f"{k[0]}-v{k[1]}")
def test_variant_values_are_pinned(key: tuple[str, int]) -> None:
    name, i = key
    v = make_variant(preset(name), i)
    expected = PINNED_VARIANTS[key]
    assert {k: v[k] for k in expected} == expected
    # Every field outside the spread is the preset's own value. ("variants" is a batch-only
    # default that the final resolve adds to v1+; render_kick and the sidecar drop it.)
    assert {k: x for k, x in v.items() if k not in expected and k != "variants"} == {
        k: x for k, x in preset(name).items() if k not in expected
    }


def test_one_pinned_value_matches_an_independent_derivation() -> None:
    """centre v1 click_level re-derived here with hashlib from the documented rule (53 bits of
    SHA-256(salt + "1001:1:click_level") -> u in [-1, 1), uniform in 0.35 +- 0.12, 4 decimals),
    without calling variants.py."""
    digest = hashlib.sha256(b"abeltongod-kick-variant/v1:1001:1:click_level").digest()
    u = (int.from_bytes(digest[:8], "big") >> 11) / 2.0**52 - 1.0
    lo, hi = 0.35 - 0.12, 0.35 + 0.12
    assert round(lo + (u + 1) / 2 * (hi - lo), 4) == PINNED_VARIANTS[("centre", 1)]["click_level"]


# A base whose pitch barely drops (end 120 Hz, tau 128 ms; the case named in PR #54): the
# guideline cap of most variants lies below the -20 % edge of the tau box, so the settle
# fallback [0.8 * cap, cap] is used.
FALLBACK_BASE = {"schema_version": "0.2", "length_ms": 274.65, "pitch_start_hz": 131.24,
                 "pitch_end_hz": 120.0, "pitch_decay_ms": 127.85, "amp_decay_ms": 336.68,
                 "amp_attack_ms": 0.0, "click_level": 0.0, "drive": 0.0, "tone": 0.0}


def test_settle_fallback_spreads_values_below_the_cap() -> None:
    """The fallback is an interval, not a clamp (#55): its values spread over [0.8, 1] x cap."""
    assert pitch_settles({**FALLBACK_BASE, "seed": 0})
    ratios = []
    for seed in range(4):
        base = {**FALLBACK_BASE, "seed": seed}
        for i in range(1, 9):
            v = make_variant(base, i)
            cap = max_settled_pitch_decay_ms(v)
            if cap < 0.8 * FALLBACK_BASE["pitch_decay_ms"]:  # box and guideline do not overlap
                ratios.append(v["pitch_decay_ms"] / cap)
    assert len(ratios) >= 10
    assert all(0.8 - 1e-6 <= r <= 1.0 for r in ratios)
    assert min(ratios) < 0.85 and max(ratios) > 0.95  # spread across the interval
    assert sum(r < 0.95 for r in ratios) >= len(ratios) // 3
    # One literal fallback value (seed 0, variant 4), recorded from main 05fbb96.
    assert make_variant({**FALLBACK_BASE, "seed": 0}, 4)["pitch_decay_ms"] == 84.7124


def test_derived_seed_stays_in_the_contract_range() -> None:
    hi = load_schema(KICK_SCHEMA_FILE)["properties"]["seed"]["maximum"]
    seeds = [derived_seed(s, i) for s in (0, 1, 2**32 - 1) for i in range(1, 9)]
    assert all(0 <= s <= hi for s in seeds)
    assert len(set(seeds)) == len(seeds)


@pytest.mark.parametrize("name", NAMES)
def test_variant_zero_is_the_preset_byte_for_byte(name: str) -> None:
    p = preset(name)
    v0 = make_variant(p, 0)
    wav, _, rendered = render_kick_wav(p)
    assert v0 == rendered  # the resolved params a single render of the preset uses
    assert render_kick_wav(v0)[0] == wav


@pytest.mark.parametrize("name", NAMES)
def test_variants_are_reproducible_and_differ_from_each_other(name: str) -> None:
    first = make_variants(preset(name), 8)
    second = make_variants(dict(preset(name)), 8)
    assert first == second
    wavs = [render_kick_wav(v)[0] for v in first]
    assert [render_kick_wav(v)[0] for v in second[:3]] == wavs[:3]  # byte-identical re-render
    digests = [hashlib.sha256(w).hexdigest() for w in wavs]
    assert len(set(digests)) == 8
    assert len({v["seed"] for v in first}) == 8


# Presets exempt from the -40 dB rule below, each with its reason. Keep this list narrow: one
# named preset per user decision, never a pattern.
MINUS_40_DB_EXEMPT = {
    # User decision on #116 (option a, lead comment
    # https://github.com/castorsalzmann-ui/AbeltonGod/issues/116#issuecomment-6495172822):
    # dense must stay byte-identical to the file chosen in listening tests 1 and 2 (#103).
    # Its drive lifts the tail; variant 0 ends about 36.5 dB below its peak (analysis.py
    # envelope) and is then faded over the last 5 ms, so -40 dB is not reached inside 480 ms.
    "dense": "#116: byte-identical to the user's listening-test pick; tail ends near -36.5 dB",
}
MINUS_40_DB_CHECKED = [n for n in NAMES if n not in MINUS_40_DB_EXEMPT]


def test_minus_40_db_exemption_is_narrow() -> None:
    """Only the named, decided preset is exempt, every other preset is still checked, and the
    exemption is still needed (if dense ever reaches -40 dB, drop it from the list)."""
    assert set(MINUS_40_DB_EXEMPT) == {"dense"}
    assert sorted(MINUS_40_DB_CHECKED) == sorted(set(NAMES) - {"dense"})
    audio, r = render_kick(preset("dense"))
    assert analyse(audio, r["sample_rate"])["decay_40db_ms"] is None


@pytest.mark.parametrize("name", MINUS_40_DB_CHECKED)
def test_every_variant_reaches_minus_40_db_inside_the_file(name: str) -> None:
    """CI rule from the design: variants 0-7 of every preset decay 40 dB before the file ends
    (found while prototyping: driven at 360 ms was cut off). Exempt: MINUS_40_DB_EXEMPT."""
    for v in make_variants(preset(name), 8):
        audio, r = render_kick(v)
        env = _rms_envelope_db(audio, r["sample_rate"])
        peak = int(np.argmax(env))
        assert np.any(env[peak:] <= env[peak] - 40.0), (name, v["seed"])
        assert analyse(audio, r["sample_rate"])["decay_40db_ms"] is not None


def _rms_envelope_db(audio: np.ndarray, sr: int) -> np.ndarray:
    """10 ms RMS envelope, hop 1 ms (independent of analysis.py's 40 ms max envelope)."""
    win, hop = int(0.010 * sr), int(0.001 * sr)
    frames = np.array([math.sqrt(float(np.mean(audio[s:s + win] ** 2)))
                       for s in range(0, len(audio) - win + 1, hop)])
    return 20 * np.log10(np.maximum(frames, 1e-12))


@pytest.mark.parametrize("name", NAMES)
def test_every_variant_passes_the_01a_checks(name: str) -> None:
    for v in make_variants(preset(name), 8)[1:]:
        _check_01a(v)


@pytest.mark.parametrize("name", NAMES)
def test_variant_sidecars_rerender_identically(name: str, tmp_path) -> None:
    for i, v in enumerate(make_variants(preset(name), 4)):
        wav_path, json_path = write_kick(v, tmp_path, name=f"{name}_v{i}", created_at=FIXED_TIME)
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        assert meta["parameters"]["seed"] == v["seed"]
        assert meta["parameters"]["preset"] == name
        assert rerender_from_sidecar(json_path) == wav_path.read_bytes()


def test_input_is_not_mutated() -> None:
    p = {**preset("punchy"), "variants": 4}
    before = json.loads(json.dumps(p))
    make_variants(p, 4)
    assert p == before


@pytest.mark.parametrize("bad", [-1, 1.0, True, "1"])
def test_bad_variant_index_is_rejected(bad) -> None:
    with pytest.raises(ValueError):
        make_variant(preset("centre"), bad)


# --- seeded property tests over random contract-valid bases ---------------------------------

N_BASES = 300
N_VARIANTS = 7  # i = 1 … 7 per base


def _random_bases() -> list[dict]:
    """Uniform draws over the whole contract (test_kick.random_params), half of them moved
    onto the pitch-settle guideline so the settling branch is exercised as often as the other.
    """
    out = []
    for k in range(N_BASES):
        rng = kp.rng(30_000 + k)
        p = random_params(rng)
        if k % 2 == 0:
            limit = max_settled_pitch_decay_ms(p)
            if limit >= 2:
                p["pitch_decay_ms"] = rng.uniform(2, limit)
        if k % 5 == 0:
            p["drive"] = 0.0
        if k % 7 == 0:  # edges of the contract
            p["click_level"] = rng.choice([0.0, 1.0])
            p["tone"] = rng.choice([-1.0, 1.0])
            p["pitch_end_hz"] = rng.choice([30.0, min(120.0, p["pitch_start_hz"])])
        out.append(p)
    return out


BASES = _random_bases()


def _variants_or_skip(base: dict) -> list[tuple[int, dict]]:
    out = []
    for i in range(1, N_VARIANTS + 1):
        try:
            out.append((i, make_variant(base, i)))
        except VariantError:
            # Only allowed when no contract value settles for the variant's other values.
            assert pitch_settles(base)
    return out


ALL = [(b, i, v) for b in BASES for i, v in _variants_or_skip(b)]


def test_almost_all_random_variants_can_be_made() -> None:
    assert len(ALL) >= 0.99 * N_BASES * N_VARIANTS


FALLBACKS: list[tuple[int, int]] = []


def test_random_variants_are_valid_and_inside_spread_and_contract() -> None:
    props = load_schema(KICK_SCHEMA_FILE)["properties"]
    FALLBACKS.clear()
    for base, i, v in ALL:
        assert resolve_kick_params(v) == v
        r = resolve_kick_params(base)
        for field, (kind, w) in SPREAD_SPEC.items():
            if field == "drive" and r["drive"] == 0:
                assert v["drive"] == 0.0
                continue
            lo, hi = box(kind, w, r[field])
            assert props[field]["minimum"] <= v[field] <= props[field]["maximum"]
            if field == "pitch_decay_ms" and pitch_settles(r):
                limit = max_settled_pitch_decay_ms(v)
                if limit < lo:  # documented fallback: box and guideline do not overlap
                    assert max(0.8 * limit, 2.0) - 1e-4 <= v[field] <= limit
                    FALLBACKS.append((i, r["seed"]))
                    continue
            # 1e-9 relative slack for float rounding of the box itself only.
            assert lo - 1e-9 * abs(lo) <= v[field] <= hi + 1e-9 * abs(hi), (field, i, r, v)
            assert v[field] == round(v[field], 4)
        for field in FIXED_FIELDS:
            assert v[field] == r[field]
        for key in ("preset", "bpm"):
            assert v.get(key) == base.get(key)
        assert v["pitch_start_hz"] >= v["pitch_end_hz"]
        assert v["seed"] == derived_seed(r["seed"], i)
    # The fallback is rare and only for bases far from the presets (see variants.py).
    assert len(FALLBACKS) <= 0.02 * len(ALL), len(FALLBACKS)


@pytest.mark.parametrize("name", NAMES)
def test_preset_variants_never_use_the_settle_fallback(name: str) -> None:
    p = preset(name)
    for i in range(1, 9):
        v = make_variant(p, i)
        assert v["pitch_decay_ms"] >= 0.8 * p["pitch_decay_ms"] - 1e-9
        assert v["pitch_decay_ms"] <= 1.2 * p["pitch_decay_ms"] + 1e-9


def test_settling_bases_give_settling_variants() -> None:
    n = 0
    for base, _, v in ALL:
        if pitch_settles(base):
            n += 1
            assert pitch_settles(v)
    assert n > 900  # the branch is exercised


def test_clean_bases_stay_clean_and_driven_stay_driven() -> None:
    clean = [v for b, _, v in ALL if b["drive"] == 0]
    driven = [v for b, _, v in ALL if b["drive"] > 0]
    assert len(clean) > 300 and len(driven) > 1000
    assert all(v["drive"] == 0 for v in clean)
    assert all(v["drive"] > 0 for v in driven)


def test_offsets_are_never_clamped_onto_an_edge() -> None:
    """Draws are uniform inside spread ∩ contract, so a value lands on a contract edge only by
    the 4-decimal rounding grid: with this many draws, that should be (nearly) never. A clamp
    would put every overshooting draw exactly on the edge (base values on an edge do this ~50 %
    of the time for abs fields)."""
    props = load_schema(KICK_SCHEMA_FILE)["properties"]
    on_edge = total = 0
    for base, _, v in ALL:
        r = resolve_kick_params(base)
        for field in ("click_level", "tone", "drive"):
            if field == "drive" and r["drive"] == 0:
                continue
            total += 1
            on_edge += v[field] in (props[field]["minimum"], props[field]["maximum"])
    assert total > 4000
    assert on_edge <= 2


def test_offsets_cover_the_whole_spread() -> None:
    """Each field uses its whole box, not a narrower one: the normalised position of the value
    in the (contract-limited) box spans almost [0, 1] and has a mean near 0.5."""
    props = load_schema(KICK_SCHEMA_FILE)["properties"]
    for field, (kind, w) in SPREAD_SPEC.items():
        if field in ("pitch_decay_ms", "pitch_start_hz"):
            continue  # extra limits (guideline, start >= end) shape these two
        pos = []
        for base, _, v in ALL:
            r = resolve_kick_params(base)
            if field == "drive" and r["drive"] == 0:
                continue
            lo, hi = box(kind, w, r[field])
            lo, hi = max(lo, props[field]["minimum"]), min(hi, props[field]["maximum"])
            if field == "drive":
                lo = max(lo, 1e-4)
            if hi - lo < 1e-3 * max(1.0, abs(hi)):
                continue
            pos.append((v[field] - lo) / (hi - lo))
        pos = np.array(pos)
        assert pos.min() < 0.01 and pos.max() > 0.99, field
        assert abs(pos.mean() - 0.5) < 0.03, field


def test_each_field_moves_independently_of_the_others() -> None:
    """One hash per field: two bases that differ only in one spread field give the same
    relative position in every other field's box."""
    a = preset("punchy")
    b = {**a, "tone": 0.0}
    for i in range(1, 8):
        va, vb = make_variant(a, i), make_variant(b, i)
        for field in ("click_level", "pitch_end_hz", "amp_decay_ms", "drive"):
            assert va[field] == vb[field]
        assert va["tone"] - 0.3 == pytest.approx(vb["tone"] - 0.0, abs=2e-4)


def test_offsets_of_different_fields_are_uncorrelated() -> None:
    """One hash per field: the drawn offsets of two fields are independent (|r| small over
    2000+ variants). A single shared draw for all fields would give r ~ 1."""
    pos: dict[str, list[float]] = {"click_level": [], "tone": [], "amp_decay_ms": []}
    for base, _, v in ALL:
        r = resolve_kick_params(base)
        if not (0.12 < r["click_level"] < 0.88 and -0.9 < r["tone"] < 0.9):
            continue  # boxes cut by the contract: positions not comparable
        pos["click_level"].append(v["click_level"] - r["click_level"])
        pos["tone"].append(v["tone"] - r["tone"])
        pos["amp_decay_ms"].append(v["amp_decay_ms"] / r["amp_decay_ms"] - 1)
    a, b, c = (np.array(x) for x in pos.values())
    assert len(a) > 800
    for x, y in ((a, b), (a, c), (b, c)):
        assert abs(np.corrcoef(x, y)[0, 1]) < 0.1


def test_random_variant_renders_are_deterministic_and_clean() -> None:
    rng = kp.rng(4242)
    for _, _, v in rng.sample(ALL, 25):
        w1, audio, r = render_kick_wav(v)
        assert render_kick_wav(dict(v))[0] == w1
        assert np.all(np.isfinite(audio))
        assert abs(float(np.mean(audio))) < DC_THRESHOLD
        ints, _, _ = decode_wav(w1)
        assert int(np.max(np.abs(ints))) <= ceiling_lsb(r)


def test_variant_pairs_differ_for_random_bases() -> None:
    by_base: dict[int, list[dict]] = {}
    for base, _, v in ALL:
        by_base.setdefault(id(base), []).append(v)
    for vs in by_base.values():
        for x, y in itertools.combinations(vs, 2):
            assert x != y
