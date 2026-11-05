"""PyInstaller entry point (absolute imports: the file runs as a script, not as a package)."""

import multiprocessing

from launcher.cli import entry

if __name__ == "__main__":
    multiprocessing.freeze_support()
    entry()
