"""Form model and render service for every category (no Qt)."""

from __future__ import annotations

import hashlib
import io
import json
import random
from pathlib import Path

import pytest

from audio_engine import cli
from audio_engine.presets import load_preset, preset_names
from gui_core.form import ALWAYS_ACTIVE, CATEGORY_KEYS, HIDDEN_FIELDS, CategoryFormModel
from gui_core.render import RenderJob, run_job

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
CATS = list(CATEGORY_KEYS)


def raw_fields(cat: str) -> dict[str, tuple[dict, str | None]]:
    """``{field: (definition, gate_version)}`` read straight from the JSON file."""
    schema = json.loads((CONTRACTS / f"{cat}-params.schema.json").read_text(encoding="utf-8"))
    out = {k: (v, None) for k, v in schema["properties"].items() if k not in HIDDEN_FIELDS}
    for branch in schema.get("allOf", []):
        const = branch.get("if", {}).get("properties", {}).get("schema_version", {}).get("const")
        if const:
            for k, v in branch["then"]["properties"].items():
                if k not in out:  # laser 0.1 only narrows length_ms (3000): a rule, not a field
                    out[k] = (v, const)
    return out


def number_branch(d: dict) -> dict:
    for key in ("oneOf", "anyOf"):
        if key in d:
            return next(b for b in d[key] if b.get("type") == "number")
    return d


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("cat", CATS)
def test_every_contract_field_of_the_category_has_a_spec(cat):
    m = CategoryFormModel(cat)
    specs = {s.name: s for s in m.specs}
    raw = raw_fields(cat)
    assert set(specs) == set(raw), (cat, set(raw) ^ set(specs))
    for name, (d, gate) in raw.items():
        s = specs[name]
        assert s.gate_version == gate, name
        assert s.label and s.label != name, f"{cat}.{name}: German label missing"
        n = number_branch(d)
        if "enum" in d:
            assert s.kind == "enum" and list(s.choices) == d["enum"], name
        elif d.get("type") == "boolean":
            assert s.kind == "bool", name
        elif d.get("type") == "array":  # atmos intervals (#533)
            assert s.kind == "list", name
            assert (s.minimum, s.maximum) == (d["items"]["minimum"], d["items"]["maximum"])
            assert (s.min_items, s.max_items) == (d["minItems"], d["maxItems"]), name
        else:
            assert (s.minimum, s.maximum) == (n["minimum"], n["maximum"]), (cat, name)
            assert s.kind == ("int" if n["type"] == "integer" else "float"), name
            assert s.zero_ok == ("oneOf" in d or "anyOf" in d), name


@pytest.mark.parametrize("cat", CATS)
def test_every_preset_loads_valid_and_reproduces_itself(cat):
    names = preset_names(cat)
    assert names
    for name in names:
        m = CategoryFormModel(cat, name)
        assert m.issues() == [], (cat, name, m.issues())
        expected = dict(load_preset(name, cat))
        expected["variants"] = 1
        got = m.build_request()
        assert got == expected and list(got) == list(expected), (cat, name)
        assert m.overrides() == {}


@pytest.mark.parametrize("cat", CATS)
def test_boundaries_for_every_numeric_field(cat):
    for name, (d, _gate) in raw_fields(cat).items():
        if "enum" in d or d.get("type") in ("boolean", "array"):  # lists: test_atmos_page
            continue
        n = number_branch(d)
        lo, hi = n["minimum"], n["maximum"]
        step = 1 if n["type"] == "integer" else 1e-6
        cases = [(lo, True), (hi, True), (lo - step, False), (hi + step, False)]
        if "oneOf" in d or "anyOf" in d:
            cases += [(0, True)]
        for value, ok in cases:
            if value == 0 and not ok:
                continue
            m = CategoryFormModel(cat)
            m.set_active(name, True)
            m.set_text(name, repr(value))
            assert (name in m.field_issues()) is (not ok), (cat, name, value)


@pytest.mark.parametrize("cat", CATS)
def test_random_in_range_values_are_sent_unchanged(cat):
    rng = random.Random(405)
    fields = [
        (k, number_branch(d)) for k, (d, _g) in raw_fields(cat).items()
        if "enum" not in d and d.get("type") not in ("boolean", "array")
    ]
    for _ in range(100):
        name, n = rng.choice(fields)
        v = (rng.randint(n["minimum"], n["maximum"]) if n["type"] == "integer"
             else rng.uniform(n["minimum"], n["maximum"]))
        m = CategoryFormModel(cat)
        m.set_active(name, True)
        m.set_text(name, repr(v))
        assert name not in m.field_issues()
        assert m.build_request()[name] == v


