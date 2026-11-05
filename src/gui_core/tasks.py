"""Run one blocking function in a daemon thread and hand back a handle (no Qt).

The Goa, Live and chat pages use it so the window never waits for the engine, the network or
Claude. ``fn`` is expected to return a result object for its own failures; an exception that
still escapes is stored in ``TaskHandle.error`` and the handle always finishes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


class TaskHandle:
    def __init__(self) -> None:
        self._done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    @property
    def done(self) -> bool:
        return self._done.is_set()


def start_task(
    fn: Callable[[], Any],
    on_done: Callable[[TaskHandle], None] | None = None,
    name: str = "gui-task",
) -> TaskHandle:
    """Start ``fn`` in a thread. ``on_done(handle)`` runs in that thread after the handle is
    finished; a failing callback cannot kill the thread."""
    handle = TaskHandle()

    def work() -> None:
        try:
            handle.result = fn()
        except BaseException as exc:  # noqa: BLE001 - the handle must always finish
            handle.error = exc
        handle._done.set()
        if on_done is not None:
            try:
                on_done(handle)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=work, name=name, daemon=True).start()
    return handle
