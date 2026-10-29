"""TEMPORARY diagnostic for #160 - removed before the PR is final.

Round 3: the fixed hook. Loops the real `test_parallel_hooks_do_not_lose_counts` and the
parallel-process scenario, and always fails with a one-line summary, because the CI
annotation step publishes only the first line of each failure message.
"""

from __future__ import annotations

import collections
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / ".claude" / "hooks" / "waste_watch.py"
TESTS = ROOT / "tests" / "dev_tools" / "test_budget_watch.py"
spec = importlib.util.spec_from_file_location("test_budget_watch_diag", TESTS)
tbw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tbw)

ITERATIONS = int(os.environ.get("DIAG160_ITER", "300"))


def test_diag_loop_real_parallel_test(tmp_path):
    outcomes: collections.Counter[str] = collections.Counter()
    for it in range(ITERATIONS):
        d = tmp_path / f"l{it}"
        d.mkdir()
        mp = pytest.MonkeyPatch()
        try:
            tbw.test_parallel_hooks_do_not_lose_counts(d, mp)
            outcomes["passed"] += 1
        except Exception as exc:  # noqa: BLE001 - diagnostic
            outcomes[f"failed:{str(exc).splitlines()[0][:80]}"] += 1
        finally:
            mp.undo()
    pytest.fail(
        f"DIAG160 loop {platform.platform()} hook={tbw.HOOK.parent.parent.parent.name} "
        f"iters={ITERATIONS} :: {dict(outcomes)}"
    )


def test_diag_processes(tmp_path):
    """The user's case: parallel hook processes. Fewer iterations (process start is slow)."""
    iters = max(1, ITERATIONS // 7)
    bad_iters = 0
    lost = 0
    for it in range(iters):
        root = tmp_path / f"r{it}"
        root.mkdir()
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
        payload = json.dumps(
            {"hook_event_name": "PostToolUse", "tool_name": "Bash",
             "tool_input": {"command": "x"}, "session_id": "p"}
        )
        code = (
            "import runpy,sys,io\n"
            f"p={payload!r}\n"
            "for _ in range(10):\n"
            "    sys.stdin=io.TextIOWrapper(io.BytesIO(p.encode()))\n"
            f"    m=runpy.run_path({str(HOOK)!r})\n"
            "    m['main']()\n"
        )
        procs = [
            subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.DEVNULL)
            for _ in range(6)
        ]
        for p in procs:
            p.wait()
        state = root / "logs" / "dev-usage" / "sessions" / "p.json"
        count = json.loads(state.read_text(encoding="utf-8"))["tool_calls"]
        if count != 60:
            bad_iters += 1
        lost += 60 - count
    pytest.fail(
        f"DIAG160 processes {sys.platform} iters={iters} bad_iters={bad_iters} lost_counts={lost}"
    )
