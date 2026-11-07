"""Choice log entry format v0.1: contracts/choice-log.schema.json (#110, D-032).

Positive instances: ``tests/fixtures/choice_log/valid.jsonl`` and the converted answers of
listening test 1 (``lt1.jsonl``). Negative instances: ``invalid.json`` (patches on a base entry,
each with the one error it must raise). All are data, so a reader in another language can run
the same cases.

The LT1 expectations below are written by hand from the user's verbatim answers in
https://github.com/castorsalzmann-ui/AbeltonGod/issues/103#issuecomment-6494057184, not derived
from the fixture. The random entries are built by a generator in this file from the contract's
prose (docs/INTERFACES.md "Choice log"), not from the schema file.
"""

import copy
import json
import random
import string
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts" / "choice-log.schema.json").read_text(encoding="utf-8"))
SIDECAR_SCHEMA = json.loads(
    (ROOT / "contracts" / "sample-metadata.schema.json").read_text(encoding="utf-8"))
FIXTURES = ROOT / "tests" / "fixtures" / "choice_log"
VALIDATOR = Draft202012Validator(SCHEMA)


def read_jsonl(name: str) -> list[dict]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def errors(entry) -> set[tuple[str, str]]:
    """(JSON pointer of the instance location, failing keyword) of every error."""
    return {("".join(f"/{p}" for p in e.absolute_path), e.validator)
            for e in VALIDATOR.iter_errors(entry)}


def _decode(value):
    """{"$repeat": s, "times": n} stands for a long string (keeps the fixture short)."""
    if isinstance(value, dict):
        if set(value) == {"$repeat", "times"}:
            return value["$repeat"] * value["times"]
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def apply_patch(doc, patch: list[dict]):
    """RFC 6902 add / remove / replace on a deep copy (path '' = the whole document)."""
    doc = copy.deepcopy(doc)
    for step in patch:
        if step["path"] == "":
            doc = copy.deepcopy(step["value"])
            continue
        *parents, last = step["path"].split("/")[1:]
        target = doc
        for key in parents:
            target = target[key]
        if step["op"] == "remove":
            del target[last]
        else:
            assert step["op"] in ("add", "replace"), step
            target[last] = copy.deepcopy(step["value"])
    return doc


VALID = read_jsonl("valid.jsonl")
LT1 = read_jsonl("lt1.jsonl")
INVALID = _decode(json.loads((FIXTURES / "invalid.json").read_text(encoding="utf-8")))
BASE = VALID[0]


def test_schema_is_draft_2020_12():
    Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["properties"]["schema_version"] == {"const": "0.1"}


@pytest.mark.parametrize("entry", VALID + LT1, ids=lambda e: f"{e['source']}-{e['sample']['path']}")
def test_positive_instances(entry):
    assert errors(entry) == set()


def test_fixture_lines_are_single_json_objects():
    """JSONL: one object per line, no blank or wrapped lines in the fixtures."""
    for name in ("valid.jsonl", "lt1.jsonl"):
        text = (FIXTURES / name).read_text(encoding="utf-8")
        assert text.endswith("\n") and "\r" not in text
        for line in text.splitlines():
            assert isinstance(json.loads(line), dict), (name, line)


def test_negative_base_is_line_1_of_valid():
    assert INVALID["base"] == "valid.jsonl#1"
    assert errors(BASE) == set()


@pytest.mark.parametrize("case", INVALID["cases"], ids=lambda c: c["name"])
def test_negative_instances(case):
    """Each case fails with exactly its stated error, so it fails for that reason only."""
    assert errors(apply_patch(BASE, case["patch"])) == {(case["at"], case["keyword"])}


def test_negative_case_names_are_unique():
    names = [c["name"] for c in INVALID["cases"]]
    assert len(names) == len(set(names))


# --- listening test 1 ------------------------------------------------------------------------

