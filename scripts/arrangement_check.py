"""Arrangement capability check in the open Live set (#140; questionnaire task A3).

Run it on the Windows machine with Live open on a *dedicated, freshly opened test set*, after
installing the extension 0.2.0 (``scripts/install_abletonosc_extension.py``,
``docs/setup/ABLETONOSC_WINDOWS.md`` section 8):

    python scripts/arrangement_check.py      # bar 5, 4 bars, locator "AbeltonGod Test"
    python scripts/arrangement_check.py --bar 9 --bars 2 --name Intro

Steps:
1. Connects, reads Live version, signature (only 4/4 is accepted), tracks, locators, song
   position and whether Live is playing (it must be stopped).
2. Checks that the extension answers (three no-argument calls; they change nothing in Live
   and leave three ERROR lines in ``abletonosc.log``). If not: install hint.
3. Refuses before anything is sent if a locator exists at the clip start (adding a locator is
   a toggle in Live: it would delete that one).
4. Asks "test set?" (default No), prints the plan, asks again (default No).
5. Writes (``bridge.arrangement_check.ArrangementWriter``): song position to the clip start
   (if not there), new MIDI track at the end, empty MIDI clip in the Arrangement, one note per
   beat (C1), a locator at the clip start, its name. Action-log entry before and after every
   write; each write is read back before the next one.
6. Asks right away whether to undo everything (default No), *before* the user looks at or
   touches anything in Live (#50 runs 2 and 3). Yes: one undo at a time, each read back, the
   chain stops at the first surprise. No: everything stays; asks whether Live shows it and
   prints how to remove it by hand.
7. Prints a result block to paste into issue #140.

Capability gate: none of the new calls has a registry entry yet; they run only through the
explicit ``allow_unregistered`` opt-in below and are listed in ``capability_overrides_used``.
``song.undo`` is ``tested``. Statuses and entries change only in a separate contract-change PR
with the pasted output as evidence (D-004).

Never sends destructive commands. User-facing text is German; code and comments are English.
"""

from __future__ import annotations

import argparse
import logging
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from bridge.arrangement_check import (
    ArrangementOutcome,
    ArrangementPlan,
    ArrangementState,
    ArrangementWriter,
    make_plan,
    read_arrangement_state,
    same_time,
)
from bridge.capabilities import CapabilityError, CapabilityRegistry
from bridge.check_cli import (
    MSG_PORT_IN_USE,
    UNDO_HINT,
    ask,
    ask_yes,
    env_port,
    msg_no_answer,
    now_iso,
)
from bridge.clip_import import (
    DEFAULT_ACTION_LOG,
    ActionLog,
    ActionLogError,
    ImportAborted,
    ImportInterrupted,
)
from bridge.osc_client import (
    DEFAULT_HOST,
    DEFAULT_RECEIVE_PORT,
    DEFAULT_SEND_PORT,
    DEFAULT_TIMEOUT_S,
    UNREGISTERED,
    AbletonBridge,
    BridgeError,
    BridgeUnavailableError,
    ReceivePortInUseError,
)

SCRIPT_VERSION = "0.1.0"

# Every unregistered capability this script may call (#140); nothing else is opted in.
ALLOW_UNREGISTERED = tuple(UNREGISTERED)

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_NO_CONNECTION = 2
EXIT_PORT_IN_USE = 3
EXIT_SETUP_ERROR = 4
EXIT_EXTENSION_MISSING = 5
EXIT_INTERRUPTED = 130

DEFAULT_BAR = 5
DEFAULT_BARS = 4
DEFAULT_NAME = "AbeltonGod Test"

# Capability -> step label, in run order (result block).
CAPABILITY_STEPS = (
    ("song.current_song_time.set", "set_song_time"),
    ("song.create_midi_track", "create_midi_track"),
    ("track.create_midi_clip", "create_midi_clip"),
    ("arrangement_clip.notes.add", "add_notes"),
    ("song.cue_point.add_or_delete", "add_cue"),
    ("song.cue_point.set_name", "set_cue_name"),
)

