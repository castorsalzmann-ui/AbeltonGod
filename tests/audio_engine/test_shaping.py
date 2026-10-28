"""Independent tests for tone, drive and the amplitude envelope (issue #11).

Before this file, the merged engine's tests did not notice when ``tone`` was inverted or
removed, and caught a removed drive, a halved ``amp_decay_ms`` or a removed attack only by
accident (round-6 review of PR #8). Every test here measures the rendered audio with a method
written in this file and compares it with an expectation written here, never with a helper
from ``audio_engine.kick``.

What the parameters are expected to do. Attack and decay come from the contract
(kick-params v0.2, #7); tone and drive are not defined in the contract yet, so they come from
the ``kick.py`` docstring:

- ``tone``: -1 darker ... +1 brighter, a tilt that leaves the low band alone.
- ``drive``: 0 clean ... 1 heavy saturation; a memoryless curve, so a steady sine gains odd
  harmonics and the waveform gets flatter (lower crest factor).
- ``amp_attack_ms``: linear rise from 0 to full level, starting at t = 0.
- ``amp_decay_ms``: time for the level to fall by 60 dB, measured from the end of the attack,
  i.e. an exponential decay of ``60 / amp_decay_ms`` dB per ms; -20 dB after a third of it.

Measured margins (lead session, 2026-10-28, numbers from probe runs over the random sets
below) are noted next to each limit.
"""

from __future__ import annotations

import math
import random
from functools import cache

import numpy as np
import pytest

from audio_engine import kick as K
from audio_engine.analysis import analyse
from audio_engine.kick import render_kick
from audio_engine.params import resolve_kick_params

SCHEMA_VERSION = "0.2"
BASE = {"schema_version": SCHEMA_VERSION, "seed": 11}
TONES = (-1.0, -0.5, 0.0, 0.5, 1.0)
DRIVES = (0.0, 0.25, 0.5, 0.75, 1.0)
N_RANDOM = 30


