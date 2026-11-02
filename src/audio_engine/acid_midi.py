"""Acid line JSON -> Standard MIDI File bytes (pure, deterministic, stdlib only).

Source of the mapping: docs/research/2026-11-02_acid-lines-to-live.md, sections 4-6
(PROPOSAL, not a contract). No Ableton, no listening claim: this module only turns a
resolved list of steps into notes and bytes.

Acid-line JSON (version "0.1-proposal")
---------------------------------------
::

    {
      "format": "acid_line",            # required, exactly this string
      "version": "0.1-proposal",        # required, exactly this string
      "seed": 1234,                     # optional int, informational (never used here)
      "root": "A", "root_octave": 2,    # optional, informational
      "scale": "minor",                 # optional, informational
      "length": 16,                     # required int 1..32
      "steps": [                        # required, exactly `length` entries
        {"on": true, "note": 45, "accent": true, "slide": false,
         "degree": 0, "octave": 0},     # degree/octave informational
        {"on": false}
      ],
      "render": {                       # optional, every key optional
        "velocity": 100, "accent_velocity": 127,
        "gate": 0.125, "slide_overlap": 0.03125
      }
    }

``note`` is the resolved MIDI pitch (integer 0-126) and is the only pitch input; the
scale tables are not needed here. ``accent`` and ``slide`` default to false.
``gate``/``slide_overlap`` are in beats. Tempo is not part of the line.

Mapping (one rule set)
----------------------
* Step ``i`` starts at ``i * 0.25`` beat. The clip is ``length * 0.25`` beat long.
* Rest: no note. Normal note: ``velocity``, duration ``gate``. Accent: ``accent_velocity``.
* ``slide`` sits on the step slid FROM. If step ``i+1`` sounds with a *different* pitch,
  note ``i`` ends ``slide_overlap`` after step ``i+1`` has started (legato overlap).
* If step ``i+1`` sounds with the *same* pitch, the two notes are tied: one note from the
  start of ``i`` to the end of what note ``i+1`` would have been; the merged note is
  accented if either was. Ties chain (a slid-from note in the chain continues the tie).
* A slide before a rest, or on the last step, has no effect (no wrap-around).

The PPQ is 480 (step = 120 ticks); beat values are rounded to whole ticks.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PPQ = 480
STEP_BEATS = 0.25
FORMAT_NAME = "acid_line"
FORMAT_VERSION = "0.1-proposal"
MAX_NOTE = 126
MIN_LENGTH, MAX_LENGTH = 1, 32

DEFAULT_RENDER: dict[str, float] = {
    "velocity": 100,
    "accent_velocity": 127,
    "gate": 0.125,
    "slide_overlap": 0.03125,
}


@dataclass(frozen=True)
class Note:
    start: int  # ticks
    end: int  # ticks (note-off)
    pitch: int
    velocity: int


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _render(line: Mapping[str, Any]) -> dict[str, float]:
    r = dict(DEFAULT_RENDER)
    given = line.get("render")
    if given is None:
        return r
    if not isinstance(given, Mapping):
        raise ValueError("render must be an object")
    for k, v in given.items():
        if k not in DEFAULT_RENDER:
            raise ValueError(f"unknown render key {k!r}")
        r[k] = v
    for k in ("velocity", "accent_velocity"):
        if not _is_int(r[k]) or not 1 <= r[k] <= 127:
            raise ValueError(f"render.{k} must be an integer 1-127")
    if not _is_num(r["gate"]) or not 0 < r["gate"] < STEP_BEATS:
        raise ValueError("render.gate must be in (0, 0.25) beat")
    if not _is_num(r["slide_overlap"]) or not 0 <= r["slide_overlap"] < STEP_BEATS:
        raise ValueError("render.slide_overlap must be in [0, 0.25) beat")
    if round(r["gate"] * PPQ) < 1 or round(r["gate"] * PPQ) >= round(STEP_BEATS * PPQ):
        raise ValueError("render.gate rounds to an unusable tick length")
    return r


def validate_line(line: Any) -> None:
    """Raise ValueError with a specific message if ``line`` is not a valid acid line."""
    if not isinstance(line, Mapping):
        raise ValueError("acid line must be an object")
    if line.get("format") != FORMAT_NAME:
        raise ValueError(f"format must be {FORMAT_NAME!r}")
    if line.get("version") != FORMAT_VERSION:
        raise ValueError(f"version must be {FORMAT_VERSION!r}")
    if "seed" in line and not _is_int(line["seed"]):
        raise ValueError("seed must be an integer")
    n = line.get("length")
    if not _is_int(n) or not MIN_LENGTH <= n <= MAX_LENGTH:
        raise ValueError(f"length must be an integer {MIN_LENGTH}-{MAX_LENGTH}")
    steps = line.get("steps")
    if not isinstance(steps, list) or len(steps) != n:
        raise ValueError("steps must be a list with exactly `length` entries")
    for i, s in enumerate(steps):
        if not isinstance(s, Mapping) or not isinstance(s.get("on"), bool):
            raise ValueError(f"step {i}: 'on' must be a boolean")
        if not s["on"]:
            continue
        if not _is_int(s.get("note")) or not 0 <= s["note"] <= MAX_NOTE:
            raise ValueError(f"step {i}: note must be an integer 0-{MAX_NOTE}")
        for flag in ("accent", "slide"):
            if flag in s and not isinstance(s[flag], bool):
                raise ValueError(f"step {i}: {flag} must be a boolean")
    _render(line)


def line_to_notes(line: Mapping[str, Any]) -> list[Note]:
    """Map a validated acid line to notes, sorted by (start, pitch)."""
    validate_line(line)
    r = _render(line)
    steps = line["steps"]
    n = line["length"]
    step = round(STEP_BEATS * PPQ)
    gate = round(r["gate"] * PPQ)
    overlap = round(r["slide_overlap"] * PPQ)

    def sounds(i: int) -> bool:
        return i < n and steps[i]["on"]

    notes: list[Note] = []
    i = 0
    while i < n:
        if not steps[i]["on"]:
            i += 1
            continue
        pitch = steps[i]["note"]
        accent = bool(steps[i].get("accent", False))
        j = i
        # tie chain: slid-from step into a sounding step of the same pitch
        while steps[j].get("slide", False) and sounds(j + 1) and steps[j + 1]["note"] == pitch:
            j += 1
            accent = accent or bool(steps[j].get("accent", False))
        if steps[j].get("slide", False) and sounds(j + 1):
            end = (j + 1) * step + overlap  # different pitch: legato overlap
        else:
            end = j * step + gate
        vel = r["accent_velocity"] if accent else r["velocity"]
        notes.append(Note(i * step, end, pitch, int(vel)))
        i = j + 1
    notes.sort(key=lambda x: (x.start, x.pitch))
    return notes


def _vlq(v: int) -> bytes:
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def acid_line_to_midi(
    line: Mapping[str, Any], bpm: float | None = None, name: str | None = None
) -> bytes:
    """Return a format-0 SMF (PPQ 480, channel 1) for ``line``.

    ``bpm`` None (default) writes no tempo event, so the host keeps its own tempo;
    a number writes a tempo meta event. ``name`` (ASCII) writes a track-name event.
    """
    notes = line_to_notes(line)
    n = line["length"]
    trk = bytearray()
    if bpm is not None:
        if not _is_num(bpm) or not 20 <= bpm <= 400:
            raise ValueError("bpm must be a number 20-400")
        us = round(60_000_000 / bpm)
        trk += b"\x00\xff\x51\x03" + us.to_bytes(3, "big")
    trk += b"\x00\xff\x58\x04\x04\x02\x18\x08"  # 4/4
    if name is not None:
        raw = name.encode("ascii")
        if len(raw) > 127:
            raise ValueError("name too long")
        trk += b"\x00\xff\x03" + bytes([len(raw)]) + raw
    events: list[tuple[int, int, bytes]] = []  # (tick, order: off before on, bytes)
    for nt in notes:
        events.append((nt.start, 1, bytes([0x90, nt.pitch, nt.velocity])))
        events.append((nt.end, 0, bytes([0x80, nt.pitch, 0])))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    last = 0
    for tick, _, data in events:
        trk += _vlq(tick - last) + data
        last = tick
    clip_end = n * round(STEP_BEATS * PPQ)
    trk += _vlq(max(0, clip_end - last)) + b"\xff\x2f\x00"
    head = b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ)
    return head + b"MTrk" + struct.pack(">I", len(trk)) + bytes(trk)


def load_acid_line(path: str | Path) -> dict[str, Any]:
    """Read and validate an acid-line JSON file."""
    line = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_line(line)
    return line


def write_acid_midi(
    line: Mapping[str, Any], path: str | Path, bpm: float | None = None,
    name: str | None = None,
) -> Path:
    """Write the .mid for ``line`` (bytes are computed first, so a bad line writes nothing)."""
    data = acid_line_to_midi(line, bpm=bpm, name=name)
    p = Path(path)
    p.write_bytes(data)
    return p
