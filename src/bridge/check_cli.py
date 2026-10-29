"""Shared helpers of the user-facing Live check scripts (``scripts/live_import.py``,
``scripts/arrangement_check.py``): prompts, German messages, ports. No Live calls here.

Moved out of ``live_import.py`` 0.3.0 unchanged (#140), so both scripts say the same thing.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable

YES = {"y", "yes", "j", "ja"}


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).astimezone().isoformat(timespec="seconds")


def msg_no_answer(host: str, send_port: int) -> str:
    return (
        f"FEHLER: AbletonOSC antwortet nicht ({host}:{send_port}).\n"
        "Mögliche Ursachen (von hier aus nicht zu unterscheiden, bitte alle prüfen):\n"
        "  1. Ableton Live ist nicht geöffnet.\n"
        "  2. 'AbletonOSC' ist nicht als Control Surface ausgewählt\n"
        "     (Optionen -> Einstellungen -> Link, Tempo & MIDI).\n"
        "  3. In Live ist ein Dialog offen (z. B. Speichern) und blockiert die Antwort.\n"
        "  4. Live wurde nach der Installation nicht neu gestartet.\n"
        "Log: ...\\Remote Scripts\\AbletonOSC\\logs\\abletonosc.log"
    )


MSG_PORT_IN_USE = (
    "FEHLER: Port {port} ({host}) ist schon belegt. Ein anderes Programm (z. B. ein zweites\n"
    "Terminal mit diesem Script oder bridge_check.py) empfängt dort. Dieses schließen und neu\n"
    "starten. Es wurde nichts in Live geändert."
)

# Live 12 manual: English "View -> Undo History", German "Ansicht -> Widerrufen-Historie",
# shortcut Ctrl+Alt+Z (Win); clicking an entry undoes back to it (checked 2026-10-29:
# ableton.com/en/live-manual/12/managing-files-and-sets/, /de/live-manual/12/live-concepts/
# section 3.20).
UNDO_HINT = ("In Live zeigt die Widerrufen-Historie, welche Schritte es gibt: Strg+Alt+Z oder "
             "Menü Ansicht -> Widerrufen-Historie (englische Oberfläche: View -> Undo History). "
             "Dort nur nachsehen, keinen Eintrag anklicken: ein Klick setzt das Set auf diesen "
             "Stand zurück.")


def ask(prompt: str, input_fn: Callable[[str], str]) -> str | None:
    """Stripped answer, or None on EOF. Ctrl+C propagates."""
    try:
        return input_fn(prompt).strip()
    except EOFError:
        return None


def ask_yes(prompt: str, input_fn: Callable[[str], str]) -> bool:
    return (ask(prompt, input_fn) or "").lower() in YES


def env_port(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default
