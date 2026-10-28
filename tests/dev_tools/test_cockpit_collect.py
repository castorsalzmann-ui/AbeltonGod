"""Tests for the pure parsers of scripts/qa/cockpit_collect.py (#65).

No network: `gh` / `gh_all` / `run` are monkeypatched with canned GitHub JSON. Expected
values are written out by hand, not derived from the script's own helpers.
Set COCKPIT_COLLECT=<path> to run these tests against a mutated copy (fault injection).
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = Path(os.environ.get("COCKPIT_COLLECT", ROOT / "scripts" / "qa" / "cockpit_collect.py"))


def _load():
    spec = importlib.util.spec_from_file_location("cockpit_collect", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cc = _load()


# ---------- phase references and phase keys ----------
@pytest.mark.parametrize(("text", "expected"), [
    ("Phases 01–03 and **04a (resource guard)** accepted.", ["01", "02", "03", "04a"]),
    ("Phase 01 and Phase 02 accepted.", ["01", "02"]),
    ("Phases 00-02 accepted", ["00", "01", "02"]),
    ("Phase 04B and 03, again 03", ["03", "04b"]),
    ("None.", []),
    ("PR #100 and #205 merged", []),  # digits inside longer numbers are not phases
    ("Phase 05 and 10", []),  # only 00..04 exist
])
def test_expand_phase_refs(text, expected):
    assert cc.expand_phase_refs(text) == expected


@pytest.mark.parametrize(("raw", "expected"), [
    ("01", "01"), ("04A", "04a"), ("04b", "04b"), ("04", "04"), ("02x", "02"),
    ("", None), (None, None),
])
def test_phase_key(raw, expected):
    assert cc.phase_key(raw) == expected


# ---------- phase files ----------
def _phase_repo(tmp_path: Path) -> Path:
    d = tmp_path / "docs" / "phases"
    d.mkdir(parents=True)
    (d / "PHASE_02_ABLETON_BRIDGE.md").write_text(
        "# Phase 02\n\n"
        "**Status:** DONE (PR #42, 2026-10-28) · **Agent:** `bridge-engineer` · "
        "**Tested in:** user's Windows machine\n\n"
        "## Objective\n\nTalk to\nLive over OSC.\n\n"
        "## Prerequisites\n\nPhase 01 accepted. Phase 03 is later.\n\n"
        "## Acceptance criteria\n\n- [x] one\n- [ ] two\n- [X] three\n\n"
        "## Notes\n\n- [x] not a criterion\n",
        encoding="utf-8",
    )
    (d / "PHASE_04B_CLAUDE_ORCHESTRATOR.md").write_text(
        "**Status:** IN PROGRESS · **Tested in:** CI\n\n"
        "## Prerequisites\n\nPhases 01–03 and **04a (resource guard)** accepted.\n",
        encoding="utf-8",
    )
    (d / "PHASE_00_SETUP.md").write_text("No status line here.\n", encoding="utf-8")
    (d / "PHASE_NOTES.md").write_text("**Status:** DONE\n", encoding="utf-8")  # no phase id
    return tmp_path


def test_collect_phases(tmp_path):
    rows = cc.collect_phases(_phase_repo(tmp_path))
    assert rows == [
        {"phase": "00", "name": "Setup", "goal": "", "file_status": "PLANNED",
         "criteria_total": 0, "criteria_met": 0, "depends_on": "", "tested_in": "",
         "order": 0},
        {"phase": "02", "name": "Ableton-Bridge", "goal": "Talk to Live over OSC.",
         "file_status": "DONE", "criteria_total": 3, "criteria_met": 2,
         "depends_on": "01", "tested_in": "user's Windows machine", "order": 1},
        {"phase": "04b", "name": "Claude-Orchestrator", "goal": "",
         "file_status": "IN PROGRESS", "criteria_total": 0, "criteria_met": 0,
         "depends_on": "01, 02, 03, 04a", "tested_in": "CI", "order": 2},
    ]


# ---------- issues ----------
NOT_A_PR = object()


def _issue(number, title, labels=(), state="open", pr=NOT_A_PR, body="", comments=0):
    """Canned REST issue; `pr` is the PR's merged_at (None = unmerged PR)."""
    i = {
        "number": number, "title": title, "labels": [{"name": n} for n in labels],
        "state": state, "body": body, "comments": comments,
        "created_at": f"2026-10-01T00:00:{number:02d}Z",
        "closed_at": None if state == "open" else "2026-10-02T00:00:00Z",
        "html_url": f"https://example.invalid/{number}",
    }
    if pr is not NOT_A_PR:
        i["pull_request"] = {"merged_at": pr}
    return i


