"""Shared helpers for the bridge tests.

Test files import from here (``from bridge_helpers import ...``), never from ``conftest``:
without ``tests/__init__.py`` every ``conftest.py`` is loaded as the module name ``conftest``,
so a second conftest elsewhere can shadow it depending on collection order (#86, #133).
``tests/bridge/conftest.py`` keeps the fixtures. ``TEST_TIMEOUT_S`` is still defined there until
#180 (qa-tester) is merged; moving it here is the remaining part of #133.
"""

from __future__ import annotations

import json
from pathlib import Path

from bridge.capabilities import CAPABILITIES_FILE, CapabilityRegistry


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
