"""Install the AbeltonGod extension into the user's AbletonOSC (Phase 03 #50, #140).

The extension edits two files of the user's installed AbletonOSC. Both are pinned to
AbletonOSC commit ``0ca68214``; every line reference below is to that commit. AbletonOSC
itself is not copied into this repo; this script only edits the user's installed copy.

1. ``abletonosc/clip_slot.py`` (#50, option A of
   ``docs/research/2026-10-28_abletonosc-protocol-and-create-audio-clip.md``): one word added
   to the ``methods`` list, so that AbletonOSC registers ``/live/clip_slot/create_audio_clip``
   with its generic ``_call_method`` (``clip_slot.py`` lines 27-32 and 46-48). The patched
   bytes are exactly those of script 0.1.0, so an existing install is recognised as patched.
2. ``abletonosc/track.py`` (#140, ``docs/research/2026-10-29_live-midi-arrangement-devices.md``
   Q6): ``"create_midi_clip"`` added to the ``methods`` list (lines 32-35, registered at
   62-64), which gives ``/live/track/create_midi_clip track start length`` ->
   ``Track.create_midi_clip(start, length)``; and two own handlers after line 109 for the
   notes of Arrangement clips, because every ``/live/clip/*`` handler resolves
   ``track.clip_slots[i].clip`` (``clip.py`` lines 53-55) and so reaches Session clips only.
   They use ``track.arrangement_clips[i]`` with the same Live calls as ``clip.py`` line 139
   (``get_notes_extended``) and lines 145-155 (``MidiNoteSpecification`` + ``add_new_notes``).

Safety (each file on its own, same rules as script 0.1.0):
- A file is only patched if its content (line endings normalised) is exactly the known
  original of commit ``0ca68214`` (SHA-256 below). It counts as patched only if undoing our
  replacements gives exactly that original. Any other version is refused.
- **All or nothing before writing:** every file is classified and every existing backup is
  checked before the first write. One unknown or missing file, or one foreign backup, and
  nothing is written at all.
- Before patching, the original is saved next to it as ``<name>.abeltongod-orig`` (temp file
  + fsync + rename, so it is never half-written). An existing backup is never overwritten
  (D-006) and is reused only if its raw bytes equal the current unpatched file (so
  ``--uninstall`` restores exactly the user's file, line endings included); otherwise the
  install is refused. A patch is written only after its backup reads back byte-identical.
  An unreadable path (a folder, no permission) ends with a message, not a traceback.
- The new file is written to a temporary file in the same folder and moved over the original
  in one step (``os.replace``); it must compile as Python first.
- Files are written one after the other. Each one is always either the original or the
  patched version (never half-written); if a later file fails, the earlier ones stay patched
  (with their backup), the output says which, and a re-run patches the rest.
- ``--uninstall`` puts the backups back (only for files that are exactly our patched version,
  and only if every such file has a valid backup).
- Default-No prompt before any write. ``--check`` only reports.

Live reads remote scripts at start: close Live before installing, restart it afterwards.

User-facing text is German; code and comments are English.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

# 0.2.0 (#140): second pinned file abletonosc/track.py (Arrangement MIDI clip + notes).
SCRIPT_VERSION = "0.2.0"

PINNED_COMMIT = "0ca68214bd62c9b5cb641ca34006cfd70ba94430"

BACKUP_SUFFIX = ".abeltongod-orig"

EXIT_OK = 0
EXIT_REFUSED = 1  # unknown version, missing folder, user said no
EXIT_ERROR = 2  # write failed
EXIT_INTERRUPTED = 130

YES = {"y", "yes", "j", "ja"}

STATE_ORIGINAL = "original"
STATE_PATCHED = "patched"
STATE_UNKNOWN = "unknown"
STATE_MISSING = "missing"


@dataclass(frozen=True)
class PatchSpec:
    """One pinned file and the exact text replacements of the extension in it."""

    relative: Path  # inside the AbletonOSC folder
    known_original: str  # SHA-256 of the pinned original, LF line endings
    replacements: tuple[tuple[str, str], ...]  # (old, new); each old occurs exactly once
    summary: str  # German, for the plan

    @property
    def name(self) -> str:
        return self.relative.name


# -- clip_slot.py (#50) ---------------------------------------------------------------------
# SHA-256 of abletonosc/clip_slot.py at PINNED_COMMIT with LF line endings (2811 bytes,
# 67 lines; computed 2026-10-28 from raw.githubusercontent.com and from a git clone; re-checked
# 2026-10-29).
KNOWN_ORIGINAL_SHA256 = "989f9f6a6631fd04598fff0b278b9d844e03b3e211ae9b23d293e985b22d4aed"

# The exact text of the methods list end (clip_slot.py lines 31-32) and its replacement.
PATCH_OLD = '            "delete_clip"\n        ]\n'
PATCH_NEW = ('            "delete_clip",\n'
             '            "create_audio_clip"  # added by AbeltonGod (#50)\n'
             '        ]\n')

# -- track.py (#140) ------------------------------------------------------------------------
# SHA-256 of abletonosc/track.py at PINNED_COMMIT with LF line endings (15550 bytes, 274
# lines; computed 2026-10-29 from raw.githubusercontent.com).
TRACK_KNOWN_ORIGINAL_SHA256 = "512a92ff0a08c7ba8276c3b5f06fbff3f55863b18a51bef3ee0837eceb55ed4a"

# track.py lines 33-35: end of the methods list.
TRACK_METHODS_OLD = ('            "delete_device",\n'
                     '            "stop_all_clips"\n'
                     '        ]\n')
TRACK_METHODS_NEW = ('            "delete_device",\n'
                     '            "stop_all_clips",\n'
                     '            "create_midi_clip"  # added by AbeltonGod (#140)\n'
                     '        ]\n')

# track.py line 109: the handler registration after which the note handlers are inserted.
TRACK_ANCHOR = ('        self.osc_server.add_handler("/live/track/delete_clip", '
                'create_track_callback(track_delete_clip))\n')
TRACK_NOTE_HANDLERS = '''
        # ---- added by AbeltonGod (#140): notes of Arrangement clips -----------------------
        # /live/clip/* resolves track.clip_slots[i].clip (Session clips only), so these two
        # address track.arrangement_clips[i]. Same Live calls as clip.py (get/add notes).
        def abeltongod_arrangement_clip_get_notes(track, params: Tuple[Any]):
            clip_index = int(params[0])
            clip = track.arrangement_clips[clip_index]
            rv = [clip_index]
            for note in clip.get_notes_extended(0, 127, -8192, 16384):
                rv += [note.pitch, note.start_time, note.duration, note.velocity, note.mute]
            return tuple(rv)

        def abeltongod_arrangement_clip_add_notes(track, params: Tuple[Any]):
            import Live
            clip_index = int(params[0])
            values = params[1:]
            if not values or len(values) % 5:
                raise ValueError("notes must be groups of 5: pitch start duration velocity mute")
            clip = track.arrangement_clips[clip_index]
            notes = []
            for offset in range(0, len(values), 5):
                pitch, start_time, duration, velocity, mute = values[offset:offset + 5]
                notes.append(Live.Clip.MidiNoteSpecification(start_time=float(start_time),
                                                             duration=float(duration),
                                                             pitch=int(pitch),
                                                             velocity=float(velocity),
                                                             mute=bool(mute)))
            clip.add_new_notes(tuple(notes))

        self.osc_server.add_handler("/live/track/arrangement_clip/get/notes",
                                    create_track_callback(abeltongod_arrangement_clip_get_notes))
        self.osc_server.add_handler("/live/track/arrangement_clip/add/notes",
                                    create_track_callback(abeltongod_arrangement_clip_add_notes))
        # ---- end of AbeltonGod (#140) ------------------------------------------------------
'''

PATCHES: tuple[PatchSpec, ...] = (
    PatchSpec(Path("abletonosc") / "clip_slot.py", KNOWN_ORIGINAL_SHA256,
              ((PATCH_OLD, PATCH_NEW),),
              'das Wort "create_audio_clip" in die Liste \'methods\' eintragen (eine Zeile; '
              "Kick-Import, #50)"),
    PatchSpec(Path("abletonosc") / "track.py", TRACK_KNOWN_ORIGINAL_SHA256,
              ((TRACK_METHODS_OLD, TRACK_METHODS_NEW),
               (TRACK_ANCHOR, TRACK_ANCHOR + TRACK_NOTE_HANDLERS)),
              'das Wort "create_midi_clip" in die Liste \'methods\' eintragen und zwei Befehle '
              "für Noten in Arrangement-Clips anhängen (Arrangement-Check, #140)"),
)

# Kept for script 0.1.0 callers and tests: the clip_slot.py target.
RELATIVE_TARGET = PATCHES[0].relative


def default_abletonosc_dir() -> Path:
    """Default path from docs/setup/ABLETONOSC_WINDOWS.md section 2."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "Documents" / "Ableton" / "User Library" / "Remote Scripts" / "AbletonOSC"


