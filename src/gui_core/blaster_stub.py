"""STUB laser engine for fast tests only. It is NOT the laser engine (``audio_engine.laser``).

A seeded sine sweep with an exponential decay that follows the contract fields
``pitch_start_hz``, ``pitch_end_hz``, ``length_ms`` and ``stereo_width``. It exists so window
tests do not pay the real engine's render time. The normal start of the window never uses it,
and it makes no statement about how a real shot sounds.
"""

from __future__ import annotations

from typing import Any

import numpy as np


class StubLaserEngine:
    sample_rate = 48000
    is_stub = True

    def __init__(self, stereo: bool = True) -> None:
        self.stereo = stereo
        self.calls: list[tuple[dict[str, Any], int]] = []

    def render(self, params: dict[str, Any], seed: int) -> np.ndarray:
        self.calls.append((dict(params), int(seed)))
        n = max(16, int(params["length_ms"] / 1000 * self.sample_rate))
        t = np.arange(n) / n
        f0, f1 = float(params["pitch_start_hz"]), float(params["pitch_end_hz"])
        f = f0 * (f1 / f0) ** t
        phase0 = np.random.default_rng(int(seed)).uniform(0, 2 * np.pi)
        x = np.sin(phase0 + 2 * np.pi * np.cumsum(f) / self.sample_rate)
        x = x * np.exp(-5.0 * t) * 0.8
        if not self.stereo:
            return x
        w = float(params.get("stereo_width", 0.0))
        return np.stack([x, x * (1.0 - 0.5 * w)], axis=1)
