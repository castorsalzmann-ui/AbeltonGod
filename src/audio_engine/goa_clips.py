"""Goa MIDI clips: one short loop per voice (lead, arp, pad, pluck), like the Acid line (D-035).

D-035 (1): the Goa page generates clips, not a song. A clip is ``bars`` bars (1-16, default
4) of one voice in key/scale/tempo. There are no sections, no energy curve and no song form
here; song form belongs to the arrangement planner (D-033).

Since #570 the notes come from ``goa_cells`` (cell model, rule set N1-N10 of
``docs/research/2026-11-10_klassische-goa-leads-und-melodien.md``): arp, pluck/acid line and
lead repeat one short cell literally, with separate cycles for pitch, accent and slide; the
pad holds root plus fifth; the default progression is the root only. This module keeps the
options, the file layout and the CLI. ``goa_melody`` (random-walk phrases) is unchanged and
still used by ``goa_arrangement``; it is no longer used here.

What the notes encode: an accent is the higher of two velocity levels; a slide is a note
that ends shortly after the next note of the same voice has started (overlap). Whether an
instrument in Live turns these into a filter accent and a glide depends on its settings
(see the README text below); none of it was tested in Live.

A non-default ``progression`` transposes the cell inside the scale per bar
(:func:`bar_chords`: chords spread evenly over the bars; a clip shorter than the progression
holds the first ``bars`` chords). ``arp_pattern`` is still accepted and has no effect: the
cell model has no chord-tone arpeggio.

File layout: ONE format-0 ``.mid`` PER VOICE (one clip per file). Reason: in Live a MIDI
file dropped on a track (or a clip slot) becomes one clip on that track, so the user puts
each voice on the track with the instrument meant for it. Each file has a tempo event (the
bpm the clip was made for), 4/4, a track name and its end-of-track event exactly at
``bars * 4 * 480`` ticks, so the clip loops at the bar line. No note crosses the clip end.

Not tested in Live, not listened to. Nothing here writes to Ableton.

CLI::

    python -m audio_engine.goa_clips --out DIR --seed N [--bars 4] [--bpm 145] [--root A]
        [--scale phrygian] [--density 0.6 | lead=0.5,arp=1] [--register 0 | lead=1,pad=-1]
        [--progression 0] [--voices lead,arp,pad,pluck] [--cell-length auto | 9 | arp=5,lead=11]
        [--lead-mode own|double] [--restart-bars 4] [--grouping displaced|3+3+2|3+3+3+3+4]
        [--pitches lead=5,arp=4,pluck=4] [--accent-cycle auto|3|5] [--slides lead=1,arp=0,pluck=2]
        [--variation on|off] [--velocity 84] [--accent-velocity 120] [--gate 50]
        [--sub-seeds auto | pitch=1,rhythm=2,accent=3,slide=4]

writes ``DIR/goa_<voice>_seed<N>_<BPM>bpm_<bars>bars.mid`` per voice and ``DIR/README.md``.
Existing targets are refused before anything is written.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from audio_engine import goa_cells
from audio_engine.acid_midi import PPQ, Note

VOICES = goa_cells.VOICES
MIN_BARS, MAX_BARS = goa_cells.MIN_BARS, goa_cells.MAX_BARS  # 1, 16
DEFAULT_BARS = goa_cells.DEFAULT_BARS
BAR_TICKS = 4 * PPQ


def normalise(params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and fill defaults (the rules of ``goa_cells.normalise``).

    ``sections``, ``energy``, ``title`` or ``length`` are rejected: a clip has no song form.
    """
    return goa_cells.normalise(params)


def bar_chords(o: Mapping[str, Any]) -> list[int]:
    """Chord slot (index into the progression) for every bar of the clip.

    ``bars >= len(progression)``: the chords are spread evenly, bar ``b`` plays chord
    ``b * K // bars`` (K = number of chords), so every chord is in the clip.
    ``bars < K``: the first ``bars`` chords, one per bar (the rest do not fit).
    """
    return goa_cells.bar_slots(o)


