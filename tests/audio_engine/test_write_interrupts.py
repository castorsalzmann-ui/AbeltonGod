"""Interrupts and errors inside ``audio_engine.io.write_kick`` leave no partial file (#94).

The sweep raises ``KeyboardInterrupt`` from a ``sys.settrace`` hook at every line event of
``write_kick`` and its clean-up helper, one run per point, and compares the whole folder with
its start state. Before #94 it found a 0-byte WAV, a WAV without sidecar and a WAV with a
0-byte sidecar. The expected end state is written out here (start files, plus the foreign
sidecar if the simulated race already wrote it), not derived from the module.
"""

from __future__ import annotations

import builtins
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import audio_engine.io as io_mod
from audio_engine.io import write_kick

FAST = {"schema_version": "0.2", "seed": 7, "length_ms": 80}
FIXED_TIME = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
TRACED = {"write_kick", "_discard"}


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(root.iterdir())}


class _Sweep:
    """Raise KeyboardInterrupt at the k-th line event of the traced io functions."""

    def __init__(self, k: int) -> None:
        self.k, self.seen, self.hit = k, 0, None

    def _local(self, frame, event, arg):
        if event == "line":
            self.seen += 1
            if self.seen == self.k:
                self.hit = (frame.f_code.co_name, frame.f_lineno)
                raise KeyboardInterrupt
        return self._local

    def global_trace(self, frame, event, arg):
        code = frame.f_code
        if code.co_filename == io_mod.__file__ and code.co_name in TRACED:
            return self._local
        return None


def _run_with_interrupt(k: int, call) -> tuple[_Sweep, str]:
    sweep = _Sweep(k)
    sys.settrace(sweep.global_trace)
    try:
        call()
        result = "returned"
    except KeyboardInterrupt:
        result = "interrupted"
    finally:
        sys.settrace(None)
    return sweep, result


def _racing_unique_pair(monkeypatch) -> dict:
    """The sidecar name of the first attempt is taken right after the free-name check."""
    real = io_mod._unique_pair
    state = {"raced": False}

    def racing(out, stem):
        wav, js = real(out, stem)
        if not state["raced"]:
            js.write_bytes(b"theirs")
            state["raced"] = True
        return wav, js

    monkeypatch.setattr(io_mod, "_unique_pair", racing)
    return state


@pytest.fixture
def no_tracer():
    if sys.gettrace() is not None:  # a debugger or coverage tool owns the hook
        pytest.skip("another trace function is active")


@pytest.mark.parametrize("race", [False, True], ids=["existing-pair", "sidecar-race"])
def test_ctrl_c_at_every_line_of_write_kick_leaves_no_partial_file(
    tmp_path, monkeypatch, no_tracer, race: bool
) -> None:
    points = interrupted = 0
    problems = []
    for k in range(1, 1000):
        out = tmp_path / f"run{k}"
        out.mkdir()
        (out / "kick.wav").write_bytes(b"k")  # someone else's pair: must never change
        (out / "kick.json").write_bytes(b"j")
        if race:
            (out / "kick.wav").unlink()
            (out / "kick.json").unlink()
            (out / "other.wav").write_bytes(b"o")
            state = _racing_unique_pair(monkeypatch)
        before = snapshot(out)
        sweep, result = _run_with_interrupt(
            k, lambda out=out: write_kick(FAST, out, created_at=FIXED_TIME)
        )
        if sweep.hit is None:
            assert result == "returned"
            break
        points += 1
        assert result == "interrupted", sweep.hit
        interrupted += 1
        expected = dict(before)
        if race and state["raced"]:
            expected["kick.json"] = b"theirs"
        after = snapshot(out)
        if after != expected:
            problems.append((sweep.hit, sorted(set(after) ^ set(expected))))
        monkeypatch.undo()
    # The sweep really reached the writes: at least the render, both opens and the return.
    assert points >= 30, points
    assert problems == []


def test_sweep_detects_the_old_window(tmp_path, monkeypatch, no_tracer) -> None:
    """The sweep can fail: with the clean-up switched off, interrupt points that leave files
    are found (guards against a tracer that silently never fires)."""
    monkeypatch.setattr(io_mod, "_discard", lambda *a, **k: None)
    left = 0
    for k in range(1, 1000):
        out = tmp_path / f"run{k}"
        out.mkdir()
        sweep, _ = _run_with_interrupt(
            k, lambda out=out: write_kick(FAST, out, created_at=FIXED_TIME)
        )
        if sweep.hit is None:
            break
        left += bool(list(out.iterdir()))
    assert left >= 5


