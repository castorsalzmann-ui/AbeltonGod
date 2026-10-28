"""Report golden-hash results (#35) as GitHub annotations, so CI evidence per platform can be
read from the check-run annotations even when job logs are not accessible.

``test_golden_sha256`` stores ``("golden", "<platform> <name> match|MISMATCH <sha256>")`` in
``user_properties``; that travels from pytest-xdist workers to the controller, which prints
one ``::notice`` line per case at the end of the run. Only under GitHub Actions.
"""

from __future__ import annotations

import os

_GOLDEN_LINES: list[str] = []


def pytest_runtest_logreport(report) -> None:
    if report.when != "call":
        return
    _GOLDEN_LINES.extend(v for k, v in report.user_properties if k == "golden")


def pytest_terminal_summary(terminalreporter) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not _GOLDEN_LINES:
        return
    for line in sorted(_GOLDEN_LINES):
        terminalreporter.write_line(f"::notice title=golden hash::{line}")