def normalise(data: bytes) -> bytes:
    """CRLF -> LF, so a git checkout with autocrlf hashes like the ZIP download."""
    return data.replace(b"\r\n", b"\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply_patch(original: bytes, replacements: Sequence[tuple[str, str]]) -> bytes:
    text = original.decode("utf-8")
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError(f"anchor not found exactly once: {old.splitlines()[0]!r}")
        text = text.replace(old, new)
    return text.encode("utf-8")


def patched_text(original: bytes) -> bytes:
    """The clip_slot.py patch (script 0.1.0 interface)."""
    return apply_patch(original, PATCHES[0].replacements)


def classify_spec(data: bytes | None, spec: PatchSpec) -> str:
    if data is None:
        return STATE_MISSING
    norm = normalise(data)
    if sha256(norm) == spec.known_original:
        return STATE_ORIGINAL
    try:
        text = norm.decode("utf-8")
    except UnicodeDecodeError:
        return STATE_UNKNOWN
    # Patched = exactly the known original with all our replacements applied.
    for old, new in reversed(spec.replacements):
        if text.count(new) != 1:
            return STATE_UNKNOWN
        text = text.replace(new, old)
    if sha256(text.encode("utf-8")) == spec.known_original:
        return STATE_PATCHED
    return STATE_UNKNOWN


def classify(data: bytes | None, known_original: str) -> str:
    """The clip_slot.py classification (script 0.1.0 interface)."""
    return classify_spec(data, PatchSpec(PATCHES[0].relative, known_original,
                                         PATCHES[0].replacements, PATCHES[0].summary))


def atomic_write(target: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ask_yes(prompt: str, input_fn: Callable[[str], str]) -> bool:
    try:
        return input_fn(prompt).strip().lower() in YES
    except EOFError:
        return False


class UnreadableError(Exception):
    """A file the script must read exists but cannot be read (directory, no permission)."""


def read_or_none(path: Path) -> bytes | None:
    """File content, None if it does not exist, :class:`UnreadableError` otherwise."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:  # IsADirectoryError, PermissionError (Windows: also for folders)
        raise UnreadableError(f"{path} ({type(exc).__name__}: {exc})") from exc


@dataclass
class FileState:
    spec: PatchSpec
    target: Path
    backup: Path
    data: bytes | None
    state: str


def run(abletonosc_dir: Path, *, uninstall: bool, check_only: bool,
        input_fn: Callable[[str], str], out: TextIO,
        known_original: str | None = None,
        specs: Sequence[PatchSpec] | None = None) -> int:
    """``specs`` defaults to :data:`PATCHES`. ``known_original`` (script 0.1.0 interface)
    replaces the clip_slot.py hash and limits the run to that one file."""
    if specs is None:
        specs = PATCHES
        if known_original is not None:
            s = PATCHES[0]
            specs = (PatchSpec(s.relative, known_original, s.replacements, s.summary),)
    try:
        return _run(abletonosc_dir, uninstall=uninstall, check_only=check_only,
                    input_fn=input_fn, out=out, specs=tuple(specs))
    except UnreadableError as exc:
        print(f"FEHLER: Datei nicht lesbar: {exc}\nNichts geändert. Bitte prüfen, ob dort "
              "wirklich eine Datei liegt (kein Ordner) und ob du Leserechte hast.", file=out)
        return EXIT_REFUSED


def _run(abletonosc_dir: Path, *, uninstall: bool, check_only: bool,
         input_fn: Callable[[str], str], out: TextIO, specs: tuple[PatchSpec, ...]) -> int:
    print(f"AbeltonGod install_abletonosc_extension {SCRIPT_VERSION}", file=out)
    print(f"AbletonOSC-Ordner: {abletonosc_dir}", file=out)
    if not (abletonosc_dir / "__init__.py").is_file():
        print("FEHLER: Dort liegt kein AbletonOSC (es fehlt __init__.py). Pfad mit "
              "--abletonosc-dir angeben (siehe docs/setup/ABLETONOSC_WINDOWS.md, Abschnitt 2). "
              "Nichts geändert.", file=out)
        return EXIT_REFUSED
    files: list[FileState] = []
    for spec in specs:
        target = abletonosc_dir / spec.relative
        data = read_or_none(target)
        state = classify_spec(data, spec)
        digest = sha256(normalise(data)) if data is not None else "-"
        print(f"Datei: {target}", file=out)
        print(f"Zustand: {state} (sha256 {digest})", file=out)
        files.append(FileState(spec, target, target.with_name(target.name + BACKUP_SUFFIX),
                               data, state))

    missing = [f for f in files if f.state == STATE_MISSING]
    if missing:
        print("FEHLER: " + ", ".join(str(f.spec.relative) for f in missing)
              + " fehlt. Nichts geändert.", file=out)
        return EXIT_REFUSED
    unknown = [f for f in files if f.state == STATE_UNKNOWN]
    if unknown:
        print("FEHLER: Diese AbletonOSC-Version ist unbekannt ("
              + ", ".join(f.spec.name for f in unknown) + ": weder Original von Commit "
              f"{PINNED_COMMIT[:8]} noch die AbeltonGod-Erweiterung). Das Script ändert "
              "nichts, auch nicht an den anderen Dateien.\n"
              "Bitte diese Ausgabe in Issue #140 einfügen.", file=out)
        return EXIT_REFUSED
    if check_only:
        print("Nur geprüft (--check), nichts geändert.", file=out)
        return EXIT_OK
    if uninstall:
        return _uninstall(files, input_fn, out)
    return _install(files, input_fn, out)


def _install(files: list[FileState], input_fn: Callable[[str], str], out: TextIO) -> int:
    todo = [f for f in files if f.state == STATE_ORIGINAL]
    if not todo:
        print("Die Erweiterung ist schon installiert. Nichts zu tun.", file=out)
        return EXIT_OK
    # Check every backup and every new text BEFORE the first write (all or nothing).
    plans: list[tuple[FileState, bytes, bytes | None]] = []
    for f in todo:
        assert f.data is not None
        # An existing backup is only reused if its RAW bytes equal the current, unpatched
        # file, so --uninstall gives back exactly what the user had (also line endings).
        # Anything else (a backup cut short by a full disk, another version, other line
        # endings) stops the install (review of PR #87, rounds 1 and 2).
        existing = read_or_none(f.backup)
        if existing is not None and existing != f.data:
            same_text = classify_spec(existing, f.spec) == STATE_ORIGINAL
            why = ("ist dasselbe Original, aber nicht byte-gleich (z. B. andere Zeilenenden)"
                   if same_text else "ist NICHT das Original")
            print(f"FEHLER: Die vorhandene Sicherung {f.backup.name} {why} "
                  f"(sha256 {sha256(existing)}, jetzige Datei sha256 {sha256(f.data)}). Das "
                  "Script ändert nichts (an keiner Datei) und überschreibt die Sicherung "
                  "nicht.\nBitte die Sicherung prüfen (z. B. wegschieben) und diese Ausgabe "
                  "in Issue #140 einfügen.", file=out)
            return EXIT_REFUSED
        new = apply_patch(normalise(f.data), f.spec.replacements)
        try:
            compile(new, str(f.target), "exec")
        except SyntaxError as exc:
            print(f"FEHLER: Die geänderte Datei {f.spec.name} wäre kein gültiges Python "
                  f"({exc}). Nichts geändert.", file=out)
            return EXIT_ERROR
        plans.append((f, new, existing))

    print("\nGeplante Änderung (Live muss dafür GESCHLOSSEN sein):", file=out)
    n = 1
    for f in files:
        if f.state == STATE_PATCHED:
            print(f"  -  {f.spec.relative}: schon installiert, bleibt unverändert", file=out)
    for f, _new, existing in plans:
        print(f"  {n}. Original sichern als {f.backup.name}"
              + (" (gültige Sicherung existiert schon und bleibt unverändert)"
                 if existing is not None else ""), file=out)
        print(f"  {n + 1}. In {f.spec.relative} {f.spec.summary}", file=out)
        n += 2
    print("Danach Live neu starten.", file=out)
    if not ask_yes("Live ist geschlossen. Jetzt installieren? [y/N]: ", input_fn):
        print("Nichts geändert.", file=out)
        return EXIT_REFUSED
    done: list[str] = []
    for f, new, existing in plans:
        try:
            if existing is None:
                if f.backup.exists():  # appeared since the check: never overwrite (D-006)
                    raise FileExistsError(f"{f.backup.name} appeared during the install")
                atomic_write(f.backup, f.data)  # temp file + fsync + rename
            # Patch only on top of a backup that reads back byte-identical to the file.
            if read_or_none(f.backup) != f.data:
                raise OSError(f"backup {f.backup.name} does not read back as the original")
            atomic_write(f.target, new)
        except OSError as exc:
            print(f"FEHLER beim Schreiben von {f.spec.name}: {exc}\nDiese Datei ist "
                  "unverändert." + (" Schon installiert in diesem Lauf: " + ", ".join(done)
                                    + " (mit Sicherung). Nach dem Beheben das Script erneut "
                                    "ausführen; es ergänzt den Rest."
                                    if done else " Nichts installiert."), file=out)
            return EXIT_ERROR
        done.append(f.spec.name)
    print("Installiert: " + ", ".join(done) + ". Sicherungen: "
          + ", ".join(str(f.backup) for f, _n, _e in plans) + "\nJetzt Live neu starten.",
          file=out)
    return EXIT_OK


def _uninstall(files: list[FileState], input_fn: Callable[[str], str], out: TextIO) -> int:
    todo = [f for f in files if f.state == STATE_PATCHED]
    if not todo:
        print("Die Erweiterung ist nicht installiert. Nichts zu tun.", file=out)
        return EXIT_OK
    originals: list[tuple[FileState, bytes]] = []
    for f in todo:  # every backup is checked before the first write
        original = read_or_none(f.backup)
        if original is None or classify_spec(original, f.spec) != STATE_ORIGINAL:
            print(f"FEHLER: Keine gültige Sicherung {f.backup.name}. Nichts geändert (an keiner "
                  "Datei). AbletonOSC kann stattdessen neu heruntergeladen werden (Anleitung "
                  "Abschnitt 1-2).", file=out)
            return EXIT_REFUSED
        originals.append((f, original))
    print("\nGeplante Änderung (Live muss dafür GESCHLOSSEN sein): "
          + ", ".join(f"{f.spec.relative} durch die Sicherung {f.backup.name}"
                      for f, _o in originals)
          + " ersetzen. Danach Live neu starten.", file=out)
    if not ask_yes("Live ist geschlossen. Jetzt deinstallieren? [y/N]: ", input_fn):
        print("Nichts geändert.", file=out)
        return EXIT_REFUSED
    done: list[str] = []
    for f, original in originals:
        try:
            atomic_write(f.target, original)
        except OSError as exc:
            print(f"FEHLER beim Schreiben von {f.spec.name}: {exc}"
                  + (" Schon zurückgesetzt: " + ", ".join(done) + "." if done else ""),
                  file=out)
            return EXIT_ERROR
        done.append(f.spec.name)
    print("Deinstalliert: " + ", ".join(done) + " (Sicherungen bleiben liegen). Jetzt Live "
          "neu starten.", file=out)
    return EXIT_OK


def main(argv: list[str] | None = None, input_fn: Callable[[str], str] = input,
         out: TextIO | None = None) -> int:
    out = out if out is not None else sys.stdout
    p = argparse.ArgumentParser(description="AbeltonGod-Erweiterung für AbletonOSC (#50, #140).")
    p.add_argument("--abletonosc-dir", type=Path, default=None,
                   help="Ordner AbletonOSC (Standard: Dokumente\\Ableton\\User Library\\"
                        "Remote Scripts\\AbletonOSC)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="nur prüfen, nichts ändern")
    g.add_argument("--uninstall", action="store_true", help="Original wiederherstellen")
    args = p.parse_args(argv)
    folder = args.abletonosc_dir or default_abletonosc_dir()
    try:
        return run(folder, uninstall=args.uninstall, check_only=args.check,
                   input_fn=input_fn, out=out)
    except KeyboardInterrupt:
        # Each write is atomic, so every file is either its original or fully patched; a
        # Ctrl+C between two files leaves the first one patched (with its backup).
        print("\nABGEBROCHEN mit Strg+C. Jede Datei ist entweder unverändert oder vollständig "
              "geändert; --check zeigt den Stand, ein neuer Lauf ergänzt den Rest.", file=out)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
