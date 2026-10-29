"""Render a kick, put it in the Live project folder and import it into Live (Phase 03, #129).

One command on the Windows machine, with Live open on a *dedicated test set* and the
AbeltonGod extension installed (``docs/setup/ABLETONOSC_WINDOWS.md`` section 7):

    python scripts/kick_to_live.py --preset dense --project "C:\\...\\MyProject"

Steps:
1. Resolves the kick parameters exactly like ``python -m audio_engine.kick`` (preset,
   ``--seed``, ``--set``; :func:`audio_engine.cli.plan`, so the file name is the same
   ``<preset>_s<seed>_v0[_custom]``). Bad values stop here: nothing written, nothing sent.
2. Renders it into ``<project>/Samples/Drums/Kicks/`` with :func:`library.place_kick` (WAV +
   sidecar; an existing file is never overwritten, the new one gets ``_002``, ``_003`` ...).
   The project folder must exist; it is not read from Live.
3. Imports that absolute path with the ``scripts/live_import.py`` 0.3.0 flow (its ``run``):
   test-set question, target, plan, confirmation, read-back, undo question *before* the
   listening question, manual-removal text. Same capability overrides as ``live_import.py``.
4. Always says where the WAV is and whether a clip is in Live. The files stay in the project
   folder in every case (also after an undo: Live's undo does not touch files, D-006); this
   script deletes nothing.
5. Prints a result block to paste into issue #129.

Why a separate script and not a mode of ``live_import.py``: ``live_import.py`` takes an
existing WAV as its one positional argument and its result block is the #50 evidence format;
a render mode would make both conditional. This script reuses its ``run`` and helpers and
changes nothing in it (#126 is reviewed separately). The outer error handling of
``live_import.main`` is repeated here (``import_kick``) because ``main`` does not return its
report; keep the two in step until #136 merges them into one function.

Step 2 refuses ``--project`` unless it is an existing absolute folder with a ``.als`` file
directly in it, not Live's ``Backup`` folder and not inside the AbeltonGod checkout.

User-facing text is German; code and comments are English.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import platform
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from audio_engine import ENGINE_VERSION
from audio_engine import cli as kick_cli
from audio_engine.presets import UnknownPresetError
from bridge.capabilities import CapabilityError, CapabilityRegistry
from bridge.clip_import import (
    DEFAULT_ACTION_LOG,
    REPO_ROOT,
    ActionLog,
    ImportPathError,
    validate_wav_path,
)
from bridge.osc_client import (
    DEFAULT_HOST,
    DEFAULT_RECEIVE_PORT,
    DEFAULT_SEND_PORT,
    DEFAULT_TIMEOUT_S,
    AbletonBridge,
    BridgeError,
    BridgeUnavailableError,
    ReceivePortInUseError,
)
from library import library_folder, place_kick, sidecar_path


def _load_live_import() -> types.ModuleType:
    """``scripts/live_import.py``. As a script, ``scripts/`` is on ``sys.path``; when this file
    is loaded by path (tests) it is loaded the same way, without changing ``sys.path``."""
    if "live_import" in sys.modules:
        return sys.modules["live_import"]
    path = Path(__file__).resolve().parent / "live_import.py"
    spec = importlib.util.spec_from_file_location("live_import", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["live_import"] = module
    spec.loader.exec_module(module)
    return module


live_import = _load_live_import()

SCRIPT_VERSION = "0.1.0"

EXIT_OK = live_import.EXIT_OK
EXIT_CHECK_FAILED = live_import.EXIT_CHECK_FAILED
EXIT_NO_CONNECTION = live_import.EXIT_NO_CONNECTION
EXIT_PORT_IN_USE = live_import.EXIT_PORT_IN_USE
EXIT_SETUP_ERROR = live_import.EXIT_SETUP_ERROR  # bad parameters / project folder / config
EXIT_EXTENSION_MISSING = live_import.EXIT_EXTENSION_MISSING
EXIT_WRITE_FAILED = 6  # the kick could not be written (disk full, permission ...)
EXIT_INTERRUPTED = live_import.EXIT_INTERRUPTED

# kick_in_live values (result block)
CLIP_NONE = "none (nothing sent to Live)"
CLIP_REMOVED = "removed by undo (read back)"
CLIP_REMOVED_NAMES = "removed by undo (read back; track names not restored)"
CLIP_UNKNOWN = "unknown (see the messages above)"

# --project may not lie in the AbeltonGod checkout this script runs from, nor in the one the
# bridge package is imported from (the same folder after `pip install -e .`).
REFUSED_ROOTS = tuple(sorted({Path(__file__).resolve().parent.parent, REPO_ROOT.resolve()}))


@dataclass
class Kick:
    preset: str
    project: str
    seed: str = "-"
    custom: str = "-"
    folder: str = "-"
    wav: Path | None = None
    sidecar: Path | None = None
    written: str = "no"


# -- step 1 and 2: render into the project folder ---------------------------------------------

def make_kick(args: argparse.Namespace, kick: Kick, out: TextIO) -> int | None:
    """Render and place the kick. ``None`` = written (``kick.wav`` set), else an exit code."""
    try:
        try:
            plan = types.SimpleNamespace(preset=args.preset, out=kick.project, seed=args.seed,
                                         overrides=args.overrides, variants=1)
            _, variants, stems, descriptions = kick_cli.plan(plan)
            folder = library_folder(kick.project)
        except (ValueError, UnknownPresetError) as exc:  # UsageError, KickParamsError, Library…
            print(f"FEHLER in den Kick-Werten: {exc}\nEs wurde nichts geschrieben und nichts "
                  "in Live geändert.", file=out)
            kick.written = f"no ({type(exc).__name__})"
            return EXIT_SETUP_ERROR
        params = variants[0]
        kick.seed = str(params["seed"])
        kick.custom = ", ".join(args.overrides) or "-"
        kick.folder = str(folder)
        problem = project_problem(args.project)
        if problem is not None:
            print(f"FEHLER mit dem Projektordner: {problem}\nEs wurde nichts geschrieben und "
                  "nichts in Live geändert. Anleitung: docs/setup/KICK_TO_LIVE.md", file=out)
            kick.written = "no (project folder refused)"
            return EXIT_SETUP_ERROR
        print(f"Kick: Preset {args.preset}, Seed {kick.seed}"
              + (f", geändert: {kick.custom}" if args.overrides else "") + "\n"
              f"Schreibe WAV + Sidecar nach:\n  {folder}\n"
              "(vorhandene Dateien werden nie überschrieben; neue Datei bekommt dann _002 ...)",
              file=out)
        try:
            # Stored at once: a Ctrl+C after this line still knows the pair exists.
            kick.wav = place_kick(params, kick.project, name=stems[0],
                                  description=descriptions[0])
        except ValueError as exc:  # LibraryPathError (path too long ...), KickParamsError
            print(f"FEHLER: {exc}\nEs wurde nichts geschrieben und nichts in Live geändert.",
                  file=out)
            kick.written = f"no ({type(exc).__name__})"
            return EXIT_SETUP_ERROR
        except OSError as exc:
            print(f"FEHLER beim Schreiben: {exc}\nplace_kick entfernt, was dieser Aufruf "
                  f"angelegt hat. Bitte in {folder} nachsehen. In Live wurde nichts geändert.",
                  file=out)
            kick.written = f"no ({type(exc).__name__}: {exc})"
            return EXIT_WRITE_FAILED
        kick.sidecar, kick.written = sidecar_path(kick.wav), "yes"
        print(f"Geschrieben:\n  {kick.wav}\n  {kick.sidecar}\n", file=out)
    except KeyboardInterrupt:
        if kick.wav is not None:  # place_kick had returned: the pair is complete and stays
            kick.sidecar, kick.written = sidecar_path(kick.wav), "yes"
            print(f"\nABGEBROCHEN mit Strg+C. Der Kick war schon geschrieben:\n  {kick.wav}\n"
                  f"  {kick.sidecar}\nIn Live wurde nichts geändert.", file=out)
            return EXIT_INTERRUPTED
        print("\nABGEBROCHEN mit Strg+C beim Erzeugen des Kicks. place_kick entfernt, was "
              "dieser Aufruf angelegt hat (bis auf seltene, in library.place_kick beschriebene "
              "Fälle, z. B. ein leerer Ordner). Bitte in "
              f"{kick.folder if kick.folder != '-' else kick.project} nachsehen. In Live "
              "wurde nichts geändert.", file=out)
        kick.written = "no (interrupted by user, Ctrl+C)"
        return EXIT_INTERRUPTED
    return None


def project_problem(raw: str) -> str | None:
    """Why ``--project`` is not accepted (German), or None. Nothing is written before this.

    Required: an existing absolute folder with a ``.als`` file directly in it (Live keeps the
    set at the top of its project folder), not Live's ``Backup`` folder, not inside the
    AbeltonGod checkout (an empty ``--project`` would otherwise mean the current folder)."""
    if not raw.strip():
        return "--project ist leer. Bitte den vollen Pfad des Projektordners angeben."
    if not os.path.isabs(raw):
        return (f"--project muss ein voller Pfad sein (z. B. \"C:\\...\\Test Project\"), "
                f"nicht {raw!r}.")
    folder = Path(raw)
    if not folder.is_dir():
        return f"Den Ordner gibt es nicht: {raw}"
    real = folder.resolve()
    for root in REFUSED_ROOTS:
        if real.is_relative_to(root):
            return (f"{raw} liegt im AbeltonGod-Ordner ({root}). Das ist kein Live-Projekt; "
                    "bitte den Projektordner deines Test-Sets angeben.")
    if folder.name.lower() == "backup":
        return (f"{raw} ist Lives Backup-Ordner. Bitte den Ordner darüber nehmen (dort liegt "
                "die .als-Datei des Sets).")
    try:
        has_set = any(p.suffix.lower() == ".als" and p.is_file() for p in folder.iterdir())
    except OSError as exc:
        return f"{raw} lässt sich nicht lesen: {exc}"
    if not has_set:
        return (f"In {raw} liegt keine .als-Datei, also ist es nicht der Projektordner eines "
                "gespeicherten Live-Sets. Set zuerst in Live speichern (Datei -> Live-Set "
                "speichern unter ...), dann den Ordner nehmen, in dem die .als-Datei liegt.")
    return None


# -- step 3: the live_import 0.3.0 flow --------------------------------------------------------

def import_kick(args: argparse.Namespace, kick: Kick, report: live_import.Report,
                input_fn: Callable[[str], str], out: TextIO) -> int:
    """``live_import.main`` without argument parsing and result block. Differences: the WAV
    must lie in the project's kick folder (``library_root``); Ctrl+C texts come from
    :func:`interrupted_text`; Ctrl+C while connecting or after ``run()`` is caught (#135 is
    the same gap in ``live_import.main``). De-duplication: issue #136."""
    assert kick.wav is not None
    code = EXIT_OK
    bridge: AbletonBridge | None = None
    run_started = False
    log = ActionLog(args.log)
    try:
        report.path = validate_wav_path(kick.wav, library_root=kick.folder)
        report.action_log = str(log.path)
        send_port = (args.send_port if args.send_port is not None
                     else live_import.env_port("ABLETON_OSC_SEND_PORT", DEFAULT_SEND_PORT))
        receive_port = (args.receive_port if args.receive_port is not None
                        else live_import.env_port("ABLETON_OSC_RECEIVE_PORT",
                                                  DEFAULT_RECEIVE_PORT))
        try:
            bridge = AbletonBridge.connect(
                DEFAULT_HOST, send_port, receive_port, timeout_s=args.timeout,
                registry=CapabilityRegistry.from_file(), allow_untested=live_import.ALLOWED)
        except ReceivePortInUseError as exc:
            print(live_import.MSG_PORT_IN_USE.format(port=receive_port, host=DEFAULT_HOST),
                  file=out)
            report.error = f"ReceivePortInUseError: {exc}"
            code = EXIT_PORT_IN_USE
        if bridge is not None:
            run_started = True
            try:
                code = live_import.run(bridge, report, report.path, args.slot, log,
                                       args.timeout, input_fn, out)
            except live_import.Stop as stop:
                code, report.error = stop.code, stop.error
            except KeyboardInterrupt:
                report.interrupted = True
                report.error = "interrupted by user (Ctrl+C) outside a write"
                print("\nABGEBROCHEN mit Strg+C. " + interrupted_text(report), file=out)
            except BridgeUnavailableError as exc:
                print(live_import.msg_no_answer(DEFAULT_HOST, send_port) + "\n" + (
                    "Es wurde nichts in Live geändert." if not report.plan_confirmed
                    else "Bitte in Live nachsehen, was schon ausgeführt wurde."), file=out)
                report.error = f"{type(exc).__name__}: {exc}"
                code = EXIT_NO_CONNECTION
            except BridgeError as exc:
                print(f"FEHLER: unerwartete Antwort von AbletonOSC: {exc}", file=out)
                report.error = f"{type(exc).__name__}: {exc}"
                code = EXIT_CHECK_FAILED
            live_import.split_overrides(report, bridge.gate.overrides_used)
    except ImportPathError as exc:
        print(f"FEHLER mit der Datei: {exc}\nEs wurde nichts in Live geändert.", file=out)
        report.error = f"ImportPathError: {exc}"
        code = EXIT_SETUP_ERROR
    except (CapabilityError, ValueError) as exc:
        print(f"FEHLER in der Konfiguration: {exc}", file=out)
        report.error = f"{type(exc).__name__}: {exc}"
        code = EXIT_SETUP_ERROR
    except KeyboardInterrupt:
        # Before run(): checking the file or connecting. After run() started: a Ctrl+C in
        # split_overrides or a second Ctrl+C while a handler above was printing (PR #134
        # review, problem 2): say what the importer's record shows, not "nothing changed".
        report.interrupted = True
        if not run_started:
            report.error = "interrupted by user (Ctrl+C) before connecting"
            print("\nABGEBROCHEN mit Strg+C. Es wurde nichts in Live geändert.", file=out)
        else:
            if report.error is None:
                report.error = "interrupted by user (Ctrl+C) after the import flow"
            print("\nABGEBROCHEN mit Strg+C. " + interrupted_text(report), file=out)
    finally:
        if bridge is not None:
            bridge.close()
    if report.interrupted:
        code = EXIT_INTERRUPTED
    return code


