"""Load and validate the guard policy.

File: config/guard-policy.json · schema: contracts/guard-policy.schema.json.

The policy is user configuration. A bad file is rejected with every problem listed; nothing is
clamped or silently replaced by a default.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_SCHEMA_FILE = REPO_ROOT / "contracts" / "guard-policy.schema.json"
DEFAULT_POLICY_FILE = REPO_ROOT / "config" / "guard-policy.json"


class PolicyError(ValueError):
    """The policy file is missing, not valid JSON, or does not match the schema."""


class UnknownProfileError(PolicyError, KeyError):
    """The requested profile name is not in the policy."""

    def __str__(self) -> str:  # KeyError would otherwise wrap the message in quotes
        return self.args[0] if self.args else ""


@dataclass(frozen=True)
class Profile:
    """Limits for one request type. Field meanings: contracts/guard-policy.schema.json."""

    name: str
    description: str
    max_output_tokens: int
    max_model_calls: int
    max_tool_calls: int
    max_budget_usd: float
    timeout_s: float
    max_identical_tool_calls: int
    max_files_written: int
    max_live_writes: int
    warn_at_fraction: float


@dataclass(frozen=True)
class GlobalLimits:
    session_budget_usd: float
    daily_budget_usd: float
    max_concurrent_requests: int


@dataclass(frozen=True)
class Policy:
    global_limits: GlobalLimits
    profiles: Mapping[str, Profile]

    def profile(self, name: str) -> Profile:
        try:
            return self.profiles[name]
        except (KeyError, TypeError):
            known = ", ".join(sorted(self.profiles)) or "(none)"
            raise UnknownProfileError(
                f"Unknown guard profile {name!r}. Known profiles: {known}."
            ) from None


def _reject_constant(token: str) -> Any:
    # Python's json accepts NaN/Infinity, and JSON Schema range checks let NaN through
    # (NaN <= 0 is False). A NaN budget would disable the guard, so reject it while parsing.
    raise PolicyError(f"Policy contains {token}; only finite numbers are allowed.")


def _schema() -> dict[str, Any]:
    return json.loads(POLICY_SCHEMA_FILE.read_text(encoding="utf-8"))


def parse_policy(doc: Any) -> Policy:
    """Validate a decoded policy document and return a typed, read-only Policy."""
    errors = sorted(Draft202012Validator(_schema()).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        lines = [f"- {'.'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]
        raise PolicyError("Invalid guard policy:\n" + "\n".join(lines))
    g = doc["global"]
    global_limits = GlobalLimits(
        session_budget_usd=float(g["session_budget_usd"]),
        daily_budget_usd=float(g["daily_budget_usd"]),
        max_concurrent_requests=int(g["max_concurrent_requests"]),
    )
    profiles = {
        name: Profile(
            name=name,
            description=p.get("description", ""),
            max_output_tokens=int(p["max_output_tokens"]),
            max_model_calls=int(p["max_model_calls"]),
            max_tool_calls=int(p["max_tool_calls"]),
            max_budget_usd=float(p["max_budget_usd"]),
            timeout_s=float(p["timeout_s"]),
            max_identical_tool_calls=int(p["max_identical_tool_calls"]),
            max_files_written=int(p["max_files_written"]),
            max_live_writes=int(p["max_live_writes"]),
            warn_at_fraction=float(p["warn_at_fraction"]),
        )
        for name, p in doc["profiles"].items()
    }
    return Policy(global_limits=global_limits, profiles=MappingProxyType(profiles))


def load_policy(path: Path | str = DEFAULT_POLICY_FILE) -> Policy:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"Cannot read guard policy {path}: {exc}") from exc
    try:
        doc = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise PolicyError(f"Guard policy {path} is not valid JSON: {exc}") from exc
    return parse_policy(doc)
