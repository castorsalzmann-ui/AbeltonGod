"""AbletonBridge calls of the Arrangement check (#140) against the fake server: the
unregistered-capability gate, argument checks and reply parsing. CI only."""

from __future__ import annotations

import pytest
from conftest import registry_with
from fake_abletonosc import build

from bridge.capabilities import (
    CapabilityGate,
    CapabilityNotTestedError,
    CapabilityRegistry,
    CapabilityRegistryError,
)
from bridge.osc_client import (
    ADDRESSES,
    UNREGISTERED,
    AbletonBridge,
    BridgeProtocolError,
    ExtensionMissingError,
)

NOTE = (36, 0.0, 0.25, 100, False)

CALLS = {
    "song.create_midi_track": lambda b: b.create_midi_track(-1),
    "track.has_midi_input.get": lambda b: b.get_track_has_midi_input(0),
    "track.arrangement_clips.get": lambda b: b.get_arrangement_clips(0),
    "song.is_playing.get": lambda b: b.get_is_playing(),
    "song.current_song_time.get": lambda b: b.get_song_time(),
    "song.current_song_time.set": lambda b: b.set_song_time(4.0),
    "song.cue_points.get": lambda b: b.get_cue_points(),
    "song.cue_point.add_or_delete": lambda b: b.toggle_cue_at_song_time(),
    "song.cue_point.set_name": lambda b: b.set_cue_name(0, "x"),
    "track.create_midi_clip": lambda b: b.create_arrangement_midi_clip(0, 0.0, 4.0),
    "arrangement_clip.notes.add": lambda b: b.add_arrangement_clip_notes(0, 0, [NOTE]),
    "arrangement_clip.notes.get": lambda b: b.get_arrangement_clip_notes(0, 0),
}


def bridge_with(transport, tmp_path, unregistered=(), tested=None):
    reg = registry_with(tmp_path, set(ADDRESSES) if tested is None else tested)
    return AbletonBridge(transport, CapabilityGate(reg, (), unregistered))


def test_every_unregistered_capability_has_a_call_here():
    assert set(CALLS) == set(UNREGISTERED)


def test_unregistered_ids_are_really_not_in_the_registry():
    reg = CapabilityRegistry.from_file()
    assert not set(UNREGISTERED) & set(reg.ids())


@pytest.mark.parametrize("cap_id", sorted(CALLS))
def test_refused_without_opt_in_before_any_network_io(fake, transport, tmp_path, cap_id):
    """Even with every registered capability tested (D-004)."""
    b = bridge_with(transport, tmp_path)
    with pytest.raises(CapabilityNotTestedError) as err:
        CALLS[cap_id](b)
    assert err.value.capability_id == cap_id and err.value.status == "unregistered"
    b.ping()
    fake.wait_received(2)
    assert fake.payload() == []


def test_probe_refused_without_opt_in(fake, transport, tmp_path):
    b = bridge_with(transport, tmp_path)
    with pytest.raises(CapabilityNotTestedError):
        b.probe_arrangement_extension()
    b.ping()
    fake.wait_received(2)
    assert fake.payload() == []


@pytest.mark.parametrize("cap_id", sorted(CALLS))
def test_opt_in_for_one_id_unlocks_only_that_one(fake, transport, tmp_path, cap_id):
    b = bridge_with(transport, tmp_path, unregistered={cap_id})
    fake.tracks[0]["midi"] = True
    fake.tracks[0]["arrangement"] = [{"start": 0.0, "length": 4.0, "notes": []}]
    fake.cue_points = [["a", 0.0]]
    CALLS[cap_id](b)
    assert set(b.gate.overrides_used) == {cap_id}
    for other in sorted(set(CALLS) - {cap_id}):
        with pytest.raises(CapabilityNotTestedError):
            CALLS[other](b)


def test_connect_refuses_typos_and_registered_ids(fake):
    with pytest.raises(ValueError, match="not an unregistered"):
        AbletonBridge.connect(send_port=fake.port, receive_port=0,
                              allow_unregistered=["song.create_midi_trak"])
    with pytest.raises(ValueError, match="not an unregistered"):
        AbletonBridge.connect(send_port=fake.port, receive_port=0,
                              allow_unregistered=["song.undo"])
    reg = CapabilityRegistry.from_file()
    with pytest.raises(CapabilityRegistryError, match="in the registry now"):
        CapabilityGate(reg, (), ["song.undo"])


def test_registered_id_goes_through_the_normal_gate(tmp_path):
    gate = CapabilityGate(registry_with(tmp_path, set()))
    with pytest.raises(CapabilityNotTestedError) as err:
        gate.check_unregistered("song.undo")
    assert err.value.status == "supported"


ALL = tuple(UNREGISTERED)


@pytest.fixture
def b(transport, tmp_path):
    return bridge_with(transport, tmp_path, unregistered=ALL)


def test_reads_parse_the_fake_replies(fake, b):
    fake.tracks[1]["midi"] = True
    fake.tracks[1]["arrangement"] = [{"start": 16.0, "length": 8.0,
                                      "notes": [(36, 0.0, 0.25, 100.0, False)]}]
    fake.cue_points = [["Intro", 16.0], ["B", 0.0]]
    fake.song_time = 3.5
    assert b.get_track_has_midi_input(1) is True
    assert b.get_arrangement_clips(1) == ((16.0, 8.0),)
    assert b.get_arrangement_clips(0) == ()
    assert b.get_arrangement_clip_notes(1, 0) == ((36, 0.0, 0.25, 100.0, False),)
    assert b.get_cue_points() == (("Intro", 16.0), ("B", 0.0))
    assert b.get_song_time() == 3.5 and b.get_is_playing() is False


