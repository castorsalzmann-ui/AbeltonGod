"""Parameter controls of the widget kit: one class per kind of contract field, all with the same
small interface so a page can treat them alike.

Interface (signals use the contract field name):

* ``edited(name, value)``: the user changed the value (number for number fields, the model text
  such as ``"48000"`` / ``"ja"`` for choices). Programmatic ``set_value`` never emits.
* ``activeToggled(name, on)``: the user clicked the dot ("send this value" / "use the default").
* ``committed(name)``: a drag, key press or typed entry is finished (heavier updates may run).
* ``resetRequested(name)``: double click on a slider or knob.
* ``set_value`` / ``set_active`` / ``set_limits`` / ``set_derived_note`` / ``set_edit_note`` /
  ``set_invalid``: show state.

A number control keeps the exact value it is given; dragging produces rounded values; a typed
value is clamped into the contract range and the limits of linked parameters.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui_core.form import FieldSpec, parse_number
from gui_core.valuemap import ValueMap, map_of

from .choice import Segmented, WrapSegmented
from .mapped import KnobDial, MappedSlider, TrackSlider
from .section import StepEdit
from .toggle import ActiveDot, Toggle

CHOICE_COLUMN_M = 14  # a choice row beside its 15 M label fits the width of a slider row


class ReadoutEdit(QLineEdit):
    """The value as text next to a slider; typing a number and pressing Enter sets it."""

    entered = Signal(str)

    def __init__(self, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignRight) -> None:
        super().__init__()
        self.setObjectName("readout")
        self.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        self._shown = ""
        self.editingFinished.connect(self._finished)

    def show_text(self, text: str, muted: bool = False) -> None:
        self._shown = text
        if self.text() != text:
            self.setText(text)
        if bool(self.property("muted")) != muted:  # re-polish only when the look changes
            self.setProperty("muted", muted)
            self.style().unpolish(self)
            self.style().polish(self)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if event.key() == Qt.Key.Key_Escape:
            self.setText(self._shown)
            self.clearFocus()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _finished(self) -> None:
        if self.text() != self._shown:
            self.entered.emit(self.text())


class ParamControl(QWidget):
    edited = Signal(str, object)
    activeToggled = Signal(str, bool)
    committed = Signal(str)
    resetRequested = Signal(str)

    def __init__(self, spec: FieldSpec, always_active: bool = False, accent: bool = False) -> None:
        super().__init__()
        self.spec = spec
        self.name = spec.name
        self.accent = accent
        self.always_active = always_active
        self.dot = ActiveDot()
        self.dot.accent = accent
        self.dot.setVisible(not always_active)
        policy = self.dot.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # rows stay aligned without a dot
        self.dot.setSizePolicy(policy)
        self.dot.toggled.connect(lambda on: self.activeToggled.emit(self.name, on))
        self.label = QLabel(spec.label)
        self.label.setToolTip(spec.description)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.note.hide()
        self._limit_reason = ""  # why a linked parameter limits this field (German)
        self.edit_note = ""  # what happened to the last typed value; stays until the next edit
        self.derived_note = ""  # what the engine made of this field
        self.show_limit_note = False  # slider rows show the limit under the slider
        self._active = True
        self.setToolTip(spec.description)

    # --- state shown by the page -------------------------------------------------------------
    def set_active(self, on: bool) -> None:
        self._active = on or self.always_active
        self.dot.blockSignals(True)
        self.dot.setChecked(self._active)
        self.dot.blockSignals(False)
        self._after_active()

    def is_active(self) -> bool:
        return self._active

    def _after_active(self) -> None:  # subclasses restyle
        pass

    def _finish(self, row: QHBoxLayout) -> None:
        """Lay out ``row`` with the note label below it (the note is never parentless)."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(row)
        outer.addWidget(self.note)

    def _show_note(self) -> None:
        """One line below the control: the typed-value note first, then the engine's derived
        value, then (slider rows only) the limit reason."""
        if self.edit_note:
            text, error = self.edit_note, True
        elif self.derived_note:
            text, error = self.derived_note, False
        elif self.show_limit_note and self._limit_reason:
            text, error = self._limit_reason, True
        else:
            text, error = "", False
        name = "linkhint" if error else "muted"
        if self.note.objectName() != name:
            self.note.setObjectName(name)
            self.note.style().unpolish(self.note)
            self.note.style().polish(self.note)
        self.note.setText(text)
        self.note.setVisible(bool(text))

    @property
    def limit_reason(self) -> str:
        self._want_limits()
        return self._limit_reason

    def _want_limits(self) -> None:  # NumberControl: ask the page for fresh limits
        pass

    def set_derived_note(self, text: str) -> None:
        self.derived_note = text
        self._show_note()

    def set_edit_note(self, text: str) -> None:
        self.edit_note = text
        self._show_note()

    def clear_edit_note(self) -> None:
        if self.edit_note:
            self.set_edit_note("")

    def set_invalid(self, message: str | None) -> None:
        self.setToolTip(message or self.spec.description)