def _draw(rng: random.Random) -> dict:
    """Uniform draw over the whole kick-params contract range (pitch_end <= pitch_start)."""
    p = {
        "schema_version": SCHEMA_VERSION,
        "seed": rng.randrange(2**32),
        "sample_rate": rng.choice([44100, 48000]),
        "bit_depth": rng.choice([16, 24]),
        "length_ms": rng.uniform(80, 2000),
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


def _sets(curated: dict[str, dict], seed0: int, n: int = N_RANDOM) -> list:
    return [pytest.param({**BASE, **c}, id=name) for name, c in curated.items()] + [
        pytest.param(_draw(random.Random(seed0 + i)), id=f"random-{seed0 + i}") for i in range(n)
    ]


@cache
def _render_frozen(items: tuple) -> tuple[np.ndarray, int]:
    audio, resolved = render_kick(dict(items))
    audio.setflags(write=False)
    return audio, int(resolved["sample_rate"])


def _render(p: dict, **override) -> tuple[np.ndarray, int]:
    return _render_frozen(tuple(sorted({**p, **override}.items())))


# --- measurements (rectangular window over the whole file, see kick-gen2 note, pitfall 1) ---


def _power_spectrum(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    return np.fft.rfftfreq(len(x), 1.0 / sr), np.abs(np.fft.rfft(x)) ** 2


def _band_ratio(x: np.ndarray, sr: int) -> float:
    """Energy 3-20 kHz divided by energy below 300 Hz."""
    f, s = _power_spectrum(x, sr)
    return float(s[(f >= 3000) & (f < 20000)].sum() / s[f < 300].sum())


def _centroid_hz(x: np.ndarray, sr: int) -> float:
    f, s = _power_spectrum(x, sr)
    return float((f * s).sum() / s.sum())


def _crest(x: np.ndarray) -> float:
    return float(np.max(np.abs(x)) / np.sqrt(np.mean(x**2)))


# --- tone ---------------------------------------------------------------------------------

TONE_SETS = _sets(
    {
        "defaults": {},
        "clean-no-click": {"drive": 0.0, "click_level": 0.0},
        "hard-click": {"drive": 1.0, "click_level": 1.0, "click_tone_hz": 12000},
        "low-short-16bit": {"pitch_end_hz": 30, "length_ms": 80, "bit_depth": 16},
    },
    seed0=11000,
)
# Each step of 0.5 in tone must multiply the 3-20 kHz / <300 Hz energy ratio by at least this.
# Measured minimum over 40 random sets: 1.61.
TONE_MIN_STEP = 1.3
# tone +1 vs 0: measured 3.18-3.54 (a tilt of about +5 dB at the top). tone -1 vs 0: >= 7.4.
TONE_PLUS_RANGE = (2.5, 4.5)
TONE_MINUS_MIN = 5.0


@pytest.mark.parametrize("p", TONE_SETS)
def test_tone_brightens_at_every_step(p: dict) -> None:
    ratios, centroids = [], []
    for tone in TONES:
        x, sr = _render(p, tone=tone)
        ratios.append(_band_ratio(x, sr))
        centroids.append(_centroid_hz(x, sr))
    steps = [b / a for a, b in zip(ratios, ratios[1:], strict=False)]
    assert min(steps) >= TONE_MIN_STEP, (steps, TONES)
    # The centroid is dominated by the sub, so its steps are small (measured down to +0.26 %),
    # but it must still rise strictly.
    assert all(b > a for a, b in zip(centroids, centroids[1:], strict=False)), centroids


@pytest.mark.parametrize("p", TONE_SETS)
def test_tone_extremes_have_the_expected_size(p: dict) -> None:
    (x_dark, sr), (x_mid, _), (x_bright, _) = (_render(p, tone=t) for t in (-1.0, 0.0, 1.0))
    mid = _band_ratio(x_mid, sr)
    plus = _band_ratio(x_bright, sr) / mid
    minus = mid / _band_ratio(x_dark, sr)
    assert TONE_PLUS_RANGE[0] <= plus <= TONE_PLUS_RANGE[1], plus
    assert minus >= TONE_MINUS_MIN, minus


def test_tone_leaves_the_low_band_level_alone() -> None:
    """Tilt, not overall gain: tone +1 lifts 8-16 kHz by more than 3 dB relative to 30-100 Hz.
    Compared as a ratio of ratios, so the peak normalisation cancels."""
    p = {**BASE, "drive": 0.0, "click_level": 0.5}
    (x0, sr), (x1, _) = _render(p, tone=0.0), _render(p, tone=1.0)
    f, s0 = _power_spectrum(x0, sr)
    _, s1 = _power_spectrum(x1, sr)
    low = (f >= 30) & (f < 100)
    top = (f >= 8000) & (f < 16000)
    # Gain of the top band relative to the low band, in dB.
    rel_db = 10 * math.log10((s1[top].sum() / s0[top].sum()) / (s1[low].sum() / s0[low].sum()))
    assert rel_db > 3.0, rel_db


# --- drive --------------------------------------------------------------------------------

DRIVE_SETS = _sets(
    {
        "defaults": {},
        "long-low": {"pitch_end_hz": 30, "amp_decay_ms": 2000, "length_ms": 2000},
        "short-fast": {"length_ms": 80, "amp_decay_ms": 20, "pitch_decay_ms": 2},
        "44k1-16bit": {"sample_rate": 44100, "bit_depth": 16},
    },
    seed0=12000,
)
# Crest factor over drive 0 ... 1, tone 0 and no click. Late steps can rise slightly: on
# random-12011 1.2341 -> 1.2354; with the engine's 10 Hz DC blocker switched off the same kick
# falls monotonically to 1.085, so the high-pass is the cause (it raises the crest of a nearly
# square, heavily driven waveform). Undoing the high-pass in the test is not exact, because the
# fade-out and the mean correction run after it (review of this PR, random-32154). Measured over
# 800 fresh sets: largest step ratio 1.0206, largest crest(drive 1) / crest(drive 0) 0.708.
DRIVE_STEP_CREST_MAX = 1.03
DRIVE_TOTAL_CREST_MAX = 0.85
# Endpoints for any click level and tone <= 0: crest(drive 1) / crest(drive 0) at most 0.706
# over 373 fresh sets. With a click and tone > 0 the ratio exceeded 1 on about 1 % of sets
# (review: random-72067 gives 1.156; 0.646 without the click, 0.662 with tone 0); cause not
# established, so that region is not covered by a crest test. The residual and third-harmonic
# tests below still cover drive there.
DRIVE_END_CREST_MAX = 0.85
# Distance from the clean render (least-squares residual share) rises with drive; measured
# smallest step 0.024 over 40 random sets (34 sets here: main 0.0219, after #16 0.0195).
DRIVE_MIN_RESIDUAL_STEP = 0.01


@pytest.mark.parametrize("p", DRIVE_SETS)
def test_drive_lowers_crest_factor(p: dict) -> None:
    crests = [_crest(_render(p, drive=d, tone=0.0, click_level=0.0)[0]) for d in DRIVES]
    steps = [b / a for a, b in zip(crests, crests[1:], strict=False)]
    assert max(steps) <= DRIVE_STEP_CREST_MAX, crests
    assert crests[-1] / crests[0] <= DRIVE_TOTAL_CREST_MAX, crests


@pytest.mark.parametrize("p", DRIVE_SETS)
def test_full_drive_lowers_crest_factor_with_click_and_dark_tone(p: dict) -> None:
    tone = -abs(p.get("tone", 0.0))
    full, _ = _render(p, drive=1.0, tone=tone)
    clean, _ = _render(p, drive=0.0, tone=tone)
    ratio = _crest(full) / _crest(clean)
    assert ratio <= DRIVE_END_CREST_MAX, ratio


@pytest.mark.parametrize("p", DRIVE_SETS)
def test_drive_moves_the_sound_further_from_the_clean_render(p: dict) -> None:
    clean, _ = _render(p, drive=0.0)
    shares = []
    for d in DRIVES:
        y, _ = _render(p, drive=d)
        scale = float(y @ clean) / float(clean @ clean)
        shares.append(float(np.linalg.norm(y - scale * clean) / np.linalg.norm(y)))
    assert shares[0] == 0.0
    steps = [b - a for a, b in zip(shares, shares[1:], strict=False)]
    assert min(steps) >= DRIVE_MIN_RESIDUAL_STEP, shares


def _third_harmonic_db(x: np.ndarray, sr: int, f0: float) -> float:
    """Level of the 3rd harmonic relative to the fundamental on a steady segment (Hann window
    on a steady part only, so pitfall 1 does not apply)."""
    seg = x[int(0.05 * sr) : int(0.45 * sr)]
    f = np.fft.rfftfreq(len(seg), 1.0 / sr)
    s = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))

    def level(h: int) -> float:
        return float(s[np.abs(f - h * f0) <= 3.0].max())

    return 20 * math.log10(level(3) / level(1))


