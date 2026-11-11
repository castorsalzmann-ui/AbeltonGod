"""Rough offline preview of Goa clips (numpy only, deterministic). NOT a synth product.

Label in the UI: :data:`PREVIEW_LABEL` ("grobe Vorschau"). D-035 (2): the ``.mid`` stays the
product; this only lets the user hear the notes before dragging a clip into Live (#571).
One pass of the clip (``bars`` bars at the clip's bpm), then the release tail and the echoes;
stereo, :data:`SAMPLE_RATE`, peak normalised to :data:`PEAK`. No listening claim is made.

Input is plain note events per voice (:class:`PreviewNote`: pitch, start, length, velocity).
Two conventions of the clips are read from them and nothing else:

* **accent** = the higher velocity level. Velocity maps linearly to an accent amount 0..1
  between :data:`ACCENT_VELOCITY_LOW` and :data:`ACCENT_VELOCITY_HIGH`;
* **slide** = a note that overlaps the next note of the same voice (lead, arp, pluck are
  one-note-at-a-time voices; the pad is chords and never slides). The earlier note is cut at
  the start of the next one, the pitch glides there within :data:`GLIDE_S`, and the envelopes
  are not restarted.

Signal chain per voice (constants in :data:`VOICES`; blocks in ``gui_core.preview_dsp``)::

    band-limited saw (+ square)  ->  two-pole resonant filter  ->  amplitude envelope
        -> velocity level  ->  [sum of the voice's notes, mono]  ->  ping-pong echoes (stereo)

    cutoff(t) = base_hz * 2 ** (env_oct * exp(-t / env_decay_s)     envelope, from note start
                                + accent_oct * accent               accent lift
                                + ramp_oct * position_in_clip       slow ramp, 0..1 over the clip
                                + key_track * octaves_above_key_ref)  follows the pitch

A note is released at the clip's end at the latest, so every release ends inside
:data:`TAIL_S` and the buffer ends in exact silence after the last echo.

API for the GUI (keyword options are those of ``audio_engine.goa_clips``)::

    render_voice_preview(voice, **options) -> np.ndarray    # float32 (n, 2) in [-PEAK, PEAK]
    render_mix_preview(**options) -> np.ndarray              # all selected voices
    voice_preview_wav_bytes(voice, **options) -> bytes       # 16-bit stereo WAV
    mix_preview_wav_bytes(**options) -> bytes

and, independent of the generator, ``render_events`` / ``render_events_mix``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from audio_engine import goa_clips
from audio_engine.acid_midi import PPQ
from audio_engine.io import encode_wav

from . import preview_dsp as dsp

# Source classes: "sourced" = editorial/manual source named in the research report of
# 2026-11-10 ("Klassische Goa Leads und Melodien"); "forum" = producer forum only;
# "derived" = working value of this project, named by no source.
PREVIEW_LABEL = "grobe Vorschau"
SAMPLE_RATE = 44100  # derived: partials up to 0.45 * sr = 19.8 kHz, cutoff clamp above every voice
PEAK = 0.8  # derived: peak normalisation of every preview (unchanged convention)
TAIL_S = 0.5  # derived: room after the clip for the longest release (0.4 s)
GLIDE_S = 0.040  # derived: slide time, same value as gui_core.acid_preview
ACCENT_VELOCITY_LOW = 84  # derived: velocity with accent amount 0 (report N6, "z. B. 84 und 120")
ACCENT_VELOCITY_HIGH = 120  # derived: velocity with accent amount 1 (same line of the report)
DELAY_SIXTEENTHS = 3  # forum (one writer names 3/16 for Goa; sourced only for acid house lines)
DELAY_FEEDBACK = 0.40  # sourced, not Goa: Drift lead tutorial, about 40 % feedback
DELAY_WET = 0.30  # sourced, not Goa: same tutorial, 30 % dry/wet
DELAY_WET_PLUCK = 0.15  # derived: half of DELAY_WET (the acid-line source only says "subtle")
VELOCITY_EXPONENT = 2.0  # derived: level = (velocity / 127) ** 2, so 84 -> 120 is +6.2 dB
SQUARE_LEVEL = 0.5  # forum: two thirds saw, one third square = square at half the saw's level
PAD_DETUNE = (1.004, 0.996)  # derived: two saws about 7 cents above and below the note
MIX_GAIN = {"lead": 1.0, "arp": 0.7, "pad": 0.6, "pluck": 0.8}  # derived (unchanged)
MAX_SECONDS = 32.0  # derived: 16 bars at 135 bpm (28.4 s) + tail + 7 echoes (2.3 s) fit
_LN2 = math.log(2.0)


@dataclass(frozen=True)
class Voice:
    """One voice's working values; every number is "derived" unless its comment says more."""

    mode: str  # filter output: dsp.LOWPASS or dsp.BANDPASS
    base_hz: float  # cutoff with envelope, accent and ramp at 0
    q: float  # filter quality factor (resonance)
    env_oct: float  # cutoff envelope depth in octaves
    env_decay_s: float  # time constant of the cutoff envelope
    accent_oct: float  # cutoff lift in octaves at accent amount 1
    ramp_oct: float  # cutoff rise in octaves from the clip's start to its end
    attack_s: float  # linear amplitude attack (0 = none)
    decay_s: float  # amplitude decay time constant (0 = sustain)
    release_s: float  # linear release to exactly 0 after the note's end
    square: float  # level of the square next to the saw
    delay_wet: float  # share of the echoes (0 = no delay)
    slides: bool  # overlapping notes glide (one note at a time)
    detune: tuple[float, ...] = (1.0,)  # frequency ratios of the saws that make one note
    key_track: float = 0.0  # cutoff octaves per octave of pitch above key_ref
    key_ref: int = 60  # MIDI note at which the cutoff is exactly as computed without tracking