def clip_notes(voice: str, **params: Any) -> list[Note]:
    """Notes of one clip in ticks (PPQ 480), sorted by (start, pitch).

    The voice is generated together with the selected ``voices`` (the rule against held
    semitone clashes on accents looks at all of them), so it equals that voice's exported
    clip. A voice outside ``voices`` is generated together with them as well.
    """
    if voice not in VOICES:
        raise ValueError(f"voice must be one of {list(VOICES)}")
    o = normalise(params)
    together = [v for v in VOICES if v in o["voices"] or v == voice]
    return goa_cells.clips_for(o, together)[voice]


def clip_length_ticks(**params: Any) -> int:
    return normalise(params)["bars"] * BAR_TICKS


def _vlq(v: int) -> bytes:
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def _midi(voice: str, o: Mapping[str, Any], notes: list[Note]) -> bytes:
    end = o["bars"] * BAR_TICKS
    trk = bytearray()
    trk += b"\x00\xff\x51\x03" + round(60_000_000 / o["bpm"]).to_bytes(3, "big")
    trk += b"\x00\xff\x58\x04\x04\x02\x18\x08"
    name = f"Goa {voice}".encode("ascii")
    trk += b"\x00\xff\x03" + bytes([len(name)]) + name
    events: list[tuple[int, int, bytes]] = []
    for nt in notes:
        if not 0 <= nt.start < nt.end <= end:
            raise ValueError(f"{voice}: note outside the clip (internal error)")
        events.append((nt.start, 1, bytes([0x90, nt.pitch, nt.velocity])))
        events.append((nt.end, 0, bytes([0x80, nt.pitch, 0])))  # off before on
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    last = 0
    for tick, _, data in events:
        trk += _vlq(tick - last) + data
        last = tick
    trk += _vlq(end - last) + b"\xff\x2f\x00"
    head = b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ)
    return head + b"MTrk" + struct.pack(">I", len(trk)) + bytes(trk)


def clip_to_midi(voice: str, **params: Any) -> bytes:
    """Format-0 SMF bytes of one clip: tempo, 4/4, track name ``Goa <voice>``, notes, end."""
    return _midi(voice, normalise(params), clip_notes(voice, **params))


def clip_filename(voice: str, **params: Any) -> str:
    o = normalise(params)
    return f"goa_{voice}_seed{o['seed']}_{o['bpm']:g}bpm_{o['bars']}bars.mid"


def build_clips(**params: Any) -> dict[str, bytes]:
    """``{voice: .mid bytes}`` for every selected voice, in fixed voice order."""
    o = normalise(params)
    clips = goa_cells.clips_for(o, o["voices"])
    return {v: _midi(v, o, clips[v]) for v in o["voices"]}


