"""Goa melodic voices (lead, arp, pad, pluck) as deterministic multitrack MIDI (#393, D-027).

The Goa plugin owns only the melodic elements; kick, bass and percussion come from the
existing engines. The output is MIDI for Live's own instruments (D-026); nothing here is
tested in Live, rendered to audio or listened to. Every value below is a default that can
be changed; no measured value is claimed to be "the Goa sound".

CLI::

    python -m audio_engine.goa_melody --out DIR --seed N [--bpm 145] [--root A]
        [--scale phrygian] [--length 4] [--density 0.6 | lead=0.5,arp=1]
        [--register 0 | lead=1,pad=-1] [--arp-pattern up] [--progression 0,5,6,4]
        [--voices lead,arp,pad,pluck] [--sections "Intro:8:0.3:pad,Peak:16:1:lead+arp"]

writes ``DIR/goa_melody_seed<N>_<BPM>bpm.mid`` and ``DIR/README.md``; an existing target is
refused and nothing is written.

Options (all validated; out-of-range values raise ValueError, nothing is clamped)
---------------------------------------------------------------------------------
* ``seed`` int >= 0: picks which grid steps carry notes and the lead/pluck pitch walk.
* ``bpm`` 135-150 (default 145), ``root`` A-G with optional ``#``/``b``, ``scale`` one of
  ``SCALES`` (every pitch of every voice is a scale tone).
* ``length`` 1-16: bars of one phrase (a pattern); it repeats inside each section.
* ``density`` 0-1, global or per voice. Notes per bar: lead ``round(d * 8)``, pluck and arp
  ``round(d * 16)`` (16th grid), so density 0 is silent. Pad: chord length in bars is
  ``4 - round(3 * d)`` (4 .. 1); the pad is never silent.
* ``register`` -2..2 octaves, global or per voice, added to the window of each voice
  (lead 60-83, arp 57-80, pad 48-59, pluck 36-59 before the shift; MIDI note numbers).
* ``arp_pattern``: ``up``, ``down``, ``updown``, ``random`` (step ``i`` of the bar plays chord
  tone ``i`` of the pattern; density only removes steps).
* ``progression``: scale degrees 0-6 (one chord per bar for the arp; one per chord for the
  pad); chords are stacked thirds on the degree.
* ``voices``: which of lead, arp, pad, pluck get a track.
* ``sections``: list of ``{"name", "bars", "energy", "voices"}``. Section energy 0-1 does two
  things: the density used in that section is ``density * (0.5 + 0.5 * energy)``, and the
  MIDI writer scales velocities by ``0.70 + 0.30 * energy`` (arrangement_midi rule).
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from audio_engine import arrangement_midi

VOICES = ("lead", "arp", "pad", "pluck")
SCALES: dict[str, tuple[int, ...]] = {
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "phrygian_dominant": (0, 1, 4, 5, 7, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
}
ARP_PATTERNS = ("up", "down", "updown", "random")
PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
DEFAULT_BPM = 145.0
MIN_BPM, MAX_BPM = 135.0, 150.0
MIN_LENGTH, MAX_LENGTH = 1, 16
MIN_REGISTER, MAX_REGISTER = -2, 2
DEFAULT_DENSITY = {"lead": 0.6, "arp": 1.0, "pad": 0.0, "pluck": 0.5}
DEFAULT_PROGRESSION = (0, 5, 6, 4)
DEFAULT_SECTIONS: tuple[dict[str, Any], ...] = (
    {"name": "Intro", "bars": 8, "energy": 0.3, "voices": ["pad"]},
    {"name": "Build", "bars": 8, "energy": 0.6, "voices": ["pad", "arp", "pluck"]},
    {"name": "Peak", "bars": 16, "energy": 1.0, "voices": ["lead", "arp", "pad", "pluck"]},
    {"name": "Break", "bars": 8, "energy": 0.2, "voices": ["pad", "lead"]},
    {"name": "Peak2", "bars": 16, "energy": 1.0, "voices": ["lead", "arp", "pad", "pluck"]},
)
# (window start, window size in semitones, base velocity, accent bonus on beats)
WINDOW = {"lead": (60, 24, 100, 14), "arp": (57, 24, 88, 10),
          "pad": (48, 12, 78, 0), "pluck": (36, 24, 96, 14)}
MAX_PER_BAR = {"lead": 8, "arp": 16, "pluck": 16}
GATE_BEATS = {"arp": 0.2, "pluck": 0.2}
LEAD_MAX_BEATS = 2.0
PAD_GAP_BEATS = 0.0625


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _count(d: float, n: int) -> int:
    return int(d * n + 0.5)


def _rng(seed: int, tag: str) -> random.Random:
    digest = hashlib.sha256(f"goa_melody:{seed}:{tag}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def root_pc(root: str) -> int:
    if not isinstance(root, str) or len(root) not in (1, 2) or root[0] not in PC \
            or (len(root) == 2 and root[1] not in "#b"):
        raise ValueError("root must be A-G with an optional # or b")
    pc = PC[root[0]] + (1 if root.endswith("#") else -1 if root.endswith("b") else 0)
    return pc % 12


# ---------------------------------------------------------------- options

def _per_voice(value: Any, name: str, default: Mapping[str, Any] | Any, check) -> dict[str, Any]:
    out = dict(default) if isinstance(default, Mapping) else {v: default for v in VOICES}
    if isinstance(value, Mapping):
        unknown = set(value) - set(VOICES)
        if unknown:
            raise ValueError(f"{name}: unknown voices {sorted(unknown)}")
        for k, v in value.items():
            out[k] = v
    elif value is not None:
        out = {v: value for v in VOICES}
    for k, v in out.items():
        check(k, v)
    return out


def _check_density(k: str, v: Any) -> None:
    if not _is_num(v) or not 0 <= v <= 1:
        raise ValueError(f"density[{k}] must be a number 0-1")


def _check_register(k: str, v: Any) -> None:
    if not _is_int(v) or not MIN_REGISTER <= v <= MAX_REGISTER:
        raise ValueError(f"register[{k}] must be an integer {MIN_REGISTER}..{MAX_REGISTER}")


def normalise(params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and fill defaults. Returns every option with its chosen value."""
    known = {"seed", "bpm", "root", "scale", "length", "density", "register", "arp_pattern",
             "progression", "voices", "sections", "title"}
    extra = set(params) - known
    if extra:
        raise ValueError(f"unknown options {sorted(extra)}")
    seed = params.get("seed", 0)
    if not _is_int(seed) or seed < 0:
        raise ValueError("seed must be an integer >= 0")
    bpm = params.get("bpm", DEFAULT_BPM)
    if not _is_num(bpm) or not MIN_BPM <= bpm <= MAX_BPM:
        raise ValueError(f"bpm must be a number {MIN_BPM:g}-{MAX_BPM:g}")
    root = params.get("root", "A")
    root_pc(root)
    scale = params.get("scale", "phrygian")
    if scale not in SCALES:
        raise ValueError(f"scale must be one of {sorted(SCALES)}")
    length = params.get("length", 4)
    if not _is_int(length) or not MIN_LENGTH <= length <= MAX_LENGTH:
        raise ValueError(f"length must be an integer {MIN_LENGTH}-{MAX_LENGTH} bars")
    density = _per_voice(params.get("density"), "density", DEFAULT_DENSITY, _check_density)
    register = _per_voice(params.get("register"), "register", 0, _check_register)
    arp_pattern = params.get("arp_pattern", "up")
    if arp_pattern not in ARP_PATTERNS:
        raise ValueError(f"arp_pattern must be one of {list(ARP_PATTERNS)}")
    prog = params.get("progression", DEFAULT_PROGRESSION)
    if not isinstance(prog, Sequence) or isinstance(prog, str) or not 1 <= len(prog) <= 16 \
            or not all(_is_int(x) and 0 <= x <= 6 for x in prog):
        raise ValueError("progression must be 1-16 scale degrees, each an integer 0-6")
    voices = params.get("voices", list(VOICES))
    if not isinstance(voices, Sequence) or isinstance(voices, str) or not voices \
            or any(v not in VOICES for v in voices) or len(set(voices)) != len(voices):
        raise ValueError(f"voices must be a non-empty list of distinct names from {list(VOICES)}")
    voices = [v for v in VOICES if v in voices]  # fixed track order
    title = params.get("title", "Goa melody")
    sections = params.get("sections")
    if sections is None:
        sections = [dict(s, voices=list(s["voices"])) for s in DEFAULT_SECTIONS]
    if not isinstance(sections, Sequence) or isinstance(sections, str) or not sections:
        raise ValueError("sections must be a non-empty list")
    secs = []
    for i, s in enumerate(sections):
        if not isinstance(s, Mapping) or set(s) != {"name", "bars", "energy", "voices"}:
            raise ValueError(f"section {i}: needs exactly name, bars, energy, voices")
        sv = s["voices"]
        if not isinstance(sv, Sequence) or isinstance(sv, str) \
                or any(v not in VOICES for v in sv) or len(set(sv)) != len(sv):
            raise ValueError(f"section {i}: voices must be distinct names from {list(VOICES)}")
        if not _is_num(s["energy"]) or not 0 <= s["energy"] <= 1:
            raise ValueError(f"section {i}: energy must be a number 0-1")
        secs.append({"name": s["name"], "bars": s["bars"], "energy": float(s["energy"]),
                     "voices": [v for v in voices if v in sv]})
    return {"seed": seed, "bpm": float(bpm), "root": root, "scale": scale, "length": length,
            "density": density, "register": register, "arp_pattern": arp_pattern,
            "progression": list(prog), "voices": voices, "sections": secs, "title": title}