VOICES: dict[str, Voice] = {
    # sourced: saw through a resonant band-pass (general source); forum: square share, ping-pong.
    # key_track 0.5 from the lowest note of the window: measured, the level of an unaccented
    # 2-beat note then differs by 2.3 dB between MIDI 60 and 83 (10.9 dB without tracking)
    "lead": Voice(dsp.BANDPASS, base_hz=900.0, q=4.0, env_oct=1.5, env_decay_s=0.20,
                  accent_oct=1.0, ramp_oct=1.0, attack_s=0.002, decay_s=0.0, release_s=0.060,
                  square=SQUARE_LEVEL, delay_wet=DELAY_WET, slides=True,
                  key_track=0.5, key_ref=60),
    # forum: attack 0, decay, fast release, band-pass
    "arp": Voice(dsp.BANDPASS, base_hz=700.0, q=4.0, env_oct=2.0, env_decay_s=0.09,
                 accent_oct=1.0, ramp_oct=1.0, attack_s=0.0, decay_s=0.12, release_s=0.030,
                 square=SQUARE_LEVEL, delay_wet=DELAY_WET, slides=True,
                 key_track=0.5, key_ref=57),
    # sourced: saw, resonant low-pass, strong envelope with a short decay, high resonance,
    # glide on overlaps (303-style line); the numbers themselves are derived
    "pluck": Voice(dsp.LOWPASS, base_hz=300.0, q=8.0, env_oct=3.0, env_decay_s=0.12,
                   accent_oct=1.0, ramp_oct=1.0, attack_s=0.0, decay_s=0.30, release_s=0.020,
                   square=0.0, delay_wet=DELAY_WET_PLUCK, slides=True),
    # two detuned saws, low-pass without resonance peak (q = 0.707), slow attack, no delay
    "pad": Voice(dsp.LOWPASS, base_hz=1200.0, q=0.707, env_oct=0.0, env_decay_s=1.0,
                 accent_oct=0.0, ramp_oct=0.0, attack_s=0.250, decay_s=0.0, release_s=0.400,
                 square=0.0, delay_wet=0.0, slides=False, detune=PAD_DETUNE),
}


@dataclass(frozen=True)
class PreviewNote:
    """One note event. ``start`` and ``length`` in beats (quarter notes) from the clip start."""

    pitch: int
    start: float
    length: float
    velocity: int


def accent_amount(velocity: float) -> float:
    span = ACCENT_VELOCITY_HIGH - ACCENT_VELOCITY_LOW
    return min(1.0, max(0.0, (velocity - ACCENT_VELOCITY_LOW) / span))


def delay_samples(bpm: float) -> int:
    """The echo spacing: DELAY_SIXTEENTHS sixteenth notes at ``bpm``, in samples."""
    return max(1, int(round(DELAY_SIXTEENTHS * 60.0 / bpm / 4.0 * SAMPLE_RATE)))


def _dry_samples(bpm: float, beats: float) -> int:
    return int((beats * 60.0 / bpm + TAIL_S) * SAMPLE_RATE)


def _check(bpm: float, beats: float) -> None:
    if not (isinstance(bpm, (int, float)) and math.isfinite(bpm) and 20 <= bpm <= 400):
        raise ValueError("bpm must be 20-400")
    if not (isinstance(beats, (int, float)) and math.isfinite(beats) and beats > 0):
        raise ValueError("clip length must be positive")


