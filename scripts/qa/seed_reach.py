"""Does ``--fresh-seeds`` reach a test's random inputs? Checked by behaviour, not by text (#119).

Runs pytest twice on the same selection, at ``--fresh-seeds=0`` and ``--fresh-seeds=N``, in
two parallel processes with the probe plugin ``tests/support/seed_probe.py``, and compares:

- **Seedings.** Every RNG seeding made by test code (module level, parametrize, and the test
  bodies that were run), keyed by source line and phase. A key whose fresh-N seeds share a
  value with its fresh-0 seeds is *unshifted*: that stream ignores ``--fresh-seeds``. Phases
  are matched by test function and parametrize index, because drawn values in test ids
  change the node ids.
- **Parametrize values.** Every parametrized item, paired by test function and index; the
  report lists which argument values changed.

    python scripts/qa/seed_reach.py tests/audio_engine/test_kick.py
    python scripts/qa/seed_reach.py --run tests/library/test_layout.py   # bodies too
    python scripts/qa/seed_reach.py --run --fresh 3 -n 4 tests            # whole-suite audit

Without ``--run`` only collection is done (module-level and parametrize seedings). With
``--run`` the selected tests are executed too (pass ``-n <k>`` to spread them over xdist
workers). Exit code 1 if any seeding outside :data:`INDEPENDENT` is unshifted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Seedings that ignore --fresh-seeds on purpose (path prefix -> reason).
INDEPENDENT = {
    "tests/qa/test_render_cache.py": (
        "_draw is the render cache's own input generator: the cache tests must not depend on "
        "the shared generator they could otherwise hide a fault in, and their fixed inputs "
        "keep the cache hit/miss counts reproducible (#77)"),
    "tests/qa/test_kick_params.py": (
        "pins the shared generator against the former copies and checks the shift itself: "
        "its reference streams must stay the unshifted random.Random / default_rng ones"),
}


def probe(selection: list[str], fresh: int, run: bool = False, *, run_only: list[str] = (),
          root: Path = ROOT, extra: list[str] = (), timeout: float = 900) -> dict:
    """One pytest process with the probe in ``root``; returns the merged probe records.

    ``src`` and ``tests`` of this repo are on the path (the probe and ``support`` come from
    here even when ``root`` is another tree, e.g. a planted one)."""
    # basetemp inside the tree, like the default ``.pytest_tmp`` (tests/library/test_project.py
    # relies on tmp_path lying inside the checkout); own folder per process, removed after.
    basetemp = root / ".pytest_tmp" / f"seed_probe-{fresh}-{os.getpid()}"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "probe"
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests")]),
            "SEED_PROBE_OUT": str(out),
            "SEED_PROBE_RUN": ",".join(run_only),
        }
        env.pop("PYTEST_XDIST_WORKER", None)
        cmd = [
            sys.executable, "-m", "pytest", "-p", "support.seed_probe", "-p", "no:cacheprovider",
            "-o", "pythonpath=src", "-q", f"--fresh-seeds={fresh}",
            f"--basetemp={basetemp}",
        ]
        if not (run or run_only):
            cmd.append("--collect-only")
        if "-n" not in extra and not any(a.startswith("-n") for a in extra):
            cmd += ["-n", "0"]
        cmd += [*extra, *selection]
        try:
            proc = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True,
                                  timeout=timeout)
        finally:
            shutil.rmtree(basetemp, ignore_errors=True)
        files = sorted(Path(tmp).glob("probe.*.json"))
        # 1 = some tests failed: their seedings were still recorded (the caller sees "exit").
        if proc.returncode not in (0, 1, 5) or not files:
            raise RuntimeError(f"probe run failed (exit {proc.returncode}, {len(files)} files):\n"
                               f"{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
        return merge([json.loads(f.read_text(encoding="utf-8")) for f in files]) | {
            "exit": proc.returncode, "fresh": fresh}


def merge(docs: list[dict]) -> dict:
    """xdist: every worker collects everything, so collection records repeat per worker."""
    params: dict[tuple[str, int], dict] = {}
    for d in docs:
        for p in d["params"]:
            params.setdefault((p["function"], p["index"]), p)
    seeds, seen_collect = [], False
    skipped = sorted({n for d in docs for n in d.get("skipped", [])})
    for d in docs:
        collect = [s for s in d["seeds"] if s["phase"] == "collect"]
        if collect and not seen_collect:
            seeds += collect
            seen_collect = True
        seeds += [s for s in d["seeds"] if s["phase"] != "collect"]
    return {"params": [params[k] for k in sorted(params)], "seeds": seeds, "skipped": skipped}


def probe_pair(selection: list[str], fresh: int = 1, **kw) -> tuple[dict, dict]:
    """The fresh-0 and fresh-N probes, run in parallel."""
    if fresh < 1:
        raise ValueError("compare against a fresh value >= 1")
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.map(lambda n: probe(selection, n, **kw), (0, fresh))
    return a, b


def _phase_key(probe_doc: dict) -> dict[str, str]:
    """node id -> 'function#index' for parametrized items (their ids may hold drawn values)."""
    out = {}
    for p in probe_doc["params"]:
        out[f"{p['function']}[{p['id']}]"] = f"{p['function']}#{p['index']}"
    return out


def seed_table(probe_doc: dict) -> dict[tuple[str, str], list]:
    keys = _phase_key(probe_doc)
    table: dict[tuple[str, str], list] = defaultdict(list)
    for s in probe_doc["seeds"]:
        table[(s["where"], keys.get(s["phase"], s["phase"]))].append(s["seed"])
    return dict(table)


def compare_seeds(a: dict, b: dict) -> dict[str, dict]:
    """Per seeding key: ``unshifted`` (shared seed values), ``only_in`` and ``unseeded``."""
    ta, tb = seed_table(a), seed_table(b)
    out: dict[str, dict] = {}
    for key in sorted(set(ta) | set(tb)):
        sa, sb = ta.get(key, []), tb.get(key, [])
        entry: dict = {"n0": len(sa), "n1": len(sb)}
        if key not in ta or key not in tb:
            entry["only_in"] = "fresh 0" if key in ta else "fresh N"
        common = {s for s in sa if s is not None} & {s for s in sb if s is not None}
        if common:
            entry["unshifted"] = sorted(common, key=repr)[:5]
        if None in sa or None in sb:
            entry["unseeded"] = True
        out[f"{key[0]} @ {key[1]}"] = entry
    return out


def compare_params(a: dict, b: dict) -> dict[tuple[str, int], dict]:
    """Per (function, index): the argument names whose value changed, and both ids."""
    pb = {(p["function"], p["index"]): p for p in b["params"]}
    out = {}
    for p in a["params"]:
        key = (p["function"], p["index"])
        q = pb.get(key)
        if q is None:
            out[key] = {"id0": p["id"], "id1": None, "changed": None}
            continue
        changed = sorted(n for n in p["params"] if p["params"][n] != q["params"].get(n))
        out[key] = {"id0": p["id"], "id1": q["id"], "changed": changed}
    for key, q in pb.items():
        out.setdefault(key, {"id0": None, "id1": q["id"], "changed": None})
    return out


def stuck(changes: dict[tuple[str, int], dict], spec: dict[str, tuple[str, str]]) -> dict:
    """Random-derived parametrize values that did not change.

    ``spec`` maps a test function to ``(argument, id regex)``: the cases whose id fully matches
    are drawn, so ``argument`` must change. A function without any matching case is reported
    too (renamed test or changed ids: the spec no longer checks anything there)."""
    out = {}
    for fn, (arg, ids) in spec.items():
        drawn = [v for (f, _), v in changes.items()
                 if f == fn and re.fullmatch(ids, v["id0"] or "")]
        bad = [v["id0"] for v in drawn if not v["changed"] or arg not in v["changed"]]
        if not drawn:
            out[fn] = f"no case with an id matching {ids!r}"
        elif bad:
            out[fn] = bad
    return out


def independent(where: str) -> str | None:
    for prefix, why in INDEPENDENT.items():
        if where.startswith(prefix):
            return why
    return None


def unshifted(seeds: dict[str, dict]) -> dict[str, dict]:
    return {k: v for k, v in seeds.items() if "unshifted" in v and not independent(k)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fresh", type=int, default=1, help="fresh-seeds value to compare with 0")
    ap.add_argument("--run", action="store_true", help="also run the tests (body seedings)")
    ap.add_argument("-n", default="0", help="xdist workers inside each probe run")
    ap.add_argument("selection", nargs="+", help="pytest paths / node ids")
    args = ap.parse_args(argv)
    a, b = probe_pair(args.selection, args.fresh, run=args.run, extra=["-n", args.n])
    seeds = compare_seeds(a, b)
    params = compare_params(a, b)
    bad = unshifted(seeds)
    shifted = [k for k, v in seeds.items() if "unshifted" not in v]
    print(f"seeding keys: {len(seeds)}, shifted {len(shifted)}, unshifted {len(bad)}, "
          f"independent {sum(1 for k, v in seeds.items() if 'unshifted' in v and independent(k))}")
    for k, v in bad.items():
        print(f"UNSHIFTED {k}: {v['n0']} seedings, shared values {v['unshifted']}")
    for k, v in seeds.items():
        if "only_in" in v:
            print(f"only at {v['only_in']}: {k}")
        if v.get("unseeded"):
            print(f"unseeded (None): {k}")
    by_fn: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for (fn, _), v in params.items():
        by_fn[fn][0] += 1
        by_fn[fn][1] += bool(v["changed"])
    moved = {fn: c for fn, c in by_fn.items() if c[1]}
    print(f"parametrized functions: {len(by_fn)}, with changed values: {len(moved)}")
    for fn, (n, c) in sorted(moved.items()):
        print(f"  {c}/{n} changed  {fn}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
