"""Library layout and safe placement (issue #64).

Expected names and limits are written out here by hand (from the Microsoft Learn pages cited
in ``library.layout``), not taken from the module under test. Sidecar validation and re-render
use the contract file and ``audio_engine.io.rerender_from_sidecar``.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import random
import string
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import audio_engine.io as io_mod
import library.layout as layout_mod
from audio_engine.io import rerender_from_sidecar
from audio_engine.params import METADATA_SCHEMA_FILE, KickParamsError, load_schema
from library import (
    LibraryLayout,
    LibraryPathError,
    library_folder,
    longest_path,
    path_chars,
    place_kick,
    sidecar_path,
    windows_name_problem,
)

FAST = {"schema_version": "0.2", "seed": 7, "length_ms": 80}
FIXED_TIME = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
VALIDATOR = Draft202012Validator(load_schema(METADATA_SCHEMA_FILE))

# Microsoft Learn, "Naming Files, Paths, and Namespaces": reserved device names, also with an
# extension; plus the console names CONIN$ / CONOUT$.
RESERVED = [
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "COM¹", "COM²", "COM³",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    "LPT¹", "LPT²", "LPT³",
]
RESERVED_CHARS = list('<>:"/\\|?*') + [chr(c) for c in range(32)]


def tree(root: Path) -> list[tuple[str, str, bytes | None]]:
    """Everything below ``root``: (relative path, kind, file bytes). Symlinks are not
    followed, so a dangling one is listed too."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames + filenames):
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                out.append((rel, "link", os.readlink(p).encode()))
            elif p.is_dir():
                out.append((rel, "dir", None))
            else:
                out.append((rel, "file", p.read_bytes()))
    return sorted(out)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:  # Windows without symlink privilege
        pytest.skip(f"cannot create symlinks here: {exc}")


# --- layout and returned path ----------------------------------------------------------------


def test_default_layout_returns_absolute_wav_with_sidecar_next_to_it(tmp_path) -> None:
    project = tmp_path / "My Set Project"
    project.mkdir()
    wav = place_kick(FAST, project, name="dark kick", created_at=FIXED_TIME)
    assert wav.is_absolute()
    assert wav == project / "Samples" / "Drums" / "Kicks" / "dark-kick.wav"
    sidecar = project / "Samples" / "Drums" / "Kicks" / "dark-kick.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    VALIDATOR.validate(meta)
    assert meta["file"] == "dark-kick.wav"
    assert meta["sha256"] == sha(wav.read_bytes())
    assert sha(rerender_from_sidecar(sidecar)) == meta["sha256"]
    assert [p for p, *_ in tree(project)] == [
        "Samples", "Samples/Drums", "Samples/Drums/Kicks",
        "Samples/Drums/Kicks/dark-kick.json", "Samples/Drums/Kicks/dark-kick.wav",
    ]


def test_relative_project_dir_gives_absolute_path(tmp_path, monkeypatch) -> None:
    (tmp_path / "proj").mkdir()
    monkeypatch.chdir(tmp_path)
    wav = place_kick(FAST, "proj", created_at=FIXED_TIME)
    assert wav.is_absolute()
    assert wav == tmp_path / "proj" / "Samples" / "Drums" / "Kicks" / "kick.wav"


@pytest.mark.parametrize(
    ("kicks", "parts"),
    [
        ("Kicks", ("Kicks",)),
        ("Samples\\Generated\\Kicks", ("Samples", "Generated", "Kicks")),
        ("Samples/Drums\\Kicks", ("Samples", "Drums", "Kicks")),
        ("Samples/AbeltonGod Kicks", ("Samples", "AbeltonGod Kicks")),
        (".generated/Kicks", (".generated", "Kicks")),  # a leading period is allowed
        ("Bässe/Kicks", ("Bässe", "Kicks")),
    ],
)
def test_layout_is_configurable(tmp_path, kicks: str, parts: tuple[str, ...]) -> None:
    layout = LibraryLayout(kicks=kicks)
    wav = place_kick(FAST, tmp_path, created_at=FIXED_TIME, layout=layout)
    assert wav == tmp_path.joinpath(*parts, "kick.wav")
    assert wav.with_suffix(".json").is_file()
    assert library_folder(tmp_path, layout) == tmp_path.joinpath(*parts)