# ---------------------------------------------------------------- generators

def _window(voice: str, register: int) -> tuple[int, int]:
    lo, span = WINDOW[voice][0] + 12 * register, WINDOW[voice][1]
    return lo, lo + span  # half open


def _pool(voice: str, register: int, rpc: int, scale: str) -> list[int]:
    lo, hi = _window(voice, register)
    pcs = {(rpc + o) % 12 for o in SCALES[scale]}
    return [p for p in range(lo, hi) if p % 12 in pcs]


def _chord_pcs(rpc: int, scale: str, degree: int) -> set[int]:
    s = SCALES[scale]
    return {(rpc + s[(degree + k) % 7]) % 12 for k in (0, 2, 4)}


def _chord_tones(voice: str, register: int, rpc: int, scale: str, degree: int) -> list[int]:
    lo, hi = _window(voice, register)
    pcs = _chord_pcs(rpc, scale, degree)
    return [p for p in range(lo, hi) if p % 12 in pcs]


def _positions(rng: random.Random, bars: int, per_bar_max: int, d: float) -> list[int]:
    """Absolute 16th-step indices (bar * 16 + step). Always draws 16 numbers per bar."""
    n = _count(d, per_bar_max)
    out: list[int] = []
    for b in range(bars):
        keyed = []
        for i in range(16):
            w = 4.0 if i % 4 == 0 else 2.0 if i % 2 == 0 else 1.0
            keyed.append((-(rng.random() ** (1.0 / w)), i))
        keyed.sort()
        out += sorted(b * 16 + i for _, i in keyed[:n])
    return out


