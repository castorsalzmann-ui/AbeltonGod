"""Listening package for the kick keyword prompts (issue #271).

    python -m audio_engine.listening_keywords --out DIR

Plan and expectations: ``docs/research/2026-11-02_keyword-prompt-listening-plan.md`` (section
numbers below refer to it); parser: :mod:`audio_engine.prompt` (not changed here). Writes, into
a new folder ``DIR``:

- ``DIR/hoerer/`` (what the listener gets): 24 blind-numbered loops ``REF.wav``, ``E01 ... E17``
  (16 keyword ends + the byte-identical twin of ``REF``), ``K01 ... K06`` (combined prompts),
  plus ``Anleitung.md`` and ``Antwortbogen.md``. No keyword, prompt or key is in this folder.
- ``DIR/lead/`` (lead only): ``Schluessel.md`` (decode table, gains) and ``Vorcheck.md`` (the
  number pre-check of section 3 next to the plan's expectations; failed rows are marked).

Every file is 4 bars at 136 BPM with one hit per bar (1.765 s), mono 48 kHz / 24 bit, 3 ms
raised-cosine fade at the end of each bar. Level: ``REF`` peaks at :data:`REF_PEAK_DBFS`, every
other file is matched to the ``REF`` onset RMS (0-100 ms), peaks are asserted <= -0.3 dBFS. The
blind numbers come from :func:`audio_engine.listening_test3.blind_order` (SHA-256 of seed,
block, index; no RNG state, no clock), so the same code gives byte-identical files.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .dsp import highpass_cascade, raised_cosine, rbj_lowpass
from .io import encode_wav, wav_samples
from .kick import render_kick
from .listening_test3 import BLIND_SEED, blind_order, onset_rms_db, peak_dbfs
from .prompt import parse_prompt

BPM = 136
BARS = 4
SAMPLE_RATE = 48000
BIT_DEPTH = 24
CUT_FADE_MS = 3.0
REF_PEAK_DBFS = -7.0
CEILING_DBFS = -0.3
KEYWORDS = ("sub", "punch", "click", "bite", "tail", "drive", "wums", "bright")

# Listener-visible words that would reveal the key. Used by the tests; kept here so the list
# sits next to the data it guards.
FORBIDDEN_IN_LISTENER = (*KEYWORDS, "kurz", "lang", "dunkel", "hell", "sauber", "note", "prompt",
                         "dense", "seed")

# (id, prompt, expected answer word and sign vs REF; plan section 9). Hypotheses, not results.
ENDS: list[tuple[str, str, str]] = [
    ("S1", "sub:0", "Tiefbass weniger (Koerper may come up)"),
    ("S2", "sub:2", "Tiefbass mehr"),
    ("P1", "punch:0", "Koerper weniger"),
    ("P2", "punch:2", "Koerper mehr"),
    ("C0", "click:0", "Klick weniger"),
    ("C2", "click:2", "Klick mehr"),
    ("B1", "bite:0", "Hoehe vom Klick tiefer (WEAK: 'nein' plausible)"),
    ("B2", "bite:2", "Hoehe vom Klick hoeher (WEAK: 'nein' plausible)"),
    ("T1", "tail:0", "Laenge kuerzer"),
    ("T2", "tail:2", "Laenge laenger"),
    ("D1", "drive:0", "Saettigung weniger (also level/transient; 'Lautstaerke' or 'etwas anderes' "
                      "counts as audible)"),
    ("D2", "drive:2", "Saettigung mehr"),
    ("W1", "wums:1", "Anschlag-Druck mehr"),
    ("W2", "wums:2", "Anschlag-Druck mehr als W1"),
    ("H1", "bright:0", "Helligkeit insgesamt weniger"),
    ("H2", "bright:2", "Helligkeit insgesamt mehr (also lowers Koerper)"),
]
TWIN = ("Z", "", "nein (control: byte copy of REF)")
COMBINED: list[tuple[str, str]] = [
    ("C1", "sub:1.5, punch:1.2, dunkel, note:Am"),
    ("C2", "kurz, punch:1.2, click:1.2"),
    ("C3", "sub:1.5, lang, dunkel, click:0.5"),
    ("C4", "punch:1.3, click:1.3, drive:1.2, wums:1"),
    ("C5", "drive:1.3, bite:1.5, wums:1"),
    ("C6", "sub:1.7, tail:1.5, note:31"),
]
BLOCK_SINGLE, BLOCK_COMBO = "kw-single", "kw-combo"


# --- measures (plan section 2 / vocabulary section 6; own implementation, numpy + engine biquads)


def _onset(x: np.ndarray) -> int:
    return int(np.argmax(np.abs(x) >= 0.1 * np.max(np.abs(x))))


def _db(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def _rms(x: np.ndarray) -> float:
    return math.sqrt(float(np.mean(x**2)))


def _energy_share(seg: np.ndarray, lo: float, hi: float | None) -> float:
    spec = np.abs(np.fft.rfft(seg)) ** 2
    freq = np.fft.rfftfreq(len(seg), 1.0 / SAMPLE_RATE)
    mask = (freq >= lo) & (freq < (hi if hi is not None else 1e12))
    return float(spec[mask].sum() / spec.sum())


def measures(x: np.ndarray, f0_hz: float) -> dict[str, float | None]:
    sr, on = SAMPLE_RATE, _onset(x)
    ms = lambda t: round(t * sr / 1000.0)  # noqa: E731
    win100 = x[on : on + ms(100)]
    out: dict[str, float | None] = {
        "crest": _db(float(np.max(np.abs(win100))) / _rms(win100)),
        "sub": 1.0 - _energy_share(x, 100.0, None),
        "sub150": 1.0 - _energy_share(x[on : on + ms(150)], 100.0, None),
    }
    band = rbj_lowpass(rbj_lowpass(highpass_cascade(x, sr, 80.0), sr, 300.0), sr, 300.0)
    out["body"] = _db(_rms(band[on + ms(5) : on + ms(80)]))
    out["on1k"] = 1.0 - _energy_share(x[on : on + ms(10)], 0.0, 1000.0)
    hi = highpass_cascade(x, sr, 1000.0)[on : on + ms(15)]
    out["clickdb"] = _db(_rms(hi))
    spec = np.abs(np.fft.rfft(hi)) ** 2
    freq = np.fft.rfftfreq(len(hi), 1.0 / sr)
    out["clickcent"] = float((spec * freq).sum() / spec.sum())
    frame = ms(5)
    n = (len(x) - on) // frame
    env = np.array([_rms(x[on + i * frame : on + (i + 1) * frame]) for i in range(n)])
    peak_i = int(np.argmax(env))
    below = np.flatnonzero(env[peak_i:] <= env[peak_i] * 10.0 ** (-40.0 / 20.0))
    out["d40"] = float((peak_i + int(below[0])) * 5) if len(below) else None
    seg = x[ms(100) : ms(300)] * np.hanning(ms(300) - ms(100))
    spec = np.abs(np.fft.rfft(seg)) ** 2
    df = sr / len(seg)

    def band_power(f: float) -> float:
        k = round(f / df)
        return float(spec[max(k - 3, 0) : k + 4].sum())

    out["harm"] = sum(band_power(m * f0_hz) for m in range(2, 9)) / band_power(f0_hz)
    return out


# --- rendering ----------------------------------------------------------------------------------


def bar_samples() -> int:
    return round(60.0 / BPM * 4.0 * SAMPLE_RATE)


def build_loop(hit: np.ndarray, gain_db: float) -> np.ndarray:
    """One hit per bar for 4 bars, each bar ends with a 3 ms cosine fade, times the gain."""
    bar = bar_samples()
    fade = round(CUT_FADE_MS / 1000.0 * SAMPLE_RATE)
    out = np.zeros(bar * BARS)
    seg = np.zeros(bar)
    used = min(len(hit), bar)
    seg[:used] = hit[:used]
    seg[-fade:] *= raised_cosine(fade, rising=False)
    for i in range(BARS):
        out[i * bar : (i + 1) * bar] = seg * 10.0 ** (gain_db / 20.0)
    return out


def _onset_rms_float(x: np.ndarray) -> float:
    on = _onset(x)
    return _db(_rms(x[on : on + round(0.1 * SAMPLE_RATE)]))


@dataclass
class Item:
    ident: str  # plan id (S1, ..., C6, Z) or "REF"
    prompt: str
    expected: str
    hit: np.ndarray
    f0_hz: float
    metrics: dict[str, float | None]
    gain_db: float = 0.0
    name: str = ""  # blind file stem
    wav: bytes = b""


def _render(prompt: str, ident: str, expected: str) -> Item:
    parsed = parse_prompt(prompt)
    hit, resolved = render_kick(parsed.params)
    f0 = float(resolved["pitch_end_hz"])
    return Item(ident, prompt, expected, hit, f0, measures(hit, f0))


def render_package() -> list[Item]:
    """All 24 files, levelled and named. The order of the list is REF, E01.., K01.."""
    ref = _render("", "REF", "reference")
    pre = REF_PEAK_DBFS - 20.0 * math.log10(float(np.max(np.abs(ref.hit))))
    ref.gain_db, ref.name = pre, "REF"
    ref_rms = _onset_rms_float(ref.hit)

    singles = [_render(p, i, e) for i, p, e in ENDS]
    twin = Item(TWIN[0], "", TWIN[2], ref.hit, ref.f0_hz, ref.metrics, pre)
    singles.append(twin)
    combos = [_render(p, i, f"closer to 'mein Kick' than REF? (no prediction), {p}")
              for i, p in COMBINED]
    for it in (*singles, *combos):
        if it is not twin:
            it.gain_db = pre + ref_rms - _onset_rms_float(it.hit)
    for block, items, tag in ((BLOCK_SINGLE, singles, "E"), (BLOCK_COMBO, combos, "K")):
        position = blind_order(block, len(items), BLIND_SEED)
        for i, it in enumerate(items):
            it.name = f"{tag}{position[i] + 1:02d}"
    out = [ref, *sorted(singles, key=lambda t: t.name), *sorted(combos, key=lambda t: t.name)]
    for it in out:
        it.wav = encode_wav(build_loop(it.hit, it.gain_db), SAMPLE_RATE, BIT_DEPTH)
    twin.wav = ref.wav  # a byte copy, not a re-render
    for it in out:
        peak = peak_dbfs(wav_samples(it.wav))
        if peak > CEILING_DBFS:
            raise RuntimeError(f"{it.name}: peak {peak:.2f} dBFS exceeds {CEILING_DBFS}")
    return out


# --- lead pre-check (plan section 3) ------------------------------------------------------------

# keyword -> (measure, direction as w rises, minimum step, plan's observed w=0/1/2 values)
# A step "passes" when it moves in the direction by at least the minimum. For bite and bright
# only the w=2 step has a size minimum (plan: "w = 0 only needs to be lower"); wums has no w=0
# file (w=0 is REF). Plan values are copied from section 3; None = not reached / not in the plan.
CHECKS: dict[str, list[tuple[str, int, float, tuple[float | None, ...]]]] = {
    "sub": [("sub150", +1, 0.10, (0.431, 0.556, 0.713)), ("body", -1, 0.4, (-2.82, -3.24, -4.64))],
    "punch": [("body", +1, 0.4, (-4.13, -3.24, -2.71)), ("sub", -1, 0.08, (0.725, 0.623, 0.529))],
    "click": [("clickdb", +1, 1.5, (-21.62, -19.49, -16.07)),
              ("on1k", +1, 0.008, (0.0207, 0.0298, 0.0575))],
    "bite": [("clickcent", +1, 0.0, (2436, 2582, 3201))],
    "tail": [("d40", +1, 80.0, (350, 450, None))],
    "drive": [("crest", -1, 0.3, (8.80, 2.19, 1.74))],
    "wums": [("crest", -1, 0.3, (2.19, 0.96, 0.67))],
    "bright": [("clickcent", +1, 0.0, (2027, 2582, 2900)),
               ("on1k", +1, 0.008, (0.0188, 0.0298, 0.0448))],
}
PLAN_NOTES = {
    "click": "plan: w=0 on1k step inside the seed range (marginal)",
    "bite": "plan: WEAK, only the centroid moves; 'kein Unterschied' plausible",
    "bright": "plan: w=0 on1k step marginal",
    "wums": "plan: its own values 0.96 -> 0.67 dB are a step of 0.29, just under the 0.3 minimum",
    "drive": "plan: w=0 is a very large jump (6.6 dB quieter at equal peak)",
}
EXTRA_MIN = {("bite", "clickcent", 2): 300.0, ("bright", "clickcent", 2): 300.0}


def _steps(kw: str, by_prompt: dict[str, Item]) -> list[tuple[str, int, tuple[Item, Item]]]:
    ref = by_prompt[""]
    if kw == "wums":
        trio = (ref, by_prompt["wums:1"], by_prompt["wums:2"])
    else:
        trio = (by_prompt[f"{kw}:0"], ref, by_prompt[f"{kw}:2"])
    return [("w0->1", 1, (trio[0], trio[1])), ("w1->2", 2, (trio[1], trio[2]))]


def precheck(items: list[Item]) -> tuple[str, bool]:
    """Markdown report of the plan-section-3 numbers, and whether every expectation held."""
    by_prompt = {it.prompt: it for it in items if it.ident != "Z"}
    lines = [
        "# Vorcheck Stichwort-Hoerpaket (nur Lead)",
        "",
        "Zahlen beschreiben Signale, nichts Gehoertes. Messungen: eigene Implementierung "
        "(`listening_keywords.measures`, Biquad-Filter der Engine), Seed = Preset-Seed. "
        "`Plan` = Beobachtung im Plan (Abschnitt 3, anderes Skript: Abweichungen in der "
        "Groessenordnung von Fenster-/Filterdetails sind nicht automatisch ein Fehler). "
        "`Pass` = Richtung stimmt UND Schritt >= Mindestgroesse; ein `FAIL` ist ein "
        "Parser-/Mapping-Befund, der VOR dem Hoeren gemeldet wird (nicht hier korrigiert).",
        "",
        "| Keyword | Mass | w0 (this / plan) | w1 (this / plan) | w2 (this / plan) | "
        "Schritt 0>1 | Schritt 1>2 | Verdikt |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    all_ok = True
    for kw, checks in CHECKS.items():
        steps = _steps(kw, by_prompt)
        for measure, direction, minimum, plan in checks:
            cells, verdicts = [], []
            for _label, which, (a, b) in steps:
                va, vb = a.metrics[measure], b.metrics[measure]
                need = EXTRA_MIN.get((kw, measure, which), minimum)
                if kw in ("bite", "bright") and measure == "clickcent" and which == 1:
                    need = 0.0
                if kw == "wums" and which == 1:
                    need = minimum
                if va is None and vb is None:
                    ok, delta = False, "n/a"
                elif vb is None:  # not reached inside the file = longer than the file
                    ok, delta = direction > 0, "not reached"
                elif va is None:
                    ok, delta = direction < 0, "n/a"
                else:
                    d = vb - va
                    ok = d * direction > 0 and abs(d) >= need
                    delta = f"{d:+.4g}"
                verdicts.append(ok)
                cells.append(f"{delta} (min {need:g}) {'pass' if ok else 'FAIL'}")
            all_ok &= all(verdicts)
            vs = [steps[0][2][0], steps[0][2][1], steps[1][2][1]]
            show = [f"{v.metrics[measure]:.4g}" if v.metrics[measure] is not None else "not reached"
                    for v in vs]
            plans = ["-" if p is None else f"{p:g}" for p in plan]
            lines.append(
                f"| `{kw}` | {measure} | {show[0]} / {plans[0]} | {show[1]} / {plans[1]} | "
                f"{show[2]} / {plans[2]} | {cells[0]} | {cells[1]} | "
                f"{'pass' if all(verdicts) else 'FAIL'} |"
            )
    lines += ["", "Hinweise aus dem Plan:", ""]
    lines += [f"- `{k}`: {v}" for k, v in PLAN_NOTES.items()]
    lines += ["", "## Kombinierte Prompts (Messwerte, keine Pass-Regel)", "",
              "| Datei | ID | Prompt | sub150 | body dB | clickdb dB | clickcent | d40 | crest |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for it in items:
        if it.name.startswith("K"):
            m = it.metrics
            d40 = "not reached" if m["d40"] is None else f"{m['d40']:g}"
            lines.append(f"| {it.name} | {it.ident} | `{it.prompt}` | {m['sub150']:.3f} | "
                         f"{m['body']:.2f} | {m['clickdb']:.2f} | {m['clickcent']:.0f} | {d40} | "
                         f"{m['crest']:.2f} |")
    twin = next(it for it in items if it.ident == "Z")
    ref = items[0]
    lines += ["", f"Kontrolle: Zwilling {twin.name} byte-gleich mit REF: {twin.wav == ref.wav}.",
              ""]
    return "\n".join(lines), all_ok


# --- texts --------------------------------------------------------------------------------------

ANLEITUNG = """# Hoercheck: Kick-Varianten (ca. 13 Minuten)

