"""Read-only look inside an Ableton Live set (.als = gzip-compressed XML).

Usage:  python scripts/als_inspect.py "C:\\path\\to\\MySet.als"

Prints the root attributes (Live version / schema), tempo, track kinds and names,
clip counts and locator names. It writes nothing, and it talks to no Live. It exists to
turn the user's own saved set into evidence for the .als feasibility note
(docs/research/2026-11-03_goa-arrangement-delivery-to-live.md, tests S1-S3).
Tag names are read from the file; if a tag is not found the line says "not found",
so a different Live schema shows up as a gap instead of a wrong number.
"""

from __future__ import annotations

import gzip
import io
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_BYTES = 200 * 2**20  # cap on the decompressed XML
TRACK_TAGS = ("MidiTrack", "AudioTrack", "GroupTrack", "ReturnTrack")


def load_set(path: str | Path) -> ET.Element:
    raw = Path(path).read_bytes()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
            data = gz.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError(f"{path}: decompressed size exceeds {MAX_BYTES // 2**20} MB")
        raw = data
    except OSError as exc:  # not gzip: maybe already plain XML
        if not raw.lstrip().startswith(b"<"):
            raise ValueError(f"{path}: neither gzip nor XML ({exc})") from exc
        if len(raw) > MAX_BYTES:
            raise ValueError(f"{path}: size exceeds {MAX_BYTES // 2**20} MB") from exc
    return ET.fromstring(raw)


def _name(el: ET.Element) -> str:
    n = el.find("./Name/EffectiveName")
    return n.get("Value", "") if n is not None else "(no EffectiveName)"


def summarise(root: ET.Element) -> list[str]:
    out = [f"root: {root.tag} " + " ".join(f"{k}={v}" for k, v in sorted(root.attrib.items()))]
    live = root.find("LiveSet")
    if live is None:
        return out + ["LiveSet: not found"]
    tempo = live.find(".//MasterTrack//Tempo/Manual")
    out.append("tempo (Master Tempo/Manual): "
               + (tempo.get("Value", "?") if tempo is not None else "not found"))
    tracks = live.find("Tracks")
    if tracks is None:
        out.append("Tracks: not found")
    else:
        for el in tracks:
            clips = len(el.findall(".//MidiClip")) + len(el.findall(".//AudioClip"))
            out.append(f"track {el.tag}: {_name(el)!r}, clips: {clips}, "
                       f"notes: {len(el.findall('.//MidiNoteEvent'))}")
    locs = live.findall(".//Locators/Locators/Locator")
    out.append(f"locators: {len(locs)}")
    for loc in locs:
        n, t = loc.find("Name"), loc.find("Time")
        out.append(f"  locator {n.get('Value') if n is not None else '?'!r} at beat "
                   f"{t.get('Value') if t is not None else '?'}")
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        print("\n".join(summarise(load_set(args[0]))))
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
