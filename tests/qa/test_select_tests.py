"""scripts/qa/select_tests.py (#278): changed files -> test files, on a small synthetic repo."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "qa"))
import select_tests as st  # noqa: E402

FILES = {
    "src/pkg/__init__.py": "",
    "src/pkg/low.py": "X = 1\n",
    "src/pkg/mid.py": "from .low import X\n",
    "src/pkg/top.py": "from pkg import mid\n",
    "src/pkg/alone.py": "Y = 2\n",
    "src/other/__init__.py": "from .thing import T\n",
    "src/other/thing.py": "T = 3\n",
    "tests/pkg/test_low.py": "from pkg.low import X\n",
    "tests/pkg/test_top.py": "import pkg.top\n",
    "tests/pkg/test_alone.py": "from pkg import alone\n",
    "tests/pkg/helper.py": "H = 1\n",
    "tests/other/test_thing.py": "from other import T\n",
    "tests/bridge/test_script.py": "RUN = 'scripts/tool.py'\n",
    "scripts/tool.py": "",
    "scripts/unused.py": "",
    "docs/x.md": "text",
    "contracts/s.json": "{}",
}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    for rel, body in FILES.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return tmp_path


def sel(repo: Path, *files: str) -> list[str]:
    return st.select(list(files), root=repo)[0]


def test_change_reaches_tests_through_a_chain_of_importers(repo: Path) -> None:
    # low <- mid (relative import) <- top (from pkg import mid) <- tests/pkg/test_top.py
    assert sel(repo, "src/pkg/low.py") == ["tests/pkg/test_low.py", "tests/pkg/test_top.py"]


def test_leaf_importer_selects_only_what_sees_it(repo: Path) -> None:
    assert sel(repo, "src/pkg/top.py") == ["tests/pkg/test_top.py"]
    assert sel(repo, "src/pkg/alone.py") == ["tests/pkg/test_alone.py"]


def test_changed_package_init_selects_tests_of_every_module_below(repo: Path) -> None:
    assert sel(repo, "src/other/__init__.py") == ["tests/other/test_thing.py"]
    assert sel(repo, "src/pkg/__init__.py") == [
        "tests/pkg/test_alone.py", "tests/pkg/test_low.py", "tests/pkg/test_top.py"]


def test_changed_test_and_test_helper(repo: Path) -> None:
    assert sel(repo, "tests/pkg/test_low.py") == ["tests/pkg/test_low.py"]
    assert sel(repo, "tests/pkg/helper.py") == [
        "tests/pkg/test_alone.py", "tests/pkg/test_low.py", "tests/pkg/test_top.py"]


def test_other_files_select_tests_that_name_them(repo: Path) -> None:
    assert sel(repo, "scripts/tool.py") == ["tests/bridge/test_script.py"]
    paths, notes = st.select(["scripts/unused.py"], root=repo)
    assert paths == [] and "no test names this file" in notes[0]


def test_docs_select_nothing(repo: Path) -> None:
    assert sel(repo, "docs/x.md") == []


@pytest.mark.parametrize(
    "file", ["tests/conftest.py", "tests/support/render_cache.py", "pyproject.toml",
             "contracts/s.json", ".github/workflows/ci.yml"])
def test_untraceable_changes_select_the_whole_tests_folder(repo: Path, file: str) -> None:
    paths, notes = st.select(["src/pkg/alone.py", file], root=repo)
    assert paths == ["tests"] and file in notes[0]


def test_real_repo_selection_for_a_known_module() -> None:
    paths, _ = st.select(["scripts/qa/mutate.py"])
    assert "tests/qa/test_mutate.py" in paths
    paths, _ = st.select(["src/audio_engine/dsp.py"])
    assert "tests/audio_engine/test_dsp_blocks.py" in paths
    assert "tests/audio_engine/test_kick.py" in paths  # via kick.py importing dsp
