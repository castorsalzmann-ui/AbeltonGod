"""Command line for the arrangement plan generator (#222, G5).

    python -m orchestrator.plan_cli --genre techno --bpm 140 --minutes 6 --out plan.json
    python -m orchestrator.plan_cli --genre trance --bpm 138 --bars 200 --set intro_length=16 \
        --out plan.json

Writes arrangement-plan v0.1 JSON (``contracts/arrangement-plan.schema.json``) and prints the
adjustments and warnings. Never overwrites a file. No Claude, no Live. Exit codes: 0 written,
1 the generator refused the request (texts as in the Claude tool), 2 usage or file problem.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from orchestrator.arrangement_generator import generate_plan
from orchestrator.plan_tools import build_request, plan_summary, refusal_text


def _setting(text: str) -> tuple[str, int | str]:
    key, sep, value = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError("use --set key=value")
    return key, int(value) if value.lstrip("-").isdigit() else value


def main(argv: list[str] | None = None, *, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m orchestrator.plan_cli")
    parser.add_argument("--genre", required=True)
    parser.add_argument("--bpm", required=True, type=float)
    length = parser.add_mutually_exclusive_group(required=True)
    length.add_argument("--bars", type=float)
    length.add_argument("--minutes", type=float)
    parser.add_argument("--set", dest="changes", action="append", type=_setting, default=[],
                        metavar="KEY=VALUE", help="change a setting (repeatable)")
    parser.add_argument("--out", required=True, type=Path, help="plan JSON file to create")
    args = parser.parse_args(argv)
    unit, value = ("bars", args.bars) if args.bars is not None else ("minutes", args.minutes)
    req = build_request(args.genre, args.bpm, value, unit, args.changes)
    result = generate_plan(req)
    if not result.ok:
        out.write(refusal_text(result.errors) + "\n")
        return 1
    try:
        with args.out.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(result.plan, indent=2) + "\n")
    except OSError as exc:
        out.write(f"cannot create {args.out}: {exc}\n")
        return 2
    summary = plan_summary(result.plan)
    out.write(f"Wrote {args.out}: {summary['total_bars']} bars, "
              f"{summary['duration_minutes']} min at {summary['bpm']:g} BPM.\n")
    for item in result.adjustments:
        out.write(f"adjustment {item['code']}: {item['detail']}\n")
    for item in result.warnings:
        out.write(f"warning {item['code']}: {item['detail']}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
