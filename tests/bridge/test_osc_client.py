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
from conftest import TEST_TIMEOUT_S, registry_with
from fake_abletonosc import MARKER, build
from pythonosc.osc_bundle_builder import IMMEDIATELY, OscBundleBuilder
from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

from bridge.capabilities import CapabilityNotTestedError
from bridge.osc_client import (
    ADDRESSES,
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
SLOW_S = 2.0  # timeout for requests that wait for a held fake to release


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
    assert fake.payload()[-1] == ("/live/track/set/mute", (1, 1))
    assert transport.query("/live/track/get/mute", (1,), expect_prefix=(1,)) == (True,)
    bridge.undo()
    assert transport.query("/live/track/get/mute", (1,), expect_prefix=(1,)) == (False,)


def test_every_request_is_bracketed_by_two_fresh_markers(bridge, fake):
    bridge.get_tempo()
    bridge.set_track_mute(0, True)
    fake.wait_received(6)
    received = fake.received
    nonces = [p[0] for a, p in received if a == MARKER and len(p) == 1]
    assert [a for a, _ in received] == [MARKER, MARKER, MARKER, MARKER,
                                        "/live/track/set/mute", MARKER]
    assert len(nonces) == 4 and len(set(nonces)) == 4
    assert all(isinstance(n, str) for n in nonces)


def test_ping_sends_markers_only(bridge, fake):
    bridge.ping()
    fake.wait_received(2)
    assert fake.payload() == []


def test_wire_format_of_a_write_matches_hand_encoding():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(2)
    with OscTransport(send_port=server.getsockname()[1], receive_port=0, timeout_s=0.3) as t:
        with pytest.raises(BridgeTimeoutError):  # nobody answers the markers
            t.send_confirmed("/live/track/set/mute", (0, 1))
        datagrams = [server.recvfrom(1024) for _ in range(3)]
        assert all(src[1] == t.receive_port for _, src in datagrams)  # sent from reply socket
    server.close()
    expected = (osc_string("/live/track/set/mute") + osc_string(",ii")
                + struct.pack(">i", 0) + struct.pack(">i", 1))
    assert datagrams[1][0] == expected
    for data, _ in (datagrams[0], datagrams[2]):
        assert data.startswith(osc_string(MARKER) + osc_string(",s"))


def test_hand_encoded_reply_is_decoded(bridge, fake):
    fake.raw_reply["/live/song/get/tempo"] = (
        osc_string("/live/song/get/tempo") + osc_string(",f") + struct.pack(">f", 128.5)
    )
    assert bridge.get_tempo() == 128.5


def test_reply_inside_a_bundle_is_decoded(bridge, fake):
    msg = OscMessageBuilder(address="/live/song/get/tempo")
    msg.add_arg(127.0)
    inner = OscBundleBuilder(IMMEDIATELY)
    inner.add_content(msg.build())
    outer = OscBundleBuilder(IMMEDIATELY)
    outer.add_content(inner.build())
    fake.raw_reply["/live/song/get/tempo"] = outer.build().dgram
    assert bridge.get_tempo() == 127.0


def test_random_mute_sequences_round_trip(bridge, fake, transport):
    rng = random.Random(4)
    fake.tracks = [{"name": f"T{i}", "mute": False} for i in range(16)]
    expected = [False] * 16
    for _ in range(60):
        idx, mute = rng.randrange(16), rng.random() < 0.5
        bridge.set_track_mute(idx, mute)
        expected[idx] = mute
        assert transport.query("/live/track/get/mute", (idx,), expect_prefix=(idx,)) == (mute,)
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


@pytest.mark.parametrize("tempo", [20.0, 999.0])
def test_tempo_range_boundaries_are_accepted(bridge, fake, tempo):
    fake.tempo = tempo
    assert bridge.get_tempo() == tempo


@pytest.mark.parametrize("names", [[], ["Kick ü ß 🥁", ""], [f"T{i:03d}" for i in range(150)]])
def test_track_name_edge_cases(bridge, fake, names):
    fake.tracks = [{"name": n, "mute": False} for n in names]
    assert bridge.get_track_names() == names


def test_reply_for_another_track_is_not_taken(fake, transport):
    fake.tracks[1]["mute"] = True
    fake.extra_before = [("/live/track/get/mute", (0, False))]
    assert transport.query("/live/track/get/mute", (1,), expect_prefix=(1,)) == (True,)


def test_unrelated_messages_before_the_reply_are_ignored(bridge, fake):
    fake.extra_before = [("/live/startup", ()), ("/live/song/get/is_playing", (1,))]
    assert bridge.get_tempo() == 136.0


def test_stale_datagram_in_socket_is_not_taken(bridge, fake, transport):
    fake.sock.sendto(build("/live/song/get/tempo", (99.0,)), ("127.0.0.1", transport.receive_port))
    time.sleep(0.1)
    assert bridge.get_tempo() == 136.0


def test_malformed_reply_is_ignored_and_reported_as_missing(bridge, fake):
    fake.raw_reply["/live/song/get/tempo"] = b"\x00garbage"
    start = time.monotonic()
    with pytest.raises(BridgeProtocolError, match="no matching reply"):
        bridge.get_tempo()
    assert time.monotonic() - start < TEST_TIMEOUT_S  # decided by the end marker, not a timeout


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


def test_unknown_address_raises_without_waiting_for_timeout(transport):
    start = time.monotonic()
    with pytest.raises(AbletonOSCError, match="Unknown OSC address: /live/nope"):
        transport.query("/live/nope", timeout_s=SLOW_S)
    assert time.monotonic() - start < SLOW_S / 2


def test_handler_exception_on_write_raises_ableton_error(bridge, fake):
    with pytest.raises(AbletonOSCError, match="index out of range"):
        bridge.set_track_mute(9, True)
    fake.wait_received(2)  # the error can reach the client before the fake logs the next one
    assert fake.payload()[-1] == ("/live/track/set/mute", (9, 1))
    assert bridge.get_tempo() == 136.0  # the client recovers


@pytest.mark.parametrize("tag, payload", [
    (",s", osc_string("fast")),
    (",f", struct.pack(">f", 5.0)),
    (",f", struct.pack(">f", 19.99)),
    (",f", struct.pack(">f", 999.5)),
    (",T", b""),
    (",", b""),
])
def test_malformed_tempo_reply_is_a_protocol_error(bridge, fake, tag, payload):
    fake.raw_reply["/live/song/get/tempo"] = (
        osc_string("/live/song/get/tempo") + osc_string(tag) + payload
    )
    with pytest.raises(BridgeProtocolError):
        bridge.get_tempo()


@pytest.mark.parametrize("version", [(12,), (12, 3, 1), (12.0, 3), ("12", "3"), (True, 3)])
def test_malformed_version_reply_is_a_protocol_error(bridge, fake, version):
    fake.version = version
    with pytest.raises(BridgeProtocolError):
        bridge.get_version()


def test_non_string_track_names_are_a_protocol_error(bridge, fake):
    fake.tracks = [{"name": 3, "mute": False}]
    with pytest.raises(BridgeProtocolError):
        bridge.get_track_names()


@pytest.mark.parametrize("sig", [(0, 4), (4, 0)])
def test_invalid_signature_is_a_protocol_error(bridge, fake, sig):
    fake.signature = sig
    with pytest.raises(BridgeProtocolError):
        bridge.get_signature()


# -- Live busy: late replies must never answer a later request (review #4, problem 1) --------


def test_write_that_fails_after_a_timed_out_write_is_not_confirmed(bridge, fake, transport):
    """Live blocked: write A times out; retry B fails in Live. B must not count as done."""
    fake.hold()
    with pytest.raises(BridgeTimeoutError):
        bridge.set_track_mute(0, True)
    fake.release_after(0.2)
    transport.timeout_s = SLOW_S
    with pytest.raises(AbletonOSCError, match="index out of range"):
        bridge.set_track_mute(9, True)


def test_error_of_a_timed_out_request_is_not_raised_on_the_next(bridge, fake, transport):
    fake.hold()
    with pytest.raises(BridgeTimeoutError):
        bridge.set_track_mute(9, True)
    fake.release_after(0.2)
    transport.timeout_s = SLOW_S
    assert bridge.get_tempo() == 136.0


def test_late_read_reply_does_not_answer_the_next_read(bridge, fake, transport):
    fake.hold()
    with pytest.raises(BridgeTimeoutError):
        bridge.get_tempo()  # processed at 136 BPM, reply held
    fake.tempo = 140.0
    fake.release_after(0.2)
    transport.timeout_s = SLOW_S
    assert bridge.get_tempo() == 140.0


def test_write_is_confirmed_only_after_its_own_end_marker(bridge, fake, transport):
    """While held, nothing confirms; after release the same request completes."""
    fake.hold()
    transport.timeout_s = SLOW_S
    fake.release_after(0.3)
    bridge.set_track_mute(1, True)
    # Ordering, not wall-clock time: the call can only return after the release.
    assert fake.released.is_set()
    assert fake.tracks[1]["mute"] is True


# -- timeouts and Live not running -----------------------------------------------------------


def test_dropped_reply_is_reported_without_timeout(bridge, fake):
    fake.drop.add("/live/song/get/track_names")  # markers still answered
    with pytest.raises(BridgeProtocolError, match="no matching reply"):
        bridge.get_track_names()


def test_missing_markers_time_out_after_the_timeout(bridge, fake):
    fake.drop.add(MARKER)
    start = time.monotonic()
    with pytest.raises(BridgeTimeoutError, match="Control Surface"):
        bridge.get_tempo()
    elapsed = time.monotonic() - start
    assert TEST_TIMEOUT_S <= elapsed < TEST_TIMEOUT_S + MARGIN_S


def test_per_call_timeout_overrides_default(fake, transport):
    fake.drop.add(MARKER)
    start = time.monotonic()
    with pytest.raises(BridgeTimeoutError):
        transport.ping(timeout_s=0.6)
    assert 0.6 <= time.monotonic() - start < 0.6 + MARGIN_S


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), True, "1"])
def test_bad_per_call_timeout_is_rejected_before_sending(fake, transport, bad):
    with pytest.raises(ValueError):
        transport.send_confirmed("/live/song/undo", timeout_s=bad)
    time.sleep(0.05)
    assert fake.received == []


