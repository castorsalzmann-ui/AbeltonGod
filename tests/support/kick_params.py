"""One shared, seeded kick-params generator for property tests (#105, QA report #69 item 4).

Why: five test modules had their own copy of the same uniform draw and drifted apart (one
draws ``drive`` from 0.01, two never draw ``bit_depth``, none drew ``bpm``). Now every
property generator in ``tests/audio_engine/`` goes through :func:`draw` with a named
:class:`Profile`, and the ranges come from ``contracts/kick-params.schema.json`` (read here as
plain JSON, not through the engine's own schema loader).

- **Ranges from the contract.** Numbers are drawn uniformly over ``[minimum, maximum]``,
  integers over every allowed value, enums over their members, strings up to ``maxLength``.
  A schema range change therefore changes the draws without a code change here; a new
  optional field under ``properties`` is drawn by :data:`ALL` at once (fields in ``allOf``
  branches are not: see :data:`DRAWN_SCHEMA_VERSION`). The render profiles keep their fixed field
  lists (adding a field to them changes every default draw, so that is a decision for the
  owning role, made in an issue).
- **Contract rule outside the schema:** ``pitch_end_hz <= pitch_start_hz``. When both are
  drawn, ``pitch_end_hz`` is drawn up to ``min(maximum, pitch_start_hz)``.
- **Byte-identical defaults.** Each profile keeps the draw order and key order of the copy it
  replaces, so the default parameter sets are the same bytes as before (PR evidence; pinned
  by ``tests/qa/test_kick_params.py``).
- **Fresh seeds.** ``pytest --fresh-seeds=<n>`` (``tests/conftest.py``) calls
  :func:`set_fresh_seeds`. :func:`rng` and :func:`np_rng` then seed with
  ``base + n * 2**32``, so a reviewer reruns every property test on new sets without
  writing a generator. All test seeds in the repo are below ``2**32``, so the shifted
  streams never coincide with a default one. ``n = 0`` (the default) changes nothing.
  Expect parametrize ids that contain a drawn value (e.g. ``seed<kick seed>``) to change.
  A kick ``seed`` *value* used directly (not as an RNG seed) goes through :func:`kick_seed`
  instead: it stays inside the contract's seed range (#119).
- **Bounds (#119).** Numbers and integers are drawn only over a bounded range: a field without
  ``minimum``/``exclusiveMinimum`` or ``maximum``/``exclusiveMaximum`` is refused with a
  ValueError when a profile containing it is defined (``ALL`` at import), never drawn from an
  invented range. ``exclusiveMinimum``/``exclusiveMaximum`` are honoured: integers move the
  bound inwards, numbers redraw a value that lands on an open bound (fields with only closed
  bounds draw exactly as before, so the default sets keep their bytes).

Works with ``random.Random`` and ``numpy.random.Generator``; numpy results are converted to
plain ``int``/``float`` (the render cache only keys plain values).
"""

from __future__ import annotations

import json
import math
import random
import string
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "contracts" / "kick-params.schema.json"
SCHEMA: dict[str, Any] = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
FIELDS: dict[str, dict[str, Any]] = SCHEMA["properties"]

# The schema version every draw carries. Pinned, not read from the contract: since v0.3
# (PR #114) ``schema_version`` is an enum (``["0.2", "0.3"]``) and the v0.3 fields live in an
# ``allOf`` branch, not under ``properties``. The generator draws only ``properties`` fields
# (also :data:`ALL`), which is exactly a v0.2 set, so the sets say "0.2" as before (#137).
# Moving to "0.3" changes every default draw: a decision for the owning role, in an issue.
DRAWN_SCHEMA_VERSION = "0.2"


def checked_schema_version(schema: Mapping[str, Any], version: str = DRAWN_SCHEMA_VERSION) -> str:
    """``version`` if the contract allows it for a ``properties``-only set, else ValueError.

    Accepts ``schema_version`` as ``const`` (up to v0.2) or ``enum`` (v0.3 on). Refuses a
    version that an ``allOf`` branch keys on: such a set would allow fields not drawn here.
    """
    spec = schema["properties"]["schema_version"]
    allowed = [spec["const"]] if "const" in spec else list(spec.get("enum", []))
    if version not in allowed:
        raise ValueError(f"schema_version {version!r} not allowed by the contract: {allowed}")
    for branch in schema.get("allOf", []):
        cond = branch.get("if", {}).get("properties", {}).get("schema_version", {})
        if cond.get("const") == version or version in cond.get("enum", []):
            raise ValueError(f"schema_version {version!r} has an allOf branch: not drawn here")
    return version