def test_writes_send_exactly_these_messages(fake, b):
    b.create_midi_track(-1)
    b.create_arrangement_midi_clip(2, 16, 8)
    b.add_arrangement_clip_notes(2, 0, [NOTE, (38, 1.5, 0.5, 90, True)])
    b.set_song_time(16)
    b.toggle_cue_at_song_time()
    b.set_cue_name(0, "Intro")
    assert fake.payload() == [
        ("/live/song/create_midi_track", (-1,)),
        ("/live/track/create_midi_clip", (2, 16.0, 8.0)),
        ("/live/track/arrangement_clip/add/notes", (2, 0, 36, 0.0, 0.25, 100, 0,
                                                    38, 1.5, 0.5, 90, 1)),
        ("/live/song/set/current_song_time", (16.0,)),
        ("/live/song/cue_point/add_or_delete", ()),
        ("/live/song/cue_point/set/name", (0, "Intro")),
    ]
    assert [type(v) for v in fake.payload()[1][1]] == [int, float, float]


@pytest.mark.parametrize("call", [
    lambda b: b.create_arrangement_midi_clip(0, -1.0, 4.0),
    lambda b: b.create_arrangement_midi_clip(0, 0.0, 0.0),
    lambda b: b.create_arrangement_midi_clip(0, 1576799.0, 4.0),
    lambda b: b.create_arrangement_midi_clip(0, float("nan"), 4.0),
    lambda b: b.create_arrangement_midi_clip(0, True, 4.0),
    lambda b: b.create_arrangement_midi_clip(-1, 0.0, 4.0),
    lambda b: b.add_arrangement_clip_notes(0, 0, []),
    lambda b: b.add_arrangement_clip_notes(0, 0, [NOTE] * 65),
    lambda b: b.add_arrangement_clip_notes(0, 0, [(127, 0.0, 0.25, 100, False)]),
    lambda b: b.add_arrangement_clip_notes(0, 0, [(-1, 0.0, 0.25, 100, False)]),
    lambda b: b.add_arrangement_clip_notes(0, 0, [(36, 0.0, 0.25, 0, False)]),
    lambda b: b.add_arrangement_clip_notes(0, 0, [(36, 0.0, 0.25, 128, False)]),
    lambda b: b.add_arrangement_clip_notes(0, 0, [(36, 0.0, 0.0, 100, False)]),
    lambda b: b.add_arrangement_clip_notes(0, 0, [(36, -0.5, 0.25, 100, False)]),
    lambda b: b.add_arrangement_clip_notes(0, 0, [(36, 0.0, 0.25, 100, 0)]),
    lambda b: b.add_arrangement_clip_notes(0, 0, [(36, 0.0, 0.25, 100)]),
    lambda b: b.add_arrangement_clip_notes(0, 0, [(36.0, 0.0, 0.25, 100, False)]),
    lambda b: b.set_song_time(-1),
    lambda b: b.set_song_time(float("inf")),
    lambda b: b.set_cue_name(0, ""),
    lambda b: b.set_cue_name(-1, "x"),
    lambda b: b.set_cue_name(0, "a\x00b"),
    lambda b: b.create_midi_track(-2),
])
def test_bad_arguments_are_refused_before_sending(fake, b, call):
    with pytest.raises(ValueError):
        call(b)
    b.ping()
    fake.wait_received(2)
    assert fake.payload() == []


@pytest.mark.parametrize("address,raw,call", [
    ("/live/song/get/cue_points", ("a",), lambda b: b.get_cue_points()),
    ("/live/song/get/cue_points", (1, 2.0), lambda b: b.get_cue_points()),
    ("/live/song/get/current_song_time", ("x",), lambda b: b.get_song_time()),
    ("/live/song/get/is_playing", (2,), lambda b: b.get_is_playing()),
    ("/live/track/get/arrangement_clips/length", (0, 1.0, 2.0),
     lambda b: b.get_arrangement_clips(0)),
    ("/live/track/get/arrangement_clips/length", (0, "x"), lambda b: b.get_arrangement_clips(0)),
    ("/live/track/arrangement_clip/get/notes", (0, 0, 36, 0.0, 0.25, 100.0),
     lambda b: b.get_arrangement_clip_notes(0, 0)),
    ("/live/track/arrangement_clip/get/notes", (0, 0, 36.0, 0.0, 0.25, 100.0, False),
     lambda b: b.get_arrangement_clip_notes(0, 0)),
    ("/live/track/arrangement_clip/get/notes", (0, 0, 36, 0.0, 0.25, 100.0, 3),
     lambda b: b.get_arrangement_clip_notes(0, 0)),
])
def test_malformed_replies_are_protocol_errors(fake, b, address, raw, call):
    fake.tracks[0]["midi"] = True
    fake.tracks[0]["arrangement"] = [{"start": 0.0, "length": 4.0, "notes": []}]
    fake.raw_reply[address] = build(address, raw)
    with pytest.raises(BridgeProtocolError):
        call(b)


def test_probe_reports_missing_addresses(fake, b):
    assert b.probe_arrangement_extension() == []
    fake.arrangement_extension_installed = False
    assert b.probe_arrangement_extension() == [
        "/live/track/create_midi_clip", "/live/track/arrangement_clip/add/notes",
        "/live/track/arrangement_clip/get/notes"]
    with pytest.raises(ExtensionMissingError):
        b.create_arrangement_midi_clip(0, 0.0, 4.0)
    with pytest.raises(ExtensionMissingError):
        b.get_arrangement_clip_notes(0, 0)


def test_probe_that_succeeds_is_a_protocol_error(fake, b):
    real = fake._handlers
    fake._handlers = lambda: {**real(), "/live/track/create_midi_clip": lambda p: None}
    with pytest.raises(BridgeProtocolError, match="does not look like"):
        b.probe_arrangement_extension()
