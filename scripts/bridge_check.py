"""Manual bridge check against Ableton Live via AbletonOSC (Phase 02, issue #5).

Run it on the Windows machine with Live open on a *dedicated test set*:

    python scripts/bridge_check.py

What it does:
1. Connectivity: a marker round trip (``ping``), which also checks that AbletonOSC echoes extra
   getter arguments - the request bracketing of ``src/bridge/osc_client.py`` relies on it.
2. Reads (no change in Live): Live version (major/minor only - AbletonOSC does not expose the
   patch level), tempo, time signature, track names, and the mute state of one track.
3. Only after two explicit confirmations ("test set?" and "run these changes?", both default
   No): a reversible mute sequence on one track, ending with ``/live/song/undo``:

       R0 read mute            -> M0 (original state)
       W1 set mute = not M0    -> R1 expect not M0
       W2 set mute = M0        -> R2 expect M0
       W3 set mute = not M0    -> R3 expect not M0
       U  /live/song/undo      -> R4 expect M0  (undo reverts W3)

   Both directions of the mute write are exercised, undo is exercised for real, and if undo
   works the set ends exactly as it started. If R4 is not M0, undo did not revert W3 (it may
   have reverted something else in the set): the script then sets mute back to M0 once (W4),
   reads it back (R5) and reports undo as FAIL. No second undo is ever sent.
   If a read-back does not match (R1-R3), undo is not sent: the write did not land as
   expected, so an undo could revert something else. If any write times out, its outcome is
   unknown (it may still be applied later). In both cases the script stops writing, reads the
   state back once, never sends undo, and tells the user the original state.
4. Prints a fenced result block to paste into issue #5.

Capability gate: every capability in ``contracts/capabilities.json`` that this script touches is
still ``supported``. The script uses the gate's explicit check-script override
(``allow_untested``); it never changes the registry. Statuses become ``tested`` only in a
separate contract-change PR, with the pasted output as evidence.

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
from typing import TextIO

from bridge.capabilities import CapabilityError, CapabilityRegistry
from bridge.osc_client import (
    DEFAULT_HOST,
    DEFAULT_RECEIVE_PORT,
    DEFAULT_SEND_PORT,
    DEFAULT_TIMEOUT_S,
    AbletonBridge,
    AbletonOSCError,
    BridgeError,
    BridgeProtocolError,
    BridgeTimeoutError,
    BridgeUnavailableError,
    ReceivePortInUseError,
)

SCRIPT_VERSION = "0.1.0"

# The only capabilities this script may call, through the explicit override.
READ_CAPABILITIES = ("app.version", "song.tempo.get", "song.signature.get",
                     "song.track_names.get")
WRITE_CAPABILITIES = ("track.mute.set", "song.undo")
ALLOWED = READ_CAPABILITIES + WRITE_CAPABILITIES

PASS, FAIL, SKIPPED = "PASS", "FAIL", "SKIPPED"

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_NO_CONNECTION = 2
EXIT_PORT_IN_USE = 3
EXIT_SETUP_ERROR = 4

YES = {"y", "yes", "j", "ja"}


# -- German user messages --------------------------------------------------------------------


def msg_no_answer(host: str, send_port: int) -> str:
    return (
        f"FEHLER: AbletonOSC antwortet nicht ({host}:{send_port}).\n"
        "Mögliche Ursachen (von hier aus nicht zu unterscheiden, bitte alle prüfen):\n"
        "  1. Ableton Live ist nicht geöffnet.\n"
        "  2. 'AbletonOSC' ist nicht als Control Surface ausgewählt\n"
        "     (Optionen -> Einstellungen -> Link, Tempo & MIDI).\n"
        "  3. In Live ist ein Dialog offen (z. B. Speichern) und blockiert die Antwort.\n"
        "  4. Live wurde nach dem Kopieren von AbletonOSC nicht neu gestartet.\n"
        "Log: ...\\Remote Scripts\\AbletonOSC\\logs\\abletonosc.log\n"
        "Es wurde nichts in Live geändert."
    )


def msg_port_in_use(host: str, receive_port: int) -> str:
    return (
        f"FEHLER: Port {receive_port} ({host}) ist schon belegt.\n"
        "Ein anderes Programm empfängt dort bereits Antworten von AbletonOSC - zum Beispiel ein\n"
        "zweites Terminal, in dem dieses Script oder der Ping-Test noch läuft. Dieses Programm\n"
        "schließen und das Script erneut starten. Es wurde nichts in Live geändert."
    )


# -- result model ----------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    result: str = SKIPPED
    raw: str = "-"
    note: str = ""


@dataclass
class Report:
    started_at: str
    checks: dict[str, CheckResult] = field(default_factory=dict)
    live_version: str = "unbekannt"
    track_index: int | None = None
    track_name: str | None = None
    write_log: list[str] = field(default_factory=list)
    error: str | None = None
    finished_at: str = ""
    overrides_used: list[str] = field(default_factory=list)

    def check(self, name: str) -> CheckResult:
        if name not in self.checks:
            self.checks[name] = CheckResult(name)
        return self.checks[name]

    def any_failed(self) -> bool:
        return any(c.result == FAIL for c in self.checks.values())


CHECK_ORDER = ("bridge.marker_echo",) + ALLOWED


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")


def render_result_block(report: Report) -> str:
    lines = [
        "```text",
        "AbeltonGod bridge_check result",
        f"script_version: {SCRIPT_VERSION}",
        f"python: {platform.python_version()} ({platform.system()} {platform.release()})",
        f"started_at: {report.started_at}",
        f"finished_at: {report.finished_at}",
        f"live_version_api: {report.live_version} (API reports major.minor only)",
        f"capability_overrides_used: {', '.join(sorted(set(report.overrides_used))) or '-'}",
    ]
    if report.track_index is not None:
        lines.append(f"test_track: {report.track_index} {report.track_name!r}")
    for name in CHECK_ORDER:
        c = report.checks.get(name, CheckResult(name))
        line = f"{c.name}: {c.result} raw={c.raw}"
        if c.note:
            line += f" note={c.note}"
        lines.append(line)
    if report.write_log:
        lines.append("write_sequence:")
        lines.extend(f"  {entry}" for entry in report.write_log)
    lines.append(f"error: {report.error or '-'}")
    lines.append("```")
    return "\n".join(lines)


# -- interaction -----------------------------------------------------------------------------


def ask(prompt: str, input_fn: Callable[[str], str]) -> str:
    try:
        return input_fn(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def ask_yes(prompt: str, input_fn: Callable[[str], str]) -> bool:
    return ask(prompt, input_fn).lower() in YES


def choose_track(names: list[str], input_fn: Callable[[str], str], out: TextIO) -> int | None:
    for _ in range(3):
        answer = ask(
            f"Welche Spur soll kurz stummgeschaltet werden? Index 0-{len(names) - 1} "
            f"[Enter = 0 '{names[0]}']: ",
            input_fn,
        )
        if answer == "":
            return 0
        if answer.isdigit() and int(answer) < len(names):
            return int(answer)
        print(f"Ungültige Eingabe {answer!r}. Bitte eine Zahl von 0 bis {len(names) - 1}.",
              file=out)
    return None


# -- the check -------------------------------------------------------------------------------


class WriteAborted(Exception):
    """A write in the mute sequence timed out or failed; stop writing."""


def run_reads(bridge: AbletonBridge, report: Report, out: TextIO) -> list[str] | None:
    """Read-only part. Returns track names, or None if they could not be read."""

    def record(name: str, fn: Callable[[], object], label: str) -> object | None:
        c = report.check(name)
        try:
            value = fn()
        except (BridgeProtocolError, AbletonOSCError) as exc:
            c.result, c.raw, c.note = FAIL, repr(bridge.last_reply), str(exc)
            print(f"{label}: FEHLER - unerwartete Antwort: {exc}", file=out)
            return None
        c.result, c.raw = PASS, repr(bridge.last_reply)
        return value

    version = record("app.version", bridge.get_version, "Live-Version")
    if version is not None:
        report.live_version = f"{version[0]}.{version[1]}"
        print(f"Live-Version (laut API, nur Haupt.Neben): {report.live_version}", file=out)
    tempo = record("song.tempo.get", bridge.get_tempo, "Tempo")
    if tempo is not None:
        print(f"Tempo: {tempo:g} BPM", file=out)
    sig = record("song.signature.get", bridge.get_signature, "Taktart")
    if sig is not None:
        print(f"Taktart: {sig[0]}/{sig[1]}", file=out)
    names = record("song.track_names.get", bridge.get_track_names, "Spurnamen")
    if names is not None:
        print(f"Spuren ({len(names)}):", file=out)
        for i, name in enumerate(names):
            print(f"  {i}: {name}", file=out)
    return names  # type: ignore[return-value]


def run_writes(bridge: AbletonBridge, report: Report, idx: int, m0: bool, out: TextIO) -> None:
    mute_check, undo_check = report.check("track.mute.set"), report.check("song.undo")
    reads: list[str] = []
    undo_sent = [False]

    def write(label: str, value: bool) -> None:
        report.write_log.append(f"{label} set mute={int(value)}")
        try:
            bridge.set_track_mute(idx, value)
        except BridgeTimeoutError as exc:
            report.write_log[-1] += " -> TIMEOUT (outcome unknown)"
            raise WriteAborted(f"{label} timed out") from exc
        except (AbletonOSCError, BridgeUnavailableError) as exc:
            report.write_log[-1] += f" -> ERROR {exc}"
            raise WriteAborted(f"{label}: {exc}") from exc
        report.write_log[-1] += " -> confirmed"

    def read(label: str, expected: bool) -> bool:
        try:
            value = bridge.get_track_mute(idx)
        except BridgeError as exc:
            report.write_log.append(f"{label} read failed: {type(exc).__name__}")
            raise WriteAborted(f"{label} read failed: {exc}") from exc
        reads.append(f"{label}={bridge.last_reply!r}")
        ok = value == expected
        report.write_log.append(
            f"{label} read mute={int(value)} expected={int(expected)} "
            f"{'ok' if ok else 'MISMATCH'} raw={bridge.last_reply!r}"
        )
        print(f"  {label}: Spur {idx} ist {'stumm' if value else 'nicht stumm'}"
              f" (erwartet: {'stumm' if expected else 'nicht stumm'}) "
              f"{'OK' if ok else 'ABWEICHUNG'}", file=out)
        return ok

    try:
        # A read-back mismatch stops the sequence before undo: if the writes did not land,
        # an undo would revert something else in the set.
        for w_label, r_label, value in (("W1", "R1", not m0), ("W2", "R2", m0),
                                        ("W3", "R3", not m0)):
            write(w_label, value)
            if not read(r_label, value):
                raise WriteAborted(f"{r_label} read-back mismatch")
        mute_check.result, mute_check.raw = PASS, "; ".join(reads)

        undo_sent[0] = True
        report.write_log.append("U  /live/song/undo")
        try:
            bridge.undo()
        except BridgeTimeoutError as exc:
            report.write_log[-1] += " -> TIMEOUT (outcome unknown)"
            raise WriteAborted("undo timed out") from exc
        except (AbletonOSCError, BridgeUnavailableError) as exc:
            report.write_log[-1] += f" -> ERROR {exc}"
            undo_check.result, undo_check.note = FAIL, f"undo error: {exc}"
            raise WriteAborted(f"undo: {exc}") from exc
        report.write_log[-1] += " -> confirmed"
        undo_reads_start = len(reads)
        ok4 = read("R4", m0)
        undo_check.raw = "; ".join(reads[undo_reads_start:])
        if ok4:
            undo_check.result = PASS
            print("Undo hat die letzte Mute-Änderung zurückgenommen. Das Set ist wie vorher.",
                  file=out)
        else:
            undo_check.result = FAIL
            undo_check.note = "undo did not revert W3; it may have reverted something else"
            print("ACHTUNG: Undo hat die Mute-Änderung NICHT zurückgenommen. Möglicherweise wurde "
                  "etwas anderes im Set rückgängig gemacht - bitte das Test-Set prüfen.\n"
                  "Das Script setzt die Spur jetzt einmal direkt auf den Ausgangszustand zurück "
                  "(kein zweites Undo).", file=out)
            write("W4", m0)
            read("R5", m0)
    except WriteAborted as exc:
        report.error = f"write sequence aborted: {exc}"
        if mute_check.result == SKIPPED:
            mute_check.result, mute_check.raw = FAIL, "; ".join(reads) or "-"
            mute_check.note = str(exc)
        if undo_sent[0] and undo_check.result == SKIPPED:
            undo_check.result, undo_check.note = FAIL, str(exc)
        elif undo_check.result == SKIPPED:
            undo_check.note = "not sent: write sequence aborted before undo"
        if "mismatch" in str(exc):
            print("FEHLER: Der zurückgelesene Mute-Zustand passt nicht zur gesendeten Änderung.",
                  file=out)
        else:
            print("FEHLER: Ein Schritt wurde nicht bestätigt. Das Ergebnis der letzten Änderung "
                  "ist UNBEKANNT - Live führt sie eventuell noch aus (z. B. nach einem "
                  "geschlossenen Dialog).", file=out)
        print("Das Script sendet KEINE weiteren Änderungen und KEIN Undo.", file=out)
        try:
            value = bridge.get_track_mute(idx)
            report.write_log.append(f"after-abort read mute={int(value)} expected={int(m0)} "
                                    f"raw={bridge.last_reply!r}")
            state = "stumm" if value else "nicht stumm"
            print(f"Spur {idx} ist jetzt {state}; ursprünglich war sie "
                  f"{'stumm' if m0 else 'nicht stumm'}. Bitte in Live nachsehen und ggf. "
                  "von Hand korrigieren.", file=out)
        except BridgeError:
            report.write_log.append("after-abort read failed")
            print(f"Der Zustand von Spur {idx} konnte nicht gelesen werden. Bitte in Live "
                  f"nachsehen: ursprünglich war sie {'stumm' if m0 else 'nicht stumm'}.",
                  file=out)


def run_check(bridge: AbletonBridge, report: Report, input_fn: Callable[[str], str],
              out: TextIO) -> None:
    host, send_port, _ = bridge.endpoint
    marker = report.check("bridge.marker_echo")
    try:
        bridge.ping()
    except BridgeUnavailableError as exc:
        marker.result, marker.note = FAIL, type(exc).__name__
        raise
    marker.result, marker.raw = PASS, "start+end nonce echoed"
    print(f"Verbindung zu AbletonOSC ({host}:{send_port}) steht.\n", file=out)

    print("--- Teil 1: nur lesen (ändert nichts) ---", file=out)
    names = run_reads(bridge, report, out)
    print("", file=out)

    print("--- Teil 2: kleine, rückgängig gemachte Änderung (optional) ---", file=out)
    if not names:
        why = "keine Spuren im Set" if names == [] else "Spurnamen nicht lesbar"
        print(f"Übersprungen: {why}.", file=out)
        for name in WRITE_CAPABILITIES:
            report.check(name).note = why
        return
    if not ask_yes("Ist das geöffnete Set ein eigenes TEST-Set (kein echtes Projekt)? [y/N]: ",
                   input_fn):
        print("Keine Änderung. Teil 2 übersprungen (nur mit einem Test-Set erlaubt).", file=out)
        for name in WRITE_CAPABILITIES:
            report.check(name).note = "user: not a test set"
        return
    idx = choose_track(names, input_fn, out)
    if idx is None:
        print("Keine gültige Spur gewählt. Teil 2 übersprungen.", file=out)
        for name in WRITE_CAPABILITIES:
            report.check(name).note = "no valid track index"
        return
    report.track_index, report.track_name = idx, names[idx]
    try:
        m0 = bridge.get_track_mute(idx)
    except (BridgeProtocolError, AbletonOSCError) as exc:
        c = report.check("track.mute.set")
        c.result, c.raw, c.note = FAIL, repr(bridge.last_reply), f"R0 read: {exc}"
        print(f"FEHLER: Mute-Zustand von Spur {idx} nicht lesbar: {exc}\n"
              "Keine Änderung gesendet.", file=out)
        return
    report.write_log.append(f"R0 read mute={int(m0)} raw={bridge.last_reply!r}")
    now, other = ("stumm", "nicht stumm") if m0 else ("nicht stumm", "stumm")
    print(
        f"\nGeplante Änderungen an Spur {idx} '{names[idx]}' (aktuell: {now}):\n"
        f"  1. Spur auf {other} setzen, zurücklesen\n"
        f"  2. Spur auf {now} setzen, zurücklesen\n"
        f"  3. Spur auf {other} setzen, zurücklesen\n"
        f"  4. Undo in Live (/live/song/undo), zurücklesen - erwartet: {now}\n"
        "Danach ist das Set wie vorher. Nimmt Undo die Änderung nicht zurück, setzt das Script\n"
        f"die Spur einmal direkt auf {now} zurück und meldet Undo als FAIL.\n"
        "Es wird nichts gelöscht und nichts anderes verändert.",
        file=out,
    )
    if not ask_yes("Diese Änderungen jetzt ausführen? [y/N]: ", input_fn):
        print("Keine Änderung. Teil 2 übersprungen.", file=out)
        for name in WRITE_CAPABILITIES:
            report.check(name).note = "user answered no"
        return
    run_writes(bridge, report, idx, m0, out)


def env_port(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AbeltonGod: Bridge-Check gegen Ableton Live (#5).")
    p.add_argument("--send-port", type=int, default=None,
                   help="AbletonOSC-Port (Standard: ABLETON_OSC_SEND_PORT oder 11000)")
    p.add_argument("--receive-port", type=int, default=None,
                   help="Antwort-Port (Standard: ABLETON_OSC_RECEIVE_PORT oder 11001)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S,
                   help=f"Sekunden pro Anfrage (Standard {DEFAULT_TIMEOUT_S:g})")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, input_fn: Callable[[str], str] = input,
         out: TextIO | None = None) -> int:
    out = out if out is not None else sys.stdout
    if hasattr(out, "reconfigure"):
        try:
            out.reconfigure(errors="backslashreplace")  # emoji track names on cp1252 pipes
        except (AttributeError, ValueError):
            pass
    args = parse_args(argv)
    # The gate logs a warning per override call; the result block lists the overrides once.
    logging.getLogger("abeltongod").addHandler(logging.NullHandler())
    report = Report(started_at=now_iso())
    print(f"AbeltonGod bridge_check {SCRIPT_VERSION}\n", file=out)
    exit_code = EXIT_OK
    bridge: AbletonBridge | None = None
    try:
        send_port = (args.send_port if args.send_port is not None
                     else env_port("ABLETON_OSC_SEND_PORT", DEFAULT_SEND_PORT))
        receive_port = (args.receive_port if args.receive_port is not None
                        else env_port("ABLETON_OSC_RECEIVE_PORT", DEFAULT_RECEIVE_PORT))
        try:
            bridge = AbletonBridge.connect(
                DEFAULT_HOST, send_port, receive_port, timeout_s=args.timeout,
                registry=CapabilityRegistry.from_file(), allow_untested=ALLOWED,
            )
        except ReceivePortInUseError as exc:
            print(msg_port_in_use(DEFAULT_HOST, receive_port), file=out)
            report.error = f"ReceivePortInUseError: {exc}"
            exit_code = EXIT_PORT_IN_USE
        if bridge is not None:
            try:
                run_check(bridge, report, input_fn, out)
            except BridgeUnavailableError as exc:  # timeout or Windows ICMP reset
                print(msg_no_answer(DEFAULT_HOST, send_port), file=out)
                report.error = f"{type(exc).__name__}: {exc}"
                exit_code = EXIT_NO_CONNECTION
            except BridgeError as exc:
                print(f"FEHLER: unerwartete Antwort von AbletonOSC: {exc}", file=out)
                report.error = f"{type(exc).__name__}: {exc}"
                exit_code = EXIT_CHECK_FAILED
            report.overrides_used = list(bridge.gate.overrides_used)
    except (CapabilityError, ValueError) as exc:
        print(f"FEHLER in der Konfiguration: {exc}", file=out)
        report.error = f"{type(exc).__name__}: {exc}"
        exit_code = EXIT_SETUP_ERROR
    finally:
        if bridge is not None:
            bridge.close()
    if exit_code == EXIT_OK and (report.any_failed() or report.error):
        exit_code = EXIT_CHECK_FAILED
    report.finished_at = now_iso()
    print("\nBitte den folgenden Block komplett in Issue #5 einfügen:\n", file=out)
    print(render_result_block(report), file=out)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
