"""Rhythm section of the Goa arrangement: kick, bass and hat come from the existing engines.

D-027: the Goa plugin (``goa_patterns``: lead, arp, pad, pluck) owns only melodic material.
The rhythm tracks are taken from the sample engines and their presets:

* the one-shots are rendered with ``render_sample_wav`` from engine presets (kick preset,
  bass preset such as ``goa-roll-medium``, hat preset) and written next to the MIDI file;
* the bass note length in the MIDI is the bass preset's own ``gate_ms`` (converted to beats at
  the track tempo, always shorter than the gap to the next note), so the MIDI gate and the
  rendered one-shot agree;
* the rhythm positions of the bass are the ``roll`` option of ``goa_patterns.bass_line``
  (``off_kick_16th``, ``offbeat_8th``, ``offbeat_ghost``, ``gallop``, ``triplet_gallop``).

No voice is synthesised in this module. Nothing here is verified in Live and no sound claim
is made. Preset names and rhythm choices are options; defaults are only defaults.
"""

from __future__ import annotations

from typing import Any

from audio_engine import acid_midi
from audio_engine.bass import resolve_bass_params
from audio_engine.io import render_sample_wav
from audio_engine.presets import load_preset, preset_names

PPQ = acid_midi.PPQ
KICK_PITCH, HAT_CLOSED, HAT_PEDAL, SHAKER = 36, 42, 44, 70
GHOST_VELOCITY = 70  # off-beat-ghost notes that are not the off-beat 8th (default, not measured)

DEFAULT_KICK_PRESET = "dense"
DEFAULT_BASS_PRESET = "goa-roll-medium"
DEFAULT_HAT_PRESET = "closed-std"
SAMPLE_DIR = "samples"


def kick_pattern() -> dict[str, Any]:
    return {"length_beats": 4,
            "notes": hits(KICK_PITCH, [0.0, 1.0, 2.0, 3.0], 0.25, 110)}


def hits(pitch: int, starts: list[float], dur: float, vel: int) -> list[dict[str, Any]]:
    return [{"pitch": pitch, "start": s, "duration": dur, "velocity": vel} for s in starts]


def perc_pattern(energy: float) -> dict[str, Any]:
    """Off-beat closed hat always; ghost 16ths from energy 0.5; shaker 16ths from 0.8."""
    notes = hits(HAT_CLOSED, [b + 0.5 for b in range(4)], 0.125, 85)
    if energy >= 0.5:
        notes += hits(HAT_PEDAL, [b + o for b in range(4) for o in (0.25, 0.75)], 0.0625, 55)
    if energy >= 0.8:
        notes += hits(SHAKER, [i * 0.25 for i in range(16)], 0.0625, 45)
    return {"length_beats": 4, "notes": notes}


def resolve_kit(
    kick_preset: str = DEFAULT_KICK_PRESET, bass_preset: str = DEFAULT_BASS_PRESET,
    hat_preset: str = DEFAULT_HAT_PRESET,
) -> dict[str, dict[str, Any]]:
    """Validate the preset names and return ``{category: {"preset", "params"}}``."""
    kit: dict[str, dict[str, Any]] = {}
    for cat, name in (("kick", kick_preset), ("bass", bass_preset), ("hat", hat_preset)):
        if not isinstance(name, str) or name not in preset_names(cat):
            raise ValueError(f"{cat} preset must be one of {preset_names(cat)}")
        kit[cat] = {"preset": name, "params": load_preset(name, cat)}
    return kit


def bass_gate_ms(kit: dict[str, dict[str, Any]]) -> float:
    return float(resolve_bass_params(dict(kit["bass"]["params"]))["gate_ms"])


def bass_note(kit: dict[str, dict[str, Any]]) -> int:
    return int(resolve_bass_params(dict(kit["bass"]["params"]))["note"])


def shape_bass(pattern: dict[str, Any], roll: str, gate_ms: float, bpm: float) -> dict[str, Any]:
    """Give every bass note the preset gate (capped below the gap to the next onset) and, for
    ``offbeat_ghost``, ``GHOST_VELOCITY`` to all notes that are not on the off-beat 8th."""
    gate = max(1, round(gate_ms / 1000.0 * bpm / 60.0 * PPQ))  # ticks
    notes = sorted(pattern["notes"], key=lambda n: n["start"])
    out = []
    for i, n in enumerate(notes):
        start_t = round(n["start"] * PPQ)
        if i + 1 < len(notes):
            gap = round(notes[i + 1]["start"] * PPQ) - start_t
        else:
            gap = round(pattern["length_beats"] * PPQ) - start_t
        dur_t = max(1, min(gate, gap - 1))
        vel = n["velocity"]
        if roll == "offbeat_ghost" and start_t % PPQ != PPQ // 2:
            vel = min(vel, GHOST_VELOCITY)
        out.append({"pitch": n["pitch"], "start": n["start"], "duration": dur_t / PPQ,
                    "velocity": vel})
    return {"length_beats": pattern["length_beats"], "notes": out}


def render_kit(kit: dict[str, dict[str, Any]]) -> list[tuple[str, bytes, str]]:
    """Render the one-shots with the engines: ``[(file name, WAV bytes, description)]``."""
    files = []
    for cat in ("kick", "bass", "hat"):
        name = kit[cat]["preset"]
        wav, _audio, _resolved = render_sample_wav(cat, dict(kit[cat]["params"]))
        files.append((f"{cat}_{name}.wav", wav, f"{cat} engine, preset `{name}`"))
    return files
