"""Package for the rim listening test (issue #359): five items, 18 blind-named loops.

    python -m audio_engine.listening_test_rim --out DIR

Writes into a new folder ``DIR`` (outside the repo):

- ``DIR/hoerer/R?_<A..E>.wav``: what is sent to the listener.
- ``DIR/Schluessel.md``: the key. Not sent.

Every loop is 4 bars at 136 BPM (16 beats), mono 48 kHz / 24 bit, ``dense`` kick on every beat
(bus -6 dB, as in test 3) and a closed-hat bed (``closed-std``, a hit on every 16th, bus -14 dB)
as drum-loop context, both reused from :mod:`audio_engine.listening_test_hat`. The rim sits on
every off-beat 8th (beat positions 1.1.3, 1.2.3, ...); each hit is cut at the next off-beat with
a 3 ms raised-cosine fade (only when the render is longer than the slot). Rim bus -8 dB plus the
item gain; item gains are <= 0.

Level match inside an item: RMS of one rim render alone over its first 60 ms, every file scaled
down to the quietest of its item; gains are in the key. This is a signal match, not a loudness
judgement. Positions A..E come from SHA-256 of a fixed seed (no RNG state, no clock): same
code, byte-identical files and key.

Questions (measurable hypotheses, none is a listening claim):

- R1: the five rim presets against each other.
- R0: control pair, two identical files.
- R2: ``click_ms`` 3 / 1 / 0.2 at ``click_level`` 0.6, plus ``click_level`` 0. The effective click
  level is below the nominal one and depends on ``click_ms`` (0.92 at 3 ms, 0.80 at 1 ms, 0.39
  at 0.2 ms, PR #330 review); the key lists a measured click ratio per file.
- R3: ``hp_hz`` 200 / 500 / 700 on a rim with ``f1_hz`` 900 (``hp_hz`` < 0.8 * ``f1_hz`` = 720).
- R4: ``f2_ratio`` 2 / 3.66 / 5 and a single partial (``level2`` 0).
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
from . import listening_test_hat as lth
from .dsp import rbj_highpass
from .io import encode_wav, wav_samples
from .presets import load_preset
from .rim import render_rim

SAMPLE_RATE = lt3.SAMPLE_RATE
BIT_DEPTH = lt3.BIT_DEPTH
CEILING_DBFS = lt3.CEILING_DBFS
BLIND_SEED = 359
KICK_BUS_DB = lth.KICK_BUS_DB
HAT_BED_BUS_DB = -14.0
RIM_BUS_DB = -8.0  # fixed starting level, not a loudness claim
MATCH_MS = 60.0
CLICK_BAND_HZ = 4000.0  # click ratio: energy above this, first 3 ms over the next 30 ms
LABELS = "ABCDE"
SLOT_KIND = "open"  # off-beat 8ths, reused from the hat generator


def _rim(preset: str = "rim", **changes: Any) -> np.ndarray:
    params = dict(load_preset(preset, "rim"))
    params.update({"seed": 1, "peak_ceiling_dbfs": CEILING_DBFS, **changes})
    return render_rim(params)[0]


# Unique renders, by id: (description, maker).
RENDERS: dict[str, tuple[str, Any]] = {
    "clave": ("preset clave", lambda: _rim("clave")),
    "high": ("preset high", lambda: _rim("high")),
    "long": ("preset long", lambda: _rim("long")),
    "rim": ("preset rim", _rim),
    "tight": ("preset tight", lambda: _rim("tight")),
    "click0": ("rim with click_level 0", lambda: _rim(click_level=0.0)),
    "click3": ("rim with click_level 0.6, click_ms 3", lambda: _rim(click_level=0.6, click_ms=3)),
    "click1": ("rim with click_level 0.6, click_ms 1", lambda: _rim(click_level=0.6, click_ms=1)),
    "click02": (
        "rim with click_level 0.6, click_ms 0.2",
        lambda: _rim(click_level=0.6, click_ms=0.2),
    ),
    "hp200": ("preset high with hp_hz 200", lambda: _rim("high", hp_hz=200)),
    "hp500": ("preset high (hp_hz 500)", lambda: _rim("high")),
    "hp700": ("preset high with hp_hz 700", lambda: _rim("high", hp_hz=700)),
    "ratio2": ("rim with f2_ratio 2", lambda: _rim(f2_ratio=2.0)),
    "ratio366": ("rim (f2_ratio 3.66)", _rim),
    "ratio5": ("rim with f2_ratio 5", lambda: _rim(f2_ratio=5.0)),
    "single": ("rim with level2 0 (one partial)", lambda: _rim(level2=0.0)),
}

# Listening order. Each item: the render id of every file, in definition order (not blind).
ITEMS: dict[str, list[str]] = {
    "R1": ["clave", "high", "long", "rim", "tight"],
    "R0": ["rim", "rim"],
    "R2": ["click0", "click3", "click1", "click02"],
    "R3": ["hp200", "hp500", "hp700"],
    "R4": ["ratio2", "ratio366", "ratio5", "single"],
}


def rim_loop(hit: np.ndarray) -> np.ndarray:
    return lth.hat_loop(hit, SLOT_KIND)


def background() -> np.ndarray:
    """Kick loop plus the closed-hat bed: identical in every file."""
    bed = lth.hat_loop(lth._hat(), "closed") * 10.0 ** (HAT_BED_BUS_DB / 20.0)
    return lth.kick_loop() + bed


def match_db(hit: np.ndarray) -> float:
    """RMS (dB re full scale) over the match window of a hit (all hits start at sample 0)."""
    window = hit[: round(MATCH_MS / 1000.0 * SAMPLE_RATE)]
    return 20.0 * math.log10(math.sqrt(float(np.mean(window**2))))


def click_ratio_db(hit: np.ndarray) -> float:
    """Energy above 4 kHz in the first 3 ms over the same band in the next 30 ms (dB)."""
    high = rbj_highpass(hit, SAMPLE_RATE, CLICK_BAND_HZ)
    n3, n33 = round(0.003 * SAMPLE_RATE), round(0.033 * SAMPLE_RATE)
    early = float(np.sum(high[:n3] ** 2))
    late = float(np.sum(high[n3:n33] ** 2))
    return 10.0 * math.log10(max(early, 1e-30) / max(late, 1e-30))


@dataclass
class Rendered:
    item: str
    label: str  # "A" ...
    render: str  # id in RENDERS
    gain_db: float
    wav: bytes


def render_package() -> list[Rendered]:
    hits = {k: v[1]() for k, v in RENDERS.items()}
    back = background()
    out: list[Rendered] = []
    for item, ids in ITEMS.items():
        levels = [match_db(hits[r]) for r in ids]
        position = lt3.blind_order(item, len(ids), BLIND_SEED)
        for i, r in enumerate(ids):
            gain_db = min(levels) - levels[i]  # <= 0: the quietest file keeps 0 dB
            bus = 10.0 ** ((RIM_BUS_DB + gain_db) / 20.0)
            mix = back + rim_loop(hits[r]) * bus
            out.append(
                Rendered(item, LABELS[position[i]], r, gain_db,
                         encode_wav(mix, SAMPLE_RATE, BIT_DEPTH))
            )
    return sorted(out, key=lambda f: (f.item, f.label))


def rim_only_ints(wav: bytes) -> np.ndarray:
    """Rim part of a written file: the file minus the (identical) quantised background."""
    full = 2.0 ** (BIT_DEPTH - 1) - 1
    return wav_samples(wav) - np.round(np.clip(background(), -1, 1) * full)


def rim_match_db(wav: bytes, slot: int = 0) -> float:
    """Match-window level of rim slot ``slot`` in a written file (dB re full scale)."""
    start = lth.slot_starts(SLOT_KIND)[slot]
    x = rim_only_ints(wav)[start : start + round(MATCH_MS / 1000.0 * SAMPLE_RATE)]
    x = x / 2.0 ** (BIT_DEPTH - 1)
    return 20.0 * math.log10(math.sqrt(float(np.mean(x**2))))


def measure(files: list[Rendered]) -> dict[str, Any]:
    peaks = {f"{f.item}_{f.label}": lt3.peak_dbfs(wav_samples(f.wav)) for f in files}
    spread = {}
    for item in ITEMS:
        levels = [rim_match_db(f.wav) for f in files if f.item == item]
        spread[item] = max(levels) - min(levels)
    r0 = [f.wav for f in files if f.item == "R0"]
    return {"peak_dbfs": peaks, "match_spread_db": spread, "r0_identical": r0[0] == r0[1]}


def key_text(files: list[Rendered], report: dict[str, Any]) -> str:
    clicks = {k: click_ratio_db(v[1]()) for k, v in RENDERS.items() if k.startswith("click")}
    lines = [
        "# Schluessel Hoertest Rim",
        "",
        "Erst nach dem Test oeffnen. Aufbau: 4 Takte, 136 BPM, Kick (`dense`) auf jedem Beat, "
        "geschlossener Hat (`closed-std`) auf jedem 16tel als Beet (Bus -14 dB), Rim auf jedem "
        "Off-Beat-8tel; jeder Schlag wird beim naechsten Slot mit 3 ms Fade abgeschnitten. "
        f"Position A bis E mit festem Seed ({BLIND_SEED}) gemischt. Pegelangleich je Item: RMS "
        "des Rims allein ueber die ersten 60 ms, leiser gezogen auf die leiseste Datei des "
        "Items. Das ist ein Signalangleich, kein Lautheitsurteil. R0 ist das Kontrollpaar "
        "(zwei identische Dateien).",
        "",
        "| Datei | Inhalt | Gain (Angleich) | Spitze dBFS | Rim-RMS im Fenster dBFS |",
        "| --- | --- | --- | --- | --- |",
    ]
    for f in files:
        lines.append(
            f"| `{f.item}_{f.label}.wav` | {RENDERS[f.render][0]} | {f.gain_db:+.2f} dB "
            f"| {lt3.peak_dbfs(wav_samples(f.wav)):.2f} | {rim_match_db(f.wav):.2f} |"
        )
    lines += [
        "",
        "Pegelunterschied innerhalb eines Items (dB): "
        + ", ".join(f"{k} {v:.3f}" for k, v in report["match_spread_db"].items()),
        "",
        "Gemessenes Klick-Verhaeltnis in R2 (Energie ueber 4 kHz, erste 3 ms zu naechste 30 ms, "
        "dB; nur Signalmass, vor Angleich): "
        + ", ".join(f"{RENDERS[k][0]}: {v:.1f}" for k, v in clicks.items()),
        "",
    ]
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
    parser = argparse.ArgumentParser(description="Render the rim listening test package.")
    parser.add_argument("--out", required=True, help="new, empty folder outside the repo")
    args = parser.parse_args(argv)
    print(json.dumps(write_package(args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
