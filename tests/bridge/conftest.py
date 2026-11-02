from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_abletonosc import FakeAbletonOSC

from bridge.capabilities import CAPABILITIES_FILE, CapabilityGate, CapabilityRegistry
from bridge.osc_client import ADDRESSES, AbletonBridge, OscTransport

TEST_TIMEOUT_S = 0.25
# Tests that expect an ANSWER get a generous deadline: under heavy CPU load (25 busy processes
# on 2 cores) a 0.25 s deadline expired and the test failed with BridgeTimeoutError (#180).
REPLY_TIMEOUT_S = 5.0
# Tests that expect the TIMEOUT keep the short one. A new test that drops or stalls a reply
# and fails because it now waits 5 s: add its name (or its module) here.
SHORT_TIMEOUT_MODULES = {"test_clip_import_late.py", "test_arrangement_late.py"}
SHORT_TIMEOUT_TESTS = {
    "test_missing_markers_time_out_after_the_timeout",
    "test_timed_out_write_that_reads_back_as_intended_is_settled",
    "test_timed_out_write_that_never_happened_is_unknown_and_blocks_undo",
    "test_timed_out_write_with_failed_readback",
    "test_late_read_reply_does_not_answer_the_next_read",
    "test_error_of_a_timed_out_request_is_not_raised_on_the_next",
    "test_write_that_fails_after_a_timed_out_write_is_not_confirmed",
}


def registry_with(tmp_path: Path, tested: set[str]) -> CapabilityRegistry:
    """Copy of the real registry where exactly the given ids are ``tested`` (fake evidence).

    Entries that are ``tested`` in the real registry but not listed are set back to
    ``supported``, so gate tests do not depend on what the user has verified so far.
    """
    doc = json.loads(CAPABILITIES_FILE.read_text(encoding="utf-8"))
    for cap in doc["capabilities"]:
        if cap["id"] in tested:
            cap["status"] = "tested"
            cap["evidence"] = "test fixture - not real evidence"
        elif cap["status"] == "tested":
            cap["status"] = "supported"
            cap.pop("evidence", None)
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return CapabilityRegistry.from_file(path)


def registry_with_status(tmp_path: Path, statuses: dict[str, str]) -> CapabilityRegistry:
    """Copy of the real registry with the given ids set to the given non-``tested`` status.

    For tests of the override path that must not depend on what the user has verified so far
    (e.g. ``clip_slot.create_audio_clip`` became ``tested`` in #50)."""
    doc = json.loads(CAPABILITIES_FILE.read_text(encoding="utf-8"))
    for cap in doc["capabilities"]:
        if cap["id"] in statuses:
            assert statuses[cap["id"]] != "tested", "use registry_with for tested entries"
            cap["status"] = statuses[cap["id"]]
            cap.pop("evidence", None)
    assert {c["id"] for c in doc["capabilities"]} >= set(statuses), statuses
    path = tmp_path / "capabilities-status.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return CapabilityRegistry.from_file(path)


@pytest.fixture
def fake():
    server = FakeAbletonOSC()
    yield server
    server.close()


@pytest.fixture
def transport(fake, request):
    expects_timeout = (request.node.path.name in SHORT_TIMEOUT_MODULES
                       or request.node.originalname in SHORT_TIMEOUT_TESTS)
    t = OscTransport(send_port=fake.port, receive_port=0,
                     timeout_s=TEST_TIMEOUT_S if expects_timeout else REPLY_TIMEOUT_S)
    fake.response_port = t.receive_port
    yield t
    t.close()


@pytest.fixture
def bridge(fake, transport, tmp_path):
    """Bridge whose registry marks every bridge capability as tested (CI only)."""
    gate = CapabilityGate(registry_with(tmp_path, set(ADDRESSES)))
    return AbletonBridge(transport, gate)