STEADY_SETS = [
    pytest.param(
        {
            "schema_version": SCHEMA_VERSION,
            "seed": rng.randrange(2**32),
            "sample_rate": rng.choice([44100, 48000]),
            "bit_depth": rng.choice([16, 24]),
            "pitch_start_hz": (f := rng.uniform(60, 120)),
            "pitch_end_hz": f,  # contract allows start == end: a steady sine body
            "pitch_decay_ms": rng.uniform(2, 300),
            "amp_attack_ms": 0.0,
            "amp_decay_ms": rng.uniform(1000, 2000),
            "length_ms": 600,
            "click_level": 0.0,
            "tone": 0.0,
        },
        id=f"steady-{i}",
    )
    for i, rng in enumerate(random.Random(13000 + k) for k in range(12))
]


@pytest.mark.parametrize("p", STEADY_SETS)
def test_drive_adds_third_harmonic_at_every_step(p: dict) -> None:
    """Measured over these 12 sets with the continuous drive of #16 (gain 10 * drive**0.8):
    -108 dB or lower clean; at drive 0.25 -18.0 ... -24.9 dB (lower for shorter amp_decay_ms,
    because the saturation depends on the level); smallest step 0.87 dB (limit 0.5 dB)."""
    levels = [_third_harmonic_db(*_render(p, drive=d), p["pitch_end_hz"]) for d in DRIVES]
    assert levels[0] < -80.0, levels
    assert levels[1] > -30.0, levels
    assert all(b > a + 0.5 for a, b in zip(levels, levels[1:], strict=False)), levels


# --- amplitude envelope ---------------------------------------------------------------------

DC_BLOCK_HZ = 10.0  # the engine's DC blocker, documented in kick.py; undone by the attack test


def test_dc_blocker_frequency_matches_the_attack_test() -> None:
    assert K.DC_BLOCK_HZ == DC_BLOCK_HZ