# -- step 4 and 5: where things are ------------------------------------------------------------

def clip_in_live(report: live_import.Report) -> str:
    """What this run left in Live, from the importer's own record (kick_in_live)."""
    outcome = report.importer.last_outcome if report.importer is not None else None
    sent = outcome is not None and any(s.outcome != "refused" for s in outcome.steps)
    if not sent:
        # Plan confirmed, but the import flow ended without a result (Ctrl+C or a lost
        # connection inside the import): a write may have gone out before its step was
        # recorded (clip_import._send), so this is unknown, not none (PR #134 review).
        if report.plan_confirmed and report.import_result == "SKIPPED":
            return CLIP_UNKNOWN
        return CLIP_NONE
    if report.import_result != "PASS":
        return CLIP_UNKNOWN
    if report.undo_result.startswith("PASS"):
        return CLIP_REMOVED
    if report.undo_result.startswith("PARTIAL"):
        return CLIP_REMOVED_NAMES
    if report.undo_result.startswith("SKIPPED"):
        return f"in Live (track {outcome.track_index}, slot {outcome.slot_index})"
    return CLIP_UNKNOWN


def interrupted_text(report: live_import.Report) -> str:
    """What a Ctrl+C message says about Live (German), from :func:`clip_in_live`."""
    state = clip_in_live(report)
    done = report.importer.last_outcome if report.importer is not None else None
    if state.startswith("in Live") and done is not None:
        return ("Der Import war schon fertig; der Clip bleibt im Set"
                + (", die neue Spur auch" if done.created_track else "")
                + ".\n" + live_import.manual_removal_text(done))
    if state in (CLIP_REMOVED, CLIP_REMOVED_NAMES):
        return "Der Import war schon per Undo zurückgenommen (zurückgelesen)."
    if state == CLIP_UNKNOWN:
        return ("Ob schon etwas gesendet wurde oder noch im Set ist, ist unbekannt. Erst in "
                "Live nachsehen. " + live_import.UNDO_HINT)
    return "Es wurde nichts in Live geändert."


