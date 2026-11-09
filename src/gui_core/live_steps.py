"""Why a Live-import button is grey and what to do next (#548). No Qt.

The Live-import page has three steps: 1 Live-Set lesen -> 2 Plan prüfen -> 3 In Live
importieren. :func:`reasons` gives, per button, the German reason it is disabled ("" =
enabled, the same rule as ``LivePanel._update_state``); :func:`next_step` the one sentence
that tells the user what to do now.
"""

from __future__ import annotations

from dataclasses import dataclass

STEPS = ("Live-Set lesen", "Plan prüfen", "In Live importieren")
SETUP_DOC = "docs/setup/ABLETONOSC_WINDOWS.md"
SETUP_URL = ("https://github.com/castorsalzmann-ui/AbeltonGod/blob/main/"
             "docs/setup/ABLETONOSC_WINDOWS.md")
TESTSET_TEXT = "Das geöffnete Set ist ein eigenes Test-Set"
UNVERIFIED_TEXT = "Ich weiß, dass diese Live-Funktionen 'nicht verifiziert' sind"


@dataclass(frozen=True)
class StepState:
    have_wav: bool
    gate_ok: bool
    busy: bool
    inspection_ok: bool | None  # None = step 1 not run (or reset by a changed input)
    plan_ok: bool | None  # None = step 2 not run
    testset: bool
    needs_unverified: bool
    unverified_ok: bool


def reasons(s: StepState) -> dict[str, str]:
    """German reason per button (``inspect``, ``plan``, ``import``); "" = enabled."""
    common = ""
    if not s.gate_ok:
        common = "Die Capability-Registry ist nicht lesbar (siehe Hinweis oben)."
    elif s.busy:
        common = "Ein Schritt läuft gerade; bitte warten."
    out = {"inspect": common, "plan": common, "import": common}
    if not common and not s.have_wav:
        out["inspect"] = out["plan"] = (
            "Erst eine WAV wählen: „Bibliothek lesen“ oder „Andere Datei …“.")
    if not out["plan"]:
        if s.inspection_ok is None:
            out["plan"] = "Erst Schritt 1: „Live-Set lesen“."
        elif not s.inspection_ok:
            out["plan"] = ("Schritt 1 ist fehlgeschlagen (Meldung unten). Fehler beheben, dann "
                           "„Live-Set lesen“ noch einmal.")
    if not out["import"]:
        if s.plan_ok is None:
            out["import"] = ("Erst Schritt 2: „Plan prüfen“." if s.inspection_ok
                             else "Erst Schritt 1 und 2: „Live-Set lesen“, dann „Plan prüfen“.")
        elif not s.plan_ok:
            out["import"] = ("Der Plan ist fehlgeschlagen (Meldung unten). Eingaben ändern und "
                             "neu prüfen.")
        elif not s.testset:
            out["import"] = f"Bestätigen: „{TESTSET_TEXT}“."
        elif s.needs_unverified and not s.unverified_ok:
            out["import"] = f"Bestätigen: „{UNVERIFIED_TEXT}“."
    return out


def current_step(s: StepState) -> int:
    """1, 2 or 3: the step the user is at."""
    if s.inspection_ok is not True:
        return 1
    if s.plan_ok is not True:
        return 2
    return 3


def next_step(s: StepState) -> str:
    """One German sentence: what to do now."""
    r = reasons(s)
    step = current_step(s)
    key = ("inspect", "plan", "import")[step - 1]
    if r[key]:
        return f"Nächster Schritt: {r[key]}"
    return f"Nächster Schritt: {step} · „{STEPS[step - 1]}“ klicken."
