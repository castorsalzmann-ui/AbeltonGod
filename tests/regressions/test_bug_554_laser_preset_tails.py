"""#554: four shipped laser presets had a ``length_ms`` shorter than their own sound, so the
engine cut the echo tail with the fade (contract laser-params, point 12: "A sound longer than
length_ms is cut with the fade").

Measured before the fix (commit f66490b, each preset with its own seed; end level as defined
below, relative to the file's peak):

    ion            length_ms 1200   -37.1 dB
    pew-wide-echo  length_ms 1000   -31.0 dB
    glitch         length_ms  700   -52.9 dB
    blaster-echo   length_ms 2500   -72.9 dB

The first two fail the bound below; glitch and blaster-echo passed it and were lengthened
because the lead decided that every shipped laser preset is long enough for its own tail.
The other ten presets were between -63.7 dB (subboom) and -122.8 dB. Fix: preset data only
(``length_ms`` 2890 / 2160 / 1280 / 3030), no engine change. pew-wide-echo is 2160 and not
the 2150 its tail needs: at exactly 2150 ms one 24-bit sample sat on a rounding boundary and
the WAV bytes differed between machines (CI run 42849157745; guarded by
``test_laser_v02.test_bytes_do_not_depend_on_last_bit_noise_of_the_voice``).

End level = loudest sample (either channel) in the 20 ms before the final fade, relative to
the loudest sample of the file. The fade is 5 ms, or 50 ms when ``reverb_mix`` is above 0
(contract point 16); both numbers are written here, not read from the engine. This measures
the rendered audio; it does not compare ``length_ms`` with a length formula.

The JSON case format of ``test_regressions.py`` renders kick-params only, so it does not fit
a laser preset; the bad values are recorded in ``BEFORE_FIX`` instead.
"""

from __future__ import annotations

import numpy as np
import pytest

from audio_engine.laser import render_laser, resolve_laser_params
from audio_engine.presets import load_preset, preset_names

# A preset that rang out is below this 20 ms before the fade. Chosen from the measurement:
# the two cut presets were at -31.0 and -37.1 dB, every preset after the fix is at or below
# -63.7 dB (subboom), so the bound has more than 12 dB of margin on both sides.
RANG_OUT_DB = -50.0
BEFORE_FIX = {"commit": "f66490b", "end_db": {"ion": -37.1, "pew-wide-echo": -31.0}}
WINDOW_MS = 20.0


def end_db(audio: np.ndarray, sample_rate: int, fade_ms: float) -> float:
    peak = float(np.max(np.abs(audio)))
    stop = len(audio) - int(round(fade_ms * sample_rate / 1000.0))
    start = stop - int(round(WINDOW_MS * sample_rate / 1000.0))
    assert peak > 0.0 and start > 0
    return 20.0 * float(np.log10(max(float(np.max(np.abs(audio[start:stop]))), 1e-12) / peak))


def preset_end_db(name: str, **override: float) -> float:
    r = resolve_laser_params({**load_preset(name, "laser"), **override})
    audio = render_laser({k: v for k, v in r.items() if k != "seed"}, r["seed"])
    fade_ms = 50.0 if r.get("reverb_mix", 0) > 0 else 5.0
    return end_db(audio, int(r["sample_rate"]), fade_ms)


def test_the_recorded_bad_values_are_outside_the_bound() -> None:
    assert all(v > RANG_OUT_DB for v in BEFORE_FIX["end_db"].values())


@pytest.mark.parametrize("name", preset_names("laser"))
def test_shipped_laser_preset_rings_out_before_the_fade(name: str) -> None:
    level = preset_end_db(name)
    assert level < RANG_OUT_DB, (
        f"{name}: {level:.1f} dB below peak 20 ms before the fade; length_ms is too short "
        f"for the preset's own tail")


@pytest.mark.parametrize("name,old_length_ms", [("ion", 1200), ("pew-wide-echo", 1000)])
def test_the_old_lengths_fail_the_measurement(name: str, old_length_ms: int) -> None:
    """The check can fail: with the length shipped before the fix the tail is still loud."""
    level = preset_end_db(name, length_ms=old_length_ms)
    assert level == pytest.approx(BEFORE_FIX["end_db"][name], abs=0.5)
    assert level > RANG_OUT_DB


def test_end_level_of_a_hand_made_signal() -> None:
    """Independent check of the measurement: a constant 0.1 that jumps to 1.0 for one sample
    is -20 dB; silence in the window gives the -240 dB floor."""
    sr = 48000
    x = np.full((sr, 2), 0.1)
    x[100, 0] = 1.0
    assert end_db(x, sr, 5.0) == pytest.approx(-20.0, abs=1e-9)
    x[sr - 240 - 960: sr - 240] = 0.0  # exactly the 20 ms window before a 5 ms fade
    assert end_db(x, sr, 5.0) == pytest.approx(-240.0, abs=1e-9)
    x[sr - 240 - 961, 1] = 0.5  # one sample before the window: not counted
    x[sr - 240, 1] = 0.5  # first sample of the fade: not counted
    assert end_db(x, sr, 5.0) == pytest.approx(-240.0, abs=1e-9)
