"""pytest plugin (QA measurement, #77): count real ``render_kick`` calls and cache hits per test.

    python -m pytest -o pythonpath=src -n 0 -p support.render_counter tests/audio_engine

Writes ``RENDER_COUNTER_OUT`` (default ``render_counter.json``, ``render_counter.<gwN>.json``
per xdist worker, in pytest's ``--basetemp`` folder ``.pytest_tmp`` or the system temp dir):
per test node id the number of real engine renders, cache hits and whether the test used
``monkeypatch``, plus totals. It wraps ``audio_engine.kick.render_kick`` (and the name bound
in ``audio_engine.io``) when the plugin is loaded, i.e. before any test module imports it, so
every real render is counted, including those the cache makes on a miss.

Use it to show that a test calls the engine directly: its ``renders`` equal the number of
renders it asks for and its ``cache_hits`` are 0.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path

import audio_engine.io as _io
import audio_engine.kick as _kick

_original = _kick.render_kick
_current = {"test": None}
per_test: dict[str, dict] = defaultdict(lambda: {"renders": 0, "cache_hits": 0, "mp": False})


def counting_render_kick(params, *args, **kwargs):
    per_test[_current["test"] or "<outside a test>"]["renders"] += 1
    return _original(params, *args, **kwargs)


_kick.render_kick = counting_render_kick
_io.render_kick = counting_render_kick


def pytest_runtest_setup(item):
    _current["test"] = item.nodeid
    per_test[item.nodeid]["mp"] = "monkeypatch" in item.fixturenames


def pytest_runtest_call(item):
    from support import render_cache

    item._render_hits_before = render_cache.stats["hits"]


def pytest_runtest_teardown(item):
    from support import render_cache

    before = getattr(item, "_render_hits_before", render_cache.stats["hits"])
    per_test[item.nodeid]["cache_hits"] += render_cache.stats["hits"] - before
    _current["test"] = None


def _default_dir(config) -> Path:
    """pytest's --basetemp (``.pytest_tmp``, git-ignored) if set, else the system temp dir,
    so a run never leaves a file in the working tree."""
    base = getattr(config.option, "basetemp", None)
    folder = Path(base) if base else Path(tempfile.gettempdir())
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def pytest_sessionfinish(session):
    if hasattr(session.config, "workerinput"):  # xdist worker: counts are per process
        name = f"render_counter.{session.config.workerinput['workerid']}.json"
    else:
        name = "render_counter.json"
    out = os.environ.get("RENDER_COUNTER_OUT") or _default_dir(session.config) / name
    rows = dict(sorted(per_test.items()))
    summary = {
        "renders": sum(r["renders"] for r in rows.values()),
        "cache_hits": sum(r["cache_hits"] for r in rows.values()),
        "tests": rows,
    }
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