class NumberControl(ParamControl):
    """A number field as a slider row (``style="row"``) or as a knob (``style="knob"``).

    ``limitsWanted(name)`` is emitted (synchronously) right before the limits are read: by a
    user move, a typed value, or code reading ``limits`` / ``limit_reason``. A page that keeps
    only the limits of visible controls up to date (#434) brings this one up to date first.
    """

    limitsWanted = Signal(str)

    def __init__(self, spec: FieldSpec, style: str = "row", always_active: bool = False,
                 accent: bool = False, vmap: ValueMap | None = None) -> None:
        super().__init__(spec, always_active, accent)
        self.vmap = vmap or map_of(spec)
        self.style_name = style
        self._value: float = self.vmap.minimum
        em = self.fontMetrics().horizontalAdvance("M")
        self.readout = ReadoutEdit(Qt.AlignmentFlag.AlignRight if style == "row"
                                   else Qt.AlignmentFlag.AlignHCenter)
        self.readout.setAccessibleName(spec.label)
        self.readout.entered.connect(self._typed)
        if style == "knob":
            self.slider: MappedSlider = KnobDial(self.vmap, accent=True)
            self.readout.setFixedWidth(em * 7)
            self.label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.label.setWordWrap(True)
            # Always room for two label lines, so a wrapped label ("Klang (dunkel/hell)") does
            # not move its knob against the others in the row (#467).
            self.label.setFixedHeight(self.fontMetrics().lineSpacing() * 2 + 2)
            self.label.setObjectName("muted")
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            lay.addWidget(self.slider, 0, Qt.AlignmentFlag.AlignHCenter)
            lay.addWidget(self.readout, 0, Qt.AlignmentFlag.AlignHCenter)
            row = QHBoxLayout()
            row.setSpacing(4)
            row.addStretch(1)
            row.addWidget(self.dot)
            row.addWidget(self.label)
            row.addStretch(1)
            lay.addLayout(row)
            self.note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lay.addWidget(self.note)  # a wrapped line under the knob (clamped entry)
            lay.addStretch(1)  # extra height goes below, the dial stays at the top
            # 9 M, or what dot + label need (Windows CI: 110 > 108, the label was cut, #517)
            self.setFixedWidth(max(em * 9, lay.minimumSize().width()))
        else:
            self.slider = TrackSlider(self.vmap, accent=accent)
            self.readout.setFixedWidth(em * 8)
            self.label.setFixedWidth(em * 15)
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            row = QHBoxLayout()
            row.addWidget(self.dot)
            row.addWidget(self.label)
            row.addWidget(self.slider, 1)
            row.addWidget(self.readout)
            outer.addLayout(row)
            outer.addWidget(self.note)
            self.show_limit_note = True
        self.slider.setAccessibleName(spec.label)
        self.slider.setToolTip(spec.description)
        self.slider.aboutToMove.connect(self._want_limits)
        self.slider.userChanged.connect(self._slid)
        self.slider.released.connect(lambda: self.committed.emit(self.name))
        self.slider.resetRequested.connect(lambda: self.resetRequested.emit(self.name))
        self.set_value(self.vmap.clamp(spec.default) if isinstance(spec.default, int | float)
                       else self.vmap.minimum)

    # --- value ---------------------------------------------------------------------------------
    def value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        self._value = self.vmap.clamp(value)
        self.slider.set_value(self._value)
        self.readout.show_text(self.vmap.format(self._value), muted=not self._active)

    def _after_active(self) -> None:
        self.slider.inactive = not self._active
        self.slider.update()
        self.readout.show_text(self.vmap.format(self._value), muted=not self._active)

    def set_limits(self, lo: float, hi: float, reason: str = "") -> None:
        self.slider.set_limits(lo, hi)
        self._limit_reason = reason
        self.slider.setToolTip((self.spec.description + "\n\n" + reason).strip())
        self._show_note()

    @property
    def limits(self) -> tuple[float, float]:
        self._want_limits()
        return self.slider.limits

    def _want_limits(self) -> None:
        self.limitsWanted.emit(self.name)

    def is_dragging(self) -> bool:
        return self.slider.is_dragging()

    def _slid(self, value: float) -> None:
        self.clear_edit_note()
        self._value = value
        self.readout.show_text(self.vmap.format(value), muted=False)
        self.edited.emit(self.name, value)

    def _typed(self, text: str) -> None:
        """Typed entry: a number, with or without the unit; clamped, never refused."""
        raw = text.strip()
        if self.vmap.zero_off and raw.lower() == "aus":
            number: float | None = 0
        else:
            unit = self.vmap.unit
            number = parse_number(re.sub(re.escape(unit) + r"\s*$", "", raw).strip()
                                  if unit else raw)
        if number is None:
            self.readout.show_text(self.vmap.format(self._value), muted=not self._active)
            self.set_edit_note("Bitte eine Zahl eingeben.")
            return
        value = self.vmap.clamp(number)
        lo, hi = self.limits  # the page may bring stale limits up to date first
        if not (self.vmap.zero_off and value == 0):
            if lo > self.vmap.minimum:
                value = max(value, lo)
            if hi < self.vmap.maximum:
                value = min(value, hi)
        outside = value != number
        if self.vmap.integer:
            value = int(round(value))  # an int the user typed into a float field stays an int
        off_grid = False
        if self.vmap.grid and not (self.vmap.zero_off and value == 0):
            snapped = self.vmap.snap(value, max(lo, self.vmap.minimum),
                                     min(hi, self.vmap.maximum))
            off_grid, value = snapped != value, snapped
        if outside:
            self.set_edit_note(f"{raw} liegt außerhalb des erlaubten Bereichs, gesetzt auf "
                               f"{self.vmap.format(value)}.")
        elif off_grid:
            self.set_edit_note(f"{raw} liegt nicht auf dem Raster von "
                               f"{self.vmap.format(self.vmap.grid)}, gesetzt auf "
                               f"{self.vmap.format(value)}.")
        elif value != number:
            self.set_edit_note(f"{raw} ist keine ganze Zahl, gesetzt auf "
                               f"{self.vmap.format(value)}.")
        else:
            self.clear_edit_note()
        self.set_value(value)
        self.edited.emit(self.name, value)
        self.committed.emit(self.name)