# Written by hand from the user's answers (2026-10-29 11:19): pair -> (chosen, other, user words
# beyond the letter). "Schritt 0: weiß nicht" names no file and has no entry.
LT1_EXPECTED = [
    ("P1", "P1_B", "P1_A", None),
    ("P2", "P2_A", "P2_B", "im low end"),
    ("P3", "P3_A", "P3_B", "ist besser, vollmundiger"),
    ("P4", "P4_B", "P4_A", "4a mehr generisch, 4b sehr viel main character eher hardsytle kick"),
    ("P5", "P5_B", "P5_A", None),
    ("P6", "P6_B", "P6_A", None),
    ("closing", "P6_B", None, "am nächsten am Hauptcharakter: P6b"),
]


def test_lt1_entries_match_the_users_answers():
    assert len(LT1) == len(LT1_EXPECTED)
    for entry, (item, chosen, other, note) in zip(LT1, LT1_EXPECTED, strict=True):
        assert entry["source"] == "listening-test"
        assert entry["verdict"] == "favourite"
        assert entry["test"]["id"] == "LT1" and entry["test"]["item"] == item
        assert entry["sample"]["path"] == f"lt1/{chosen}.wav"
        if other is None:
            assert "compared_with" not in entry["test"]
        else:
            assert entry["test"]["compared_with"]["path"] == f"lt1/{other}.wav"
        assert entry.get("note") == note
        # The LT1 WAVs are not in the repo: their hashes are unknown and must not be invented.
        assert entry["sample"]["sha256"] is None and entry["sidecar"] is None
        assert entry["time"] == "2026-10-29T11:19:00+01:00"


# --- current verdict: parsed instants, not strings ---------------------------------------------

ORDER = read_jsonl("order.jsonl")


def instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def current_verdict(entries: list[dict]) -> str:
    """The contract's rule: newest parsed instant wins, equal instants -> the later line."""
    best = max(range(len(entries)), key=lambda i: (instant(entries[i]["time"]), i))
    return entries[best]["verdict"]


def test_order_fixture_is_valid():
    for entry in ORDER:
        assert errors(entry) == set()
    assert len({e["sample"]["sha256"] for e in ORDER}) == 1


def test_current_verdict_compares_instants_not_strings():
    # Line 1 is 10:30+01:00 = 09:30Z, line 2 is 09:45Z: by instant line 2 is newest.
    assert current_verdict(ORDER) == "favourite"
    # The case is discriminating: comparing the strings would pick line 1.
    assert max(ORDER, key=lambda e: e["time"])["verdict"] == "reject"


def test_current_verdict_equal_instants_take_the_later_line():
    # Without line 2, lines 1 and 3 are the same instant (09:30Z); line 3 is later in the file.
    assert current_verdict([ORDER[0], ORDER[2]]) == "neutral"
    assert max([ORDER[0], ORDER[2]], key=lambda e: e["time"])["verdict"] == "reject"


def test_parameters_copy_is_verbatim_sidecar_parameters():
    """The positive 'parameters' instance is the kick-v01 fixture sidecar's parameters."""
    sidecar = json.loads((ROOT / "tests" / "fixtures" / "sidecars" / "kick-v01.json")
                         .read_text(encoding="utf-8"))
    with_params = [e for e in VALID if e["sidecar"] and "parameters" in e["sidecar"]]
    assert len(with_params) == 1
    assert with_params[0]["sidecar"]["parameters"] == sidecar["parameters"]
    assert with_params[0]["sidecar"]["seed"] == sidecar["parameters"]["seed"]


# --- cross-contract and seeded property tests ------------------------------------------------

def test_every_sidecar_category_fits_the_category_field():
    categories = SIDECAR_SCHEMA["properties"]["category"]["enum"]
    assert categories, "sample-metadata has no category enum any more"
    for category in categories:
        entry = apply_patch(
            BASE, [{"op": "replace", "path": "/sample/category", "value": category}])
        assert errors(entry) == set(), category


SEGMENT_CHARS = string.ascii_letters + string.digits + " _-.()äöüßé#&+,=@[]{}~'!$%"


def random_segment(rng: random.Random) -> str:
    while True:
        seg = "".join(rng.choice(SEGMENT_CHARS) for _ in range(rng.randint(1, 24)))
        if seg not in (".", ".."):
            return seg


