"""Bug #547: the riser presets start with an audible noise bed (user, Windows exe, 2026-11-09).

Measured on origin/main 3f07f1e (seed 1, 48 kHz / 24 bit, file peak at -1.0 dBFS): the first
10 ms of ``riser-8bar`` sit at -61.2 dB RMS relative to the file peak (-62.2 dBFS absolute).

Cause (switch-off in #547, riser-8bar): the engine follows the contract; the start level is the
riser's kind default ``level_start_db`` -36 dB plus the narrow band-pass at 300 Hz. Level flat
at 0 dB: -26.0 dB re peak in the first 10 ms (filter sweep alone, -11 dB against a static 9 kHz
band); filter static at 9 kHz: -49.4 (level ramp alone); both flat: -15.0 (the noise's own
crest). -15.0 - 11.0 - 36 = -62 against -61.2 measured, so no stage other than these two (not
the reverb, not the normalisation, no dither exists) lifts the start. Fix: the three riser
presets set ``level_start_db`` to -60 (the contract minimum), a named override (presets are
overrides on top of the kind defaults). The engine bytes for given parameters are unchanged.

The reference measure below is independent of the engine: plain RMS and peak of the rendered
float buffer in numpy, no engine analysis helper.
"""

from __future__ import annotations

import numpy as np
import pytest

from audio_engine.fx import render_fx
from audio_engine.presets import load_preset

SR = 48000
WINDOWS_MS = (10, 50, 100)
# Start RMS of each window relative to the file peak must be at most this (dB). Chosen as
# "near silence": 20 dB below the -60 dBFS that a -36 dB start reaches, with ~4 dB margin to
# the fixed riser-8bar at 100 ms (-84.0 measured).
BOUND_DB = -80.0
# before the fix (origin/main 3f07f1e): first 10 / 50 / 100 ms, RMS dB re file peak
BEFORE_FIX = {
    "riser-8bar": (-61.2, -61.1, -60.3),
    "riser-16bar": (-61.8, -61.7, -60.9),
    "riser-32bar": (-61.9, -61.8, -61.1),
}


def start_levels_db(audio: np.ndarray) -> list[float]:
    peak = float(np.max(np.abs(audio)))
    out = []
    for ms in WINDOWS_MS:
        w = audio[: SR * ms // 1000]
        out.append(20.0 * np.log10(np.sqrt(np.mean(w * w)) / peak))
    return out


def test_before_fix_values_lie_outside_the_bound() -> None:
    for values in BEFORE_FIX.values():
        assert all(v > BOUND_DB for v in values)


@pytest.mark.parametrize("name", sorted(BEFORE_FIX))
def test_riser_preset_starts_near_silence(name: str) -> None:
    audio, p = render_fx(load_preset(name, "fx"))
    assert int(p["sample_rate"]) == SR
    got = start_levels_db(audio)
    assert all(v <= BOUND_DB for v in got), (name, [round(v, 1) for v in got])
