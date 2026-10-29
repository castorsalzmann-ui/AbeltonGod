"""Where generated samples go inside a Live project folder (Phase 03, issue #64).

``place_kick`` renders a kick into ``<project>/Samples/Drums/Kicks/`` (configurable) and returns
the absolute WAV path, ready for ``ClipSlot.create_audio_clip``. File naming, the no-overwrite
rule (D-006), dangling-symlink handling and the sidecar all come from
:func:`audio_engine.io.write_kick`; this module adds only the folder layout, Windows path rules
for the layout, a path-length limit and the clean-up of folders it created.

Windows rules used here (Microsoft Learn, "Naming Files, Paths, and Namespaces" and "Maximum
Path Length Limitation", read 2026-10-28):

- reserved device names CON, PRN, AUX, NUL, COM1-9, COM¹²³, LPT1-9, LPT¹²³, also with any
  extension (``NUL.txt``); CONIN$ / CONOUT$ are refused as well;
- reserved characters ``< > : " / \\ | ? *`` and code points 0-31; no trailing space or period;
- MAX_PATH is 260 characters including the terminating NUL, so 259 visible characters. Long
  paths need an opt-in per application; whether Live has it is not known, so the default
  refuses anything longer. A folder must leave room for an 8.3 name (MAX_PATH - 12); the
  default limit keeps the kick folder at most 229 characters, well inside that.

The longest path a placement leads to is not the WAV or its sidecar but Live's analysis file
``<name>.wav.asd``, which Live writes next to a sample it loads. The length limit is checked
against that path, so the sidecar and the WAV are always shorter.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from audio_engine.io import safe_stem, write_kick

WINDOWS_MAX_PATH_CHARS = 259  # MAX_PATH 260 minus the terminating NUL
DEFAULT_KICK_FOLDER = "Samples/Drums/Kicks"
MIN_STEM_CHARS = 16  # below this the name would be cut too short to stay readable
# write_kick adds _002, _003 … on a clash. The length check reserves room for up to 9999
# files of the same name; beyond that the files are checked after writing (and removed).
SUFFIX_RESERVE = "_9999"
# Longest name Live or we put next to a stem: Live's analysis file "<stem>.wav.asd" (8),
# longer than the sidecar "<stem>.json" (5) and the WAV "<stem>.wav" (4).
LONGEST_EXTENSION = ".wav.asd"
MAX_COMPONENT_CHARS = 255  # NTFS limit per path component (UTF-16 code units)

_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{dev}{n}" for dev in ("COM", "LPT") for n in (*"123456789", "¹", "²", "³")}
)
_RESERVED_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class LibraryPathError(ValueError):
    """A library path was refused before anything was written (bad layout, project folder
    missing, a file or dangling symlink where a folder belongs, path too long)."""


@dataclass(frozen=True)
class LibraryLayout:
    """Where kicks go below the project folder.

    ``kicks``: relative folder, ``/`` or ``\\`` separated, at least one component; every
    component must be a valid Windows file name. ``max_path_chars``: longest allowed absolute
    file path in UTF-16 code units (default 259, Windows MAX_PATH); ``None`` switches the
    check off.
    """

    kicks: str = DEFAULT_KICK_FOLDER
    max_path_chars: int | None = WINDOWS_MAX_PATH_CHARS

    def __post_init__(self) -> None:
        split_folder(self.kicks)  # raises LibraryPathError
        limit = self.max_path_chars
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
            raise TypeError(f"max_path_chars must be an int or None, got {limit!r}")
        if limit is not None and limit < 1:
            raise LibraryPathError(f"max_path_chars must be positive, got {limit}")

    @property
    def kick_parts(self) -> tuple[str, ...]:
        return split_folder(self.kicks)


def split_folder(folder: str) -> tuple[str, ...]:
    """``"Samples\\Drums/Kicks"`` -> ``("Samples", "Drums", "Kicks")``.

    Refuses (``LibraryPathError``) an absolute or drive path, empty components, ``.`` and
    ``..``, and every component :func:`windows_name_problem` objects to.
    """
    if not isinstance(folder, str):
        raise TypeError(f"folder must be a str, got {type(folder).__name__}")
    if not folder:
        raise LibraryPathError("library folder is empty; give at least one folder name")
    if folder[0] in "/\\" or (len(folder) >= 2 and folder[1] == ":"):
        raise LibraryPathError(f"library folder {folder!r} must be relative to the project")
    parts = tuple(re.split(r"[/\\]", folder))
    for part in parts:
        problem = windows_name_problem(part)
        if problem:
            raise LibraryPathError(f"library folder {folder!r}: component {part!r} {problem}")
    return parts


def windows_name_problem(name: str) -> str | None:
    """Why ``name`` is not a valid Windows file or folder name, or ``None`` if it is."""
    if name == "":
        return "is empty"
    if name in (".", ".."):
        return "is a relative step"
    bad = _RESERVED_CHARS.search(name)
    if bad:
        return f"contains the reserved character {bad.group()!r}"
    if name[-1] in " .":
        return "ends with a space or a period"
    if name.split(".")[0].rstrip(" ").upper() in _RESERVED_DEVICE_NAMES:
        return "is a reserved Windows device name"
    if path_chars(name) > MAX_COMPONENT_CHARS:
        return f"is longer than {MAX_COMPONENT_CHARS} characters"
    return None


def path_chars(path: str | os.PathLike[str]) -> int:
    """Length as Windows counts it: UTF-16 code units (an emoji counts 2)."""
    return len(os.fspath(path).encode("utf-16-le", "surrogatepass")) // 2


DEFAULT_LAYOUT = LibraryLayout()


def library_folder(project_dir: str | os.PathLike[str],
                   layout: LibraryLayout = DEFAULT_LAYOUT) -> Path:
    """Absolute kick folder of a project. Pure: touches no file (e.g. for the Explorer
    fallback). Symlinks in ``project_dir`` are kept, not resolved."""
    _check_layout(layout)
    return Path(os.path.abspath(project_dir)).joinpath(*layout.kick_parts)


def place_kick(
    params: dict[str, Any],
    project_dir: str | os.PathLike[str],
    *,
    name: str = "kick",
    description: str | None = None,
    created_at: datetime | None = None,
    layout: LibraryLayout = DEFAULT_LAYOUT,
) -> Path:
    """Render a kick into the project's kick folder and return the absolute WAV path.

    The sidecar is always ``wav_path.with_suffix(".json")`` in the same folder. ``params``,
    ``name``, ``description`` and ``created_at`` mean the same as in
    :func:`audio_engine.io.write_kick`, which does the naming and writing: existing files are
    never overwritten (``_002``, ``_003`` …), and a failed write removes its own files.

    ``project_dir`` must be an existing folder; the layout's folders below it are created as
    needed. If the call fails for any reason (bad parameters, disk full, permission, Ctrl+C),
    the WAV/sidecar pair it wrote and the folders it created are removed again, so the project
    tree is left as it was. Known exceptions, all a few bytecodes wide or outside this call:

    - an interrupt between ``os.mkdir`` and recording that folder leaves that empty folder;
    - an interrupt after ``write_kick`` has finished but before its result is stored here, or
      after the ``try`` block ends, leaves the finished, valid pair (the caller gets no path);
    - a second Ctrl+C during the clean-up stops the clean-up;
    - two calls on the same project at the same time: if both fail, empty layout folders can
      stay (each call may see the other's folder as existing and not remove it).

    A ``name`` that would make a path longer than ``layout.max_path_chars`` is shortened; if
    even a ``MIN_STEM_CHARS`` name does not fit, :class:`LibraryPathError` is raised before
    rendering.

    Raises :class:`LibraryPathError` (a ``ValueError``) for refused paths, ``KickParamsError``
    / ``ValueError`` for bad parameters, ``OSError`` for file system failures.
    """
    folder = library_folder(project_dir, layout)
    root = Path(os.path.abspath(project_dir))
    if not root.is_dir():
        raise LibraryPathError(f"project folder {root} does not exist or is not a folder")
    stem = _fitting_stem(name, folder, layout.max_path_chars)

    # One clean-up path for every failure. ``created`` is filled by _make_folders right after
    # each mkdir, inside this try, so an interrupt after a folder is recorded (also right
    # after _make_folders returns) still removes it; only an interrupt between one mkdir and
    # its append leaves that folder. ``written`` holds the pair once write_kick has returned,
    # so a failure or Ctrl+C after that removes the finished pair too.
    created: list[Path] = []
    written: tuple[Path, Path] | None = None
    try:
        _make_folders(root, layout.kick_parts, created)
        written = write_kick(
            params, folder, name=stem, description=description, created_at=created_at
        )
        wav_path = written[0]
        limit = layout.max_path_chars
        longest = longest_path(wav_path)
        if limit is not None and path_chars(longest) > limit:
            # Only reachable with more than 9999 files of the same name (see SUFFIX_RESERVE).
            # The except below removes the pair and the new folders.
            raise LibraryPathError(
                f"{longest} (Live's analysis file for {wav_path.name}) would be "
                f"{path_chars(longest)} characters, over the limit of {limit} "
                f"(too many files named {stem!r}); nothing was kept"
            )
    except BaseException:
        if written is not None:
            _remove_files((written[1], written[0]))  # sidecar first, then the WAV
        _remove_folders(created)  # neither raises OSError: the original error stays
        raise
    return wav_path


def sidecar_path(wav_path: str | os.PathLike[str]) -> Path:
    """The sidecar JSON that belongs to a WAV written by :func:`place_kick` (same folder,
    same stem, ``.json``)."""
    wav = Path(wav_path)
    if wav.suffix != ".wav":
        raise ValueError(f"{wav} is not a .wav path")
    return wav.with_suffix(".json")


def longest_path(wav_path: str | os.PathLike[str]) -> Path:
    """Longest path a placement leads to: Live's analysis file ``<wav>.asd``."""
    wav = Path(wav_path)
    return wav.with_name(wav.name + ".asd")


def _check_layout(layout: Any) -> None:
    if not isinstance(layout, LibraryLayout):
        raise TypeError(f"layout must be a LibraryLayout, got {type(layout).__name__}")


def _fitting_stem(name: str, folder: Path, limit: int | None) -> str:
    stem = safe_stem(name)
    if limit is None:
        return stem
    room = limit - path_chars(folder) - 1 - len(SUFFIX_RESERVE) - len(LONGEST_EXTENSION)
    if room < MIN_STEM_CHARS:
        raise LibraryPathError(
            f"kick folder {folder} is {path_chars(folder)} characters; with a file name of "
            f"{MIN_STEM_CHARS} characters, the counter and '{LONGEST_EXTENSION}' (Live's "
            "analysis file) the path would exceed "
            f"{limit} characters (Windows MAX_PATH). Move the project to a shorter path or "
            "choose a shorter layout."
        )
    # The cut may end on '-' or '.': write_kick applies safe_stem again, which can only make
    # it shorter, or "kick-<device>" (at most 13 characters) if a bare device name is left.
    return stem[:room]


def _make_folders(root: Path, parts: tuple[str, ...], created: list[Path]) -> None:
    """Create ``root/parts…`` one level at a time and append each folder this call made to
    ``created`` (the caller owns the list and removes them on failure). A file or a dangling
    symlink in the way is refused; a symlink to a folder is followed."""
    current = root
    for part in parts:
        current = current / part
        try:
            os.mkdir(current)
        except FileExistsError:
            if current.is_dir():
                continue
            what = "a dangling symlink" if current.is_symlink() else "not a folder"
            raise LibraryPathError(
                f"{current} is {what}; the kick folder cannot be created there"
            ) from None
        created.append(current)


def _remove_files(paths: tuple[Path, ...]) -> None:
    """Remove the files this call wrote. Every ``OSError`` (also "already gone") is swallowed
    for the same reason as in :func:`_remove_folders`."""
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            pass


def _remove_folders(created: list[Path]) -> None:
    """Remove folders this call created, deepest first. A folder that is no longer empty
    (someone else wrote into it meanwhile) stays. Every ``OSError`` here is swallowed on
    purpose: this runs while another exception is propagating, and that one must reach the
    caller unchanged (a "directory not empty" must not replace a "disk full")."""
    for folder in reversed(created):
        try:
            os.rmdir(folder)
        except OSError:
            pass
