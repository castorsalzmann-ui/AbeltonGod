"""Capability registry and gate (issue #4, acceptance criterion 2)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import registry_with

from bridge.capabilities import (
    CAPABILITIES_FILE,
    CapabilityGate,
    CapabilityNotTestedError,
    CapabilityRegistry,
    CapabilityRegistryError,
    UnknownCapabilityError,
)
from bridge.osc_client import ADDRESSES, AbletonBridge

RAW = json.loads(CAPABILITIES_FILE.read_text(encoding="utf-8"))


def test_real_registry_loads_with_all_ids_and_statuses():
    reg = CapabilityRegistry.from_file()
    assert reg.ids() == [c["id"] for c in RAW["capabilities"]]
    for c in RAW["capabilities"]:
        assert reg.get(c["id"]).status == c["status"]


def test_bridge_addresses_match_registry_targets():
    """Every address the bridge sends is the one recorded in the capability registry."""
    targets = {c["id"]: c["target"] for c in RAW["capabilities"]}
    for cap_id, addresses in ADDRESSES.items():
        assert cap_id in targets, cap_id
        recorded = {a.strip() for a in targets[cap_id].split(",")}
        assert set(addresses) == recorded, cap_id


@pytest.mark.parametrize("status", ["unknown", "supported"])
def test_gate_refuses_not_tested(tmp_path, status):
    reg = registry_with(tmp_path, set())
    cap_id = next(c["id"] for c in RAW["capabilities"] if c["status"] == status)
    with pytest.raises(CapabilityNotTestedError) as err:
        CapabilityGate(reg).check(cap_id)
    assert err.value.status == status


def test_gate_allows_tested(tmp_path):
    gate = CapabilityGate(registry_with(tmp_path, {"song.tempo.get"}))
    assert gate.check("song.tempo.get").status == "tested"
    assert gate.overrides_used == []


def test_override_allows_named_capability_only_and_is_recorded(tmp_path):
    gate = CapabilityGate(registry_with(tmp_path, set()), allow_untested={"track.mute.set"})
    assert gate.check("track.mute.set").status == "supported"
    assert gate.overrides_used == ["track.mute.set"]
    with pytest.raises(CapabilityNotTestedError):
        gate.check("song.undo")


def test_override_cannot_unlock_unsupported(tmp_path):
    reg = registry_with(tmp_path, set())
    with pytest.raises(CapabilityNotTestedError):
        CapabilityGate(reg, allow_untested={"song.export_audio"})
    with pytest.raises(CapabilityNotTestedError):
        CapabilityGate(reg).check("song.export_audio")


def test_override_with_unknown_id_fails_at_construction(tmp_path):
    with pytest.raises(UnknownCapabilityError):
        CapabilityGate(registry_with(tmp_path, set()), allow_untested={"track.mute.sett"})


def test_unknown_capability_is_refused(tmp_path):
    with pytest.raises(UnknownCapabilityError):
        CapabilityGate(registry_with(tmp_path, set())).check("song.delete_everything")


def test_registry_rejects_tested_without_evidence(tmp_path):
    doc = json.loads(json.dumps(RAW))
    doc["capabilities"][0]["status"] = "tested"
    doc["capabilities"][0].pop("evidence", None)
    path = tmp_path / "caps.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(CapabilityRegistryError, match="schema"):
        CapabilityRegistry.from_file(path)


def test_registry_rejects_bad_json_and_missing_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(CapabilityRegistryError):
        CapabilityRegistry.from_file(bad)
    with pytest.raises(CapabilityRegistryError):
        CapabilityRegistry.from_file(tmp_path / "missing.json")


def test_registry_rejects_duplicate_ids(tmp_path):
    doc = json.loads(json.dumps(RAW))
    doc["capabilities"].append(dict(doc["capabilities"][0]))
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(CapabilityRegistryError, match="duplicate"):
        CapabilityRegistry.from_file(path)


# With no bridge capability tested, every bridge call must be refused before anything
# reaches the network. Uses a fixture registry: the committed one has them tested (#5).
BRIDGE_CALLS = {
    "app.version": lambda b: b.get_version(),
    "song.tempo.get": lambda b: b.get_tempo(),
    "song.signature.get": lambda b: b.get_signature(),
    "song.track_names.get": lambda b: b.get_track_names(),
    "track.mute.set": lambda b: b.set_track_mute(0, True),
    "song.undo": lambda b: b.undo(),
}


def test_every_bridge_capability_has_a_gate_test():
    assert set(BRIDGE_CALLS) == set(ADDRESSES)


@pytest.mark.parametrize("cap_id", sorted(BRIDGE_CALLS))
def test_bridge_refuses_untested_before_any_network_io(fake, transport, tmp_path, cap_id):
    bridge = AbletonBridge(transport, CapabilityGate(registry_with(tmp_path, set())))
    with pytest.raises(CapabilityNotTestedError) as err:
        BRIDGE_CALLS[cap_id](bridge)
    assert err.value.capability_id == cap_id
    bridge.ping()  # two markers; anything sent before them would be processed first
    fake.wait_received(2)
    assert fake.payload() == []


@pytest.mark.parametrize("cap_id", sorted(BRIDGE_CALLS))
def test_bridge_refuses_when_only_other_capabilities_are_tested(fake, transport, tmp_path,
                                                                cap_id):
    others = set(ADDRESSES) - {cap_id}
    bridge = AbletonBridge(transport, CapabilityGate(registry_with(tmp_path, others)))
    with pytest.raises(CapabilityNotTestedError):
        BRIDGE_CALLS[cap_id](bridge)


@pytest.mark.parametrize("cap_id", sorted(BRIDGE_CALLS))
def test_bridge_override_lets_check_script_call(fake, transport, tmp_path, cap_id):
    gate = CapabilityGate(registry_with(tmp_path, set()), allow_untested={cap_id})
    BRIDGE_CALLS[cap_id](AbletonBridge(transport, gate))
    assert gate.overrides_used and set(gate.overrides_used) == {cap_id}


ROOT = Path(__file__).resolve().parents[2]
SCANNED = [ROOT / "src", ROOT / "scripts"]  # scripts/: bridge_check.py (#5) and later tools


def test_only_osc_client_uses_the_transport():
    """The ungated wire layer must not be reachable from other modules or scripts (D-004)."""
    pattern = re.compile(r"\bOscTransport\b|\b_transport\b|\b_sock\b")
    offenders = [
        str(path.relative_to(ROOT))
        for base in SCANNED
        if base.exists()
        for path in base.rglob("*.py")
        if path.name != "osc_client.py" and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_transport_scan_would_catch_an_offender(tmp_path):
    """The scan above is not vacuous: the same pattern finds a typical bypass."""
    pattern = re.compile(r"\bOscTransport\b|\b_transport\b|\b_sock\b")
    assert pattern.search("from bridge.osc_client import OscTransport")
    assert pattern.search("bridge._transport.send_confirmed('/live/song/undo')")
    assert not pattern.search("bridge.endpoint")
