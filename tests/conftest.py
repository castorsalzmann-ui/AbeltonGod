"""Report golden-hash results (#35) as GitHub annotations, so CI evidence per platform can be
read from the check-run annotations even when job logs are not accessible.

``test_golden_sha256`` stores ``("golden", "<platform> <name> match|MISMATCH <sha256>")`` in
``user_properties``; that travels from pytest-xdist workers to the controller, which prints
one ``::notice`` line per case at the end of the run. Only under GitHub Actions.

It lives in ``tests/`` (the rootdir's test root), not ``tests/audio_engine/``: a sub-folder
conftest is only loaded by the controller once that folder is collected there, and under
``pytest -n auto`` its terminal-summary hook was not called (0 notices in a full run).


It also installs the opt-in render cache (#77, ``tests/support/render_cache.py``) for the
test functions listed there, for the duration of each such test only.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_GOLDEN_LINES: list[str] = []


def _test_key(item) -> str:
    path = Path(item.path).resolve()
    try:
        rel = path.relative_to(_ROOT).as_posix()
    except ValueError:
        rel = path.as_posix()
    return f"{rel}::{getattr(item, 'originalname', item.name)}"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    from support import render_cache

    module = getattr(item, "module", None)
    if module is None or not render_cache.should_cache(_test_key(item), item.fixturenames):
        return (yield)
    import audio_engine.io as io_mod

    targets = [(m, m.render_kick) for m in (module, io_mod) if hasattr(m, "render_kick")]
    for m, _ in targets:
        m.render_kick = render_cache.cached_render_kick
    try:
        return (yield)
    finally:
        for m, original in targets:
            m.render_kick = original


def pytest_runtest_logreport(report) -> None:
    if report.when != "call":
        return
    _GOLDEN_LINES.extend(v for k, v in report.user_properties if k == "golden")


def pytest_terminal_summary(terminalreporter) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or not _GOLDEN_LINES:
        return
    for line in sorted(_GOLDEN_LINES):
        terminalreporter.write_line(f"::notice title=golden hash::{line}")
