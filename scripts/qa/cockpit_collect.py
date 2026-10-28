"""AbeltonGod cockpit collector.

Reads GitHub (REST via `gh api`, read-only: GET requests only) and a clone of the repo,
writes one JSON file per cockpit dataset into OUT_DIR.

Usage:
    python scripts/qa/cockpit_collect.py <repo_dir> <out_dir> [<previous_gate.json>]

    <repo_dir>            checkout to read (docs/, contracts/, config/, git log)
    <out_dir>             gets phases.json, issues.json, reviews.json, prs.json, decisions.json,
                          decision_refs.json, ci_runs.json, commits.json, capabilities.json,
                          guard.json, guard_budget.json, guard_usage.json, gate.json
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
    "04a": "Resource Guard", "04b": "Claude-Orchestrator",
}
TRACK = {
    "00": "Setup", "01": "Kick", "02": "Bridge", "03": "Import", "04a": "Guard",
    "04b": "Orchestrator",
}


def phase_key(s: str | None) -> str | None:
    if not s:
        return None
    s = s.lower()
    return s if s.startswith("04") and len(s) == 3 else s[:2]


def expand_phase_refs(text: str) -> list[str]:
    refs: list[str] = []
    for a, b in re.findall(r"\b(0[0-4])\s*[–-]\s*(0[0-4][ab]?)\b", text):
        for n in range(int(a), int(b[:2]) + 1):
            refs.append("04a" if n == 4 else f"{n:02d}")
    text = re.sub(r"\b0[0-4]\s*[–-]\s*0[0-4][ab]?\b", " ", text)
    refs += [m.lower() for m in re.findall(r"\b(0[0-4][abAB]?)\b", text)]
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
            "phase": pid, "name": PHASE_NAMES.get(pid, pid), "goal": goal, "file_status": status,
            "criteria_total": len(boxes), "criteria_met": sum(b.lower() == "x" for b in boxes),
            "depends_on": ", ".join(deps), "tested_in": tested, "order": len(rows),
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
        needs_user = (
            "needs:user-test" in labels or "needs:user-decision" in labels
        ) and i["state"] == "open"
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
            "merged": merged, "url": i["html_url"],
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
    "state": "State", "docs": "Docs",
}


def main() -> None:
    repo, out = Path(sys.argv[1]), Path(sys.argv[2])
    prev = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")) if len(sys.argv) > 3 else []
    out.mkdir(parents=True, exist_ok=True)
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
    write(out, "issues", issues)
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
    print(json.dumps({"sha": sha, "issues": len(issues), "reviews": len(reviews), "prs": len(prs),
                      "decision_refs": len(refs), "ci_runs": len(ci), "commits": len(commits)}))


if __name__ == "__main__":
    main()
