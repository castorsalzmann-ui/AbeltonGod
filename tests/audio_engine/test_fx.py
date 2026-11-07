"""FX transitions (#482): contract resolution, frames, measured sweep / glide / level / pump,
determinism with golden hashes, presets, variants, CLI, loudness report, fault injection.

Measurement methods are independent of the engine code (numpy only): filter centre from a Welch
spectrum peak with parabolic interpolation; tone frequency from zero crossings; level from the
RMS of windows in dB; frame counts from exact fractions. Expected values come from the contract
text, written here by hand. Each important check is a ``_check_*`` function that runs on the
engine and again on a deliberately broken engine (``test_mutant_*``), so it is shown to fail.
"""

from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

import audio_engine.fx as F
from audio_engine import fx_variants
from audio_engine.cli import main as cli_main
from audio_engine.fx import FxParamsError, render_fx, resolve_fx_params
from audio_engine.io import encode_wav, rerender_from_sidecar
from audio_engine.presets import describe, load_preset, preset_names

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(F.FX_SCHEMA_FILE.read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]
META_V = Draft202012Validator(
    json.loads((ROOT / "contracts/sample-metadata.schema.json").read_text("utf-8")))
SR = 48000
KINDS = ("riser", "downlifter", "sweep", "impact", "noise_crash", "reverse_crash")
BASE = {"schema_version": "0.1", "seed": 7, "bpm": 180}
# A plain test signal: flat noise, no tail, no reverb, no tone.
PLAIN = {**BASE, "kind": "sweep", "length_beats": 4, "tail_beats": 0, "reverb_mix": 0,
         "level_start_db": 0, "level_end_db": 0, "stereo_width": 0}


def _r(**kw) -> np.ndarray:
    return render_fx({**PLAIN, **kw})[0]


def _wav(params: dict) -> bytes:
    audio, p = render_fx(params)
    return encode_wav(audio, p["sample_rate"], p["bit_depth"])


# --- independent measurement helpers ----------------------------------------------------------