def test_hat_choke_zero_means_off_and_the_gap_is_rejected():
    m = CategoryFormModel("hat", "closed-std")
    m.set_active("choke_ms", True)
    for text, ok in (("0", True), ("3", False), ("5", True), ("900", True), ("901", False)):
        m.set_text("choke_ms", text)
        assert ("choke_ms" not in m.field_issues()) is ok, text
    assert m.spec("choke_ms").range_text == "0 (aus) oder 5 bis 900 ms"


def test_string_enum_and_bool_fields():
    m = CategoryFormModel("hat", "closed-std")
    m.set_active("model", True)
    m.set_text("model", "noise")
    assert m.build_request()["model"] == "noise"
    m.set_text("model", "banana")
    assert "model" in m.field_issues()
    c = CategoryFormModel("clap", "default")
    c.set_active("tail_reverse", True)
    for text, value in (("ja", True), ("nein", False)):
        c.set_text("tail_reverse", text)
        assert c.build_request()["tail_reverse"] is value
    c.set_text("tail_reverse", "true")
    assert "tail_reverse" in c.field_issues()


def test_clap_version_follows_the_fields_in_use():
    m = CategoryFormModel("clap", "default")
    assert m.build_request()["schema_version"] == "0.1"
    m.set_active("fold", True)
    m.set_text("fold", "0.4")
    req = m.build_request()
    assert req["schema_version"] == "0.2" and req["fold"] == 0.4
    assert m.is_valid
    x = CategoryFormModel("clap", "xtreme-wreck")
    assert x.build_request()["schema_version"] == "0.2" and x.is_valid


def test_category_cross_rule_comes_from_the_engines_resolve():
    m = CategoryFormModel("bass", "default")
    m.set_text("hp_hz", "120")
    m.set_active("hp_hz", True)
    m.set_text("lp_hz", "60")
    assert m.field_issues() == {}  # each value alone is inside its contract range
    issues = m.issues()
    assert len(issues) == 1 and issues[0].startswith("Ungültige Kombination")
    assert "hp_hz" in issues[0]
    assert not m.is_valid


@pytest.mark.parametrize("cat", CATS)
def test_inactive_and_always_active_rules_hold_in_every_category(cat):
    m = CategoryFormModel(cat)
    for name in ALWAYS_ACTIVE:
        m.set_active(name, False)
        assert name in m.active
    m.set_text("seed", "4294967296")
    assert "seed" in m.field_issues()


# (category, preset, seed, variants, --set overrides, sha256 of each WAV) from a run of
# `python -m audio_engine.cli --category ...` (Linux, Python 3.13).
PINNED = [
    ("kick", "punchy", 42, 2, [], [
        "47824200b3d4e4a67d36abbe3473124153738b00dea533322596dfabff6ecd36",
        "9144df7dd5b3f64fc1e2647db429c4afce31b652bf40ad46bd9100ba07cabf7b"]),
    ("hat", "closed-std", 11, 2, [], [
        "1353222a1fdc0820441cdf108c173074aec1d7742befcca3bd9b1112e8c0d766",
        "d1906eb2df0a15288218d332408f3a8ba8c5c04d6865a23672b882f850764793"]),
    ("hat", "open-short", 12, 1, ["decay_ms=80", "choke_ms=100"], [
        "e4d9b04b38f81d50d7d6e3c43f2d07c5d43733a0fa90582664595ca815c771d7"]),
    ("snare", "default", 21, 2, [], [
        "98b2160e96e6fe523744878bf427247cbc412617c18418368266033d3463b94d",
        "6bd638f0c6dcea4e7b3d0d52dea2d6625258fb2bb991b0c2f0eb083accc54f71"]),
    ("snare", "tight", 22, 1, ["drive=0.3"], [
        "e45e0c71189ff5da435976cee07f8e614d2678a1d0b26c7808eb5591ef0101f2"]),
    ("clap", "default", 31, 2, [], [
        "7602935d46750f01a0877359296852e8bd930afab0a5ae047b341ee82a234ea2",
        "72913f31b1aa0f16af21d1492d0c8d280f4bad25ca813b5bd00f31bc88008bc4"]),
    ("clap", "xtreme-wreck", 32, 1, ["fold=0.5"], [
        "03c8eacb2053a6686bd0837340b7b26fc32ea24116a89c423e34dec6294d963e"]),
    ("clap", "default", 33, 1, ["tail_level=0.5"], [
        "aecc3d90b01324eca8c829fe5944aa7186b1827c94964d27703ca813b4dddda6"]),
    ("rim", "rim", 41, 2, [], [
        "401d70107a51a1b2a4e3a25e4aec26742e0f7396878da7f9d3fba4958bb3076d",
        "4fb52a656b46e372e8d68e464c9b7b2393f8a640e0dd03bfa3254033d665e7bc"]),
    ("rim", "clave", 42, 1, ["drive=0.3"], [
        "cc067125dd92ebd77cdb2dcc8b204b60255cb1e2243591e9a996ef099af7043e"]),
    ("bass", "default", 51, 2, [], [
        "8f738491634dda2ce31d883f3baebfca63a19c5321f4b52b8daac81e01e50e24",
        "8647ae112a0ad5c8f824fefb6fa340485d00af7230f3d48fb25711aab025d01d"]),
    ("bass", "sub", 52, 1, ["drive=0.4", "note=36"], [
        "52873c4c8a3fee64576cd593d8bb8a2d70a4dfdd9c3311cb682d291b6f4cdb7d"]),
]


