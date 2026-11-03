"""Goa arrangement description -> ONE multi-track Standard MIDI File (format 1).

Pure, deterministic, stdlib only. Nothing here talks to Ableton, and nothing here is
verified in Live: the file is meant to be dragged into Live by the user (see
docs/research/2026-11-03_goa-arrangement-delivery-to-live.md and its user test list).

Input: "goa_arrangement" JSON, version "0.1-proposal" (PROPOSAL, not a contract)
-------------------------------------------------------------------------------
::

    {
      "format": "goa_arrangement", "version": "0.1-proposal",
      "title": "optional ASCII",                    # conductor track name
      "tempo": 145,                                 # BPM, 135-150 (number)
      "key": {"root": "A", "scale": "phrygian"},    # informational: written as a text event
      "elements": [                                 # one MIDI track per element, in this order
        {"name": "kick", "pattern": <pattern>},
        {"name": "bass", "pattern": <pattern>}
      ],
      "sections": [                                 # played one after the other, 4/4 only
        {"name": "Intro", "bars": 16, "energy": 0.3,
         "elements": ["kick"],                      # which elements play in this section
         "patterns": {"kick": <pattern>}}           # optional per-section pattern override
      ]
    }

``<pattern>`` is either

* native: ``{"length_beats": 4, "notes": [{"pitch": 36, "start": 0.0, "duration": 0.25,
  "velocity": 110}, ...]}`` (starts/durations in beats inside the pattern; a note must end
  inside ``length_beats``; same-pitch notes may not overlap), or
* a note line in the ``acid_line`` / ``goa_line`` 0.1-proposal format (``steps`` with
  ``on``/``note``/``accent``/``slide``, 1 step = 0.25 beat). Converted by
  ``audio_engine.acid_midi.line_to_notes`` (the only mapping rule set; a ``goa_line`` is
  accepted when its ``steps`` follow that shape; ALIGNMENT POINT with the goa_patterns
  generator, which this module deliberately does not import).

Placement rules
---------------
* Sections start at the sum of the earlier sections' bars (1 bar = 4 beats = 1920 ticks).
* An active element's pattern is repeated from the section start; repeats start every
  ``length`` beats; anything past the section end is cut (a note running over the end is
  shortened to it; a note starting at or after it is dropped).
* Energy (0-1) scales velocities: ``velocity * (0.70 + 0.30 * energy)``, rounded, clamped
  to 1-127 (PROPOSAL; energy 1.0 leaves velocities unchanged).
* An element that is not listed in a section is silent there.

File layout
-----------
Track 0 (conductor): name, tempo, time signature 4/4, a text event ``key: <root> <scale>``,
one marker per section (text = section name) at its first tick, end-of-track at the end
of the last section. Then one track per element: track name, notes, end-of-track at the
same final tick (so every track has the full length). PPQ 480, all notes on channel 1.
Same input gives the same bytes.
"""

from __future__ import annotations

import json
import math
import os
import re
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from audio_engine import acid_midi

PPQ = acid_midi.PPQ  # 480
BEATS_PER_BAR = 4
BAR_TICKS = PPQ * BEATS_PER_BAR
FORMAT_NAME = "goa_arrangement"
FORMAT_VERSION = "0.1-proposal"
TEMPO_MIN, TEMPO_MAX = 135.0, 150.0
MAX_SECTIONS = 64
MAX_ELEMENTS = 32
MAX_TOTAL_BARS = 1024
MAX_SECTION_BARS = 512
MAX_PATTERN_NOTES = 4096
MAX_PATTERN_BEATS = 128
ENERGY_FLOOR, ENERGY_SPAN = 0.70, 0.30
LINE_FORMATS = ("acid_line", "goa_line")

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,31}$")
_ROOT_RE = re.compile(r"^[A-G][#b]?$")
_SCALE_RE = re.compile(r"^[a-z][a-z _\-]{0,31}$")
_NAME_HELP = "name must be 1-32 ASCII letters, digits, space, _ or -"
_TITLE_RE = re.compile(r"^[ -~]{1,64}$")


