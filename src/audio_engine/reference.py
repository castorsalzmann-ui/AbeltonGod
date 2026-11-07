"""Reference kick analysis and nearest-candidate search (issue #480, first slice of #58).

:func:`match_reference_file` reads a user WAV, measures it, and finds the kick among a fixed
grid of candidates whose measures lie closest. The result says which *engine parameters* give
measures near the reference's. It does not say that the candidate sounds like the reference;
only the user's listening decides that (D-032: "no synthesis that claims to match a
reference"). Nothing is fitted or optimised.

Reading (:func:`read_reference_wav`): RIFF/WAVE with PCM (format tag 1, or 0xFFFE
WAVE_FORMAT_EXTENSIBLE with the PCM sub-format), 16 or 24 bit, mono or stereo, 44.1 or 48 kHz,
50 ms to :data:`MAX_SECONDS`. Stereo becomes the mean of both channels (a side signal that
cancels in the sum is not measured). Anything else raises :class:`ReferenceAudioError` with a
German message for the GUI.

Measures (:func:`measure`), all on the mono signal with its mean (DC) subtracted, from its
**onset**, the first sample whose magnitude reaches 10 % of the peak (kick-gen2 learnings,
section 2 method and pitfall 2). The mean subtraction removes a constant offset exactly; a
file whose wanted content has a mean far from 0 (not high-passed) gets that mean removed too,
and an offset that changes inside the file is not removed:

- ``fundamental_hz``, ``decay_20db_ms``, ``decay_40db_ms``: :func:`audio_engine.analysis.analyse`
  of the signal from the onset (so the times count from the onset). Their limits apply: the
  fundamental is ``None`` for short tails and approximate (+-5 %) for very short kicks; the
  decay times are on a 40 ms max-envelope and are not the inverse of ``amp_decay_ms`` (the
  docstring of :mod:`audio_engine.analysis`, #27, #32); ``None`` when the level never falls
  that far inside the file (pitfall 5) -- a reference cut off early gives ``None`` or a
  censored value, never a guess.
- ``body_hz``: zero-crossing frequency over :data:`BODY_WINDOW_MS` after the onset, on a
  copy low-passed at :data:`BODY_LOWPASS_HZ` (2nd order) so click noise does not add
  crossings. It summarises how far the pitch drop has come in the body zone; it is not a
  start pitch (start pitch is "not established", kick-gen2 section 2).
- ``sub_share``: energy below 100 Hz over all energy, whole signal from the onset, rectangular
  window (pitfall 1).
- ``click_share``: energy above 1 kHz over all energy in the first 10 ms after the onset
  (the "onset brightness" of kick-gen2 section 2).

All measures are in physical units (Hz, ms, energy shares), so a 44.1 kHz reference is compared
with 48 kHz candidates without resampling.

Distance (:func:`distances`): per measure, ``|a - b| / scale`` on the transformed values of
:data:`MEASURES` (pitches in semitones, times as log ratios, shares linear). A measure that is
``None`` on exactly one side counts :data:`MISSING_DISTANCE`; on both sides 0. The total is the
root mean square over every measure, so the number of measures is fixed.

Candidates (:func:`candidates`): every kick preset with variants ``0 ..
VARIANTS_PER_PRESET - 1`` of :func:`audio_engine.variants.make_variants` (variant 0 is the
preset itself), rendered with the engine and measured once per process (cached). Same
presets and engine give the same candidates; the search is a plain minimum with ties broken by
grid order, so the same file always gives the same answer.
"""

from __future__ import annotations

import functools
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .analysis import analyse, zero_crossing_frequency
from .dsp import rbj_lowpass
from .kick import render_resolved
from .presets import load_preset, preset_names
from .variants import make_variants

SAMPLE_RATES = (44100, 48000)
BIT_DEPTHS = (16, 24)
MIN_SECONDS = 0.05
MAX_SECONDS = 3.0  # a kick one-shot; longer files are likely loops or tracks (not split here)
MAX_FILE_BYTES = 64 * 1024 * 1024
SILENCE_DBFS = -60.0  # peak below this: the file counts as silent

ONSET_FRACTION = 0.1
# Body zone (kick-gen2 F1: about 5-80 ms). Starts after most of the click; 60 ms holds three
# positive zero crossings down to about 40 Hz (zero_crossing_frequency needs three).
BODY_WINDOW_MS = (10.0, 70.0)
BODY_LOWPASS_HZ = 400.0
SUB_SPLIT_HZ = 100.0
CLICK_SPLIT_HZ = 1000.0
CLICK_WINDOW_MS = 10.0

VARIANTS_PER_PRESET = 8
MISSING_DISTANCE = 3.0

# name -> (transform, scale). semitone: 12 * log2(x); log: ln(x); lin: x.
MEASURES: dict[str, tuple[str, float]] = {
    "fundamental_hz": ("semitone", 1.0),  # 1 semitone (5.9 %)
    "body_hz": ("semitone", 2.0),
    "decay_20db_ms": ("log", math.log(1.25)),  # analysis.py: -8 to +25 % on clean kicks
    "decay_40db_ms": ("log", math.log(1.25)),
    "sub_share": ("lin", 0.05),
    "click_share": ("lin", 0.05),
}


