from __future__ import annotations

import json
from pathlib import Path

import pytest
from fake_abletonosc import FakeAbletonOSC

from bridge.capabilities import CAPABILITIES_FILE, CapabilityGate, CapabilityRegistry
from bridge.osc_client import ADDRESSES, AbletonBridge, OscTransport

TEST_TIMEOUT_S = 0.25


def registry_with(tmp_path: Path, tested: set[str]) -> CapabilityRegistry:
    """Copy of the real registry with the given ids marked ``tested`` (fake evidence)."""
    doc = json.loads(CAPABILITIES_FILE.read_text(encoding="utf-8"))
    for cap in doc["capabilities"]:
        if cap["id"] in tested:
            cap["status"] = "tested"
            cap["evidence"] = "test fixture - not real evidence"
    path = tmp_path / "capabilities.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return CapabilityRegistry.from_file(path)


@pytest.fixture
def fake():
    server = FakeAbletonOSC()
    yield server
    server.close()


@pytest.fixture
def transport(fake):
    t = OscTransport(send_port=fake.port, receive_port=0, timeout_s=TEST_TIMEOUT_S,
                     resync_grace_s=0.3)
    fake.response_port = t.receive_port
    yield t
    t.close()


@pytest.fixture
def bridge(fake, transport, tmp_path):
    """Bridge whose registry marks every bridge capability as tested (CI only)."""
    gate = CapabilityGate(registry_with(tmp_path, set(ADDRESSES)))
    return AbletonBridge(transport, gate)
