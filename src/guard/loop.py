"""Loop detection: the same tool with the same arguments, repeated within one request."""

from __future__ import annotations

import json
import math
from collections import Counter as _Tally
from typing import Any


def _normalise(value: Any) -> Any:
    # The model sends JSON, so 3 and 3.0 are the same argument. Bools stay bools (True == 1 in
    # Python, but not for a tool). NaN/Inf become strings so they compare equal to themselves.
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return f"<float {value!r}>"
        return int(value) if value.is_integer() else value
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalise(v) for v in value]
    return f"<{type(value).__name__} {value!r}>"


def call_key(name: str, args: Any) -> str:
    """Canonical text for ``name`` + ``args``: key order and 3 vs 3.0 do not matter."""
    return json.dumps(
        [name, _normalise(args)], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


class LoopDetector:
    def __init__(self, max_identical: int) -> None:
        self.max_identical = max_identical
        self._seen: _Tally[str] = _Tally()

    def count_if_called(self, key: str) -> int:
        """How many times this exact call would have run, including the one about to start."""
        return self._seen[key] + 1

    def record(self, key: str) -> None:
        self._seen[key] += 1

    def max_repeat(self) -> int:
        return max(self._seen.values(), default=0)
