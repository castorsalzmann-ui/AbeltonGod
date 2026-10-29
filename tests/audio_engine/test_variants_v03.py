"""Variants of kick-params v0.3 requests (#120 item 3): the note is kept, and every variant of
a ``length_beats`` request decays 60 dB before its end (checked with the independent
reference of ``test_length_rule.py``)."""

from __future__ import annotations

import math
import random

import pytest
from test_length_rule import ref_fits_wav, render_wav  # same folder (rootdir import mode)

from audio_engine.length import derive_amp_decay
from audio_engine.params import (
    NOTE_HZ,
    max_settled_pitch_decay_ms,
    pitch_settles,
    resolve_kick_params,
    tail_note_of,
)
from audio_engine.variants import make_variant, make_variants

V03 = {"schema_version": "0.3", "seed": 1}


def _note_request(rng: random.Random) -> dict:
    return {
        **V03, "seed": rng.randrange(2**32), "tail_note": rng.randint(23, 46),
        "pitch_start_hz": rng.uniform(140, 600), "drive": rng.uniform(0, 1),
        "click_q": rng.uniform(0.5, 8), "polarity": rng.choice([1, -1]),
    }


@pytest.mark.parametrize("i", range(10))
def test_tail_note_variants_keep_the_note(i) -> None:
    req = _note_request(random.Random(130120 + i))
    variants = make_variants(req, 8)
    for v in variants:
        assert v["pitch_end_hz"] == NOTE_HZ[req["tail_note"]]
        assert tail_note_of(v) == req["tail_note"]
        assert v["pitch_start_hz"] >= v["pitch_end_hz"]
        assert "tail_note" not in v
        assert v["click_q"] == req["click_q"] and v["polarity"] == req["polarity"]
    # The other fields still spread.
    assert len({v["pitch_start_hz"] for v in variants}) == 8
    assert len({v["seed"] for v in variants}) == 8


def test_resolved_base_spreads_pitch_end_as_before() -> None:
    """A resolved form is a plain pitch_end_hz request: its variants spread the pitch (the
    note is only kept when the request itself names tail_note)."""
    req = {**V03, "tail_note": 33, "seed": 5}
    resolved = resolve_kick_params(req)
    spread = {make_variant(resolved, i)["pitch_end_hz"] for i in range(1, 6)}
    assert spread != {55.0}
    assert {make_variant(req, i)["pitch_end_hz"] for i in range(1, 6)} == {55.0}


def _beats_request(rng: random.Random, explicit: bool) -> dict:
    bpm = rng.uniform(120, 175)
    req = {
        **V03, "seed": rng.randrange(2**32), "bpm": bpm, "length_beats": rng.choice([0.5, 1, 2]),
        "drive": rng.uniform(0, 1), "tone": rng.uniform(-1, 1), "clip_db": rng.choice([0, 6]),
        "offset_ms": rng.uniform(0, 12), "sample_rate": rng.choice([44100, 48000]),
    }
    if explicit:
        derived = resolve_kick_params(req)["amp_decay_ms"]
        req["amp_decay_ms"] = round(derived * rng.uniform(0.6, 1.0), 1)
    return req


@pytest.mark.parametrize(("i", "explicit"), [(i, e) for i in range(4) for e in (False, True)])
def test_length_beats_variants_follow_the_rule(i, explicit) -> None:
    req = _beats_request(random.Random(140120 + i), explicit)
    base = resolve_kick_params(req)
    variants = make_variants(req, 6)
    assert variants[0] == {k: v for k, v in base.items() if k != "variants"}
    for v in variants:
        assert v["length_ms"] == base["length_ms"] and v["bpm"] == base["bpm"]
        assert "length_beats" not in v
        assert ref_fits_wav(render_wav(v)), (v["seed"], v["amp_decay_ms"])
    decays = [v["amp_decay_ms"] for v in variants[1:]]
    assert len(set(decays)) == len(decays)  # a range, not one clamped value
    for v, d in zip(variants[1:], decays, strict=True):
        assert 0.9 * base["amp_decay_ms"] - 1e-4 <= d <= 1.1 * base["amp_decay_ms"] + 1e-4
        # Drawn inside the allowed range, not set to the variant's own limit (a clamp would
        # put about half of them there: their spread box reaches above the limit).
        assert d != derive_amp_decay(v), d


def test_drawn_decay_that_does_not_fit_falls_back_to_the_limit(monkeypatch) -> None:
    """variants._draw_decay_by_rule fallback (PR #130 review, problem 2): where 'fits' is not
    monotonic a drawn value below the limit can fail. Forced here by a check that rejects
    every drawn value; the variant must then carry its own derived limit, which fits."""
    import audio_engine.variants as V

    req = {**V03, "seed": 21, "bpm": 140, "length_beats": 1, "drive": 0.45}
    honest = [make_variant(req, i)["amp_decay_ms"] for i in range(1, 5)]
    monkeypatch.setattr(V, "fits", lambda p: False)
    for i, drawn in zip(range(1, 5), honest, strict=True):
        v = make_variant(req, i)
        limit = derive_amp_decay(v)
        assert v["amp_decay_ms"] == limit != drawn
        assert ref_fits_wav(render_wav(v))


@pytest.mark.parametrize("i", range(4))
def test_length_beats_variants_follow_the_pitch_settle_guideline(i) -> None:
    """Base close to its guideline limit, so the variants' limit decides.

    Under length_beats the limit depends on pitch_decay_ms itself: it changes the derived
    amp_decay_ms (measured: up to about 3 %, not monotonic, see max_settled_pitch_decay_ms).
    So the base value is lowered in 1 % steps until it settles."""
    rng = random.Random(150120 + i)
    req = {**V03, "seed": rng.randrange(2**32), "bpm": rng.uniform(120, 175),
           "length_beats": rng.choice([0.5, 1, 2]), "pitch_start_hz": rng.uniform(150, 400)}
    limit = max_settled_pitch_decay_ms(req)
    for step in range(10):
        req["pitch_decay_ms"] = math.floor(limit * (1 - 0.01 * step) * 1e4) / 1e4
        if pitch_settles(req):
            break
    assert pitch_settles(resolve_kick_params(req))
    for v in make_variants(req, 8):
        assert pitch_settles(v), v


def test_length_beats_variants_are_deterministic() -> None:
    req = {**V03, "seed": 9, "bpm": 128, "length_beats": 1, "drive": 0.45}
    assert make_variants(req, 5) == make_variants(dict(req), 5)
