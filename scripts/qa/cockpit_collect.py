"""AbeltonGod cockpit collector.

Reads GitHub (REST via `gh api`, read-only: GET requests only) and a clone of the repo,
writes one JSON file per cockpit dataset into OUT_DIR.

Usage:
    python scripts/qa/cockpit_collect.py <repo_dir> <out_dir> [<previous_gate.json>]

    <repo_dir>            checkout to read (docs/, contracts/, config/, git log)
    <out_dir>             gets phases.json, pipeline.json, features.json, research.json,
                          snapshot.json, issues.json, reviews.json, prs.json,
                          decisions.json, decision_refs.json, ci_runs.json, commits.json,
                          capabilities.json, guard.json, guard_budget.json, guard_usage.json,
                          gate.json
    <previous_gate.json>  optional earlier gate.json; its history is kept, the row for the
                          current SHA is replaced

Needs: gh with REST access to castorsalzmann-ui/abeltongod, git, python3.11+.

Run it on a dedicated clone, not on a checkout you work in: it runs `pip install -e .` and
`pytest` inside <repo_dir>, which writes `*.egg-info` and wipes `.pytest_tmp/`, so a
concurrent pytest run in the same checkout collides with it.
Runs `ruff check .` and `pytest -q` in a throwaway venv to record the gate (takes minutes).
Prints a one-line JSON summary (sha and row counts) at the end.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from itertools import takewhile
from pathlib import Path

R = "repos/castorsalzmann-ui/abeltongod"


def gh(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def gh_all(path: str):
    rows, page = [], 1
    sep = "&" if "?" in path else "?"
    while True:
        chunk = gh(f"{path}{sep}per_page=100&page={page}")
        if isinstance(chunk, dict):
            chunk = chunk.get("workflow_runs", [])
        rows += chunk
        if len(chunk) < 100:
            return rows
        page += 1


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def write(out: Path, name: str, rows) -> None:
    (out / f"{name}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )


# ---------- phases ----------
PHASE_NAMES = {
    "00": "Setup", "01": "Kick-Engine", "02": "Ableton-Bridge", "03": "Sample-Import",
    "04a": "Resource Guard", "04b": "Claude-Orchestrator", "05": "Kick-Charakter",
}
TRACK = {
    "00": "Setup", "01": "Kick", "02": "Bridge", "03": "Import", "04a": "Guard",
    "04b": "Orchestrator", "05": "Kick",
}


def phase_key(s: str | None) -> str | None:
    if not s:
        return None
    s = s.lower()
    return s if s.startswith("04") and len(s) == 3 else s[:2]


def phase_title(txt: str) -> str:
    """Readable name from a spec's title line `# PHASE 06 — Name (detail)` -> `Name`."""
    m = re.search(r"^# PHASE \S+\s+[—–-]\s+(.+?)\s*$", txt, re.M)
    return re.sub(r"\s*\(.*\)$", "", m.group(1)).strip() if m else ""


def expand_phase_refs(text: str) -> list[str]:
    refs: list[str] = []
    for a, b in re.findall(r"\b(0\d)\s*[–-]\s*(0\d[ab]?)\b", text):
        for n in range(int(a), int(b[:2]) + 1):
            refs.append("04a" if n == 4 else f"{n:02d}")
    text = re.sub(r"\b0\d\s*[–-]\s*0\d[ab]?\b", " ", text)
    refs += [m.lower() for m in re.findall(r"\b(0\d[abAB]?)\b", text)]
    return sorted(set(refs), key=lambda x: (x[:2], x))


