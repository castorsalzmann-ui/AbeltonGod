"""Sound categories the engine can render, with their engine identity (D-025, #229, #230).

``sample-metadata.schema.json`` v0.2 names two categories, ``kick`` and ``clap``. Each category
carries its own engine name and version, so a byte change in one never invalidates the sidecars
of another. Only categories that have a renderer are *registered* here: kick, clap
(#231) and hat (#270). A category the contract names but that is not registered raises
:class:`CategoryUnavailable` before any parameter of that category is looked at.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import ENGINE_NAME, ENGINE_VERSION, analysis, clap, hat, kick
from .params import resolve_kick_params

# Categories named by contracts/sample-metadata.schema.json (a test compares with the file).
CONTRACT_CATEGORIES = ("kick", "clap", "hat")


class CategoryUnavailable(ValueError):
    """The category is unknown, or it is in the contract but this engine has no renderer for it."""


@dataclass(frozen=True)
class Category:
    """Everything the generic write / re-render path needs to know about one category."""

    name: str
    engine_name: str
    engine_version: str
    metadata_schema_version: str  # sidecar schema_version this category writes
    default_stem: str  # file name used when a name has no usable characters
    resolve: Callable[[dict[str, Any]], dict[str, Any]]
    render: Callable[[dict[str, Any]], tuple[np.ndarray, dict[str, Any]]]  # (audio, resolved)
    analyse: Callable[[np.ndarray, int], dict[str, Any]]

    @property
    def engine(self) -> dict[str, str]:
        return {"name": self.engine_name, "version": self.engine_version}


_REGISTRY: dict[str, Category] = {
    "kick": Category(
        name="kick",
        engine_name=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        metadata_schema_version="0.1",
        default_stem="kick",
        resolve=resolve_kick_params,
        # Looked up at call time (not bound here) so the test harness' render counter and cache,
        # which replace ``kick.render_kick``, keep working through the generic path.
        render=lambda params: kick.render_kick(params),
        analyse=lambda audio, sr: analysis.analyse(audio, sr),
    ),
    "clap": Category(
        name="clap",
        engine_name=clap.CLAP_NAME,
        engine_version=clap.CLAP_VERSION,
        metadata_schema_version="0.2",
        default_stem="clap",
        resolve=clap.resolve_clap_params,
        render=lambda params: clap.render_clap(params),
        analyse=lambda audio, sr: analysis.analyse_nonpitched(audio, sr),
    ),
    "hat": Category(
        name="hat",
        engine_name=hat.HAT_NAME,
        engine_version=hat.HAT_VERSION,
        metadata_schema_version="0.2",
        default_stem="hat",
        resolve=hat.resolve_hat_params,
        render=lambda params: hat.render_hat(params),
        analyse=lambda audio, sr: analysis.analyse_nonpitched(audio, sr),
    ),
}


def get_category(name: str) -> Category:
    """The registered category ``name``; :class:`CategoryUnavailable` otherwise."""
    try:
        return _REGISTRY[name]
    except (KeyError, TypeError):
        if name in CONTRACT_CATEGORIES:
            raise CategoryUnavailable(
                f"category {name!r} is in the sample-metadata contract but this engine has no "
                "renderer for it yet"
            ) from None
        raise CategoryUnavailable(
            f"unknown category {name!r}; the contract knows {', '.join(CONTRACT_CATEGORIES)}"
        ) from None


def registered_categories() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def resolve_params(category: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate ``params`` against the category's contract; returns its resolved form."""
    return get_category(category).resolve(params)