SCHEMA_VERSION: str = checked_schema_version(SCHEMA)

# Cross-field rule of the contract that JSON Schema cannot express: field <= other field.
UPPER_BOUND_BY = {"pitch_end_hz": "pitch_start_hz"}

# Characters for drawn strings (``preset``): plain, file-name safe.
STRING_ALPHABET = string.ascii_letters + string.digits + "-_"

SEED_SHIFT = 2**32
_fresh = 0


def set_fresh_seeds(n: int) -> None:
    """Shift every seed base by ``n * 2**32`` (0 = the default, byte-identical sets)."""
    global _fresh
    if type(n) is not int or n < 0:
        raise ValueError(f"fresh seeds must be an int >= 0, got {n!r}")
    _fresh = n


def fresh_seeds() -> int:
    return _fresh


def seed(base: int) -> int:
    """The seed actually used for ``base`` under the current ``--fresh-seeds`` value."""
    return base + _fresh * SEED_SHIFT


def rng(base: int) -> random.Random:
    return random.Random(seed(base))


def np_rng(base: int) -> np.random.Generator:
    return np.random.default_rng(seed(base))


# Odd step (2**32 / golden ratio), so ``n * step`` is a multiple of 2**32 only for n = 0 (mod
# 2**32): every fresh value moves every kick seed, and the shift is a permutation of the range.
KICK_SEED_STEP = 0x9E3779B1


def kick_seed(value: int) -> int:
    """A kick ``seed`` value (not an RNG seed) under the current ``--fresh-seeds`` value.

    ``value`` itself at fresh 0. Otherwise shifted by ``n * KICK_SEED_STEP`` and wrapped into
    the contract's ``seed`` range, so it stays a valid kick seed (``seed(value)`` would leave
    the range: the contract maximum is 2**32 - 1).
    """
    lo, hi = FIELDS["seed"]["minimum"], FIELDS["seed"]["maximum"]
    if not lo <= value <= hi:
        raise ValueError(f"kick seed {value} outside the contract range {lo}..{hi}")
    if _fresh == 0:
        return value
    return lo + (value - lo + _fresh * KICK_SEED_STEP) % (hi - lo + 1)


@dataclass(frozen=True)
class Profile:
    """What one property generator draws.

    ``fields`` is the draw order (it decides the bytes). ``ranges`` narrows a field to a
    sub-range of the contract (checked). ``zero_spike`` fields are ``0.0`` with probability
    1/2, else uniform (``choice([0.0, uniform])``, uniform drawn first). ``keys`` is the key
    order of the result if it differs from the draw order. ``why`` says why it is narrower
    than :data:`RENDER`.
    """

    name: str
    fields: tuple[str, ...]
    ranges: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    zero_spike: tuple[str, ...] = ()
    keys: tuple[str, ...] | None = None
    why: str = ""

    def __post_init__(self) -> None:
        unknown = set(self.fields) - set(FIELDS)
        if unknown:
            raise ValueError(f"{self.name}: not in the kick-params schema: {sorted(unknown)}")
        for name in self.fields:
            if FIELDS[name].get("type") in ("number", "integer") and "enum" not in FIELDS[name]:
                bounds(name)  # refuses an unbounded field here, not at the first draw
            if FIELDS[name].get("type") == "string" and "maxLength" not in FIELDS[name]:
                raise ValueError(f"kick-params field {name!r}: string without maxLength")
        for name, (lo, hi) in self.ranges.items():
            c_lo, c_hi, lo_open, hi_open = bounds(name)
            low_ok = c_lo < lo if lo_open else c_lo <= lo
            high_ok = hi < c_hi if hi_open else hi <= c_hi
            if not (low_ok and lo <= hi and high_ok):
                raise ValueError(f"{self.name}: {name} {lo}..{hi} outside {c_lo}..{c_hi}")
        for name in self.zero_spike:
            if bounds(name)[2]:
                raise ValueError(f"{self.name}: {name} has an open minimum, no zero spike")
        for low, high in UPPER_BOUND_BY.items():
            if low in self.fields and high in self.fields:
                if self.fields.index(high) > self.fields.index(low):
                    raise ValueError(f"{self.name}: {high} must be drawn before {low}")
        if self.keys is not None and sorted(self.keys) != sorted(self.fields):
            raise ValueError(f"{self.name}: keys must be a permutation of fields")


