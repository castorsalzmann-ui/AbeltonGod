"""STUB laser engine for tests and screenshots only. It is NOT the laser engine of issue #416.

A seeded sine sweep with an exponential decay, driven by the adapter parameters. It exists so
the blaster window can be tested before ``audio_engine.laser`` is merged. The normal start of
the window never uses it; ``python -m gui.blaster --screenshot`` may, and then says so in the
window title. It makes no statement about how a real shot sounds.
"""

from __future__ import annotations

from typing import Any

import numpy as np


class StubLaserEngine:
    sample_rate = 22050
    is_stub = True

    def __init__(self, stereo: bool = False) -> None:
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
        if self.stereo:
            w = float(params.get("stereo_width", 0.5))
            return np.stack([x, x * (1.0 - 0.5 * w)], axis=1)
        return x