class ReferenceAudioError(ValueError):
    """The file cannot be used as a reference; the message is German (shown in the GUI)."""


@dataclass(frozen=True)
class ReferenceAudio:
    samples: np.ndarray  # mono float64, full scale 1.0
    sample_rate: int
    channels: int
    bit_depth: int

    @property
    def length_ms(self) -> float:
        return len(self.samples) / self.sample_rate * 1000.0


@dataclass(frozen=True)
class Candidate:
    name: str  # "<preset> v<index>"
    preset: str
    variant: int
    params: dict[str, Any]  # resolved kick-params (re-renders the candidate)
    measures: dict[str, float | None]


@dataclass(frozen=True)
class ReferenceMatch:
    reference: dict[str, float | None]  # measures of the reference (plus info fields)
    nearest: Candidate
    distances: dict[str, float]  # per measure, nearest vs reference
    total: float
    ranking: list[tuple[float, Candidate]] = field(default_factory=list)  # all, nearest first


# --- reading ------------------------------------------------------------------------------------

def read_reference_wav(path: str | Path) -> ReferenceAudio:
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ReferenceAudioError(f"Datei nicht lesbar: {path.name} ({exc.strerror or exc}).") \
            from exc
    if size > MAX_FILE_BYTES:
        raise ReferenceAudioError(
            f"Die Datei ist zu groß ({size // (1024 * 1024)} MB); erwartet wird ein einzelner "
            f"Kick von höchstens {MAX_SECONDS:g} s.")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReferenceAudioError(f"Datei nicht lesbar: {path.name} ({exc.strerror or exc}).") \
            from exc
    return decode_reference_wav(data)


def decode_reference_wav(data: bytes) -> ReferenceAudio:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ReferenceAudioError("Keine WAV-Datei (RIFF/WAVE-Kopf fehlt).")
    fmt: bytes | None = None
    frames: bytes | None = None
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        (csize,) = struct.unpack("<I", data[pos + 4:pos + 8])
        body = data[pos + 8:pos + 8 + csize]
        if cid == b"fmt ":
            fmt = body
        elif cid == b"data":
            if len(body) < csize:
                raise ReferenceAudioError(
                    "Die WAV-Datei ist abgeschnitten (data-Block unvollständig).")
            if frames is None:  # the first data chunk counts; keep walking for a later fmt
                frames = body
        pos += 8 + csize + (csize & 1)  # chunks are padded to an even size
    if fmt is None or len(fmt) < 16:
        raise ReferenceAudioError("Die WAV-Datei hat keinen gültigen fmt-Block.")
    if frames is None:
        raise ReferenceAudioError("Die WAV-Datei enthält keinen data-Block.")
    tag, channels, sr, _, block, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE and len(fmt) >= 26:
        tag = struct.unpack("<H", fmt[24:26])[0]  # first two bytes of the sub-format GUID
    if tag != 1:
        raise ReferenceAudioError(
            "Nur unkomprimiertes PCM wird gelesen (keine Float-, MP3- oder ADPCM-WAVs).")
    if bits not in BIT_DEPTHS:
        raise ReferenceAudioError(
            f"{bits} Bit wird nicht unterstützt; erlaubt sind 16 oder 24 Bit.")
    if channels not in (1, 2):
        raise ReferenceAudioError(
            f"{channels} Kanäle werden nicht unterstützt; erlaubt: Mono, Stereo.")
    if sr not in SAMPLE_RATES:
        raise ReferenceAudioError(
            f"Samplerate {sr} Hz wird nicht unterstützt; erlaubt sind 44100 und 48000 Hz.")
    width = bits // 8
    if block != width * channels:
        raise ReferenceAudioError("Die WAV-Datei hat einen ungültigen fmt-Block (Blockgröße).")
    n = len(frames) // block
    seconds = n / sr
    if seconds > MAX_SECONDS:
        raise ReferenceAudioError(
            f"Die Datei ist zu lang ({seconds:.1f} s); erwartet wird ein einzelner Kick von "
            f"höchstens {MAX_SECONDS:g} s. Loops bitte vorher auf den ersten Schlag kürzen.")
    if seconds < MIN_SECONDS:
        raise ReferenceAudioError(
            f"Die Datei ist zu kurz ({seconds * 1000:.0f} ms); mindestens "
            f"{MIN_SECONDS * 1000:.0f} ms.")
    raw = frames[:n * block]
    if bits == 16:
        ints = np.frombuffer(raw, dtype="<i2").astype(np.int64)
    else:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
        value = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = np.where(value >= 1 << 23, value - (1 << 24), value)
    x = ints.reshape(n, channels).astype(np.float64).mean(axis=1) / float(2 ** (bits - 1))
    peak = float(np.max(np.abs(x - np.mean(x)))) if n else 0.0  # pure DC is silence too
    if peak <= 10 ** (SILENCE_DBFS / 20.0):
        raise ReferenceAudioError(
            f"Die Datei ist still (Spitze unter {SILENCE_DBFS:g} dBFS"
            + (", nach dem Mischen der Kanäle auf Mono" if channels == 2 else "") + ").")
    return ReferenceAudio(x, int(sr), int(channels), int(bits))


