"""Rhythm section of the Goa arrangement: ONE engine-side source for kick, bass, hat, snare,
clap and rim (D-027, #392).

The Goa plugin (``goa_patterns``: lead, arp, pad, pluck) owns only melodic material. Every
rhythm note pattern of the arrangement is produced here, from engine presets:

* one-shots are rendered with ``render_sample_wav`` from engine presets (kick, bass such as
  ``goa-roll-medium``, hat, snare, clap, rim) and written next to the MIDI file;
* bass: roll positions (``ROLL_GRID``, ghost shares, triplet slots) and the pitch pool live
  in this module; ``goa_patterns.bass_line`` reads them. The note length is the bass preset's
  own ``gate_ms`` (``shape_bass``);
* hat: the note pitch (closed 42 / open 46), the note length and whether 16th ghost hits fit
  between the off-beat hits are derived from the hat preset's ``decay_ms`` (``hat_spec``);
* snare, clap, rim: hit positions are a configurable option (``PERC_PATTERNS``); the sound
  comes from the chosen preset (rendered one-shot). A voice is off with preset or pattern
  ``"none"``;
* kick: four on the floor.

What is NOT preset-derived: kick, snare, clap, rim positions, the bass roll positions and
pitches, all velocities, the energy thresholds. These are defaults and options, not measured
facts about Goa. Nothing here is verified in Live and no sound claim is made.
"""

from __future__ import annotations

from typing import Any

from audio_engine import acid_midi
from audio_engine.bass import resolve_bass_params
from audio_engine.io import render_sample_wav
from audio_engine.presets import load_preset, preset_names

PPQ = acid_midi.PPQ
STEPS_PER_BAR = 16
KICK_PITCH = 36
SNARE_PITCH, CLAP_PITCH, RIM_PITCH = 38, 39, 37
HAT_CLOSED, HAT_OPEN = 42, 46
GHOST_VELOCITY = 70  # off-beat-ghost notes that are not the off-beat 8th (default, not measured)

DEFAULT_KICK_PRESET = "dense"
DEFAULT_BASS_PRESET = "goa-roll-medium"
DEFAULT_HAT_PRESET = "closed-std"
DEFAULT_SNARE_PRESET = "default"
DEFAULT_CLAP_PRESET = "default"
DEFAULT_RIM_PRESET = "rim"
SAMPLE_DIR = "samples"
NONE = "none"

# ------------------------------------------------------------------ bass roll (single source)

TRIPLET_GALLOP = "triplet_gallop"
# roll -> (steps used inside a bar, weight per step % 4, default density). The default roll
# is the original one; its entries must not change (byte-identity tests in goa_patterns).
ROLL_GRID: dict[str, tuple[tuple[int, ...], dict[int, float], float]] = {
    "off_kick_16th": (tuple(s for s in range(STEPS_PER_BAR) if s % 4 != 0),
                      {2: 3.0, 3: 2.0, 1: 1.0}, 0.75),
    # one note on the off-beat 8th of every beat (step % 4 == 2); density 1.0 keeps all four
    "offbeat_8th": (tuple(s for s in range(STEPS_PER_BAR) if s % 4 == 2), {2: 1.0}, 1.0),
    # 16th-grid gallop: the 16th right after the kick and the 16th right before the next one
    "gallop": (tuple(s for s in range(STEPS_PER_BAR) if s % 4 in (1, 3)),
               {1: 1.5, 3: 1.5}, 1.0),
}
BASS_POOL = (0, 7, 1, 4)  # scale-degree indices: root, octave (7), 2nd degree, fifth
BASS_POOL_W = (6.0, 2.0, 1.5, 1.0)
TRIPLET_GATE_BEATS = 0.2
TRIPLET_VELOCITY, TRIPLET_ACCENT_VELOCITY = 100, 127
# offbeat_ghost: share of beats that carry the off-beat 8th (step 2) and each neighbouring
# 16th (steps 1 and 3). PROPOSAL values from docs/research/2026-11-03_goa-reference-
# measurements.md (50-65 % and 28-38 %, mid-points; low confidence), defaults only.
GHOST_MAIN_SHARE, GHOST_SIDE_SHARE = 0.575, 0.33

# ------------------------------------------------------------------ percussion options

