"""gui_core.live against the fake AbletonOSC server.

CI only: nothing here talks to Ableton Live. These tests show what the service sends, refuses and
logs; whether Live behaves like the fake is what a run on the user's machine shows.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from live_helpers import (  # noqa: E402
    config_for,
    free_udp_port,
    make_fake,
    registry_with_status,
    write_wav,
    writes,
)

from bridge.capabilities import CapabilityRegistry  # noqa: E402
from gui_core import live  # noqa: E402

CREATE_CLIP = "/live/clip_slot/create_audio_clip"
CREATE_TRACK = "/live/song/create_audio_track"


@pytest.fixture
def fake():
    server = make_fake()
    yield server
    server.close()


@pytest.fixture
def wav(tmp_path):
    return write_wav(tmp_path / "Kick 1.wav")


def test_required_caps_exist_in_the_registry_and_gate_text_follows_their_status(tmp_path):
    reg = CapabilityRegistry.from_file()
    assert set(live.REQUIRED_CAPS) <= set(reg.ids())
    rows = live.capability_rows(reg)
    assert [r.status for r in rows] == [reg.get(c).status for c in live.REQUIRED_CAPS]
    bad = registry_with_status(tmp_path, {"clip_slot.create_audio_clip": "supported"})
    text = live.gate_text(live.capability_rows(bad))
    assert "NICHT VERIFIZIERT" in text and "clip_slot.create_audio_clip (supported)" in text
    assert [r.id for r in live.unverified_caps(bad)] == ["clip_slot.create_audio_clip"]


def test_inspect_lists_tracks_with_live_numbers_and_sends_no_write(fake, tmp_path, wav):
    res = live.inspect_live(config_for(fake, tmp_path), wav)
    assert res.ok, res.error
    assert res.live_version == "12.3" and res.num_scenes == 4
    assert [t.label for t in res.tracks] == [
        "1: 1-Audio", "2: 2-MIDI  (keine Audiospur)", "3: 3-Audio"]
    assert [t.is_audio for t in res.tracks] == [True, False, True]
    assert writes(fake) == []


def test_inspect_refuses_bad_files_before_connecting(tmp_path):
    cfg = live.LiveConfig("127.0.0.1", free_udp_port(), free_udp_port(), 5.0,
                          tmp_path / "a.jsonl")
    rel = live.inspect_live(cfg, "relative.wav")
    assert not rel.ok and "must be absolute" in rel.error
    missing = live.inspect_live(cfg, str(tmp_path / "nope.wav"))
    assert not missing.ok and "Datei" in missing.error
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    assert not live.inspect_live(cfg, str(txt)).ok


def test_category_wav_outside_a_project_folder_is_refused_with_the_reason(fake, tmp_path):
    p = write_wav(tmp_path / "kick_s1_v0.wav")
    (tmp_path / "kick_s1_v0.json").write_text(json.dumps({"category": "kick"}))
    res = live.inspect_live(config_for(fake, tmp_path), p)
    assert not res.ok and "liegt aber nicht im Ordner" in res.error
    assert writes(fake) == []


def test_missing_extension_is_reported_and_nothing_changes(fake, tmp_path, wav):
    fake.extension_installed = False
    res = live.inspect_live(config_for(fake, tmp_path), wav)
    assert not res.ok and "Erweiterung fehlt" in res.error
    assert writes(fake) == []


def test_no_answer_from_live_is_a_message_not_a_hang(tmp_path, wav):
    cfg = live.LiveConfig("127.0.0.1", free_udp_port(), free_udp_port(), 0.3,
                          tmp_path / "a.jsonl")  # short deadline: the timeout is the subject
    res = live.inspect_live(cfg, wav)
    assert not res.ok and "antwortet nicht" in res.error


def test_plan_picks_first_free_slot_and_refuses_midi_track_and_occupied_slot(fake, tmp_path, wav):
    cfg = config_for(fake, tmp_path)
    ok = live.prepare_import(cfg, wav, 0, None)
    assert ok.ok and ok.slot == 1  # slot 0 holds old.wav
    assert "Spur 1 '1-Audio', Szene 2" in ok.text and wav in ok.text
    midi = live.prepare_import(cfg, wav, 1, None)
    assert not midi.ok and "keine Audiospur" in midi.error
    busy = live.prepare_import(cfg, wav, 0, 0)
    assert not busy.ok and "schon belegt" in busy.error
    far = live.prepare_import(cfg, wav, 0, 9)
    assert not far.ok and "gibt es nicht" in far.error
    new = live.prepare_import(cfg, wav, None, None)
    assert new.ok and "Neue Audiospur am Ende anlegen (wird Spur 4)" in new.text
    assert writes(fake) == []


def test_import_into_existing_track_writes_reads_back_and_logs(fake, tmp_path, wav):
    cfg = config_for(fake, tmp_path)
    plan = live.prepare_import(cfg, wav, 2, 3)
    res = live.execute_import(cfg, plan, test_set_confirmed=True)
    assert res.ok, res.message
    assert fake.tracks[2]["slots"][3] == wav
    assert writes(fake) == [(CREATE_CLIP, (2, 3, wav))]
    assert res.file_path_read == wav and "angehört wurde nichts" in res.message
    assert any("create_audio_clip" in line for line in res.log_lines)
    assert any(s.startswith("create_audio_clip") for s in res.steps)
    entries = [json.loads(x) for x in cfg.log_path.read_text(encoding="utf-8").splitlines()]
    assert [e["status"] for e in entries if e["action"] == "create_audio_clip"][:1] == ["planned"]


def test_import_into_new_track_creates_the_track_then_the_clip(fake, tmp_path, wav):
    cfg = config_for(fake, tmp_path)
    plan = live.prepare_import(cfg, wav, None, None)
    res = live.execute_import(cfg, plan, test_set_confirmed=True)
    assert res.ok, res.message
    assert [a for a, _ in writes(fake)] == [CREATE_TRACK, CREATE_CLIP]
    assert len(fake.tracks) == 4 and fake.tracks[3]["slots"][0] == wav


def test_without_test_set_confirmation_nothing_is_sent(fake, tmp_path, wav):
    cfg = config_for(fake, tmp_path)
    plan = live.prepare_import(cfg, wav, 2, 0)
    res = live.execute_import(cfg, plan, test_set_confirmed=False)
    assert not res.ok and "Test-Set" in res.message
    assert writes(fake) == [] and not cfg.log_path.exists()


def test_execute_needs_a_valid_plan(fake, tmp_path, wav):
    cfg = config_for(fake, tmp_path)
    bad = live.prepare_import(cfg, wav, 1, None)
    assert not live.execute_import(cfg, bad, True).ok
    assert writes(fake) == []


def test_set_changed_after_the_plan_aborts_before_any_write(fake, tmp_path, wav):
    cfg = config_for(fake, tmp_path)
    plan = live.prepare_import(cfg, wav, 2, 1)
    fake.tracks[2]["slots"][2] = "C:\\someone_else.wav"  # the user did something in Live
    res = live.execute_import(cfg, plan, True)
    assert not res.ok and "the set changed" in res.message
    assert "nichts in Live geändert" in res.message
    assert writes(fake) == []
    assert not res.writes_sent


def test_unverified_capability_stays_behind_the_confirmation(fake, tmp_path, wav):
    reg = registry_with_status(tmp_path, {"clip_slot.create_audio_clip": "supported"})
    cfg = config_for(fake, tmp_path)
    refused = live.inspect_live(cfg, wav, reg)
    assert not refused.ok and "NICHT VERIFIZIERT" in refused.error
    assert [r.id for r in refused.unverified] == ["clip_slot.create_audio_clip"]
    assert fake.payload() == []  # not even a read was sent
    plan_refused = live.prepare_import(cfg, wav, 2, 0, reg)
    assert not plan_refused.ok and fake.payload() == []
    # accepted: the plan is made, and a write needs the acceptance again
    plan = live.prepare_import(cfg, wav, 2, 0, reg, accept_unverified=True)
    assert plan.ok and [r.id for r in plan.unverified] == ["clip_slot.create_audio_clip"]
    no = live.execute_import(cfg, plan, True, reg, accept_unverified=False)
    assert not no.ok and "NICHT VERIFIZIERT" in no.message and writes(fake) == []
    yes = live.execute_import(cfg, plan, True, reg, accept_unverified=True)
    assert yes.ok, yes.message
    assert writes(fake) == [(CREATE_CLIP, (2, 0, wav))]


def test_unsupported_capability_cannot_be_accepted(fake, tmp_path, wav):
    reg = registry_with_status(tmp_path, {"clip_slot.create_audio_clip": "unsupported"})
    res = live.inspect_live(config_for(fake, tmp_path), wav, reg, accept_unverified=True)
    assert not res.ok and "unsupported" in res.error
    assert fake.payload() == []
