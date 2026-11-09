"""Reference steering v2, slice 1 (#540): reader, kick and bass features, calibrated distance.

Design: ``docs/research/2026-11-08_reference-steering-v2.md`` (sections 2, 3.1, 3.7, 10 E1-E3).
Nothing here fits parameters (E6) or says that a render sounds like a reference (D-032). The
v1 kick page (:mod:`audio_engine.reference`, :mod:`gui_core.reference`) is unchanged: its
reader keeps rejecting float and 96 kHz files, and :func:`audio_engine.reference.measure` is
called here unchanged for the six v1 kick values.

Reader (:func:`read_reference_v2`, E1)
--------------------------------------
RIFF/WAVE, PCM 16/24 bit or IEEE float 32 bit (format tag 3, or 0xFFFE with that sub-format),
mono or stereo, 44.1 / 48 / 96 kHz. Stereo is kept as an ``(n, 2)`` array; mono features use
the mid signal ``(L + R) / 2``. Float samples are kept as written (values above 1.0 are not
clipped; every feature is peak-normalised). NaN or infinite samples are refused.

Hits: the file is split at the first *rise* of its 10 ms RMS envelope (hop 1 ms) of at least
:data:`HIT_RISE_DB` over the minimum of the preceding :data:`HIT_LOOKBACK_MS`, to a level
within :data:`HIT_LEVEL_DB` of the file's envelope peak, at least :data:`HIT_MIN_GAP_MS` after
the previous hit. ``hit_count`` counts such rises (plus the first hit); the first hit ends at
the envelope minimum before the second (kick-gen2 pitfall 6). Not seen (limits): a later hit
that starts while the previous one is still within 15 dB of the new level, and a hit more
than 6 dB below the loudest (it stays inside the first hit's segment).

Length limits per category come from the contracts (read from the schema files): kick
``length_ms`` 80 ... 2000 ms; bass ``gate_ms + release_ms`` minimum (55 ms) to ``offset_ms +
gate_ms + release_ms`` maximum (1912 ms). They apply to the first hit, counted from sample 0
of the file (so leading and trailing silence count, and an engine render of the exact limit
passes). The whole file may be up to :data:`LOOP_MAX_SECONDS` (loops).

``censored_tail`` (pitfall 7: a hit cut by the next one, or a file that ends early). Kick:
the 5 ms RMS envelope of the first hit (mid, DC removed) does not fall
:data:`CENSOR_DROP_DB` below its peak before the last :data:`CENSOR_GUARD_MS` of the hit (the
guard covers the engine's 5 ms fade-out, which would otherwise fake a decay). Bass: the last
:data:`BASS_END_MS` of the hit still reach :data:`BASS_END_DB` of its peak. The kick rule
cannot be used for a bass: its linear release reaches -40 dB only in its last 1 %, inside
any guard, so every engine bass counted as cut.

Preprocessing for every feature (note section 2.1): mid signal of the first hit, mean (DC)
removed, cut at the onset (first sample at 10 % of the peak), peak-normalised. All times are
counted from that onset.

Kick features (section 3.1, :func:`kick_features_from_audio`)
-------------------------------------------------------------
- The six values of :func:`audio_engine.reference.measure` (unchanged, byte-equal).
- ``pitch_5ms_hz`` ... ``pitch_40ms_hz``: frequency from the unwrapped phase of the analytic
  signal of a zero-phase FFT low-pass (flat to 600 Hz, raised-cosine to 0 at 800 Hz, so about
  700 Hz at -6 dB; kick-gen2 section 2): ``1 / (t+ - t-)`` where the phase is ``pi`` below and
  above its value at the time. That is the mean frequency over one period centred (in phase)
  on the time. One period, not a fixed window, because the odd harmonics of a driven body
  make the phase slope oscillate inside a period (a +-1 ms slope was off by up to 9
  semitones on the ``driven`` preset; over a whole period they cancel). Cost: during a fast
  drop the one-period mean lags the instantaneous pitch (synthetic 600 -> 30 Hz with a 2 ms
  time constant: -22 % at 5 ms). ``None`` when that period starts less than 1 ms after the onset
  (:data:`PITCH_EDGE_MS`), leaves the signal, or the analytic magnitude in it falls below
  -60 dB of its maximum. Values before 5 ms are not measured
  (start pitch "not established", kick-gen2 section 2).
- ``tail_harmonics_db``: power of partials 2 ... 8 over the fundamental, dB, in the tail
  window of :func:`audio_engine.analysis.tail_window`, cut to whole periods of
  ``fundamental_hz``, Hann window, DFT at the exact partial frequencies (partials at or above
  Nyquist are skipped). Floored at :data:`DB_FLOOR`. ``None`` without a fundamental or with
  fewer than 4 periods in the window.
- ``body_energy_db``: energy in 80 ... 300 Hz of the 5 ... 80 ms zone (rectangular window,
  pitfall 1) over the energy of the whole signal, dB, floored at :data:`DB_FLOOR`. ``None``
  if the signal is shorter than 80 ms.

Bass features (section 3.7, :func:`bass_features_from_audio`)
-------------------------------------------------------------
A reference has no gate parameter, so the gate is estimated from the signal:

1. Gate (:func:`knee_gate`): break point of a two-line least-squares fit of the 25 ms forward
   max-envelope, the second line ending at 0 where the envelope reaches -40 dB (a held note
   with a linear release). Tried first and dropped: "last time at -6 dB of the peak" (a
   bright start more than 6 dB above the hold moved it to the start), and the 90 % / 50 %
   points of the release (a hold whose level falls with the filter envelope moved them).
2. Period (:func:`period_hz`, YIN) in the *stationary window* (:func:`stationary`): 40 ...
   80 % of that gate (the contract's window), or 10 ... 90 % when 40-80 % holds fewer than 4
   periods or no period. Short rolling notes need the wide window: a 62 ms gate at 65 Hz
   leaves 1.6 periods in 40-80 %, and YIN, which needs 2, found nothing. If the period is
   longer than 25 ms, step 1 is repeated with a one-period envelope window.
3. ``release_ms`` = last sample with |x| >= 0.01 L (-40 dB, ``L`` = max |x| in the stationary
   window) minus ``gate_ms`` (contract rule 8 reads it the same way on renders).

- ``note_hz``: the frequency of the waveform period in the stationary window. With an audible
  sub-octave the waveform repeats at f0 / 2, so ``note_hz`` is f0 / 2 there; the sidecar
  convention "the note, not the sub" (contract rule 6) needs the parameters, which a
  reference does not have. A spectral "is the lowest peak a sub?" rule was tried and
  dropped: with ``drive`` the intermodulation at 1.5 f0 came within 15 dB of f0 and the
  rule flipped. Mapping the period to ``note`` and ``sub_octave_level`` is left to the fit
  (E6). ``None`` if the window holds fewer than 2 periods or YIN finds no dip below 0.25.
- ``harm2_db``, ``harm3_db``: level of the partial at 2 / 3 x note over the note, dB,
  stationary window cut to an even number of note periods (so a sub-octave is whole too),
  rectangular, DFT at the exact frequencies; floored at :data:`HARM_FLOOR_DB` (-60 dB);
  ``None`` below 2 whole periods (over whole periods the DFT of a periodic note is exact;
  synthetic saws at 2-4 periods give -6.02 / -9.54 dB within 0.01 dB).
- ``sub_share``: energy below 100 Hz over all, whole signal from the onset (as the kick).
- ``centroid_hz``: power-weighted mean frequency of the stationary window (rectangular, whole
  periods, DC excluded).
- ``filter_move_db``: 20 log10 of the centroid of the first 30 ms over ``centroid_hz``;
  ``None`` when 30 ms hold fewer than 2 note periods (bass note P4).
- ``attack_ms``: 10 % to 90 % of ``L`` on the backward running max of |x| (max so far); a
  sine series reaches its crest up to one period late, so the error is up to one period of
  the lowest peak (contract rule 8 gives the same tolerance).
- ``gate_ms``, ``release_ms``: step 3.

Distance (E3, :func:`feature_distances`, :func:`total_distance`)
----------------------------------------------------------------
Per feature ``|T(a) - T(b)| / scale`` with the transforms of :data:`FEATURES` (semitone =
12 log2, log = ln, db and lin as is). One side ``None`` = :data:`MISSING_DISTANCE`, both
``None`` = 0. Total = root of the weighted mean of squares over the features with weight >
0. Scales and weights come from the committed calibration table
(``calibration/reference_scales.json``, written by :mod:`audio_engine.reference_calibration`);
a feature missing from the table uses its provisional scale (note section 3) and weight 1,
and :func:`feature_table` marks it ``provisional``.
"""

