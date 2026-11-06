"""No console window for the Claude CLI under the windowed exe (#453).

The windowed ``AbeltonGod.exe`` (#448) has no console; ``claude.exe`` is a console program,
so Windows would give it a new console window per chat (closing it kills the CLI). The client
starts the CLI with ``CREATE_NO_WINDOW`` (0x08000000, winbase.h) on Windows when this process
has no console window, through its private event loop; elsewhere nothing changes.

The unit tests run the SDK's real ``SubprocessCLITransport.connect`` (version probe and main
start) on the client's loop with a fake process starter in place of the OS start. The
Windows-only test starts one real chat request from ``pythonw.exe`` (no console) to a fake
CLI under ``python.exe`` (a console program) and reads the console window the CLI got; the
same run with ``creationflags=0`` is the control that shows the window appears without the
flag. No real Claude CLI and no network.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    clock_fixture,
    events_fixture,
    make_guard_fixture,
)

from orchestrator.auth import AuthMode, AuthSettings
from orchestrator.loop import Orchestrator
from orchestrator.sdk_client import SdkModelClient, default_cli_creationflags
from orchestrator.tools import Toolbox

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW, winbase.h (written here, not taken from the code)
HERE = Path(__file__).resolve().parent


def settings() -> AuthSettings:
    return AuthSettings(AuthMode.SUBSCRIPTION, "claude-opus-5-5", api_key_present=False)


@pytest.fixture(name="client")
def client_fixture():
    made: list[SdkModelClient] = []

    def make(**kwargs) -> SdkModelClient:
        client = SdkModelClient(settings(), per_call_estimate_usd=0.01,
                                cli_path="fake-claude-not-started", **kwargs)
        made.append(client)
        return client

    yield make
    for client in made:
        client.close()


def fake_starter(client: SdkModelClient) -> list[tuple[list[str], int]]:
    """Replace the OS process start of the client's loop (the step below
    ``loop.subprocess_exec``): record argv and ``creationflags``, start nothing."""
    calls: list[tuple[list[str], int]] = []

    async def start(protocol, args, shell, stdin, stdout, stderr, bufsize, **kwargs):
        calls.append(([str(a) for a in args], kwargs.get("creationflags")))
        raise FileNotFoundError(args[0])

    client._loop._make_subprocess_transport = start
    return calls


def chat(make_guard, client) -> object:
    return Orchestrator(make_guard(), client, Toolbox(), profile="p").handle("Hallo")


# --- decision ------------------------------------------------------------------------------


@pytest.mark.parametrize(("platform", "console", "expected"), [
    ("win32", False, NO_WINDOW),  # windowed exe / pythonw
    ("win32", True, 0),           # python -m orchestrator.chat, the CLI exe
    ("linux", False, 0),
    ("linux", True, 0),
    ("darwin", False, 0),
])
def test_flag_only_on_windows_without_a_console(platform, console, expected):
    assert default_cli_creationflags(platform, has_console=lambda: console) == expected


@pytest.mark.skipif(sys.platform == "win32", reason="the default off Windows")
def test_default_off_windows_keeps_the_plain_event_loop(client):
    c = client()
    assert c.creationflags == 0
    assert type(c._loop).__name__ != "_CliEventLoop"


# --- the SDK's spawns get the flag ---------------------------------------------------------


def test_windowed_case_passes_the_flag_to_every_cli_start(make_guard, client, monkeypatch):
    monkeypatch.delenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", raising=False)
    c = client(creationflags=NO_WINDOW)
    calls = fake_starter(c)
    out = chat(make_guard, c)
    assert out.success is False and out.error == "model_unavailable", out
    # the SDK's "-v" probe, then the CLI itself; both through the client's loop
    assert [argv[:2] for argv, _ in calls][0] == ["fake-claude-not-started", "-v"]
    assert len(calls) == 2 and "--max-turns" in calls[1][0], calls
    assert [flags for _, flags in calls] == [NO_WINDOW, NO_WINDOW]


def test_console_case_starts_the_cli_without_flags(make_guard, client, monkeypatch):
    monkeypatch.delenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", raising=False)
    c = client(creationflags=0)
    calls = fake_starter(c)
    out = chat(make_guard, c)
    assert out.success is False and out.error == "model_unavailable", out
    assert len(calls) == 2 and "--max-turns" in calls[1][0], calls
    assert [flags for _, flags in calls] == [0, 0]  # the SDK's own value (anyio's default)


# --- Windows: a real chat request from a windowed process ----------------------------------


def _windowed_chat(tmp_path: Path, mode: str) -> tuple[dict, int]:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        pytest.skip(f"no pythonw.exe next to {sys.executable}")
    out_file, console_file = tmp_path / f"{mode}.json", tmp_path / f"{mode}.console"
    env = {**os.environ, "FAKE_CLI_CONSOLEFILE": str(console_file)}
    subprocess.run([str(pythonw), str(HERE / "windowed_chat_probe.py"), str(out_file),
                    sys.executable, mode], env=env, timeout=120, check=False,
                   stdin=subprocess.DEVNULL, capture_output=True)
    result = json.loads(out_file.read_text(encoding="utf-8"))
    assert "error" not in result, result["error"]
    return result, int(console_file.read_text(encoding="ascii"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console behaviour")
def test_windowed_parent_chat_opens_no_console_window(tmp_path):
    result, window = _windowed_chat(tmp_path, "default")
    assert result["parent_console"] is False  # pythonw: no console, like AbeltonGod.exe
    assert result["creationflags"] == NO_WINDOW
    assert result["success"] is True and result["reply"] == "Hallo zurück", result
    assert window == 0, f"the CLI got console window {window:#x}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console behaviour")
def test_control_without_the_flag_the_cli_gets_a_console_window(tmp_path):
    """Shows the check above can fail: the SDK's own start from a windowed process gives the
    console CLI a new console window (the bug of #453)."""
    result, window = _windowed_chat(tmp_path, "plain")
    assert result["parent_console"] is False and result["creationflags"] == 0
    assert result["success"] is True, result
    assert window != 0