def _velocity(voice: str, step: int) -> int:
    base, bonus = WINDOW[voice][2], WINDOW[voice][3]
    return min(127, base + (bonus if step % 4 == 0 else 0))


def _walk(pool: list[int], count: int, rng: random.Random, rpc: int) -> list[int]:
    roots = [i for i, p in enumerate(pool) if p % 12 == rpc] or [0]
    idx = roots[0]
    out = []
    for _ in range(count):
        r = rng.random()
        if r < 0.3:
            idx = roots[int(rng.random() * len(roots)) % len(roots)]
        else:
            idx += (-2, -1, -1, 0, 1, 1, 2)[int(rng.random() * 7) % 7]
        idx = max(0, min(len(pool) - 1, idx))
        out.append(pool[idx])
    return out


def _note(pitch: int, start: float, dur: float, vel: int) -> dict[str, Any]:
    return {"pitch": pitch, "start": start, "duration": dur, "velocity": vel}


def _line_voice(voice: str, o: Mapping[str, Any], d: float) -> list[dict[str, Any]]:
    rpc = root_pc(o["root"])
    pool = _pool(voice, o["register"][voice], rpc, o["scale"])
    bars = o["length"]
    pos = _positions(_rng(o["seed"], voice + ":pos"), bars, MAX_PER_BAR[voice], d)
    pitches = _walk(pool, len(pos), _rng(o["seed"], voice + ":pitch"), rpc)
    notes = []
    end = bars * 4.0
    for k, (p, pitch) in enumerate(zip(pos, pitches, strict=True)):
        start = p * 0.25
        if voice == "lead":
            nxt = pos[k + 1] * 0.25 if k + 1 < len(pos) else end
            dur = min(nxt - start, LEAD_MAX_BEATS)
        else:
            dur = GATE_BEATS[voice]
        notes.append(_note(pitch, start, dur, _velocity(voice, p % 16)))
    return notes