def events_seconds(voices: Sequence[str], bpm: float, beats: float) -> float:
    """Length of the preview of these voices: clip, release tail, echoes."""
    _check(bpm, beats)
    echoes = max((dsp.echo_count(DELAY_FEEDBACK, VOICES[v].delay_wet) for v in voices), default=0)
    return (_dry_samples(bpm, beats) + echoes * delay_samples(bpm)) / SAMPLE_RATE


def _chains(notes: Sequence[PreviewNote], slides: bool) -> list[list[PreviewNote]]:
    """Notes grouped into what one envelope plays: a note, or a run of overlapping notes."""
    ordered = sorted(notes, key=lambda n: (n.start, n.pitch, n.length, n.velocity))
    if not slides:
        return [[n] for n in ordered]
    chains: list[list[PreviewNote]] = []
    for n in ordered:
        prev = chains[-1][-1] if chains else None
        if prev is not None and n.start < prev.start + prev.length:
            chains[-1].append(n)
        else:
            chains.append([n])
    return chains


def _segment(v: Voice, chain: Sequence[PreviewNote], bpm: float, clip_n: int,
             total_n: int) -> tuple[int, np.ndarray, np.ndarray, np.ndarray] | None:
    """One chain as (first sample, source signal, cutoff in Hz, gain) or None if outside."""
    sr = SAMPLE_RATE
    per_beat = 60.0 / bpm * sr
    starts = [int(round(n.start * per_beat)) for n in chain]
    s0 = starts[0]
    last = chain[-1]
    if s0 < 0 or s0 >= clip_n:
        return None
    # a note is released at the clip's end at the latest, so its release fits into TAIL_S
    gate_end = min(clip_n, max(starts[-1] + 1, int(round((last.start + last.length) * per_beat))))
    n_on = gate_end - s0
    n_rel = max(1, int(v.release_s * sr))
    m = min(n_on + n_rel, total_n - s0)
    # per-sample pitch (log2 Hz), velocity and accent; a slide ramps all three within GLIDE_S
    pitch = np.empty(m)
    vel = np.empty(m)
    glide_n = max(1, int(GLIDE_S * sr))
    pitch[:] = math.log2(dsp.midi_hz(chain[0].pitch))
    vel[:] = chain[0].velocity
    for n, st in zip(chain[1:], starts[1:], strict=True):
        a = st - s0
        if a >= n_on:
            break
        b = min(m, a + glide_n)
        frac = np.arange(1, b - a + 1) / glide_n
        for arr, target in ((pitch, math.log2(dsp.midi_hz(n.pitch))), (vel, float(n.velocity))):
            arr[a:b] = arr[a] + (target - arr[a]) * frac
            arr[b:] = target
    freq = np.exp(pitch * _LN2)
    accent = np.clip((vel - ACCENT_VELOCITY_LOW)
                     / (ACCENT_VELOCITY_HIGH - ACCENT_VELOCITY_LOW), 0.0, 1.0)
    t = np.arange(m) / sr
    src = sum(dsp.saw(freq * d, sr) for d in v.detune) / len(v.detune)
    if v.square:
        src = src + v.square * dsp.square(freq, sr)
    position = np.clip((s0 + np.arange(m)) / clip_n, 0.0, 1.0)
    octaves = v.accent_oct * accent + v.ramp_oct * position
    if v.key_track:
        octaves = octaves + v.key_track * (pitch - math.log2(dsp.midi_hz(v.key_ref)))
    if v.env_oct:
        octaves = octaves + v.env_oct * np.exp(-t / v.env_decay_s)
    cutoff = v.base_hz * np.exp(octaves * _LN2)
    env = np.ones(m)
    if v.attack_s > 0:
        env = np.minimum(1.0, (np.arange(m) + 1) / max(1, int(v.attack_s * sr)))
    if v.decay_s > 0:
        env = env * np.exp(-t / v.decay_s)
    if m > n_on:  # release: linear from the level at the note's end to exactly 0
        env[n_on:] = env[n_on - 1] * (1.0 - np.arange(1, m - n_on + 1) / n_rel)
    return s0, src, cutoff, env * (vel / 127.0) ** VELOCITY_EXPONENT