def test_library_folder_touches_nothing(tmp_path) -> None:
    folder = library_folder(tmp_path / "not-there")
    assert folder == tmp_path / "not-there" / "Samples" / "Drums" / "Kicks"
    assert list(tmp_path.iterdir()) == []


def test_existing_folders_and_their_files_are_kept(tmp_path) -> None:
    kicks = tmp_path / "Samples" / "Drums" / "Kicks"
    kicks.mkdir(parents=True)
    (kicks / "user.wav").write_bytes(b"user")
    (tmp_path / "Samples" / "loop.wav").write_bytes(b"loop")
    wav = place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert wav == kicks / "kick.wav"
    assert (kicks / "user.wav").read_bytes() == b"user"
    assert (tmp_path / "Samples" / "loop.wav").read_bytes() == b"loop"


def test_symlinked_project_folder_is_kept_in_the_returned_path(tmp_path) -> None:
    real = tmp_path / "real-project"
    real.mkdir()
    _symlink_or_skip(tmp_path / "linked", real, target_is_directory=True)
    wav = place_kick(FAST, tmp_path / "linked", created_at=FIXED_TIME)
    assert wav == tmp_path / "linked" / "Samples" / "Drums" / "Kicks" / "kick.wav"
    assert (real / "Samples" / "Drums" / "Kicks" / "kick.wav").is_file()


def test_symlinked_kick_folder_is_followed(tmp_path) -> None:
    real = tmp_path / "elsewhere"
    real.mkdir()
    project = tmp_path / "proj"
    (project / "Samples" / "Drums").mkdir(parents=True)
    _symlink_or_skip(project / "Samples" / "Drums" / "Kicks", real, target_is_directory=True)
    wav = place_kick(FAST, project, created_at=FIXED_TIME)
    assert wav == project / "Samples" / "Drums" / "Kicks" / "kick.wav"
    assert (real / "kick.wav").is_file() and (real / "kick.json").is_file()


# --- no overwrite (D-006) --------------------------------------------------------------------


def test_second_and_third_placement_never_overwrite(tmp_path) -> None:
    first = place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    before = first.read_bytes(), first.with_suffix(".json").read_bytes()
    second = place_kick({**FAST, "seed": 8}, tmp_path, created_at=FIXED_TIME)
    third = place_kick({**FAST, "seed": 9}, tmp_path, created_at=FIXED_TIME)
    assert [first.name, second.name, third.name] == ["kick.wav", "kick_002.wav", "kick_003.wav"]
    assert (first.read_bytes(), first.with_suffix(".json").read_bytes()) == before
    for wav in (first, second, third):
        meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
        assert meta["file"] == wav.name and meta["sha256"] == sha(wav.read_bytes())


@pytest.mark.parametrize("taken", ["kick.wav", "kick.json", "KICK_002.wav"])
def test_name_clash_with_foreign_file(tmp_path, taken: str) -> None:
    kicks = tmp_path / "Samples" / "Drums" / "Kicks"
    kicks.mkdir(parents=True)
    (kicks / taken).write_bytes(b"foreign")
    wav = place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert (kicks / taken).read_bytes() == b"foreign"
    if taken.startswith("kick."):
        assert wav.name == "kick_002.wav"
    else:  # only the same name blocks; on Windows KICK_002 is the same file as kick_002
        assert wav.name == "kick.wav"


@pytest.mark.parametrize("suffix", [".wav", ".json"])
def test_dangling_symlink_at_file_name_blocks_it(tmp_path, suffix: str) -> None:
    kicks = tmp_path / "Samples" / "Drums" / "Kicks"
    kicks.mkdir(parents=True)
    _symlink_or_skip(kicks / f"kick{suffix}", tmp_path / "missing-target")
    wav = place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert wav.name == "kick_002.wav"
    assert (kicks / f"kick{suffix}").is_symlink()
    assert not (tmp_path / "missing-target").exists()


@pytest.mark.parametrize("level", ["Samples", "Samples/Drums", "Samples/Drums/Kicks"])
def test_dangling_symlink_at_folder_is_refused(tmp_path, level: str) -> None:
    link = tmp_path / level
    link.parent.mkdir(parents=True, exist_ok=True)
    _symlink_or_skip(link, tmp_path / "missing-target", target_is_directory=True)
    before = tree(tmp_path)
    with pytest.raises(LibraryPathError, match="dangling symlink"):
        place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert tree(tmp_path) == before
    assert not (tmp_path / "missing-target").exists()


