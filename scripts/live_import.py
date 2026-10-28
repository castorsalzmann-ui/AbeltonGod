"""Import one WAV into the open Live set as a Session clip (Phase 03, issue #50).

Run it on the Windows machine with Live open on a *dedicated test set*, after installing the
extension (``scripts/install_abletonosc_extension.py``, ``docs/setup/ABLETONOSC_WINDOWS.md``
section 7):

    python scripts/live_import.py "C:\\...\\kick.wav"

Steps:
1. Checks the file (absolute, exists, ``.wav``, RIFF/WAVE header) before anything else.
2. Connects, reads Live version, tracks (with "audio track?" each), number of scenes.
3. Checks that the extension answers (one no-argument call; changes nothing in Live, leaves
   one ERROR line in ``abletonosc.log``). If it is missing: install hint + Explorer fallback.
4. Asks "test set?" (default No), then the target: an existing audio track or a new audio
   track at the end; the first empty clip slot (or ``--slot``). MIDI tracks and occupied
   slots are refused before anything is sent.
5. Prints the planned changes and asks again (default No).
6. Imports (``bridge.clip_import.ClipImporter``): action-log entry before and after every
   write, read-back of slots and the clip's file path.
7. Asks whether the kick plays (the user's answer is recorded as such).
8. Asks whether to undo (default No). Undo is sent only after a read-back shows the set as
   the import left it; each undo is read back. Never after a timeout or Ctrl+C.
9. Prints a result block to paste into issue #50.

Capability gate: ``clip_slot.create_audio_clip`` (``unknown``), ``song.create_audio_track``
(``supported``) and the pending reads go through the gate's explicit check-script override;
``capability_overrides_used`` in the result block lists them. Statuses change only in a
separate contract-change PR with the pasted output as evidence.

Never sends destructive commands. User-facing text is German; code and comments are English.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from bridge.capabilities import CapabilityError, CapabilityRegistry
from bridge.clip_import import (
    DEFAULT_ACTION_LOG,
    ActionLog,
    ActionLogError,
    ClipImporter,
    ImportAborted,
    ImportInterrupted,
    ImportOutcome,
    ImportPathError,
    SlotState,
    first_empty_slot,
    read_state,
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

SCRIPT_VERSION = "0.1.0"

ALLOWED = ("app.version", "song.track_names.get", "song.undo", "song.create_audio_track",
           "clip_slot.create_audio_clip")

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_NO_CONNECTION = 2
EXIT_PORT_IN_USE = 3
EXIT_SETUP_ERROR = 4
EXIT_EXTENSION_MISSING = 5
EXIT_INTERRUPTED = 130

YES = {"y", "yes", "j", "ja"}
NEW_TRACK = {"n", "neu", "new"}


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")


# -- German user messages --------------------------------------------------------------------

def msg_no_answer(host: str, send_port: int) -> str:
    return (
        f"FEHLER: AbletonOSC antwortet nicht ({host}:{send_port}).\n"
        "Mögliche Ursachen (von hier aus nicht zu unterscheiden, bitte alle prüfen):\n"
        "  1. Ableton Live ist nicht geöffnet.\n"
        "  2. 'AbletonOSC' ist nicht als Control Surface ausgewählt\n"
        "     (Optionen -> Einstellungen -> Link, Tempo & MIDI).\n"
        "  3. In Live ist ein Dialog offen (z. B. Speichern) und blockiert die Antwort.\n"
        "  4. Live wurde nach der Installation nicht neu gestartet.\n"
        "Log: ...\\Remote Scripts\\AbletonOSC\\logs\\abletonosc.log"
    )


MSG_PORT_IN_USE = (
    "FEHLER: Port {port} ({host}) ist schon belegt. Ein anderes Programm (z. B. ein zweites\n"
    "Terminal mit diesem Script oder bridge_check.py) empfängt dort. Dieses schließen und neu\n"
    "starten. Es wurde nichts in Live geändert."
)

MSG_EXTENSION_MISSING = (
    "FEHLER: Die AbeltonGod-Erweiterung fehlt in AbletonOSC (AbletonOSC kennt den Import-Befehl\n"
    "nicht). Es wurde nichts in Live geändert.\n"
    "  1. Live beenden.\n"
    "  2. python scripts/install_abletonosc_extension.py\n"
    "  3. Live starten und dieses Script erneut ausführen.\n"
    "Anleitung: docs/setup/ABLETONOSC_WINDOWS.md, Abschnitt 7.\n"
    "Ohne Erweiterung geht der Import von Hand: docs/setup/SAMPLE_IMPORT_FALLBACK.md"
)

UNDO_HINT = ("In Live zeigt der Undo-Verlauf (Strg+Alt+Z; im Handbuch: View -> Undo History), "
             "welche Schritte es gibt.")


# -- report ----------------------------------------------------------------------------------

@dataclass
class Report:
    started_at: str
    path: str = "-"
    live_version: str = "unbekannt"
    tracks: list[str] = field(default_factory=list)
    num_scenes: int | None = None
    extension: str = "SKIPPED"
    target: str = "-"
    plan_confirmed: bool = False
    steps: list[str] = field(default_factory=list)
    import_result: str = "SKIPPED"
    file_path_read: str = "-"
    user_hears_kick: str = "not asked"
    undo_result: str = "SKIPPED"
    action_log: str = "-"
    overrides_used: list[str] = field(default_factory=list)
    error: str | None = None
    interrupted: bool = False
    finished_at: str = ""


def render_result_block(r: Report) -> str:
    lines = [
        "```text",
        "AbeltonGod live_import result",
        f"script_version: {SCRIPT_VERSION}",
        f"python: {platform.python_version()} ({platform.system()} {platform.release()})",
        f"started_at: {r.started_at}",
        f"finished_at: {r.finished_at}",
        f"live_version_api: {r.live_version} (API reports major.minor only)",
        f"capability_overrides_used: {', '.join(sorted(set(r.overrides_used))) or '-'}",
        f"wav: {r.path}",
        f"tracks: {r.tracks!r}",
        f"num_scenes: {r.num_scenes if r.num_scenes is not None else '-'}",
        f"extension: {r.extension}",
        f"target: {r.target}",
        f"plan_confirmed: {'yes' if r.plan_confirmed else 'no'}",
        "steps:",
        *[f"  {s}" for s in r.steps or ["-"]],
        f"clip_slot.create_audio_clip: {r.import_result}",
        f"clip_file_path_read: {r.file_path_read}",
        f"user_hears_kick: {r.user_hears_kick}",
        f"song.undo: {r.undo_result}",
        f"action_log: {r.action_log}",
        f"error: {r.error or '-'}",
        "```",
    ]
    return "\n".join(lines)


# -- interaction -----------------------------------------------------------------------------

def ask(prompt: str, input_fn: Callable[[str], str]) -> str | None:
    """Stripped answer, or None on EOF. Ctrl+C propagates."""
    try:
        return input_fn(prompt).strip()
    except EOFError:
        return None


def ask_yes(prompt: str, input_fn: Callable[[str], str]) -> bool:
    return (ask(prompt, input_fn) or "").lower() in YES


def choose_target(names: list[str], audio: list[bool], input_fn: Callable[[str], str],
                  out: TextIO) -> tuple[bool, int | None]:
    """(chosen, track index or None for a new audio track). Not chosen -> (False, None)."""
    for _ in range(3):
        answer = ask("Ziel: Nummer einer Audiospur oder 'n' für eine neue Audiospur am Ende "
                     "[Enter = abbrechen]: ", input_fn)
        if not answer:
            return False, None
        if answer.lower() in NEW_TRACK:
            return True, None
        if answer.isascii() and answer.isdecimal() and int(answer) < len(names):
            idx = int(answer)
            if audio[idx]:
                return True, idx
            print(f"Spur {idx} '{names[idx]}' ist keine Audiospur. Ein Audio-Clip geht nur auf "
                  "eine Audiospur.", file=out)
            continue
        print(f"Ungültige Eingabe {answer!r}.", file=out)
    return False, None


def plan_text(path: str, names: list[str], track: int | None, slot: int) -> str:
    target = len(names)
    lines = ["", "Geplante Änderungen im Live-Set:"]
    n = 1
    if track is None:
        lines.append(f"  {n}. Neue Audiospur am Ende anlegen (wird Spur {target}).")
        n += 1
        where = f"die neue Spur {target}"
    else:
        where = f"Spur {track} '{names[track]}'"
    lines += [
        f"  {n}. Audio-Clip in {where}, Zelle (Szene) {slot}, aus der Datei:",
        f"       {path}",
        "     Live verweist auf die Datei; sie wird nicht kopiert oder verändert.",
        "Danach liest das Script die Zellen der Spur und den Dateipfad des Clips zurück.",
        "Jede Änderung wird vorher und nachher in das Aktions-Log geschrieben.",
        "",
        "Am Ende fragt das Script, ob es die Änderungen per Undo in Live zurücknehmen soll",
        "(Standard: nein). Undo wird nur gesendet, wenn das Set noch genau so aussieht, wie der",
        "Import es hinterlassen hat. Damit Undo nichts Fremdes zurücknimmt: Test-Set frisch",
        "öffnen und während des Scripts nichts in Live ändern.",
    ]
    return "\n".join(lines)


# -- the run ---------------------------------------------------------------------------------

class Stop(Exception):
    """End the run with this exit code (message already printed)."""

    def __init__(self, code: int, error: str | None = None) -> None:
        super().__init__(error or "")
        self.code, self.error = code, error


def run(bridge: AbletonBridge, report: Report, path: str, slot_arg: int | None,
        log: ActionLog, timeout_s: float, input_fn: Callable[[str], str], out: TextIO) -> int:
    host, send_port, _ = bridge.endpoint
    bridge.ping()
    print(f"Verbindung zu AbletonOSC ({host}:{send_port}) steht.\n", file=out)

    major, minor = bridge.get_version()
    report.live_version = f"{major}.{minor}"
    names = bridge.get_track_names()
    report.tracks = names
    num_scenes = bridge.get_num_scenes()
    report.num_scenes = num_scenes
    audio = [bridge.get_track_has_audio_input(i) for i in range(len(names))]
    print(f"Live-Version (laut API): {report.live_version}  Szenen: {num_scenes}", file=out)
    print(f"Spuren ({len(names)}):", file=out)
    for i, (name, is_audio) in enumerate(zip(names, audio, strict=True)):
        print(f"  {i}: {name}  [{'Audio' if is_audio else 'keine Audiospur'}]", file=out)

    if not bridge.probe_audio_clip_extension():
        report.extension = "MISSING"
        print("\n" + MSG_EXTENSION_MISSING, file=out)
        raise Stop(EXIT_EXTENSION_MISSING, "extension missing (Unknown OSC address)")
    report.extension = "PRESENT"
    print("AbeltonGod-Erweiterung: vorhanden.\n", file=out)

    if num_scenes < 1:
        print("Das Set hat keine Szene, also keine Zelle für einen Clip. Nichts geändert.",
              file=out)
        raise Stop(EXIT_CHECK_FAILED, "no scenes")
    if not ask_yes("Ist das geöffnete Set ein eigenes TEST-Set (kein echtes Projekt)? [y/N]: ",
                   input_fn):
        print("Keine Änderung (nur mit einem Test-Set erlaubt).", file=out)
        report.error = "user: not a test set"
        return EXIT_OK
    chosen, track = choose_target(names, audio, input_fn, out)
    if not chosen:
        print("Kein Ziel gewählt. Keine Änderung.", file=out)
        report.error = "no target chosen"
        return EXIT_OK

    if track is None:
        expected = SlotState(tuple(names), ())
        slot = 0 if slot_arg is None else slot_arg
    else:
        expected = read_state(bridge, track, num_scenes)
        empty = first_empty_slot(expected)
        slot = empty if slot_arg is None else slot_arg
        if slot is None:
            print(f"Spur {track} hat keine freie Zelle. Das Script legt keine Szenen an. "
                  "Nichts geändert.", file=out)
            raise Stop(EXIT_CHECK_FAILED, f"no empty slot on track {track}")
    if not 0 <= slot < num_scenes:
        print(f"Zelle {slot} gibt es nicht (Szenen 0-{num_scenes - 1}). Nichts geändert.",
              file=out)
        raise Stop(EXIT_CHECK_FAILED, f"slot {slot} out of range")
    if track is not None and expected.has_clip[slot]:
        print(f"Zelle {slot} von Spur {track} ist schon belegt. Das Script überschreibt keine "
              "Clips. Nichts geändert.", file=out)
        raise Stop(EXIT_CHECK_FAILED, f"slot {slot} of track {track} is occupied")
    report.target = (f"new audio track {len(names)}" if track is None
                     else f"track {track} {names[track]!r}") + f", slot {slot}"

    print(plan_text(path, names, track, slot), file=out)
    if not ask_yes("\nDiese Änderungen jetzt ausführen? [y/N]: ", input_fn):
        print("Keine Änderung.", file=out)
        report.error = "user answered no"
        return EXIT_OK
    report.plan_confirmed = True

    importer = ClipImporter(bridge, log, timeout_s=timeout_s)
    try:
        outcome = importer.run(path=path, track_index=track, slot_index=slot,
                               num_slots=num_scenes, expected_before=expected)
    except (ImportAborted, ActionLogError) as exc:
        return after_failed_import(importer.last_outcome, report, exc, out)
    finally:
        if importer.last_outcome is not None:
            report.steps = [f"{s.label}: {s.outcome}" + (f" ({s.detail})" if s.detail else "")
                            for s in importer.last_outcome.steps]
    report.import_result = "PASS"
    report.file_path_read = repr(outcome.file_path_read)
    print(f"\nOK: Clip liegt in Spur {outcome.track_index}, Zelle {slot}. Live meldet als "
          f"Datei:\n  {outcome.file_path_read}", file=out)

    answer = ask("\nBitte in Live die Zelle starten und anhören. Spielt der Kick? [y/n]: ",
                 input_fn)
    report.user_hears_kick = {"y": "yes", "j": "yes", "ja": "yes", "yes": "yes",
                              "n": "no", "nein": "no", "no": "no"}.get(
        (answer or "").lower(), "no answer")

    if not ask_yes("Import per Undo in Live zurücknehmen? [y/N]: ", input_fn):
        print("Kein Undo. Der Clip bleibt im Set." + (" Die neue Spur auch." if
                                                       outcome.created_track else ""), file=out)
        report.undo_result = "SKIPPED (user answered no)"
        return EXIT_OK
    return run_undo(importer, outcome, report, out)


def after_failed_import(outcome: ImportOutcome | None, report: Report, exc: Exception,
                        out: TextIO) -> int:
    report.import_result = "FAIL"
    report.error = f"{type(exc).__name__}: {exc}"
    interrupted = isinstance(exc, ImportInterrupted)
    report.interrupted = interrupted
    if outcome is None:
        print(f"FEHLER vor dem Senden: {exc}\nEs wurde nichts in Live geändert.", file=out)
        return EXIT_CHECK_FAILED
    if outcome.outcome_unknown:
        print("FEHLER: Ein Schritt wurde nicht bestätigt (Zeitüberschreitung oder Strg+C). Sein "
              "Ergebnis ist UNBEKANNT - Live führt ihn eventuell noch aus (z. B. nach einem "
              "geschlossenen Dialog).\nDas Script sendet nichts mehr und KEIN Undo. Bitte in "
              "Live nachsehen; zurückgelesen: " + str(exc), file=out)
    else:
        print(f"FEHLER: {exc}\nDas Script sendet nichts mehr und kein Undo.", file=out)
    if any(s.outcome == "confirmed" for s in outcome.steps):
        print("Bereits ausgeführt: " + ", ".join(s.label for s in outcome.steps
                                                  if s.outcome == "confirmed")
              + ". Entfernen bitte von Hand in Live (oder Strg+Z, wenn du sicher bist, was es "
              "zurücknimmt). " + UNDO_HINT, file=out)
    else:
        print("Kein Schritt wurde von AbletonOSC bestätigt.", file=out)
    return EXIT_INTERRUPTED if interrupted else EXIT_CHECK_FAILED


def run_undo(importer: ClipImporter, outcome: ImportOutcome, report: Report,
             out: TextIO) -> int:
    after, clip_before, before = outcome.after, outcome.after_track or outcome.before, \
        outcome.before
    assert after is not None
    results: list[str] = []
    try:
        ok = importer.undo_step(outcome, expect_now=after, expect_after=clip_before,
                                label="undo_clip")
        report.steps.append("undo_clip: " + ("ok" if ok else "read-back differs"))
        state_now = outcome.steps[-1].detail
        if not ok:
            now = read_state(importer.bridge, outcome.track_index, len(after.has_clip))
            if outcome.created_track and now.track_names == before.track_names:
                # One undo removed track and clip together: the set is as before the import.
                report.undo_result = "PASS (one undo reverted track and clip together)"
                print("Undo hat Clip und neue Spur in einem Schritt zurückgenommen. Das Set ist "
                      "wie vor dem Import (soweit das Script sieht).", file=out)
                return EXIT_OK
            report.undo_result = f"FAIL (after undo_clip: {state_now})"
            print("FEHLER: Nach dem Undo sieht das Set nicht so aus wie vor dem Clip. Das Script "
                  "sendet KEIN weiteres Undo. " + UNDO_HINT, file=out)
            return EXIT_CHECK_FAILED
        results.append("clip removed")
        print("Undo 1: Clip ist wieder weg (zurückgelesen).", file=out)
        if outcome.created_track:
            ok = importer.undo_step(outcome, expect_now=clip_before,
                                    expect_after=SlotState(before.track_names, ()),
                                    label="undo_track")
            report.steps.append("undo_track: " + ("ok" if ok else "read-back differs"))
            if not ok:
                report.undo_result = "FAIL (after undo_track: " + outcome.steps[-1].detail + ")"
                print("FEHLER: Nach dem zweiten Undo sieht das Set nicht so aus wie vor dem "
                      "Import. Das Script sendet nichts mehr. " + UNDO_HINT, file=out)
                return EXIT_CHECK_FAILED
            results.append("track removed")
            print("Undo 2: neue Spur ist wieder weg (zurückgelesen).", file=out)
    except (ImportInterrupted, KeyboardInterrupt) as exc:
        report.undo_result = f"FAIL (interrupted: {type(exc).__name__} {exc}; " \
                             f"undos sent: {outcome.undos_sent})"
        report.interrupted = True
        print("\nABGEBROCHEN mit Strg+C während des Undo. Ergebnis unbekannt; das Script sendet "
              "nichts mehr. " + UNDO_HINT, file=out)
        return EXIT_INTERRUPTED
    except (ImportAborted, ActionLogError, BridgeError) as exc:
        report.undo_result = f"FAIL ({type(exc).__name__}: {exc})"
        print(f"FEHLER beim Undo: {exc}\nDas Script sendet nichts mehr. " + UNDO_HINT, file=out)
        return EXIT_CHECK_FAILED
    report.undo_result = "PASS (" + ", ".join(results) + "; read back)"
    print("Das Set ist wieder wie vor dem Import (geprüft: Spurnamen und Zellen der Zielspur; "
          "nicht geprüft: andere Spuren, Geräte, Automation).", file=out)
    return EXIT_OK


def env_port(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AbeltonGod: eine WAV als Clip in Live importieren "
                                            "(#50).")
    p.add_argument("wav", help="absoluter Pfad zur WAV-Datei")
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
    report = Report(started_at=now_iso())
    print(f"AbeltonGod live_import {SCRIPT_VERSION}\n", file=out)
    code = EXIT_OK
    bridge: AbletonBridge | None = None
    log = ActionLog(args.log)
    try:
        report.path = validate_wav_path(args.wav)
        report.action_log = str(log.path)
        send_port = (args.send_port if args.send_port is not None
                     else env_port("ABLETON_OSC_SEND_PORT", DEFAULT_SEND_PORT))
        receive_port = (args.receive_port if args.receive_port is not None
                        else env_port("ABLETON_OSC_RECEIVE_PORT", DEFAULT_RECEIVE_PORT))
        try:
            bridge = AbletonBridge.connect(
                DEFAULT_HOST, send_port, receive_port, timeout_s=args.timeout,
                registry=CapabilityRegistry.from_file(), allow_untested=ALLOWED)
        except ReceivePortInUseError as exc:
            print(MSG_PORT_IN_USE.format(port=receive_port, host=DEFAULT_HOST), file=out)
            report.error = f"ReceivePortInUseError: {exc}"
            code = EXIT_PORT_IN_USE
        if bridge is not None:
            try:
                code = run(bridge, report, report.path, args.slot, log, args.timeout,
                           input_fn, out)
            except Stop as stop:
                code, report.error = stop.code, stop.error
            except KeyboardInterrupt:
                report.interrupted = True
                report.error = "interrupted by user (Ctrl+C) outside a write"
                if report.import_result == "PASS":
                    tail = "Der Import war schon fertig; der Clip bleibt im Set."
                elif report.plan_confirmed:
                    tail = ("Ob schon etwas gesendet wurde, ist unbekannt. Bitte in Live "
                            "nachsehen. " + UNDO_HINT)
                else:
                    tail = "Es wurde nichts in Live geändert."
                print("\nABGEBROCHEN mit Strg+C. " + tail, file=out)
            except BridgeUnavailableError as exc:
                print(msg_no_answer(DEFAULT_HOST, send_port) + "\n" + (
                    "Es wurde nichts in Live geändert." if not report.plan_confirmed
                    else "Bitte in Live nachsehen, was schon ausgeführt wurde."), file=out)
                report.error = f"{type(exc).__name__}: {exc}"
                code = EXIT_NO_CONNECTION
            except BridgeError as exc:
                print(f"FEHLER: unerwartete Antwort von AbletonOSC: {exc}", file=out)
                report.error = f"{type(exc).__name__}: {exc}"
                code = EXIT_CHECK_FAILED
            report.overrides_used = list(bridge.gate.overrides_used)
    except ImportPathError as exc:
        print(f"FEHLER mit der Datei: {exc}\nEs wurde nichts in Live geändert.", file=out)
        report.error = f"ImportPathError: {exc}"
        code = EXIT_SETUP_ERROR
    except (CapabilityError, ValueError) as exc:
        print(f"FEHLER in der Konfiguration: {exc}", file=out)
        report.error = f"{type(exc).__name__}: {exc}"
        code = EXIT_SETUP_ERROR
    finally:
        if bridge is not None:
            bridge.close()
    if report.interrupted:
        code = EXIT_INTERRUPTED
    report.finished_at = now_iso()
    print("\nBitte den folgenden Block komplett in Issue #50 einfügen:\n", file=out)
    print(render_result_block(report), file=out)
    return code


if __name__ == "__main__":
    sys.exit(main())