def spec_bounds(name: str, spec: Mapping[str, Any]) -> tuple[float, float, bool, bool]:
    """``(lo, hi, lo_open, hi_open)`` of a number or integer field, or ValueError.

    The stricter of ``minimum`` and ``exclusiveMinimum`` wins (same for the maximum). Integer
    bounds are moved inwards to the nearest allowed integer, so they are always closed.
    Refused: a missing side, a boolean ``exclusive*`` (draft-4 form, not this contract's
    draft 2020-12), and an empty range.
    """
    for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if key in spec and (isinstance(spec[key], bool) or not isinstance(spec[key], int | float)):
            raise ValueError(f"kick-params field {name!r}: {key} must be a number, got "
                             f"{spec[key]!r}")
    sides = []
    for closed, open_, pick in (("minimum", "exclusiveMinimum", max),
                                ("maximum", "exclusiveMaximum", min)):
        if closed not in spec and open_ not in spec:
            raise ValueError(
                f"kick-params field {name!r} has no {closed} or {open_}: the generator draws "
                "only bounded ranges (give the field a bound in the contract)")
        if closed in spec and open_ in spec:
            bound = pick(spec[closed], spec[open_])
            is_open = bound == spec[open_]  # equal values: the open bound is the stricter
        else:
            is_open = open_ in spec
            bound = spec[open_] if is_open else spec[closed]
        sides.append((bound, is_open))
    (lo, lo_open), (hi, hi_open) = sides
    if spec.get("type") == "integer":
        lo = math.floor(lo) + 1 if lo_open else math.ceil(lo)
        hi = math.ceil(hi) - 1 if hi_open else math.floor(hi)
        lo_open = hi_open = False
    if lo > hi or (lo == hi and (lo_open or hi_open)):
        raise ValueError(f"kick-params field {name!r}: empty range {spec}")
    return lo, hi, lo_open, hi_open


def bounds(name: str) -> tuple[float, float, bool, bool]:
    return spec_bounds(name, FIELDS[name])


def number_range(name: str) -> tuple[float, float]:
    lo, hi, _, _ = bounds(name)
    return lo, hi


def drawable_fields() -> tuple[str, ...]:
    """Every ``properties`` field except ``schema_version``, in schema order.

    Fields in ``allOf`` branches (the v0.3 fields ``tail_note``, ``length_beats``, ...) are not
    drawn, by any profile including :data:`ALL`: they need ``schema_version`` "0.3", which the
    engine refuses until it renders them (#137).
    """
    return tuple(n for n, s in FIELDS.items() if n != "schema_version" and "const" not in s)


# The render fields of v0.2 in the draw order of the former copies (test_kick.random_params,
# test_shaping._draw). Not drawn by any render profile: variants (batch-only), bpm (sidecar
# metadata), preset (a label); ALL draws them.
RENDER = Profile(
    "render",
    (
        "seed", "sample_rate", "bit_depth", "length_ms", "pitch_start_hz", "pitch_decay_ms",
        "amp_attack_ms", "amp_decay_ms", "click_level", "click_tone_hz", "drive", "tone",
        "peak_ceiling_dbfs", "pitch_end_hz",
    ),
)
NOT_RENDER_DRAWN = {
    "variants": "batch-only, dropped before rendering",
    "bpm": "sidecar metadata, does not change the render",
    "preset": "a label, does not change the render",
}

NO_DRIVE = Profile(
    "no_drive",
    tuple(f for f in RENDER.fields if f != "drive"),
    zero_spike=("amp_attack_ms",),
    why="test_drive_continuity: each test sets drive itself; amp_attack_ms is 0 half the time",
)

SETTLE = Profile(
    "settle",
    tuple(f for f in RENDER.fields if f not in ("bit_depth", "pitch_decay_ms")),
    why="test_contract_semantics: the guideline check picks pitch_decay_ms itself and "
    "measures the float render (bit_depth has no effect there)",
)