def test_symlink_loop_at_folder_is_refused(tmp_path) -> None:
    (tmp_path / "Samples").mkdir()
    loop = tmp_path / "Samples" / "Drums"
    _symlink_or_skip(loop, loop, target_is_directory=True)
    before = tree(tmp_path)
    with pytest.raises(LibraryPathError, match="cannot be created"):
        place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert tree(tmp_path) == before


@pytest.mark.parametrize("level", ["Samples", "Samples/Drums", "Samples/Drums/Kicks"])
def test_file_where_a_folder_belongs_is_refused(tmp_path, level: str) -> None:
    blocker = tmp_path / level
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_bytes(b"not a folder")
    before = tree(tmp_path)
    with pytest.raises(LibraryPathError, match="not a folder"):
        place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert tree(tmp_path) == before


def test_missing_project_folder_is_refused_and_not_created(tmp_path) -> None:
    with pytest.raises(LibraryPathError, match="does not exist"):
        place_kick(FAST, tmp_path / "no-such-project", created_at=FIXED_TIME)
    assert list(tmp_path.iterdir()) == []


def test_project_path_that_is_a_file_is_refused(tmp_path) -> None:
    (tmp_path / "set.als").write_bytes(b"als")
    with pytest.raises(LibraryPathError, match="not a folder"):
        place_kick(FAST, tmp_path / "set.als", created_at=FIXED_TIME)
    assert tree(tmp_path) == [("set.als", "file", b"als")]


def test_dangling_symlink_as_project_folder_is_refused(tmp_path) -> None:
    _symlink_or_skip(tmp_path / "proj", tmp_path / "gone", target_is_directory=True)
    with pytest.raises(LibraryPathError, match="does not exist"):
        place_kick(FAST, tmp_path / "proj", created_at=FIXED_TIME)
    assert not (tmp_path / "gone").exists()


# --- Windows names ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", RESERVED)
@pytest.mark.parametrize("form", ["plain", ".wav", ".tar.gz", "space-dot", "lower"])
def test_reserved_device_names_are_refused_as_folders(name: str, form: str) -> None:
    component = {
        "plain": name, ".wav": f"{name}.wav", ".tar.gz": f"{name}.tar.gz",
        "space-dot": f"{name} .x", "lower": name.lower(),
    }[form]
    assert windows_name_problem(component) is not None
    with pytest.raises(LibraryPathError):
        LibraryLayout(kicks=f"Samples/{component}")


@pytest.mark.parametrize("char", RESERVED_CHARS)
def test_reserved_characters_are_refused(char: str) -> None:
    assert windows_name_problem(f"Ki{char}cks") is not None
    if char not in "/\\":  # in a layout string these two separate folders
        with pytest.raises(LibraryPathError):
            LibraryLayout(kicks=f"Samples/Ki{char}cks")


@pytest.mark.parametrize(
    ("kicks", "message"),
    [("", "empty"), ("Samples//Kicks", "is empty"), ("Kicks/", "is empty"),
     ("Samples/./Kicks", "relative step"), ("../Kicks", "relative step"),
     ("Samples/..", "relative step"), ("Kicks.", "period"), ("Kicks ", "space"),
     ("/abs/Kicks", "relative to the project"), ("\\Kicks", "relative to the project"),
     ("C:\\Kicks", "relative to the project"), ("c:Kicks", "relative to the project"),
     ("\\\\server\\share\\Kicks", "relative to the project"), ("x" * 256, "255")],
)
def test_bad_layouts_are_refused(kicks: str, message: str) -> None:
    with pytest.raises(LibraryPathError, match=message):
        LibraryLayout(kicks=kicks)


@pytest.mark.parametrize("good", ["COM", "COM10", "LPT", "CONSOLE", "NUL1", "AUXILIARY",
                                  "x" * 255, ".hidden", "Kicks 2026", "kick-CON"])
def test_names_that_are_not_reserved_are_accepted(good: str) -> None:
    assert windows_name_problem(good) is None
    LibraryLayout(kicks=f"Samples/{good}")


