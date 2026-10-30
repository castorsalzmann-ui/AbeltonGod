"""Arrangement capability check (#140): writes, read-backs and the undo chain.

What one run does in the open Live set (``scripts/arrangement_check.py`` shows the plan and asks
first), following ``docs/research/2026-10-29_live-midi-arrangement-devices.md`` E1-E5:

0. moves the song position to the clip start (needed by step 4; skipped if already there);
1. creates a MIDI track at the end (``/live/song/create_midi_track -1``);
2. creates an empty MIDI clip **in the Arrangement** of that track at a bar position
   (``Track.create_midi_clip`` through the AbeltonGod extension);
3. writes notes into it (extension handler for Arrangement clips);
4. adds a locator at the clip start (``Song.set_or_delete_cue``, a toggle: it is sent only
   after a read-back shows no locator at that time and the song position at the clip start);
5. names the locator.

Every write follows the rules of :mod:`bridge.clip_import` (D-006): an action-log entry before
and after, a read-back that must show exactly the intended change (polled for a bounded
window), and an unknown outcome (Ctrl+C, read-back that never matched) stops the run and rules
out any undo. A write whose confirmation timed out is read back (more time per read, same
window); only a read-back showing exactly the intended change settles it (#140 run 1: Live had
created the track, the confirmation was late or lost). Undo timeouts are never settled.

Undo (only if the user asks right after the writes, with nothing done in Live in between,
#50 runs 2 and 3): one ``/live/song/undo`` at a time, each only after a read-back shows the set
exactly as this run last saw it. After each undo the set must read back as one of this run's
earlier states (which one is recorded: that is how many undo steps Live made of the writes,
research note E2). Any other result (no visible change, an unknown state) stops the chain.
Never more undos than confirmed writes of steps 1-5; step 0 is not undone (the song position
is reported, not restored).

What the read-backs see: all track names (the new track's name is not pinned, in case Live
renames it), whether the new track is a MIDI track, its Arrangement clips (start, length),
the notes of its first Arrangement clip, all locators (name, time) and the song position.
Blind spots: clips on other tracks, devices, automation, return/master tracks. Nothing here
deletes anything.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from bridge.clip_import import (
    READBACK_AFTER_TIMEOUT_FACTOR,
    READBACK_POLL_INTERVAL_S,
    READBACK_WINDOW_S,
    ActionLog,
    ImportAborted,
    ImportInterrupted,
    Step,
    poll_until,
)
from bridge.osc_client import (
    ARRANGEMENT_MAX_BEATS,
    MAX_NOTES_PER_MESSAGE,
    AbletonBridge,
    BridgeError,
    BridgeTimeoutError,
)

Note = tuple[int, float, float, float, bool]  # pitch, start, duration, velocity, mute

BEATS_PER_BAR = 4  # the script refuses any signature other than 4/4
TIME_TOLERANCE = 1e-6
NOTE_PITCH = 36  # C1, a kick on every beat: easy to see in Live
NOTE_DURATION = 0.25
NOTE_VELOCITY = 100
MAX_BARS = 16  # 4 notes per bar; one message holds MAX_NOTES_PER_MESSAGE notes

# Writes that the undo chain may revert, in order (step 0 is not one of them).
UNDOABLE = ("create_midi_track", "create_midi_clip", "add_notes", "add_cue", "set_cue_name")


def r6(value: float) -> float:
    """Values come back as OSC float32; rounding makes exact tuple comparison safe."""
    return round(float(value), 6)


def same_time(a: float, b: float) -> bool:
    return abs(a - b) <= TIME_TOLERANCE


# -- plan ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ArrangementPlan:
    bar: int  # 1-based bar of the clip start
    bars: int
    locator_name: str

    @property
    def start(self) -> float:
        return float((self.bar - 1) * BEATS_PER_BAR)

    @property
    def length(self) -> float:
        return float(self.bars * BEATS_PER_BAR)

    def notes(self) -> tuple[tuple[int, float, float, int, bool], ...]:
        """One note per beat, in clip time (0 = clip start)."""
        return tuple((NOTE_PITCH, float(b), NOTE_DURATION, NOTE_VELOCITY, False)
                     for b in range(int(self.length)))

    def expected_notes(self) -> tuple[Note, ...]:
        return tuple(sorted((p, r6(s), r6(d), r6(v), m) for p, s, d, v, m in self.notes()))


def make_plan(bar: int, bars: int, locator_name: str) -> ArrangementPlan:
    """Validated plan; raises ValueError with the reason."""
    if isinstance(bar, bool) or not isinstance(bar, int) or bar < 1:
        raise ValueError(f"bar must be an int >= 1 (got {bar!r})")
    if isinstance(bars, bool) or not isinstance(bars, int) or not 1 <= bars <= MAX_BARS:
        raise ValueError(f"bars must be an int in 1..{MAX_BARS} (got {bars!r})")
    if bars * BEATS_PER_BAR > MAX_NOTES_PER_MESSAGE:
        raise ValueError("too many notes for one message")
    if not isinstance(locator_name, str) or not locator_name.strip() or len(locator_name) > 64 \
            or not locator_name.isprintable():
        raise ValueError(f"locator name must be 1..64 printable characters (got "
                         f"{locator_name!r})")
    plan = ArrangementPlan(bar, bars, locator_name)
    if plan.start + plan.length > ARRANGEMENT_MAX_BEATS:
        raise ValueError(f"clip would end after beat {ARRANGEMENT_MAX_BEATS:g}")
    return plan


# -- state -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class ArrangementState:
    """What the check can see. ``target_index`` is where the new track is (or will be)."""

    track_names: tuple[str, ...]
    target_index: int
    target_is_midi: bool | None  # None: the target track does not exist
    clips: tuple[tuple[float, float], ...]  # (start, length) of the target's Arrangement clips
    notes: tuple[Note, ...] | None  # notes of the target's first Arrangement clip; None: none
    cues: tuple[tuple[str, float], ...]  # all locators, sorted
    song_time: float  # recorded, never part of key()

    def target_name(self) -> str | None:
        n = self.target_index
        return self.track_names[n] if n < len(self.track_names) else None

    def key(self) -> tuple:
        """Everything compared: all of the above except the target's name and the position."""
        names = tuple(None if i == self.target_index else n
                      for i, n in enumerate(self.track_names))
        return (len(self.track_names), names, self.target_is_midi, self.clips, self.notes,
                self.cues)

    def cue_at(self, beats: float) -> list[tuple[str, float]]:
        return [c for c in self.cues if same_time(c[1], beats)]

    def as_json(self) -> dict[str, Any]:
        return {"track_names": list(self.track_names), "target_index": self.target_index,
                "target_is_midi": self.target_is_midi,
                "clips": [list(c) for c in self.clips],
                "notes": None if self.notes is None else [list(n) for n in self.notes],
                "cues": [list(c) for c in self.cues], "song_time": self.song_time}


