"""Bug #428: an inactive field kept its old text, ``limit_of`` judged the limit from that text,
found it refused and reported the field as free, so a typed value was not clamped and the
combination was refused (Render blocked).

Repro from the issue (rim page): Frequenz 1 on 900, Hochpass 500, Hochpass off, Frequenz 1 off;
then 6000 typed into Hochpass was not clamped. The engine refuses hp_hz >= 0.8 * f1_hz; with
f1_hz off it uses the contract default for f1_hz. The bound is written here from that rule and
the contract file, not from the form code. The full click path is in ``tests/gui/test_widgets.py``
(``test_bug_428_...``).
"""

from __future__ import annotations

import json

from audio_engine.params import CONTRACTS_DIR
from gui_core import links
from gui_core.form import CategoryFormModel


def _rim_f1_default() -> float:
    schema = json.loads((CONTRACTS_DIR / "rim-params.schema.json").read_text(encoding="utf-8"))
    return float(schema["properties"]["f1_hz"]["default"])


def test_bug_428_inactive_field_limit_comes_from_the_engine_default_not_the_stale_text():
    m = CategoryFormModel("rim")
    m.set_active("f1_hz", True)
    m.set_text("f1_hz", "900")
    m.set_active("hp_hz", True)
    m.set_text("hp_hz", "500")
    m.set_active("hp_hz", False)  # text "500" stays
    m.set_active("f1_hz", False)  # text "900" stays; the engine uses the default
    assert m.issues() == []
    bound = 0.8 * _rim_f1_default()
    lim = links.limit_of(m, "hp_hz")
    # before the fix: hi == contract maximum (free), because "500" with default f1 is refused
    assert lim.limited and lim.hi < bound <= 1.01 * lim.hi, lim
    assert "f1_hz" in lim.partners
