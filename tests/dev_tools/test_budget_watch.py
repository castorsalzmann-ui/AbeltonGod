"""Tests for the development budget watcher hook and its report script."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / ".claude" / "hooks" / "waste_watch.py"
REPORT = ROOT / "scripts" / "dev_budget_report.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ww = _load("waste_watch", HOOK)
report = _load("dev_budget_report", REPORT)

LIMITS = {
    "identical_calls_without_change": 3,
    "failure_streak": 4,
    "edits_same_file": 15,
    "tool_calls_first_warn": 300,
    "tool_calls_warn_every": 150,
    "subagents_per_session": 4,
    "reviewer_runs_per_session": 3,
}


def ev(tool="Bash", tool_input=None, name="PostToolUse", **extra):
    if tool_input is None:
        tool_input = {"command": "pytest"}
    return {"hook_event_name": name, "tool_name": tool, "tool_input": tool_input, **extra}


def run(events, limits=LIMITS):
    state = ww.new_state()
    keys = []
    for e in events:
        keys.extend(k for k, _, _ in ww.evaluate(e, state, limits))
    return keys, state


def kinds(keys):
    return [k.split(":", 1)[0] for k in keys]


# --- repeat detection -------------------------------------------------------


def test_identical_call_warns_exactly_at_threshold_and_once():
    keys, _ = run([ev()] * 2)
    assert keys == []
    keys, _ = run([ev()] * 3)
    assert kinds(keys) == ["repeat"]
    keys, _ = run([ev()] * 10)
    assert kinds(keys) == ["repeat"]


def test_file_change_resets_and_opens_new_window():
    edit = ev("Edit", {"file_path": "/x/a.py", "old_string": "a", "new_string": "b"})
    keys, _ = run([ev(), ev(), edit, ev(), ev()])
    assert keys == []
    keys, _ = run([ev(), ev(), ev(), edit, ev(), ev(), ev()])
    assert kinds(keys) == ["repeat", "repeat"]


def test_different_inputs_do_not_count_as_repeat():
    events = [ev(tool_input={"command": f"pytest -k t{i}"}) for i in range(20)]
    keys, _ = run(events)
    assert keys == []


def test_key_order_does_not_change_signature():
    a = ev("Read", {"file_path": "x", "offset": 1})
    b = ev("Read", {"offset": 1, "file_path": "x"})
    keys, _ = run([a, b, a])
    assert kinds(keys) == ["repeat"]


def test_failed_edit_does_not_reset_repeat_window():
    failed_edit = ev("Edit", {"file_path": "/x/a.py"}, name="PostToolUseFailure")
    keys, _ = run([ev(), failed_edit, ev(), ev()])
    assert "repeat" in kinds(keys)


# --- failure streak ---------------------------------------------------------


def test_failure_streak_warns_at_threshold_once_per_streak():
    fail = [ev(tool_input={"command": f"x{i}"}, name="PostToolUseFailure") for i in range(10)]
    keys, _ = run(fail[:3])
    assert keys == []
    keys, _ = run(fail[:4])
    assert kinds(keys) == ["fail_streak"]
    keys, _ = run(fail)
    assert kinds(keys) == ["fail_streak"]


def test_success_breaks_streak_and_new_streak_warns_again():
    fail = [ev(tool_input={"command": f"x{i}"}, name="PostToolUseFailure") for i in range(8)]
    ok = ev(tool_input={"command": "ok"})
    keys, _ = run(fail[:3] + [ok] + fail[3:6])
    assert keys == []
    keys, _ = run(fail[:4] + [ok] + fail[4:8])
    assert kinds(keys) == ["fail_streak", "fail_streak"]


# --- edit thrashing ---------------------------------------------------------


def test_same_file_edits_warn_at_threshold_once():
    edits = [ev("Edit", {"file_path": "/x/a.py", "new_string": str(i)}) for i in range(30)]
    keys, _ = run(edits[:14])
    assert keys == []
    keys, _ = run(edits[:15])
    assert kinds(keys) == ["edits"]
    keys, _ = run(edits)
    assert kinds(keys) == ["edits"]


def test_edits_to_different_files_do_not_warn():
    edits = [ev("Write", {"file_path": f"/x/f{i}.py"}) for i in range(40)]
    keys, _ = run(edits)
    assert keys == []


# --- session size, subagents, reviewer -------------------------------------


def test_tool_call_warnings_at_first_and_every_step():
    events = [ev(tool_input={"command": f"c{i}"}) for i in range(600)]
    keys, _ = run(events)
    assert [k for k in keys if k.startswith("tool_calls")] == [
        "tool_calls:300",
        "tool_calls:450",
        "tool_calls:600",
    ]
    keys, _ = run(events[:299])
    assert keys == []


def test_subagent_and_reviewer_limits():
    agents = [ev("Agent", {"subagent_type": "Explore", "prompt": str(i)}) for i in range(3)]
    keys, _ = run(agents)
    assert keys == []
    reviews = [ev("Agent", {"subagent_type": "reviewer", "prompt": str(i)}) for i in range(3)]
    keys, state = run(reviews)
    assert kinds(keys) == ["reviewer"]
    assert state["reviewer_runs"] == 3
    keys, _ = run(agents + reviews[:1])
    assert kinds(keys) == ["subagents"]


def test_non_tool_events_and_missing_tool_change_nothing():
    keys, state = run([{"hook_event_name": "Stop"}, {"hook_event_name": "PostToolUse"}] * 5)
    assert keys == []
    assert state["tool_calls"] == 0


# --- limits file ------------------------------------------------------------


def test_load_limits_falls_back_on_bad_values(tmp_path):
    (tmp_path / "config").mkdir()
    cfg = tmp_path / "config" / "dev-budget.json"
    cfg.write_text(
        json.dumps({"failure_streak": 0, "edits_same_file": True, "subagents_per_session": 7}),
        encoding="utf-8",
    )
    limits = ww.load_limits(tmp_path)
    assert limits["failure_streak"] == ww.DEFAULTS["failure_streak"]
    assert limits["edits_same_file"] == ww.DEFAULTS["edits_same_file"]
    assert limits["subagents_per_session"] == 7
    cfg.write_text("{broken", encoding="utf-8")
    assert ww.load_limits(tmp_path) == ww.DEFAULTS
    assert ww.load_limits(tmp_path / "missing") == ww.DEFAULTS


def test_repo_config_is_valid_and_matches_defaults():
    raw = json.loads((ROOT / "config" / "dev-budget.json").read_text(encoding="utf-8"))
    assert {k: raw[k] for k in ww.DEFAULTS} == ww.DEFAULTS
    assert ww.load_limits(ROOT) == ww.DEFAULTS


# --- handle(): files, output, Stop summary ---------------------------------


def test_handle_writes_state_event_log_and_output(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    out = None
    for _ in range(3):
        out = ww.handle(ev(session_id="s/1", agent_type="reviewer"))
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "identical call" in out["hookSpecificOutput"]["additionalContext"]
    assert out["systemMessage"].startswith("Budget:")
    base = tmp_path / "logs" / "dev-usage"
    assert (base / "sessions" / "s_1.json").exists()
    lines = (base / "waste-events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "repeat"
    assert not list((base / "sessions").glob("*.lock"))

    stop = ww.handle({"hook_event_name": "Stop", "session_id": "s/1"})
    assert "repeat" in stop["systemMessage"]
    assert ww.handle({"hook_event_name": "Stop", "session_id": "s/1"}) is None


def test_handle_survives_corrupt_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    sessions = tmp_path / "logs" / "dev-usage" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "s.json").write_text('{"tool_calls": "many", "warned": 5}', encoding="utf-8")
    assert ww.handle(ev(session_id="s")) is None
    state = json.loads((sessions / "s.json").read_text(encoding="utf-8"))
    assert state["tool_calls"] == 1


def test_stale_lock_is_broken(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    sessions = tmp_path / "logs" / "dev-usage" / "sessions"
    sessions.mkdir(parents=True)
    lock = sessions / "s.lock"
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (0, 0))
    ww.handle(ev(session_id="s"))
    assert json.loads((sessions / "s.json").read_text(encoding="utf-8"))["tool_calls"] == 1


def test_parallel_hooks_do_not_lose_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    errors = []

    def worker(i):
        try:
            for j in range(10):
                ww.handle(ev(tool_input={"command": f"{i}-{j}"}, session_id="p"))
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    state_path = tmp_path / "logs" / "dev-usage" / "sessions" / "p.json"
    assert json.loads(state_path.read_text(encoding="utf-8"))["tool_calls"] == 60


@pytest.mark.parametrize(
    "stdin",
    ["", "not json", "[]", "null", '{"hook_event_name": 5}', '{"tool_name": {"x": 1}}'],
)
def test_script_never_fails_and_never_prints_garbage(tmp_path, stdin):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env
    )
    assert result.returncode == 0
    assert result.stdout == "" or isinstance(json.loads(result.stdout), dict)


def test_script_end_to_end_prints_one_json_object(tmp_path):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    payload = json.dumps(ev(session_id="e2e"))
    outputs = [
        subprocess.run(
            [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True, env=env
        ).stdout
        for _ in range(3)
    ]
    assert outputs[:2] == ["", ""]
    parsed = json.loads(outputs[2])
    assert set(parsed) == {"systemMessage", "hookSpecificOutput"}


def test_unwritable_project_dir_still_exits_zero(tmp_path):
    blocker = tmp_path / "logs"
    blocker.write_text("a file where a folder should be", encoding="utf-8")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(ev(session_id="x")),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert result.stdout == ""


# --- review of PR #18 (pullrequestreview-5682180564) ---------------------------


def test_undeletable_stale_lock_ends_at_the_deadline(tmp_path, monkeypatch):
    # Review P1: a stale lock that cannot be removed (held open on Windows) made the loop
    # spin until Claude Code's 10 s hook timeout.
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    lock = sessions / "s.lock"
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (0, 0))
    real_unlink = Path.unlink

    def refuse_lock(self, *args, **kwargs):
        if self.suffix == ".lock":
            raise PermissionError("held open")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_lock)
    monkeypatch.setattr(ww, "LOCK_WAIT_S", 0.2)
    outcome = []

    def attempt():
        try:
            with ww.file_lock(lock):
                outcome.append("acquired")
        except TimeoutError:
            outcome.append("timeout")

    worker = threading.Thread(target=attempt, daemon=True)
    worker.start()
    worker.join(timeout=3)
    assert not worker.is_alive(), "lock loop did not end"
    assert outcome == ["timeout"]


def test_windows_encoding_input_and_output(tmp_path):
    # Review P2: with a cp1252 locale the hook could not read some UTF-8 input and wrote
    # umlauts as invalid UTF-8. Bytes in, bytes out, as Claude Code sends and reads them.
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path), "PYTHONIOENCODING": "cp1252"}
    payload = json.dumps(
        ev(tool_input={"command": "echo Á"}, session_id="enc"), ensure_ascii=False
    ).encode("utf-8")
    outputs = [
        subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, env=env)
        for _ in range(3)
    ]
    assert [o.returncode for o in outputs] == [0, 0, 0]
    assert outputs[2].stdout, "the third identical call was not counted"
    text = outputs[2].stdout.decode("ascii")  # pure ASCII is valid in any encoding
    message = json.loads(text)["systemMessage"]
    assert "Dateiänderung" in message and "echo Á" in message


def test_git_branch_in_a_worktree(tmp_path):
    # Review P3: in a worktree .git is a file, so every event was logged with branch null.
    real_git = tmp_path / "main" / ".git" / "worktrees" / "wt"
    real_git.mkdir(parents=True)
    (real_git / "HEAD").write_text("ref: refs/heads/phase-00/x\n", encoding="utf-8")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {real_git}\n", encoding="utf-8")
    assert ww.git_branch(wt) == "phase-00/x"
    (wt / ".git").write_text("gitdir: ../main/.git/worktrees/wt\n", encoding="utf-8")
    assert ww.git_branch(wt) == "phase-00/x"
    (wt / ".git").write_text("garbage\n", encoding="utf-8")
    assert ww.git_branch(wt) is None


def test_git_branch_in_a_normal_checkout(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert ww.git_branch(tmp_path) == "main"


def test_settings_register_the_hook_for_all_three_events():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    for event in ("PostToolUse", "PostToolUseFailure", "Stop"):
        commands = [h["command"] for group in settings["hooks"][event] for h in group["hooks"]]
        assert any("waste_watch.py" in c for c in commands), event


# --- report -----------------------------------------------------------------


def _write_events(base: Path, events: list[dict]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    with (base / "waste-events.jsonl").open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
        fh.write("garbage line\n")


def test_report_marks_recurring_only_across_sessions(tmp_path, capsys):
    base = tmp_path / "dev-usage"
    _write_events(
        base,
        [
            {"ts": "2026-10-28T10:00:00+00:00", "session": "a", "branch": "b1", "kind": "repeat"},
            {"ts": "2026-10-28T10:01:00+00:00", "session": "a", "branch": "b1", "kind": "repeat"},
            {"ts": "2026-10-28T11:00:00+00:00", "session": "b", "branch": "b2", "kind": "edits"},
            {"ts": "2026-10-28T12:00:00+00:00", "session": "c", "branch": "b2", "kind": "edits"},
        ],
    )
    report.main(["--base", str(base)])
    text = capsys.readouterr().out
    assert "edits" in text and "RECURRING" in text
    repeat_line = next(line for line in text.splitlines() if line.startswith("- repeat"))
    assert "RECURRING" not in repeat_line

    report.main(["--base", str(base), "--branch", "b1"])
    assert "edits" not in capsys.readouterr().out


def test_report_mark_reviewed_hides_old_events(tmp_path, capsys):
    base = tmp_path / "dev-usage"
    _write_events(base, [{"ts": "2000-01-01T00:00:00+00:00", "session": "a", "kind": "repeat"}])
    report.main(["--base", str(base), "--mark-reviewed"])
    capsys.readouterr()
    report.main(["--base", str(base)])
    assert "No budget warnings" in capsys.readouterr().out
    report.main(["--base", str(base), "--all"])
    assert "repeat" in capsys.readouterr().out


def test_report_without_log(tmp_path, capsys):
    assert report.main(["--base", str(tmp_path / "none")]) == 0
    assert "No budget warnings" in capsys.readouterr().out
