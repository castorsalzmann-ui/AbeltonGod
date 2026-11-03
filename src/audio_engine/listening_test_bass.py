"""Package for the bass listening test (issue #361): six items, 18 blind-named loops.

    python -m audio_engine.listening_test_bass --out DIR

Plan: ``docs/research/2026-11-02_bass-targets.md`` section 6 (skeleton), the drive question of
issue #335 and the bass voice of PR #334. Items and render values as in
``docs/setup/LISTENING_TEST_BASS_LEAD.md``; built after the pattern of
:mod:`audio_engine.listening_test_hat`. Writes into a new folder ``DIR``:

- ``DIR/hoerer/<B?>_<A|B|C|D|E>.wav``: what is sent to the listener.
- ``DIR/Schluessel.md``: the key. Not sent.

Every loop is 4 bars at 140 BPM (16 beats), mono 48 kHz / 24 bit, ``dense`` kick on every beat
(bus -6 dB, :func:`audio_engine.listening_test3.build_loop` with ``bpm=140``). Bass patterns
(slot ``k`` starts at ``round(position_in_beats * 60 / 140 * 48000)``); each note is cut at the
end of its slot with a 3 ms raised-cosine fade, only when the render is longer than the slot:

- ``offbeat``: one note on every off-beat 8th (beat positions b + 0.5), 16 notes, slot 1 beat.
- ``bar``: one note per bar at beat 0.5 of the bar, 4 notes, slot 4 beats (>= 1.5 s even for
  the sustained notes).
- ``rolling``: a note on every 16th except the four beat positions (step % 4 == 0), 48 notes,
  slot one 16th.

Bass bus -9 dB plus the item gain; gains are <= 0. Level match inside an item: RMS of one note
rendered alone over a stationary window, the same absolute window for every file of the item,
from 40 % to 80 % of the item's shortest ``gate_ms``; every file is scaled down to the
quietest one of its item. Gains are in the key. Positions A.. come from SHA-256 of a fixed
seed (no RNG state, no clock): same code, byte-identical files and key.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from . import listening_test3 as lt3
from .bass import render_bass
from .dsp import raised_cosine
from .io import encode_wav, wav_samples
from .presets import load_preset

BPM = 140
SAMPLE_RATE = lt3.SAMPLE_RATE
BIT_DEPTH = lt3.BIT_DEPTH
CUT_FADE_MS = lt3.CUT_FADE_MS
BLIND_SEED = 361
KICK_BUS_DB = -6.0
BASS_BUS_DB = -9.0  # a fixed starting level under the kick bus, not a loudness claim
MATCH_FRACTION = (0.4, 0.8)  # of the item's shortest gate
ROOTS = {"E1": 28, "G1": 31, "A1": 33}
ROOT = ROOTS["E1"]


def _bass(preset: str = "default", **changes: Any) -> np.ndarray:
    params = dict(load_preset(preset, "bass"))
    params.update(changes)
    return render_bass(params)


# Render id -> (description for the key, preset, parameter changes).
RENDERS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "ref": ("default, note 28 (E1)", "default", {"note": ROOT}),
    "sub": ("sub, note 28", "sub", {"note": ROOT}),
    "rolling": ("rolling (gate 110), note 28", "rolling", {"note": ROOT}),
    "bright": ("bright, note 28", "bright", {"note": ROOT}),
    "low": ("low (gate 300; note overridden to 28), note 28", "low", {"note": ROOT}),
    "g1": ("default, note 31 (G1)", "default", {"note": ROOTS["G1"]}),
    "a1": ("default, note 33 (A1)", "default", {"note": ROOTS["A1"]}),
    "d0_long": (
        "default, drive 0, gate 1000", "default", {"note": ROOT, "drive": 0.0, "gate_ms": 1000}
    ),
    "d2_long": (
        "default, drive 0.2, gate 1000", "default", {"note": ROOT, "drive": 0.2, "gate_ms": 1000}
    ),
    "short": ("default, gate 120", "default", {"note": ROOT, "gate_ms": 120}),
    "long": ("default, gate 800", "default", {"note": ROOT, "gate_ms": 800}),
}

# Listening order. Each item: (pattern, render ids in definition order, not blind).
ITEMS: dict[str, tuple[str, list[str]]] = {
    "B1": ("offbeat", ["ref", "sub", "rolling", "bright", "low"]),
    "B2": ("offbeat", ["ref", "ref"]),  # byte-identical pair
    "B3": ("offbeat", ["ref", "g1", "a1"]),
    "B4": ("bar", ["d0_long", "d2_long"]),
    "B5": ("bar", ["short", "ref", "long"]),
    "B6": ("rolling", ["rolling", "ref", "sub"]),
}
LABELS = "ABCDE"


def pattern_slots(pattern: str) -> list[tuple[int, int]]:
    """(start, end) sample of each note slot; exact fractions of beats, rounded once."""
    beat = Fraction(60 * SAMPLE_RATE, BPM)
    total = lt3.loop_samples(BPM)[0]

    def at(position: Fraction) -> int:
        return int((position * beat + Fraction(1, 2)) // 1)

    if pattern == "offbeat":
        grid = [(Fraction(b) + Fraction(1, 2), Fraction(1)) for b in range(16)]
    elif pattern == "bar":
        grid = [(Fraction(4 * bar) + Fraction(1, 2), Fraction(4)) for bar in range(4)]
    elif pattern == "rolling":
        grid = [(Fraction(s, 4), Fraction(1, 4)) for s in range(64) if s % 4 != 0]
    else:
        raise ValueError(pattern)
    return [(at(p), min(at(p + length), total)) for p, length in grid]


def bass_loop(note: np.ndarray, pattern: str) -> np.ndarray:
    """Bass pattern, each note cut at the end of its slot with a 3 ms fade if it is longer."""
    out = np.zeros(lt3.loop_samples(BPM)[0])
    fade = round(CUT_FADE_MS / 1000.0 * SAMPLE_RATE)
    for start, end in pattern_slots(pattern):
        seg = note[: end - start].copy()
        if len(note) > end - start:
            seg[-fade:] *= raised_cosine(fade, rising=False)
        out[start : start + len(seg)] += seg
    return out


def kick_loop() -> np.ndarray:
    return lt3.build_loop(lt3._dense(), KICK_BUS_DB, BPM)


def item_window_ms(
    item: str, notes: dict[str, tuple[np.ndarray, dict[str, Any]]]
) -> tuple[float, float]:
    gate = min(notes[r][1]["gate_ms"] for r in ITEMS[item][1])
    return MATCH_FRACTION[0] * gate, MATCH_FRACTION[1] * gate


def match_db(note: np.ndarray, window_ms: tuple[float, float]) -> float:
    """RMS (dB re full scale) of one note over the window (ms from its first sample)."""
    lo, hi = (round(w / 1000.0 * SAMPLE_RATE) for w in window_ms)
    return 20.0 * math.log10(math.sqrt(float(np.mean(note[lo:hi] ** 2))))


@dataclass
class Rendered:
    item: str
    label: str
    render: str
    gain_db: float
    wav: bytes


def render_package() -> list[Rendered]:
    notes = {k: _bass(v[1], **v[2]) for k, v in RENDERS.items()}
    kick = kick_loop()
    out: list[Rendered] = []
    for item, (pattern, ids) in ITEMS.items():
        window = item_window_ms(item, notes)
        levels = [match_db(notes[r][0], window) for r in ids]
        position = lt3.blind_order(item, len(ids), BLIND_SEED)
        for i, r in enumerate(ids):
            gain_db = min(levels) - levels[i]  # <= 0: the quietest file keeps 0 dB
            bus = 10.0 ** ((BASS_BUS_DB + gain_db) / 20.0)
            mix = kick + bass_loop(notes[r][0], pattern) * bus
            out.append(Rendered(item, LABELS[position[i]], r, gain_db,
                                encode_wav(mix, SAMPLE_RATE, BIT_DEPTH)))
    return sorted(out, key=lambda f: (f.item, f.label))


def bass_only_ints(wav: bytes) -> np.ndarray:
    """Bass part of a written file: the file minus the (identical) quantised kick loop."""
    full = 2.0 ** (BIT_DEPTH - 1) - 1
    kick = np.round(np.clip(kick_loop(), -1, 1) * full)
    return wav_samples(wav) - kick


def window_samples(item: str) -> tuple[int, int]:
    notes = {r: _bass(RENDERS[r][1], **RENDERS[r][2]) for r in ITEMS[item][1]}
    lo, hi = item_window_ms(item, notes)
    return round(lo / 1000.0 * SAMPLE_RATE), round(hi / 1000.0 * SAMPLE_RATE)


def file_match_db(wav: bytes, item: str, slot: int = 0) -> float:
    """Match-window level of note slot ``slot`` in a written file (dB re full scale)."""
    lo, hi = window_samples(item)
    start = pattern_slots(ITEMS[item][0])[slot][0]
    x = bass_only_ints(wav)[start + lo : start + hi] / 2.0 ** (BIT_DEPTH - 1)
    return 20.0 * math.log10(math.sqrt(float(np.mean(x**2))))


def measure(files: list[Rendered]) -> dict[str, Any]:
    peaks = {f"{f.item}_{f.label}": lt3.peak_dbfs(wav_samples(f.wav)) for f in files}
    spread = {}
    for item in ITEMS:
        levels = [file_match_db(f.wav, item) for f in files if f.item == item]
        spread[item] = max(levels) - min(levels)
    b2 = [f.wav for f in files if f.item == "B2"]
    return {"peak_dbfs": peaks, "match_spread_db": spread, "b2_identical": b2[0] == b2[1]}


def key_text(files: list[Rendered], report: dict[str, Any]) -> str:
    lines = [
        "# Schluessel Hoertest Bass",
        "",
        "Erst nach dem Test oeffnen. Aufbau: 4 Takte, 140 BPM, Kick (`dense`) auf jedem Beat, "
        "mono, 48 kHz, 24 bit. Muster: B1-B3 eine Note je Off-Beat-8tel; B4, B5 eine Note je "
        "Takt (Beat 1,5); B6 Noten auf allen 16teln ausser den Beat-Positionen. Jede Note wird "
        f"am Slot-Ende mit 3 ms Fade abgeschnitten. Position mit festem Seed ({BLIND_SEED}) "
        "gemischt. Pegelangleich je Item: RMS einer einzelnen Note ueber 40-80 % der "
        "kuerzesten Gate-Laenge des Items (gleiches absolutes Fenster fuer alle Dateien), "
        "leiser gezogen auf die leiseste Datei. B2 ist ein byte-gleiches Paar (Kontrolle). "
        "Das ist ein Signalangleich, kein Lautheitsurteil.",
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
    parser = argparse.ArgumentParser(description="Render the bass listening test package.")
    parser.add_argument("--out", required=True, help="new, empty folder outside the repo")
    args = parser.parse_args(argv)
    print(json.dumps(write_package(args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
