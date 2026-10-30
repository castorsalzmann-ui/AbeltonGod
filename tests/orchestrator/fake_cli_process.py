"""Fake Claude Code CLI as a **real process** (bug #176; CI only, no network).

``fake_cli.FakeCLI`` replaces the SDK transport, so the SDK's subprocess handling (start,
initialize, stdin EOF, terminate, kill) never runs in those tests. This script is started by
the real ``SubprocessCLITransport`` instead (the tests run it as ``python fake_cli_process.py``
and skip the SDK's ``-v`` version probe), so a CLI that hangs, never starts or keeps retrying
behaves like a separate process does.

Behaviour comes from environment variables (the SDK passes the parent's environment on):

- ``FAKE_CLI_MODE``:
  - ``silent``: never writes anything, ignores stdin EOF and SIGTERM (a CLI stuck at start);
  - ``exit``: exits at once with code 0 and no output;
  - ``offline``: answers ``initialize``, then for the prompt sends ``init``, a ``status`` frame
    and ``api_retry`` frames without an HTTP status (``error_status: null``), the shape the
    bundled CLI 2.1.310 emitted with the API unreachable (measured on Linux for #176, see the
    PR). Never sends a result; ignores interrupt, stdin EOF and SIGTERM;
  - ``hang``: answers ``initialize`` and sends ``init``, then nothing (no retry frames);
    ignores interrupt, stdin EOF and SIGTERM;
  - ``slow_ok``: answers ``initialize``; ``FAKE_CLI_DELAY`` seconds after the prompt sends
    ``init``, one assistant text and a success result; exits on stdin EOF.
- ``FAKE_CLI_CHILD=1``: first starts a grandchild process that sleeps (a CLI child such as a
  shell or an MCP server); its pid goes to the pid file too.
- ``FAKE_CLI_PIDFILE``: file that gets ``<pid>`` (and ``<child pid>``), one per line.
- ``FAKE_CLI_RETRY_GAP``: seconds between ``api_retry`` frames (default 0.2).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time

ACCOUNT = {"email": "user@example.invalid", "subscriptionType": "Claude Max",
           "apiProvider": "firstParty"}
VERSION = "2.1.310"


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def init_frame() -> dict:
    return {"type": "system", "subtype": "init", "uuid": "u-init", "session_id": "s1",
            "apiKeySource": "none", "tools": [], "mcp_servers": [], "model": "claude-opus-5-5",
            "cwd": ".", "permissionMode": "dontAsk", "slash_commands": [],
            "output_style": "default", "skills": [], "claude_code_version": VERSION}


def sleep_forever() -> None:
    while True:
        time.sleep(3600)


def main() -> None:
    mode = os.environ.get("FAKE_CLI_MODE", "silent")
    pids = [os.getpid()]
    if os.environ.get("FAKE_CLI_CHILD") == "1":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        pids.append(child.pid)
    pidfile = os.environ.get("FAKE_CLI_PIDFILE")
    if pidfile:
        with open(pidfile + ".tmp", "w", encoding="ascii") as fh:
            fh.write("\n".join(str(p) for p in pids) + "\n")
        os.replace(pidfile + ".tmp", pidfile)
    stubborn = mode in ("silent", "offline", "hang")
    if stubborn and hasattr(signal, "SIGTERM") and os.name != "nt":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if mode == "exit":
        sys.exit(0)
    if mode == "silent":
        for _line in sys.stdin:  # read and drop everything, never answer
            pass
        sleep_forever()

    delay = float(os.environ.get("FAKE_CLI_DELAY", "0"))
    gap = float(os.environ.get("FAKE_CLI_RETRY_GAP", "0.2"))

    def answer_prompt() -> None:
        if mode == "offline":
            emit(init_frame())
            emit({"type": "system", "subtype": "status", "status": "requesting",
                  "session_id": "s1", "uuid": "u-status"})
            for attempt in range(1, 11):
                time.sleep(gap)
                emit({"type": "system", "subtype": "api_retry", "attempt": attempt,
                      "max_retries": 10, "retry_delay_ms": int(gap * 1000),
                      "error_status": None, "error": "unknown", "session_id": "s1",
                      "uuid": f"u-retry-{attempt}"})
            sleep_forever()
        if mode == "hang":
            emit(init_frame())
            sleep_forever()
        time.sleep(delay)
        emit(init_frame())
        emit({"type": "assistant", "session_id": "s1", "parent_tool_use_id": None,
              "message": {"id": "msg_1", "model": "claude-opus-5-5",
                          "content": [{"type": "text", "text": "Hallo zurück"}],
                          "usage": {"output_tokens": 3, "input_tokens": 5}}})
        emit({"type": "result", "subtype": "success", "is_error": False, "duration_ms": 1,
              "duration_api_ms": 1, "num_turns": 1, "session_id": "s1",
              "total_cost_usd": 0.01, "usage": {"output_tokens": 3, "input_tokens": 5},
              "result": "Hallo zurück"})

    for line in sys.stdin:
        if not line.strip():
            continue
        msg = json.loads(line)
        if msg.get("type") == "control_request":
            sub = msg["request"].get("subtype")
            if sub == "interrupt" and stubborn:
                continue  # a CLI that does not react any more
            response = {}
            if sub == "initialize":
                response = {"commands": [], "account": ACCOUNT, "claude_code_version": VERSION}
            emit({"type": "control_response", "response": {
                "subtype": "success", "request_id": msg["request_id"], "response": response}})
        elif msg.get("type") == "user":
            threading.Thread(target=answer_prompt, daemon=True).start()
    if stubborn:
        sleep_forever()


if __name__ == "__main__":
    main()