def _map_text(values: Mapping[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in values.items())


def render_readme(names: Mapping[str, str], **params: Any) -> str:
    o = normalise(params)
    clips = goa_cells.clips_for(o, o["voices"])
    chosen = goa_cells.describe(**params)
    L = ["# Goa MIDI clips", "",
         "One `.mid` per voice (one clip each). Generated by `python -m audio_engine.goa_clips`; "
         "same options and seed give the same bytes.", "",
         "Not tested in Live, not listened to. Drag each file onto the MIDI track with the "
         "instrument for that voice; the clip loops after the bars below.", "",
         "## How the notes are built", "",
         "Arp, pluck (acid line) and lead repeat one short cell of 16th steps literally. A "
         "cell whose length does not divide 16 runs across the bar lines and starts again "
         f"every {o['restart_bars']} bars. The pad holds root and fifth. This follows the "
         "construction described in `docs/research/2026-11-10_klassische-goa-leads-und-"
         "melodien.md` (rule set N1-N10); it says nothing about how the clips sound.", "",
         "- Accent: a note with the higher velocity "
         f"({o['accent_velocity']} instead of {o['velocity']}). To have an effect beyond "
         "loudness, route velocity to the filter of the instrument.",
         "- Slide: a note that ends shortly after the next note has started. To have an "
         "effect, the instrument must be monophonic with legato and glide switched on.",
         "- Both are untested in Live.", "",
         "## Options used", "",
         f"- seed: {o['seed']}", f"- bars per clip: {o['bars']}", f"- bpm: {o['bpm']:g}",
         f"- key: {o['root']} {o['scale']}",
         f"- progression (scale degrees): {', '.join(map(str, o['progression']))}",
         "- degree per bar: " + ", ".join(str(o["progression"][s]) for s in bar_chords(o)),
         f"- lead mode: {o['lead_mode']}", f"- grouping: {o['grouping']}",
         f"- restart every: {o['restart_bars']} bars",
         f"- pitches per cell (at most): {_map_text(o['pitches'])}",
         f"- slides per bar (at most): {_map_text(o['slides'])}",
         f"- variation in the last bar before a restart: {'on' if o['variant_steps'] else 'off'}",
         f"- velocity / accent velocity: {o['velocity']} / {o['accent_velocity']}",
         f"- gate: {o['gate']} % of a 16th",
         "- sub-seeds: " + ", ".join(f"{k} {v}" for k, v in o["sub_seeds"].items()), "",
         "| voice | file | notes | density | register (octaves) | cell steps | accent cycle |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    for v in o["voices"]:
        c = chosen.get(v)
        cell = (str(c["cell_length"]), str(c["accent_cycle"])) if c else ("-", "-")
        L.append(f"| {v} | `{names[v]}` | {len(clips[v])} | {o['density'][v]:g} | "
                 f"{o['register'][v]} | {cell[0]} | {cell[1]} |")
    L.append("")
    return "\n".join(L)


def write_clips(out_dir: str | Path, **params: Any) -> tuple[list[Path], Path]:
    """Write one ``.mid`` per voice and a README into ``out_dir``.

    Every byte is computed first. If any target exists, nothing is written. If a write
    fails halfway, the files this call already wrote are removed again.
    """
    o = normalise(params)
    clips = build_clips(**params)
    names = {v: clip_filename(v, **params) for v in o["voices"]}
    text = render_readme(names, **params)
    d = Path(out_dir)
    mids = [d / names[v] for v in o["voices"]]
    readme = d / "README.md"
    for p in (*mids, readme):
        if os.path.lexists(p):
            raise FileExistsError(f"{p} already exists; choose another folder (nothing written)")
    d.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for v, p in zip(o["voices"], mids, strict=True):
            with open(p, "xb") as fh:
                written.append(p)
                fh.write(clips[v])
        with open(readme, "x", encoding="utf-8", newline="\n") as fh:
            written.append(readme)
            fh.write(text)
    except BaseException:
        for p in written:
            try:
                p.unlink()
            except OSError:
                pass
        raise
    return mids, readme


# ---------------------------------------------------------------- CLI

def _map_default(values: Mapping[str, Any]) -> str:
    return ",".join(f"{k}={v}" for k, v in values.items())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m audio_engine.goa_clips",
        description="Goa lead/arp/pad/pluck clips built from repeated cells: one looping "
                    ".mid per voice (not tested in Live)")
    p.add_argument("--out", required=True, help="output folder (created; never overwritten)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--bars", type=int, default=DEFAULT_BARS, help="clip length in bars (1-16)")
    p.add_argument("--bpm", type=float, default=goa_cells.DEFAULT_BPM)
    p.add_argument("--root", default="A")
    p.add_argument("--scale", choices=sorted(goa_cells.SCALES), default=goa_cells.DEFAULT_SCALE)
    p.add_argument("--density", help="share of cell steps that are notes, 0-1, or "
                                     "voice=value,voice=value")
    p.add_argument("--register", help="octave shift -2..2, or voice=value,...")
    p.add_argument("--arp-pattern", choices=goa_cells.ARP_PATTERNS, default="up",
                   help="accepted for older calls; the cell model does not use it")
    p.add_argument("--progression", default="0",
                   help="comma list of scale degrees; default 0 = root only")
    p.add_argument("--voices", default=",".join(VOICES))
    p.add_argument("--cell-length", default="auto",
                   help="steps per cell: auto (chosen by the seed), one of "
                        f"{','.join(map(str, goa_cells.CELL_LENGTHS))}, or voice=value,...")
    p.add_argument("--lead-mode", choices=goa_cells.LEAD_MODES, default="own",
                   help="own cell, or the arp doubled an octave higher")
    p.add_argument("--restart-bars", type=int, choices=goa_cells.RESTART_BARS, default=4,
                   help="the cell starts again every N bars")
    p.add_argument("--grouping", choices=list(goa_cells.GROUPINGS), default="displaced",
                   help="displaced cell, or bar-filling groups with the root on each group")
    p.add_argument("--pitches", default=_map_default(goa_cells.DEFAULT_PITCHES),
                   help="pitches per cell, 3-5 (lead up to 6), or voice=value,...")
    p.add_argument("--accent-cycle", choices=["auto", "3", "5"], default="auto",
                   help="every 3rd or 5th note is accented")
    p.add_argument("--slides", default=_map_default(goa_cells.DEFAULT_SLIDES),
                   help="slides per bar at most, 0-2, or voice=value,...")
    p.add_argument("--variation", choices=["on", "off"], default="on",
                   help="one changed step in the last bar before a restart")
    p.add_argument("--velocity", type=int, default=goa_cells.INT_OPTIONS["velocity"][0])
    p.add_argument("--accent-velocity", type=int,
                   default=goa_cells.INT_OPTIONS["accent_velocity"][0])
    p.add_argument("--gate", type=int, default=goa_cells.INT_OPTIONS["gate"][0],
                   help="note length without slide, percent of a 16th (25-100)")
    p.add_argument("--sub-seeds", default="auto",
                   help="auto (from the seed), or pitch=N,rhythm=N,accent=N,slide=N")
    return p


def _parse_map(text: str, cast, name: str) -> Any:
    """``value`` or ``voice=value,voice=value`` (same form as density and register)."""
    if "=" not in text:
        return cast(text)
    out = {}
    for part in text.split(","):
        k, _, v = part.partition("=")
        out[k.strip()] = cast(v)
    if not out:
        raise ValueError(f"{name}: empty")
    return out


def _length_value(text: str) -> Any:
    return "auto" if text.strip() == "auto" else int(text)


def params_from_args(a: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {
        "seed": a.seed, "bars": a.bars, "bpm": a.bpm, "root": a.root, "scale": a.scale,
        "arp_pattern": a.arp_pattern,
        "progression": [int(x) for x in a.progression.split(",")],
        "voices": [v for v in a.voices.split(",") if v],
        "cell_length": _parse_map(a.cell_length, _length_value, "cell-length"),
        "lead_mode": a.lead_mode, "restart_bars": a.restart_bars, "grouping": a.grouping,
        "pitches": _parse_map(a.pitches, int, "pitches"),
        "accent_cycle": "auto" if a.accent_cycle == "auto" else int(a.accent_cycle),
        "slides": _parse_map(a.slides, int, "slides"),
        "variant_steps": 1 if a.variation == "on" else 0,
        "velocity": a.velocity, "accent_velocity": a.accent_velocity, "gate": a.gate}
    if a.sub_seeds.strip() != "auto":
        sub = _parse_map(a.sub_seeds, int, "sub-seeds")
        if not isinstance(sub, dict):
            raise ValueError("sub-seeds must be auto or pitch=N,rhythm=N,accent=N,slide=N")
        params["sub_seeds"] = sub
    if a.density is not None:
        params["density"] = _parse_map(a.density, float, "density")
    if a.register is not None:
        params["register"] = _parse_map(a.register, int, "register")
    return params


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        mids, readme = write_clips(a.out, **params_from_args(a))
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for m in mids:
        print(f"wrote {m} ({m.stat().st_size} bytes)")
    print(f"wrote {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
