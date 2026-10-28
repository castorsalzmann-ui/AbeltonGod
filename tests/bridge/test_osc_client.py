"""OSC client against the fake AbletonOSC server (issue #4, acceptance criterion 1).

CI only: nothing here talks to Ableton Live. Live behaviour is verified in #5 on the user's
Windows machine.
"""

from __future__ import annotations

import random
import socket
import struct
import threading
import time

import pytest
from conftest import TEST_TIMEOUT_S
from fake_abletonosc import build

from bridge.osc_client import (
    AbletonBridge,
    AbletonOSCError,
    BridgeProtocolError,
    BridgeTimeoutError,
    BridgeUnavailableError,
    LiveNotReachableError,
    OscTransport,
    ReceivePortInUseError,
)

MARGIN_S = 0.5  # scheduling slack on shared CI runners


def osc_string(s: str) -> bytes:
    """Hand-written OSC string encoding: bytes, NUL, padded to a multiple of 4."""
    raw = s.encode() + b"\0"
    return raw + b"\0" * (-len(raw) % 4)


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# -- request/response ------------------------------------------------------------------------


def test_reads_return_fake_song_state(bridge):
    assert bridge.get_version() == (12, 3)
    assert bridge.get_tempo() == 136.0
    assert bridge.get_signature() == (4, 4)
    assert bridge.get_track_names() == ["1-Kick", "2-Bass"]


def test_mute_write_is_visible_and_undo_reverts_it(bridge, fake, transport):
    bridge.set_track_mute(1, True)
    assert transport.query("/live/track/get/mute", (1,), expect_prefix=(1,)) == (1,)
    assert fake.received[-3:-1] == [("/live/track/set/mute", (1, 1)), ("/live/test", ())]
    bridge.undo()
    assert transport.query("/live/track/get/mute", (1,), expect_prefix=(1,)) == (0,)


def test_create_audio_track_then_undo(bridge):
    bridge.create_audio_track(-1)
    assert bridge.get_track_names() == ["1-Kick", "2-Bass", "3-Audio"]
    bridge.undo()
    assert bridge.get_track_names() == ["1-Kick", "2-Bass"]


def test_ping(bridge, fake):
    bridge.ping()
    assert fake.addresses() == ["/live/test"]


def test_wire_format_of_a_write_matches_hand_encoding():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(2)
    with OscTransport(send_port=server.getsockname()[1], receive_port=0) as t:
        t.send("/live/track/set/mute", (0, 1))
        data, src = server.recvfrom(1024)
        assert src[1] == t.receive_port  # sent from the reply socket itself
    server.close()
    expected = (osc_string("/live/track/set/mute") + osc_string(",ii")
                + struct.pack(">i", 0) + struct.pack(">i", 1))
    assert data == expected


def test_hand_encoded_reply_is_decoded(bridge, fake):
    fake.raw_reply["/live/song/get/tempo"] = (
        osc_string("/live/song/get/tempo") + osc_string(",f") + struct.pack(">f", 128.5)
    )
    assert bridge.get_tempo() == 128.5


def test_random_mute_sequences_round_trip(bridge, fake, transport):
    rng = random.Random(4)
    fake.tracks = [{"name": f"T{i}", "mute": 0} for i in range(16)]
    expected = [0] * 16
    for _ in range(60):
        idx, mute = rng.randrange(16), rng.random() < 0.5
        bridge.set_track_mute(idx, mute)
        expected[idx] = int(mute)
        assert transport.query("/live/track/get/mute", (idx,), expect_prefix=(idx,)) == (int(mute),)
    assert [t["mute"] for t in fake.tracks] == expected


@pytest.mark.parametrize("seed", range(5))
def test_random_tempo_and_signature_values(bridge, fake, seed):
    rng = random.Random(seed)
    for _ in range(20):
        tempo = rng.uniform(20.0, 999.0)
        fake.tempo = tempo
        fake.signature = (rng.randint(1, 99), rng.choice([1, 2, 4, 8, 16]))
        # Reference: OSC 'f' is IEEE float32, rounded independently with struct.
        assert bridge.get_tempo() == struct.unpack(">f", struct.pack(">f", tempo))[0]
        assert bridge.get_signature() == fake.signature


def test_unrelated_messages_before_the_reply_are_ignored(bridge, fake):
    fake.extra_before = [("/live/startup", ()), ("/live/song/get/is_playing", (1,)),
                         ("/live/track/get/mute", (0, 1))]
    assert bridge.get_tempo() == 136.0