MSG_EXTENSION_MISSING = (
    "FEHLER: Die AbeltonGod-Erweiterung 0.2.0 fehlt in AbletonOSC (AbletonOSC kennt die\n"
    "Arrangement-Befehle nicht: {missing}). Es wurde nichts in Live geändert.\n"
    "  1. Live beenden.\n"
    "  2. python scripts/install_abletonosc_extension.py\n"
    "  3. Live starten, das Test-Set öffnen und dieses Script erneut ausführen.\n"
    "Anleitung: docs/setup/ABLETONOSC_WINDOWS.md, Abschnitt 8."
)

UNDO_CHOICE = (
    "\nJetzt entscheiden: Undo ODER Nachsehen (beides nacheinander ist nicht sicher).\n"
    "  y     = alles sofort per Undo zurücknehmen, ohne in Live nachzusehen. Bis dahin in Live\n"
    "          nichts anklicken, scrollen oder starten: eine Aktion in Live kann ein eigener\n"
    "          Undo-Schritt sein; dann nimmt Undo diese zurück, oder das Script hält an (#50).\n"
    "  Enter = kein Undo. Alles bleibt im Set; du siehst es dir in Live an. Entfernen danach\n"
    "          von Hand (das Script sagt wie)."
)


def bar_of(beats: float) -> str:
    return f"Takt {int(beats // 4) + 1}"


def manual_removal_text(outcome: ArrangementOutcome) -> str:
    """How to remove the check's changes by hand (German), from the newest read-back."""
    state = outcome.newest_state()
    plan = outcome.plan
    lines = ["Von Hand entfernen, nur was noch da ist (erst in Live nachsehen):"]
    name = state.target_name()
    if name is not None and name in outcome.target_names_seen():
        lines.append(f"  - Spur {outcome.target_index} '{name}' (ganz rechts/unten): Spurkopf "
                     "anklicken, Entf drücken. Das entfernt auch den Clip und die Noten.")
    else:
        lines.append(f"  - neue MIDI-Spur: laut letztem Zurücklesen nicht da (Spur "
                     f"{outcome.target_index}).")
    ours = {plan.locator_name, outcome.cue_default_name}
    cues = [c for c in state.cue_at(plan.start) if c[0] in ours]
    if cues:
        lines.append(f"  - Locator '{cues[0][0]}' bei {bar_of(plan.start)}: im Arrangement "
                     "anklicken, Entf drücken.")
    else:
        lines.append(f"  - Locator bei {bar_of(plan.start)}: laut letztem Zurücklesen nicht da.")
    lines.append("  Strg+Z nur, wenn du in der Widerrufen-Historie siehst, was es zurücknimmt.")
    return "\n".join(lines)


# -- report ----------------------------------------------------------------------------------

@dataclass
class Report:
    started_at: str
    live_version: str = "unbekannt"
    signature: str = "-"
    is_playing: str = "-"
    song_time_before: str = "-"
    tracks: list[str] = field(default_factory=list)
    cues: list = field(default_factory=list)
    extension: str = "SKIPPED"
    plan: str = "-"
    plan_confirmed: bool = False
    steps: list[str] = field(default_factory=list)
    results: dict[str, str] = field(default_factory=dict)
    clips_read: str = "-"
    notes_read: str = "-"
    cue_default_name: str = "-"
    target_name: str = "-"
    undo_result: str = "SKIPPED"
    undo_chain: list[str] = field(default_factory=list)
    song_time_after: str = "-"
    user_sees_result: str = "not asked"
    action_log: str = "-"
    overrides_used: list[str] = field(default_factory=list)
    writer: ArrangementWriter | None = None
    error: str | None = None
    interrupted: bool = False
    finished_at: str = ""