CANNED_ISSUES = [
    _issue(10, "Kick thing", ["phase:01", "status:ready", "agent:audio"],
           body="Text\n**Depends on:** #11, #12\n"),
    _issue(11, "Old task", state="closed"),
    _issue(12, "Phase 04b: orchestrator", pr=None),
    _issue(13, "phase-02 abandoned PR", state="closed", pr=None),
    _issue(14, "merged PR", ["phase:03"], state="closed", pr="2026-10-03T00:00:00Z"),
    _issue(15, "Guard", ["phase:04", "status:blocked", "needs:user-test", "agent:qa"]),
    _issue(16, "Odd thing", ["side-finding", "needs:user-decision", "status:in-progress",
                             "agent:sound"]),
    _issue(17, "Loop", ["status:in-review", "agent:orchestrator"]),
    _issue(18, "Notes", ["agent:research"]),
    _issue(19, "Other", ["agent:unknownrole"]),
    _issue(20, "Review", ["agent:reviewer", "needs:user-test"], state="closed"),
]


@pytest.fixture
def issues(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "CURRENT_STATE.md").write_text(
        "## Done\n\n#18 was earlier\n\n## Next step\n\n1. #12, then #10, again #12; #11\n\n"
        "## Later\n\n#17\n",
        encoding="utf-8",
    )
    calls = []

    def fake_gh_all(path):
        calls.append(path)
        return [dict(i) for i in reversed(CANNED_ISSUES)]

    monkeypatch.setattr(cc, "gh_all", fake_gh_all)
    rows, bodies = cc.collect_issues(tmp_path)
    assert calls == [f"{cc.R}/issues?state=all"]
    return {r["number"]: r for r in rows}, rows, bodies


def test_issue_rows_sorted_and_bodies(issues):
    by_num, rows, bodies = issues
    assert [r["number"] for r in rows] == list(range(10, 21))
    assert {b["number"]: b["kind"] for b in bodies}[12] == "PR"
    assert {b["number"]: b["kind"] for b in bodies}[16] == "Issue"
    assert next(b["text"] for b in bodies if b["number"] == 10).startswith("Text")


@pytest.mark.parametrize(("n", "kind", "phase", "track", "status", "owner", "needs_user"), [
    (10, "Issue", "01", "Kick", "Bereit", "audio-engineer", False),
    (11, "Issue", "—", "Sonstiges", "Fertig", "nicht zugewiesen", False),
    (12, "PR", "04b", "Orchestrator", "In Review", "Du", False),
    (13, "PR", "02", "Bridge", "Geschlossen", "nicht zugewiesen", False),
    (14, "PR", "03", "Import", "Fertig", "nicht zugewiesen", False),
    (15, "Issue", "04a", "Guard", "Blockiert", "qa-tester", True),
    (16, "Side-Finding", "—", "Sonstiges", "In Arbeit", "Du", True),
    (17, "Issue", "—", "Sonstiges", "In Review", "orchestrator-engineer", False),
    (18, "Issue", "—", "Sonstiges", "Offen", "researcher", False),
    (19, "Issue", "—", "Sonstiges", "Offen", "unknownrole", False),
    (20, "Issue", "—", "Sonstiges", "Fertig", "reviewer", False),
])
def test_issue_status_and_owner(issues, n, kind, phase, track, status, owner, needs_user):
    r = issues[0][n]
    assert (r["kind"], r["phase"], r["track"], r["status"], r["owner"], r["needs_user"]) == (
        kind, phase, track, status, owner, needs_user)


def test_d017_agent_labels_mapped():
    assert {k: cc.AGENT[k] for k in ("qa", "sound", "orchestrator", "research")} == {
        "qa": "qa-tester", "sound": "sound-designer",
        "orchestrator": "orchestrator-engineer", "research": "researcher",
    }
    # the pre-D-017 mapping is unchanged
    assert {k: cc.AGENT[k] for k in ("audio", "bridge", "main", "reviewer")} == {
        "audio": "audio-engineer", "bridge": "bridge-engineer", "main": "main session",
        "reviewer": "reviewer",
    }


def test_issue_dependencies_and_next_rank(issues):
    by_num = issues[0]
    assert by_num[10]["depends_on"] == "11, 12"
    assert by_num[10]["waiting_on"] == "12"  # 11 is closed
    assert (by_num[12]["next_rank"], by_num[10]["next_rank"]) == (1, 2)
    assert by_num[11]["next_rank"] is None  # listed, but closed
    assert by_num[17]["next_rank"] is None  # only outside "## Next step"
    assert by_num[14]["merged"] == "2026-10-03T00:00:00Z"
    assert by_num[13]["merged"] is None
    assert by_num[16]["labels"] == (
        "side-finding, needs:user-decision, status:in-progress, agent:sound")