def test_stale_datagram_in_socket_is_drained_before_request(bridge, fake, transport):
    fake.sock.sendto(build("/live/song/get/tempo", (99.0,)), ("127.0.0.1", transport.receive_port))
    time.sleep(0.1)
    assert bridge.get_tempo() == 136.0


def test_malformed_datagram_is_ignored(bridge, fake):
    fake.extra_before = []
    fake.raw_reply["/live/song/get/tempo"] = b"\x00garbage"
    with pytest.raises(BridgeTimeoutError):
        bridge.get_tempo()


def test_concurrent_callers_each_get_their_own_answer(bridge):
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            for _ in range(15):
                if i % 2:
                    assert bridge.get_tempo() == 136.0
                else:
                    assert bridge.get_track_names() == ["1-Kick", "2-Bass"]
        except BaseException as exc:  # noqa: BLE001 - collected and re-raised below
            errors.append(exc)

    # Daemon threads + bounded join: without the transport lock one thread can leave the shared
    # socket blocking forever, which must show up as a failure, not a hung test run.
    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(8)]
    for t in threads:
        t.start()
    end = time.monotonic() + 10
    for t in threads:
        t.join(timeout=max(0.0, end - time.monotonic()))
    assert not any(t.is_alive() for t in threads), "callers hung on the shared socket"
    assert errors == []


# -- errors from AbletonOSC ------------------------------------------------------------------


def test_unknown_address_raises_ableton_error_without_waiting_for_timeout(transport):
    start = time.monotonic()
    with pytest.raises(AbletonOSCError, match="Unknown OSC address: /live/nope"):
        transport.query("/live/nope")
    assert time.monotonic() - start < TEST_TIMEOUT_S


def test_handler_exception_on_write_raises_ableton_error(bridge, fake):
    with pytest.raises(AbletonOSCError, match="index out of range"):
        bridge.set_track_mute(9, True)
    assert fake.received[-2] == ("/live/track/set/mute", (9, 1))
    assert bridge.get_tempo() == 136.0  # the client recovers


@pytest.mark.parametrize("reply, method", [
    ((b",s", osc_string("fast")), "get_tempo"),
    ((b",f", struct.pack(">f", 5.0)), "get_tempo"),
    ((b",f", struct.pack(">f", 1000.0)), "get_tempo"),
    ((b",", b""), "get_tempo"),
])
def test_malformed_tempo_reply_is_a_protocol_error(bridge, fake, reply, method):
    tag, payload = reply
    fake.raw_reply["/live/song/get/tempo"] = (
        osc_string("/live/song/get/tempo") + osc_string(tag.decode()) + payload
    )
    with pytest.raises(BridgeProtocolError):
        getattr(bridge, method)()


@pytest.mark.parametrize("version", [(12,), (12, 3, 1), (12.0, 3), ("12", "3")])
def test_malformed_version_reply_is_a_protocol_error(bridge, fake, version):
    fake.version = version
    with pytest.raises(BridgeProtocolError):
        bridge.get_version()


def test_non_string_track_names_are_a_protocol_error(bridge, fake):
    fake.tracks = [{"name": 3, "mute": 0}]
    with pytest.raises(BridgeProtocolError):
        bridge.get_track_names()


@pytest.mark.parametrize("sig", [(0, 4), (4, 0)])
def test_invalid_signature_is_a_protocol_error(bridge, fake, sig):
    fake.signature = sig
    with pytest.raises(BridgeProtocolError):
        bridge.get_signature()


# -- timeouts and Live not running -----------------------------------------------------------


def test_dropped_reply_times_out_after_the_timeout(bridge, fake):
    fake.drop.add("/live/song/get/tempo")
    start = time.monotonic()
    with pytest.raises(BridgeTimeoutError, match="Control Surface"):
        bridge.get_tempo()
    elapsed = time.monotonic() - start
    assert TEST_TIMEOUT_S <= elapsed < TEST_TIMEOUT_S + MARGIN_S


def test_dropped_confirmation_of_a_write_times_out(bridge, fake):
    fake.drop.add("/live/test")
    with pytest.raises(BridgeTimeoutError):
        bridge.set_track_mute(0, True)


def test_late_reply_after_timeout_does_not_answer_the_next_request(bridge, fake):
    # Request 1 is answered 0.1 s after its timeout. Request 2 starts right away and its own
    # reply takes 0.2 s, so the stale 136 BPM lands while request 2 is (or would be) waiting.
    fake.delays["/live/song/get/tempo"] = [TEST_TIMEOUT_S + 0.1, 0.2]
    with pytest.raises(BridgeTimeoutError):
        bridge.get_tempo()
    fake.tempo = 140.0
    assert bridge.get_tempo() == 140.0