def summary_text(kick: Kick, state: str) -> str:
    lines = ["", "Zusammenfassung:"]
    if state == CLIP_NONE:
        lines.append("  Live: kein Clip, in Live wurde nichts geändert.")
    elif state in (CLIP_REMOVED, CLIP_REMOVED_NAMES):
        lines.append("  Live: der Clip wurde per Undo wieder entfernt (zurückgelesen)."
                     + (" Spurnamen bitte von Hand prüfen (siehe oben)."
                        if state == CLIP_REMOVED_NAMES else ""))
    elif state == CLIP_UNKNOWN:
        lines.append("  Live: ob ein Clip im Set ist, ist UNBEKANNT. Erst in Live nachsehen "
                     "(siehe oben).")
    else:
        lines.append("  Live: der Clip ist im Set und verweist auf die Datei unten.")
    lines += ["  Kick-Datei (bleibt im Projektordner; das Script löscht nichts):",
              f"    {kick.wav}", f"    {kick.sidecar}"]
    if not state.startswith("in Live"):
        lines.append(f'  Von Hand importieren: explorer "{kick.folder}" eingeben, dann die '
                     "WAV auf eine leere Zelle einer Audiospur ziehen "
                     "(docs/setup/SAMPLE_IMPORT_FALLBACK.md).")
    return "\n".join(lines)