class ArrangementError(ValueError):
    """The arrangement description is not valid; nothing was written."""


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _ticks(beats: float) -> int:
    return int(math.floor(beats * PPQ + 0.5))


# ---------------------------------------------------------------- patterns

Placed = list[tuple[int, int, int, int]]  # (start, end, pitch, velocity), ticks


def _native_pattern(p: Mapping[str, Any], where: str) -> tuple[int, Placed]:
    allowed = {"length_beats", "notes"}
    extra = set(p) - allowed
    if extra:
        raise ArrangementError(f"{where}: unknown pattern keys {sorted(extra)}")
    lb = p.get("length_beats")
    if not _is_num(lb) or not 0 < lb <= MAX_PATTERN_BEATS:
        raise ArrangementError(
            f"{where}: length_beats must be a number in (0, {MAX_PATTERN_BEATS}]")
    length = _ticks(lb)
    if length < 1:
        raise ArrangementError(f"{where}: length_beats is shorter than one tick")
    raw = p.get("notes")
    if not isinstance(raw, list) or len(raw) > MAX_PATTERN_NOTES:
        raise ArrangementError(f"{where}: notes must be a list of at most {MAX_PATTERN_NOTES}")
    out: list[tuple[int, int, int, int]] = []
    for i, n in enumerate(raw):
        w = f"{where}: note {i}"
        if not isinstance(n, Mapping) or set(n) != {"pitch", "start", "duration", "velocity"}:
            raise ArrangementError(f"{w}: needs exactly pitch, start, duration, velocity")
        if not _is_int(n["pitch"]) or not 0 <= n["pitch"] <= 127:
            raise ArrangementError(f"{w}: pitch must be an integer 0-127")
        if not _is_int(n["velocity"]) or not 1 <= n["velocity"] <= 127:
            raise ArrangementError(f"{w}: velocity must be an integer 1-127")
        if not _is_num(n["start"]) or n["start"] < 0:
            raise ArrangementError(f"{w}: start must be a number >= 0")
        if not _is_num(n["duration"]) or n["duration"] <= 0:
            raise ArrangementError(f"{w}: duration must be a number > 0")
        s = _ticks(n["start"])
        d = _ticks(n["duration"])
        if d < 1:
            raise ArrangementError(f"{w}: duration is shorter than one tick")
        if s + d > length:
            raise ArrangementError(f"{w}: ends after the pattern (length_beats)")
        out.append((s, s + d, n["pitch"], n["velocity"]))
    last_end: dict[int, int] = {}
    for s, e, pitch, _ in sorted(out, key=lambda x: (x[2], x[0], x[1])):
        if pitch in last_end and s < last_end[pitch]:
            raise ArrangementError(f"{where}: same-pitch notes overlap (pitch {pitch})")
        last_end[pitch] = e
    return length, out


def _line_pattern(p: Mapping[str, Any], where: str) -> tuple[int, Placed]:
    line = dict(p)
    line["format"] = "acid_line"
    line["version"] = acid_midi.FORMAT_VERSION
    try:
        notes = acid_midi.line_to_notes(line)
    except ValueError as exc:
        raise ArrangementError(f"{where}: {exc}") from exc
    length = line["length"] * round(acid_midi.STEP_BEATS * PPQ)
    return length, [(n.start, n.end, n.pitch, n.velocity) for n in notes]


def _pattern(p: Any, where: str) -> tuple[int, Placed]:
    """-> (length in ticks, [(start, end, pitch, velocity)] in ticks)."""
    if not isinstance(p, Mapping):
        raise ArrangementError(f"{where}: pattern must be an object")
    if p.get("format") in LINE_FORMATS:
        return _line_pattern(p, where)
    if "format" in p:
        raise ArrangementError(f"{where}: unknown pattern format {p['format']!r}")
    return _native_pattern(p, where)


