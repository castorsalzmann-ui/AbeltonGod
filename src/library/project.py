"""Is a folder the project folder of a saved Live set? (Phase 04, issue #149)

``check_project_dir`` is the one check every caller runs before it writes a sample into a
project folder: ``scripts/kick_to_live.py`` (``--project``) and the Phase 04b copilot (the
project folder of its session configuration, ``docs/INTERFACES.md`` "Tool inputs"). It returns
a structured result and no user text; each caller words the refusal itself.

Accepted is an existing absolute folder

1. with a ``.als`` file (any case) directly in it: Live keeps the set at the top of its
   project folder,
2. that is not Live's ``Backup`` folder (any case): neither the given name nor the folder it
   resolves to (symlink, junction, ``..``) may be called ``Backup``,
3. that does not lie inside a refused root, after resolving symlinks and junctions. The
   default root is the AbeltonGod checkout this module is loaded from. It is used only if
   it is verified (``pyproject.toml`` with ``name = "abeltongod"`` and ``src/library/``
   next to it); otherwise, e.g. after a non-editable install, the check refuses every
   folder with ``checkout_unknown`` instead of silently skipping the checkout rule.

The checks run in the order of :class:`ProjectReason`; the first failing one is returned.
Nothing is created or written.

``unreadable`` covers an OSError while checking. Which OSErrors reach the check depends on
the Python version: up to 3.13 ``Path.is_dir()`` raises on a permission error (EACCES), so
a folder the user cannot access is ``unreadable``; from 3.14 on ``is_dir()`` returns False
there and the same folder is ``missing``. A folder that exists but cannot be listed is
``unreadable`` on every version; its detail names the folder as given, not the resolved one.
A RuntimeError inside the checks (a symlink loop in ``resolve()`` before 3.13, but also any
other RuntimeError) is ``unreadable`` too: the check fails closed.

"Absolute" is :func:`os.path.isabs` of the running Python: on Windows ``C:\\x`` and
``\\\\server\\share\\x`` are absolute, the drive-relative ``C:x`` is not. A rooted path
without a drive (``\\x``) is absolute up to Python 3.12 and not from 3.13 on.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# src/library/project.py -> the checkout (src layout); verified by checkout_root().
CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_NAME = "abeltongod"  # [project] name in the checkout's pyproject.toml
LIVE_BACKUP_FOLDER = "backup"  # compared case-insensitively
SET_SUFFIX = ".als"  # compared case-insensitively


class ProjectReason(StrEnum):
    """Why a folder is refused, in the order the checks run."""

    EMPTY = "empty"  # empty or only whitespace (would mean the current folder)
    NOT_ABSOLUTE = "not_absolute"
    MISSING = "missing"  # does not exist, or is not a folder
    # refused_roots=None, but CHECKOUT_ROOT is not a verified checkout; detail = why
    CHECKOUT_UNKNOWN = "checkout_unknown"
    IN_CHECKOUT = "in_checkout"  # inside a refused root; detail = that root
    BACKUP_FOLDER = "backup_folder"  # Live's Backup folder; detail = the resolved folder
    UNREADABLE = "unreadable"  # an OSError while checking; detail = the error text
    NO_ALS_FILE = "no_als_file"  # no .als file directly in the folder


@dataclass(frozen=True)
class ProjectDirProblem:
    """A refusal: the reason, the path as given (``os.fspath``) and an optional detail."""

    reason: ProjectReason
    path: str
    detail: str = ""


def checkout_problem(root: Path) -> str | None:
    """Why ``root`` is not a verified AbeltonGod checkout (English detail), or None."""
    try:
        with open(root / "pyproject.toml", "rb") as fh:
            name = tomllib.load(fh).get("project", {}).get("name")
        has_src = (root / "src" / "library").is_dir()
    except (OSError, tomllib.TOMLDecodeError, AttributeError) as exc:
        return f"{root}: no readable pyproject.toml ({type(exc).__name__}: {exc})"
    if name != PROJECT_NAME:
        return f"{root}: pyproject.toml names project {name!r}, not {PROJECT_NAME!r}"
    if not has_src:
        return f"{root}: no src/library folder"
    return None


def check_project_dir(
    project_dir: str | os.PathLike[str], *,
    refused_roots: Iterable[str | os.PathLike[str]] | None = None,
) -> ProjectDirProblem | None:
    """``None`` if ``project_dir`` may receive samples, else why not.

    ``refused_roots``: folders the project may not lie in (resolved here), any iterable of
    paths; a single ``str`` / ``PathLike`` is a ``TypeError`` (a string would be read one
    character at a time). ``None`` means :data:`CHECKOUT_ROOT`, verified at each call; tests
    pass their own, because pytest's temp folder lies inside the checkout. An empty iterable
    refuses no root."""
    raw = os.fspath(project_dir)
    if not isinstance(raw, str):
        raise TypeError(f"project_dir must be a str path, not {type(raw).__name__}")
    if isinstance(refused_roots, (str, bytes, os.PathLike)):
        raise TypeError("refused_roots must be an iterable of paths, not a single path")
    roots = None if refused_roots is None else tuple(refused_roots)

    def problem(reason: ProjectReason, detail: str = "") -> ProjectDirProblem:
        return ProjectDirProblem(reason, raw, detail)

    if not raw.strip():
        return problem(ProjectReason.EMPTY)
    if not os.path.isabs(raw):
        return problem(ProjectReason.NOT_ABSOLUTE)
    folder = Path(raw)
    try:
        if not folder.is_dir():
            return problem(ProjectReason.MISSING)
        if roots is None:
            unverified = checkout_problem(CHECKOUT_ROOT)
            if unverified is not None:
                return problem(ProjectReason.CHECKOUT_UNKNOWN, unverified)
            roots = (CHECKOUT_ROOT,)
        real = folder.resolve()
        for root in roots:
            resolved_root = Path(root).resolve()
            if real.is_relative_to(resolved_root):
                return problem(ProjectReason.IN_CHECKOUT, str(resolved_root))
        if LIVE_BACKUP_FOLDER in (folder.name.lower(), real.name.lower()):
            return problem(ProjectReason.BACKUP_FOLDER, str(real))
        has_set = any(p.suffix.lower() == SET_SUFFIX and p.is_file() for p in folder.iterdir())
    except (OSError, RuntimeError) as exc:  # RuntimeError: symlink loop in resolve() (<3.13)
        return problem(ProjectReason.UNREADABLE, str(exc))
    if not has_set:
        return problem(ProjectReason.NO_ALS_FILE)
    return None


__all__ = [
    "CHECKOUT_ROOT",
    "ProjectDirProblem",
    "ProjectReason",
    "check_project_dir",
    "checkout_problem",
]
