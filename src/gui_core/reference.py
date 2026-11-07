"""Logic of the "Referenz" page (#480, first slice of #58; no Qt).

Measures a user WAV with :mod:`audio_engine.reference`, shows the values next to the nearest
kick candidate, and puts that candidate's values into the kick form. The texts say what the
numbers are and are not: measured values of the file, no judgement of the sound (D-032).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_engine.reference import (
    MAX_SECONDS,
    Candidate,
    ReferenceAudioError,
    ReferenceMatch,
    match_reference_file,
)

# (measure, German label, unit, decimals)
ROWS: tuple[tuple[str, str, str, int], ...] = (
    ("fundamental_hz", "Grundton im Ausklang", "Hz", 1),
    ("body_hz", "Tonhöhe im Körper (10–70 ms)", "Hz", 1),
    ("decay_20db_ms", "Abfall um 20 dB", "ms", 0),
    ("decay_40db_ms", "Abfall um 40 dB", "ms", 0),
    ("sub_share", "Energieanteil unter 100 Hz", "%", 0),
    ("click_share", "Anteil über 1 kHz (erste 10 ms)", "%", 0),
)

# Kick-form fields taken from the candidate. sample_rate / bit_depth stay as the settings say;
# variants stays 1. The rest of a candidate equals its preset (variants spread only these).
APPLIED_FIELDS = ("seed", "pitch_start_hz", "pitch_end_hz", "pitch_decay_ms", "amp_decay_ms",
                  "click_level", "click_tone_hz", "drive", "tone")

INTRO = (
    "Wähle eine eigene Kick-WAV (oder zieh sie hierher). Das Programm misst sie mit derselben "
    "Analyse wie die gerenderten Kicks und sucht unter den Presets und je acht festen "
    "Varianten den Kandidaten mit den nächsten Messwerten. Das sind Zahlen, kein Klangurteil: "
    "ob der Kandidat nach deiner Referenz klingt, entscheidet nur dein Ohr. Die Datei bleibt "
    "auf deinem Rechner und wird nicht kopiert.")
LIMITS = (
    f"Grenzen: Mono oder Stereo (als Mono-Summe), 16/24 Bit PCM, 44,1 oder 48 kHz, höchstens "
    f"{MAX_SECONDS:g} s; ein Loop wird nicht in Schläge zerlegt. Gemessen ab dem Einsatz (10 % "
    "der Spitze). „–“ heißt: in der Datei nicht messbar (z. B. kein Grundton bei sehr kurzem "
    "Ausklang, oder der Pegel fällt nicht weit genug, bevor die Datei endet). Die Abfallzeiten "
    "kommen aus einer 40-ms-Hüllkurve und sind nicht dasselbe wie „Abklingzeit“ im Kick-"
    "Formular; ein abgeschnittener Ausklang verkürzt sie.")


@dataclass(frozen=True)
class ReferenceOutcome:
    path: Path
    match: ReferenceMatch | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.match is not None


def analyse_reference(path: str | Path) -> ReferenceOutcome:
    """Run in a worker thread; never raises."""
    path = Path(path)
    try:
        return ReferenceOutcome(path, match=match_reference_file(path))
    except ReferenceAudioError as exc:
        return ReferenceOutcome(path, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - the page shows it instead of losing the thread
        return ReferenceOutcome(path, error=f"Analyse fehlgeschlagen: {exc}")


def value_text(name: str, value: float | None) -> str:
    if value is None:
        return "–"
    for key, _, unit, decimals in ROWS:
        if key == name:
            shown = value * 100.0 if unit == "%" else value
            return f"{shown:.{decimals}f} {unit}".replace(".", ",")
    return str(value)


def table_rows(match: ReferenceMatch) -> list[tuple[str, str, str, str]]:
    """(label, reference, nearest candidate, distance) per measure."""
    out = []
    for key, label, _, _ in ROWS:
        out.append((label, value_text(key, match.reference.get(key)),
                    value_text(key, match.nearest.measures.get(key)),
                    f"{match.distances[key]:.2f}".replace(".", ",")))
    return out


def file_text(match: ReferenceMatch, path: Path) -> str:
    r = match.reference
    chans = "Mono" if r["channels"] == 1 else "Stereo (Mono-Summe)"
    return (f"{path.name}: {r['length_ms']:.0f} ms, {r['sample_rate']} Hz, {r['bit_depth']} Bit, "
            f"{chans}")


def candidate_text(match: ReferenceMatch) -> str:
    c = match.nearest
    which = "das Preset selbst" if c.variant == 0 else f"Variante {c.variant} des Presets"
    total = f"{match.total:.2f}".replace(".", ",")
    return (f"Nächster Kandidat: {c.name} ({which} „{c.preset}“), Gesamtabstand {total}. "
            "Abstand je Messwert: 1 ≈ ein Halbton (Körper: zwei), 25 % Zeit oder 5 "
            "Prozentpunkte; ein Wert, der nur auf einer Seite messbar ist, zählt 3.")


def _text(value: Any) -> str:
    return repr(value) if isinstance(value, float) else str(value)


def apply_to_form(model: Any, candidate: Candidate) -> list[str]:
    """Load the candidate's preset into the kick form, then its values of
    :data:`APPLIED_FIELDS`. Returns the fields that differ from the preset."""
    if model.category != "kick":
        raise ValueError("Referenz-Werte gehören in das Kick-Formular.")
    model.set_preset(candidate.preset)
    changed = []
    names = set(model.specs_names())
    for name in APPLIED_FIELDS:
        if name not in candidate.params or name not in names:
            continue
        text = _text(candidate.params[name])
        if model.text.get(name) != text or name not in model.active:
            changed.append(name)
        model.set_text(name, text)
        model.set_active(name, True)
    return changed
