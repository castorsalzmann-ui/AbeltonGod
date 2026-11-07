"""Kit export (#498, D-032): copy one sample per slot into a kit folder with a ``kit.json``. No Qt.
Files only: nothing here talks to Ableton (no Drum Rack, no Live write; those capabilities are
not tested).

Format: ``contracts/kit.schema.json`` v0.1 and docs/INTERFACES.md "Kit manifest".

* :func:`plan_kit` checks the picks (the kick slot filled, the others optional; each file a
  readable library WAV of the slot's category below the output folder), hashes the sources and
  chooses the copy names. It writes nothing.
* :func:`export_kit` builds the kit in a fresh temporary folder next to the kits, checks every
  copy's bytes against the planned SHA-256, writes ``kit.json`` (validated first) and only then
  renames the folder to ``<name>``, ``<name>_002`` ... A kit folder is never overwritten. On any
  failure (disk full, a source changed, Ctrl+C) the temporary folder and the folders this call
  created are removed, so no half kit is left. Not covered: a power cut or a killed process
  leaves a ``.kit-tmp-*`` folder (never a folder with a kit name).
* :func:`prefill` proposes picks from the choice log: per slot the newest current favourite
  (by parsed instant, never by string) whose file is in the library.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from audio_engine.io import safe_stem
from gui_core.choices import instant, utc_now
from gui_core.library import LibraryEntry, read_entry
from library.layout import WINDOWS_MAX_PATH_CHARS, path_chars

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA_FILE = CONTRACTS_DIR / "kit.schema.json"
KITS_FOLDER = ("Samples", "Kits")
MANIFEST = "kit.json"
MAX_SUFFIX = 999  # <name>_002 … <name>_999
SUFFIX_RESERVE = "_999"
MIN_STEM_CHARS = 8
TMP_PREFIX = ".kit-tmp-"
TMP_HEX = 6  # random bytes in the temporary folder's name (12 hex characters)
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Slot:
    key: str  # key in kit.json "slots"
    label: str  # German, for the GUI
    categories: tuple[str, ...]
    tag: str  # in the copy's name; "" = the file's category
    required: bool = False  # only the kick is required (lead decision on PR #502)
    prefers: str = ""  # prefill: preset containing this word first ("!open" = not containing)


SLOTS: tuple[Slot, ...] = (
    Slot("kick", "Kick", ("kick",), "kick", required=True),
    Slot("clap_snare", "Clap / Snare", ("clap", "snare"), ""),
    Slot("closed_hat", "Hat geschlossen", ("hat",), "hat-closed", prefers="!open"),
    Slot("open_hat", "Hat offen", ("hat",), "hat-open", prefers="open"),
    Slot("rim", "Rim", ("rim",), "rim"),
    Slot("perc", "Perc", ("perc",), "perc"),
    Slot("bass", "Bass", ("bass",), "bass"),
)
SLOT_BY_KEY = {s.key: s for s in SLOTS}


class KitError(ValueError):
    """The kit cannot be planned or exported (message in German); nothing was left behind."""


_validator: Draft202012Validator | None = None


def problems(doc) -> list[str]:
    """Contract errors of a kit manifest (empty = valid)."""
    global _validator
    if _validator is None:
        _validator = Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(kit)'}: {e.message}"
            for e in _validator.iter_errors(doc)]


def kits_dir(output_dir: Path) -> Path:
    return Path(os.path.abspath(output_dir)).joinpath(*KITS_FOLDER)


def in_kits(path: Path, output_dir: Path) -> bool:
    """True for a file inside an exported kit (or a leftover temporary kit folder)."""
    try:
        Path(os.path.abspath(path)).relative_to(kits_dir(output_dir))
    except ValueError:
        return False
    return True


def candidates(slot: Slot, entries: Iterable[LibraryEntry], output_dir: Path) -> list[LibraryEntry]:
    """Readable library entries that fit ``slot``, kit copies left out, in library order."""
    return [e for e in entries if e.readable and e.category in slot.categories
            and not in_kits(e.wav_path, output_dir)]


# --- plan ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class KitItem:
    slot: str
    source: Path  # absolute
    source_rel: str  # relative to the output dir, "/" separated
    sha256: str
    category: str
    file: str  # name of the copy in the kit folder


@dataclass(frozen=True)
class KitPlan:
    output_dir: Path
    name: str
    items: tuple[KitItem, ...]

    @property
    def kits_dir(self) -> Path:
        return kits_dir(self.output_dir)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def plan_kit(output_dir: Path, name: str, picks: Mapping[str, Path | None],
             max_path_chars: int | None = WINDOWS_MAX_PATH_CHARS) -> KitPlan:
    """Check the picks and choose the copy names. Raises :class:`KitError`; writes nothing."""
    out = Path(os.path.abspath(output_dir))
    if not name.strip():
        raise KitError("Bitte einen Kit-Namen eingeben.")
    unknown = sorted(set(picks) - set(SLOT_BY_KEY))
    if unknown:
        raise KitError(f"Unbekannter Slot: {unknown[0]}")
    kit_name = safe_stem(name, "kit")
    # The copies are written in the temporary folder first: the longer of the two names counts.
    longest_folder = max(kit_name + SUFFIX_RESERVE, TMP_PREFIX + "0" * TMP_HEX * 2, key=len)
    folder = kits_dir(out) / longest_folder
    items = []
    for number, slot in enumerate(SLOTS, start=1):
        pick = picks.get(slot.key)
        if pick is None:
            if slot.required:
                raise KitError(f"{slot.label}: keine Datei gewählt.")
            continue
        src = Path(os.path.abspath(pick))
        try:
            rel = src.resolve().relative_to(out.resolve()).as_posix()
        except (OSError, ValueError):
            raise KitError(f"{slot.label}: {src.name} liegt nicht im Ausgabeordner.") from None
        entry = read_entry(src)
        if not entry.readable:
            raise KitError(f"{slot.label}: {src.name} ist unlesbar ({entry.problem}).")
        if entry.category not in slot.categories:
            raise KitError(f"{slot.label}: {src.name} ist {entry.category}, erwartet "
                           f"{' oder '.join(slot.categories)}.")
        try:
            sha = file_sha256(src)
        except OSError as exc:
            raise KitError(f"{slot.label}: {src.name} nicht lesbar ({type(exc).__name__}).") \
                from None
        tag = slot.tag or entry.category
        prefix = f"{number:02d}_{tag}_"
        stem = safe_stem(src.stem, tag)
        if max_path_chars is not None:
            # Longest path in the kit: Live's analysis file <copy>.wav.asd.
            room = (max_path_chars - path_chars(folder) - 1 - len(prefix)
                    - len(".wav.asd"))
            if room < MIN_STEM_CHARS:
                raise KitError(
                    f"Kit-Pfad zu lang: {folder} hat {path_chars(folder)} Zeichen, über die "
                    f"Windows-Grenze von {max_path_chars}. Kürzeren Namen oder Ausgabeordner "
                    "wählen.")
            stem = stem[:room].rstrip("-.") or tag
        items.append(KitItem(slot.key, src, rel, sha, entry.category, f"{prefix}{stem}.wav"))
    return KitPlan(out, kit_name, tuple(items))


def manifest(plan: KitPlan, created_at: str) -> dict:
    return {
        "schema_version": "0.1",
        "name": plan.name,
        "created_at": created_at,
        "slots": {i.slot: {"file": i.file, "sha256": i.sha256, "source": i.source_rel,
                           "category": i.category} for i in plan.items},
    }


# --- export ----------------------------------------------------------------------------------

def _copy_file(src: Path, dst: Path) -> str:
    """Copy bytes into a new file (never overwrites), fsync, return the copy's SHA-256."""
    h = hashlib.sha256()
    with open(src, "rb") as fin, open(dst, "xb") as fout:
        while chunk := fin.read(_CHUNK):
            fout.write(chunk)
            h.update(chunk)
        fout.flush()
        os.fsync(fout.fileno())
    return h.hexdigest()