def test_injected_clock_controls_the_deadline(fake):
    now = [0.0]

    def clock() -> float:
        now[0] += 1.0  # every reading advances 1 s, so a 0.2 s deadline passes at once
        return now[0]

    fake.drop.add(MARKER)
    with OscTransport(send_port=fake.port, receive_port=0, timeout_s=0.2, clock=clock) as t:
        fake.response_port = t.receive_port
        start = time.monotonic()
        with pytest.raises(BridgeTimeoutError):
            t.ping()
        assert time.monotonic() - start < 0.2  # fake clock ran out, not the wall clock


def test_live_not_running_raises_unavailable_within_timeout():
    """Real socket, nothing listening. Windows reports a reset, Linux times out."""
    with OscTransport(send_port=free_udp_port(), receive_port=0,
                      timeout_s=TEST_TIMEOUT_S) as t:
        start = time.monotonic()
        with pytest.raises(BridgeUnavailableError, match="Ableton Live is running"):
            t.ping()
        assert time.monotonic() - start < TEST_TIMEOUT_S + MARGIN_S


class _ResetOnce:
    """Socket wrapper that raises ``count`` ConnectionResetErrors in the chosen mode."""

    def __init__(self, sock, blocking: bool, count: int = 1) -> None:
        self._sock = sock
        self._blocking = blocking
        self._left = count
        self.raised = False

    def __getattr__(self, name):
        return getattr(self._sock, name)

    def recvfrom(self, size):
        timeout = self._sock.gettimeout()
        in_mode = (timeout is None or timeout > 0) if self._blocking else timeout == 0.0
        if in_mode and self._left > 0:
            self._left -= 1
            self.raised = True
            raise ConnectionResetError(10054, "WSAECONNRESET")
        return self._sock.recvfrom(size)


