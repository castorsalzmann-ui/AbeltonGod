"""Hat category plumbing (#252) and its registered state (#270): folder, place_sample and the CLI
render hats; kick and clap placement is unchanged."""

from __future__ import annotations

import io
import json

import pytest

from audio_engine import cli
from audio_engine.categories import get_category, registered_categories
from audio_engine.io import rerender_from_sidecar
from library import place_sample
from library.layout import DEFAULT_LAYOUT, LibraryLayout, LibraryPathError


def test_hat_folder_is_samples_drums_hats() -> None:
    assert DEFAULT_LAYOUT.parts_for("hat") == ("Samples", "Drums", "Hats")
    assert LibraryLayout(hats="X/Y").parts_for("hat") == ("X", "Y")
    assert DEFAULT_LAYOUT.parts_for("kick") == ("Samples", "Drums", "Kicks")
    assert DEFAULT_LAYOUT.parts_for("clap") == ("Samples", "Drums", "Claps")
    with pytest.raises(LibraryPathError):
        LibraryLayout(hats="../x")


def test_hat_is_registered_with_its_own_engine_identity() -> None:
    assert sorted(registered_categories()) == ["bass", "clap", "hat", "kick"]
    engine = get_category("hat").engine
    assert engine == {"name": "abeltongod-audio-engine-hat", "version": "0.1.0"}
    assert get_category("hat").metadata_schema_version == "0.2"


def test_place_sample_hat_renders_into_the_hats_folder(tmp_path) -> None:
    wav = place_sample("hat", {"schema_version": "0.1", "seed": 1}, tmp_path)
    assert wav.relative_to(tmp_path).parts[:-1] == ("Samples", "Drums", "Hats")
    assert wav.name.startswith("hat") and wav.suffix == ".wav"
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "hat" and meta["engine"]["name"] == "abeltongod-audio-engine-hat"
    assert rerender_from_sidecar(wav.with_suffix(".json")) == wav.read_bytes()


def test_place_sample_kick_and_clap_still_go_to_their_folders(tmp_path) -> None:
    kick = place_sample("kick", {"schema_version": "0.3", "seed": 1}, tmp_path)
    clap = place_sample("clap", {"schema_version": "0.1", "seed": 1}, tmp_path)
    assert kick.relative_to(tmp_path).parts[:-1] == ("Samples", "Drums", "Kicks")
    assert clap.relative_to(tmp_path).parts[:-1] == ("Samples", "Drums", "Claps")


def test_place_sample_hat_rejects_a_bad_cross_field_before_any_folder(tmp_path) -> None:
    from audio_engine.hat import HatParamsError

    bad = {"schema_version": "0.1", "seed": 1, "hp_hz": 9000, "lp_hz": 10000}  # 10000 < 10800
    with pytest.raises(HatParamsError, match="lp_hz"):
        place_sample("hat", bad, tmp_path)
    assert not any(p.suffix == ".wav" for p in tmp_path.rglob("*"))


def test_cli_lists_and_renders_hat_presets(tmp_path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert cli.main(["--category", "hat", "--list-presets"], out, err) == 0
    assert [ln.split()[0] for ln in out.getvalue().splitlines()] == [
        "closed-loose", "closed-std", "closed-tight", "open-long", "open-short"]
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "hat", "--preset", "open-short", "--variants", "3",
                     "--out", str(tmp_path)], out, err)
    assert code == 0 and err.getvalue() == ""
    assert sorted(p.name for p in tmp_path.glob("*.wav")) == [
        f"open-short_s1_v{i}.wav" for i in range(3)]
    for js in sorted(tmp_path.glob("*.json")):
        meta = json.loads(js.read_text(encoding="utf-8"))
        assert meta["category"] == "hat" and meta["parameters"]["preset"] == "open-short"
        assert rerender_from_sidecar(js) == js.with_suffix(".wav").read_bytes()


@pytest.mark.parametrize("argv", [
    ["--preset", "closed-std", "--set", "lp_hz=8000", "--set", "hp_hz=9000"],  # lp <= 1.2 hp
    ["--preset", "closed-std", "--set", "choke_ms=3"],
    ["--preset", "centre"],  # a kick preset name
    ["--prompt", "sub"],
])
def test_cli_hat_errors_write_nothing(tmp_path, argv) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["--category", "hat", *argv, "--out", str(tmp_path / "o")], out, err)
    assert code == cli.EXIT_USAGE and err.getvalue().startswith("error:")
    assert out.getvalue() == "" and list(tmp_path.iterdir()) == []