# --- measuring ----------------------------------------------------------------------------------

def onset_index(audio: np.ndarray) -> int:
    """First sample whose magnitude reaches ``ONSET_FRACTION`` of the peak (0 for silence)."""
    mag = np.abs(audio)
    peak = float(np.max(mag)) if len(mag) else 0.0
    if peak == 0.0:
        return 0
    return int(np.argmax(mag >= ONSET_FRACTION * peak))


def measure(audio: np.ndarray, sr: int) -> dict[str, float | None]:
    """The measures of :data:`MEASURES` for a mono signal (see the module docstring)."""
    if audio.ndim != 1:
        raise ValueError("measure() expects mono audio (1-D array).")
    # Remove DC first (review of #485, finding 1): a constant offset in a user file moves the
    # zero crossings and holds the envelope above -40 dB (1 % DC: fundamental and -40 dB decay
    # became None). Engine renders already have mean 0 (kick.py step 8), so candidates are
    # unchanged by this; for them it subtracts at most float rounding.
    x = audio - np.mean(audio) if len(audio) else audio
    x = x[onset_index(x):]
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak > 0.0:
        x = x / peak
    base = analyse(x, sr)
    a, b = (int(round(ms * sr / 1000.0)) for ms in BODY_WINDOW_MS)
    body = None
    if len(x) >= b:
        low = rbj_lowpass(x[:b], sr, BODY_LOWPASS_HZ)
        body = zero_crossing_frequency(low[a:b], sr)
    power = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    total = float(np.sum(power))
    sub = round(float(np.sum(power[freqs < SUB_SPLIT_HZ]) / total), 6) if total > 0 else None
    head = x[:int(round(CLICK_WINDOW_MS * sr / 1000.0))]
    hp = np.abs(np.fft.rfft(head)) ** 2
    hf = np.fft.rfftfreq(len(head), 1.0 / sr)
    htotal = float(np.sum(hp))
    click = round(float(np.sum(hp[hf > CLICK_SPLIT_HZ]) / htotal), 6) if htotal > 0 else None
    return {
        "fundamental_hz": base["fundamental_hz"],
        "body_hz": body,
        "decay_20db_ms": base["decay_20db_ms"],
        "decay_40db_ms": base["decay_40db_ms"],
        "sub_share": sub,
        "click_share": click,
    }


def _transform(kind: str, value: float) -> float:
    if kind == "semitone":
        return 12.0 * math.log2(max(value, 1e-9))
    if kind == "log":
        return math.log(max(value, 1e-9))
    return value


def distances(a: dict[str, float | None], b: dict[str, float | None]) -> dict[str, float]:
    """Per-measure distance (see the module docstring)."""
    out: dict[str, float] = {}
    for name, (kind, scale) in MEASURES.items():
        va, vb = a.get(name), b.get(name)
        if va is None and vb is None:
            out[name] = 0.0
        elif va is None or vb is None:
            out[name] = MISSING_DISTANCE
        else:
            out[name] = abs(_transform(kind, va) - _transform(kind, vb)) / scale
    return out


def total_distance(per_measure: dict[str, float]) -> float:
    return math.sqrt(sum(d * d for d in per_measure.values()) / len(MEASURES))


# --- candidates and search ----------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def candidates() -> tuple[Candidate, ...]:
    """Every kick preset x variants 0 .. VARIANTS_PER_PRESET - 1, rendered and measured."""
    out: list[Candidate] = []
    for name in preset_names("kick"):
        for i, params in enumerate(make_variants(load_preset(name), VARIANTS_PER_PRESET)):
            audio = render_resolved(params)
            out.append(Candidate(f"{name} v{i}", name, i, params,
                                 measure(audio, int(params["sample_rate"]))))
    return tuple(out)


def match_measures(ref: dict[str, float | None]) -> ReferenceMatch:
    ranking = sorted(((total_distance(distances(ref, c.measures)), k, c)
                      for k, c in enumerate(candidates())), key=lambda t: (t[0], t[1]))
    total, _, best = ranking[0]
    return ReferenceMatch(dict(ref), best, distances(ref, best.measures), total,
                          [(d, c) for d, _, c in ranking])


def match_reference(audio: ReferenceAudio) -> ReferenceMatch:
    ref = measure(audio.samples, audio.sample_rate)
    match = match_measures(ref)
    match.reference.update(length_ms=round(audio.length_ms, 3),
                           sample_rate=audio.sample_rate, channels=audio.channels,
                           bit_depth=audio.bit_depth)
    return match


def match_reference_file(path: str | Path) -> ReferenceMatch:
    """Read ``path`` (:func:`read_reference_wav`) and find the nearest candidate."""
    return match_reference(read_reference_wav(path))
