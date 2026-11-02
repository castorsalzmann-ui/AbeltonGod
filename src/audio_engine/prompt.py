"""Keyword prompt -> kick-params v0.3 (issue #233).

Vocabulary: docs/research/2026-11-02_kick-keyword-vocabulary.md.

    parse_prompt("sub:1.5, punch:1.2, dunkel, note:Am") -> ParsedPrompt

Deterministic, no AI call, no file access: the same prompt text gives the same request dict.
The result is a *request* (it may hold ``tail_note`` / ``length_beats``) that
``resolve_kick_params`` accepts; the parser only guarantees the contract ranges and the
pitch-settle guideline, the engine still has the last word (e.g. the -60 dB rule of ``beats``).

Syntax: words separated by commas or spaces; ``word`` or ``word:value``; case-insensitive.

- Weighted keywords ``sub punch click bite tail drive wums bright``: weight ``w`` in 0 ... 2
  (default 1 = the ``dense`` preset). Ratio fields: ``base * r ** (w - 1)``; linear fields:
  ``base + (w - 1) * d``; ``wums`` is an add-on: ``clip_db = 3 * w``. Keywords that share a
  field add their steps in the field's own unit (ratio fields multiply, linear add).
- Aliases with a fixed weight: ``kurz`` = tail 0.4, ``lang`` = tail 1.6, ``dunkel`` = bright 0.4,
  ``hell`` = bright 1.6, ``sauber`` = drive 0.5. The same written word may appear only once.
- Slots: ``note`` (MIDI number 23-46, name ``G#1`` (60 = C4) or pitch class ``Am`` / ``C`` /
  ``Bb``, resolved into the window 27-38), ``key`` (Camelot ``8A``, tonic as pitch class),
  ``bpm`` 60-200, ``beats`` 0.25-4 (needs ``bpm``; ``tail`` is then ignored), ``seed``,
  ``variants`` 1-8.

Order (vocabulary section 4.6): add steps per field, clamp to the contract (reported), pitch
start not below pitch end (reported), pitch-settle fix (reported). A weight outside 0 ... 2, an
unknown word or a bad slot value is an error (:class:`PromptError`, all problems listed), not
a clamp.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field
from typing import Any

from .params import (
    KICK_SCHEMA_FILE,
    NOTE_HZ,
    KickParamsError,
    load_schema,
    max_settled_pitch_decay_ms,
    pitch_settles,
    resolve_kick_params,
)
from .presets import load_preset

# (field, kind, step): kind "ratio" -> value * step ** (w - 1); "linear" -> value + (w - 1) * step.
KEYWORD_STEPS: dict[str, tuple[tuple[str, str, float], ...]] = {
    "sub": (("pitch_start_hz", "ratio", 1 / 1.2), ("pitch_decay_ms", "ratio", 1 / 1.3)),
    "punch": (("pitch_start_hz", "ratio", 1.3),),
    "click": (("click_level", "linear", 0.35),),
    "bite": (("click_tone_hz", "ratio", 1.5),),
    "tail": (("amp_decay_ms", "ratio", 1.35), ("length_ms", "ratio", 1.35)),
    "drive": (("drive", "linear", 0.45),),
    "bright": (("tone", "linear", 0.5),),
}
WUMS_DB_PER_WEIGHT = 3.0  # add-on: clip_db = w * 3
KEYWORDS = (*KEYWORD_STEPS, "wums")
ALIASES: dict[str, tuple[str, float]] = {
    "kurz": ("tail", 0.4),
    "lang": ("tail", 1.6),
    "dunkel": ("bright", 0.4),
    "hell": ("bright", 1.6),
    "sauber": ("drive", 0.5),
}
SLOTS = ("note", "key", "bpm", "beats", "seed", "variants")
WEIGHT_MIN, WEIGHT_MAX = 0.0, 2.0
BASE_PRESET = "dense"
DECIMALS = 6  # results are rounded to 6 decimals (stable sidecar numbers, libm-independent)

# Camelot code -> tonic pitch class (C = 0 ... B = 11). A = minor, B = major; mode is ignored.
_CAMELOT_A = {1: 8, 2: 3, 3: 10, 4: 5, 5: 0, 6: 7, 7: 2, 8: 9, 9: 4, 10: 11, 11: 6, 12: 1}
_CAMELOT_B = {1: 11, 2: 6, 3: 1, 4: 8, 5: 3, 6: 10, 7: 5, 8: 0, 9: 7, 10: 2, 11: 9, 12: 4}
_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NOTE_WINDOW_LOW = 27  # pitch class without octave -> the note in 27 ... 38 (closest to 52 Hz)

_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\Z")
_NOTE_NAME = re.compile(r"([A-Ga-g])([#b]?)(m|min|maj)?(-?\d+)?\Z")
_CAMELOT = re.compile(r"(\d{1,2})([ABab])\Z")


class PromptError(ValueError):
    """The prompt cannot be parsed. The message lists every problem, one per line."""


@dataclass(frozen=True)
class Adjustment:
    """One change the parser made or ignored on purpose; never silent."""

    kind: str  # "clamp" | "pitch_start" | "pitch_settle" | "ignored"
    field: str
    requested: float | None
    applied: float | None
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class ParsedPrompt:
    prompt: str  # the text as given (goes into the sidecar description)
    params: dict[str, Any]  # kick-params 0.3 request (validated with resolve_kick_params)
    weights: dict[str, float]  # per keyword, 1.0 where unmentioned (wums: 0.0 = off)
    adjustments: list[Adjustment] = field(default_factory=list)
    note_midi: int | None = None  # the tail_note chosen by note / key, if any
    slots: frozenset[str] = frozenset()  # slot words the prompt gave (seed, variants, ...)


def parse_prompt(text: str) -> ParsedPrompt:
    """Parse ``text`` into a kick-params 0.3 request. Raises :class:`PromptError`."""
    if not isinstance(text, str):
        raise PromptError(f"The prompt must be text, got {type(text).__name__}.")
    problems: list[str] = []
    contributions: dict[str, list[float]] = {k: [] for k in KEYWORDS}
    slots: dict[str, str] = {}
    seen: set[str] = set()

    for token in _tokens(text):
        word, sep, value = token.partition(":")
        word = word.lower()
        if word in seen:
            problems.append(f"- {word!r} appears twice; use each written word once")
            continue
        seen.add(word)
        if word in KEYWORDS:
            weight = _weight(word, value if sep else None, problems)
            if weight is not None:
                contributions[word].append(weight)
        elif word in ALIASES:
            if sep:
                problems.append(f"- {word!r} is a fixed-weight alias, it takes no value")
                continue
            target, weight = ALIASES[word]
            contributions[target].append(weight)
        elif word in SLOTS:
            if not sep or not value:
                problems.append(f"- {word!r} needs a value, e.g. {_SLOT_EXAMPLE[word]}")
            else:
                slots[word] = value
        else:
            problems.append(_unknown(word))

    request = _base_request()
    adjustments: list[Adjustment] = []
    note, beats, bpm = _slots(slots, request, problems)
    if problems:
        raise PromptError("Cannot parse the prompt:\n" + "\n".join(problems))

    if beats is not None:
        for fld in ("amp_decay_ms", "length_ms"):
            request.pop(fld)
        request["bpm"], request["length_beats"] = bpm, beats
        if contributions["tail"]:
            adjustments.append(Adjustment(
                "ignored", "tail", None, None,
                "tail is ignored: beats sets the length (the engine derives amp_decay_ms)"))
    if note is not None:
        request.pop("pitch_end_hz")
        request["tail_note"] = note
    elif bpm is not None:
        request["bpm"] = bpm

    weights = {k: _mean_weight(k, v) for k, v in contributions.items()}
    _apply_steps(request, contributions, beats is not None)
    _clamp(request, adjustments)
    _pitch_start_floor(request, adjustments)
    try:
        _settle(request, adjustments)
        resolve_kick_params(request)
    except KickParamsError as exc:
        raise PromptError(f"The engine rejects this prompt:\n{exc}") from exc
    return ParsedPrompt(text, request, weights, adjustments, note, frozenset(slots))


# --- tokens and values -------------------------------------------------------------------------

_SLOT_EXAMPLE = {
    "note": "note:32 or note:Am", "key": "key:8A", "bpm": "bpm:136", "beats": "beats:1",
    "seed": "seed:1001", "variants": "variants:4",
}


def _tokens(text: str) -> list[str]:
    return re.sub(r"\s*:\s*", ":", text).replace(",", " ").split()


def _unknown(word: str) -> str:
    valid = [*KEYWORDS, *ALIASES, *SLOTS]
    close = difflib.get_close_matches(word, valid, n=1)
    hint = f" Did you mean {close[0]!r}?" if close else ""
    return f"- unknown word {word!r}.{hint} Valid words: {', '.join(valid)}"


def _number(text: str) -> float | None:
    if not _NUMBER.match(text):
        return None
    value = float(text)
    return value if math.isfinite(value) else None


def _weight(word: str, text: str | None, problems: list[str]) -> float | None:
    if text is None:
        return 1.0
    value = _number(text)
    if value is None:
        problems.append(f"- {word}:{text}: the weight must be a number")
        return None
    if not WEIGHT_MIN <= value <= WEIGHT_MAX:
        problems.append(f"- {word}:{text}: the weight must lie in {WEIGHT_MIN:g} ... "
                        f"{WEIGHT_MAX:g}")
        return None
    return value


def _mean_weight(word: str, values: list[float]) -> float:
    """Reporting only: the weight of the keyword (sum of the steps, 1 + sum(w - 1))."""
    if word == "wums":
        return sum(values) if values else 0.0
    return 1.0 + sum(w - 1.0 for w in values)


def _int_slot(name: str, text: str, lo: int, hi: int, problems: list[str]) -> int | None:
    value = _number(text)
    if value is None or value != int(value) or not lo <= value <= hi:
        problems.append(f"- {name}:{text}: must be a whole number in {lo} ... {hi}")
        return None
    return int(value)


def _slots(slots: dict[str, str], request: dict[str, Any],
           problems: list[str]) -> tuple[int | None, float | None, float | None]:
    note: int | None = None
    if "note" in slots and "key" in slots:
        problems.append("- note and key both set the tail note; give only one")
    elif "note" in slots:
        note = _note(slots["note"], problems)
    elif "key" in slots:
        note = _key(slots["key"], problems)
    for name, lo, hi in (("seed", 0, 4294967295), ("variants", 1, 8)):
        if name in slots:
            value = _int_slot(name, slots[name], lo, hi, problems)
            if value is not None:
                request[name] = value
    bpm = beats = None
    if "bpm" in slots:
        bpm = _number(slots["bpm"])
        if bpm is None or not 60 <= bpm <= 200:
            problems.append(f"- bpm:{slots['bpm']}: must be a number in 60 ... 200")
            bpm = None
    if "beats" in slots:
        beats = _number(slots["beats"])
        if beats is None or not 0.25 <= beats <= 4:
            problems.append(f"- beats:{slots['beats']}: must be a number in 0.25 ... 4")
            beats = None
        elif "bpm" not in slots:
            problems.append("- beats needs bpm, e.g. bpm:136 beats:1")
            beats = None
    return note, beats, bpm


def _note(text: str, problems: list[str]) -> int | None:
    number = _number(text)
    if number is not None:
        if number != int(number) or not 23 <= number <= 46:
            problems.append(f"- note:{text}: a MIDI number must be a whole number in 23 ... 46")
            return None
        return int(number)
    match = _NOTE_NAME.match(text)
    if match is None:
        problems.append(f"- note:{text}: not a number (23-46), note name (Ab1) or pitch class "
                        "(Am, C, Bb)")
        return None
    letter, accidental, mode, octave = match.groups()
    pitch_class = (_PITCH_CLASS[letter.upper()] + {"#": 1, "b": -1, "": 0}[accidental]) % 12
    if octave is None:
        return NOTE_WINDOW_LOW + (pitch_class - NOTE_WINDOW_LOW) % 12
    if mode:
        problems.append(f"- note:{text}: a mode (m, min, maj) cannot be combined with an octave")
        return None
    midi = 12 * (int(octave) + 1) + pitch_class  # scientific pitch: 60 = C4
    if not 23 <= midi <= 46:
        problems.append(f"- note:{text}: MIDI note {midi} is outside 23 ... 46 (scientific "
                        "names, 60 = C4)")
        return None
    return midi


def _key(text: str, problems: list[str]) -> int | None:
    match = _CAMELOT.match(text)
    if match is None or not 1 <= int(match.group(1)) <= 12:
        problems.append(f"- key:{text}: not a Camelot code (1A ... 12B)")
        return None
    table = _CAMELOT_A if match.group(2).upper() == "A" else _CAMELOT_B
    pitch_class = table[int(match.group(1))]
    return NOTE_WINDOW_LOW + (pitch_class - NOTE_WINDOW_LOW) % 12


# --- mapping -----------------------------------------------------------------------------------


def _base_request() -> dict[str, Any]:
    """The ``dense`` preset as a 0.3 request with ``clip_db`` 0 (vocabulary section 2)."""
    base = dict(load_preset(BASE_PRESET))
    base["schema_version"] = "0.3"
    base.pop("preset", None)
    base["clip_db"] = 0.0
    return base


def _apply_steps(request: dict[str, Any], contributions: dict[str, list[float]],
                 beats: bool) -> None:
    for word, steps in KEYWORD_STEPS.items():
        for weight in contributions[word]:
            for fld, kind, step in steps:
                if fld not in request:  # beats: length_ms / amp_decay_ms are derived
                    continue
                if kind == "ratio":
                    request[fld] = request[fld] * step ** (weight - 1.0)
                else:
                    request[fld] = request[fld] + (weight - 1.0) * step
    if contributions["wums"]:
        request["clip_db"] = WUMS_DB_PER_WEIGHT * sum(contributions["wums"])
    for fld in ("pitch_start_hz", "pitch_decay_ms", "click_level", "click_tone_hz", "drive",
                "tone", "clip_db", "amp_decay_ms", "length_ms"):
        if fld in request:
            request[fld] = round(request[fld], DECIMALS)


def _clamp(request: dict[str, Any], adjustments: list[Adjustment]) -> None:
    props = load_schema(KICK_SCHEMA_FILE)["properties"]
    ranges = {k: (v["minimum"], v["maximum"]) for k, v in props.items() if "minimum" in v}
    ranges["clip_db"] = (0, 12)  # v0.3 field, not under "properties"
    for fld in ("pitch_start_hz", "pitch_decay_ms", "click_level", "click_tone_hz", "drive",
                "tone", "clip_db", "amp_decay_ms", "length_ms"):
        if fld not in request:
            continue
        lo, hi = ranges[fld]
        value = request[fld]
        clamped = min(max(value, lo), hi)
        if clamped != value:
            request[fld] = float(clamped)
            adjustments.append(Adjustment(
                "clamp", fld, value, float(clamped),
                f"{fld} {value:g} is outside the contract range {lo:g} ... {hi:g}; "
                f"set to {clamped:g}"))


def _end_hz(request: dict[str, Any]) -> float:
    return NOTE_HZ[request["tail_note"]] if "tail_note" in request else request["pitch_end_hz"]


def _pitch_start_floor(request: dict[str, Any], adjustments: list[Adjustment]) -> None:
    end = _end_hz(request)
    if request["pitch_start_hz"] < end:
        old = request["pitch_start_hz"]
        request["pitch_start_hz"] = math.ceil(end * 10**DECIMALS) / 10**DECIMALS
        adjustments.append(Adjustment(
            "pitch_start", "pitch_start_hz", old, request["pitch_start_hz"],
            f"pitch_start_hz {old:g} is below the tail pitch {end:.4f} Hz; raised to "
            f"{request['pitch_start_hz']:g}"))


def _settle(request: dict[str, Any], adjustments: list[Adjustment]) -> None:
    """Lower ``pitch_decay_ms`` to the pitch-settle limit (reported)."""
    min_decay = load_schema(KICK_SCHEMA_FILE)["properties"]["pitch_decay_ms"]["minimum"]
    old = request["pitch_decay_ms"]
    limit = max_settled_pitch_decay_ms(request)
    if old <= limit:
        return
    new = max(math.floor(limit * 10**DECIMALS) / 10**DECIMALS, float(min_decay))
    request["pitch_decay_ms"] = new
    # length_beats requests derive amp_decay_ms from the render, so the limit can move a few
    # percent with pitch_decay_ms (params.max_settled_pitch_decay_ms): re-check on the request.
    for _ in range(20):
        if pitch_settles(request) or new <= min_decay:
            break
        new = max(math.floor(new * 0.97 * 10**DECIMALS) / 10**DECIMALS, float(min_decay))
        request["pitch_decay_ms"] = new
    note = ("" if pitch_settles(request) else
            "; no allowed value settles in time, the minimum is used")
    adjustments.append(Adjustment(
        "pitch_settle", "pitch_decay_ms", old, new,
        f"pitch_decay_ms {old:g} is above the pitch-settle limit {limit:.4f}; lowered to "
        f"{new:g}{note}"))
