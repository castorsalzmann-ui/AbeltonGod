"""Regression for #176: the chat seemed to hang when Claude was unreachable (network off).

User's run (Windows, 2026-10-30, main f7ca895, Max login, WLAN off): ``python -m
orchestrator.chat --project ...``, typed ``Hallo``; nothing more was printed and the console
took no input until the window was closed (waited at least ~1 minute).

What the real CLI does offline (bundled Claude Code 2.1.310, Linux build, run for #176 with
the API address unreachable, no request reached Anthropic): it answers ``initialize`` at once,
sends ``init``, then retries the API call 10 times with growing pauses and reports each retry
as a ``system``/``api_retry`` frame with ``error_status: null``; the error result came after
~190 s. Before the fix the client ignored those frames and waited for the request deadline
(profile ``timeout_s`` 90 s, plus 5 s grace), then closed the CLI gracefully (interrupt, stdin
EOF, up to ~20 s more), all without any output; the main thread sat in one long
``Future.result`` wait, so nobody read the console. Whether the request would have ended on
the user's machine is **not established** (the window was closed first).

These tests start ``fake_cli_process.py`` as a real process through the SDK's own
``SubprocessCLITransport`` (CI only, no network, no model call). The fake CLIs ignore
interrupts, stdin EOF and SIGTERM, so only a hard kill ends them. ``before_fix`` (origin/main
f2c3e4b... see the PR): every case below except ``slow_ok`` and ``exit`` failed on time or on a
still-running process.
"""

from __future__ import annotations

import _thread
import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "orchestrator"))

from claude_agent_sdk._internal.transport.subprocess_cli import (  # noqa: E402
    SubprocessCLITransport,
)
from orch_helpers import Events, SpyGuard, make_policy  # noqa: E402

from orchestrator.auth import AuthMode, AuthSettings  # noqa: E402
from orchestrator.loop import Orchestrator  # noqa: E402
from orchestrator.sdk_client import SdkModelClient  # noqa: E402
from orchestrator.tools import Toolbox  # noqa: E402

FAKE = ROOT / "tests" / "orchestrator" / "fake_cli_process.py"


@pytest.fixture(name="cli")
def cli_fixture(monkeypatch, tmp_path):
    """Run the fake CLI as ``python fake_cli_process.py <SDK arguments>``; yield a helper
    that sets its mode and reads its pid file. Every process it reports is killed at the end,
    so a failing test leaves nothing running."""
    original = SubprocessCLITransport._build_command

    def build(self):
        return [sys.executable, *original(self)]

    monkeypatch.setattr(SubprocessCLITransport, "_build_command", build)
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    pidfile = tmp_path / "pids.txt"
    monkeypatch.setenv("FAKE_CLI_PIDFILE", str(pidfile))
    clients: list[SdkModelClient] = []

    class Cli:
        def mode(self, mode: str, **env: str) -> None:
            monkeypatch.setenv("FAKE_CLI_MODE", mode)
            for key, value in env.items():
                monkeypatch.setenv(key, value)

        def client(self, **kwargs) -> SdkModelClient:
            made = SdkModelClient(
                AuthSettings(AuthMode.SUBSCRIPTION, "claude-opus-5-5", api_key_present=False),
                per_call_estimate_usd=0.01, cli_path=str(FAKE), **kwargs)
            clients.append(made)
            return made

        def pids(self, wait_s: float = 10.0) -> list[int]:
            until = time.monotonic() + wait_s
            while not pidfile.exists():
                if time.monotonic() > until:
                    raise AssertionError("the fake CLI never started")
                time.sleep(0.02)
            return [int(p) for p in pidfile.read_text(encoding="ascii").split()]

    yield Cli()
    for client in clients:
        client.close()
    if pidfile.exists():
        for pid in (int(p) for p in pidfile.read_text(encoding="ascii").split()):
            if alive(pid):
                kill(pid)


def alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)  # QUERY_LIMITED | SYNC
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A killed child that nobody reaped yet is a zombie: dead for our purpose.
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
    except OSError:
        pass


def wait_dead(pids: list[int], within_s: float = 3.0) -> list[int]:
    until = time.monotonic() + within_s
    while True:
        living = [p for p in pids if alive(p)]
        if not living or time.monotonic() > until:
            return living
        time.sleep(0.05)


def guard(tmp_path, timeout_s: float) -> SpyGuard:
    # Real clock: these tests measure wall time.
    return SpyGuard(make_policy(timeout_s=timeout_s), log_path=tmp_path / "usage.jsonl",
                    events=Events())