class SeedControl(ParamControl):
    """Integer field without a useful slider (seed): a plain editable number with Up/Down."""

    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec, always_active=True)
        em = self.fontMetrics().horizontalAdvance("M")
        self.edit = StepEdit()
        self.edit.setAccessibleName(spec.label)
        self.edit.setFixedWidth(em * 12)
        self.edit.setToolTip(spec.description)
        self.edit.edited.connect(self._typed)
        self.label.setFixedWidth(em * 15)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.dot)  # hidden, keeps the label column aligned
        row.addWidget(self.label)
        # The range sits under the field, not beside it: beside it the seed row was the widest
        # row of a page (37.7 M; #442, 1920 x 1080 at 150 %).
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.edit)
        self.range_label = QLabel(spec.range_text)
        self.range_label.setObjectName("muted")
        self.range_label.setWordWrap(True)
        self.range_label.setFixedWidth(em * 12)
        column.addWidget(self.range_label)
        row.addLayout(column)
        row.addStretch(1)
        self._finish(row)

    def set_value(self, value: int | str) -> None:
        if self.edit.text() != str(value):
            self.edit.setText(str(value))

    def _typed(self, text: str) -> None:
        """The raw text goes to the model, which decides (an invalid seed blocks Render)."""
        self.edited.emit(self.name, text)
        self.committed.emit(self.name)

    def set_invalid(self, message: str | None) -> None:
        super().set_invalid(message)
        self.edit.setToolTip(message or self.spec.description)
        if bool(self.edit.property("invalid")) != bool(message):
            self.edit.setProperty("invalid", bool(message))
            self.edit.style().unpolish(self.edit)
            self.edit.style().polish(self.edit)


