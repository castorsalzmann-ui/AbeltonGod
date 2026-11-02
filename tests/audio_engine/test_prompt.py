"""Issue #233: keyword prompt parser (src/audio_engine/prompt.py).

Expected values are typed by hand from the vocabulary note
(docs/research/2026-11-02_kick-keyword-vocabulary.md, sections 2-4), e.g. 200 * 1.3 ** 0.5 =
228.035085, not computed by the parser. The property test restates the weight formulas
separately in the test and draws weights over the whole 0 ... 2 range.
"""

from __future__ import annotations

import io
import json
import random

import numpy as np
import pytest

import audio_engine.cli as cli
from audio_engine.kick import render_kick
from audio_engine.params import KICK_SCHEMA_FILE, load_schema, pitch_settles, resolve_kick_params
from audio_engine.presets import load_preset
from audio_engine.prompt import PromptError, parse_prompt

WEIGHTS = (0, 0.5, 1, 1.5, 2)

# keyword -> field -> expected value at w = 0, 0.5, 1, 1.5, 2 (hand-written; the pitch_decay_ms
# cuts of sub:0 / sub:0.5 / tail:0 / tail:0.5 are the pitch-settle rule: note 4.4 gives 43.7
# for sub:0 and 34.3 for tail:0).
TABLE = {
    "sub": {
        "pitch_start_hz": (240.0, 219.089023, 200.0, 182.574186, 166.666667),
        "pitch_decay_ms": (43.721024, 44.959399, 40.0, 35.082321, 30.769231),
    },
    "punch": {"pitch_start_hz": (153.846154, 175.411604, 200.0, 228.035085, 260.0)},
    "click": {"click_level": (0.0, 0.175, 0.35, 0.525, 0.7)},
    "bite": {"click_tone_hz": (2333.333333, 2857.738033, 3500.0, 4286.60705, 5250.0)},
    "tail": {
        "amp_decay_ms": (414.814815, 481.971261, 560.0, 650.661202, 756.0),
        "length_ms": (355.555556, 413.118224, 480.0, 557.709602, 648.0),
        "pitch_decay_ms": (34.334952, 39.873581, 40.0, 40.0, 40.0),
    },
    "drive": {"drive": (0.0, 0.225, 0.45, 0.675, 0.9)},
    "wums": {"clip_db": (0.0, 1.5, 3.0, 4.5, 6.0)},
    "bright": {"tone": (-0.5, -0.25, 0.0, 0.25, 0.5)},
}
DENSE = {
    "pitch_start_hz": 200.0, "pitch_end_hz": 52.0, "pitch_decay_ms": 40.0, "click_level": 0.35,
    "click_tone_hz": 3500.0, "amp_decay_ms": 560.0, "length_ms": 480.0, "drive": 0.45,
    "clip_db": 0.0, "tone": 0.0,
}


@pytest.mark.parametrize("word", TABLE)
@pytest.mark.parametrize("i", range(5))
def test_weight_table(word, i):
    p = parse_prompt(f"{word}:{WEIGHTS[i]}").params
    expected = dict(DENSE)
    for fld, values in TABLE[word].items():
        expected[fld] = values[i]
    for fld, value in expected.items():
        assert p[fld] == pytest.approx(value, rel=1e-6, abs=1e-9), (word, WEIGHTS[i], fld)
    assert p["schema_version"] == "0.3"


def test_empty_prompt_is_dense_and_renders_the_same_bytes():
    parsed = parse_prompt("")
    assert parsed.adjustments == []
    ref = load_preset("dense")
    a, _ = render_kick(parsed.params)
    b, _ = render_kick(ref)
    assert np.array_equal(a, b)


def test_aliases_and_worked_examples():
    # vocabulary section 3 aliases and prompt P2 / P3 / P9
    assert parse_prompt("kurz").params == parse_prompt("tail:0.4").params
    assert parse_prompt("lang").params == parse_prompt("tail:1.6").params
    assert parse_prompt("dunkel").params["tone"] == pytest.approx(-0.3)
    assert parse_prompt("hell").params["tone"] == pytest.approx(0.3)
    assert parse_prompt("sauber").params["drive"] == pytest.approx(0.225)
    p2 = parse_prompt("kurz, punch:1.2, click:1.2")
    assert p2.params["amp_decay_ms"] == pytest.approx(468, abs=0.5)
    assert p2.params["length_ms"] == pytest.approx(401, abs=0.5)
    assert p2.params["pitch_start_hz"] == pytest.approx(211, abs=0.5)
    assert p2.params["click_level"] == pytest.approx(0.42)
    assert p2.params["pitch_decay_ms"] == pytest.approx(38.0, abs=0.05)  # settle cut 40 -> 38.0
    assert [a.kind for a in p2.adjustments] == ["pitch_settle"]
    p9 = parse_prompt("sub:2, punch:2")  # opposing words: 200 / 1.2 * 1.3 = 216.67
    assert p9.params["pitch_start_hz"] == pytest.approx(216.666667, rel=1e-6)
    assert p9.params["pitch_decay_ms"] == pytest.approx(30.769231, rel=1e-6)
    assert parse_prompt("kurz, lang").params["amp_decay_ms"] == pytest.approx(560, rel=1e-6)