@pytest.mark.parametrize("bad", [None, 3, b"Kicks", Path("Kicks")])
def test_layout_folder_must_be_a_string(bad) -> None:
    with pytest.raises(TypeError):
        LibraryLayout(kicks=bad)


@pytest.mark.parametrize("bad", [0, -1])
def test_max_path_chars_must_be_positive(bad: int) -> None:
    with pytest.raises(LibraryPathError):
        LibraryLayout(max_path_chars=bad)


@pytest.mark.parametrize("bad", [True, 259.0, "259"])
def test_max_path_chars_must_be_an_int(bad) -> None:
    with pytest.raises(TypeError):
        LibraryLayout(max_path_chars=bad)


def test_layout_must_be_a_library_layout(tmp_path) -> None:
    with pytest.raises(TypeError):
        place_kick(FAST, tmp_path, layout="Samples/Kicks")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [("CON", "kick-CON.wav"), ("nul.final", "kick-nul.final.wav"), ("a<b>c:d", "a-b-c-d.wav"),
     ("kick.", "kick.wav"), ("..\\..\\evil", "evil.wav"), ("", "kick.wav")],
)
def test_file_names_are_windows_safe(tmp_path, name: str, expected: str) -> None:
    wav = place_kick(FAST, tmp_path, name=name, created_at=FIXED_TIME)
    assert wav.name == expected
    assert wav.parent == tmp_path / "Samples" / "Drums" / "Kicks"


@pytest.mark.skipif(not hasattr(ntpath, "isreserved"),
                    reason="ntpath.isreserved needs Python >= 3.13")
@pytest.mark.parametrize("case", range(20))
def test_windows_name_rules_agree_with_ntpath_isreserved(case: int) -> None:
    """Independent reference: the standard library's Windows rules (Python 3.13+). CI runs
    3.12 and skips this; it runs on the user's 3.14 and on any 3.13+ box.

    ``isreserved`` takes a *path*: it splits on ``/`` and ``\\`` and reads ``X:`` as a drive.
    So the comparison covers single components only: no separator, no ``:`` as the second
    character, not ``.``/``..`` (relative steps, refused by us, not reserved for ntpath).
    Those cases are pinned by hand in the tests above."""
    rng = random.Random(6400 + 1000 + case)
    alphabet = "abcK. :" + "".join(c for c in RESERVED_CHARS[:14] if c not in "/\\") + "¹²$"
    names = [rng.choice(RESERVED) + rng.choice(["", ".x", " ", " .y", "."]) for _ in range(50)]
    names += ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8))) for _ in range(250)]
    for name in names:
        if name in (".", "..") or name[1:2] == ":":
            continue
        ours = windows_name_problem(name) is not None
        assert ours == ntpath.isreserved(name), (name, windows_name_problem(name))


def test_sidecar_and_asd_paths(tmp_path) -> None:
    wav = place_kick(FAST, tmp_path, name="a.b", created_at=FIXED_TIME)
    assert wav.name == "a.b.wav"
    assert sidecar_path(wav) == wav.parent / "a.b.json"
    assert sidecar_path(wav).is_file()
    assert longest_path(wav) == wav.parent / "a.b.wav.asd"
    assert sidecar_path(str(wav)) == wav.parent / "a.b.json"
    with pytest.raises(ValueError):
        sidecar_path(wav.parent / "a.b.json")


def test_path_chars_counts_utf16_code_units() -> None:
    assert path_chars("abc") == 3
    assert path_chars("Bässe") == 5
    assert path_chars("\U0001f941") == 2  # drum emoji: a surrogate pair on Windows
    assert path_chars(Path("a") / "b") == 3


# --- path length (MAX_PATH) ------------------------------------------------------------------


def test_default_limit_is_windows_max_path_minus_nul() -> None:
    assert LibraryLayout().max_path_chars == 259
    assert LibraryLayout().kicks == "Samples/Drums/Kicks"


def _limit_for_room(folder: Path, room: int) -> int:
    # room = characters left for the stem: folder + separator + stem + "_9999" + ".wav.asd"
    # (Live's analysis file next to the WAV is the longest name a placement leads to)
    return path_chars(folder) + 1 + room + 5 + 8


