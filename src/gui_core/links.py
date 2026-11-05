"""Linked parameters of a category form, derived from the contract and the engine (no Qt).

Nothing here copies a rule. Three sources:

* **Value limits.** For a numeric field the limits are found by asking the category's own
  ``resolve`` (``get_category(cat).resolve``): with all other fields as they are, which values
  of this field does the engine accept? The interval around the current value is found by
  probing the range ends and bisecting. The partners named in the limit come from the engine's
  own error line (field names it mentions).
* **Exclusions and requirements.** Read from the contract's ``dependentSchemas`` (``not
  required``: two fields exclude each other) and ``dependentRequired`` (a field needs another).
* **Derived values.** What the engine computes from a field that is consumed on resolve
  (``tail_note`` -> ``pitch_end_hz``, ``length_beats`` -> ``length_ms``) is read from the resolved
  form, not recomputed.

Texts are German; the engine's own (English) sentence is kept as ``engine_text``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from audio_engine.categories import get_category
from audio_engine.params import load_schema

from .form import CategoryFormModel, FieldSpec, schema_path
from .valuemap import map_of

BISECT_STEPS = 60  # upper bound; the loop ends when the edge is known to 2 % of a grid step
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


@dataclass(frozen=True)
class Limit:
    name: str
    lo: float  # allowed interval (inclusive); equals the contract range when not limited
    hi: float
    partners: tuple[str, ...]
    reason: str  # German, empty when not limited
    engine_text: str  # the engine's sentence for the first refused end

    @property
    def limited(self) -> bool:
        return bool(self.reason)


# --- contract rules between fields -----------------------------------------------------------

def exclusions(category: str) -> list[tuple[str, str]]:
    """``(a, b)``: giving ``a`` forbids ``b`` (contract ``dependentSchemas`` / not required)."""
    schema = load_schema(schema_path(category))
    pairs: list[tuple[str, str]] = []
    blocks = [schema.get("dependentSchemas", {})]
    for branch in schema.get("allOf", ()):
        blocks.append(branch.get("then", {}).get("dependentSchemas", {}))
    for block in blocks:
        for a, rule in block.items():
            pairs += [(a, b) for b in rule.get("not", {}).get("required", ())]
    return pairs


def requirements(category: str) -> dict[str, tuple[str, ...]]:
    """``{a: (b, ...)}``: giving ``a`` needs ``b`` (contract ``dependentRequired``)."""
    schema = load_schema(schema_path(category))
    out: dict[str, tuple[str, ...]] = {}
    blocks = [schema.get("dependentRequired", {})]
    for branch in schema.get("allOf", ()):
        blocks.append(branch.get("then", {}).get("dependentRequired", {}))
    for block in blocks:
        out.update({a: tuple(b) for a, b in block.items()})
    return out


def activate(model: CategoryFormModel, name: str) -> list[str]:
    """Switch ``name`` on together with what the contract demands; returns German notices.

    A field that excludes (or is excluded by) an active one switches that one off; a field that
    needs another switches it on. A later contract version's field also drags its siblings'
    version along (the model decides the ``schema_version`` itself).
    """
    notices: list[str] = []
    model.set_active(name, True)
    for a, b in exclusions(model.category):
        other = b if a == name else a if b == name else None
        if other and other in model.active and other != name and _known(model, other):
            model.set_active(other, False)
            notices.append(
                f"{_label(model, name)} und {_label(model, other)} schließen sich aus "
                f"(Kontrakt): {_label(model, other)} ist jetzt aus."
            )
    for need in requirements(model.category).get(name, ()):
        if need in model.active or not _known(model, need):
            continue
        model.set_active(need, True)
        notices.append(f"{_label(model, name)} braucht {_label(model, need)}: jetzt an.")
    return notices


def _known(model: CategoryFormModel, name: str) -> bool:
    return name in {s.name for s in model.specs}


def _label(model: CategoryFormModel, name: str) -> str:
    return model.spec(name).label


# --- value limits ----------------------------------------------------------------------------

def _accepts(model: CategoryFormModel, name: str, value: Any) -> tuple[bool, str]:
    try:
        get_category(model.category).resolve(model.probe_request(name, value))
    except ValueError as exc:
        return False, " ".join(str(exc).split())
    return True, ""


def _decimals(spec: FieldSpec) -> int:
    """Decimals of the limit grid: the slider's, at least 3 on a logarithmic range."""
    vmap = map_of(spec)
    return max(vmap.decimals, 3) if vmap.log else vmap.decimals


