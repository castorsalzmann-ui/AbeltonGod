"""Helpers for the Live import tests: the fake AbletonOSC server from ``tests/bridge`` (CI only;
nothing here is evidence for Live behaviour), free ports, a tiny WAV and a registry copy."""

from __future__ import annotations

import importlib.util
import json
import socket
import struct
import sys
from pathlib import Path

from bridge.capabilities import CAPABILITIES_FILE, CapabilityRegistry
from gui_core.live import LiveConfig

BRIDGE_TESTS = Path(__file__).resolve().parents[1] / "bridge"
REPLY_TIMEOUT_S = 5.0  # tests expecting an answer never use less (#180)


def _load_fake():
    name = "fake_abletonosc"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, BRIDGE_TESTS / "fake_abletonosc.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


FakeAbletonOSC = _load_fake().FakeAbletonOSC


def free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def write_wav(path: Path) -> str:
    data = b"\x00\x00" * 4
    fmt = struct.pack("<HHIIHH", 1, 1, 48000, 96000, 2, 16)
    body = (b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data"
            + struct.pack("<I", len(data)) + data)
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return str(path)


def make_fake() -> FakeAbletonOSC:
    server = FakeAbletonOSC()
    server.tracks = [
        {"name": "1-Audio", "mute": False, "audio": True, "slots": ["C:\\old.wav", None,
                                                                    None, None]},
        {"name": "2-MIDI", "mute": False, "slots": [None] * 4},
        {"name": "3-Audio", "mute": False, "audio": True, "slots": [None] * 4},
    ]
    return server


def config_for(fake: FakeAbletonOSC, tmp_path: Path, timeout_s: float = REPLY_TIMEOUT_S
               ) -> LiveConfig:
    receive = free_udp_port()
    fake.response_port = receive
    return LiveConfig("127.0.0.1", fake.port, receive, timeout_s, tmp_path / "actions.jsonl")


def registry_with_status(tmp_path: Path, statuses: dict[str, str]) -> CapabilityRegistry:
    """The real registry with the given ids set to a non-``tested`` status."""
    doc = json.loads(CAPABILITIES_FILE.read_text(encoding="utf-8"))
    for cap in doc["capabilities"]:
        if cap["id"] in statuses:
            cap["status"] = statuses[cap["id"]]
            cap.pop("evidence", None)
    path = tmp_path / "capabilities-status.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return CapabilityRegistry.from_file(path)


def writes(fake) -> list[tuple[str, tuple]]:
    """Real writes the fake saw (the no-argument extension probe is not a write)."""
    names = ("/live/clip_slot/create_audio_clip", "/live/song/create_audio_track",
             "/live/song/undo")
    return [(a, p) for a, p in fake.payload() if a in names and p != ()]