from __future__ import annotations

import functools
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .analysis import tail_window
from .params import CONTRACTS_DIR, load_schema
from .reference import (
    MAX_FILE_BYTES,
    SILENCE_DBFS,
    ReferenceAudioError,
    measure,
    onset_index,
    riff_chunks,
)

# --- reader constants -------------------------------------------------------------------------

SAMPLE_RATES_V2 = (44100, 48000, 96000)
PCM_BITS = (16, 24)
FLOAT_BITS = 32
LOOP_MAX_SECONDS = 30.0  # whole file (a loop); the category limit applies to the first hit
CATEGORIES = ("kick", "bass")
CATEGORY_LABEL = {"kick": "Kick", "bass": "Bass-Ton"}

HIT_ENV_MS = 10.0  # RMS window of the hit detector (ripple about 5 dB at 30 Hz)
HIT_HOP_MS = 1.0
HIT_RISE_DB = 15.0
# A hit rises within about one envelope window. 30 ms counted the slow re-rise of two
# layers that cancel and rebuild (15 dB over 25 ms, a beating stereo mid) as a second hit.
HIT_LOOKBACK_MS = 12.0
# A later hit must come back to within 6 dB of the loudest: the rebuilt level of two
# cancelling layers stays below (-9 dB measured at 96 kHz, where the null is sharper and
# rises 15 dB within 12 ms). Cost: ghost notes and accents more than 6 dB down stay inside
# the first hit's segment.
HIT_LEVEL_DB = -6.0
HIT_MIN_GAP_MS = 50.0

CENSOR_ENV_MS = 5.0  # pitfall 4: RMS envelope of at least 5 ms
CENSOR_DROP_DB = 40.0
CENSOR_GUARD_MS = 6.0  # >= the kick/clap FADE_OUT_MS (5 ms)
# A bass release is a linear ramp that ends at 0 with the file: it is censored when its last
# millisecond is still above -20 dB (releases below about 10 ms count as cut).
BASS_END_MS = 1.0
BASS_END_DB = -20.0