def _asd(wav: Path) -> Path:
    return wav.parent / (wav.name + ".asd")


@pytest.mark.parametrize("room", [16, 17, 40, 79, 80, 81, 200])
def test_long_name_is_cut_to_fit_the_limit(tmp_path, room: int) -> None:
    layout = LibraryLayout(max_path_chars=_limit_for_room(library_folder(tmp_path), room))
    name = "abcdefghij" * 20  # 200 characters; safe_stem keeps at most 80
    wav = place_kick(FAST, tmp_path, name=name, created_at=FIXED_TIME, layout=layout)
    assert wav.name == name[: min(room, 80)] + ".wav"
    assert wav.with_suffix(".json").is_file()
    assert path_chars(_asd(wav)) <= layout.max_path_chars


def test_cut_never_ends_on_a_period_or_dash(tmp_path) -> None:
    layout = LibraryLayout(max_path_chars=_limit_for_room(library_folder(tmp_path), 20))
    name = "a" * 18 + "-." + "b" * 30  # cut at 20 lands right after "-."
    wav = place_kick(FAST, tmp_path, name=name, created_at=FIXED_TIME, layout=layout)
    assert wav.name == "a" * 18 + ".wav"


def test_cut_is_applied_after_making_the_name_safe(tmp_path) -> None:
    """Runs of unsafe characters collapse to one '-' first; the cut then fills the room."""
    layout = LibraryLayout(max_path_chars=_limit_for_room(library_folder(tmp_path), 16))
    name = "a" * 10 + "<<<<<<" + "b" * 30
    wav = place_kick(FAST, tmp_path, name=name, created_at=FIXED_TIME, layout=layout)
    assert wav.name == "aaaaaaaaaa-bbbbb.wav"


def test_cut_that_leaves_a_device_name_still_fits(tmp_path) -> None:
    layout = LibraryLayout(max_path_chars=_limit_for_room(library_folder(tmp_path), 16))
    wav = place_kick(FAST, tmp_path, name="CON" + "-" * 13 + "tail" * 5, created_at=FIXED_TIME,
                     layout=layout)
    assert wav.name == "kick-CON.wav"


@pytest.mark.parametrize("room", [15, 1, -50])
def test_too_long_project_path_is_refused_before_anything_is_written(tmp_path, room) -> None:
    layout = LibraryLayout(max_path_chars=max(1, _limit_for_room(library_folder(tmp_path), room)))
    with pytest.raises(LibraryPathError, match="MAX_PATH"):
        place_kick(FAST, tmp_path, created_at=FIXED_TIME, layout=layout)
    assert list(tmp_path.iterdir()) == []


def test_long_real_path_on_this_file_system(tmp_path) -> None:
    """A project folder close to 259 characters: the default limit cuts or refuses, and the
    file that is written really exists at the returned path."""
    room = 22  # characters left for the stem
    # folder = tmp + "/" + project + "/Samples/Drums/Kicks"; file = folder + "/" + stem
    # + "_9999" + ".wav.asd" must be exactly 259 characters
    depth_chars = 259 - (path_chars(tmp_path) + 1 + 20 + 1 + room + 5 + 8)
    if depth_chars < 20:
        pytest.skip(f"temp folder too long for this test ({path_chars(tmp_path)} chars)")
    project = tmp_path / ("p" * depth_chars)
    try:
        project.mkdir()
    except OSError as exc:  # Windows without long-path support in the test runner
        pytest.skip(f"cannot create a {path_chars(project)}-character folder here: {exc}")
    wav = place_kick(FAST, project, name="n" * 60, created_at=FIXED_TIME)
    assert wav.name == "n" * room + ".wav"
    assert path_chars(_asd(wav)) == 259 - 5  # no counter used: the 5 reserved stay free
    assert path_chars(wav.with_suffix(".json")) == 259 - 5 - 3
    assert wav.is_file() and wav.with_suffix(".json").is_file()
    deeper = project / ("q" * 6)  # 7 more characters: room 15 < 16
    deeper.mkdir()
    with pytest.raises(LibraryPathError, match="MAX_PATH"):
        place_kick(FAST, deeper, created_at=FIXED_TIME)
    assert list(deeper.iterdir()) == []