def test_connection_reset_while_waiting_maps_to_live_not_reachable(bridge, transport,
                                                                  monkeypatch):
    wrapper = _ResetOnce(transport._sock, blocking=True)
    monkeypatch.setattr(transport, "_sock", wrapper)
    with pytest.raises(LiveNotReachableError, match="Control Surface"):
        bridge.get_tempo()
    assert wrapper.raised
    assert bridge.get_tempo() == 136.0  # the next request works


def test_stale_reset_from_an_earlier_send_does_not_fail_a_healthy_request(bridge, transport,
                                                                         monkeypatch):
    # Two earlier failed sends can leave two pending resets on Windows.
    wrapper = _ResetOnce(transport._sock, blocking=False, count=2)
    monkeypatch.setattr(transport, "_sock", wrapper)
    assert bridge.get_tempo() == 136.0
    assert wrapper._left == 0  # the drain met both and went on


def test_reply_port_in_use_is_reported(transport):
    with pytest.raises(ReceivePortInUseError, match=str(transport.receive_port)):
        OscTransport(receive_port=transport.receive_port)


# -- input validation (nothing is sent) ------------------------------------------------------


@pytest.mark.parametrize("call", [
    lambda b: b.set_track_mute(-1, True),
    lambda b: b.set_track_mute(True, True),
    lambda b: b.set_track_mute(1.0, True),
    lambda b: b.set_track_mute(0, 1),
])
def test_bad_bridge_arguments_are_rejected_before_sending(bridge, fake, call):
    with pytest.raises(ValueError):
        call(bridge)
    time.sleep(0.05)
    assert fake.received == []