@dataclass(frozen=True)
class ReferenceAudioV2:
    """A decoded reference. ``samples`` is ``(n,)`` for mono, ``(n, 2)`` for stereo."""

    samples: np.ndarray
    sample_rate: int
    channels: int
    bit_depth: int
    sample_format: str  # "pcm" or "float"
    hit_count: int
    first_hit_end: int  # sample index where the first hit ends (exclusive)
    censored_tail: bool

    @property
    def multi_hit(self) -> bool:
        return self.hit_count > 1

    @property
    def length_ms(self) -> float:
        return len(self.samples) / self.sample_rate * 1000.0

    @property
    def mid(self) -> np.ndarray:
        """Mono mid signal ``(L + R) / 2`` of the whole file (the samples for mono)."""
        return mid_signal(self.samples)

    @property
    def first_hit(self) -> np.ndarray:
        """Mid signal of the first hit."""
        return self.mid[: self.first_hit_end]

    @property
    def first_hit_stereo(self) -> np.ndarray:
        return self.samples[: self.first_hit_end]


def mid_signal(samples: np.ndarray) -> np.ndarray:
    return samples if samples.ndim == 1 else samples.mean(axis=1)


@functools.cache
def length_limits_ms(category: str) -> tuple[float, float]:
    """(min, max) length in ms of one sound of ``category``, from its contract."""
    if category == "kick":
        p = load_schema(CONTRACTS_DIR / "kick-params.schema.json")["properties"]
        return float(p["length_ms"]["minimum"]), float(p["length_ms"]["maximum"])
    if category == "bass":
        p = load_schema(CONTRACTS_DIR / "bass-params.schema.json")["properties"]
        lo = p["gate_ms"]["minimum"] + p["release_ms"]["minimum"]
        hi = p["offset_ms"]["maximum"] + p["gate_ms"]["maximum"] + p["release_ms"]["maximum"]
        return float(lo), float(hi)
    raise ReferenceAudioError(
        f"Die Kategorie „{category}“ wird für Referenzen noch nicht unterstützt "
        f"(möglich: {', '.join(CATEGORIES)}).")


def read_reference_v2(path: str | Path, category: str) -> ReferenceAudioV2:
    """Read a reference WAV for ``category`` (see the module docstring)."""
    length_limits_ms(category)  # unknown category first
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ReferenceAudioError(f"Datei nicht lesbar: {path.name} ({exc.strerror or exc}).") \
            from exc
    if size > MAX_FILE_BYTES:
        raise ReferenceAudioError(
            f"Die Datei ist zu groß ({size // (1024 * 1024)} MB); gelesen werden höchstens "
            f"{MAX_FILE_BYTES // (1024 * 1024)} MB.")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReferenceAudioError(f"Datei nicht lesbar: {path.name} ({exc.strerror or exc}).") \
            from exc
    return decode_reference_v2(data, category)


def decode_reference_v2(data: bytes, category: str) -> ReferenceAudioV2:
    lo_ms, hi_ms = length_limits_ms(category)
    fmt, frames = riff_chunks(data)
    tag, channels, sr, _, block, bits = struct.unpack("<HHIIHH", fmt[:16])
    if tag == 0xFFFE and len(fmt) >= 26:
        tag = struct.unpack("<H", fmt[24:26])[0]
    if tag == 1:
        if bits not in PCM_BITS:
            raise ReferenceAudioError(
                f"{bits} Bit PCM wird nicht unterstützt; erlaubt sind 16 oder 24 Bit PCM "
                "oder 32 Bit Float.")
        kind = "pcm"
    elif tag == 3:
        if bits != FLOAT_BITS:
            raise ReferenceAudioError(
                f"{bits} Bit Float wird nicht unterstützt; erlaubt ist 32 Bit Float.")
        kind = "float"
    else:
        raise ReferenceAudioError(
            "Nur unkomprimiertes PCM (16/24 Bit) oder 32-Bit-Float wird gelesen "
            "(keine MP3- oder ADPCM-WAVs).")
    if channels not in (1, 2):
        raise ReferenceAudioError(
            f"{channels} Kanäle werden nicht unterstützt; erlaubt: Mono, Stereo.")
    if sr not in SAMPLE_RATES_V2:
        raise ReferenceAudioError(
            f"Samplerate {sr} Hz wird nicht unterstützt; erlaubt sind 44100, 48000 und "
            "96000 Hz.")
    width = bits // 8
    if block != width * channels:
        raise ReferenceAudioError("Die WAV-Datei hat einen ungültigen fmt-Block (Blockgröße).")
    n = len(frames) // block
    if n / sr > LOOP_MAX_SECONDS:
        raise ReferenceAudioError(
            f"Die Datei ist zu lang ({n / sr:.1f} s); gelesen werden höchstens "
            f"{LOOP_MAX_SECONDS:g} s (bei Loops wird nur der erste Schlag gemessen).")
    raw = frames[: n * block]
    if kind == "float":
        x = np.frombuffer(raw, dtype="<f4").astype(np.float64)
        if not np.all(np.isfinite(x)):
            raise ReferenceAudioError(
                "Die Float-WAV enthält ungültige Werte (NaN oder unendlich).")
    elif bits == 16:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    else:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
        value = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(value >= 1 << 23, value - (1 << 24), value).astype(np.float64) / 2.0**23
    samples = x if channels == 1 else x.reshape(n, 2)
    mid = mid_signal(samples)
    mid0 = mid - np.mean(mid) if n else mid
    peak = float(np.max(np.abs(mid0))) if n else 0.0
    if peak <= 10 ** (SILENCE_DBFS / 20.0):
        raise ReferenceAudioError(
            f"Die Datei ist still (Spitze unter {SILENCE_DBFS:g} dBFS"
            + (", im Mittensignal (L+R)/2" if channels == 2 else "") + ").")
    hits, end = detect_hits(mid0, sr)
    label = CATEGORY_LABEL[category]
    what = "Die Datei" if hits == 1 else "Der erste Schlag der Datei"
    if end > int(round(hi_ms * sr / 1000.0)):
        raise ReferenceAudioError(
            f"{what} ist zu lang ({end / sr:.2f} s); ein {label} ist laut Vertrag höchstens "
            f"{hi_ms / 1000.0:g} s lang.")
    if end < int(round(lo_ms * sr / 1000.0)):
        raise ReferenceAudioError(
            f"{what} ist zu kurz ({end / sr * 1000.0:.0f} ms); ein {label} ist laut Vertrag "
            f"mindestens {lo_ms:g} ms lang.")
    return ReferenceAudioV2(samples, int(sr), int(channels), int(bits), kind, hits, end,
                            censored_tail(mid0[:end], sr, category))


