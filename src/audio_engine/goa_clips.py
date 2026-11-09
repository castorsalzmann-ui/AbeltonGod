"""Goa MIDI clips: one short loop per voice (lead, arp, pad, pluck), like the Acid line (D-035).

D-035 (1): the Goa page generates clips, not a song. A clip is ``bars`` bars (1-16, default
4) of one voice in key/scale/tempo with the melodic options of ``goa_melody`` (density,
register, arp pattern, progression). There are no sections, no energy curve and no song
form here; song form belongs to the arrangement planner (D-033).

The notes come from ``goa_melody.voice_pattern`` at full energy, so a clip is exactly the
phrase ``goa_melody`` would repeat, with no section scaling of density or velocity.

File layout: ONE format-0 ``.mid`` PER VOICE (one clip per file). Reason: in Live a MIDI
file dropped on a track (or a clip slot) becomes one clip on that track, so the user puts
each voice on the track with the instrument meant for it. A format-1 file with four tracks
would have to be dropped on an empty area to spread into tracks and is not "one clip".
Each file has a tempo event (the bpm the clip was made for), 4/4, a track name and its
end-of-track event exactly at ``bars * 4 * 480`` ticks, so the clip loops at the bar line.

Not tested in Live, not listened to. Nothing here writes to Ableton.

CLI::

    python -m audio_engine.goa_clips --out DIR --seed N [--bars 4] [--bpm 145] [--root A]
        [--scale phrygian] [--density 0.6 | lead=0.5,arp=1] [--register 0 | lead=1,pad=-1]
        [--arp-pattern up] [--progression 0,5,6,4] [--voices lead,arp,pad,pluck]

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

from audio_engine import goa_melody
from audio_engine.acid_midi import PPQ, Note

VOICES = goa_melody.VOICES
MIN_BARS, MAX_BARS = goa_melody.MIN_LENGTH, goa_melody.MAX_LENGTH  # 1, 16
DEFAULT_BARS = 4
BAR_TICKS = 4 * PPQ
_KNOWN = {"seed", "bpm", "root", "scale", "bars", "density", "register", "arp_pattern",
          "progression", "voices"}


def normalise(params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and fill defaults (same rules as ``goa_melody.normalise``; ``bars`` = length).

    ``sections``, ``energy`` or ``title`` are rejected: a clip has no song form.
    """
    extra = set(params) - _KNOWN
    if extra:
        raise ValueError(f"unknown options {sorted(extra)} (clips have no sections or energy)")
    bars = params.get("bars", DEFAULT_BARS)
    if not goa_melody._is_int(bars) or not MIN_BARS <= bars <= MAX_BARS:
        raise ValueError(f"bars must be an integer {MIN_BARS}-{MAX_BARS}")
    p = {k: v for k, v in params.items() if k != "bars"}
    p["length"] = bars
    o = goa_melody.normalise(p)
    o.pop("sections")
    o.pop("title")
    o["bars"] = o.pop("length")
    return o


def _melody_options(o: Mapping[str, Any]) -> dict[str, Any]:
    return dict(o, length=o["bars"])


def _ticks(beats: float) -> int:
    return int(beats * PPQ + 0.5)


def clip_notes(voice: str, **params: Any) -> list[Note]:
    """Notes of one clip in ticks (PPQ 480), sorted by (start, pitch)."""
    if voice not in VOICES:
        raise ValueError(f"voice must be one of {list(VOICES)}")
    o = normalise(params)
    pat = goa_melody.voice_pattern(voice, _melody_options(o), 1.0)
    notes = []
    for n in pat["notes"]:
        s = _ticks(n["start"])
        notes.append(Note(s, s + _ticks(n["duration"]), n["pitch"], n["velocity"]))
    notes.sort(key=lambda x: (x.start, x.pitch))
    return notes


def clip_length_ticks(**params: Any) -> int:
    return normalise(params)["bars"] * BAR_TICKS


def _vlq(v: int) -> bytes:
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def clip_to_midi(voice: str, **params: Any) -> bytes:
    """Format-0 SMF bytes of one clip: tempo, 4/4, track name ``Goa <voice>``, notes, end."""
    o = normalise(params)
    notes = clip_notes(voice, **params)
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


def clip_filename(voice: str, **params: Any) -> str:
    o = normalise(params)
    return f"goa_{voice}_seed{o['seed']}_{o['bpm']:g}bpm_{o['bars']}bars.mid"


def build_clips(**params: Any) -> dict[str, bytes]:
    """``{voice: .mid bytes}`` for every selected voice, in fixed voice order."""
    o = normalise(params)
    return {v: clip_to_midi(v, **params) for v in o["voices"]}


def render_readme(names: Mapping[str, str], **params: Any) -> str:
    o = normalise(params)
    L = ["# Goa MIDI clips", "",
         "One `.mid` per voice (one clip each). Generated by `python -m audio_engine.goa_clips`; "
         "same options and seed give the same bytes.", "",
         "Not tested in Live, not listened to. Drag each file onto the MIDI track with the "
         "instrument for that voice; the clip loops after the bars below.", "",
         "## Options used", "",
         f"- seed: {o['seed']}", f"- bars per clip: {o['bars']}", f"- bpm: {o['bpm']:g}",
         f"- key: {o['root']} {o['scale']}", f"- arp pattern: {o['arp_pattern']}",
         f"- progression (scale degrees): {', '.join(map(str, o['progression']))}", "",
         "| voice | file | notes | density | register (octaves) |",
         "| --- | --- | --- | --- | --- |"]
    for v in o["voices"]:
        n = len(clip_notes(v, **params))
        L.append(f"| {v} | `{names[v]}` | {n} | {o['density'][v]:g} | {o['register'][v]} |")
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

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m audio_engine.goa_clips",
        description="Goa lead/arp/pad/pluck clips: one looping .mid per voice (not tested in Live)")
    p.add_argument("--out", required=True, help="output folder (created; never overwritten)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--bars", type=int, default=DEFAULT_BARS, help="clip length in bars (1-16)")
    p.add_argument("--bpm", type=float, default=goa_melody.DEFAULT_BPM)
    p.add_argument("--root", default="A")
    p.add_argument("--scale", choices=sorted(goa_melody.SCALES), default="phrygian")
    p.add_argument("--density", help="0-1, or voice=value,voice=value")
    p.add_argument("--register", help="octave shift -2..2, or voice=value,...")
    p.add_argument("--arp-pattern", choices=goa_melody.ARP_PATTERNS, default="up")
    p.add_argument("--progression", default=",".join(map(str, goa_melody.DEFAULT_PROGRESSION)),
                   help="comma list of scale degrees 0-6")
    p.add_argument("--voices", default=",".join(VOICES))
    return p


def params_from_args(a: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {
        "seed": a.seed, "bars": a.bars, "bpm": a.bpm, "root": a.root, "scale": a.scale,
        "arp_pattern": a.arp_pattern,
        "progression": [int(x) for x in a.progression.split(",")],
        "voices": [v for v in a.voices.split(",") if v]}
    if a.density is not None:
        params["density"] = goa_melody._parse_voice_map(a.density, float, "density")
    if a.register is not None:
        params["register"] = goa_melody._parse_voice_map(a.register, int, "register")
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
