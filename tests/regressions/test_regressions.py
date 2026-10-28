"""Regression corpus (#14): one JSON case per fixed bug, every case checked on every run.

A case pins one measured value of one deterministic render to a bound. File name
``bug_<issue>.json`` or ``bug_<issue>_<slug>.json`` (one PR or issue can hold several
findings); ``<issue>`` must match the number in the case's ``issue`` link. Fields:

- ``issue``: link to the issue, PR or review that reported the bug.
- ``finding``: one or two sentences: what was wrong and what fixed it.
- ``params``: the full kick-params object (all fields, so a changed default cannot change
  the case), validated against ``contracts/kick-params.schema.json``.
- ``measure``: one of ``MEASURES`` below. ``analysis.<feature>`` uses ``analyse()``; use it only
  when the bug was in the analyser. The other measures are computed here, independently.
- ``expected``: ``{"min": x, "max": y}`` (at least one), plus ``"allow_null": true`` when
  "unmeasurable" (None) is an acceptable answer.
- ``before_fix``: ``{"commit": "<sha>", "value": <measured before the fix>}``. The loader
  checks that this value lies outside the bound, i.e. the case would have caught the bug.

A fix starts with a failing case here (see CLAUDE.md, "Bugs").
"""

from __future__ import annotations

import json
import math
import re
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from audio_engine.analysis import analyse
from audio_engine.io import render_kick_wav
from audio_engine.kick import render_kick
from audio_engine.params import KICK_SCHEMA_FILE, KickParamsError, load_schema

CASE_DIR = Path(__file__).parent
FILE_NAME = re.compile(r"^bug_(\d+)(_[a-z0-9_]+)?\.json$")
ISSUE_LINK = re.compile(
    r"^https://github\.com/castorsalzmann-ui/abeltongod/(?:issues|pull)/(\d+)(?:[#?]\S*)?$",
    re.IGNORECASE,
)
ANALYSIS_FEATURES = (
    "peak_dbfs", "length_ms", "fundamental_hz", "decay_20db_ms", "decay_40db_ms", "dc_offset",
)
MEASURES = (
    "audio.mean", "audio.first_sample", "audio.last_sample", "audio.peak_dbfs",
    "wav.peak_dbfs", *(f"analysis.{f}" for f in ANALYSIS_FEATURES),
)

CASE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issue", "finding", "params", "measure", "expected", "before_fix"],
    "properties": {
        "issue": {"type": "string"},
        "finding": {"type": "string", "minLength": 20},
        "params": {"type": "object"},
        "measure": {"enum": list(MEASURES)},
        "expected": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "min": {"type": "number"},
                "max": {"type": "number"},
                "allow_null": {"type": "boolean"},
            },
        },
        "before_fix": {
            "type": "object",
            "additionalProperties": False,
            "required": ["commit", "value"],
            "properties": {
                "commit": {"type": "string", "pattern": "^[0-9a-f]{7,40}$"},
                "value": {"type": ["number", "null"]},
            },
        },
    },
}
_CASE_VALIDATOR = Draft202012Validator(CASE_SCHEMA)
_KICK_VALIDATOR = Draft202012Validator(load_schema(KICK_SCHEMA_FILE))


class CaseError(Exception):
    """A malformed regression case. The message names the file and the problem."""


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not valid JSON")