def handle(client, g, text="Hallo"):
    start = time.monotonic()
    out = Orchestrator(g, client, Toolbox(), profile="p").handle(text)
    return out, time.monotonic() - start


def test_offline_cli_fails_fast_with_a_clear_message(cli, tmp_path):
    """The CLI's retry frames without an HTTP status end the request within seconds."""
    cli.mode("offline")
    client = cli.client()
    out, took = handle(client, guard(tmp_path, timeout_s=30))
    assert out.success is False and out.error == "model_unreachable", out
    assert took < 8.0, f"took {took:.1f} s (deadline 30 s)"
    assert "nicht erreichbar" in out.message_de
    assert "Internetverbindung" in out.message_de
    assert "Es wurde nichts geändert" in out.message_de
    assert wait_dead(cli.pids()) == []


def test_cli_that_never_answers_is_killed_at_the_deadline(cli, tmp_path):
    """No retry frames, no answer: the request ends at its own deadline (not deadline + the
    SDK's graceful close), the message names the wait, the process is gone."""
    cli.mode("hang")
    out, took = handle(cli.client(), guard(tmp_path, timeout_s=5))  # policy minimum
    assert out.success is False and out.error == "model_unreachable", out
    assert took < 5 + 2.0, f"took {took:.1f} s (deadline 5 s)"
    assert "keine Antwort nach 5 s" in out.message_de, out.message_de
    assert "Internetverbindung" in out.message_de
    assert "Es wurde nichts geändert" in out.message_de
    assert wait_dead(cli.pids()) == []


def test_cli_that_never_starts_is_killed(cli, tmp_path):
    """The process runs but never answers ``initialize``."""
    cli.mode("silent")
    out, took = handle(cli.client(), guard(tmp_path, timeout_s=5))
    assert out.success is False and out.error == "model_unreachable", out
    assert took < 5 + 2.0, f"took {took:.1f} s (deadline 5 s)"
    assert wait_dead(cli.pids()) == []


def test_cli_that_exits_without_output_is_unavailable(cli, tmp_path):
    """Before the fix the exit was only noticed at the request deadline."""
    cli.mode("exit")
    out, took = handle(cli.client(), guard(tmp_path, timeout_s=10))
    assert out.success is False and out.error == "model_unavailable", out
    assert took < 4.0, f"took {took:.1f} s (deadline 10 s)"
    assert "nicht erreichbar" in out.message_de and "exit code 0" in out.message_de


def test_children_of_the_cli_are_killed_too(cli, tmp_path):
    """A CLI that started a child (shell, MCP server): the whole tree goes (Windows:
    ``taskkill /T``; Linux: the descendants read from /proc)."""
    cli.mode("offline", FAKE_CLI_CHILD="1")
    out, _ = handle(cli.client(), guard(tmp_path, timeout_s=30))
    assert out.success is False
    pids = cli.pids()
    assert len(pids) == 2
    assert wait_dead(pids) == []


def test_slow_answer_within_the_limit_still_succeeds(cli, tmp_path):
    cli.mode("slow_ok", FAKE_CLI_DELAY="1.5")
    out, took = handle(cli.client(), guard(tmp_path, timeout_s=20))
    assert out.success is True, out
    assert out.reply == "Hallo zurück"
    assert took >= 1.5


def test_ctrl_c_while_waiting_ends_the_request_at_once(cli, tmp_path):
    """Ctrl+C is modelled with ``_thread.interrupt_main``: like a console Ctrl+C on Windows
    before Python 3.14 (gh-125541), it does not wake a thread blocked in a lock wait, so the
    client must wait in short slices. The request ends as failed, the CLI is killed, and the
    chat can go on."""
    assert threading.current_thread() is threading.main_thread()
    cli.mode("hang")
    client = cli.client()
    timer = threading.Timer(1.0, _thread.interrupt_main)
    timer.start()
    try:
        out, took = handle(client, guard(tmp_path, timeout_s=20))
    finally:
        timer.cancel()
    assert out.success is False and out.error == "interrupted", out
    assert took < 1.0 + 2.0, f"took {took:.1f} s"
    assert "Abgebrochen" in out.message_de and "Es wurde nichts geändert" in out.message_de
    assert wait_dead(cli.pids()) == []
    # the next request works again
    cli.mode("slow_ok", FAKE_CLI_DELAY="0")
    again, _ = handle(client, guard(tmp_path, timeout_s=20))
    assert again.success is True, again