def render_result_block(r: Report) -> str:
    lines = [
        "```text",
        "AbeltonGod arrangement_check result",
        f"script_version: {SCRIPT_VERSION}",
        f"python: {platform.python_version()} ({platform.system()} {platform.release()})",
        f"started_at: {r.started_at}",
        f"finished_at: {r.finished_at}",
        f"live_version_api: {r.live_version} (API reports major.minor only)",
        f"capability_overrides_used: {', '.join(sorted(set(r.overrides_used))) or '-'}",
        f"signature: {r.signature}",
        f"is_playing_before: {r.is_playing}",
        f"song_time_before: {r.song_time_before}",
        f"tracks_before: {r.tracks!r}",
        f"cue_points_before: {r.cues!r}",
        f"extension: {r.extension}",
        f"plan: {r.plan}",
        f"plan_confirmed: {'yes' if r.plan_confirmed else 'no'}",
        "steps:",
        *[f"  {s}" for s in r.steps or ["-"]],
        *[f"{cap}: {r.results.get(cap, 'SKIPPED')}" for cap, _ in CAPABILITY_STEPS],
        f"arrangement_clips_read: {r.clips_read}",
        f"notes_read: {r.notes_read}",
        f"cue_default_name: {r.cue_default_name}",
        f"target_track_name: {r.target_name}",
        f"song.undo: {r.undo_result}",
        "undo_chain:",
        *[f"  {s}" for s in r.undo_chain or ["-"]],
        f"song_time_after: {r.song_time_after}",
        f"user_sees_result: {r.user_sees_result}",
        f"action_log: {r.action_log}",
        f"error: {r.error or '-'}",
        "```",
    ]
    return "\n".join(lines)


def fill_from_outcome(report: Report, outcome: ArrangementOutcome | None) -> None:
    if outcome is None:
        return
    report.steps = [f"{s.label}: {s.outcome}" + (f" ({s.detail})" if s.detail else "")
                    for s in outcome.steps]
    report.results.update(outcome.results)
    report.undo_chain = list(outcome.undo_chain)
    report.cue_default_name = repr(outcome.cue_default_name) if outcome.cue_default_name \
        is not None else "-"
    last = outcome.last
    if last.target_name() is not None:
        report.clips_read = repr(list(last.clips))
        report.notes_read = ("-" if last.notes is None else
                             f"{len(last.notes)} notes; first {list(last.notes[:2])!r}")
    names = [n for _l, s in outcome.snapshots if (n := s.target_name()) is not None]
    report.target_name = " -> ".join(dict.fromkeys(repr(n) for n in names)) or "-"
    report.song_time_after = f"{outcome.newest_state().song_time:g}"


# -- the run ---------------------------------------------------------------------------------

class Stop(Exception):
    """End the run with this exit code (message already printed)."""

    def __init__(self, code: int, error: str | None = None) -> None:
        super().__init__(error or "")
        self.code, self.error = code, error


def plan_text(plan: ArrangementPlan, names: list[str], state: ArrangementState) -> str:
    target = len(names)
    lines = ["", "Geplante Änderungen im Live-Set (in dieser Reihenfolge):"]
    n = 1
    if not same_time(state.song_time, plan.start):
        lines.append(f"  {n}. Abspielposition auf {bar_of(plan.start)} setzen (Beat "
                     f"{plan.start:g}; jetzt Beat {state.song_time:g}). Wird nicht "
                     "zurückgesetzt.")
        n += 1
    lines += [
        f"  {n}. Neue MIDI-Spur am Ende anlegen (wird Spur {target}).",
        f"  {n + 1}. Im ARRANGEMENT dieser Spur einen leeren MIDI-Clip anlegen: ab "
        f"{bar_of(plan.start)}, {plan.bars} Takt(e) lang.",
        f"  {n + 2}. {len(plan.notes())} Noten in den Clip schreiben (C1, eine pro Schlag).",
        f"  {n + 3}. Einen Locator bei {bar_of(plan.start)} setzen.",
        f"  {n + 4}. Den Locator '{plan.locator_name}' nennen.",
        "Nach jedem Schritt liest das Script zurück, was Live zeigt, und hält bei jeder",
        "Abweichung an. Jede Änderung steht vorher und nachher im Aktions-Log.",
        "",
        "Direkt danach fragt das Script, ob es alles sofort per Undo zurücknehmen soll",
        "(Standard: nein). Damit Undo nichts Fremdes zurücknimmt: Test-Set frisch öffnen und",
        "während des Scripts in Live nichts anklicken, scrollen oder starten.",
    ]
    return "\n".join(lines)


