"""Agent Resource Guard (D-011): the one entry point for every product Claude call and every
model-callable tool.

Usage (Phase 04b)::

    guard = Guard()                                   # once per session
    with guard.request("kick_generation") as req:
        req.add_open("3 kick variants")
        permit = req.before_model_call(estimated_cost_usd=0.02)
        ...  # call the model with max_tokens=permit.max_output_tokens, timeout=req.remaining_s()
        req.after_model_call(permit, ModelUsage(output_tokens=..., cost_usd=...))
        tool = req.before_tool("generate_kick", args, writes_files=6)
        ...  # run the tool
        req.after_tool(tool, files_written=6, label="3 kick variants")
        req.mark_done("3 kick variants")
        result = req.finish("Drei Kicks erzeugt.")

Levels: ``ok``; ``warn`` once any limit reaches ``warn_at_fraction`` (the orchestrator then starts
no new sub-tasks and keeps answers short); ``stop`` when a step would exceed a limit or a limit
was exceeded. A stop raises ``GuardStop`` and is sticky: every later step of that request raises
it again, and ``finish`` can never return a success result for it.

Reaching a count limit exactly is allowed (the 8th of 8 model calls runs); the next attempt stops.
Money and timeout limits stop as soon as they are exceeded, even by a call that already ran.
"""

from __future__ import annotations

import itertools
import math
import numbers
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from guard.budget import EPS, BudgetBook, Counter, SessionLedger, is_valid_amount
from guard.loop import LoopDetector, call_key
from guard.policy import Policy, Profile, load_policy
from guard.usage_log import DEFAULT_LOG_FILE, UsageLog, UsageLogError


class Level(StrEnum):
    OK = "ok"
    WARN = "warn"
    STOP = "stop"


class Limit(StrEnum):
    """Names match the policy fields, so a stop reason points straight at the setting."""

    MODEL_CALLS = "max_model_calls"
    TOOL_CALLS = "max_tool_calls"
    OUTPUT_TOKENS = "max_output_tokens"
    REQUEST_BUDGET = "max_budget_usd"
    SESSION_BUDGET = "session_budget_usd"
    DAILY_BUDGET = "daily_budget_usd"
    TIMEOUT = "timeout_s"
    LOOP = "max_identical_tool_calls"
    FILES = "max_files_written"
    LIVE_WRITES = "max_live_writes"
    CONCURRENCY = "max_concurrent_requests"
    USAGE_LOG = "usage_log"
    UNREADABLE_USAGE = "unreadable_usage"
    UNDECLARED_WRITE = "undeclared_write"  # a tool did more than it declared (orchestrator)


_REASON_DE = {
    Limit.MODEL_CALLS: "zu viele Modellaufrufe für diese Anfrage",
    Limit.TOOL_CALLS: "zu viele Werkzeugaufrufe für diese Anfrage",
    Limit.OUTPUT_TOKENS: "eine Modellantwort war länger als erlaubt",
    Limit.REQUEST_BUDGET: "das Kostenlimit dieser Anfrage ist erreicht",
    Limit.SESSION_BUDGET: "das Kostenlimit dieser Sitzung ist erreicht",
    Limit.DAILY_BUDGET: "das Tageslimit für Kosten ist erreicht",
    Limit.TIMEOUT: "die Anfrage hat zu lange gedauert",
    Limit.LOOP: "dasselbe Werkzeug wurde wiederholt mit denselben Werten aufgerufen (Schleife)",
    Limit.FILES: "zu viele Dateien für diese Anfrage",
    Limit.LIVE_WRITES: "zu viele Änderungen am Ableton-Set für diese Anfrage",
    Limit.CONCURRENCY: "es läuft schon eine andere Anfrage",
    Limit.USAGE_LOG: "das Nutzungsprotokoll konnte nicht geschrieben werden",
    Limit.UNREADABLE_USAGE: "die gemeldete Nutzung eines Aufrufs war nicht lesbar",
    Limit.UNDECLARED_WRITE: "ein Werkzeug hat mehr geschrieben, als es angekündigt hatte",
}


def warning_message_de(reasons: list[Limit]) -> str:
    """Short German note for the user while a request is at ``warn``."""
    if not reasons:
        return ""
    names = ", ".join(r.value for r in reasons)
    return f"Hinweis: Diese Anfrage nähert sich ihren Grenzen ({names}). Ich fasse mich kurz."


