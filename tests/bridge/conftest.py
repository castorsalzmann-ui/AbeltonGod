"""Fixtures for the bridge tests. Shared helper functions live in ``bridge_helpers.py`` (#133)."""

from __future__ import annotations

import pytest
from bridge_helpers import REPLY_TIMEOUT_S, TEST_TIMEOUT_S, registry_with, short_writes_if_listed
from fake_abletonosc import FakeAbletonOSC

from bridge.capabilities import CapabilityGate
from bridge.osc_client import ADDRESSES, AbletonBridge, OscTransport

# Tests that expect an ANSWER get a generous deadline: under heavy CPU load (25 busy processes
# on 2 cores) a 0.25 s deadline expired and the test failed with BridgeTimeoutError (#180).
# Tests that expect the TIMEOUT keep the short one (TEST_TIMEOUT_S, bridge_helpers). A new test
# that drops or stalls a reply and fails because it now waits 5 s: add its name here, or its
# module to SHORT_WRITE_MODULES in bridge_helpers.
SHORT_TIMEOUT_TESTS = {
    "test_missing_markers_time_out_after_the_timeout",
    "test_timed_out_write_that_reads_back_as_intended_is_settled",
    "test_timed_out_write_that_never_happened_is_unknown_and_blocks_undo",
    "test_timed_out_write_with_failed_readback",
    "test_late_read_reply_does_not_answer_the_next_read",
    "test_error_of_a_timed_out_request_is_not_raised_on_the_next",
    "test_write_that_fails_after_a_timed_out_write_is_not_confirmed",
    "test_unknown_or_pushed_out_request_ids_give_none",
}


@pytest.fixture
def fake():
    server = FakeAbletonOSC()
    yield server
    server.close()


@pytest.fixture
def transport(fake, request):
    expects_timeout = request.node.originalname in SHORT_TIMEOUT_TESTS
    t = OscTransport(send_port=fake.port, receive_port=0,
                     timeout_s=TEST_TIMEOUT_S if expects_timeout else REPLY_TIMEOUT_S)
    fake.response_port = t.receive_port
    yield t
    t.close()


@pytest.fixture
def bridge(fake, transport, tmp_path, request):
    """Bridge whose registry marks every bridge capability as tested (CI only)."""
    gate = CapabilityGate(registry_with(tmp_path, set(ADDRESSES)))
    return short_writes_if_listed(AbletonBridge(transport, gate), transport, request)