# pattern name -> sixteenth steps inside one 4/4 bar
PERC_PATTERNS: dict[str, tuple[int, ...]] = {
    "backbeat": (4, 12),                    # beats 2 and 4
    "beat_4": (12,),                        # beat 4 only
    "offbeat_8th": (2, 6, 10, 14),          # between the kicks
    "sixteenth_offbeat": (3, 7, 11, 15),    # last 16th of each beat
}
PERC_PATTERN_CHOICES = (NONE, *PERC_PATTERNS)
# voice -> (MIDI pitch, velocity, first section energy that plays it, default pattern)
PERC_VOICES: dict[str, tuple[int, int, float, str]] = {
    "snare": (SNARE_PITCH, 100, 0.62, "backbeat"),
    "clap": (CLAP_PITCH, 90, 0.46, "backbeat"),
    "rim": (RIM_PITCH, 70, 0.38, "sixteenth_offbeat"),
}
DEFAULT_PRESETS = {"kick": DEFAULT_KICK_PRESET, "bass": DEFAULT_BASS_PRESET,
                   "hat": DEFAULT_HAT_PRESET, "snare": DEFAULT_SNARE_PRESET,
                   "clap": DEFAULT_CLAP_PRESET, "rim": DEFAULT_RIM_PRESET}

# hat: a preset with decay_ms at or above this is played as an open hat (closed presets
# shipped: 35-120 ms, open: 250-500 ms; the boundary is a default, not a measurement)
HAT_OPEN_DECAY_MS = 200.0
HAT_MAIN_VELOCITY, HAT_GHOST_VELOCITY, HAT_DENSE_VELOCITY = 85, 55, 45
HAT_GHOST_ENERGY, HAT_DENSE_ENERGY = 0.5, 0.8


def hits(pitch: int, starts: list[float], dur: float, vel: int) -> list[dict[str, Any]]:
    return [{"pitch": pitch, "start": s, "duration": dur, "velocity": vel} for s in starts]


def kick_pattern() -> dict[str, Any]:
    return {"length_beats": 4, "notes": hits(KICK_PITCH, [0.0, 1.0, 2.0, 3.0], 0.25, 110)}


def perc_part(voice: str, pattern: str) -> dict[str, Any]:
    """One bar of snare / clap / rim hits at the steps of ``PERC_PATTERNS[pattern]``."""
    pitch, vel, _min_e, _default = PERC_VOICES[voice]
    steps = PERC_PATTERNS[pattern]
    return {"length_beats": 4, "notes": hits(pitch, [s / 4 for s in steps], 0.125, vel)}


def perc_active(voice: str, energy: float) -> bool:
    return energy >= PERC_VOICES[voice][2]


# ------------------------------------------------------------------ kit / presets


def resolve_kit(
    kick_preset: str = DEFAULT_KICK_PRESET, bass_preset: str = DEFAULT_BASS_PRESET,
    hat_preset: str = DEFAULT_HAT_PRESET, snare_preset: str = DEFAULT_SNARE_PRESET,
    clap_preset: str = DEFAULT_CLAP_PRESET, rim_preset: str = DEFAULT_RIM_PRESET,
) -> dict[str, dict[str, Any]]:
    """Validate preset names and return ``{category: {"preset", "params"}}``. Snare, clap and
    rim may be ``"none"`` (voice off, absent from the result)."""
    kit: dict[str, dict[str, Any]] = {}
    for cat, name in (("kick", kick_preset), ("bass", bass_preset), ("hat", hat_preset),
                      ("snare", snare_preset), ("clap", clap_preset), ("rim", rim_preset)):
        optional = cat in PERC_VOICES
        if optional and name == NONE:
            continue
        if not isinstance(name, str) or name not in preset_names(cat):
            extra = f" or {NONE!r}" if optional else ""
            raise ValueError(f"{cat} preset must be one of {preset_names(cat)}{extra}")
        kit[cat] = {"preset": name, "params": load_preset(name, cat)}
    return kit


def check_pattern(voice: str, pattern: str) -> None:
    if pattern not in PERC_PATTERN_CHOICES:
        raise ValueError(f"{voice} pattern must be one of {list(PERC_PATTERN_CHOICES)}")


def active_voices(kit: dict[str, dict[str, Any]], patterns: dict[str, str]) -> list[str]:
    """Snare/clap/rim voices that are on: a preset in the kit and a pattern other than none."""
    return [v for v in PERC_VOICES if v in kit and patterns[v] != NONE]


def bass_gate_ms(kit: dict[str, dict[str, Any]]) -> float:
    return float(resolve_bass_params(dict(kit["bass"]["params"]))["gate_ms"])


def bass_note(kit: dict[str, dict[str, Any]]) -> int:
    return int(resolve_bass_params(dict(kit["bass"]["params"]))["note"])


# ------------------------------------------------------------------ bass


