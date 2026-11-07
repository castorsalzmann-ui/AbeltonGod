"""Kit manifest v0.1: contracts/kit.schema.json (#498, D-032).

The base instance and every mutation are written here by hand from the prose in
docs/INTERFACES.md "Kit manifest"; the random manifests come from a generator in this file,
not from the schema or from gui_core.kit."""

import copy
import json
import random
import string
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "contracts" / "kit.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
SHA = "0123456789abcdef" * 4

SLOT_CATEGORIES = {
    "kick": ["kick"], "clap_snare": ["clap", "snare"], "closed_hat": ["hat"],
    "open_hat": ["hat"], "rim": ["rim"], "perc": ["perc"], "bass": ["bass"],
}
REQUIRED = ["kick", "clap_snare", "closed_hat", "open_hat", "rim", "perc"]


def item(n: int, cat: str) -> dict:
    return {"file": f"{n:02d}_{cat}_{cat}-x.wav", "sha256": SHA,
            "source": f"Samples/Drums/{cat}-x.wav", "category": cat}


BASE = {
    "schema_version": "0.1",
    "name": "Peak-Time",
    "created_at": "2026-11-07T12:00:00Z",
    "slots": {k: item(i, cats[0]) for i, (k, cats) in enumerate(SLOT_CATEGORIES.items(), 1)},
}


def with_(path: str, value=None, remove: bool = False) -> dict:
    doc = copy.deepcopy(BASE)
    *parents, last = path.split("/")
    target = doc
    for key in parents:
        target = target[key]
    if remove:
        del target[last]
    else:
        target[last] = value
    return doc


def test_schema_is_draft_2020_12_and_base_is_valid():
    Draft202012Validator.check_schema(SCHEMA)
    assert list(VALIDATOR.iter_errors(BASE)) == []


def test_bass_may_be_left_out_and_snare_fits_the_clap_slot():
    assert VALIDATOR.is_valid(with_("slots/bass", remove=True))
    assert VALIDATOR.is_valid(with_("slots/clap_snare/category", "snare"))
    assert VALIDATOR.is_valid(with_("created_at", "2026-11-07T13:00:00.5+01:00"))


BAD = [
    ("schema_version", "0.2"),
    ("name", ""), ("name", "a b"), ("name", "x" * 81), ("name", "ä"), ("name", "a/b"),
    ("created_at", "2026-11-07 12:00:00Z"), ("created_at", "2026-11-07T12:00:00"),
    ("created_at", "2026-13-07T12:00:00Z"),
    ("slots/bass", None),
    ("slots/drum", item(9, "kick")),
    ("slots/kick/category", "hat"), ("slots/closed_hat/category", "kick"),
    ("slots/clap_snare/category", "kick"), ("slots/bass/category", "kick"),
    ("slots/kick/sha256", SHA.upper()), ("slots/kick/sha256", SHA[:-1]),
    ("slots/kick/file", "kick.wav"), ("slots/kick/file", "1_kick.wav"),
    ("slots/kick/file", "01_kick/x.wav"), ("slots/kick/file", "01_kick.json"),
    ("slots/kick/source", "/abs/k.wav"), ("slots/kick/source", "C:/k.wav"),
    ("slots/kick/source", "a/../k.wav"), ("slots/kick/source", "a\\k.wav"),
    ("slots/kick/source", "a//k.wav"), ("slots/kick/source", "a/k.mp3"),
    ("slots/kick/extra", 1), ("extra", 1),
]


@pytest.mark.parametrize("path,value", BAD, ids=[f"{p}={v!r}"[:40] for p, v in BAD])
def test_one_broken_rule_is_refused(path, value):
    assert not VALIDATOR.is_valid(with_(path, value))


@pytest.mark.parametrize("path", ["schema_version", "name", "created_at", "slots",
                                  *[f"slots/{k}" for k in REQUIRED],
                                  "slots/kick/file", "slots/kick/sha256", "slots/kick/source",
                                  "slots/kick/category"])
def test_required_keys(path):
    assert not VALIDATOR.is_valid(with_(path, remove=True))


def test_seeded_random_manifests_from_the_prose_are_valid():
    rng = random.Random(4980)
    safe = string.ascii_letters + string.digits + "._-"
    for _ in range(300):
        slots = {}
        for n, (key, cats) in enumerate(SLOT_CATEGORIES.items(), 1):
            if key == "bass" and rng.random() < 0.5:
                continue
            cat = rng.choice(cats)
            stem = "".join(rng.choice(safe) for _ in range(rng.randint(1, 120)))
            src = "/".join("".join(rng.choice(string.ascii_letters + " ü-") for _ in
                                   range(rng.randint(1, 12))).strip(". ") or "d"
                           for _ in range(rng.randint(0, 4)))
            slots[key] = {"file": f"{n:02d}_{stem}.wav",
                          "sha256": "".join(rng.choice("0123456789abcdef") for _ in range(64)),
                          "source": (src + "/" if src else "") + "x.WAV",
                          "category": cat}
        doc = {"schema_version": "0.1",
               "name": "".join(rng.choice(safe) for _ in range(rng.randint(1, 80))),
               "created_at": f"20{rng.randint(10, 99)}-{rng.randint(1, 12):02d}-"
                             f"{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:"
                             f"{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z",
               "slots": slots}
        assert list(VALIDATOR.iter_errors(doc)) == [], doc