def _welch_peak_hz(x: np.ndarray, sr: int = SR, nfft: int = 8192, smooth: int = 1) -> float:
    win = np.hanning(nfft)
    acc = np.zeros(nfft // 2 + 1)
    for start in range(0, len(x) - nfft + 1, nfft // 2):
        acc += np.abs(np.fft.rfft(x[start:start + nfft] * win)) ** 2
    if smooth > 1:  # moving average over `smooth` bins (noise ripple of the periodogram)
        acc = np.convolve(acc, np.ones(smooth) / smooth, mode="same")
    k = int(np.argmax(acc[1:-1])) + 1
    a, b, c = np.log(acc[k - 1: k + 2])
    shift = 0.5 * (a - c) / (a - 2 * b + c)
    return (k + shift) * sr / nfft


def _zero_cross_hz(x: np.ndarray, sr: int = SR) -> float:
    s = np.signbit(x)
    idx = np.nonzero(s[1:] != s[:-1])[0]
    # linear interpolation of each crossing
    pos = idx + x[idx] / (x[idx] - x[idx + 1])
    return (len(pos) - 1) / 2.0 / ((pos[-1] - pos[0]) / sr)


def _pcm(wav: bytes, bits: int) -> np.ndarray:
    """Integer samples of a 44-byte-header PCM WAV (16 or 24 bit, any channel count)."""
    data = np.frombuffer(wav[44:], dtype=np.uint8)
    if bits == 16:
        return data.view("<i2").astype(np.int64)
    b = data.reshape(-1, 3).astype(np.int64)
    v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
    return np.where(v >= 1 << 23, v - (1 << 24), v)


def _rms_db(x: np.ndarray) -> float:
    return 10.0 * math.log10(float(np.mean(x * x)))


def _frames(beats, bpm, sr=SR) -> int:
    """Exact: round(beats * 60 * sr / bpm) with Fractions (ties do not occur in the tests)."""
    return round(Fraction(str(beats)) * 60 * sr / Fraction(str(bpm)))


# --- resolution and cross-field rules ---------------------------------------------------------

RESOLVED = {  # hand-written from the contract's allOf branches
    "riser": {"length_beats": 64, "tail_beats": 4, "filter_mode": "bp", "filter_q": 1.2,
              "sweep_curve": 1.5, "cutoff_start_hz": 300, "cutoff_end_hz": 9000,
              "ramp_beats": 64, "tone_glide_beats": 64, "reverb_mix": 0.3},
    "sweep": {"filter_mode": "lp", "filter_q": 4, "cutoff_end_hz": 12000, "ramp_beats": 16},
    "downlifter": {"sweep_curve": 0.7, "tone_wave": "saw", "level_end_db": -36},
    "impact": {"ramp_beats": 0.25, "tone_glide_beats": 0.5, "tone_decay_beats": 6,
               "tone_level": 1, "filter_q": 0.7071, "tail_beats": 8},
    "noise_crash": {"cutoff_start_hz": 1000, "level_end_db": -60, "length_beats": 16},
    "reverse_crash": {"tail_beats": 0, "tone_wave": "metal", "tone_level": 0.5,
                      "level_start_db": -60, "length_beats": 4},
}


@pytest.mark.parametrize("kind", KINDS)
def test_resolve_takes_the_kind_defaults(kind: str) -> None:
    p = resolve_fx_params({**BASE, "kind": kind})
    for name, value in RESOLVED[kind].items():
        assert p[name] == value, (kind, name)
    assert p["peak_ceiling_dbfs"] == -1.0 and p["echo_note"] == "1/8D"
    assert resolve_fx_params(p) == p  # idempotent
    assert resolve_fx_params({**BASE})["kind"] == "riser"
    assert resolve_fx_params({**BASE, "kind": kind, "filter_q": 9})["filter_q"] == 9


def test_cross_field_rules_are_rejected_with_text() -> None:
    # A: 128 + 16 beats at 120 BPM = 72000 ms exactly is allowed, a bit more is not
    resolve_fx_params({**BASE, "bpm": 120, "length_beats": 128, "tail_beats": 16})
    with pytest.raises(FxParamsError, match="rule A"):
        resolve_fx_params({**BASE, "bpm": 119.9, "length_beats": 128, "tail_beats": 16})
    resolve_fx_params({**BASE, "bpm": 60})  # riser default 64 + 4 beats = 68 s at 60 BPM
    with pytest.raises(FxParamsError, match="rule B"):
        resolve_fx_params({**BASE, "noise_level": 0, "tone_level": 0})
    resolve_fx_params({**BASE, "noise_level": 0, "tone_level": 0.1})
    with pytest.raises(FxParamsError, match="rule C"):
        resolve_fx_params({**BASE, "length_beats": 4, "cut_beats": 4})
    resolve_fx_params({**BASE, "length_beats": 4, "cut_beats": 3.75})
    with pytest.raises(FxParamsError):  # schema: reverse_crash has no tail
        resolve_fx_params({**BASE, "kind": "reverse_crash", "tail_beats": 1})
    for bad in ({**BASE, "wobble": 1}, {"schema_version": "0.1", "seed": 1},
                {**BASE, "drive": float("nan")}, {**BASE, "length_beats": 1.1}):
        with pytest.raises(FxParamsError):
            resolve_fx_params(bad)


def test_rule_a_bound_is_the_file_not_the_musical_length() -> None:
    """Rule A counts the tail: 124 + 16 beats at 120 BPM is 70 s and passes; 128 + 16 beats at
    119 BPM is 144 * 60000 / 119 = 72605.0 ms and fails."""
    resolve_fx_params({**BASE, "bpm": 120, "length_beats": 124, "tail_beats": 16})
    with pytest.raises(FxParamsError, match="72605.0 ms"):
        resolve_fx_params({**BASE, "bpm": 119, "length_beats": 128, "tail_beats": 16})


# --- frames and anchor --------------------------------------------------------------------------


def test_frames_and_boundary_by_hand() -> None:
    # 4 + 1 beats at 140 BPM: 102857.14 -> 102857 frames; boundary 82285.71 -> 82286
    p = resolve_fx_params({**BASE, "bpm": 140, "kind": "sweep", "length_beats": 4,
                           "tail_beats": 1})
    assert (F.file_samples(p), F.boundary_frame(p)) == (102857, 82286)
    # 32 bars at 135 BPM (research note section 3): boundary 2730667
    q = resolve_fx_params({**BASE, "bpm": 135, "length_beats": 128, "tail_beats": 4})
    assert (F.boundary_frame(q), F.file_samples(q)) == (2730667, 2816000)


def _check_frames(render) -> None:
    rng = np.random.default_rng(482)
    for _ in range(12):
        kind = KINDS[int(rng.integers(len(KINDS)))]
        bpm = round(float(rng.uniform(60, 200)), 3)
        length = int(rng.integers(4, 13)) / 4
        tail = 0 if kind == "reverse_crash" else int(rng.integers(0, 5)) / 4
        sr = int(rng.choice([44100, 48000]))
        params = {**BASE, "bpm": bpm, "kind": kind, "length_beats": length, "tail_beats": tail,
                  "sample_rate": sr, "reverb_mix": 0, "noise_level": 1}
        audio, p = render(params)
        assert audio.shape == (_frames(length + tail, bpm, sr), 2), params
        feats = F.analyse_fx(audio, sr, p)
        assert feats["boundary_frame"] == _frames(length, bpm, sr)
        assert feats["anchor"] == ("end" if kind == "reverse_crash" else "start")
        if kind == "reverse_crash":
            assert feats["boundary_frame"] == len(audio)  # N, one past the last frame


def test_frames_match_the_boundary_math() -> None:
    _check_frames(render_fx)


# --- filter: static centre and moving sweep ---------------------------------------------------


def _check_static_centre(render) -> None:
    for fc in (700.0, 3000.0):
        x = render({**PLAIN, "bpm": 60, "length_beats": 16, "filter_mode": "bp",
                    "filter_q": 12, "cutoff_start_hz": fc, "cutoff_end_hz": fc})[0][:, 0]
        got = _welch_peak_hz(x, smooth=9)
        assert abs(got / fc - 1) < 0.005, (fc, got)


def test_static_band_pass_centre() -> None:
    _check_static_centre(render_fx)


def test_svf_impulse_response_peaks_at_fc_with_0_db() -> None:
    """Fixed cutoff: the band-pass peak sits on fc at 0 dB, the lp passes DC at 0 dB, the hp
    blocks DC (the contract's 0 dB peak gain and modes)."""
    n = 1 << 17
    imp = np.zeros(n)
    imp[0] = 1.0
    f = np.fft.rfftfreq(n, 1 / SR)
    for fc, q in ((700.0, 12.0), (3000.0, 1.2), (15000.0, 4.0)):
        h = np.abs(np.fft.rfft(F.svf(imp, np.full(n, fc), q, "bp", SR)))
        k = int(np.argmax(h))
        assert abs(f[k] - fc) <= SR / n and abs(h[k] - 1.0) < 1e-3, (fc, f[k], h[k])
    lp = np.abs(np.fft.rfft(F.svf(imp, np.full(n, 1000.0), 0.7071, "lp", SR)))
    hp = np.abs(np.fft.rfft(F.svf(imp, np.full(n, 1000.0), 0.7071, "hp", SR)))
    assert abs(lp[0] - 1) < 1e-9 and hp[0] < 1e-9
    k1 = int(round(1000 * n / SR))  # Butterworth Q: -3.01 dB at fc for both
    assert abs(20 * math.log10(lp[k1]) + 3.01) < 0.05 and abs(20 * math.log10(hp[k1]) + 3.01) < 0.05


def _check_sweep_track(render) -> None:
    """bp Q 12, 500 -> 4000 Hz over 8 beats at 60 BPM, curve 2: the spectral peak of short
    windows follows 500 * 8^(s^2) (written here from the contract formula)."""
    params = {**PLAIN, "bpm": 60, "length_beats": 8, "filter_mode": "bp", "filter_q": 12,
              "cutoff_start_hz": 500, "cutoff_end_hz": 4000, "sweep_curve": 2}
    x = render(params)[0][:, 0]
    n, w = len(x), 16384
    for frac in (0.3, 0.6, 0.9):
        mid = int(frac * n)
        got = _welch_peak_hz(x[mid - w // 2: mid + w // 2], nfft=4096)
        expected = 500.0 * 8.0 ** (frac**2)
        assert abs(math.log2(got / expected)) < 1 / 24, (frac, got, expected)


def test_sweep_follows_the_cutoff_curve() -> None:
    _check_sweep_track(render_fx)


def test_sweep_end_frequency_and_direction_of_the_riser_default() -> None:
    """Riser defaults (bp Q 1.2, 300 -> 9000 Hz): the last quarter beat before the boundary
    peaks near 9000 Hz, the first near 300 Hz (a wide band in a short window: 1/2 octave)."""
    audio, p = render_fx({**BASE, "bpm": 200, "length_beats": 8, "tail_beats": 0,
                          "reverb_mix": 0, "level_start_db": 0})
    x = audio[:, 0]
    q = int(F.samples_per_beat(p) / 4)
    end, start = _welch_peak_hz(x[-q:], nfft=2048), _welch_peak_hz(x[:q], nfft=2048)
    assert abs(math.log2(end / 9000)) < 1 / 2, end
    assert abs(math.log2(start / 300)) < 1 / 2, start
    assert end / start > 16


def test_hp_lp_and_lp_modes_shape_the_noise() -> None:
    def band_db(x, lo, hi):
        spec = np.abs(np.fft.rfft(x)) ** 2
        f = np.fft.rfftfreq(len(x), 1 / SR)
        return 10 * math.log10(float(np.mean(spec[(f >= lo) & (f < hi)])))

    lp = _r(filter_mode="lp", filter_q=0.7071, cutoff_start_hz=1000, cutoff_end_hz=1000)[:, 0]
    assert band_db(lp, 200, 500) - band_db(lp, 8000, 16000) > 40  # 12 dB/oct over 3+ octaves
    hl = _r(filter_mode="hp_lp", filter_q=0.7071, cutoff_start_hz=500, cutoff_end_hz=500,
            lp_ratio=4)[:, 0]
    inside = band_db(hl, 800, 1500)
    assert inside - band_db(hl, 50, 100) > 25 and inside - band_db(hl, 10000, 16000) > 25


# --- tone ---------------------------------------------------------------------------------------


def _check_tone_glide(render) -> None:
    """Sine 150 -> 40 Hz over 1 beat at 120 BPM (0.5 s); after the glide 40 Hz exactly, at
    t = 0.25 s 150 * (40/150)^0.5 = 77.46 Hz (zero crossings of the tone alone)."""
    params = {**PLAIN, "bpm": 120, "noise_level": 0, "tone_level": 1, "tone_wave": "sine",
              "tone_start_hz": 150, "tone_end_hz": 40, "tone_glide_beats": 1,
              "tone_decay_beats": 32}
    x = render(params)[0][:, 0]
    late = x[int(0.7 * SR): int(1.9 * SR)]
    assert abs(_zero_cross_hz(late) / 40 - 1) < 0.002
    mid = x[int(0.235 * SR): int(0.265 * SR)]
    assert abs(_zero_cross_hz(mid) / 77.46 - 1) < 0.03


def test_tone_glide_frequency() -> None:
    _check_tone_glide(render_fx)


@pytest.mark.parametrize("wave", ["saw", "square", "metal"])
def test_band_limited_waves_have_no_partial_above_0_45_sr(wave: str) -> None:
    x = _r(noise_level=0, tone_level=1, tone_wave=wave, tone_start_hz=1500, tone_end_hz=1500,
           tone_decay_beats=32)[:, 0]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    top = float(np.max(spec))
    assert 10 * math.log10(float(np.max(spec[f > 0.45 * SR])) / top) < -80
    if wave == "saw":  # even partials present (2nd at 3000 Hz), square: odd only
        k2 = int(np.argmin(np.abs(f - 3000)))
        assert 10 * math.log10(float(np.max(spec[k2 - 3:k2 + 4])) / top) > -12
    if wave == "square":
        k2 = int(np.argmin(np.abs(f - 3000)))
        assert 10 * math.log10(float(np.max(spec[k2 - 3:k2 + 4])) / top) < -60


def test_tone_decay_falls_60_db_over_tone_decay_beats() -> None:
    """tone_decay_beats 2 at 120 BPM = 1 s for 60 dB: windows 0.5 s apart differ by 30 dB."""
    x = _r(bpm=120, noise_level=0, tone_level=1, tone_start_hz=1000, tone_end_hz=1000,
           tone_decay_beats=2)[:, 0]
    w = 4800
    a, b = _rms_db(x[SR // 10: SR // 10 + w]), _rms_db(x[SR * 6 // 10: SR * 6 // 10 + w])
    assert abs((a - b) - 30.0) < 0.3, a - b


def test_tone_layer_is_seed_independent_and_noise_is_not() -> None:
    tone = {"noise_level": 0, "tone_level": 1, "tone_decay_beats": 32}
    assert np.array_equal(_r(seed=1, **tone), _r(seed=2, **tone))
    assert not np.array_equal(_r(seed=1), _r(seed=2))


# --- level, dry end, tail, pump, width ----------------------------------------------------------


def _check_level_ramp(render) -> None:
    """lp at 20 kHz (flat), -30 -> 0 dB linear in dB over 4 beats: window RMS differences
    follow the line within 0.5 dB."""
    params = {**PLAIN, "bpm": 60, "filter_mode": "lp", "filter_q": 0.7071,
              "cutoff_start_hz": 20000, "cutoff_end_hz": 20000, "level_start_db": -30,
              "level_end_db": 0}
    x = render(params)[0][:, 0]
    n, w = len(x), 9600
    ref = None
    for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
        mid = int(frac * n)
        got = _rms_db(x[mid - w // 2: mid + w // 2])
        expected = -30 + 30 * frac
        if ref is None:
            ref = got - expected
        assert abs(got - expected - ref) < 0.5, (frac, got - ref, expected)


def test_level_ramp_in_db() -> None:
    _check_level_ramp(render_fx)


def test_dry_signal_ends_at_boundary_minus_cut_and_the_tail_rings() -> None:
    p = {**PLAIN, "bpm": 120, "length_beats": 4, "tail_beats": 2, "cut_beats": 1}
    x = render_fx(p)[0]
    stop = _frames(3, 120)
    assert not np.any(x[stop:])  # no reverb, no echo: silent from there
    fade = int(round(0.005 * SR))
    assert np.max(np.abs(x[stop - 4 * fade: stop - fade])) > 0.05
    with_tail = render_fx({**p, "reverb_mix": 0.5})[0]
    assert np.max(np.abs(with_tail[stop + SR // 10:])) > 1e-3  # the reverb runs on


def test_reverse_crash_ends_loud_on_the_boundary() -> None:
    audio, p = render_fx({**BASE, "bpm": 140, "kind": "reverse_crash"})
    assert len(audio) == F.boundary_frame(p) == _frames(4, 140)
    ms10 = SR // 100
    env = [_rms_db(audio[i:i + ms10]) for i in range(0, len(audio) - ms10, ms10)]
    # the 10 ms just before the end fade sits within 6 dB of the loudest 10 ms window
    last = _rms_db(audio[-ms10 - SR // 200: -SR // 200])
    assert max(env) - last < 6
    assert env[0] < max(env) - 30  # it starts quiet: a swell


def test_reverse_crash_reverb_runs_before_the_reversal() -> None:
    """Point 7: the chain runs in forward time and is reversed. A burst at the FILE start is
    the forward end, so its reverb falls outside the file: what follows is only the -60 dB
    floor and its own reverb (measured ~38 dB below the burst window). Run without the
    reversal, the burst's reverb rings after it (measured ~13 dB below at 0.25-0.35 s)."""
    p = {**BASE, "bpm": 120, "kind": "reverse_crash", "length_beats": 4, "tone_level": 0,
         "level_start_db": 0, "level_end_db": -60, "ramp_beats": 0.25, "reverb_mix": 1,
         "reverb_decay_ms": 4000, "filter_mode": "lp", "cutoff_start_hz": 20000,
         "cutoff_end_hz": 20000}
    x = render_fx(p)[0][:, 0]
    burst = _rms_db(x[: SR // 8])
    after = _rms_db(x[SR // 4: SR // 4 + 4800])
    assert burst - after > 30, burst - after


def _check_pump(render) -> None:
    """pump_depth 1: the first 2 % of every beat is far quieter than the middle of the beat,
    on the grid from frame 0 (anchor start) and from frame N (anchor end)."""
    for kind, length in (("sweep", 4.0), ("reverse_crash", 3.5)):
        params = {**PLAIN, "bpm": 120, "kind": kind, "length_beats": length,
                  "pump_depth": 1, "filter_mode": "lp", "cutoff_start_hz": 20000,
                  "cutoff_end_hz": 20000, "tone_level": 0, "level_start_db": 0,
                  "level_end_db": 0}
        x = render(params)[0][:, 0]
        spb, n = 24000, len(x)
        origin = n if kind == "reverse_crash" else 0
        starts = [origin - k * spb for k in range(1, 4)] if origin else [k * spb for k in (1, 2)]
        for s in starts:
            dip = _rms_db(x[s: s + 480])
            middle = _rms_db(x[s + 10000: s + 14000])
            assert middle - dip > 20, (kind, s, middle - dip)


def test_pump_dips_on_the_anchored_beat_grid() -> None:
    _check_pump(render_fx)


def test_stereo_width_sets_the_noise_correlation() -> None:
    for width in (0.0, 0.5, 1.0):
        x = _r(stereo_width=width, filter_mode="bp", cutoff_start_hz=2000, cutoff_end_hz=2000)
        corr = float(np.corrcoef(x[:, 0], x[:, 1])[0, 1])
        assert abs(corr - (1 - width)) < 0.03, (width, corr)
    assert np.array_equal(*_r(stereo_width=0).T)


def test_pink_noise_is_tilted_3_db_per_octave() -> None:
    x = _r(noise_color="pink", filter_mode="lp", filter_q=0.7071, cutoff_start_hz=20000,
           cutoff_end_hz=20000)[:, 0]
    spec = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)

    def band(lo):
        return 10 * math.log10(float(np.mean(spec[(f >= lo) & (f < 2 * lo)])))

    slope = (band(4000) - band(250)) / 4  # dB per octave over 4 octaves
    assert abs(slope + 3.01) < 0.3, slope


# --- peak, determinism, property test over the contract range ----------------------------------


def _draw(rng: np.random.Generator) -> dict:
    p: dict = {"schema_version": "0.1", "seed": int(rng.integers(0, 2**32))}
    for name, prop in PROPS.items():
        if name in ("schema_version", "seed", "preset", "variants"):
            continue
        if "enum" in prop:
            p[name] = prop["enum"][int(rng.integers(len(prop["enum"])))]
        else:
            pick = rng.random()
            p[name] = float(prop["minimum"] if pick < 0.08 else prop["maximum"] if pick < 0.16
                            else rng.uniform(prop["minimum"], prop["maximum"]))
    # short files keep CI fast; the long case has its own smoke test
    p["length_beats"] = int(rng.integers(4, 17)) / 4
    p["tail_beats"] = 0 if p["kind"] == "reverse_crash" else int(rng.integers(0, 9)) / 4
    p["cut_beats"] = min(p["cut_beats"], p["length_beats"] - 0.25) // 0.25 * 0.25
    p["bpm"] = float(rng.uniform(100, 200))
    p["tone_start_hz"] = max(p["tone_start_hz"], 60.0)  # bounds the additive partial count
    p["tone_end_hz"] = max(p["tone_end_hz"], 60.0)
    if rng.random() < 0.3:
        del p["ramp_beats"]
    return p


RANDOM = [_draw(np.random.default_rng(4820 + i)) for i in range(14)]


@pytest.mark.parametrize("params", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_random_contract_range_renders_valid_files(params: dict) -> None:
    audio, p = render_fx(params)
    assert audio.shape == (_frames(p["length_beats"] + p["tail_beats"], p["bpm"],
                                   p["sample_rate"]), 2)
    assert np.all(np.isfinite(audio))
    wav = encode_wav(audio, p["sample_rate"], p["bit_depth"])
    ints = _pcm(wav, p["bit_depth"])
    assert len(ints) == 2 * len(audio)
    full = 2 ** (p["bit_depth"] - 1) - 1
    ceiling = 10 ** (p["peak_ceiling_dbfs"] / 20) * full
    assert ceiling - 1.0 <= np.max(np.abs(ints)) <= ceiling, p  # point 9
    meta = {"schema_version": "0.2", "file": "fx.wav", "category": "fx",
            "engine": {"name": F.FX_NAME, "version": F.FX_VERSION}, "parameters": p,
            "features": F.analyse_fx(audio, p["sample_rate"], p),
            "created_at": "2026-11-07T12:00:00+00:00"}
    META_V.validate(meta)
    assert np.array_equal(render_fx(params)[0], audio)  # same params, same samples


def test_one_long_smoke_case_32_bars_at_135_bpm() -> None:
    """The longest preset: 2816000 frames stereo, peak at the ceiling, ends silent."""
    audio, p = render_fx(load_preset("riser-32bar", "fx"))
    assert audio.shape == (2816000, 2) and F.boundary_frame(p) == 2730667
    peak_db = 20 * math.log10(float(np.max(np.abs(audio))))
    assert -1.001 < peak_db <= -1.0
    assert audio[-1].tolist() == [0.0, 0.0]


# --- elementary functions (independent reference: numpy / math) ---------------------------------


def test_platform_independent_math_matches_numpy() -> None:
    u = np.linspace(-40.0, 40.0, 200001)
    assert np.max(np.abs(F.sin_cycles(u) - np.sin(2 * np.pi * u))) < 1e-13
    assert np.max(np.abs(F.cos_cycles(u) - np.cos(2 * np.pi * u))) < 1e-13
    x = np.geomspace(1e-300, 1e300, 20001)
    assert np.max(np.abs(F.log2(x) - np.log2(x))) < 1e-12
    y = np.linspace(-1000.0, 1000.0, 20001)
    assert np.max(np.abs(F.exp2(y) / np.exp2(y) - 1)) < 1e-14
    v = np.linspace(1e-6, 0.46, 20001)
    assert np.max(np.abs(F.tan_half_cycles(v) / np.tan(np.pi * v) - 1)) < 1e-13
    assert np.max(np.abs(F.db_to_gain(np.array([-60.0, -6.0, 0.0])) - [1e-3, 0.501187, 1.0])
                  ) < 1e-6


# --- golden hashes (Linux and Windows CI must agree) ---------------------------------------------

GOLDEN_VERSION = "0.1.0"
SHORT = {"bpm": 200, "length_beats": 2, "tail_beats": 1}
GOLDEN: dict[str, dict] = {
    **{f"preset {n}": load_preset(n, "fx") for n in ("impact", "reverse-crash", "downlifter")},
    "riser short": {**BASE, **SHORT, "filter_q": 6},
    "sweep pink hp_lp echo": {**BASE, **SHORT, "kind": "sweep", "noise_color": "pink",
                              "filter_mode": "hp_lp", "echo_mix": 0.5, "echo_pingpong": 1},
    "saw drive pump": {**BASE, **SHORT, "kind": "downlifter", "tone_level": 0.8,
                       "drive": 0.6, "pump_depth": 0.7, "sample_rate": 44100, "bit_depth": 16},
    "square tone only": {**BASE, **SHORT, "kind": "impact", "noise_level": 0,
                         "tone_wave": "square", "tone_start_hz": 400},
    "noise crash cut": {**BASE, **SHORT, "kind": "noise_crash", "cut_beats": 0.5,
                        "stereo_width": 1, "level_curve": 3},
}
GOLDEN_SHA = {  # pinned on Linux x86_64, NumPy 2.5.3; CI checks the same table on Windows
    "preset impact": "d540c6c65397badd3fb354dfbf63cb89e5a9e4a0959f7a64af7cd737012ac4a7",
    "preset reverse-crash": "578a22f79eef32d5c0adea562e62d6875b47ba4c31b2d466d92042401b231aef",
    "preset downlifter": "10ea2e6b3bd48d7b07b8bbacaa30c5510e50fbd5c4988400b14c508ea82c7a11",
    "riser short": "30aa15849db809639c85d967aceb6a4e060242d23fa63041d2cdd2b1f1aa63d6",
    "sweep pink hp_lp echo": "ce4ebab8f9be0b7b381dc9237b8a019896fd130a8f6494e2c9d14819f6ad9a3c",
    "saw drive pump": "3e5acda5bddd1c897ab4efb0575b7c87e88d9fc07df68a272a6a2146749d9270",
    "square tone only": "39a90a6608d8d61c81adddfb8ba80a1ccbf8a1bd8ae55feb76d24ec50bc9a123",
    "noise crash cut": "2f9255e42411b3e38a9abf7a5a5dbc0df8094ec4b8f5e1d185b88b8efe109a87",
}


def test_golden_table_is_complete_and_version_pinned() -> None:
    assert F.FX_VERSION == GOLDEN_VERSION, (
        "fx engine bytes changed: bump FX_VERSION (D-013) and update GOLDEN_SHA in this file")
    assert set(GOLDEN_SHA) == set(GOLDEN)


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_sha256(name: str) -> None:
    assert hashlib.sha256(_wav(GOLDEN[name])).hexdigest() == GOLDEN_SHA[name]


# --- presets, variants, CLI, re-render, sidecar --------------------------------------------------

PRESETS = ("downlifter", "impact", "noise-crash", "reverse-crash", "riser-16bar", "riser-32bar",
           "riser-8bar", "sweep")


def test_presets_are_complete_and_written_at_135_bpm() -> None:
    assert preset_names("fx") == sorted(PRESETS)
    kinds = set()
    for name in PRESETS:
        p = load_preset(name, "fx")
        assert p["preset"] == name and p["bpm"] == 135
        kinds.add(resolve_fx_params(p)["kind"])
        assert "set bpm to the track's tempo" in describe(name, "fx")
    assert kinds == set(KINDS)
    lengths = [resolve_fx_params(load_preset(f"riser-{b}bar", "fx"))["length_beats"]
               for b in (8, 16, 32)]
    assert lengths == [32, 64, 128]


def test_variants_move_only_seed_and_filter() -> None:
    base = {**BASE, "kind": "noise_crash"}
    v = fx_variants.make_variants(base, 4)
    assert v[0] == {k: x for k, x in resolve_fx_params(base).items() if k != "variants"}
    assert len({x["seed"] for x in v}) == 4
    for x in v[1:]:
        ratio = x["cutoff_start_hz"] / v[0]["cutoff_start_hz"]
        assert abs(math.log2(ratio)) <= 0.1 + 1e-6
        assert x["cutoff_end_hz"] == x["cutoff_start_hz"]  # static stays static
        for key in ("kind", "length_beats", "tail_beats", "bpm", "level_end_db"):
            assert x[key] == v[0][key]
    assert fx_variants.make_variants(base, 4) == v
    edge = fx_variants.make_variants({**BASE, "cutoff_start_hz": 20, "cutoff_end_hz": 20000}, 3)
    for x in edge:
        resolve_fx_params(x)


def test_cli_renders_fx_with_the_track_bpm(tmp_path: Path, capsys) -> None:
    code = cli_main(["--category", "fx", "--preset", "reverse-crash", "--set", "bpm=150",
                     "--set", "echo_note=1/8", "--set", "echo_mix=0.2", "--set",
                     "length_beats=1", "--variants", "2", "--out", str(tmp_path)])
    assert code == 0
    sidecars = sorted(tmp_path.glob("*.json"))
    assert len(sidecars) == 2
    meta = json.loads(sidecars[0].read_text("utf-8"))
    META_V.validate(meta)
    assert meta["parameters"]["bpm"] == 150 and meta["parameters"]["echo_note"] == "1/8"
    assert meta["features"]["boundary_frame"] == _frames(1, 150)
    assert rerender_from_sidecar(sidecars[0]) == sidecars[0].with_suffix(".wav").read_bytes()
    assert cli_main(["--category", "fx", "--preset", "impact", "--set", "kind=chord",
                     "--out", str(tmp_path / "x")]) == 2
    assert not (tmp_path / "x").exists()


def test_level_vs_kick_report() -> None:
    """Report only (no target): max short-term loudness of three fx presets against a 4-bar
    loop of the kick preset `dense` at the same ceiling. Sanity: finite, within +-30 LU."""
    from audio_engine.categories import get_category
    from audio_engine.loudness import short_term_lufs

    kick, kp = get_category("kick").render({**load_preset("dense"), "bpm": 135})
    beat = int(round(60 / 135 * kp["sample_rate"]))
    loop = np.zeros(16 * beat)
    for k in range(16):
        seg = kick[: min(len(kick), len(loop) - k * beat)]
        loop[k * beat: k * beat + len(seg)] += seg
    kick_lu = float(np.max(short_term_lufs(np.stack([loop, loop], axis=1), kp["sample_rate"])))
    report = {}
    for name in ("riser-8bar", "impact", "noise-crash"):
        audio, p = render_fx({**load_preset(name, "fx"), "peak_ceiling_dbfs": -0.3})
        lu = float(np.max(short_term_lufs(audio, p["sample_rate"])))
        report[name] = round(lu - kick_lu, 1)
    print("fx max short-term LUFS minus kick-loop LUFS:", report)
    for name, diff in report.items():
        assert math.isfinite(diff) and -30 < diff < 30, (name, diff)


# --- fault injection: each check must fail on a broken engine ------------------------------------


def _broken(monkeypatch, target: str, factory) -> None:
    monkeypatch.setattr(F, target, factory(getattr(F, target)))


MUTANTS = {
    "frames: bpm x1.02": ("file_samples", lambda f: lambda p: f({**p, "bpm": p["bpm"] * 1.02}),
                          _check_frames),
    "boundary off by one": ("boundary_frame", lambda f: lambda p: f(p) - 1, _check_frames),
    "cutoff x1.02": ("cutoff_track", lambda f: lambda p, t: f(p, t) * 1.02,
                     _check_static_centre),
    "sweep curve ignored": ("cutoff_track",
                            lambda f: lambda p, t: f({**p, "sweep_curve": 1.0}, t),
                            _check_sweep_track),
    "glide x1.02": ("tone_hz", lambda f: lambda p, t: f(p, t) * 1.02, _check_tone_glide),
    "level curve ignored half": ("level_db", lambda f: lambda p, t: f(p, t) * 0.8,
                                 _check_level_ramp),
    "pump phase from frame 0 always": ("anchor", lambda f: lambda p: "start", _check_pump),
}


@pytest.mark.parametrize("name", MUTANTS)
def test_mutant_is_caught(name: str, monkeypatch) -> None:
    target, factory, check = MUTANTS[name]
    _broken(monkeypatch, target, factory)
    with pytest.raises(AssertionError):
        check(render_fx)
