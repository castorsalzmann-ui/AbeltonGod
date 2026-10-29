"""Capability registry and gate (D-004).

Loads ``contracts/capabilities.json``, validates it against its schema, and refuses calls to
capabilities whose status is not ``tested``. Check scripts that must exercise a not-yet-tested
capability name it explicitly in ``allow_untested``; that override is logged and recorded.
``unsupported`` capabilities are refused even with an override.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
CAPABILITIES_FILE = CONTRACTS_DIR / "capabilities.json"
CAPABILITIES_SCHEMA_FILE = CONTRACTS_DIR / "capabilities.schema.json"

logger = logging.getLogger("abeltongod.bridge.capabilities")


class CapabilityError(Exception):
    """Base class for capability registry and gate errors."""


class CapabilityRegistryError(CapabilityError):
    """The registry file is missing, not JSON, or does not match its schema."""


class UnknownCapabilityError(CapabilityError):
    """The capability id is not in the registry."""


class CapabilityNotTestedError(CapabilityError):
    """The capability exists but may not be called (status is not ``tested``)."""

    def __init__(self, capability_id: str, status: str, reason: str) -> None:
        self.capability_id = capability_id
        self.status = status
        super().__init__(f"capability {capability_id!r} has status {status!r}: {reason}")


@dataclass(frozen=True)
class Capability:
    id: str
    kind: str
    target: str
    status: str
    notes: str
    evidence: str | None = None
    reversible: bool | None = None


class CapabilityRegistry:
    """Read-only view of the capability registry."""

    def __init__(self, capabilities: Iterable[Capability], live_version_tested: str | None) -> None:
        self._by_id: dict[str, Capability] = {}
        for cap in capabilities:
            if cap.id in self._by_id:
                raise CapabilityRegistryError(f"duplicate capability id {cap.id!r}")
            self._by_id[cap.id] = cap
        self.live_version_tested = live_version_tested

    @classmethod
    def from_file(
        cls,
        path: Path = CAPABILITIES_FILE,
        schema_path: Path = CAPABILITIES_SCHEMA_FILE,
    ) -> CapabilityRegistry:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityRegistryError(f"cannot read capability registry {path}: {exc}") from exc
        errors = sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: e.path)
        if errors:
            first = errors[0]
            where = "/".join(str(p) for p in first.path) or "<root>"
            raise CapabilityRegistryError(
                f"capability registry {path} does not match its schema at {where}: {first.message}"
            )
        caps = [
            Capability(
                id=c["id"],
                kind=c["kind"],
                target=c["target"],
                status=c["status"],
                notes=c["notes"],
                evidence=c.get("evidence"),
                reversible=c.get("reversible"),
            )
            for c in doc["capabilities"]
        ]
        return cls(caps, doc["live_version_tested"])

    def __contains__(self, capability_id: object) -> bool:
        return capability_id in self._by_id

    def ids(self) -> list[str]:
        return list(self._by_id)

    def get(self, capability_id: str) -> Capability:
        try:
            return self._by_id[capability_id]
        except KeyError:
            raise UnknownCapabilityError(f"unknown capability {capability_id!r}") from None


class UnregisteredCapabilityError(CapabilityNotTestedError):
    """The capability has no registry entry yet and the caller did not opt in explicitly."""

    def __init__(self, capability_id: str, reason: str) -> None:
        super().__init__(capability_id, "unregistered", reason)


class CapabilityGate:
    """Decides whether a capability may be called.

    ``allow_untested`` is meant only for manual check scripts (Phase 02 ``bridge_check.py``).
    Every id in it must exist in the registry and must not be ``unsupported``; this is checked
    when the gate is built, so a typo fails loudly instead of silently allowing nothing.

    ``allow_unregistered`` (#140) is the same kind of explicit check-script opt-in for
    capabilities that have **no registry entry yet** (they get one, with the user's evidence,
    in a later contract-change PR). No registry status can ever unlock them, so production
    code cannot reach them by accident. An id that is in the registry is refused here: once a
    contract-change PR registers it, the caller must use ``allow_untested`` (or nothing, if it
    is ``tested``) instead, and fails loudly until it does.
    """

    def __init__(self, registry: CapabilityRegistry, allow_untested: Iterable[str] = (),
                 allow_unregistered: Iterable[str] = ()) -> None:
        self.registry = registry
        allowed = frozenset(allow_untested)
        for cap_id in sorted(allowed):
            cap = registry.get(cap_id)  # raises UnknownCapabilityError
            if cap.status == "unsupported":
                raise CapabilityNotTestedError(
                    cap_id, cap.status, "unsupported capabilities cannot be overridden"
                )
        unregistered = frozenset(allow_unregistered)
        registered_now = sorted(c for c in unregistered if c in registry)
        if registered_now:
            raise CapabilityRegistryError(
                f"{registered_now} are in the registry now: use allow_untested, not "
                "allow_unregistered"
            )
        self.allow_untested = allowed
        self.allow_unregistered = unregistered
        self.overrides_used: list[str] = []

    def check_unregistered(self, capability_id: str) -> Capability | None:
        """Gate for a capability that has no registry entry yet (#140).

        Registered ids go through :meth:`check`. An unregistered id passes only if it was
        named in ``allow_unregistered``; the use is logged and recorded in ``overrides_used``.
        """
        if capability_id in self.registry:
            return self.check(capability_id)
        if capability_id in self.allow_unregistered:
            logger.warning("capability %r (no registry entry) called through an explicit "
                           "check-script opt-in", capability_id)
            self.overrides_used.append(capability_id)
            return None
        raise UnregisteredCapabilityError(
            capability_id, "no registry entry yet; only a check script that names it in "
                           "allow_unregistered may call it")

    def check(self, capability_id: str) -> Capability:
        """Return the capability if it may be called; raise otherwise."""
        cap = self.registry.get(capability_id)
        if cap.status == "tested":
            return cap
        if cap.status == "unsupported":
            raise CapabilityNotTestedError(cap.id, cap.status, "known not to work; never called")
        if cap.id in self.allow_untested:
            logger.warning(
                "capability %r (status %r) called through an explicit check-script override",
                cap.id,
                cap.status,
            )
            self.overrides_used.append(cap.id)
            return cap
        raise CapabilityNotTestedError(
            cap.id,
            cap.status,
            "only 'tested' capabilities may be called; verify it on the user's machine first",
        )
