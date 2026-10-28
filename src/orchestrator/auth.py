"""Auth switch (D-008, D-014): one configuration point, ``ABELTONGOD_CLAUDE_AUTH``.

- ``subscription`` (default, D-014): the Claude Agent SDK uses the user's Claude login.
- ``api_key``: the SDK uses ``ANTHROPIC_API_KEY``.

The value is read from the process environment, else from ``.env`` in the repo root
(git-ignored; variables documented in ``.env.example``). Secrets are never logged or returned
in messages; only whether a key is present.

Known trap (auth note row 8, Agent SDK note PR #79 Q6, **not verified on the user's machine**):
a set ``ANTHROPIC_API_KEY`` or ``ANTHROPIC_AUTH_TOKEN`` silently wins over the subscription
login in SDK runs and bills a Console organisation. In ``subscription`` mode such a variable is
therefore refused before any model call. The SDK adapter (step 2) must also compare the init
message's ``apiKeySource`` with the mode via ``check_api_key_source``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
AUTH_VARIABLE = "ABELTONGOD_CLAUDE_AUTH"
MODEL_VARIABLE = "ABELTONGOD_CLAUDE_MODEL"
DEFAULT_MODEL = "claude-opus-5-5"  # D-014
# Variables that make the SDK's CLI use API billing instead of the login (auth precedence).
OVERRIDING_VARIABLES = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")

# apiKeySource values from the research note (PR #79, Q6); unverified on the user's machine (V7).
_EXPECTED_SOURCE = {"subscription": ("none",), "api_key": ("ANTHROPIC_API_KEY",)}


class AuthMode(StrEnum):
    SUBSCRIPTION = "subscription"
    API_KEY = "api_key"


class AuthConfigError(ValueError):
    """The auth configuration is invalid or contradicts itself. Message is safe to show."""


@dataclass(frozen=True)
class AuthSettings:
    mode: AuthMode
    model: str
    api_key_present: bool

    def __repr__(self) -> str:  # never print a secret, only its presence
        return (
            f"AuthSettings(mode={self.mode.value!r}, model={self.model!r}, "
            f"api_key_present={self.api_key_present})"
        )


def read_env_file(path: Path | str) -> dict[str, str]:
    """Minimal ``.env`` reader: ``KEY=VALUE`` lines, ``#`` comments, optional quotes.
    A missing file is an empty mapping."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise AuthConfigError(f"cannot read {path}: {exc.strerror or exc}") from None
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def merged_environment(
    environ: Mapping[str, str] | None = None, env_file: Path | str | None = DEFAULT_ENV_FILE
) -> dict[str, str]:
    """``.env`` values with the process environment on top (the process wins)."""
    merged = read_env_file(env_file) if env_file is not None else {}
    merged.update(os.environ if environ is None else environ)
    return merged


def load_auth(
    environ: Mapping[str, str] | None = None, env_file: Path | str | None = DEFAULT_ENV_FILE
) -> AuthSettings:
    """Read and check the auth switch. Raises ``AuthConfigError`` on any contradiction."""
    env = merged_environment(environ, env_file)
    raw = env.get(AUTH_VARIABLE, "").strip().lower() or AuthMode.SUBSCRIPTION.value
    try:
        mode = AuthMode(raw)
    except ValueError:
        raise AuthConfigError(
            f"{AUTH_VARIABLE} must be 'subscription' or 'api_key', got {raw!r}"
        ) from None
    present = {name for name in OVERRIDING_VARIABLES if env.get(name, "").strip()}
    if mode is AuthMode.SUBSCRIPTION and present:
        raise AuthConfigError(
            f"{AUTH_VARIABLE}=subscription, but {', '.join(sorted(present))} is set. The SDK "
            "would use it instead of your Claude login. Remove it from .env and from the "
            "Windows environment, or set "
            f"{AUTH_VARIABLE}=api_key."
        )
    if mode is AuthMode.API_KEY and "ANTHROPIC_API_KEY" not in present:
        raise AuthConfigError(f"{AUTH_VARIABLE}=api_key needs ANTHROPIC_API_KEY in .env")
    model = env.get(MODEL_VARIABLE, "").strip() or DEFAULT_MODEL
    return AuthSettings(mode=mode, model=model, api_key_present="ANTHROPIC_API_KEY" in present)


def check_api_key_source(mode: AuthMode, api_key_source: str | None) -> None:
    """Compare the backend's reported credential source with the switch; refuse a mismatch.
    For the SDK adapter's startup check (step 2). Expected values are unverified (V7)."""
    expected = _EXPECTED_SOURCE[AuthMode(mode).value]
    if api_key_source not in expected:
        raise AuthConfigError(
            f"auth mode {AuthMode(mode).value!r} expects credential source "
            f"{' or '.join(expected)}, but the backend reports {api_key_source!r}"
        )


__all__ = [
    "AUTH_VARIABLE",
    "DEFAULT_MODEL",
    "MODEL_VARIABLE",
    "AuthConfigError",
    "AuthMode",
    "AuthSettings",
    "check_api_key_source",
    "load_auth",
    "merged_environment",
    "read_env_file",
]
