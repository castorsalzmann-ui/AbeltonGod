"""``length_beats`` and its -60 dB rule (kick-params v0.3, #120), tested by behaviour.

The reference below is written from the contract text alone (``length_beats`` description,
steps 1-6a) and is independent of ``audio_engine.length``: it reads the WAV bytes with the
standard library ``wave`` module, works in floating point (fractions of full scale), builds
the RMS with ``np.convolve`` and compares ``20 * log10(r / R)`` with -60 as written. The engine
uses exact integer window sums instead; the two may only disagree when a window sits within
float rounding of the -60 dB line, which the comparison allows explicitly.
"""

from __future__ import annotations

import io
import json
import math
import random
import wave

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from audio_engine import kick as K
from audio_engine import length as L
from audio_engine.io import encode_wav, render_kick_wav, rerender_from_sidecar, write_kick
from audio_engine.params import KICK_SCHEMA_FILE, KickParamsError, load_schema, resolve_kick_params

V03 = {"schema_version": "0.3", "seed": 1}


# --- independent reference (contract text) ---------------------------------------------------


def wav_fractions(wav: bytes) -> tuple[np.ndarray, int]:
    """Samples of a WAV as fractions of full scale, via the stdlib reader."""
    with wave.open(io.BytesIO(wav)) as w:
        width, sr, frames = w.getsampwidth(), w.getframerate(), w.readframes(w.getnframes())
    raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, width).astype(np.int64)
    value = sum(raw[:, b] << (8 * b) for b in range(width))
    value = np.where(value >= 1 << (8 * width - 1), value - (1 << (8 * width)), value)
    return value / float(2 ** (8 * width - 1) - 1), sr


def ref_rule(x: np.ndarray, sr: int) -> tuple[int | None, float | None, bool]:
    """(i60, level of window i60 in dB re R, fits) exactly as the contract words it."""
    n = len(x)
    big_n = sr // 200
    r = np.sqrt(np.convolve(x * x, np.ones(big_n), mode="valid") / big_n)  # i = 0 … n - N
    assert len(r) == n - big_n + 1
    big_r = float(r.max())
    i_max = int(np.flatnonzero(r == big_r)[0])
    with np.errstate(divide="ignore"):
        level = 20.0 * np.log10(r / big_r)
    later = np.flatnonzero(level[i_max + 1 :] <= -60.0)
    if len(later) == 0:
        return None, None, False
    i60 = i_max + 1 + int(later[0])
    n_fade = round(0.005 * sr)  # the engine's 5 ms end fade-out
    return i60, float(level[i60]), (i60 + big_n) / sr <= (n - n_fade) / sr


def ref_fits_wav(wav: bytes) -> bool:
    return ref_rule(*wav_fractions(wav))[2]


def assert_same_decision(wav: bytes) -> None:
    """Engine and reference agree, or the reference sits within rounding of the line."""
    x, sr = wav_fractions(wav)
    i60_ref, level, fits_ref = ref_rule(x, sr)
    ints = np.round(x * (2 ** 23 - 1 if wav[34] == 24 else 2 ** 15 - 1)).astype(np.int64)
    i60 = L.t60_window(ints, sr)
    if i60 != i60_ref:
        assert level is not None and abs(level + 60.0) < 1e-9, (i60, i60_ref, level)
    else:
        assert L.samples_fit(ints, sr) == fits_ref


def render_wav(resolved: dict) -> bytes:
    return encode_wav(K.render_resolved(resolved), resolved["sample_rate"], resolved["bit_depth"])


def ref_bisection(fits_k) -> int | None:
    """Rule (6a) as written: returns k, or None for 'rejected'."""
    if fits_k(19800):
        return 19800
    if not fits_k(0):
        return None
    lo, hi = 0, 19800
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if fits_k(mid):
            lo = mid
        else:
            hi = mid
    return lo