# ---------------------------------------------------------------- validation

def validate_arrangement(arr: Any) -> None:
    """Raise ArrangementError with a specific message if ``arr`` is not valid."""
    _prepare(arr)


def _prepare(arr: Any) -> dict[str, Any]:
    if not isinstance(arr, Mapping):
        raise ArrangementError("arrangement must be an object")
    if arr.get("format") != FORMAT_NAME:
        raise ArrangementError(f"format must be {FORMAT_NAME!r}")
    if arr.get("version") != FORMAT_VERSION:
        raise ArrangementError(f"version must be {FORMAT_VERSION!r}")
    title = arr.get("title", "Goa arrangement")
    if not isinstance(title, str) or not _TITLE_RE.match(title):
        raise ArrangementError("title must be printable ASCII, 1-64 characters")
    tempo = arr.get("tempo")
    if not _is_num(tempo) or not TEMPO_MIN <= tempo <= TEMPO_MAX:
        raise ArrangementError(f"tempo must be a number {TEMPO_MIN:g}-{TEMPO_MAX:g} BPM")
    key = arr.get("key")
    if not isinstance(key, Mapping) or set(key) != {"root", "scale"}:
        raise ArrangementError("key must be an object with root and scale")
    if not isinstance(key["root"], str) or not _ROOT_RE.match(key["root"]):
        raise ArrangementError("key.root must be A-G with an optional # or b")
    if not isinstance(key["scale"], str) or not _SCALE_RE.match(key["scale"]):
        raise ArrangementError("key.scale must be lower-case letters, spaces, _ or -")

    els = arr.get("elements")
    if not isinstance(els, list) or not 1 <= len(els) <= MAX_ELEMENTS:
        raise ArrangementError(f"elements must be a list of 1-{MAX_ELEMENTS}")
    patterns: dict[str, tuple[int, list[tuple[int, int, int, int]]]] = {}
    order: list[str] = []
    for i, e in enumerate(els):
        if not isinstance(e, Mapping) or set(e) != {"name", "pattern"}:
            raise ArrangementError(f"element {i}: needs exactly name and pattern")
        name = e["name"]
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ArrangementError(f"element {i}: {_NAME_HELP}")
        if name in patterns:
            raise ArrangementError(f"element {i}: duplicate name {name!r}")
        patterns[name] = _pattern(e["pattern"], f"element {name!r}")
        order.append(name)

    secs = arr.get("sections")
    if not isinstance(secs, list) or not 1 <= len(secs) <= MAX_SECTIONS:
        raise ArrangementError(f"sections must be a list of 1-{MAX_SECTIONS}")
    out_secs: list[dict[str, Any]] = []
    total_bars = 0
    for i, s in enumerate(secs):
        if not isinstance(s, Mapping) or not {"name", "bars", "energy", "elements"} <= set(s) \
                or set(s) - {"name", "bars", "energy", "elements", "patterns"}:
            raise ArrangementError(
                f"section {i}: needs name, bars, energy, elements (patterns optional)")
        if not isinstance(s["name"], str) or not _NAME_RE.match(s["name"]):
            raise ArrangementError(f"section {i}: {_NAME_HELP}")
        if not _is_int(s["bars"]) or not 1 <= s["bars"] <= MAX_SECTION_BARS:
            raise ArrangementError(f"section {i}: bars must be an integer 1-{MAX_SECTION_BARS}")
        if not _is_num(s["energy"]) or not 0 <= s["energy"] <= 1:
            raise ArrangementError(f"section {i}: energy must be a number 0-1")
        act = s["elements"]
        if not isinstance(act, list) or not all(isinstance(a, str) for a in act):
            raise ArrangementError(f"section {i}: elements must be a list of names")
        if len(set(act)) != len(act):
            raise ArrangementError(f"section {i}: duplicate element name")
        for a in act:
            if a not in patterns:
                raise ArrangementError(f"section {i}: unknown element {a!r}")
        over: dict[str, tuple[int, list[tuple[int, int, int, int]]]] = {}
        given = s.get("patterns", {})
        if not isinstance(given, Mapping):
            raise ArrangementError(f"section {i}: patterns must be an object")
        for k, v in given.items():
            if k not in act:
                raise ArrangementError(f"section {i}: pattern override for inactive element {k!r}")
            over[k] = _pattern(v, f"section {i} pattern {k!r}")
        total_bars += s["bars"]
        out_secs.append({"name": s["name"], "bars": s["bars"], "energy": float(s["energy"]),
                         "active": list(act), "over": over})
    if total_bars > MAX_TOTAL_BARS:
        raise ArrangementError(f"total length {total_bars} bars exceeds {MAX_TOTAL_BARS}")
    return {"title": title, "tempo": float(tempo), "key": dict(key), "order": order,
            "patterns": patterns, "sections": out_secs, "total_bars": total_bars}


