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

Samples outside a project (#413): the bridge (``bridge.sample_info.read_sample_info``) only
imports a WAV with a sidecar from its category folder of a Live project
(``<project>/Samples/Drums/Kicks`` …), but the GUI renders into its own output folder. For
such a file :func:`plan_placement` plans a copy of WAV + sidecar into that folder of the
project the user names (checked with ``library.check_project_dir``); :func:`execute_import`
copies right before the first Live write and imports the copy, so the bridge rule and the
capabilities stay unchanged. The copy never overwrites: an identical pair already there is
reused, a different one gets the next free ``_002`` … name (the sidecar's ``file`` field is
updated to match). If nothing reached Live, the copy is removed again. Since #443 GUI renders
already sit in a project-shaped folder and are importable in place; when a project folder is
given and the file lies outside it, it is still copied into the project (#443 decision).
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterable, Iterator
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
from bridge.sample_info import SampleCategoryError, SampleInfo, read_sample_info
from launcher.paths import is_frozen
from library import (
    DEFAULT_LAYOUT,
    LibraryLayout,
    LibraryPathError,
    check_project_dir,
    library_folder,
    longest_path,
    path_chars,
    sidecar_path,
)
from library.project import ProjectDirProblem, ProjectReason

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
    path: str = ""  # the file Live gets (the project copy if one is planned)
    unverified: tuple[CapRow, ...] = ()
    placement: Placement | None = None


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
    placement: Placement | None = None  # set on an ok plan; copy before the first write


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


# --- placement into a project (#413) -------------------------------------------------------

_MAX_COPY_NAMES = 999  # stem, stem_002 … stem_999


@dataclass(frozen=True)
class Placement:
    """Which file Live gets. ``target == source``: the WAV is importable where it is.
    Otherwise ``target`` lies in the project's category folder; ``copy`` says whether
    :func:`copy_into_project` still has to write it (False: an identical pair is there)."""

    source: str
    target: str
    sample: SampleInfo
    copy: bool = False

    @property
    def moved(self) -> bool:
        return self.target != self.source


def default_refused_roots() -> tuple[Path, ...] | None:
    """``()`` in the frozen exe, else ``None`` (``check_project_dir``'s own default: the
    verified checkout is refused, and an unverified one refuses every folder with
    ``checkout_unknown``, fail-closed). Only the exe skips the rule: it has no checkout to
    protect, and the default would refuse every folder there."""
    return () if is_frozen() else None


def project_problem_text(problem: ProjectDirProblem) -> str:
    raw, reason, detail = problem.path, problem.reason, problem.detail
    if reason is ProjectReason.EMPTY:
        return "Kein Projektordner angegeben."
    if reason is ProjectReason.NOT_ABSOLUTE:
        return f"Der Projektordner muss ein voller Pfad sein, nicht {raw!r}."
    if reason is ProjectReason.MISSING:
        return f"Den Projektordner gibt es nicht: {raw}"
    if reason is ProjectReason.CHECKOUT_UNKNOWN:
        return ("Der AbeltonGod-Ordner, aus dem das Programm läuft, ist nicht als Checkout "
                f"erkennbar ({detail}); aus Vorsicht wird kein Projektordner angenommen.")
    if reason is ProjectReason.IN_CHECKOUT:
        return f"{raw} liegt im AbeltonGod-Ordner ({detail}); das ist kein Live-Projekt."
    if reason is ProjectReason.BACKUP_FOLDER:
        return f"{raw} ist Lives Backup-Ordner. Bitte den Ordner darüber nehmen."
    if reason is ProjectReason.UNREADABLE:
        return f"{raw} lässt sich nicht lesen: {detail}"
    if reason is ProjectReason.NO_ALS_FILE:
        return (f"In {raw} liegt keine .als-Datei, also ist es nicht der Projektordner eines "
                "gespeicherten Live-Sets. Set zuerst in Live speichern, dann den Ordner mit "
                "der .als-Datei wählen.")
    return f"{raw} wurde abgelehnt ({reason}: {detail})."


def _misplaced_category(path: Path, layout: LibraryLayout) -> str | None:
    """The category of a WAV whose only fault is its folder, else None (any other sidecar
    problem keeps the bridge's own refusal)."""
    try:
        meta = json.loads(sidecar_path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    category = meta.get("category") if isinstance(meta, dict) else None
    if not isinstance(category, str):
        return None
    try:
        parts = layout.parts_for(category)
    except LibraryPathError:
        return None
    folder = tuple(p.casefold() for p in path.parent.parts[-len(parts):])
    if folder == tuple(p.casefold() for p in parts):
        return None  # already in place: the refusal had another reason
    return category


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _same_sidecar(src_side: Path, side: Path, wav: Path) -> bool:
    """``side`` is ``src_side`` as :func:`copy_into_project` writes it for ``wav``."""
    try:
        a = json.loads(src_side.read_text(encoding="utf-8"))
        b = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if wav.name != src_side.with_suffix(".wav").name:
        a = {**a, "file": wav.name}
    return a == b


def _target_in(folder: Path, source: Path, limit: int | None) -> tuple[Path, bool]:
    """``(target WAV, copy needed)``: the first name in ``folder`` that is free (copy) or
    already holds exactly this pair (reuse). Never an existing different file."""
    src_side = sidecar_path(source)
    for n in range(1, _MAX_COPY_NAMES + 1):
        stem = source.stem if n == 1 else f"{source.stem}_{n:03d}"
        wav = folder / f"{stem}.wav"
        side = sidecar_path(wav)
        if limit is not None and path_chars(longest_path(wav)) > limit:
            raise ImportPathError(
                f"Der Zielpfad {wav} wäre mit Lives Analyse-Datei (.asd) länger als {limit} "
                "Zeichen (Windows MAX_PATH). Projekt an einen kürzeren Pfad legen.")
        taken = [p for p in (wav, side) if p.exists() or p.is_symlink()]
        if not taken:
            return wav, True
        if len(taken) == 2 and _same_file(source, wav) and _same_sidecar(src_side, side, wav):
            return wav, False  # this pair was copied here before: reuse it
    raise ImportPathError(f"Kein freier Dateiname für {source.stem} in {folder}.")


def _check_project(project_dir: str | os.PathLike[str],
                   refused_roots: Iterable[str | os.PathLike[str]] | None) -> None:
    roots = default_refused_roots() if refused_roots is None else tuple(refused_roots)
    problem = check_project_dir(project_dir, refused_roots=roots)
    if problem is not None:
        raise ImportPathError(project_problem_text(problem))


def _inside(path: Path, folder: Path) -> bool:
    try:
        return path.resolve().is_relative_to(folder.resolve())
    except (OSError, RuntimeError):
        return False


def plan_placement(wav: str | os.PathLike[str], project_dir: str | os.PathLike[str] | None,
                   *, layout: LibraryLayout = DEFAULT_LAYOUT,
                   refused_roots: Iterable[str | os.PathLike[str]] | None = None) -> Placement:
    """Where Live will read ``wav`` from. Writes nothing; raises :class:`ImportPathError`
    with a German reason. ``refused_roots`` None means :func:`default_refused_roots`."""
    path = validate_wav_path(wav)
    no_project = project_dir is None or not os.fspath(project_dir).strip()
    try:
        info = read_sample_info(path, layout=layout)
    except SampleCategoryError as exc:
        category = _misplaced_category(Path(path), layout)
        if category is None:
            raise
        refusal = str(exc)
    else:
        # Importable where it is. With a project folder given, a file from outside that
        # project (e.g. the GUI output folder, laid out like a project since #443) is still
        # copied into it, so the set keeps its samples next to it.
        if no_project or info.category is None:
            return Placement(path, path, info)
        _check_project(project_dir, refused_roots)  # a project the user named must be valid
        if _inside(Path(path), Path(project_dir)):
            return Placement(path, path, info)
        category, refusal = info.category, ""
    folder_name = os.sep.join(layout.parts_for(category))
    if no_project:
        raise ImportPathError(
            f"{refusal} Live-Projektordner wählen (der Ordner mit der .als-Datei des Test-Sets): "
            f"dann kopiert das Programm WAV und Sidecar vor dem Import nach "
            f"<Projekt>{os.sep}{folder_name} und importiert die Kopie.")
    _check_project(project_dir, refused_roots)
    folder = library_folder(project_dir, layout, category)
    target, copy = _target_in(folder, Path(path), layout.max_path_chars)
    return Placement(path, str(target), SampleInfo(category, target.stem), copy)


def copy_into_project(placement: Placement) -> None:
    """Write the planned copy: sidecar first, then the WAV, both with exclusive create (an
    existing file is never overwritten). A renamed copy gets its sidecar ``file`` field set
    to the new WAV name. Afterwards the copy must pass the bridge's own check. On any failure
    the files this call wrote are removed and the error is raised (``OSError`` or
    :class:`ImportPathError`)."""
    if not placement.copy:
        return
    src, dst = Path(placement.source), Path(placement.target)
    side_bytes = sidecar_path(src).read_bytes()  # bytes: keeps CRLF of a Windows sidecar
    if dst.name != src.name:
        meta = json.loads(side_bytes.decode("utf-8"))
        meta["file"] = dst.name
        eol = "\r\n" if b"\r\n" in side_bytes else "\n"
        text = json.dumps(meta, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        side_bytes = text.replace("\n", eol).encode("utf-8")
    written: list[Path] = []
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(sidecar_path(dst), "xb") as fh:
            written.append(sidecar_path(dst))
            fh.write(side_bytes)
        with open(src, "rb") as fin, open(dst, "xb") as fout:
            written.append(dst)
            shutil.copyfileobj(fin, fout)
        if not _same_file(src, dst):
            raise ImportPathError(f"Die Kopie {dst} weicht vom Original ab.")
        read_sample_info(dst)
    except BaseException:
        remove_copy(written)
        raise


def remove_copy(paths: Iterable[str | os.PathLike[str]]) -> None:
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass


def inspect_live(config: LiveConfig, wav: str | os.PathLike[str],
                 registry: CapabilityRegistry | None = None,
                 accept_unverified: bool = False,
                 project_dir: str | os.PathLike[str] | None = None,
                 refused_roots: Iterable[str | os.PathLike[str]] | None = None
                 ) -> LiveInspection:
    """Check the file (and where it will be copied, see :func:`plan_placement`), then read
    version, tracks and scenes. Sends no write, writes no file."""
    try:
        registry = registry or CapabilityRegistry.from_file()
        placement = plan_placement(wav, project_dir, refused_roots=refused_roots)
        path, sample = placement.target, placement.sample
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
                          tuple(bad), placement)


def prepare_import(config: LiveConfig, wav: str | os.PathLike[str], track: int | None,
                   slot: int | None, registry: CapabilityRegistry | None = None,
                   accept_unverified: bool = False,
                   project_dir: str | os.PathLike[str] | None = None,
                   refused_roots: Iterable[str | os.PathLike[str]] | None = None) -> ImportPlan:
    """The plan the user confirms: target, slot (first free one if ``slot`` is None), the
    copy into the project if one is needed, and the state of the set it was made from.
    Sends no write, writes no file."""
    try:
        registry = registry or CapabilityRegistry.from_file()
        placement = plan_placement(wav, project_dir, refused_roots=refused_roots)
        path, sample = placement.target, placement.sample
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
    return ImportPlan(True, "", plan_text(path, tuple(names), track, use, sample, placement),
                      path, track, use, scenes, expected, tuple(names), tuple(bad), placement)


def plan_text(path: str, names: tuple[str, ...], track: int | None, slot: int,
              sample: SampleInfo | None, placement: Placement | None = None) -> str:
    where = (f"die neue Spur {live_number(len(names))}" if track is None
             else f"Spur {live_number(track)} '{names[track]}'")
    lines = []
    if placement is not None and placement.copy:
        lines += ["Vorher auf der Festplatte: WAV und Sidecar in den Projektordner kopieren",
                  f"  von  {placement.source}", f"  nach {placement.target}",
                  "  (nichts wird überschrieben; geht der Import schief, bevor etwas in Live "
                  "ankommt, wird die Kopie wieder gelöscht)."]
    elif placement is not None and placement.moved:
        lines.append(f"Die Datei liegt schon unverändert im Projektordner: {placement.target}")
    lines.append("Geplante Änderungen im Live-Set:")
    n = 1
    if track is None:
        lines.append(f"  {n}. Neue Audiospur am Ende anlegen (wird Spur "
                     f"{live_number(len(names))}).")
        n += 1
    lines += [
        f"  {n}. Audio-Clip in {where}, Szene {live_number(slot)}, aus der Datei:",
        *([f"       Sample: {sample.label}"] if sample is not None else []),
        f"       {path}",
        "Live verweist auf diese Datei; das Programm verändert sie danach nicht.",
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
    placement = plan.placement
    if placement is None or not placement.copy:
        return _execute(config, plan, registry, allow)
    try:
        copy_into_project(placement)
    except (OSError, ImportPathError, ValueError) as exc:
        return ImportResult(False, f"Kopieren in den Projektordner fehlgeschlagen: {exc} "
                            "Es wurde nichts in Live geändert.")
    # An unexpected exception keeps the copy: whether Live already points at it is unknown.
    res = _execute(config, plan, registry, allow)
    # writes_sent = a write was confirmed; outcome_unknown = a write may still be applied
    # by Live later (timeout). In both cases Live may point at the copy: keep it.
    if res.ok or res.writes_sent or res.outcome_unknown:
        res.message += f" Die Kopie liegt in {placement.target}."
    else:
        remove_copy((sidecar_path(placement.target), placement.target))
        res.message += " Die Kopie im Projektordner wurde wieder gelöscht."
    return res


def _execute(config: LiveConfig, plan: ImportPlan, registry: CapabilityRegistry,
             allow: list[str]) -> ImportResult:
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