def load_case(path: Path) -> dict[str, Any]:
    def fail(msg: str) -> CaseError:
        return CaseError(f"{path.name}: {msg}")

    name = FILE_NAME.match(path.name)
    if not name:
        raise fail("file name must be bug_<issue>.json or bug_<issue>_<slug>.json")
    try:
        case = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except ValueError as e:
        raise fail(f"not valid JSON ({e})") from None
    error = best_match(_CASE_VALIDATOR.iter_errors(case))
    if error is not None:
        where = "/".join(str(p) for p in error.absolute_path) or "(top level)"
        raise fail(f"{where}: {error.message}")
    link = ISSUE_LINK.match(case["issue"])
    if not link:
        raise fail(f"issue: {case['issue']!r} is not a link to an issue or PR of this repo")
    if link.group(1) != name.group(1):
        raise fail(f"file name says #{name.group(1)}, but the issue link is {case['issue']}")
    error = best_match(_KICK_VALIDATOR.iter_errors(case["params"]))
    if error is not None:
        where = "".join(f"/{p}" for p in error.absolute_path)
        raise fail(f"params{where}: {error.message}")
    missing = sorted(set(_KICK_VALIDATOR.schema["properties"]) - set(case["params"]) - {
        "variants", "bpm", "preset"
    })
    if missing:
        raise fail(f"params must list every engine field; missing: {', '.join(missing)}")
    lo, hi = case["expected"].get("min"), case["expected"].get("max")
    before = case["before_fix"]["value"]
    for label, x in (("expected min", lo), ("expected max", hi), ("before_fix value", before)):
        if x is not None and not math.isfinite(x):  # json.loads turns 1e999 into inf
            raise fail(f"{label} must be finite, got {x}")
    if lo is None and hi is None:
        raise fail("expected needs at least one of min or max")
    if lo is not None and hi is not None and lo > hi:
        raise fail(f"expected min {lo} is greater than max {hi}")
    if within(case["before_fix"]["value"], case["expected"]):
        raise fail(
            f"before_fix value {case['before_fix']['value']} is inside the expected bound, "
            "so this case would not have caught the bug"
        )
    return case


def within(value: float | None, expected: dict[str, Any]) -> bool:
    if value is None:
        return bool(expected.get("allow_null", False))
    if not math.isfinite(value):
        return False
    lo, hi = expected.get("min", -math.inf), expected.get("max", math.inf)
    return lo <= value <= hi


def _db(x: float) -> float | None:
    return 20 * math.log10(x) if x > 0 else None


