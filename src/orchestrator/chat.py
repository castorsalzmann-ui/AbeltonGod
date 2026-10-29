"""Minimal terminal chat (Phase 04b).

    python -m orchestrator.chat                       # Claude via the Agent SDK (#106)
    python -m orchestrator.chat --replay FILE.json    # fake model replaying a recording

Each line is one guarded request (profile ``kick_generation``). Empty line, ``exit`` or
``quit`` (or Ctrl+D / Ctrl+C) ends the chat. No product tools yet (D-020 step 2, #81).

Exit codes: 0 normal end · 2 usage or setup error (bad policy, bad recording).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from guard import Guard, PolicyError
from orchestrator.clients import make_model_client
from orchestrator.fake_model import FakeModel, RecordingError
from orchestrator.loop import DEFAULT_PROFILE, Orchestrator
from orchestrator.model_client import ModelClient
from orchestrator.tools import Tool, Toolbox

EXIT_OK = 0
EXIT_SETUP = 2
_YES = {"j", "ja", "y", "yes"}
_QUIT = {"", "exit", "quit"}


class TerminalApprover:
    """Asks before any ``confirm`` tool. Only an explicit yes counts."""

    def __init__(self, read: Callable[[str], str], out: TextIO) -> None:
        self._read = read
        self._out = out

    def confirm(self, tool: Tool, arguments: dict[str, Any]) -> bool:
        self._out.write(f"Bestätigen: {tool.name} {arguments} ändert das Ableton-Set.\n")
        try:
            answer = self._read("Ausführen? [j/N] ")
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() in _YES


def run_chat(
    orchestrator: Orchestrator, read: Callable[[str], str], out: TextIO
) -> int:
    out.write("AbeltonGod Copilot. Leere Zeile oder 'exit' beendet.\n")
    while True:
        try:
            line = read("> ")
        except (EOFError, KeyboardInterrupt):
            out.write("\n")
            return EXIT_OK
        if line.strip().lower() in _QUIT:
            return EXIT_OK
        outcome = orchestrator.handle(line)
        out.write(outcome.text_for_user + "\n")


def main(
    argv: list[str] | None = None,
    *,
    read: Callable[[str], str] = input,
    out: TextIO | None = None,
    guard: Guard | None = None,
    model: ModelClient | None = None,
) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m orchestrator.chat")
    parser.add_argument("--replay", type=Path, help="replay a recorded model session (no Claude)")
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    args = parser.parse_args(argv)
    try:
        guard = guard or Guard()
        if model is None:
            model = (
                FakeModel.from_file(args.replay)
                if args.replay
                else make_model_client(profile=guard.policy.profile(args.profile))
            )
        orchestrator = Orchestrator(
            guard,
            model,
            Toolbox(),
            profile=args.profile,
            approver=TerminalApprover(read, out),
        )
    except (RecordingError, PolicyError) as exc:
        out.write(f"Fehler: {exc}\n")
        return EXIT_SETUP
    try:
        return run_chat(orchestrator, read, out)
    finally:
        close = getattr(model, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
