"""Fixtures for the bridge tests. Shared helper functions live in ``bridge_helpers.py`` (#133)."""

from __future__ import annotations

import pytest
from bridge_helpers import TEST_TIMEOUT_S, registry_with
from fake_abletonosc import FakeAbletonOSC

from bridge.capabilities import CapabilityGate
from bridge.osc_client import ADDRESSES, AbletonBridge, OscTransport


@pytest.fixture
def fake():
    server = FakeAbletonOSC()
    yield server
    server.close()


@pytest.fixture
def transport(fake):
    t = OscTransport(send_port=fake.port, receive_port=0, timeout_s=TEST_TIMEOUT_S)
    fake.response_port = t.receive_port
    yield t
    t.close()


@pytest.fixture
def bridge(fake, transport, tmp_path):
    """Bridge whose registry marks every bridge capability as tested (CI only)."""
    gate = CapabilityGate(registry_with(tmp_path, set(ADDRESSES)))
    return AbletonBridge(transport, gate)
