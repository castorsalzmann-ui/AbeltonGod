"""Value <-> slider position mapping for the widget kit (no Qt).

A slider or knob works on whole positions ``0 .. pos_max``. :class:`ValueMap` turns a position
into a contract value and back, clamps, and writes the value as German text ("0,35 s", "aus").
The map is built from a contract :class:`~gui_core.form.FieldSpec` (range, kind, unit) and never
from a copy of a range.

* ``log``: a range that spans a factor of 20 or more (Hz, ms) is mapped on a logarithmic scale,
  so the low end stays usable. Values are rounded to 3 significant digits.
* ``zero_off``: contract fields "0 = off, otherwise min..max" get position 0 for the value 0.
* Integer fields move in whole numbers; a float is rounded to the decimals the range needs.

Dragging produces rounded values; a value that is set from outside (preset, typed number) is
kept exactly by the widgets and only its position is looked up here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .form import FieldSpec

LOG_RATIO = 20.0  # a range whose max/min is at least this is logarithmic
MAX_STEPS = 1000  # positions of a float or a wide integer range


def _round_sig(value: float, digits: int) -> float:
    if value == 0:
        return 0.0
    return round(value, digits - 1 - math.floor(math.log10(abs(value))))


@dataclass(frozen=True)
class ValueMap:
    minimum: float
    maximum: float
    integer: bool = False
    log: bool = False
    zero_off: bool = False
    unit: str = ""
    steps: int = MAX_STEPS  # positions between minimum and maximum (not counting "off")

    # --- positions -----------------------------------------------------------------------
    @property
    def offset(self) -> int:
        """1 when position 0 is the "off" value, so the range starts at position 1."""
        return 1 if self.zero_off else 0

    @property
    def pos_max(self) -> int:
        return self.steps + self.offset

    @property
    def decimals(self) -> int:
        if self.integer:
            return 0
        span = self.maximum - self.minimum
        return max(0, min(6, math.ceil(-math.log10(span / self.steps))))

    def clamp(self, value: float) -> float:
        if self.zero_off and value == 0:
            return 0
        return min(max(value, self.minimum), self.maximum)

    def from_pos(self, pos: int) -> float | int:
        pos = min(max(int(pos), 0), self.pos_max)
        if self.zero_off and pos == 0:
            return 0
        t = (pos - self.offset) / self.steps
        if self.log:
            value = self.minimum * (self.maximum / self.minimum) ** t
            value = _round_sig(value, 3)
        else:
            value = self.minimum + t * (self.maximum - self.minimum)
            value = round(value, self.decimals)
        value = self.clamp(value)
        return int(round(value)) if self.integer else float(value)

    def to_pos(self, value: float) -> int:
        if self.zero_off and value == 0:
            return 0
        value = self.clamp(value)
        if self.maximum == self.minimum:
            return self.offset
        if self.log:
            t = math.log(value / self.minimum) / math.log(self.maximum / self.minimum)
        else:
            t = (value - self.minimum) / (self.maximum - self.minimum)
        return self.offset + int(round(t * self.steps))

    def single_step(self) -> int:
        """Arrow key: 1 % of the travel (at least one position)."""
        return max(1, self.steps // 100)

    def page_step(self) -> int:
        return max(1, self.steps // 10)

    # --- text ----------------------------------------------------------------------------
    def format(self, value: float, with_unit: bool = True) -> str:
        if self.zero_off and value == 0:
            return "aus"
        if self.integer:
            text = str(int(round(value)))
        else:
            text = f"{value:.5g}"  # an exact preset value keeps its digits (0.35, 78.399)
            if "e" in text:
                text = f"{value:.0f}"
            text = text.replace(".", ",")
        return f"{text} {self.unit}".strip() if with_unit else text


def map_of(spec: FieldSpec) -> ValueMap:
    """The slider map of a numeric contract field."""
    if spec.kind not in ("int", "float"):
        raise ValueError(f"{spec.name} is not a number field")
    lo, hi = float(spec.minimum), float(spec.maximum)  # type: ignore[arg-type]
    integer = spec.kind == "int"
    log = lo > 0 and hi / lo >= LOG_RATIO and not integer
    steps = MAX_STEPS
    if integer and hi - lo <= MAX_STEPS:
        steps = int(hi - lo)
    return ValueMap(lo, hi, integer, log, spec.zero_ok, spec.unit, max(1, steps))
