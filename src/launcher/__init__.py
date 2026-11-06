"""AbeltonGod.exe launcher (#401): one entry point that dispatches to every tool's own CLI.

``AbeltonGod-cli.exe <tool> <args>`` runs the tool exactly as ``python -m ...`` would;
without arguments ``AbeltonGod-cli.exe`` opens a text menu and the windowed ``AbeltonGod.exe``
the GUI (#445). The launcher adds no features to the
tools; it only routes (``launcher.tools``), finds bundled files (``launcher.paths``) and
reports the version (``launcher.version``).
"""
