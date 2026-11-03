"""Bug #314: preset sub-folders (clap/, hat/, ...) were missing from non-editable installs.

``package-data`` only listed ``*.json`` for ``audio_engine.presets``, so setuptools left the
sub-folder presets out of the built package. This test runs setuptools' own ``build_py`` step
on the repo's ``pyproject.toml`` (in-process, into a temp folder, no network) and checks that
every ``*.json`` under ``src/audio_engine/presets`` at any depth is in the build output.
"""

from __future__ import annotations

import os
from pathlib import Path

from setuptools import Distribution
from setuptools.config.pyprojecttoml import apply_configuration

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "src" / "audio_engine" / "presets"


def test_all_preset_json_files_are_built(tmp_path):
    cwd = os.getcwd()
    os.chdir(REPO)
    try:
        dist = apply_configuration(
            Distribution({"script_name": "setup.py"}), REPO / "pyproject.toml"
        )
        dist.script_args = ["build_py", "--build-lib", str(tmp_path)]
        dist.parse_command_line()
        dist.run_commands()
    finally:
        os.chdir(cwd)
    built = {p.relative_to(tmp_path / "audio_engine" / "presets").as_posix()
             for p in (tmp_path / "audio_engine" / "presets").rglob("*.json")}
    source = {p.relative_to(PRESETS).as_posix() for p in PRESETS.rglob("*.json")}
    assert any("/" in name for name in source), "expected preset sub-folders in the source tree"
    assert source - built == set(), f"missing from the built package: {sorted(source - built)}"
