"""#492: defaults that follow another field (fx ``kind`` branches, derived defaults), read from the
contract; existing categories unchanged. No Qt."""

from __future__ import annotations

import json
import random

import pytest

from audio_engine.params import CONTRACTS_DIR
from audio_engine.presets import preset_names
from gui_core.form import CATEGORY_KEYS, CategoryFormModel, resolve_defaults

FX = json.loads((CONTRACTS_DIR / "fx-params.schema.json").read_text(encoding="utf-8"))
KINDS = FX["properties"]["kind"]["enum"]


def fx(kind: str | None = None) -> CategoryFormModel:
    m = CategoryFormModel("fx")
    if kind is not None:
        m.set_active("kind", True)
        m.set_text("kind", kind)
    return m


# --- hand-written values (from the contract text, not from the resolver) -------------------------

@pytest.mark.parametrize(("kind", "field", "text"), [
    (None, "length_beats", "64"), (None, "sweep_curve", "1.5"), (None, "cutoff_end_hz", "9000"),
    (None, "ramp_beats", "64"),  # derived: = length_beats
    ("riser", "filter_mode", "bp"), ("riser", "level_start_db", "-36"),
    ("sweep", "filter_q", "4"), ("sweep", "length_beats", "16"), ("sweep", "ramp_beats", "16"),
    ("sweep", "tone_glide_beats", "16"),
    ("downlifter", "cutoff_start_hz", "8000"), ("downlifter", "tone_wave", "saw"),
    ("impact", "ramp_beats", "0.25"),  # impact's own default, not length_beats
])
def test_fx_placeholders_follow_the_kind(kind, field, text):
    m = fx(kind)
    value, problem = m.parse(field)
    assert problem is None and m.text[field] in (text, text + ".0"), (kind, field, m.text[field])
    assert field not in m.active  # not sent: the engine resolves it


def test_changing_kind_updates_untouched_fields_and_keeps_typed_ones():
    m = fx("riser")
    m.set_active("filter_q", True)
    m.set_text("filter_q", "7")  # typed by the user
    m.set_active("reverb_mix", True)
    m.set_text("reverb_mix", "0.9")
    m.set_active("reverb_mix", False)  # switched off: text 0.9 is the user's, not a default
    m.set_text("kind", "sweep")
    assert m.text["filter_q"] == "7" and "filter_q" in m.active
    assert m.text["reverb_mix"] == "0.9"
    assert m.parse("cutoff_end_hz")[0] == 12000 and m.parse("length_beats")[0] == 16
    m.set_text("kind", "riser")
    assert m.parse("cutoff_end_hz")[0] == 9000


def test_derived_default_follows_a_typed_length():
    m = fx("sweep")
    m.set_active("length_beats", True)
    m.set_text("length_beats", "32")
    assert m.parse("ramp_beats")[0] == 32 and m.parse("tone_glide_beats")[0] == 32
    req = m.build_request()
    assert "ramp_beats" not in req and req["length_beats"] == 32 and "preset" not in req


# --- property: every kind, every branch field ------------------------------------------------

def test_property_every_branch_default_of_every_kind_is_shown_for_random_states():
    """For each kind and random typed fields, an untouched field shows the branch default of
    that kind (looked up here by walking the schema directly), else the top-level default."""
    rng = random.Random(492)
    branch_of = {}
    for b in FX["allOf"]:
        const = b["if"]["properties"]["kind"]["const"]
        branch_of[const] = {n: d["default"] for n, d in b["then"]["properties"].items()
                            if "default" in d}
    checked = 0
    for _ in range(40):
        kind = rng.choice(KINDS)
        m = fx(kind)
        typed = rng.sample([n for n in branch_of[kind] if m.spec(n).kind in ("int", "float")], 3)
        for n in typed:
            spec = m.spec(n)
            m.set_active(n, True)
            m.set_text(n, str(spec.minimum))
        m.set_text("kind", kind := rng.choice(KINDS))  # change kind after typing
        for n, d in branch_of[kind].items():
            if n in typed:
                assert m.parse(n)[0] == m.spec(n).minimum, (kind, n)
            else:
                assert m.parse(n)[0] == d, (kind, n, m.text[n])
                checked += 1
    assert checked > 300


def test_resolver_absent_kind_uses_only_branches_without_required():
    got = resolve_defaults(FX, {})
    assert got["length_beats"] == 64 and got["filter_q"] == 1.2  # riser, the default kind
    got = resolve_defaults(FX, {"kind": "impact"})
    assert got["ramp_beats"] == 0.25 and "kind" not in got


# --- existing categories unchanged ----------------------------------------------------------

def _old_placeholder(spec):
    if spec.default is not None:
        return repr(spec.default) if isinstance(spec.default, float) else (
            ("ja" if spec.default else "nein") if isinstance(spec.default, bool)
            else str(spec.default))
    if spec.kind in ("enum", "bool"):
        return spec.choice_texts[0]
    return repr(spec.minimum) if isinstance(spec.minimum, float) else str(spec.minimum)


@pytest.mark.parametrize("category", CATEGORY_KEYS)
def test_existing_categories_keep_their_placeholders_and_requests(category):
    rng = random.Random(f"keep-{category}")
    for preset in preset_names(category):
        m = CategoryFormModel(category, preset)
        for spec in m.specs:
            if spec.name not in m.active and spec.name != "variants":
                assert m.text[spec.name] == _old_placeholder(spec), (category, spec.name)
        before = dict(m.text)
        name = rng.choice([s.name for s in m.specs if s.name not in m.active])
        m.set_active(name, True)
        m.set_active(name, False)
        assert m.text == before  # toggling never rewrites other texts
        assert "preset" in m.build_request()
