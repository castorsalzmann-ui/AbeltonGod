"""Append-only JSONL usage log in a local, git-ignored folder (``logs/`` by default).

One line per settled model call, finished tool call, stop and request end. The daily budget is
rebuilt from this file on start, so a restart does not reset it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from guard.policy import REPO_ROOT

DEFAULT_LOG_FILE = REPO_ROOT / "logs" / "guard-usage.jsonl"


class UsageLogError(OSError):
    """The log could not be written. The guard treats this as a stop."""


def _reject_constant(token: str) -> Any:
    raise ValueError(token)


class UsageLog:
    def __init__(self, path: Path | str = DEFAULT_LOG_FILE) -> None:
        self.path = Path(path)
        self.skipped_lines = 0  # unreadable lines seen by the last counted_cost_on()

    def append(self, entry: dict[str, Any]) -> None:
        # allow_nan=False: a NaN in the log would poison the daily total after a restart.
        try:
            line = json.dumps(entry, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise UsageLogError(f"Usage log entry is not plain JSON: {exc}") from exc
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
                fh.flush()
        except OSError as exc:
            raise UsageLogError(f"Cannot write usage log {self.path}: {exc}") from exc

    def counted_cost_on(self, date: str) -> float:
        """Sum of ``counted_cost_usd`` of model calls logged on local date ``date``.

        Lines that are not valid JSON objects (e.g. a line cut off by a crash) are skipped and
        counted in ``skipped_lines``. A missing file means nothing was spent.
        """
        self.skipped_lines = 0
        if not self.path.exists():
            return 0.0
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise UsageLogError(f"Cannot read usage log {self.path}: {exc}") from exc
        total = 0.0
        for raw in text.splitlines():
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw, parse_constant=_reject_constant)
            except ValueError:
                self.skipped_lines += 1
                continue
            if not isinstance(entry, dict):
                self.skipped_lines += 1
                continue
            if entry.get("kind") != "model" or entry.get("date") != date:
                continue
            cost = entry.get("counted_cost_usd")
            if isinstance(cost, bool) or not isinstance(cost, int | float) or not (
                math.isfinite(cost) and cost >= 0
            ):
                self.skipped_lines += 1
                continue
            total += cost
        return total
