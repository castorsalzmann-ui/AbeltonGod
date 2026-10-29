"""Issue #3 (Phase 01b): the kick CLI ``python -m audio_engine.kick``.

Exit codes, file names, never-overwrite, sidecar content, and that every error before writing
leaves the output folder untouched (it is not even created).
"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import audio_engine
import audio_engine.cli as cli
from audio_engine.io import rerender_from_sidecar, write_kick
from audio_engine.params import METADATA_SCHEMA_FILE, load_schema
from audio_engine.presets import load_preset

NAMES = ["centre", "dark-dry", "dense", "driven", "punchy", "rumble-ready"]


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def tree(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*")) if path.exists() else []


# --- happy path ------------------------------------------------------------------------------


def test_list_presets() -> None:
    code, out, err = run(["--list-presets"])
    assert code == 0 and err == ""
    assert [line.split()[0] for line in out.splitlines()] == NAMES


def test_preset_with_variants_writes_named_pairs(tmp_path) -> None:
    code, out, err = run(["--preset", "punchy", "--variants", "3", "--out", str(tmp_path)])
    assert (code, err) == (0, "")
    stems = [f"punchy_s1003_v{i}" for i in range(3)]
    assert tree(tmp_path) == sorted(f"{s}.{e}" for s in stems for e in ("json", "wav"))
    lines = out.splitlines()
    assert len(lines) == 3
    for stem, line in zip(stems, lines, strict=True):
        assert line.startswith(str(tmp_path / f"{stem}.wav"))
        assert "f0=" in line and "d40=" in line and "peak=-0.3 dBFS" in line
    schema = load_schema(METADATA_SCHEMA_FILE)
    seeds = []
    for i, stem in enumerate(stems):
        meta = json.loads((tmp_path / f"{stem}.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(meta)
        assert meta["file"] == f"{stem}.wav"
        assert meta["parameters"]["preset"] == "punchy"
        assert "variants" not in meta["parameters"]
        assert f"Variant {i} of 3, base seed 1003" in meta["description"]
        seeds.append(meta["parameters"]["seed"])
        wav = (tmp_path / f"{stem}.wav").read_bytes()
        assert meta["sha256"] == hashlib.sha256(wav).hexdigest()
        assert rerender_from_sidecar(tmp_path / f"{stem}.json") == wav
    assert seeds == [1003, 2022732847, 2606410306]  # literal, from the design proposal


def test_variant_zero_equals_the_preset_rendered_alone(tmp_path) -> None:
    run(["--preset", "centre", "--out", str(tmp_path / "cli")])
    wav, _ = write_kick(load_preset("centre"), tmp_path / "direct", name="x")
    assert (tmp_path / "cli" / "centre_s1001_v0.wav").read_bytes() == wav.read_bytes()


def test_cli_runs_are_byte_identical(tmp_path) -> None:
    for d in ("a", "b"):
        assert run(["--preset", "driven", "--variants", "4", "--out", str(tmp_path / d)])[0] == 0
    for i in range(4):
        name = f"driven_s1005_v{i}.wav"
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_existing_files_are_never_overwritten(tmp_path) -> None:
    args = ["--preset", "dark-dry", "--variants", "2", "--out", str(tmp_path)]
    run(args)
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    code, out, _ = run(args)
    assert code == 0
    assert {p: p.read_bytes() for p in before} == before
    assert "dark-dry_s1002_v0_002.wav" in out and "dark-dry_s1002_v1_002.wav" in out
    assert len(list(tmp_path.iterdir())) == 8


def test_seed_and_set_change_name_and_values(tmp_path) -> None:
    code, _, err = run(["--preset", "centre", "--seed", "77", "--set", "pitch_decay_ms=15",
                        "--set", "bpm=128", "--variants", "2", "--out", str(tmp_path)])
    assert (code, err) == (0, "")
    assert tree(tmp_path) == sorted(
        f"centre_s77_v{i}_custom.{e}" for i in range(2) for e in ("json", "wav")
    )
    meta = json.loads((tmp_path / "centre_s77_v0_custom.json").read_text(encoding="utf-8"))
    assert meta["parameters"]["seed"] == 77
    assert meta["parameters"]["pitch_decay_ms"] == 15
    assert meta["bpm"] == 128
    assert "Custom values: pitch_decay_ms=15, bpm=128." in meta["description"]
    # --seed alone is not "custom": it is a new family of the same preset.
    run(["--preset", "centre", "--seed", "77", "--out", str(tmp_path / "s")])
    assert tree(tmp_path / "s") == ["centre_s77_v0.json", "centre_s77_v0.wav"]


def test_odd_length_24_bit_file_for_the_format_tag_question(tmp_path) -> None:
    """Listening-guide item: length 450.02 ms at 48 kHz = 21601 samples (odd 24-bit chunk)."""
    run(["--preset", "centre", "--set", "length_ms=450.02", "--out", str(tmp_path)])
    data = (tmp_path / "centre_s1001_v0_custom.wav").read_bytes()
    assert int.from_bytes(data[40:44], "little") == 21601 * 3
    assert len(data) == 44 + 21601 * 3 + 1  # RIFF pad byte


def test_python_dash_m_entry_point(tmp_path) -> None:
    """The documented command, as a subprocess, against this checkout's source."""
    src = str(Path(audio_engine.__file__).resolve().parents[1])
    env = {**os.environ, "PYTHONPATH": src}
    ok = subprocess.run(
        [sys.executable, "-m", "audio_engine.kick", "--preset", "punchy", "--out", str(tmp_path)],
        capture_output=True, text=True, env=env, check=False,
    )
    assert ok.returncode == 0, ok.stderr
    assert (tmp_path / "punchy_s1003_v0.wav").exists()
    bad = subprocess.run(
        [sys.executable, "-m", "audio_engine.kick", "--preset", "nope", "--out", str(tmp_path)],
        capture_output=True, text=True, env=env, check=False,
    )
    assert bad.returncode == 2 and "Valid presets" in bad.stderr