def render_voice_dry(voice: str, notes: Sequence[PreviewNote], bpm: float,
                     beats: float) -> np.ndarray:
    """Mono float64 signal of one voice before echoes and normalisation (clip + TAIL_S)."""
    if voice not in VOICES:
        raise ValueError(f"voice must be one of {list(VOICES)}")
    _check(bpm, beats)
    v = VOICES[voice]
    total_n = _dry_samples(bpm, beats)
    clip_n = max(1, int(round(beats * 60.0 / bpm * SAMPLE_RATE)))
    segs = [s for s in (_segment(v, c, bpm, clip_n, total_n)
                        for c in _chains([n for n in notes if n.length > 0], v.slides))
            if s is not None]
    buf = np.zeros(total_n)
    filtered = dsp.resonant_filter([s[1] for s in segs], [s[2] for s in segs], v.q,
                                   SAMPLE_RATE, v.mode)
    for (s0, _src, _cut, gain), y in zip(segs, filtered, strict=True):
        buf[s0:s0 + len(y)] += y * gain
    return buf


def _voice_stereo(voice: str, notes: Sequence[PreviewNote], bpm: float,
                  beats: float) -> np.ndarray:
    return dsp.ping_pong(render_voice_dry(voice, notes, bpm, beats), delay_samples(bpm),
                         DELAY_FEEDBACK, VOICES[voice].delay_wet)


def _finish(buf: np.ndarray) -> np.ndarray:
    if buf.shape[0] / SAMPLE_RATE > MAX_SECONDS:
        raise ValueError("preview too long")
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0:
        buf = buf * (PEAK / peak)
    return buf.astype(np.float32)


def render_events(voice: str, notes: Sequence[PreviewNote], bpm: float,
                  beats: float) -> np.ndarray:
    """Stereo float32 ``(n, 2)`` preview of one voice's notes; ``beats`` = clip length."""
    return _finish(_voice_stereo(voice, notes, bpm, beats))


def render_events_mix(notes_by_voice: Mapping[str, Sequence[PreviewNote]], bpm: float,
                      beats: float) -> np.ndarray:
    """Stereo float32 preview of several voices together: each voice at its own peak times
    :data:`MIX_GAIN`, summed, then normalised to :data:`PEAK`."""
    if any(v not in VOICES for v in notes_by_voice):
        raise ValueError(f"voices must be from {list(VOICES)}")
    n = int(round(events_seconds(list(notes_by_voice), bpm, beats) * SAMPLE_RATE))
    buf = np.zeros((n, 2))
    for voice, notes in notes_by_voice.items():
        b = _voice_stereo(voice, notes, bpm, beats)
        p = float(np.max(np.abs(b))) if b.size else 0.0
        if p > 0:
            buf[: len(b)] += b * (MIX_GAIN[voice] / p)
    return _finish(buf)


# --- adapter to the clip generator -------------------------------------------------------
def _notes(voice: str, options: Mapping[str, Any]) -> list[PreviewNote]:
    return [PreviewNote(nt.pitch, nt.start / PPQ, (nt.end - nt.start) / PPQ, nt.velocity)
            for nt in goa_clips.clip_notes(voice, **options)]


def _clip(options: Mapping[str, Any], voices: Sequence[str]) -> tuple[float, float]:
    o = goa_clips.normalise(options)
    bpm, beats = float(o["bpm"]), o["bars"] * 4.0
    if events_seconds(voices, bpm, beats) > MAX_SECONDS:
        raise ValueError("preview too long")
    return bpm, beats


def preview_seconds(**options: Any) -> float:
    """Length of the mix preview of the selected voices."""
    o = goa_clips.normalise(options)
    return events_seconds(o["voices"], float(o["bpm"]), o["bars"] * 4.0)


def render_voice_preview(voice: str, **options: Any) -> np.ndarray:
    """Stereo float32 preview of one voice's clip (one pass, tail, echoes)."""
    if voice not in goa_clips.VOICES:
        raise ValueError(f"voice must be one of {list(goa_clips.VOICES)}")
    bpm, beats = _clip(options, [voice])
    return render_events(voice, _notes(voice, options), bpm, beats)


def render_mix_preview(**options: Any) -> np.ndarray:
    """Stereo float32 preview of all selected voices (``voices`` option) played together."""
    o = goa_clips.normalise(options)
    bpm, beats = _clip(options, o["voices"])
    return render_events_mix({v: _notes(v, options) for v in o["voices"]}, bpm, beats)


def voice_preview_wav_bytes(voice: str, **options: Any) -> bytes:
    return encode_wav(render_voice_preview(voice, **options), SAMPLE_RATE, 16)


def mix_preview_wav_bytes(**options: Any) -> bytes:
    return encode_wav(render_mix_preview(**options), SAMPLE_RATE, 16)
