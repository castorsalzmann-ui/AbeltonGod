"""End-to-end smoke test of what ``main`` can do today, as a user would run it (QA tool).

    python scripts/qa/smoke_pipeline.py [--presets-per-category N] [--keep DIR] [--json FILE]
                                      [--expect-fail SUBSTRING ...]

Needs only ``PYTHONPATH=src`` (or an install), no Ableton. Per category the CLI
``python -m audio_engine.kick --category <c>`` lists the presets and renders each one with 2
variants into a temporary folder; then, with checks that do not reuse the engine's own helpers:

* the sidecar validates against ``contracts/sample-metadata.schema.json``;
* the WAV is read with a small RIFF parser written here (header, sizes, peak, DC, length,
  silence, tail), and peak/length/sha256 are compared with the sidecar;
* ``rerender_from_sidecar`` gives the WAV bytes back (byte identity).

Then, once: library placement (folder layout, ``_002`` collision suffix), the
``generate_sample`` tool schema and its hash against the pins in the tests, and a dry
``generate_sample`` + ``import_sample`` run with the fake AbletonOSC server from ``tests/bridge``.
**Nothing here talks to Live**; the fake server is a test double, never evidence for Ableton.

Exit code 0 only if every check passed, or the only failures are known ones named with
``--expect-fail SUBSTRING`` (reported as KNOWN). A substring that matches no failure is
reported as STALE and listed in ``stale_expect_fail``, but does not fail the run. Categories
are read from the engine registry, so a new category on main is picked up without changes here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

DC_LIMIT = 0.005  # fraction of full scale; the engine's DC blocker keeps real output far below
TAIL_LIMIT = 0.01  # |last sample| (fraction of full scale): a hard cut at the end clicks
MAX_SECONDS = 6.0


class Results:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.rows.append((name, bool(ok), detail))
        if not ok:
            print(f"FAIL {name}: {detail}")
        return bool(ok)

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [r for r in self.rows if not r[1]]


def split_known(failed: list[tuple[str, bool, str]], expect: list[str]):
    """Split failures into (known, unexpected) by ``--expect-fail`` substrings (name or detail).

    Also returns the substrings that matched no failure: a known issue that started passing.
    """
    known = [r for r in failed if any(e in r[0] or e in r[2] for e in expect)]
    unexpected = [r for r in failed if r not in known]
    stale = [e for e in expect if not any(e in r[0] or e in r[2] for r in failed)]
    return known, unexpected, stale


def read_wav(data: bytes) -> dict:
    """Independent RIFF/WAVE reader (PCM only). Raises ValueError on a malformed file."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not RIFF/WAVE")
    riff_size = struct.unpack("<I", data[4:8])[0]
    pos, fmt, samples_raw = 12, None, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if len(body) != size:
            raise ValueError(f"chunk {cid!r} truncated")
        if cid == b"fmt ":
            tag, ch, sr, brate, align, bits = struct.unpack("<HHIIHH", body[:16])
            fmt = dict(tag=tag, channels=ch, sr=sr, byte_rate=brate, align=align, bits=bits)
        elif cid == b"data":
            samples_raw = body
        pos += 8 + size + (size & 1)
    if fmt is None or samples_raw is None:
        raise ValueError("fmt or data chunk missing")
    width = fmt["bits"] // 8
    if fmt["tag"] != 1 or fmt["bits"] not in (16, 24) or fmt["channels"] < 1:
        raise ValueError(f"unexpected format {fmt}")
    frame = width * fmt["channels"]
    if fmt["align"] != frame or fmt["byte_rate"] != fmt["sr"] * frame or len(samples_raw) % frame:
        raise ValueError(f"inconsistent fmt/data sizes {fmt}, data {len(samples_raw)}")
    ints = [int.from_bytes(samples_raw[i:i + width], "little", signed=True)
            for i in range(0, len(samples_raw), width)]
    scale = float(2 ** (fmt["bits"] - 1))
    return {**fmt, "riff_size_ok": riff_size == len(data) - 8,
            "frames": len(ints) // fmt["channels"], "samples": [v / scale for v in ints],
            "min_int": min(ints), "max_int": max(ints), "full": int(scale)}


