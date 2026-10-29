"""The three Phase 04b copilot tools (#148): ``generate_kick``, ``list_tracks``,
``import_sample``.

Every handler here is only ever run by ``Toolbox.run`` (guard first, schema check, approval;
``tests/orchestrator/test_guard_wiring.py`` checks that statically). Input schemas come from
``contracts/`` with the root metadata ``$schema``, ``$id``, ``title`` and ``$comment`` dropped
(INTERFACES.md "Tool inputs"); nothing else is changed.

Session table (INTERFACES.md, decision #81: the model never names a file). ``KickSession``
maps ``sample_id`` -> (absolute WAV path, SHA-256 of the WAV bytes). It is filled only by its
own ``generate_kick`` handler, from what ``library.place_kick`` wrote into the kick folder of
the project the user named when starting the chat. ``import_sample`` takes nothing else.

Results the tools return (the contract defines inputs only; these are the outputs, #148):

- ``generate_kick`` -> ``{"kicks": [{"sample_id", "file", "variant", "seed", "parameters",
  "features"}], "folder"}``. Two files per kick (WAV + sidecar), Live untouched. Approval
  ``routine``.
- ``list_tracks`` -> ``{"tracks": [{"index", "name", "is_audio_track"}], "scene_count",
  "note"}``. Reads only. ``is_audio_track`` is Live's ``has_audio_input``; a ``false`` value
  has never been observed on the user's machine (#153). Nothing that writes relies on it: a
  ``false`` only ever makes ``import_sample`` refuse, and ``import_sample`` reads it again
  itself right before the write (``ClipImporter.run``).
- ``import_sample`` -> ``{"imported": {"sample_id", "file", "track_index", "slot_index",
  "track_name_before", "track_name_after", "file_path_read"}}``. Approval ``confirm``; at most
  one Live write (``clip_slot.create_audio_clip``); existing audio tracks only (v1); no undo.

SHA-256 pin: the handler hashes the WAV bytes itself right after ``place_kick`` and pins that
value. The sidecar's ``sha256`` is optional in sample-metadata; when it is present it must be
the same value, otherwise the kick is refused (no id). ``import_sample`` hashes the file again
in its plan step and once more right before the write; any difference is refused.

Reused path: ``place_kick`` never overwrites, but after the user deletes a kick it may give the
same name to a new one. When a new kick lands on the path an older id points to, the older id
is removed from the table, so it is refused as unknown (a second guard next to the hash).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_engine.params import INTEGER_FIELDS, resolve_kick_params
from audio_engine.variants import make_variants
from bridge.capabilities import (
    CONTRACTS_DIR,
    CapabilityError,
    CapabilityGate,
    CapabilityRegistry,
)
from bridge.clip_import import (
    DEFAULT_ACTION_LOG,
    ActionLog,
    ClipImporter,
    ImportPathError,
    SlotState,
    first_empty_slot,
    read_state,
    same_file_path,
    validate_wav_path,
)
from bridge.osc_client import DEFAULT_TIMEOUT_S, AbletonBridge, BridgeError
from library import library_folder, place_kick, sidecar_path
from orchestrator.project import (
    ProjectCheck,
    ProjectCheckUnavailable,
    load_project_check,
    project_problem,
)
from orchestrator.tools import Approval, Plan, Tool, ToolError, ToolOutput

# Root keys of a contract file that are metadata, not input schema (INTERFACES.md: `$id`
# alone makes the CLI fall back to non-strict). `$comment` is kick-params' change note.
DROPPED_ROOT_KEYS = ("$schema", "$id", "title", "$comment")
# The one place that names each tool's schema source. generate_kick: kick-params itself until
# the strict tool schema of #131 (PR #162, contracts/tool-generate-kick.schema.json) is merged;
# then point this at that file. The handler always runs resolve_kick_params, so a tool schema
# that accepts more than the contract cannot let a bad kick through.
KICK_PARAMS_CONTRACT = "kick-params.schema.json"
TOOL_CONTRACTS = {
    "generate_kick": KICK_PARAMS_CONTRACT,
    "list_tracks": "tool-list-tracks.schema.json",
    "import_sample": "tool-import-sample.schema.json",
}
FILES_PER_KICK = 2  # WAV + sidecar
SAMPLE_ID_PREFIX = "kick-"
CONTEXT_MAX_KICKS = 24  # kicks listed in the system prompt (newest first)

LIST_TRACKS_CAPS = ("song.track_names.get", "track.has_audio_input.get", "song.num_scenes.get")
IMPORT_CAPS = (
    "clip_slot.create_audio_clip",
    "song.track_names.get",
    "track.has_audio_input.get",
    "clip_slot.has_clip.get",
    "clip.file_path.get",
    "song.num_scenes.get",
)
AUDIO_FLAG_NOTE = (
    "is_audio_track is Live's has_audio_input. A false value has not been observed on this "
    "machine yet; import_sample checks it again itself and refuses a track that is not audio."
)

GENERATE_DESCRIPTION = (
    "Renders kicks with the local, deterministic kick engine into the kick folder of the "
    "user's Live project (WAV + sidecar per kick). variants = number of kicks (1 = only the "
    "given parameters; more = variations around them, each with its own derived seed). "
    "Returns one sample_id per kick; pass it to import_sample. Does not touch the Live set."
)


def contract_input_schema(file_name: str) -> dict[str, Any]:
    """The contract file minus its root metadata (``DROPPED_ROOT_KEYS``)."""
    doc = json.loads((CONTRACTS_DIR / file_name).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{file_name} is not a JSON Schema object")
    return {k: copy.deepcopy(v) for k, v in doc.items() if k not in DROPPED_ROOT_KEYS}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _whole_int(value: Any) -> int | None:
    """``value`` as an int if it is an int or a whole-number float (JSON 2.0), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


