"""Guard against the ``from conftest import`` name trap (#86, checker in tests/support/).

``test_repo_tests_tree_has_no_conftest_name_trap`` is the guard on the real tree. The other
tests pin the checker on small synthetic trees, and ``test_trap_is_real_in_pytest`` runs real
pytest on the #78 layout, so the checker's premise is measured, not assumed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from support.conftest_names import conftest_importers, find_conftest_name_traps

TESTS_ROOT = Path(__file__).resolve().parent.parent

HELPER_CONFTEST = "def helper():\n    return 42\n"
FUNCTION_LEVEL_IMPORT = (
    "def test_uses_helper():\n    from conftest import helper\n\n    assert helper() == 42\n"
)


def build(root: Path, files: dict[str, str]) -> Path:
    tests = root / "tests"
    for rel, text in files.items():
        path = tests / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tests


# The shape of the #78 branch: bridge-like folder `a` imports from its conftest inside a test
# function, and a later folder `z` adds its own conftest.py.
TRAP = {
    "conftest.py": "",
    "a/conftest.py": HELPER_CONFTEST,
    "a/test_a.py": FUNCTION_LEVEL_IMPORT,
    "z/conftest.py": "",
    "z/test_z.py": "def test_z():\n    pass\n",
}


def test_repo_tests_tree_has_no_conftest_name_trap():
    assert find_conftest_name_traps(TESTS_ROOT) == []


def test_flags_a_second_subfolder_conftest(tmp_path):
    problems = find_conftest_name_traps(build(tmp_path, TRAP))
    assert len(problems) == 1
    assert problems[0].startswith(
        "z/conftest.py replaces sys.modules['conftest'] for a/test_a.py:2;"
    )


def test_importers_are_found_at_module_and_function_level(tmp_path):
    tests = build(tmp_path, {
        "a/test_m.py": "import os\nfrom conftest import helper\n",
        "a/test_f.py": FUNCTION_LEVEL_IMPORT,
        "a/test_i.py": "def f():\n    import conftest\n",
        "a/test_rel.py": "from .conftest import helper\nfrom conftest_x import y\n",
    })
    found = {p.name: lines for p, lines in conftest_importers(tests).items()}
    assert found == {"test_m.py": [2], "test_f.py": [2], "test_i.py": [2]}


@pytest.mark.parametrize("files, expected", [
    pytest.param(
        {"a/conftest.py": HELPER_CONFTEST, "a/test_a.py": FUNCTION_LEVEL_IMPORT,
         "b/conftest.py": HELPER_CONFTEST, "b/test_b.py": FUNCTION_LEVEL_IMPORT},
        ["`from conftest import` is used in more than one folder: a, b"],
        id="importers-in-two-folders"),
    pytest.param(
        {"conftest.py": "", "a/test_a.py": FUNCTION_LEVEL_IMPORT},
        ["a: imports from `conftest` without its own conftest.py"],
        id="importer-without-sibling-conftest"),
    pytest.param(
        {"conftest.py": HELPER_CONFTEST, "test_root.py": FUNCTION_LEVEL_IMPORT},
        [".: imports from the root `conftest`, which any sub-folder conftest.py replaces"],
        id="importer-at-root"),
])
def test_flags_other_unsafe_layouts(tmp_path, files, expected):
    assert find_conftest_name_traps(build(tmp_path, files)) == expected


@pytest.mark.parametrize("files", [
    pytest.param({"conftest.py": "", "a/conftest.py": "", "z/conftest.py": "",
                  "a/a_helpers.py": HELPER_CONFTEST,
                  "a/test_a.py": "from a_helpers import helper\n"}, id="uniquely-named-helpers"),
    pytest.param({"conftest.py": "", "a/conftest.py": HELPER_CONFTEST,
                  "a/test_a.py": FUNCTION_LEVEL_IMPORT}, id="root-plus-one-importer-folder"),
])
def test_safe_layouts_pass(tmp_path, files):
    assert find_conftest_name_traps(build(tmp_path, files)) == []


def run_pytest(root: Path) -> subprocess.CompletedProcess[str]:
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:xdist", "-p", "no:cacheprovider",
         "-c", str(root / "pytest.ini"), "--rootdir", str(root)],
        cwd=root, env=env, capture_output=True, text=True, timeout=120,
    )


def test_trap_is_real_in_pytest(tmp_path):
    trapped = tmp_path / "trapped"
    build(trapped, TRAP)
    red = run_pytest(trapped)
    assert red.returncode == 1, red.stdout + red.stderr
    assert "cannot import name 'helper' from 'conftest'" in red.stdout

    safe = tmp_path / "safe"
    build(safe, {k: v for k, v in TRAP.items() if k != "z/conftest.py"})
    green = run_pytest(safe)
    assert green.returncode == 0, green.stdout + green.stderr
    assert "2 passed" in green.stdout