# --- conversion and range ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("beats", "bpm", "ms"),
    [(1, 128, 468.75), (0.25, 187.5, 80.0), (4, 120, 2000.0), (0.5, 140, 214.28571428571428),
     (2, 174, 689.6551724137931)],
)
def test_length_beats_becomes_length_ms(beats, bpm, ms) -> None:
    p = resolve_kick_params({**V03, "length_beats": beats, "bpm": bpm})
    assert p["length_ms"] == ms  # beats * 60000 / bpm, computed by hand above
    assert "length_beats" not in p
    _, audio, _ = render_kick_wav(p)
    assert len(audio) == round(ms * 48000 / 1000)


@pytest.mark.parametrize(
    ("beats", "bpm", "shown"),
    [
        # Allowed beats = [max(0.25, 80*bpm/60000), min(4, 2000*bpm/60000)], shown on a
        # 4-decimal grid inside it (computed by hand): the schema's 0.25 ... 4 always applies.
        (0.25, 200, "0.2667 ... 4"),  # 0.26667 ... 6.667 -> upper end is the schema's 4
        (0.25, 187.6, "0.2502 ... 4"),  # 0.250133 rounded up
        (4, 119.9, "0.25 ... 3.9966"),  # 3.99667 rounded down
        (4, 60, "0.25 ... 2"),
        (3, 80, "0.25 ... 2.6666"),
    ],
)
def test_length_outside_80_to_2000_ms_is_rejected(beats, bpm, shown) -> None:
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**V03, "length_beats": beats, "bpm": bpm})
    text = str(exc.value)
    assert "length_beats" in text and "80 ... 2000 ms" in text
    assert f"length_beats must lie in {shown}" in text


@pytest.fixture
def no_rule(monkeypatch):
    """Range tests only: skip the -60 dB rule (it needs renders and is tested elsewhere)."""
    monkeypatch.setattr(L, "apply_length_rule", lambda resolved, beats, given: None)


def test_exact_boundaries_are_accepted_despite_float_rounding(no_rule) -> None:
    """PR #130 review, problem 3: 2.14 beats at 64.2 BPM is exactly 2000 ms but computes as
    2000.0000000000002. Every beats value on a 0.01 grid whose exact length is 80 or 2000 ms
    (bpm = beats * 750 or beats * 30) is accepted. A value that rounds outside becomes exactly
    the limit; one that rounds inside keeps the formula's value."""
    outside = 0
    for hundredths in range(25, 401):
        beats = hundredths / 100
        for bpm, limit in ((beats * 30, 2000.0), (beats * 750, 80.0)):
            if not 60 <= bpm <= 200:
                continue
            raw = beats * 60000 / bpm
            p = resolve_kick_params({**V03, "length_beats": beats, "bpm": bpm})
            assert 80 <= p["length_ms"] <= 2000 and abs(p["length_ms"] - limit) < 1e-9
            if not 80 <= raw <= 2000:
                outside += 1
                assert p["length_ms"] == limit, (beats, bpm)
            else:
                assert p["length_ms"] == raw
    assert outside > 10  # the float problem really occurs on this grid
    # The lower limit: 0.250422 beats at 187.8165 BPM is exactly 80 ms, computes as
    # 79.99999999999999 (found by search; the 0.01 grid above has no such case at 80 ms).
    assert 0.250422 * 60000 / 187.8165 < 80
    assert resolve_kick_params({**V03, "length_beats": 0.250422, "bpm": 187.8165})[
        "length_ms"] == 80.0
    # Beyond the epsilon it stays an error: 2000.000001 ms and 80 - 1e-6 ms are refused.
    for beats, bpm in ((4, 119.99999994), (0.25, 187.5 * 80 / (80 - 1e-6))):
        assert abs(beats * 60000 / bpm - (2000 if beats == 4 else 80)) > 1e-7
        with pytest.raises(KickParamsError, match="80 ... 2000 ms"):
            resolve_kick_params({**V03, "length_beats": beats, "bpm": bpm})
    p = resolve_kick_params({**V03, "length_beats": 2.14, "bpm": 64.2})
    assert p["length_ms"] == 2000.0
    Draft202012Validator(load_schema(KICK_SCHEMA_FILE)).validate(p)


