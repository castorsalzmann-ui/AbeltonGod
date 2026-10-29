"""Project-folder check ``library.check_project_dir`` (issue #149).

The expected reasons are written out here by hand from the rules in the issue (the rules of
``scripts/kick_to_live.py`` ``project_problem`` before #149), not derived from the module.
pytest's temp folder lies inside the checkout (``--basetemp=.pytest_tmp``), so every test
passes its own refused root unless it checks the default root on purpose.

Windows cases run only on the Windows CI runner (drive letters, UNC, junctions); symlink
cases are skipped where the OS does not let the test create a symlink.
"""

from __future__ import annotations

import importlib.util
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

import library
import library.project as project_mod
from library import CHECKOUT_ROOT, ProjectDirProblem, ProjectReason, check_project_dir

REPO = Path(__file__).resolve().parents[2]  # tests/library/test_project.py -> checkout
WINDOWS = sys.platform == "win32"
R = ProjectReason


@pytest.fixture
def root(tmp_path) -> Path:
    """A stand-in for the AbeltonGod checkout."""
    r = tmp_path / "repo"
    r.mkdir()
    return r


@pytest.fixture
def project(tmp_path) -> Path:
    p = tmp_path / "My Project"
    p.mkdir()
    (p / "My Project.als").write_bytes(b"")
    return p


def check(path, root: Path):
    return check_project_dir(path, refused_roots=(root,))


def reason(path, root: Path) -> ProjectReason | None:
    problem = check(path, root)
    return None if problem is None else problem.reason


def tree(folder: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(folder)), p.lstat().st_size) for p in folder.rglob("*"))


def symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a symlink here: {exc}")


# -- the reason codes are the agreed interface (#149 comment, #148) -------------------------

def test_reason_codes_are_the_agreed_strings_in_check_order():
    assert [r.value for r in ProjectReason] == [
        "empty", "not_absolute", "missing", "checkout_unknown", "in_checkout", "backup_folder",
        "unreadable", "no_als_file"]
    assert all(isinstance(r, str) for r in ProjectReason)
    assert library.check_project_dir is check_project_dir


def test_default_root_is_this_checkout():
    assert CHECKOUT_ROOT == REPO
    assert (CHECKOUT_ROOT / "src" / "library" / "project.py").is_file()
    assert project_mod.checkout_problem(REPO) is None


# -- the default root must be a verified checkout (round 1, finding 4) ----------------------