class GuardStop(Exception):
    """A request was stopped. Carries what was finished and what is still open."""

    def __init__(
        self,
        reason: Limit,
        detail: str,
        *,
        profile: str,
        request_id: str,
        done: tuple[str, ...] = (),
        open_items: tuple[str, ...] = (),
        usage: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"Guard stop ({reason.value}): {detail}")
        self.reason = reason
        self.detail = detail
        self.profile = profile
        self.request_id = request_id
        self.done = done
        self.open = open_items
        self.usage = usage or {}

    @property
    def user_message_de(self) -> str:
        done = ", ".join(self.done) if self.done else "nichts"
        still_open = ", ".join(self.open) if self.open else "nichts"
        return f"Abgebrochen: {_REASON_DE[self.reason]}. Fertig: {done}. Offen: {still_open}."

    @property
    def result(self) -> RequestResult:
        return RequestResult(
            success=False,
            profile=self.profile,
            request_id=self.request_id,
            done=self.done,
            open=self.open,
            stop_reason=self.reason,
            summary=self.user_message_de,
            usage=self.usage,
        )


@dataclass(frozen=True)
class RequestResult:
    success: bool
    profile: str
    request_id: str
    done: tuple[str, ...]
    open: tuple[str, ...]
    stop_reason: Limit | None
    summary: str | None
    usage: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.success and (self.stop_reason is not None or self.open):
            raise ValueError("A stopped or unfinished request cannot be a success.")
        if not self.success and self.stop_reason is None:
            raise ValueError("A failed result must name its stop reason.")


@dataclass(frozen=True)
class ModelUsage:
    """Actual usage reported after a model call. ``None`` = unknown (counted conservatively)."""

    output_tokens: int | None = None
    input_tokens: int | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class ModelCallPermit:
    id: int
    request_id: str
    max_output_tokens: int  # pass to the SDK/API as max_tokens
    reserved_cost_usd: float
    level: Level
    # Limits for an SDK that enforces its own (D-011), taken in the same locked step and from
    # the same day's counter as this reservation, *including* this call: max_turns >= 1 and
    # max_budget_usd > 0 whenever a permit is issued. Use these, not a separate sdk_limits()
    # read, which can see another day across local midnight (review of PR #89). No default:
    # a permit without limits is a construction error, never an empty dict.
    sdk_limits: dict[str, Any]


@dataclass(frozen=True)
class ToolPermit:
    id: int
    request_id: str
    name: str
    level: Level


@dataclass
class _ModelReservation:
    max_output_tokens: int
    cost: float
    daily: Counter
    date: str  # the day the call was reserved on; its cost is logged on this day


@dataclass
class _ToolReservation:
    name: str
    files: int
    live: int


def _valid_count(value: object) -> bool:
    """Strict check for values the orchestrator passes in (plain int >= 0)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _as_count(value: object) -> int | None:
    """Reported count as int: 3, 3.0 and NumPy ints are accepted; anything else is None."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    if isinstance(value, numbers.Integral):
        number = int(value)
    else:
        f = float(value)
        if not (math.isfinite(f) and f.is_integer()):
            return None
        number = int(f)
    return number if number >= 0 else None


