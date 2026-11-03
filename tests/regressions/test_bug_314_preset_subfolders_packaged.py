"""Bug #314: preset sub-folders (clap/, hat/, ...) were missing from non-editable installs.

``package-data`` only listed ``*.json`` for ``audio_engine.presets``, so setuptools left the
sub-folder presets out of the built package. This test runs setuptools' own ``build_py`` step
on the repo's ``pyproject.toml`` (in-process, into a temp folder, no network) and checks that
every ``*.json`` under ``src/audio_engine/presets`` at any depth is in the build output.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from setuptools import Distribution
from setuptools.config.pyprojecttoml import apply_configuration

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "src" / "audio_engine" / "presets"


def test_all_preset_json_files_are_built(tmp_path):
    # Build from a clean copy of pyproject.toml + src: a stale, git-ignored
    # src/abeltongod.egg-info (its SOURCES.txt lists files) must not influence the result.
    proj = tmp_path / "proj"
    proj.mkdir()
    shutil.copy(REPO / "pyproject.toml", proj / "pyproject.toml")
    if (REPO / "README.md").exists():
        shutil.copy(REPO / "README.md", proj / "README.md")
    shutil.copytree(
        REPO / "src", proj / "src",
        ignore=shutil.ignore_patterns("*.egg-info", "__pycache__"),
    )
    tmp_path = tmp_path / "build"
    cwd = os.getcwd()
    os.chdir(proj)
    try:
        dist = apply_configuration(
            Distribution({"script_name": "setup.py"}), proj / "pyproject.toml"
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
