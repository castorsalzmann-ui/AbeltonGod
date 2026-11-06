"""PyInstaller entry point of both exes (absolute imports: the file runs as a script).

``scripts/build_exe.py`` builds this script twice into one folder (#445):

* ``AbeltonGod.exe``: windowed (no console). Double-click opens the GUI. Windowed processes
  have no ``sys.stdout``/``sys.stderr``; they are sent to a log file instead.
* ``AbeltonGod-cli.exe``: console. Without arguments the text menu, with arguments the tools.
"""

import multiprocessing
import sys
from pathlib import Path

from launcher.cli import entry
from launcher.startup_log import redirect_missing_streams

if __name__ == "__main__":
    multiprocessing.freeze_support()
    redirect_missing_streams()
    entry(cli_exe=Path(sys.executable).stem.lower().endswith("-cli"))