# --- errors before writing: exit 2, nothing written, folder not created ----------------------

BAD = [
    (["--preset", "hard-trance"], "Valid presets: centre, dark-dry, dense, driven, punchy"),
    (["--preset", "punchy", "--variants", "9"], "variants"),
    (["--preset", "punchy", "--variants", "0"], "variants"),
    (["--preset", "punchy", "--seed", "-1"], "seed"),
    (["--preset", "punchy", "--seed", str(2**32)], "seed"),
    (["--preset", "punchy", "--set", "drive=1.5"], "drive"),
    (["--preset", "punchy", "--set", "drive=NaN"], "must be a number"),
    (["--preset", "punchy", "--set", "drive=Infinity"], "must be a number"),
    (["--preset", "punchy", "--set", "drive=1e999"], "finite"),
    (["--preset", "punchy", "--set", "drive=abc"], "must be a number"),
    (["--preset", "punchy", "--set", "drive=true"], "must be a number"),
    (["--preset", "punchy", "--set", "drive"], "FIELD=VALUE"),
    (["--preset", "punchy", "--set", "=1"], "FIELD=VALUE"),
    (["--preset", "punchy", "--set", "wobble=1"], "wobble"),
    (["--preset", "punchy", "--set", "variants=3"], "use --variants"),
    (["--preset", "punchy", "--set", "seed=3"], "use --seed"),
    (["--preset", "punchy", "--set", "schema_version=0.1"], "cannot be set"),
    (["--preset", "punchy", "--set", "preset=x"], "cannot be set"),
    (["--preset", "punchy", "--set", "drive=0.1", "--set", "drive=0.2"], "more than once"),
    (["--preset", "punchy", "--set", "pitch_end_hz=120", "--set", "pitch_start_hz=100"],
     "pitch_end_hz must not be higher"),
    (["--preset", "punchy", "--set", "sample_rate=96000"], "sample_rate"),
    (["--variants", "2"], "--preset is required"),
]


@pytest.mark.parametrize(("extra", "fragment"), BAD)
def test_parameter_errors_exit_2_and_write_nothing(tmp_path, extra, fragment) -> None:
    out_dir = tmp_path / "new" / "nested"
    code, out, err = run([*extra, "--out", str(out_dir)])
    assert code == 2
    assert out == ""
    assert fragment in err
    assert not (tmp_path / "new").exists()


def test_missing_out_is_a_usage_error() -> None:
    code, _, err = run(["--preset", "punchy"])
    assert code == 2 and "--out is required" in err


@pytest.mark.parametrize("argv", [["--bogus"], ["--variants", "x"], ["--seed", "1.5"]])
def test_argparse_errors_exit_2(argv, tmp_path, capsys) -> None:
    code, out, _ = run([*argv, "--preset", "punchy", "--out", str(tmp_path / "x")])
    assert code == 2 and out == ""
    assert not (tmp_path / "x").exists()


