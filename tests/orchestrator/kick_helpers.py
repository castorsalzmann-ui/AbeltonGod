"""Helpers for the #148 tool-wiring tests: a project folder, the fake AbletonOSC server from
``tests/bridge``, a capability registry copy and an approver that records what it was shown.

The fake server is CI-only (``tests/bridge/fake_abletonosc.py``); nothing here is evidence
for Live behaviour.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from bridge.capabilities import CAPABILITIES_FILE, CapabilityGate, CapabilityRegistry
from bridge.osc_client import AbletonBridge, OscTransport
from orchestrator.kick_tools import IMPORT_CAPS, LIST_TRACKS_CAPS, KickSession
from orchestrator.tools import Toolbox

BRIDGE_TESTS = Path(__file__).resolve().parents[1] / "bridge"
TEST_TIMEOUT_S = 0.25
# Fast kicks: short, no drive. Values written here, not taken from a preset.
FAST_KICK = {"schema_version": "0.2", "seed": 4711, "length_ms": 120.0, "amp_decay_ms": 60.0,
             "drive": 0.0, "bpm": 136}


def _load_fake_module():
    name = "fake_abletonosc"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, BRIDGE_TESTS / "fake_abletonosc.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FakeAbletonOSC = _load_fake_module().FakeAbletonOSC


def registry_copy(tmp_path: Path, tested: set[str] | None = None,
                  not_tested: dict[str, str] | None = None) -> CapabilityRegistry:
    """The real registry with the given ids ``tested`` (fixture evidence) and the
    ``not_tested`` ones set to their status; independent of what the user verified so far."""
    tested = set(LIST_TRACKS_CAPS) | set(IMPORT_CAPS) if tested is None else tested
    doc = json.loads(CAPABILITIES_FILE.read_text(encoding="utf-8"))
    for cap in doc["capabilities"]:
        if not_tested and cap["id"] in not_tested:
            cap["status"] = not_tested[cap["id"]]
            cap.pop("evidence", None)
        elif cap["id"] in tested:
            cap["status"] = "tested"
            cap["evidence"] = "test fixture - not real evidence"
        elif cap["status"] == "tested":
            cap["status"] = "supported"
            cap.pop("evidence", None)
    path = tmp_path / f"capabilities-{len(list(tmp_path.glob('capabilities-*')))}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return CapabilityRegistry.from_file(path)


def make_project(tmp_path: Path, name: str = "Test Project") -> Path:
    project = tmp_path / name
    project.mkdir(parents=True)
    (project / "Test.als").write_bytes(b"not a real set")
    return project


def audio_set(fake) -> None:
    """Track 0 audio, track 1 MIDI, track 2 audio with slot 0 taken; 4 scenes."""
    fake.num_scenes = 4
    fake.tracks = [
        {"name": "1-Kick", "mute": False, "audio": True},
        {"name": "2-Bass", "mute": False},
        {"name": "3-Audio", "mute": False, "audio": True,
         "slots": ["C:/other.wav", None, None, None]},
    ]


def bridge_factory(fake, registry: CapabilityRegistry, made: list | None = None):
    def connect() -> AbletonBridge:
        t = OscTransport(send_port=fake.port, receive_port=0, timeout_s=TEST_TIMEOUT_S)
        fake.response_port = t.receive_port
        bridge = AbletonBridge(t, CapabilityGate(registry))
        if made is not None:
            made.append(bridge)
        return bridge

    return connect


class Problem:
    def __init__(self, reason: str, path: str, detail: str = "") -> None:
        self.reason, self.path, self.detail = reason, path, detail


class ProjectCheckDouble:
    """Stands in for ``library.check_project_dir`` (#149, not merged yet) in CI. It
    implements none of the real rules: it accepts exactly the folders in ``accept``."""

    def __init__(self, *accept: Path) -> None:
        self.accept = {str(p) for p in accept}
        self.calls: list[tuple[str, Any]] = []

    def __call__(self, project_dir, *, refused_roots=None):
        self.calls.append((str(project_dir), refused_roots))
        if str(project_dir) in self.accept:
            return None
        return Problem("refused_by_double", str(project_dir))


def make_session(tmp_path: Path, fake=None, **kwargs: Any) -> KickSession:
    registry = kwargs.pop("registry", None) or registry_copy(tmp_path)
    project = kwargs.pop("project", None) or make_project(tmp_path)
    factory = kwargs.pop("bridge_factory", None)
    if factory is None and fake is not None:
        factory = bridge_factory(fake, registry)
    kwargs.setdefault("project_check", ProjectCheckDouble(project))
    return KickSession(project, bridge_factory=factory, registry=registry,
                       action_log=tmp_path / "actions.jsonl", refused_roots=(), **kwargs)


def toolbox(session: KickSession, clock: Callable[[], float] | None = None) -> Toolbox:
    kwargs = {"clock": clock} if clock is not None else {}
    return Toolbox(session.tools(), capability_gate=session.gate(), **kwargs)


def writes_sent(fake) -> list[tuple[str, tuple]]:
    """Every message the fake got that changes the set."""
    write_addresses = {"/live/clip_slot/create_audio_clip", "/live/song/create_audio_track",
                       "/live/track/set/mute", "/live/song/undo"}
    return [(a, p) for a, p in fake.payload() if a in write_addresses]


def tool_log(guard) -> list[dict]:
    path = guard._log.path
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]
    return [e for e in entries if e.get("kind") == "tool"]


class RecordingApprover:
    """Answers ``answer``; records (tool, arguments, plan summary); ``during`` runs while the
    user is "deciding" (to change files or the set between plan and yes)."""

    def __init__(self, answer: Any = True, during: Callable[[], None] | None = None) -> None:
        self.answer = answer
        self.during = during
        self.asked: list[tuple[str, dict, dict | None]] = []

    def confirm(self, tool, arguments, plan):
        self.asked.append((tool.name, arguments, None if plan is None else plan.summary))
        if self.during is not None:
            self.during()
        return self.answer


@pytest.fixture(name="fake")
def fake_fixture():
    server = FakeAbletonOSC()
    audio_set(server)
    yield server
    server.close()