@pytest.mark.parametrize("i", range(200))
def test_shown_beat_range_is_accepted_and_just_outside_is_not(no_rule, i) -> None:
    """Seeded over the bpm range: both ends of the range an error shows (formula of the
    parametrized test above) are accepted; 0.001 beats outside the true range is rejected.
    Where the request is outside, the shown range is read back from the message itself."""
    rng = random.Random(160130 + i)
    bpm = rng.choice([60, 200, rng.uniform(60, 200), round(rng.uniform(60, 200), 1)])
    b_lo = math.ceil(max(0.25, 80 * bpm / 60000) * 1e4) / 1e4
    b_hi = math.floor(min(4.0, 2000 * bpm / 60000) * 1e4) / 1e4
    if bpm < 119.9:  # 4 beats are longer than 2000 ms here: compare with the message
        with pytest.raises(KickParamsError) as exc:
            resolve_kick_params({**V03, "length_beats": 4, "bpm": bpm})
        assert f"must lie in {b_lo:g} ... {b_hi:g}" in str(exc.value)
    for beats in (b_lo, b_hi):
        p = resolve_kick_params({**V03, "length_beats": beats, "bpm": bpm})
        assert 80 <= p["length_ms"] <= 2000
    true_lo, true_hi = 80 * bpm / 60000, 2000 * bpm / 60000
    for beats in (true_lo - 0.001, true_hi + 0.001):
        if 0.25 <= beats <= 4:
            with pytest.raises(KickParamsError, match="80 ... 2000 ms"):
                resolve_kick_params({**V03, "length_beats": beats, "bpm": bpm})


def test_length_range_check_comes_before_any_render(monkeypatch) -> None:
    def boom(p):
        raise AssertionError("rendered before the range check")

    monkeypatch.setattr(L, "render_resolved", boom)
    with pytest.raises(KickParamsError, match="80 ... 2000 ms"):
        resolve_kick_params({**V03, "length_beats": 4, "bpm": 61.5, "seed": 999})


def test_length_beats_needs_bpm_and_excludes_length_ms() -> None:
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**V03, "length_beats": 1})
    assert "- length_beats: requires bpm" in str(exc.value)
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**V03, "length_beats": 1, "bpm": 128, "length_ms": 450})
    assert "- length_beats: cannot be combined with length_ms" in str(exc.value)
    assert "should not be valid under" not in str(exc.value)
    assert "unknown field" not in str(exc.value)


# --- the rule on crafted sample sequences ------------------------------------------------------