# ---------- reviews ----------
REVIEW_1 = (
    "## Independent review\n\n**Verdict: CHANGES NEEDED.** Two things.\n\n"
    "- `pytest` → `1,922 passed, 2 skipped in 334.70s`\n\n"
    "**1. [major] The criterion is narrowed.**\n"
    "**2. [Minor] Edge case.**\n"
    "**A3 [nit] Wording.**\n"
    "**4 [minor] Another.**\n"
    "Inline **5. [blocker] not at line start** is not counted.\n"
    "## Fault injection\n\n| mutant | result |\n"
)
REVIEW_2 = "Verdict: **APPROVE-READY** by a fresh reviewer.\n\nNo findings.\n"


@pytest.fixture
def review_rows(monkeypatch):
    issue_rows = [
        {"number": 30, "kind": "PR", "title": "PR thirty", "comments": 1},
        {"number": 31, "kind": "PR", "title": "PR open", "comments": 0},
        {"number": 32, "kind": "Issue", "title": "issue", "comments": 2},
        {"number": 33, "kind": "Issue", "title": "quiet issue", "comments": 0},
    ]
    pages = {
        f"{cc.R}/pulls/30/reviews": [
            {"body": REVIEW_1, "submitted_at": "2026-10-28T11:00:00Z"},
            {"body": REVIEW_2, "submitted_at": "2026-10-28T12:00:00Z"},
        ],
        f"{cc.R}/pulls/31/reviews": [],
        f"{cc.R}/issues/30/comments": [{"body": "see D-001"}],
        f"{cc.R}/issues/31/comments": [],
        f"{cc.R}/issues/32/comments": [{"body": "a"}, {"body": None}],
    }
    details = {
        f"{cc.R}/pulls/30": {"title": "PR thirty", "state": "closed", "commits": 3,
                             "additions": 10, "deletions": 2, "changed_files": 1,
                             "created_at": "2026-10-28T10:00:00Z",
                             "merged_at": "2026-10-28T13:30:00Z", "closed_at": None},
        f"{cc.R}/pulls/31": {"title": "PR open", "state": "open",
                             "created_at": "2026-10-28T10:00:00Z", "merged_at": None,
                             "closed_at": None},
    }
    monkeypatch.setattr(cc, "gh_all", lambda p: pages[p])
    monkeypatch.setattr(cc, "gh", lambda p: details[p])
    bodies: list[dict] = []
    reviews, prs = cc.collect_reviews(issue_rows, bodies)
    return reviews, prs, bodies


def test_review_verdict_and_severity(review_rows):
    reviews = review_rows[0]
    assert reviews == [
        {"review": "30-1", "pr": 30, "round": 1, "submitted": "2026-10-28T11:00:00Z",
         "verdict": "CHANGES NEEDED", "tests_passed": 1922, "tests_skipped": 2,
         "problems": 4, "blocker": 0, "major": 1, "minor": 2, "nit": 1,
         "fault_injection": True, "fresh_reviewer": False},
        {"review": "30-2", "pr": 30, "round": 2, "submitted": "2026-10-28T12:00:00Z",
         "verdict": "APPROVE-READY", "tests_passed": None, "tests_skipped": None,
         "problems": 0, "blocker": 0, "major": 0, "minor": 0, "nit": 0,
         "fault_injection": False, "fresh_reviewer": True},
    ]


def test_pr_rows(review_rows):
    prs = review_rows[1]
    assert prs[0] == {
        "pr": 30, "title": "PR thirty", "state": "gemergt", "rounds": 2, "commits": 3,
        "additions": 10, "deletions": 2, "changed_files": 1, "hours_to_merge": 3.5,
        "final_verdict": "APPROVE-READY", "created": "2026-10-28T10:00:00Z",
        "merged": "2026-10-28T13:30:00Z",
    }
    assert (prs[1]["state"], prs[1]["rounds"], prs[1]["hours_to_merge"],
            prs[1]["final_verdict"], prs[1]["commits"]) == ("open", 0, None, "kein Review", None)


def test_review_bodies_collected(review_rows):
    bodies = review_rows[2]
    assert [(b["number"], b["kind"], b["text"]) for b in bodies] == [
        (30, "Review", REVIEW_1), (30, "Review", REVIEW_2), (30, "Kommentar", "see D-001"),
        (32, "Kommentar", "a"), (32, "Kommentar", ""),
    ]


