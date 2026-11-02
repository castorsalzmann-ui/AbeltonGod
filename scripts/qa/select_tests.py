"""Targeted test selection (#278): changed files -> the test files that can see the change.

For early feedback while you work. **It never replaces the full gate** (`ruff check . && pytest`
on the merged state); the lead runs that before every merge go-ahead.

    python scripts/qa/select_tests.py                 # changes vs origin/main + working tree
    python scripts/qa/select_tests.py --base main src/audio_engine/dsp.py
    pytest $(python scripts/qa/select_tests.py)       # run the selection

How it decides (static, no test is run):

- A changed test file selects itself. A changed ``tests/<dir>/helper.py`` selects every test file
  in that directory.
- A changed ``src/<pkg>/<mod>.py`` selects every test file that imports it, or any ``src``
  module that (transitively) imports it, or the package ``__init__``/re-export. Imports are read
  with ``ast``; a test's imports include ``from pkg import mod`` and ``import pkg.mod``.
- Any other changed file (``scripts/``, ``contracts/``, ``config/``) selects the test files whose
  text names its path or its file name. Docs-only changes select nothing.
- ``tests/conftest.py``, ``tests/support/``, ``pyproject.toml``, ``.github/`` and
  ``contracts/*.json`` can affect everything or cannot be traced: the output then is the whole
  ``tests`` folder and a note on stderr says why.

Output: one test path per line on stdout (empty = nothing to run), notes on stderr.
Exit code 0 always, unless git fails (2).
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_PKGS = ("audio_engine", "bridge", "orchestrator", "guard", "library")
FULL_TRIGGERS = ("tests/conftest.py", "tests/support/", "pyproject.toml", ".github/")


def changed_files(base: str) -> list[str]:
    """Files changed since the merge base with ``base`` plus uncommitted and untracked files."""
    def git(*args: str) -> list[str]:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
        return [ln for ln in out.splitlines() if ln]

    files = set(git("diff", "--name-only", f"{base}...HEAD"))
    files |= set(git("diff", "--name-only", "HEAD"))
    files |= set(git("ls-files", "--others", "--exclude-standard"))
    return sorted(files)


def _imports(path: Path, package: str = "") -> set[str]:
    """Dotted module names a file imports (``from a import b`` counts as ``a`` and ``a.b``).
    ``package`` is the file's own package, to resolve relative imports (``from .io import x``)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join(p for p in (*up, node.module) if p)
            if base:
                found.add(base)
                found.update(f"{base}.{a.name}" for a in node.names)
    return found


def _module_name(rel: str) -> str | None:
    parts = Path(rel).with_suffix("").parts
    if len(parts) < 3 or parts[0] != "src":
        return None
    parts = parts[1:]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _src_graph(root: Path) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for path in (root / "src").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        name = _module_name(rel)
        if name:
            pkg = name if path.name == "__init__.py" else name.rpartition(".")[0]
            graph[name] = _imports(path, pkg)
    return graph


def _dependents(changed: set[str], graph: dict[str, set[str]]) -> set[str]:
    """``changed`` plus every src module that imports one of them, transitively. A package
    ``__init__`` re-exports, so importing ``pkg`` counts as importing every module below it."""
    result = set(changed)
    for mod in changed:  # a changed package __init__ may change what every module below exports
        if any(g.startswith(mod + ".") for g in graph) and (ROOT / "src").exists():
            result.update(g for g in graph if g.startswith(mod + "."))
    grew = True
    while grew:
        grew = False
        for mod, imports in graph.items():
            if mod not in result and imports & result:
                result.add(mod)
                grew = True
    return result


def select(files: list[str], root: Path = ROOT) -> tuple[list[str], list[str]]:
    """Return (test paths, notes). Paths are relative to ``root``, sorted, without duplicates."""
    notes: list[str] = []
    tests = sorted(p.relative_to(root).as_posix() for p in (root / "tests").rglob("test_*.py"))
    for f in files:
        if f.startswith(FULL_TRIGGERS) or (f.startswith("contracts/") and f.endswith(".json")):
            notes.append(f"{f} can affect every test: whole tests/ folder")
            return ["tests"], notes
    chosen: set[str] = set()
    graph = _src_graph(root)
    test_imports = {t: _imports(root / t) for t in tests}
    texts: dict[str, str] = {}

    def text(t: str) -> str:
        if t not in texts:
            texts[t] = (root / t).read_text(encoding="utf-8", errors="replace")
        return texts[t]

    changed_src: set[str] = set()
    for f in files:
        p = Path(f)
        if not f.endswith(".py") and not f.startswith(("scripts/", "contracts/", "config/")):
            continue  # docs and the like
        if f.startswith("tests/"):
            if p.name.startswith("test_") and p.suffix == ".py":
                chosen.add(f)
            else:  # helper, fixture data or conftest below tests/: its folder
                chosen.update(t for t in tests if t.startswith(f"{p.parent.as_posix()}/"))
            continue
        mod = _module_name(f)
        if mod:
            changed_src.add(mod)
            continue
        hits = {t for t in tests if f in text(t) or p.name in text(t)}
        if not hits:
            notes.append(f"{f}: no test names this file")
        chosen |= hits
    if changed_src:
        affected = _dependents(changed_src, graph)
        for t, imps in test_imports.items():
            if imps & affected:
                chosen.add(t)
        for m in sorted(changed_src):
            if not any(test_imports[t] & affected for t in tests):
                notes.append(f"{m}: no test imports it (directly or via another module)")
    return sorted(chosen), notes


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base", default="origin/main", help="merge base ref (default origin/main)")
    ap.add_argument("files", nargs="*", help="changed files (default: ask git)")
    args = ap.parse_args(argv)
    try:
        files = args.files or changed_files(args.base)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"git failed: {exc}", file=sys.stderr)
        return 2
    paths, notes = select(files)
    for n in notes:
        print(f"note: {n}", file=sys.stderr)
    print(
        "note: targeted selection for early feedback only; the full gate stays "
        "`ruff check . && pytest`",
        file=sys.stderr,
    )
    print("\n".join(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
