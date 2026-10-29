"""Minimal terminal chat (Phase 04b).

    python -m orchestrator.chat                       # Claude via the Agent SDK (#106)
    python -m orchestrator.chat --project "C:\\...\\MyProject"   # with the kick tools (#148)
    python -m orchestrator.chat --replay FILE.json    # fake model replaying a recording

Each line is one guarded request (profile ``kick_generation``). Empty line, ``exit`` or
``quit`` (or Ctrl+D / Ctrl+C) ends the chat.

Tools (#148): with ``--project`` (the Live project folder, the one with the ``.als`` file)
the copilot gets ``generate_kick``, ``list_tracks`` and ``import_sample``; without it, none.
Kicks go to ``<project>\\Samples\\Drums\\Kicks``; ``import_sample`` asks before it changes
the Live set.

Exit codes: 0 normal end · 2 usage or setup error (bad policy, bad recording, refused
project folder, capability registry unreadable).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from bridge.capabilities import CapabilityError
from guard import Guard, PolicyError
from orchestrator.clients import make_model_client
from orchestrator.fake_model import FakeModel, RecordingError
from orchestrator.kick_tools import KickSession
from orchestrator.loop import DEFAULT_PROFILE, Orchestrator
from orchestrator.model_client import ModelClient
from orchestrator.project import ProjectCheckUnavailable
from orchestrator.tools import CONFIRM_WINDOW_S, Plan, Tool, Toolbox, ToolDefinitionError

EXIT_OK = 0
EXIT_SETUP = 2
_YES = {"j", "ja", "y", "yes"}
_QUIT = {"", "exit", "quit"}


class TerminalApprover:
    """Asks before any ``confirm`` tool. Only an explicit yes counts."""

    def __init__(self, read: Callable[[str], str], out: TextIO) -> None:
        self._read = read
        self._out = out

    def confirm(self, tool: Tool, arguments: dict[str, Any], plan: Plan | None = None) -> bool:
        if plan is not None and tool.name == "import_sample":
            s = plan.summary
            self._out.write(
                f"Bestätigen: {s.get('file')} ({s.get('sample_id')}) in Spur "
                f"{s.get('track_index')} \"{s.get('track_name')}\", Zelle (Szene) "
                f"{s.get('slot_index')} importieren. Das ändert das Ableton-Set.\n"
                f"Bitte innerhalb von {CONFIRM_WINDOW_S:g} s antworten, sonst wird nichts "
                "ausgeführt.\n"
            )
        else:
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
    session_factory: Callable[[str], KickSession] = KickSession,
) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m orchestrator.chat")
    parser.add_argument("--replay", type=Path, help="replay a recorded model session (no Claude)")
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--project", help="Live project folder (the one with the .als file); "
                        "enables generate_kick, list_tracks and import_sample")
    args = parser.parse_args(argv)
    unavailable = ""
    try:
        guard = guard or Guard()
        guard.policy.profile(args.profile)
        session = None
        if args.project is not None:
            try:
                session = session_factory(args.project)
            except ProjectCheckUnavailable as exc:  # until #149 is merged
                unavailable = str(exc)
        toolbox = (Toolbox(session.tools(), capability_gate=session.gate())
                   if session is not None else Toolbox())
        if model is None:
            model = (
                FakeModel.from_file(args.replay)
                if args.replay
                else make_model_client(profile=guard.policy.profile(args.profile))
            )
        orchestrator = Orchestrator(
            guard,
            model,
            toolbox,
            profile=args.profile,
            approver=TerminalApprover(read, out),
            context=session.context if session is not None else None,
        )
    except (RecordingError, PolicyError, ToolDefinitionError, CapabilityError,
            ValueError, OSError) as exc:
        out.write(f"Fehler: {exc}\n")
        return EXIT_SETUP
    if unavailable:
        out.write("Kick-Werkzeuge noch nicht verfügbar: die Prüfung des Projektordners "
                  f"(#149) fehlt noch ({unavailable}). Der Chat läuft ohne Werkzeuge.\n")
    elif session is None:
        out.write("Ohne --project: keine Kick-Werkzeuge (generate_kick, list_tracks, "
                  "import_sample).\n")
    else:
        out.write(f"Kicks gehen nach: {session.kick_folder}\n")
    try:
        return run_chat(orchestrator, read, out)
    finally:
        close = getattr(model, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
