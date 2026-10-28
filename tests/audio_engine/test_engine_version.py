"""Engine version rule (#35): every change to rendered bytes bumps ``ENGINE_VERSION``.

The golden SHA-256s below pin the exact WAV bytes of three 48 kHz / 24-bit renders. If one of
them fails, rendered bytes changed: bump ``ENGINE_VERSION`` in ``audio_engine/__init__.py``
**and** update ``ENGINE_VERSION_OF_GOLDEN`` and the hashes here, in the same PR (PR template
checkbox). Never update a hash without the bump.

Hashes recorded on Linux (CPython 3.13, NumPy from ``pip install -e ".[dev]"``) for
``ENGINE_VERSION`` 0.1.0, i.e. after the continuous drive of #16. Byte identity is proven per
platform only (PR #8); see ``GOLDEN_PLATFORMS``. Sample count and file size are checked on
every platform.
"""

from __future__ import annotations

import hashlib
import json
import sys

import pytest

import audio_engine
import audio_engine.io as io_mod
from audio_engine.io import EngineVersionMismatch, render_kick_wav, rerender_from_sidecar

# The version the hashes below were recorded with. A byte change without a version bump
# fails the hash test; a bump without new hashes fails test_golden_hashes_match_the_version.
ENGINE_VERSION_OF_GOLDEN = "0.1.0"
# Recorded on Linux only. Whether Windows gives the same bytes is not established; add
# "win32" once a Windows run (CI or the user's machine) has shown the same hashes.
GOLDEN_PLATFORMS = ("linux",)

GOLDEN = {
    # 80.02 ms at 48 kHz -> 3841 samples: odd 24-bit data chunk, so the RIFF pad byte (#26).
    "odd-24bit-clean": (
        {"schema_version": "0.2", "seed": 35, "length_ms": 80.02, "drive": 0.0},
        3841,
        11568,
        "72e802231c82a8d7f031d9300b82c96816c69ae80dc0f0e4222a250721ab31d9",
    ),
    "even-24bit-clean": (
        {"schema_version": "0.2", "seed": 35, "length_ms": 80.0, "drive": 0.0},
        3840,
        11564,
        "8bd08d677622eb9a5dd3d693c43653319faae4aaa55898510fbe6b9d25d7f33c",
    ),
    "even-24bit-drive-0.6": (
        {"schema_version": "0.2", "seed": 35, "length_ms": 80.0, "drive": 0.6},
        3840,
        11564,
        "f0920b11bc66bb438fd7fae537c117e6e23a29f7bb0fc2ddbca55dfeb49ca280",
    ),
}


def test_golden_hashes_match_the_version() -> None:
    assert audio_engine.ENGINE_VERSION == ENGINE_VERSION_OF_GOLDEN, (
        "ENGINE_VERSION changed: re-record the golden hashes in this file for the new version"
    )


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_render_size(name: str) -> None:
    """Platform-independent part: sample count and file size (44-byte header + pad byte)."""
    params, samples, size, _ = GOLDEN[name]
    wav, audio, resolved = render_kick_wav(params)
    assert (resolved["sample_rate"], resolved["bit_depth"]) == (48000, 24)
    assert len(audio) == samples
    assert len(wav) == size == 44 + 3 * samples + samples % 2


@pytest.mark.skipif(sys.platform not in GOLDEN_PLATFORMS, reason="hashes recorded per platform")
@pytest.mark.parametrize("name", GOLDEN)
def test_golden_sha256(name: str) -> None:
    params, _, _, expected = GOLDEN[name]
    wav, _, _ = render_kick_wav(params)
    assert hashlib.sha256(wav).hexdigest() == expected, (
        f"{name}: rendered bytes changed. Bump ENGINE_VERSION and update the golden hashes."
    )


# --- re-rendering a sidecar from another engine version --------------------------------------


@pytest.fixture
def sidecar(tmp_path):
    _, json_path = io_mod.write_kick(GOLDEN["even-24bit-drive-0.6"][0], tmp_path, name="g")
    return json_path


def _with_engine(path, **engine) -> None:
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["engine"].update(engine)
    path.write_text(json.dumps(meta), encoding="utf-8")


def test_sidecar_carries_the_current_version(sidecar) -> None:
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["engine"] == {"name": "abeltongod-audio-engine", "version": "0.1.0"}


def test_same_version_rerenders_identically(sidecar) -> None:
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert hashlib.sha256(rerender_from_sidecar(sidecar)).hexdigest() == meta["sha256"]


@pytest.mark.parametrize(
    "engine",
    [
        {"version": "0.0.1"},
        {"version": "0.1.1"},
        {"version": "0.1"},
        {"version": "0.1.0 "},
        {"version": ""},
        {"name": "other-engine"},
    ],
    ids=lambda e: repr(e),
)
def test_other_engine_is_refused(sidecar, engine) -> None:
    _with_engine(sidecar, **engine)
    with pytest.raises(EngineVersionMismatch) as exc:
        rerender_from_sidecar(sidecar)
    assert isinstance(exc.value, ValueError)
    assert exc.value.current_engine == {"name": "abeltongod-audio-engine", "version": "0.1.0"}
    assert exc.value.sidecar_engine["version"] == {"version": "0.1.0", **engine}["version"]
    assert "allow_engine_mismatch" in str(exc.value)


def test_opt_in_renders_with_the_current_engine(sidecar) -> None:
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    _with_engine(sidecar, version="0.0.1")
    wav = rerender_from_sidecar(sidecar, allow_engine_mismatch=True)
    assert hashlib.sha256(wav).hexdigest() == meta["sha256"]  # params unchanged here


def test_refusal_happens_before_rendering(sidecar, monkeypatch) -> None:
    _with_engine(sidecar, version="0.0.1")

    def boom(params):
        raise AssertionError("rendered although the engine version differs")

    monkeypatch.setattr(io_mod, "render_kick_wav", boom)
    with pytest.raises(EngineVersionMismatch):
        rerender_from_sidecar(sidecar)


def test_opt_in_is_keyword_only(sidecar) -> None:
    with pytest.raises(TypeError):
        rerender_from_sidecar(sidecar, True)  # noqa: FBT003