def collect_phases(repo: Path) -> list[dict]:
    rows = []
    for f in sorted((repo / "docs" / "phases").glob("PHASE_*.md")):
        m = re.match(r"PHASE_(\d\d[AB]?)_", f.name)
        if not m:
            continue
        pid = m.group(1).lower()
        txt = f.read_text(encoding="utf-8")
        status = (
            re.search(r"\*\*Status:\*\*\s*([A-Z]+(?: [A-Z]+)*)", txt) or [None, "PLANNED"]
        )[1].strip()
        tested = (re.search(r"\*\*Tested in:\*\*\s*(.+)", txt) or [None, ""])[1].strip()
        goal = ""
        g = re.search(r"## Objective\s+(.+?)\n\n", txt, re.S)
        if g:
            goal = " ".join(g.group(1).split())
        acc = re.search(r"## Acceptance criteria(.+?)(\n## |\Z)", txt, re.S)
        boxes = re.findall(r"- \[( |x|X)\]", acc.group(1)) if acc else []
        pre = re.search(r"## Prerequisites(.+?)(\n## |\Z)", txt, re.S)
        first = re.split(r"(?<=\.)\s", pre.group(1).strip(), maxsplit=1)[0] if pre else ""
        deps = [d for d in expand_phase_refs(first) if d != pid]
        rows.append({
            "phase": pid, "name": PHASE_NAMES.get(pid) or phase_title(txt) or pid,
            "goal": goal, "file_status": status,
            "criteria_total": len(boxes), "criteria_met": sum(b.lower() == "x" for b in boxes),
            "depends_on": ", ".join(deps), "tested_in": tested, "order": len(rows),
        })
    return rows


# ---------- pipeline (parallel tracks) ----------
PIPELINE_COLUMNS = {
    "track": "track", "phase": "phase", "role(s)": "roles", "roles": "roles", "role": "roles",
    "goal": "goal", "status": "status", "next": "next",
}


def _cells(line: str) -> list[str]:
    inner = line.strip()[1:-1] if line.strip().endswith("|") else line.strip()[1:]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", inner)]


def collect_pipeline(repo: Path) -> list[dict]:
    """Rows of the first table under `## Pipeline` in docs/ROADMAP.md ([] if there is none)."""
    f = repo / "docs" / "ROADMAP.md"
    txt = f.read_text(encoding="utf-8") if f.exists() else ""
    sec = re.search(r"^## Pipeline\b.*?\n(.*?)(?=^## |\Z)", txt, re.S | re.M)
    lines = (sec.group(1) if sec else "").splitlines()
    start = next((k for k, ln in enumerate(lines) if ln.lstrip().startswith("|")), None)
    if start is None:
        return []
    table = []
    for ln in lines[start:]:
        if not ln.lstrip().startswith("|"):
            break
        table.append(_cells(ln))
    header = [PIPELINE_COLUMNS.get(h.lower(), "") for h in table[0]]
    rows = []
    for cells in table[1:]:
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue  # separator line
        row = {k: "" for k in ("track", "phase", "roles", "goal", "status", "next")}
        for key, val in zip(header, cells, strict=False):
            if key:
                row[key] = val
        rows.append(row)
    return rows


# ---------- features & research notes ----------
FEATURE_STATUS = ("Fertig", "In Arbeit", "Geplant", "Parkplatz")
FEATURE_COLUMNS = {
    "feature": "feature", "phase": "phase", "status": "status", "research": "research",
    "work": "work",
}
RESEARCH_URL = "https://github.com/castorsalzmann-ui/AbeltonGod/blob/main/docs/research/"


def collect_features(repo: Path) -> list[dict]:
    """Rows of the table under `## Features` in docs/ROADMAP.md ([] + stderr message if absent).

    Warns on stderr for every Research cell that names a file missing in docs/research/.
    """
    f = repo / "docs" / "ROADMAP.md"
    txt = f.read_text(encoding="utf-8") if f.exists() else ""
    sec = re.search(r"^## Features\b.*?\n(.*?)(?=^## |\Z)", txt, re.S | re.M)
    lines = (sec.group(1) if sec else "").splitlines()
    start = next((k for k, ln in enumerate(lines) if ln.lstrip().startswith("|")), None)
    if start is None:
        print("cockpit_collect: no '## Features' table in docs/ROADMAP.md -> features.json is []",
              file=sys.stderr)
        return []
    table = [_cells(ln) for ln in takewhile(lambda x: x.lstrip().startswith("|"), lines[start:])]
    header = [FEATURE_COLUMNS.get(h.lower(), "") for h in table[0]]
    rows = []
    for cells in table[1:]:
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue  # separator line
        raw = {k: "" for k in FEATURE_COLUMNS.values()}
        for key, val in zip(header, cells, strict=False):
            if key:
                raw[key] = val
        files = [x.strip().strip("`") for x in raw["research"].split(",")]
        files = [x for x in files if x and x != "-"]
        for name in files:
            if not (repo / "docs" / "research" / name).is_file():
                print(f"cockpit_collect: feature '{raw['feature']}' names research file "
                      f"'{name}' which does not exist in docs/research/", file=sys.stderr)
        rows.append({
            "feature": raw["feature"], "phase": raw["phase"],
            "status": raw["status"] if raw["status"] in FEATURE_STATUS else "Unklar",
            "research": files, "work": raw["work"], "research_count": len(files),
        })
    return rows