def _undo_dc_blocker(y: np.ndarray, sr: int) -> np.ndarray:
    """Exact inverse of the one-pole high-pass step y[n] = a * (y[n-1] + x[n] - x[n-1]) alone.

    The engine's fade-out and mean correction run after the high-pass and are not undone, so
    on the final output this is only an approximation. It is used for the attack fit, which
    looks at the first 40 ms: without it the 10 Hz high-pass shifts the estimate by up to
    1.7 ms on low or short kicks; with the high-pass switched off in the engine the same fit is
    within 0.005 ms (experiment, lead session 2026-10-28; reproduced in review)."""
    a = math.exp(-2.0 * math.pi * DC_BLOCK_HZ / sr)
    x = np.empty_like(y)
    prev_x = prev_y = 0.0
    for i, yi in enumerate(y.tolist()):
        prev_x = prev_x + yi / a - prev_y
        prev_y = yi
        x[i] = prev_x
    return x


ATTACK_FIT_MS = 40.0  # attack is at most 20 ms; the fit sees 20 ms of decay after the longest
ATTACK_GRID_MS = 0.01


def _fit_attack_ms(with_attack: np.ndarray, no_attack: np.ndarray, sr: int, decay_ms: float):
    """Attack length that best explains ``with_attack`` as ``no_attack`` times the ratio of the
    two envelopes: for t < A that ratio is (t/A)·e^((t-A)/tau), after A it is constant. The
    overall scale (normalisation) is solved by least squares for every candidate A."""
    n = int(round(ATTACK_FIT_MS * sr / 1000.0))
    ya = _undo_dc_blocker(with_attack, sr)[:n]
    y0 = _undo_dc_blocker(no_attack, sr)[:n]
    t = np.arange(n) / sr * 1000.0
    tau = decay_ms / math.log(1000.0)
    best_err, best_a = math.inf, None
    for a in np.arange(0.0, 25.0, ATTACK_GRID_MS):
        m = np.ones(n) if a == 0 else np.where(t < a, (t / a) * np.exp((t - a) / tau), 1.0)
        b = m * y0
        k = float(ya @ b) / float(b @ b)
        err = float(np.sum((ya - k * b) ** 2))
        if err < best_err:
            best_err, best_a = err, float(a)
    return best_a


# Precondition: length_ms >= 120. On shorter kicks the Hann-shaped mean correction (applied to
# the whole file, after the high-pass) shifts the fit: review of this PR found 10 of 48 corner
# combinations failing at attack >= 15 ms, amp_decay <= 30 ms and length <= 90 ms (e.g. attack
# 20 / decay 20 / length 80 -> 18.4 ms); with the mean correction switched off they pass, and
# at length 120 all pass. On kicks shorter than 120 ms the attack is covered only by the coarse
# decay_20db test.
ATTACK_MIN_LENGTH_MS = 120.0
ATTACK_SETS = [
    pytest.param({**BASE, "amp_attack_ms": a}, id=f"attack-{a}") for a in (0.0, 0.5, 5.0, 20.0)
] + [
    pytest.param(
        {**BASE, "amp_attack_ms": 20.0, "amp_decay_ms": 20.0, "length_ms": ATTACK_MIN_LENGTH_MS},
        id="corner-20-20-120",
    )
] + [
    pytest.param(
        {
            **(q := _draw(random.Random(14000 + i))),
            "length_ms": max(ATTACK_MIN_LENGTH_MS, q["length_ms"]),
        },
        id=f"random-{14000 + i}",
    )
    for i in range(N_RANDOM)
]
# Fit error with the DC blocker undone; a 2 % wrong attack must be outside it for A >= 5 ms.
ATTACK_TOLERANCE_MS = 0.05


@pytest.mark.parametrize("p", ATTACK_SETS)
def test_time_to_envelope_peak_follows_amp_attack(p: dict) -> None:
    p = resolve_kick_params(p)  # fills contract defaults for the curated sets
    clean = {"drive": 0.0, "click_level": 0.0, "tone": 0.0}
    with_attack, sr = _render(p, **clean)
    no_attack, _ = _render(p, **clean, amp_attack_ms=0.0)
    a_hat = _fit_attack_ms(with_attack, no_attack, sr, p["amp_decay_ms"])
    assert abs(a_hat - p["amp_attack_ms"]) <= ATTACK_TOLERANCE_MS, (a_hat, p["amp_attack_ms"])


