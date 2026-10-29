"""Capability registry and gate (issue #4, acceptance criterion 2)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import registry_with, registry_with_status

from bridge.capabilities import (
    CAPABILITIES_FILE,
    CapabilityGate,
    CapabilityNotTestedError,
    CapabilityRegistry,
    CapabilityRegistryError,
    UnknownCapabilityError,
)
from bridge.osc_client import ADDRESSES, EXTENSION_ADDRESSES, PENDING_REGISTRY, AbletonBridge

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


# Any single- or double-quoted string literal that starts with /live/ (also f-strings and
# literals with digits, '*' or '{...}'), so an address cannot hide behind a quoting style (#44).
OSC_LITERAL = re.compile(r"""["'](/live/[^"'\s]*)["']""")


def scanned_address_literals() -> set[str]:
    files = [*(ROOT / "src" / "bridge").glob("*.py"), *(ROOT / "scripts").glob("*.py")]
    return {m for f in files for m in OSC_LITERAL.findall(f.read_text(encoding="utf-8"))}


def test_address_scan_finds_every_quoting_style():
    found = set(OSC_LITERAL.findall(
        """a = '/live/track/get/solo'\nb = "/live/x/y"\nc = f"/live/track/{i}/z"\n"""
        """d = '/live/clip_slot/*'\n"""
    ))
    assert found == {"/live/track/get/solo", "/live/x/y", "/live/track/{i}/z",
                     "/live/clip_slot/*"}


def test_every_address_the_bridge_sends_is_registered_or_pending():
    """No /live/ literal in src/bridge/ or scripts/ outside ADDRESSES, PENDING_REGISTRY and
    the marker/error addresses (#39, #44).

    This also flags a quoted /live/ path in future user-facing text (e.g. a German hint
    naming an OSC address). That is on purpose: such text must take the address from
    ADDRESSES, not repeat it as a literal (nit from the PR #45 review)."""
    literals = scanned_address_literals()
    assert literals, "scan found nothing: the pattern or the paths are broken"
    known = {a for addrs in ADDRESSES.values() for a in addrs}
    known |= {a for addrs, _ in PENDING_REGISTRY.values() for a in addrs}
    known |= {a for addrs, _ in EXTENSION_ADDRESSES.values() for a in addrs}
    known |= {"/live/error", "/live/song/get/tempo"}  # reply error address; request marker
    assert literals - known == set()


def test_extension_capabilities_are_registered_with_their_lom_target():
    """Extension addresses are not AbletonOSC's own; the registry records the LOM call (#50)."""
    targets = {c["id"]: c["target"] for c in RAW["capabilities"]}
    assert set(EXTENSION_ADDRESSES) == {"clip_slot.create_audio_clip"}
    for cap_id, (addresses, target) in EXTENSION_ADDRESSES.items():
        assert targets[cap_id] == target
        assert cap_id not in ADDRESSES
        assert addresses == ("/live/clip_slot/create_audio_clip",)


def test_import_capability_statuses_follow_the_50_evidence():
    """#50 contract-change: create_audio_clip is `tested` from user runs 2-4 and keeps its
    limitations; create_audio_track stays `supported` until its undo is run in Live (D-004)."""
    caps = {c["id"]: c for c in RAW["capabilities"]}
    clip, track = caps["clip_slot.create_audio_clip"], caps["song.create_audio_track"]
    assert clip["status"] == "tested"
    assert clip["evidence"].startswith(
        "https://github.com/castorsalzmann-ui/AbeltonGod/issues/50#issuecomment-")
    for limitation in ("undo after user interaction in Live is not reliable",
                       "cause not established", "the pre-check refused and sent nothing",
                       "not on a new track with live_import 0.2.0",
                       # PR #124 review: no claim stronger than #50 shows
                       "not established whether the clip was launched in run 3 or in run 4",
                       "most likely the user's own interaction in Live, not confirmed",
                       "neither supports nor rules out the launch hypothesis",
                       "Live 12.4 per API; user reports 12.4.5"):
        assert limitation in clip["notes"], limitation
    for overstatement in ("nothing touched in Live", "reverted by the user", "user hears the kick"):
        assert overstatement not in clip["notes"], overstatement
    assert track["status"] == "supported"
    assert "evidence" not in track
    assert "Missing for 'tested'" in track["notes"]


def test_pending_entries_are_not_yet_in_the_registry_and_borrow_a_real_gate():
    """Pending ids must move into ADDRESSES (and the registry) in the contract-change PR."""
    targets = {c["id"]: c["target"] for c in RAW["capabilities"]}
    for cap_id, (addresses, borrowed) in PENDING_REGISTRY.items():
        assert cap_id not in targets, f"{cap_id} is registered now: move it into ADDRESSES"
        assert cap_id not in ADDRESSES
        assert borrowed in ADDRESSES or borrowed in EXTENSION_ADDRESSES
        assert borrowed in targets
        assert not set(addresses) & {a for v in ADDRESSES.values() for a in v}
    # track.mute.get moved into ADDRESSES and the registry in #42. #50 added the four reads of
    # the clip import; they borrow the import's own gate. New entries must be added deliberately.
    assert {k: v[1] for k, v in PENDING_REGISTRY.items()} == {
        "track.has_audio_input.get": "clip_slot.create_audio_clip",
        "clip_slot.has_clip.get": "clip_slot.create_audio_clip",
        "clip.file_path.get": "clip_slot.create_audio_clip",
        "song.num_scenes.get": "clip_slot.create_audio_clip",
    }


@pytest.mark.parametrize("status", ["unknown", "supported"])
def test_gate_refuses_not_tested(tmp_path, status):
    # No real entry is `unknown` any more (#50), so the status is set on a copy.
    cap_id = "clip_slot.create_audio_clip"
    reg = registry_with_status(tmp_path, {cap_id: status})
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
    "track.mute.get": lambda b: b.get_track_mute(0),
    "song.undo": lambda b: b.undo(),
    "song.create_audio_track": lambda b: b.create_audio_track(-1),
}

# Extension and pending calls (#50): each is refused unless its gate capability is allowed.
GATED_EXTRA_CALLS = {
    "clip_slot.create_audio_clip": lambda b: b.create_audio_clip(0, 0, str(ROOT / "k.wav")),
    "probe_audio_clip_extension": lambda b: b.probe_audio_clip_extension(),
    "track.has_audio_input.get": lambda b: b.get_track_has_audio_input(0),
    "clip_slot.has_clip.get": lambda b: b.get_clip_slot_has_clip(0, 0),
    "clip.file_path.get": lambda b: b.get_clip_file_path(0, 0),
    "song.num_scenes.get": lambda b: b.get_num_scenes(),
}


def test_every_bridge_capability_has_a_gate_test():
    assert set(BRIDGE_CALLS) == set(ADDRESSES)
    assert set(GATED_EXTRA_CALLS) == (set(EXTENSION_ADDRESSES) | set(PENDING_REGISTRY)
                                      | {"probe_audio_clip_extension"})


@pytest.mark.parametrize("name", sorted(GATED_EXTRA_CALLS))
def test_import_calls_refused_before_any_network_io(fake, transport, tmp_path, name):
    """Even with every other capability tested, the import path stays locked (D-004)."""
    others = set(ADDRESSES)
    bridge = AbletonBridge(transport, CapabilityGate(registry_with(tmp_path, others)))
    with pytest.raises(CapabilityNotTestedError) as err:
        GATED_EXTRA_CALLS[name](bridge)
    assert err.value.capability_id == "clip_slot.create_audio_clip"
    bridge.ping()
    fake.wait_received(2)
    assert fake.payload() == []


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
