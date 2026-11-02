"""Minimal terminal chat (Phase 04b).

    python -m orchestrator.chat                       # Claude via the Agent SDK (#106)
    python -m orchestrator.chat --project "C:\\...\\MyProject"   # with the kick tools (#148)
    python -m orchestrator.chat --replay FILE.json    # fake model replaying a recording

Each line is one guarded request (profile ``kick_generation``). Empty line, ``exit`` or
``quit`` (or Ctrl+D / Ctrl+C at the prompt) ends the chat. Ctrl+C while a request runs ends
that request (never as a success) and the chat asks for the next line (#176); at the
"Ausführen? [j/N]" question Ctrl+C means "no" and the request goes on. Claude
unreachable (no connection, or no answer within the profile's ``timeout_s``): the request
fails with a German message and the chat goes on.

Tools (#148): with ``--project`` (the Live project folder, the one with the ``.als`` file)
the copilot gets ``generate_kick``, ``list_tracks`` and ``import_sample``; without it, none.
Kicks go to ``<project>\\Samples\\Drums\\Kicks``; ``import_sample`` asks before it changes
the Live set.

Exit codes: 0 normal end · 2 usage or setup error (bad policy, bad recording, refused
project folder, capability registry unreadable).
"""

from __future__ import annotations

import argparse
import logging
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
from orchestrator.plan_tools import PlanSession
from orchestrator.project import ProjectCheckUnavailable
from orchestrator.sample_tools import SampleTools
from orchestrator.tools import CONFIRM_WINDOW_S, Plan, Tool, Toolbox, ToolDefinitionError

SDK_LOGGER = "claude_agent_sdk"
EXIT_OK = 0
EXIT_SETUP = 2
_YES = {"j", "ja", "y", "yes"}
_QUIT = {"", "exit", "quit"}


def _live_number(index: Any) -> str:
    """0-based tool index -> Live's 1-based number; anything else shown as is."""
    if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
        return str(index + 1)
    return str(index)


class TerminalApprover:
    """Asks before any ``confirm`` tool. Only an explicit yes counts."""

    def __init__(self, read: Callable[[str], str], out: TextIO) -> None:
        self._read = read
        self._out = out

    def confirm(self, tool: Tool, arguments: dict[str, Any], plan: Plan | None = None) -> bool:
        if plan is not None and tool.name == "import_sample":
            s = plan.summary
            # Live counts tracks and scenes from 1; the tools count from 0 (PR #168 review).
            track, slot = _live_number(s.get("track_index")), _live_number(s.get("slot_index"))
            self._out.write(
                f"Bestätigen: {s.get('file')} ({s.get('sample_id')}) in Spur "
                f"\"{s.get('track_name')}\" (Spur {track} von links), Zelle in Szene {slot} "
                "importieren. Das ändert das Ableton-Set.\n"
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
        # #176: while Claude works nothing reads the console, so say so (and how to stop).
        # At a "Ausführen? [j/N]" question Ctrl+C means "no" (TerminalApprover), not "abort".
        out.write("(Claude arbeitet ... Strg+C bricht die Anfrage ab. Bei der Frage "
                  "\"Ausführen?\" heißt Strg+C: nein.)\n")
        out.flush()
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
        limit = guard.policy.profile(args.profile).max_files_written
        plans = PlanSession()  # needs no project folder: plans stay in this chat
        toolbox = (Toolbox(session.tools(files_per_request=limit)
                           + SampleTools(session).tools(files_per_request=limit)
                           + plans.tools(),
                           capability_gate=session.gate())
                   if session is not None else Toolbox(plans.tools()))
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
            context=lambda: "\n\n".join(
                t for t in (session.context() if session is not None else "", plans.context())
                if t),
        )
    except (RecordingError, PolicyError, ToolDefinitionError, CapabilityError,
            ValueError, OSError) as exc:
        out.write(f"Fehler: {exc}\n")
        return EXIT_SETUP
    if unavailable:
        out.write("Kick-Werkzeuge noch nicht verfügbar: die Prüfung des Projektordners "
                  f"(#149) fehlt noch ({unavailable}). Der Chat läuft ohne Kick-Werkzeuge.\n")
    elif session is None:
        out.write("Ohne --project: keine Kick-Werkzeuge (generate_kick, list_tracks, "
                  "import_sample).\n")
    else:
        out.write(f"Kicks gehen nach: {session.kick_folder}\n")
    # #176 review P3: a killed CLI makes the SDK log "Fatal error in message reader: ... exit
    # code -9" at ERROR level. The chat configures no logging, so Python would print that
    # English line to the console before our German message. The outcome carries the facts.
    sdk_log = logging.getLogger(SDK_LOGGER)
    sdk_level = sdk_log.level
    sdk_log.setLevel(logging.CRITICAL)
    try:
        return run_chat(orchestrator, read, out)
    finally:
        sdk_log.setLevel(sdk_level)
        close = getattr(model, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
