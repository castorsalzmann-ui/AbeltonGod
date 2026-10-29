"""Strict tool variant of kick-params 0.3: contracts/tool-generate-kick.schema.json (#131).

The rules (docs/INTERFACES.md, "Strict tool variant") are written here by hand. The structure the
tool file must have is regenerated from contracts/kick-params.schema.json and compared, and every
range, default and length limit in the descriptions is parsed and compared for equality, so a
contract change that is not carried over to the tool file (or a wrong number in the tool file)
turns a test red. Strict subset, root metadata, model-facing descriptions and the optional-field
budget are checked by the one strict checker in tests/test_contracts.py (``STRICT_TOOLS``).
"""

import json
import random
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
TOOL_FILE = "tool-generate-kick.schema.json"


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


CANON = load("kick-params.schema.json")
TOOL = load(TOOL_FILE)
V03_BRANCH_IF = {"properties": {"schema_version": {"const": "0.3"}}}

def test_tool_schema_is_a_valid_schema_with_its_own_id() -> None:
    Draft202012Validator.check_schema(TOOL)
    assert TOOL["$schema"] == CANON["$schema"]
    assert TOOL["$id"].endswith("/contracts/" + TOOL_FILE)


# --- structure regenerated from the contract --------------------------------------------------

def contract_fields() -> dict:
    """properties plus the v0.3 branch (the branch found by its if, not by position)."""
    branch = next(b for b in CANON["allOf"] if b.get("if") == V03_BRANCH_IF)
    v03 = branch["then"]["properties"]
    assert not set(v03) & set(CANON["properties"])
    return {**CANON["properties"], **v03}


def expected_structure(name: str, prop: dict) -> dict:
    """The tool file's field without its description, derived from the contract field."""
    if name == "schema_version":
        return {"type": "string", "const": "0.3"}
    out = {}
    if "type" in prop:
        out["type"] = prop["type"]
    if "enum" in prop:
        values = prop["enum"]
        if "type" not in prop:
            ints = all(isinstance(v, int) and not isinstance(v, bool) for v in values)
            out["type"] = "integer" if ints else "string"
        out["enum"] = values
    return out


def test_tool_fields_are_exactly_the_contract_fields() -> None:
    fields = contract_fields()
    assert list(TOOL["properties"]) == list(fields)  # same names, same order
    assert len(fields) == 25
    assert TOOL["required"] == CANON["required"] == ["schema_version", "seed"]
    assert TOOL["additionalProperties"] is False


@pytest.mark.parametrize("name", list(contract_fields()))
def test_tool_field_structure_follows_the_contract(name: str) -> None:
    tool_field = {k: v for k, v in TOOL["properties"][name].items() if k != "description"}
    assert tool_field == expected_structure(name, contract_fields()[name])


# A whole number token: not followed by another digit or by '.digit' (so "1" is never read out
# of "12" or "1.5", and "0" never out of "0.5"). JSON parses it, so 4 and 4.0 stay different.
NUM = r"(-?\d+(?:\.\d+)?)(?!\.?\d)"


def _numbers(pattern: str, text: str) -> list:
    """Every match of ``pattern`` (with NUM groups) in ``text``, numbers parsed as JSON."""
    return [tuple(json.loads(g) for g in m.groups()) for m in re.finditer(pattern, text)]


def _same(a, b) -> bool:
    return a == b and type(a) is type(b)


@pytest.mark.parametrize("name", list(contract_fields()))
def test_dropped_constraints_are_stated_exactly_in_the_description(name: str) -> None:
    """Range, default and maximum length are parsed out of the tool text and must equal the
    contract's values exactly (exactly one statement each; none where the contract has none)."""
    prop = contract_fields()[name]
    text = TOOL["properties"][name]["description"]
    ranges = _numbers(rf"Range {NUM} \.\.\. {NUM}", text)
    if "minimum" in prop:
        assert len(ranges) == 1, (name, text)
        lo, hi = ranges[0]
        assert _same(lo, prop["minimum"]) and _same(hi, prop["maximum"]), (name, ranges)
    else:
        assert ranges == [] and "Range" not in text, (name, text)
    defaults = _numbers(rf"Default {NUM}", text)
    if "default" in prop:
        assert len(defaults) == 1 and "No default" not in text, (name, text)
        assert _same(defaults[0][0], prop["default"]), (name, defaults)
    else:
        assert defaults == [] and "Default" not in text, (name, text)
        if name not in CANON["required"]:
            assert "No default" in text, (name, text)
    lengths = _numbers(rf"At most {NUM} characters", text)
    assert lengths == ([(prop["maxLength"],)] if "maxLength" in prop else []), (name, text)


