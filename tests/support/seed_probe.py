"""pytest plugin: record every RNG seeding done by test code and every parametrize value (#119).

Load it with ``-p support.seed_probe`` and set ``SEED_PROBE_OUT`` to a file path. At the end of
the session it writes one JSON file per process (``<out>.<worker>.json``, worker ``main``
without xdist):

- ``seeds``: one record per seeding call ``{"where", "phase", "kind", "seed"}``. ``where`` is
  ``<path relative to the rootdir>:<line>`` of the first calling frame outside ``random``,
  numpy, this file and ``tests/support/kick_params.py`` (so a ``kp.rng(...)`` call is
  attributed to the test line that made it). Only calls whose ``where`` lies under
  ``<rootdir>/tests`` are kept: the engine seeding its click noise from a parameter set is
  not a test seed. ``phase`` is ``collect`` (module level, parametrize) or the node id of the
  running test.
- ``params``: one record per collected parametrized item ``{"function", "index", "id",
  "params"}``; ``params`` maps each argument name to a ``repr`` with memory addresses removed.
- ``skipped``: node ids of the tests that were run but skipped (their bodies seed nothing).

Seen: ``random.Random(x)`` / ``.seed(x)`` (also ``SystemRandom`` subclasses, any spelling of
the class), module-level ``random.seed(x)``, ``numpy.random.default_rng(x)`` and
``numpy.random.seed(x)``. Not seen: ``numpy.random.RandomState(x)``, ``Generator(PCG64(x))``
and bit generators built directly (none in ``tests/`` at #119), and names bound with
``from numpy.random import default_rng`` before the plugin is configured.

``SEED_PROBE_RUN`` (optional, comma-separated node-id prefixes): after the parametrize values
are recorded, only matching items are kept, so a collect + run of a few tests sees the
seedings made inside those test bodies.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

_HERE = Path(__file__).resolve()
_SKIP_FILES = {
    str(_HERE), str(_HERE.with_name("kick_params.py")), str(Path(random.__file__).resolve()),
}
_NUMPY_DIR = str(Path(np.__file__).resolve().parent)
_ADDR = re.compile(r" at 0x[0-9a-fA-F]+")

_state: dict[str, Any] = {
    "phase": "collect", "seeds": [], "params": [], "root": None, "skipped": [],
}
_originals: dict[str, Any] = {}


_resolved: dict[str, str] = {}


def _real(filename: str) -> str:
    if filename not in _resolved:
        _resolved[filename] = str(Path(filename).resolve())
    return _resolved[filename]


def _caller() -> str | None:
    frame = sys._getframe(2)
    while frame is not None:
        f = _real(frame.f_code.co_filename)
        if f not in _SKIP_FILES and not f.startswith(_NUMPY_DIR):
            break
        frame = frame.f_back
    if frame is None:
        return None
    path = Path(_real(frame.f_code.co_filename))
    root = _state["root"]
    try:
        path.relative_to(root / "tests")
    except ValueError:
        return None
    return f"{path.relative_to(root).as_posix()}:{frame.f_lineno}"


def _plain(seed: Any) -> Any:
    if seed is None or (isinstance(seed, int) and not isinstance(seed, bool)):
        return seed
    if isinstance(seed, np.integer):
        return int(seed)
    return _ADDR.sub("", repr(seed))


def _record(kind: str, seed: Any) -> None:
    where = _caller()
    if where is not None:
        _state["seeds"].append(
            {"where": where, "phase": _state["phase"], "kind": kind, "seed": _plain(seed)})


def _install() -> None:
    _originals["Random.seed"] = orig_seed = random.Random.seed
    _originals["random.seed"] = random.seed
    _originals["default_rng"] = orig_rng = np.random.default_rng
    _originals["np.seed"] = orig_np_seed = np.random.seed

    def seed(self, a=None, version=2):
        _record("random", a)
        return orig_seed(self, a, version)

    def module_seed(a=None, version=2):
        return random._inst.seed(a, version)  # goes through the patched method above

    def default_rng(seed=None):
        _record("numpy", seed)
        return orig_rng(seed)

    def np_seed(seed=None):
        _record("numpy-legacy", seed)
        return orig_np_seed(seed)

    random.Random.seed = seed
    random.seed = module_seed
    np.random.default_rng = default_rng
    np.random.seed = np_seed


def _uninstall() -> None:
    if not _originals:
        return
    random.Random.seed = _originals.pop("Random.seed")
    random.seed = _originals.pop("random.seed")
    np.random.default_rng = _originals.pop("default_rng")
    np.random.seed = _originals.pop("np.seed")


def pytest_configure(config) -> None:
    _state["root"] = Path(config.rootpath).resolve()
    _install()


def pytest_unconfigure(config) -> None:
    _uninstall()


def _function(item) -> str:
    return item.nodeid.split("[", 1)[0]


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items) -> None:
    counts: dict[str, int] = {}
    for item in items:
        callspec = getattr(item, "callspec", None)
        if callspec is None:
            continue
        fn = _function(item)
        index = counts[fn] = counts.get(fn, -1) + 1
        _state["params"].append({
            "function": fn, "index": index, "id": callspec.id,
            "params": {k: _ADDR.sub("", repr(v)) for k, v in callspec.params.items()},
        })
    run = [p for p in os.environ.get("SEED_PROBE_RUN", "").split(",") if p]
    if run:
        keep = [i for i in items if any(i.nodeid.startswith(p) for p in run)]
        config.hook.pytest_deselected(items=[i for i in items if i not in keep])
        items[:] = keep


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    _state["phase"] = item.nodeid
    try:
        return (yield)
    finally:
        _state["phase"] = "collect"


def pytest_runtest_logreport(report) -> None:
    if report.skipped and report.when in ("setup", "call"):
        _state["skipped"].append(report.nodeid)


def pytest_sessionfinish(session) -> None:
    out = os.environ.get("SEED_PROBE_OUT")
    if not out:
        return
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    doc = {"seeds": _state["seeds"], "params": _state["params"], "skipped": _state["skipped"]}
    Path(f"{out}.{worker}.json").write_text(json.dumps(doc), encoding="utf-8")
