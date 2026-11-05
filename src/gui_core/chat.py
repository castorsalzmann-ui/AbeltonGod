"""Copilot chat service (no Qt) on the existing orchestrator (``orchestrator.chat`` wiring).

Same pieces as ``python -m orchestrator.chat`` without ``--project``: ``Guard`` with the policy
file unchanged, profile ``kick_generation``, the plan tools, the model client from
``orchestrator.auth`` / ``orchestrator.clients``. Differences: the access settings are read from
the ``.env`` next to the app, and there is no terminal approver. This chat has no tool that
asks for a confirmation (no project folder, so no kick or import tools); a confirm tool would
be declined by :class:`DenyApprover`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from guard import Guard
from launcher.paths import app_dir
from orchestrator.auth import AuthConfigError, AuthMode, load_auth
from orchestrator.clients import make_model_client
from orchestrator.loop import DEFAULT_PROFILE, Orchestrator
from orchestrator.model_client import ModelClient
from orchestrator.plan_tools import PlanSession
from orchestrator.tools import Toolbox


def default_env_file() -> Path:
    return app_dir() / ".env"


@dataclass(frozen=True)
class ChatStatus:
    ready: bool
    message: str  # German; never contains a key value
    mode: str = ""


def chat_status(env_file: Path | str | None = None) -> ChatStatus:
    """Can the chat start with this ``.env``? A missing key in ``api_key`` mode is a clear
    message instead of an error on the first request."""
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
    return ChatStatus(True, "Zugang: Claude-Anmeldung (subscription). Ob die Anmeldung gilt, "
                      "zeigt erst die erste Anfrage. Modell: " + settings.model,
                      settings.mode.value)


class DenyApprover:
    def confirm(self, tool: Any, arguments: dict[str, Any], plan: Any = None) -> bool:
        return False


def build_orchestrator(
    env_file: Path | str | None = None, *, model: ModelClient | None = None,
    guard: Guard | None = None, profile: str = DEFAULT_PROFILE,
) -> Orchestrator:
    """Orchestrator for the chat page. ``model`` is for tests (a fake client)."""
    env_file = Path(env_file) if env_file is not None else default_env_file()
    guard = guard or Guard()
    prof = guard.policy.profile(profile)
    if model is None:
        model = make_model_client(load_auth(env_file=env_file), profile=prof, env_file=env_file)
    plans = PlanSession()
    return Orchestrator(guard, model, Toolbox(plans.tools()), profile=profile,
                        approver=DenyApprover(), context=plans.context)


@dataclass(frozen=True)
class ChatReply:
    text: str
    success: bool


class ChatSession:
    """One chat: lazily builds the orchestrator on the first question."""

    def __init__(self, env_file: Path | str | None = None, *, model: ModelClient | None = None,
                 guard: Guard | None = None) -> None:
        self.env_file = Path(env_file) if env_file is not None else default_env_file()
        self._model = model
        self._guard = guard
        self._orch: Orchestrator | None = None

    def status(self) -> ChatStatus:
        if self._model is not None:  # injected client (tests): no access check needed
            return ChatStatus(True, "Testmodell (kein Claude).", "fake")
        return chat_status(self.env_file)

    def ask(self, text: str) -> ChatReply:
        st = self.status()
        if not st.ready:
            return ChatReply(st.message, False)
        try:
            if self._orch is None:
                self._orch = build_orchestrator(self.env_file, model=self._model,
                                                guard=self._guard)
            outcome = self._orch.handle(text)
        except Exception as exc:  # noqa: BLE001 - shown in the chat, never a crash
            return ChatReply(f"Unerwarteter Fehler: {type(exc).__name__}: {exc}", False)
        return ChatReply(outcome.text_for_user, outcome.success)

    def close(self) -> None:
        model = self._orch.model if self._orch is not None else self._model
        close = getattr(model, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass
