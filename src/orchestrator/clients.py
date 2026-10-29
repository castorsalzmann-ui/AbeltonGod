"""Model-client selection.

The real route is ``SdkModelClient`` (Claude Agent SDK, #106). Whenever it cannot be built -
auth config error, SDK not installed - the result is an ``UnavailableModel``: every call fails
cleanly with ``ModelUnavailable(request_sent=False)``, which is exactly the "Claude
unreachable" path the engine and bridge must survive.
"""

from __future__ import annotations

from typing import Any

from orchestrator.auth import AuthConfigError, AuthSettings, load_auth
from orchestrator.model_client import ModelClient, ModelRequest, ModelResponse, ModelUnavailable

SDK_MISSING = "the Claude Agent SDK is not installed (pip install -e .)"


class UnavailableModel:
    """A model client that is never reachable. Makes no network call."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.calls = 0

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        raise ModelUnavailable(self.reason, request_sent=False)


def make_model_client(
    settings: AuthSettings | None = None, *, profile: Any = None, **sdk_options: Any
) -> ModelClient:
    """Client for the configured auth mode. A config error or a missing SDK becomes an
    unreachable model with the reason, so the chat still starts and says what to fix.
    ``profile`` (a guard ``Profile``) sets the per-call cost reservation."""
    if settings is None:
        try:
            settings = load_auth()
        except AuthConfigError as exc:
            return UnavailableModel(str(exc))
    try:
        from orchestrator.sdk_client import SdkModelClient, per_call_estimate
    except ImportError as exc:
        return UnavailableModel(f"{SDK_MISSING}: {exc}")
    estimate = per_call_estimate(profile) if profile is not None else None
    return SdkModelClient(settings, per_call_estimate_usd=estimate, **sdk_options)


__all__ = ["SDK_MISSING", "UnavailableModel", "make_model_client"]
