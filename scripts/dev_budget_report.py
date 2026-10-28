"""Summarise budget warnings from Claude Code development sessions.

Reads logs/dev-usage/waste-events.jsonl written by .claude/hooks/waste_watch.py.

    python scripts/dev_budget_report.py                     # events not yet reviewed
    python scripts/dev_budget_report.py --branch phase-01/x # one branch (for /finish-task)
    python scripts/dev_budget_report.py --all
    python scripts/dev_budget_report.py --mark-reviewed     # after /close-phase handled them

A kind of warning that occurs in two or more sessions is marked RECURRING: that is the
signal to add or sharpen a rule in CLAUDE.md ("Budget lessons").
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "logs" / "dev-usage"

KIND_HINTS = {
    "repeat": "identical call repeated without a file change",
    "fail_streak": "several failed tool calls in a row",
    "edits": "one file edited very often",
    "tool_calls": "very long session",
    "subagents": "many subagents in one session",
    "reviewer": "more than two review rounds",
}


def load_events(path: Path) -> list[dict]:
    events: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and isinstance(item.get("ts"), str):
            events.append(item)
    return events


def read_marker(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def build_report(events: list[dict]) -> tuple[str, list[str]]:
    """Return (report text, recurring kinds)."""
    if not events:
        return "No budget warnings in the selected range.", []
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_kind[str(e.get("kind"))].append(e)
    recurring = sorted(
        kind for kind, items in by_kind.items() if len({i.get("session") for i in items}) >= 2
    )
    n_sessions = len({e.get("session") for e in events})
    lines = [f"{len(events)} budget warning(s), {n_sessions} session(s)"]
    for kind in sorted(by_kind, key=lambda k: -len(by_kind[k])):
        items = by_kind[kind]
        sessions = len({i.get("session") for i in items})
        flag = "  RECURRING" if kind in recurring else ""
        lines.append(
            f"- {kind} ({KIND_HINTS.get(kind, 'unknown kind')}): "
            f"{len(items)}x in {sessions} session(s){flag}"
        )
        for item in items[-3:]:
            lines.append(f"    {item['ts']} {item.get('branch') or '?'}: {item.get('message', '')}")
    return "\n".join(lines), recurring


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="include already reviewed events")
    parser.add_argument("--branch", help="only events from this branch")
    parser.add_argument("--mark-reviewed", action="store_true", help="mark everything as reviewed")
    parser.add_argument("--base", type=Path, default=BASE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    events = load_events(args.base / "waste-events.jsonl")
    marker_path = args.base / "last-review.txt"
    since = None if args.all else read_marker(marker_path)
    if since:
        events = [e for e in events if e["ts"] > since]
    if args.branch:
        events = [e for e in events if e.get("branch") == args.branch]

    text, _ = build_report(events)
    print(text)
    if args.mark_reviewed:
        args.base.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        marker_path.write_text(now + "\n", encoding="utf-8")
        print(f"Marked reviewed up to {now}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
