"""Model-client selection. The real Claude Agent SDK adapter is not part of step 1 (D-020: SDK
specifics stay behind the interface until the cluster-1 research note is merged and verified).
Until then the real route is an ``UnavailableModel``: every call fails cleanly with
``ModelUnavailable(request_sent=False)``, which is exactly the "Claude unreachable" path the
engine and bridge must survive.
"""

from __future__ import annotations

from orchestrator.auth import AuthConfigError, AuthSettings, load_auth
from orchestrator.model_client import ModelClient, ModelRequest, ModelResponse, ModelUnavailable

NOT_BUILT = "the Claude Agent SDK adapter is not built yet (Phase 04b step 2)"


class UnavailableModel:
    """A model client that is never reachable. Makes no network call."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        raise ModelUnavailable(self.reason, request_sent=False)


def make_model_client(settings: AuthSettings | None = None) -> ModelClient:
    """Client for the configured auth mode. A config error becomes an unreachable model with
    the error as its reason, so the chat still starts and says what to fix."""
    if settings is None:
        try:
            settings = load_auth()
        except AuthConfigError as exc:
            return UnavailableModel(str(exc))
    return UnavailableModel(f"{NOT_BUILT}; auth mode {settings.mode.value}")


__all__ = ["NOT_BUILT", "UnavailableModel", "make_model_client"]