def _write_new(path: Path, data: bytes) -> None:
    with open(path, "xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


_rename = os.rename  # one name, so a test can make the final step fail


def export_kit(plan: KitPlan, now: str | None = None) -> Path:
    """Write the kit of ``plan``; returns the new kit folder. Raises :class:`KitError` or
    ``OSError``; after any failure nothing of this call is left (see the module doc)."""
    created_at = now or utc_now()
    doc = manifest(plan, created_at)
    found = problems(doc)
    if found:
        raise KitError("Kit passt nicht zum Format: " + found[0])
    out = plan.output_dir
    if not out.is_dir():
        raise KitError(f"Ausgabeordner {out} fehlt.")
    made: list[Path] = []
    tmp: Path | None = None
    done = False
    try:
        current = out
        for part in KITS_FOLDER:
            current = current / part
            try:
                os.mkdir(current)
                made.append(current)
            except FileExistsError:
                if not current.is_dir():
                    raise KitError(f"{current} ist kein Ordner.") from None
        tmp = current / f"{TMP_PREFIX}{secrets.token_hex(TMP_HEX)}"
        os.mkdir(tmp)
        for item in plan.items:
            got = _copy_file(item.source, tmp / item.file)
            if got != item.sha256:
                raise KitError(f"{item.source.name} hat sich seit der Auswahl geändert; "
                               "Kit nicht erstellt.")
            side = item.source.with_suffix(".json")
            _copy_file(side, (tmp / item.file).with_suffix(".json"))  # verbatim
        _write_new(tmp / MANIFEST,
                   (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        final = _rename_free(tmp, current, plan.name)
        done = True
        return final
    except FileNotFoundError as exc:
        raise KitError(f"Datei fehlt: {Path(exc.filename or '').name}; Kit nicht erstellt.") \
            from None
    finally:
        if not done:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
            for folder in reversed(made):
                try:
                    os.rmdir(folder)
                except OSError:
                    pass


def _rename_free(tmp: Path, parent: Path, name: str) -> Path:
    """Rename ``tmp`` to the first free ``name``, ``name_002`` … Never replaces a folder that
    holds anything (POSIX rename may replace an *empty* folder that appeared meanwhile; Windows
    refuses)."""
    for n in range(1, MAX_SUFFIX + 1):
        target = parent / (name if n == 1 else f"{name}_{n:03d}")
        if os.path.lexists(target):
            continue
        try:
            _rename(tmp, target)
        except OSError as exc:
            if isinstance(exc, FileExistsError) or exc.errno in (errno.EEXIST, errno.ENOTEMPTY):
                continue
            raise
        return target
    raise KitError(f"Schon {MAX_SUFFIX} Kits namens {name}; bitte anderen Namen wählen.")


# --- prefill from favourites -----------------------------------------------------------------

def favourites_newest_first(log_entries: list[dict]) -> list[str]:
    """SHA-256 of the files whose current verdict is favourite, newest verdict first (parsed
    instant; equal instants: the later line counts as newer)."""
    best: dict[str, tuple] = {}
    for i, e in enumerate(log_entries):
        sha = e["sample"]["sha256"]
        if sha is None:
            continue
        key = (instant(e["time"]), i)
        if sha not in best or key > best[sha][0]:
            best[sha] = (key, e["verdict"])
    favs = [(key, sha) for sha, (key, verdict) in best.items() if verdict == "favourite"]
    return [sha for _, sha in sorted(favs, reverse=True)]


def _preferred(slot: Slot, entry: LibraryEntry) -> bool:
    if not slot.prefers:
        return True
    word = slot.prefers.lstrip("!")
    has = word in entry.preset.lower()
    return not has if slot.prefers.startswith("!") else has


def prefill(entries: list[LibraryEntry], log_entries: list[dict], output_dir: Path,
            sha_of: Callable[[Path], str | None]) -> dict[str, Path | None]:
    """Proposed pick per slot: the newest favourite of the slot's categories not used by an
    earlier slot (the hat slots look at the preset name first: "open" for the open hat).
    Slots without a fitting favourite stay None."""
    order = favourites_newest_first(log_entries)
    if not order:
        return {s.key: None for s in SLOTS}
    rank = {sha: i for i, sha in enumerate(order)}
    pool: list[tuple[int, LibraryEntry, str]] = []
    seen: set[str] = set()
    for e in entries:
        if not e.readable or in_kits(e.wav_path, output_dir):
            continue
        if not any(e.category in s.categories for s in SLOTS):
            continue
        sha = sha_of(e.wav_path)
        if sha in rank and sha not in seen:  # byte-identical copies: the first listed one
            seen.add(sha)
            pool.append((rank[sha], e, sha))
    pool.sort(key=lambda p: p[0])
    used: set[str] = set()
    out: dict[str, Path | None] = {}
    for slot in SLOTS:
        fits = [p for p in pool if p[1].category in slot.categories and p[2] not in used]
        pick = next((p for p in fits if _preferred(slot, p[1])), fits[0] if fits else None)
        out[slot.key] = pick[1].wav_path if pick else None
        if pick:
            used.add(pick[2])
    return out
