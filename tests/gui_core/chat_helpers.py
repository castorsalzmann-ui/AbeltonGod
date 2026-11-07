"""Helpers for the GUI copilot tests (#491): a ``ChatSession`` on a fake model, the fake
AbletonOSC server of ``tests/bridge`` and a guard with its own log. CI only: nothing here is
evidence for Claude or Live behaviour."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from live_helpers import REPLY_TIMEOUT_S, make_fake, writes  # noqa: F401 - re-exported

from bridge.capabilities import CapabilityGate, CapabilityRegistry
from bridge.osc_client import AbletonBridge, OscTransport
from guard import Guard
from guard.policy import DEFAULT_POLICY_FILE, parse_policy
from gui_core.chat import ChatSession
from orchestrator.fake_model import FakeModel

CLAP = {"category": "clap", "preset": "short", "prompt": "", "seed": 7, "variants": 1,
        "adjust": []}
IMPORT = {"sample_id": "clap-1", "track_index": 2}  # track 3 "3-Audio", all slots empty
CREATE = "/live/clip_slot/create_audio_clip"


def guard_for(tmp_path: Path, **profile_changes: Any) -> Guard:
    """The real policy file with ``kick_generation`` changed as given (values written in the
    test, not read from the code under test)."""
    doc = json.loads(Path(DEFAULT_POLICY_FILE).read_text(encoding="utf-8"))
    doc["profiles"]["kick_generation"].update(profile_changes)
    n = len(list(tmp_path.glob("usage*.jsonl")))
    return Guard(parse_policy(doc), log_path=tmp_path / f"usage{n}.jsonl")


def bridge_factory(fake, registry: CapabilityRegistry, timeout_s: float = REPLY_TIMEOUT_S):
    def connect() -> AbletonBridge:
        t = OscTransport(send_port=fake.port, receive_port=0, timeout_s=timeout_s)
        fake.response_port = t.receive_port
        return AbletonBridge(t, CapabilityGate(registry))

    return connect


def turn_generate(call_id: str = "g1", args: dict | None = None) -> dict:
    return {"tool_calls": [{"id": call_id, "name": "generate_sample",
                            "arguments": args or CLAP}],
            "usage": {"output_tokens": 50, "cost_usd": 0.01}}


def turn_import(call_id: str = "i1", args: dict | None = None) -> dict:
    return {"tool_calls": [{"id": call_id, "name": "import_sample",
                            "arguments": args or IMPORT}],
            "usage": {"output_tokens": 50, "cost_usd": 0.01}}


def turn_text(text: str = "Fertig.") -> dict:
    return {"text": text, "usage": {"output_tokens": 20, "cost_usd": 0.01}}


def make_chat(tmp_path: Path, turns: list[dict], fake=None, *, guard: Guard | None = None,
              approver: Any = None, out: Path | None = None, project: str = "",
              bridge_timeout_s: float = REPLY_TIMEOUT_S) -> tuple[ChatSession, FakeModel]:
    """A session on ``turns`` with the output folder ``tmp_path/out``. ``refused_roots=()``:
    the test folder lies inside the checkout, which the default check refuses. ``project``:
    the shared Live project folder (#500). A short ``bridge_timeout_s`` only for a test whose
    subject is the timeout (#180)."""
    registry = CapabilityRegistry.from_file()  # the real registry: only `tested` caps pass
    options: dict[str, Any] = {"registry": registry, "action_log": tmp_path / "actions.jsonl",
                               "refused_roots": (), "bridge_timeout_s": bridge_timeout_s}
    if fake is not None:
        options["bridge_factory"] = bridge_factory(fake, registry, bridge_timeout_s)
    model = FakeModel(turns)
    session = ChatSession(tmp_path / ".env", model=model, guard=guard or guard_for(tmp_path),
                          output_dir=out or tmp_path / "out", approver=approver,
                          project_dir=project, session_options=options)
    return session, model


def make_project(tmp_path: Path, name: str = "Proj") -> Path:
    project = tmp_path / name
    project.mkdir(parents=True)
    (project / "Test.als").write_bytes(b"not a real set")
    return project


def wavs(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.wav")) if folder.is_dir() else []