def line_to_native(line: dict[str, Any], max_length: int) -> dict[str, Any]:
    """acid_line (long) -> native arrangement pattern. Pure tick <-> beat conversion."""
    notes = acid_midi.line_to_notes(line, max_length=max_length)
    return {"length_beats": line["length"] * acid_midi.STEP_BEATS,
            "notes": [{"pitch": n.pitch, "start": n.start / PPQ,
                       "duration": (n.end - n.start) / PPQ, "velocity": n.velocity}
                      for n in notes]}


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


def bass_part(
    kit: dict[str, dict[str, Any]], roll: str, root_note: int, scale: str, bars: int,
    bpm: float, seed: int, energy: float,
) -> dict[str, Any]:
    """Bass pattern of one section: roll positions and pitches from this module's tables
    (through ``goa_patterns.bass_line``), note length from the bass preset's gate."""
    from audio_engine import goa_patterns  # lazy: goa_patterns imports this module

    if roll == TRIPLET_GALLOP:
        raw = goa_patterns.bass_triplet_gallop(root_note, scale, bars, 1.0, 0.2, seed, float(bpm))
    else:
        kw: dict[str, Any] = {}
        if roll == "off_kick_16th":
            kw["density"] = round(0.5 + 0.4 * energy, 2)
        raw = line_to_native(
            goa_patterns.bass_line(root_note, scale, bars, seed=seed, bpm=float(bpm), roll=roll,
                                   **kw), goa_patterns.LONG_MAX_LENGTH)
    return shape_bass(raw, roll, bass_gate_ms(kit), float(bpm))


# ------------------------------------------------------------------ hat


def hat_spec(kit: dict[str, dict[str, Any]], bpm: float) -> dict[str, Any]:
    """What the hat preset decides: ``open`` (decay_ms >= HAT_OPEN_DECAY_MS), MIDI ``pitch``,
    ``decay_ticks`` (the preset's decay at ``bpm``) and ``ghosts_fit`` (the decay is not longer
    than one 16th, so 16th hits do not ring into each other)."""
    from audio_engine.hat import resolve_hat_params

    decay_ms = float(resolve_hat_params(dict(kit["hat"]["params"]))["decay_ms"])
    ticks = max(1, round(decay_ms / 1000.0 * bpm / 60.0 * PPQ))
    is_open = decay_ms >= HAT_OPEN_DECAY_MS
    return {"open": is_open, "pitch": HAT_OPEN if is_open else HAT_CLOSED,
            "decay_ms": decay_ms, "decay_ticks": ticks,
            "ghosts_fit": ticks <= PPQ // 4}


def hat_part(kit: dict[str, dict[str, Any]], energy: float, bpm: float) -> dict[str, Any]:
    """One bar of hat hits. Off-beat 8ths always; the other 16ths of each beat at low velocity
    from ``HAT_GHOST_ENERGY`` (steps 1 and 3) and ``HAT_DENSE_ENERGY`` (step 0 as well), only
    if the preset's decay fits one 16th. Every note has the preset's decay as its length,
    cut one tick before the next hat hit. All hits use the one pitch the preset maps to."""
    spec = hat_spec(kit, bpm)
    hits_t = [(PPQ * b + PPQ // 2, HAT_MAIN_VELOCITY) for b in range(4)]
    if spec["ghosts_fit"]:
        if energy >= HAT_GHOST_ENERGY:
            hits_t += [(PPQ * b + o, HAT_GHOST_VELOCITY) for b in range(4)
                       for o in (PPQ // 4, 3 * PPQ // 4)]
        if energy >= HAT_DENSE_ENERGY:
            hits_t += [(PPQ * b, HAT_DENSE_VELOCITY) for b in range(4)]
    hits_t.sort()
    notes = []
    for i, (t, vel) in enumerate(hits_t):
        nxt = hits_t[i + 1][0] if i + 1 < len(hits_t) else 4 * PPQ
        dur = max(1, min(spec["decay_ticks"], nxt - t - 1))
        notes.append({"pitch": spec["pitch"], "start": t / PPQ, "duration": dur / PPQ,
                      "velocity": vel})
    return {"length_beats": 4, "notes": notes}


# ------------------------------------------------------------------ samples


def render_kit(kit: dict[str, dict[str, Any]]) -> list[tuple[str, bytes, str]]:
    """Render the one-shots with the engines: ``[(file name, WAV bytes, description)]``."""
    files = []
    for cat in ("kick", "bass", "hat", "snare", "clap", "rim"):
        if cat not in kit:
            continue
        name = kit[cat]["preset"]
        wav, _audio, _resolved = render_sample_wav(cat, dict(kit[cat]["params"]))
        files.append((f"{cat}_{name}.wav", wav, f"{cat} engine, preset `{name}`"))
    return files