def _half_cycle_peaks(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    a = np.abs(x)
    i = np.nonzero((a[1:-1] > a[:-2]) & (a[1:-1] >= a[2:]))[0] + 1
    return i / sr * 1000.0, a[i]


def _decay_rate_sets() -> list:
    out = []
    for i in range(N_RANDOM):
        rng = random.Random(15000 + i)
        p = _draw(rng)
        # Conditions under which the body is a settled, decaying sine in the measured region:
        # no drive, click or tone, a fast pitch drop, and a decay long enough for >= 6 peaks.
        p.update(drive=0.0, click_level=0.0, tone=0.0)
        p["pitch_decay_ms"] = rng.uniform(2, 20)
        p["amp_decay_ms"] = rng.uniform(400, 2000)
        p["length_ms"] = min(2000.0, p["amp_attack_ms"] + 0.75 * p["amp_decay_ms"] + 20)
        out.append(pytest.param(p, id=f"random-{15000 + i}"))
    short = {"drive": 0.0, "click_level": 0.0, "tone": 0.0, "pitch_decay_ms": 2}
    for name, end_hz, decay_ms in (("100ms", 120, 100), ("2s", 30, 2000)):
        p = {**BASE, **short, "pitch_end_hz": end_hz, "amp_decay_ms": decay_ms}
        out.append(pytest.param(p, id=name))
    return out


# Measured error of the slope over 87 random sets: within 0.021 %.
DECAY_RATE_TOLERANCE = 0.005


@pytest.mark.parametrize("p", _decay_rate_sets())
def test_amp_decay_sets_the_decay_rate(p: dict) -> None:
    """Regression of the half-cycle peak levels (dB) over time, between the settled pitch and
    -40 dB, must give -60 dB per amp_decay_ms."""
    p = resolve_kick_params(p)
    x, sr = _render(p)
    t0 = p["amp_attack_ms"] + 6 * p["pitch_decay_ms"] + 20
    t1 = min(p["amp_attack_ms"] + p["amp_decay_ms"] * 2 / 3, p["length_ms"] - 10)
    t, peaks = _half_cycle_peaks(x, sr)
    sel = (t >= t0) & (t <= t1)
    assert sel.sum() >= 6, (sel.sum(), t0, t1)
    slope = float(np.polyfit(t[sel], 20 * np.log10(peaks[sel]), 1)[0])
    expected = -60.0 / p["amp_decay_ms"]
    assert abs(slope / expected - 1) <= DECAY_RATE_TOLERANCE, (slope, expected)


DECAY20_SETS = [
    pytest.param(
        {
            **(q := _draw(random.Random(16000 + i))),
            "drive": 0.0,
            "click_level": 0.0,
            "tone": 0.0,
            "length_ms": max(
                80.0, min(2000.0, q["amp_attack_ms"] + q["amp_decay_ms"] / 3 * 1.3 + 60)
            ),
        },
        id=f"random-{16000 + i}",
    )
    for i in range(N_RANDOM)
] + [
    pytest.param(
        {**BASE, "drive": 0.0, "click_level": 0.0, "amp_attack_ms": 0.5, "amp_decay_ms": 20},
        id="20ms",
    ),
]
# Coarse check of the sidecar feature against the parameter, over the full amp_decay range.
# Measured deviation of analyse()'s decay_20db_ms from attack + amp_decay/3 over 200 random
# sets (half with amp_decay 20-100 ms): -12.4 ... +3.6 ms, -9.1 ... +11.9 %, every case within
# 2.5 ms + 10 %; two earlier probes (210 sets) reached -11.2 %. The larger
# relative deviations are at short decays (positive) and long decays (negative); cause not
# established (the long-decay ones are not within one pitch period of the 40 ms analysis
# frames). This is a coarse check of the sidecar feature; the precise check is the slope test.
DECAY20_TOLERANCE_MS = 3.0
DECAY20_TOLERANCE = 0.12


@pytest.mark.parametrize("p", DECAY20_SETS)
def test_decay_20db_is_a_third_of_amp_decay(p: dict) -> None:
    p = resolve_kick_params(p)
    x, sr = _render(p)
    measured = analyse(x, sr)["decay_20db_ms"]
    expected = p["amp_attack_ms"] + p["amp_decay_ms"] / 3
    assert measured is not None
    limit = DECAY20_TOLERANCE_MS + DECAY20_TOLERANCE * expected
    assert abs(measured - expected) <= limit, (measured, expected, limit)