def _moving_rms(x: np.ndarray, win: int) -> np.ndarray:
    win = max(1, win)
    return np.sqrt(np.maximum(np.convolve(x * x, np.full(win, 1.0 / win), mode="same"), 0.0))


def detect_hits(x: np.ndarray, sr: int) -> tuple[int, int]:
    """``(hit_count, first_hit_end)`` of a mono, DC-free signal (module docstring)."""
    n = len(x)
    if n == 0:
        return 0, 0
    hop = max(1, int(round(HIT_HOP_MS * sr / 1000.0)))
    env = _moving_rms(x, int(round(HIT_ENV_MS * sr / 1000.0)))[::hop]
    top = float(np.max(env))
    if top <= 0.0:
        return 0, n
    db = 20.0 * np.log10(np.maximum(env / top, 1e-12))
    look = max(1, int(round(HIT_LOOKBACK_MS / HIT_HOP_MS)))
    gap = int(round(HIT_MIN_GAP_MS / HIT_HOP_MS))
    last = onset_index(x) // hop
    count, end = 1, n
    i = last + gap
    while i < len(db):
        if db[i] >= HIT_LEVEL_DB:
            lo = max(0, i - look)
            k = lo + int(np.argmin(db[lo:i]))
            if db[i] - db[k] >= HIT_RISE_DB:
                if count == 1:
                    end = k * hop
                count += 1
                last = i
                i = last + gap
                continue
        i += 1
    return count, end


def censored_tail(x: np.ndarray, sr: int, category: str = "kick") -> bool:
    """Whether the sound in ``x`` is cut off (module docstring). Kick: the 5 ms RMS envelope
    never falls ``CENSOR_DROP_DB`` under its peak before the last ``CENSOR_GUARD_MS``. Bass:
    the last ``BASS_END_MS`` still reach ``BASS_END_DB`` of the peak (the note has not ended)."""
    if len(x) == 0:
        return True
    x = x - np.mean(x)
    if category == "bass":
        tail = x[-max(1, int(round(BASS_END_MS * sr / 1000.0))):]
        return bool(np.max(np.abs(tail)) > np.max(np.abs(x)) * 10 ** (BASS_END_DB / 20.0))
    env = _moving_rms(x, int(round(CENSOR_ENV_MS * sr / 1000.0)))
    p = int(np.argmax(env))
    limit = len(x) - int(round(CENSOR_GUARD_MS * sr / 1000.0))
    if limit <= p:
        return True
    thr = float(env[p]) * 10 ** (-CENSOR_DROP_DB / 20.0)
    return not bool(np.any(env[p:limit] <= thr))


# --- shared preprocessing ---------------------------------------------------------------------

DB_FLOOR = -80.0
SUB_SPLIT_HZ = 100.0


def prepare_signal(x: np.ndarray) -> np.ndarray:
    """Mid of a mono or ``(n, 2)`` signal, DC removed, cut at the onset, peak-normalised."""
    x = mid_signal(np.asarray(x, dtype=np.float64))
    if len(x):
        x = x - np.mean(x)
    x = x[onset_index(x):]
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    return x / peak if peak > 0.0 else x


def _db(ratio: float) -> float:
    return max(DB_FLOOR, 10.0 * math.log10(ratio)) if ratio > 0.0 else DB_FLOOR


def band_share(x: np.ndarray, sr: int, below_hz: float) -> float | None:
    """Energy share below ``below_hz`` of the whole signal (rectangular window)."""
    power = np.abs(np.fft.rfft(x)) ** 2
    total = float(np.sum(power))
    if total <= 0.0:
        return None
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    return round(float(np.sum(power[freqs < below_hz]) / total), 6)


def _dft_mag(seg: np.ndarray, sr: int, f: float) -> float:
    t = np.arange(len(seg), dtype=np.float64) / sr
    return abs(complex(np.dot(seg, np.exp(-2j * np.pi * f * t))))


# --- kick -------------------------------------------------------------------------------------

PITCH_TIMES_MS = (5.0, 10.0, 20.0, 40.0)
PITCH_PASS_HZ, PITCH_STOP_HZ = 600.0, 800.0
PITCH_MIN_DB = -60.0
# The period must start at least this long after the onset: the zero-phase filter rings
# around the cut at the onset, so the first millisecond of analytic phase is not the sound's.
PITCH_EDGE_MS = 1.0
TAIL_PARTIALS = range(2, 9)
TAIL_MIN_PERIODS = 4
BODY_ZONE_MS = (5.0, 80.0)
BODY_BAND_HZ = (80.0, 300.0)