def fake_checkout(base: Path, pyproject: str | None, src: bool = True) -> Path:
    base.mkdir(parents=True)
    if pyproject is not None:
        (base / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    if src:
        (base / "src" / "library").mkdir(parents=True)
    return base


@pytest.mark.parametrize("pyproject, src, part", [
    (None, True, "no readable pyproject.toml"),
    ('[project]\nname = "other"\n', True, "names project 'other'"),
    ("[tool.x]\n", True, "names project None"),
    ("[project\nname=", True, "TOMLDecodeError"),
    ('project = "abeltongod"\n', True, "AttributeError"),
    ('[project]\nname = "abeltongod"\n', False, "no src/library folder"),
])
def test_unverified_default_root_refuses_everything(tmp_path, project, monkeypatch, pyproject,
                                                    src, part):
    """E.g. a non-editable install: CHECKOUT_ROOT is the venv's Lib folder."""
    fake = fake_checkout(tmp_path / "lib", pyproject, src)
    monkeypatch.setattr(project_mod, "CHECKOUT_ROOT", fake)
    problem = check_project_dir(project)
    assert problem.reason is R.CHECKOUT_UNKNOWN and problem.path == str(project)
    assert part in problem.detail and str(fake) in problem.detail
    # explicit roots do not need the default root
    assert check_project_dir(project, refused_roots=(tmp_path / "elsewhere",)) is None


def test_verified_fake_default_root_is_used(tmp_path, monkeypatch):
    fake = fake_checkout(tmp_path / "clone", '[project]\nname = "abeltongod"\n')
    monkeypatch.setattr(project_mod, "CHECKOUT_ROOT", fake)
    inside = fake / "docs"
    inside.mkdir()
    (inside / "s.als").write_bytes(b"")
    outside = tmp_path / "p"
    outside.mkdir()
    (outside / "s.als").write_bytes(b"")
    assert check_project_dir(inside) == ProjectDirProblem(R.IN_CHECKOUT, str(inside),
                                                          str(fake.resolve()))
    assert check_project_dir(outside) is None


def test_order_missing_before_checkout_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(project_mod, "CHECKOUT_ROOT", tmp_path / "nothing")
    assert check_project_dir(tmp_path / "nope").reason is R.MISSING
    assert check_project_dir("rel").reason is R.NOT_ABSOLUTE


# -- refused_roots: any iterable of paths, never a single path (round 1, finding 5) ---------

def test_refused_roots_any_iterable(tmp_path, root):
    inside = root / "proj"
    inside.mkdir()
    for roots in ([root], [str(root)], {str(root)}, (r for r in [root]),
                  (tmp_path / "other", root)):
        assert reason_with(inside, roots) is R.IN_CHECKOUT, roots


def reason_with(path, roots):
    problem = check_project_dir(path, refused_roots=roots)
    return None if problem is None else problem.reason


@pytest.mark.parametrize("single", ["/nonexistent/other", "zz", b"/x", Path("/x")])
def test_refused_roots_single_path_is_a_type_error(project, single):
    with pytest.raises(TypeError, match="iterable of paths"):
        check_project_dir(project, refused_roots=single)


# -- accepted -------------------------------------------------------------------------------

def test_project_with_als_is_accepted(project, root):
    assert check(project, root) is None
    assert check(str(project), root) is None


@pytest.mark.parametrize("name", ["set.als", "SET.ALS", "Set.Als", "x [1].als"])
def test_als_suffix_any_case(tmp_path, root, name):
    p = tmp_path / "p"
    p.mkdir()
    (p / name).write_bytes(b"")
    assert check(p, root) is None


@pytest.mark.parametrize("name", ["Backups", "My Backup", "backup2", "Backup.old", "Back up"])
def test_names_that_only_contain_backup_are_accepted(tmp_path, root, name):
    p = tmp_path / name
    p.mkdir()
    (p / "s.als").write_bytes(b"")
    assert check(p, root) is None


def test_trailing_separator_is_accepted(project, root):
    assert check(str(project) + os.sep, root) is None
    if WINDOWS:
        assert check(str(project) + "/", root) is None


def test_sibling_with_root_as_name_prefix_is_not_inside(tmp_path):
    """``/x/repo-projects`` starts with the string ``/x/repo`` but is not inside it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    p = tmp_path / "repo-projects" / "p"
    p.mkdir(parents=True)
    (p / "s.als").write_bytes(b"")
    assert check(p, repo) is None


def test_empty_refused_roots_refuse_no_root(tmp_path):
    p = tmp_path / "p"
    p.mkdir()
    (p / "s.als").write_bytes(b"")
    assert check_project_dir(p, refused_roots=()) is None


def test_dotdot_out_of_a_backup_folder_is_the_project(project, root):
    (project / "Backup").mkdir()
    raw = str(project / "Backup" / "..")
    assert check(raw, root) is None


# -- each refusal: reason, path as given, detail --------------------------------------------

@pytest.mark.parametrize("raw", ["", " ", "\t\n", "   "])
def test_empty(raw, root, project, monkeypatch):
    monkeypatch.chdir(project)  # the current folder looks like a project: still refused
    assert check(raw, root) == ProjectDirProblem(R.EMPTY, raw, "")


@pytest.mark.parametrize("raw", ["My Project", "./My Project", "../x", ".", "C:x", "C:"])
def test_not_absolute(raw, root, tmp_path, project, monkeypatch):
    monkeypatch.chdir(tmp_path)  # "My Project" would exist relative to here
    assert check(raw, root) == ProjectDirProblem(R.NOT_ABSOLUTE, raw, "")


def test_pathlike_empty_is_dot_and_not_absolute(root):
    assert check(Path(""), root) == ProjectDirProblem(R.NOT_ABSOLUTE, ".", "")


def test_leading_space_before_an_absolute_path_is_not_absolute(project, root):
    raw = " " + str(project)
    assert reason(raw, root) is R.NOT_ABSOLUTE


def test_missing_folder_is_not_created(tmp_path, root):
    missing = tmp_path / "nope"
    assert check(missing, root) == ProjectDirProblem(R.MISSING, str(missing), "")
    assert not missing.exists()


def test_file_is_missing(project, root):
    f = project / "My Project.als"
    assert check(f, root) == ProjectDirProblem(R.MISSING, str(f), "")


def test_nul_character_is_missing(project, root):
    raw = str(project) + "\0x"
    assert reason(raw, root) is R.MISSING


def test_dangling_symlink_is_missing(tmp_path, root):
    link = tmp_path / "dangling"
    symlink(link, tmp_path / "gone")
    assert reason(link, root) is R.MISSING


@pytest.mark.parametrize("sub", ["", "docs", "a/b/c"])
def test_inside_refused_root(root, sub):
    target = root / sub if sub else root
    target.mkdir(parents=True, exist_ok=True)
    (target / "s.als").write_bytes(b"")  # a set file does not make it acceptable
    assert check(target, root) == ProjectDirProblem(R.IN_CHECKOUT, str(target),
                                                    str(root.resolve()))


def test_second_refused_root_counts(tmp_path, project):
    other = tmp_path / "other"
    other.mkdir()
    problem = check_project_dir(project, refused_roots=(other, tmp_path))
    assert problem == ProjectDirProblem(R.IN_CHECKOUT, str(project), str(tmp_path.resolve()))


@pytest.mark.parametrize("sub", ["", "docs", "tests/library"])
def test_default_root_refuses_the_real_checkout(sub):
    target = REPO / sub if sub else REPO
    problem = check_project_dir(target)
    assert problem is not None and problem.reason is R.IN_CHECKOUT
    assert problem.detail == str(REPO.resolve())


def test_default_root_refuses_pytests_temp_folder(project):
    """basetemp lies inside the checkout; without refused_roots the real root applies."""
    assert project.resolve().is_relative_to(REPO)
    assert check_project_dir(project).reason is R.IN_CHECKOUT


@pytest.mark.parametrize("name", ["Backup", "backup", "BACKUP", "bAcKuP"])
def test_backup_folder_any_case(project, root, name):
    backup = project / name
    backup.mkdir()
    (backup / "My Project [2026-10-29 120000].als").write_bytes(b"")
    assert check(backup, root) == ProjectDirProblem(R.BACKUP_FOLDER, str(backup),
                                                    str(backup.resolve()))


@pytest.mark.parametrize("suffix", [os.sep, os.sep + ".", os.sep + "." + os.sep])
def test_backup_folder_with_trailing_separator_or_dot(project, root, suffix):
    backup = project / "Backup"
    backup.mkdir()
    (backup / "b.als").write_bytes(b"")
    assert reason(str(backup) + suffix, root) is R.BACKUP_FOLDER


def test_dotdot_into_a_backup_folder_is_refused(project, root):
    """The given name is '..', the folder is Backup (stricter than project_problem before
    #149, which only looked at the given name)."""
    backup = project / "Backup"
    (backup / "sub").mkdir(parents=True)
    (backup / "b.als").write_bytes(b"")
    assert reason(str(backup / "sub" / ".."), root) is R.BACKUP_FOLDER


def test_symlink_to_a_backup_folder_is_refused(tmp_path, project, root):
    backup = project / "Backup"
    backup.mkdir()
    (backup / "b.als").write_bytes(b"")
    link = tmp_path / "kicks here"
    symlink(link, backup)
    assert check(link, root) == ProjectDirProblem(R.BACKUP_FOLDER, str(link),
                                                  str(backup.resolve()))


def test_symlink_named_backup_is_refused(tmp_path, project, root):
    link = tmp_path / "Backup"
    symlink(link, project)
    assert reason(link, root) is R.BACKUP_FOLDER


def test_symlink_into_refused_root_is_refused(tmp_path, root):
    inside = root / "proj"
    inside.mkdir()
    (inside / "s.als").write_bytes(b"")
    link = tmp_path / "looks outside"
    symlink(link, inside)
    assert check(link, root) == ProjectDirProblem(R.IN_CHECKOUT, str(link),
                                                  str(root.resolve()))


def test_refused_root_given_through_a_symlink_still_matches(tmp_path, root):
    inside = root / "proj"
    inside.mkdir()
    (inside / "s.als").write_bytes(b"")
    root_link = tmp_path / "root link"
    symlink(root_link, root)
    # the detail names the real folder, not the link it was given as
    assert check(inside, root_link) == ProjectDirProblem(R.IN_CHECKOUT, str(inside),
                                                         str(root.resolve()))


def test_refused_root_as_str_and_relative_dotdot(tmp_path, root):
    inside = root / "proj"
    inside.mkdir()
    problem = check_project_dir(inside, refused_roots=(str(root / "x" / ".."),))
    assert problem is not None and problem.reason is R.IN_CHECKOUT


def test_no_als_file(tmp_path, root):
    p = tmp_path / "plain"
    p.mkdir()
    (p / "x.als.txt").write_bytes(b"")
    (p / "sub.als").mkdir()  # a folder named *.als is not a set
    (p / "Backup").mkdir()
    (p / "Backup" / "old.als").write_bytes(b"")  # only directly in the folder counts
    (p / "als").write_bytes(b"")
    (p / ".als").write_bytes(b"")  # a dotfile has no suffix
    assert check(p, root) == ProjectDirProblem(R.NO_ALS_FILE, str(p), "")


def test_empty_folder_has_no_als_file(tmp_path, root):
    p = tmp_path / "empty"
    p.mkdir()
    assert reason(p, root) is R.NO_ALS_FILE


def test_dangling_als_symlink_is_not_a_set(tmp_path, root):
    p = tmp_path / "p"
    p.mkdir()
    try:
        (p / "s.als").symlink_to(tmp_path / "gone.als")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create a symlink here: {exc}")
    assert reason(p, root) is R.NO_ALS_FILE


# -- unreadable: every OSError while checking is a refusal, never an exception --------------

def test_unreadable_listing(project, root, monkeypatch):
    def denied(self):
        raise PermissionError(13, "Zugriff verweigert", str(self))
    monkeypatch.setattr(Path, "iterdir", denied)
    problem = check(project, root)
    assert problem.reason is R.UNREADABLE and problem.path == str(project)
    assert "Zugriff verweigert" in problem.detail


def test_unreadable_listing_names_the_folder_as_given(tmp_path, project, root, monkeypatch):
    """The folder is listed as given (as before #149), so the error text names the path the
    user typed, not the folder a symlink resolves to (round 1, finding 2)."""
    link = tmp_path / "projlink"
    symlink(link, project)

    def denied(self):
        raise PermissionError(13, "Permission denied", str(self))
    monkeypatch.setattr(Path, "iterdir", denied)
    problem = check(link, root)
    assert problem.reason is R.UNREADABLE
    assert problem.detail == f"[Errno 13] Permission denied: {str(link)!r}"
    k2l = load_kick_to_live()
    monkeypatch.setattr(k2l, "REFUSED_ROOTS", (root,))
    assert k2l.project_problem(str(link)) == (
        f"{link} lässt sich nicht lesen: [Errno 13] Permission denied: {str(link)!r}")


def test_unreadable_entry(project, root, monkeypatch):
    real_is_file = Path.is_file

    def denied(self, *a, **kw):
        if self.suffix == ".als":
            raise PermissionError(13, "denied", str(self))
        return real_is_file(self, *a, **kw)
    monkeypatch.setattr(Path, "is_file", denied)
    assert reason(project, root) is R.UNREADABLE


def test_unreadable_is_dir(project, root, monkeypatch):
    """Real only up to Python 3.13: there ``is_dir()`` raises on EACCES. From 3.14 on it
    returns False and such a folder is ``missing`` (still a refusal); the fault is injected
    here so the except path is tested on every version."""
    def denied(self, *a, **kw):
        raise PermissionError(13, "denied", str(self))
    monkeypatch.setattr(Path, "is_dir", denied)
    assert reason(project, root) is R.UNREADABLE


@pytest.mark.parametrize("exc", [OSError(40, "loop"), RuntimeError("Symlink loop")])
def test_resolve_failure(project, root, monkeypatch, exc):
    def broken(self, *a, **kw):
        raise exc
    monkeypatch.setattr(Path, "resolve", broken)
    problem = check(project, root)
    assert problem.reason is R.UNREADABLE and str(exc) == problem.detail


@pytest.mark.skipif(WINDOWS or os.geteuid() == 0, reason="needs POSIX permissions, not root")
def test_real_unreadable_folder(project, root):  # pragma: no cover - CI runs as non-root
    project.chmod(0o000)
    try:
        assert reason(project, root) is R.UNREADABLE
    finally:
        project.chmod(0o755)


def test_bytes_path_is_a_type_error(project, root):
    with pytest.raises(TypeError):
        check(os.fsencode(project), root)


# -- order of the checks ---------------------------------------------------------------------

def test_order_checkout_before_backup_before_als(root):
    backup = root / "Backup"
    backup.mkdir()
    assert reason(backup, root) is R.IN_CHECKOUT


def test_order_backup_before_unreadable(project, root, monkeypatch):
    backup = project / "Backup"
    backup.mkdir()
    monkeypatch.setattr(Path, "iterdir", lambda self: (_ for _ in ()).throw(OSError("x")))
    assert reason(backup, root) is R.BACKUP_FOLDER


# -- seeded property test over combinations ---------------------------------------------------

def expected_reason(case: dict) -> ProjectReason | None:
    """Independent decision table, written from the rules in issue #149."""
    if case["kind"] == "empty":
        return R.EMPTY
    if case["kind"] == "relative":
        return R.NOT_ABSOLUTE
    if not case["exists"] or case["is_file"]:
        return R.MISSING
    if case["inside_root"]:
        return R.IN_CHECKOUT
    if case["name"].lower() == "backup":
        return R.BACKUP_FOLDER
    if case["als_file"]:
        return None
    return R.NO_ALS_FILE


@pytest.mark.parametrize("seed", range(6))
def test_random_combinations(tmp_path, seed, monkeypatch):
    rng = random.Random(seed)
    base = tmp_path / f"s{seed}"
    repo = base / "repo"
    repo.mkdir(parents=True)
    outside = base / "out"
    outside.mkdir()
    monkeypatch.chdir(outside)
    names = ["Backup", "backup", "BACKUP", "Project", "Backups", "Ä Set", "x y"]
    for i in range(40):
        case = {
            "kind": rng.choice(["empty", "relative", "absolute", "absolute", "absolute"]),
            "exists": rng.random() < 0.85,
            "is_file": rng.random() < 0.1,
            "inside_root": rng.random() < 0.3,
            "name": rng.choice(names),
            "als_file": rng.random() < 0.6,
            "als_case": rng.choice([".als", ".ALS", ".Als"]),
            "decoys": rng.random() < 0.5,
            "trailing_sep": rng.random() < 0.3,
        }
        parent = (repo if case["inside_root"] else outside) / f"c{i}"
        parent.mkdir()
        folder = parent / case["name"]
        if case["exists"]:
            if case["is_file"]:
                folder.write_bytes(b"")
            else:
                folder.mkdir()
                if case["als_file"]:
                    (folder / ("set" + case["als_case"])).write_bytes(b"")
                if case["decoys"]:
                    (folder / "d.als").mkdir()
                    (folder / "x.als.bak").write_bytes(b"")
        if case["kind"] == "empty":
            raw = rng.choice(["", " ", "\t"])
        elif case["kind"] == "relative":
            raw = os.path.relpath(folder, outside)
        else:
            raw = str(folder) + (os.sep if case["trailing_sep"] else "")
        before = tree(base)
        problem = check_project_dir(raw, refused_roots=(repo,))
        assert tree(base) == before, (seed, i, case)  # nothing is ever written
        got = None if problem is None else problem.reason
        assert got is expected_reason(case), (seed, i, case, raw, problem)
        if problem is not None:
            assert problem.path == raw


# -- Windows (only on the Windows CI runner) -------------------------------------------------

windows_only = pytest.mark.skipif(not WINDOWS, reason="Windows path semantics")


@windows_only
def test_windows_drive_letter_and_forward_slashes(project, root):  # pragma: no cover
    raw = str(project)
    assert raw[1:3] == ":\\"
    assert check(raw, root) is None
    assert check(raw.replace("\\", "/"), root) is None
    assert check(raw[0].swapcase() + raw[1:], root) is None
    assert reason(raw[:2] + "relative", root) is R.NOT_ABSOLUTE  # drive-relative C:x


@windows_only
def test_windows_root_matched_in_any_case(root):  # pragma: no cover
    inside = root / "proj"
    inside.mkdir()
    assert reason(str(inside).upper(), root) is R.IN_CHECKOUT
    assert reason(inside, Path(str(root).lower())) is R.IN_CHECKOUT


@windows_only
def test_windows_backup_with_trailing_backslash(project, root):  # pragma: no cover
    (project / "Backup").mkdir()
    assert reason(str(project) + "\\BACKUP\\", root) is R.BACKUP_FOLDER


@windows_only
def test_windows_unc_path(project, root):  # pragma: no cover
    raw = str(project)
    unc = "\\\\localhost\\" + raw[0] + "$" + raw[2:]
    if not os.path.isdir(unc):
        pytest.skip("administrative share not reachable on this machine")
    assert check(unc, root) is None
    assert reason(unc + "\\Missing", root) is R.MISSING


@windows_only
def test_windows_unc_missing_server(root):  # pragma: no cover
    raw = "\\\\abeltongod-no-such-server\\share\\proj"
    assert reason(raw, root) in (R.MISSING, R.UNREADABLE)


def junction(link: Path, target: Path) -> None:  # pragma: no cover - Windows only
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True, text=True)
    if done.returncode != 0 or not link.is_dir():
        pytest.skip(f"mklink /J failed: {done.stdout} {done.stderr}")


@windows_only
def test_windows_junction_into_refused_root(tmp_path, root):  # pragma: no cover
    inside = root / "proj"
    inside.mkdir()
    (inside / "s.als").write_bytes(b"")
    link = tmp_path / "junction"
    junction(link, inside)
    assert reason(link, root) is R.IN_CHECKOUT


@windows_only
def test_windows_junction_to_backup(tmp_path, project, root):  # pragma: no cover
    backup = project / "Backup"
    backup.mkdir()
    (backup / "b.als").write_bytes(b"")
    link = tmp_path / "junction"
    junction(link, backup)
    assert reason(link, root) is R.BACKUP_FOLDER


# -- scripts/kick_to_live.py words each reason (hand-over for #149) ------------------------

def load_kick_to_live():
    if "kick_to_live" in sys.modules:
        return sys.modules["kick_to_live"]
    spec = importlib.util.spec_from_file_location("kick_to_live",
                                                  REPO / "scripts" / "kick_to_live.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["kick_to_live"] = module
    spec.loader.exec_module(module)
    return module


RAW = "C:\\Proj"
GERMAN = {  # copied from project_problem before #149; must not change
    R.EMPTY: "--project ist leer. Bitte den vollen Pfad des Projektordners angeben.",
    R.NOT_ABSOLUTE: ("--project muss ein voller Pfad sein (z. B. \"C:\\...\\Test Project\"), "
                     "nicht 'C:\\\\Proj'."),
    R.MISSING: "Den Ordner gibt es nicht: C:\\Proj",
    R.IN_CHECKOUT: ("C:\\Proj liegt im AbeltonGod-Ordner (DETAIL). Das ist kein Live-Projekt; "
                    "bitte den Projektordner deines Test-Sets angeben."),
    R.BACKUP_FOLDER: ("C:\\Proj ist Lives Backup-Ordner. Bitte den Ordner darüber nehmen (dort "
                      "liegt die .als-Datei des Sets)."),
    R.UNREADABLE: "C:\\Proj lässt sich nicht lesen: DETAIL",
    R.NO_ALS_FILE: ("In C:\\Proj liegt keine .als-Datei, also ist es nicht der Projektordner "
                    "eines gespeicherten Live-Sets. Set zuerst in Live speichern (Datei -> "
                    "Live-Set speichern unter ...), dann den Ordner nehmen, in dem die "
                    ".als-Datei liegt."),
    # new in #149 round 2; the script always passes its own roots, so it only gets the
    # fallback text if that ever changes
    R.CHECKOUT_UNKNOWN: "C:\\Proj wurde abgelehnt (checkout_unknown: DETAIL).",
}


@pytest.mark.parametrize("code", list(ProjectReason))
def test_kick_to_live_text_for_each_reason(code, monkeypatch):
    k2l = load_kick_to_live()
    seen = {}

    def fake_check(raw, *, refused_roots):
        seen["raw"], seen["roots"] = raw, refused_roots
        return ProjectDirProblem(code, raw, "DETAIL")
    monkeypatch.setattr(k2l, "check_project_dir", fake_check)
    monkeypatch.setattr(k2l, "REFUSED_ROOTS", ("ROOTS",))
    padded = " " + RAW + " "
    assert k2l.project_problem(RAW) == GERMAN[code]
    assert seen == {"raw": RAW, "roots": ("ROOTS",)}  # script's roots, read at call time
    k2l.project_problem(padded)
    assert seen["raw"] == padded  # passed on unchanged, never stripped


def test_kick_to_live_refuses_a_padded_absolute_path(project, root, monkeypatch):
    """The script keeps working with raw, so the check must see raw (round 1, finding 1)."""
    k2l = load_kick_to_live()
    monkeypatch.setattr(k2l, "REFUSED_ROOTS", (root,))
    raw = " " + str(project)
    assert k2l.project_problem(raw).startswith("--project muss ein voller Pfad sein")


def test_kick_to_live_unknown_reason_still_refuses(monkeypatch):
    k2l = load_kick_to_live()
    monkeypatch.setattr(k2l, "check_project_dir",
                        lambda raw, *, refused_roots: ProjectDirProblem("later", raw, "d"))
    text = k2l.project_problem(RAW)
    assert text is not None and "abgelehnt" in text and "later" in text


def test_kick_to_live_accepts_what_the_library_accepts(project, root, monkeypatch):
    k2l = load_kick_to_live()
    monkeypatch.setattr(k2l, "REFUSED_ROOTS", (root,))
    assert k2l.project_problem(str(project)) is None
    monkeypatch.setattr(k2l, "REFUSED_ROOTS", (project.parent,))
    assert "liegt im AbeltonGod-Ordner" in k2l.project_problem(str(project))


def test_module_has_no_user_text():
    """The library returns codes; German wording lives in the callers."""
    source = Path(project_mod.__file__).read_text(encoding="utf-8")
    for word in ("Ordner", "bitte", "Bitte", "nicht ", "liegt"):
        assert word not in source