def run(bridge: AbletonBridge, report: Report, plan: ArrangementPlan, log: ActionLog,
        timeout_s: float, input_fn: Callable[[str], str], out: TextIO) -> int:
    host, send_port, _ = bridge.endpoint
    bridge.ping()
    print(f"Verbindung zu AbletonOSC ({host}:{send_port}) steht.\n", file=out)

    major, minor = bridge.get_version()
    report.live_version = f"{major}.{minor}"
    num, den = bridge.get_signature()
    report.signature = f"{num}/{den}"
    names = bridge.get_track_names()
    report.tracks = names
    playing = bridge.get_is_playing()
    report.is_playing = str(playing)
    state = read_arrangement_state(bridge, len(names))
    report.cues = [list(c) for c in state.cues]
    report.song_time_before = f"{state.song_time:g}"
    print(f"Live-Version (laut API): {report.live_version}  Taktart: {report.signature}  "
          f"Position: Beat {state.song_time:g}", file=out)
    print(f"Spuren ({len(names)}): " + ", ".join(f"{i}: {n}" for i, n in enumerate(names)),
          file=out)
    print("Locator: " + (", ".join(f"'{n}' bei Beat {t:g}" for n, t in state.cues) or "keine"),
          file=out)

    missing = bridge.probe_arrangement_extension()
    if missing:
        report.extension = "MISSING (" + ", ".join(missing) + ")"
        print("\n" + MSG_EXTENSION_MISSING.format(missing=", ".join(missing)), file=out)
        raise Stop(EXIT_EXTENSION_MISSING, "extension missing (Unknown OSC address)")
    report.extension = "PRESENT"
    print("AbeltonGod-Erweiterung (Arrangement): vorhanden.\n", file=out)

    if (num, den) != (4, 4):
        print(f"Das Set steht auf {num}/{den}. Das Script rechnet Takte nur in 4/4. Nichts "
              "geändert.", file=out)
        raise Stop(EXIT_CHECK_FAILED, f"signature {num}/{den}, only 4/4 supported")
    if playing:
        print("Live spielt gerade. Bitte die Wiedergabe stoppen und das Script neu starten. "
              "Nichts geändert.", file=out)
        raise Stop(EXIT_CHECK_FAILED, "Live is playing")
    if state.cue_at(plan.start):
        print(f"Bei {bar_of(plan.start)} gibt es schon einen Locator. Einen Locator setzen ist "
              "in Live ein Umschalter: das Script würde ihn LÖSCHEN. Nichts geändert. Anderen "
              "Takt wählen (--bar).", file=out)
        raise Stop(EXIT_CHECK_FAILED, f"a locator exists at beat {plan.start:g}")
    report.plan = (f"new MIDI track {len(names)}; Arrangement MIDI clip at bar {plan.bar} "
                   f"(beat {plan.start:g}), {plan.length:g} beats; {len(plan.notes())} notes "
                   f"pitch 36; locator {plan.locator_name!r} at beat {plan.start:g}")

    if not ask_yes("Ist das geöffnete Set ein eigenes TEST-Set (kein echtes Projekt)? [y/N]: ",
                   input_fn):
        print("Keine Änderung (nur mit einem Test-Set erlaubt).", file=out)
        report.error = "user: not a test set"
        return EXIT_OK
    print(plan_text(plan, names, state), file=out)
    if not ask_yes("\nDiese Änderungen jetzt ausführen? [y/N]: ", input_fn):
        print("Keine Änderung.", file=out)
        report.error = "user answered no"
        return EXIT_OK
    report.plan_confirmed = True

    writer = ArrangementWriter(bridge, log, timeout_s=timeout_s)
    report.writer = writer
    try:
        outcome = writer.run(plan, state)
    except (ImportAborted, ActionLogError) as exc:
        return after_failed_run(writer.last_outcome, report, exc, out)
    finally:
        fill_from_outcome(report, writer.last_outcome)
    print("\nOK: Spur, Arrangement-Clip, Noten und Locator sind da (zurückgelesen).", file=out)

    print(UNDO_CHOICE, file=out)
    if ask_yes("Alles jetzt per Undo zurücknehmen, OHNE Nachsehen? [y/N]: ", input_fn):
        report.user_sees_result = "not asked (undo chosen before looking)"
        return run_undo(writer, outcome, report, out)
    report.undo_result = "SKIPPED (user answered no)"
    print("Kein Undo. Alles bleibt im Set.", file=out)
    answer = ask(f"\nBitte in Live ins Arrangement schauen: Siehst du in der neuen Spur ab "
                 f"{bar_of(plan.start)} einen MIDI-Clip mit Noten und darüber den Locator "
                 f"'{plan.locator_name}'? [y/n]: ", input_fn)
    report.user_sees_result = {"y": "yes", "j": "yes", "ja": "yes", "yes": "yes",
                               "n": "no", "nein": "no", "no": "no"}.get(
        (answer or "").lower(), "no answer")
    print("\nZum Aufräumen später:\n" + manual_removal_text(outcome), file=out)
    return EXIT_OK