def analytic_lowpassed(x: np.ndarray, sr: int) -> np.ndarray:
    """Analytic signal of ``x`` through a zero-phase raised-cosine low-pass (600-800 Hz)."""
    n = len(x)
    nfft = 1 << max(1, int(math.ceil(math.log2(2 * n))))
    spec = np.fft.fft(x, nfft)
    f = np.fft.fftfreq(nfft, 1.0 / sr)
    h = np.zeros(nfft)
    pos = f > 0
    taper = np.clip((f - PITCH_PASS_HZ) / (PITCH_STOP_HZ - PITCH_PASS_HZ), 0.0, 1.0)
    h[pos] = 2.0 * 0.5 * (1.0 + np.cos(np.pi * taper[pos]))
    h[0] = 1.0
    return np.fft.ifft(spec * h)[:n]


def pitch_at_ms(x: np.ndarray, sr: int, times_ms=PITCH_TIMES_MS) -> list[float | None]:
    """Instantaneous frequency at ``times_ms`` after the start of a prepared signal."""
    if len(x) < 4:
        return [None] * len(times_ms)
    z = analytic_lowpassed(x, sr)
    mag = np.abs(z)
    top = float(np.max(mag))
    phase = np.unwrap(np.angle(z))
    edge = PITCH_EDGE_MS * sr / 1000.0
    out: list[float | None] = []
    for t in times_ms:
        i = int(round(t * sr / 1000.0))
        if i >= len(x) or top <= 0.0:
            out.append(None)
            continue
        lo = _phase_crossing(phase, i, -np.pi)
        hi = _phase_crossing(phase, i, np.pi)
        if lo is None or hi is None or hi <= lo or lo < edge or float(
                np.min(mag[int(lo):int(math.ceil(hi)) + 1])) < top * 10 ** (PITCH_MIN_DB / 20.0):
            out.append(None)
            continue
        out.append(round(float(sr / (hi - lo)), 3))
    return out


def _phase_crossing(phase: np.ndarray, i: int, offset: float) -> float | None:
    """Fractional sample where the unwrapped phase first reaches ``phase[i] + offset``, going
    backwards for a negative offset and forwards for a positive one; ``None`` outside."""
    target = float(phase[i]) + offset
    if offset < 0:
        idx = np.nonzero(phase[: i + 1] <= target)[0]
        if len(idx) == 0:
            return None
        k = int(idx[-1])  # phase[k] <= target < phase[k + 1]
    else:
        idx = np.nonzero(phase[i:] >= target)[0]
        if len(idx) == 0:
            return None
        k = i + int(idx[0]) - 1  # phase[k] < target <= phase[k + 1]
        if k < 0:
            return None
    step = float(phase[k + 1] - phase[k])
    return k + ((target - float(phase[k])) / step if step != 0 else 0.0)


def tail_harmonics_db(x: np.ndarray, sr: int, f0: float | None) -> float | None:
    """Partials 2-8 over the fundamental in the tail window, dB (module docstring)."""
    if f0 is None or f0 <= 0.0:
        return None
    a, b = tail_window(x, sr)
    periods = int((b - a) * f0 / sr)
    if periods < TAIL_MIN_PERIODS:
        return None
    seg = x[a: a + int(round(periods * sr / f0))]
    seg = seg * np.hanning(len(seg))
    fund = _dft_mag(seg, sr, f0) ** 2
    if fund <= 0.0:
        return None
    harm = sum(_dft_mag(seg, sr, k * f0) ** 2 for k in TAIL_PARTIALS if k * f0 < sr / 2.0)
    return round(_db(harm / fund), 3)


def body_energy_db(x: np.ndarray, sr: int) -> float | None:
    """Energy in 80-300 Hz of the 5-80 ms zone over all energy, dB (module docstring)."""
    a, b = (int(round(ms * sr / 1000.0)) for ms in BODY_ZONE_MS)
    total = float(np.sum(x * x))
    if len(x) < b or total <= 0.0:
        return None
    seg = x[a:b]
    spec = np.abs(np.fft.rfft(seg)) ** 2
    df = sr / len(seg)
    centre = np.arange(len(spec)) * df
    # Each bin counts with the share of [centre - df/2, centre + df/2] inside the band, so a
    # band edge on a bin centre counts half. A plain "freq >= 80" moved the value by 2 dB
    # between 48 and 44.1 kHz (bin 6 is 80.00 Hz at 48 kHz and 79.99 Hz at 44.1 kHz).
    overlap = np.clip(np.minimum(centre + df / 2, BODY_BAND_HZ[1])
                      - np.maximum(centre - df / 2, BODY_BAND_HZ[0]), 0.0, None) / df
    overlap[0] = 0.0
    if len(seg) % 2 == 0:
        overlap[-1] = 0.0
    energy = 2.0 * float(np.sum(spec * overlap)) / len(seg)  # Parseval, one-sided bins
    return round(_db(energy / total), 3)