@pytest.mark.parametrize("cat,preset,seed,n,sets,hashes", PINNED)
def test_bytes_equal_the_category_cli(tmp_path, cat, preset, seed, n, sets, hashes):
    m = CategoryFormModel(cat, preset)
    m.set_text("seed", str(seed))
    m.set_text("variants", str(n))
    for item in sets:
        name, value = item.split("=")
        m.set_active(name, True)
        m.set_text(name, value)
    assert m.is_valid, m.issues()
    result = run_job(RenderJob(m.build_request(), tmp_path / "gui", preset, m.overrides(), cat))
    assert result.ok, result.error
    assert [sha(f.wav_path) for f in result.files] == hashes

    args = ["--category", cat, "--preset", preset, "--seed", str(seed), "--variants", str(n),
            "--out", str(tmp_path / "cli")]
    for item in sets:
        args += ["--set", item]
    assert cli.main(args, stdout=io.StringIO(), stderr=io.StringIO()) == 0
    for f in result.files:
        # #443: the GUI name is the CLI name with the category in front; same bytes
        cli_name = f.wav_path.name.removeprefix(f"{cat}_")
        assert f.wav_path.name.startswith(f"{cat}_{preset}_s{seed}_v")
        assert f.wav_path.read_bytes() == (tmp_path / "cli" / cli_name).read_bytes()
        gui_meta = json.loads(f.json_path.read_text(encoding="utf-8"))
        cli_side = tmp_path / "cli" / cli_name.replace(".wav", ".json")
        cli_meta = json.loads(cli_side.read_text(encoding="utf-8"))
        assert gui_meta["file"] == f.wav_path.name and cli_meta["file"] == cli_name
        skip = {"file": None, "created_at": None}
        assert {**gui_meta, **skip} == {**cli_meta, **skip}
        assert gui_meta["category"] == cat


@pytest.mark.parametrize("cat", CATS)
def test_invalid_request_is_an_error_object_and_writes_nothing(tmp_path, cat):
    req = CategoryFormModel(cat).build_request()
    req["peak_ceiling_dbfs"] = 5  # above -0.1: outside every category's contract
    out = tmp_path / "never"
    result = run_job(RenderJob(req, out, "x", {}, cat))
    assert not result.ok and result.files == ()
    assert result.error.kind == "invalid_params" and not out.exists()


def test_unknown_category_is_an_error_object(tmp_path):
    req = CategoryFormModel("kick").build_request()
    result = run_job(RenderJob(req, tmp_path / "o", "punchy", {}, "tom"))
    assert not result.ok and result.error.kind == "invalid_params"


def test_engine_refusal_at_render_time_is_invalid_params_not_internal(tmp_path):
    def refuses(*a, **kw):
        raise ValueError("the click has no energy")

    req = CategoryFormModel("rim").build_request()
    result = run_job(RenderJob(req, tmp_path, "rim", {}, "rim"), writer=refuses)
    assert result.error.kind == "invalid_params" and "no energy" in result.error.detail