@pytest.mark.parametrize("args", [(True,), (float("nan"),), (float("inf"),), (None,), (b"x",)])
def test_bad_osc_arguments_are_rejected_before_sending(fake, transport, args):
    with pytest.raises(ValueError):
        transport.send_confirmed("/live/song/set/tempo", args)
    time.sleep(0.05)
    assert fake.received == []


@pytest.mark.parametrize("kwargs", [
    {"host": "192.168.1.10"}, {"host": "localhost"}, {"send_port": 0}, {"send_port": 70000},
    {"receive_port": -1}, {"receive_port": True}, {"timeout_s": 0}, {"timeout_s": float("nan")},
    {"timeout_s": True},
])
def test_bad_transport_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        OscTransport(**{"receive_port": 0, **kwargs})


def test_bad_address_is_rejected(transport):
    with pytest.raises(ValueError):
        transport.send_confirmed("live/test")


# -- construction --------------------------------------------------------------------------


def test_connect_uses_given_registry_and_override(fake, tmp_path):
    reg = registry_with(tmp_path, set())
    with AbletonBridge.connect(send_port=fake.port, receive_port=0, timeout_s=TEST_TIMEOUT_S,
                               registry=reg, allow_untested={"song.tempo.get"}) as b:
        fake.response_port = b.endpoint[2]
        assert b.get_tempo() == 136.0
        assert b.gate.overrides_used == ["song.tempo.get"]
        with pytest.raises(CapabilityNotTestedError):
            b.get_version()


def test_connect_with_tested_registry_needs_no_override(fake, tmp_path):
    reg = registry_with(tmp_path, set(ADDRESSES))
    with AbletonBridge.connect(send_port=fake.port, receive_port=0, timeout_s=TEST_TIMEOUT_S,
                               registry=reg) as b:
        fake.response_port = b.endpoint[2]
        assert b.get_version() == (12, 3)
        assert b.gate.overrides_used == []