def collect_research(repo: Path, features: list[dict]) -> list[dict]:
    """One row per docs/research/*.md, newest first; `mapped` = some feature lists the file."""
    rows = []
    for f in (repo / "docs" / "research").glob("*.md"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)\.md$", f.name)
        txt = f.read_text(encoding="utf-8")
        h1 = re.search(r"^# (.+?)\s*$", txt, re.M)
        names = [x["feature"] for x in features if f.name in x["research"]]
        rows.append({
            "file": f.name, "date": m.group(1) if m else "",
            "title": h1.group(1) if h1 else f.name,
            "topic": m.group(2) if m else f.stem, "features": names, "mapped": bool(names),
            "url": RESEARCH_URL + f.name, "words": len(txt.split()),
        })
    return sorted(rows, key=lambda r: (r["date"], r["file"]), reverse=True)


def collect_snapshot(sha: str, issues: list[dict]) -> list[dict]:
    """One row: when the run happened, on which commit, and the PR/issue counts."""
    prs = [i for i in issues if i["kind"] == "PR"]
    return [{
        "at": datetime.now(UTC).isoformat(timespec="seconds"), "sha": sha,
        "open_prs": sum(p["closed"] is None for p in prs),
        "open_issues": sum(i["closed"] is None for i in issues if i["kind"] != "PR"),
        "merged_prs": sum(p["merged"] is not None for p in prs),
    }]


# ---------- active work & user actions ----------
def _labels(row: dict) -> list[str]:
    return [x for x in row["labels"].split(", ") if x]


def collect_active_work(issues: list[dict], head_refs: dict[int, str]) -> list[dict]:
    """Open issues labelled status:in-progress and open PRs with a label or a `prefix/` branch."""
    rows = []
    for i in issues:
        if i["closed"] is not None:
            continue
        labels = _labels(i)
        if i["kind"] == "PR":
            ref = head_refs.get(i["number"], "")
            prefix = ref.split("/")[0] if "/" in ref else ""
            if not labels and not prefix:
                continue
        elif "status:in-progress" not in labels:
            continue
        else:
            prefix = ""
        role = next((x.split(":", 1)[1] for x in labels if x.startswith("agent:")), prefix or "?")
        status = next((x.split(":", 1)[1] for x in labels if x.startswith("status:")), "")
        rows.append({
            "role": role, "kind": "PR" if i["kind"] == "PR" else "Issue", "number": i["number"],
            "title": i["title"], "url": i["url"], "status": status or "PR offen",
            "updated": i["updated"],
        })
    return sorted(rows, key=lambda r: r["updated"] or "", reverse=True)


GH_PREFIX = "https://github.com/castorsalzmann-ui/AbeltonGod/"
ACTION_KINDS = ("Merge", "Test", "Entscheidung", "Schließen")


def collect_user_actions(repo: Path, issues: list[dict]) -> list[dict]:
    """Rows of docs/WAITING_ON_USER.md (Was | Link | Aufgabe | Seit) plus every open PR that
    the table does not list (auto=true)."""
    f = repo / "docs" / "WAITING_ON_USER.md"
    by_num = {i["number"]: i for i in issues}
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    if not f.exists():
        print("cockpit_collect: docs/WAITING_ON_USER.md is missing -> only automatic rows",
              file=sys.stderr)
    table = [_cells(ln) for ln in lines if ln.lstrip().startswith("|")]
    header = [h.lower() for h in table[0]] if table else []
    rows, listed = [], set()
    for cells in table[1:]:
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        raw = dict(zip(header, cells, strict=False))
        link = raw.get("link", "")
        m = re.search(r"\((https?://[^)\s]+)\)", link)
        url = (m.group(1) if m else link.strip())
        url = url if url.startswith(GH_PREFIX) else ""
        nm = re.search(r"/(?:issues|pull)/(\d+)", url)
        number = int(nm.group(1)) if nm else None
        item = by_num.get(number)
        was = raw.get("was", "")
        kind = next((k for k in ACTION_KINDS if was.lower().startswith(k.lower())), "Sonstiges")
        if item is None:
            state = ""
        elif item["closed"] is None:
            state = "open"
        else:
            state = "merged" if item["merged"] else "closed"
        if number is not None:
            listed.add(number)
        rows.append({
            "kind": kind, "url": url, "number": number, "title": item["title"] if item else "",
            "task": raw.get("aufgabe", ""), "since": raw.get("seit", ""), "state": state,
            "auto": False,
        })
    for i in issues:
        if i["kind"] == "PR" and i["closed"] is None and i["number"] not in listed:
            rows.append({
                "kind": "Merge", "url": i["url"], "number": i["number"], "title": i["title"],
                "task": "PR prüfen und mergen (CI grün?)", "since": (i["created"] or "")[:10],
                "state": "open", "auto": True,
            })
    return rows


