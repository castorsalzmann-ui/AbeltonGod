"""Independent reference renderer for the atmos tests (#529).

Re-implements the contract (atmos-params v0.1 $comment points 3-12) by other methods than the
engine: sources in the time domain (np.sin / np.exp instead of the engine's DFT-domain drone and
polynomial helpers), the moving filter as its own Zavalishin TPT loop (direct form, np.tan) run
over many tiled periods (its own count, not the engine's warm-up), the reverb steady state by
folding the reverb's impulse response modulo N and convolving circularly (not by tiling), and
level / pan / pump / mono_below with numpy's own functions. Shared with the engine are only the
contract's random sub-streams (``dsp.substreams``) and the laser reverb itself
(``laser_fx.reverb_wet``, the stage the contract names), used here only to get its impulse
response.
"""

from __future__ import annotations

import math

import numpy as np

from audio_engine import laser_fx
from audio_engine.dsp import substreams

METAL = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)


def frames(p: dict) -> int:
    return int(round(240 * p["bars"] * p["sample_rate"] / p["bpm"]))


def f0(p: dict) -> float:
    return 440.0 * 2.0 ** ((p["note"] - 69 + p["cents"] / 100.0) / 12.0)


def _freqs(n: int, sr: int) -> np.ndarray:
    return np.fft.rfftfreq(n, 1.0 / sr)


def _noise(p: dict, n: int) -> np.ndarray:
    s = substreams(p["seed"], 8)
    w0, w1 = s[0].standard_normal(n), s[1].standard_normal(n)
    c = 1.0 - p["stereo_width"]
    chans = [w0, c * w0 + math.sqrt(1.0 - c * c) * w1]
    f = _freqs(n, p["sample_rate"])
    tilt = np.where(f >= 20.0, np.power(10.0, p["tilt_db_oct"] * np.log2(np.maximum(f, 1e-9)
                                                                         / 1000.0) / 20.0), 0.0)
    out = []
    for w in chans:
        y = np.fft.irfft(np.fft.rfft(w) * tilt, n)
        out.append(y * (np.sqrt(np.mean(w * w)) / np.sqrt(np.mean(y * y))))
    return np.stack(out, axis=1)


def _weights(p: dict, count: int) -> np.ndarray:
    return 10.0 ** (p["brightness_db_oct"] * np.log2(np.arange(1, count + 1)) / 20.0)


def _voices(p: dict) -> list[float]:
    return [f0(p) * 2.0 ** (iv / 12.0) for iv in p["intervals"]]


def _drone(p: dict, n: int) -> np.ndarray:
    sr = p["sample_rate"]
    w = _weights(p, p["partials"])
    parts = []
    for fv in _voices(p):
        for k in range(1, p["partials"] + 1):
            if k * fv > 0.45 * sr:
                break
            b = max(1, round(k * fv * n / sr))
            parts.append((b, w[k - 1]))
            d = p["detune_bins"]
            if d and (b + d) * sr / n <= 0.45 * sr:
                parts.append((b + d, w[k - 1]))
    draws = substreams(p["seed"], 8)[3].random(9 * len(parts)).reshape(len(parts), 9)
    t = np.arange(n)
    out = np.zeros((n, 2))
    mc = p["move_cycles"]
    grid = np.arange(512) / 512
    for (b, amp), r in zip(parts, draws, strict=True):
        if mc and p["drift_db"]:
            def s(u, r=r):
                return sum(r[2 * h - 1] / h * np.sin(2 * np.pi * (h * u + r[2 * h]))
                           for h in range(1, 5))
            d = s(mc * t / n) / np.max(np.abs(s(grid)))
            g = 10.0 ** (p["drift_db"] / 2 * d / 20)
        else:
            g = 1.0
        for ch, ph in enumerate((r[0], r[0] * (1 + p["stereo_width"]))):
            out[:, ch] += amp * g * np.sin(2 * np.pi * (b * t / n + ph))
    return out


def _metal(p: dict, n: int) -> np.ndarray:
    sr = p["sample_rate"]
    t = np.arange(n)
    out = np.zeros(n)
    for fi in METAL:
        f = f0(p) * fi / METAL[0]
        h = 1
        while h * f <= 0.45 * sr:
            out += 4 / (np.pi * h) / 6 * np.sin(2 * np.pi * max(1, round(h * f * n / sr)) * t / n)
            h += 2
    return np.stack([out, out], axis=1)


def _grains(p: dict, src: np.ndarray) -> np.ndarray:
    n, sr = len(src), p["sample_rate"]
    count = max(1, round(p["grain_density"] * n / sr))
    g = round(p["grain_ms"] * sr / 1000)
    win = np.hanning(g) if g > 1 else np.ones(1)
    rng = substreams(p["seed"], 8)[4]
    out = np.zeros((n, 2))
    j = np.arange(g)
    for _ in range(count):
        o = int(rng.integers(0, n))
        u = rng.uniform(-1, 1)
        pc = rng.uniform(-p["grain_pitch_cents"], p["grain_pitch_cents"])
        q = rng.uniform(-p["grain_pan"], p["grain_pan"])
        pos = (o + u * p["grain_spread"] * n / 2 + j * 2 ** (pc / 1200)) % n
        for ch, gain in enumerate((np.cos((q + 1) * np.pi / 4), np.sin((q + 1) * np.pi / 4))):
            val = np.interp(pos, np.arange(n + 1), np.append(src[:, ch], src[0, ch]))
            np.add.at(out[:, ch], (o + j) % n, gain * win * val)
    return out