def _decay(n: int, sr: int, db_per_ms: float, start: int = 0) -> np.ndarray:
    """Integer full-scale noise-free signal: a 1 kHz square-ish tone decaying linearly in dB."""
    t = np.arange(n)
    level = np.where(t < start, 0.0, 10.0 ** (-(t - start) / sr * 1000 * db_per_ms / 20))
    sign = np.where((t // 24) % 2 == 0, 1, -1)
    return np.round(sign * level * (2**23 - 1)).astype(np.int64)


def test_t60_is_the_end_of_the_first_window_60_db_down() -> None:
    sr, n = 48000, 48000
    ints = _decay(n, sr, 0.25)  # -60 dB after 240 ms
    i60 = L.t60_window(ints, sr)
    x = ints / (2**23 - 1)
    i60_ref, level, _ = ref_rule(x, sr)
    assert i60 == i60_ref and level <= -60.0
    assert L.t60_seconds(ints, sr) == (i60 + 240) / sr  # window END, not start


def test_window_hop_is_one_sample() -> None:
    """Shifting the signal by one sample moves i60 by exactly one sample."""
    sr = 48000
    a = _decay(30000, sr, 0.3)
    b = np.concatenate([[0], a[:-1]])
    assert L.t60_window(b, sr) == L.t60_window(a, sr) + 1


def test_reference_is_the_first_maximum() -> None:
    """Two equal RMS maxima: the search starts after the first one."""
    sr = 48000
    block = np.full(240, 1000, dtype=np.int64)
    quiet = np.zeros(400, dtype=np.int64)
    ints = np.concatenate([block, quiet, block, quiet, np.zeros(2000, dtype=np.int64)])
    # First max at i = 0; the first window after it at -60 dB (all zero) starts at 240.
    assert L.t60_window(ints, sr) == 240
    i60_ref, _, _ = ref_rule(ints / 32767.0, sr)
    assert i60_ref == 240


def test_threshold_is_inclusive_and_exact() -> None:
    """A window exactly 60 dB (power ratio 1e-6) below R counts; one unit above does not."""
    sr = 48000
    loud = np.full(240, 10**4, dtype=np.int64)  # S_max = 240 * 10**8
    for value, expect in ((10, True), (11, False)):  # S = 240 * value**2; ratio 1e-6 at 10
        tail = np.full(2000, value, dtype=np.int64)
        ints = np.concatenate([loud, tail])
        i60 = L.t60_window(ints, sr)
        assert (i60 is not None and i60 >= 240) == expect, value


def test_end_fade_out_never_counts() -> None:
    """The -60 dB window must end before the last 5 ms; ending inside them is no fit."""
    sr, n = 48000, 4800
    loud = np.full(240, 10**4, dtype=np.int64)
    for gap_end, expect in ((n - 240, True), (n - 239, False)):
        ints = np.zeros(n, dtype=np.int64)
        ints[:240] = loud
        # Keep the level up until the window that first reaches -60 dB ends at gap_end.
        ints[240 : gap_end - 240] = 10**4
        assert L.samples_fit(ints, sr) == expect, gap_end
        assert ref_rule(ints / 32767.0, sr)[2] == expect


def test_no_window_below_minus_60_db_does_not_fit() -> None:
    sr = 48000
    ints = _decay(4800, sr, 0.01)  # only -1 dB over the file
    assert L.t60_window(ints, sr) is None and not L.samples_fit(ints, sr)
    assert L.t60_window(np.zeros(4800, dtype=np.int64), sr) is None  # silence
    assert L.t60_window(np.ones(100, dtype=np.int64), sr) is None  # shorter than N


def test_window_length_follows_the_sample_rate() -> None:
    assert (L.window_samples(48000), L.window_samples(44100)) == (240, 220)
    assert (K.fade_out_samples(10**5, 48000), K.fade_out_samples(10**5, 44100)) == (240, 220)


def test_rule_reads_the_quantised_samples(monkeypatch) -> None:
    """A float tail that is 60 dB down only after quantisation to 16 bit (it rounds to zero)
    fits at 16 bit and not at 24 bit."""
    sr, n = 48000, 4800

    def fake_render(p):
        x = np.zeros(n)
        x[:480] = 0.0004 * np.sign(np.sin(np.arange(1, 481)))
        x[480:] = 0.0000013 * np.sign(np.sin(np.arange(481, n + 1)))  # -49.8 dB re head
        return x

    monkeypatch.setattr(L, "render_resolved", fake_render)
    base = {"sample_rate": sr, "length_ms": 100.0, "amp_decay_ms": 50.0, "seed": 3}
    # 16 bit: head = round(0.0004 * 32767) = 13, tail = round(0.0000013 * 32767) = 0 -> fits.
    # 24 bit: head = 3355, tail = 11 -> 20*log10(11/3355) = -49.7 dB -> does not fit.
    assert L._render_fits({**base, "bit_depth": 16}) is True
    assert L._render_fits({**base, "bit_depth": 24}) is False


# --- bisection exactly as written ------------------------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_bisection_follows_the_contract_on_any_predicate(monkeypatch, seed) -> None:
    """Including non-monotonic predicates: the engine probes and returns what the written
    algorithm does, and the result always fits."""
    rng = random.Random(9120 + seed)
    table = {}

    def predicate(k: int) -> bool:
        if k not in table:
            table[k] = rng.random() < 0.6
        return table[k]

    calls = []

    def fake_fits_cached(key: str) -> bool:
        k = round((json.loads(key)["amp_decay_ms"] - 20.0) * 10)
        calls.append(k)
        return predicate(k)

    monkeypatch.setattr(L, "_fits_cached", fake_fits_cached)
    L._derive_cached.cache_clear()
    got = L.derive_amp_decay({"seed": seed, "probe": "bisection"})
    L._derive_cached.cache_clear()
    probes = []
    expected = ref_bisection(lambda k: probes.append(k) or predicate(k))
    assert calls == probes
    if expected is None:
        assert got is None
    else:
        assert got == round(20 + expected / 10, 1)
        assert predicate(expected)


def test_grid_values() -> None:
    assert [L.grid_value(k) for k in (0, 1, 9, 10, 4113, 19799, 19800)] == [
        20.0, 20.1, 20.9, 21.0, 431.3, 1999.9, 2000.0]
    assert all(L.grid_value(k) == round(20 + k / 10, 1) for k in range(0, 19801, 7))


# --- derived and explicit amp_decay_ms on real renders ------------------------------------------


def _random_beats_request(rng: random.Random) -> dict:
    bpm = rng.uniform(60, 200)
    lo, hi = max(0.25, 80 * bpm / 60000), min(4.0, 2000 * bpm / 60000)
    req = {
        **V03, "seed": rng.randrange(2**32), "bpm": bpm, "length_beats": rng.uniform(lo, hi),
        "sample_rate": rng.choice([44100, 48000]), "bit_depth": rng.choice([16, 24]),
        "drive": rng.choice([0.0, rng.uniform(0, 1)]), "tone": rng.uniform(-1, 1),
        "click_level": rng.uniform(0, 1), "click_tone_hz": rng.uniform(500, 12000),
        "click_decay_ms": rng.uniform(0.5, 12), "click_q": rng.uniform(0.5, 8),
        "amp_attack_ms": rng.choice([0.0, rng.uniform(0, 20)]),
        "pitch_decay_ms": rng.uniform(2, 300), "offset_ms": rng.uniform(0, 12),
        "clip_db": rng.choice([0.0, rng.uniform(0, 12)]), "polarity": rng.choice([1, -1]),
        "peak_ceiling_dbfs": rng.uniform(-12, -0.1),
    }
    if rng.random() < 0.5:
        req["tail_note"] = rng.randint(23, 46)
        req["pitch_start_hz"] = rng.uniform(117, 600)
    else:
        req["pitch_end_hz"] = rng.uniform(30, 120)
        req["pitch_start_hz"] = rng.uniform(req["pitch_end_hz"], 600)
    return req


RANDOM_REQUESTS = [_random_beats_request(random.Random(20120 + i)) for i in range(14)]


@pytest.mark.parametrize("req", RANDOM_REQUESTS, ids=lambda r: f"seed{r['seed']}")
def test_derived_decay_fits_and_the_next_grid_value_does_not(req) -> None:
    """Property over the whole range, checked with the independent reference on the WAV."""
    try:
        p = resolve_kick_params(req)
    except KickParamsError as exc:
        # Only the (6a) rejection is acceptable here; confirm it with the reference.
        assert "found no amp_decay_ms of 20 ms or more" in str(exc)
        assert not ref_fits_wav(render_wav(as_ms_request(req, 20.0)))
        return
    d = p["amp_decay_ms"]
    wav = render_wav(p)
    assert ref_fits_wav(wav), d
    assert_same_decision(wav)
    assert render_kick_wav(p)[0] == wav  # the rule saw exactly the bytes that are written
    if d < 2000.0:
        nxt = render_wav({**p, "amp_decay_ms": round(d + 0.1, 1)})
        assert not ref_fits_wav(nxt), d
        assert_same_decision(nxt)


def test_explicit_decay_that_fits_is_kept() -> None:
    req = {**V03, "length_beats": 1, "bpm": 128, "drive": 0.2}
    derived = resolve_kick_params(req)["amp_decay_ms"]
    for value in (20, 100.5, derived):
        p = resolve_kick_params({**req, "amp_decay_ms": value})
        assert p["amp_decay_ms"] == value
        assert ref_fits_wav(render_wav(p))


def test_explicit_decay_that_does_not_fit_is_rejected_naming_the_derived_value() -> None:
    req = {**V03, "length_beats": 1, "bpm": 128, "drive": 0.2}
    derived = resolve_kick_params(req)["amp_decay_ms"]
    too_long = round(derived + 0.1, 1)
    assert not ref_fits_wav(render_wav({**resolve_kick_params(req), "amp_decay_ms": too_long}))
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**req, "amp_decay_ms": too_long})
    text = str(exc.value)
    assert f"amp_decay_ms {too_long} does not decay 60 dB" in text
    assert f"derives {derived}" in text and "never shortened" in text


