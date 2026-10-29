"""Opt-in, read-only render cache for property tests (#77).

Why: in a serial run, 1001 of 3440 ``render_kick`` calls repeated an input that had already
been rendered (QA report #69). Almost all of them come from ``test_kick.py``: each of the 161
parameter sets is rendered again by five tests that only *read* the render.

How it stays honest:

- **Opt-in per test.** Only the test functions in ``CACHED_TESTS`` get the cache, and only
  for the duration of that test (``tests/conftest.py`` installs it in the test module and in
  ``audio_engine.io``, and restores the originals afterwards). Determinism, golden-hash,
  sidecar re-render and variant reproducibility tests are never on the list, so they always
  call the engine twice for real.
- **Bypassed under monkeypatch.** A test that requests ``monkeypatch`` is never cached, even
  if it is on the list. In addition, every call compares the engine modules
  (``audio_engine.kick``, ``.dsp``, ``.params``) with the state at import time: if any
  attribute was replaced (by monkeypatch or anything else), the call renders directly and
  nothing is stored. **Limit:** only rebinding is detected (the identity of each module
  attribute). An in-place change to a module-level object (e.g. writing into a module-level
  array or dict such as ``dsp._SPECTRA`` or ``kick._DRIVE_FILTER``) is *not* detected; such
  tests must not be on the list.
- **Exact key.** The key is the canonical JSON of the parameter dict. Only plain
  ``str``/``int``/``float``/``bool``/``None`` values are accepted; anything else (numpy
  scalars, nested objects) renders directly. ``7`` and ``7.0`` are different keys.
- **Self-checking.** Every hit compares the stored resolved params with
  ``resolve_kick_params(params)`` and raises ``StaleRenderError`` on a mismatch, so a wrong
  key can never hand a test another set's render.
- **Read-only.** The cached array is marked non-writeable and every call returns a view of
  it (a view of a read-only base cannot be made writeable again), plus a fresh copy of the
  resolved-params dict, so no test can change what the next one sees.
- **Switch off:** ``ABELTONGOD_RENDER_CACHE=0`` disables it for a whole run (cache-off
  comparison runs). Each process (each xdist worker, each mutation-runner run) has its own
  cache, so a mutant can never be hidden by a render from unmutated code.
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from typing import Any

import numpy as np

import audio_engine.dsp as _dsp
import audio_engine.kick as _kick
import audio_engine.params as _params

ENV_SWITCH = "ABELTONGOD_RENDER_CACHE"

# Test functions (file relative to the repo root :: function name) that only read renders and
# may share them. Keep determinism and byte-identity tests off this list.
CACHED_TESTS = frozenset(
    "tests/audio_engine/test_kick.py::" + name
    for name in (
        "test_signal_properties",
        "test_quantised_file_peak_never_exceeds_ceiling",
        "test_analysis_measures_the_real_signal",
        "test_measured_tail_pitch_matches_parameters",
        "test_tail_pitch_is_measurable_for_almost_all_kicks",
        "test_fast_decay_short_kicks_are_measured_correctly_or_reported_unmeasurable",
        "test_fast_decay_unmeasurable_share_is_bounded",
    )
)

# Upper bound on cached sample memory per process (float64 samples). The full test_kick set
# needs about 70 MB; older entries are dropped first when the bound is reached.
MAX_BYTES = 256 * 1024 * 1024

_WATCHED_MODULES = (_kick, _dsp, _params)
_ALLOWED_TYPES = (str, int, float, bool, type(None))

_store: OrderedDict[str, tuple[np.ndarray, dict[str, Any]]] = OrderedDict()
_bytes = 0
stats = {"hits": 0, "misses": 0, "bypassed": 0}


def _snapshot() -> tuple[tuple[str, tuple[tuple[str, int], ...]], ...]:
    return tuple(
        (m.__name__, tuple(sorted((k, id(v)) for k, v in vars(m).items())))
        for m in _WATCHED_MODULES
    )


# Keep the original objects alive, so their ids cannot be reused by a replacement.
_PINNED = tuple(dict(vars(m)) for m in _WATCHED_MODULES)
_PRISTINE = _snapshot()


def enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "1") != "0"


def should_cache(test_key: str, fixturenames) -> bool:
    """Whether the test ``<path>::<function>`` may use the cache."""
    return enabled() and test_key in CACHED_TESTS and "monkeypatch" not in fixturenames


def engine_untouched() -> bool:
    return _snapshot() == _PRISTINE


def cache_key(params: Any) -> str | None:
    """Canonical JSON of a flat params dict, or None if the input is not plainly keyable."""
    if type(params) is not dict:
        return None
    for k, v in params.items():
        if type(k) is not str or type(v) not in _ALLOWED_TYPES:
            return None
    return json.dumps(params, sort_keys=True, allow_nan=True)


def clear() -> None:
    global _bytes
    _store.clear()
    _bytes = 0
    for k in stats:
        stats[k] = 0


class StaleRenderError(AssertionError):
    """A cache hit belongs to other parameters than the ones asked for."""


def _check_hit(params: dict[str, Any], stored: dict[str, Any]) -> None:
    """Every hit is checked against the engine's own resolver (independent of the key code).

    Needed because a stale hit carries its own resolved params: tests that read everything
    from the returned ``(audio, resolved)`` pair stay self-consistent and cannot see that they
    got the wrong render (mutant STALE_KEY_FIELD_NAMES survived test_kick.py without this).
    """
    expected = _params.resolve_kick_params(params)
    for name in _kick.BATCH_ONLY_PARAMS:
        expected.pop(name, None)
    if expected != stored:
        raise StaleRenderError(f"cache hit for other parameters: {expected} != {stored}")


def _engine(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    # Looked up at call time, so a render counter wrapped around the engine still counts.
    return _kick.render_kick(params)


def cached_render_kick(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Drop-in for ``render_kick`` that may return a stored, read-only render."""
    global _bytes
    key = cache_key(params)
    if key is None or not engine_untouched():
        stats["bypassed"] += 1
        return _engine(params)
    hit = _store.get(key)
    if hit is not None:
        _check_hit(params, hit[1])
        _store.move_to_end(key)
        stats["hits"] += 1
        return hit[0].view(), dict(hit[1])
    audio, resolved = _engine(params)
    stats["misses"] += 1
    if not engine_untouched():  # patched while rendering: do not keep the result
        return audio, resolved
    frozen = np.array(audio, copy=True)
    frozen.setflags(write=False)
    _store[key] = (frozen, dict(resolved))
    _bytes += frozen.nbytes
    while _bytes > MAX_BYTES and len(_store) > 1:
        _, (old, _) = _store.popitem(last=False)
        _bytes -= old.nbytes
    return frozen.view(), dict(resolved)