def test_length_limits_in_the_length_beats_text_are_the_length_ms_range() -> None:
    text = TOOL["properties"]["length_beats"]["description"]
    limits = _numbers(rf"must lie in {NUM} \.\.\. {NUM} ms", text)
    ms = CANON["properties"]["length_ms"]
    assert limits == [(ms["minimum"], ms["maximum"])], text


def test_number_parser_does_not_read_prefixes() -> None:
    """The parser itself: the prefixes that a substring check would accept are not matches."""
    assert _numbers(rf"Range {NUM} \.\.\. {NUM}", "Range 0 ... 12.") == [(0, 12)]
    assert _numbers(rf"Range {NUM} \.\.\. {NUM}", "Range 80 ... 20000.") == [(80, 20000)]
    assert _numbers(rf"Default {NUM}", "Default 0.5.") == [(0.5,)]
    assert _numbers(rf"Default {NUM}", "Default -0.3.") == [(-0.3,)]
    assert not _same(_numbers(rf"Default {NUM}", "Default 4.0.")[0][0], 4)


def test_exclusions_and_dependency_are_stated() -> None:
    props = TOOL["properties"]
    assert "Do not combine with pitch_end_hz" in props["tail_note"]["description"]
    assert "Do not combine with tail_note" in props["pitch_end_hz"]["description"]
    assert "Requires bpm; do not combine with length_ms" in props["length_beats"]["description"]
    assert "Do not combine with length_beats" in props["length_ms"]["description"]
    assert "required by length_beats" in props["bpm"]["description"]
    assert "rejected, never shortened" in props["amp_decay_ms"]["description"]
    assert "rejected" in TOOL["description"] and "never clamped" in TOOL["description"]


def test_meaning_sentences_are_stated() -> None:
    """Free text whose meaning the engine relies on (review nit 5 of PR #162)."""
    props = TOOL["properties"]
    assert "sets pitch_end_hz = 440 * 2 ** ((tail_note - 69) / 12)" in (
        props["tail_note"]["description"])
    assert "Must not be lower than pitch_end_hz (or the frequency of tail_note)" in (
        props["pitch_start_hz"]["description"])
    assert "applied in whole samples" in props["offset_ms"]["description"]
    assert "length_ms = length_beats * 60000 / bpm" in props["length_beats"]["description"]
    assert "If no derived value fits" in props["length_beats"]["description"]
    assert "the request is rejected" in props["length_beats"]["description"]
    assert "-1 gives the exactly inverted file" in props["polarity"]["description"]


def test_descriptions_are_model_facing() -> None:
    texts = [TOOL["description"], *(p["description"] for p in TOOL["properties"].values())]
    for text in texts:
        assert text.strip() and len(text) <= 600, text
        assert "#" not in text and "issue" not in text.lower() and "PR " not in text, text


# --- instances: tool schema vs. contract ------------------------------------------------------

def _tool_valid(doc) -> bool:
    return Draft202012Validator(TOOL).is_valid(doc)


def _canon_valid(doc) -> bool:
    return Draft202012Validator(CANON).is_valid(doc)


def _random_valid_v03(rng: random.Random) -> dict:
    """A random valid 0.3 request over the whole contract range (ranges from the contract,
    boundaries drawn on purpose, whole-number floats for integer fields)."""
    fields = contract_fields()
    doc = {"schema_version": "0.3", "seed": rng.choice([0, 4294967295, rng.randint(0, 2**32 - 1)])}
    for name, prop in fields.items():
        if name in doc or rng.random() < 0.5:
            continue
        if "enum" in prop:
            doc[name] = rng.choice(prop["enum"])
        elif prop.get("type") == "string":
            doc[name] = "p" * rng.randint(0, prop["maxLength"])
        elif prop["type"] == "integer":
            v = rng.randint(prop["minimum"], prop["maximum"])
            doc[name] = float(v) if rng.random() < 0.2 else v
        else:
            lo, hi = prop["minimum"], prop["maximum"]
            doc[name] = rng.choice([lo, hi, rng.uniform(lo, hi)])
    if "tail_note" in doc:
        doc.pop("pitch_end_hz", None)
    if "length_beats" in doc:
        doc.pop("length_ms", None)
        doc.setdefault("bpm", rng.uniform(60, 200))
    return doc


def test_every_valid_v03_request_is_valid_against_the_tool_schema() -> None:
    """Seeded property test: the tool schema never rejects what the contract accepts."""
    rng = random.Random(131)
    for _ in range(600):
        doc = _random_valid_v03(rng)
        assert _canon_valid(doc), doc
        assert _tool_valid(doc), doc