def test_counter_up_to_9999_still_fits(tmp_path) -> None:
    folder = library_folder(tmp_path)
    folder.mkdir(parents=True)
    layout = LibraryLayout(max_path_chars=_limit_for_room(folder, 16))
    stem = "k" * 16
    for i in range(2, 9999):
        (folder / f"{stem}_{i:03d}.wav").touch()
    (folder / f"{stem}.json").touch()
    wav = place_kick(FAST, tmp_path, name=stem, created_at=FIXED_TIME, layout=layout)
    assert wav.name == f"{stem}_9999.wav"
    assert path_chars(_asd(wav)) == layout.max_path_chars


def test_counter_beyond_the_reserve_is_refused_and_removed(tmp_path) -> None:
    folder = library_folder(tmp_path)
    folder.mkdir(parents=True)
    layout = LibraryLayout(max_path_chars=_limit_for_room(folder, 16))
    stem = "k" * 16
    for i in range(2, 10000):
        (folder / f"{stem}_{i:03d}.wav").touch()
    (folder / f"{stem}.json").touch()
    before = tree(tmp_path)
    with pytest.raises(LibraryPathError, match="too many files"):
        place_kick(FAST, tmp_path, name=stem, created_at=FIXED_TIME, layout=layout)
    assert tree(tmp_path) == before


def test_limit_off_allows_long_paths(tmp_path) -> None:
    layout = LibraryLayout(max_path_chars=None)
    wav = place_kick(FAST, tmp_path, name="z" * 200, created_at=FIXED_TIME, layout=layout)
    assert wav.name == "z" * 80 + ".wav"


# --- property test over names, layouts and parameters ----------------------------------------

_NAME_ALPHABET = string.printable + "äöüßÄé€¹²³\U0001f941" + "".join(RESERVED_CHARS)


def _random_name(rng: random.Random) -> str:
    if rng.random() < 0.2:
        return rng.choice(RESERVED) + rng.choice(["", ".wav", ".x.y", " "])
    return "".join(rng.choice(_NAME_ALPHABET) for _ in range(rng.randint(0, 120)))


def _random_component(rng: random.Random) -> str:
    alphabet = string.ascii_letters + string.digits + " _-.äé"
    while True:
        comp = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 24)))
        if comp[-1] not in " ." and comp not in (".", ".."):
            return comp


def _random_params(rng: random.Random) -> dict:
    """Every kick-params field over its full contract range (contracts/kick-params.schema.json,
    v0.2), limits written out here. Length is mostly short to keep the run fast, sometimes
    long up to the 2000 ms maximum."""
    end = rng.uniform(30, 120)
    params = {
        "schema_version": "0.2",
        "seed": rng.randint(0, 2**32 - 1),
        "length_ms": rng.uniform(80, 200) if rng.random() < 0.8 else rng.uniform(200, 2000),
        "pitch_start_hz": rng.uniform(max(60, end), 600),  # contract: end <= start
        "pitch_end_hz": end,
        "pitch_decay_ms": rng.uniform(2, 300),
        "amp_attack_ms": rng.uniform(0, 20),
        "amp_decay_ms": rng.uniform(20, 2000),
        "click_level": rng.uniform(0, 1),
        "click_tone_hz": rng.uniform(500, 12000),
        "drive": rng.choice([0.0, rng.uniform(0, 1)]),
        "tone": rng.uniform(-1, 1),
        "peak_ceiling_dbfs": rng.uniform(-12, -0.1),
        "bit_depth": rng.choice([16, 24]),
        "sample_rate": rng.choice([44100, 48000]),
    }
    if rng.random() < 0.5:
        params["bpm"] = rng.uniform(60, 200)
    return params


