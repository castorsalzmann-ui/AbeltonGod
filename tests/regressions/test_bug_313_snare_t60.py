"""Bug #313: the sidecar ``t60_ms`` of a snare read ~325 ms for every preset.

Cause (shown by switch-off in #313 and in the lead's proposal): the snare's DC removal leaves a
sub-audio floor near -47 dB in the file; the 1 ms RMS envelope sat close to the -60 dB threshold
for the whole tail, so the first crossing landed late. Fix: ``analyse_nonpitched`` reads
``t60_ms`` on a copy high-passed at 30 Hz. The WAV bytes are untouched.

Before the fix (origin/main c8aa1e3, float render, seed 1): tight 326.292, default 325.75,
long 459.188 ms for noise_decay_ms 90 / 180 / 350. The reference below is independent of the
fix: an FFT brick-wall high-pass and its own first-crossing search (not ``dsp.rbj_highpass``,
not ``analysis.t60_ms``).
"""

from __future__ import annotations

import numpy as np
import pytest

from audio_engine import analysis
from audio_engine.presets import load_preset
from audio_engine.snare import render_snare

SR = 48000


def _ref_t60_ms(x: np.ndarray, hp_hz: float = 30.0) -> float | None:
    spec = np.fft.rfft(x)
    spec[np.fft.rfftfreq(len(x), 1.0 / SR) < hp_hz] = 0.0
    y = np.fft.irfft(spec, len(x))
    win = SR // 1000
    c = np.concatenate([[0.0], np.cumsum(y * y)])
    env = np.sqrt((c[win:] - c[:-win]) / win)  # trailing 1 ms RMS (offset by < 1 ms)
    pk = int(np.argmax(env))
    stop = len(env) - int(0.006 * SR)
    hit = np.nonzero(env[pk:stop] <= env[pk] * 1e-3)[0]
    return None if len(hit) == 0 else float(hit[0]) / SR * 1000.0


def _t60(params: dict) -> float:
    a, _ = render_snare(params)
    got = analysis.analyse_nonpitched(a, SR)["t60_ms"]
    assert got is not None
    return got


# Measured on main before the fix: 326.3 / 325.8 / 459.2. Measured after: 79.5 / 156.3 / 296.4.
@pytest.mark.parametrize("name,decay", [("tight", 90.0), ("default", 180.0), ("long", 350.0)])
def test_preset_t60_follows_noise_decay(name: str, decay: float) -> None:
    got = _t60(load_preset(name, "snare"))
    assert 0.78 * decay <= got <= 1.02 * decay, (name, got)


def test_t60_is_not_a_floor_shared_by_all_presets() -> None:
    tight, default = (_t60(load_preset(n, "snare")) for n in ("tight", "default"))
    assert default - tight > 50.0


@pytest.mark.parametrize("seed", range(12))
def test_t60_over_the_decay_range_matches_independent_measure(seed: int) -> None:
    """Seeded random noise_decay_ms over the contract range that fits the 400 ms default length."""
    rng = np.random.default_rng(31300 + seed)
    decay = float(rng.uniform(60.0, 260.0))
    body = float(rng.uniform(40.0, 250.0))
    p = {**load_preset("default", "snare"), "seed": int(rng.integers(1, 10**6)),
         "noise_decay_ms": decay, "body_decay_ms": body}
    a, _ = render_snare(p)
    got = analysis.analyse_nonpitched(a, SR)["t60_ms"]
    ref = _ref_t60_ms(a)
    assert got is not None and ref is not None
    assert got == pytest.approx(ref, rel=0.10)  # noisy first crossing; spread cause not isolated
    assert 0.6 * decay <= got <= 1.05 * max(decay, body), (decay, body, got)  # slower layer ends it


def test_the_high_pass_is_what_fixes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fault injection kept as a test: with the high-pass off the old ~325 ms floor returns, so
    the preset test above turns red for exactly this reason."""
    monkeypatch.setattr(analysis, "T60_HP_HZ", 0.0)
    assert _t60(load_preset("tight", "snare")) > 300.0