def read_arrangement_state(bridge: AbletonBridge, target_index: int,
                           timeout_s: float | None = None) -> ArrangementState:
    names = tuple(bridge.get_track_names(timeout_s=timeout_s))
    cues = tuple(sorted((n, r6(t)) for n, t in bridge.get_cue_points(timeout_s=timeout_s)))
    song_time = r6(bridge.get_song_time(timeout_s=timeout_s))
    if target_index >= len(names):
        return ArrangementState(names, target_index, None, (), None, cues, song_time)
    is_midi = bridge.get_track_has_midi_input(target_index, timeout_s=timeout_s)
    clips = tuple((r6(s), r6(n)) for s, n in
                  bridge.get_arrangement_clips(target_index, timeout_s=timeout_s))
    notes = None
    if clips:
        notes = tuple(sorted((p, r6(s), r6(d), r6(v), m) for p, s, d, v, m in
                             bridge.get_arrangement_clip_notes(target_index, 0,
                                                               timeout_s=timeout_s)))
    return ArrangementState(names, target_index, is_midi, clips, notes, cues, song_time)


# -- outcome ---------------------------------------------------------------------------------

@dataclass
class ArrangementOutcome:
    plan: ArrangementPlan
    target_index: int
    before: ArrangementState  # before any write
    snapshots: list[tuple[str, ArrangementState]] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    results: dict[str, str] = field(default_factory=dict)  # capability -> PASS / SKIPPED ...
    cue_default_name: str | None = None
    outcome_unknown: bool = False
    undos_sent: int = 0
    undo_chain: list[str] = field(default_factory=list)  # "undo_1: 'a' -> 'b'"
    undo_reads: list[ArrangementState] = field(default_factory=list)
    refused_now: ArrangementState | None = None
    done: bool = False

    @property
    def last(self) -> ArrangementState:
        return self.snapshots[-1][1] if self.snapshots else self.before

    def confirmed_undoable_writes(self) -> int:
        return sum(1 for s in self.steps if s.outcome == "confirmed" and s.label in UNDOABLE)

    def target_names_seen(self) -> frozenset[str]:
        return frozenset(n for _l, s in self.snapshots if (n := s.target_name()) is not None)

    def newest_state(self) -> ArrangementState:
        if self.refused_now is not None:
            return self.refused_now
        if self.undo_reads:
            return self.undo_reads[-1]
        return self.last


