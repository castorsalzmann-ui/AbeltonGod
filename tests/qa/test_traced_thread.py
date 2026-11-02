"""The interrupt-sweep helper keeps a leaked handled exception out of the worker thread (#183)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import pytest
from support.traced_thread import run_in_fresh_thread

import audio_engine.io as io_mod
from audio_engine.io import write_kick

FAST = {"schema_version": "0.2", "seed": 7, "length_ms": 80}
LEAK_POINT = 35  # race case: found by bisection, a KeyboardInterrupt right after a handled
# FileExistsError in write_kick leaves it as the thread's handled exception (CPython 3.13.18)


def _sweep_point(k: int, tmp_path, monkeypatch) -> None:
    """The sidecar-race sweep point, written without the audio_engine test helpers."""
    out = tmp_path / f"run{k}"
    out.mkdir()
    (out / "other.wav").write_bytes(b"o")
    real = io_mod._unique_pair
    raced = []

    def racing(o, stem):
        wav, js = real(o, stem)
        if not raced:
            js.write_bytes(b"theirs")
            raced.append(1)
        return wav, js

    monkeypatch.setattr(io_mod, "_unique_pair", racing)
    seen = [0]

    def local(frame, event, arg):
        if event == "line":
            seen[0] += 1
            if seen[0] == k:
                raise KeyboardInterrupt
        return local

    def glob(frame, event, arg):
        c = frame.f_code
        if c.co_filename == io_mod.__file__ and c.co_name in {"write_kick", "_discard"}:
            return local
        return None

    sys.settrace(glob)
    try:
        write_kick(FAST, out, created_at=datetime(2026, 10, 28, tzinfo=UTC))
    except KeyboardInterrupt:
        pass
    finally:
        sys.settrace(None)


def test_sweep_point_in_a_fresh_thread_leaves_this_thread_clean(tmp_path, monkeypatch) -> None:
    if sys.gettrace() is not None:
        pytest.skip("another trace function is active")
    assert sys.exception() is None
    run_in_fresh_thread(lambda: _sweep_point(LEAK_POINT, tmp_path, monkeypatch))
    assert sys.exception() is None
    try:
        raise IndexError("later error")
    except IndexError as exc:
        assert exc.__context__ is None


def test_the_leak_is_real_in_the_same_thread(tmp_path, monkeypatch) -> None:
    """Guards the guard: without the fresh thread the sweep point does leave the exception
    (if CPython ever fixes this, the test fails and the helper can go)."""
    if sys.gettrace() is not None:
        pytest.skip("another trace function is active")

    def leak_and_report() -> bool:
        _sweep_point(LEAK_POINT, tmp_path, monkeypatch)
        return sys.exception() is not None

    assert run_in_fresh_thread(leak_and_report) is True  # inside a thread: main stays clean
    assert sys.exception() is None


def test_errors_and_results_cross_the_thread_boundary() -> None:
    assert run_in_fresh_thread(lambda: 5) == 5
    with pytest.raises(KeyError):
        run_in_fresh_thread(lambda: {}["x"])
