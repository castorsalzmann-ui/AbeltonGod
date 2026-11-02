"""Package for the hat listening test (issue #300): seven items, 19 blind-named loops.

    python -m audio_engine.listening_test_hat --out DIR

Plan: ``docs/research/2026-11-02_hat-targets-and-listening-plan.md`` section 5; items and
parameter values as in ``docs/setup/LISTENING_TEST_HAT_LEAD.md`` (PR #299), now rendered as
loops after the pattern of :mod:`audio_engine.listening_test_clap`. Writes into a new folder
``DIR``:

- ``DIR/hoerer/<T?>_<A|B|C|D>.wav``: what is sent to the listener.
- ``DIR/Schluessel.md``: the key. Not sent.

Every loop is 4 bars at 136 BPM (16 beats), mono 48 kHz / 24 bit, ``dense``
kick on every beat (bus -6 dB, as in test 3). Hat patterns (start of slot ``k`` is
``round(k * 60 / 136 * 48000 / divisions)`` samples):

- closed (items T1, T0, T2, T3, T6): a hat on every 16th, 16 per bar; each hit is cut at the
  next 16th with a 3 ms raised-cosine fade (only when the render is longer than the slot).
- open (items T5, T4): a hat on every off-beat 8th (beat positions 1.1.3, 1.2.3, ...), 4 per
  bar, no closed hat; each hit is cut at the next off-beat (one beat later) with the same fade.

Hat bus -8 dB plus the item gain; item gains are <= 0. Level match inside an item: RMS of
one hat render alone over its first 30 ms (closed) or 100 ms (open), every file scaled down
to the quietest of its item; gains are in the key. Positions A/B/C/D come from SHA-256 of a
fixed seed (no RNG state, no clock): same code, byte-identical files and key.
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
from .dsp import raised_cosine
from .hat import render_hat
from .hat_variants import make_variants
from .io import encode_wav, wav_samples
from .presets import load_preset

BPM = lt3.BPM
SAMPLE_RATE = lt3.SAMPLE_RATE
BIT_DEPTH = lt3.BIT_DEPTH
CEILING_DBFS = lt3.CEILING_DBFS
CUT_FADE_MS = lt3.CUT_FADE_MS
BLIND_SEED = 300
KICK_BUS_DB = -6.0
HAT_BUS_DB = -8.0  # 2 dB under the kick bus (a fixed starting level, not a loudness claim)
MATCH_MS = {"closed": 30.0, "open": 100.0}


def _hat(preset: str = "closed-std", **changes: Any) -> np.ndarray:
    params = dict(load_preset(preset, "hat"))
    params.update({"seed": 1, "peak_ceiling_dbfs": CEILING_DBFS, **changes})
    return render_hat(params)[0]


def _variant(index: int) -> np.ndarray:
    base = dict(load_preset("closed-std", "hat"))
    base.update({"seed": 1, "peak_ceiling_dbfs": CEILING_DBFS})
    return render_hat(make_variants(base, 4)[index])[0]


# Unique renders, by id: (description, maker, pattern kind).
RENDERS: dict[str, tuple[str, Any, str]] = {
    "loose": ("closed-loose (decay_ms 120, hp_hz 5000)", lambda: _hat("closed-loose"), "closed"),
    "tight": ("closed-tight (decay_ms 35, hp_hz 7000)", lambda: _hat("closed-tight"), "closed"),
    "S": ("S = closed-std (decay_ms 70, hp_hz 6000, metal 0.6), seed 1", _hat, "closed"),
    "hp9000": ("S with hp_hz 9000", lambda: _hat(hp_hz=9000), "closed"),
    "hp4500": ("S with hp_hz 4500", lambda: _hat(hp_hz=4500), "closed"),
    "m1": ("S with metal 1", lambda: _hat(metal=1), "closed"),
    "m0": ("S with metal 0", lambda: _hat(metal=0), "closed"),
    "v1": ("variant 1 of S (variants 4)", lambda: _variant(1), "closed"),
    "v2": ("variant 2 of S (variants 4)", lambda: _variant(2), "closed"),
    "v3": ("variant 3 of S (variants 4)", lambda: _variant(3), "closed"),
    "split": (
        "open-long with body_mix 0.4, decay_hi_ratio 0.5",
        lambda: _hat("open-long", body_mix=0.4, decay_hi_ratio=0.5),
        "open",
    ),
    "long": ("open-long (decay_ms 500)", lambda: _hat("open-long"), "open"),
    "choke": ("open-long with choke_ms 220", lambda: _hat("open-long", choke_ms=220), "open"),
    "short": ("open-short (decay_ms 250)", lambda: _hat("open-short"), "open"),
}

# Listening order. Each item: the render id of every file, in definition order (not blind).
# v0 of `variants 4` is the preset itself = S.
ITEMS: dict[str, list[str]] = {
    "T1": ["loose", "tight"],
    "T0": ["S", "S"],
    "T2": ["S", "hp9000", "hp4500"],
    "T5": ["split", "long"],
    "T4": ["choke", "short", "long"],
    "T3": ["m1", "m0", "S"],
    "T6": ["v2", "S", "v3", "v1"],
}


def item_kind(item: str) -> str:
    kinds = {RENDERS[r][2] for r in ITEMS[item]}
    assert len(kinds) == 1, item
    return kinds.pop()


def slot_starts(kind: str) -> list[int]:
    """Start sample of each hat slot in the loop (16 beats; closed 4 per beat, open 1 per beat)."""
    beat = 60.0 / BPM * SAMPLE_RATE
    n_beats = lt3.BARS * 4
    if kind == "closed":
        return [round(k * beat / 4) for k in range(n_beats * 4)]
    return [round((b + 0.5) * beat) for b in range(n_beats)]  # off-beat 8ths


def slot_ends(kind: str) -> list[int]:
    """Cut point of each slot: the next slot start (the last one: the end of the loop)."""
    total = lt3.loop_samples()[0]
    starts = slot_starts(kind)
    if kind == "closed":
        return [*starts[1:], total]
    return [*starts[1:], round((lt3.BARS * 4 + 0.5) * 60.0 / BPM * SAMPLE_RATE)]


def hat_loop(hit: np.ndarray, kind: str) -> np.ndarray:
    """Hat pattern of ``kind``, each hit cut at the next slot with a 3 ms fade if it is longer."""
    total = lt3.loop_samples()[0]
    out = np.zeros(total)
    fade = round(CUT_FADE_MS / 1000.0 * SAMPLE_RATE)
    for start, end in zip(slot_starts(kind), slot_ends(kind), strict=True):
        seg = hit[: end - start].copy()
        if len(hit) > end - start:
            seg[-fade:] *= raised_cosine(fade, rising=False)
        used = min(len(seg), total - start)
        out[start : start + used] += seg[:used]
    return out


def match_db(hit: np.ndarray, kind: str) -> float:
    """RMS (dB re full scale) over the match window of a hit (all hits start at sample 0)."""
    window = hit[: round(MATCH_MS[kind] / 1000.0 * SAMPLE_RATE)]
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
    # v0 of `variants 4` is the preset itself; the item T6 relies on it
    base = dict(load_preset("closed-std", "hat"))
    base.update({"seed": 1, "peak_ceiling_dbfs": CEILING_DBFS})
    assert np.array_equal(render_hat(make_variants(base, 4)[0])[0], hits["S"])
    kick = kick_loop()
    out: list[Rendered] = []
    for item, ids in ITEMS.items():
        kind = item_kind(item)
        levels = [match_db(hits[r], kind) for r in ids]
        position = lt3.blind_order(item, len(ids), BLIND_SEED)
        for i, r in enumerate(ids):
            gain_db = min(levels) - levels[i]  # <= 0: the quietest file keeps 0 dB
            bus = 10.0 ** ((HAT_BUS_DB + gain_db) / 20.0)
            mix = kick + hat_loop(hits[r], kind) * bus
            out.append(Rendered(item, "ABCD"[position[i]], r, gain_db,
                                encode_wav(mix, SAMPLE_RATE, BIT_DEPTH)))
    return sorted(out, key=lambda f: (f.item, f.label))


def hat_only_ints(wav: bytes) -> np.ndarray:
    """Hat part of a written file: the file minus the (identical) quantised kick loop."""
    full = 2.0 ** (BIT_DEPTH - 1) - 1
    kick = np.round(np.clip(kick_loop(), -1, 1) * full)
    return wav_samples(wav) - kick


def hat_match_db(wav: bytes, item: str, slot: int = 0) -> float:
    """Match-window level of hat slot ``slot`` in a written file (dB re full scale)."""
    kind = item_kind(item)
    start = slot_starts(kind)[slot]
    x = hat_only_ints(wav)[start : start + round(MATCH_MS[kind] / 1000.0 * SAMPLE_RATE)]
    x = x / 2.0 ** (BIT_DEPTH - 1)
    return 20.0 * math.log10(math.sqrt(float(np.mean(x**2))))


def measure(files: list[Rendered]) -> dict[str, Any]:
    peaks = {f"{f.item}_{f.label}": lt3.peak_dbfs(wav_samples(f.wav)) for f in files}
    spread = {}
    for item in ITEMS:
        levels = [hat_match_db(f.wav, item) for f in files if f.item == item]
        spread[item] = max(levels) - min(levels)
    t0 = [f.wav for f in files if f.item == "T0"]
    return {"peak_dbfs": peaks, "match_spread_db": spread, "t0_identical": t0[0] == t0[1]}


def key_text(files: list[Rendered], report: dict[str, Any]) -> str:
    lines = [
        "# Schluessel Hoertest Hat",
        "",
        "Erst nach dem Test oeffnen. Aufbau: 4 Takte, 136 BPM, Kick (`dense`) auf jedem Beat, "
        "mono, 48 kHz, 24 bit. Closed (T1, T0, T2, T3, T6): Hat auf jedem 16tel; Open (T5, T4): "
        "Hat auf jedem Off-Beat-8tel; jeder Schlag wird beim naechsten Slot mit 3 ms Fade "
        f"abgeschnitten. Position A/B/C/D mit festem Seed ({BLIND_SEED}) gemischt. "
        "Pegelangleich je Item: RMS des Hats allein ueber die ersten 30 ms (Closed) bzw. "
        "100 ms (Open), leiser gezogen auf die leiseste Datei des Items. Das ist ein "
        "Signalangleich, kein Lautheitsurteil.",
        "",
        "| Datei | Inhalt | Gain (Angleich) | Spitze dBFS | Hat-RMS im Fenster dBFS |",
        "| --- | --- | --- | --- | --- |",
    ]
    for f in files:
        lines.append(
            f"| `{f.item}_{f.label}.wav` | {RENDERS[f.render][0]} | {f.gain_db:+.2f} dB "
            f"| {lt3.peak_dbfs(wav_samples(f.wav)):.2f} | {hat_match_db(f.wav, f.item):.2f} |"
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
    parser = argparse.ArgumentParser(description="Render the hat listening test package.")
    parser.add_argument("--out", required=True, help="new, empty folder outside the repo")
    args = parser.parse_args(argv)
    print(json.dumps(write_package(args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