# Pass the tool schema on purpose (strict has no ranges, no if/then, no maxLength); the contract
# rejects them, and so does the engine before rendering anything.
LOOSER_THAN_CONTRACT = {
    "drive above range": {"drive": 1.02},
    "seed negative": {"seed": -1},
    "tail_note below range": {"tail_note": 22},
    "length_beats above range": {"length_beats": 4.5, "bpm": 120},
    "tail_note with pitch_end_hz": {"tail_note": 33, "pitch_end_hz": 55},
    "length_beats with length_ms": {"length_beats": 1, "bpm": 128, "length_ms": 450},
    "length_beats without bpm": {"length_beats": 1},
    "preset of 65 characters": {"preset": "p" * 65},
}


@pytest.mark.parametrize("extra", LOOSER_THAN_CONTRACT.values(), ids=LOOSER_THAN_CONTRACT)
def test_what_the_tool_schema_lets_through_the_engine_rejects(extra: dict) -> None:
    from audio_engine.params import KickParamsError, resolve_kick_params

    doc = {"schema_version": "0.3", "seed": 1, **extra}
    assert _tool_valid(doc)
    assert not _canon_valid(doc)
    with pytest.raises(KickParamsError):
        resolve_kick_params(doc)


TOOL_INVALID = {
    "schema_version 0.2": {"schema_version": "0.2", "seed": 1},
    "schema_version as number": {"schema_version": 0.3, "seed": 1},
    "no schema_version": {"seed": 1},
    "no seed": {"schema_version": "0.3"},
    "unknown field": {"schema_version": "0.3", "seed": 1, "wobble": 3},
    "seed fraction": {"schema_version": "0.3", "seed": 1.5},
    "seed true": {"schema_version": "0.3", "seed": True},
    "tail_note fraction": {"schema_version": "0.3", "seed": 1, "tail_note": 33.5},
    "polarity 0": {"schema_version": "0.3", "seed": 1, "polarity": 0},
    "polarity true": {"schema_version": "0.3", "seed": 1, "polarity": True},
    "sample_rate 96000": {"schema_version": "0.3", "seed": 1, "sample_rate": 96000},
    "bit_depth 32": {"schema_version": "0.3", "seed": 1, "bit_depth": 32},
    "drive as string": {"schema_version": "0.3", "seed": 1, "drive": "0.2"},
    "preset as number": {"schema_version": "0.3", "seed": 1, "preset": 3},
    "root is a list": [],
}


@pytest.mark.parametrize("doc", TOOL_INVALID.values(), ids=TOOL_INVALID)
def test_tool_invalid_instances(doc) -> None:
    assert not _tool_valid(doc)


def test_wrong_types_fail_for_every_field() -> None:
    """Seeded: a value of the wrong JSON type in any field fails the tool schema."""
    rng = random.Random(1310)
    wrong = (None, True, "1", [], {}, 1.5)
    for _ in range(300):
        doc = _random_valid_v03(rng)
        name = rng.choice(list(TOOL["properties"]))
        prop = TOOL["properties"][name]
        candidates = [w for w in wrong if not (
            (prop.get("type") == "string" and isinstance(w, str) and "const" not in prop)
            or (prop.get("type") == "number" and isinstance(w, float))
        )]
        value = rng.choice(candidates)
        assert not _tool_valid({**doc, name: value}), (name, value)


def test_a_03_request_without_v03_fields_gives_the_0_2_samples() -> None:
    """Why schema_version can be pinned to 0.3 in the tool schema (INTERFACES.md)."""
    from audio_engine.kick import render_kick

    base = {"seed": 7, "length_ms": 120, "drive": 0.45}
    a, _ = render_kick({"schema_version": "0.2", **base})
    b, resolved = render_kick({"schema_version": "0.3", **base})
    assert a.tobytes() == b.tobytes()
    assert resolved["schema_version"] == "0.3" and resolved["offset_ms"] == 0


# --- contract text that follows the engine (#131 items 3-5) -----------------------------------

V03_PROPS = contract_fields()


def test_offset_rounding_is_written_and_matches_the_engine() -> None:
    from audio_engine.kick import offset_samples, render_kick

    text = V03_PROPS["offset_ms"]["description"]
    for phrase in (
        "n_off = round(offset_ms * sample_rate / 1000)",
        "halves to even: 0.03125 ms at 48 kHz = 1.5 -> 2, 0.09375 ms = 4.5 -> 4",
        "renders the kick into n - n_off samples",
        "the DC blocker, the clip stage, the 5 ms end fade-out, the mean correction and the "
        "normalisation to peak_ceiling_dbfs, and then puts n_off zero samples in front",
        "(polarity is applied after that)",
    ):
        assert phrase in text, phrase
    # The two tie examples, checked against the engine (written values, not recomputed).
    assert offset_samples({"offset_ms": 0.03125, "sample_rate": 48000}) == 2
    assert offset_samples({"offset_ms": 0.09375, "sample_rate": 48000}) == 4
    # Lead-in of exact zeros, then the kick rendered into n - n_off samples.
    req = {"schema_version": "0.3", "seed": 3, "length_ms": 100, "drive": 0.3}
    plain, _ = render_kick(req)
    shifted, _ = render_kick({**req, "offset_ms": 2.5})  # 120 samples at 48 kHz
    shorter, _ = render_kick({**req, "length_ms": 100 - 2.5})
    assert len(shifted) == len(plain) == 4800
    assert not shifted[:120].any()
    assert shifted[120:].tobytes() == shorter.tobytes()
    # At most half a sample gives the samples of offset 0.
    assert offset_samples({"offset_ms": 0.5 / 48, "sample_rate": 48000}) == 0
    tiny, _ = render_kick({**req, "offset_ms": 0.5 / 48})
    assert tiny.tobytes() == plain.tobytes()


