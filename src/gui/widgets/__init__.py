"""Shared widget kit: sliders, knobs, switches, button rows and chips on contract values.

Every widget has an offscreen test in ``tests/gui/test_widgets.py``; the logic they share
(value mapping, links between parameters) lives in ``gui_core`` and has no Qt."""

from .choice import FlowLayout, PresetChips, Segmented
from .controls import (
    BoolControl,
    ChoiceControl,
    ListControl,
    NumberControl,
    ParamControl,
    ReadoutEdit,
    SeedControl,
)
from .mapped import KnobDial, MappedSlider, TrackSlider
from .section import Collapsible, StepEdit, heading, muted, rule
from .stepper import Stepper
from .toggle import ActiveDot, Toggle, ToggleRow

__all__ = [
    "ActiveDot", "BoolControl", "ChoiceControl", "Collapsible", "FlowLayout", "KnobDial",
    "ListControl", "MappedSlider", "NumberControl", "ParamControl", "PresetChips", "ReadoutEdit",
    "SeedControl", "Segmented", "StepEdit", "Stepper", "Toggle", "ToggleRow", "TrackSlider",
    "heading", "muted", "rule",
]
