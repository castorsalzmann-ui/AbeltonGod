"""AbeltonGod.exe launcher (#401): one entry point that dispatches to every tool's own CLI.

``AbeltonGod.exe <tool> <args>`` runs the tool exactly as ``python -m ...`` would;
``AbeltonGod.exe`` without arguments opens a text menu. The launcher adds no features to the
tools; it only routes (``launcher.tools``), finds bundled files (``launcher.paths``) and
reports the version (``launcher.version``).
"""