def test_length_snap_and_recovery_are_written_and_match_the_engine() -> None:
    from audio_engine.params import resolve_kick_params

    root = CANON["description"]
    for phrase in (
        "a result at most 1e-9 ms below 80 or above 2000 is stored as exactly 80.0 or 2000.0",
        "2.14 beats at 64.2 BPM compute as 2000.0000000000002 ms",
        "both only up to float rounding",
        "3.97 beats at 180.4 BPM give 1320.3991130820398 ms, which recovers 3.9699999999999993",
    ):
        assert phrase in root, phrase
    assert 2.14 * 60000 / 64.2 == 2000.0000000000002
    assert 3.97 * 60000 / 180.4 == 1320.3991130820398
    assert 1320.3991130820398 * 180.4 / 60000 == 3.9699999999999993
    req = {"schema_version": "0.3", "seed": 1, "length_beats": 2.14, "bpm": 64.2,
           "amp_decay_ms": 100}
    assert resolve_kick_params(req)["length_ms"] == 2000.0
    assert 1e-9 * 200 / 60000 < 3.4e-12  # "less than 3.4e-12" at the highest bpm


# Error texts quoted in the contract must be what the engine says (contract follows engine).
NO_FIT = {
    "schema_version": "0.3", "seed": 1, "length_beats": 0.25, "bpm": 187.5, "offset_ms": 12,
    "amp_attack_ms": 20, "click_level": 1.0, "click_decay_ms": 12, "drive": 1.0,
}


def _quoted(text: str, start: str) -> str:
    """The text between ``start`` and the next single quote."""
    i = text.index(start)
    return text[i:text.index("'", i + len(start))]


def test_quoted_error_texts_are_the_engines() -> None:
    from audio_engine.params import KickParamsError, resolve_kick_params

    rule = V03_PROPS["length_beats"]["description"]
    no_fit = _quoted(rule, "the contract's bisection")
    assert no_fit.endswith(": 20.0 ms does not fit")
    head, tail = no_fit.split(" (...)")
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params(NO_FIT)
    message = str(exc.value)
    assert f"- amp_decay_ms: {head} (" in message and tail in message
    assert "a larger explicit amp_decay_ms may still fit" in message
    assert "a larger explicit amp_decay_ms may still fit" in rule

    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**NO_FIT, "amp_decay_ms": 300})
    assert f"- amp_decay_ms 300: {head} (" in str(exc.value)
    assert "after 'amp_decay_ms <value>: '" in rule

    explicit = _quoted(rule, "amp_decay_ms <value> does not decay")
    first, second = explicit.split(" ...; ")
    req = {"schema_version": "0.3", "seed": 1, "length_beats": 1, "bpm": 128}
    derived = resolve_kick_params(req)["amp_decay_ms"]
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({**req, "amp_decay_ms": 2000})
    message = str(exc.value)
    assert first.replace("<value>", "2000") in message
    assert second.replace("<derived>", str(derived)) in message


def test_bisection_wording_claims_no_monotonicity() -> None:
    rule = V03_PROPS["length_beats"]["description"]
    assert "A rejection therefore means exactly that neither 2000.0 nor 20.0 fits" in rule
    assert "'Fits' is not monotonic in amp_decay_ms" in rule
    assert "not always the longest fitting grid value" in rule
    assert "a rejection does not prove that no grid value fits" in rule
    assert "expected, to be verified" not in rule
    assert "This is the longest fitting grid value if" not in rule


def test_no_stale_engine_refuses_text() -> None:
    texts = [CANON["description"], CANON["$comment"],
             (ROOT / "docs" / "INTERFACES.md").read_text(encoding="utf-8")]
    for text in texts:
        assert "refuses schema_version 0.3" not in text
        assert 'refuses `schema_version` "0.3"' not in text
        assert "renders 0.2 only" not in text
        assert "Draft v0.3 (proposal" not in text
    assert "contracts/tool-generate-kick.schema.json" in CANON["$comment"]