def _grid(spec: FieldSpec, value: float, up: bool) -> float | int:
    """Round ``value`` to the decimals the slider shows (``up``: ceil, else floor)."""
    if spec.kind == "int":
        return int(math.ceil(value) if up else math.floor(value))
    scale = 10 ** _decimals(spec)
    return (math.ceil(value * scale) if up else math.floor(value * scale)) / scale


def _bisect(model: CategoryFormModel, spec: FieldSpec, good: float, bad: float) -> float:
    """Last accepted value between a good and a refused one."""
    integer = spec.kind == "int"
    tolerance = 0.02 * 10.0 ** -_decimals(spec)
    for _ in range(BISECT_STEPS):
        if not integer and abs(bad - good) <= tolerance:
            break
        mid = (good + bad) / 2
        if integer:
            mid = math.floor(mid) if bad < good else math.ceil(mid)
            if mid in (good, bad):
                break
        value = int(mid) if integer else mid
        if _accepts(model, spec.name, value)[0]:
            good = mid
        else:
            bad = mid
    return good


def limit_of(model: CategoryFormModel, name: str) -> Limit:
    """The values of ``name`` the engine accepts, with everything else as it is now."""
    spec = model.spec(name)
    lo, hi = float(spec.minimum), float(spec.maximum)  # type: ignore[arg-type]
    free = Limit(name, lo, hi, (), "", "")
    if spec.kind not in ("int", "float") or spec.zero_ok or name == "length_beats":
        return free
    current, problem = model.parse(name)
    if problem or not _accepts(model, name, current)[0]:
        return free  # the state is already invalid: nothing to limit against
    new_lo, new_hi, text = lo, hi, ""
    for end, is_low in ((lo, True), (hi, False)):
        value = int(end) if spec.kind == "int" else end
        ok, message = _accepts(model, name, value)
        if ok:
            continue
        text = text or message
        # round inwards: a lower end rounds up, an upper end down
        edge = _grid(spec, _bisect(model, spec, float(current), float(end)), up=is_low)
        if not _accepts(model, name, edge)[0]:
            edge = current
        if is_low:
            new_lo = edge
        else:
            new_hi = edge
    if (new_lo, new_hi) == (lo, hi):
        return free
    partners = _partners(model, name, text)
    return Limit(name, new_lo, new_hi, partners, _reason(model, spec, new_lo, new_hi, partners),
                 text)


def _partners(model: CategoryFormModel, name: str, text: str) -> tuple[str, ...]:
    names = {s.name for s in model.specs}
    found = []
    for word in _WORD.findall(text):
        if word in names and word != name and word not in found:
            found.append(word)
    return tuple(found)


def _value_text(model: CategoryFormModel, name: str) -> str:
    spec = model.spec(name)
    value, problem = model.parse(name)
    if problem:
        return "?"
    if spec.kind in ("int", "float"):
        return map_of(spec).format(value)
    return str(value)


def _reason(model: CategoryFormModel, spec: FieldSpec, lo: float, hi: float,
            partners: tuple[str, ...]) -> str:
    vmap = map_of(spec)
    if lo > spec.minimum and hi < spec.maximum:  # type: ignore[operator]
        span = f"nur {vmap.format(lo, False)} bis {vmap.format(hi)}"
    elif lo > spec.minimum:  # type: ignore[operator]
        span = f"mindestens {vmap.format(lo)}"
    else:
        span = f"höchstens {vmap.format(hi)}"
    because = ", ".join(f"{_label(model, p)} = {_value_text(model, p)}" for p in partners)
    tail = f", solange {because}" if because else " (Regel des Kontrakts)"
    return f"{spec.label}: {span}{tail}."