def _arp(o: Mapping[str, Any], d: float) -> list[dict[str, Any]]:
    rpc = root_pc(o["root"])
    bars = o["length"]
    pos = _positions(_rng(o["seed"], "arp:pos"), bars, 16, d)
    rng = _rng(o["seed"], "arp:pitch")
    notes = []
    for p in pos:
        bar, step = divmod(p, 16)
        degree = o["progression"][bar % len(o["progression"])]
        tones = _chord_tones("arp", o["register"]["arp"], rpc, o["scale"], degree)
        pat = o["arp_pattern"]
        if pat == "up":
            pitch = tones[step % len(tones)]
        elif pat == "down":
            pitch = tones[::-1][step % len(tones)]
        elif pat == "updown":
            seq = tones + tones[-2:0:-1]
            pitch = seq[step % len(seq)]
        else:
            pitch = tones[int(rng.random() * len(tones)) % len(tones)]
        notes.append(_note(pitch, p * 0.25, GATE_BEATS["arp"], _velocity("arp", step)))
    return notes


def pad_chord_bars(d: float) -> int:
    return 4 - _count(d, 3)


def _pad(o: Mapping[str, Any], d: float) -> list[dict[str, Any]]:
    rpc = root_pc(o["root"])
    cb = pad_chord_bars(d)
    notes = []
    bar, i = 0, 0
    while bar < o["length"]:
        span = min(cb, o["length"] - bar)
        degree = o["progression"][i % len(o["progression"])]
        for pitch in _chord_tones("pad", o["register"]["pad"], rpc, o["scale"], degree):
            notes.append(_note(pitch, bar * 4.0, span * 4.0 - PAD_GAP_BEATS,
                               _velocity("pad", 0)))
        bar += span
        i += 1
    return notes


def voice_pattern(voice: str, o: Mapping[str, Any], energy: float) -> dict[str, Any]:
    """One native pattern for ``voice`` at section ``energy`` (``o`` from ``normalise``)."""
    d = o["density"][voice] * (0.5 + 0.5 * energy)
    if voice in ("lead", "pluck"):
        notes = _line_voice(voice, o, d)
    elif voice == "arp":
        notes = _arp(o, d)
    else:
        notes = _pad(o, d)
    return {"length_beats": o["length"] * 4, "notes": notes}


def build_arrangement(**params: Any) -> dict[str, Any]:
    o = normalise(params)
    cache: dict[tuple[str, float], dict[str, Any]] = {}

    def pat(v: str, e: float) -> dict[str, Any]:
        if (v, e) not in cache:
            cache[(v, e)] = voice_pattern(v, o, e)
        return cache[(v, e)]

    sections = []
    for s in o["sections"]:
        active = [v for v in s["voices"] if v in o["voices"]]
        sections.append({"name": s["name"], "bars": s["bars"], "energy": s["energy"],
                         "elements": active,
                         "patterns": {v: pat(v, s["energy"]) for v in active}})
    arr = {"format": arrangement_midi.FORMAT_NAME, "version": arrangement_midi.FORMAT_VERSION,
           "title": o["title"], "tempo": o["bpm"],
           "key": {"root": o["root"], "scale": o["scale"]},
           "elements": [{"name": v, "pattern": pat(v, 1.0)} for v in o["voices"]],
           "sections": sections}
    try:
        arrangement_midi.validate_arrangement(arr)
    except arrangement_midi.ArrangementError as exc:
        raise ValueError(str(exc)) from exc
    return arr


def build_midi(**params: Any) -> bytes:
    return arrangement_midi.arrangement_to_midi(build_arrangement(**params))


# ---------------------------------------------------------------- README + files

def full_options(params: Mapping[str, Any]) -> dict[str, Any]:
    return normalise(params)


def render_readme(arr: Mapping[str, Any], mid_name: str, params: Mapping[str, Any]) -> str:
    o = normalise(params)
    notes = arrangement_midi.arrangement_notes(arr)
    L = [
        "# Goa melody (lead, arp, pad, pluck) as MIDI", "",
        f"File: `{mid_name}` (one format-1 MIDI file, one track per voice). Generated by "
        "`python -m audio_engine.goa_melody`; same options and seed give the same bytes.", "",
        "Not tested in Live, not rendered, not listened to. Drag the file into Live and put "
        "your own instrument on each track.", "",
        "## Options used", "",
        f"- seed: {o['seed']}", f"- bpm: {o['bpm']:g}", f"- root: {o['root']}",
        f"- scale: {o['scale']}", f"- length (bars per phrase): {o['length']}",
        f"- arp pattern: {o['arp_pattern']}",
        f"- progression (scale degrees): {', '.join(map(str, o['progression']))}",
        f"- voices: {', '.join(o['voices'])}", "",
        "| voice | density | register (octaves) | window (MIDI, start-end) |",
        "| --- | --- | --- | --- |",
    ]
    for v in o["voices"]:
        lo, hi = _window(v, o["register"][v])
        L.append(f"| {v} | {o['density'][v]:g} | {o['register'][v]} | {lo}-{hi - 1} |")
    L += ["", "## Option reference", "",
          "- `--density 0-1` (global or `lead=0.5,arp=1`): notes per bar lead round(d*8), "
          "arp/pluck round(d*16); pad: chord length 4-round(3d) bars (never silent).",
          "- `--register -2..2` octaves (global or per voice).",
          "- `--length 1-16` bars per phrase; `--scale`, `--root`, `--bpm 135-150`.",
          "- `--sections Name:bars:energy:voice+voice,...`: energy 0-1 scales density by "
          "0.5+0.5*energy and velocity by 0.70+0.30*energy.", "",
          "## Sections", "", "| start bar | name | bars | energy | voices |",
          "| --- | --- | --- | --- | --- |"]
    pos = 1
    for s in arr["sections"]:
        L.append(f"| {pos} | {s['name']} | {s['bars']} | {s['energy']:g} | "
                 f"{', '.join(s['elements']) or '-'} |")
        pos += s["bars"]
    L += ["", "## Notes per track", "", "| track | notes |", "| --- | --- |"]
    for v in o["voices"]:
        L.append(f"| {v} | {len(notes[v])} |")
    L.append("")
    return "\n".join(L)