# ---------------------------------------------------------------- placement

def _scaled_velocity(v: int, energy: float) -> int:
    return max(1, min(127, int(math.floor(v * (ENERGY_FLOOR + ENERGY_SPAN * energy) + 0.5))))


def _place(prep: Mapping[str, Any]) -> dict[str, list[tuple[int, int, int, int]]]:
    """-> {element: [(start, end, pitch, velocity)]} in absolute ticks, sorted."""
    placed: dict[str, list[tuple[int, int, int, int]]] = {n: [] for n in prep["order"]}
    pos = 0
    for sec in prep["sections"]:
        sec_start = pos
        sec_end = pos + sec["bars"] * BAR_TICKS
        for name in sec["active"]:
            length, notes = sec["over"].get(name) or prep["patterns"][name]
            base = sec_start
            while base < sec_end:
                for s, e, pitch, vel in notes:
                    a = base + s
                    b = min(base + e, sec_end)
                    if a >= sec_end or b <= a:
                        continue
                    placed[name].append((a, b, pitch, _scaled_velocity(vel, sec["energy"])))
                base += length
        pos = sec_end
    for lst in placed.values():
        lst.sort()
    return placed


def arrangement_notes(arr: Mapping[str, Any]) -> dict[str, list[tuple[int, int, int, int]]]:
    """Validated arrangement -> {element: [(start, end, pitch, velocity)]}, absolute ticks."""
    return _place(_prepare(arr))


# ---------------------------------------------------------------- bytes

def _vlq(v: int) -> bytes:
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def _meta(typ: int, payload: bytes) -> bytes:
    return b"\xff" + bytes([typ]) + _vlq(len(payload)) + payload


def _chunk(events: list[tuple[int, int, bytes]], end_tick: int) -> bytes:
    events = sorted(events, key=lambda e: (e[0], e[1], e[2]))
    body = bytearray()
    last = 0
    for tick, _, data in events:
        body += _vlq(tick - last) + data
        last = tick
    body += _vlq(end_tick - last) + _meta(0x2F, b"")
    return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def arrangement_to_midi(arr: Mapping[str, Any]) -> bytes:
    """Return the format-1 SMF bytes for ``arr`` (raises ArrangementError if invalid)."""
    prep = _prepare(arr)
    placed = _place(prep)
    end_tick = prep["total_bars"] * BAR_TICKS
    us = round(60_000_000 / prep["tempo"])
    key = prep["key"]
    cond: list[tuple[int, int, bytes]] = [
        (0, 0, _meta(0x03, prep["title"].encode("ascii"))),
        (0, 1, _meta(0x51, us.to_bytes(3, "big"))),
        (0, 2, _meta(0x58, bytes([4, 2, 24, 8]))),
        (0, 3, _meta(0x01, f"key: {key['root']} {key['scale']}".encode("ascii"))),
    ]
    pos = 0
    for sec in prep["sections"]:
        cond.append((pos, 4, _meta(0x06, sec["name"].encode("ascii"))))
        pos += sec["bars"] * BAR_TICKS
    chunks = [_chunk(cond, end_tick)]
    for name in prep["order"]:
        ev: list[tuple[int, int, bytes]] = [(0, 0, _meta(0x03, name.encode("ascii")))]
        for a, b, pitch, vel in placed[name]:
            ev.append((a, 6, bytes([0x90, pitch, vel])))
            ev.append((b, 5, bytes([0x80, pitch, 0])))  # off before on at the same tick
        chunks.append(_chunk(ev, end_tick))
    head = b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), PPQ)
    return head + b"".join(chunks)