**Aufbau (2 Minuten):** Alle `.wav` des Pakets in eine Audiospur laden, Warp aus, Projekttempo 136 BPM, jede Datei als Loop (ein Kick pro Takt). Gleiche Lautstaerke an der Spur, nichts auf dem Master. Die Dateinamen sind anonym. `REF.wav` ist dein Vergleichskick. Eine `Schluessel`-Datei bekommst du nicht; sie liegt beim Lead.

**So gehst du vor (fuer jede Datei `E01` bis `E17`, dann `K01` bis `K06`):**
1. Hoere `REF`, dann die Datei, dann nochmal `REF`. Beliebig oft wiederholen.
2. Antworte im Antwortbogen: **Hoerst du einen Unterschied zu `REF`?** (ja / nein / unsicher). "Nein" ist eine gueltige Antwort.
3. Wenn ja: **Was ist der Hauptunterschied?** Kreuze hoechstens zwei Woerter aus der Liste an und sag jeweils **mehr** oder **weniger** als `REF`.

**Wortliste (gilt fuer jede Datei gleich):** Tiefbass · Koerper (Mitten) · Klick · Hoehe vom Klick · Laenge des Ausklangs · Saettigung · Anschlag-Druck · Helligkeit insgesamt · Lautstaerke · etwas anderes (ein Wort).

