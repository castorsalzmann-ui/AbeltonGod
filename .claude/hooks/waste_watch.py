"""Claude Code hook: warn when a development session burns usage without progress.

Registered in .claude/settings.json for PostToolUse, PostToolUseFailure and Stop.
It never blocks anything and always exits 0. On a crossed soft limit it prints one
JSON object: a German `systemMessage` for the user and a factual English
`additionalContext` for Claude. Each warning fires once per crossing.

Signals (limits in config/dev-budget.json):
- same tool + same input repeated without any file change in between
- consecutive failed tool calls
- one file edited very often (thrashing)
- total tool calls in the session (generous, repeating soft warning)
- many subagents / reviewer runs in one session

State: logs/dev-usage/sessions/<session>.json; events: logs/dev-usage/waste-events.jsonl
(logs/ is git-ignored). Standard library only, so it runs with any Python 3.11+.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

DEFAULTS: dict[str, int] = {
    "identical_calls_without_change": 3,
    "failure_streak": 4,
    "edits_same_file": 15,
    "tool_calls_first_warn": 300,
    "tool_calls_warn_every": 150,
    "subagents_per_session": 4,
    "reviewer_runs_per_session": 3,
}

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
AGENT_TOOLS = {"Agent", "Task"}
LOCK_WAIT_S = 2.0


def project_dir(event: dict) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return Path(event.get("cwd") or ".")


def load_limits(root: Path) -> dict[str, int]:
    limits = dict(DEFAULTS)
    try:
        raw = json.loads((root / "config" / "dev-budget.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return limits
    if not isinstance(raw, dict):
        return limits
    for key, default in DEFAULTS.items():
        value = raw.get(key, default)
        # bool is an int subclass; reject it and anything below 1
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            limits[key] = value
    return limits


def signature(tool: str, tool_input: object) -> str:
    try:
        text = json.dumps(tool_input, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(tool_input)
    return tool + ":" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def safe_name(session_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:80]
    return cleaned or "unknown"


def git_branch(root: Path) -> str | None:
    try:
        head = (root / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return head.removeprefix("ref: refs/heads/") if head.startswith("ref:") else head[:12]


def new_state() -> dict:
    return {
        "tool_calls": 0,
        "since_change": {},
        "change_epoch": 0,
        "edits": {},
        "fail_streak": 0,
        "subagents": 0,
        "reviewer_runs": 0,
        "warned": [],
        "pending_summary": [],
    }


def evaluate(event: dict, state: dict, limits: dict[str, int]) -> list[tuple[str, str, str]]:
    """Update `state` with one hook event; return new warnings as (key, user_de, claude_en)."""
    name = event.get("hook_event_name")
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input")
    found: list[tuple[str, str, str]] = []

    def warn(key: str, de: str, en: str) -> None:
        if key not in state["warned"]:
            state["warned"].append(key)
            found.append((key, de, en))

    if name not in ("PostToolUse", "PostToolUseFailure") or not tool:
        return found

    state["tool_calls"] += 1
    n = state["tool_calls"]
    first, every = limits["tool_calls_first_warn"], limits["tool_calls_warn_every"]
    if n >= first and (n - first) % every == 0:
        warn(
            f"tool_calls:{n}",
            f"Budget: {n} Tool-Aufrufe in dieser Sitzung. Lohnt sich ein frischer Start?",
            f"This session has made {n} tool calls. The CLAUDE.md budget rule applies: "
            "state in two lines what is still open and whether a fresh session would be cheaper.",
        )

    if name == "PostToolUseFailure":
        state["fail_streak"] += 1
        streak = state["fail_streak"]
        if streak >= limits["failure_streak"]:
            warn(
                f"fail_streak:{n - streak + 1}",
                f"Budget: {streak} fehlgeschlagene Tool-Aufrufe hintereinander.",
                f"{streak} tool calls in a row have failed. The CLAUDE.md budget rule applies: "
                "stop retrying, name the cause or ask the user.",
            )
    else:
        state["fail_streak"] = 0

    if tool in EDIT_TOOLS and name == "PostToolUse":
        state["since_change"] = {}
        state["change_epoch"] += 1
        path = ""
        if isinstance(tool_input, dict):
            path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        if path:
            count = state["edits"].get(path, 0) + 1
            state["edits"][path] = count
            if count >= limits["edits_same_file"]:
                short = Path(path).name
                warn(
                    f"edits:{path}",
                    f"Budget: {short} wurde {count}-mal geändert. Möglicherweise Herumprobieren.",
                    f"{path} has been edited {count} times this session. The CLAUDE.md budget "
                    "rule applies: isolate the cause before the next edit.",
                )
        return found

    sig = signature(tool, tool_input)
    count = state["since_change"].get(sig, 0) + 1
    state["since_change"][sig] = count
    if count >= limits["identical_calls_without_change"]:
        detail = tool
        if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
            detail = f"{tool}: {tool_input['command'][:60]}"
        # one warning per signature per change window; a file change opens a new window
        warn(
            f"repeat:{sig}:{state['change_epoch']}",
            f"Budget: derselbe Aufruf {count}-mal ohne Dateiänderung ({detail}).",
            f"The identical call ({detail}) ran {count} times with no file change in between, "
            "so the result cannot differ. The CLAUDE.md budget rule applies.",
        )

    if tool in AGENT_TOOLS and name == "PostToolUse":
        state["subagents"] += 1
        if state["subagents"] >= limits["subagents_per_session"]:
            warn(
                f"subagents:{state['subagents']}",
                f"Budget: {state['subagents']} Subagents in dieser Sitzung.",
                f"{state['subagents']} subagents have run in this session (D-010: few agents). "
                "Each starts without context. The CLAUDE.md budget rule applies.",
            )
        agent_type = tool_input.get("subagent_type") if isinstance(tool_input, dict) else None
        if agent_type == "reviewer":
            state["reviewer_runs"] += 1
            runs = state["reviewer_runs"]
            if runs >= limits["reviewer_runs_per_session"]:
                warn(
                    f"reviewer:{runs}",
                    f"Budget: {runs}. Review-Runde. Ab jetzt nur mit deiner Zustimmung.",
                    f"This is review round {runs}. The CLAUDE.md budget rule allows two rounds; "
                    "ask the user before another one.",
                )
    return found


@contextlib.contextmanager
def file_lock(lock_path: Path):
    deadline = time.monotonic() + LOCK_WAIT_S
    fd = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > 30
            except OSError:
                stale = False
            if stale:
                with contextlib.suppress(OSError):
                    lock_path.unlink()
                continue
            if time.monotonic() > deadline:
                raise TimeoutError("lock busy") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            lock_path.unlink()


def read_state(path: Path) -> dict:
    state = new_state()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(loaded, dict):
        for key, default in state.items():
            if isinstance(loaded.get(key), type(default)):
                state[key] = loaded[key]
    return state


def write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def handle(event: dict) -> dict | None:
    """Process one event; return the JSON object to print, or None."""
    if not isinstance(event, dict):
        return None
    root = project_dir(event)
    base = root / "logs" / "dev-usage"
    sessions = base / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sid = safe_name(str(event.get("session_id") or "unknown"))
    state_path = sessions / f"{sid}.json"
    name = event.get("hook_event_name")

    with file_lock(sessions / f"{sid}.lock"):
        state = read_state(state_path)
        if name == "Stop":
            pending = state["pending_summary"]
            state["pending_summary"] = []
            write_json_atomic(state_path, state)
            if not pending:
                return None
            return {
                "systemMessage": "Budget-Warnungen in diesem Schritt: "
                + "; ".join(pending)
                + ". Details: python scripts/dev_budget_report.py"
            }
        found = evaluate(event, state, load_limits(root))
        state["pending_summary"].extend(k.split(":", 1)[0] for k, _, _ in found)
        state["last_seen"] = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
        write_json_atomic(state_path, state)

    if not found:
        return None
    branch = git_branch(root)
    with (base / "waste-events.jsonl").open("a", encoding="utf-8") as log:
        for key, de, _ in found:
            log.write(
                json.dumps(
                    {
                        "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
                        "session": sid,
                        "branch": branch,
                        "agent_type": event.get("agent_type"),
                        "kind": key.split(":", 1)[0],
                        "message": de,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return {
        "systemMessage": " | ".join(de for _, de, _ in found),
        "hookSpecificOutput": {
            "hookEventName": name,
            "additionalContext": " ".join(en for _, _, en in found),
        },
    }


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "null")
        out = handle(event)
    except Exception:  # noqa: BLE001 - a watcher must never break the session
        return 0
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