# ---------- decisions ----------
def test_collect_decisions(tmp_path, monkeypatch):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "DECISIONS.md").write_text(
        "# Decisions\n\n"
        "## D-001 · 2026-10-28 · accepted — Bridge = Remote Script, not M4L\n\ntext D-002\n\n"
        "## D-002 · 2026-10-29 · superseded — Old · thing\n\n"
        "## D-003 · 2026-10-29 · accepted - plain hyphen is not a heading\n"
        "### D-004 · 2026-10-29 · accepted — level 3 is not a heading\n",
        encoding="utf-8",
    )
    files = {
        "src/a.py": "D-001 and D-001, D-0011 no", "tests/t.py": "D-002",
        "config/p.json": "D-001", "contracts/c.json": "D-001",
        ".claude/agents/x.md": "D-001", "docs/x.md": "D-999 D-003", "img.png": "D-001",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    listing = "\n".join(["docs/DECISIONS.md", *files, "missing.md"]) + "\n"

    def fake_run(cmd, cwd=None):
        assert cmd == ["git", "ls-files"] and cwd == tmp_path
        return subprocess.CompletedProcess(cmd, 0, listing, "")

    monkeypatch.setattr(cc, "run", fake_run)
    bodies = [
        {"number": 5, "kind": "Review", "title": "PR #5 Review 1", "text": "D-001, D-001"},
        {"number": 5, "kind": "PR", "title": "pr five", "text": "D-001"},
        {"number": 6, "kind": "Kommentar", "title": "issue six", "text": "D-002 D-004"},
    ]
    decs, refs = cc.collect_decisions(tmp_path, bodies)
    assert decs == [
        {"id": "D-001", "date": "2026-10-28", "status": "accepted",
         "title": "Bridge = Remote Script, not M4L"},
        {"id": "D-002", "date": "2026-10-29", "status": "superseded", "title": "Old · thing"},
    ]
    got = [(r["decision"], r["ref_kind"], r["ref"], r["label"], r["mentions"], r["link"])
           for r in refs]
    assert got == [
        ("D-001", "Agent/Skill", ".claude/agents/x.md", ".claude/agents/x.md", 1,
         "D-001|.claude/agents/x.md"),
        ("D-001", "Code", "config/p.json", "config/p.json", 1, "D-001|config/p.json"),
        ("D-001", "Code", "src/a.py", "src/a.py", 2, "D-001|src/a.py"),
        ("D-001", "Contract", "contracts/c.json", "contracts/c.json", 1,
         "D-001|contracts/c.json"),
        ("D-001", "PR", "#5", "PR #5 Review 1", 3, "D-001|#5"),
        ("D-002", "Issue", "#6", "issue six", 1, "D-002|#6"),
        ("D-002", "Test", "tests/t.py", "tests/t.py", 1, "D-002|tests/t.py"),
    ]


# ---------- GitHub access stays read-only ----------
def test_gh_calls_are_plain_get(monkeypatch):
    seen = []

    def fake_subprocess_run(cmd, **kw):
        seen.append(cmd)
        page = int(re.search(r"page=(\d+)$", cmd[2]).group(1))
        n = 100 if page == 1 else 7
        return subprocess.CompletedProcess(cmd, 0, "[" + ",".join(["{}"] * n) + "]", "")

    monkeypatch.setattr(cc.subprocess, "run", fake_subprocess_run)
    rows = cc.gh_all(f"{cc.R}/issues?state=all")
    assert len(rows) == 107
    assert seen == [
        ["gh", "api", f"{cc.R}/issues?state=all&per_page=100&page=1"],
        ["gh", "api", f"{cc.R}/issues?state=all&per_page=100&page=2"],
    ]


def test_gh_all_unwraps_workflow_runs(monkeypatch):
    monkeypatch.setattr(cc, "gh", lambda p: {"total_count": 2, "workflow_runs": [1, 2]})
    assert cc.gh_all(f"{cc.R}/actions/runs") == [1, 2]


def test_no_github_write_call_in_source():
    src = SCRIPT.read_text(encoding="utf-8")
    for flag in ('"-X"', '"--method"', '"--input"', '"-f"', '"-F"', '"--field"',
                 '"--raw-field"', "POST", "PATCH", "PUT", "DELETE"):
        assert flag not in src, flag
    assert src.count('["gh", "api", path]') == 1
    assert len(re.findall(r'"gh"', src)) == 1  # the only gh invocation is the GET helper
