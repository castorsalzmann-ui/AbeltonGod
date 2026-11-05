"""Dispatch table: tool name -> the tool's own ``main(argv)``.

Nothing here re-implements a tool. The six sound categories share ``audio_engine.cli`` (the
same entry point as ``python -m audio_engine.kick``) and get ``--category <name>`` prepended;
the Live scripts under ``scripts/`` are not a package, so they are loaded by path (from the
bundle in the exe, from the checkout otherwise), the same way ``kick_to_live`` loads
``live_import``.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType

from .paths import scripts_dir

Main = Callable[[list[str]], int | None]


@dataclass(frozen=True)
class Tool:
    name: str
    summary: str
    module: str  # dotted module, or the file name stem under scripts/ when script=True
    script: bool = False
    prefix: tuple[str, ...] = ()  # arguments put in front of the user's
    # Menu: what the menu passes (--out is added by the menu where out_mode says so).
    # out_mode: "dir" = --out <folder> (files named by the tool), "new" = --out <new subfolder>,
    # "" = the tool has no output folder (the menu asks for free arguments only).
    out_mode: str = ""
    menu_args: tuple[str, ...] = ()


TOOLS: tuple[Tool, ...] = (
    Tool("kick", "Kick-WAV erzeugen", "audio_engine.cli", prefix=(),
         out_mode="dir", menu_args=("--preset", "centre")),
    Tool("hat", "Hi-Hat-WAV erzeugen", "audio_engine.cli", prefix=("--category", "hat"),
         out_mode="dir", menu_args=("--preset", "closed-std")),
    Tool("snare", "Snare-WAV erzeugen", "audio_engine.cli", prefix=("--category", "snare"),
         out_mode="dir", menu_args=("--preset", "default")),
    Tool("clap", "Clap-WAV erzeugen", "audio_engine.cli", prefix=("--category", "clap"),
         out_mode="dir", menu_args=("--preset", "default")),
    Tool("rim", "Rim-WAV erzeugen", "audio_engine.cli", prefix=("--category", "rim"),
         out_mode="dir", menu_args=("--preset", "rim")),
    Tool("bass", "Bass-WAV erzeugen", "audio_engine.cli", prefix=("--category", "bass"),
         out_mode="dir", menu_args=("--preset", "default")),
    Tool("goa-arrangement", "Kompletter Goa-Track als MIDI + README",
         "audio_engine.goa_arrangement", out_mode="new"),
    Tool("goa-melody", "Goa-Melodien (Lead/Arp/Pad/Pluck) als MIDI + README",
         "audio_engine.goa_melody", out_mode="new"),
    Tool("goa-patterns", "Goa-Bass- und Rhythmus-Muster als MIDI",
         "audio_engine.goa_patterns"),
    Tool("arrangement-midi", "Arrangement-JSON in eine MIDI-Datei umwandeln",
         "audio_engine.arrangement_midi"),
    Tool("live-import", "WAV als Clip in Live importieren (schreibt in Live)",
         "live_import", script=True),
    Tool("kick-to-live", "Kick erzeugen und in Live importieren (schreibt in Live)",
         "kick_to_live", script=True),
    Tool("bridge-check", "Verbindung zu Live/AbletonOSC pruefen", "bridge_check", script=True),
    Tool("arrangement-check", "Arrangement-Funktionen in Live pruefen (schreibt in Live)",
         "arrangement_check", script=True),
    Tool("install-abletonosc", "AbletonOSC-Erweiterung installieren",
         "install_abletonosc_extension", script=True),
    Tool("als-inspect", "Live-Set (.als) inspizieren", "als_inspect", script=True),
    Tool("plan", "Arrangement-Plan erzeugen (ohne Claude)", "orchestrator.plan_cli"),
    Tool("chat", "Claude-Copilot im Terminal (braucht Zugang, siehe .env.example)",
         "orchestrator.chat"),
)

BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}
assert len(BY_NAME) == len(TOOLS), "duplicate tool name"


def _load_script(stem: str) -> ModuleType:
    if stem in sys.modules:
        return sys.modules[stem]
    path = scripts_dir() / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[stem] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(stem, None)
        raise
    return module


def resolve(tool: Tool) -> Main:
    """The tool's ``main`` function (imports the tool's module on first use)."""
    module = _load_script(tool.module) if tool.script else importlib.import_module(tool.module)
    return module.main


def run_tool(tool: Tool, argv: list[str]) -> int:
    """Run ``tool`` with ``argv`` like its own command line; return the exit code."""
    main = resolve(tool)
    try:
        code = main([*tool.prefix, *argv])
    except SystemExit as exc:  # argparse --help / usage errors inside a tool
        if exc.code is None:
            return 0
        return exc.code if isinstance(exc.code, int) else 1
    return 0 if code is None else code