class _EnterInterrupted:
    """A real file whose ``with`` entry is interrupted: the file exists, is open, and the
    ``with`` statement never took ownership of closing it."""

    instances: list = []

    def __init__(self, f) -> None:
        self.f = f
        _EnterInterrupted.instances.append(self)

    def __enter__(self):
        raise KeyboardInterrupt

    def __exit__(self, *exc):  # pragma: no cover - never entered
        return False

    def close(self) -> None:
        self.f.close()


@pytest.mark.parametrize("suffix", [".wav", ".json"])
def test_interrupt_right_after_open_closes_and_removes_the_file(
    tmp_path, monkeypatch, suffix: str
) -> None:
    real_open = builtins.open
    _EnterInterrupted.instances = []

    def open_then_interrupt(file, mode="r", *args, **kwargs):
        f = real_open(file, mode, *args, **kwargs)
        return _EnterInterrupted(f) if str(file).endswith(suffix) else f

    monkeypatch.setattr(io_mod, "open", open_then_interrupt, raising=False)
    with pytest.raises(KeyboardInterrupt):
        write_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert list(tmp_path.iterdir()) == []
    [opened] = _EnterInterrupted.instances
    assert opened.f.closed  # closed before unlink (an open file cannot be removed on Windows)


def test_permission_error_in_clean_up_keeps_the_original_error(tmp_path, monkeypatch) -> None:
    """Windows: a scanner holds the fresh WAV, so removing it fails. The caller must still get
    the disk-full error, and the sidecar must still be removed."""
    real_open = builtins.open
    real_unlink = os.unlink

    class FullDisk:
        def __init__(self, f):
            self._f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._f.close()
            return False

        def close(self):
            self._f.close()

        def write(self, _data):
            raise OSError(28, "No space left on device (simulated)")

    def open_full_json(file, mode="r", *args, **kwargs):
        f = real_open(file, mode, *args, **kwargs)
        return FullDisk(f) if str(file).endswith(".json") else f

    def held_wav_unlink(path, *args, **kwargs):
        if str(path).endswith(".wav"):
            raise PermissionError(13, "held by another process (simulated)")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(io_mod, "open", open_full_json, raising=False)
    monkeypatch.setattr(io_mod.os, "unlink", held_wav_unlink)
    with pytest.raises(OSError) as info:
        write_kick(FAST, tmp_path, created_at=FIXED_TIME)
    monkeypatch.undo()
    assert info.value.errno == 28 and "simulated" in str(info.value)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["kick.wav"]  # could not be removed


def test_failed_removal_after_a_sidecar_race_is_raised_not_skipped(tmp_path, monkeypatch) -> None:
    """Sidecar name taken, our WAV cannot be removed: the call must not go on to the next
    counter (that would leave an orphan WAV silently); the removal error is raised and the
    foreign sidecar stays."""
    _racing_unique_pair(monkeypatch)
    real_unlink = os.unlink

    def held_wav_unlink(path, *args, **kwargs):
        if str(path).endswith(".wav"):
            raise PermissionError(13, "held by another process (simulated)")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(io_mod.os, "unlink", held_wav_unlink)
    with pytest.raises(PermissionError, match="simulated"):
        write_kick(FAST, tmp_path, created_at=FIXED_TIME)
    monkeypatch.undo()
    assert snapshot(tmp_path).keys() == {"kick.wav", "kick.json"}
    assert (tmp_path / "kick.json").read_bytes() == b"theirs"


def test_interrupt_while_removing_after_a_sidecar_race_keeps_the_foreign_sidecar(
    tmp_path, monkeypatch
) -> None:
    """Ctrl+C during the removal of our WAV (sidecar race): our WAV is still removed by the
    general clean-up, the foreign sidecar is never touched."""
    _racing_unique_pair(monkeypatch)
    real_unlink = os.unlink
    calls = {"n": 0}

    def interrupted_first_unlink(path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise KeyboardInterrupt
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(io_mod.os, "unlink", interrupted_first_unlink)
    with pytest.raises(KeyboardInterrupt):
        write_kick(FAST, tmp_path, created_at=FIXED_TIME)
    monkeypatch.undo()
    assert calls["n"] == 2
    assert snapshot(tmp_path) == {"kick.json": b"theirs"}


def test_rendered_bytes_are_unchanged_by_the_new_write_path(tmp_path) -> None:
    """#94 changes only file handling: the WAV on disk is exactly what the encoder returns."""
    wav_path, _ = write_kick(FAST, tmp_path, created_at=FIXED_TIME)
    wav_bytes, _, _ = io_mod.render_kick_wav(FAST)
    assert wav_path.read_bytes() == wav_bytes