@dataclass
class UndoResult:
    passed: bool
    detail: str


# -- the writer ------------------------------------------------------------------------------

class ArrangementWriter:
    """Runs the five writes and, on request, the undo chain. The caller has shown the plan
    and got the user's yes. Raises :class:`ImportAborted` instead of guessing;
    ``last_outcome`` keeps what happened so far."""

    def __init__(self, bridge: AbletonBridge, log: ActionLog, *, timeout_s: float,
                 source: str = "scripts/arrangement_check.py",
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
        self.last_outcome: ArrangementOutcome | None = None

    # -- helpers ---------------------------------------------------------------------------

    def _log(self, **entry: Any) -> None:
        self.log.append({"source": self.source, **entry})

    def _read(self, outcome: ArrangementOutcome,
              timeout_s: float | None = None) -> ArrangementState:
        return read_arrangement_state(self.bridge, outcome.target_index, timeout_s=timeout_s)

    def _unknown(self, outcome: ArrangementOutcome, label: str, capability: str, params: dict,
                 status: str, note: str) -> str:
        """Mark the outcome unknown, read back once with more time, log it."""
        outcome.outcome_unknown = True
        try:
            readback: Any = self._read(
                outcome, timeout_s=self.timeout_s * READBACK_AFTER_TIMEOUT_FACTOR).as_json()
        except (BridgeError, KeyboardInterrupt) as exc:
            readback = f"read-back failed: {type(exc).__name__}"
        self._log(action=label, capability=capability, params=params, status=status,
                  readback=readback, note=f"{note}; outcome unknown; no undo will be sent")
        return json.dumps(readback, ensure_ascii=False)

    def _send(self, outcome: ArrangementOutcome, label: str, capability: str, params: dict,
              before: ArrangementState, send: Callable[[], None],
              resolve_timeout: bool = False) -> BridgeTimeoutError | None:
        """Log the plan, send, record the outcome. Raises ImportAborted on any failure.

        With ``resolve_timeout`` a timeout is returned (step recorded as ``timeout``) for the
        caller to settle by read-back; otherwise it is an unknown outcome at once."""
        self._log(action=label, capability=capability, params=params, status="planned",
                  before=before.as_json())
        try:
            send()
        except BridgeTimeoutError as exc:
            outcome.steps.append(Step(label, "timeout", "outcome unknown"))
            if resolve_timeout:
                return exc
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
        return None

    def _resolve_timeout(self, outcome: ArrangementOutcome, label: str, capability: str,
                         params: dict, exc: BridgeTimeoutError,
                         expect: Callable[[ArrangementState], bool]) -> ArrangementState:
        """Settle a timed-out forward write by read-back (#140 run 1), or stop as unknown.

        Every read-back is bracketed like any request, and AbletonOSC processes datagrams in
        arrival order (research note 2026-10-28, fact 7; loopback keeps the order). So a read
        that is answered at all was processed after the write: the write is applied by then,
        or its datagram never reached Live. A read that shows exactly the intended change
        (the same ``expect`` as after a confirmed write) therefore settles the outcome. A late
        ``/live/error`` of the write, a read that fails or never matches in the window: the
        outcome stays unknown, the run stops, no undo. Reads get more time than the write
        (``READBACK_AFTER_TIMEOUT_FACTOR``), since Live may still be busy.
        """
        long_s = self.timeout_s * READBACK_AFTER_TIMEOUT_FACTOR

        def check() -> tuple[ArrangementState, bool]:
            state = self._read(outcome, timeout_s=long_s)
            return state, expect(state)

        def stop(readback: Any, note: str) -> None:
            outcome.outcome_unknown = True
            self._log(action=label, capability=capability, params=params, status="timeout",
                      readback=readback, late_reply=late_json(),
                      note=f"timed out; {note}; outcome unknown; no undo will be sent")

        def late_json() -> dict[str, Any] | None:
            late = self.bridge.late_reply(exc.request_id)
            return None if late is None else {
                "start_seen": late.start_seen, "end_seen": late.end_seen,
                "errors": list(late.errors), "end_after_s": late.end_after_s}

        try:
            state, ok, polls = poll_until(check, self.readback_window_s, self.poll_interval_s,
                                          self._clock, self._sleep)
        except KeyboardInterrupt as err:
            outcome.steps[-1] = Step(label, "interrupted", "outcome unknown")
            stop("read-back interrupted", "Ctrl+C during the read-back after the timeout")
            raise ImportInterrupted(f"{label} timed out, read-back interrupted") from err
        except BridgeError as err:
            stop(f"read-back failed: {type(err).__name__}", "read-back after the timeout failed")
            raise ImportAborted(f"{label} timed out; outcome unknown; read-back failed: "
                                f"{type(err).__name__}: {err}") from err
        late = late_json()
        if late is not None and late["errors"]:
            outcome.results[capability] = "FAIL (AbletonOSC error after the timeout)"
            outcome.steps[-1].detail = f"outcome unknown; late /live/error: {late['errors'][0]}"
            stop(state.as_json(), f"late /live/error: {late['errors'][0]}")
            raise ImportAborted(f"{label} timed out, then AbletonOSC reported an error: "
                                f"{late['errors'][0]}; outcome unknown") from exc
        if not ok:
            stop(state.as_json(), f"read-back after {polls} read(s) does not show the change")
            raise ImportAborted(f"{label} timed out; outcome unknown; read-back "
                                f"{json.dumps(state.as_json(), ensure_ascii=False)}") from exc
        if late is None or not late["end_seen"]:
            echo = "end echo not seen"
        else:
            echo = f"end echo after {late['end_after_s']:.2f} s"
        detail = (f"late: no confirmation within {self.timeout_s:g} s; read-back matched "
                  f"({polls} read(s)); {echo}")
        outcome.steps[-1] = Step(label, "confirmed", detail)
        self._log(action=label, capability=capability, params=params, status="read_back",
                  after=state.as_json(), ok=True, polls=polls, late_reply=late,
                  note="confirmation timed out; settled by read-back")
        outcome.results[capability] = "PASS (late: read-back after timeout)"
        outcome.snapshots.append((f"after {label}", state))
        return state

    def _poll_readback(self, outcome: ArrangementOutcome, label: str, capability: str,
                       params: dict, check: Callable[[], tuple[Any, bool]]
                       ) -> tuple[Any, bool, int]:
        """Poll a read-back right after a confirmed write; failure makes the outcome unknown."""
        try:
            return poll_until(check, self.readback_window_s, self.poll_interval_s,
                              self._clock, self._sleep)
        except KeyboardInterrupt as exc:
            self._unknown(outcome, label, capability, params, "interrupted",
                          "Ctrl+C during read-back")
            raise ImportInterrupted(f"{label}: read-back interrupted") from exc
        except BridgeError as exc:
            self._unknown(outcome, label, capability, params, "readback_failed",
                          f"read-back failed: {type(exc).__name__}")
            raise ImportAborted(f"{label}: read-back failed: {type(exc).__name__}: {exc}"
                                ) from exc

    def _write(self, outcome: ArrangementOutcome, label: str, capability: str, params: dict,
               send: Callable[[], None],
               expect: Callable[[ArrangementState], bool]) -> ArrangementState:
        """Send one write and poll until ``expect`` holds for the read-back. A timed-out send
        is settled by :meth:`_resolve_timeout` (same ``expect``) or stops as unknown."""
        before = outcome.last
        timed_out = self._send(outcome, label, capability, params, before, send,
                               resolve_timeout=True)
        if timed_out is not None:
            return self._resolve_timeout(outcome, label, capability, params, timed_out, expect)

        def check() -> tuple[ArrangementState, bool]:
            state = self._read(outcome)
            return state, expect(state)

        state, ok, polls = self._poll_readback(outcome, label, capability, params, check)
        self._log(action=label, capability=capability, params=params, status="read_back",
                  after=state.as_json(), ok=ok, polls=polls)
        if not ok:
            # Confirmed but never seen as intended: what Live did is unknown (no undo).
            outcome.outcome_unknown = True
            outcome.results[capability] = "FAIL (read-back differs)"
            outcome.steps[-1].detail = f"read-back differs after {polls} read(s)"
            raise ImportAborted(
                f"{label}: read-back after {polls} read(s) in {self.readback_window_s:g} s does "
                f"not show the intended change (read="
                f"{json.dumps(state.as_json(), ensure_ascii=False)})")
        outcome.results[capability] = "PASS"
        outcome.snapshots.append((f"after {label}", state))
        return state

    # -- the run ---------------------------------------------------------------------------

    def run(self, plan: ArrangementPlan, expected_before: ArrangementState) -> ArrangementOutcome:
        """The writes of steps 0-5. ``expected_before`` is the state the plan was shown with;
        if the set reads back differently now, nothing is sent."""
        self.last_outcome = None
        target = len(expected_before.track_names)
        before = read_arrangement_state(self.bridge, target)
        if before.key() != expected_before.key():
            raise ImportAborted("the set changed between the plan and the confirmation; "
                                "nothing sent")
        if self.bridge.get_is_playing():
            raise ImportAborted("Live is playing; the locator would land at a moving position; "
                                "nothing sent")
        if before.cue_at(plan.start):
            raise ImportAborted(f"a locator exists at beat {plan.start:g}; the toggle would "
                                "delete it; nothing sent")
        outcome = ArrangementOutcome(plan=plan, target_index=target, before=before)
        self.last_outcome = outcome
        start, length = plan.start, plan.length

        # 0. song position (not part of the undo chain)
        if same_time(before.song_time, start):
            outcome.results["song.current_song_time.set"] = "SKIPPED (already at the clip start)"
            outcome.snapshots.append(("before", before))
        else:
            state = self._write(
                outcome, "set_song_time", "song.current_song_time.set", {"beats": start},
                lambda: self.bridge.set_song_time(start),
                lambda s: s.key() == before.key() and same_time(s.song_time, start))
            outcome.snapshots[-1] = ("before", state)  # the undo chain ends here

        # 1. MIDI track at the end
        s0 = outcome.last
        self._write(
            outcome, "create_midi_track", "song.create_midi_track", {"index": -1},
            lambda: self.bridge.create_midi_track(-1),
            lambda s: (len(s.track_names) == len(s0.track_names) + 1
                       and s.track_names[:-1] == s0.track_names and s.target_is_midi is True
                       and s.clips == () and s.notes is None and s.cues == s0.cues))

        # 2. empty MIDI clip in the Arrangement
        s1 = outcome.last
        self._write(
            outcome, "create_midi_clip", "track.create_midi_clip",
            {"track_index": target, "start": start, "length": length},
            lambda: self.bridge.create_arrangement_midi_clip(target, start, length),
            lambda s: s.key() == replace(s1, clips=((r6(start), r6(length)),),
                                         notes=()).key())

        # 3. notes
        s2 = outcome.last
        notes = plan.notes()
        self._write(
            outcome, "add_notes", "arrangement_clip.notes.add",
            {"track_index": target, "clip_index": 0, "notes": [list(n) for n in notes]},
            lambda: self.bridge.add_arrangement_clip_notes(target, 0, notes),
            lambda s: s.key() == replace(s2, notes=plan.expected_notes()).key())

        # 4. locator (a toggle): only with no locator at the start and the position there
        s3 = outcome.last
        if s3.cue_at(start) or not same_time(s3.song_time, start):
            outcome.steps.append(Step("add_cue", "refused", "locator or position changed"))
            self._log(action="add_cue", capability="song.cue_point.add_or_delete",
                      status="refused", now=s3.as_json(),
                      reason="a locator exists at the clip start or the song position moved")
            raise ImportAborted("before the locator: a locator exists at the clip start or the "
                                "song position is not there any more; nothing sent")

        def new_cue(s: ArrangementState) -> list[tuple[str, float]]:
            rest = list(s.cues)
            for cue in s3.cues:
                if cue not in rest:
                    return []
                rest.remove(cue)
            return rest

        def cue_added(s: ArrangementState) -> bool:
            added = new_cue(s)
            return (len(added) == 1 and same_time(added[0][1], start)
                    and s.key() == replace(s3, cues=s.cues).key())

        s4 = self._write(outcome, "add_cue", "song.cue_point.add_or_delete", {"beats": start},
                         self.bridge.toggle_cue_at_song_time, cue_added)
        default_name = new_cue(s4)[0][0]
        outcome.cue_default_name = default_name

        # 5. name the locator
        if default_name == plan.locator_name:
            outcome.results["song.cue_point.set_name"] = "SKIPPED (Live's name is the same)"
        else:
            try:  # Live's own order: set_name takes an index into it
                live_order = self.bridge.get_cue_points()
            except BridgeError as exc:
                raise ImportAborted(f"reading the locators before naming failed: "
                                    f"{type(exc).__name__}: {exc}; name not sent") from exc
            at_start = [i for i, (_n, t) in enumerate(live_order) if same_time(r6(t), start)]
            if len(at_start) != 1:
                outcome.steps.append(Step("set_cue_name", "refused", "locator not found once"))
                self._log(action="set_cue_name", capability="song.cue_point.set_name",
                          status="refused", cues=[list(c) for c in live_order],
                          reason="not exactly one locator at the clip start")
                raise ImportAborted("the new locator is not found exactly once; name not sent")
            index = at_start[0]
            expected_cues = tuple(sorted(
                [c for c in s4.cues if c != (default_name, r6(start))]
                + [(plan.locator_name, r6(start))]))
            self._write(outcome, "set_cue_name", "song.cue_point.set_name",
                        {"cue_index": index, "name": plan.locator_name},
                        lambda: self.bridge.set_cue_name(index, plan.locator_name),
                        lambda s: s.key() == replace(s4, cues=expected_cues).key())
        outcome.done = True
        return outcome

    # -- undo ------------------------------------------------------------------------------

    def _match_earlier(self, outcome: ArrangementOutcome, state: ArrangementState,
                       k: int) -> int | None:
        """Newest snapshot j < k that ``state`` equals (target name: one this run saw)."""
        name = state.target_name()
        if name is not None and name not in outcome.target_names_seen():
            return None
        for j in range(k - 1, -1, -1):
            if state.key() == outcome.snapshots[j][1].key():
                return j
        return None

    def undo_all(self, outcome: ArrangementOutcome) -> UndoResult:
        """Undo the writes, one ``/live/song/undo`` at a time, each read back.

        Raises :class:`ImportAborted` if undo is not allowed, if the read-back before an undo
        differs (nothing sent then), or on a bridge error.
        """
        if outcome.outcome_unknown:
            raise ImportAborted("a write has an unknown outcome; undo is never sent then")
        if not outcome.done:
            raise ImportAborted("the writes did not all finish; undo is only offered after a "
                                "complete run")
        k = len(outcome.snapshots) - 1
        last_name = outcome.snapshots[k][1].target_name()
        limit = outcome.confirmed_undoable_writes()
        while k > 0:
            if outcome.undos_sent >= limit:
                return UndoResult(False, f"{outcome.undos_sent} undos sent (one per write) but "
                                         f"the set is at '{outcome.snapshots[k][0]}', not "
                                         "'before'")
            label = f"undo_{outcome.undos_sent + 1}"
            expected = outcome.snapshots[k][1]
            now = self._read(outcome)
            if now.key() != expected.key() or now.target_name() != last_name:
                self._log(action=label, capability="song.undo", status="refused",
                          reason="read-back before undo differs from the expected state",
                          now=now.as_json(), expected=expected.as_json(),
                          expected_target_name=last_name)
                outcome.refused_now = now
                outcome.steps.append(Step(label, "refused", "set changed since the last read"))
                raise ImportAborted("the set is not as this run left it; undo NOT sent")
            self._send(outcome, label, "song.undo", {}, now, self.bridge.undo)
            outcome.undos_sent += 1
            def check(k_now: int = k) -> tuple[tuple[ArrangementState, int | None], bool]:
                state = self._read(outcome)
                j = self._match_earlier(outcome, state, k_now)
                return (state, j), j is not None

            (state, j), ok, polls = self._poll_readback(outcome, label, "song.undo", {}, check)
            outcome.undo_reads.append(state)
            from_label = outcome.snapshots[k][0]
            to_label = outcome.snapshots[j][0] if j is not None else None
            self._log(action=label, capability="song.undo", status="read_back",
                      after=state.as_json(), ok=ok, polls=polls,
                      reverted_from=from_label, reached=to_label)
            if not ok:
                what = ("no visible change" if state.key() == expected.key()
                        else "a state this run never had")
                outcome.steps[-1].detail = f"read-back shows {what}"
                outcome.undo_chain.append(f"{label}: '{from_label}' -> {what}")
                return UndoResult(False, f"after {label} the set shows {what} (polled {polls}x); "
                                         "no further undo sent")
            assert j is not None
            outcome.undo_chain.append(f"{label}: '{from_label}' -> '{to_label}'")
            k, last_name = j, state.target_name()
        # k == 0: the read-back equals 'before' in key(), and 'before' has no target track,
        # so every track name, the track count and every locator (name and time) are back.
        return UndoResult(True, f"{outcome.undos_sent} undo(s) for "
                                f"{outcome.confirmed_undoable_writes()} write(s); read back")
