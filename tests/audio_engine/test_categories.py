"""Category-neutral write / re-render / place path (#230). Kick bytes must not move; a clap
sidecar is refused by category, not by kick-parameter validation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from audio_engine import ENGINE_NAME, ENGINE_VERSION
from audio_engine.categories import (
    CONTRACT_CATEGORIES,
    CategoryUnavailable,
    get_category,
    registered_categories,
    resolve_params,
)
from audio_engine.io import (
    EngineVersionMismatch,
    rerender_from_sidecar,
    write_kick,
    write_sample,
)
from audio_engine.params import METADATA_SCHEMA_FILE, KickParamsError
from library import place_kick, place_sample

STAMP = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)
KICK = {"schema_version": "0.3", "seed": 4}


def _clap_sidecar(directory: Path, engine_version: str = "0.1.0") -> Path:
    meta = {
        "schema_version": "0.2",
        "file": "clap.wav",
        "category": "clap",
        "engine": {"name": "abeltongod-audio-engine-clap", "version": engine_version},
        "parameters": {"schema_version": "0.1", "seed": 1},
        "features": {"peak_dbfs": -0.3, "length_ms": 500.0},
        "created_at": "2026-11-02T12:00:00+00:00",
    }
    path = directory / "clap.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    return path


def test_registry_and_contract_agree() -> None:
    schema = json.loads(METADATA_SCHEMA_FILE.read_text(encoding="utf-8"))
    assert tuple(schema["properties"]["category"]["enum"]) == CONTRACT_CATEGORIES
    assert registered_categories() == ("kick", "clap", "hat", "rim")
    assert get_category("kick").engine == {"name": ENGINE_NAME, "version": ENGINE_VERSION}


@pytest.fixture
def clap_unregistered(monkeypatch):
    """A contract category without a renderer (what clap was before #231)."""
    from audio_engine import categories

    monkeypatch.delitem(categories._REGISTRY, "clap")


def test_unregistered_category_is_refused_by_category_everywhere(
    tmp_path: Path, clap_unregistered
) -> None:
    with pytest.raises(CategoryUnavailable, match="clap"):
        get_category("clap")
    with pytest.raises(CategoryUnavailable, match="clap"):
        resolve_params("clap", {"schema_version": "0.1", "seed": 1})
    with pytest.raises(CategoryUnavailable, match="clap"):
        write_sample("clap", {"schema_version": "0.1", "seed": 1}, tmp_path)
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(CategoryUnavailable, match="clap"):
        place_sample("clap", {"schema_version": "0.1", "seed": 1}, tmp_path)
    assert list(tmp_path.iterdir()) == []  # no folders created either


@pytest.mark.parametrize("allow", [False, True])
def test_rerender_refuses_unregistered_category_by_category(
    tmp_path: Path, allow: bool, clap_unregistered
) -> None:
    sidecar = _clap_sidecar(tmp_path)
    with pytest.raises(CategoryUnavailable) as err:
        rerender_from_sidecar(sidecar, allow_engine_mismatch=allow)
    # not a kick-parameter error, not an engine mismatch
    assert not isinstance(err.value, KickParamsError | EngineVersionMismatch)
    assert "clap" in str(err.value)


def test_kick_write_sample_is_byte_identical_to_write_kick(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    wav_a, json_a = write_kick(KICK, a, "k", created_at=STAMP)
    wav_b, json_b = write_sample("kick", KICK, b, "k", created_at=STAMP)
    assert wav_a.read_bytes() == wav_b.read_bytes()
    assert json_a.read_bytes() == json_b.read_bytes()
    meta = json.loads(json_a.read_text(encoding="utf-8"))
    assert meta["category"] == "kick" and meta["schema_version"] == "0.1"
    assert meta["engine"] == {"name": ENGINE_NAME, "version": ENGINE_VERSION}


def test_kick_rerender_and_engine_mismatch_still_work(tmp_path: Path) -> None:
    wav, sidecar = write_kick(KICK, tmp_path, "k", created_at=STAMP)
    assert rerender_from_sidecar(sidecar) == wav.read_bytes()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["engine"]["version"] = "9.9.9"
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(EngineVersionMismatch) as err:
        rerender_from_sidecar(sidecar)
    assert err.value.current_engine == {"name": ENGINE_NAME, "version": ENGINE_VERSION}


def test_place_sample_kick_matches_place_kick(tmp_path: Path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    a = place_kick(KICK, one, name="x", created_at=STAMP)
    b = place_sample("kick", KICK, two, name="x", created_at=STAMP)
    assert a.relative_to(one) == b.relative_to(two)
    assert a.read_bytes() == b.read_bytes()


def test_unknown_category_name_is_refused() -> None:
    with pytest.raises(CategoryUnavailable, match="unknown category"):
        get_category("perc")