# A request where even 20 ms does not fit: 80 ms file, 12 ms lead-in, 20 ms attack, a long
# click (window 60 ms) at full level. Found by search while writing this test.
NO_FIT = {
    **V03, "length_beats": 0.25, "bpm": 187.5, "offset_ms": 12, "amp_attack_ms": 20,
    "click_level": 1.0, "click_decay_ms": 12, "drive": 1.0,
}


def as_ms_request(req: dict, decay_ms: float) -> dict:
    """The same kick as a length_ms request with a given amp_decay_ms (no rule applied)."""
    out = {k: v for k, v in req.items() if k != "length_beats"}
    return resolve_kick_params(
        {**out, "length_ms": req["length_beats"] * 60000 / req["bpm"], "amp_decay_ms": decay_ms}
    )


def test_no_fitting_decay_is_rejected_with_the_contract_wording() -> None:
    # The reference agrees that 20 ms does not fit here.
    assert not ref_fits_wav(render_wav(as_ms_request(NO_FIT, 20.0)))
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params(NO_FIT)
    text = str(exc.value)
    assert (
        "the contract's bisection (rule 6a) found no amp_decay_ms of 20 ms or more that "
        "decays 60 dB within length_beats at this bpm"
    ) in text
    # Truthful (PR #130 review): it claims only that 20.0 ms does not fit.
    assert "20.0 ms does not fit" in text and "a larger explicit amp_decay_ms may" in text


