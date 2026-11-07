"""Copilot chat service (no Qt) on the existing orchestrator (``orchestrator.chat`` wiring).

Same pieces as ``python -m orchestrator.chat --project``: ``Guard`` with the policy file
unchanged, profile ``kick_generation``, ``KickSession`` (``generate_kick``, ``list_tracks``,
``import_sample``) + ``SampleTools`` (``generate_sample``) + the plan tools in one ``Toolbox``
with the capability gate of the session, the model client from ``orchestrator.auth`` /
``orchestrator.clients``, and the orchestrator's ``ChatMemory`` (#175). Every model and tool
call goes through ``Orchestrator`` -> ``Toolbox.run``; this module calls no tool handler.

Differences to the terminal chat (#491):

* The session folder is the GUI **output folder** (shared settings), not a Live project: the
  main window renders into it in the project layout (``Samples/Drums/Kicks`` …, #443), the
  library lists it, and the bridge imports a WAV from there in place. The folder has no
  ``.als`` file, so :func:`output_folder_check` runs ``library.check_project_dir`` and lets
  only that one refusal (``no_als_file``) pass; checkout, Live's Backup folder, a missing or
  unreadable folder stay refused. ``import_sample`` therefore makes Live point at the file in
  the output folder; it does not copy it into the shared project folder (the Live-import page
  does that).
* Approval: the approver is set by the GUI (:class:`GuiApprover`, a modal dialog on the GUI
  thread); without one every confirm tool is declined (:class:`DenyApprover`).
* Cancel: :meth:`ChatSession.cancel` stops the request at its next guard step
  (``Orchestrator.cancel``) and declines an open confirmation.
* Access settings come from the ``.env`` next to the app.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bridge.capabilities import CapabilityError
from guard import Guard
from gui_core.live import (
    Placement,
    copy_into_project,
    default_refused_roots,
    plan_placement,
    remove_copy,
)
from launcher.paths import app_dir
from library import check_project_dir, sidecar_path
from library.project import ProjectDirProblem, ProjectReason
from orchestrator.auth import AuthConfigError, AuthMode, load_auth
from orchestrator.clients import make_model_client
from orchestrator.kick_tools import ImportPlan, KickSession
from orchestrator.loop import DEFAULT_PROFILE, Orchestrator, Outcome
from orchestrator.memory import ChatMemory
from orchestrator.model_client import ModelClient
from orchestrator.plan_tools import PlanSession
from orchestrator.project import ProjectCheckUnavailable
from orchestrator.sample_tools import SampleTools
from orchestrator.tools import CONFIRM_WINDOW_S, Plan, Tool, Toolbox, ToolDefinitionError

from .paths import default_output_dir

# The dialog closes as "no" when the confirmation window of the orchestrator is over: a later
# yes would be refused as too late anyway (orchestrator.tools.CONFIRM_WINDOW_S, 20 s).
CONFIRM_TIMEOUT_S = CONFIRM_WINDOW_S


def default_env_file() -> Path:
    return app_dir() / ".env"


@dataclass(frozen=True)
class ChatStatus:
    ready: bool
    message: str  # German; never contains a key value
    mode: str = ""


def chat_status(env_file: Path | str | None = None) -> ChatStatus:
    """Can the chat start with this ``.env``? A missing key in ``api_key`` mode is a clear
    message instead of an error on the first request. Whether a subscription login is valid
    cannot be seen without a request; the text says so."""
    env_file = Path(env_file) if env_file is not None else default_env_file()
    try:
        settings = load_auth(env_file=env_file)
    except AuthConfigError as exc:
        text = str(exc)
        if "needs ANTHROPIC_API_KEY" in text:
            return ChatStatus(False, (
                "Kein API-Schlüssel gefunden. ABELTONGOD_CLAUDE_AUTH steht auf api_key, aber "
                f"in {env_file} fehlt ANTHROPIC_API_KEY=... (Vorlage: .env.example). Schlüssel "
                "eintragen oder ABELTONGOD_CLAUDE_AUTH=subscription setzen und das Programm "
                "neu starten."), "api_key")
        return ChatStatus(False, f"Die Zugangsdaten für Claude sind falsch eingestellt: {text}")
    if settings.mode is AuthMode.API_KEY:
        return ChatStatus(True, f"Zugang: API-Schlüssel aus {env_file} (der Wert wird nie "
                          "angezeigt). Modell: " + settings.model, settings.mode.value)
    return ChatStatus(True, "Zugang: Claude-Anmeldung (subscription). Ob du angemeldet bist, "
                      "zeigt erst die erste Anfrage; geprüft wird vorher nichts. Modell: "
                      + settings.model, settings.mode.value)


LOGIN_HINT = (
    "Falls du nicht bei Claude angemeldet bist: im Terminal claude starten und /login "
    "ausführen, oder in der .env ABELTONGOD_CLAUDE_AUTH=api_key und ANTHROPIC_API_KEY=... "
    "setzen und das Programm neu starten."
)


class DenyApprover:
    """Declines every confirm tool (no GUI attached)."""

    def confirm(self, tool: Any, arguments: dict[str, Any], plan: Any = None) -> bool:
        return False


# --- GUI approval ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfirmText:
    """What the dialog shows. ``lines`` name exactly what would be written to Live."""

    title: str
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def confirm_text(tool: Tool, arguments: Mapping[str, Any], plan: Plan | None,
                 timeout_s: float = CONFIRM_TIMEOUT_S) -> ConfirmText:
    """German dialog text for a confirm tool. For ``import_sample`` it lists the target track
    and scene (Live numbers, from 1), the file with its full path and the SHA-256 the
    orchestrator pinned when the file was written (it hashes the file again right before the
    write and refuses on any difference)."""
    data = getattr(plan, "data", None)
    s = dict(getattr(plan, "summary", None) or {})
    tail = (f"Bitte innerhalb von {timeout_s:g} s antworten. Ohne Antwort, mit Nein oder "
            "Schließen wird nichts ausgeführt.")
    if tool.name == "import_sample" and isinstance(data, ImportPlan):
        e = data.entry
        p = data.placement
        if p is None or getattr(p, "project_dir", None) == "":
            where = ("Live verweist danach auf diese Datei im Ausgabeordner (kein Projektordner "
                     "in den Einstellungen, also keine Kopie ins Projekt).",)
        elif p.copy:
            where = ("Vorher auf der Festplatte: WAV und Sidecar in den Projektordner kopieren",
                     f"  nach {p.target}",
                     "  (nichts wird überschrieben; erreicht nichts Live, wird die Kopie wieder "
                     "gelöscht). Live verweist danach auf die Kopie.")
        elif str(p.target) != str(p.source):
            where = (f"Die Datei liegt schon unverändert im Projektordner: {p.target}",
                     "Live verweist danach auf diese Datei.")
        else:
            where = ("Die Datei liegt schon im Projektordner; Live verweist danach auf sie.",)
        return ConfirmText("Live-Set ändern?", (
            "Der Copilot möchte das geöffnete Live-Set ändern:",
            f"  1 Audio-Clip anlegen in Spur {data.track_index + 1} \"{data.track_name}\", "
            f"Szene {data.slot_index + 1} (von {data.num_scenes}).",
            f"  Sample: {e.sample_id} ({e.category})",
            f"  Datei: {e.path}",
            f"  SHA-256: {e.sha256}",
            *where,
            "Es wird kein Clip überschrieben; ein Undo sendet das Programm nicht.",
            tail,
        ))
    shown = s or dict(arguments)
    return ConfirmText("Live-Set ändern?", (
        f"Der Copilot möchte das Werkzeug {tool.name} ausführen. Das ändert das Live-Set.",
        *(f"  {k}: {v}" for k, v in shown.items()),
        tail,
    ))


class ConfirmRequest:
    """One open question to the user. The worker waits on it; the GUI answers it. Only an
    explicit yes given before the request expired counts; everything else is no."""

    def __init__(self, text: ConfirmText, timeout_s: float) -> None:
        self.text = text
        self.timeout_s = max(0.0, float(timeout_s))
        self.deadline = time.monotonic() + self.timeout_s  # the GUI countdown ends here
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._answer: bool | None = None
        self._closed = False

    def answer(self, yes: bool) -> bool:
        """Record the user's answer; False when the request was already closed (too late,
        cancelled). Only the first answer counts."""
        with self._lock:
            if self._closed:
                return False
            self._answer = yes is True
            self._closed = True
        self._done.set()
        return True

    def expire(self) -> None:
        """Close the request as no (timeout, cancel, shutdown) unless it was answered."""
        with self._lock:
            if not self._closed:
                self._answer = False
                self._closed = True
        self._done.set()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def wait(self) -> bool:
        """Block the calling (worker) thread until answered or ``timeout_s`` passed."""
        self._done.wait(self.timeout_s)
        self.expire()  # the timeout counts as no; a recorded answer stays as it was
        with self._lock:
            return self._answer is True


class GuiApprover:
    """Approver for the GUI. ``post(request)`` must hand the request to the GUI thread and
    return at once (a Qt signal); the GUI shows the dialog and calls ``request.answer``. The
    worker thread waits here; a timeout, a cancel or an exception in ``post`` is a no."""

    def __init__(self, post: Callable[[ConfirmRequest], None],
                 timeout_s: float = CONFIRM_TIMEOUT_S) -> None:
        self._post = post
        self.timeout_s = float(timeout_s)
        self._lock = threading.Lock()
        self._open: list[ConfirmRequest] = []
        self.asked: list[ConfirmText] = []  # what was shown, oldest first

    def confirm(self, tool: Tool, arguments: dict[str, Any], plan: Plan | None = None) -> bool:
        return self.confirm_within(tool, arguments, plan, None)

    def confirm_within(self, tool: Tool, arguments: dict[str, Any], plan: Plan | None,
                       window_s: float | None) -> bool:
        """``window_s``: what is left of the orchestrator's confirmation window (from the
        model turn's start, ``Toolbox.confirm_window_left``); the dialog's time and text use
        it instead of a fresh ``timeout_s`` (#493 review). None: ``timeout_s``."""
        timeout = self.timeout_s
        if window_s is not None:
            timeout = max(0.0, min(timeout, float(window_s)))
        request = ConfirmRequest(confirm_text(tool, arguments, plan, math.floor(timeout)),
                                 timeout)
        with self._lock:
            self._open.append(request)
            self.asked.append(request.text)
        try:
            self._post(request)
        except Exception:  # noqa: BLE001 - a dialog that cannot be shown is a no
            request.expire()
        try:
            return request.wait()
        finally:
            with self._lock:
                self._open = [r for r in self._open if r is not request]

    def decline_open(self) -> None:
        """Answer every open question with no (cancel button, closing the window)."""
        with self._lock:
            pending = list(self._open)
        for r in pending:
            r.expire()


# --- session folder -------------------------------------------------------------------------


def output_folder_check(folder: str | os.PathLike[str], *,
                        refused_roots: Any = None) -> Any:
    """``library.check_project_dir`` for the GUI output folder: every refusal stays except
    ``no_als_file`` (the output folder is laid out like a project but holds no set)."""
    roots = default_refused_roots() if refused_roots is None else refused_roots
    problem = (check_project_dir(folder) if roots is None
               else check_project_dir(folder, refused_roots=roots))
    if problem is not None and problem.reason is ProjectReason.NO_ALS_FILE:
        return None
    return problem


class _FolderRefused(ValueError):
    """The output folder was refused before anything was created (German text)."""


_BEFORE_CREATE = (ProjectReason.EMPTY, ProjectReason.NOT_ABSOLUTE,
                  ProjectReason.CHECKOUT_UNKNOWN, ProjectReason.IN_CHECKOUT,
                  ProjectReason.BACKUP_FOLDER, ProjectReason.UNREADABLE)


def folder_problem_before_create(folder: Path, check: Callable[..., Any],
                                 refused_roots: Any) -> Any:
    """The refusal of ``folder`` that is known before creating it, or None. An existing folder
    gets the full check. For a missing one: a relative path is refused as such; a missing
    component named ``Backup`` (anywhere on the way) is refused; the nearest existing parent
    is checked and its checkout, Backup and unreadable refusals count for the new folder too
    (``missing`` and ``no_als_file`` of the parent do not). Creates nothing."""
    def run(path: Path) -> Any:
        return (check(path) if refused_roots is None
                else check(path, refused_roots=refused_roots))

    if not os.path.isabs(folder) or folder.is_dir():
        return run(folder)
    parent = folder
    while not parent.exists() and parent != parent.parent:
        # #500 (review nit of #493): no folder named Backup is created anywhere on the way,
        # not only as the last component.
        if parent.name.casefold() == "backup":
            return ProjectDirProblem(ProjectReason.BACKUP_FOLDER, os.fspath(folder),
                                     str(parent))
        parent = parent.parent
    if parent.exists() and not parent.is_dir():
        return ProjectDirProblem(ProjectReason.MISSING, os.fspath(folder),
                                 f"{parent} is a file")
    problem = run(parent)
    if problem is not None and getattr(problem, "reason", None) in _BEFORE_CREATE:
        return ProjectDirProblem(problem.reason, os.fspath(folder), problem.detail)
    return None


def output_problem_text(problem: Any) -> str:
    """German refusal text for the **output** folder (``project_problem_text`` speaks of the
    Live project folder)."""
    reason, raw, detail = (getattr(problem, "reason", None), getattr(problem, "path", ""),
                           getattr(problem, "detail", ""))
    texts = {
        ProjectReason.EMPTY: "Kein Ausgabeordner angegeben.",
        ProjectReason.NOT_ABSOLUTE: f"Der Ausgabeordner muss ein voller Pfad sein, nicht {raw!r}.",
        ProjectReason.MISSING: f"Den Ausgabeordner gibt es nicht und er lässt sich nicht "
                               f"anlegen: {raw} ({detail})",
        ProjectReason.CHECKOUT_UNKNOWN: "Der AbeltonGod-Ordner, aus dem das Programm läuft, ist "
                                        f"nicht als Checkout erkennbar ({detail}); aus Vorsicht "
                                        "wird kein Ausgabeordner angenommen.",
        ProjectReason.IN_CHECKOUT: f"Der Ausgabeordner {raw} liegt im AbeltonGod-Ordner "
                                   f"({detail}).",
        ProjectReason.BACKUP_FOLDER: f"Der Ausgabeordner {raw} ist (oder liegt in) Lives "
                                     "Backup-Ordner.",
        ProjectReason.UNREADABLE: f"Der Ausgabeordner {raw} lässt sich nicht lesen: {detail}",
    }
    return texts.get(reason, f"Der Ausgabeordner {raw} wurde abgelehnt ({reason}: {detail}).")


@dataclass(frozen=True)
class ToolsState:
    """What the copilot can do in this session (German ``note`` for the page)."""

    names: tuple[str, ...]
    folder: Path | None  # where new samples go; None = no sample tools
    note: str


# --- reply and budget -----------------------------------------------------------------------


def _usd(value: Any) -> str:
    try:
        return f"{float(value):.2f} $".replace(".", ",")
    except (TypeError, ValueError):
        return "?"


def budget_text(guard: Guard, usage: Mapping[str, Any] | None = None,
                profile: str = DEFAULT_PROFILE, mode: str = "") -> str:
    """Status line: the guard's limits per request, what the last request used, and the money
    of the session and the day (the guard's own counters, never an estimate of this page)."""
    p = guard.policy.profile(profile)
    g = guard.policy.global_limits
    if usage:
        req = (f"Letzte Anfrage: {usage.get('model_calls', 0)} von {p.max_model_calls} "
               f"Modellaufrufen, {usage.get('tool_calls', 0)} von {p.max_tool_calls} "
               f"Werkzeugaufrufen, {usage.get('files_written', 0)} von {p.max_files_written} "
               f"Dateien, {usage.get('live_writes', 0)} von {p.max_live_writes} "
               f"Live-Änderungen, {_usd(usage.get('cost_usd', 0))} von "
               f"{_usd(p.max_budget_usd)}.")
    else:
        req = (f"Guard je Anfrage: höchstens {p.max_model_calls} Modellaufrufe, "
               f"{p.max_tool_calls} Werkzeugaufrufe, {p.max_files_written} Dateien, "
               f"{p.max_live_writes} Live-Änderungen, {_usd(p.max_budget_usd)}, "
               f"{p.timeout_s:g} s.")
    money = (f"Sitzung {_usd(guard.session_spent_usd)} von {_usd(g.session_budget_usd)}, "
             f"heute {_usd(guard.daily_spent_usd)} von {_usd(g.daily_budget_usd)}.")
    note = (" Beim Abo sind die $-Werte der geschätzte API-Gegenwert, kein berechnetes Geld."
            if mode == "subscription" else "")
    return f"{req} {money}{note}"


@dataclass(frozen=True)
class ChatReply:
    text: str
    success: bool
    files: tuple[Path, ...] = ()  # WAVs this request wrote (from the session's sample table)
    budget: str = ""  # guard status after the request
    cancelled: bool = False


class _ApproverSlot:
    """The orchestrator's approver: whatever ``ChatSession.approver`` is at call time."""

    def __init__(self, session: ChatSession) -> None:
        self._session = session

    def confirm(self, tool: Tool, arguments: dict[str, Any], plan: Plan | None = None) -> bool:
        approver = self._session.approver
        within = getattr(approver, "confirm_within", None)
        box = self._session._toolbox
        if callable(within) and box is not None:
            return within(tool, arguments, plan, box.confirm_window_left()) is True
        return approver.confirm(tool, arguments, plan) is True


@dataclass(frozen=True)
class ChatPlacement:
    """Where Live reads an imported file from (``KickSession`` placement plan, #500)."""

    source: str
    target: str
    copy: bool
    project_dir: str  # "" = no project folder set: Live reads the file where it is
    placement: Placement | None = None  # gui_core.live's plan, None without a project


class ProjectCopy:
    """``ImportPlacement`` for the copilot: the Live page's copy plan (``gui_core.live``)
    into the shared project folder, read at plan time (a settings change needs no rebuild).
    No project folder: Live reads the file in the output folder, as before #500."""

    def __init__(self, project_dir: str = "", refused_roots: Any = None) -> None:
        self.project_dir = project_dir
        self.refused_roots = refused_roots

    def plan(self, wav: str) -> ChatPlacement:
        project = (self.project_dir or "").strip()
        if not project:
            return ChatPlacement(str(wav), str(wav), False, "")
        p = plan_placement(wav, project, refused_roots=self.refused_roots)  # ImportPathError
        return ChatPlacement(str(p.source), str(p.target), bool(p.copy), project, p)

    def copy(self, placement: ChatPlacement) -> None:
        if placement.placement is not None:
            copy_into_project(placement.placement)

    def remove(self, placement: ChatPlacement) -> None:
        remove_copy((sidecar_path(placement.target), placement.target))


class ChatSession:
    """One chat: tools for the current output folder, the orchestrator built on the first
    question, one ``ChatMemory`` for the whole chat (kept when the folder changes)."""

    def __init__(self, env_file: Path | str | None = None, *, model: ModelClient | None = None,
                 guard: Guard | None = None, output_dir: Path | str | None = None,
                 approver: Any = None, project_dir: str = "",
                 session_options: Mapping[str, Any] | None = None) -> None:
        """``session_options``: extra ``KickSession`` arguments (tests: ``bridge_factory`` to
        the fake AbletonOSC, ``registry``, ``action_log``, ``refused_roots``; the latter is
        also used for the project-folder copy plan). ``project_dir``: the shared Live project
        folder; set, ``import_sample`` copies into it first (#500)."""
        self.env_file = Path(env_file) if env_file is not None else default_env_file()
        self._model = model
        self._guard = guard
        self.approver = approver if approver is not None else DenyApprover()
        self._session_options = dict(session_options or {})
        self.placement = ProjectCopy(project_dir, self._session_options.get(
            "refused_roots", default_refused_roots()))
        self.memory = ChatMemory()
        self._lock = threading.Lock()
        self._folder = Path(output_dir) if output_dir is not None else default_output_dir()
        self._built_for: Path | None = None
        self._kick: KickSession | None = None
        self._toolbox: Toolbox | None = None
        self._context: Callable[[], str] = lambda: ""
        self._tools_state: ToolsState | None = None
        self._orch: Orchestrator | None = None
        self._running: Orchestrator | None = None
        self._build = threading.RLock()  # tools / orchestrator are built by one thread at once

    # ----- configuration -----------------------------------------------------------------

    @property
    def guard(self) -> Guard:
        if self._guard is None:
            self._guard = Guard()
        return self._guard

    @property
    def output_dir(self) -> Path:
        with self._lock:
            return self._folder

    def set_output_dir(self, folder: Path | str) -> None:
        """New output folder: the tools are rebuilt before the next request (memory stays)."""
        with self._lock:
            self._folder = Path(folder)

    @property
    def project_dir(self) -> str:
        return self.placement.project_dir

    def set_project_dir(self, project_dir: str) -> None:
        """The shared project folder; read by the next import's plan (no rebuild, the
        samples of this chat stay importable)."""
        self.placement.project_dir = project_dir or ""

    def status(self) -> ChatStatus:
        if self._model is not None:  # injected client (tests): no access check needed
            return ChatStatus(True, "Testmodell (kein Claude).", "fake")
        return chat_status(self.env_file)

    def tools_state(self) -> ToolsState:
        """What the copilot can do. Creates nothing: for an output folder that does not exist
        yet, the tools are set up (and the folder created) by the first question."""
        with self._build:
            folder = self.output_dir
            if not (self._toolbox is not None and self._built_for == folder) \
                    and not folder.is_dir():
                return ToolsState((), None, (
                    f"Die Werkzeuge (Samples erzeugen, Live lesen, in Live importieren, planen) "
                    f"werden bei der ersten Frage eingerichtet; dabei wird der Ausgabeordner "
                    f"{folder} angelegt."))
            self._build_tools()
            st = self._tools_state
            assert st is not None
            if st.folder is None:
                return st
            project = self.project_dir.strip()
            where = (f" Vor dem Import kopiert der Copilot WAV und Sidecar in den Projektordner "
                     f"{project} (wie die Live-Import-Seite)." if project else
                     " Kein Projektordner eingestellt: Live verweist beim Import auf die Datei "
                     "im Ausgabeordner.")
            return ToolsState(st.names, st.folder, st.note + where)

    def budget(self, usage: Mapping[str, Any] | None = None) -> str:
        return budget_text(self.guard, usage, mode=self.status().mode)

    def _ensure_tools(self) -> None:
        with self._build:
            self._build_tools()

    def _build_tools(self) -> None:
        folder = self.output_dir
        if self._toolbox is not None and (self._built_for == folder
                                          or self._running is not None):
            return  # up to date, or a request uses the tools right now (rebuilt later)
        plans = PlanSession()
        limit = self.guard.policy.profile(DEFAULT_PROFILE).max_files_written
        kick: KickSession | None = None
        why = ""
        options = {"project_check": output_folder_check,
                   "refused_roots": default_refused_roots(), "placement": self.placement,
                   **self._session_options}
        try:
            # Check first, create only then (review of #493): a relative folder, one inside
            # the checkout or below Live's Backup folder is refused without creating anything.
            problem = folder_problem_before_create(folder, options["project_check"],
                                                   options["refused_roots"])
            if problem is not None:
                raise _FolderRefused(output_problem_text(problem))
            folder.mkdir(parents=True, exist_ok=True)  # the GUI renders here as well
            kick = KickSession(folder, **options)
            toolbox = Toolbox(kick.tools(files_per_request=limit)
                              + SampleTools(kick).tools(files_per_request=limit)
                              + plans.tools(), capability_gate=kick.gate())
        except ToolDefinitionError as exc:  # e.g. a Live capability is not `tested`
            kick, why = None, f"eine Live-Funktion nicht freigegeben ist: {exc}"
        except ValueError as exc:  # the check (before or in KickSession) refused the folder
            kick, why = None, (f"der Ausgabeordner abgelehnt wurde: "
                               f"{self._refusal(folder, exc, options['refused_roots'])}")
        except (ProjectCheckUnavailable, CapabilityError, OSError) as exc:
            kick, why = None, f"{type(exc).__name__}: {exc}"
        if kick is None:
            toolbox = Toolbox(plans.tools())
        self._kick, self._toolbox, self._built_for = kick, toolbox, folder

        def context() -> str:
            parts = (kick.context() if kick is not None else "", plans.context())
            return "\n\n".join(t for t in parts if t)

        self._context = context
        names = toolbox.names
        if kick is not None:
            note = (f"Werkzeuge: {', '.join(names)}. Neue Samples gehen in den Ausgabeordner "
                    f"{folder} (Bibliothek). import_sample fragt vor jeder Änderung am "
                    "Live-Set in einem Fenster nach.")
        else:
            note = (f"Nur Planen ({', '.join(names)}): keine Sample- und Live-Werkzeuge, weil "
                    f"{why}")
        self._tools_state = ToolsState(names, folder if kick is not None else None, note)
        if self._orch is not None:  # same model and memory, new tools
            self._orch = self._make_orch(self._orch.model)

    @staticmethod
    def _refusal(folder: Path, exc: Exception, roots: Any) -> str:
        """German text of the folder refusal (the check's own result, else the error)."""
        if isinstance(exc, _FolderRefused):
            return str(exc)
        problem = output_folder_check(folder, refused_roots=roots)
        if problem is not None and hasattr(problem, "reason"):
            return output_problem_text(problem)
        return str(exc)

    def _make_orch(self, model: ModelClient) -> Orchestrator:
        assert self._toolbox is not None
        return Orchestrator(self.guard, model, self._toolbox, profile=DEFAULT_PROFILE,
                            approver=_ApproverSlot(self), context=self._context,
                            memory=self.memory)

    def _ensure_orch(self) -> Orchestrator:
        with self._build:
            self._build_tools()
            return self._built_orch()

    def _built_orch(self) -> Orchestrator:
        if self._orch is None:
            model = self._model
            if model is None:
                prof = self.guard.policy.profile(DEFAULT_PROFILE)
                model = make_model_client(load_auth(env_file=self.env_file), profile=prof,
                                          env_file=self.env_file)
            self._orch = self._make_orch(model)
        return self._orch

    # ----- requests ----------------------------------------------------------------------

    def _sample_paths(self) -> dict[str, Path]:
        kick = self._kick
        if kick is None:
            return {}
        out = {}
        for sid in kick.sample_ids():
            entry = kick.entry(sid)
            if entry is not None:
                out[sid] = Path(entry.path)
        return out

    def ask(self, text: str) -> ChatReply:
        st = self.status()
        if not st.ready:
            return ChatReply(st.message, False)
        try:
            orch = self._ensure_orch()
            before = self._sample_paths()
            with self._lock:
                self._running = orch
            try:
                outcome = orch.handle(text)
            finally:
                with self._lock:
                    self._running = None
        except Exception as exc:  # noqa: BLE001 - shown in the chat, never a crash
            return ChatReply(f"Unerwarteter Fehler: {type(exc).__name__}: {exc}", False)
        after = self._sample_paths()
        files = tuple(p for sid, p in after.items() if before.get(sid) != p and p.is_file())
        return ChatReply(self._reply_text(outcome, st.mode), outcome.success, files,
                         budget_text(self.guard, outcome.usage, mode=st.mode),
                         outcome.error == "cancelled")

    @staticmethod
    def _reply_text(outcome: Outcome, mode: str) -> str:
        text = outcome.text_for_user
        if (mode == "subscription" and not outcome.success
                and outcome.error in ("model_unavailable", "model_protocol")):
            text += "\n" + LOGIN_HINT
        return text

    def cancel(self) -> None:
        """Stop the running request at its next guard step; an open confirmation is a no."""
        with self._lock:
            orch = self._running  # only a running request: a late press must not stop the next
            if orch is not None:
                orch.cancel()
        decline = getattr(self.approver, "decline_open", None)
        if callable(decline):
            decline()

    def close(self) -> None:
        self.cancel()
        model = self._orch.model if self._orch is not None else self._model
        close = getattr(model, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["CONFIRM_TIMEOUT_S", "ChatReply", "ChatSession", "ChatStatus", "ConfirmRequest",
           "ConfirmText", "DenyApprover", "GuiApprover", "ToolsState", "budget_text",
           "chat_status", "confirm_text", "output_folder_check"]