def _decode_wav_peak(data: bytes) -> tuple[int, int]:
    """Largest absolute sample and bit depth, parsed with struct (not with the stdlib wave
    module the engine uses to write)."""
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE", "not a RIFF/WAVE file"
    pos, bits, samples = 12, None, None
    while pos + 8 <= len(data):
        tag, size = data[pos : pos + 4], struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        body = data[pos + 8 : pos + 8 + size]
        if tag == b"fmt ":
            bits = struct.unpack("<H", body[14:16])[0]
        elif tag == b"data":
            samples = body
        pos += 8 + size + (size & 1)
    assert bits in (16, 24) and samples is not None, "fmt or data chunk missing"
    if bits == 16:
        ints = np.frombuffer(samples, dtype="<i2").astype(np.int64)
    else:
        b = np.frombuffer(samples[: len(samples) // 3 * 3], dtype=np.uint8)
        b = b.reshape(-1, 3).astype(np.int64)
        ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = np.where(ints >= 2**23, ints - 2**24, ints)
    return int(np.max(np.abs(ints))), bits


def measure(case: dict[str, Any]) -> float | None:
    kind = case["measure"]
    if kind == "wav.peak_dbfs":
        peak, bits = _decode_wav_peak(render_kick_wav(case["params"])[0])
        return _db(peak / (2 ** (bits - 1) - 1))
    audio, r = render_kick(case["params"])
    if kind == "audio.mean":
        return float(np.mean(audio))
    if kind == "audio.first_sample":
        return float(audio[0])
    if kind == "audio.last_sample":
        return float(audio[-1])
    if kind == "audio.peak_dbfs":
        return _db(float(np.max(np.abs(audio))))
    return analyse(audio, r["sample_rate"])[kind.removeprefix("analysis.")]


# Not glob("*.json"): that is case-sensitive on Linux but not on Windows. Every .json file,
# whatever its case, is collected, so a misnamed one fails the name check on every OS.
CASE_FILES = sorted(p for p in CASE_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".json")


def test_corpus_is_not_empty() -> None:
    assert CASE_FILES, f"no regression cases in {CASE_DIR}"


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_regression_case(path: Path) -> None:
    try:
        case = load_case(path)
        value = measure(case)
    except CaseError as e:
        pytest.fail(str(e), pytrace=False)
    except KickParamsError as e:
        pytest.fail(f"{path.name}: engine rejected params: {e}", pytrace=False)
    assert within(value, case["expected"]), (
        f"{path.name}: {case['measure']} = {value!r}, expected {case['expected']} "
        f"(regression of {case['issue']}: {case['finding']})"
    )


# --- the loader rejects malformed cases with a clear message ---------------------------------


def _good_case() -> dict[str, Any]:
    return json.loads((CASE_DIR / "bug_8_dc_short_kick.json").read_text(encoding="utf-8"))


def _edit(path: str, value: Any):
    def apply(case: dict[str, Any]) -> None:
        *parents, last = path.split(".")
        target = case
        for key in parents:
            target = target[key]
        if value is _DELETE:
            del target[last]
        else:
            target[last] = value

    return apply


_DELETE = object()

MALFORMED = [
    ("bug_8.json", _edit("measure", _DELETE), "'measure' is a required property"),
    ("bug_8.json", _edit("measure", "audio.rms"), "measure: 'audio.rms' is not one of"),
    ("bug_8.json", _edit("expected", {"allow_null": True}), "needs at least one of min or max"),
    ("bug_8.json", _edit("expected", {"min": 1, "max": 0}), "min 1 is greater than max 0"),
    ("bug_8.json", _edit("before_fix.value", 0.0), "would not have caught the bug"),
    ("bug_8.json", _edit("before_fix", _DELETE), "'before_fix' is a required property"),
    ("bug_8.json", _edit("params.pitch_end_hz", 5), "params/pitch_end_hz"),
    ("bug_8.json", _edit("params.wobble", 1), "params: Additional properties"),
    ("bug_8.json", _edit("params.drive", _DELETE), "missing: drive"),
    ("bug_8.json", _edit("issue", "https://example.com/8"), "issue:"),
    ("bug_9.json", lambda c: None, "file name says #9"),
    ("regression_8.json", lambda c: None, "file name must be bug_<issue>"),
    ("bug_8.json", _edit("extra", 1), "Additional properties are not allowed"),
    ("bug_8.JSON", lambda c: None, "file name must be bug_<issue>"),
]


@pytest.mark.parametrize(
    ("name", "edit", "fragment"), MALFORMED, ids=[f"case{i}" for i in range(len(MALFORMED))]
)
def test_malformed_case_is_rejected_with_clear_message(tmp_path, name, edit, fragment) -> None:
    case = _good_case()
    edit(case)
    path = tmp_path / name
    path.write_text(json.dumps(case), encoding="utf-8")
    with pytest.raises(CaseError) as info:
        load_case(path)
    message = str(info.value)
    assert message.startswith(f"{name}: ") and fragment in message, message


@pytest.mark.parametrize("text", ["{not json", '{"x": NaN}'], ids=["broken", "nan"])
def test_invalid_json_is_rejected_with_clear_message(tmp_path, text: str) -> None:
    path = tmp_path / "bug_8.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CaseError, match=r"^bug_8\.json: not valid JSON"):
        load_case(path)


@pytest.mark.parametrize(
    ("field", "label"),
    [("expected.max", "expected max"), ("before_fix.value", "before_fix value")],
)
def test_overflowing_number_is_rejected_as_non_finite(tmp_path, field: str, label: str) -> None:
    """json.loads reads the literal 1e999 as inf without calling parse_constant (review of #24)."""
    case = _good_case()
    _edit(field, "__HUGE__")(case)
    path = tmp_path / "bug_8.json"
    path.write_text(json.dumps(case).replace('"__HUGE__"', "-1e999"), encoding="utf-8")
    with pytest.raises(CaseError, match=rf"^bug_8\.json: {label} must be finite"):
        load_case(path)


def test_good_case_loads(tmp_path) -> None:
    path = tmp_path / "bug_8_copy.json"
    path.write_text(json.dumps(_good_case()), encoding="utf-8")
    assert load_case(path)["measure"] == "audio.mean"


@pytest.mark.parametrize(
    ("value", "expected", "ok"),
    [
        (0.5, {"min": 0, "max": 1}, True),
        (1.5, {"min": 0, "max": 1}, False),
        (-1.0, {"max": 0}, True),
        (None, {"min": 0}, False),
        (None, {"min": 0, "allow_null": True}, True),
        (math.nan, {"min": 0, "max": 1}, False),
        (math.inf, {"min": 0}, False),
    ],
)
def test_bound_check(value, expected, ok) -> None:
    assert within(value, expected) is ok
