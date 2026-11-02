"""The teardown guard in tests/conftest.py (#183): fails the test that leaves a handled
exception in its thread, and only that one."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run_probe(tmp_path: Path) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "pythonpath=src", "-n", "0", "-q",
         "-p", "no:cacheprovider", f"--basetemp={tmp_path / 'bt'}",
         str(ROOT / "tests" / "qa" / "leaky_probe.py")],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    return proc.stdout + proc.stderr


def test_guard_blames_only_the_leaking_test(tmp_path) -> None:
    out = _run_probe(tmp_path)
    assert "leaky_probe.py::test_leaks_a_handled_exception left a handled exception" in out, out
    assert "planted leak" in out, out
    # the innocent tests after it are not blamed, although the object stays set in the thread
    assert "test_after_one left" not in out and "test_after_two left" not in out, out
    assert "3 passed, 1 error" in out, out
