"""pytest plugin (QA measurement, #278): find engine renders repeated across tests.

    PYTHONPATH=scripts/qa python -m pytest -o pythonpath=src -n 0 -p no:cacheprovider \
        -p render_dups tests/audio_engine                # run from the repo root

Records, for every real ``render_kick`` call, the canonical JSON of its input and the test
function that made it (parameter ids stripped). At the end it prints, per test function, how
many of its renders were an input that an *earlier call in the same run* had already rendered,
and the CPU seconds spent on those repeats, so shared renders can be targeted by measured cost
rather than by guess. **Candidates, not proof:** it compares inputs only. A test that patches
the engine (``monkeypatch``) renders the same input differently on purpose, so its "repeats" are not
savings (#278: test_dc_correction, the aliasing and drive-continuity tests). Check each hit
before sharing a render. Only counts; it changes no test and never caches anything. Output file:
``RENDER_DUPS_OUT`` (default ``render_dups.json`` in the system temp dir).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections import defaultdict

import audio_engine.io as _io
import audio_engine.kick as _kick

_original = _kick.render_kick
_current = {"fn": "<outside>"}
_seen: dict[str, str] = {}  # input -> test function that first rendered it
_fn = defaultdict(lambda: {"renders": 0, "repeats": 0, "cpu": 0.0, "repeat_cpu": 0.0, "from": {}})


def _key(params) -> str:
    try:
        return json.dumps(params, sort_keys=True, default=repr)
    except TypeError:
        return repr(params)


def counting_render_kick(params, *args, **kwargs):
    k = _key(params)
    t0 = time.process_time()
    try:
        return _original(params, *args, **kwargs)
    finally:
        dt = time.process_time() - t0
        row = _fn[_current["fn"]]
        row["renders"] += 1
        row["cpu"] += dt
        if k in _seen:
            row["repeats"] += 1
            row["repeat_cpu"] += dt
            src = _seen[k]
            row["from"][src] = row["from"].get(src, 0) + 1
        else:
            _seen[k] = _current["fn"]


_kick.render_kick = counting_render_kick
_io.render_kick = counting_render_kick


def pytest_runtest_setup(item):
    _current["fn"] = f"{item.path.name}::{getattr(item, 'originalname', item.name)}"


def pytest_sessionfinish(session):
    out = os.environ.get("RENDER_DUPS_OUT") or os.path.join(
        tempfile.gettempdir(), "render_dups.json"
    )
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(_fn.items())), fh, indent=1)
    rows = sorted(_fn.items(), key=lambda kv: -kv[1]["repeat_cpu"])
    total = sum(r["renders"] for _, r in rows)
    rep = sum(r["repeats"] for _, r in rows)
    print(f"\nrender_dups: {total} renders, {rep} repeated inputs; top repeat cost (cpu s):")
    for name, r in rows[:15]:
        print(
            f"  {r['repeat_cpu']:7.2f}s  {r['repeats']:5d}/{r['renders']:5d}  {name}"
            f"  <- {dict(sorted(r['from'].items(), key=lambda kv: -kv[1])[:2])}"
        )