def kick_features_from_audio(audio: np.ndarray, sr: int) -> dict[str, float | None]:
    """Kick features of a mono or stereo signal (one hit)."""
    mono = mid_signal(np.asarray(audio, dtype=np.float64))
    out: dict[str, float | None] = dict(measure(mono, sr))  # the v1 six, unchanged
    x = prepare_signal(mono)
    for t, v in zip(PITCH_TIMES_MS, pitch_at_ms(x, sr), strict=True):
        out[f"pitch_{t:g}ms_hz"] = v
    out["tail_harmonics_db"] = tail_harmonics_db(x, sr, out["fundamental_hz"])
    out["body_energy_db"] = body_energy_db(x, sr)
    return out


# --- bass -------------------------------------------------------------------------------------

COARSE_ENV_MS = 25.0
STATIONARY = (0.4, 0.8)  # contract rule 6
# Fallback when 40-80 % holds fewer than WINDOW_MIN_PERIODS periods (short rolling notes: a
# 62 ms gate at 65 Hz gives 1.6 periods there and YIN cannot see the period at all).
STATIONARY_WIDE = (0.1, 0.9)
NOTE_BAND_HZ = (12.0, 1000.0)
YIN_THRESHOLD = 0.1
YIN_MAX_DIP = 0.25  # a best dip above this is no period
KNEE_HOP_MS = 1.0
NOTE_MIN_PERIODS = 2
WINDOW_MIN_PERIODS = 4  # below this in 40-80 %, the 10-90 % window is used
# Harmonic levels need an even number of whole periods (a sub-octave is then whole too);
# over whole periods of a periodic note the rectangular DFT is exact, so 2 suffice.
HARM_MIN_PERIODS = 2
# An absent partial reads as cut residue: -63 dB at 48 kHz and the -80 dB floor at 44.1 kHz on
# the `sub` preset (no partial at 3x its period), a 17 dB "method error" between two zeros.
HARM_FLOOR_DB = -60.0
EARLY_MS = 30.0
RELEASE_DB = -40.0


def forward_max(x: np.ndarray, win: int) -> np.ndarray:
    """``max |x[i : i + win]|`` for every i (the window is cut at the end)."""
    a = np.abs(x)
    win = max(1, min(win, len(a)))
    padded = np.concatenate([a, np.zeros(win - 1)])
    return np.lib.stride_tricks.sliding_window_view(padded, win).max(axis=1)


