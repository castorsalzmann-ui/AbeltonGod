"""Category-aware import (clap next to kick) against the fake AbletonOSC server.

CI only: nothing here talks to Ableton Live. The import sends the same tested functions for
every category; these tests show that a registered category is accepted, that unknown or
unregistered ones are refused before any connection, and what the user is told.
"""

from __future__ import annotations

import importlib.util
import io
import json
import socket
import sys
from pathlib import Path

import pytest
from fake_abletonosc import FakeAbletonOSC

from audio_engine import categories
from bridge.clip_import import ImportPathError
from bridge.sample_info import SampleCategoryError, read_sample_info
from library import place_sample

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("live_import", ROOT / "scripts" / "live_import.py")
live_import = importlib.util.module_from_spec(spec)
sys.modules["live_import"] = live_import
spec.loader.exec_module(live_import)

CREATE_CLIP = "/live/clip_slot/create_audio_clip"
CREATE_TRACK = "/live/song/create_audio_track"
UNDO = "/live/song/undo"
PROBE = (CREATE_CLIP, ())
KICK = {"schema_version": "0.3", "seed": 4}
CLAP = {"schema_version": "0.1", "seed": 3}


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def fake():
    server = FakeAbletonOSC()
    server.tracks = [{"name": "1-Audio", "mute": False, "audio": True, "slots": [None] * 4}]
    yield server
    server.close()


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "P"
    p.mkdir()
    return p


def run(fake, tmp_path, wav, answers):
    receive = free_udp_port()
    fake.response_port = receive
    queue = list(answers)
    prompts: list[str] = []

    def input_fn(prompt):
        prompts.append(prompt)
        return queue.pop(0)

    out = io.StringIO()
    code = live_import.main(
        [str(wav), "--send-port", str(fake.port), "--receive-port", str(receive),
         "--timeout", "5", "--log", str(tmp_path / "actions.jsonl")],
        input_fn=input_fn, out=out)
    return code, out.getvalue(), prompts


def sent(fake):
    return [m for m in fake.payload() if m != PROBE and m[0] in (CREATE_CLIP, CREATE_TRACK, UNDO)]


def block(text):
    body = text.split("```text\n", 1)[1].split("```", 1)[0]
    return dict(line.split(": ", 1) for line in body.splitlines()
                if ": " in line and not line.startswith("  "))


def test_clap_imports_with_the_same_tested_functions(fake, tmp_path, project):
    wav = place_sample("clap", CLAP, project, name="tight")
    assert wav.parent == project / "Samples" / "Drums" / "Claps"
    # test set, track 0, run, no undo, "does it play"
    code, out, prompts = run(fake, tmp_path, wav, ["y", "0", "y", "n", "y"])
    assert code == 0, out
    assert sent(fake) == [(CREATE_CLIP, (0, 0, str(wav)))]
    assert "Sample: clap: tight" in out
    assert any("Spielt der Clap?" in q for q in prompts)
    b = block(out)
    assert b["sample_category"] == "clap"
    assert b["clip_slot.create_audio_clip"] == "PASS"
    assert b["clip_file_path_read"] == repr(str(wav))


def test_kick_still_imports_and_is_labelled(fake, tmp_path, project):
    wav = place_sample("kick", KICK, project, name="deep")
    code, out, prompts = run(fake, tmp_path, wav, ["y", "0", "y", "n", "y"])
    assert code == 0, out
    assert "Sample: kick: deep" in out
    assert block(out)["sample_category"] == "kick"
    assert any("Spielt der Kick?" in q for q in prompts)


HAT = {"schema_version": "0.1", "seed": 5}


def test_hat_imports_with_the_same_tested_functions(fake, tmp_path, project):
    wav = place_sample("hat", HAT, project, name="closed")
    assert wav.parent == project / "Samples" / "Drums" / "Hats"
    code, out, prompts = run(fake, tmp_path, wav, ["y", "0", "y", "n", "y"])
    assert code == 0, out
    assert sent(fake) == [(CREATE_CLIP, (0, 0, str(wav)))]  # no rename, no new function
    assert "Sample: hat: closed" in out
    assert any("Spielt der Hat?" in q for q in prompts)
    b = block(out)
    assert b["sample_category"] == "hat"
    assert b["clip_slot.create_audio_clip"] == "PASS"