def test_reply_for_another_track_is_not_taken(fake, transport):
    fake.tracks[1]["mute"] = 1
    fake.extra_before = [("/live/track/get/mute", (0, 0))]
    assert transport.query("/live/track/get/mute", (1,), expect_prefix=(1,)) == (1,)


def test_injected_clock_controls_the_deadline(fake):
    now = [0.0]

    def clock() -> float:
        now[0] += 0.05  # every reading advances 50 ms
        return now[0]

    fake.drop.add("/live/test")
    with OscTransport(send_port=fake.port, receive_port=0, timeout_s=0.2, clock=clock) as t:
        fake.response_port = t.receive_port
        with pytest.raises(BridgeTimeoutError):
            t.ping(timeout_s=0.2)
        assert now[0] < 1.0  # a handful of readings, not a real-time wait


def test_live_not_running_raises_unavailable_within_timeout():
    """Real socket, nothing listening. Windows reports a reset, Linux times out."""
    with OscTransport(send_port=free_udp_port(), receive_port=0,
                      timeout_s=TEST_TIMEOUT_S) as t:
        start = time.monotonic()
        with pytest.raises(BridgeUnavailableError, match="Ableton Live is running"):
            t.ping()
        assert time.monotonic() - start < TEST_TIMEOUT_S + MARGIN_S


def test_connection_reset_maps_to_live_not_reachable(bridge, fake, transport, monkeypatch):
    real_recvfrom = transport._sock.recvfrom
    calls = {"n": 0}

    class FakeSock:
        def __getattr__(self, name):
            return getattr(real_sock, name)

        def recvfrom(self, size):
            if (transport._sock.gettimeout() or 0) > 0 and calls["n"] == 0:
                calls["n"] += 1
                raise ConnectionResetError(10054, "WSAECONNRESET")
            return real_recvfrom(size)

    real_sock = transport._sock
    monkeypatch.setattr(transport, "_sock", FakeSock())
    with pytest.raises(LiveNotReachableError, match="Control Surface"):
        bridge.get_tempo()
    assert bridge.get_tempo() == 136.0  # after the reset the next request works


def test_reply_port_in_use_is_reported(transport):
    with pytest.raises(ReceivePortInUseError, match=str(transport.receive_port)):
        OscTransport(receive_port=transport.receive_port)


# -- input validation (nothing is sent) ------------------------------------------------------


@pytest.mark.parametrize("call", [
    lambda b: b.set_track_mute(-1, True),
    lambda b: b.set_track_mute(True, True),
    lambda b: b.set_track_mute(1.0, True),
    lambda b: b.set_track_mute(0, 1),
    lambda b: b.create_audio_track(-2),
    lambda b: b.create_audio_track(False),
])
def test_bad_bridge_arguments_are_rejected_before_sending(bridge, fake, call):
    with pytest.raises(ValueError):
        call(bridge)
    bridge.ping()
    fake.wait_received(1)
    assert fake.addresses() == ["/live/test"]


@pytest.mark.parametrize("args", [(True,), (float("nan"),), (float("inf"),), (None,), (b"x",)])
def test_bad_osc_arguments_are_rejected(transport, args):
    with pytest.raises(ValueError):
        transport.send("/live/song/set/tempo", args)


@pytest.mark.parametrize("kwargs", [
    {"host": "192.168.1.10"}, {"host": "localhost"}, {"send_port": 0}, {"send_port": 70000},
    {"receive_port": -1}, {"receive_port": True}, {"timeout_s": 0}, {"timeout_s": float("nan")},
    {"resync_grace_s": -1},
])
def test_bad_transport_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        OscTransport(**{"receive_port": 0, **kwargs})


def test_bad_address_is_rejected(transport):
    with pytest.raises(ValueError):
        transport.send("live/test")


def test_from_env_reads_ports_and_rejects_garbage(monkeypatch, fake):
    monkeypatch.setenv("ABLETON_OSC_HOST", "")
    monkeypatch.setenv("ABLETON_OSC_SEND_PORT", str(fake.port))
    monkeypatch.setenv("ABLETON_OSC_RECEIVE_PORT", "0")
    with AbletonBridge.from_env() as b:
        assert b.transport.host == "127.0.0.1"
        assert b.transport.send_port == fake.port
        fake.response_port = b.transport.receive_port
        b.ping()
    monkeypatch.setenv("ABLETON_OSC_SEND_PORT", "eleven-thousand")
    with pytest.raises(ValueError, match="ABLETON_OSC_SEND_PORT"):
        AbletonBridge.from_env()