def period_hz(seg: np.ndarray, sr: int) -> float | None:
    """Frequency of the waveform period of a stationary segment (YIN, de Cheveigné and
    Kawahara 2002): cumulative-mean-normalised difference function over lags for
    :data:`NOTE_BAND_HZ`, first lag under :data:`YIN_THRESHOLD` (then its local minimum),
    else the global minimum; parabolic interpolation of the dip. The lag range is cut so
    the compared windows hold at least half the segment. ``None`` without a usable dip."""
    seg = np.asarray(seg, dtype=np.float64)
    seg = seg - np.mean(seg) if len(seg) else seg
    n = len(seg)
    tau_min = max(2, int(math.floor(sr / NOTE_BAND_HZ[1])))
    tau_max = min(int(math.ceil(sr / NOTE_BAND_HZ[0])), n // 2)
    if tau_max <= tau_min + 2 or not np.any(seg):
        return None
    w = n - tau_max
    head = seg[:w]
    nfft = 1 << int(math.ceil(math.log2(n + w)))
    cross = np.fft.irfft(np.fft.rfft(seg, nfft) * np.conj(np.fft.rfft(head, nfft)), nfft)
    sq = np.concatenate([[0.0], np.cumsum(seg * seg)])
    taus = np.arange(0, tau_max + 1)
    energy_shift = sq[taus + w] - sq[taus]
    d = float(sq[w]) + energy_shift - 2.0 * cross[: tau_max + 1]
    d[0] = 0.0
    csum = np.cumsum(d[1:])
    dn = np.ones(tau_max + 1)
    dn[1:] = np.where(csum > 0, d[1:] * taus[1:] / np.maximum(csum, 1e-300), 1.0)
    rng = np.arange(tau_min, tau_max)
    below = rng[dn[rng] < YIN_THRESHOLD]
    if len(below):
        k = int(below[0])
        while k + 1 < tau_max and dn[k + 1] < dn[k]:
            k += 1
    else:
        k = int(rng[np.argmin(dn[rng])])
    if not (tau_min < k < tau_max) or dn[k] >= YIN_MAX_DIP:
        return None
    a, b, c = dn[k - 1], dn[k], dn[k + 1]
    denom = a - 2.0 * b + c
    shift = 0.5 * (a - c) / denom if denom > 0 else 0.0
    return sr / (k + shift)


def _line_sse(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Least-squares line SSE of every prefix ``[0, k]`` of (t, y), k = 0 .. n-1."""
    n = np.arange(1, len(t) + 1, dtype=np.float64)
    s1, s2 = np.cumsum(t), np.cumsum(t * t)
    sy, sty, syy = np.cumsum(y), np.cumsum(t * y), np.cumsum(y * y)
    vt = s2 - s1 * s1 / n
    cov = sty - s1 * sy / n
    vy = syy - sy * sy / n
    with np.errstate(divide="ignore", invalid="ignore"):
        sse = vy - np.where(vt > 0, cov * cov / vt, 0.0)
    return np.maximum(sse, 0.0)


def knee_gate(x: np.ndarray, sr: int, win: int) -> int | None:
    """Gate end (samples) as the break point of a two-line least-squares fit of the forward
    max-envelope (window ``win``, 1 ms frames) from its first frame at 90 % of the peak to its
    last frame at -40 dB. A held note with a linear release gives the gate exactly; a hold
    whose level falls (filter envelope) or a driven, bent release moves it (calibrated in E3).
    ``None`` when that range holds fewer than 6 frames."""
    hop = max(1, int(round(KNEE_HOP_MS * sr / 1000.0)))
    e = forward_max(x, win)[::hop]
    top = float(np.max(e)) if len(e) else 0.0
    if top <= 0.0:
        return None
    start = int(np.argmax(e >= 0.9 * top))
    end = int(np.nonzero(e >= 0.01 * top)[0][-1])
    y = e[start: end + 1]
    if len(y) < 6:
        return None
    t = np.arange(len(y), dtype=np.float64)
    pre = _line_sse(t, y)
    # suffix [k, n-1]: a line through (n-1, 0), the end of the release
    u = (len(y) - 1) - t
    suy, suu, syy = (np.cumsum(v[::-1])[::-1] for v in (u * y, u * u, y * y))
    post = np.maximum(syy - np.where(suu > 0, suy * suy / np.maximum(suu, 1e-300), 0.0), 0.0)
    cost = pre[2:-2] + post[2:-2]
    g = 2 + int(np.argmin(cost))
    return (start + g) * hop


def _window(gate: int, frac: tuple[float, float]) -> tuple[int, int]:
    return int(round(frac[0] * gate)), int(round(frac[1] * gate))


def stationary(x: np.ndarray, gate: int, sr: int) -> tuple[int, int, float | None]:
    """``(a, b, period_hz)``: 40-80 % of the gate, or 10-90 % when that holds fewer than
    :data:`WINDOW_MIN_PERIODS` periods or no period (module docstring)."""
    a, b = _window(gate, STATIONARY)
    f = period_hz(x[a:b], sr) if b - a >= 16 else None
    if f is not None and (b - a) * f / sr >= WINDOW_MIN_PERIODS:
        return a, b, f
    a2, b2 = _window(gate, STATIONARY_WIDE)
    f2 = period_hz(x[a2:b2], sr) if b2 - a2 >= 16 else None
    if f2 is not None:
        return a2, b2, f2
    return a, b, f


def _centroid(seg: np.ndarray, sr: int) -> float | None:
    power = np.abs(np.fft.rfft(seg)) ** 2
    freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
    total = float(np.sum(power[1:]))
    if total <= 0.0:
        return None
    return float(np.sum(freqs[1:] * power[1:]) / total)


def _whole_periods(seg: np.ndarray, sr: int, f: float, even: bool = False) \
        -> tuple[np.ndarray | None, int]:
    """``(cut, periods)``: ``seg`` cut to a whole (even) number of periods of ``f``. The
    count is returned as an integer: re-deriving it from the rounded cut length gave 3.9996
    for an exact 4-period cut and dropped the harmonics (review of PR #541, P1)."""
    periods = int(len(seg) * f / sr)
    if even:
        periods -= periods % 2
    if periods < 1:
        return None, 0
    return seg[: min(len(seg), int(round(periods * sr / f)))], periods


def bass_features_from_audio(audio: np.ndarray, sr: int) -> dict[str, float | None]:
    """Bass features of a mono or stereo signal (one note; module docstring)."""
    x = prepare_signal(audio)
    out: dict[str, float | None] = dict.fromkeys(BASS_FEATURES)
    if len(x) < 16 or not np.any(x):
        return out
    out["sub_share"] = band_share(x, sr, SUB_SPLIT_HZ)
    # 1. coarse gate: knee of a 25 ms forward max-envelope
    gate = knee_gate(x, sr, int(round(COARSE_ENV_MS * sr / 1000.0)))
    if gate is None:
        return out
    a, b, low = stationary(x, gate, sr)
    if low is None:
        return out
    # 2. a period longer than 25 ms ripples that envelope: repeat over one period
    period = int(round(sr / low))
    if period > int(round(COARSE_ENV_MS * sr / 1000.0)):
        gate = knee_gate(x, sr, period)
        if gate is None:
            return out
        a, b, _ = stationary(x, gate, sr)
        if b - a < 16:
            return out
    out["gate_ms"] = round(gate / sr * 1000.0, 3)
    level = float(np.max(np.abs(x[a:b])))
    loud = np.nonzero(np.abs(x) >= level * 10 ** (RELEASE_DB / 20.0))[0]
    out["release_ms"] = round((int(loud[-1]) - gate) / sr * 1000.0, 3) \
        if len(loud) and loud[-1] > gate else None
    # attack: 10 % to 90 % of the stationary level on the running max so far
    run = np.maximum.accumulate(np.abs(x))
    i10 = np.nonzero(run >= 0.1 * level)[0]
    i90 = np.nonzero(run >= 0.9 * level)[0]
    if len(i10) and len(i90):
        out["attack_ms"] = round(max(int(i90[0]) - int(i10[0]), 1) / sr * 1000.0, 3)
    # 3. note and spectrum in the stationary window
    note = period_hz(x[a:b], sr)
    if note is None or (b - a) * note / sr < NOTE_MIN_PERIODS:
        return out
    out["note_hz"] = round(float(note), 3)
    seg = x[a:b]
    whole, periods = _whole_periods(seg, sr, note, even=True)
    if whole is not None and periods >= HARM_MIN_PERIODS:
        fund = _dft_mag(whole, sr, note) ** 2
        if fund > 0.0:
            for k in (2, 3):
                key = f"harm{k}_db"
                out[key] = round(max(HARM_FLOOR_DB,
                                     _db(_dft_mag(whole, sr, k * note) ** 2 / fund)), 3) \
                    if k * note < sr / 2.0 else None
    stat, _ = _whole_periods(seg, sr, note)
    cen = _centroid(stat, sr) if stat is not None else None
    out["centroid_hz"] = round(cen, 3) if cen is not None else None
    early_n = int(round(EARLY_MS * sr / 1000.0))
    if cen is not None and EARLY_MS / 1000.0 * note >= NOTE_MIN_PERIODS and len(x) >= early_n:
        early = _centroid(x[:early_n], sr)
        if early is not None and early > 0.0:
            out["filter_move_db"] = round(20.0 * math.log10(early / cen), 3)
    return out


# --- feature tables and distance --------------------------------------------------------------

MISSING_DISTANCE = 3.0
LN125, LN13, LN11 = math.log(1.25), math.log(1.3), math.log(1.1)

# name -> (transform, provisional scale) from the note's section 3 tables.
FEATURES: dict[str, dict[str, tuple[str, float]]] = {
    "kick": {
        "fundamental_hz": ("semitone", 1.0),
        "body_hz": ("semitone", 2.0),
        "pitch_5ms_hz": ("semitone", 1.0),
        "pitch_10ms_hz": ("semitone", 1.0),
        "pitch_20ms_hz": ("semitone", 1.0),
        "pitch_40ms_hz": ("semitone", 1.0),
        "decay_20db_ms": ("log", LN125),
        "decay_40db_ms": ("log", LN125),
        "sub_share": ("lin", 0.05),
        "click_share": ("lin", 0.05),
        "tail_harmonics_db": ("db", 3.0),
        "body_energy_db": ("db", 1.5),
    },
    "bass": {
        "note_hz": ("semitone", 0.1),
        "harm2_db": ("db", 1.5),
        "harm3_db": ("db", 1.5),
        "sub_share": ("lin", 0.05),
        "centroid_hz": ("semitone", 1.0),
        "filter_move_db": ("db", 1.0),
        "attack_ms": ("log", LN13),
        "gate_ms": ("log", LN11),
        "release_ms": ("log", LN11),
    },
}
BASS_FEATURES = tuple(FEATURES["bass"])
KICK_FEATURES = tuple(FEATURES["kick"])

FEATURE_FUNCTIONS = {"kick": kick_features_from_audio, "bass": bass_features_from_audio}


def features_from_audio(category: str, audio: np.ndarray, sr: int) -> dict[str, float | None]:
    if category not in FEATURE_FUNCTIONS:
        length_limits_ms(category)  # raises the German error
    return FEATURE_FUNCTIONS[category](audio, sr)


def reference_features(ref: ReferenceAudioV2, category: str) -> dict[str, float | None]:
    """Features of the first hit of a reference."""
    return features_from_audio(category, ref.first_hit, ref.sample_rate)


def transform(kind: str, value: float) -> float:
    if kind == "semitone":
        return 12.0 * math.log2(max(value, 1e-9))
    if kind == "log":
        return math.log(max(value, 1e-9))
    return float(value)


CALIBRATION_FILE = Path(__file__).resolve().parent / "calibration" / "reference_scales.json"
WEIGHT_ZERO_RATIO = 1.0 / 3.0


def weight_for(seed_spread: float, between_spread: float) -> float:
    """Rule 2.4 (a): weight 0 when the mean seed spread is at least one third of the
    between-candidate spread (both in transformed units), else 1."""
    return 0.0 if seed_spread >= between_spread * WEIGHT_ZERO_RATIO else 1.0


@dataclass(frozen=True)
class FeatureScale:
    transform: str
    scale: float
    weight: float
    provisional: bool


@functools.cache
def load_calibration(path: Path = CALIBRATION_FILE) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def feature_table(category: str, calibration: dict[str, Any] | None = None) \
        -> dict[str, FeatureScale]:
    """Transform, scale and weight per feature: calibrated where the table has the feature."""
    cal = load_calibration() if calibration is None else calibration
    rows = cal.get("categories", {}).get(category, {}).get("features", {})
    out = {}
    for name, (kind, provisional) in FEATURES[category].items():
        row = rows.get(name)
        if row is None:
            out[name] = FeatureScale(kind, provisional, 1.0, True)
        else:
            out[name] = FeatureScale(kind, float(row["scale"]), float(row["weight"]), False)
    return out


def feature_distances(category: str, a: dict[str, float | None], b: dict[str, float | None],
                      table: dict[str, FeatureScale] | None = None) -> dict[str, float]:
    """Unweighted distance per feature (module docstring)."""
    table = feature_table(category) if table is None else table
    out = {}
    for name, fs in table.items():
        va, vb = a.get(name), b.get(name)
        if va is None and vb is None:
            out[name] = 0.0
        elif va is None or vb is None:
            out[name] = MISSING_DISTANCE
        else:
            out[name] = abs(transform(fs.transform, va) - transform(fs.transform, vb)) / fs.scale
    return out


def total_distance(category: str, per_feature: dict[str, float],
                   table: dict[str, FeatureScale] | None = None) -> float:
    """Root of the weighted mean square over features with weight > 0."""
    table = feature_table(category) if table is None else table
    wsum = sum(fs.weight for fs in table.values())
    if wsum <= 0.0:
        return 0.0
    return math.sqrt(sum(fs.weight * per_feature[n] ** 2 for n, fs in table.items()) / wsum)