def test_explicit_decay_when_nothing_fits_uses_the_6a_wording() -> None:
    """Nit 1 of the PR #114 round-2 review: no derived value exists to name."""
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**NO_FIT, "amp_decay_ms": 300})
    text = str(exc.value)
    assert "amp_decay_ms 300: the contract's bisection (rule 6a) found no amp_decay_ms" in text
    assert "derives" not in text


# PR #130 review, case 8 (reviewer seed 4242): 'fits' is not monotonic here. 20.0 … 23.0 ms
# do not fit, 23.1 ms does (and up to about 57.5 ms). The contract's bisection probes 2000.0
# and 20.0, both do not fit, so (6a) rejects although explicit values fit. Today's
# documented behaviour, pinned until #131 decides the rule; cause not established.
NON_MONOTONE = {
    "schema_version": "0.3", "seed": 8, "bpm": 143.57900286590456,
    "length_beats": 0.2716507875933293, "amp_attack_ms": 17.932543080219805,
    "offset_ms": 7.51494471890089, "drive": 0.9082857833356175, "clip_db": 8.91860023009783,
    "pitch_end_hz": 30, "pitch_start_hz": 68.68954745687981, "pitch_decay_ms": 300,
    "click_level": 1, "click_decay_ms": 12, "tone": -0.15456163358807595,
}


