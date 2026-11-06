"""TEMPORARY debug probe for #459 (never merged): where does node spend time on Windows CI?

Reports via warnings (visible in the CI summary): node boot time (performance.now at the
first script line), time to process exit, time to stdout/stderr EOF, exit code, and which
handle the worker's STD_INPUT_HANDLE is (and whether GetFileType on it blocks).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import warnings

import pytest

NODE = shutil.which("node")
JS = (
    "process.stderr.write('boot_ms=' + performance.now().toFixed(1) + '\\n');"
    "process.on('exit', () => process.stderr.write('exit_ms=' + performance.now().toFixed(1)"
    " + '\\n'));"
    "console.log('ok')"
)
DEADLINE = 35.0


def handle_info() -> str:
    if os.name != "nt":
        return "posix"
    import _winapi
    import ctypes
    import msvcrt

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetFileType.argtypes = [ctypes.c_void_p]
    k32.GetFileType.restype = ctypes.c_uint32
    parts = []
    for fd, code in ((0, _winapi.STD_INPUT_HANDLE), (1, _winapi.STD_OUTPUT_HANDLE),
                     (2, _winapi.STD_ERROR_HANDLE)):
        h = _winapi.GetStdHandle(code)
        try:
            fdh = msvcrt.get_osfhandle(fd)
        except OSError:
            fdh = None
        res: dict = {}

        def q(h=h, res=res):
            t = time.perf_counter()
            res["type"] = k32.GetFileType(h) if h else None
            res["ms"] = round((time.perf_counter() - t) * 1000, 1)

        th = threading.Thread(target=q, daemon=True)
        th.start()
        th.join(2.0)
        typ = f"{res['type']}({res['ms']}ms)" if "type" in res else "BLOCKED>2s"
        parts.append(f"{fd}: std={h} fd_os={fdh} type={typ}")
    return "; ".join(parts)


def run(cmd, stdin) -> dict:
    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True)
    out: dict = {}
    eof: dict = {}

    def rd(name, stream):
        out[name] = stream.read()
        eof[name] = round(time.perf_counter() - t0, 3)

    for name, stream in (("o", p.stdout), ("e", p.stderr)):
        threading.Thread(target=rd, args=(name, stream), daemon=True).start()
    t_exit = None
    while time.perf_counter() - t0 < DEADLINE:
        if t_exit is None and p.poll() is not None:
            t_exit = round(time.perf_counter() - t0, 3)
        if t_exit is not None and len(eof) == 2:
            break
        time.sleep(0.005)
    killed = False
    if p.poll() is None:
        p.kill()
        killed = True
        p.wait()
    return {"exit_s": t_exit, "rc": p.returncode, "killed": killed, "eof": dict(eof),
            "stderr": (out.get("e") or "").strip().replace("\n", " | ")[:300]}


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("copy", range(16))
@pytest.mark.parametrize("stdin", ["inherit", "devnull"])
def test_node_probe(copy, stdin):
    info = handle_info()
    r = run([NODE, "-e", JS], None if stdin == "inherit" else subprocess.DEVNULL)
    worker = os.environ.get("PYTEST_XDIST_WORKER", "-")
    warnings.warn(
        f"PROBE459 worker={worker} wall={time.strftime('%H:%M:%S')} stdin={stdin} copy={copy}"
        f" result={r} handles=[{info}]",
        stacklevel=1,
    )