def _nearest_accepted(model: CategoryFormModel, name: str) -> float | int | None:
    """The value of ``name`` closest to the current one that the engine accepts with every other
    field as it is, or ``None``. Coarse scan over the slider positions, then bisection to the
    edge on the side of the current value."""
    spec = model.spec(name)
    vmap = map_of(spec)
    current, problem = model.parse(name)
    if problem:
        return None
    stride = max(1, vmap.pos_max // 60)
    positions = sorted({*range(0, vmap.pos_max + 1, stride), vmap.pos_max})
    here = vmap.to_pos(current)
    good = [p for p in positions if _accepts(model, name, vmap.from_pos(p))[0]]
    if not good:
        return None
    best = min(good, key=lambda p: abs(p - here))
    value = vmap.from_pos(best)
    toward = [p for p in positions if (p > best) == (here > best) and p != best]
    if toward:  # the grid point next to ``best`` on the side of the current value is refused
        bad_pos = min(toward, key=lambda p: abs(p - best))
        bad = vmap.from_pos(bad_pos)
        if not _accepts(model, name, bad)[0]:
            edge = _bisect(model, spec, float(value), float(bad))
            edge = _grid(spec, edge, up=bad < value)
            if _accepts(model, name, edge)[0]:
                value = edge
    return int(value) if spec.kind == "int" else float(value)


MAX_REPAIRS = 6


@dataclass(frozen=True)
class Repair:
    notices: list[str]  # German, one per moved field
    moved: list[str]  # names of the fields that were moved


def repair(model: CategoryFormModel, changed: str | None = None) -> Repair:
    """Bring a refused combination back into what the engine accepts; German notices.

    Called after a change that the per-field limits cannot see (a field switched off, a choice
    such as the sample rate changed). The engine's own error line names the fields involved;
    the one (not ``changed``) that can be moved the least makes the form valid again and is set
    to the nearest accepted value. Nothing changes when the form is valid or no single field
    can fix it; the caller then still has the engine's message ("Ungültige Kombination").
    """
    notices: list[str] = []
    moved: list[str] = []
    for _ in range(MAX_REPAIRS):
        issue = model.cross_issue()
        if issue is None:
            break
        names = {s.name for s in model.specs}
        involved = [w for w in dict.fromkeys(_WORD.findall(issue)) if w in names]
        best: tuple[float, str, float | int] | None = None
        for name in involved:
            spec = model.spec(name)
            if (name == changed or name not in model.active or spec.kind not in ("int", "float")
                    or spec.zero_ok or name == "length_beats"):
                continue
            value = _nearest_accepted(model, name)
            if value is None:
                continue
            vmap = map_of(spec)
            cost = abs(vmap.to_pos(model.parse(name)[0]) - vmap.to_pos(value))
            if best is None or cost < best[0]:
                best = (cost, name, value)
        if best is None:
            break
        _, name, value = best
        moved.append(name)
        spec = model.spec(name)
        model.set_text(name, repr(value) if isinstance(value, float) else str(value))
        others = ", ".join(_label(model, w) for w in involved if w != name) or "den anderen Feldern"
        notices.append(
            f"{spec.label} wurde auf {map_of(spec).format(value)} gesetzt, damit die Kombination "
            f"mit {others} gültig bleibt (Regel des Kontrakts)."
        )
    return Repair(notices, moved)


def limits(model: CategoryFormModel, skip: str | None = None) -> dict[str, Limit]:
    """Limits of every numeric field (``skip``: the field being edited right now)."""
    return {
        s.name: limit_of(model, s.name)
        for s in model.specs
        if s.kind in ("int", "float") and s.name != skip
    }


# --- derived values --------------------------------------------------------------------------

@dataclass(frozen=True)
class Derived:
    shown: dict[str, Any]  # inactive field -> the value the engine uses (default or derived)
    notes: dict[str, str]  # consumed active field -> German text of what the engine made of it


def derived_values(model: CategoryFormModel, heavy: bool = False) -> Derived:
    """What the engine derives, read from the resolved form (nothing is recomputed here).

    ``shown``: an inactive field's resolved value (its default, or derived like ``amp_decay_ms``
    under ``length_beats``). ``notes``: for a field the engine consumes (``tail_note``,
    ``length_beats``) the value of its excluded partner (``pitch_end_hz``, ``length_ms``).
    ``length_beats`` renders the kick (about 0.3 s the first time), so it is only resolved with
    ``heavy=True``. Empty when the form is invalid.
    """
    empty = Derived({}, {})
    if model.field_issues():
        return empty
    request = model._request_unchecked()
    if "length_beats" in request and not heavy:
        request.pop("length_beats")
    try:
        resolved = get_category(model.category).resolve(request)
    except ValueError:
        return empty
    shown = {
        s.name: resolved[s.name]
        for s in model.specs if s.name not in model.active and s.name in resolved
    }
    notes: dict[str, str] = {}
    for a, b in exclusions(model.category):
        if a in request and b in resolved and b not in request:
            spec = model.spec(b)
            notes[a] = f"= {map_of(spec).format(resolved[b])} ({spec.label}, vom Engine abgeleitet)"
    return Derived(shown, notes)