def test_non_monotone_case_is_pinned() -> None:
    req = NON_MONOTONE
    # The independent reference sees the non-monotone pattern on the WAV.
    pattern = {d: ref_fits_wav(render_wav(as_ms_request(req, d)))
               for d in (20.0, 23.0, 23.1, 25.0, 40.0, 57.0, 60.0, 2000.0)}
    assert pattern == {20.0: False, 23.0: False, 23.1: True, 25.0: True, 40.0: True,
                       57.0: True, 60.0: False, 2000.0: False}
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params(req)
    assert "20.0 ms does not fit" in str(exc.value)
    assert "a larger explicit amp_decay_ms may" in str(exc.value)
    assert resolve_kick_params({**req, "amp_decay_ms": 25.0})["amp_decay_ms"] == 25.0
    # The engine's own check agrees with the reference at every probed value.
    for d, expected in pattern.items():
        assert L.fits(as_ms_request(req, d)) == expected, d


def test_long_enough_length_gives_the_grid_maximum() -> None:
    p = resolve_kick_params({**V03, "length_beats": 4, "bpm": 120, "drive": 0})
    assert p["amp_decay_ms"] == 2000.0
    assert ref_fits_wav(render_wav(p))


def test_derivation_is_deterministic_and_cache_independent() -> None:
    req = {**V03, "length_beats": 0.5, "bpm": 140, "drive": 0.45, "seed": 77}
    first = resolve_kick_params(req)
    L._fits_cached.cache_clear()
    L._derive_cached.cache_clear()
    assert resolve_kick_params(req) == first


# --- resolved form -------------------------------------------------------------------------


def test_resolved_form_is_idempotent_and_rerenders_byte_identically(tmp_path) -> None:
    for i, req in enumerate(RANDOM_REQUESTS[:6]):
        try:
            p = resolve_kick_params(req)
        except KickParamsError:
            continue
        assert not {"length_beats", "tail_note"} & set(p)
        assert resolve_kick_params(p) == p
        assert resolve_kick_params(json.loads(json.dumps(p))) == p
        wav_path, json_path = write_kick(req, tmp_path, name=f"k{i}")
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        # The sidecar drops the batch field "variants", as it always has.
        assert meta["parameters"] == {k: v for k, v in p.items() if k != "variants"}
        assert rerender_from_sidecar(json_path) == wav_path.read_bytes()
        assert math.isclose(p["length_ms"] * p["bpm"] / 60000, req["length_beats"],
                            rel_tol=1e-12)


def test_rerender_of_a_resolved_form_derives_nothing(tmp_path, monkeypatch) -> None:
    _, json_path = write_kick({**V03, "length_beats": 1, "bpm": 130, "seed": 5}, tmp_path)

    def boom(*a, **k):
        raise AssertionError("re-render ran the -60 dB rule again")

    monkeypatch.setattr(L, "apply_length_rule", boom)
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    wav = rerender_from_sidecar(json_path)
    import hashlib

    assert hashlib.sha256(wav).hexdigest() == meta["sha256"]


# --- monotonicity spot check (#120 item 2; full scan in the PR) ----------------------------------


@pytest.mark.parametrize("req", RANDOM_REQUESTS[:3], ids=lambda r: f"seed{r['seed']}")
def test_fits_changes_once_near_the_derived_value(req) -> None:
    """Every grid value within 1 ms below the derived one fits, every one within 1 ms above
    does not (a spot check; the bisection does not rely on it)."""
    try:
        p = resolve_kick_params(req)
    except KickParamsError:
        pytest.skip("no fitting decay for this request")
    k = round((p["amp_decay_ms"] - 20) * 10)
    for j in range(max(0, k - 10), min(19800, k + 10) + 1):
        assert L.fits({**p, "amp_decay_ms": L.grid_value(j)}) == (j <= k), L.grid_value(j)