def random_path(rng: random.Random) -> str:
    segs = [random_segment(rng) for _ in range(rng.randint(0, 5))]
    name = random_segment(rng) + rng.choice([".wav", ".WAV", ".Wav"])
    return "/".join([*segs, name])


def random_time(rng: random.Random) -> str:
    stamp = (f"{rng.randint(1, 9999):04d}-{rng.randint(1, 12):02d}-{rng.randint(1, 31):02d}"
             f"T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}")
    if rng.random() < 0.5:
        stamp += "." + "".join(rng.choice(string.digits) for _ in range(rng.randint(1, 6)))
    if rng.random() < 0.5:
        return stamp + "Z"
    return stamp + f"{rng.choice('+-')}{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}"


def random_entry(rng: random.Random) -> dict:
    source = rng.choice(["gui", "listening-test"])
    sha = "".join(rng.choice("0123456789abcdef") for _ in range(64))
    if source == "listening-test" and rng.random() < 0.5:
        sha = None
    entry = {
        "schema_version": "0.1",
        "time": random_time(rng),
        "verdict": rng.choice(["favourite", "reject", "neutral"]),
        "sample": {"path": random_path(rng), "sha256": sha,
                   "category": rng.choice([None, "kick", "perc", "fx_riser", "a"])},
        "sidecar": None if rng.random() < 0.3 else {
            "engine": {"name": "abeltongod-audio-engine-" + random_segment(rng),
                       "version": f"{rng.randint(0, 9)}.{rng.randint(0, 99)}.{rng.randint(0, 99)}"},
            "preset": rng.choice([None, "punchy", random_segment(rng)]),
            "seed": rng.choice([None, 0, rng.randint(0, 2**32 - 1), 2**32 - 1])},
        "source": source,
    }
    if entry["sidecar"] is not None and rng.random() < 0.5:
        entry["sidecar"]["parameters"] = {"seed": rng.randint(0, 2**32 - 1),
                                          "drive": rng.random(), "preset": None}
    if rng.random() < 0.5:
        entry["note"] = "".join(rng.choice(SEGMENT_CHARS + "\n\t\"\\")
                                for _ in range(rng.randint(1, 2000)))
    if source == "listening-test":
        entry["test"] = {"id": "LT" + str(rng.randint(1, 99)),
                         "item": rng.choice(["P1", "closing", "x_2", "Q-10", "a" * 32])}
        if rng.random() < 0.7:
            entry["test"]["compared_with"] = {"path": random_path(rng), "sha256": None}
    return entry


# One mutation per main rule; each must turn a valid random entry invalid.
MUTATIONS = {
    "drive letter": lambda e: e["sample"].__setitem__("path", "D:/" + e["sample"]["path"]),
    "leading slash": lambda e: e["sample"].__setitem__("path", "/" + e["sample"]["path"]),
    "parent segment": lambda e: e["sample"].__setitem__("path", "a/../" + e["sample"]["path"]),
    "dot segment": lambda e: e["sample"].__setitem__("path", "./" + e["sample"]["path"]),
    "backslash": lambda e: e["sample"].__setitem__("path", e["sample"]["path"].replace(
        e["sample"]["path"][0], "\\", 1)),
    "not wav": lambda e: e["sample"].__setitem__("path", e["sample"]["path"][:-4] + ".aif"),
    "short sha": lambda e: e["sample"].__setitem__("sha256", "ab" * 31),
    "no offset": lambda e: e.__setitem__("time", e["time"].rstrip("Z").split("+")[0][:19]),
    "bad verdict": lambda e: e.__setitem__("verdict", "maybe"),
    "extra key": lambda e: e.__setitem__("score", 1),
    "no source": lambda e: e.pop("source"),
}


@pytest.mark.parametrize("seed", range(20))
def test_random_entries_valid_and_mutations_rejected(seed):
    rng = random.Random(seed)
    for _ in range(25):
        entry = random_entry(rng)
        assert errors(entry) == set(), entry
        for name, mutate in MUTATIONS.items():
            bad = copy.deepcopy(entry)
            mutate(bad)
            assert errors(bad), (name, bad)
