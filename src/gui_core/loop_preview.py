"""Loop preview (#553): a one-shot sample repeated on a 4/4 grid at a tempo. No Qt.

"Im Takt abspielen" renders a short deterministic loop (1 or 2 bars), optionally with a kick
on every quarter, and the shell plays it looping through the backend (at the output volume,
#545) until Stopp. The loop is a temp file for listening only, never written to the library.

Grid: a bar has 16 sixteenths; sixteenth ``k`` starts at sample ``round(k * 15 * sr / bpm)``
(15 = 60 s / 4 sixteenths per beat), computed with exact fractions so a hit never drifts. A
hit is the sample from its start to the loop end (overlapping hits are summed); the last
:data:`FADE_MS` of the loop fade to zero so the cut tail does not click at the loop point. If
the sum peaks above :data:`CEILING`, the whole loop is turned down to it (one static gain: no
clipping, no pumping). Loops (atmos) play as they are.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path

import numpy as np

from audio_engine.io import encode_wav

PATTERNS: dict[str, tuple[int, ...]] = {  # sixteenths of one bar that get a hit
    "Viertel": (0, 4, 8, 12),
    "Offbeat-Achtel": (2, 6, 10, 14),
    "2 und 4": (4, 12),
    "Achtel": (0, 2, 4, 6, 8, 10, 12, 14),
    "Sechzehntel": tuple(range(16)),
    "einmal pro Takt": (0,),
}
AS_IS = "als Loop (wie die Datei)"  # atmos: the file is already a loop
CATEGORY_PATTERN: dict[str, str] = {
    "kick": "Viertel", "clap": "2 und 4", "snare": "2 und 4", "hat": "Offbeat-Achtel",
    "rim": "Achtel", "perc": "Achtel", "bass": "Offbeat-Achtel", "laser": "einmal pro Takt",
    "fx": "einmal pro Takt", "atmos": AS_IS,
}
FALLBACK_PATTERN = "einmal pro Takt"
PATTERN_CHOICES: tuple[str, ...] = (*PATTERNS, AS_IS)
DEFAULT_BPM = 140
BPM_MIN, BPM_MAX = 60, 200
BARS_CHOICES = (1, 2)
FADE_MS = 5.0
CEILING = 0.89  # -1 dBFS
MAX_LOOP_S = 60.0  # an as-is loop longer than this is cut (a preview, not the file)
LOOP_RESTART_MS = 250  # a running loop restarts this long after the volume slider rests


class LoopError(ValueError):
    """German text for the user."""


def step_start(step: int, bpm: float, sr: int) -> int:
    """First sample of sixteenth ``step`` (counted from the loop start), exact rounding
    (half up) of ``step * 15 * sr / bpm``."""
    x = Fraction(step * 15 * sr) / Fraction(bpm)
    return int((x + Fraction(1, 2)).__floor__())


def loop_samples(bpm: float, sr: int, bars: int) -> int:
    """Loop length in samples: ``bars`` x 4 beats."""
    return step_start(16 * bars, bpm, sr)


def hit_positions(pattern: str, bpm: float, sr: int, bars: int = 1) -> list[int]:
    steps = PATTERNS[pattern]
    return [step_start(16 * b + s, bpm, sr) for b in range(bars) for s in steps]


def _check(bpm: float, bars: int) -> None:
    if not BPM_MIN <= bpm <= BPM_MAX:
        raise LoopError(f"Tempo muss zwischen {BPM_MIN} und {BPM_MAX} BPM liegen.")
    if bars not in BARS_CHOICES:
        raise LoopError("Ein oder zwei Takte.")


def _stereo(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        return np.stack([x, x], axis=1)
    if x.ndim == 2 and x.shape[1] == 2:
        return x
    raise LoopError("Nur Mono- oder Stereo-Samples.")


def _finish(out: np.ndarray, sr: int) -> np.ndarray:
    fade = min(len(out), max(1, int(round(FADE_MS * sr / 1000.0))))
    if fade:
        out[len(out) - fade:] *= np.linspace(1.0, 0.0, fade)[:, None]
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > CEILING:
        out *= CEILING / peak
    return out


def render_loop(sample: np.ndarray, sr: int, bpm: float, pattern: str, bars: int = 1,
                kick: np.ndarray | None = None) -> np.ndarray:
    """Stereo float loop ``(loop_samples, 2)``. ``kick`` (same rate) adds a kick on every
    quarter. ``pattern`` :data:`AS_IS` returns the sample itself (kick ignored)."""
    if pattern == AS_IS:
        x = _stereo(sample)[: int(MAX_LOOP_S * sr)].copy()
        if not len(x):
            raise LoopError("Die Datei ist leer.")
        return _finish(x, sr)
    if pattern not in PATTERNS:
        raise LoopError(f"Unbekanntes Muster: {pattern}")
    _check(bpm, bars)
    n = loop_samples(bpm, sr, bars)
    out = np.zeros((n, 2))
    layers = [(_stereo(sample), hit_positions(pattern, bpm, sr, bars))]
    if kick is not None:
        layers.append((_stereo(kick), hit_positions("Viertel", bpm, sr, bars)))
    for x, starts in layers:
        for p in starts:
            m = min(len(x), n - p)
            if m > 0:
                out[p:p + m] += x[:m]
    return _finish(out, sr)


def loop_wav_bytes(sample: np.ndarray, sr: int, bpm: float, pattern: str, bars: int = 1,
                   kick: np.ndarray | None = None) -> bytes:
    """The loop as a 16-bit stereo WAV (what the backend plays)."""
    return encode_wav(render_loop(sample, sr, bpm, pattern, bars, kick), sr, 16)


def read_frames(wav_path: str | Path) -> tuple[np.ndarray, int]:
    """Samples of a PCM WAV (16 or 24 bit, mono ``(n,)`` or stereo ``(n, 2)``, full scale
    1.0) and its rate, channels kept (the main preview's waveform is the mid; a loop of an
    atmos bed keeps its stereo image, review of #559). Raises ``LoopError``."""
    try:
        data = Path(wav_path).read_bytes()
    except OSError as exc:
        raise LoopError(f"Datei nicht lesbar: {exc}") from exc
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise LoopError("Keine WAV-Datei.")
    pos, fmt = 12, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = (int.from_bytes(body[0:2], "little"), int.from_bytes(body[2:4], "little"),
                   int.from_bytes(body[4:8], "little"), int.from_bytes(body[14:16], "little"))
        elif cid == b"data" and fmt is not None:
            tag, ch, sr, bits = fmt
            if tag != 1 or ch not in (1, 2) or bits not in (16, 24):
                raise LoopError(f"Nur PCM 16/24 Bit, mono oder stereo ({bits} Bit, {ch} Kanäle).")
            width = bits // 8
            body = body[: len(body) - len(body) % (width * ch)]
            if bits == 16:
                ints = np.frombuffer(body, dtype="<i2").astype(np.int64)
            else:
                raw = np.frombuffer(body, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
                v = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
                ints = np.where(v >= 1 << 23, v - (1 << 24), v)
            x = ints / float(2 ** (bits - 1))
            return (x.reshape(-1, 2) if ch == 2 else x), sr
        pos += 8 + size + (size & 1)
    raise LoopError("WAV ohne Daten.")


def category_of(wav_path: str | Path) -> str | None:
    """The category of an engine WAV from its sidecar (no ``category`` = kick, the first
    format), else from the file name prefix (``hat_...``); ``None`` if neither says."""
    p = Path(wav_path)
    try:
        meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
        if isinstance(meta, Mapping):
            cat = meta.get("category", "kick")
            if isinstance(cat, str) and cat:
                return cat
    except (OSError, ValueError):
        pass
    prefix = p.stem.split("_", 1)[0].lower()
    return prefix if prefix in CATEGORY_PATTERN else None


def default_pattern(category: str | None) -> str:
    return CATEGORY_PATTERN.get(category or "", FALLBACK_PATTERN)


def default_kick(sr: int) -> np.ndarray:
    """The kick for "mit Kick": the default kick preset of the main window's form, rendered
    in memory at ``sr`` (deterministic)."""
    from audio_engine.categories import get_category

    from .form import CategoryFormModel

    cat = get_category("kick")
    req = CategoryFormModel("kick").build_request()
    req["sample_rate"] = sr if sr in (44100, 48000) else req.get("sample_rate", 48000)
    audio, resolved = cat.render(cat.resolve(req))
    if int(resolved["sample_rate"]) != sr:
        raise LoopError(f"Kick nur mit 44100 oder 48000 Hz (Sample: {sr} Hz).")
    return np.asarray(audio, dtype=np.float64)