def test_help_exits_0(capsys) -> None:
    assert run(["--help"])[0] == 0


def test_all_variants_are_validated_before_the_first_write(tmp_path, monkeypatch) -> None:
    """A variant that cannot be made (here: forced) stops the run before variant 0 is written."""
    import audio_engine.variants as variants_mod

    real = variants_mod.make_variant

    def fail_on_last(base, index):
        if index == 3:
            raise variants_mod.VariantError("forced")
        return real(base, index)

    monkeypatch.setattr(variants_mod, "make_variant", fail_on_last)
    code, out, err = run(["--preset", "punchy", "--variants", "4", "--out", str(tmp_path / "o")])
    assert code == 2 and out == "" and "forced" in err
    assert not (tmp_path / "o").exists()


# --- output errors: exit 3, earlier pairs stay, nothing half-written -------------------------


def test_out_is_a_file_exits_3(tmp_path) -> None:
    target = tmp_path / "file"
    target.write_text("keep", encoding="utf-8")
    code, out, err = run(["--preset", "punchy", "--out", str(target)])
    assert code == 3 and out == ""
    assert "variant 0" in err
    assert target.read_text(encoding="utf-8") == "keep"


def _fail_write(monkeypatch, at: int, exc: BaseException) -> list[int]:
    calls: list[int] = []
    real = write_kick

    def wrapped(params, out_dir, **kw):
        calls.append(1)
        if len(calls) == at:
            # Fail inside the real writer after its WAV is on disk, when it creates the sidecar
            # (as a full disk or Ctrl+C there would): the writer's own clean-up must remove
            # the WAV, so no half pair stays.
            import builtins

            real_open = builtins.open

            def bad_open(path, mode="r", *a, **k):
                if "x" in mode and str(path).endswith(".json"):
                    assert Path(str(path)).with_suffix(".wav").exists()
                    raise exc
                return real_open(path, mode, *a, **k)

            monkeypatch.setattr(builtins, "open", bad_open)
            try:
                return real(params, out_dir, **kw)
            finally:
                monkeypatch.setattr(builtins, "open", real_open)
        return real(params, out_dir, **kw)

    monkeypatch.setattr(cli, "write_kick", wrapped)
    return calls


def test_disk_full_on_third_variant_exits_3_and_keeps_earlier_pairs(tmp_path, monkeypatch) -> None:
    _fail_write(monkeypatch, 3, OSError(errno.ENOSPC, "No space left on device"))
    code, out, err = run(["--preset", "punchy", "--variants", "4", "--out", str(tmp_path)])
    assert code == 3
    assert "variant 2 (punchy_s1003_v2)" in err and "2 file pair(s) written" in err
    assert len(out.splitlines()) == 2
    assert tree(tmp_path) == sorted(
        f"punchy_s1003_v{i}.{e}" for i in range(2) for e in ("json", "wav")
    )


def test_ctrl_c_exits_130_and_leaves_no_half_pair(tmp_path, monkeypatch) -> None:
    _fail_write(monkeypatch, 2, KeyboardInterrupt())
    code, out, err = run(["--preset", "punchy", "--variants", "3", "--out", str(tmp_path)])
    assert code == 130 and "Interrupted" in err
    assert tree(tmp_path) == ["punchy_s1003_v0.json", "punchy_s1003_v0.wav"]


def test_no_free_name_exits_3(tmp_path, monkeypatch) -> None:
    import audio_engine.io as io_mod

    monkeypatch.setattr(io_mod, "_MAX_NAME_ATTEMPTS", 0)
    code, _, err = run(["--preset", "punchy", "--out", str(tmp_path)])
    assert code == 3 and "No free file name" in err


def test_unexpected_error_exits_1(tmp_path, monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "write_kick", boom)
    with pytest.raises(RuntimeError):
        run(["--preset", "punchy", "--out", str(tmp_path)])
    # Under ``python -m`` an uncaught exception prints a traceback and exits with 1.
    src = str(Path(audio_engine.__file__).resolve().parents[1])
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys, audio_engine.cli as c\n"
         "c.write_kick = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))\n"
         "sys.exit(c.main(['--preset', 'punchy', '--out', sys.argv[1]]))",
         str(tmp_path / "x")],
        capture_output=True, text=True, env={**os.environ, "PYTHONPATH": src}, check=False,
    )
    assert proc.returncode == 1 and "RuntimeError: boom" in proc.stderr