**Fuer `K01` bis `K06` zusaetzlich:** **Ist die Datei naeher an "meinem Kick" als `REF`?** (ja / gleich / nein).

**Wichtig:** Rate nicht. Wenn du nichts hoerst, schreib "nein". Du musst nicht jede Datei begruenden. Nicht zwischendurch in den Schluessel schauen (es gibt keinen). Am Ende: Welche Datei ist am ehesten "mein Kick", oder reicht `REF`?
"""  # noqa: E501


def antwortbogen(names: list[str]) -> str:
    lines = ["# Antwortbogen Hoercheck Kick-Varianten", "",
             "Datum: ____   Hoerumgebung (Kopfhoerer / Monitore): ____   "
             "Pegel gleich gelassen: ja / nein", "",
             "| Datei | Unterschied zu REF? (ja/nein/unsicher) | Hauptunterschied (max. 2 Woerter "
             "aus der Liste) | mehr / weniger | naeher an \"meinem Kick\" als REF? (nur K) |",
             "| --- | --- | --- | --- | --- |"]
    for n in names:
        lines.append(f"| {n} | ___ | ___ | ___ | {'___' if n.startswith('K') else '-'} |")
    lines += ["", 'Gesamt: Welche Datei ist am ehesten "mein Kick"? ____  (oder: "REF reicht")',
              "", "Anmerkungen: ____", ""]
    return "\n".join(lines)


def key_text(items: list[Item]) -> str:
    lines = [
        "# Schluessel Stichwort-Hoerpaket (nur Lead, NICHT an den Hoerer)",
        "",
        f"Aufbau: {BARS} Takte, {BPM} BPM, ein Schlag pro Takt, mono, 48 kHz, 24 bit; "
        f"Nummern per SHA-256-Mischung (Seed {BLIND_SEED}, Bloecke `{BLOCK_SINGLE}` / "
        f"`{BLOCK_COMBO}`). REF-Spitze {REF_PEAK_DBFS:g} dBFS, alle anderen auf REF-Onset-RMS "
        "(0-100 ms) angeglichen. Erwartete Antworten sind Hypothesen aus dem Plan.",
        "",
        "| Datei | ID | Prompt | Erwartung | Gain dB | Spitze dBFS | RMS 0-100 ms dBFS |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for it in items:
        ints = wav_samples(it.wav)
        prompt = f"`{it.prompt}`" if it.prompt else "(leer = dense)"
        lines.append(f"| `{it.name}.wav` | {it.ident} | {prompt} | {it.expected} | "
                     f"{it.gain_db:+.2f} | {peak_dbfs(ints):.2f} | {onset_rms_db(ints):.2f} |")
    lines += ["", "Lesehilfe: siehe Plan Abschnitt 9 (`docs/research/2026-11-02_keyword-prompt-"
              "listening-plan.md`). Kontrolle Z muss mit 'nein' beantwortet werden.", ""]
    return "\n".join(lines)


def write_package(out: str | Path) -> dict[str, Any]:
    root = Path(out)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"{root} is not empty; choose a new folder")
    listener, lead = root / "hoerer", root / "lead"
    listener.mkdir(parents=True)
    lead.mkdir()
    items = render_package()
    report, ok = precheck(items)
    for it in items:
        (listener / f"{it.name}.wav").write_bytes(it.wav)
    (listener / "Anleitung.md").write_text(ANLEITUNG, encoding="utf-8")
    (listener / "Antwortbogen.md").write_text(
        antwortbogen([it.name for it in items if it.name != "REF"]), encoding="utf-8")
    (lead / "Schluessel.md").write_text(key_text(items), encoding="utf-8")
    (lead / "Vorcheck.md").write_text(report, encoding="utf-8")
    return {"files": len(items), "precheck_all_pass": ok,
            "bytes": {it.name: len(it.wav) for it in items}, "report": report}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the kick keyword listening package.")
    parser.add_argument("--out", required=True, help="new, empty folder outside the repo")
    args = parser.parse_args(argv)
    result = write_package(args.out)
    print(result["report"])
    print(json.dumps({k: v for k, v in result.items() if k != "report"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
