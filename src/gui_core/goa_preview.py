"""Rough offline preview of Goa clips (numpy only, deterministic). NOT a synth model.

Label in the UI: :data:`PREVIEW_LABEL` ("grobe Vorschau"). D-035 (2): the ``.mid`` stays
the product; this only lets the user hear the notes before dragging a clip into Live.
One pass of the clip (``bars`` bars at the clip's bpm) plus a short release tail, mono,
22.05 kHz, peak normalised to :data:`PEAK`. Simple per-voice tones:

* lead: a few sine harmonics (saw-like), 5 ms attack, held, 60 ms release;
* arp, pluck: the same harmonics with an exponential decay (arp 90 ms, pluck 140 ms);
* pad: three slightly detuned sines per note, 150 ms attack, 300 ms release.

Every note starts at phase 0 and its envelope returns to exactly 0, so the result does
not depend on anything but the notes, bpm and voice. No listening claim is made.

API for the GUI (keyword options are those of ``audio_engine.goa_clips``)::

    render_voice_preview(voice, **options) -> np.ndarray    # float32 mono in [-PEAK, PEAK]
    render_mix_preview(**options) -> np.ndarray              # all selected voices
    voice_preview_wav_bytes(voice, **options) -> bytes       # 16-bit mono WAV
    mix_preview_wav_bytes(**options) -> bytes
"""

from __future__ import annotations

from typing import Any

import numpy as np

from audio_engine import goa_clips
from audio_engine.acid_midi import PPQ
from audio_engine.io import encode_wav

PREVIEW_LABEL = "grobe Vorschau"
SAMPLE_RATE = 22050
TAIL_S = 0.5
MAX_SECONDS = 30.0  # 16 bars at 135 bpm = 28.4 s + tail: every valid clip fits
PEAK = 0.8
HARMONICS = (1.0, 0.5, 0.33, 0.25, 0.2)
MIX_GAIN = {"lead": 1.0, "arp": 0.7, "pad": 0.6, "pluck": 0.8}
_ATTACK = {"lead": 0.005, "arp": 0.002, "pluck": 0.002, "pad": 0.150}
_RELEASE = {"lead": 0.060, "arp": 0.030, "pluck": 0.030, "pad": 0.300}
_DECAY = {"arp": 0.090, "pluck": 0.140}
_PAD_DETUNE = (1.0, 1.004, 0.996)


def _hz(note: int) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def preview_seconds(**options: Any) -> float:
    o = goa_clips.normalise(options)
    return o["bars"] * 4 * 60.0 / o["bpm"] + TAIL_S


def _tone(voice: str, f: float, t: np.ndarray) -> np.ndarray:
    nyq = SAMPLE_RATE / 2
    w = 2 * np.pi * t
    if voice == "pad":
        return sum(np.sin(w * f * d) for d in _PAD_DETUNE) / len(_PAD_DETUNE)
    out = np.zeros_like(t)
    for k, a in enumerate(HARMONICS, start=1):
        if f * k < nyq * 0.9:  # no aliasing: skip partials near Nyquist
            out += a * np.sin(w * f * k)
    return out


def _env(voice: str, n_on: int, n_rel: int) -> np.ndarray:
    sr = SAMPLE_RATE
    n_att = max(1, int(_ATTACK[voice] * sr))
    i = np.arange(n_on + n_rel, dtype=np.float64)
    env = np.minimum(1.0, (i + 1) / n_att)
    if voice in _DECAY:
        env = env * np.exp(-i / (_DECAY[voice] * sr))
    level_at_off = env[n_on - 1] if n_on else 0.0
    rel = level_at_off * (1.0 - np.arange(1, n_rel + 1) / n_rel)  # linear to exactly 0
    env[n_on:] = rel
    return env


def _voice_buffer(voice: str, options: dict[str, Any], n: int) -> np.ndarray:
    o = goa_clips.normalise(options)
    sec_per_tick = 60.0 / o["bpm"] / PPQ
    sr = SAMPLE_RATE
    buf = np.zeros(n)
    n_rel = max(1, int(_RELEASE[voice] * sr))
    for nt in goa_clips.clip_notes(voice, **options):
        s0 = int(round(nt.start * sec_per_tick * sr))
        n_on = max(1, int(round(nt.end * sec_per_tick * sr)) - s0)
        if s0 >= n:
            continue
        m = min(n_on + n_rel, n - s0)
        t = np.arange(m) / sr
        seg = _tone(voice, _hz(nt.pitch), t) * _env(voice, n_on, n_rel)[:m]
        buf[s0:s0 + m] += seg * (nt.velocity / 127.0)
    return buf


def _finish(buf: np.ndarray) -> np.ndarray:
    # no end fade needed: every note's release ends inside the tail (max 300 ms < TAIL_S)
    peak = float(np.max(np.abs(buf))) if len(buf) else 0.0
    if peak > 0:
        buf = buf * (PEAK / peak)
    return buf.astype(np.float32)


def _length(options: dict[str, Any]) -> int:
    secs = preview_seconds(**options)
    if secs > MAX_SECONDS:
        raise ValueError("preview too long")
    return int(secs * SAMPLE_RATE)


def render_voice_preview(voice: str, **options: Any) -> np.ndarray:
    """Mono float32 preview of one voice's clip (one pass plus tail)."""
    if voice not in goa_clips.VOICES:
        raise ValueError(f"voice must be one of {list(goa_clips.VOICES)}")
    return _finish(_voice_buffer(voice, options, _length(options)))


def render_mix_preview(**options: Any) -> np.ndarray:
    """Mono float32 preview of all selected voices (``voices`` option) played together."""
    o = goa_clips.normalise(options)
    n = _length(options)
    buf = np.zeros(n)
    for v in o["voices"]:
        b = _voice_buffer(v, options, n)
        p = float(np.max(np.abs(b))) if n else 0.0
        if p > 0:
            buf += b * (MIX_GAIN[v] / p)
    return _finish(buf)


def voice_preview_wav_bytes(voice: str, **options: Any) -> bytes:
    return encode_wav(render_voice_preview(voice, **options), SAMPLE_RATE, 16)


def mix_preview_wav_bytes(**options: Any) -> bytes:
    return encode_wav(render_mix_preview(**options), SAMPLE_RATE, 16)
