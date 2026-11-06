"""Cockpit builder (#236): output of a good run, fail-closed paths, and the shim API.

The collector is replaced by a fake that writes small datasets; the real collector needs
GitHub and runs the whole gate. The shim is run under node (skipped if node is missing).
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

QA = Path(__file__).resolve().parents[2] / "scripts" / "qa"
BUILD = QA / "cockpit_build.py"
SHIM = QA / "cockpit_page" / "shim.js"

FAKE = textwrap.dedent(
    """
    import json, sys, os
    from datetime import datetime, timedelta, UTC
    from pathlib import Path
    out = Path(sys.argv[2]); out.mkdir(parents=True)
    mode = os.environ.get("FAKE_MODE", "ok")
    Path(os.environ["FAKE_LOG"]).write_text(json.dumps(
        {"argv": sys.argv[3:], "skip": os.environ.get("COCKPIT_SKIP_GATE")}))
    if mode == "crash":
        sys.exit(1)
    age = timedelta(hours=3) if mode == "stale" else timedelta(0)
    row = [{"x": 1}]
    names = "features research issues prs gate phases pipeline capabilities user_actions"
    names += " active_work"
    for n in names.split():
        rows = [] if (mode == "empty" and n == "features") else row
        (out / f"{n}.json").write_text(json.dumps(rows))
    ua = [{"kind": "PR", "url": "https://github.com/x/y/pull/1", "state": "open"}]
    (out / "user_actions.json").write_text(json.dumps(ua))
    at = (datetime.now(UTC) - age).isoformat(timespec="seconds")
    (out / "snapshot.json").write_text(json.dumps([{"at": at, "sha": "abc1234"}]))
    """
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    g = ["git", "-c", "user.email=a@b", "-c", "user.name=t"]
    subprocess.run([*g, "init", "-q"], cwd=repo, check=True)
    (repo / "f").write_text("x")
    subprocess.run([*g, "add", "f"], cwd=repo, check=True)
    subprocess.run([*g, "commit", "-qm", "c"], cwd=repo, check=True)
    fake = tmp_path / "fake_collect.py"
    fake.write_text(FAKE)

    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "log.json"))

    def build(mode: str, out: Path, *extra: str):
        monkeypatch.setenv("FAKE_MODE", mode)
        return subprocess.run(
            [sys.executable, str(BUILD), str(out), "--repo", str(repo), "--collector", str(fake),
             *extra],
            capture_output=True, text=True,
        )

    return build


def test_good_build_writes_site(env, tmp_path):
    out = tmp_path / "site"
    r = env("ok", out)
    assert r.returncode == 0, r.stderr
    html = (out / "index.html").read_text(encoding="utf-8")
    for tab in ("overview", "roadmap", "research", "work", "quality"):
        assert f'id="{tab}"' in html
    assert "window.dash" in html and "COCKPIT_DATA" in html and 'id="age_banner"' in html
    snap = json.loads((out / "data" / "snapshot.json").read_text())
    assert snap[0]["sha"] == "abc1234"
    assert "data_at" in json.loads((out / "snapshot.json").read_text())


@pytest.mark.parametrize("mode", ["crash", "empty", "stale"])
def test_failure_writes_nothing(env, tmp_path, mode):
    out = tmp_path / "site"
    r = env(mode, out)
    assert r.returncode == 1
    assert not out.exists()


def test_no_gate_needs_previous_gate(env, tmp_path):
    out = tmp_path / "site"
    r = env("ok", out, "--no-gate", "--prev-gate-url", (tmp_path / "missing.json").as_uri())
    assert r.returncode == 1 and not out.exists()
    assert "WARNING no previous gate.json" in r.stderr


def test_no_gate_passes_previous_gate_and_flag(env, tmp_path):
    prev = tmp_path / "gate.json"
    prev.write_text(json.dumps([{"run": "x", "date": "2026-01-01T00:00:00+00:00"}]))
    out = tmp_path / "site"
    r = env("ok", out, "--no-gate", "--prev-gate-url", prev.as_uri())
    assert r.returncode == 0, r.stderr
    log = json.loads((tmp_path / "log.json").read_text())
    assert log["skip"] == "1" and log["argv"][-1].endswith("prev_gate.json")


def test_unreachable_site_warns_but_builds_with_gate(env, tmp_path):
    out = tmp_path / "site"
    r = env("ok", out, "--prev-gate-url", (tmp_path / "missing.json").as_uri())
    assert r.returncode == 0 and "WARNING" in r.stderr


NODE = shutil.which("node")

# The first node start on a fresh Windows CI runner is slow, later starts are not (#459):
# the first `node -e 0` took 15.7 s and the second 0.07 s on one runner; the first script
# reached its first line after 1.4-4.0 s on four others, and three runs (13:49-13:55,
# 2026-11-06) passed 30 s. The shim's own work after that first line took 2-35 ms. So
# start-up and the shim get separate deadlines: a generous one until the script's first
# line runs, and the old 30 s for the shim work after it.
NODE_START_S = 120.0
SHIM_RUN_S = 30.0
READY = "__node_ready__"


def run_node(script: Path, start_s: float = NODE_START_S, run_s: float = SHIM_RUN_S):
    """Run ``node script``; return (stdout, stderr). The script must write
    ``READY`` + newline to stderr as its first statement. Fails the test, naming the phase,
    if node does not reach that line within ``start_s`` or does not exit ``run_s`` after it."""
    t0 = time.perf_counter()
    p = subprocess.Popen([NODE, str(script)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines: queue.Queue = queue.Queue()
    out: list[str] = []

    def pump_stderr():
        for line in p.stderr:
            lines.put(line)

    readers = [threading.Thread(target=pump_stderr, daemon=True),
               threading.Thread(target=lambda: out.append(p.stdout.read()), daemon=True)]
    for t in readers:
        t.start()
    err: list[str] = []
    try:
        while READY not in "".join(err):
            left = start_s - (time.perf_counter() - t0)
            try:
                err.append(lines.get(timeout=max(left, 0)))
            except queue.Empty:
                pytest.fail(f"node did not reach the script's first line within {start_s} s "
                            f"(start-up, not the shim; #459); stderr so far: {''.join(err)!r}")
        started = time.perf_counter() - t0
        try:
            p.wait(timeout=run_s)
        except subprocess.TimeoutExpired:
            pytest.fail(f"node started after {started:.1f} s, then did not finish within "
                        f"{run_s} s (the shim script hangs)")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    for t in readers:
        t.join(run_s)
    while not lines.empty():
        err.append(lines.get())
    stderr = "".join(err).replace(READY + "\n", "", 1)
    assert p.returncode == 0, stderr
    return "".join(out), stderr


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize(
    ("body", "start_s", "run_s", "phase"),
    [
        # never reaches its first line in time: start-up phase
        (f"setTimeout(() => process.stderr.write('{READY}\\n'), 60000);", 1.0, 30.0, "start-up"),
        # starts, then never exits: shim phase (generous start deadline, short run deadline,
        # the run deadline is the subject here)
        (f"process.stderr.write('{READY}\\n'); setInterval(() => {{}}, 1000);",
         NODE_START_S, 1.0, "the shim script hangs"),
    ],
    ids=["slow-start", "hang-after-start"],
)
def test_run_node_names_the_phase_that_timed_out(tmp_path, body, start_s, run_s, phase):
    f = tmp_path / "h.js"
    f.write_text(body)
    with pytest.raises(pytest.fail.Exception, match=phase):
        run_node(f, start_s=start_s, run_s=run_s)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_shim_api(tmp_path):
    """data, calc (incl. calc of calc), onData, data-source binding, fetch + file:// fallback."""
    js = textwrap.dedent(
        f"""
        process.stderr.write('{READY}\\n');
        const fs = require('fs');
        const served = {{ nums: [{{n: 1, s: 'a'}}, {{n: 2, s: 'b'}}] }};
        const el = (attrs) => ({{dataset: attrs, textContent: ''}});
        const bound = el({{source: 'second', field: 'n', row: '0', where: 's=b'}});
        global.document = {{ querySelectorAll: () => [bound] }};
        global.window = global;
        global.COCKPIT_DATA = {{ only_embedded: [{{v: 7}}] }};
        global.fetch = async (u) => {{
          const id = u.replace('data/', '').replace('.json', '');
          if (!(id in served)) return {{ok: false, status: 404}};
          return {{ok: true, json: async () => served[id]}};
        }};
        eval(fs.readFileSync({json.dumps(str(SHIM))}, 'utf8'));
        dash.calc('doubled', {{inputs: ['nums'],
          fn: (r) => r.map((x) => ({{n: x.n * 2, s: x.s}}))}});
        dash.calc('second', {{inputs: ['doubled'], fn: (r) => r.slice(1)}});
        let calls = 0;
        const first = dash.data('nums');
        if (first.status !== 'loading') throw new Error('expected loading');
        dash.onData(() => {{
          calls++;
          const d = dash.data('second'), e = dash.data('only_embedded'), m = dash.data('nope');
          if (d.status === 'ok' && e.status === 'ok' && m.status === 'error') {{
            setTimeout(() => {{
              console.log(JSON.stringify({{d: d.data, e: e.data, bound: bound.textContent}}));
            }}, 0);
          }}
        }});
        """
    )
    f = tmp_path / "t.js"
    f.write_text(js)
    stdout, _stderr = run_node(f)
    got = json.loads(stdout.strip().splitlines()[0])
    assert got == {"d": [{"n": 4, "s": "b"}], "e": [{"v": 7}], "bound": "4"}
