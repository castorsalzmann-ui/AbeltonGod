"""Static check for the ``from conftest import`` name trap (#86).

The test tree has no ``__init__.py`` files, so pytest (default ``prepend`` import mode) imports
every ``conftest.py`` under the plain module name ``conftest`` and drops the previous
``sys.modules["conftest"]`` entry first. A test file that does ``from conftest import X`` gets
whichever ``conftest.py`` was loaded last, which depends on the collection order and on the
paths given on the command line. A second sub-folder ``conftest.py`` (seen on the #78 branch
with ``tests/orchestrator/conftest.py``) made the bridge tests fail with
``ImportError: cannot import name 'registry_with' from 'conftest'``.

``find_conftest_name_traps(tests_root)`` returns one line per problem; an empty list means the
tree is safe. While any test file imports from ``conftest``, the only ``conftest.py`` files
allowed are ``<tests_root>/conftest.py`` (always loaded first) and the one next to the
importing files, and all importers must sit in that one folder. Without importers any number
of ``conftest.py`` files is fine. The fix for a finding is to move the shared helpers into a
uniquely named module (example: ``tests/orchestrator/orch_helpers.py``).
"""

from __future__ import annotations

import ast
from pathlib import Path


def conftest_importers(tests_root: Path) -> dict[Path, list[int]]:
    """Files under ``tests_root`` that import the module ``conftest``, with the line numbers."""
    found: dict[Path, list[int]] = {}
    for path in sorted(tests_root.rglob("*.py")):
        if path.name == "conftest.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "conftest":
                lines.append(node.lineno)
            elif isinstance(node, ast.Import) and any(a.name == "conftest" for a in node.names):
                lines.append(node.lineno)
        if lines:
            found[path] = sorted(lines)
    return found


def find_conftest_name_traps(tests_root: Path) -> list[str]:
    tests_root = tests_root.resolve()
    importers = conftest_importers(tests_root)
    if not importers:
        return []

    def rel(p: Path) -> str:
        return p.relative_to(tests_root).as_posix()

    problems: list[str] = []
    importer_dirs = sorted({p.parent for p in importers})
    if len(importer_dirs) > 1:
        problems.append(
            "`from conftest import` is used in more than one folder: "
            + ", ".join(rel(d) or "." for d in importer_dirs)
        )
    allowed = {tests_root / "conftest.py"} | {d / "conftest.py" for d in importer_dirs}
    for d in importer_dirs:
        if d == tests_root:
            problems.append(
                ".: imports from the root `conftest`, which any sub-folder conftest.py replaces"
            )
        elif not (d / "conftest.py").is_file():
            problems.append(f"{rel(d)}: imports from `conftest` without its own conftest.py")
    users = ", ".join(f"{rel(p)}:{n}" for p, ns in importers.items() for n in ns)
    for conftest in sorted(tests_root.rglob("conftest.py")):
        if conftest not in allowed:
            problems.append(
                f"{rel(conftest)} replaces sys.modules['conftest'] for {users}; move shared "
                "helpers into a uniquely named module instead"
            )
    return problems