# ---------- issues & PRs ----------
# `agent:<key>` label -> owner shown in the cockpit. Unknown keys are shown as they are.
AGENT = {
    "audio": "audio-engineer", "bridge": "bridge-engineer", "main": "main session",
    "reviewer": "reviewer", "review": "reviewer",  # the GitHub label is `agent:review`
    # D-017 roles
    "qa": "qa-tester", "sound": "sound-designer", "orchestrator": "orchestrator-engineer",
    "research": "researcher",
}
ISSUE_STATUS = {
    "in-progress": "In Arbeit", "in-review": "In Review", "blocked": "Blockiert",
    "ready": "Bereit",
}


def collect_issues(repo: Path) -> tuple[list[dict], list[dict]]:
    raw = gh_all(f"{R}/issues?state=all")
    state_md = (repo / "docs" / "CURRENT_STATE.md").read_text(encoding="utf-8")
    nxt = re.search(r"## Next step(.+?)(\n## |\Z)", state_md, re.S)
    order: list[int] = []
    for n in re.findall(r"#(\d+)", nxt.group(1) if nxt else ""):
        if int(n) not in order:
            order.append(int(n))
    by_num = {i["number"]: i for i in raw}
    rows, bodies = [], []
    for i in raw:
        labels = [lb["name"] for lb in i["labels"]]
        is_pr = "pull_request" in i
        merged = (i.get("pull_request") or {}).get("merged_at")
        title = i["title"]
        pm = re.search(r"[Pp]hase[ -](\d\d[ab]?)", title)
        lab_phase = next((lb.split(":")[1] for lb in labels if lb.startswith("phase:")), None)
        phase = phase_key(pm.group(1) if pm else lab_phase)
        if phase == "04" or (phase is None and lab_phase == "04"):
            phase = "04a"
        status_lab = next((lb.split(":")[1] for lb in labels if lb.startswith("status:")), None)
        if i["state"] == "closed":
            status = "Fertig" if (merged or not is_pr) else "Geschlossen"
        elif is_pr:
            status = "In Review"
        else:
            status = ISSUE_STATUS.get(status_lab or "", "Offen")
        # waiting for the user: any open PR, or an open issue labelled needs-user / needs:user-*
        needs_user = i["state"] == "open" and (
            is_pr or bool({"needs-user", "needs:user-test", "needs:user-decision"} & set(labels))
        )
        agent = next(
            (AGENT.get(lb.split(":")[1], lb.split(":")[1])
             for lb in labels if lb.startswith("agent:")),
            "",
        )
        if needs_user and status != "Blockiert":
            owner = "Du"
        elif agent:
            owner = agent
        else:
            owner = "Du" if is_pr and i["state"] == "open" else "nicht zugewiesen"
        body = i.get("body") or ""
        dm = re.search(r"Depends on:?\**\s*(.+)", body, re.I)
        deps = [int(x) for x in re.findall(r"#(\d+)", dm.group(1))] if dm else []
        deps_open = (
            [d for d in deps if d in by_num and by_num[d]["state"] == "open"]
            if i["state"] == "open" else []
        )
        kind = "PR" if is_pr else ("Side-Finding" if "side-finding" in labels else "Issue")
        in_order = i["number"] in order and i["state"] == "open"
        rows.append({
            "number": i["number"], "kind": kind, "title": title, "phase": phase or "—",
            "track": TRACK.get(phase or "", "Sonstiges"), "owner": owner, "status": status,
            "needs_user": needs_user, "labels": ", ".join(labels),
            "depends_on": ", ".join(map(str, deps)), "waiting_on": ", ".join(map(str, deps_open)),
            "next_rank": order.index(i["number"]) + 1 if in_order else None,
            "comments": i["comments"], "created": i["created_at"], "closed": i["closed_at"],
            "merged": merged, "url": i["html_url"], "updated": i.get("updated_at"),
        })
        bodies.append({
            "number": i["number"], "kind": "PR" if is_pr else "Issue", "title": title,
            "text": body,
        })
    rows.sort(key=lambda r: r["number"])
    return rows, bodies