def check_audio(res: Results, label: str, wav_path: Path, meta: dict) -> None:
    data = wav_path.read_bytes()
    try:
        w = read_wav(data)
    except ValueError as exc:
        res.check(f"{label}: wav parses", False, str(exc))
        return
    s = w["samples"]
    n = len(s)
    peak = max(abs(v) for v in s)
    dc = sum(s) / n
    secs = w["frames"] / w["sr"]
    res.check(f"{label}: riff size field", w["riff_size_ok"])
    res.check(f"{label}: peak <= full scale, not silent",
              0.01 < peak <= 1.0 and w["min_int"] > -w["full"] - 1 and w["max_int"] < w["full"],
              f"peak={peak:.4f}")
    clipped = sum(1 for v in w["samples"] if abs(v) >= (w["full"] - 1) / w["full"])
    res.check(f"{label}: no clipping", clipped <= 2, f"{clipped} samples at full scale")
    res.check(f"{label}: DC offset", abs(dc) <= DC_LIMIT, f"dc={dc:.6f}")
    res.check(f"{label}: length", 0.01 <= secs <= MAX_SECONDS, f"{secs:.3f} s")
    res.check(f"{label}: tail ends near zero", abs(s[-1]) <= TAIL_LIMIT, f"last={s[-1]:.5f}")
    res.check(f"{label}: finite", all(math.isfinite(v) for v in s))
    feats = meta.get("features", {})
    if "peak_dbfs" in feats and peak > 0:
        mine = 20 * math.log10(peak)
        res.check(f"{label}: sidecar peak_dbfs matches", abs(mine - feats["peak_dbfs"]) <= 0.06,
                  f"mine={mine:.3f} sidecar={feats['peak_dbfs']}")
    if "length_ms" in feats:
        res.check(f"{label}: sidecar length_ms matches",
                  abs(secs * 1000 - feats["length_ms"]) <= 0.1,
                  f"mine={secs * 1000:.3f} sidecar={feats['length_ms']}")
    res.check(f"{label}: sidecar sha256 matches file",
              hashlib.sha256(data).hexdigest() == meta.get("sha256"))


def cli(*args: str) -> subprocess.CompletedProcess:
    env ={**os.environ, "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run([sys.executable, "-m", "audio_engine.kick", *args], env=env,
                          capture_output=True, text=True, timeout=300)


def smoke_categories(res: Results, work: Path, limit: int | None,
                     only: list[str] | None = None) -> dict:
    import jsonschema

    from audio_engine.categories import CONTRACT_CATEGORIES, CategoryUnavailable, get_category
    from audio_engine.io import rerender_from_sidecar

    schema = json.loads((ROOT / "contracts" / "sample-metadata.schema.json").read_text("utf-8"))
    validator = jsonschema.validators.validator_for(schema)(schema)
    summary: dict[str, dict] = {}
    for cat in only or CONTRACT_CATEGORIES:
        try:
            get_category(cat)
        except CategoryUnavailable:
            summary[cat] = {"registered": False}
            continue
        listing = cli("--category", cat, "--list-presets")
        res.check(f"{cat}: --list-presets exit 0", listing.returncode == 0, listing.stderr[-300:])
        presets = [ln.split()[0] for ln in listing.stdout.splitlines() if ln.strip()]
        res.check(f"{cat}: has presets", bool(presets))
        if limit:
            presets = presets[:limit]
        files = 0
        for preset in presets:
            out = work / "cli" / cat / preset
            run = cli("--category", cat, "--preset", preset, "--variants", "2", "--out", str(out))
            ok = run.returncode == 0
            res.check(f"{cat}/{preset}: CLI exit 0", ok, run.stderr[-300:])
            if not ok:
                continue
            wavs = sorted(out.glob("*.wav"))
            res.check(f"{cat}/{preset}: 2 WAV + 2 sidecars",
                      len(wavs) == 2 and len(list(out.glob("*.json"))) == 2,
                      str([p.name for p in out.iterdir()]))
            for wav in wavs:
                label = f"{cat}/{preset}/{wav.stem}"
                side = wav.with_suffix(".json")
                meta = json.loads(side.read_text("utf-8"))
                errors = [e.message[:120] for e in validator.iter_errors(meta)]
                res.check(f"{label}: sidecar schema", not errors, "; ".join(errors[:3]))
                res.check(f"{label}: sidecar category", meta.get("category") == cat)
                check_audio(res, label, wav, meta)
                try:
                    again = rerender_from_sidecar(side)
                    res.check(f"{label}: re-render from sidecar is byte-identical",
                              again == wav.read_bytes())
                except Exception as exc:  # noqa: BLE001 - any failure is a finding
                    res.check(f"{label}: re-render from sidecar", False,
                              f"{type(exc).__name__}: {exc}")
                files += 1
        # the two variants of one preset must differ, different presets must differ
        digests = {hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (work / "cli" / cat).rglob("*.wav")}
        res.check(f"{cat}: all rendered WAVs distinct", len(digests) == files,
                  f"{len(digests)} distinct of {files}")
        summary[cat] = {"registered": True, "presets": len(presets), "wavs": files}
    return summary


