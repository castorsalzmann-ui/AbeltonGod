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
   default root is the AbeltonGod checkout this module is loaded from.

The checks run in the order of :class:`ProjectReason`; the first failing one is returned.
Nothing is created or written.

"Absolute" is :func:`os.path.isabs` of the running Python: on Windows ``C:\\x`` and
``\\\\server\\share\\x`` are absolute, the drive-relative ``C:x`` is not. A rooted path
without a drive (``\\x``) is absolute up to Python 3.12 and not from 3.13 on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# src/library/project.py -> the checkout (src layout).
CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
LIVE_BACKUP_FOLDER = "backup"  # compared case-insensitively
SET_SUFFIX = ".als"  # compared case-insensitively


class ProjectReason(StrEnum):
    """Why a folder is refused, in the order the checks run."""

    EMPTY = "empty"  # empty or only whitespace (would mean the current folder)
    NOT_ABSOLUTE = "not_absolute"
    MISSING = "missing"  # does not exist, or is not a folder
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


def check_project_dir(
    project_dir: str | os.PathLike[str], *, refused_roots: tuple[Path, ...] | None = None,
) -> ProjectDirProblem | None:
    """``None`` if ``project_dir`` may receive samples, else why not.

    ``refused_roots``: folders the project may not lie in (resolved here). ``None`` means
    :data:`CHECKOUT_ROOT`; tests pass their own, because pytest's temp folder lies inside the
    checkout. An empty tuple refuses no root."""
    raw = os.fspath(project_dir)
    if not isinstance(raw, str):
        raise TypeError(f"project_dir must be a str path, not {type(raw).__name__}")

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
        real = folder.resolve()
        roots = (CHECKOUT_ROOT,) if refused_roots is None else refused_roots
        for root in roots:
            resolved_root = Path(root).resolve()
            if real.is_relative_to(resolved_root):
                return problem(ProjectReason.IN_CHECKOUT, str(resolved_root))
        if LIVE_BACKUP_FOLDER in (folder.name.lower(), real.name.lower()):
            return problem(ProjectReason.BACKUP_FOLDER, str(real))
        has_set = any(p.suffix.lower() == SET_SUFFIX and p.is_file() for p in real.iterdir())
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
]