def write_arrangement_midi(arr: Mapping[str, Any], path: str | Path) -> Path:
    """Write the .mid. Bytes are computed first (an invalid arrangement writes nothing);
    the file appears under its final name only when complete."""
    data = arrangement_to_midi(arr)
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            tmp.unlink()
    return p


def load_arrangement(path: str | Path) -> dict[str, Any]:
    arr = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_arrangement(arr)
    return arr


# ---------------------------------------------------------------- demo

def demo_arrangement() -> dict[str, Any]:
    """A small arrangement for the user's drag-and-drop test. The patterns are TEST
    patterns (placement and track layout), not a musical proposal and not Goa claims."""
    def hits(pitch: int, starts: list[float], dur: float, vel: int) -> dict[str, Any]:
        return {"length_beats": 4, "notes": [
            {"pitch": pitch, "start": s, "duration": dur, "velocity": vel} for s in starts]}

    def bass_line() -> dict[str, Any]:
        steps = []
        for i in range(16):
            if i % 4 == 0:
                steps.append({"on": False})
            else:
                steps.append({"on": True, "note": 33 if i % 8 < 4 else 45,
                              "accent": i % 8 == 1, "slide": False})
        return {"format": "acid_line", "version": "0.1-proposal", "length": 16, "steps": steps}

    lead = {"length_beats": 8, "notes": [
        {"pitch": 69, "start": 0.0, "duration": 1.0, "velocity": 100},
        {"pitch": 70, "start": 1.0, "duration": 0.5, "velocity": 90},
        {"pitch": 72, "start": 2.0, "duration": 1.0, "velocity": 100},
        {"pitch": 70, "start": 4.0, "duration": 1.5, "velocity": 95},
        {"pitch": 69, "start": 6.0, "duration": 2.0, "velocity": 100}]}
    return {
        "format": FORMAT_NAME, "version": FORMAT_VERSION, "title": "Goa demo",
        "tempo": 145, "key": {"root": "A", "scale": "phrygian"},
        "elements": [
            {"name": "kick", "pattern": hits(36, [0.0, 1.0, 2.0, 3.0], 0.25, 110)},
            {"name": "hat", "pattern": hits(42, [0.5, 1.5, 2.5, 3.5], 0.125, 90)},
            {"name": "bass", "pattern": bass_line()},
            {"name": "lead", "pattern": lead},
        ],
        "sections": [
            {"name": "Intro", "bars": 8, "energy": 0.3, "elements": ["kick", "hat"]},
            {"name": "Groove", "bars": 8, "energy": 0.6, "elements": ["kick", "hat", "bass"]},
            {"name": "Break", "bars": 4, "energy": 0.2, "elements": ["lead"]},
            {"name": "Peak", "bars": 8, "energy": 1.0, "elements": ["kick", "hat", "bass", "lead"]},
            {"name": "Outro", "bars": 4, "energy": 0.4, "elements": ["kick", "hat"]},
        ],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="goa_arrangement JSON -> one format-1 .mid")
    ap.add_argument("out", help="output .mid path")
    ap.add_argument("--input", help="arrangement JSON (default: the built-in demo)")
    a = ap.parse_args(argv)
    try:
        arr = load_arrangement(a.input) if a.input else demo_arrangement()
        p = write_arrangement_midi(arr, a.out)
    except (ArrangementError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}")
        return 2
    print(f"wrote {p} ({p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