# ---------- reviews ----------
SEV = ("blocker", "major", "minor", "nit")


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def collect_reviews(issues: list[dict], bodies: list[dict]) -> tuple[list[dict], list[dict]]:
    reviews, prs = [], []
    for pr in [r for r in issues if r["kind"] == "PR"]:
        n = pr["number"]
        rv = gh_all(f"{R}/pulls/{n}/reviews")
        detail = gh(f"{R}/pulls/{n}")
        for k, r in enumerate(rv, 1):
            b = r.get("body") or ""
            bodies.append(
                {"number": n, "kind": "Review", "title": f"PR #{n} Review {k}", "text": b}
            )
            verdict = re.search(r"Verdict:\s*\**\s*(APPROVE-READY|CHANGES NEEDED)", b)
            passed = re.search(r"(\d[\d,]*) passed", b)
            skipped = re.search(r"(\d+) skipped", b)
            probs = re.findall(
                r"^\*\*(?:\d+|[A-Z]\d+)\.?\s*\[(blocker|major|minor|nit)\]", b, re.M | re.I
            )
            c = Counter(p.lower() for p in probs)
            mut = re.search(r"## Fault injection", b) is not None
            reviews.append({
                "review": f"{n}-{k}", "pr": n, "round": k, "submitted": r["submitted_at"],
                "verdict": verdict.group(1) if verdict else "—",
                "tests_passed": int(passed.group(1).replace(",", "")) if passed else None,
                "tests_skipped": int(skipped.group(1)) if skipped else None,
                "problems": sum(c.values()), **{s: c.get(s, 0) for s in SEV},
                "fault_injection": mut, "fresh_reviewer": "fresh reviewer" in b.lower(),
            })
        for c in gh_all(f"{R}/issues/{n}/comments"):
            bodies.append({
                "number": n, "kind": "Kommentar", "title": pr["title"],
                "text": c.get("body") or "",
            })
        created = _ts(detail["created_at"])
        end = detail.get("merged_at") or detail.get("closed_at")
        hours = None
        if end:
            hours = round((_ts(end) - created).total_seconds() / 3600, 1)
        prs.append({
            "pr": n, "title": detail["title"],
            "state": "gemergt" if detail.get("merged_at") else detail["state"],
            "rounds": len(rv), "commits": detail.get("commits"),
            "additions": detail.get("additions"), "deletions": detail.get("deletions"),
            "changed_files": detail.get("changed_files"), "hours_to_merge": hours,
            "final_verdict": reviews[-1]["verdict"] if rv else "kein Review",
            "created": detail["created_at"], "merged": detail.get("merged_at"),
        })
    for i in [r for r in issues if r["kind"] != "PR" and r["comments"]]:
        for c in gh_all(f"{R}/issues/{i['number']}/comments"):
            bodies.append({
                "number": i["number"], "kind": "Kommentar", "title": i["title"],
                "text": c.get("body") or "",
            })
    return reviews, prs


# ---------- decisions ----------
def _ref_kind(f: str) -> str:
    if f.startswith("tests/"):
        return "Test"
    if f.startswith(("src/", "config/")):
        return "Code"
    if f.startswith("contracts/"):
        return "Contract"
    if f.startswith(".claude/"):
        return "Agent/Skill"
    return "Doku"