def test_hat_in_the_clap_folder_is_refused(fake, tmp_path, project):
    wav = place_sample("hat", HAT, project)
    claps = project / "Samples" / "Drums" / "Claps"
    claps.mkdir()
    moved = wav.rename(claps / wav.name)
    wav.with_suffix(".json").rename(claps / wav.with_suffix(".json").name)
    refused_without_connecting(fake, tmp_path, moved, "Hats")


def test_clap_in_the_hat_folder_is_refused(fake, tmp_path, project):
    wav = place_sample("clap", CLAP, project)
    hats = project / "Samples" / "Drums" / "Hats"
    hats.mkdir()
    moved = wav.rename(hats / wav.name)
    wav.with_suffix(".json").rename(hats / wav.with_suffix(".json").name)
    refused_without_connecting(fake, tmp_path, moved, "Claps")


def test_unregistered_hat_is_refused_before_any_message(fake, tmp_path, project, monkeypatch):
    wav = place_sample("hat", HAT, project)
    monkeypatch.delitem(categories._REGISTRY, "hat")
    refused_without_connecting(fake, tmp_path, wav, "hat")


RIM = {"schema_version": "0.1", "seed": 6}
BASS = {"schema_version": "0.1", "seed": 7, "gate_ms": 400}


def _move(wav, folder):
    folder.mkdir(parents=True)
    moved = wav.rename(folder / wav.name)
    wav.with_suffix(".json").rename(folder / wav.with_suffix(".json").name)
    return moved


@pytest.mark.parametrize("category, params, parts, label", [
    ("rim", RIM, ("Samples", "Drums", "Rims"), "Rim"),
    ("bass", BASS, ("Samples", "Bass"), "Bass"),
])
def test_rim_and_bass_import_with_the_same_tested_functions(
        fake, tmp_path, project, category, params, parts, label):
    wav = place_sample(category, params, project, name="one")
    assert wav.parent == project.joinpath(*parts)
    code, out, prompts = run(fake, tmp_path, wav, ["y", "0", "y", "n", "y"])
    assert code == 0, out
    assert sent(fake) == [(CREATE_CLIP, (0, 0, str(wav)))]  # no rename, no new function
    assert f"Sample: {category}: one" in out
    assert any(f"Spielt der {label}?" in q for q in prompts)
    b = block(out)
    assert b["sample_category"] == category
    assert b["clip_slot.create_audio_clip"] == "PASS"


@pytest.mark.parametrize("category, params, wrong, needle", [
    ("rim", RIM, ("Samples", "Drums", "Claps"), "Rims"),
    ("rim", RIM, ("Samples", "Bass"), "Rims"),
    ("bass", BASS, ("Samples", "Drums", "Rims"), "Bass"),
    ("bass", BASS, ("Samples", "Drums", "Kicks"), "Bass"),
])
def test_rim_and_bass_in_a_wrong_folder_are_refused(
        fake, tmp_path, project, category, params, wrong, needle):
    wav = place_sample(category, params, project)
    moved = _move(wav, project.joinpath(*wrong))
    refused_without_connecting(fake, tmp_path, moved, needle)


def test_clap_in_the_rim_and_bass_folders_is_refused(fake, tmp_path, project):
    for parts, needle in ((("Samples", "Drums", "Rims"), "Claps"), (("Samples", "Bass"), "Claps")):
        wav = place_sample("clap", CLAP, project, name=parts[-1].lower())
        refused_without_connecting(fake, tmp_path, _move(wav, project.joinpath(*parts)), needle)


@pytest.mark.parametrize("category, params", [("rim", RIM), ("bass", BASS)])
def test_unregistered_rim_and_bass_are_refused_before_any_message(
        fake, tmp_path, project, monkeypatch, category, params):
    wav = place_sample(category, params, project)
    monkeypatch.delitem(categories._REGISTRY, category)
    refused_without_connecting(fake, tmp_path, wav, category)


SNARE = {"schema_version": "0.1", "seed": 8}


def test_snare_imports_with_the_same_tested_functions(fake, tmp_path, project):
    wav = place_sample("snare", SNARE, project, name="crack")
    assert wav.parent == project / "Samples" / "Drums" / "Snares"
    code, out, prompts = run(fake, tmp_path, wav, ["y", "0", "y", "n", "y"])
    assert code == 0, out
    assert sent(fake) == [(CREATE_CLIP, (0, 0, str(wav)))]  # no rename, no new function
    assert "Sample: snare: crack" in out
    assert any("Spielt der Snare?" in q for q in prompts)
    b = block(out)
    assert b["sample_category"] == "snare"
    assert b["clip_slot.create_audio_clip"] == "PASS"
    assert b["clip_file_path_read"] == repr(str(wav))