def test_connect_default_registry_refuses_everything(fake):
    with AbletonBridge.connect(send_port=fake.port, receive_port=0) as b:
        with pytest.raises(CapabilityNotTestedError):
            b.get_tempo()


def test_from_env_reads_all_three_variables(monkeypatch, fake, tmp_path):
    receive = free_udp_port()
    monkeypatch.setenv("ABLETON_OSC_HOST", " 127.0.0.1 ")
    monkeypatch.setenv("ABLETON_OSC_SEND_PORT", str(fake.port))
    monkeypatch.setenv("ABLETON_OSC_RECEIVE_PORT", str(receive))
    reg = registry_with(tmp_path, {"song.tempo.get"})
    with AbletonBridge.from_env(registry=reg) as b:
        assert b.endpoint == ("127.0.0.1", fake.port, receive)
        fake.response_port = receive
        assert b.get_tempo() == 136.0


def test_from_env_defaults_when_unset(monkeypatch):
    for name in ("ABLETON_OSC_HOST", "ABLETON_OSC_SEND_PORT", "ABLETON_OSC_RECEIVE_PORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ABLETON_OSC_RECEIVE_PORT", "0")  # 11001 may be busy on the runner
    with AbletonBridge.from_env() as b:
        assert b.endpoint[:2] == ("127.0.0.1", 11000)


@pytest.mark.parametrize("name, value, match", [
    ("ABLETON_OSC_SEND_PORT", "eleven-thousand", "ABLETON_OSC_SEND_PORT"),
    ("ABLETON_OSC_RECEIVE_PORT", "x", "ABLETON_OSC_RECEIVE_PORT"),
    ("ABLETON_OSC_HOST", "10.0.0.1", "loopback"),
])
def test_from_env_rejects_garbage(monkeypatch, name, value, match):
    monkeypatch.setenv("ABLETON_OSC_RECEIVE_PORT", "0")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=match):
        AbletonBridge.from_env()


# -- marker edge cases against a scripted server (review round 2) ---------------------------


def _scripted(replies):
    """Run one request against a server that answers with ``replies(start, end)``."""
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(2)
    t = OscTransport(send_port=server.getsockname()[1], receive_port=0, timeout_s=0.4)

    def serve():
        nonces = []
        for _ in range(3):
            data, src = server.recvfrom(1024)
            msg = OscMessage(data)
            if msg.address == MARKER and len(msg.params) == 1:
                nonces.append(msg.params[0])
        for address, args in replies(*nonces):
            server.sendto(build(address, args), ("127.0.0.1", t.receive_port))

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return t, server, thread


def _run_scripted(replies):
    t, server, thread = _scripted(replies)
    try:
        return t.query("/live/song/get/track_names")
    finally:
        thread.join(timeout=2)
        t.close()
        server.close()


def test_end_marker_before_start_marker_is_a_protocol_error():
    with pytest.raises(BridgeProtocolError, match="before start"):
        _run_scripted(lambda start, end: [(MARKER, (120.0, end)), (MARKER, (120.0, start))])


def test_marker_echo_must_have_exactly_two_arguments():
    """A three-argument echo is not our marker, so the request cannot complete."""
    with pytest.raises(BridgeTimeoutError):
        _run_scripted(lambda start, end: [
            (MARKER, (120.0, start, "x")),
            ("/live/song/get/track_names", ("A",)),
            (MARKER, (120.0, end, "x")),
        ])


def test_well_formed_script_is_accepted():
    """Control for the two tests above: the same server with correct echoes works."""
    assert _run_scripted(lambda start, end: [
        (MARKER, (120.0, start)),
        ("/live/song/get/track_names", ("A",)),
        (MARKER, (120.0, end)),
    ]) == ("A",)