@pytest.mark.parametrize("case", range(40))
def test_random_placements_keep_every_rule(tmp_path, case: int) -> None:
    rng = random.Random(6400 + case)
    parts = [_random_component(rng) for _ in range(rng.randint(1, 4))]
    sep = rng.choice(["/", "\\"])
    project = tmp_path / "proj"
    project.mkdir()
    folder = project.joinpath(*parts)
    # rooms below 16 must be refused, 16 and above must fit
    limit = rng.choice([None, 259, _limit_for_room(folder, rng.randint(8, 90))])
    layout = LibraryLayout(kicks=sep.join(parts), max_path_chars=limit)
    if rng.random() < 0.5:  # some folders already exist, some files clash
        folder.mkdir(parents=True)
    names = [_random_name(rng) for _ in range(rng.randint(1, 3))]
    if rng.random() < 0.5:
        names.append(names[0])  # same name twice → counter
    written = []
    for name in names:
        try:
            wav = place_kick(_random_params(rng), project, name=name, created_at=FIXED_TIME,
                             layout=layout)
        except LibraryPathError:
            assert limit is not None
            assert path_chars(folder) + 1 + 16 + 5 + 8 > limit
            continue
        if limit is not None:  # it fitted, so it must have been allowed
            assert path_chars(folder) + 1 + 16 + 5 + 8 <= limit
        written.append(wav)
        sidecar = wav.with_name(wav.name[: -len(".wav")] + ".json")
        assert wav.is_absolute() and wav.parent == folder
        assert wav.suffix == ".wav" and sidecar.is_file()
        for p in (wav, sidecar):
            assert windows_name_problem(p.name) is None, p.name
            assert all(ch in string.ascii_letters + string.digits + "._-" for ch in p.name)
        if limit is not None:
            assert path_chars(_asd(wav)) <= limit
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        VALIDATOR.validate(meta)
        assert meta["file"] == wav.name
        assert meta["sha256"] == sha(wav.read_bytes())
    assert len(set(written)) == len(written)
    # nothing outside the kick folder, and nothing in it except the pairs written here
    expected = {p.relative_to(project).as_posix() for w in written for p in
                (w, w.with_suffix(".json"))}
    expected |= {"/".join(parts[: i + 1]) for i in range(len(parts))} if (
        written or folder.exists()) else set()
    assert {p for p, *_ in tree(project)} == expected


@pytest.mark.parametrize("case", range(6))
def test_random_placements_rerender_byte_identically(tmp_path, case: int) -> None:
    rng = random.Random(6464 + case)
    wav = place_kick(_random_params(rng), tmp_path, name=_random_name(rng),
                     created_at=FIXED_TIME)
    assert rerender_from_sidecar(wav.with_suffix(".json")) == wav.read_bytes()


# --- failure paths: nothing half-written, created folders removed ----------------------------


class _BrokenWrite:
    def __init__(self, f, exc):
        self._f, self._exc = f, exc

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()
        return False

    def write(self, _data):
        raise self._exc


def _break_writes(monkeypatch, suffix: str, exc: BaseException) -> None:
    import builtins

    real_open = builtins.open

    def broken_open(file, mode="r", *args, **kwargs):
        f = real_open(file, mode, *args, **kwargs)
        return _BrokenWrite(f, exc) if str(file).endswith(suffix) else f

    monkeypatch.setattr(io_mod, "open", broken_open, raising=False)


FAILURES = [
    pytest.param(".wav", OSError(28, "No space left on device (simulated)"), id="wav-disk-full"),
    pytest.param(".json", OSError(28, "No space left on device (simulated)"), id="json-disk-full"),
    pytest.param(".wav", PermissionError(13, "Permission denied (simulated)"), id="wav-perm"),
    pytest.param(".json", KeyboardInterrupt(), id="json-ctrl-c"),
    pytest.param(".wav", KeyboardInterrupt(), id="wav-ctrl-c"),
]


@pytest.mark.parametrize(("suffix", "exc"), FAILURES)
def test_write_failure_in_new_folders_leaves_the_project_as_it_was(
    tmp_path, monkeypatch, suffix: str, exc: BaseException
) -> None:
    (tmp_path / "set.als").write_bytes(b"als")
    before = tree(tmp_path)
    _break_writes(monkeypatch, suffix, exc)
    with pytest.raises(type(exc)):
        place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert tree(tmp_path) == before


@pytest.mark.parametrize(("suffix", "exc"), FAILURES)
def test_write_failure_in_existing_folders_keeps_them_and_their_files(
    tmp_path, monkeypatch, suffix: str, exc: BaseException
) -> None:
    kicks = tmp_path / "Samples" / "Drums" / "Kicks"
    kicks.mkdir(parents=True)
    first = place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    before = tree(tmp_path)
    _break_writes(monkeypatch, suffix, exc)
    with pytest.raises(type(exc)):
        place_kick({**FAST, "seed": 8}, tmp_path, created_at=FIXED_TIME)
    assert tree(tmp_path) == before
    assert first.is_file()


