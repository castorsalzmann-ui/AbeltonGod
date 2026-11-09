"""Rough render-time estimate and length line for an atmos request (#533). No Qt.

The atmos engine's cost grows with the loop length N and with how many periods each recursive
stage runs (seamless mode: warm-up P plus the kept and the check period, ``$comment`` point 8;
oneshot: once over the file), plus a per-grain cost for the granular kind. The constants below
were MEASURED ONCE in the development container (Xeon 2.3 GHz, Python 3.13, NumPy 2.5;
32 bars at 107 BPM and 48 kHz = 71.8 s, one process, 2026-11-09, other agents running on the
same 2 cores) and are rough: on the user's PC the time may be half or twice as long. The
estimate never blocks a render; it only produces a German note.
"""

from __future__ import annotations

from typing import Any

# seconds per frame (per channel / per period where named), measured as described above
BASE_NOISE_S = 2.4e-6  # noise source, FFT filters, mono_below, peak scaling (noise kinds)
BASE_TONAL_S = 1.5e-6  # the same with a drone / metal source (bin-locked partials)
FILTER_S = 0.66e-6  # moving state-variable filter, per frame, channel and period
REVERB_S = 0.57e-6  # reverb, per frame (both channels) and period
DRIVE_S = 2.9e-6  # 8x oversampled drive, per frame (both channels)
GRAIN_S = 400e-6  # per grain (draws, index arithmetic)
GRAIN_FRAME_S = 0.07e-6  # per grain frame
WARN_S = 10.0  # from this estimate on the page shows a note


def _engine():
    from audio_engine import atmos

    return atmos


def estimate_seconds(p: dict[str, Any], variants: int = 1) -> float:
    """Rough render time of a RESOLVED atmos request times ``variants``."""
    a = _engine()
    n = a.loop_samples(p)
    sr = int(p["sample_rate"])
    seamless = p["loop_mode"] == "seamless"
    frames = n if seamless else a.file_samples(p)
    tonal = p["kind"] == "drone" or (p["kind"] == "granular"
                                     and p["granular_source"] in ("drone", "metal"))
    t = frames * (BASE_TONAL_S if tonal else BASE_NOISE_S)
    if p["filter_mode"] != "off":
        periods = a.preroll_filter(p) + 2 if seamless else 1
        t += FILTER_S * 2 * frames * periods
    if p["reverb_mix"] > 0:
        periods = a.preroll_reverb(p) + 2 if seamless else 1
        t += REVERB_S * frames * periods
    if p["drive"] > 0:
        t += DRIVE_S * frames
    if p["kind"] == "granular":
        count = max(1, round(float(p["grain_density"]) * n / sr))
        size = round(float(p["grain_ms"]) * sr / 1000.0)
        t += count * (GRAIN_S + GRAIN_FRAME_S * size)
    return t * max(1, int(variants))


def resolved(model: Any) -> dict[str, Any] | None:
    """The engine's resolved form of an atmos ``CategoryFormModel``; None while the form has a
    problem (the page shows that problem instead)."""
    if model.category != "atmos" or model.field_issues():
        return None
    a = _engine()
    try:
        return a.resolve_atmos_params(model.build_request())
    except (a.AtmosParamsError, ValueError):
        return None


def cost_note(model: Any) -> str:
    """The render-time note for an atmos form, or "" (short estimate or a form problem)."""
    p = resolved(model)
    if p is None:
        return ""
    return warning_text(p, int(p.get("variants", 1)))


def warning_text(p: dict[str, Any], variants: int = 1) -> str:
    """German note for the page, or "" when the estimate is below :data:`WARN_S`."""
    est = estimate_seconds(p, variants)
    if est < WARN_S:
        return ""
    amount = f"etwa {round(est):d} s" if est < 120 else f"etwa {est / 60.0:.0f} min"
    text = (f"Hinweis: geschätzte Renderzeit {amount} (grobe Schätzung, auf diesem Rechner "
            f"kann es die Hälfte oder das Doppelte sein). Lange Dateien brauchen länger; "
            f"weniger Takte oder ein höheres Tempo gehen schneller.")
    if p["kind"] == "granular" and float(p["grain_density"]) > 60:
        text += " Viele Grains pro Sekunde sind langsam: eine kleinere Grain-Dichte geht schneller."
    if variants > 1:
        text += f" {variants} Varianten zählen mit."
    return text


def _sec(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def length_text(model: Any) -> str:
    """One German line about the file: bars at the tempo, its length in seconds, loop or
    one-shot. "" while the form has a problem."""
    p = resolved(model)
    if p is None:
        return ""
    a = _engine()
    bars = p["bars"]
    loop_s = 240.0 * bars / p["bpm"]
    head = f"{bars} {'Takt' if bars == 1 else 'Takte'} bei {p['bpm']:g} BPM = {_sec(loop_s)} s"
    if p["loop_mode"] == "seamless":
        exact = a.loop_samples(p) == a.loop_samples_exact(p)
        tail = "" if exact else " Bei diesem Tempo bis zu ½ Sample neben der Taktlänge."
        return (f"{head}, nahtlose Schleife. Ein-/Ausblenden und Ausklang wirken nur bei "
                f"oneshot.{tail}")
    file_s = a.file_ms(p) / 1000.0
    return (f"{head}, One-Shot mit Ein- und Ausblenden; Datei {_sec(file_s)} s mit "
            f"{p['tail_beats']:g} Beats Ausklang.")
