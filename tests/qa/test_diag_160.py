"""TEMPORARY diagnostic for #160 - removed before the PR is final.

Loops the parallel-hook scenario and always fails with a one-line summary, because the CI
annotation step publishes only the first line of each failure message (job logs are not
readable through the REST API).
"""

from __future__ import annotations

import collections
import contextlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
HOOK = ROOT / ".claude" / "hooks" / "waste_watch.py"
spec = importlib.util.spec_from_file_location("waste_watch_diag", HOOK)
ww = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ww)

ITERATIONS = int(os.environ.get("DIAG160_ITER", "300"))


def _describe(exc: BaseException) -> str:
    frames = [
        f"{f.name}@{f.lineno}"
        for f in traceback.extract_tb(exc.__traceback__)
        if f.filename.endswith("waste_watch.py")
    ]
    fname = Path(str(getattr(exc, "filename", "") or "")).name
    return (
        f"{type(exc).__name__}(errno={getattr(exc, 'errno', None)},"
        f"winerror={getattr(exc, 'winerror', None)},file={fname})<-{'>'.join(frames)}"
    )


@contextlib.contextmanager
def lock_without_stat(lock_path: Path):
    """The hook's file_lock minus the stale check (no stat handle on the lock file)."""
    deadline = time.monotonic() + ww.LOCK_WAIT_S
    fd = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError("lock busy") from None
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            lock_path.unlink()


@contextlib.contextmanager
def lock_retry_permission(lock_path: Path):
    """Candidate fix: PermissionError on the exclusive create counts as 'busy'."""
    deadline = time.monotonic() + ww.LOCK_WAIT_S
    fd = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            if time.monotonic() > deadline:
                raise TimeoutError("lock busy") from None
            try:
                stale = time.time() - lock_path.stat().st_mtime > 30
            except OSError:
                stale = False
            if stale:
                try:
                    lock_path.unlink()
                    continue
                except OSError:
                    pass
            time.sleep(0.02)
    try:
        yield
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            lock_path.unlink()


@pytest.mark.parametrize("variant", ["orig", "nostat", "fix"])
def test_diag_threads(tmp_path, monkeypatch, variant):
    if variant == "nostat":
        monkeypatch.setattr(ww, "file_lock", lock_without_stat)
    elif variant == "fix":
        monkeypatch.setattr(ww, "file_lock", lock_retry_permission)
    kinds: collections.Counter[str] = collections.Counter()
    bad_iters = 0
    lost = 0
    for it in range(ITERATIONS):
        root = tmp_path / f"r{it}"
        root.mkdir()
        errors: list[BaseException] = []

        def worker(i, root=root, errors=errors):
            for j in range(10):
                try:
                    ww.handle(
                        {
                            "hook_event_name": "PostToolUse",
                            "tool_name": "Bash",
                            "tool_input": {"command": f"{i}-{j}"},
                            "session_id": "p",
                            "cwd": str(root),
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - diagnostic
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        state = root / "logs" / "dev-usage" / "sessions" / "p.json"
        count = json.loads(state.read_text(encoding="utf-8"))["tool_calls"]
        if errors or count != 60:
            bad_iters += 1
        lost += 60 - count
        for seen in errors:
            kinds[_describe(seen)] += 1
    summary = "; ".join(f"{n}x {k}" for k, n in kinds.most_common(4))
    pytest.fail(
        f"DIAG160 threads-{variant} {platform.platform()} py{sys.version_info[:2]} "
        f"iters={ITERATIONS} "
        f"bad_iters={bad_iters} lost_counts={lost} exc_total={sum(kinds.values())} :: {summary}"
    )


def test_diag_processes(tmp_path):
    """The user's case: parallel hook processes. Fewer iterations (process start is slow)."""
    iters = max(1, ITERATIONS // 15)
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