def render_result_block(kick: Kick, report: live_import.Report, state: str) -> str:
    inner = live_import.render_result_block(report).splitlines()
    start = next(i for i, line in enumerate(inner) if line.startswith("live_version_api:"))
    lines = [
        "```text",
        "AbeltonGod kick_to_live result",
        f"kick_to_live_version: {SCRIPT_VERSION}",
        f"live_import_version: {live_import.SCRIPT_VERSION}",
        f"engine_version: {ENGINE_VERSION}",
        f"python: {platform.python_version()} ({platform.system()} {platform.release()})",
        f"started_at: {report.started_at}",
        f"finished_at: {report.finished_at}",
        f"preset: {kick.preset}",
        f"seed: {kick.seed}",
        f"custom_values: {kick.custom}",
        f"project: {kick.project}",
        f"kick_written: {kick.written}",
        f"kick_wav: {kick.wav or '-'}",
        f"kick_sidecar: {kick.sidecar or '-'}",
        f"kick_in_live: {state}",
        *inner[start:-1],
        "```",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AbeltonGod: Kick erzeugen, in den Projektordner legen und in Live "
                    "importieren (#129).")
    p.add_argument("--preset", required=True, help="Preset-Name, z. B. dense")
    p.add_argument("--project", required=True,
                   help="Projektordner des Live-Sets (der Ordner mit der .als-Datei)")
    p.add_argument("--seed", type=int, default=None, help="anderer Seed als im Preset")
    p.add_argument("--set", dest="overrides", action="append", default=[],
                   metavar="FELD=WERT", help="einen Kick-Wert ändern, mehrfach möglich")
    p.add_argument("--slot", type=int, default=None,
                   help="Zelle (Szene, ab 0); Standard: erste freie Zelle der Spur")
    p.add_argument("--log", type=Path, default=DEFAULT_ACTION_LOG,
                   help=f"Aktions-Log (Standard: {DEFAULT_ACTION_LOG})")
    p.add_argument("--send-port", type=int, default=None)
    p.add_argument("--receive-port", type=int, default=None)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                   help=f"Sekunden pro Anfrage (Standard {DEFAULT_TIMEOUT_S:g})")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, input_fn: Callable[[str], str] = input,
         out: TextIO | None = None) -> int:
    out = out if out is not None else sys.stdout
    if hasattr(out, "reconfigure"):
        try:
            out.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    args = parse_args(argv)
    logging.getLogger("abeltongod").addHandler(logging.NullHandler())
    report = live_import.Report(started_at=live_import.now_iso())
    kick = Kick(preset=args.preset, project=os.path.abspath(args.project))
    print(f"AbeltonGod kick_to_live {SCRIPT_VERSION} (Import wie live_import "
          f"{live_import.SCRIPT_VERSION})\n", file=out)
    # Ctrl+C between the steps (after make_kick returned, before or after import_kick) or
    # while the summary is printed still ends with the WAV location and a result block.
    code: int | None = None
    try:
        code = make_kick(args, kick, out)
        if code is None:
            code = import_kick(args, kick, report, input_fn, out)
            print(summary_text(kick, clip_in_live(report)), file=out)
    except KeyboardInterrupt:
        code = EXIT_INTERRUPTED
        report.interrupted = True
        if report.error is None:
            report.error = "interrupted by user (Ctrl+C) between steps"
        print("\nABGEBROCHEN mit Strg+C. " + interrupted_text(report), file=out)
        if kick.wav is not None:
            print(f"Kick-Datei (bleibt im Projektordner):\n  {kick.wav}\n  {kick.sidecar}",
                  file=out)
    state = clip_in_live(report)
    report.finished_at = live_import.now_iso()
    print("\nBitte den folgenden Block komplett in Issue #129 einfügen:\n", file=out)
    print(render_result_block(kick, report, state), file=out)
    return code


if __name__ == "__main__":
    sys.exit(main())