@pytest.mark.parametrize("wrong", [
    ("Samples", "Drums", "Claps"), ("Samples", "Drums", "Kicks"), ("Samples", "Drums", "Hats"),
    ("Samples", "Drums", "Rims"), ("Samples", "Bass"),
])
def test_snare_in_a_wrong_folder_is_refused(fake, tmp_path, project, wrong):
    wav = place_sample("snare", SNARE, project)
    moved = _move(wav, project.joinpath(*wrong))
    refused_without_connecting(fake, tmp_path, moved, "Snares")


@pytest.mark.parametrize("category, params, parts", [
    ("clap", CLAP, ("Samples", "Drums", "Snares")),
    ("hat", HAT, ("Samples", "Drums", "Snares")),
    ("rim", RIM, ("Samples", "Drums", "Snares")),
    ("kick", KICK, ("Samples", "Drums", "Snares")),
])
def test_other_categories_in_the_snare_folder_are_refused(
        fake, tmp_path, project, category, params, parts):
    wav = place_sample(category, params, project)
    moved = _move(wav, project.joinpath(*parts))
    refused_without_connecting(fake, tmp_path, moved, {"clap": "Claps", "hat": "Hats",
                                                       "rim": "Rims", "kick": "Kicks"}[category])


def test_unregistered_snare_is_refused_before_any_message(fake, tmp_path, project, monkeypatch):
    wav = place_sample("snare", SNARE, project)
    monkeypatch.delitem(categories._REGISTRY, "snare")
    refused_without_connecting(fake, tmp_path, wav, "snare")


def refused_without_connecting(fake, tmp_path, wav, needle):
    code, out, prompts = run(fake, tmp_path, wav, [])
    assert code == live_import.EXIT_SETUP_ERROR, out
    assert needle in out
    assert "nichts in Live geändert" in out
    assert fake.payload() == [] and prompts == []  # no message at all, not even the probe


def test_unknown_category_is_refused_before_any_message(fake, tmp_path, project):
    wav = place_sample("clap", CLAP, project)
    side = wav.with_suffix(".json")
    meta = json.loads(side.read_text(encoding="utf-8"))
    meta["category"] = "cowbell"  # not in the contract (snare is, since #308)
    side.write_text(json.dumps(meta), encoding="utf-8")
    refused_without_connecting(fake, tmp_path, wav, "cowbell")


def test_unregistered_category_is_refused_before_any_message(fake, tmp_path, project,
                                                             monkeypatch):
    wav = place_sample("clap", CLAP, project)
    monkeypatch.delitem(categories._REGISTRY, "clap")  # contract names it, engine has no voice
    refused_without_connecting(fake, tmp_path, wav, "clap")


@pytest.mark.parametrize("content", ["{not json", "[]", '{"file": "x.wav"}', '{"category": 3}'])
def test_unreadable_or_category_less_sidecar_is_refused(fake, tmp_path, project, content):
    wav = place_sample("clap", CLAP, project)
    wav.with_suffix(".json").write_text(content, encoding="utf-8")
    refused_without_connecting(fake, tmp_path, wav, "Sidecar")


def test_clap_in_the_kick_folder_is_refused(fake, tmp_path, project):
    wav = place_sample("clap", CLAP, project)
    kicks = project / "Samples" / "Drums" / "Kicks"
    kicks.mkdir()
    moved = wav.rename(kicks / wav.name)
    wav.with_suffix(".json").rename(kicks / wav.with_suffix(".json").name)
    refused_without_connecting(fake, tmp_path, moved, "Claps")


def test_wav_without_sidecar_keeps_the_old_behaviour(tmp_path):
    plain = tmp_path / "hand made.wav"
    plain.write_bytes(b"RIFF\0\0\0\0WAVE")
    info = read_sample_info(plain)
    assert info.category is None and info.label == "hand made"


def test_error_is_an_import_path_error(tmp_path, project):
    wav = place_sample("clap", CLAP, project)
    wav.with_suffix(".json").write_text("{", encoding="utf-8")
    with pytest.raises(ImportPathError):
        read_sample_info(wav)
    with pytest.raises(SampleCategoryError):
        read_sample_info(wav)