def write_melody(out_dir: str | Path, **params: Any) -> tuple[Path, Path]:
    """Write ``.mid`` and README into ``out_dir``; refuse if either exists (nothing written)."""
    arr = build_arrangement(**params)
    o = normalise(params)
    d = Path(out_dir)
    mid = d / f"goa_melody_seed{o['seed']}_{o['bpm']:g}bpm.mid"
    readme = d / "README.md"
    for p in (mid, readme):
        if p.exists() or p.is_symlink():
            raise FileExistsError(f"{p} already exists; choose another folder (nothing written)")
    data = arrangement_midi.arrangement_to_midi(arr)
    text = render_readme(arr, mid.name, params)
    d.mkdir(parents=True, exist_ok=True)
    with open(mid, "xb") as fh:
        fh.write(data)
    try:
        with open(readme, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except FileExistsError as exc:
        raise FileExistsError(f"{readme} appeared meanwhile; {mid} was written") from exc
    return mid, readme


# ---------------------------------------------------------------- CLI

def _parse_voice_map(text: str, cast, name: str) -> Any:
    if "=" not in text:
        return cast(text)
    out = {}
    for part in text.split(","):
        k, _, v = part.partition("=")
        out[k.strip()] = cast(v)
    if not out:
        raise ValueError(f"{name}: empty")
    return out


def _parse_sections(text: str) -> list[dict[str, Any]]:
    out = []
    for part in text.split(","):
        f = part.split(":")
        if len(f) != 4:
            raise ValueError(f"section {part!r}: expected Name:bars:energy:voice+voice")
        out.append({"name": f[0], "bars": int(f[1]), "energy": float(f[2]),
                    "voices": [v for v in f[3].split("+") if v]})
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m audio_engine.goa_melody",
        description="Goa lead/arp/pad/pluck as multitrack MIDI plus README (not tested in Live)")
    p.add_argument("--out", required=True, help="output folder (created; never overwritten)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--bpm", type=float, default=DEFAULT_BPM)
    p.add_argument("--root", default="A")
    p.add_argument("--scale", choices=sorted(SCALES), default="phrygian")
    p.add_argument("--length", type=int, default=4, help="bars per phrase (1-16)")
    p.add_argument("--density", help="0-1, or voice=value,voice=value")
    p.add_argument("--register", help="octave shift -2..2, or voice=value,...")
    p.add_argument("--arp-pattern", choices=ARP_PATTERNS, default="up")
    p.add_argument("--progression", default=",".join(map(str, DEFAULT_PROGRESSION)),
                   help="comma list of scale degrees 0-6")
    p.add_argument("--voices", default=",".join(VOICES))
    p.add_argument("--sections", help="Name:bars:energy:voice+voice,... (default: built-in plan)")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        params: dict[str, Any] = {
            "seed": a.seed, "bpm": a.bpm, "root": a.root, "scale": a.scale,
            "length": a.length, "arp_pattern": a.arp_pattern,
            "progression": [int(x) for x in a.progression.split(",")],
            "voices": [v for v in a.voices.split(",") if v]}
        if a.density is not None:
            params["density"] = _parse_voice_map(a.density, float, "density")
        if a.register is not None:
            params["register"] = _parse_voice_map(a.register, int, "register")
        if a.sections is not None:
            params["sections"] = _parse_sections(a.sections)
        mid, readme = write_melody(a.out, **params)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"wrote {mid} ({mid.stat().st_size} bytes) and {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
