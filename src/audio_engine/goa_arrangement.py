"""Complete Goa-style track as ONE multitrack Standard MIDI File (format 1).

    python -m audio_engine.goa_arrangement --out DIR --seed 1 --bpm 145 [--dj-intro-outro 16]
        [--roll off_kick_16th|offbeat_8th|offbeat_ghost|gallop|triplet_gallop]
        [--intro-bars N] [--breakdowns 0-2] [--outro kick_on|kick_less --outro-bars N]
        [--melody-voices lead,arp,pad,pluck] [--density 0.5 | lead=0.5,arp=1]
        [--register 0 | lead=1,pad=-1] [--arp-pattern up|down|updown|random]
        [--progression 0,5,6,4]

Writes ``DIR/goa_seed<N>_<BPM>bpm.mid``, ``DIR/README.md`` (chosen options, what is in each
track, which Live instrument to put on it) and ``DIR/samples/`` (one-shots rendered by the
kick, bass, hat, snare, clap and rim engines from presets, see ``goa_rhythm``; a voice that
is switched off gets no WAV; ``--no-samples`` skips them all).
Nothing is sent to Live and nothing here is verified in Live: the user drags the file into
the Arrangement (import tests T1-T8 in
docs/research/2026-11-03_goa-arrangement-delivery-to-live.md). No listening claim is made.

Same parameters and seed give byte-identical files (local ``random.Random`` / hashed
sub-seeds only; no clock, no global RNG). Existing files are never overwritten.

Structure (HYPOTHESES, from D-026 and the research notes, not measured Goa facts)
--------------------------------------------------------------------------------
* "Accumulative" form (G1 finding 5): layers are added every 8 bars; the energy curve is a
  rising sawtooth, three cycles (build, climb, break), each cycle higher than the last
  (peak 0.78, then 0.94, then 1.0), breaks drop kick and bass (planner note C5).
* Every section length is a multiple of 8 bars; default total 224 bars (about 6.2 min at
  145 BPM, 6.0 to 6.6 min over 135-150 BPM, planner note T2 window). ``dj_bars`` adds that
  many bars of kick+perc in front and kick+bass+perc behind (DJ-friendly intro/outro).
* The bass line comes from ``goa_patterns`` with a sub-seed per cycle. Bass rhythm: ``roll``.
* The melodic tracks lead, arp, pad and pluck come from ``goa_melody`` (D-027, #397), one
  8-bar phrase per section with its own sub-seed, called with the section's energy (density
  scales by 0.5 + 0.5 * energy there). Options passed through: ``scale``, ``root``,
  ``density`` (0-1, global or per voice), ``register`` (-2..2 octaves, global or per voice),
  ``arp_pattern`` (default: one per cycle, by seed) and ``progression`` (scale degrees 0-6;
  default: one of ``PROGRESSIONS`` per cycle, by seed). ``melody_voices`` chooses which of
  lead/arp/pad/pluck get a track at all; a voice that is off has no track and no notes.

Tracks (arrangement_midi element names): kick, bass, lead, arp, pad, pluck, perc, plus
snare, clap and rim when switched on (default on; preset or pattern ``none`` turns a voice
off). All rhythm note patterns come from ``goa_rhythm`` (D-027, #392). General-MIDI drum
numbers: kick 36, snare 38, clap 39, rim 37, hat 42 (closed) or 46 (open, from the hat
preset).
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audio_engine import acid_midi, arrangement_midi, goa_melody, goa_patterns, goa_rhythm, io

PPQ = acid_midi.PPQ
BAR_BEATS = 4
MIN_BPM, MAX_BPM = goa_patterns.MIN_BPM, goa_patterns.MAX_BPM
DEFAULT_BPM = goa_patterns.DEFAULT_BPM
ROOT_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MELODIC = tuple(goa_melody.VOICES)  # lead, arp, pad, pluck: owned by goa_melody
ELEMENTS = ("kick", "bass", "lead", "arp", "pad", "pluck", "perc")
PERC_ELEMENTS = tuple(goa_rhythm.PERC_VOICES)  # snare, clap, rim: only when switched on
ALL_ELEMENTS = (*ELEMENTS, *PERC_ELEMENTS)
KICK_PITCH = goa_rhythm.KICK_PITCH
ROOT_OFFSET = {"bass": 24}  # + pitch class (C = 0); melodic windows live in goa_melody
MELODY_PHRASE_BARS = 8  # every section is a multiple of 8 bars
DJ_BARS_CHOICES = (0, 8, 16, 24, 32)
INTRO_BARS_CHOICES = (0, 8, 16, 24, 32)  # kick-less intro in front (0 = none)
OUTRO_BARS_CHOICES = (8, 16, 24, 32)
BREAKDOWN_CHOICES = (0, 1, 2)
OUTRO_MODES = ("kick_on", "kick_less")
# Tempo: the hard limits are goa_patterns.MIN_BPM..MAX_BPM (135-150). The reference
# measurements (3 tracks, low confidence) put the PROPOSAL range at 140-150; inside the hard
# limits the tempo is free. Only the default (145) is a default.
REFERENCE_BPM_RANGE = (140.0, 150.0)

# Scale degrees of the melodic chords (goa_melody: one per bar for the arp, one per chord for
# the pad). HYPOTHESES; one is picked per cycle by seed unless ``progression`` is given.
PROGRESSIONS = (
    (0, 5, 6, 4),
    (0, 0, 5, 6),
    (0, 1, 0, 4),
    (0, 3, 4, 0),
)

# name, bars, energy, elements, cycle
_K, _B, _P, _D, _A, _L = "kick", "bass", "perc", "pad", "arp", "lead"
PLAN: tuple[tuple[str, int, float, tuple[str, ...], int], ...] = (
    ("Intro", 8, 0.30, (_K, _B), 0),
    ("Groove", 8, 0.38, (_K, _B, _P), 0),
    ("Build 1", 8, 0.46, (_K, _B, _P, _D), 0),
    ("Build 2", 8, 0.54, (_K, _B, _P, _D, _A), 0),
    ("Build 3", 8, 0.62, ELEMENTS, 0),
    ("Climb 1", 16, 0.70, ELEMENTS, 0),
    ("Climb 2", 16, 0.78, ELEMENTS, 0),
    ("Break 1", 16, 0.30, (_D, _A), 0),
    ("Return", 8, 0.55, (_K, _B, _P, _D), 1),
    ("Build 4", 8, 0.65, (_K, _B, _P, _D, _A), 1),
    ("Build 5", 8, 0.75, ELEMENTS, 1),
    ("Climb 3", 16, 0.85, ELEMENTS, 1),
    ("Peak 1", 16, 0.88, ELEMENTS, 1),
    ("Peak 2", 16, 0.94, ELEMENTS, 1),
    ("Break 2", 16, 0.35, (_D, _L), 1),
    ("Final 1", 16, 0.97, ELEMENTS, 2),
    ("Final 2", 16, 1.00, ELEMENTS, 2),
    ("Taper", 8, 0.55, (_K, _B, _P, _D), 2),
    ("Outro", 8, 0.35, (_K, _B, _P), 2),
)

SYNTH_HINTS = {
    "kick": "Drum Rack (or Simpler) with a kick on C1 (MIDI 36); the project's rendered kick "
            "WAV fits here",
    "bass": "Drift (default): mono, saw, low-pass, short filter-envelope decay; second recipe "
            "Analog (saw + Sub)",
    "lead": "Drift (default): saw/square, Unison on, medium filter; second recipe Analog",
    "arp": "Drift (default): short pluck, filter envelope; second recipe Analog",
    "pad": "Drift (default): long attack and release, low-pass; second recipe Analog",
    "pluck": "Drift (default): short plucked saw/square, fast filter-envelope decay; second "
             "recipe Analog",
    "perc": "Drum Rack: the hat pitch of the track mapped to the rendered hat one-shot",
}


def _sub_seed(seed: int, tag: str, n: int) -> int:
    return int(hashlib.sha256(f"goa-arr:{seed}:{tag}:{n}".encode()).hexdigest()[:8], 16)


def _melody_options(
    seed: int, bpm: float, root: str, scale: str, density: Any, register: Any,
    arp_pattern: str, progression: list[int],
) -> dict[str, Any]:
    """Validated ``goa_melody`` options for one phrase; ValueError on any bad value."""
    return goa_melody.normalise({
        "seed": seed, "bpm": float(bpm), "root": root, "scale": scale,
        "length": MELODY_PHRASE_BARS, "density": density, "register": register,
        "arp_pattern": arp_pattern, "progression": progression})


def _plan(
    dj_bars: int, intro_bars: int = 0, breakdowns: int = 2, outro: str = "kick_on",
    outro_bars: int = 8,
) -> list[tuple[str, int, float, tuple[str, ...], int]]:
    """Section list. Defaults reproduce the original 224-bar plan. ``breakdowns`` 1 drops
    "Break 1" and its "Return"; 0 also drops "Break 2". ``intro_bars`` adds a kick-less intro
    (pad + perc) in front; ``outro`` "kick_less" ends on pad + perc without kick."""
    drop: set[str] = set()
    if breakdowns < 2:
        drop |= {"Break 1", "Return"}
    if breakdowns < 1:
        drop.add("Break 2")
    plan = [p for p in PLAN if p[0] not in drop]
    last = plan[-1]
    if outro == "kick_less":
        plan[-1] = ("Outro", outro_bars, 0.30, (_D, _P), last[4])
    else:
        plan[-1] = ("Outro", outro_bars, last[2], last[3], last[4])
    if intro_bars:
        plan.insert(0, ("Intro no kick", intro_bars, 0.22, (_D, _P), 0))
    if dj_bars:
        plan.insert(0, ("DJ Intro", dj_bars, 0.25, (_K, _P), 0))
        plan.append(("DJ Outro", dj_bars, 0.30, (_K, _B, _P), 2))
    return plan


def build_arrangement(
    seed: int = 0, bpm: float = DEFAULT_BPM, root: str = "A", scale: str = "phrygian",
    roll: str = "off_kick_16th", dj_bars: int = 0, intro_bars: int = 0, breakdowns: int = 2,
    outro: str = "kick_on", outro_bars: int = 8,
    kick_preset: str = goa_rhythm.DEFAULT_KICK_PRESET,
    bass_preset: str = goa_rhythm.DEFAULT_BASS_PRESET,
    hat_preset: str = goa_rhythm.DEFAULT_HAT_PRESET,
    snare_preset: str = goa_rhythm.DEFAULT_SNARE_PRESET,
    clap_preset: str = goa_rhythm.DEFAULT_CLAP_PRESET,
    rim_preset: str = goa_rhythm.DEFAULT_RIM_PRESET,
    snare_pattern: str = goa_rhythm.PERC_VOICES["snare"][3],
    clap_pattern: str = goa_rhythm.PERC_VOICES["clap"][3],
    rim_pattern: str = goa_rhythm.PERC_VOICES["rim"][3],
    melody_voices: Sequence[str] = MELODIC,
    density: Any = None, register: Any = None, arp_pattern: str | None = None,
    progression: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Return the ``goa_arrangement`` dict (arrangement_midi input) for a whole track.

    ``melody_voices``, ``density``, ``register``, ``arp_pattern`` and ``progression`` go to
    ``goa_melody`` (None = its defaults / the per-cycle seeded choice)."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if root not in ROOT_NAMES:
        raise ValueError(f"root must be one of {list(ROOT_NAMES)}")
    if scale not in goa_patterns.SCALES:
        raise ValueError(f"scale must be one of {sorted(goa_patterns.SCALES)}")
    if roll not in goa_patterns.ROLL_CHOICES:
        raise ValueError(f"roll must be one of {list(goa_patterns.ROLL_CHOICES)}")
    if dj_bars not in DJ_BARS_CHOICES:
        raise ValueError(f"dj_intro_outro must be one of {list(DJ_BARS_CHOICES)} bars")
    if isinstance(bpm, bool) or not isinstance(bpm, (int, float)) or not MIN_BPM <= bpm <= MAX_BPM:
        raise ValueError(f"bpm must be a number {MIN_BPM:g}-{MAX_BPM:g}")
    for name, val, choices in (("intro_bars", intro_bars, INTRO_BARS_CHOICES),
                               ("breakdowns", breakdowns, BREAKDOWN_CHOICES),
                               ("outro_bars", outro_bars, OUTRO_BARS_CHOICES)):
        if isinstance(val, bool) or val not in choices:
            raise ValueError(f"{name} must be one of {list(choices)}")
    if outro not in OUTRO_MODES:
        raise ValueError(f"outro must be one of {list(OUTRO_MODES)}")
    perc_patterns = {"snare": snare_pattern, "clap": clap_pattern, "rim": rim_pattern}
    for voice, pat in perc_patterns.items():
        goa_rhythm.check_pattern(voice, pat)
    kit = goa_rhythm.resolve_kit(kick_preset, bass_preset, hat_preset, snare_preset,
                                 clap_preset, rim_preset)
    perc_on = goa_rhythm.active_voices(kit, perc_patterns)
    pc = ROOT_NAMES.index(root)
    roots = {k: v + pc for k, v in ROOT_OFFSET.items()}
    if (isinstance(melody_voices, str) or not isinstance(melody_voices, Sequence)
            or any(v not in MELODIC for v in melody_voices)
            or len(set(melody_voices)) != len(melody_voices)):
        raise ValueError(f"melody_voices must be distinct names from {list(MELODIC)}")
    melodic_on = tuple(v for v in MELODIC if v in melody_voices)

    progs = {c: PROGRESSIONS[random.Random(f"goa-arr-prog:{seed}:{c}").randrange(len(PROGRESSIONS))]
             for c in range(3)}
    arp_styles = {c: goa_melody.ARP_PATTERNS[_sub_seed(seed, "arpstyle", c)
                                             % len(goa_melody.ARP_PATTERNS)]
                  for c in range(3)}
    # validate every melody option up front (also when the voice is off)
    def cycle_opts(sd: int, c: int) -> dict[str, Any]:
        return _melody_options(
            sd, bpm, root, scale, density, register,
            arp_styles[c] if arp_pattern is None else arp_pattern,
            list(progs[c] if progression is None else progression))

    cycle_opts(0, 0)

    sections: list[dict[str, Any]] = []
    first_pattern: dict[str, dict[str, Any]] = {}
    for idx, (name, bars, energy, active, cycle) in enumerate(
            _plan(dj_bars, intro_bars, breakdowns, outro, outro_bars)):
        lbars = min(bars, goa_patterns.MAX_BARS)
        active = tuple(e for e in active if e not in MELODIC or e in melodic_on)
        mel = cycle_opts(_sub_seed(seed, "melody", idx), cycle)
        over: dict[str, dict[str, Any]] = {}
        for el in active:
            if el == "bass":
                over[el] = goa_rhythm.bass_part(
                    kit, roll, roots["bass"], scale, lbars, float(bpm),
                    _sub_seed(seed, "bass", cycle), energy)
            elif el in MELODIC:
                over[el] = goa_melody.voice_pattern(el, mel, energy)
            elif el == "perc":
                over[el] = goa_rhythm.hat_part(kit, energy, float(bpm))
        if "kick" in active:  # snare/clap/rim play with the kick, from their energy threshold
            for v in perc_on:
                if goa_rhythm.perc_active(v, energy):
                    active = (*active, v)
                    over[v] = goa_rhythm.perc_part(v, perc_patterns[v])
        for el, pat in over.items():
            first_pattern.setdefault(el, pat)
        sec: dict[str, Any] = {"name": name, "bars": bars, "energy": energy,
                               "elements": [e for e in ALL_ELEMENTS if e in active]}
        sec["patterns"] = {e: over[e] for e in sec["elements"] if e in over and e != "kick"}
        sections.append(sec)
    first_pattern["kick"] = goa_rhythm.kick_pattern()
    for v in perc_on:  # a voice that never plays still needs a track pattern
        first_pattern.setdefault(v, goa_rhythm.perc_part(v, perc_patterns[v]))
    tracks = [e for e in ELEMENTS if e not in MELODIC or e in melodic_on]
    return {
        "format": arrangement_midi.FORMAT_NAME, "version": arrangement_midi.FORMAT_VERSION,
        "title": f"Goa seed {seed}", "tempo": float(bpm), "key": {"root": root, "scale": scale},
        "elements": [{"name": e, "pattern": first_pattern[e]} for e in (*tracks, *perc_on)],
        "sections": sections,
    }


def build_midi(**params: Any) -> bytes:
    return arrangement_midi.arrangement_to_midi(build_arrangement(**params))


def total_bars(arr: dict[str, Any]) -> int:
    return sum(s["bars"] for s in arr["sections"])


OPTION_DEFAULTS: dict[str, Any] = {
    "roll": "off_kick_16th", "dj_bars": 0, "intro_bars": 0, "breakdowns": 2,
    "outro": "kick_on", "outro_bars": 8, "kick_preset": goa_rhythm.DEFAULT_KICK_PRESET,
    "bass_preset": goa_rhythm.DEFAULT_BASS_PRESET, "hat_preset": goa_rhythm.DEFAULT_HAT_PRESET,
    "snare_preset": goa_rhythm.DEFAULT_SNARE_PRESET,
    "clap_preset": goa_rhythm.DEFAULT_CLAP_PRESET, "rim_preset": goa_rhythm.DEFAULT_RIM_PRESET,
    "snare_pattern": goa_rhythm.PERC_VOICES["snare"][3],
    "clap_pattern": goa_rhythm.PERC_VOICES["clap"][3],
    "rim_pattern": goa_rhythm.PERC_VOICES["rim"][3],
    "melody_voices": MELODIC, "density": None, "register": None, "arp_pattern": None,
    "progression": None,
}


def full_options(params: dict[str, Any]) -> dict[str, Any]:
    """Every option with its chosen (or default) value; used for the README."""
    return {"seed": params.get("seed", 0), **{k: params.get(k, v)
                                              for k, v in OPTION_DEFAULTS.items()}}


def _kit_of(opts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return goa_rhythm.resolve_kit(
        opts["kick_preset"], opts["bass_preset"], opts["hat_preset"], opts["snare_preset"],
        opts["clap_preset"], opts["rim_preset"])


def render_readme(arr: dict[str, Any], mid_name: str, params: dict[str, Any]) -> str:
    opts = full_options(params)
    bpm = arr["tempo"]
    bars_total = total_bars(arr)
    minutes = bars_total * 4 * 60 / bpm / 60
    lo, hi = REFERENCE_BPM_RANGE
    kit = _kit_of(opts)
    perc_patterns = {v: opts[f"{v}_pattern"] for v in PERC_ELEMENTS}
    perc_on = goa_rhythm.active_voices(kit, perc_patterns)
    hs = goa_rhythm.hat_spec(kit, bpm)
    perc_rows = [
        f"| {v} preset / pattern | `{opts[f'{v}_preset']}` / `{opts[f'{v}_pattern']}`"
        + (f" (from energy {goa_rhythm.PERC_VOICES[v][2]:g}, with the kick; MIDI "
           f"{goa_rhythm.PERC_VOICES[v][0]}) |" if v in perc_on else " (voice off) |")
        for v in PERC_ELEMENTS]
    perc_tracks = [
        f"| {v} | `{opts[f'{v}_pattern']}` hits, MIDI {goa_rhythm.PERC_VOICES[v][0]} | "
        f"Drum Rack pad or Simpler with `samples/{v}_{opts[f'{v}_preset']}.wav` |"
        for v in perc_on]
    mel = goa_melody.normalise({"density": opts["density"], "register": opts["register"]})
    mel_on = [v for v in MELODIC if v in opts["melody_voices"]]
    prog_text = ("per cycle by seed, from " + "; ".join(",".join(map(str, p))
                                                         for p in PROGRESSIONS)
                 if opts["progression"] is None
                 else ",".join(map(str, opts["progression"])))
    mel_rows = [
        f"| melodic voices | {', '.join(mel_on) or 'none'} (from `goa_melody`) |",
        "| melody density | " + ", ".join(f"{v} {mel['density'][v]:g}" for v in mel_on)
        + " (before the section-energy factor 0.5 + 0.5 * energy) |",
        "| melody register | " + ", ".join(f"{v} {mel['register'][v]:+d}" for v in mel_on)
        + " octaves |",
        f"| arp pattern | `{opts['arp_pattern'] or 'per cycle by seed'}` |",
        f"| progression (scale degrees) | {prog_text} |",
    ]
    mel_track_rows = {
        "lead": "seeded ostinato lead, new phrase per section (`goa_melody`)",
        "arp": "16th arpeggio over the chord of each bar (`goa_melody`)",
        "pad": "triads held for density-dependent chord length (`goa_melody`)",
        "pluck": "seeded 16th-grid pluck line (`goa_melody`)",
    }
    melody_tracks = [f"| {v} | {mel_track_rows[v]} | {SYNTH_HINTS[v]} |" for v in mel_on]
    lines = [
        f"# Goa track, seed {opts['seed']}, {bpm:g} BPM",
        "",
        f"File: `{mid_name}` (Standard MIDI File, format 1, 4/4, PPQ {PPQ}). "
        f"Key {arr['key']['root']} {arr['key']['scale']}, "
        f"{bars_total} bars (about {minutes:.1f} minutes at {bpm:g} BPM).",
        "",
        "Status: generated by code (`python -m audio_engine.goa_arrangement`). "
        "NOT tested in Live and not listened to. Importing it is the user's test list T1-T8 in "
        "`docs/research/2026-11-03_goa-arrangement-delivery-to-live.md`. The musical choices "
        "are hypotheses, not Goa facts.",
        "",
        "## Chosen options",
        "",
        "| Option | Value |",
        "| --- | --- |",
        f"| tempo | {bpm:g} BPM (limits {goa_patterns.MIN_BPM:g}-{goa_patterns.MAX_BPM:g}; "
        f"reference-measurement range {lo:g}-{hi:g}: "
        f"{'inside' if lo <= bpm <= hi else 'outside'}) |",
        f"| bass rhythm (`roll`) | `{opts['roll']}` |",
        f"| kick-less intro | {opts['intro_bars']} bars |",
        f"| breakdowns | {opts['breakdowns']} |",
        f"| outro | `{opts['outro']}`, {opts['outro_bars']} bars |",
        f"| DJ intro/outro | {opts['dj_bars']} bars each |",
        f"| kick preset | `{opts['kick_preset']}` |",
        f"| bass preset | `{opts['bass_preset']}` (gate {goa_rhythm.bass_gate_ms(kit):g} ms = "
        f"MIDI note length; the rendered one-shot is at MIDI {goa_rhythm.bass_note(kit)}) |",
        f"| hat preset | `{opts['hat_preset']}` ({hs['decay_ms']:g} ms decay: "
        f"{'open' if hs['open'] else 'closed'} hat, MIDI {hs['pitch']}, 16th ghost hits "
        f"{'fit' if hs['ghosts_fit'] else 'do not fit'} at this tempo) |",
        *perc_rows,
        *mel_rows,
        "",
        "What comes from presets and what does not. Every rhythm note pattern comes from the "
        "engine-side module `goa_rhythm` (D-027), not from the Goa melody code; lead, arp, pad "
        "and pluck come from `goa_melody` only.",
        "",
        "* Derived from a preset: the rendered WAVs in `samples/` (all voices); the bass note "
        "length (`gate_ms` of the bass preset) and, for `offbeat_ghost`, the ghost velocity "
        "rule; the hat track's pitch (closed 42 / open 46 from the preset's `decay_ms`), its "
        "note length (the decay, cut before the next hat hit) and whether the 16th hits "
        "between the off-beat hits exist at all (only if the decay is not longer than one "
        "16th at this tempo).",
        "* Chosen by option, not derived from a preset: the bass roll positions (`roll`), the "
        "snare/clap/rim hit positions (`*_pattern`), kick positions (four on the floor), all "
        "velocities, the energy thresholds at which a voice enters. These are defaults, not "
        "measured facts about Goa.",
        "",
        "The MIDI bass notes are key-dependent (they start at "
        f"MIDI {ROOT_OFFSET['bass'] + ROOT_NAMES.index(arr['key']['root'])} for this key "
        "and follow the scale), so the sampler pitch of the bass one-shot must be matched "
        "to the key by hand.",
        "",
        "Defaults are only defaults (D-027); no value above is a measured fact about Goa.",
        "",
        "## Import",
        "",
        "1. New Live set. Drag the `.mid` onto the Arrangement at bar 1: one MIDI track per "
        "element below is expected (not verified).",
        f"2. If Live does not take the tempo, set {bpm:g} BPM by hand.",
        "3. Put an instrument on every track (the file has no devices). Melodic tracks: Drift "
        "(in every Live 12 edition), Analog is the second recipe. Rhythm tracks: the one-shot "
        "WAVs in `samples/` (rendered by the kick, bass, hat, snare, clap and rim engines from "
        "the presets above; a voice that is off has no WAV) in a Drum Rack or Simpler.",
        "",
        "## Tracks",
        "",
        "| Track | Content | Put on it |",
        "| --- | --- | --- |",
        "| kick | four on the floor, MIDI 36 | " + SYNTH_HINTS["kick"] + " |",
        f"| bass | `{opts['roll']}` rhythm, line changes per cycle | " + SYNTH_HINTS["bass"]
        + " |",
        *melody_tracks,
        f"| perc | hat hits (MIDI {hs['pitch']}) from the hat preset, more 16th hits with "
        "energy if they fit | " + SYNTH_HINTS["perc"] + " |",
        *perc_tracks,
        "",
        "Synth recipes are not tested in Live. Velocity follows the section energy "
        "(0.70 + 0.30 * energy); filter sweeps and automation are not in a `.mid`.",
        "",
        "## Sections",
        "",
        "| Start bar | Bars | Section | Energy | Tracks playing |",
        "| ---: | ---: | --- | ---: | --- |",
    ]
    pos = 1
    for s in arr["sections"]:
        lines.append(f"| {pos} | {s['bars']} | {s['name']} | {s['energy']:.2f} | "
                     f"{', '.join(s['elements'])} |")
        pos += s["bars"]
    lines += ["", "Section names are also written as markers in the conductor track.", ""]
    return "\n".join(lines)


def write_track(
    out_dir: str | Path, render_samples: bool = True, *, created_at: datetime | None = None,
    **params: Any
) -> tuple[Path, Path]:
    """Write ``.mid``, README and (default) ``samples/*.wav`` into ``out_dir``. Refuses if any
    target exists (nothing written).

    Every one-shot gets its sidecar ``samples/<name>.json`` from the engine's own writer
    (:func:`audio_engine.io.write_sample`, sample-metadata contract), so the GUI library and
    the Live import know its category (#414). ``created_at`` (time-zone aware, default now)
    is the same for all of them; it is the only part of a sidecar that differs between two
    runs with the same options."""
    arr = build_arrangement(**params)
    arrangement_midi.validate_arrangement(arr)  # fail before anything is created
    opts = full_options(params)
    kit = _kit_of(opts)
    d = Path(out_dir)
    stem = f"goa_seed{opts['seed']}_{float(arr['tempo']):g}bpm"
    mid, readme = d / f"{stem}.mid", d / "README.md"
    files = goa_rhythm.kit_files(kit) if render_samples else []
    sdir = d / goa_rhythm.SAMPLE_DIR
    targets = [mid, readme] + [sdir / f"{n}{ext}" for n, *_ in files for ext in (".wav", ".json")]
    for p in targets:
        if p.exists() or p.is_symlink():
            raise FileExistsError(f"{p} already exists; choose another folder (nothing written)")
    d.mkdir(parents=True, exist_ok=True)
    text = render_readme(arr, mid.name, params)
    stamp = created_at or datetime.now(UTC).replace(microsecond=0)
    arrangement_midi.write_arrangement_midi(arr, mid)  # MIDI first, then the samples
    for name, cat, sample_params, desc in files:
        wav, side = io.write_sample(cat, sample_params, sdir, name=name, description=desc,
                                    created_at=stamp)
        if wav.name != f"{name}.wav":  # write_sample picked _002: the name appeared meanwhile
            side.unlink(missing_ok=True)
            wav.unlink(missing_ok=True)
            raise FileExistsError(f"{sdir / name}.wav appeared meanwhile; {mid} was written")
    try:
        with open(readme, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except FileExistsError as exc:
        raise FileExistsError(f"{readme} appeared meanwhile; {mid} was written") from exc
    return mid, readme


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m audio_engine.goa_arrangement",
        description="Complete Goa track as one multitrack MIDI file plus README (not tested "
                    "in Live)")
    p.add_argument("--out", required=True, help="output folder (created; never overwritten)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--bpm", type=float, default=DEFAULT_BPM)
    p.add_argument("--root", choices=ROOT_NAMES, default="A")
    p.add_argument("--scale", choices=sorted(goa_patterns.SCALES), default="phrygian")
    p.add_argument("--roll", choices=goa_patterns.ROLL_CHOICES, default="off_kick_16th")
    p.add_argument("--intro-bars", type=int, default=0, choices=INTRO_BARS_CHOICES,
                   help="kick-less intro bars in front (default 0)")
    p.add_argument("--breakdowns", type=int, default=2, choices=BREAKDOWN_CHOICES,
                   help="number of breakdowns (default 2 = original plan)")
    p.add_argument("--outro", choices=OUTRO_MODES, default="kick_on")
    p.add_argument("--outro-bars", type=int, default=8, choices=OUTRO_BARS_CHOICES)
    p.add_argument("--kick-preset", default=goa_rhythm.DEFAULT_KICK_PRESET)
    p.add_argument("--bass-preset", default=goa_rhythm.DEFAULT_BASS_PRESET)
    p.add_argument("--hat-preset", default=goa_rhythm.DEFAULT_HAT_PRESET)
    for v in PERC_ELEMENTS:
        p.add_argument(f"--{v}-preset", default=goa_rhythm.DEFAULT_PRESETS[v],
                       help=f"{v} engine preset or 'none' (voice off)")
        p.add_argument(f"--{v}-pattern", default=goa_rhythm.PERC_VOICES[v][3],
                       choices=goa_rhythm.PERC_PATTERN_CHOICES, help=f"{v} hit positions")
    p.add_argument("--melody-voices", default=",".join(MELODIC),
                   help="comma list from lead,arp,pad,pluck; a voice left out gets no track")
    p.add_argument("--density", help="melody density 0-1, or voice=value,voice=value")
    p.add_argument("--register", help="melody octave shift -2..2, or voice=value,...")
    p.add_argument("--arp-pattern", choices=goa_melody.ARP_PATTERNS,
                   help="default: one per cycle, chosen by seed")
    p.add_argument("--progression", help="comma list of scale degrees 0-6 "
                                         "(default: one per cycle, chosen by seed)")
    p.add_argument("--no-samples", action="store_true",
                   help="do not render the rhythm one-shots into DIR/samples")
    p.add_argument("--dj-intro-outro", dest="dj_bars", type=int, nargs="?", const=16,
                   default=0, help="bars of DJ intro and outro (flag alone = 16; 8-32)")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        melody: dict[str, Any] = {
            "melody_voices": [v for v in a.melody_voices.split(",") if v],
            "arp_pattern": a.arp_pattern}
        if a.density is not None:
            melody["density"] = goa_melody._parse_voice_map(a.density, float, "density")
        if a.register is not None:
            melody["register"] = goa_melody._parse_voice_map(a.register, int, "register")
        if a.progression is not None:
            melody["progression"] = [int(x) for x in a.progression.split(",")]
        mid, readme = write_track(
            a.out, render_samples=not a.no_samples, seed=a.seed, bpm=a.bpm, root=a.root,
            scale=a.scale, roll=a.roll, dj_bars=a.dj_bars, intro_bars=a.intro_bars,
            breakdowns=a.breakdowns, outro=a.outro, outro_bars=a.outro_bars,
            kick_preset=a.kick_preset, bass_preset=a.bass_preset, hat_preset=a.hat_preset,
            snare_preset=a.snare_preset, clap_preset=a.clap_preset, rim_preset=a.rim_preset,
            snare_pattern=a.snare_pattern, clap_pattern=a.clap_pattern,
            rim_pattern=a.rim_pattern, **melody)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"wrote {mid} ({mid.stat().st_size} bytes) and {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
