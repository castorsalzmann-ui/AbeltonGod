"""Laser contract v0.2 building blocks (#425, D-031): salvo plan, pan, filter, echo, reverb.

The rules are numbered in ``contracts/laser-params.schema.json`` ($comment points 15-22); this
module only names where each is implemented. Pure NumPy (no SciPy): every filter is applied as
an FFT convolution with the exact frequency response of its biquads (the impulse response is
long enough that the truncation error is below ``IR_TOLERANCE``), so cost does not depend on a
Python per-sample loop. No clock, no global RNG; the reverb uses no random numbers.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from .dsp import fft_size, substreams

S_SALVO = 6  # sub-stream index of the seed (the voice uses 0-5)
SALVO_MAX = 5
DROP_TAIL_MS = 10.0  # shots starting this close to the end of the sound (or later) are dropped
HUMAN_TIME, HUMAN_LEVEL_DB, HUMAN_PITCH_ST = 0.2, 1.5, 0.25
PITCH_MIN_HZ, PITCH_MAX_HZ = 40.0, 8000.0
BUTTERWORTH_Q = {12: (1.0 / math.sqrt(2.0),), 24: (0.5411961001461970, 1.3065629648763766)}
RESONANCE_Q = 1.5
IR_TOLERANCE = 1e-9
IR_MAX = 1 << 16
SWEEP_GRID = 3  # cutoff grid steps per octave of the closing sweep
ECHO_FLOOR = 1e-4
FDN_MS = (14.0, 17.3, 20.9, 24.6, 28.8, 32.9, 37.4, 41.3)  # delay lines at size scale 1
FDN_SCALE_MIN, FDN_SCALE_SPAN = 0.35, 1.15  # scale = 0.35 + 1.15 * reverb_size
FDN_INPUT = np.array([1, 1, 1, -1, 1, -1, -1, -1], dtype=np.float64) / math.sqrt(8.0)
FDN_OUT_L = np.array([1, -1, 1, -1, 1, -1, 1, -1], dtype=np.float64) / math.sqrt(8.0)
FDN_OUT_R = np.array([1, 1, -1, -1, 1, 1, -1, -1], dtype=np.float64) / math.sqrt(8.0)


def note_ms(note: str, bpm: float) -> float:
    """Length of a note value (``1/8``, ``1/8T`` triplet, ``1/8D`` dotted) at ``bpm`` in ms."""
    denom = int(note[2:].rstrip("TD"))
    value = 60000.0 / bpm * 4.0 / denom
    if note.endswith("T"):
        value *= 2.0 / 3.0
    elif note.endswith("D"):
        value *= 1.5
    return value


# --- salvo -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Shot:
    index: int
    start: int  # sample inside the sound
    gain: float
    pitch_scale: float
    pan: float | None  # position in [-1, 1], None = centre (no panning)
    seed: int


def shot_seed(seed: int, k: int) -> int:
    """Shot 0 uses the seed itself; later shots a SHA-256 derived sub-seed."""
    if k == 0:
        return seed
    digest = hashlib.sha256(f"abeltongod-laser-shot/v1:{seed}:{k}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def base_gap_ms(fx: dict[str, Any], bpm: float) -> float:
    mode = fx["salvo_rate_mode"]
    if mode == "ms":
        return float(fx["salvo_spacing_ms"])
    if mode == "hz":
        return 1000.0 / float(fx["salvo_rate_hz"])
    return note_ms(fx["salvo_sync_note"], bpm)


def salvo_plan(fx: dict[str, Any], seed: int, sr: int, m: int, bpm: float) -> list[Shot]:
    """Shots of the salvo (contract point 17): start, level, pitch, pan, sub-seed."""
    count = int(fx["salvo_count"])
    base = base_gap_ms(fx, bpm)
    ramp = float(fx["salvo_rate_ramp"])
    h = float(fx["salvo_humanize"])
    rng = substreams(seed, S_SALVO + 1)[S_SALVO]
    u = rng.uniform(-1.0, 1.0, size=(SALVO_MAX, 4))  # time, level, pitch, pan; per shot
    width = float(fx["salvo_pan_width"])
    mode = fx["salvo_pan_mode"]
    limit = m - int(round(DROP_TAIL_MS * sr / 1000.0))
    shots: list[Shot] = []
    t_ms = 0.0
    gap_before = 0.0
    for k in range(count):
        if k > 0:
            frac = (k - 1 + 0.5) / (count - 1)
            gap_before = base * 2.0 ** (-ramp * (2.0 * frac - 1.0))
            t_ms += gap_before
        jitter = lvl = pit = 0.0
        if k > 0 and h > 0.0:
            jitter = u[k, 0] * HUMAN_TIME * h * gap_before
            lvl = u[k, 1] * HUMAN_LEVEL_DB * h
            pit = u[k, 2] * HUMAN_PITCH_ST * h
        start = int(round(max(0.0, t_ms + jitter) * sr / 1000.0))
        if k > 0 and start >= limit:
            continue
        gain = 10.0 ** ((k * float(fx["salvo_level_step_db"]) + lvl) / 20.0)
        scale = 2.0 ** ((k * float(fx["salvo_pitch_step_st"]) + pit) / 12.0)
        if mode == "center":
            pan = None
        elif mode in ("alternate_lr", "alternate_rl"):
            left_first = mode == "alternate_lr"
            pan = -width if (k % 2 == 0) == left_first else width
        elif mode in ("sweep_lr", "sweep_rl"):
            pos = 0.0 if count == 1 else -1.0 + 2.0 * k / (count - 1)
            pan = width * (pos if mode == "sweep_lr" else -pos)
        else:  # random
            pan = width * float(u[k, 3])
        shots.append(Shot(k, start, gain, scale, pan, shot_seed(seed, k)))
    return shots


def pan_gains(pos: float) -> tuple[float, float]:
    """Equal-power balance (contract point 17): theta = (pos + 1) * pi / 4."""
    theta = (pos + 1.0) * math.pi / 4.0
    return math.sqrt(2.0) * math.cos(theta), math.sqrt(2.0) * math.sin(theta)


def clamp_pitch(hz: float) -> float:
    return min(max(hz, PITCH_MIN_HZ), PITCH_MAX_HZ)


# --- IIR filters as FFT convolutions -----------------------------------------------------------

Section = tuple[float, float, float, float, float]  # b0, b1, b2, a1, a2 (a0 = 1)


def _rbj(kind: str, sr: int, f0: float, q: float) -> Section:
    w0 = 2.0 * math.pi * f0 / sr
    cw, alpha = math.cos(w0), math.sin(w0) / (2.0 * q)
    a0 = 1.0 + alpha
    if kind == "lp":
        b0, b1 = (1.0 - cw) / 2.0 / a0, (1.0 - cw) / a0
    else:
        b0, b1 = (1.0 + cw) / 2.0 / a0, -(1.0 + cw) / a0
    return (b0, b1, b0, -2.0 * cw / a0, (1.0 - alpha) / a0)


def filter_sections(
    kind: str, sr: int, f0: float, slope: int, resonance: float = 0.0
) -> list[Section]:
    qs = list(BUTTERWORTH_Q[int(slope)])
    if kind == "lp" and resonance > 0.0:
        qs[-1] *= 1.0 + RESONANCE_Q * resonance
    return [_rbj(kind, sr, f0, q) for q in qs]


def _pole_radius(sec: Section) -> float:
    a1, a2 = sec[3], sec[4]
    disc = a1 * a1 - 4.0 * a2
    if disc < 0.0:
        return math.sqrt(a2)
    root = math.sqrt(disc)
    return max(abs(-a1 + root), abs(-a1 - root)) / 2.0


def _memory(radius: float) -> int:
    if radius <= 0.0:
        return 8
    if radius >= 1.0:
        return IR_MAX
    return int(min(IR_MAX, max(8, math.ceil(math.log(IR_TOLERANCE) / math.log(radius)))))


@lru_cache(maxsize=8)
def _grid(n_fft: int) -> np.ndarray:
    grid = np.exp(-2j * math.pi * np.arange(n_fft // 2 + 1) / n_fft)
    grid.setflags(write=False)
    return grid


def _response(sections: list[Section], n_fft: int) -> np.ndarray:
    """Frequency response on the rfft grid; cached (the same biquad is used by many calls)."""
    return _response_cached(tuple(sections), n_fft)


@lru_cache(maxsize=6)
def _response_cached(sections: tuple[Section, ...], n_fft: int) -> np.ndarray:
    z1 = _grid(n_fft)
    z2 = z1 * z1
    h = np.ones(len(z1), dtype=complex)
    for b0, b1, b2, a1, a2 in sections:
        h = h * (b0 + b1 * z1 + b2 * z2) / (1.0 + a1 * z1 + a2 * z2)
    return h


def apply_sections(
    x: np.ndarray, sections: list[Section], start: int = 0, stop: int | None = None
) -> np.ndarray:
    """Filter ``x`` (shape ``(n, c)``, zero state before sample 0) and return samples
    ``start .. stop``. Only ``x[:stop]`` is used; samples more than the filter memory before
    ``start`` are ignored (error below ``IR_TOLERANCE``)."""
    stop = len(x) if stop is None else stop
    memory = max(_memory(_pole_radius(s)) for s in sections)
    lo = max(0, start - memory)
    seg = x[lo:stop]
    size = fft_size(len(seg) + memory)
    spec = np.fft.rfft(seg, size, axis=0) * _response(sections, size)[:, None]
    y = np.fft.irfft(spec, size, axis=0)[: len(seg)]
    return y[start - lo :]


def high_pass(x: np.ndarray, sr: int, p: dict[str, Any]) -> np.ndarray:
    if p["hp_hz"] <= 20.0:
        return x
    return apply_sections(x, filter_sections("hp", sr, p["hp_hz"], p["filter_slope"]))


def low_pass(x: np.ndarray, sr: int, p: dict[str, Any], starts: list[int]) -> np.ndarray:
    """Static low-pass, or the closing sweep restarted at every shot start (point 18).

    The sweep is a bank of fixed low-passes on a cutoff grid of ``SWEEP_GRID`` per octave (from
    the higher of ``lp_hz`` / ``lp_sweep_hz`` downwards); the output at each sample is the
    linear blend of the two neighbouring grid outputs for the cutoff at that sample.
    """
    m = len(x)
    lp, end = float(p["lp_hz"]), float(p["lp_sweep_hz"])
    if float(p["lp_sweep_ms"]) <= 0.0 and lp >= 20000.0:
        return x  # 20000 = off only without a sweep (contract point 18)
    if float(p["lp_sweep_ms"]) <= 0.0 or lp == end:
        secs = filter_sections("lp", sr, lp, p["filter_slope"], p["lp_resonance"])
        return apply_sections(x, secs)
    hi = max(lp, end)
    steps = int(math.ceil(SWEEP_GRID * math.log2(hi / min(lp, end))))
    sweep_n = float(p["lp_sweep_ms"]) * sr / 1000.0
    q = np.empty(m)  # grid position of the cutoff at each sample (0 = hi, steps = lowest)
    for a, b in zip([*starts], [*starts[1:], m], strict=True):
        progress = np.minimum(1.0, np.arange(b - a) / sweep_n)
        q[a:b] = SWEEP_GRID * (math.log2(hi / lp) + progress * math.log2(lp / end))
    q = np.clip(q, 0.0, float(steps))
    banks = [
        filter_sections("lp", sr, hi * 2.0 ** (-i / SWEEP_GRID), p["filter_slope"],
                        p["lp_resonance"])
        for i in range(steps + 1)
    ]
    memory = max(_memory(_pole_radius(s)) for secs in banks for s in secs)
    size = fft_size(m + memory)
    spec_in = np.fft.rfft(x, size, axis=0)
    out = np.zeros_like(x)
    for i, secs in enumerate(banks):
        w = np.clip(1.0 - np.abs(q - i), 0.0, 1.0)
        if not w.any():
            continue
        y = np.fft.irfft(spec_in * _response(secs, size)[:, None], size, axis=0)[:m]
        out += y * w[:, None]
    return out


# --- echo (v0.2 additions to the v0.1 echo) -------------------------------------------------------


def _ipow(z: np.ndarray, n: int) -> np.ndarray:
    """``z ** n`` for an integer ``n >= 0`` by square-and-multiply: only multiplications, so the
    bytes do not depend on the platform's complex ``pow`` (the CI machines gave three
    different hashes for the echo preset with ``z ** n``)."""
    out = np.ones_like(z)
    base = z
    while n > 0:
        if n & 1:
            out = out * base
        base = base * base
        n >>= 1
    return out


def echo_v2(x: np.ndarray, p: dict[str, Any], d: int) -> np.ndarray:
    """Echo with damping and hard ping-pong (contract point 20); ``d`` = delay in samples.

    Evaluated in the frequency domain: tap ``k`` is ``x`` filtered ``k - 1`` times by the damping
    one-pole and delayed ``k * d``; the sums over odd and even taps are geometric series in
    ``r = echo_feedback * H(w) * exp(-j w d)`` (finite: the taps kept by the 1e-4 floor).
    """
    mix, fb = float(p["echo_mix"]), float(p["echo_feedback"])
    sr = int(p["sample_rate"])
    w = float(p["stereo_width"])
    pp = float(p["echo_pingpong"])
    damp = float(p["echo_damp_hz"])
    n = len(x)
    taps = 0  # taps kept: k * d < n and mix * fb ** (k - 1) >= ECHO_FLOOR
    while (taps + 1) * d < n and mix * fb**taps >= ECHO_FLOOR:
        taps += 1
    if taps == 0:
        return x.copy()
    a = math.exp(-2.0 * math.pi * damp / sr) if damp < 20000.0 else 0.0
    size = fft_size(2 * n + (_memory(a) if a > 0.0 else 0))
    z = _grid(size)
    # exp(-j w d) on the rfft grid; the phase is reduced with integers first (k * d mod size), so
    # the argument stays below 2 pi: a raw angle of up to d * pi rad would turn last-bit
    # differences of the platform's sin / cos into ~1e-12 errors and flip 24-bit LSBs
    zd = np.exp(-2j * math.pi * ((np.arange(len(z), dtype=np.int64) * d) % size) / size)
    h = (1.0 - a) / (1.0 - a * z) if a > 0.0 else np.ones(len(z), dtype=complex)
    r = fb * h * zd
    r2 = r * r
    odd_n, even_n = (taps + 1) // 2, taps // 2
    geo_odd = (1.0 - _ipow(r2, odd_n)) / (1.0 - r2)
    geo_even = (1.0 - _ipow(r2, even_n)) / (1.0 - r2)
    s_odd = mix * zd * geo_odd
    s_even = mix * zd * r * geo_even
    root = math.sqrt(2.0) / 2.0
    # channel operators (2 x 2) of odd / even taps: stereo crossover (odd only) and ping-pong
    cross = np.array([[1.0 - w, w], [w, 1.0 - w]]) if w > 0.0 else np.eye(2)
    m_odd = (1.0 - pp) * cross + pp * np.array([[0.0, 0.0], [root, root]])  # sqrt(2) * mid -> R
    m_even = (1.0 - pp) * np.eye(2) + pp * np.array([[root, root], [0.0, 0.0]])  # -> L
    spec = np.fft.rfft(x, size, axis=0)
    left, right = spec[:, 0], spec[:, 1]
    out = np.empty_like(spec)
    for c in (0, 1):
        out[:, c] = (s_odd * (m_odd[c, 0] * left + m_odd[c, 1] * right)
                     + s_even * (m_even[c, 0] * left + m_even[c, 1] * right))
    return x + np.fft.irfft(out, size, axis=0)[:n]


# --- reverb ------------------------------------------------------------------------------------


def _hadamard8(z: np.ndarray) -> np.ndarray:
    """Unnormalised 8-point Walsh-Hadamard transform along axis 0 (adds and subtracts only)."""
    blk = z.shape[1]
    h = 1
    while h < 8:
        v = z.reshape(8 // (2 * h), 2, h, blk)
        z = np.stack([v[:, 0] + v[:, 1], v[:, 0] - v[:, 1]], axis=1).reshape(8, blk)
        h *= 2
    return z


def reverb_wet(x: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    """Wet signal ``(n, 2)`` of the 8-line feedback delay network (contract point 21),
    energy-matched to ``x``; zeros if ``x`` is silent."""
    sr = int(p["sample_rate"])
    n = len(x)
    scale = FDN_SCALE_MIN + FDN_SCALE_SPAN * float(p["reverb_size"])
    d = np.array([max(8, int(round(ms * scale * sr / 1000.0))) for ms in FDN_MS])
    block = int(d.min())
    pre = int(round(float(p["reverb_predelay_ms"]) * sr / 1000.0))
    inp = np.zeros(n)
    if pre < n:
        inp[pre:] = x.mean(axis=1)[: n - pre]
    gain = 10.0 ** (-3.0 * d / (sr * float(p["reverb_decay_ms"]) / 1000.0))
    damp_hz = float(p["reverb_damp_hz"])
    a = 0.0 if damp_hz >= 20000.0 else math.exp(-2.0 * math.pi * damp_hz / sr)
    size = fft_size(2 * block)
    ir_spec = carry = None
    if a > 0.0:
        ir_spec = np.fft.rfft((1.0 - a) * a ** np.arange(block), size)
        carry = a ** (np.arange(block) + 1.0)
    pad = int(d.max())
    lines = np.zeros((8, pad + n))
    wet_lines = np.zeros((8, n))
    y_last = np.zeros(8)
    norm = 1.0 / math.sqrt(8.0)
    for pos in range(0, n, block):
        blk = min(block, n - pos)
        y = np.empty((8, blk))
        for j in range(8):
            s0 = pad + pos - int(d[j])
            y[j] = lines[j, s0 : s0 + blk]
        wet_lines[:, pos : pos + blk] = y
        if a > 0.0:
            z = np.fft.irfft(np.fft.rfft(y, size, axis=1) * ir_spec, size, axis=1)[:, :blk]
            z = z + y_last[:, None] * carry[None, :blk]
            y_last = z[:, -1].copy()
        else:
            z = y
        z = z * gain[:, None]
        lines[:, pad + pos : pad + pos + blk] = (
            FDN_INPUT[:, None] * inp[None, pos : pos + blk] + norm * _hadamard8(z)
        )
    left = (FDN_OUT_L[:, None] * wet_lines).sum(axis=0)
    right = (FDN_OUT_R[:, None] * wet_lines).sum(axis=0)
    mid, side = 0.5 * (left + right), 0.5 * (left - right)
    width = float(p["reverb_width"])
    wet = np.stack([mid + width * side, mid - width * side], axis=1)
    e_wet = float(np.sum(wet * wet))
    e_dry = float(np.sum(x * x))
    if e_wet <= 0.0 or e_dry <= 0.0:
        return np.zeros_like(wet)
    return wet * math.sqrt(e_dry / e_wet)
