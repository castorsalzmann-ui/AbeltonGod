"""Build the static cockpit site (GitHub Pages) from the real data.

Usage:
    python scripts/qa/cockpit_build.py <out_dir> [--repo DIR] [--collector FILE]
                                       [--prev-gate-url URL] [--no-gate] [--max-age-min N]

Runs cockpit_collect.py on a throwaway clone of --repo (default: this checkout) and writes
<out_dir>/index.html (page + shim + embedded data for file://), <out_dir>/data/*.json and
<out_dir>/snapshot.json (build time). Fails closed (exit 1, <out_dir> untouched): collector
error, a required dataset missing or empty, or a data timestamp older than --max-age-min.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE / "cockpit_page"
# Datasets the page reads; "may_be_empty" ones are legitimately empty (nothing for the user).
REQUIRED = ["features", "research", "snapshot", "user_actions", "active_work", "issues",
            "prs", "gate", "phases", "pipeline", "capabilities"]
MAY_BE_EMPTY = {"user_actions", "active_work", "prs"}
SHELL = """<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AbeltonGod Cockpit</title>
<style>:root{--font-anthropic-sans:system-ui,-apple-system,"Segoe UI",sans-serif;
--cds-dur-slow:.2s;--cds-ease-out:ease-out}
body{margin:0;background:#1c1c1c}</style>
%(style)s
</head><body><div id="dash-root">
%(body)s
</div>
<script>window.COCKPIT_DATA = %(data)s;</script>
<script>
%(shim)s
</script>
<script>
%(script)s
</script>
</body></html>
"""


class BuildError(Exception):
    pass


def fetch_prev_gate(url: str, dest: Path) -> str | None:
    """Earlier gate history (optional: the very first run has none)."""
    try:
        with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 (https URL from workflow)
            rows = json.loads(r.read())
        if isinstance(rows, list) and rows:
            dest.write_text(json.dumps(rows), encoding="utf-8")
            return str(dest)
        why = "not a non-empty list"
    except (OSError, ValueError) as e:
        why = repr(e)
    print(f"cockpit_build: WARNING no previous gate.json from {url}: {why}; "
          "gate history starts again", file=sys.stderr)
    return None


def collect(repo: Path, collector: Path, work: Path, prev_url: str | None,
            no_gate: bool = False) -> Path:
    clone = work / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True)
    data = work / "data"
    cmd = [sys.executable, str(collector), str(clone), str(data)]
    if prev_url and (prev := fetch_prev_gate(prev_url, work / "prev_gate.json")):
        cmd.append(prev)
    if no_gate and len(cmd) == 4:
        raise BuildError("--no-gate needs a reachable previous gate.json (--prev-gate-url)")
    env = {**os.environ, "COCKPIT_SKIP_GATE": "1"} if no_gate else None
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        raise BuildError(f"collector exited with {r.returncode}")
    return data


def check(data: Path, max_age_min: float) -> dict:
    loaded = {}
    for name in REQUIRED:
        f = data / f"{name}.json"
        if not f.exists():
            raise BuildError(f"dataset {name} missing")
        rows = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or (not rows and name not in MAY_BE_EMPTY):
            raise BuildError(f"dataset {name} empty or not a list")
        loaded[name] = rows
    at = datetime.fromisoformat(loaded["snapshot"][0]["at"])
    age = (datetime.now(UTC) - at).total_seconds() / 60
    if age > max_age_min or age < -5:
        raise BuildError(f"snapshot time {at.isoformat()} is {age:.0f} min old")
    return loaded


def assemble(out: Path, data: Path, loaded: dict) -> None:
    html = SHELL % {
        "style": (PAGE / "style.part").read_text(encoding="utf-8"),
        "body": (PAGE / "body.html").read_text(encoding="utf-8"),
        # "</" escaped so a "</script>" inside data cannot end the tag
        "data": json.dumps(loaded, ensure_ascii=False).replace("</", "<\\/"),
        "shim": (PAGE / "shim.js").read_text(encoding="utf-8"),
        "script": (PAGE / "script.js").read_text(encoding="utf-8"),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "data").mkdir(exist_ok=True)
    for name in REQUIRED:
        shutil.copyfile(data / f"{name}.json", out / "data" / f"{name}.json")
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "snapshot.json").write_text(
        json.dumps({"built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "data_at": loaded["snapshot"][0]["at"]}), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--repo", default=str(HERE.parents[1]))
    ap.add_argument("--collector", default=str(HERE / "cockpit_collect.py"))
    ap.add_argument("--prev-gate-url")
    ap.add_argument("--no-gate", action="store_true",
                    help="skip the gate run, reuse previous gate.json (needs --prev-gate-url)")
    ap.add_argument("--max-age-min", type=float, default=30)
    a = ap.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory() as w:
            data = collect(Path(a.repo), Path(a.collector), Path(w), a.prev_gate_url, a.no_gate)
            loaded = check(data, a.max_age_min)
            assemble(Path(a.out_dir), data, loaded)
    except (BuildError, subprocess.CalledProcessError, ValueError, KeyError, IndexError) as e:
        print(f"cockpit_build: FAILED, nothing written: {e!r}", file=sys.stderr)
        return 1
    print(f"cockpit_build: site written to {a.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
