"""Shared helpers for the bridge tests.

Test files import from here (``from bridge_helpers import ...``), never from ``conftest``:
without ``tests/__init__.py`` every ``conftest.py`` is loaded as the module name ``conftest``,
so a second conftest elsewhere can shadow it depending on collection order (#86, #133).
``tests/bridge/conftest.py`` keeps the fixtures only.
"""

from __future__ import annotations

import json
from pathlib import Path

from bridge.capabilities import CAPABILITIES_FILE, CapabilityRegistry

TEST_TIMEOUT_S = 1.0  # the short deadline, for tests that expect a timeout
REPLY_TIMEOUT_S = 5.0  # tests that expect an ANSWER: 0.25 s expired under CPU load (#180)
# In these modules only the WRITE calls get the short deadline (ShortWrites); ordinary reads
# keep the long one. A stalled write is what the tests expect to time out (#180).
SHORT_WRITE_MODULES = {"test_clip_import_late.py", "test_arrangement_late.py"}
WRITE_METHODS = {
    "create_audio_track", "create_audio_clip", "undo", "set_track_mute", "create_midi_track",
    "set_song_time", "toggle_cue_at_song_time", "set_cue_name", "create_arrangement_midi_clip",
    "add_arrangement_clip_notes",
}


class ShortWrites:
    """Bridge wrapper: write calls run with the short deadline, everything else keeps the
    transport's long one (#180). Read-backs that pass their own ``timeout_s`` are untouched."""

    def __init__(self, bridge, transport) -> None:
        self._bridge, self._transport = bridge, transport

    def __getattr__(self, name):
        attr = getattr(self._bridge, name)
        if name not in WRITE_METHODS:
            return attr

        def short(*args, **kwargs):
            saved = self._transport.timeout_s
            self._transport.timeout_s = TEST_TIMEOUT_S
            try:
                return attr(*args, **kwargs)
            finally:
                self._transport.timeout_s = saved

        return short


def short_writes_if_listed(bridge, transport, request):
    """Wrap ``bridge`` for the modules in SHORT_WRITE_MODULES, else return it unchanged."""
    if request.node.path.name in SHORT_WRITE_MODULES:
        return ShortWrites(bridge, transport)
    return bridge


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


class VirtualClock:
    """Clock and sleep for the read-back poll window (#307).

    ``sleep(s)`` only advances the virtual time, so the 2.0 s ``READBACK_WINDOW_S`` of a
    read-back that never matches costs no wall time. The reads inside the window are still
    real OSC round trips to the fake, one per poll interval. Only for tests whose subject is
    NOT how real time passes during the window (a fake that changes state on a timer needs the
    real clock). The reply timeouts of the transport stay real: they have their own clock.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def virtual_poll_window(monkeypatch, module, *class_names: str) -> VirtualClock:
    """Make ``module.<class>`` (ClipImporter / ArrangementWriter, as the script looks them up)
    run its poll window on a virtual clock. Production code is untouched; the script itself
    keeps its default real clock."""
    import functools

    vc = VirtualClock()
    for name in class_names:
        monkeypatch.setattr(module, name, functools.partial(getattr(module, name),
                                                            clock=vc.clock, sleep=vc.sleep))
    return vc