def after_failed_run(outcome: ArrangementOutcome | None, report: Report, exc: Exception,
                     out: TextIO) -> int:
    report.error = f"{type(exc).__name__}: {exc}"
    interrupted = isinstance(exc, ImportInterrupted)
    report.interrupted = interrupted
    if outcome is None:
        print(f"FEHLER vor dem Senden: {exc}\nEs wurde nichts in Live geändert.", file=out)
        return EXIT_CHECK_FAILED
    if outcome.outcome_unknown:
        print("FEHLER: Ein Schritt ist nicht bestätigt oder das Zurücklesen zeigt nicht das "
              "erwartete Ergebnis. Was Live genau gemacht hat, ist UNBEKANNT (Live führt ihn "
              "eventuell noch aus).\nDas Script sendet nichts mehr und KEIN Undo. "
              f"Zurückgelesen: {exc}", file=out)
    else:
        print(f"FEHLER: {exc}\nDas Script sendet nichts mehr und kein Undo.", file=out)
    confirmed = [s.label for s in outcome.steps if s.outcome == "confirmed"]
    if confirmed:
        print("Bereits ausgeführt: " + ", ".join(confirmed) + ".\n"
              + manual_removal_text(outcome) + "\n" + UNDO_HINT, file=out)
    else:
        print("Kein Schritt wurde von AbletonOSC bestätigt.", file=out)
    return EXIT_INTERRUPTED if interrupted else EXIT_CHECK_FAILED