ALIASING = Profile(
    "aliasing",
    (
        "pitch_start_hz", "seed", "sample_rate", "length_ms", "pitch_end_hz", "pitch_decay_ms",
        "amp_attack_ms", "amp_decay_ms", "click_level", "click_tone_hz", "drive", "tone",
    ),
    ranges={"drive": (0.01, 1)},
    zero_spike=("amp_attack_ms",),
    keys=(
        "seed", "sample_rate", "length_ms", "pitch_start_hz", "pitch_end_hz", "pitch_decay_ms",
        "amp_attack_ms", "amp_decay_ms", "click_level", "click_tone_hz", "drive", "tone",
    ),
    why="test_drive_aliasing: normalisation is patched out (no peak_ceiling_dbfs, bit_depth) "
    "and aliasing needs some drive (>= 0.01)",
)

# Coverage only: every field of the schema, including fields added later.
ALL = Profile("all", drawable_fields())

PROFILES = {p.name: p for p in (RENDER, NO_DRIVE, SETTLE, ALIASING, ALL)}


class _Source:
    """The three draws the generator needs, for random.Random and numpy Generators."""

    def __init__(self, r: random.Random | np.random.Generator) -> None:
        if isinstance(r, np.random.Generator):
            self.np = True
        elif isinstance(r, random.Random):
            self.np = False
        else:
            raise TypeError(f"need random.Random or numpy Generator, got {type(r).__name__}")
        self.r = r

    def uniform(self, lo: float, hi: float) -> float:
        return float(self.r.uniform(lo, hi))

    def integer(self, lo: int, hi: int) -> int:
        """Uniform over lo..hi inclusive."""
        if self.np:
            return int(self.r.integers(lo, hi + 1))
        return self.r.randrange(lo, hi + 1)

    def choice(self, options: list) -> Any:
        v = self.r.choice(options)
        return v.item() if isinstance(v, np.generic) else v


MAX_REDRAWS = 1000


def _open_uniform(src: _Source, name: str, lo: float, hi: float, lo_open: bool,
                  hi_open: bool) -> float:
    """Uniform over the interval; a value on an open bound is drawn again (closed bounds:
    exactly one draw, as before #119)."""
    for _ in range(MAX_REDRAWS):
        v = src.uniform(lo, hi)
        if not ((lo_open and v <= lo) or (hi_open and v >= hi)):
            return v
    raise RuntimeError(f"{name}: {MAX_REDRAWS} draws on an open bound of {lo}..{hi}")


def _draw_field(src: _Source, name: str, p: dict, profile: Profile) -> Any:
    spec = FIELDS[name]
    if "enum" in spec:
        return src.choice(list(spec["enum"]))
    kind = spec.get("type")
    if kind == "integer":
        lo, hi, _, _ = bounds(name)
        return src.integer(lo, hi)
    if kind == "number":
        c_lo, c_hi, lo_open, hi_open = bounds(name)
        lo, hi = profile.ranges.get(name, (c_lo, c_hi))
        lo_open, hi_open = lo_open and lo == c_lo, hi_open and hi == c_hi
        bound = UPPER_BOUND_BY.get(name)
        if bound in p and p[bound] < hi:
            hi, hi_open = p[bound], False  # the cross-field rule is <=, a closed bound
        if name in profile.zero_spike:
            return src.choice([float(lo), src.uniform(lo, hi)])
        return _open_uniform(src, name, lo, hi, lo_open, hi_open)
    if kind == "string":
        n = src.integer(spec.get("minLength", 0), spec["maxLength"])
        return "".join(src.choice(list(STRING_ALPHABET)) for _ in range(n))
    raise NotImplementedError(f"kick-params field {name!r}: no generator for {spec}")


def draw(r: random.Random | np.random.Generator, profile: Profile = RENDER) -> dict:
    """One parameter set: ``schema_version`` plus every field of ``profile``."""
    src = _Source(r)
    p: dict[str, Any] = {}
    for name in profile.fields:
        p[name] = _draw_field(src, name, p, profile)
    order = profile.keys or profile.fields
    return {"schema_version": SCHEMA_VERSION, **{k: p[k] for k in order}}