def collect_decisions(repo: Path, bodies: list[dict]) -> tuple[list[dict], list[dict]]:
    txt = (repo / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    decs = [{"id": m[0], "date": m[1], "status": m[2], "title": m[3]}
            for m in re.findall(r"^## (D-\d+) · (\S+) · (\w+) — (.+)$", txt, re.M)]
    ids = {d["id"] for d in decs}
    refs: dict[tuple, dict] = {}
    files = run(["git", "ls-files"], cwd=repo).stdout.split()
    for f in files:
        if f == "docs/DECISIONS.md" or not f.endswith((".md", ".py", ".json", ".yml", ".toml")):
            continue
        try:
            t = (repo / f).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for d, cnt in Counter(re.findall(r"\bD-\d{3}\b", t)).items():
            if d in ids:
                refs[(d, f)] = {
                    "decision": d, "ref_kind": _ref_kind(f), "ref": f, "label": f,
                    "mentions": cnt,
                }
    for b in bodies:
        for d, cnt in Counter(re.findall(r"\bD-\d{3}\b", b["text"])).items():
            if d not in ids:
                continue
            kind = "PR" if b["kind"] in ("PR", "Review") else "Issue"
            key = (d, f"#{b['number']}")
            r = refs.setdefault(key, {"decision": d, "ref_kind": kind, "ref": f"#{b['number']}",
                                      "label": b["title"], "mentions": 0})
            r["mentions"] += cnt
    rows = sorted(refs.values(), key=lambda r: (r["decision"], r["ref_kind"], r["ref"]))
    for r in rows:
        r["link"] = f"{r['decision']}|{r['ref']}"
    return decs, rows


# ---------- gate ----------
def run_gate(repo: Path, sha: str, prev: list[dict]) -> list[dict]:
    hist = [r for r in prev if r.get("source") != "Cloud-Gate" or r.get("sha") != sha]
    with tempfile.TemporaryDirectory() as venv:
        run([sys.executable, "-m", "venv", venv])
        py = str(Path(venv) / "bin" / "python")
        run([py, "-m", "pip", "install", "-q", "-e", ".[dev]"], cwd=repo)
        ruff = run([py, "-m", "ruff", "check", "."], cwd=repo)
        t = run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=repo)
    last = (t.stdout.strip().splitlines() or [""])[-1]

    def g(w: str) -> int:
        m = re.search(rf"(\d+) {w}", last)
        return int(m.group(1)) if m else 0

    hist.append({
        "run": f"Cloud-Gate {sha}", "source": "Cloud-Gate", "sha": sha,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "passed": g("passed"), "skipped": g("skipped"), "failed": g("failed") + g("error"),
        "ruff": "sauber" if ruff.returncode == 0 else "Fehler", "platforms": "Linux (Cloud)",
        "summary": last,
    })
    return sorted(hist, key=lambda r: r["date"])


GUARD_LIMIT_NAMES = {
    "max_output_tokens": "Output-Tokens je Aufruf", "max_model_calls": "Modell-Aufrufe",
    "max_tool_calls": "Tool-Aufrufe", "max_budget_usd": "Budget (USD, API-Äquivalent)",
    "timeout_s": "Timeout (s)", "max_identical_tool_calls": "Gleiche Tool-Aufrufe (Schleife)",
    "max_files_written": "Geschriebene Dateien", "max_live_writes": "Schreibzugriffe auf Live",
    "warn_at_fraction": "Warnschwelle (Anteil)",
}
COMMIT_KINDS = {
    "phase-00": "Phase 00", "phase-01": "Phase 01", "phase-02": "Phase 02",
    "phase-03": "Phase 03", "phase-04a": "Phase 04a", "phase-04b": "Phase 04b",
    **{f"phase-0{n}": f"Phase 0{n}" for n in range(5, 10)},
    "state": "State", "docs": "Docs",
}