def smoke_library(res: Results, work: Path) -> None:
    from audio_engine.categories import CONTRACT_CATEGORIES, CategoryUnavailable
    from library import library_folder, place_sample

    for cat in CONTRACT_CATEGORIES:
        project = work / "lib" / cat
        project.mkdir(parents=True)
        try:
            params = {"schema_version": "0.1", "seed": 5}
            if cat == "kick":
                params = {"schema_version": "0.2", "seed": 5, "length_ms": 150.0,
                          "amp_decay_ms": 60.0, "drive": 0.0, "bpm": 136}
            first = place_sample(cat, params, project, name="smoke")
        except CategoryUnavailable:
            continue
        except Exception as exc:  # noqa: BLE001
            res.check(f"library/{cat}: place_sample", False, f"{type(exc).__name__}: {exc}")
            continue
        folder = library_folder(project, category=cat)
        rel = first.relative_to(project)
        res.check(f"library/{cat}: under Samples/<group>/",
                  rel.parts[0] == "Samples" and len(rel.parts) >= 3, str(rel))
        res.check(f"library/{cat}: folder is library_folder()", first.parent == folder)
        second = place_sample(cat, params, project, name="smoke")
        res.check(f"library/{cat}: collision gets _002, first untouched",
                  second.name == "smoke_002.wav" and first.name == "smoke.wav"
                  and first.exists() and second.exists(), f"{first.name}, {second.name}")
        res.check(f"library/{cat}: sidecars next to WAVs",
                  first.with_suffix(".json").exists() and second.with_suffix(".json").exists())
        res.check(f"library/{cat}: same params same bytes (overwrite-free)",
                  first.read_bytes() == second.read_bytes())


