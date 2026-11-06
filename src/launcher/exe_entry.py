"""PyInstaller entry point of both exes (absolute imports: the file runs as a script).

``scripts/build_exe.py`` builds this script twice into one folder (#445):

* ``AbeltonGod.exe``: windowed (no console). Double-click opens the GUI. Windowed processes
  have no ``sys.stdout``/``sys.stderr``; they are sent to a log file instead.
* ``AbeltonGod-cli.exe``: console. Without arguments the text menu, with arguments the tools.

The file name picks the mode (``launcher.cli.is_cli_exe``).
"""

import multiprocessing
import sys

from launcher.cli import entry, is_cli_exe
from launcher.startup_log import redirect_missing_streams

if __name__ == "__main__":
    multiprocessing.freeze_support()
    redirect_missing_streams()
    entry(cli_exe=is_cli_exe(sys.executable))