@pytest.mark.parametrize("existing", ["Samples", "Samples/Drums", "Samples/Drums/Kicks"])
def test_existing_empty_folders_survive_a_failed_write(tmp_path, monkeypatch, existing) -> None:
    (tmp_path / existing).mkdir(parents=True)
    before = tree(tmp_path)
    _break_writes(monkeypatch, ".wav", OSError(28, "No space left on device (simulated)"))
    with pytest.raises(OSError):
        place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert tree(tmp_path) == before


def test_partly_existing_layout_removes_only_the_new_folders(tmp_path, monkeypatch) -> None:
    (tmp_path / "Samples").mkdir()
    (tmp_path / "Samples" / "keep.wav").write_bytes(b"keep")
    before = tree(tmp_path)
    _break_writes(monkeypatch, ".wav", OSError(28, "No space left on device (simulated)"))
    with pytest.raises(OSError):
        place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert tree(tmp_path) == before


def test_bad_parameters_leave_no_folders(tmp_path) -> None:
    with pytest.raises(KickParamsError):
        place_kick({**FAST, "drive": 2.0}, tmp_path, created_at=FIXED_TIME)
    assert list(tmp_path.iterdir()) == []


def test_naive_created_at_leaves_no_folders(tmp_path) -> None:
    with pytest.raises(ValueError):
        place_kick(FAST, tmp_path, created_at=datetime(2026, 10, 28, 12, 0))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("fail_at", [1, 2, 3])
@pytest.mark.parametrize("exc", [PermissionError(13, "Permission denied (simulated)"),
                                 OSError(28, "No space left on device (simulated)"),
                                 KeyboardInterrupt()], ids=["perm", "full", "ctrl-c"])
def test_folder_creation_failure_removes_folders_made_so_far(
    tmp_path, monkeypatch, fail_at: int, exc: BaseException
) -> None:
    real_mkdir = os.mkdir
    calls = {"n": 0}

    def failing_mkdir(path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == fail_at:
            raise exc
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(layout_mod.os, "mkdir", failing_mkdir)
    with pytest.raises(type(exc)):
        place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    monkeypatch.undo()
    assert list(tmp_path.iterdir()) == []


def test_foreign_file_written_meanwhile_keeps_its_folder(tmp_path, monkeypatch) -> None:
    """A folder this call created but someone else wrote into is not removed on failure."""

    def write_kick_with_neighbour(params, out_dir, **kwargs):
        (Path(out_dir) / "neighbour.wav").write_bytes(b"theirs")
        raise OSError(28, "No space left on device (simulated)")

    monkeypatch.setattr(layout_mod, "write_kick", write_kick_with_neighbour)
    with pytest.raises(OSError):
        place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert tree(tmp_path) == [
        ("Samples", "dir", None), ("Samples/Drums", "dir", None),
        ("Samples/Drums/Kicks", "dir", None),
        ("Samples/Drums/Kicks/neighbour.wav", "file", b"theirs"),
    ]


def test_name_taken_between_check_and_write_still_never_overwrites(tmp_path, monkeypatch) -> None:
    real_unique_pair = io_mod._unique_pair
    calls = {"n": 0}

    def racing_unique_pair(out, stem):
        wav, js = real_unique_pair(out, stem)
        if calls["n"] == 0:
            wav.write_bytes(b"other")
        calls["n"] += 1
        return wav, js

    monkeypatch.setattr(io_mod, "_unique_pair", racing_unique_pair)
    wav = place_kick(FAST, tmp_path, created_at=FIXED_TIME)
    assert wav.name == "kick_002.wav"
    assert (wav.parent / "kick.wav").read_bytes() == b"other"


def test_real_read_only_folder_is_reported_and_leaves_nothing(tmp_path) -> None:
    if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        pytest.skip("POSIX permissions do not bind here (Windows or root)")
    kicks = tmp_path / "Samples" / "Drums" / "Kicks"
    kicks.mkdir(parents=True)
    kicks.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            place_kick(FAST, tmp_path, created_at=FIXED_TIME)
        assert list(kicks.iterdir()) == []
    finally:
        kicks.chmod(0o755)