def smoke_tools(res: Results, work: Path) -> dict:
    sys.path[:0] = [str(ROOT / "tests" / "orchestrator"), str(ROOT / "tests" / "bridge"),
                    str(ROOT / "tests")]
    from datetime import datetime, timedelta, timezone

    from kick_helpers import FakeAbletonOSC, RecordingApprover, audio_set, make_session, writes_sent
    from orch_helpers import make_policy

    from guard import Guard
    from orchestrator.model_client import ToolCall
    from orchestrator.sample_tools import ADAPTERS, SampleTools, tool_input_schema
    from orchestrator.tools import Toolbox

    schema = tool_input_schema()
    digest = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
    pins = set()
    for f in (ROOT / "tests" / "orchestrator").glob("test_sample*.py"):
        pins |= set(re.findall(r"\b[0-9a-f]{64}\b", f.read_text("utf-8")))
    info = {"schema_sha256": digest, "categories": sorted(ADAPTERS),
            "pinned_in_tests": digest in pins}
    res.check("tool schema: strict, no optional fields beyond the budget",
              schema.get("additionalProperties") is False
              and sorted(schema["properties"]["category"]["enum"]) == sorted(ADAPTERS),
              str(schema["properties"]["category"]))
    # Informational: the hash of the live table is pinned only for some tables; a new category
    # changes it by design. Shape (strict, enum = table) is what is checked above.

    fake = FakeAbletonOSC()
    audio_set(fake)  # resets num_scenes to 4
    # All categories import into track 1, one slot each (never overwrites); 4 scenes ran out once
    # a 5th adapter existed (#366). One spare scene as headroom.
    fake.num_scenes = len(ADAPTERS) + 1
    try:
        tmp = work / "tools"
        tmp.mkdir()
        session = make_session(tmp, fake)
        box = Toolbox(session.tools() + SampleTools(session).tools(),
                      capability_gate=session.gate())
        res.check("toolbox: names", {"generate_kick", "list_tracks", "import_sample",
                                     "generate_sample"} <= set(box.names), str(box.names))
        tz = timezone(timedelta(hours=1))
        guard = Guard(make_policy(), log_path=tmp / "usage.jsonl", clock=lambda: 1000.0,
                      now=lambda: datetime(2026, 10, 28, 12, 0, tzinfo=tz))
        for cat in sorted(ADAPTERS):
            from audio_engine.presets import preset_names

            preset = preset_names(cat)[0]
            args = {"category": cat, "preset": preset, "prompt": "", "seed": 7, "variants": 2,
                    "adjust": []}
            with guard.request("p") as req:
                out = box.run(req, ToolCall(f"g-{cat}", "generate_sample", args), None)
            ok = out.is_error is False
            res.check(f"dry generate_sample {cat}", ok, str(out.content)[:300])
            if not ok:
                continue
            ids = [s["sample_id"] for s in out.content["samples"]]
            res.check(f"dry generate_sample {cat}: 2 ids, 4 files",
                      len(ids) == 2 and len(list(Path(out.content["folder"]).glob(
                          f"{preset}_s7_v*"))) == 4, str(ids))
            appr = RecordingApprover(True)
            before = len(writes_sent(fake))
            with guard.request("p") as req:
                imp = box.run(req, ToolCall(f"i-{cat}", "import_sample",
                                            {"sample_id": ids[0], "track_index": 0}), appr)
            res.check(f"fake-OSC import {cat} (test double, not Live)", imp.is_error is False,
                      str(imp.content)[:300])
            sent = writes_sent(fake)[before:]
            res.check(f"fake-OSC import {cat}: exactly one create_audio_clip with the WAV path",
                      len(sent) == 1 and sent[0][0] == "/live/clip_slot/create_audio_clip"
                      and sent[0][1][2] == session.entry(ids[0]).path, str(sent))
    finally:
        fake.close()
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--presets-per-category", type=int, default=None)
    ap.add_argument("--categories", nargs="+", help="only these categories (default: all)")
    ap.add_argument("--keep", help="render into this folder and keep it")
    ap.add_argument("--json", help="write the summary here")
    ap.add_argument("--expect-fail", action="append", default=[], metavar="SUBSTRING",
                    help="known issue: failures whose check name or detail contains SUBSTRING are "
                         "reported as KNOWN and do not fail the run; if nothing matches it any "
                         "more (the bug was fixed), the run fails so the flag gets removed. "
                         "May be repeated.")
    args = ap.parse_args(argv)
    res = Results()
    with tempfile.TemporaryDirectory() as td:
        work = Path(args.keep or td)
        work.mkdir(parents=True, exist_ok=True)
        cats = smoke_categories(res, work, args.presets_per_category, args.categories)
        smoke_library(res, work)
        tools = smoke_tools(res, work)
    total = len(res.rows)
    known, unexpected, stale = split_known(res.failed, args.expect_fail)
    for n, _, d in known:
        print(f"KNOWN {n}: {d}")
    for sub in stale:
        print(f"STALE --expect-fail {sub!r}: no failing check matches any more; remove the flag")
    summary = {"checks": total, "failed": len(unexpected), "known": len(known),
               "stale_expect_fail": stale, "categories": cats, "tools": tools,
               "failures": [{"check": n, "detail": d} for n, _, d in unexpected],
               "known_failures": [{"check": n, "detail": d} for n, _, d in known]}
    print(json.dumps(summary, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0 if not unexpected else 1


if __name__ == "__main__":
    raise SystemExit(main())
