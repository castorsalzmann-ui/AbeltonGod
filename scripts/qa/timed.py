"""Run a command and report wall time, CPU time (user+sys of all children) and machine load.

Why: on the shared machine wall time swings with foreign load (#69, #278); CPU time is the
steadier number. ``/usr/bin/time`` is not installed everywhere, so this uses ``resource``.

    python scripts/qa/timed.py -- python -m pytest -o pythonpath=src -q
"""

from __future__ import annotations

import os
import resource
import subprocess
import sys
import time


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print(__doc__)
        return 2
    load0 = os.getloadavg()
    t0 = time.perf_counter()
    rc = subprocess.call(argv)
    wall = time.perf_counter() - t0
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    load1 = os.getloadavg()
    print(
        f"TIMED rc={rc} wall={wall:.1f}s user={ru.ru_utime:.1f}s sys={ru.ru_stime:.1f}s "
        f"cpu={ru.ru_utime + ru.ru_stime:.1f}s cores={os.cpu_count()} "
        f"load1_start={load0[0]:.1f} load1_end={load1[0]:.1f}"
    )
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
