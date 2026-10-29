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
report; keep the two in step.

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
        if not Path(kick.project).is_dir():
            print(f"FEHLER: Den Projektordner gibt es nicht: {kick.project}\nEs wurde nichts "
                  "geschrieben und nichts in Live geändert.", file=out)
            kick.written = "no (project folder missing)"
            return EXIT_SETUP_ERROR
        if not any(Path(kick.project).glob("*.als")):
            print(f"Hinweis: In {kick.project} liegt keine .als-Datei. Ist das wirklich der "
                  "Projektordner deines Sets?", file=out)
        print(f"Kick: Preset {args.preset}, Seed {kick.seed}"
              + (f", geändert: {kick.custom}" if args.overrides else "") + "\n"
              f"Schreibe WAV + Sidecar nach:\n  {folder}\n"
              "(vorhandene Dateien werden nie überschrieben; neue Datei bekommt dann _002 ...)",
              file=out)
        try:
            wav = place_kick(params, kick.project, name=stems[0], description=descriptions[0])
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
    except KeyboardInterrupt:
        print("\nABGEBROCHEN mit Strg+C beim Erzeugen des Kicks. place_kick entfernt, was "
              "dieser Aufruf angelegt hat (bis auf seltene, in library.place_kick beschriebene "
              "Fälle, z. B. ein leerer Ordner). Bitte in "
              f"{kick.folder if kick.folder != '-' else kick.project} nachsehen. In Live "
              "wurde nichts geändert.", file=out)
        kick.written = "no (interrupted by user, Ctrl+C)"
        return EXIT_INTERRUPTED
    kick.wav, kick.sidecar, kick.written = wav, sidecar_path(wav), "yes"
    print(f"Geschrieben:\n  {wav}\n  {kick.sidecar}\n", file=out)
    return None


# -- step 3: the live_import 0.3.0 flow --------------------------------------------------------

def import_kick(args: argparse.Namespace, kick: Kick, report: live_import.Report,
                input_fn: Callable[[str], str], out: TextIO) -> int:
    """``live_import.main`` without argument parsing and result block (same handling)."""
    assert kick.wav is not None
    code = EXIT_OK
    bridge: AbletonBridge | None = None
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
            try:
                code = live_import.run(bridge, report, report.path, args.slot, log,
                                       args.timeout, input_fn, out)
            except live_import.Stop as stop:
                code, report.error = stop.code, stop.error
            except KeyboardInterrupt:
                report.interrupted = True
                report.error = "interrupted by user (Ctrl+C) outside a write"
                done = report.importer.last_outcome if report.importer is not None else None
                if report.import_result == "PASS" and done is not None:
                    tail = ("Der Import war schon fertig; der Clip bleibt im Set"
                            + (", die neue Spur auch" if done.created_track else "")
                            + ".\n" + live_import.manual_removal_text(done))
                elif report.plan_confirmed:
                    tail = ("Ob schon etwas gesendet wurde, ist unbekannt. Bitte in Live "
                            "nachsehen. " + live_import.UNDO_HINT)
                else:
                    tail = "Es wurde nichts in Live geändert."
                print("\nABGEBROCHEN mit Strg+C. " + tail, file=out)
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
    except KeyboardInterrupt:  # before run(): while checking the file or connecting
        report.interrupted = True
        report.error = "interrupted by user (Ctrl+C) before connecting"
        print("\nABGEBROCHEN mit Strg+C. Es wurde nichts in Live geändert.", file=out)
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


def summary_text(kick: Kick, state: str) -> str:
    lines = ["", "Zusammenfassung:"]
    if state == CLIP_NONE:
        lines.append("  Live: kein Clip, in Live wurde nichts geändert.")
    elif state in (CLIP_REMOVED, CLIP_REMOVED_NAMES):
        lines.append("  Live: der Clip wurde per Undo wieder entfernt (zurückgelesen)."
                     + (" Spurnamen bitte von Hand prüfen (siehe oben)."
                        if state == CLIP_REMOVED_NAMES else ""))
    elif state == CLIP_UNKNOWN:
        lines.append("  Live: ob noch ein Clip im Set ist, ist UNBEKANNT. Bitte in Live "
                     "nachsehen (siehe oben).")
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
    code = make_kick(args, kick, out)
    state = CLIP_NONE
    if code is None:
        code = import_kick(args, kick, report, input_fn, out)
        state = clip_in_live(report)
        print(summary_text(kick, state), file=out)
    report.finished_at = live_import.now_iso()
    print("\nBitte den folgenden Block komplett in Issue #129 einfügen:\n", file=out)
    print(render_result_block(kick, report, state), file=out)
    return code


if __name__ == "__main__":
    sys.exit(main())
