"""Project folder layout, the project-folder check and safe placement of generated samples
(Phase 03, issue #64; check: issue #149)."""

from .layout import (
    DEFAULT_KICK_FOLDER,
    DEFAULT_LAYOUT,
    WINDOWS_MAX_PATH_CHARS,
    LibraryLayout,
    LibraryPathError,
    library_folder,
    longest_path,
    path_chars,
    place_kick,
    sidecar_path,
    split_folder,
    windows_name_problem,
)
from .project import CHECKOUT_ROOT, ProjectDirProblem, ProjectReason, check_project_dir

__all__ = [
    "CHECKOUT_ROOT",
    "DEFAULT_KICK_FOLDER",
    "DEFAULT_LAYOUT",
    "WINDOWS_MAX_PATH_CHARS",
    "LibraryLayout",
    "LibraryPathError",
    "ProjectDirProblem",
    "ProjectReason",
    "check_project_dir",
    "library_folder",
    "longest_path",
    "path_chars",
    "place_kick",
    "sidecar_path",
    "split_folder",
    "windows_name_problem",
]
