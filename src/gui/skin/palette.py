"""Cyber palette of the Goa skin: near-black blue-violet body, neon cyan and magenta accents,
cold chrome for the border. Plain hex strings; no Qt import so tests and docs can read them."""

from __future__ import annotations

BODY_TOP = "#0a0a1c"
BODY_BOTTOM = "#150b2a"
PANEL = "#12122a"
FIELD = "#0b0b1e"
TEXT = "#e2e9ff"
MUTED = "#8f95c0"
CYAN = "#19e6ff"
MAGENTA = "#ff2bd6"
ERROR = "#ff6b8a"

# Chrome gradient stops (position, colour). The lit set is used by facets that face the light
# (top-left), the shade set by facets that face away; real facets blend between the two.
# Each set has the same positions: base -> tip.
CHROME_POSITIONS = (0.0, 0.30, 0.52, 0.66, 0.86, 1.0)
CHROME_LIT = ("#7c8aa6", "#c9d6ea", "#2a3148", "#9fb0cc", "#f2f8ff", "#ffffff")
CHROME_SHADE = ("#05060c", "#2a3248", "#0a0c16", "#4d5a76", "#97a8c8", "#e6f0ff")

SPECULAR = "#ffffff"
RIM_COOL = "#7fe9ff"
RIM_WARM = "#ff7fe6"

# Rail (the ring the thorns grow from).
RAIL_POSITIONS = (0.0, 0.18, 0.42, 0.55, 0.78, 1.0)
RAIL_STOPS = ("#e9f2ff", "#8c9bb8", "#141828", "#566480", "#c8d6ee", "#6f7d9a")