def run_undo(writer: ArrangementWriter, outcome: ArrangementOutcome, report: Report,
             out: TextIO) -> int:
    try:
        result = writer.undo_all(outcome)
    except (ImportInterrupted, KeyboardInterrupt) as exc:
        report.undo_result = (f"FAIL (interrupted: {type(exc).__name__} {exc}; undos sent: "
                              f"{outcome.undos_sent})")
        report.interrupted = True
        print("\nABGEBROCHEN mit Strg+C während des Undo. Ergebnis unbekannt; das Script sendet "
              "nichts mehr.\n" + manual_removal_text(outcome) + "\n" + UNDO_HINT, file=out)
        return EXIT_INTERRUPTED
    except (ImportAborted, ActionLogError, BridgeError) as exc:
        report.undo_result = f"FAIL ({type(exc).__name__}: {exc})"
        refused = bool(outcome.steps) and outcome.steps[-1].outcome == "refused"
        print(f"FEHLER beim Undo: {exc}\nDas Script sendet nichts mehr."
              + (" Das Set sah vor dem Undo nicht so aus, wie das Script es zuletzt gelesen "
                 "hat (z. B. nach einer Aktion in Live); darum wurde KEIN Undo gesendet."
                 if refused else "")
              + "\n" + manual_removal_text(outcome) + "\n" + UNDO_HINT, file=out)
        return EXIT_CHECK_FAILED
    finally:
        fill_from_outcome(report, outcome)
    for line in outcome.undo_chain:
        print("  " + line, file=out)
    if not result.passed:
        report.undo_result = f"FAIL ({result.detail})"
        print(f"FEHLER: {result.detail}. Was das letzte Undo zurückgenommen hat, ist unbekannt. "
              "Das Script sendet KEIN weiteres Undo.\n" + manual_removal_text(outcome)
              + "\n" + UNDO_HINT, file=out)
        return EXIT_CHECK_FAILED
    report.undo_result = f"PASS ({result.detail})"
    print("Das Set ist wieder wie vor dem Check (geprüft: alle Spurnamen, Anzahl der Spuren, "
          "alle Locator; nicht geprüft: Clips anderer Spuren, Geräte, Automation). Die "
          f"Abspielposition steht auf Beat {outcome.newest_state().song_time:g}.", file=out)
    return EXIT_OK


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AbeltonGod: Arrangement-Check in Live (#140).")
    p.add_argument("--bar", type=int, default=DEFAULT_BAR,
                   help=f"Takt, an dem Clip und Locator beginnen (ab 1; Standard {DEFAULT_BAR})")
    p.add_argument("--bars", type=int, default=DEFAULT_BARS,
                   help=f"Länge des Clips in Takten (1-16; Standard {DEFAULT_BARS})")
    p.add_argument("--name", default=DEFAULT_NAME,
                   help=f"Name des Locators (Standard {DEFAULT_NAME!r})")
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
    print(f"AbeltonGod arrangement_check {SCRIPT_VERSION}\n", file=out)
    code = EXIT_OK
    bridge: AbletonBridge | None = None
    log = ActionLog(args.log)
    try:
        plan = make_plan(args.bar, args.bars, args.name)
        report.action_log = str(log.path)
        send_port = (args.send_port if args.send_port is not None
                     else env_port("ABLETON_OSC_SEND_PORT", DEFAULT_SEND_PORT))
        receive_port = (args.receive_port if args.receive_port is not None
                        else env_port("ABLETON_OSC_RECEIVE_PORT", DEFAULT_RECEIVE_PORT))
        try:
            bridge = AbletonBridge.connect(
                DEFAULT_HOST, send_port, receive_port, timeout_s=args.timeout,
                registry=CapabilityRegistry.from_file(),
                allow_unregistered=ALLOW_UNREGISTERED)
        except ReceivePortInUseError as exc:
            print(MSG_PORT_IN_USE.format(port=receive_port, host=DEFAULT_HOST), file=out)
            report.error = f"ReceivePortInUseError: {exc}"
            code = EXIT_PORT_IN_USE
        if bridge is not None:
            try:
                code = run(bridge, report, plan, log, args.timeout, input_fn, out)
            except Stop as stop:
                code, report.error = stop.code, stop.error
            except KeyboardInterrupt:
                report.interrupted = True
                report.error = "interrupted by user (Ctrl+C) outside a write"
                done = report.writer.last_outcome if report.writer is not None else None
                if done is not None and done.done:
                    # Ctrl+C at the undo or the "do you see it" prompt: everything stays.
                    tail = ("Die Schritte waren schon fertig; alles bleibt im Set.\n"
                            + manual_removal_text(done))
                elif done is not None:
                    # Between two writes (every send itself is caught in the writer).
                    tail = ("Bereits ausgeführt: " + (", ".join(
                        s.label for s in done.steps if s.outcome == "confirmed") or "nichts")
                        + ".\n" + manual_removal_text(done) + "\n" + UNDO_HINT)
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
    print("\nBitte den folgenden Block komplett in Issue #140 einfügen:\n", file=out)
    print(render_result_block(report), file=out)
    return code


if __name__ == "__main__":
    sys.exit(main())
