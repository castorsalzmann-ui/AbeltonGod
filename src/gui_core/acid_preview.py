"""Rough offline preview of an acid line (numpy only, deterministic). NOT a 303 sound.

Label in the UI: "grobe Vorschau, kein 303-Klang". One mono voice: naive sawtooth, a
resonant state-variable low-pass whose cutoff follows a decaying envelope (higher and more
resonant on accents), a short amplitude envelope, and a 40 ms pitch glide where the line
overlaps (slides, via ``acid_midi.line_to_notes``). The sound is a plausibility aid for the
pattern, not a model of any hardware; no listening claim is made.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np

from audio_engine.acid_midi import PPQ, line_to_notes
from audio_engine.io import encode_wav

SAMPLE_RATE = 22050
MAX_SECONDS = 30.0
GLIDE_S = 0.040
ACCENT_VELOCITY = 120  # velocity at or above this counts as accent for the filter


def _hz(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def render_preview(line: Mapping[str, Any], bpm: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Mono float32 samples in [-1, 1] for one pass of the line (plus a short tail)."""
    notes = line_to_notes(line)
    if not 20 <= bpm <= 400:
        raise ValueError("bpm must be 20-400")
    sec_per_tick = 60.0 / bpm / PPQ
    total_s = line["length"] * 0.25 * 60.0 / bpm + 0.15
    if total_s > MAX_SECONDS:
        raise ValueError("preview too long")
    n = int(total_s * sr)
    freq = np.zeros(n)
    gate = np.zeros(n)
    trig = np.zeros(n)  # 1 at a retriggered (non-legato) note start
    accent = np.zeros(n)
    prev_f, prev_end = None, -1
    glide_n = max(1, int(GLIDE_S * sr))
    for nt in notes:
        s0 = min(n, int(nt.start * sec_per_tick * sr))
        s1 = min(n, int(nt.end * sec_per_tick * sr))
        f = _hz(nt.pitch)
        if prev_f is not None and s0 < prev_end:  # legato: glide, no new trigger
            ramp = prev_f * (f / prev_f) ** (np.arange(glide_n) / glide_n)
            g_end = min(n, s0 + glide_n)
            freq[s0:g_end] = ramp[: g_end - s0]
            freq[g_end:s1] = f
            legato = True
        else:
            freq[s0:s1] = f
            legato = False
        gate[s0:s1] = 1.0
        accent[s0:s1] = 1.0 if nt.velocity >= ACCENT_VELOCITY else 0.0
        if not legato and s0 < n:
            trig[s0] = 1.0
        prev_f, prev_end = f, s1

    phase = np.cumsum(freq / sr) % 1.0
    saw = 2.0 * phase - 1.0

    out = np.zeros(n)
    amp = 0.0
    env = 0.0
    lp = bp = 0.0
    # Python loop: a few 10^4 iterations for one bar; deterministic float math.
    dec = math.exp(-1.0 / (0.20 * sr))
    dec_acc = math.exp(-1.0 / (0.12 * sr))
    a_up = 1.0 - math.exp(-1.0 / (0.002 * sr))
    a_dn = 1.0 - math.exp(-1.0 / (0.008 * sr))
    for i in range(n):
        if trig[i]:
            env = 1.0
        env *= dec_acc if accent[i] else dec
        target = gate[i]
        amp += (target - amp) * (a_up if target > amp else a_dn)
        acc = accent[i]
        cutoff = 250.0 + (2600.0 + 2400.0 * acc) * env
        q = 0.28 - 0.14 * acc  # lower = more resonance
        f_c = 2.0 * math.sin(math.pi * min(cutoff, sr * 0.45) / sr)
        hp = saw[i] - lp - q * bp
        bp += f_c * hp
        lp += f_c * bp
        out[i] = lp * amp * (0.55 + 0.45 * acc)
    peak = float(np.max(np.abs(out))) if n else 0.0
    if peak > 0:
        out = out * (0.8 / peak)
    return out.astype(np.float32)


def preview_wav_bytes(line: Mapping[str, Any], bpm: float) -> bytes:
    """16-bit mono WAV of :func:`render_preview` (what the winsound path plays)."""
    return encode_wav(render_preview(line, bpm), SAMPLE_RATE, 16)
