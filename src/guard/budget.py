"""Counters for one request plus session and daily totals.

Pattern: reserve before a call, settle with the actual amount after it. If the actual amount is
missing or invalid, the reserved amount is counted (conservative).

Thread safety: ``BudgetBook.lock`` guards every counter. ``reserve_all`` checks and reserves a
set of counters in one locked step, so parallel requests can never jointly overshoot a budget.
Callers that read or change counters outside ``reserve_all``/``settle`` must hold the lock.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Iterable
from dataclasses import dataclass

# Tolerance for float sums of USD amounts (0.1 + 0.2 != 0.3). Far below any real price.
EPS = 1e-9


class Counter:
    """One bounded quantity. ``used`` is settled, ``reserved`` is in flight."""

    __slots__ = ("name", "limit", "used", "reserved")

    def __init__(self, name: str, limit: float, used: float = 0) -> None:
        self.name = name
        self.limit = limit
        self.used = used
        self.reserved = 0

    @property
    def headroom(self) -> float:
        return self.limit - self.used - self.reserved

    def fits(self, amount: float, *, needs_room: bool = False) -> bool:
        """True if ``amount`` more fits. ``needs_room``: also refuse when nothing is left,
        even for a zero amount (used for money, where a zero estimate must not slip through)."""
        if needs_room and self.headroom <= EPS:
            return False
        return amount <= self.headroom + EPS

    def exceeded(self) -> bool:
        return self.used > self.limit + EPS

    def at_warn(self, fraction: float) -> bool:
        return self.used > 0 and self.used >= fraction * self.limit - EPS


@dataclass
class Violation:
    counter: Counter
    requested: float


class BudgetBook:
    """Owns the lock and performs atomic multi-counter reservations."""

    def __init__(self) -> None:
        self.lock = threading.RLock()

    def reserve_all(
        self, items: Iterable[tuple[Counter, float, bool]]
    ) -> Violation | None:
        """Reserve every ``(counter, amount, needs_room)`` or none of them.

        Returns the first counter that has no room, without changing anything.
        """
        items = list(items)
        for counter, amount, _ in items:
            if not is_valid_amount(amount):
                raise ValueError(f"{counter.name}: amount must be finite and >= 0, got {amount!r}")
        with self.lock:
            for counter, amount, needs_room in items:
                if not counter.fits(amount, needs_room=needs_room):
                    return Violation(counter, amount)
            for counter, amount, _ in items:
                counter.reserved += amount
            return None

    def settle(self, counter: Counter, reserved: float, counted: float) -> None:
        with self.lock:
            counter.reserved -= reserved
            if abs(counter.reserved) < EPS:
                counter.reserved = 0
            counter.used += counted


class SessionLedger:
    """Session total (lifetime of one Guard) and daily totals keyed by local ISO date.

    ``spent_today`` seeds the start date from the usage log, so a restart does not reset the
    daily budget. Other days start at zero.
    """

    def __init__(
        self, session_budget: float, daily_budget: float, start_date: str, spent_today: float
    ) -> None:
        self.session = Counter("session_budget_usd", session_budget)
        self._daily_budget = daily_budget
        self._days: dict[str, Counter] = {
            start_date: Counter("daily_budget_usd", daily_budget, used=spent_today)
        }

    def daily(self, date: str) -> Counter:
        counter = self._days.get(date)
        if counter is None:
            counter = self._days[date] = Counter("daily_budget_usd", self._daily_budget)
        return counter


def is_valid_amount(value: object) -> bool:
    """Finite, non-negative real number; bools are not amounts."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value) and value >= 0
