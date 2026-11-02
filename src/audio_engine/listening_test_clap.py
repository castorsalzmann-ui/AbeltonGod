"""Package for the clap listening test (issue #232): seven items, 18 blind-named loops.

    python -m audio_engine.listening_test_clap --out DIR


values: the revised starter set S ("short") of
``docs/research/2026-11-02_clap-reference-analysis.md`` section 5.2 replaces the plan's
"tight techno" T; L ("long") replaces "long trance". Writes into a new folder ``DIR``:

- ``DIR/package/C<n>_<A|B|C|D>.wav`` and ``DIR/package/Schluessel.md`` (what is sent).

Every loop is 4 bars at 136 BPM, mono 48 kHz / 24 bit: the ``dense`` kick on every beat
(as in test 3) and the clap on beats 2 and 4. Each clap is cut at the next beat with a 3 ms
raised-cosine fade (L at 2 beats, so it may ring until the next clap). Level match inside an
item: RMS over the first 60 ms of the clap alone; every file is scaled down to the quietest
of its item (the gains are in the key). The A/B/C/D positions come from SHA-256 of a fixed
seed (no RNG state, no clock): same code, byte-identical files and key.

Deviations from the plan, all forced by S having 4 bursts and 10 ms spacing, not 3 and 8:
C2 compares ``bursts`` 1 / 4 / 6 (4 = T); C3 compares ``bp_hz`` 800 / 1200 / 2000 (1200 = T).
The C5 wide layer uses seed 2 (a second noise stream) and the layered-column values of plan
section 2 for the fields the plan does not name.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import listening_test3 as lt3
from .clap import render_clap
from .clap_variants import make_variants
from .dsp import raised_cosine
from .io import encode_wav, wav_samples
from .kick import _normalise
from .presets import load_preset

BPM = lt3.BPM
SAMPLE_RATE = lt3.SAMPLE_RATE
BIT_DEPTH = lt3.BIT_DEPTH
CEILING_DBFS = lt3.CEILING_DBFS
CUT_FADE_MS = lt3.CUT_FADE_MS
BLIND_SEED = 232
MATCH_MS = 60.0
KICK_BUS_DB = -6.0
CLAP_BUS_DB = -11.0  # 5 dB under the kick bus; kick peak + clap peak stay under -2 dBFS
LAYER_DB = -6.0


def _clap(preset: str = "short", **changes: Any) -> np.ndarray:
    params = dict(load_preset(preset, "clap"))
    params.update({"seed": 1, **changes})
    return render_clap(params)[0]


def _layered() -> np.ndarray:
    """C5 B: T plus a wide clap at -6 dB, summed, normalised to the ceiling."""
    wide = _clap(
        seed=2, bursts=6, burst_spacing_ms=14, burst_decay_ms=30, burst_level_falloff=0.95,
        tail_level=0.6, tail_decay_ms=250, bp_hz=1200, bp_q=1.0, hp_hz=400, length_ms=700,
    )
    tight = _clap()
    total = np.zeros(max(len(tight), len(wide)))
    total[: len(tight)] += tight
    total[: len(wide)] += wide * 10.0 ** (LAYER_DB / 20.0)
    return _normalise(total, CEILING_DBFS, BIT_DEPTH)


def _variant(index: int) -> np.ndarray:
    base = dict(load_preset("short", "clap"))
    base["seed"] = 1
    return render_clap(make_variants(base, 4)[index])[0]


# Unique renders, by id. The name column of the key says what each one is.
RENDERS: dict[str, tuple[str, Any, int]] = {
    # id: (description, maker, cut in beats)
    "T": ("T = preset short (S), seed 1", _clap, 1),
    "L": ("preset long (L), seed 1", lambda: _clap("long"), 2),
    "b1": ("T with bursts 1", lambda: _clap(bursts=1), 1),
    "b6": ("T with bursts 6", lambda: _clap(bursts=6), 1),
    "bp800": ("T with bp_hz 800", lambda: _clap(bp_hz=800), 1),
    "bp2000": ("T with bp_hz 2000", lambda: _clap(bp_hz=2000), 1),
    "room": ("T with room 0.4, room_length_ms 300", lambda: _clap(room=0.4, room_length_ms=300), 1),
    "sum": ("T + wide clap (6 / 14 / 30 / 0.95, bp_hz 1200) at -6 dB, summed", _layered, 1),
    "v1": ("variant 1 of T (variants 4)", lambda: _variant(1), 1),
    "v2": ("variant 2 of T (variants 4)", lambda: _variant(2), 1),
    "v3": ("variant 3 of T (variants 4)", lambda: _variant(3), 1),
}

# Listening order. Each item: the render id of every file, in definition order (not blind).
ITEMS: dict[str, list[str]] = {
    "C1": ["T", "L"],
    "C0": ["T", "T"],
    "C4": ["T", "room"],
    "C5": ["T", "sum"],
    "C3": ["bp800", "T", "bp2000"],
    "C2": ["b1", "T", "b6"],
    "C6": ["T", "v1", "v2", "v3"],  # v0 of `variants 4` is the preset itself = T
}


def clap_loop(hit: np.ndarray, cut_beats: int) -> np.ndarray:
    """Clap on beats 2 and 4 of each bar, each cut after ``cut_beats`` beats with a fade."""
    total, starts = lt3.loop_samples()
    out = np.zeros(total)
    fade = round(CUT_FADE_MS / 1000.0 * SAMPLE_RATE)
    cut = round(cut_beats * 60.0 / BPM * SAMPLE_RATE)
    for start in starts[1::2]:
        seg = hit[:cut].copy()
        if len(hit) > cut:
            seg[-fade:] *= raised_cosine(fade, rising=False)
        used = min(len(seg), total - start)
        out[start : start + used] += seg[:used]
    return out


def match_db(clap: np.ndarray) -> float:
    """RMS (dB re full scale) over the first 60 ms of a clap (all claps start at sample 0)."""
    window = clap[: round(MATCH_MS / 1000.0 * SAMPLE_RATE)]
    return 20.0 * math.log10(math.sqrt(float(np.mean(window**2))))


def kick_loop() -> np.ndarray:
    return lt3.build_loop(lt3._dense(), KICK_BUS_DB)


@dataclass
class Rendered:
    item: str
    label: str  # "A" ...
    render: str  # id in RENDERS
    gain_db: float
    wav: bytes


def render_package() -> list[Rendered]:
    hits = {k: v[1]() for k, v in RENDERS.items()}
    # v0 of `variants 4` is the preset itself; the item C6 relies on it
    assert np.array_equal(_variant(0), hits["T"])
    kick = kick_loop()
    out: list[Rendered] = []
    for item, ids in ITEMS.items():
        levels = [match_db(hits[r]) for r in ids]
        position = lt3.blind_order(item, len(ids), BLIND_SEED)
        for i, r in enumerate(ids):
            gain_db = min(levels) - levels[i]  # <= 0: the quietest file keeps 0 dB
            bus = 10.0 ** ((CLAP_BUS_DB + gain_db) / 20.0)
            mix = kick + clap_loop(hits[r], RENDERS[r][2]) * bus
            out.append(Rendered(item, "ABCD"[position[i]], r, gain_db,
                                encode_wav(mix, SAMPLE_RATE, BIT_DEPTH)))
    return sorted(out, key=lambda f: (f.item, f.label))


def clap_only_ints(wav: bytes) -> np.ndarray:
    """Clap part of a written file: the file minus the (identical) quantised kick loop."""
    full = 2.0 ** (BIT_DEPTH - 1) - 1
    kick = np.round(np.clip(kick_loop(), -1, 1) * full)
    return wav_samples(wav) - kick


def clap_match_db(wav: bytes, first_clap_start: int | None = None) -> float:
    """Match-window level of the first clap in a written file (dB re full scale)."""
    start = first_clap_start if first_clap_start is not None else lt3.loop_samples()[1][1]
    x = clap_only_ints(wav)[start : start + round(MATCH_MS / 1000.0 * SAMPLE_RATE)]
    x = x / 2.0 ** (BIT_DEPTH - 1)
    return 20.0 * math.log10(math.sqrt(float(np.mean(x**2))))


def measure(files: list[Rendered]) -> dict[str, Any]:
    peaks = {f"{f.item}_{f.label}": lt3.peak_dbfs(wav_samples(f.wav)) for f in files}
    spread = {}
    for item in ITEMS:
        levels = [clap_match_db(f.wav) for f in files if f.item == item]
        spread[item] = max(levels) - min(levels)
    c0 = [f.wav for f in files if f.item == "C0"]
    return {"peak_dbfs": peaks, "match_spread_db": spread, "c0_identical": c0[0] == c0[1]}


def key_text(files: list[Rendered], report: dict[str, Any]) -> str:
    lines = [
        "# Schluessel Hoertest Clap",
        "",
        "Erst nach dem Test oeffnen. Aufbau: 4 Takte, 136 BPM, Kick (`dense`) auf jedem Beat, "
        "Clap auf 2 und 4, mono, 48 kHz, 24 bit. Position A/B/C/D mit festem Seed "
        f"({BLIND_SEED}) gemischt. Pegelangleich je Item: RMS ueber die ersten {MATCH_MS:.0f} ms "
        "der Clap allein, leiser gezogen auf die leiseste Datei des Items.",
        "",
        "| Datei | Inhalt | Gain (Angleich) | Spitze dBFS | Clap-RMS 0-60 ms dBFS |",
        "| --- | --- | --- | --- | --- |",
    ]
    for f in files:
        lines.append(
            f"| `{f.item}_{f.label}.wav` | {RENDERS[f.render][0]} | {f.gain_db:+.2f} dB "
            f"| {lt3.peak_dbfs(wav_samples(f.wav)):.2f} | {clap_match_db(f.wav):.2f} |"
        )
    lines += ["", "Pegelunterschied innerhalb eines Items (dB): " + ", ".join(
        f"{k} {v:.3f}" for k, v in report["match_spread_db"].items()), ""]
    return "\n".join(lines)


def write_package(out: str | Path) -> dict[str, Any]:
    root = Path(out)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"{root} is not empty; choose a new folder")
    package = root / "package"
    package.mkdir(parents=True, exist_ok=True)
    files = render_package()
    report = measure(files)
    for f in files:
        (package / f"{f.item}_{f.label}.wav").write_bytes(f.wav)
    (package / "Schluessel.md").write_text(key_text(files, report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the clap listening test package.")
    parser.add_argument("--out", required=True, help="new, empty folder outside the repo")
    args = parser.parse_args(argv)
    print(json.dumps(write_package(args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
