"""Import a WAV into a Session-view clip slot of Live (Phase 03, issue #50).

Path A of the phase spec: ``ClipSlot.create_audio_clip(path)`` through the AbeltonGod
extension of AbletonOSC (``scripts/install_abletonosc_extension.py``). Every step here goes
through :class:`bridge.osc_client.AbletonBridge`, so the capability gate applies:
``clip_slot.create_audio_clip`` is ``tested`` (#50 user runs 2-4); ``song.create_audio_track``
and the four reads used here are ``tested`` since #143. One Live undo may revert the new track
and its clip together (#143 new-track run), so every undo is read back.

Rules this module enforces (D-006, research note on the bridge):

- Every write gets an action-log entry **before** it is sent (``status: "planned"``) and one
  after (``error`` / ``timeout`` / ``interrupted``, or ``read_back`` with what was read). If
  the planned entry cannot be written, nothing is sent.
- A write counts as done only after a read-back: the slot has a clip, no other slot of the
  track changed, the track list is unchanged, and the clip's ``file_path`` is the file.
- Live renames a default-named audio track after the clip it gets (#50 user run 1, from the
  user's action log: ``3-Audio`` -> ``3-centre_s1001_v0``). The read-back after the clip
  therefore does not pin the target track's name; every other track name, the track count,
  every slot of the target track and the file path are compared.
- As a precaution, the read-back after a confirmed write is repeated (every
  ``READBACK_POLL_INTERVAL_S``) until it matches or ``READBACK_WINDOW_S`` is over. A clip that
  shows up only a moment later is possible but has not been observed (in run 1 it was visible
  at the first read). The window is bounded and fail-safe: no match means unknown, no undo.
- A write whose outcome is unknown (timeout, Ctrl+C, failed read-back, or a read-back that
  never matched within the window) is logged, and no undo is ever sent after it.
- Undo is sent only after a read-back shows the set exactly as this import last read it back
  (the target track's name included), and its effect is read back too: track count, all other
  names, the target's slots, and a target name that is one of the two this import saw (before
  or after Live's rename). At most one undo per confirmed write.

Blind spots: clips on other tracks, devices, automation, return/master tracks. Nothing here
deletes anything.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bridge.capabilities import CONTRACTS_DIR
from bridge.osc_client import (
    AbletonBridge,
    AbletonOSCError,
    BridgeError,
    BridgeProtocolError,
    BridgeTimeoutError,
)

REPO_ROOT = CONTRACTS_DIR.parent
DEFAULT_ACTION_LOG = REPO_ROOT / "logs" / "bridge-actions.jsonl"  # logs/ is git-ignored

# A timed-out write may still be queued behind a blocked GUI thread: read back with more time.
READBACK_AFTER_TIMEOUT_FACTOR = 3.0

# Precaution, not the #50 run-1 fix (that was the target-name comparison): after a confirmed
# write, the read-back is repeated until it matches or this window is over. A late clip has
# not been observed. Bounded and fail-safe: a read-back that never matches is an unknown
# outcome, never a success.
READBACK_WINDOW_S = 2.0
READBACK_POLL_INTERVAL_S = 0.1


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


def same_except_track_name(a: SlotState, b: SlotState, track_index: int) -> bool:
    """Equal slots and track count, and equal names for every track except ``track_index``.

    Live renames a default-named audio track after the clip it gets (#50 user run 1), so the
    target track's name is the one thing a read-back may not pin.
    """
    if a.has_clip != b.has_clip or len(a.track_names) != len(b.track_names):
        return False
    return all(x == y for i, (x, y) in enumerate(zip(a.track_names, b.track_names, strict=True))
               if i != track_index)


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
    target_name_before: str | None = None  # target track's name right before the clip
    target_name_after: str | None = None  # Live may rename the target track after the clip
    after_undo: SlotState | None = None  # read back after the last undo that was sent
    refused_now: SlotState | None = None  # read back by an undo pre-check that refused
    undo_reads: list[SlotState] = field(default_factory=list)  # after each undo, oldest first
    steps: list[Step] = field(default_factory=list)
    done: bool = False  # clip read back in the slot with the right file
    outcome_unknown: bool = False  # a write timed out / was interrupted / not read back
    undos_sent: int = 0

    def confirmed_writes(self) -> int:
        return sum(1 for s in self.steps
                   if s.outcome == "confirmed" and not s.label.startswith("undo"))

    def import_names(self) -> frozenset[str | None]:
        """The target track names this import itself read: before and after the clip."""
        return frozenset({self.target_name_before, self.target_name_after})


def target_name(state: SlotState, track_index: int) -> str | None:
    """The target track's name in ``state``; None if the track does not exist there."""
    return state.track_names[track_index] if track_index < len(state.track_names) else None


class ClipImporter:
    """Runs one import (optionally creating an audio track first) and its undo.

    The caller has shown the plan and got the user's yes. Methods raise
    :class:`ImportAborted` instead of guessing; ``last_outcome`` keeps what happened so far.
    """

    def __init__(self, bridge: AbletonBridge, log: ActionLog, *, timeout_s: float,
                 source: str = "scripts/live_import.py",
                 readback_window_s: float = READBACK_WINDOW_S,
                 poll_interval_s: float = READBACK_POLL_INTERVAL_S,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.bridge = bridge
        self.log = log
        self.timeout_s = timeout_s
        self.source = source
        self.readback_window_s = readback_window_s
        self.poll_interval_s = poll_interval_s
        self._clock = clock
        self._sleep = sleep
        self.last_outcome: ImportOutcome | None = None

    # -- helpers ---------------------------------------------------------------------------

    def _log(self, **entry: Any) -> None:
        self.log.append({"source": self.source, **entry})

    def _poll(self, check: Callable[[], tuple[Any, bool]]) -> tuple[Any, bool, int]:
        """Call ``check`` until it reports a match or the read-back window is over.

        Returns (last value, matched, number of reads). It always reads at least once and
        never reports a match that ``check`` did not report: "not visible yet" is not success.
        """
        deadline = self._clock() + self.readback_window_s
        polls = 0
        while True:
            value, ok = check()
            polls += 1
            if ok or self._clock() >= deadline:
                return value, ok, polls
            self._sleep(self.poll_interval_s)

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

            after_track, ok, polls = self._readback(
                outcome, "create_audio_track", "song.create_audio_track", params,
                lambda: self._poll(check_track))
            outcome.after_track = after_track
            self._log(action="create_audio_track", capability="song.create_audio_track",
                      params=params, status="read_back", after=after_track.as_json(), ok=ok,
                      polls=polls)
            if not ok:
                # Confirmed but never seen as intended: what Live did is unknown (no undo).
                outcome.outcome_unknown = True
                raise ImportAborted("the new track is not an empty audio track at the end of "
                                    f"the track list after {polls} read(s); clip not sent")
            clip_before = after_track

        params = {"track_index": target, "slot_index": slot_index, "path": path}
        self._send(outcome, "create_audio_clip", "clip_slot.create_audio_clip", params,
                   clip_before, lambda: self.bridge.create_audio_clip(target, slot_index, path))
        expected = list(clip_before.has_clip)
        expected[slot_index] = True
        errors: list[str] = []

        def check_clip() -> tuple[tuple[SlotState, str | None], bool]:
            state = read_state(self.bridge, target, num_slots)
            fp = None
            # Live renames a default-named target track after the clip (#50 run 1, action
            # log: "3-Audio" -> "3-centre_s1001_v0"), so its name is not compared here.
            if (same_except_track_name(state, SlotState(clip_before.track_names,
                                                        state.has_clip), target)
                    and state.has_clip[slot_index]):
                try:
                    fp = self.bridge.get_clip_file_path(target, slot_index)
                except (AbletonOSCError, BridgeProtocolError) as exc:  # not readable yet
                    errors.append(f"{type(exc).__name__}: {exc}")
            ok = (same_except_track_name(state, SlotState(clip_before.track_names,
                                                          tuple(expected)), target)
                  and fp is not None and same_file_path(fp, path))
            return (state, fp), ok

        (after, file_path), done, polls = self._readback(
            outcome, "create_audio_clip", "clip_slot.create_audio_clip", params,
            lambda: self._poll(check_clip))
        outcome.after, outcome.file_path_read, outcome.done = after, file_path, done
        name_before = clip_before.track_names[target]
        name_after = target_name(after, target)
        outcome.target_name_before, outcome.target_name_after = name_before, name_after
        self._log(action="create_audio_clip", capability="clip_slot.create_audio_clip",
                  params=params, status="read_back", after=after.as_json(),
                  file_path=file_path, ok=done, polls=polls,
                  target_track_name={"before": name_before, "after": name_after},
                  file_path_errors=errors[-3:])
        if not done:
            # The write was confirmed but its effect was never seen: unknown, so no undo.
            outcome.outcome_unknown = True
            raise ImportAborted(
                f"read-back after {polls} read(s) in {self.readback_window_s:g} s does not show "
                f"exactly the new clip with this file (file_path={file_path!r}, "
                f"read={json.dumps(after.as_json(), ensure_ascii=False)})")
        return outcome

    # -- undo ------------------------------------------------------------------------------

    def undo_step(self, outcome: ImportOutcome, *, expect_now: SlotState,
                  expect_after: SlotState, label: str) -> bool:
        """One Live undo, only if the set reads back exactly as ``expect_now``.

        Pre-check: everything as ``expect_now``, and the target track's name exactly as this
        import last read it back (after the clip for the first undo, after the previous undo
        otherwise). A name nobody here saw means a foreign action is the newest undo step.

        Returns True if the state after the undo equals ``expect_after`` apart from the
        target track's name, and that name is one of the two this import saw (before or after
        Live's rename; whether Live's undo reverts the rename is not known). The state read
        is kept in ``outcome.after_undo``, so the caller can tell whether the name came back.
        Raises :class:`ImportAborted` if undo is not allowed, if the read-back before the
        undo differs (nothing sent), or on a bridge error.
        """
        if outcome.outcome_unknown:
            raise ImportAborted("a write has an unknown outcome; undo is never sent then")
        if outcome.undos_sent >= outcome.confirmed_writes():
            raise ImportAborted("every confirmed write has been undone already")
        idx = outcome.track_index
        now = read_state(self.bridge, idx, len(expect_now.has_clip))
        last_seen = (outcome.target_name_after if outcome.after_undo is None
                     else target_name(outcome.after_undo, idx))
        name_now = target_name(now, idx)
        # last_seen is always one of outcome.import_names(): check_undo below enforces it.
        if not (same_except_track_name(now, expect_now, idx) and name_now == last_seen):
            self._log(action=label, capability="song.undo", status="refused",
                      reason="read-back before undo differs from the expected state",
                      now=now.as_json(), expected=expect_now.as_json(),
                      expected_target_name=last_seen)
            outcome.refused_now = now
            outcome.steps.append(Step(label, "refused", "set changed since the import"))
            raise ImportAborted("the set is not as the import left it; undo NOT sent")
        self._send(outcome, label, "song.undo", {}, now, self.bridge.undo)
        outcome.undos_sent += 1

        def check_undo() -> tuple[SlotState, bool]:
            state = read_state(self.bridge, idx, len(expect_after.has_clip))
            name = target_name(state, idx)
            return state, (same_except_track_name(state, expect_after, idx)
                           and (name is None or name in outcome.import_names()))

        after, ok, polls = self._readback(outcome, label, "song.undo", {},
                                          lambda: self._poll(check_undo))
        outcome.after_undo = after
        outcome.undo_reads.append(after)
        self._log(action=label, capability="song.undo", status="read_back",
                  after=after.as_json(), expected=expect_after.as_json(), ok=ok, polls=polls)
        if not ok:
            outcome.steps[-1].detail = f"read-back differs: {after.as_json()}"
        return ok
