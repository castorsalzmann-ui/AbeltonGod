"""Rough render-time estimate for an fx request (#503), shown before rendering. No Qt.

The fx engine's cost grows with the file length, the filter stages, the drive stage, and above
all with the tone layer's partial count ``0.45 * sr / tone_hz`` (saw, square and metal are
additive; a 72 s saw at 20 Hz took ~42 s in review). The constants below were MEASURED ONCE in
the development container (Xeon 2.3 GHz, Python 3.13, NumPy 2.5; 32 s files at 48 kHz, one
process per case, 2026-11-07) and are rough: on the user's PC the time may be half or twice
as long. The estimate never blocks a render; it only produces a German note.
"""

from __future__ import annotations

from typing import Any

# seconds per frame (or per frame and channel / partial), measured as described above
BASE_S = 0.15e-6  # noise, curves, peak scaling
FILTER_S = 0.40e-6  # one state-variable filter stage, per channel
TONE_S = 0.20e-6  # tone curves and envelope
PARTIAL_S = 10e-9  # one partial of saw / square / metal, per frame
DRIVE_S = 0.97e-6  # 8x oversampled drive, per channel
REVERB_S = 0.25e-6
ECHO_S = 0.30e-6
NYQUIST_SHARE = 0.45
METAL_RATIOS = (1.0, 304.4 / 205.3, 369.6 / 205.3, 522.7 / 205.3, 540.0 / 205.3,
                800.0 / 205.3)  # hat metal_bank partials over the lowest one
WARN_S = 10.0  # from this estimate on the page shows a note


def _frames(p: dict[str, Any]) -> int:
    return int(round((p["length_beats"] + p["tail_beats"]) * 60.0 * p["sample_rate"]
                     / p["bpm"]))


def partials(p: dict[str, Any]) -> float:
    """Partial count the tone layer computes per frame (0 when the tone is off)."""
    if p["tone_level"] <= 0:
        return 0.0
    f = min(float(p["tone_start_hz"]), float(p["tone_end_hz"]))
    k = NYQUIST_SHARE * p["sample_rate"] / f
    if p["tone_wave"] == "sine":
        return 1.0
    if p["tone_wave"] == "metal":
        return sum(k / r for r in METAL_RATIOS)
    return k


def estimate_seconds(p: dict[str, Any], variants: int = 1) -> float:
    """Rough render time of a RESOLVED fx request times ``variants``."""
    n = _frames(p)
    per_frame = BASE_S
    if p["noise_level"] > 0:
        channels = 1 if p["stereo_width"] == 0 else 2
        stages = 2 if p["filter_mode"] == "hp_lp" else 1
        per_frame += FILTER_S * channels * stages
    if p["tone_level"] > 0:
        per_frame += TONE_S + PARTIAL_S * partials(p)
    if p["drive"] > 0:
        per_frame += 2 * DRIVE_S
    if p["reverb_mix"] > 0:
        per_frame += REVERB_S
    if p["echo_mix"] > 0:
        per_frame += ECHO_S
    return n * per_frame * max(1, int(variants))


def cost_note(model: Any) -> str:
    """The note for a ``CategoryFormModel`` of category fx: "" while the form has a problem
    (the page shows that problem instead) or the estimate is short."""
    if model.category != "fx" or model.field_issues():
        return ""
    from audio_engine.fx import FxParamsError, resolve_fx_params

    try:
        p = resolve_fx_params(model.build_request())
    except (FxParamsError, ValueError):
        return ""
    return warning_text(p, int(p.get("variants", 1)))


def warning_text(p: dict[str, Any], variants: int = 1) -> str:
    """German note for the page, or "" when the estimate is below :data:`WARN_S`."""
    est = estimate_seconds(p, variants)
    if est < WARN_S:
        return ""
    minutes = est / 60.0
    amount = f"etwa {round(est):d} s" if est < 120 else f"etwa {minutes:.0f} min"
    text = (f"Hinweis: geschätzte Renderzeit {amount} (grobe Schätzung, auf diesem Rechner "
            f"kann es die Hälfte oder das Doppelte sein).")
    if partials(p) > 50:
        text += (" Tiefe Töne mit Sägezahn, Rechteck oder Metall sind langsam: ein höherer "
                 "Ton-Start/-Ende oder Sinus geht schneller.")
    if variants > 1:
        text += f" {variants} Varianten zählen mit."
    return text
