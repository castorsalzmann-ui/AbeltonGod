"""Live import service (no Qt): the import path of ``scripts/live_import.py`` as three calls.

``inspect_live`` (reads only) -> ``prepare_import`` (reads, builds the plan) -> ``execute_import``
(writes). Everything goes through ``bridge.clip_import.ClipImporter`` and the capability gate,
as in the script: action-log entry before and after every write, read-back of slots and file
path, no undo after an unknown outcome. This module adds no Ableton function.

Gate: every capability the import uses is listed in :data:`REQUIRED_CAPS`. If one of them is not
``tested`` in ``contracts/capabilities.json``, the page shows it as "nicht verifiziert" and the
calls refuse unless ``accept_unverified`` is set (then exactly those ids are passed as
``allow_untested``, like the check scripts do; ``unsupported`` is never allowed).

What is NOT done here (the script does it, the GUI does not): the undo question, the listening
question. Removing an import is done in Live by hand; the result text says how.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from bridge.capabilities import CapabilityError, CapabilityRegistry
from bridge.check_cli import MSG_PORT_IN_USE, env_port, msg_no_answer
from bridge.clip_import import (
    DEFAULT_ACTION_LOG,
    ActionLog,
    ActionLogError,
    ClipImporter,
    ImportAborted,
    ImportOutcome,
    ImportPathError,
    SlotState,
    first_empty_slot,
    live_number,
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
from bridge.sample_info import SampleInfo, read_sample_info

REQUIRED_CAPS = (
    "app.version", "song.track_names.get", "song.num_scenes.get", "track.has_audio_input.get",
    "clip_slot.has_clip.get", "clip.file_path.get", "song.create_audio_track",
    "clip_slot.create_audio_clip",
)
NEW_TRACK = None  # track index meaning "new audio track at the end"

MSG_EXTENSION_MISSING = (
    "Die AbeltonGod-Erweiterung fehlt in AbletonOSC (AbletonOSC kennt den Import-Befehl nicht). "
    "Es wurde nichts in Live geändert. Live beenden, "
    "python scripts/install_abletonosc_extension.py ausführen, "
    "Live neu starten. Anleitung: docs/setup/ABLETONOSC_WINDOWS.md, Abschnitt 7. "
    "Ohne Erweiterung geht der Import von Hand: docs/setup/SAMPLE_IMPORT_FALLBACK.md"
)
REMOVAL_HINT = (
    "Zum Entfernen in Live von Hand: den Clip in seiner Zelle anklicken und Entf drücken "
    "(bei einer neuen Spur auch deren Kopf anklicken und Entf). Strg+Z nur, wenn du in der "
    "Widerrufen-Historie siehst, was es zurücknimmt."
)


@dataclass(frozen=True)
class LiveConfig:
    host: str = DEFAULT_HOST
    send_port: int = DEFAULT_SEND_PORT
    receive_port: int = DEFAULT_RECEIVE_PORT
    timeout_s: float = DEFAULT_TIMEOUT_S
    log_path: Path = DEFAULT_ACTION_LOG

    @classmethod
    def from_env(cls) -> LiveConfig:
        return cls(
            send_port=env_port("ABLETON_OSC_SEND_PORT", DEFAULT_SEND_PORT),
            receive_port=env_port("ABLETON_OSC_RECEIVE_PORT", DEFAULT_RECEIVE_PORT))


@dataclass(frozen=True)
class CapRow:
    id: str
    status: str

    @property
    def verified(self) -> bool:
        return self.status == "tested"


def capability_rows(registry: CapabilityRegistry | None = None) -> list[CapRow]:
    registry = registry or CapabilityRegistry.from_file()
    return [CapRow(c, registry.get(c).status) for c in REQUIRED_CAPS]


def unverified_caps(registry: CapabilityRegistry | None = None) -> list[CapRow]:
    return [r for r in capability_rows(registry) if not r.verified]


def gate_text(rows: list[CapRow]) -> str:
    bad = [r for r in rows if not r.verified]
    if not bad:
        return ("Alle benötigten Live-Funktionen haben in contracts/capabilities.json den Status "
                "'tested'. Das ist der Stand der Registry, keine Aussage über diesen Lauf.")
    return ("NICHT VERIFIZIERT laut contracts/capabilities.json: "
            + ", ".join(f"{r.id} ({r.status})" for r in bad)
            + ". Diese Funktionen sind auf deinem Rechner nicht als 'tested' belegt.")


@dataclass(frozen=True)
class TrackInfo:
    index: int  # 0-based, as the tools count
    name: str
    is_audio: bool

    @property
    def label(self) -> str:
        return f"{live_number(self.index)}: {self.name}" + ("" if self.is_audio else
                                                           "  (keine Audiospur)")


@dataclass(frozen=True)
class LiveInspection:
    ok: bool
    error: str = ""
    live_version: str = ""
    tracks: tuple[TrackInfo, ...] = ()
    num_scenes: int = 0
    sample: SampleInfo | None = None
    path: str = ""
    unverified: tuple[CapRow, ...] = ()


@dataclass
class ImportPlan:
    ok: bool
    error: str = ""
    text: str = ""
    path: str = ""
    track: int | None = None  # None = new audio track
    slot: int = 0
    num_scenes: int = 0
    expected: SlotState | None = None
    names: tuple[str, ...] = ()
    unverified: tuple[CapRow, ...] = ()


@dataclass
class ImportResult:
    ok: bool
    message: str
    steps: list[str] = field(default_factory=list)
    file_path_read: str = ""
    log_lines: list[str] = field(default_factory=list)
    outcome_unknown: bool = False
    writes_sent: bool = False


@contextmanager
def _bridge(config: LiveConfig, registry: CapabilityRegistry, allow: list[str]
            ) -> Iterator[AbletonBridge]:
    bridge = AbletonBridge.connect(
        config.host, config.send_port, config.receive_port, timeout_s=config.timeout_s,
        registry=registry, allow_untested=allow)
    try:
        yield bridge
    finally:
        bridge.close()


def _allow(registry: CapabilityRegistry, accept: bool) -> tuple[list[CapRow], list[str]]:
    bad = unverified_caps(registry)
    return bad, [r.id for r in bad] if accept else []


def _refuse_unverified(bad: list[CapRow], accept: bool) -> str | None:
    if bad and not accept:
        return ("Nicht ausgeführt: " + gate_text(bad) + " Erst bestätigen, dass du das weißt "
                "('nicht verifiziert'-Haken), sonst bleibt der Import gesperrt.")
    return None


def _connection_error(exc: Exception, config: LiveConfig) -> str:
    if isinstance(exc, ReceivePortInUseError):
        return MSG_PORT_IN_USE.format(port=config.receive_port, host=config.host)
    if isinstance(exc, BridgeUnavailableError):
        return msg_no_answer(config.host, config.send_port)
    return f"Unerwartete Antwort von AbletonOSC: {exc}"


def inspect_live(config: LiveConfig, wav: str | os.PathLike[str],
                 registry: CapabilityRegistry | None = None,
                 accept_unverified: bool = False) -> LiveInspection:
    """Check the file, then read version, tracks and scenes. Sends no write."""
    try:
        registry = registry or CapabilityRegistry.from_file()
        path = validate_wav_path(wav)
        sample = read_sample_info(path)
    except ImportPathError as exc:
        return LiveInspection(False, f"Mit der Datei stimmt etwas nicht: {exc}")
    except CapabilityError as exc:
        return LiveInspection(False, f"Fehler in der Konfiguration: {exc}")
    bad, allow = _allow(registry, accept_unverified)
    refusal = _refuse_unverified(bad, accept_unverified)
    if refusal:
        return LiveInspection(False, refusal, path=path, sample=sample, unverified=tuple(bad))
    try:
        with _bridge(config, registry, allow) as bridge:
            bridge.ping()
            major, minor = bridge.get_version()
            names = bridge.get_track_names()
            scenes = bridge.get_num_scenes()
            audio = [bridge.get_track_has_audio_input(i) for i in range(len(names))]
            if not bridge.probe_audio_clip_extension():
                return LiveInspection(False, MSG_EXTENSION_MISSING, path=path, sample=sample)
    except CapabilityError as exc:
        return LiveInspection(False, f"Fehler in der Konfiguration: {exc}", path=path)
    except BridgeError as exc:
        return LiveInspection(False, _connection_error(exc, config), path=path, sample=sample)
    if scenes < 1:
        return LiveInspection(False, "Das Set hat keine Szene, also keine Zelle für einen Clip.",
                              path=path, sample=sample)
    tracks = tuple(TrackInfo(i, n, a) for i, (n, a) in enumerate(zip(names, audio, strict=True)))
    return LiveInspection(True, "", f"{major}.{minor}", tracks, scenes, sample, path,
                          tuple(bad))


def prepare_import(config: LiveConfig, wav: str | os.PathLike[str], track: int | None,
                   slot: int | None, registry: CapabilityRegistry | None = None,
                   accept_unverified: bool = False) -> ImportPlan:
    """The plan the user confirms: target, slot (first free one if ``slot`` is None) and the
    state of the set it was made from. Sends no write."""
    try:
        registry = registry or CapabilityRegistry.from_file()
        path = validate_wav_path(wav)
        sample = read_sample_info(path)
    except ImportPathError as exc:
        return ImportPlan(False, f"Mit der Datei stimmt etwas nicht: {exc}")
    except CapabilityError as exc:
        return ImportPlan(False, f"Fehler in der Konfiguration: {exc}")
    bad, allow = _allow(registry, accept_unverified)
    refusal = _refuse_unverified(bad, accept_unverified)
    if refusal:
        return ImportPlan(False, refusal, unverified=tuple(bad))
    try:
        with _bridge(config, registry, allow) as bridge:
            bridge.ping()
            names = bridge.get_track_names()
            scenes = bridge.get_num_scenes()
            if scenes < 1:
                return ImportPlan(False, "Das Set hat keine Szene. Nichts geändert.")
            if track is None:
                expected = SlotState(tuple(names), ())
                use = 0 if slot is None else slot
            else:
                if not 0 <= track < len(names):
                    return ImportPlan(False, f"Spur {live_number(track)} gibt es nicht.")
                if not bridge.get_track_has_audio_input(track):
                    return ImportPlan(False, f"Spur {live_number(track)} '{names[track]}' ist "
                                      "keine Audiospur. Ein Audio-Clip geht nur auf eine "
                                      "Audiospur.")
                expected = read_state(bridge, track, scenes)
                use = first_empty_slot(expected) if slot is None else slot
                if use is None:
                    return ImportPlan(False, f"Spur {live_number(track)} hat keine freie "
                                      "Zelle. Es werden keine Szenen angelegt.")
            if not 0 <= use < scenes:
                return ImportPlan(False, f"Zelle {live_number(use)} gibt es nicht "
                                  f"(Szenen 1-{scenes}).")
            if track is not None and expected.has_clip[use]:
                return ImportPlan(False, f"Zelle {live_number(use)} von Spur "
                                  f"{live_number(track)} ist schon belegt. Es wird kein Clip "
                                  "überschrieben.")
    except CapabilityError as exc:
        return ImportPlan(False, f"Fehler in der Konfiguration: {exc}")
    except BridgeError as exc:
        return ImportPlan(False, _connection_error(exc, config))
    return ImportPlan(True, "", plan_text(path, tuple(names), track, use, sample), path, track,
                      use, scenes, expected, tuple(names), tuple(bad))


def plan_text(path: str, names: tuple[str, ...], track: int | None, slot: int,
              sample: SampleInfo | None) -> str:
    where = (f"die neue Spur {live_number(len(names))}" if track is None
             else f"Spur {live_number(track)} '{names[track]}'")
    lines = ["Geplante Änderungen im Live-Set:"]
    n = 1
    if track is None:
        lines.append(f"  {n}. Neue Audiospur am Ende anlegen (wird Spur "
                     f"{live_number(len(names))}).")
        n += 1
    lines += [
        f"  {n}. Audio-Clip in {where}, Szene {live_number(slot)}, aus der Datei:",
        *([f"       Sample: {sample.label}"] if sample is not None else []),
        f"       {path}",
        "Live verweist auf die Datei; sie wird nicht kopiert oder verändert.",
        "Danach liest das Programm die Zellen der Spur und den Dateipfad des Clips zurück. "
        "Jede Änderung wird vorher und nachher in das Aktions-Log geschrieben.",
        "Ein Undo sendet dieses Fenster nicht; zum Entfernen siehe unten.",
    ]
    return "\n".join(lines)


def _log_lines_since(path: Path, offset: int) -> list[str]:
    try:
        with open(path, "rb") as fh:
            fh.seek(offset)
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        parts = [str(e.get("action", "?")), str(e.get("status", "?"))]
        if e.get("capability"):
            parts.append(str(e["capability"]))
        if "ok" in e:
            parts.append("ok" if e["ok"] else "NICHT ok")
        out.append(" · ".join(parts))
    return out


def execute_import(config: LiveConfig, plan: ImportPlan, test_set_confirmed: bool,
                   registry: CapabilityRegistry | None = None,
                   accept_unverified: bool = False) -> ImportResult:
    """Write the import. Refuses without a plan, without the test-set confirmation and, for a
    capability that is not ``tested``, without ``accept_unverified``."""
    if not plan.ok or plan.expected is None:
        return ImportResult(False, "Kein gültiger Plan. Nichts gesendet.")
    if not test_set_confirmed:
        return ImportResult(False, "Nicht ausgeführt: bestätigen, dass das geöffnete Set ein "
                            "Test-Set ist (kein echtes Projekt).")
    try:
        registry = registry or CapabilityRegistry.from_file()
        bad, allow = _allow(registry, accept_unverified)
    except CapabilityError as exc:
        return ImportResult(False, f"Fehler in der Konfiguration: {exc}")
    refusal = _refuse_unverified(bad, accept_unverified)
    if refusal:
        return ImportResult(False, refusal)
    log = ActionLog(config.log_path)
    try:
        before_size = Path(log.path).stat().st_size
    except OSError:
        before_size = 0
    importer: ClipImporter | None = None
    try:
        with _bridge(config, registry, allow) as bridge:
            importer = ClipImporter(bridge, log, timeout_s=config.timeout_s)
            try:
                outcome = importer.run(path=plan.path, track_index=plan.track,
                                       slot_index=plan.slot, num_slots=plan.num_scenes,
                                       expected_before=plan.expected)
            except (ImportAborted, ActionLogError) as exc:
                return _failed(importer.last_outcome, exc, log.path, before_size)
    except CapabilityError as exc:
        return ImportResult(False, f"Fehler in der Konfiguration: {exc}")
    except BridgeError as exc:
        sent = importer is not None and importer.last_outcome is not None
        tail = (" Bitte in Live nachsehen, was schon ausgeführt wurde." if sent
                else " Es wurde nichts in Live geändert.")
        return ImportResult(False, _connection_error(exc, config) + tail,
                            log_lines=_log_lines_since(Path(log.path), before_size),
                            outcome_unknown=sent, writes_sent=sent)
    return _done(outcome, log.path, before_size)


def _steps(outcome: ImportOutcome | None) -> list[str]:
    return [f"{s.label}: {s.outcome}" + (f" ({s.detail})" if s.detail else "")
            for s in (outcome.steps if outcome else [])]


def _done(outcome: ImportOutcome, log_path, offset: int) -> ImportResult:
    msg = (f"Fertig: Clip liegt in Spur {live_number(outcome.track_index)}, Szene "
           f"{live_number(outcome.slot_index)}. Live meldet als Datei: {outcome.file_path_read}")
    if outcome.target_name_after != outcome.target_name_before:
        msg += (f" Live hat die Spur umbenannt: '{outcome.target_name_before}' -> "
                f"'{outcome.target_name_after}'.")
    msg += " Das Zurücklesen stimmt; angehört wurde nichts. " + REMOVAL_HINT
    return ImportResult(True, msg, _steps(outcome), str(outcome.file_path_read),
                        _log_lines_since(Path(log_path), offset), False, True)


def _failed(outcome: ImportOutcome | None, exc: Exception, log_path, offset: int
            ) -> ImportResult:
    lines = _log_lines_since(Path(log_path), offset)
    steps = _steps(outcome)
    if outcome is None:
        return ImportResult(False, f"Fehler vor dem Senden: {exc} Es wurde nichts in Live "
                            "geändert.", steps, log_lines=lines)
    confirmed = [s.label for s in outcome.steps if s.outcome == "confirmed"]
    if outcome.outcome_unknown:
        msg = ("Fehler: Das Ergebnis eines Schritts ist UNBEKANNT (nicht bestätigt oder das "
               "Zurücklesen zeigt nicht das Erwartete). Es wird nichts mehr gesendet und kein "
               f"Undo. Bitte in Live nachsehen. Zurückgelesen: {exc}")
    else:
        msg = f"Fehler: {exc} Es wird nichts mehr gesendet."
    if confirmed:
        msg += " Schon ausgeführt: " + ", ".join(confirmed) + ". " + REMOVAL_HINT
    return ImportResult(False, msg, steps, log_lines=lines,
                        outcome_unknown=outcome.outcome_unknown, writes_sent=bool(confirmed))