def test_same_prompt_same_output_and_spelling_variants():
    a = parse_prompt("sub:1.5, punch:1.2, dunkel, note:Am")
    b = parse_prompt("  SUB : 1.5 punch:1.2   Dunkel,note:Am ")
    assert a.params == b.params and a.adjustments == b.adjustments
    assert json.dumps(a.params, sort_keys=True) == json.dumps(
        parse_prompt("sub:1.5, punch:1.2, dunkel, note:Am").params, sort_keys=True)


def test_clamp_is_reported():
    # sauber (-0.5 steps) + drive:0 (-1 step): 0.45 - 0.675 < 0 -> clamped to the contract's 0
    parsed = parse_prompt("sauber, drive:0")
    assert parsed.params["drive"] == 0.0
    [adj] = parsed.adjustments
    assert (adj.kind, adj.field) == ("clamp", "drive")
    assert adj.requested == pytest.approx(-0.225) and adj.applied == 0.0
    assert "drive" in str(adj) and "0 ... 1" in str(adj)


@pytest.mark.parametrize(
    ("word", "field", "value"),
    [("sub", "pitch_start_hz", 200.0), ("punch", "pitch_start_hz", 200.0),
     ("click", "click_level", 0.35), ("bite", "click_tone_hz", 3500.0),
     ("tail", "amp_decay_ms", 560.0), ("drive", "drive", 0.45), ("wums", "clip_db", 3.0),
     ("bright", "tone", 0.0)],
)
def test_bare_keyword_is_weight_one(word, field, value):
    # no weight = w 1 = dense (wums: the typical 3 dB)
    assert parse_prompt(word).params[field] == pytest.approx(value, rel=1e-9)


# --- slots -------------------------------------------------------------------------------------

# Camelot code -> tail_note, typed from the note table (genre-words note, section 4).
CAMELOT = {
    "2A": 27, "5B": 27, "9A": 28, "12B": 28, "4A": 29, "7B": 29, "11A": 30, "2B": 30,
    "6A": 31, "9B": 31, "1A": 32, "4B": 32, "8A": 33, "11B": 33, "3A": 34, "6B": 34,
    "10A": 35, "1B": 35, "5A": 36, "8B": 36, "12A": 37, "3B": 37, "7A": 38, "10B": 38,
}


@pytest.mark.parametrize(("code", "note"), CAMELOT.items())
def test_camelot(code, note):
    assert parse_prompt(f"key:{code}").params["tail_note"] == note


@pytest.mark.parametrize(
    ("text", "note"),
    [("32", 32), ("23", 23), ("46", 46), ("G#1", 32), ("Ab1", 32), ("A1", 33), ("C2", 36),
     ("Am", 33), ("A", 33), ("C", 36), ("Bb", 34), ("bm", 35), ("g#", 32), ("D#", 27),
     ("D", 38), ("E", 28)],
)
def test_note_names(text, note):
    parsed = parse_prompt(f"note:{text}")
    assert parsed.params["tail_note"] == note and "pitch_end_hz" not in parsed.params
    assert parsed.note_midi == note


def test_other_slots_and_beats():
    p = parse_prompt("seed:7 variants:3 bpm:136 beats:1, tail:1.5").params
    assert (p["seed"], p["variants"], p["bpm"], p["length_beats"]) == (7, 3, 136, 1)
    assert "length_ms" not in p and "amp_decay_ms" not in p
    parsed = parse_prompt("bpm:136, beats:1, tail:1.5")
    assert parsed.adjustments[0].kind == "ignored"  # a settle cut may follow
    resolved = resolve_kick_params(parsed.params)
    assert resolved["length_ms"] == pytest.approx(441.176471, rel=1e-6)


@pytest.mark.parametrize(
    ("prompt", "needle"),
    [
        ("sup:1", "Did you mean 'sub'"),
        ("sub:2.01", "0 ... 2"),
        ("sub:-0.1", "0 ... 2"),
        ("sub:nan", "must be a number"),
        ("sub:abc", "must be a number"),
        ("sub:1, sub:1.2", "appears twice"),
        ("kurz:0.5", "fixed-weight alias"),
        ("note", "needs a value"),
        ("note:47", "23 ... 46"),
        ("note:G#5", "outside 23 ... 46"),
        ("note:Am1", "cannot be combined"),
        ("note:32, key:8A", "only one"),
        ("key:13A", "Camelot"),
        ("beats:1", "needs bpm"),
        ("bpm:30", "60 ... 200"),
        ("variants:9", "1 ... 8"),
        ("seed:-1", "0 ... 4294967295"),
    ],
)
def test_errors(prompt, needle):
    with pytest.raises(PromptError, match="Cannot parse") as exc:
        parse_prompt(prompt)
    assert needle in str(exc.value)


