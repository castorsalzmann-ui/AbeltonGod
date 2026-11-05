"""Smoke test of a built AbeltonGod.exe (run by .github/workflows/build-exe.yml, #401).

    python scripts/exe_smoke.py <path-to-exe> [check ...]

Checks: version, help, unknown, kick, goa, menu, determinism (default: all). Each check prints
one PASS/FAIL line with the evidence; the exit code is 1 if any failed. The determinism check
renders the same kick and the same goa_arrangement through the exe and through
``python -m audio_engine.<module>`` and compares SHA-256 of the WAV / MID bytes.

This only proves the exe runs on the machine that runs this script. It touches nothing in Live.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

TIMEOUT = 300
KICK = ["--preset", "centre", "--seed", "7"]
GOA = ["--seed", "3", "--no-samples"]


def run(cmd: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=TIMEOUT, check=False)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def one(folder: Path, pattern: str) -> Path:
    found = sorted(folder.glob(pattern))
    if len(found) != 1:
        raise AssertionError(f"expected exactly one {pattern} in {folder}, found {found}")
    return found[0]


def check_version(exe: str) -> str:
    r = run([exe, "--version"])
    assert r.returncode == 0 and r.stdout.startswith("AbeltonGod "), (r.returncode, r.stdout)
    assert "git unknown" not in r.stdout, r.stdout
    return r.stdout.strip()


def check_help(exe: str) -> str:
    r = run([exe, "--help"])
    assert r.returncode == 0, (r.returncode, r.stderr)
    for name in ("kick", "hat", "snare", "clap", "rim", "bass", "goa-arrangement",
                 "goa-melody", "live-import", "chat"):
        assert name in r.stdout, f"{name} missing from --help"
    # every tool's own --help must load its module inside the bundle
    for tool in ("kick", "goa-arrangement", "goa-melody", "live-import", "bridge-check", "chat",
                 "plan", "als-inspect"):
        t = run([exe, tool, "--help"])
        assert t.returncode == 0, f"{tool} --help exit {t.returncode}: {t.stderr[-500:]}"
    return "--help and --help of 8 tools ok"


def check_unknown(exe: str) -> str:
    r = run([exe, "no-such-tool"])
    assert r.returncode == 2 and "kick" in r.stderr, (r.returncode, r.stderr)
    return "exit 2 with the tool list"


def check_kick(exe: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        r = run([exe, "kick", *KICK, "--out", tmp])
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        wav = one(Path(tmp), "*.wav")
        assert wav.stat().st_size > 1000, wav.stat().st_size
        one(Path(tmp), "*.json")
        return f"{wav.name} {wav.stat().st_size} bytes"


def check_goa(exe: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "goa"
        r = run([exe, "goa-arrangement", *GOA, "--out", str(out)])
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        mid = one(out, "*.mid")
        one(out, "*.md")
        return f"{mid.name} {mid.stat().st_size} bytes"


def check_menu(exe: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "menu-out"
        r = run([exe], stdin=f"kick\n{out}\n--seed 7\n\n")
        assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
        assert "Fertig (Exit-Code 0)" in r.stdout, r.stdout
        wav = one(out, "*.wav")
        return f"menu with piped stdin wrote {wav.name}"


def check_determinism(exe: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "exe_kick", Path(tmp) / "py_kick"
        for cmd in ([exe, "kick"], [sys.executable, "-m", "audio_engine.kick"]):
            out = a if cmd[0] == exe else b
            r = run([*cmd, *KICK, "--out", str(out)])
            assert r.returncode == 0, (cmd, r.returncode, r.stdout, r.stderr)
        ha, hb = sha(one(a, "*.wav")), sha(one(b, "*.wav"))
        assert ha == hb, f"kick differs: exe {ha} python {hb}"
        c, d = Path(tmp) / "exe_goa", Path(tmp) / "py_goa"
        for cmd in ([exe, "goa-arrangement"], [sys.executable, "-m",
                                               "audio_engine.goa_arrangement"]):
            out = c if cmd[0] == exe else d
            r = run([*cmd, *GOA, "--out", str(out)])
            assert r.returncode == 0, (cmd, r.returncode, r.stdout, r.stderr)
        hc, hd = sha(one(c, "*.mid")), sha(one(d, "*.mid"))
        assert hc == hd, f"goa mid differs: exe {hc} python {hd}"
        return f"kick wav sha256 {ha[:16]}..., goa mid sha256 {hc[:16]}... equal to python -m"


CHECKS: dict[str, Callable[[str], str]] = {
    "version": check_version, "help": check_help, "unknown": check_unknown,
    "kick": check_kick, "goa": check_goa, "menu": check_menu,
    "determinism": check_determinism,
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    exe, names = args[0], args[1:] or list(CHECKS)
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        print(f"unknown check(s): {unknown}; available: {list(CHECKS)}")
        return 2
    failed = 0
    for name in names:
        try:
            print(f"PASS {name}: {CHECKS[name](exe)}", flush=True)
        except (AssertionError, subprocess.SubprocessError, OSError) as exc:
            failed += 1
            print(f"FAIL {name}: {exc}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
