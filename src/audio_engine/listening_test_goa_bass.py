"""Package for the Goa rolling-bass listening test (issue #381, refs #338): 5 items, 13 blind loops.

    python -m audio_engine.listening_test_goa_bass --out DIR

Question behind it: hypothesis H-voice-1 of ``docs/research/2026-11-03_goa-synth-voice-plan.md``
(the existing bass contract covers a rolling-bass one-shot at 140-146 BPM). The preset values are
hypotheses from that note (gate 0.6-1.0 of a 16th, filter closing 2-40 ms), not findings. Built on
:mod:`audio_engine.listening_test_bass` (same loop, kick, pattern slots, level-match window rule).
Writes into a new folder ``DIR``:

- ``DIR/hoerer/<G?>_<A|B|C>.wav``: what is sent to the listener.
- ``DIR/Schluessel.md``: the key. Not sent.

Every loop: 4 bars at 140 BPM, mono 48 kHz / 24 bit, ``dense`` kick on every beat (bus -6 dB),
bass bus -9 dB plus the item gain (<= 0). Patterns as in the bass test: ``rolling`` (a note on every
16th except the beat positions, slot one 16th) and ``offbeat`` (one note per off-beat 8th, slot one
beat). Level match inside an item: RMS of one note rendered alone over 40 % to 80 % of the item's
shortest ``gate_ms`` (same absolute window for every file), every file scaled down to the quietest
of its item. Positions come from SHA-256 of a fixed seed: same code, byte-identical files.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import listening_test3 as lt3
from . import listening_test_bass as ltb
from .bass import render_bass
from .io import encode_wav, wav_samples
from .presets import load_preset

SAMPLE_RATE = ltb.SAMPLE_RATE
BIT_DEPTH = ltb.BIT_DEPTH
BPM = ltb.BPM
BLIND_SEED = 338
KICK_BUS_DB = ltb.KICK_BUS_DB
BASS_BUS_DB = ltb.BASS_BUS_DB  # a fixed starting level under the kick bus, not a loudness claim
MATCH_FRACTION = ltb.MATCH_FRACTION
LABELS = "ABC"

PRESETS = ("goa-roll-short", "goa-roll-medium", "goa-roll-long")


def _bass(preset: str, **changes: Any) -> tuple[np.ndarray, dict[str, Any]]:
    params = dict(load_preset(preset, "bass"))
    params.update(changes)
    return render_bass(params)


# Render id -> (description for the key, preset, parameter changes).
RENDERS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "short": ("goa-roll-short (gate 62, filter 8 ms), note 36", "goa-roll-short", {}),
    "medium": ("goa-roll-medium (gate 85, filter 15 ms), note 36", "goa-roll-medium", {}),
    "long": ("goa-roll-long (gate 100, filter 25 ms), note 36", "goa-roll-long", {}),
    "f5": ("goa-roll-medium, filter decay 5 ms", "goa-roll-medium", {"lp_env_decay_ms": 5}),
    "f20": ("goa-roll-medium, filter decay 20 ms", "goa-roll-medium", {"lp_env_decay_ms": 20}),
    "f40": ("goa-roll-medium, filter decay 40 ms", "goa-roll-medium", {"lp_env_decay_ms": 40}),
    "ring": (
        "goa-roll-long with gate 200, release 15 (one off-beat 8th)",
        "goa-roll-long",
        {"gate_ms": 200, "release_ms": 15},
    ),
    "n31": ("goa-roll-medium, note 31 (G1)", "goa-roll-medium", {"note": 31}),
    "n40": ("goa-roll-medium, note 40 (E2)", "goa-roll-medium", {"note": 40}),
}

# Listening order. Each item: (pattern, render ids in definition order).
ITEMS: dict[str, tuple[str, list[str]]] = {
    "G1": ("rolling", ["short", "medium", "long"]),
    "G2": ("rolling", ["medium", "medium"]),  # byte-identical pair
    "G3": ("rolling", ["f5", "f20", "f40"]),
    "G4": ("offbeat", ["medium", "ring"]),
    "G5": ("rolling", ["n31", "medium", "n40"]),
}


def item_window_ms(
    item: str, notes: dict[str, tuple[np.ndarray, dict[str, Any]]]
) -> tuple[float, float]:
    gate = min(notes[r][1]["gate_ms"] for r in ITEMS[item][1])
    return MATCH_FRACTION[0] * gate, MATCH_FRACTION[1] * gate


def render_notes() -> dict[str, tuple[np.ndarray, dict[str, Any]]]:
    return {k: _bass(v[1], **v[2]) for k, v in RENDERS.items()}


@dataclass
class Rendered:
    item: str
    label: str
    render: str
    gain_db: float
    wav: bytes


def render_package() -> list[Rendered]:
    notes = render_notes()
    kick = ltb.kick_loop()
    out: list[Rendered] = []
    for item, (pattern, ids) in ITEMS.items():
        window = item_window_ms(item, notes)
        levels = [ltb.match_db(notes[r][0], window) for r in ids]
        position = lt3.blind_order(item, len(ids), BLIND_SEED)
        for i, r in enumerate(ids):
            gain_db = min(levels) - levels[i]  # <= 0: the quietest file keeps 0 dB
            bus = 10.0 ** ((BASS_BUS_DB + gain_db) / 20.0)
            mix = kick + ltb.bass_loop(notes[r][0], pattern) * bus
            out.append(Rendered(item, LABELS[position[i]], r, gain_db,
                                encode_wav(mix, SAMPLE_RATE, BIT_DEPTH)))
    return sorted(out, key=lambda f: (f.item, f.label))


def window_samples(item: str) -> tuple[int, int]:
    lo, hi = item_window_ms(item, render_notes())
    return round(lo / 1000.0 * SAMPLE_RATE), round(hi / 1000.0 * SAMPLE_RATE)


def file_match_db(wav: bytes, item: str, slot: int = 0) -> float:
    """Match-window level of note slot ``slot`` in a written file (dB re full scale)."""
    lo, hi = window_samples(item)
    start = ltb.pattern_slots(ITEMS[item][0])[slot][0]
    x = ltb.bass_only_ints(wav)[start + lo : start + hi] / 2.0 ** (BIT_DEPTH - 1)
    return 20.0 * float(np.log10(np.sqrt(np.mean(x**2))))


def measure(files: list[Rendered]) -> dict[str, Any]:
    peaks = {f"{f.item}_{f.label}": lt3.peak_dbfs(wav_samples(f.wav)) for f in files}
    spread = {}
    for item in ITEMS:
        levels = [file_match_db(f.wav, item) for f in files if f.item == item]
        spread[item] = max(levels) - min(levels)
    g2 = [f.wav for f in files if f.item == "G2"]
    return {"peak_dbfs": peaks, "match_spread_db": spread, "g2_identical": g2[0] == g2[1]}


def key_text(files: list[Rendered], report: dict[str, Any]) -> str:
    lines = [
        "# Schluessel Hoertest Goa-Bass",
        "",
        "Erst nach dem Test oeffnen. Aufbau: 4 Takte, 140 BPM, Kick (`dense`) auf jedem Beat, "
        "mono, 48 kHz, 24 bit. Muster: G1, G2, G3, G5 Noten auf allen 16teln ausser den "
        "Beat-Positionen; G4 eine Note je Off-Beat-8tel. Jede Note wird am Slot-Ende mit 3 ms "
        f"Fade abgeschnitten. Position mit festem Seed ({BLIND_SEED}) gemischt. Pegelangleich je "
        "Item: RMS einer einzelnen Note ueber 40-80 % der kuerzesten Gate-Laenge des Items "
        "(gleiches absolutes Fenster fuer alle Dateien), leiser gezogen auf die leiseste Datei. "
        "G2 ist ein byte-gleiches Paar (Kontrolle). Das ist ein Signalangleich, kein "
        "Lautheitsurteil. Die Presetwerte sind Hypothesen aus dem Goa-Voice-Plan, keine Befunde.",
        "",
        "| Datei | Inhalt | Gain (Angleich) | Spitze dBFS | Bass-RMS im Fenster dBFS |",
        "| --- | --- | --- | --- | --- |",
    ]
    for f in files:
        lines.append(
            f"| `{f.item}_{f.label}.wav` | {RENDERS[f.render][0]} | {f.gain_db:+.2f} dB "
            f"| {lt3.peak_dbfs(wav_samples(f.wav)):.2f} | {file_match_db(f.wav, f.item):.2f} |"
        )
    lines += ["", "Pegelunterschied innerhalb eines Items (dB): " + ", ".join(
        f"{k} {v:.3f}" for k, v in report["match_spread_db"].items()), ""]
    return "\n".join(lines)


def write_package(out: str | Path) -> dict[str, Any]:
    root = Path(out)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"{root} is not empty; choose a new folder")
    package = root / "hoerer"
    package.mkdir(parents=True, exist_ok=True)
    files = render_package()
    report = measure(files)
    for f in files:
        (package / f"{f.item}_{f.label}.wav").write_bytes(f.wav)
    (root / "Schluessel.md").write_text(key_text(files, report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the Goa bass listening test package.")
    parser.add_argument("--out", required=True, help="new, empty folder outside the repo")
    args = parser.parse_args(argv)
    print(json.dumps(write_package(args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
