"""One chat request from a process without a console (#453; started by test_cli_spawn.py).

Run as ``pythonw.exe windowed_chat_probe.py <out.json> <console python.exe> <default|plain>``:
``pythonw.exe`` is a windowed program like ``AbeltonGod.exe``, so this process has no
console. It sends "Hallo" through the real ``SdkModelClient`` and the SDK's own
``SubprocessCLITransport`` to ``fake_cli_process.py``, which runs under the console program
``python.exe`` (console subsystem, like ``claude.exe``) and writes the console window it got
to ``FAKE_CLI_CONSOLEFILE``. ``plain`` forces ``creationflags=0`` (the SDK's own start, the
behaviour before #453) as the control. The outcome goes to ``out.json``: a windowed process
has no console to print to.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(HERE)]


def main() -> dict:
    out_path, python_exe, mode = sys.argv[1:4]
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
    from orch_helpers import Events, SpyGuard, make_policy

    from orchestrator.auth import AuthMode, AuthSettings
    from orchestrator.loop import Orchestrator
    from orchestrator.sdk_client import SdkModelClient, parent_has_console
    from orchestrator.tools import Toolbox

    original = SubprocessCLITransport._build_command
    SubprocessCLITransport._build_command = lambda self: [python_exe, *original(self)]
    os.environ["CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK"] = "1"
    os.environ["FAKE_CLI_MODE"] = "slow_ok"
    os.environ["FAKE_CLI_DELAY"] = "0"
    extra = {"creationflags": 0} if mode == "plain" else {}
    client = SdkModelClient(
        AuthSettings(AuthMode.SUBSCRIPTION, "claude-opus-5-5", api_key_present=False),
        per_call_estimate_usd=0.01, cli_path=str(HERE / "fake_cli_process.py"), **extra)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            guard = SpyGuard(make_policy(timeout_s=60), log_path=Path(tmp) / "usage.jsonl",
                             events=Events())
            out = Orchestrator(guard, client, Toolbox(), profile="p").handle("Hallo")
    finally:
        client.close()
    return {"parent_console": parent_has_console(), "creationflags": client.creationflags,
            "success": out.success, "reply": out.reply, "message": out.message_de}


if __name__ == "__main__":
    try:
        result = main()
    except BaseException:  # noqa: BLE001 - reported to the test, which fails on it
        result = {"error": traceback.format_exc()}
    Path(sys.argv[1]).write_text(json.dumps(result), encoding="utf-8")