def _comb(p: dict, f: np.ndarray) -> np.ndarray:
    out = np.zeros(len(f))
    w = _weights(p, p["partials"])
    fp = np.maximum(f, 1e-30)
    for fv in _voices(p):
        for k in range(1, p["partials"] + 1):
            fc = k * fv
            if fc > 0.45 * p["sample_rate"]:
                break
            out += w[k - 1] / np.sqrt(1 + p["res_q"] ** 2 * (fp / fc - fc / fp) ** 2)
    out[f == 0] = 0.0
    return out


def source(p: dict) -> np.ndarray:
    n, sr = frames(p), p["sample_rate"]
    f = _freqs(n, sr)
    kind = p["kind"]
    if kind == "drone":
        x = _drone(p, n)
    elif kind == "granular":
        src = {"noise": _noise, "drone": _drone, "metal": _metal}[p["granular_source"]](p, n)
        x = _grains(p, src)
    else:
        x = _noise(p, n)
    h = (f / p["hp_hz"]) ** 2 / np.sqrt(1 + (f / p["hp_hz"]) ** 4)
    h = h / np.sqrt(1 + (f / p["lp_hz"]) ** 4)
    if kind == "resonant":
        h = h * _comb(p, f)
    return np.fft.irfft(np.fft.rfft(x, axis=0) * h[:, None], n, axis=0)


def curve(p: dict, n: int) -> np.ndarray:
    mc = p["move_cycles"]
    t = np.arange(n)
    if mc == 0:
        return np.zeros(n)
    if p["move_shape"] == "sine":
        return np.sin(2 * np.pi * mc * t / n)
    r = substreams(p["seed"], 8)[2].random(8)
    s = sum(r[2 * h - 2] / h * np.sin(2 * np.pi * h * mc * t / n + 2 * np.pi * r[2 * h - 1])
            for h in range(1, 5))
    return s / np.max(np.abs(s))


def tpt_svf(x: np.ndarray, fc: np.ndarray, q: float, mode: str, sr: int) -> np.ndarray:
    """Zavalishin TPT SVF, direct form (hp first), np.tan prewarp."""
    g = np.tan(np.pi * fc / sr).tolist()
    k = 1.0 / q
    s1 = s2 = 0.0
    y = np.empty(len(x))
    for i, xi in enumerate(x.tolist()):
        gi = g[i]
        hp = (xi - (k + gi) * s1 - s2) / (1.0 + k * gi + gi * gi)
        bp = gi * hp + s1
        s1 = gi * hp + bp
        lp = gi * bp + s2
        s2 = gi * bp + lp
        y[i] = k * bp if mode == "bp" else lp if mode == "lp" else hp
    return y


def reverb_steady(x: np.ndarray, p: dict) -> np.ndarray:
    """Steady-state wet of the period x by folding the impulse response modulo N."""
    n, sr = len(x), p["sample_rate"]
    length = int(math.ceil((4.0 * p["reverb_decay_ms"] + p["reverb_predelay_ms"]) / 1000 * sr))
    length = max(length, n)
    imp = np.zeros((length, 2))
    imp[0] = 1.0
    ir = laser_fx.reverb_wet(imp, p)  # scaled by an arbitrary scalar; the energy match removes it
    pad = (-length) % n
    folded = np.concatenate([ir, np.zeros((pad, 2))]).reshape(-1, n, 2).sum(axis=0)
    mono = x.mean(axis=1)
    wet = np.fft.irfft(np.fft.rfft(mono)[:, None] * np.fft.rfft(folded, axis=0), n, axis=0)
    return wet * math.sqrt(np.sum(x * x) / np.sum(wet * wet))


def render(p: dict, filter_periods: int = 8) -> np.ndarray:
    """Seamless loop of the resolved parameters ``p`` (drive must be 0), float, before scaling."""
    assert p["loop_mode"] == "seamless" and p["drive"] == 0
    sr = p["sample_rate"]
    x = source(p)
    n = len(x)
    c = curve(p, n)
    if p["filter_mode"] != "off":
        fc = p["filter_hz"] * 2.0 ** (p["move_depth_oct"] / 2 * c)
        reps = filter_periods
        x = np.stack([tpt_svf(np.tile(x[:, ch], reps), np.tile(fc, reps), p["filter_q"],
                              p["filter_mode"], sr)[-n:] for ch in (0, 1)], axis=1)
    level = 10.0 ** (p["amp_move_db"] / 2 * c / 20)
    x = x * np.stack([level * np.sqrt(1 - p["pan_move"] * c),
                      level * np.sqrt(1 + p["pan_move"] * c)], axis=1)
    if p["reverb_mix"] > 0:
        x = x + p["reverb_mix"] * reverb_steady(x, p)
    if p["pump_depth"] > 0:
        phi = np.mod(np.arange(n) / (60 * sr / p["bpm"]), 1.0)
        x = x * (1 - p["pump_depth"] * (1 - phi) ** 4)[:, None]
    if p["mono_below_hz"] > 0:
        f = _freqs(n, sr)
        lo, hi = p["mono_below_hz"], p["mono_below_hz"] * math.sqrt(2)
        w = np.clip(np.log2(np.maximum(f, 1e-30) / lo) / np.log2(hi / lo), 0, 1)
        mid, side = (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2
        side = np.fft.irfft(np.fft.rfft(side) * w, n)
        x = np.stack([mid + side, mid - side], axis=1)
    return x


def quantise(x: np.ndarray, p: dict) -> np.ndarray:
    """Peak scaling (half an LSB below the ceiling) and rounding, as the contract's point 12."""
    full = 2 ** (p["bit_depth"] - 1) - 1
    target = 10 ** (p["peak_ceiling_dbfs"] / 20) - 0.5 / full
    return np.round(x * (target / np.max(np.abs(x))) * full).astype(np.int64)