@dataclass(frozen=True)
class SampleEntry:
    sample_id: str
    path: str  # absolute, as place_kick returned it
    sha256: str  # of the WAV bytes, computed by this session right after writing
    file: str
    variant: int
    seed: int


@dataclass(frozen=True)
class ImportPlan:
    entry: SampleEntry
    track_index: int
    slot_index: int
    num_scenes: int
    state: SlotState  # what the user was shown; ClipImporter.run compares it again
    track_name: str


class KickSession:
    """One chat session's kick tools and sample table. One request at a time (guard)."""

    def __init__(
        self,
        project_dir: str | Path,
        *,
        bridge_factory: Callable[[], AbletonBridge] | None = None,
        registry: CapabilityRegistry | None = None,
        action_log: str | Path = DEFAULT_ACTION_LOG,
        bridge_timeout_s: float = DEFAULT_TIMEOUT_S,
        refused_roots: tuple[Path, ...] | None = None,
        project_check: ProjectCheck | None = None,
    ) -> None:
        """``project_check``: the shared check of #149 (default ``library.check_project_dir``;
        tests pass a double). Without one the session refuses to start
        (``ProjectCheckUnavailable``): no kick is written into an unchecked folder."""
        check = project_check if project_check is not None else load_project_check()
        if check is None:
            raise ProjectCheckUnavailable(
                "the shared project-folder check (library.check_project_dir, #149) is not "
                "available yet; the kick tools stay off until it is merged")
        self._check = check
        self._refused_roots = refused_roots
        problem = self.project_problem(project_dir)
        if problem is not None:
            raise ValueError(f"project folder refused: {problem}")
        self.project_dir = str(Path(project_dir))
        self.registry = registry if registry is not None else CapabilityRegistry.from_file()
        self._bridge_factory = bridge_factory or self._default_bridge
        self.action_log = Path(action_log)
        self.bridge_timeout_s = float(bridge_timeout_s)
        self._table: dict[str, SampleEntry] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    # ----- configuration ---------------------------------------------------------------------

    def project_problem(self, project_dir: str | Path) -> str | None:
        return project_problem(self._check, project_dir, self._refused_roots)

    @property
    def kick_folder(self) -> Path:
        return library_folder(self.project_dir)

    def gate(self) -> CapabilityGate:
        """The gate the toolbox checks the tools' capabilities with: no overrides (D-004)."""
        return CapabilityGate(self.registry)

    def _default_bridge(self) -> AbletonBridge:
        return AbletonBridge.from_env(registry=self.registry)

    # ----- session table ---------------------------------------------------------------------

    def sample_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._table)

    def entry(self, sample_id: str) -> SampleEntry | None:
        with self._lock:
            return self._table.get(sample_id)

    def _register(self, path: str, sha: str, variant: int, seed: int) -> SampleEntry:
        with self._lock:
            # A reused path (the old file was deleted, place_kick gave its name to the new
            # kick) makes every older id for it unknown (INTERFACES.md, import_sample 1.).
            for old_id in [i for i, e in self._table.items() if same_file_path(e.path, path)]:
                del self._table[old_id]
            sample_id = f"{SAMPLE_ID_PREFIX}{self._next_id}"
            self._next_id += 1
            entry = SampleEntry(sample_id, path, sha, Path(path).name, variant, seed)
            self._table[sample_id] = entry
            return entry

    def context(self) -> str:
        """Session facts for the system prompt: the kicks this session made."""
        with self._lock:
            entries = list(self._table.values())[-CONTEXT_MAX_KICKS:]
        if not entries:
            return ""
        lines = ["Kicks generated in this chat session (newest last). To import one, pass its "
                 "sample_id to import_sample; never a file name or path:"]
        lines += [f"- {e.sample_id}: {e.file} (variant {e.variant}, seed {e.seed})"
                  for e in entries]
        return "\n".join(lines)

    # ----- tools -----------------------------------------------------------------------------

    def tools(self, files_per_request: int | None = None) -> list[Tool]:
        """``files_per_request``: the guard profile's ``max_files_written``; when given, the
        generate_kick description names the resulting kick limit per request."""
        kick_schema = contract_input_schema(TOOL_CONTRACTS["generate_kick"])
        description = GENERATE_DESCRIPTION
        if files_per_request is not None:
            description += (f" At most {int(files_per_request) // FILES_PER_KICK} kicks per "
                            f"request ({FILES_PER_KICK} files each, request limit "
                            f"{int(files_per_request)} files).")
        # From the parameter contract, not the tool schema (a strict tool schema has no
        # `maximum`, #131).
        max_variants = int(
            contract_input_schema(KICK_PARAMS_CONTRACT)["properties"]["variants"]["maximum"])
        list_schema = contract_input_schema(TOOL_CONTRACTS["list_tracks"])
        import_schema = contract_input_schema(TOOL_CONTRACTS["import_sample"])

        def kick_files(arguments: Any) -> int:
            """Files one call writes, read before validation. A value the schema refuses
            (not an object, a string, 2.5, null, < 1) never reaches the handler, so it
            declares 0 and comes back as invalid_arguments, not as a guard stop (PR #168
            review). A whole number above the maximum declares what it asks for."""
            if not isinstance(arguments, Mapping):
                return 0
            n = _whole_int(arguments.get("variants", 1))
            if n is None or n < 1:
                return 0
            return FILES_PER_KICK * n

        return [
            Tool("generate_kick", description, kick_schema, self._generate,
                 approval=Approval.ROUTINE, max_files_written=FILES_PER_KICK * max_variants,
                 files_for=kick_files),
            Tool("list_tracks", list_schema["description"], list_schema, self._list_tracks,
                 approval=Approval.ROUTINE, capabilities=LIST_TRACKS_CAPS),
            Tool("import_sample", import_schema["description"], import_schema, self._import,
                 approval=Approval.CONFIRM, max_live_writes=1, capabilities=IMPORT_CAPS,
                 prepare=self._plan_import),
        ]

    # generate_kick ----------------------------------------------------------------------------

    def _generate(self, arguments: dict[str, Any]) -> ToolOutput:
        problem = self.project_problem(self.project_dir)  # the folder may have moved since
        if problem is not None:
            raise ToolError(f"the project folder is not usable now: {problem}",
                            files_written=0, live_writes=0)
        request = copy.deepcopy(arguments)
        for key in INTEGER_FIELDS:
            whole = _whole_int(request.get(key))
            if key in request and whole is not None:
                request[key] = whole
        try:
            base = resolve_kick_params(request)
            variants = make_variants(request, base["variants"])
        except ValueError as exc:  # KickParamsError, VariantError
            raise ToolError(f"kick parameters refused: {exc}", files_written=0,
                            live_writes=0) from exc
        seed = base["seed"]
        stem = f"{request.get('preset') or 'kick'}_s{seed}"
        made: list[dict[str, Any]] = []
        files = 0
        for i, params in enumerate(variants):
            description = (f"Copilot generate_kick: variant {i} of {len(variants)}, "
                           f"base seed {seed}.")
            try:
                wav = place_kick(params, self.project_dir, name=f"{stem}_v{i}",
                                 description=description)
            except (ValueError, OSError) as exc:  # place_kick removed what it wrote
                raise self._partial(made, files, f"kick {i} of {len(variants)} was not written: "
                                    f"{type(exc).__name__}: {exc}") from exc
            files += FILES_PER_KICK
            try:
                entry, info = self._pin(wav, i, int(params["seed"]))
            except ToolError as exc:
                raise self._partial(made, files, str(exc)) from exc
            made.append({"sample_id": entry.sample_id, "file": entry.file, **info})
        return ToolOutput({"kicks": made, "folder": str(self.kick_folder)},
                          files_written=files, live_writes=0)

    def _pin(self, wav: Path, variant: int, seed: int) -> tuple[SampleEntry, dict[str, Any]]:
        """Hash the WAV just written, check it against its sidecar, register it."""
        try:
            sha = sha256_file(wav)
            sidecar = json.loads(sidecar_path(wav).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ToolError(f"{wav.name} could not be read back after writing: {exc}") from exc
        if not isinstance(sidecar, dict):
            raise ToolError(f"the sidecar of {wav.name} is not a JSON object")
        stated = sidecar.get("sha256")
        if stated is not None and stated != sha:
            raise ToolError(f"{wav.name} does not match the sha256 in its sidecar; refused "
                            "(no sample_id)")
        entry = self._register(str(wav), sha, variant, seed)
        params = sidecar.get("parameters") if isinstance(sidecar.get("parameters"), dict) else {}
        shown = {k: v for k, v in params.items()
                 if k not in ("schema_version", "sample_rate", "bit_depth", "variants")}
        features = sidecar.get("features") if isinstance(sidecar.get("features"), dict) else {}
        return entry, {"variant": variant, "seed": seed, "parameters": shown,
                       "features": features}

    @staticmethod
    def _partial(made: list[dict[str, Any]], files: int, why: str) -> ToolError:
        ids = [m["sample_id"] for m in made]
        return ToolError(
            why + (f"; finished before it: {', '.join(ids)}" if ids else ""),
            files_written=files, live_writes=0,
            details={"kicks": copy.deepcopy(made)},
        )

    # list_tracks ------------------------------------------------------------------------------

    def _list_tracks(self, arguments: dict[str, Any]) -> ToolOutput:
        bridge = self._connect()
        try:
            names = bridge.get_track_names()
            scenes = bridge.get_num_scenes()
            tracks = [{"index": i, "name": name,
                       "is_audio_track": bridge.get_track_has_audio_input(i)}
                      for i, name in enumerate(names)]
        except (BridgeError, CapabilityError) as exc:
            raise ToolError(f"Live could not be read: {type(exc).__name__}: {exc}",
                            files_written=0, live_writes=0) from exc
        finally:
            bridge.close()
        return ToolOutput({"tracks": tracks, "scene_count": scenes, "note": AUDIO_FLAG_NOTE},
                          files_written=0, live_writes=0)

    # import_sample ----------------------------------------------------------------------------

    def _connect(self) -> AbletonBridge:
        try:
            return self._bridge_factory()
        except (BridgeError, CapabilityError, ValueError, OSError) as exc:
            raise ToolError(f"no connection to Live (AbletonOSC): {type(exc).__name__}: {exc}",
                            files_written=0, live_writes=0,
                            details={"live": "unchanged"}) from exc

    def _checked_file(self, sample_id: Any) -> tuple[SampleEntry, str]:
        """The entry and the path string Live gets; refuses unknown ids and changed files."""
        entry = self.entry(sample_id) if isinstance(sample_id, str) else None
        if entry is None:
            known = ", ".join(self.sample_ids()) or "none yet"
            raise ToolError(f"unknown sample_id {sample_id!r}: only kicks generate_kick made in "
                            f"this session can be imported (known: {known})",
                            files_written=0, live_writes=0, details={"live": "unchanged"})
        try:
            path = validate_wav_path(entry.path, library_root=self.kick_folder)
            sha = sha256_file(path)
        except (ImportPathError, OSError) as exc:
            raise ToolError(f"{entry.sample_id}: the kick file cannot be used: {exc}",
                            files_written=0, live_writes=0,
                            details={"live": "unchanged"}) from exc
        if sha != entry.sha256:
            raise ToolError(f"{entry.sample_id}: {entry.file} changed since generate_kick wrote "
                            "it (sha256 differs); refused",
                            files_written=0, live_writes=0, details={"live": "unchanged"})
        return entry, path

    def _plan_import(self, arguments: dict[str, Any]) -> Plan:
        entry, _ = self._checked_file(arguments["sample_id"])
        track = _whole_int(arguments["track_index"])
        slot_arg = arguments.get("slot_index")
        slot = _whole_int(slot_arg) if slot_arg is not None else None
        bridge = self._connect()
        try:
            names = bridge.get_track_names()
            if track is None or not 0 <= track < len(names):
                raise ToolError(f"track_index {arguments['track_index']!r} does not exist "
                                f"({len(names)} tracks, 0 to {len(names) - 1})",
                                details={"live": "unchanged"})
            if not bridge.get_track_has_audio_input(track):
                raise ToolError(f"track {track} ({names[track]!r}) is not an audio track; "
                                "v1 imports into existing audio tracks only",
                                details={"live": "unchanged"})
            scenes = bridge.get_num_scenes()
            state = read_state(bridge, track, scenes)
        except (BridgeError, CapabilityError) as exc:
            raise ToolError(f"Live could not be read: {type(exc).__name__}: {exc}",
                            details={"live": "unchanged"}) from exc
        finally:
            bridge.close()
        if slot_arg is not None:
            if slot is None or not 0 <= slot < scenes:
                raise ToolError(f"slot_index {slot_arg!r} does not exist ({scenes} scenes)",
                                details={"live": "unchanged"})
            if state.has_clip[slot]:
                raise ToolError(f"slot {slot} of track {track} already holds a clip; it is "
                                "never overwritten", details={"live": "unchanged"})
        else:
            slot = first_empty_slot(state)
            if slot is None:
                raise ToolError(f"track {track} has no empty slot ({scenes} scenes)",
                                details={"live": "unchanged"})
        summary = {"sample_id": entry.sample_id, "file": entry.file, "track_index": track,
                   "track_name": names[track], "slot_index": slot, "scene_count": scenes}
        return Plan(summary, ImportPlan(entry, track, slot, scenes, state, names[track]))

    def _import(self, arguments: dict[str, Any], plan: Plan) -> ToolOutput:
        data = plan.data
        if not isinstance(data, ImportPlan):
            raise ToolError("internal: no import plan", files_written=0, live_writes=0)
        entry, path = self._checked_file(data.entry.sample_id)  # hash right before the write
        if entry != data.entry:
            raise ToolError(f"{entry.sample_id} changed since the plan; refused",
                            files_written=0, live_writes=0, details={"live": "unchanged"})
        bridge = self._connect()
        importer = None
        try:
            importer = ClipImporter(bridge, ActionLog(self.action_log),
                                    timeout_s=self.bridge_timeout_s,
                                    source="orchestrator.import_sample")
            outcome = importer.run(path=path, track_index=data.track_index,
                                   slot_index=data.slot_index, num_slots=data.num_scenes,
                                   expected_before=data.state)
        except Exception as exc:  # noqa: BLE001 - ImportAborted, BridgeError, OSError, a bug:
            # the model must always learn whether Live may have changed
            last = importer.last_outcome if importer is not None else None
            sent = last is not None and bool(last.steps)
            raise ToolError(
                f"import not done: {type(exc).__name__}: {exc}",
                files_written=0, live_writes=1 if sent else 0,
                details={"live": "unknown: look in Live before anything else" if sent
                         else "unchanged"},
            ) from exc
        finally:
            bridge.close()
        return ToolOutput({"imported": {
            "sample_id": entry.sample_id, "file": entry.file,
            "track_index": outcome.track_index, "slot_index": outcome.slot_index,
            "track_name_before": outcome.target_name_before,
            "track_name_after": outcome.target_name_after,
            "file_path_read": outcome.file_path_read,
        }}, files_written=0, live_writes=1)


__all__ = [
    "DROPPED_ROOT_KEYS",
    "FILES_PER_KICK",
    "IMPORT_CAPS",
    "LIST_TRACKS_CAPS",
    "TOOL_CONTRACTS",
    "ImportPlan",
    "KickSession",
    "SampleEntry",
    "contract_input_schema",
    "sha256_file",
]
