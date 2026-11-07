"""Sound categories the engine can render, with their engine identity (D-025, #229, #230).

``sample-metadata.schema.json`` v0.2 names two categories, ``kick`` and ``clap``. Each category
carries its own engine name and version, so a byte change in one never invalidates the sidecars
of another. Only categories that have a renderer are *registered* here: kick, clap
(#231), hat (#270), snare (#308), rim (#321), bass (#328), laser (#416) and perc (#475). A
category the contract names but that is not registered raises :class:`CategoryUnavailable` before
any parameter of that category is looked at.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import (
    ENGINE_NAME,
    ENGINE_VERSION,
    analysis,
    bass,
    clap,
    hat,
    kick,
    laser,
    perc,
    rim,
    snare,
)
from .params import resolve_kick_params

# Categories named by contracts/sample-metadata.schema.json (a test compares with the file).
CONTRACT_CATEGORIES = ("kick", "clap", "hat", "snare", "rim", "bass", "laser", "perc", "fx")


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
    # Optional: features that need the resolved parameters (bass: the gate window, #328).
    analyse_resolved: Callable[[np.ndarray, int, dict[str, Any]], dict[str, Any]] | None = None
    # Optional: engine version by parameters (laser: 0.1 requests keep reporting 0.1.0 because
    # their bytes did not change, so existing sidecars still re-render, #425).
    version_for: Callable[[dict[str, Any]], str] | None = None

    def features(self, audio: np.ndarray, resolved: dict[str, Any]) -> dict[str, Any]:
        """Sidecar features of a render of this category."""
        sr = resolved["sample_rate"]
        if self.analyse_resolved is not None:
            return self.analyse_resolved(audio, sr, resolved)
        return self.analyse(audio, sr)

    @property
    def engine(self) -> dict[str, str]:
        return {"name": self.engine_name, "version": self.engine_version}

    def engine_for(self, params: dict[str, Any]) -> dict[str, str]:
        """Engine identity to write into / expect from a sidecar with these parameters."""
        if self.version_for is None:
            return self.engine
        return {"name": self.engine_name, "version": self.version_for(params)}


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
    "snare": Category(
        name="snare",
        engine_name=snare.SNARE_NAME,
        engine_version=snare.SNARE_VERSION,
        metadata_schema_version="0.2",
        default_stem="snare",
        resolve=snare.resolve_snare_params,
        render=lambda params: snare.render_snare(params),
        analyse=lambda audio, sr: analysis.analyse_nonpitched(audio, sr),
    ),
    "rim": Category(
        name="rim",
        engine_name=rim.RIM_NAME,
        engine_version=rim.RIM_VERSION,
        metadata_schema_version="0.2",
        default_stem="rim",
        resolve=rim.resolve_rim_params,
        render=lambda params: rim.render_rim(params),
        analyse=lambda audio, sr: analysis.analyse_nonpitched(audio, sr),
    ),
    "laser": Category(
        name="laser",
        engine_name=laser.LASER_NAME,
        engine_version=laser.LASER_VERSION,
        version_for=laser.engine_version_for,
        metadata_schema_version="0.2",
        default_stem="laser",
        resolve=laser.resolve_laser_params,
        render=lambda params: laser.render_laser_category(params),
        analyse=laser.analyse_laser,
    ),
    "bass": Category(
        name="bass",
        engine_name=bass.BASS_NAME,
        engine_version=bass.BASS_VERSION,
        metadata_schema_version="0.2",
        default_stem="bass",
        resolve=bass.resolve_bass_params,
        render=lambda params: bass.render_bass(params),
        # Not analysis.analyse: its tail window lands in the release of a gated note.
        analyse=bass.analyse_basic,
        analyse_resolved=bass.analyse_bass,
    ),
    "perc": Category(
        name="perc",
        engine_name=perc.PERC_NAME,
        engine_version=perc.PERC_VERSION,
        metadata_schema_version="0.2",
        default_stem="perc",
        resolve=perc.resolve_perc_params,
        render=lambda params: perc.render_perc(params),
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
