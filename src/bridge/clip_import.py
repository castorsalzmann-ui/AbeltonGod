"""Import a WAV into a Session-view clip slot of Live (Phase 03, issue #50).

Path A of the phase spec: ``ClipSlot.create_audio_clip(path)`` through the AbeltonGod
extension of AbletonOSC (``scripts/install_abletonosc_extension.py``). Every step here goes
through :class:`bridge.osc_client.AbletonBridge`, so the capability gate applies:
``clip_slot.create_audio_clip`` is ``unknown`` and ``song.create_audio_track`` is
``supported`` until the user's Live run gives evidence, so only a check script with an
explicit override can run this.

Rules this module enforces (D-006, research note on the bridge):

- Every write gets an action-log entry **before** it is sent (``status: "planned"``) and one
  after (``error`` / ``timeout`` / ``interrupted``, or ``read_back`` with what was read). If
  the planned entry cannot be written, nothing is sent.
- A write counts as done only after a read-back: the slot has a clip, no other slot of the
  track changed, the track list is unchanged, and the clip's ``file_path`` is the file.
- A write whose outcome is unknown (timeout, Ctrl+C, failed read-back) is read back once and
  logged, and no undo is ever sent after it.
- Undo is sent only after a read-back shows the set exactly as the import left it, and its
  effect is read back too. At most one undo per confirmed write.

Blind spots: clips on other tracks, devices, automation, return/master tracks. Nothing here
deletes anything.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bridge.capabilities import CONTRACTS_DIR
from bridge.osc_client import AbletonBridge, BridgeError, BridgeTimeoutError

REPO_ROOT = CONTRACTS_DIR.parent
DEFAULT_ACTION_LOG = REPO_ROOT / "logs" / "bridge-actions.jsonl"  # logs/ is git-ignored

# A timed-out write may still be queued behind a blocked GUI thread: read back with more time.
READBACK_AFTER_TIMEOUT_FACTOR = 3.0


class ImportPathError(ValueError):
    """The file cannot be imported (not absolute, missing, not a WAV, outside the root)."""


class ActionLogError(OSError):
    """The action log could not be written. Callers must not send the write."""


class ImportAborted(Exception):
    """A pre-check, write or read-back failed; the message says what happened."""


class ImportInterrupted(ImportAborted):
    """Ctrl+C during a write or read-back. The outcome of the last write is unknown."""


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")


def validate_wav_path(path: str | os.PathLike[str],
                      library_root: str | os.PathLike[str] | None = None) -> str:
    """Return the absolute path string Live gets, or raise :class:`ImportPathError`.

    Checks: absolute; suffix ``.wav`` (any case); a regular file; a RIFF/WAVE header; inside
    ``library_root`` if one is given (after resolving symlinks). Until the sample library
    (#64) lands, callers pass ``library_root=None`` and any absolute WAV is accepted.
    """
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ImportPathError(f"not a usable path: {raw!r}")
    if not os.path.isabs(raw):
        raise ImportPathError(f"path must be absolute: {raw!r}")
    p = Path(raw)
    if p.suffix.lower() != ".wav":
        raise ImportPathError(f"only .wav files are imported (got {p.suffix or 'no suffix'!r})")
    if not p.is_file():
        raise ImportPathError(f"file does not exist or is not a regular file: {raw}")
    try:
        with p.open("rb") as fh:
            head = fh.read(12)
    except OSError as exc:
        raise ImportPathError(f"cannot read {raw}: {exc}") from exc
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise ImportPathError(f"not a RIFF/WAVE file: {raw}")
    if library_root is not None:
        root = Path(library_root).resolve()
        if not p.resolve().is_relative_to(root):
            raise ImportPathError(f"{raw} is outside the sample library {root}")
    return str(p)


def same_file_path(a: str, b: str) -> bool:
    """Path equality as the OS sees it (case-insensitive and ``/`` == ``\\`` on Windows)."""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


class ActionLog:
    """Append-only JSONL log of every change sent to Live (D-006 layer 1)."""

    def __init__(self, path: Path | str = DEFAULT_ACTION_LOG,
                 clock: Callable[[], str] = now_iso) -> None:
        self.path = Path(path)
        self._clock = clock
        self.entries: list[dict[str, Any]] = []  # what this process wrote, for reports

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        full = {"ts": self._clock(), **entry}
        try:
            line = json.dumps(full, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ActionLogError(f"action log entry is not plain JSON: {exc}") from exc
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            raise ActionLogError(f"cannot write action log {self.path}: {exc}") from exc
        self.entries.append(full)
        return full


@dataclass(frozen=True)
class SlotState:
    """What the import can see: all track names and the target track's clip slots."""

    track_names: tuple[str, ...]
    has_clip: tuple[bool, ...]  # every clip slot of the target track; () if it does not exist

    def as_json(self) -> dict[str, Any]:
        return {"track_names": list(self.track_names),
                "has_clip": [int(v) for v in self.has_clip]}


def read_state(bridge: AbletonBridge, track_index: int | None, num_slots: int,
               timeout_s: float | None = None) -> SlotState:
    names = tuple(bridge.get_track_names(timeout_s=timeout_s))
    if track_index is None or track_index >= len(names):
        return SlotState(names, ())
    slots = tuple(bridge.get_clip_slot_has_clip(track_index, s, timeout_s=timeout_s)
                  for s in range(num_slots))
    return SlotState(names, slots)


def first_empty_slot(state: SlotState) -> int | None:
    return next((i for i, has in enumerate(state.has_clip) if not has), None)


@dataclass
class Step:
    """One write of the import (or undo), as it ends up in the result block."""

    label: str
    outcome: str  # confirmed | timeout | error | interrupted | refused
    detail: str = ""


@dataclass
class ImportOutcome:
    track_index: int
    slot_index: int
    path: str
    created_track: bool
    num_slots: int
    before: SlotState  # before any write
    after_track: SlotState | None = None  # after the new track, before the clip
    after: SlotState | None = None  # after the clip, as read back
    file_path_read: str | None = None
    steps: list[Step] = field(default_factory=list)
    done: bool = False  # clip read back in the slot with the right file
    outcome_unknown: bool = False  # a write timed out / was interrupted / not read back
    undos_sent: int = 0

    def confirmed_writes(self) -> int:
        return sum(1 for s in self.steps
                   if s.outcome == "confirmed" and not s.label.startswith("undo"))


class ClipImporter:
    """Runs one import (optionally creating an audio track first) and its undo.

    The caller has shown the plan and got the user's yes. Methods raise
    :class:`ImportAborted` instead of guessing; ``last_outcome`` keeps what happened so far.
    """

    def __init__(self, bridge: AbletonBridge, log: ActionLog, *, timeout_s: float,
                 source: str = "scripts/live_import.py") -> None:
        self.bridge = bridge
        self.log = log
        self.timeout_s = timeout_s
        self.source = source
        self.last_outcome: ImportOutcome | None = None

    # -- helpers ---------------------------------------------------------------------------

    def _log(self, **entry: Any) -> None:
        self.log.append({"source": self.source, **entry})

    def _unknown(self, outcome: ImportOutcome, label: str, capability: str, params: dict,
                 status: str, note: str) -> str:
        """Mark the outcome unknown, read back once with more time, log it."""
        outcome.outcome_unknown = True
        try:
            state = read_state(self.bridge, outcome.track_index, outcome.num_slots,
                               timeout_s=self.timeout_s * READBACK_AFTER_TIMEOUT_FACTOR)
            readback = state.as_json()
        except (BridgeError, KeyboardInterrupt) as exc:
            readback = f"read-back failed: {type(exc).__name__}"
        self._log(action=label, capability=capability, params=params, status=status,
                  readback=readback, note=f"{note}; outcome unknown; no undo will be sent")
        return json.dumps(readback, ensure_ascii=False)

    def _send(self, outcome: ImportOutcome, label: str, capability: str, params: dict,
              before: SlotState, send: Callable[[], None]) -> None:
        """Log the plan, send, record the outcome. Raises ImportAborted on any failure."""
        self._log(action=label, capability=capability, params=params, status="planned",
                  before=before.as_json())
        try:
            send()
        except BridgeTimeoutError as exc:
            outcome.steps.append(Step(label, "timeout", "outcome unknown"))
            rb = self._unknown(outcome, label, capability, params, "timeout", "timed out")
            raise ImportAborted(f"{label} timed out; outcome unknown; read-back {rb}") from exc
        except KeyboardInterrupt as exc:
            outcome.steps.append(Step(label, "interrupted", "outcome unknown"))
            rb = self._unknown(outcome, label, capability, params, "interrupted", "Ctrl+C")
            raise ImportInterrupted(f"{label} interrupted; read-back {rb}") from exc
        except BridgeError as exc:
            outcome.steps.append(Step(label, "error", f"{type(exc).__name__}: {exc}"))
            self._log(action=label, capability=capability, params=params, status="error",
                      error=f"{type(exc).__name__}: {exc}")
            raise ImportAborted(f"{label}: {type(exc).__name__}: {exc}") from exc
        outcome.steps.append(Step(label, "confirmed"))

    def _readback(self, outcome: ImportOutcome, label: str, capability: str, params: dict,
                  fn: Callable[[], Any]) -> Any:
        """A read-back right after a confirmed write; failure makes the outcome unknown."""
        try:
            return fn()
        except KeyboardInterrupt as exc:
            self._unknown(outcome, label, capability, params, "interrupted",
                          "Ctrl+C during read-back")
            raise ImportInterrupted(f"{label}: read-back interrupted") from exc
        except BridgeError as exc:
            self._unknown(outcome, label, capability, params, "readback_failed",
                          f"read-back failed: {type(exc).__name__}")
            raise ImportAborted(f"{label}: read-back failed: {type(exc).__name__}: {exc}"
                                ) from exc

    # -- import ----------------------------------------------------------------------------

    def run(self, *, path: str, track_index: int | None, slot_index: int, num_slots: int,
            expected_before: SlotState) -> ImportOutcome:
        """Import ``path`` into ``slot_index`` of ``track_index`` (None = new audio track).

        ``expected_before`` is the state the plan was shown with; if the set reads back
        differently now, nothing is sent.
        """
        self.last_outcome = None
        if not 0 <= slot_index < num_slots:
            raise ImportAborted(f"slot {slot_index} does not exist ({num_slots} scenes)")
        create_track = track_index is None
        if not create_track and not self.bridge.get_track_has_audio_input(track_index):
            raise ImportAborted(f"track {track_index} is not an audio track; nothing sent")
        before = read_state(self.bridge, track_index, num_slots)
        if before != expected_before:
            raise ImportAborted("the set changed between the plan and the confirmation; "
                                "nothing sent")
        if not create_track and before.has_clip[slot_index]:
            raise ImportAborted(f"slot {slot_index} of track {track_index} is not empty; "
                                "nothing sent")
        target = len(before.track_names) if create_track else track_index
        outcome = ImportOutcome(track_index=target, slot_index=slot_index, path=path,
                                created_track=create_track, num_slots=num_slots,
                                before=before)
        self.last_outcome = outcome

        clip_before = before
        if create_track:
            params = {"index": -1}
            self._send(outcome, "create_audio_track", "song.create_audio_track", params,
                       before, lambda: self.bridge.create_audio_track(-1))

            def check_track() -> tuple[SlotState, bool]:
                state = read_state(self.bridge, target, num_slots)
                ok = (len(state.track_names) == len(before.track_names) + 1
                      and state.track_names[:-1] == before.track_names
                      and len(state.has_clip) == num_slots and not any(state.has_clip)
                      and self.bridge.get_track_has_audio_input(target))
                return state, ok

            after_track, ok = self._readback(outcome, "create_audio_track",
                                             "song.create_audio_track", params, check_track)
            outcome.after_track = after_track
            self._log(action="create_audio_track", capability="song.create_audio_track",
                      params=params, status="read_back", after=after_track.as_json(), ok=ok)
            if not ok:
                raise ImportAborted("the new track is not an empty audio track at the end of "
                                    "the track list; clip not sent")
            clip_before = after_track

        params = {"track_index": target, "slot_index": slot_index, "path": path}
        self._send(outcome, "create_audio_clip", "clip_slot.create_audio_clip", params,
                   clip_before, lambda: self.bridge.create_audio_clip(target, slot_index, path))

        def check_clip() -> tuple[SlotState, str | None]:
            state = read_state(self.bridge, target, num_slots)
            fp = None
            if state.track_names == clip_before.track_names and state.has_clip[slot_index]:
                fp = self.bridge.get_clip_file_path(target, slot_index)
            return state, fp

        after, file_path = self._readback(outcome, "create_audio_clip",
                                          "clip_slot.create_audio_clip", params, check_clip)
        outcome.after, outcome.file_path_read = after, file_path
        expected = list(clip_before.has_clip)
        expected[slot_index] = True
        outcome.done = (after.track_names == clip_before.track_names
                        and list(after.has_clip) == expected
                        and file_path is not None and same_file_path(file_path, path))
        self._log(action="create_audio_clip", capability="clip_slot.create_audio_clip",
                  params=params, status="read_back", after=after.as_json(),
                  file_path=file_path, ok=outcome.done)
        if not outcome.done:
            raise ImportAborted("read-back after the import does not show exactly the new "
                                f"clip with this file (file_path={file_path!r})")
        return outcome

    # -- undo ------------------------------------------------------------------------------

    def undo_step(self, outcome: ImportOutcome, *, expect_now: SlotState,
                  expect_after: SlotState, label: str) -> bool:
        """One Live undo, only if the set reads back exactly as ``expect_now``.

        Returns True if the state after the undo equals ``expect_after``. Raises
        :class:`ImportAborted` if undo is not allowed, if the read-back before the undo
        differs (nothing sent), or on a bridge error.
        """
        if outcome.outcome_unknown:
            raise ImportAborted("a write has an unknown outcome; undo is never sent then")
        if outcome.undos_sent >= outcome.confirmed_writes():
            raise ImportAborted("every confirmed write has been undone already")
        now = read_state(self.bridge, outcome.track_index, len(expect_now.has_clip))
        if now != expect_now:
            self._log(action=label, capability="song.undo", status="refused",
                      reason="read-back before undo differs from the expected state",
                      now=now.as_json(), expected=expect_now.as_json())
            outcome.steps.append(Step(label, "refused", "set changed since the import"))
            raise ImportAborted("the set is not as the import left it; undo NOT sent")
        self._send(outcome, label, "song.undo", {}, now, self.bridge.undo)
        outcome.undos_sent += 1
        after = self._readback(outcome, label, "song.undo", {}, lambda: read_state(
            self.bridge, outcome.track_index, len(expect_after.has_clip)))
        ok = after == expect_after
        self._log(action=label, capability="song.undo", status="read_back",
                  after=after.as_json(), expected=expect_after.as_json(), ok=ok)
        if not ok:
            outcome.steps[-1].detail = f"read-back differs: {after.as_json()}"
        return ok
