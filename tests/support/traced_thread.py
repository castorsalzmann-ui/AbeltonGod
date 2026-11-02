"""Run a trace-hook interrupt sweep in a throw-away thread (#183).

Why: on CPython 3.13.18 a trace function that raises ``KeyboardInterrupt`` at a line right
after a handled ``FileExistsError`` (``with suppress(FileExistsError): ...`` followed by
``continue`` in ``audio_engine.io.write_kick``, sweep point k = 35 of the "sidecar-race" case)
leaves that ``FileExistsError`` as the thread's *currently handled exception*:
``sys.exception()`` keeps returning it after the test, and every exception raised later in the
same thread gets it as ``__context__`` ("During handling of the above exception ..."). With
pytest-xdist the thread is the worker's, so a failure in an unrelated later test showed a
traceback that pointed at the sweep (#180, #183).

The handled-exception state belongs to the thread, and no pure-Python call clears it. The sweep
therefore runs in its own thread, which takes the leaked state with it when it ends.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def run_in_fresh_thread(fn: Callable[[], T]) -> T:
    """Call ``fn()`` in a new thread and return its result or re-raise its exception here.

    ``sys.settrace`` inside ``fn`` affects that thread only."""
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # handed to the caller below, KeyboardInterrupt included
            box["error"] = exc

    thread = threading.Thread(target=target, name="traced-sweep")
    thread.start()
    thread.join()
    if "error" in box:
        error = box["error"]
        assert isinstance(error, BaseException)
        raise error
    return box["value"]  # type: ignore[return-value]


def leaked_exception() -> BaseException | None:
    """The exception this thread still treats as 'being handled', or None when clean."""
    return sys.exception()