def write_all(out: Path, datasets: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in datasets.items():
        write(out, name, rows)


def main() -> None:
    """Collect everything in memory first; write only if every GitHub call succeeded, so a
    failed call can never replace good datasets with empty or partial ones (exit code 1)."""
    out = Path(sys.argv[2])
    try:
        datasets = build(Path(sys.argv[1]), sys.argv[3] if len(sys.argv) > 3 else None)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as e:
        detail = (getattr(e, "stderr", "") or "").strip() or repr(e)
        print(f"cockpit_collect: GitHub call failed, nothing written: {detail}", file=sys.stderr)
        sys.exit(1)
    summary = datasets.pop("_summary")
    write_all(out, datasets)
    print(json.dumps(summary))


def build(repo: Path, prev_path: str | None) -> dict:
    prev = json.loads(Path(prev_path).read_text(encoding="utf-8")) if prev_path else []
    pending: dict = {}

    def write(_out, name, rows):  # buffered: see main()
        pending[name] = rows

    out = None
    sha = run(["git", "rev-parse", "--short", "HEAD"], cwd=repo).stdout.strip()

    phases = collect_phases(repo)
    issues, bodies = collect_issues(repo)
    for p in phases:
        mine = [i for i in issues if i["phase"] == p["phase"]]
        if p["file_status"] == "DONE":
            p["status"] = "Fertig"
        elif p["file_status"] == "IN PROGRESS" or any(
            i["status"] in ("Fertig", "In Arbeit", "In Review") for i in mine
        ):
            p["status"] = "In Arbeit"
        else:
            p["status"] = "Geplant"
    write(out, "phases", phases)
    write(out, "pipeline", collect_pipeline(repo) or [{  # a dataset needs at least one row
        "track": "", "phase": "", "roles": "", "goal": "",
        "status": "Keine Pipeline-Tabelle in docs/ROADMAP.md gefunden.", "next": "",
    }])
    features = collect_features(repo)
    write(out, "features", features)
    research = collect_research(repo, features)
    write(out, "research", research)
    write(out, "issues", issues)
    write(out, "snapshot", collect_snapshot(sha, issues))
    head_refs = {
        i["number"]: gh(f"{R}/pulls/{i['number']}")["head"]["ref"]
        for i in issues if i["kind"] == "PR" and i["closed"] is None
    }
    write(out, "active_work", collect_active_work(issues, head_refs))
    write(out, "user_actions", collect_user_actions(repo, issues))
    reviews, prs = collect_reviews(issues, bodies)
    write(out, "reviews", reviews)
    write(out, "prs", prs)
    decs, refs = collect_decisions(repo, bodies)
    write(out, "decisions", decs)
    write(out, "decision_refs", refs)

    runs = gh_all(f"{R}/actions/runs")
    ci = []
    for r in runs:
        a = _ts(r["run_started_at"])
        b = _ts(r["updated_at"])
        ci.append({
            "run_id": str(r["id"]), "branch": r["head_branch"], "sha": r["head_sha"][:7],
            "event": r["event"], "status": r["status"],
            "conclusion": r["conclusion"] or r["status"], "started": r["run_started_at"],
            "duration_s": int((b - a).total_seconds()),
        })
    write(out, "ci_runs", ci)

    log = run(["git", "log", "--format=%h|%cI|%s"], cwd=repo).stdout.strip().splitlines()
    commits = []
    for line in log:
        h, t, s = line.split("|", 2)
        k = "Merge" if s.startswith("Merge") else COMMIT_KINDS.get(s.split(":")[0], "Sonstiges")
        commits.append({"sha": h, "at": t, "kind": k, "message": s})
    write(out, "commits", commits)

    caps = json.loads((repo / "contracts" / "capabilities.json").read_text(encoding="utf-8"))
    write(out, "capabilities", [
        {"id": c["id"], "kind": c["kind"], "status": c["status"], "target": c["target"],
         "evidence": c.get("evidence", "")}
        for c in caps["capabilities"]
    ])

    pol = json.loads((repo / "config" / "guard-policy.json").read_text(encoding="utf-8"))
    profs = list(pol["profiles"])
    write(out, "guard", [
        {"limit": v, "key": k, **{p: pol["profiles"][p].get(k) for p in profs}}
        for k, v in GUARD_LIMIT_NAMES.items()
    ])
    write(out, "guard_budget", [{"scope": "Sitzung", "usd": pol["global"]["session_budget_usd"]},
                                {"scope": "Tag", "usd": pol["global"]["daily_budget_usd"]}])

    usage_dir = repo / "logs"
    usage = []
    for f in sorted(usage_dir.glob("*.jsonl")) if usage_dir.exists() else []:
        usage += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not usage:  # a dataset needs at least one row; the page ignores rows without ts
        usage = [{
            "ts": None, "profile": None, "kind": "kein Eintrag", "level": None,
            "note": "Noch kein Usage-Log im Repo-Klon (Resource Guard #6 noch nicht gebaut).",
        }]
    write(out, "guard_usage", usage)

    write(out, "gate", run_gate(repo, sha, prev))
    pending["_summary"] = ({
        "sha": sha, "issues": len(issues), "reviews": len(reviews), "prs": len(prs),
        "decision_refs": len(refs), "ci_runs": len(ci), "commits": len(commits),
        "features": len(features), "research": len(research)})
    return pending


if __name__ == "__main__":
    main()
