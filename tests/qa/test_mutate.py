"""Tests for the mutation runner ``scripts/qa/mutate.py`` (#73).

The runner is exercised on a tiny throwaway git repo (one module, one test), so each run takes
about a second. The mutant files in ``tests/qa/mutants/`` are checked against this repo.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "qa" / "mutate.py"
MUTANT_DIR = ROOT / "tests" / "qa" / "mutants"

_spec = importlib.util.spec_from_file_location("qa_mutate", SCRIPT)
mutate = importlib.util.module_from_spec(_spec)
sys.modules["qa_mutate"] = mutate  # dataclasses need the module registered
_spec.loader.exec_module(mutate)

MODULE = 'VALUE = 1\nOTHER = 1\nNAME = "x"\n'
TEST = (
    "from pkg.mod import NAME, OTHER, VALUE\n\n\n"
    "def test_value():\n    assert VALUE == 1\n\n\n"
    "def test_name():\n    assert NAME == 'x'\n"
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=qa", "-c", "user.email=qa@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "src" / "pkg").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (r / "src" / "pkg" / "mod.py").write_text(MODULE, encoding="utf-8")
    (r / "tests" / "test_mod.py").write_text(TEST, encoding="utf-8")
    (r / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r


def _mutant(**kw) -> dict:
    base = {"id": "m", "file": "src/pkg/mod.py", "old": "VALUE = 1", "new": "VALUE = 2",
            "tests": ["tests/test_mod.py"]}
    base.update(kw)
    return base


def _write(tmp_path: Path, *mutants: dict, name: str = "m.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"mutants": list(mutants)}), encoding="utf-8")
    return p


def _cli(repo: Path, *args: str | Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(repo), *map(str, args)],
        capture_output=True, text=True, timeout=300, env=env, check=False,
    )


def _snapshot(path: Path) -> dict[str, tuple[str, int]]:
    """Content hash and mtime of every file below ``path``, including .git."""
    return {
        str(p.relative_to(path)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


# --- unique "old" ------------------------------------------------------------------------


def test_refuses_non_unique_old(repo: Path, tmp_path: Path) -> None:
    # "= 1\n" occurs twice (VALUE and OTHER).
    spec = _write(tmp_path, _mutant(old="= 1\n", new="= 2\n"))
    proc = _cli(repo, spec)
    assert proc.returncode == mutate.EXIT_INVALID
    assert "occurs 2 times" in proc.stderr
    assert "baseline" not in proc.stderr and "| Mutant |" not in proc.stdout  # nothing ran


def test_refuses_absent_old(repo: Path, tmp_path: Path) -> None:
    proc = _cli(repo, _write(tmp_path, _mutant(old="VALUE = 3")))
    assert proc.returncode == mutate.EXIT_INVALID
    assert "occurs 0 times" in proc.stderr


def test_one_invalid_mutant_stops_the_whole_run(repo: Path, tmp_path: Path) -> None:
    good = _mutant(id="good")
    bad = _mutant(id="bad", old="= 1\n", new="= 2\n")
    proc = _cli(repo, _write(tmp_path, good, bad))
    assert proc.returncode == mutate.EXIT_INVALID
    assert "bad" in proc.stderr and "mutant good" not in proc.stderr


def test_apply_mutant_replaces_exactly_one_occurrence() -> None:
    m = mutate.Mutant(id="m", file="f", old="b", new="X", tests=("t",))
    assert mutate.apply_mutant("abc", m) == "aXc"
    with pytest.raises(mutate.MutantError, match="occurs 2 times"):
        mutate.apply_mutant("abcb", m)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"file": "../outside.py"}, "relative"),
        ({"file": "/etc/passwd"}, "relative"),
        ({"tests": []}, "non-empty"),
        ({"tests": ["../t.py"]}, "relative"),
        ({"new": "VALUE = 1"}, "identical"),
        ({"old": ""}, "empty"),
        ({"expected": "maybe"}, "expected"),
        ({"typo": 1}, "unknown keys"),
        ({"pytest_args": "-x"}, "pytest_args"),
    ],
)
def test_rejects_invalid_definitions(tmp_path: Path, change: dict, message: str) -> None:
    with pytest.raises(mutate.MutantError, match=message):
        mutate.load_mutants([_write(tmp_path, _mutant(**change))])


def test_rejects_duplicate_ids_across_files(tmp_path: Path) -> None:
    a = _write(tmp_path, _mutant(), name="a.json")
    b = _write(tmp_path, _mutant(), name="b.json")
    with pytest.raises(mutate.MutantError, match="duplicate mutant id 'm'"):
        mutate.load_mutants([a, b])


# --- working tree untouched --------------------------------------------------------------


def test_leaves_the_repo_unchanged(repo: Path, tmp_path: Path) -> None:
    # An uncommitted edit and an untracked file must survive, byte- and mtime-identical.
    mod = repo / "src" / "pkg" / "mod.py"
    mod.write_text(MODULE + "# local edit\n", encoding="utf-8")
    (repo / "notes.txt").write_text("untracked", encoding="utf-8")
    # `git status` may refresh the index stat cache, so it runs before the snapshot.
    status_before = _git(repo, "status", "--porcelain")
    before = _snapshot(repo)

    proc = _cli(repo, _write(tmp_path, _mutant(id="killed"), _mutant(id="survives",
                old="OTHER = 1", new="OTHER = 2")))

    assert proc.returncode == mutate.EXIT_SURVIVORS, proc.stderr
    assert _snapshot(repo) == before
    assert _git(repo, "status", "--porcelain") == status_before
    assert "VALUE = 2" not in mod.read_text(encoding="utf-8")


def test_copy_includes_uncommitted_changes_and_skips_ignored(repo: Path, tmp_path: Path) -> None:
    (repo / "src" / "pkg" / "mod.py").write_text(MODULE + "EXTRA = 1\n", encoding="utf-8")
    (repo / "ignored").mkdir()
    (repo / "ignored" / "big.bin").write_bytes(b"x")
    dest = tmp_path / "copy"
    dest.mkdir()
    mutate.copy_tree(repo, None, dest)
    assert "EXTRA = 1" in (dest / "src" / "pkg" / "mod.py").read_text(encoding="utf-8")
    assert not (dest / "ignored").exists()
    assert not (dest / ".git").exists()


def test_rev_uses_the_committed_version(repo: Path, tmp_path: Path) -> None:
    # Working tree drops OTHER; the committed version still has it, so with --rev the
    # mutant applies and survives, without --rev it is refused.
    (repo / "src" / "pkg" / "mod.py").write_text('VALUE = 1\nNAME = "x"\n', encoding="utf-8")
    (repo / "tests" / "test_mod.py").write_text(TEST.replace("OTHER, ", ""), encoding="utf-8")
    spec = _write(tmp_path, _mutant(old="OTHER = 1", new="OTHER = 2"))
    assert _cli(repo, spec).returncode == mutate.EXIT_INVALID
    proc = _cli(repo, "--rev", "HEAD", spec)
    assert proc.returncode == mutate.EXIT_SURVIVORS, proc.stderr
    assert "Source: `HEAD`" in proc.stdout


# --- exit code reflects survivors --------------------------------------------------------


def test_exit_0_when_every_mutant_is_killed(repo: Path, tmp_path: Path) -> None:
    proc = _cli(repo, _write(tmp_path, _mutant(id="v"), _mutant(id="n", old='"x"', new='"y"')))
    assert proc.returncode == mutate.EXIT_ALL_KILLED, proc.stderr
    assert "2 killed, 0 survived, 0 error(s) of 2" in proc.stdout
    assert "| `v` | `src/pkg/mod.py` | `tests/test_mod.py` | **killed** | 1 failed, 1 passed" in (
        proc.stdout
    )
    assert "`tests/test_mod.py::test_value`" in proc.stdout


def test_exit_1_when_one_mutant_survives(repo: Path, tmp_path: Path) -> None:
    proc = _cli(repo, _write(tmp_path, _mutant(id="v"),
                             _mutant(id="o", old="OTHER = 1", new="OTHER = 2")))
    assert proc.returncode == mutate.EXIT_SURVIVORS, proc.stderr
    assert "| `o` |" in proc.stdout and "**survived** | 2 passed" in proc.stdout
    assert "1 killed, 1 survived, 0 error(s) of 2" in proc.stdout


def test_subset_selects_what_runs(repo: Path, tmp_path: Path) -> None:
    # The same mutant survives when the only test that sees it is deselected.
    proc = _cli(repo, _write(tmp_path, _mutant(pytest_args=["-k", "name"])))
    assert proc.returncode == mutate.EXIT_SURVIVORS
    assert "1 passed, 1 deselected" in proc.stdout


def test_exit_3_when_the_baseline_is_red(repo: Path, tmp_path: Path) -> None:
    (repo / "tests" / "test_mod.py").write_text(TEST + "\n\ndef test_red():\n    assert False\n",
                                                encoding="utf-8")
    proc = _cli(repo, _write(tmp_path, _mutant()))
    assert proc.returncode == mutate.EXIT_ERROR
    assert "**error** | baseline not green (1 failed, 2 passed" in proc.stdout


def test_exit_3_when_pytest_cannot_collect(repo: Path, tmp_path: Path) -> None:
    proc = _cli(repo, "--no-baseline", _write(tmp_path, _mutant(new="VALUE = (")))
    assert proc.returncode == mutate.EXIT_ERROR
    assert "**error** | pytest exit 2" in proc.stdout


def test_exit_3_on_timeout(repo: Path, tmp_path: Path) -> None:
    slow = _mutant(new="import time\ntime.sleep(30)\nVALUE = 1")
    proc = _cli(repo, "--no-baseline", "--timeout", "3", _write(tmp_path, slow))
    assert proc.returncode == mutate.EXIT_ERROR
    assert "timeout after 3 s" in proc.stdout


def test_import_from_outside_the_copy_is_an_error(repo: Path, tmp_path: Path) -> None:
    # A package of the same name earlier on sys.path would shadow the mutated copy.
    shadow = tmp_path / "shadow" / "pkg"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "mod.py").write_text(MODULE, encoding="utf-8")
    copy = tmp_path / "copy"
    copy.mkdir()
    mutate.copy_tree(repo, None, copy)
    sitecustomize = copy / "src" / "sitecustomize.py"
    sitecustomize.write_text(f"import sys\nsys.path.insert(0, {str(shadow.parent)!r})\n",
                             encoding="utf-8")
    error = mutate.check_import_origin(copy, "src/pkg/mod.py", timeout=60)
    assert error is not None and "not from the copy" in error
    sitecustomize.unlink()
    assert mutate.check_import_origin(copy, "src/pkg/mod.py", timeout=60) is None


def test_refuses_a_git_ignored_target(repo: Path, tmp_path: Path) -> None:
    # read_source can read the file, but copy_tree skips it: refused before anything runs.
    (repo / "ignored").mkdir()
    (repo / "ignored" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    proc = _cli(repo, _write(tmp_path, _mutant(file="ignored/mod.py")))
    assert proc.returncode == mutate.EXIT_INVALID, proc.stderr
    assert "ignored/mod.py is not in the copied tree" in proc.stderr
    assert "baseline" not in proc.stderr and "Traceback" not in proc.stderr


def test_refuses_a_target_missing_from_the_revision(repo: Path, tmp_path: Path) -> None:
    (repo / "src" / "pkg" / "new.py").write_text("VALUE = 1\n", encoding="utf-8")  # untracked
    spec = _write(tmp_path, _mutant(file="src/pkg/new.py"))
    proc = _cli(repo, "--rev", "HEAD", spec)
    assert proc.returncode == mutate.EXIT_INVALID, proc.stderr
    assert "not in the copied tree" in proc.stderr


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (FileNotFoundError("gone"), "internal error: FileNotFoundError: gone"),
        (KeyboardInterrupt(), "interrupted, results incomplete"),
    ],
)
def test_unexpected_exceptions_exit_3_not_1(
    repo: Path, tmp_path: Path, monkeypatch, capsys, exc: BaseException, message: str
) -> None:
    def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(mutate, "run", boom)
    code = mutate.main(["--root", str(repo), str(_write(tmp_path, _mutant()))])
    err = capsys.readouterr().err
    assert code == mutate.EXIT_ERROR
    assert message in err and "Traceback" not in err


def test_import_check_timeout_is_an_error_not_a_crash(repo: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    copy.mkdir()
    mutate.copy_tree(repo, None, copy)
    (copy / "src" / "sitecustomize.py").write_text("import time\ntime.sleep(30)\n",
                                                   encoding="utf-8")
    error = mutate.check_import_origin(copy, "src/pkg/mod.py", timeout=1)
    assert error == "import check for pkg.mod timed out after 1 s"


@pytest.mark.parametrize(
    ("statuses", "code"),
    [
        (["killed"], 0),
        (["killed", "survived"], 1),
        (["survived", "error"], 3),
        (["killed", "error"], 3),
    ],
)
def test_exit_code_mapping(statuses: list[str], code: int) -> None:
    m = mutate.Mutant(id="m", file="f", old="a", new="b", tests=("t",))
    assert mutate.exit_code([mutate.Result(m, s, "") for s in statuses]) == code


def test_classify_uses_the_pytest_exit_code() -> None:
    assert mutate.classify(0) == mutate.SURVIVED
    assert mutate.classify(1) == mutate.KILLED
    for code in (2, 3, 4, 5, None):  # interrupted, internal error, usage, no tests, timeout
        assert mutate.classify(code) == mutate.ERROR


def test_expected_column_flags_a_difference() -> None:
    m = mutate.Mutant(id="m|x", file="f", old="a", new="b", tests=("t",), expected="killed")
    table = mutate.render_table([mutate.Result(m, mutate.SURVIVED, "3 passed")], rev=None)
    assert "| `m\\|x` |" in table  # pipes escaped
    assert "killed (**differs**)" in table


# --- the shipped mutant files ------------------------------------------------------------


def test_shipped_mutants_load_and_apply_to_this_repo() -> None:
    files = sorted(MUTANT_DIR.glob("*.json"))
    mutants = mutate.load_mutants(files)
    assert {"TONE_PIVOT_HZ", "LSB_16BIT_NEG", "SCALE_44K1", "CLICK_Q", "M1"} <= {
        m.id for m in mutants
    }
    for m in mutants:
        text = mutate.read_source(ROOT, None, m.file)
        assert mutate.apply_mutant(text, m) != text
        for t in m.tests:
            assert (ROOT / t.split("::")[0]).exists(), f"{m.id}: {t} does not exist"
