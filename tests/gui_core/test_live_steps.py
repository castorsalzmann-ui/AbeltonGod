"""#548: a grey Live-import button always says why, and the reason is "" exactly when the
button is enabled. The enable rule is written here from LivePanel._update_state (not taken
from gui_core.live_steps)."""

from __future__ import annotations

import itertools

from gui_core.live_steps import StepState, current_step, next_step, reasons


def enabled(s: StepState) -> dict[str, bool]:
    idle = not s.busy
    unv = (not s.needs_unverified) or s.unverified_ok
    return {
        "inspect": s.have_wav and idle and s.gate_ok,
        "plan": s.have_wav and idle and s.gate_ok and s.inspection_ok is True,
        "import": idle and s.gate_ok and s.plan_ok is True and s.testset and unv,
    }


def all_states():
    tri = (None, False, True)
    for have, gate, busy, ins, plan, ts, need, ok in itertools.product(
            (False, True), (False, True), (False, True), tri, tri, (False, True), (False, True),
            (False, True)):
        yield StepState(have, gate, busy, ins, plan, ts, need, ok)


def test_reason_is_empty_exactly_when_the_button_is_enabled_in_every_state():
    n = 0
    for s in all_states():
        why, on = reasons(s), enabled(s)
        for key in ("inspect", "plan", "import"):
            assert (why[key] == "") == on[key], (key, s, why[key])
        assert next_step(s).startswith("Nächster Schritt: ")
        n += 1
    assert n == 2 * 2 * 2 * 3 * 3 * 2 * 2 * 2


def test_the_texts_name_the_next_action():
    s = StepState(False, True, False, None, None, False, False, False)
    assert "Erst eine WAV wählen" in reasons(s)["inspect"]
    s = StepState(True, True, False, None, None, False, False, False)
    assert current_step(s) == 1
    assert next_step(s) == "Nächster Schritt: 1 · „Live-Set lesen“ klicken."
    assert reasons(s)["plan"] == "Erst Schritt 1: „Live-Set lesen“."
    s = StepState(True, True, False, False, None, False, False, False)
    assert "fehlgeschlagen" in reasons(s)["plan"]
    s = StepState(True, True, False, True, None, False, False, False)
    assert current_step(s) == 2 and reasons(s)["import"] == "Erst Schritt 2: „Plan prüfen“."
    s = StepState(True, True, False, True, True, False, True, False)
    assert current_step(s) == 3 and "Test-Set" in reasons(s)["import"]
    s = StepState(True, True, False, True, True, True, True, False)
    assert "nicht verifiziert" in reasons(s)["import"]
    s = StepState(True, True, False, True, True, True, True, True)
    assert next_step(s) == "Nächster Schritt: 3 · „In Live importieren“ klicken."
    s = StepState(True, True, True, None, None, False, False, False)
    assert "läuft gerade" in reasons(s)["inspect"]
