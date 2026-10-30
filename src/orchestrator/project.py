"""Project-folder check for the copilot's session configuration (#148): **not yet available**.

The copilot renders kicks into ``<project>/Samples/Drums/Kicks/`` of the Live project the user
names when starting the chat (``--project``), never into a folder a tool argument names
(INTERFACES.md "Tool inputs"). That folder must pass the shared check of #149
(``library.check_project_dir``, owner audio-engineer): the rules of ``scripts/kick_to_live.py``
``project_problem`` with a structured result. ``src/orchestrator/`` neither repeats those rules
nor imports from ``scripts/`` (lead, #148).

Until #149 is merged, ``library`` has no ``check_project_dir``: ``load_project_check`` returns
``None`` and ``KickSession`` refuses to start (``ProjectCheckUnavailable``), so the chat runs
without the kick tools. Interface agreed on #149 (comment by the orchestrator-engineer)::

    library.check_project_dir(project_dir, *, refused_roots=None) -> ProjectDirProblem | None
    ProjectDirProblem: .reason (str code), .path (str), .detail (str, may be "")

``refused_roots=None`` means the AbeltonGod checkout; tests pass their own roots, because the
test temp folder lies inside the checkout.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

ProjectCheck = Callable[..., Any]  # (project_dir, *, refused_roots=...) -> problem | None


class ProjectCheckUnavailable(RuntimeError):
    """The shared project-folder check (#149) is not in ``library`` yet."""


def load_project_check() -> ProjectCheck | None:
    """``library.check_project_dir`` if it exists (after #149), else ``None``."""
    try:
        from library import check_project_dir  # type: ignore[attr-defined]
    except ImportError:
        return None
    return check_project_dir if callable(check_project_dir) else None


def problem_text(problem: Any) -> str:
    reason = getattr(problem, "reason", None)
    path = getattr(problem, "path", None)
    detail = getattr(problem, "detail", "")
    if reason is None:
        return str(problem)
    return f"{getattr(reason, 'value', reason)}: {path}" + (f" ({detail})" if detail else "")


def project_problem(
    check: ProjectCheck, project_dir: str | os.PathLike[str],
    refused_roots: tuple[Path, ...] | None,
) -> str | None:
    """Text of the check's refusal, or ``None`` when the folder is accepted. A check that
    raises counts as a refusal."""
    try:
        if refused_roots is None:
            problem = check(project_dir)
        else:
            problem = check(project_dir, refused_roots=refused_roots)
    except Exception as exc:  # noqa: BLE001 - an unusable check never accepts a folder
        return f"project check failed: {type(exc).__name__}: {exc}"
    return None if problem is None else problem_text(problem)


__all__ = ["ProjectCheck", "ProjectCheckUnavailable", "load_project_check", "problem_text",
           "project_problem"]
