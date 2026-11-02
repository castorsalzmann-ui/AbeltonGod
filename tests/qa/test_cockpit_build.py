"""Cockpit builder (#236): output of a good run, fail-closed paths, and the shim API.

The collector is replaced by a fake that writes small datasets; the real collector needs
GitHub and runs the whole gate. The shim is run under node (skipped if node is missing).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
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

    def build(mode: str, out: Path):
        monkeypatch.setenv("FAKE_MODE", mode)
        return subprocess.run(
            [sys.executable, str(BUILD), str(out), "--repo", str(repo), "--collector", str(fake)],
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


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_shim_api(tmp_path):
    """data, calc (incl. calc of calc), onData, data-source binding, fetch + file:// fallback."""
    js = textwrap.dedent(
        f"""
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
    r = subprocess.run([NODE, str(f)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[0])
    assert got == {"d": [{"n": 4, "s": "b"}], "e": [{"v": 7}], "bound": "4"}