class ListControl(ParamControl):
    """List field (atmos ``intervals``, #533): the model text ``"0, 7, 12"`` in a line edit,
    with the allowed form under it. The model checks the text; an invalid list blocks Render."""

    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        self.setAccessibleName(spec.label)  # stable name for the control inventory
        em = self.fontMetrics().horizontalAdvance("M")
        self.edit = ReadoutEdit(Qt.AlignmentFlag.AlignLeft)
        self.edit.setAccessibleName(spec.label)
        self.edit.setToolTip(spec.description)
        self.edit.setFixedWidth(em * 12)
        self.edit.entered.connect(self._typed)
        self.label.setFixedWidth(em * 15)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.dot)
        row.addWidget(self.label)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.edit)
        self.range_label = QLabel(spec.range_text)
        self.range_label.setObjectName("muted")
        self.range_label.setWordWrap(True)
        self.range_label.setFixedWidth(em * 12)
        column.addWidget(self.range_label)
        row.addLayout(column)
        row.addStretch(1)
        self._finish(row)

    def set_value(self, text: str) -> None:
        self.edit.show_text(text, muted=not self._active)

    def value(self) -> str:
        return self.edit.text()

    def _after_active(self) -> None:
        self.edit.show_text(self.edit.text(), muted=not self._active)

    def _typed(self, text: str) -> None:
        self.edited.emit(self.name, text)
        self.committed.emit(self.name)

    def set_invalid(self, message: str | None) -> None:
        super().set_invalid(message)
        self.edit.setToolTip(message or self.spec.description)
        if bool(self.edit.property("invalid")) != bool(message):
            self.edit.setProperty("invalid", bool(message))
            self.edit.style().unpolish(self.edit)
            self.edit.style().polish(self.edit)


class ChoiceControl(ParamControl):
    """Enum field as buttons; values are the model texts of the choices."""

    def __init__(self, spec: FieldSpec, accent: bool = False) -> None:
        super().__init__(spec, accent=accent)
        em = self.fontMetrics().horizontalAdvance("M")
        self.texts = list(spec.choice_texts)
        # 20 characters: perc `model` (5 choices, 26 characters) measured 438 px as one row on
        # Windows CI, above the 34 M page (408 px); every other enum is <= 15 or >= 29 (#475).
        wide = len(self.texts) > 5 or sum(len(t) for t in self.texts) > 20
        self.seg = (WrapSegmented(self.texts) if wide else Segmented(self.texts, accent=accent))
        self.seg.setAccessibleName(spec.label)
        self.seg.setToolTip(spec.description)
        self.seg.chosen.connect(self._chosen)
        self.label.setFixedWidth(em * 15)
        row = QHBoxLayout()
        row.addWidget(self.dot)
        row.addWidget(self.label)
        # A button row wider than its column (the platform font decides: hat "model" is
        # 330 px on Linux, wider on Windows; #442) goes under the label, so the row never needs
        # more than a slider row.
        self.stacked = self.seg.minimumSizeHint().width() > em * CHOICE_COLUMN_M
        if self.stacked:
            row.addStretch(1)
            self._finish(row)
            self.layout().insertWidget(1, self.seg)
        else:
            row.addWidget(self.seg, 1)
            self._finish(row)

    def set_value(self, text: str) -> None:
        self.seg.set_index(self.texts.index(text) if text in self.texts else -1)

    def value(self) -> str:
        i = self.seg.index()
        return self.texts[i] if i >= 0 else ""

    def _after_active(self) -> None:
        self.seg.setEnabled(True)  # a touch activates the field, like the sliders
        self.seg.setWindowOpacity(1.0)
        self.seg.setProperty("inactive", not self._active)

    def _chosen(self, index: int) -> None:
        self.edited.emit(self.name, self.texts[index])
        self.committed.emit(self.name)


class BoolControl(ParamControl):
    """Boolean field as a switch; values are the model texts ``"ja"`` / ``"nein"``."""

    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec)
        em = self.fontMetrics().horizontalAdvance("M")
        self.texts = list(spec.choice_texts)  # ("nein", "ja")
        self.toggle = Toggle()
        self.toggle.setAccessibleName(spec.label)
        self.toggle.setToolTip(spec.description)
        self.toggle.toggled.connect(self._toggled)
        self.label.setFixedWidth(em * 15)
        row = QHBoxLayout()
        row.addWidget(self.dot)
        row.addWidget(self.label)
        row.addWidget(self.toggle)
        row.addStretch(1)
        self._finish(row)

    def set_value(self, text: str) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(text == self.texts[1])
        self.toggle.blockSignals(False)

    def value(self) -> str:
        return self.texts[1] if self.toggle.isChecked() else self.texts[0]

    def _toggled(self, on: bool) -> None:
        self.edited.emit(self.name, self.texts[1 if on else 0])
        self.committed.emit(self.name)