def test_all_problems_listed_and_engine_rejection_is_a_prompt_error():
    with pytest.raises(PromptError) as exc:
        parse_prompt("foo, sub:3, bar")
    text = str(exc.value)
    assert "'foo'" in text and "'bar'" in text and "sub:3" in text
    with pytest.raises(PromptError, match="engine rejects"):  # 0.25 beats at 190 BPM
        parse_prompt("bpm:190 beats:0.25")


# --- property: whole weight range ----------------------------------------------------------------


def _expected(w: dict[str, float]) -> dict[str, float]:
    """Pre-settle field values from the vocabulary formulas (written here, not imported)."""
    s = lambda k: w.get(k, 1.0) - 1.0  # noqa: E731
    out = {
        "pitch_start_hz": 200 * (1 / 1.2) ** s("sub") * 1.3 ** s("punch"),
        "click_level": 0.35 + s("click") * 0.35,
        "click_tone_hz": 3500 * 1.5 ** s("bite"),
        "amp_decay_ms": 560 * 1.35 ** s("tail"),
        "length_ms": 480 * 1.35 ** s("tail"),
        "drive": 0.45 + s("drive") * 0.45,
        "clip_db": 3 * w.get("wums", 0.0),
        "tone": s("bright") * 0.5,
    }
    props = load_schema(KICK_SCHEMA_FILE)["properties"]
    for fld, value in out.items():
        lo, hi = (0, 12) if fld == "clip_db" else (props[fld]["minimum"], props[fld]["maximum"])
        out[fld] = min(max(value, lo), hi)
    return out


@pytest.mark.parametrize("seed", range(40))
def test_random_weights_over_the_whole_range(seed):
    rng = random.Random(seed)
    words = ["sub", "punch", "click", "bite", "tail", "drive", "wums", "bright"]
    chosen = rng.sample(words, rng.randint(1, 8))
    w = {k: round(rng.uniform(0, 2), 3) for k in chosen}
    prompt = ", ".join(f"{k}:{v}" for k, v in w.items())
    parsed = parse_prompt(prompt)
    p = parsed.params
    for fld, value in _expected(w).items():
        assert p[fld] == pytest.approx(value, rel=1e-5, abs=1e-6), (prompt, fld)
    resolve_kick_params(p)  # inside the contract
    assert pitch_settles(p), prompt
    assert p["pitch_decay_ms"] <= 40 * 1.3 ** 1 + 1e-9
    assert parse_prompt(prompt).params == p  # deterministic


# --- CLI ---------------------------------------------------------------------------------------


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    return cli.main(argv, stdout=out, stderr=err), out.getvalue(), err.getvalue()


def test_cli_prompt_writes_files_with_prompt_in_description(tmp_path):
    prompt = "sub:1.5, punch:1.2, dunkel, note:Am"
    code, out, err = run(["--prompt", prompt, "--out", str(tmp_path / "a"), "--seed", "5"])
    assert code == 0, err
    [meta_file] = list((tmp_path / "a").glob("*.json"))
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert prompt in meta["description"]
    assert meta["parameters"]["seed"] == 5
    assert meta["parameters"]["pitch_end_hz"] == pytest.approx(55.0)
    code, _, err = run(["--prompt", prompt, "--out", str(tmp_path / "b"), "--seed", "5"])
    assert code == 0, err
    a = next((tmp_path / "a").glob("*.wav")).read_bytes()
    b = next((tmp_path / "b").glob("*.wav")).read_bytes()
    assert a == b


def test_cli_prints_adjustments_and_rejects_bad_use(tmp_path):
    code, out, _ = run(["--prompt", "kurz", "--out", str(tmp_path / "c")])
    assert code == 0 and "adjusted: pitch_decay_ms" in out
    for argv in (["--prompt", "wobble", "--out", str(tmp_path / "d")],
                 ["--prompt", "sub", "--preset", "dense", "--out", str(tmp_path / "d")],
                 ["--prompt", "seed:3", "--seed", "4", "--out", str(tmp_path / "d")]):
        code, _, err = run(argv)
        assert code == 2 and err.startswith("error:")
        assert not (tmp_path / "d").exists()
    code, _, err = run(["--prompt", "sub:1", "--category", "clap", "--out", str(tmp_path / "d")])
    assert code == 2 and "clap" in err and "Traceback" not in err
    assert not (tmp_path / "d").exists()
