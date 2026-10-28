"""Install the AbeltonGod extension into the user's AbletonOSC (Phase 03, issue #50).

The extension is option A of
``docs/research/2026-10-28_abletonosc-protocol-and-create-audio-clip.md``: one word added to
the ``methods`` list of ``abletonosc/clip_slot.py`` so that AbletonOSC registers
``/live/clip_slot/create_audio_clip`` with its generic ``_call_method``
(``clip_slot.py`` lines 27-32 and 46-48 at AbletonOSC commit ``0ca68214``).
AbletonOSC itself is not copied into this repo; this script only edits the user's installed copy.

Safety:
- The file is only patched if its content (line endings normalised) is exactly the known
  original of commit ``0ca68214`` (SHA-256 below). Any other version is refused, nothing is
  written, and the user is asked to report the hash.
- Before patching, the original is saved next to it as ``clip_slot.py.abeltongod-orig``. An
  existing backup is never overwritten (D-006).
- The new file is written to a temporary file in the same folder and moved over the original
  in one step (``os.replace``); it must compile as Python first.
- ``--uninstall`` puts the backup back (only if the current file is exactly our patched
  version).
- Default-No prompt before any write. ``--check`` only reports.

Live reads remote scripts at start: restart Live after installing or uninstalling.

User-facing text is German; code and comments are English.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

SCRIPT_VERSION = "0.1.0"

PINNED_COMMIT = "0ca68214bd62c9b5cb641ca34006cfd70ba94430"
# SHA-256 of abletonosc/clip_slot.py at PINNED_COMMIT with LF line endings (2811 bytes,
# 67 lines; computed 2026-10-28 from raw.githubusercontent.com and from a git clone).
KNOWN_ORIGINAL_SHA256 = "989f9f6a6631fd04598fff0b278b9d844e03b3e211ae9b23d293e985b22d4aed"

# The exact text of the methods list end (clip_slot.py lines 31-32) and its replacement.
PATCH_OLD = '            "delete_clip"\n        ]\n'
PATCH_NEW = ('            "delete_clip",\n'
             '            "create_audio_clip"  # added by AbeltonGod (#50)\n'
             '        ]\n')

BACKUP_SUFFIX = ".abeltongod-orig"
RELATIVE_TARGET = Path("abletonosc") / "clip_slot.py"

EXIT_OK = 0
EXIT_REFUSED = 1  # unknown version, missing folder, user said no
EXIT_ERROR = 2  # write failed

YES = {"y", "yes", "j", "ja"}

STATE_ORIGINAL = "original"
STATE_PATCHED = "patched"
STATE_UNKNOWN = "unknown"
STATE_MISSING = "missing"


def default_abletonosc_dir() -> Path:
    """Default path from docs/setup/ABLETONOSC_WINDOWS.md section 2."""
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "Documents" / "Ableton" / "User Library" / "Remote Scripts" / "AbletonOSC"


def normalise(data: bytes) -> bytes:
    """CRLF -> LF, so a git checkout with autocrlf hashes like the ZIP download."""
    return data.replace(b"\r\n", b"\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patched_text(original: bytes) -> bytes:
    text = original.decode("utf-8")
    if text.count(PATCH_OLD) != 1:
        raise ValueError("methods list end not found exactly once")
    return text.replace(PATCH_OLD, PATCH_NEW).encode("utf-8")


def classify(data: bytes | None, known_original: str) -> str:
    if data is None:
        return STATE_MISSING
    norm = normalise(data)
    digest = sha256(norm)
    if digest == known_original:
        return STATE_ORIGINAL
    try:
        # Patched = exactly the known original with our patch applied.
        original = norm.decode("utf-8").replace(PATCH_NEW, PATCH_OLD).encode("utf-8")
    except UnicodeDecodeError:
        return STATE_UNKNOWN
    if norm != original and sha256(original) == known_original:
        return STATE_PATCHED
    return STATE_UNKNOWN


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


def read_or_none(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def run(abletonosc_dir: Path, *, uninstall: bool, check_only: bool,
        input_fn: Callable[[str], str], out: TextIO,
        known_original: str = KNOWN_ORIGINAL_SHA256) -> int:
    target = abletonosc_dir / RELATIVE_TARGET
    backup = target.with_name(target.name + BACKUP_SUFFIX)
    print(f"AbeltonGod install_abletonosc_extension {SCRIPT_VERSION}", file=out)
    print(f"AbletonOSC-Ordner: {abletonosc_dir}", file=out)
    if not (abletonosc_dir / "__init__.py").is_file():
        print("FEHLER: Dort liegt kein AbletonOSC (es fehlt __init__.py). Pfad mit "
              "--abletonosc-dir angeben (siehe docs/setup/ABLETONOSC_WINDOWS.md, Abschnitt 2). "
              "Nichts geändert.", file=out)
        return EXIT_REFUSED
    data = read_or_none(target)
    state = classify(data, known_original)
    digest = sha256(normalise(data)) if data is not None else "-"
    print(f"Datei: {target}", file=out)
    print(f"Zustand: {state} (sha256 {digest})", file=out)

    if state == STATE_MISSING:
        print(f"FEHLER: {RELATIVE_TARGET} fehlt. Nichts geändert.", file=out)
        return EXIT_REFUSED
    if state == STATE_UNKNOWN:
        print("FEHLER: Diese AbletonOSC-Version ist unbekannt (weder Original von Commit "
              f"{PINNED_COMMIT[:8]} noch die AbeltonGod-Erweiterung). Das Script ändert nichts.\n"
              "Bitte diese Ausgabe in Issue #50 einfügen.", file=out)
        return EXIT_REFUSED
    if check_only:
        print("Nur geprüft (--check), nichts geändert.", file=out)
        return EXIT_OK

    if not uninstall:
        if state == STATE_PATCHED:
            print("Die Erweiterung ist schon installiert. Nichts zu tun.", file=out)
            return EXIT_OK
        print("\nGeplante Änderung:\n"
              f"  1. Original sichern als {backup.name}"
              + (" (Sicherung existiert schon und bleibt unverändert)" if backup.exists()
                 else "") + "\n"
              f"  2. In {RELATIVE_TARGET} das Wort \"create_audio_clip\" in die Liste 'methods' "
              "eintragen (eine Zeile)\n"
              "Danach Live neu starten.", file=out)
        if not ask_yes("Jetzt installieren? [y/N]: ", input_fn):
            print("Nichts geändert.", file=out)
            return EXIT_REFUSED
        new = patched_text(normalise(data))
        compile(new, str(target), "exec")
        try:
            if not backup.exists():
                with backup.open("xb") as fh:  # "x": never overwrite (D-006)
                    fh.write(data)
            atomic_write(target, new)
        except OSError as exc:
            print(f"FEHLER beim Schreiben: {exc}\nDie Originaldatei ist unverändert oder "
                  f"liegt als {backup.name} daneben.", file=out)
            return EXIT_ERROR
        print(f"Installiert. Sicherung: {backup}\nJetzt Live neu starten.", file=out)
        return EXIT_OK

    # uninstall
    if state == STATE_ORIGINAL:
        print("Die Erweiterung ist nicht installiert. Nichts zu tun.", file=out)
        return EXIT_OK
    original = read_or_none(backup)
    if original is None or classify(original, known_original) != STATE_ORIGINAL:
        print(f"FEHLER: Keine gültige Sicherung {backup.name}. Nichts geändert. AbletonOSC "
              "kann stattdessen neu heruntergeladen werden (Anleitung Abschnitt 1-2).", file=out)
        return EXIT_REFUSED
    print(f"\nGeplante Änderung: {RELATIVE_TARGET} durch die Sicherung {backup.name} "
          "ersetzen. Danach Live neu starten.", file=out)
    if not ask_yes("Jetzt deinstallieren? [y/N]: ", input_fn):
        print("Nichts geändert.", file=out)
        return EXIT_REFUSED
    try:
        atomic_write(target, original)
    except OSError as exc:
        print(f"FEHLER beim Schreiben: {exc}", file=out)
        return EXIT_ERROR
    print("Deinstalliert (Sicherung bleibt liegen). Jetzt Live neu starten.", file=out)
    return EXIT_OK


def main(argv: list[str] | None = None, input_fn: Callable[[str], str] = input,
         out: TextIO | None = None) -> int:
    out = out if out is not None else sys.stdout
    p = argparse.ArgumentParser(description="AbeltonGod-Erweiterung für AbletonOSC (#50).")
    p.add_argument("--abletonosc-dir", type=Path, default=None,
                   help="Ordner AbletonOSC (Standard: Dokumente\\Ableton\\User Library\\"
                        "Remote Scripts\\AbletonOSC)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="nur prüfen, nichts ändern")
    g.add_argument("--uninstall", action="store_true", help="Original wiederherstellen")
    args = p.parse_args(argv)
    folder = args.abletonosc_dir or default_abletonosc_dir()
    return run(folder, uninstall=args.uninstall, check_only=args.check, input_fn=input_fn,
               out=out)


if __name__ == "__main__":
    sys.exit(main())
