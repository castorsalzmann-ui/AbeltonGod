"""Package for listening test 3 (issue #103): six blocks, blind-named 4-bar loops.

    python -m audio_engine.listening_test3 --out DIR

Plan and parameters: ``docs/research/2026-11-02_listening-test-3-plan.md`` (blocks, gains) and
the lead's package decision on #103. Writes, into a new folder ``DIR``:

- ``DIR/package/K<n>_<A|B|C|D>.wav`` and ``DIR/package/Schluessel.md`` (what is sent);
- ``DIR/sidecars/K5_v<i>.{wav,json}`` (the four K5 kicks as single hits with their sidecars,
  seeds included; kept out of the package because the names would give the key away).

Every loop is 4 bars (16 beats) of one hit per beat at 136 BPM, mono 48 kHz / 24 bit; each
hit is cut at the next beat with a 3 ms raised-cosine fade. The gain of each file is fixed
in :data:`BLOCKS` (RMS match over 0-100 ms after the onset, measured in the plan). The A/B/C/D
positions are drawn from :data:`BLIND_SEED` with SHA-256 (no RNG state, no clock), so the same
code gives byte-identical files and key. Only the sidecars carry ``created_at``, fixed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .dsp import raised_cosine
from .io import encode_wav, wav_samples, write_kick
from .kick import _normalise, render_kick
from .presets import load_preset
from .variants import make_variants

BPM = 136
BARS = 4
SAMPLE_RATE = 48000
BIT_DEPTH = 24
CEILING_DBFS = -0.3
CUT_FADE_MS = 3.0
BLIND_SEED = 103
SIDECAR_CREATED_AT = datetime(2026, 11, 2, tzinfo=UTC)

Item = tuple[str, Callable[[], np.ndarray], float]  # (true name, single hit, gain in dB)


def _dense(**changes: Any) -> np.ndarray:
    params = dict(load_preset("dense"))
    params.update(changes)
    return render_kick(params)[0]


def _v03(**changes: Any) -> np.ndarray:
    params = dict(load_preset("dense"))
    if "length_beats" in changes:
        # length_beats sets length_ms itself and the engine derives amp_decay_ms (380.6)
        del params["length_ms"], params["amp_decay_ms"]
    params.update(schema_version="0.3", **changes)
    return render_kick(params)[0]


def _layered() -> np.ndarray:
    """K3 B: dense plus a second kick at -6 dB, summed, normalised to the ceiling."""
    second = _dense(
        pitch_start_hz=500, pitch_end_hz=110, pitch_decay_ms=6, amp_decay_ms=110,
        length_ms=150, click_level=0.6, click_tone_hz=4000, drive=0.2,
    )
    main = _dense()
    total = main.copy()
    total[: len(second)] += second * 10.0 ** (-6.0 / 20.0)
    return _normalise(total, CEILING_DBFS, BIT_DEPTH)


def _variant(index: int) -> np.ndarray:
    return render_kick(make_variants(load_preset("dense"), 4)[index])[0]


# Block order is the listening order. Gains in dB from the plan (RMS match over 0-100 ms).
BLOCKS: dict[str, list[Item]] = {
    "K2": [("dense", _dense, 0.0), ("clip_db 3", lambda: _v03(clip_db=3), -1.23)],
    "K0": [("dense", _dense, 0.0), ("dense (same file)", _dense, 0.0)],
    "K3": [("dense", _dense, -2.35), ("dense + layer -6 dB", _layered, 0.0)],
    "K1": [
        ("drive 0.30", lambda: _dense(drive=0.30), 0.0),
        ("drive 0.45 (dense)", _dense, -0.51),
        ("drive 0.60", lambda: _dense(drive=0.60), -0.78),
    ],
    "K4": [
        ("dense", _dense, -0.69),
        ("bpm 136, length_beats 1, pitch_decay_ms 28",
         lambda: _v03(bpm=136, length_beats=1, pitch_decay_ms=28), 0.0),
    ],
    "K5": [
        ("variant v0 (dense)", lambda: _variant(0), -0.41),
        ("variant v1", lambda: _variant(1), -0.38),
        ("variant v2", lambda: _variant(2), 0.0),
        ("variant v3", lambda: _variant(3), -0.26),
    ],
}


def blind_order(block: str, n: int, seed: int = BLIND_SEED) -> list[int]:
    """Position (0 = A) of each of the ``n`` items: sort by SHA-256 of seed, block, index."""
    def digest(i: int) -> str:
        return hashlib.sha256(f"{seed}:{block}:{i}".encode()).hexdigest()

    ranked = sorted(range(n), key=digest)
    return [ranked.index(i) for i in range(n)]


def loop_samples() -> tuple[int, list[int]]:
    """Total loop length and the start sample of each of the 16 hits."""
    beat = 60.0 / BPM * SAMPLE_RATE
    n_beats = BARS * 4
    return round(n_beats * beat), [round(i * beat) for i in range(n_beats)]


def build_loop(hit: np.ndarray, gain_db: float) -> np.ndarray:
    """One hit per beat, each cut at the next beat with a 3 ms cosine fade, times the gain."""
    total, starts = loop_samples()
    out = np.zeros(total)
    gain = 10.0 ** (gain_db / 20.0)
    fade = round(CUT_FADE_MS / 1000.0 * SAMPLE_RATE)
    for start, end in zip(starts, [*starts[1:], total], strict=True):
        seg = np.zeros(end - start)
        used = min(len(hit), len(seg))
        seg[:used] = hit[:used]
        seg[-fade:] *= raised_cosine(fade, rising=False)
        out[start:end] = seg * gain
    return out


def onset_rms_db(ints: np.ndarray) -> float:
    """RMS (dB re full scale) over 100 ms from the first sample at 10 % of the peak."""
    x = ints / float(2 ** (BIT_DEPTH - 1))
    onset = int(np.argmax(np.abs(x) >= 0.1 * np.max(np.abs(x))))
    window = x[onset : onset + round(0.1 * SAMPLE_RATE)]
    return 20.0 * math.log10(math.sqrt(float(np.mean(window**2))))


def peak_dbfs(ints: np.ndarray) -> float:
    return 20.0 * math.log10(float(np.max(np.abs(ints))) / float(2 ** (BIT_DEPTH - 1) - 1))


@dataclass
class Rendered:
    block: str
    label: str  # "A" ... "D"
    name: str  # true identity, for the key
    gain_db: float
    wav: bytes


def render_package() -> list[Rendered]:
    out: list[Rendered] = []
    for block, items in BLOCKS.items():
        position = blind_order(block, len(items))
        for i, (name, make, gain_db) in enumerate(items):
            wav = encode_wav(build_loop(make(), gain_db), SAMPLE_RATE, BIT_DEPTH)
            out.append(Rendered(block, "ABCD"[position[i]], name, gain_db, wav))
    return sorted(out, key=lambda r: (r.block, r.label))


def measure(files: list[Rendered]) -> dict[str, Any]:
    """Checks on the written bytes: peak, RMS-match spread per block, K0 identity."""
    peaks = {f"{r.block}_{r.label}": peak_dbfs(wav_samples(r.wav)) for r in files}
    spread = {}
    for block in BLOCKS:
        levels = [onset_rms_db(wav_samples(r.wav)) for r in files if r.block == block]
        spread[block] = (max(levels) - min(levels)) if len(levels) > 1 else 0.0
    k0 = [r.wav for r in files if r.block == "K0"]
    return {"peak_dbfs": peaks, "rms_spread_db": spread, "k0_identical": k0[0] == k0[1]}


def key_text(files: list[Rendered], report: dict[str, Any]) -> str:
    lines = [
        "# Schluessel Hoertest 3",
        "",
        "Erst nach dem Test oeffnen. Aufbau: 4 Takte, 136 BPM, ein Schlag pro Beat, mono, 48 kHz, "
        f"24 bit. Reihenfolge A/B/C/D mit festem Seed ({BLIND_SEED}) gemischt.",
        "",
        "| Datei | Inhalt | Gain (RMS-Angleich) | Spitze dBFS | RMS 0-100 ms dBFS |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in files:
        ints = wav_samples(r.wav)
        lines.append(
            f"| `{r.block}_{r.label}.wav` | {r.name} | {r.gain_db:+.2f} dB "
            f"| {peak_dbfs(ints):.2f} | {onset_rms_db(ints):.2f} |"
        )
    lines += ["", "RMS-Unterschied innerhalb eines Blocks (dB): " + ", ".join(
        f"{b} {v:.3f}" for b, v in report["rms_spread_db"].items()), ""]
    return "\n".join(lines)


def write_package(out: str | Path) -> dict[str, Any]:
    root = Path(out)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"{root} is not empty; choose a new folder")
    package = root / "package"
    package.mkdir(parents=True, exist_ok=True)
    files = render_package()
    report = measure(files)
    for r in files:
        (package / f"{r.block}_{r.label}.wav").write_bytes(r.wav)
    (package / "Schluessel.md").write_text(key_text(files, report), encoding="utf-8")
    sidecars = root / "sidecars"
    for i, params in enumerate(make_variants(load_preset("dense"), 4)):
        write_kick(params, sidecars, f"K5_v{i}", created_at=SIDECAR_CREATED_AT)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the listening test 3 package.")
    parser.add_argument("--out", required=True, help="new, empty folder outside the repo")
    args = parser.parse_args(argv)
    report = write_package(args.out)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
