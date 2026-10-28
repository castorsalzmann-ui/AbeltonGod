"""Mutation runner: apply one text mutant to a copy of the repo and run a test subset (#73).

Each mutant replaces one exact ``old`` string by ``new`` in one file. ``old`` must occur
exactly once in that file, otherwise the mutant is refused before anything runs.

For every mutant the runner

1. copies the tree into a fresh temporary directory (the working tree, including uncommitted
   and untracked-but-not-ignored files, or ``git archive <rev>`` with ``--rev``),
2. applies the mutant to the copy,
3. checks that the mutated module is imported from the copy, not from an installed package,
4. runs ``python -m pytest -o pythonpath=src -p no:cacheprovider <tests>`` in a new process
   with the copy as working directory,
5. reports *killed* (pytest exit 1: tests failed) or *survived* (exit 0).

Before the mutants, each distinct test subset is run once on an unmutated copy (the
baseline). A subset that is already red cannot kill anything, so its mutants are reported as
errors. The working tree itself is only read, never written.

    python scripts/qa/mutate.py tests/qa/mutants/pr40_round1.json
    python scripts/qa/mutate.py --rev dd86430 tests/qa/mutants/pr40_round1.json
    python scripts/qa/mutate.py --only M1 tests/qa/mutants/*.json

Mutant file format (``tests/qa/mutants/*.json``)::

    {"mutants": [{"id": "TONE_PIVOT_HZ",            # unique across the run
                  "file": "src/audio_engine/kick.py", # relative to the repo root
                  "old": "TONE_PIVOT_HZ = 1500.0",    # must occur exactly once
                  "new": "TONE_PIVOT_HZ = 1530.0",
                  "tests": ["tests/audio_engine/test_engine_version.py"],
                  "pytest_args": ["-k", "golden"],    # optional
                  "expected": "killed",               # optional: killed | survived
                  "note": "PR #40 round 1"}]}         # optional

Exit codes: 0 every mutant killed · 1 at least one survived · 2 invalid mutant definition or
arguments, including a target file that is not in the copied tree (nothing was run) · 3 a
baseline was red, a run errored or timed out, imports did not come from the copy, the run was
interrupted (Ctrl+C) or the runner itself failed (results are not usable).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

KILLED = "killed"
SURVIVED = "survived"
ERROR = "error"

EXIT_ALL_KILLED = 0
EXIT_SURVIVORS = 1
EXIT_INVALID = 2
EXIT_ERROR = 3

_REQUIRED = {"id": str, "file": str, "old": str, "new": str, "tests": list}
_OPTIONAL = {"pytest_args": list, "expected": str, "note": str}
_SUMMARY = re.compile(r"\b\d+ (passed|failed|error|errors|skipped|deselected)\b|no tests ran")


class MutantError(ValueError):
    """A mutant definition is invalid or cannot be applied."""


@dataclass(frozen=True)
class Mutant:
    id: str
    file: str
    old: str
    new: str
    tests: tuple[str, ...]
    pytest_args: tuple[str, ...] = ()
    expected: str | None = None
    note: str = ""
    source: str = ""


@dataclass
class Result:
    mutant: Mutant
    status: str
    detail: str
    failed: list[str] = field(default_factory=list)


def load_mutants(paths: list[Path]) -> list[Mutant]:
    mutants: list[Mutant] = []
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MutantError(f"{path}: cannot read mutant file: {exc}") from exc
        if not isinstance(doc, dict) or not isinstance(doc.get("mutants"), list):
            raise MutantError(f'{path}: expected an object with a "mutants" list')
        for i, raw in enumerate(doc["mutants"]):
            mutants.append(_parse_mutant(raw, f"{path}#{i}"))
    seen: set[str] = set()
    for m in mutants:
        if m.id in seen:
            raise MutantError(f"duplicate mutant id {m.id!r}")
        seen.add(m.id)
    return mutants


def _parse_mutant(raw: object, where: str) -> Mutant:
    if not isinstance(raw, dict):
        raise MutantError(f"{where}: a mutant must be an object")
    unknown = set(raw) - set(_REQUIRED) - set(_OPTIONAL)
    if unknown:
        raise MutantError(f"{where}: unknown keys {sorted(unknown)}")
    for key, typ in _REQUIRED.items():
        if not isinstance(raw.get(key), typ):
            raise MutantError(f"{where}: {key!r} is required and must be a {typ.__name__}")
    for key, typ in _OPTIONAL.items():
        if key in raw and not isinstance(raw[key], typ):
            raise MutantError(f"{where}: {key!r} must be a {typ.__name__}")
    if not raw["old"]:
        raise MutantError(f"{where}: 'old' must not be empty")
    if raw["old"] == raw["new"]:
        raise MutantError(f"{where}: 'old' and 'new' are identical")
    if not raw["tests"] or not all(isinstance(t, str) and t for t in raw["tests"]):
        raise MutantError(f"{where}: 'tests' must be a non-empty list of paths")
    if not all(isinstance(a, str) for a in raw.get("pytest_args", [])):
        raise MutantError(f"{where}: 'pytest_args' must be a list of strings")
    if raw.get("expected") not in (None, KILLED, SURVIVED):
        raise MutantError(f"{where}: 'expected' must be {KILLED!r} or {SURVIVED!r}")
    _check_relative(raw["file"], where)
    for t in raw["tests"]:
        _check_relative(t.split("::")[0], where)
    return Mutant(
        id=raw["id"],
        file=raw["file"],
        old=raw["old"],
        new=raw["new"],
        tests=tuple(raw["tests"]),
        pytest_args=tuple(raw.get("pytest_args", [])),
        expected=raw.get("expected"),
        note=raw.get("note", ""),
        source=where,
    )


def _check_relative(rel: str, where: str) -> None:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or rel.startswith(("/", "\\")):
        raise MutantError(f"{where}: path {rel!r} must be relative to the repo root")


def apply_mutant(text: str, mutant: Mutant) -> str:
    """Return ``text`` with the single occurrence of ``mutant.old`` replaced."""
    count = text.count(mutant.old)
    if count != 1:
        raise MutantError(
            f"{mutant.id}: 'old' occurs {count} times in {mutant.file}, it must occur exactly once"
        )
    return text.replace(mutant.old, mutant.new, 1)


def _git(root: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )
    if proc.returncode != 0:
        raise MutantError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace')}")
    return proc.stdout


def read_source(root: Path, rev: str | None, rel: str) -> str:
    """Read one file from the working tree or from ``rev`` (without copying everything)."""
    if rev is None:
        path = root / rel
        if not path.is_file():
            raise MutantError(f"{rel}: no such file in {root}")
        return path.read_text(encoding="utf-8")
    try:
        return _git(root, "show", f"{rev}:{rel}").decode("utf-8")
    except MutantError as exc:
        raise MutantError(f"{rel}: not readable at {rev}: {exc}") from exc


def tree_files(root: Path, rev: str | None) -> set[str]:
    """Relative paths of the files :func:`copy_tree` copies (posix separators)."""
    if rev is not None:
        listing = _git(root, "ls-tree", "-r", "-z", "--name-only", rev)
        return {r for r in listing.decode("utf-8").split("\0") if r}
    listing = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return {
        r
        for r in listing.decode("utf-8").split("\0")
        if r and not r.endswith("/") and (root / r).is_file()  # nested repo or deleted file
    }


def check_target(files: set[str], mutant: Mutant) -> None:
    """Refuse a mutant whose file would not exist in the copy (e.g. git-ignored)."""
    if Path(mutant.file).as_posix() not in files:
        raise MutantError(
            f"{mutant.id}: {mutant.file} is not in the copied tree "
            "(git-ignored, untracked-and-ignored, or not in the revision)"
        )


def copy_tree(root: Path, rev: str | None, dest: Path) -> None:
    """Copy the repo into ``dest``: working tree (tracked + untracked, not ignored) or ``rev``."""
    if rev is not None:
        data = _git(root, "archive", "--format=tar", rev)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            if hasattr(tarfile, "data_filter"):
                tar.extractall(dest, filter="data")
            else:  # pragma: no cover - Python < 3.11.4
                tar.extractall(dest)  # noqa: S202 - our own git archive
        return
    for rel in sorted(tree_files(root, None)):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, target)


def _child_env(copy: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("PYTEST_XDIST", "PYTEST_CURRENT_TEST")) and k != "PYTHONPATH"
    }
    env["PYTHONPATH"] = str(copy / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _module_name(rel: str) -> str | None:
    parts = Path(rel).parts
    if len(parts) < 2 or parts[0] != "src" or not rel.endswith(".py"):
        return None
    names = list(parts[1:])
    names[-1] = names[-1][: -len(".py")]
    if names[-1] == "__init__":
        names.pop()
    return ".".join(names) or None


def check_import_origin(copy: Path, rel: str, timeout: float) -> str | None:
    """Return an error message if the module of ``rel`` would not be imported from ``copy``."""
    module = _module_name(rel)
    if module is None:
        return None
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.find_spec({module!r})\n"
        "print(spec.origin if spec else '')\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=copy,
            env=_child_env(copy),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"import check for {module} timed out after {timeout:g} s"
    origin = proc.stdout.strip()
    expected = (copy / rel).resolve()
    if proc.returncode != 0 or not origin or Path(origin).resolve() != expected:
        return f"{module} imports from {origin or proc.stderr.strip()!r}, not from the copy"
    return None


def run_pytest(copy: Path, tests: tuple[str, ...], extra: tuple[str, ...], timeout: float):
    cmd = [
        sys.executable, "-m", "pytest", "-o", "pythonpath=src", "-p", "no:cacheprovider",
        *extra, *tests,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=copy,
            env=_child_env(copy),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout:g} s", []
    out = proc.stdout + proc.stderr
    return proc.returncode, _summary(out), _failed_ids(out)


def _summary(output: str) -> str:
    for line in reversed(output.splitlines()):
        line = line.strip().strip("=").strip()
        if _SUMMARY.search(line):
            return line
    tail = [ln for ln in output.splitlines() if ln.strip()]
    return tail[-1].strip() if tail else "(no output)"


def _failed_ids(output: str) -> list[str]:
    ids = []
    for line in output.splitlines():
        if line.startswith(("FAILED ", "ERROR ")):
            ids.append(line.split(" ", 1)[1].split(" - ", 1)[0].strip())
    return ids


def classify(code: int | None) -> str:
    if code == 0:
        return SURVIVED
    if code == 1:
        return KILLED
    return ERROR


def run(
    mutants: list[Mutant],
    root: Path,
    rev: str | None = None,
    timeout: float = 900.0,
    baseline: bool = True,
    log=None,
) -> list[Result]:
    """Run every mutant. Raises :class:`MutantError` before running anything if one is invalid."""
    log = log or (lambda msg: print(msg, file=sys.stderr, flush=True))
    mutated: dict[str, str] = {}
    files = tree_files(root, rev)
    for m in mutants:  # validate all mutants first: nothing runs if one is invalid
        check_target(files, m)
        mutated[m.id] = apply_mutant(read_source(root, rev, m.file), m)

    red_baselines: dict[tuple, str] = {}
    if baseline:
        for key in dict.fromkeys((m.tests, m.pytest_args) for m in mutants):
            with tempfile.TemporaryDirectory(prefix="mutate-base-") as tmp:
                copy = Path(tmp)
                copy_tree(root, rev, copy)
                log(f"baseline: {' '.join(key[1] + key[0])}")
                code, summary, _ = run_pytest(copy, key[0], key[1], timeout)
                if code != 0:
                    red_baselines[key] = f"baseline not green ({summary})"

    results: list[Result] = []
    for m in mutants:
        red = red_baselines.get((m.tests, m.pytest_args))
        if red:
            results.append(Result(m, ERROR, red))
            continue
        with tempfile.TemporaryDirectory(prefix="mutate-") as tmp:
            copy = Path(tmp)
            copy_tree(root, rev, copy)
            target = copy / m.file
            target.write_text(mutated[m.id], encoding="utf-8", newline="")
            origin_error = check_import_origin(copy, m.file, timeout)
            if origin_error:
                results.append(Result(m, ERROR, origin_error))
                continue
            log(f"mutant {m.id}: {' '.join(m.pytest_args + m.tests)}")
            code, summary, failed = run_pytest(copy, m.tests, m.pytest_args, timeout)
            status = classify(code)
            if status == ERROR and code is not None:
                summary = f"pytest exit {code}: {summary}"
            results.append(Result(m, status, summary, failed))
    return results


def exit_code(results: list[Result]) -> int:
    statuses = {r.status for r in results}
    if ERROR in statuses:
        return EXIT_ERROR
    if SURVIVED in statuses:
        return EXIT_SURVIVORS
    return EXIT_ALL_KILLED


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_table(results: list[Result], rev: str | None, max_failed: int = 3) -> str:
    where = f"`{rev}`" if rev else "working tree"
    lines = [
        f"Source: {where}",
        "",
        "| Mutant | File | Tests | Result | pytest | Expected |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        detail = r.detail
        if r.failed:
            shown = ", ".join(f"`{f}`" for f in r.failed[:max_failed])
            more = f" (+{len(r.failed) - max_failed} more)" if len(r.failed) > max_failed else ""
            detail = f"{detail}: {shown}{more}"
        if r.mutant.expected is None:
            expected = ""
        elif r.mutant.expected == r.status:
            expected = f"{r.mutant.expected} (matches)"
        else:
            expected = f"{r.mutant.expected} (**differs**)"
        tests = " ".join(r.mutant.pytest_args + r.mutant.tests)
        lines.append(
            f"| `{_cell(r.mutant.id)}` | `{_cell(r.mutant.file)}` | `{_cell(tests)}` "
            f"| **{r.status}** | {_cell(detail)} | {expected} |"
        )
    killed = sum(r.status == KILLED for r in results)
    survived = sum(r.status == SURVIVED for r in results)
    errors = sum(r.status == ERROR for r in results)
    lines += ["", f"{killed} killed, {survived} survived, {errors} error(s) of {len(results)}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="+", type=Path, help="mutant JSON files")
    parser.add_argument("--rev", help="run against this git revision instead of the working tree")
    parser.add_argument("--only", action="append", default=[], help="run only this mutant id")
    parser.add_argument("--root", type=Path, default=ROOT, help="repo root (default: this repo)")
    parser.add_argument("--timeout", type=float, default=900.0, help="seconds per pytest run")
    parser.add_argument(
        "--no-baseline", action="store_true", help="skip the unmutated baseline run"
    )
    args = parser.parse_args(argv)
    try:
        mutants = load_mutants(args.files)
        if args.only:
            missing = set(args.only) - {m.id for m in mutants}
            if missing:
                raise MutantError(f"--only: unknown mutant id(s) {sorted(missing)}")
            mutants = [m for m in mutants if m.id in args.only]
        if not mutants:
            raise MutantError("no mutants to run")
        results = run(
            mutants,
            args.root.resolve(),
            rev=args.rev,
            timeout=args.timeout,
            baseline=not args.no_baseline,
        )
        table = render_table(results, args.rev)
    except MutantError as exc:
        print(f"mutate: {exc}", file=sys.stderr)
        return EXIT_INVALID
    except KeyboardInterrupt:
        # subprocess.run kills the running pytest child; temp copies are removed on unwind.
        print("mutate: interrupted, results incomplete", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - any crash must not look like "survived" (exit 1)
        print(f"mutate: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(table)
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