def _as_amount(value: object) -> float | None:
    """Reported USD amount as float (finite, >= 0); anything else is None."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    f = float(value)
    return f if math.isfinite(f) and f >= 0 else None


class Guard:
    """One per user session. Holds session/daily totals and the concurrency slots."""

    def __init__(
        self,
        policy: Policy | None = None,
        *,
        log_path: Path | str = DEFAULT_LOG_FILE,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.policy = policy if policy is not None else load_policy()
        self.session_id = uuid.uuid4().hex[:12]
        self._clock = clock
        self._now = now or (lambda: datetime.now().astimezone())
        self._log = UsageLog(log_path)
        self._book = BudgetBook()
        g = self.policy.global_limits
        today = self._today()
        self._ledger = SessionLedger(
            g.session_budget_usd, g.daily_budget_usd, today, self._log.counted_cost_on(today)
        )
        self._active = 0
        self._ids = itertools.count(1)

    def _today(self) -> str:
        return self._now().date().isoformat()

    def _refresh_daily(self, date: str) -> Counter:
        """Daily counter for ``date``, raised to what the log shows. Other Guard instances or
        processes sharing the log become visible once their calls are settled (call with the
        lock held; raises UsageLogError if the log cannot be read)."""
        counter = self._ledger.daily(date)
        counter.used = max(counter.used, self._log.counted_cost_on(date))
        return counter

    def request(self, profile_name: str) -> GuardedRequest:
        """Create a request for ``profile_name``. Unknown profiles raise ``UnknownProfileError``.
        Use it as a context manager; entering takes a concurrency slot."""
        profile = self.policy.profile(profile_name)
        return GuardedRequest(self, profile, f"{self.session_id}-{next(self._ids)}")

    @property
    def session_spent_usd(self) -> float:
        with self._book.lock:
            return self._ledger.session.used

    @property
    def daily_spent_usd(self) -> float:
        with self._book.lock:
            return self._ledger.daily(self._today()).used


class GuardedRequest:
    def __init__(self, guard: Guard, profile: Profile, request_id: str) -> None:
        self._g = guard
        self.profile = profile
        self.request_id = request_id
        p = profile
        self._model_calls = Counter(Limit.MODEL_CALLS.value, p.max_model_calls)
        self._tool_calls = Counter(Limit.TOOL_CALLS.value, p.max_tool_calls)
        self._files = Counter(Limit.FILES.value, p.max_files_written)
        self._live = Counter(Limit.LIVE_WRITES.value, p.max_live_writes)
        self._cost = Counter(Limit.REQUEST_BUDGET.value, p.max_budget_usd)
        self._loop = LoopDetector(p.max_identical_tool_calls)
        self._ids = itertools.count(1)
        self._models: dict[int, _ModelReservation] = {}
        self._tools: dict[int, _ToolReservation] = {}
        self._done: list[str] = []
        self._open: list[str] = []
        self._output_tokens_total = 0
        self._max_call_tokens = 0
        self._stopped: GuardStop | None = None
        self._state = "new"  # new -> running -> finished/closed
        self._start = 0.0
        self.log_errors: list[str] = []  # log failures that could not be raised (on exit)

    # ----- context manager ------------------------------------------------------------------

    def __enter__(self) -> GuardedRequest:
        if self._state != "new":
            raise RuntimeError("A guarded request can be entered only once.")
        g = self._g
        with g._book.lock:
            if g._active >= g.policy.global_limits.max_concurrent_requests:
                stop = self._make_stop(
                    Limit.CONCURRENCY,
                    f"{g._active} request(s) already running, "
                    f"limit {g.policy.global_limits.max_concurrent_requests}",
                )
                self._stopped = stop
                self._state = "closed"  # never entered, so __exit__ will not run
                self._write_log(
                    {"kind": "stop", "stop_reason": stop.reason.value, "detail": stop.detail},
                    fatal=False,
                )
                raise stop
            g._active += 1
        self._state = "running"
        self._start = g._clock()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self._state == "closed":
            return False
        # Nothing in here may hide the original exception or leak the concurrency slot.
        with self._g._book.lock:
            try:
                for pid in list(self._models):
                    self._settle_model(pid, None, log_errors_fatal=False)
                for pid in list(self._tools):
                    self._settle_tool(
                        pid, None, None, ok=False, label=None, log_errors_fatal=False
                    )
            except Exception as err:  # noqa: BLE001 - recorded, never raised from __exit__
                self.log_errors.append(f"settling on exit failed: {err!r}")
            finally:
                outcome = (
                    "stopped" if self._stopped is not None
                    else "error" if exc_type is not None
                    else "success" if self._state == "finished"
                    else "abandoned"
                )
                self._state = "closed"
                self._g._active -= 1
        self._write_log(
            {"kind": "request_end", "outcome": outcome, **self._usage()}, fatal=False
        )
        return False

    # ----- public state ---------------------------------------------------------------------

    @property
    def level(self) -> Level:
        with self._g._book.lock:
            if self._stopped is not None:
                return Level.STOP
            return Level.WARN if self._warn_reasons() else Level.OK

    @property
    def warnings(self) -> list[Limit]:
        with self._g._book.lock:
            return self._warn_reasons()

    @property
    def done(self) -> tuple[str, ...]:
        return tuple(self._done)

    @property
    def open(self) -> tuple[str, ...]:
        return tuple(self._open)

    def elapsed_s(self) -> float:
        return self._g._clock() - self._start if self._state != "new" else 0.0

    def remaining_s(self) -> float:
        """Seconds left before the timeout. Pass this as the timeout of the model/tool call."""
        return max(0.0, self.profile.timeout_s - self.elapsed_s())

    def sdk_limits(self) -> dict[str, Any]:
        """Limits right now, for display. For a model call use ``permit.sdk_limits`` from
        ``before_model_call``: this separate read can see the old day's budget across local
        midnight while the reservation already uses the new day's (review of PR #89)."""
        with self._g._book.lock:
            daily = self._g._ledger.daily(self._g._today())
            budget = min(self._cost.headroom, self._g._ledger.session.headroom, daily.headroom)
            return {
                "max_turns": max(0, int(self._model_calls.headroom)),
                "max_budget_usd": max(0.0, budget),
            }

    def add_open(self, item: str) -> None:
        with self._g._book.lock:
            self._require_running()
            if item not in self._open:
                self._open.append(item)

    def mark_done(self, item: str) -> None:
        with self._g._book.lock:
            self._require_running()
            if item in self._open:
                self._open.remove(item)
            if item not in self._done:
                self._done.append(item)

    # ----- model calls ----------------------------------------------------------------------

    def before_model_call(
        self, *, estimated_cost_usd: float | None = None, max_output_tokens: int | None = None
    ) -> ModelCallPermit:
        """Reserve one model call. ``estimated_cost_usd=None`` reserves all money still
        available (the most conservative estimate)."""
        p = self.profile
        if max_output_tokens is None:
            max_output_tokens = p.max_output_tokens
        if not _valid_count(max_output_tokens) or max_output_tokens == 0:
            raise ValueError(f"max_output_tokens must be a positive int, got {max_output_tokens!r}")
        if max_output_tokens > p.max_output_tokens:
            raise ValueError(
                f"max_output_tokens {max_output_tokens} is above the profile limit "
                f"{p.max_output_tokens}; the orchestrator must not ask for more."
            )
        if estimated_cost_usd is not None and not is_valid_amount(estimated_cost_usd):
            raise ValueError(
                f"estimated_cost_usd must be finite and >= 0, got {estimated_cost_usd!r}"
            )
        g = self._g
        with g._book.lock:
            self._require_running()
            self._check_timeout(open_item="Modellaufruf")
            today = g._today()
            try:
                daily = g._refresh_daily(today)
            except UsageLogError as exc:
                self._stop(Limit.USAGE_LOG, str(exc), open_item="Modellaufruf")
            money = (self._cost, g._ledger.session, daily)
            money_left = max(0.0, min(c.headroom for c in money))
            sdk_limits = {
                "max_turns": max(0, int(self._model_calls.headroom)),
                "max_budget_usd": money_left,
            }
            est = money_left if estimated_cost_usd is None else float(estimated_cost_usd)
            violation = g._book.reserve_all(
                [(self._model_calls, 1, False)] + [(c, est, True) for c in money]
            )
            if violation is not None:
                self._stop(
                    Limit(violation.counter.name),
                    f"needs {violation.requested:g}, {violation.counter.name} has "
                    f"{max(0.0, violation.counter.headroom):g} of {violation.counter.limit:g} left",
                    open_item="Modellaufruf",
                )
            # A started call counts at once; only money is settled later.
            g._book.settle(self._model_calls, 1, 1)
            pid = next(self._ids)
            self._models[pid] = _ModelReservation(max_output_tokens, est, daily, today)
            return ModelCallPermit(
                pid, self.request_id, max_output_tokens, est, self._level_unlocked(), sdk_limits
            )

    def after_model_call(self, permit: ModelCallPermit, usage: ModelUsage | None) -> Level:
        """Settle a model call with its actual usage. Raises ``GuardStop`` if a limit was
        exceeded by it, or if the request was already stopped."""
        with self._g._book.lock:
            self._require_open_permits()
            if getattr(permit, "request_id", None) != self.request_id:
                raise ValueError("This model permit belongs to another request.")
            if permit.id not in self._models:
                raise ValueError(f"Unknown or already settled model permit {permit.id}.")
            self._settle_model(permit.id, usage, log_errors_fatal=True)
            self._raise_if_stopped()
            self._check_timeout(open_item=None)
            return self._level_unlocked()

    # ----- tool calls -----------------------------------------------------------------------

    def before_tool(
        self, name: str, args: Any, *, writes_files: int = 0, live_writes: int = 0
    ) -> ToolPermit:
        """Reserve one tool call. ``writes_files``/``live_writes`` are the most the tool may do."""
        if not isinstance(name, str) or not name:
            raise ValueError("Tool name must be a non-empty string.")
        for label, value in (("writes_files", writes_files), ("live_writes", live_writes)):
            if not _valid_count(value):
                raise ValueError(f"{label} must be an int >= 0, got {value!r}")
        with self._g._book.lock:
            self._require_running()
            item = f"Werkzeug {name}"
            self._check_timeout(open_item=item)
            key = call_key(name, args)
            repeat = self._loop.count_if_called(key)
            if not self._tool_calls.fits(1):
                self._stop(Limit.TOOL_CALLS, f"limit {self.profile.max_tool_calls}", open_item=item)
            if repeat > self.profile.max_identical_tool_calls:
                self._stop(
                    Limit.LOOP,
                    f"{name} with the same arguments would run {repeat} times, "
                    f"limit {self.profile.max_identical_tool_calls}",
                    open_item=item,
                )
            violation = self._g._book.reserve_all(
                [(self._files, writes_files, False), (self._live, live_writes, False)]
            )
            if violation is not None:
                self._stop(
                    Limit(violation.counter.name),
                    f"{name} needs {violation.requested:g}, "
                    f"{max(0, violation.counter.headroom):g} of {violation.counter.limit:g} left",
                    open_item=item,
                )
            self._tool_calls.used += 1
            self._loop.record(key)
            pid = next(self._ids)
            self._tools[pid] = _ToolReservation(name, writes_files, live_writes)
            return ToolPermit(pid, self.request_id, name, self._level_unlocked())

    def after_tool(
        self,
        permit: ToolPermit,
        *,
        files_written: int | None = None,
        live_writes: int | None = None,
        ok: bool = True,
        label: str | None = None,
    ) -> Level:
        """Settle a tool call. Missing counts use the reserved amount. A failed tool (``ok=False``)
        is listed as open, not done."""
        if not isinstance(ok, bool):
            raise TypeError(f"ok must be a bool, got {ok!r}")
        with self._g._book.lock:
            self._require_open_permits()
            if getattr(permit, "request_id", None) != self.request_id:
                raise ValueError("This tool permit belongs to another request.")
            if permit.id not in self._tools:
                raise ValueError(f"Unknown or already settled tool permit {permit.id}.")
            self._settle_tool(
                permit.id, files_written, live_writes, ok=ok, label=label, log_errors_fatal=True
            )
            self._raise_if_stopped()
            self._check_timeout(open_item=None)
            return self._level_unlocked()

    def files_left(self) -> int:
        """Files this request may still write (``max_files_written`` minus reserved and
        written). Lets a tool refuse a too-large call with a reason instead of a stop."""
        with self._g._book.lock:
            return max(0, int(self._files.headroom))

    def check_deadline(self, open_item: str | None = None) -> None:
        """Raise ``GuardStop`` (``timeout_s``) if the request's time is up, or if it was
        stopped already. For a step that waited outside the guard after its permit, e.g. a
        user confirmation (#81: re-check the deadline after the user said yes)."""
        with self._g._book.lock:
            self._require_open_permits()
            self._raise_if_stopped()
            self._check_timeout(open_item=open_item)

    def stop_request(self, reason: Limit, detail: str) -> None:
        """Stop this request for a reason found outside the guard (e.g. a tool broke its own
        declaration). Sticky like every stop; always raises ``GuardStop``."""
        if not isinstance(reason, Limit):
            raise TypeError(f"reason must be a Limit, got {reason!r}")
        with self._g._book.lock:
            self._require_open_permits()
            self._stop(reason, str(detail))

    # ----- finishing ------------------------------------------------------------------------

    def finish(self, summary: str | None = None) -> RequestResult:
        """Return the success result. Raises ``GuardStop`` if the request was stopped (or times
        out now), and ``ValueError`` while calls are unsettled or items are still open."""
        with self._g._book.lock:
            self._require_running()
            self._check_timeout(open_item=None)
            if self._models or self._tools:
                raise ValueError("Settle every model and tool call before finishing.")
            if self._open:
                raise ValueError(f"Still open: {', '.join(self._open)}. Mark them done first.")
            self._state = "finished"
            return RequestResult(
                success=True,
                profile=self.profile.name,
                request_id=self.request_id,
                done=tuple(self._done),
                open=(),
                stop_reason=None,
                summary=summary,
                usage=self._usage(),
            )

    # ----- internals (call with the lock held) ----------------------------------------------

    def _settle_model(self, pid: int, usage: ModelUsage | None, *, log_errors_fatal: bool) -> None:
        g = self._g
        res = self._models.pop(pid)
        reported_cost = usage.cost_usd if usage is not None else None
        reported_tokens = usage.output_tokens if usage is not None else None
        cost = _as_amount(reported_cost)
        tokens = _as_count(reported_tokens)
        # A value that was reported but cannot be read may hide an overrun: count the
        # reservation now and stop below. A missing value (None) only counts the reservation.
        unreadable = [
            f"{name}={value!r}"
            for name, value, parsed in (
                ("cost_usd", reported_cost, cost),
                ("output_tokens", reported_tokens, tokens),
            )
            if value is not None and parsed is None
        ]
        counted = cost if cost is not None else res.cost
        for counter in (self._cost, g._ledger.session, res.daily):
            g._book.settle(counter, res.cost, counted)
        counted_tokens = tokens if tokens is not None else res.max_output_tokens
        self._output_tokens_total += counted_tokens
        self._max_call_tokens = max(self._max_call_tokens, counted_tokens)
        entry = {
            "kind": "model",
            "estimated_cost_usd": res.cost,
            "actual_cost_usd": cost,
            "counted_cost_usd": counted,
            "max_output_tokens": res.max_output_tokens,
            "actual_output_tokens": tokens,
            "input_tokens": _as_count(usage.input_tokens) if usage is not None else None,
            "level": self._level_unlocked().value,
        }
        self._write_log(entry, fatal=log_errors_fatal, date=res.date)
        if not log_errors_fatal:
            return
        if tokens is not None and tokens > res.max_output_tokens:
            self._stop(
                Limit.OUTPUT_TOKENS,
                f"call returned {tokens} output tokens, limit {res.max_output_tokens}",
            )
        for counter in (self._cost, g._ledger.session, res.daily):
            if counter.exceeded():
                self._stop(
                    Limit(counter.name),
                    f"spent {counter.used:g} of {counter.limit:g} USD",
                )
        if unreadable:
            self._stop(Limit.UNREADABLE_USAGE, "model call reported " + ", ".join(unreadable))

    def _settle_tool(
        self,
        pid: int,
        files_written: object,
        live_writes: object,
        *,
        ok: bool,
        label: str | None,
        log_errors_fatal: bool,
    ) -> None:
        g = self._g
        res = self._tools.pop(pid)
        files_parsed = _as_count(files_written)
        live_parsed = _as_count(live_writes)
        unreadable = [
            f"{name}={value!r}"
            for name, value, parsed in (
                ("files_written", files_written, files_parsed),
                ("live_writes", live_writes, live_parsed),
            )
            if value is not None and parsed is None
        ]
        files = files_parsed if files_parsed is not None else res.files
        live = live_parsed if live_parsed is not None else res.live
        g._book.settle(self._files, res.files, files)
        g._book.settle(self._live, res.live, live)
        item = label or f"Werkzeug {res.name}"
        if ok:
            if item in self._open:
                self._open.remove(item)
            self._done.append(item)
        elif item not in self._open:
            self._open.append(item)
        self._write_log(
            {
                "kind": "tool",
                "tool": res.name,
                "ok": ok,
                "files_written": files,
                "live_writes": live,
                "level": self._level_unlocked().value,
            },
            fatal=log_errors_fatal,
        )
        if not log_errors_fatal:
            return
        if self._files.exceeded():
            self._stop(Limit.FILES, f"{res.name} wrote {files}; total {self._files.used:g}")
        if self._live.exceeded():
            self._stop(Limit.LIVE_WRITES, f"{res.name} made {live}; total {self._live.used:g}")
        if unreadable:
            self._stop(Limit.UNREADABLE_USAGE, f"{res.name} reported " + ", ".join(unreadable))

    def _warn_reasons(self) -> list[Limit]:
        p = self.profile
        f = p.warn_at_fraction
        g = self._g
        reasons = [
            Limit(c.name)
            for c in (
                self._model_calls,
                self._tool_calls,
                self._files,
                self._live,
                self._cost,
                g._ledger.session,
                g._ledger.daily(g._today()),
            )
            if c.at_warn(f)
        ]
        if self._max_call_tokens >= f * p.max_output_tokens:
            reasons.append(Limit.OUTPUT_TOKENS)
        repeat = self._loop.max_repeat()
        if repeat >= 2 and repeat >= f * p.max_identical_tool_calls:
            reasons.append(Limit.LOOP)  # a single call is never a repetition
        if self._state != "new" and self.elapsed_s() >= f * p.timeout_s:
            reasons.append(Limit.TIMEOUT)
        return reasons

    def _level_unlocked(self) -> Level:
        if self._stopped is not None:
            return Level.STOP
        return Level.WARN if self._warn_reasons() else Level.OK

    def _check_timeout(self, open_item: str | None) -> None:
        elapsed = self.elapsed_s()
        if elapsed >= self.profile.timeout_s:
            self._stop(
                Limit.TIMEOUT,
                f"{elapsed:.1f} s elapsed, limit {self.profile.timeout_s:g} s",
                open_item=open_item,
            )

    def _require_running(self) -> None:
        if self._state == "new":
            raise RuntimeError("Enter the request first: with guard.request(...) as req:")
        if self._state in ("finished", "closed") and self._stopped is None:
            raise RuntimeError(f"Request {self.request_id} is already {self._state}.")
        self._raise_if_stopped()

    def _require_open_permits(self) -> None:
        # Settling is allowed after a stop (a call in flight still finishes), not after close.
        if self._state in ("new", "closed"):
            raise RuntimeError(f"Request {self.request_id} is not running.")

    def _raise_if_stopped(self) -> None:
        if self._stopped is not None:
            raise self._stopped

    def _usage(self) -> dict[str, Any]:
        return {
            "model_calls": int(self._model_calls.used),
            "tool_calls": int(self._tool_calls.used),
            "files_written": int(self._files.used),
            "live_writes": int(self._live.used),
            "output_tokens": self._output_tokens_total,
            "cost_usd": self._cost.used,
            "elapsed_s": round(self.elapsed_s(), 3),
        }

    def _make_stop(self, reason: Limit, detail: str) -> GuardStop:
        return GuardStop(
            reason,
            detail,
            profile=self.profile.name,
            request_id=self.request_id,
            done=tuple(self._done),
            open_items=tuple(self._open),
            usage=self._usage(),
        )

    def _stop(self, reason: Limit, detail: str, *, open_item: str | None = None) -> None:
        if self._stopped is None:
            if open_item and open_item not in self._open:
                self._open.append(open_item)
            self._stopped = self._make_stop(reason, detail)
            self._write_log(
                {"kind": "stop", "stop_reason": reason.value, "detail": detail}, fatal=False
            )
        raise self._stopped

    def _write_log(
        self, entry: dict[str, Any], *, fatal: bool, date: str | None = None
    ) -> None:
        try:
            full = {
                "ts": self._g._now().isoformat(),
                "date": date or self._g._today(),
                "session": self._g.session_id,
                "request": self.request_id,
                "profile": self.profile.name,
                **entry,
            }
            self._g._log.append(full)
        except Exception as exc:  # noqa: BLE001 - any log failure is a stop (or recorded)
            if not fatal:
                self.log_errors.append(repr(exc))
                return
            self._stop(Limit.USAGE_LOG, repr(exc))


__all__ = [
    "EPS",
    "Guard",
    "GuardStop",
    "GuardedRequest",
    "Level",
    "Limit",
    "ModelCallPermit",
    "ModelUsage",
    "RequestResult",
    "ToolPermit",
    "warning_message_de",
]
