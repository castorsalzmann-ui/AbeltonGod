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

       R0 read mute            -> M0 (original state; shown in the plan)
       S0 snapshot             -> tempo, signature, all track names, every track's mute
                                  (after confirmation)
       W1 set mute = not M0    -> R1 expect not M0
       W2 set mute = M0        -> R2 expect M0
       W3 set mute = not M0    -> R3 expect not M0
       U  /live/song/undo      -> R4 expect M0, then S1 snapshot; S1 must equal S0

   Both directions of the mute write are exercised and undo is exercised for real.
   ``/live/song/undo`` reverts Live's *last undo step*. Whether Live records a LOM mute change
   as one is unverified (#39); if not, undo reverts the user's last action instead. So the
   plan warns about this before the final confirmation and asks for a freshly reopened test
   set (per the Live 12 manual, "Undo History", opening a set clears the undo history; not
   yet verified in Live by this project).
   Outcomes after the undo:
   - S1 == S0: undo PASS, with a scope note in the result block (clips, devices, automation
     and return/master tracks are not visible to the script).
   - Only the test track's mute differs (undo did not revert W3): undo FAIL; one direct
     restore W4 + read-back R5; a failed restore is reported with a hand-fix instruction.
   - Only tempo and/or signature differ (all names and mutes as before): undo FAIL with a
     neutral message - tempo drift (automation, Ableton Link, external clock) and an undone
     tempo/signature edit look the same from here. Exact comparison, no tolerance (#43).
   - Anything else differs (track count, names, order, another track's mute, possibly
     together with tempo/signature): undo FAIL with the differences listed; nothing more is
     written.
   EOF at any prompt means "no" / abort (exit 0), never a default choice. Ctrl+C at any
   prompt aborts with exit 130 and the result block, like Ctrl+C anywhere else (#43).
   A second undo is never sent. A read-back mismatch at R1-R3 stops before undo. Any bridge
   error or Ctrl+C in the sequence stops writing; the script reads the test track once, tells
   the user its original state and prints the result block (exit 130 on Ctrl+C).
4. Prints a fenced result block to paste into issue #5.

Capability gate: the capabilities this script touches are ``tested`` since #42 (evidence: the
user's 0.1.0 run in #5). The script still passes them to the gate's explicit check-script
override (``allow_untested``), so it keeps working if one is set back to ``supported`` for a
re-test; ``capability_overrides_used`` in the result block shows which were needed. It never
changes the registry. Statuses change only in a separate contract-change PR, with the pasted
output as evidence.

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

# 0.2.0: whole-set check around undo, Ctrl+C handling (#39)
# 0.3.0: tempo/signature in the snapshot, undo scope note, EOF at track prompt aborts (#44)
# 0.3.1: mute read-back gated as its own capability track.mute.get (#42); output unchanged
# 0.4.0: neutral FAIL for tempo/signature-only changes, Ctrl+C at a prompt exits 130 (#43)
SCRIPT_VERSION = "0.4.0"

# The only capabilities this script may call, through the explicit override.
READ_CAPABILITIES = ("app.version", "song.tempo.get", "song.signature.get",
                     "song.track_names.get")
WRITE_CAPABILITIES = ("track.mute.set", "song.undo")
# Read-back used inside the write sequence and the undo snapshots; it has no result line of
# its own (its reads are the R0-R5 lines of write_sequence).
READBACK_CAPABILITIES = ("track.mute.get",)
ALLOWED = READ_CAPABILITIES + WRITE_CAPABILITIES + READBACK_CAPABILITIES

PASS, FAIL, SKIPPED = "PASS", "FAIL", "SKIPPED"

EXIT_OK = 0
EXIT_CHECK_FAILED = 1
EXIT_NO_CONNECTION = 2
EXIT_PORT_IN_USE = 3
EXIT_SETUP_ERROR = 4
EXIT_INTERRUPTED = 130  # Ctrl+C, the shell convention

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
    interrupted: bool = False

    def check(self, name: str) -> CheckResult:
        if name not in self.checks:
            self.checks[name] = CheckResult(name)
        return self.checks[name]

    def any_failed(self) -> bool:
        return any(c.result == FAIL for c in self.checks.values())


CHECK_ORDER = ("bridge.marker_echo",) + READ_CAPABILITIES + WRITE_CAPABILITIES


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


def ask(prompt: str, input_fn: Callable[[str], str]) -> str | None:
    """The stripped answer, or None on EOF (the user wants out, not a default).

    Ctrl+C is not caught here: it propagates to ``main``, which aborts with exit 130 and the
    result block, the same as Ctrl+C at any other point before a write (#43).
    """
    try:
        return input_fn(prompt).strip()
    except EOFError:
        return None


def ask_yes(prompt: str, input_fn: Callable[[str], str]) -> bool:
    return (ask(prompt, input_fn) or "").lower() in YES


# Why no track was chosen (result-block notes).
NOTE_TRACK_EOF = "user aborted at the track prompt (EOF)"
NOTE_TRACK_INVALID = "no valid track index after 3 attempts"


def choose_track(names: list[str], input_fn: Callable[[str], str],
                 out: TextIO) -> tuple[int | None, str]:
    """(track index, "") or (None, reason). Ctrl+C propagates (see ``ask``)."""
    for _ in range(3):
        answer = ask(
            f"Welche Spur soll kurz stummgeschaltet werden? Index 0-{len(names) - 1} "
            f"[Enter = 0 '{names[0]}']: ",
            input_fn,
        )
        if answer is None:  # EOF: abort, never fall back to the default track
            return None, NOTE_TRACK_EOF
        if answer == "":
            return 0, ""
        # ASCII digits only: str.isdigit() also accepts '²' or Arabic-Indic digits.
        if answer.isascii() and answer.isdecimal() and int(answer) < len(names):
            return int(answer), ""
        print(f"Ungültige Eingabe {answer!r}. Bitte eine Zahl von 0 bis {len(names) - 1}.",
              file=out)
    return None, NOTE_TRACK_INVALID


# -- the check -------------------------------------------------------------------------------


class WriteAborted(Exception):
    """A step of the mute sequence failed or was not confirmed; stop writing."""


@dataclass(frozen=True)
class Snapshot:
    """What the script can check of the set: tempo, time signature, track names (count and
    order) and every track's mute. Blind spots: return/master tracks, clips, devices,
    automation, and a move between tracks with identical names and mutes."""

    tempo: float
    signature: tuple[int, int]
    names: tuple[str, ...]
    mutes: tuple[bool, ...]

    def render(self) -> str:
        tracks = ", ".join(f"{n!r}:{int(m)}" for n, m in zip(self.names, self.mutes,
                                                               strict=True))
        return (f"tempo={bpm(self.tempo)} sig={self.signature[0]}/{self.signature[1]} "
                f"tracks=[{tracks}]")


# Scope note for the song.undo line of the result block: what an undo PASS is based on.
UNDO_SCOPE_NOTE = ("checked: tempo, signature, track count/names/order, all track mutes; "
                   "not checked: clips, devices, automation, return/master tracks")


def take_snapshot(bridge: AbletonBridge) -> Snapshot:
    tempo = bridge.get_tempo()
    signature = bridge.get_signature()
    names = tuple(bridge.get_track_names())
    return Snapshot(tempo, signature, names,
                    tuple(bridge.get_track_mute(i) for i in range(len(names))))


def bpm(tempo: float) -> str:
    """Short tempo text that never hides a difference: ``:g`` rounds to 6 digits, so a tiny
    drift (136.0001) would print as '136' on both sides; fall back to repr then (#43)."""
    short = f"{tempo:g}"
    return short if float(short) == tempo else repr(tempo)


def mute_word(value: bool) -> str:
    return "stumm" if value else "nicht stumm"


def describe_changes(before: Snapshot, after: Snapshot) -> list[str]:
    """German lines describing how ``after`` differs from ``before`` (empty if equal)."""
    song: list[str] = []
    if after.tempo != before.tempo:
        song.append(f"Tempo: vorher {bpm(before.tempo)} BPM, jetzt {bpm(after.tempo)} BPM")
    if after.signature != before.signature:
        song.append(f"Taktart: vorher {before.signature[0]}/{before.signature[1]}, jetzt "
                    f"{after.signature[0]}/{after.signature[1]}")
    if before.names != after.names:
        lines = [f"Spuren vorher ({len(before.names)}): {list(before.names)}",
                 f"Spuren jetzt  ({len(after.names)}): {list(after.names)}"]
        if len(before.names) != len(after.names):
            lines.insert(0, f"Die Spuranzahl hat sich geändert: {len(before.names)} -> "
                            f"{len(after.names)}.")
        else:
            lines.insert(0, "Spurnamen oder Reihenfolge haben sich geändert.")
        return song + lines
    return song + [
        f"Spur {i} '{name}': vorher {mute_word(b)}, jetzt {mute_word(a)}"
        for i, (name, b, a) in enumerate(zip(before.names, before.mutes, after.mutes,
                                             strict=True))
        if a != b
    ]


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


UNDO_PASS_TEXT = (
    "Undo hat die letzte Mute-Änderung zurückgenommen. Tempo, Taktart, Spuranzahl, Spurnamen "
    "und Mute-Zustand aller Spuren sind wie vorher.\n"
    "(Nicht prüfen kann das Script: Clips, Geräte, Automation sowie Return- und Master-Spuren.)"
)

UNDO_HISTORY_HINT = (
    "In Live zeigt der Undo-Verlauf (Strg+Alt+Z; im Handbuch: View -> Undo History), welcher "
    "Schritt zurückgenommen wurde; dort lässt er sich wiederherstellen."
)


TEMPO_ONLY_NOTE = ("only tempo/signature differ after undo: possible drift (automation, Link, "
                   "external clock) or an undone tempo/signature edit")

TEMPO_ONLY_TEXT = (
    "FAIL: Nach dem Undo unterscheiden sich nur Tempo und/oder Taktart vom Stand vor dem Test.\n"
    "Spurnamen und Mute-Zustände aller Spuren sind wie vorher. Unterschiede:"
)

TEMPO_ONLY_HINT = (
    "Das Script kann nicht unterscheiden, woher das kommt. Möglich sind:\n"
    "  - Das Tempo hat sich während des Tests von selbst geändert, z. B. durch\n"
    "    Tempo-Automation, Ableton Link oder eine externe MIDI-Clock (Sync).\n"
    "  - Undo hat eine frühere Tempo- oder Taktart-Änderung zurückgenommen.\n"
    "Das Script sendet keine weiteren Änderungen. Bitte Transport stoppen, Tempo-Automation\n"
    "und Link/Sync ausschalten, das Test-Set neu öffnen und den Check wiederholen.\n"
    + UNDO_HISTORY_HINT
)


def run_writes(bridge: AbletonBridge, report: Report, idx: int, m0: bool, names: list[str],
               out: TextIO) -> None:
    """The confirmed write sequence. Never raises for bridge errors or Ctrl+C.

    Every path that stops early sends no further write and no undo, reads the test track once
    and tells the user its original state. Exactly one undo is sent at most.
    """
    mute_check, undo_check = report.check("track.mute.set"), report.check("song.undo")
    reads: list[str] = []
    state = {"writes_sent": False, "undo_sent": False}

    def write(label: str, value: bool) -> None:
        report.write_log.append(f"{label} set mute={int(value)}")
        state["writes_sent"] = True
        try:
            bridge.set_track_mute(idx, value)
        except BridgeTimeoutError as exc:
            report.write_log[-1] += " -> TIMEOUT (outcome unknown)"
            raise WriteAborted(f"{label} timed out") from exc
        except BridgeError as exc:
            report.write_log[-1] += f" -> {type(exc).__name__} {exc} (outcome unknown)"
            raise WriteAborted(f"{label}: {type(exc).__name__}: {exc}") from exc
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
        print(f"  {label}: Spur {idx} ist {mute_word(value)} (erwartet: {mute_word(expected)}) "
              f"{'OK' if ok else 'ABWEICHUNG'}", file=out)
        return ok

    def snapshot(label: str) -> Snapshot:
        try:
            snap = take_snapshot(bridge)
        except BridgeError as exc:
            report.write_log.append(f"{label} set snapshot failed: {type(exc).__name__}")
            raise WriteAborted(f"{label} set snapshot failed: {exc}") from exc
        report.write_log.append(f"{label} set snapshot {snap.render()}")
        return snap

    try:
        # S0: the whole set as far as the script can see it, before any write.
        s0 = snapshot("S0")
        if s0.names != tuple(names) or s0.mutes[idx] != m0:
            raise WriteAborted("set changed between the plan and the confirmation")

        # A read-back mismatch stops the sequence before undo: if a write did not land as
        # expected, an undo would revert something else in the set.
        for w_label, r_label, value in (("W1", "R1", not m0), ("W2", "R2", m0),
                                        ("W3", "R3", not m0)):
            write(w_label, value)
            if not read(r_label, value):
                raise WriteAborted(f"{r_label} read-back mismatch")
        mute_check.result, mute_check.raw = PASS, "; ".join(reads)

        state["undo_sent"] = True
        report.write_log.append("U  /live/song/undo")
        try:
            bridge.undo()
        except BridgeError as exc:
            report.write_log[-1] += f" -> {type(exc).__name__} (outcome unknown)"
            raise WriteAborted(f"undo: {type(exc).__name__}: {exc}") from exc
        report.write_log[-1] += " -> confirmed"
        undo_reads_start = len(reads)
        read("R4", m0)
        s1 = snapshot("S1")
        changes = describe_changes(s0, s1)
        undo_check.raw = "; ".join(reads[undo_reads_start:]) + f"; S1={s1.render()}"

        if not changes:
            undo_check.result, undo_check.note = PASS, UNDO_SCOPE_NOTE
            print(UNDO_PASS_TEXT, file=out)
            return

        undo_check.result = FAIL
        only_test_mute = s0.names == s1.names and changes == [
            f"Spur {idx} '{s0.names[idx]}': vorher {mute_word(m0)}, jetzt {mute_word(not m0)}"
        ]
        if only_test_mute:
            # Undo did not revert W3 and nothing else visible changed: it reverted nothing
            # the script can see, or something it cannot see (clips, devices...).
            undo_check.note = "undo did not revert W3"
            print("ACHTUNG: Undo hat die Mute-Änderung NICHT zurückgenommen. Falls Undo etwas "
                  "anderes zurückgenommen hat (z. B. an Clips oder Geräten), sieht das Script das "
                  f"nicht. {UNDO_HISTORY_HINT}\n"
                  f"Das Script setzt Spur {idx} jetzt einmal direkt auf {mute_word(m0)} zurück "
                  "(kein zweites Undo).", file=out)
            write("W4", m0)
            if not read("R5", m0):
                raise WriteAborted("R5 read-back mismatch after the direct restore")
            return

        if s0.names == s1.names and s0.mutes == s1.mutes:
            # Only tempo and/or signature differ (exact compare, no tolerance). From here a
            # drifting tempo (automation, Link, external clock) and an undone tempo edit look
            # the same, so the message names both and blames neither (#43).
            undo_check.note = TEMPO_ONLY_NOTE
            report.error = "only tempo/signature changed across undo; nothing more written"
            print(TEMPO_ONLY_TEXT, file=out)
            for line in changes:
                print(f"  - {line}", file=out)
            print(TEMPO_ONLY_HINT, file=out)
            return

        # Undo changed the set beyond the test track's mute: it reverted something else.
        # Indices may now point at other tracks, so nothing more is written.
        undo_check.note = "undo changed the set beyond the test mute (reverted another action)"
        report.error = "undo changed the set beyond the test mute; no restore attempted"
        print("FEHLER: Nach dem Undo sieht das Set anders aus als vor dem Test. Undo hat "
              "offenbar nicht (nur) die Mute-Änderung des Scripts zurückgenommen, sondern einen "
              "anderen Schritt aus Lives Undo-Verlauf. Unterschiede:", file=out)
        for line in changes:
            print(f"  - {line}", file=out)
        print("Das Script sendet KEINE weiteren Änderungen, weil die Spurnummern nicht mehr "
              f"stimmen müssen. {UNDO_HISTORY_HINT}\n"
              f"Ursprünglich war Spur {idx} '{s0.names[idx]}' {mute_word(m0)}.", file=out)
    except (WriteAborted, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        reason = "interrupted by user (Ctrl+C)" if interrupted else str(exc)
        report.interrupted = report.interrupted or interrupted
        report.error = f"write sequence aborted: {reason}"
        restore_failed = reason.startswith(("W4", "R5"))
        if state["writes_sent"] and (mute_check.result == SKIPPED or restore_failed):
            # A write that did not land (or was not confirmed) is never a mute PASS.
            mute_check.result = FAIL
            mute_check.raw = "; ".join(reads) or "-"
            mute_check.note = reason
        if state["undo_sent"]:
            if undo_check.result == SKIPPED:
                undo_check.result, undo_check.note = FAIL, reason
        else:
            undo_check.note = "not sent: write sequence aborted before undo"
        report_abort(bridge, report, idx, m0, state, reason, interrupted, out)


def report_abort(bridge: AbletonBridge, report: Report, idx: int, m0: bool, state: dict,
                 reason: str, interrupted: bool, out: TextIO) -> None:
    if interrupted:
        print("\nABGEBROCHEN mit Strg+C.", file=out)
    elif "mismatch" in reason:
        print("FEHLER: Der zurückgelesene Mute-Zustand passt nicht zur gesendeten Änderung.",
              file=out)
    elif "set changed" in reason:
        print("FEHLER: Das Set hat sich zwischen Plan und Bestätigung geändert.", file=out)
    else:
        print("FEHLER: Ein Schritt wurde nicht bestätigt. Sein Ergebnis ist UNBEKANNT - Live "
              "führt ihn eventuell noch aus (z. B. nach einem geschlossenen Dialog).", file=out)
    print(f"Ursprünglicher Zustand: Spur {idx} '{report.track_name}' war {mute_word(m0)}.",
          file=out)
    if not state["writes_sent"]:
        print("Es wurde keine Änderung gesendet.", file=out)
        return
    print("Das Script sendet KEINE weiteren Änderungen und KEIN Undo.", file=out)
    if state["undo_sent"]:
        print("Das Undo wurde (eventuell) schon gesendet. Es kann einen anderen Schritt "
              "zurückgenommen haben. " + UNDO_HISTORY_HINT, file=out)
    try:
        value = bridge.get_track_mute(idx)
    except (BridgeError, KeyboardInterrupt):
        report.write_log.append("after-abort read failed")
        print(f"Der jetzige Zustand von Spur {idx} konnte nicht gelesen werden. Bitte in Live "
              f"nachsehen und den Mute-Knopf ggf. von Hand auf {mute_word(m0)} stellen.",
              file=out)
        return
    report.write_log.append(f"after-abort read mute={int(value)} expected={int(m0)} "
                            f"raw={bridge.last_reply!r}")
    if value == m0:
        print(f"Spur {idx} ist jetzt {mute_word(value)} - wie ursprünglich.", file=out)
    else:
        print(f"Spur {idx} ist jetzt {mute_word(value)}. Bitte in Live den Mute-Knopf von "
              f"Spur {idx} von Hand auf {mute_word(m0)} stellen.", file=out)


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
    idx, why_none = choose_track(names, input_fn, out)
    if idx is None:
        if why_none == NOTE_TRACK_EOF:
            print("Abgebrochen. Teil 2 übersprungen, es wurde nichts geändert.", file=out)
        else:
            print("Keine gültige Spur gewählt. Teil 2 übersprungen.", file=out)
        for name in WRITE_CAPABILITIES:
            report.check(name).note = why_none
        return
    report.track_index, report.track_name = idx, names[idx]
    try:
        m0 = bridge.get_track_mute(idx)
    except (BridgeProtocolError, AbletonOSCError) as exc:
        # Without a known original state nothing may be written.
        c = report.check("track.mute.set")
        c.result, c.raw, c.note = FAIL, repr(bridge.last_reply), f"R0 read: {exc}"
        report.check("song.undo").note = "not sent: R0 read failed"
        print(f"FEHLER: Mute-Zustand von Spur {idx} nicht lesbar: {exc}\n"
              "Keine Änderung gesendet.", file=out)
        return
    report.write_log.append(f"R0 read mute={int(m0)} raw={bridge.last_reply!r}")
    print(plan_text(idx, names[idx], m0), file=out)
    if not ask_yes("Diese Änderungen jetzt ausführen? [y/N]: ", input_fn):
        print("Keine Änderung. Teil 2 übersprungen.", file=out)
        for name in WRITE_CAPABILITIES:
            report.check(name).note = "user answered no"
        return
    run_writes(bridge, report, idx, m0, names, out)


def plan_text(idx: int, name: str, m0: bool) -> str:
    now, other = mute_word(m0), mute_word(not m0)
    return (
        f"\nGeplante Änderungen an Spur {idx} '{name}' (aktuell: {now}):\n"
        f"  1. Spur auf {other} setzen, zurücklesen\n"
        f"  2. Spur auf {now} setzen, zurücklesen\n"
        f"  3. Spur auf {other} setzen, zurücklesen\n"
        f"  4. Undo in Live (/live/song/undo), zurücklesen - erwartet: {now}\n"
        "Vorher und nach dem Undo liest das Script Tempo, Taktart, alle Spurnamen und den\n"
        "Mute-Zustand aller Spuren und vergleicht sie.\n"
        "\n"
        "WICHTIG - Undo-Risiko: Schritt 4 nimmt den LETZTEN Schritt in Lives Undo-Verlauf\n"
        "zurück. Ob Live eine Mute-Änderung über AbletonOSC dort einträgt, ist noch nicht\n"
        "geprüft - genau das testet dieser Check. Wenn nicht, nimmt Undo stattdessen deine\n"
        "letzte eigene Aktion zurück (z. B. eine eingefügte oder umbenannte Spur).\n"
        "Darum: Test-Set speichern, schließen und neu öffnen (über das Datei-Menü), dann\n"
        "NICHTS mehr daran ändern und erst danach hier bestätigen. Laut Live-12-Handbuch\n"
        "(\"Undo History\") leert Live beim Öffnen eines Sets den Undo-Verlauf; in diesem\n"
        "Projekt ist das noch nicht geprüft.\n"
        "\n"
        "Erkennt das Script nach dem Undo eine Änderung an Tempo, Taktart, Spuren oder\n"
        "Mute-Zuständen, meldet es Undo als FAIL, nennt die Unterschiede und sendet nichts\n"
        "mehr. Hat Undo nur die Mute-Änderung nicht zurückgenommen, setzt es Spur "
        f"{idx} einmal\n"
        f"direkt auf {now} zurück. Ein zweites Undo wird nie gesendet."
    )


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
            except KeyboardInterrupt:
                # Outside the write sequence (which handles Ctrl+C itself) nothing was written.
                print("\nABGEBROCHEN mit Strg+C. Es wurde nichts in Live geändert.", file=out)
                report.interrupted = True
                report.error = "interrupted by user (Ctrl+C) before any write"
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
    if report.interrupted:
        exit_code = EXIT_INTERRUPTED
    elif exit_code == EXIT_OK and (report.any_failed() or report.error):
        exit_code = EXIT_CHECK_FAILED
    report.finished_at = now_iso()
    print("\nBitte den folgenden Block komplett in Issue #5 einfügen:\n", file=out)
    print(render_result_block(report), file=out)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
