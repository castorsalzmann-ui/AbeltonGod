"""Engine version rule (#35): every change to rendered bytes bumps ``ENGINE_VERSION``.

The golden SHA-256s below pin the exact WAV bytes of five renders: 48 kHz / 24-bit odd, even
and driven, plus two 44.1 kHz odd-length renders that reach 16-bit, tone > 0 and < 0, a loud
bright click and an attack (review round 1 of PR #40: a tone-only byte change passed the first
three). If one of them fails, rendered bytes changed: bump ``ENGINE_VERSION`` in
``audio_engine/__init__.py`` **and** update ``ENGINE_VERSION_OF_GOLDEN`` and the hashes here,
in the same PR (PR template checkbox). Never update a hash without the bump.

Hashes recorded on Linux (CPython 3.13, NumPy 2.5) for ``ENGINE_VERSION`` 0.1.0, i.e. after
the continuous drive of #16; ubuntu and windows CI (Python 3.12) reproduce them, so a
mismatch on Linux or Windows fails. On any other platform the hash is still computed, a match
passes and a mismatch is an ``xfail`` that names the actual hash, so CI collects the evidence
(and ``tests/conftest.py`` turns either outcome into a GitHub annotation).
Sample count and file size are checked on every platform.
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
# Hard failure on these platforms; elsewhere a mismatch is an xfail with the actual hash.
# win32: windows-latest CI (Python 3.12, run 40730447060) matched all five hashes; D-005
# promises byte-identical output, so a Windows mismatch must fail (lead decision, PR #40).
GOLDEN_PLATFORMS = ("linux", "win32")

# name: (params, sample_rate, bit_depth, samples, file size, sha256)
GOLDEN = {
    # 80.02 ms at 48 kHz -> 3841 samples: odd 24-bit data chunk, so the RIFF pad byte (#26).
    "odd-24bit-clean": (
        {"schema_version": "0.2", "seed": 35, "length_ms": 80.02, "drive": 0.0},
        48000, 24, 3841, 11568,
        "72e802231c82a8d7f031d9300b82c96816c69ae80dc0f0e4222a250721ab31d9",
    ),
    "even-24bit-clean": (
        {"schema_version": "0.2", "seed": 35, "length_ms": 80.0, "drive": 0.0},
        48000, 24, 3840, 11564,
        "8bd08d677622eb9a5dd3d693c43653319faae4aaa55898510fbe6b9d25d7f33c",
    ),
    "even-24bit-drive-0.6": (
        {"schema_version": "0.2", "seed": 35, "length_ms": 80.0, "drive": 0.6},
        48000, 24, 3840, 11564,
        "f0920b11bc66bb438fd7fae537c117e6e23a29f7bb0fc2ddbca55dfeb49ca280",
    ),
    # 100.03 ms at 44.1 kHz -> 4411 samples (odd). 16-bit, bright tone, loud high click, drive.
    "odd-44k1-16bit-bright-click": (
        {"schema_version": "0.2", "seed": 35, "sample_rate": 44100, "bit_depth": 16,
         "length_ms": 100.03, "tone": 0.7, "click_level": 1.0, "click_tone_hz": 9000,
         "drive": 0.3},
        44100, 16, 4411, 8866,
        "7f98f2a0c1829f7c3853e1e11a15cc05cbd6baf74af24f2df3d935a05acde090",
    ),
    # Same length at 24-bit: dark tone and a 4 ms attack (odd 24-bit data, pad byte).
    "odd-44k1-24bit-dark-attack": (
        {"schema_version": "0.2", "seed": 35, "sample_rate": 44100, "bit_depth": 24,
         "length_ms": 100.03, "tone": -0.7, "amp_attack_ms": 4.0, "drive": 0.3},
        44100, 24, 4411, 13278,
        "819fada37f22e3016fbe1d03d0f9a1f697495c7e80a8e7af5bcb799b5e64415e",
    ),
}


def test_golden_hashes_match_the_version() -> None:
    assert audio_engine.ENGINE_VERSION == ENGINE_VERSION_OF_GOLDEN, (
        "ENGINE_VERSION changed: re-record the golden hashes in this file for the new version"
    )


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_render_size(name: str) -> None:
    """Platform-independent part: sample count and file size (44-byte header + pad byte)."""
    params, sr, bits, samples, size, _ = GOLDEN[name]
    wav, audio, resolved = render_kick_wav(params)
    assert (resolved["sample_rate"], resolved["bit_depth"]) == (sr, bits)
    assert len(audio) == samples
    width = bits // 8
    assert len(wav) == size == 44 + width * samples + (width * samples) % 2


def test_golden_cases_reach_every_rate_depth_and_tone_sign() -> None:
    """Keeps the reach the review asked for if cases are edited later."""
    resolved = [render_kick_wav(g[0])[2] for g in GOLDEN.values()]
    assert {r["sample_rate"] for r in resolved} == {44100, 48000}
    assert {r["bit_depth"] for r in resolved} == {16, 24}
    assert {(r["tone"] > 0) - (r["tone"] < 0) for r in resolved} == {-1, 0, 1}
    assert any(r["drive"] == 0 for r in resolved) and any(r["drive"] > 0 for r in resolved)
    assert any(r["amp_attack_ms"] > 1 for r in resolved)


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_sha256(name: str, request) -> None:
    params, *_, expected = GOLDEN[name]
    actual = hashlib.sha256(render_kick_wav(params)[0]).hexdigest()
    verdict = "match" if actual == expected else "MISMATCH"
    request.node.user_properties.append(("golden", f"{sys.platform} {name} {verdict} {actual}"))
    if sys.platform not in GOLDEN_PLATFORMS and actual != expected:
        pytest.xfail(f"golden hash differs on {sys.platform}: {name} actual {actual}")
    assert actual == expected, (
        f"{name}: rendered bytes changed ({actual}). Bump ENGINE_VERSION and update the "
        "golden hashes."
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
