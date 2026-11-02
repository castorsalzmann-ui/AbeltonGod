"""``--category clap`` of the audio_engine CLI (#231). The kick CLI tests stay as they were."""

from __future__ import annotations

import io
import json
from pathlib import Path

import audio_engine.cli as cli
from audio_engine.io import rerender_from_sidecar


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    return cli.main(argv, stdout=out, stderr=err), out.getvalue(), err.getvalue()


def test_list_clap_presets_and_default_list_is_still_kick() -> None:
    code, out, _ = run(["--category", "clap", "--list-presets"])
    assert code == 0 and [ln.split()[0] for ln in out.splitlines()] == [
        "bright", "default", "long", "short"]
    _, kick_out, _ = run(["--list-presets"])
    assert "centre" in kick_out and "short" not in kick_out


def test_clap_preset_with_variants_writes_valid_rerenderable_pairs(tmp_path: Path) -> None:
    code, out, err = run(["--category", "clap", "--preset", "long", "--variants", "3",
                          "--out", str(tmp_path)])
    assert code == 0 and err == ""
    assert sorted(p.name for p in tmp_path.glob("*.wav")) == [
        f"long_s2003_v{i}.wav" for i in range(3)]
    assert len(out.splitlines()) == 3 and "t60=" in out
    for js in sorted(tmp_path.glob("*.json")):
        meta = json.loads(js.read_text(encoding="utf-8"))
        assert meta["category"] == "clap" and meta["parameters"]["preset"] == "long"
        assert rerender_from_sidecar(js) == js.with_suffix(".wav").read_bytes()


def test_clap_set_seed_and_errors(tmp_path: Path) -> None:
    code, _, _ = run(["--category", "clap", "--preset", "short", "--seed", "5",
                      "--set", "tail_decay_ms=170", "--out", str(tmp_path)])
    assert code == 0 and (tmp_path / "short_s5_v0_custom.wav").exists()
    before = sorted(tmp_path.iterdir())
    for argv in (["--category", "clap", "--preset", "short", "--set", "bp_hz=99999"],
                 ["--category", "clap", "--preset", "centre"],  # a kick preset name
                 ["--category", "clap", "--preset", "short", "--set", "bogus=1"]):
        code, _, err = run([*argv, "--out", str(tmp_path)])
        assert code == 2 and err.startswith("error:")
    assert sorted(tmp_path.iterdir()) == before
