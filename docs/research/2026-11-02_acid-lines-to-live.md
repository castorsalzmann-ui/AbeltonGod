# Research: acid lines (16-step 303 patterns) into Live, as a MIDI file and as a clip over AbletonOSC

_Date: 2026-11-02 · Refs #277 · Researcher B. Sources opened 2026-11-02. Nothing here was run in Live. Docs only: no code, no capability status change, no contract change. Related (not repeated): [AbletonOSC protocol](2026-10-28_abletonosc-protocol-and-create-audio-clip.md), [MIDI/devices Q1, Q6, E1-E7](2026-10-29_live-midi-arrangement-devices.md), [drum-rack choke](2026-11-02_drum-rack-choke-and-oneshot-placement.md) (for the Live-side MIDI-track pattern)._

## For workers

- **Possible?** Yes, on two routes. (a) A Standard MIDI File the user drags into Live: needs no Live bridge at all. (b) A Session MIDI clip written by AbletonOSC: needs three already-existing handlers (`create_midi_track`, `clip_slot/create_clip`, `clip/add/notes`), but **none of them is `tested`** (see the table). Arrangement placement of the clip is not possible without an extension.
- **Recommended route:** build (a) first (deterministic, CI-testable, no Ableton). Treat (b) as a second step once the user has run tests A1-A6 below. Both routes share one pure function, `acid_line JSON -> list of (pitch, start, duration, velocity)`.
- **Mapping (PROPOSAL):** 1 step = 0.25 beat; clip 4.0 beats. Accent = high velocity. Slide = the note is made longer than its step so it overlaps the next note by a small amount; a monophonic synth with glide and legato then glides. Details in section 4.
- **Read first:** section 2 (capability gaps) and section 4 (mapping), then `contracts/capabilities.json`.
- **Effort:** (a) small; (b) medium (new capability entries via `contract-change`, a client with read-back, user tests).
- **Blockers:** the six user tests in section 3 for route (b); whether Live's file import keeps the file's tempo (the manual does not say, see finding 7).
- **Open questions for the user only:** (1) Which synth should play the line by default (Live's Drift in Mono mode, or the user's own 303 plug-in)? (2) Does the standalone Acid 303 mark slide on the step you slide **from** or the one you slide **to**? (3) Is 16 steps fixed, or do odd lengths (13, 15) matter?

## 1. Findings

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| 1 | AbletonOSC README lists `/live/song/create_midi_track index`, `/live/clip_slot/create_clip track_index clip_index length`, `/live/clip/add/notes track_id clip_id pitch start_time duration velocity mute ...` ("velocity is MIDI velocity index, mute is true/false"), `/live/clip/get/notes`, `/live/clip/set/name`, and `get`/`set` for `loop_end`. The README page was read through a summarising fetch; the file/line facts below are the stronger evidence. | medium | [AbletonOSC README](https://github.com/ideoforms/AbletonOSC) |
| 2 | `clip.py` reads the add-notes parameters in chunks of five (pitch, start, duration, velocity, mute), builds one `MidiNoteSpecification` per chunk and calls `add_new_notes` once. There is no default for a missing velocity or mute; a short chunk fails. So the client must send all five fields for every note. | medium-high (summarised fetch of the file; agrees with the earlier note's line cites `clip.py:145-155`) | [clip.py](https://raw.githubusercontent.com/ideoforms/AbletonOSC/master/abletonosc/clip.py), earlier note Q1 |
| 3 | `looping`, `loop_end` and `name` are read/write properties of the clip handler; `length` is read-only. | medium (summarised fetch) | same |
| 4 | The Roland TB-303 manual says a pattern "divides the time axis into 16 steps" with pitch, slide and gate per step; ACCENT sets "the strength of the accent that was entered in the pattern"; SLIDE is specified per step in the edit window. | high | [TB-303 manual, p. 3-6](https://rolandcloud.com/getmedia/b3e2da28-1951-467e-bd79-7aae34481570/TB-303-Manual-E.pdf?ext=.pdf) |
| 5 | Accent raises volume and filter cutoff / envelope depth; slide "ties two notes together" as a pitch glide (portamento). The manual text gives no gate-timing detail for slide. | medium (articles) | [Roland article](https://articles.roland.com/?p=92325), [MusicRadar](https://www.musicradar.com/news/producers-guide-roland-tb-303) |
| 6 | Live's Drift (documented on the Max-for-Live-side reference page of the same device) has `glidetime` (0-2 s) and `legato`. Glide "is only available if the voice mode is set to mono and notes are played legato"; legato is only available in mono. Nothing found for Live's Operator, Analog or Bass. | medium-high for Drift | [abl.device.drift~](https://docs.cycling74.com/reference/abl.device.drift~) |
| 7 | Live imports a MIDI file by browser drag or Create > Import MIDI File; in Session View into the selected slot, in Arrangement at the insert marker. The resulting clips do not reference the file. The manual does **not** say how tempo/time-signature data in the file is handled, nor list supported formats. Live exports a clip with File > Export MIDI Clip as a Standard MIDI File. | high for what it says, gap otherwise | [Live 12 manual: Managing Files and Sets](https://www.ableton.com/en/live-manual/12/managing-files-and-sets/) |
| 8 | In Live's piano roll a new note that overlaps the start of an existing note overwrites it, and one that overlaps the end shortens it. The manual does not discuss same-pitch overlaps specifically; Join (Ctrl/Cmd+J) merges notes in a key track. It is **not stated** whether `add_new_notes` follows the editor's overwrite rule. | medium (summarised fetch) | [Live 12 manual: Editing MIDI](https://www.ableton.com/en/live-manual/12/editing-midi/) |
| 9 | Live has a Scale Mode with root note and scale name per clip (highlight / fold only, it does not change notes). Whether that is settable through the LOM was not checked. | medium | same |
| 10 | PyPI lists `mido` 1.3.3, licence MIT, Python `~=3.7` (opened with curl today). `mido` is not in `pyproject.toml`. A Standard MIDI File is simple enough to write with the standard library. | high (PyPI) | `https://pypi.org/pypi/mido/json` |

## 2. Which functions are `tested`, `supported`, `unknown`

Checked against `contracts/capabilities.json` on `origin/main` (`e7d7522`).

| Needed for an acid clip | Registry entry | Status |
| --- | --- | --- |
| Create MIDI track | `song.create_midi_track` | `unknown` |
| Check track takes MIDI | `track.has_midi_input.get` | `unknown` |
| Create Session MIDI clip (`/live/clip_slot/create_clip`) | **no entry** | absent (treat as `unknown`) |
| Check slot is empty | `clip_slot.has_clip.get` | `tested` |
| Add notes (`/live/clip/add/notes`) | **no entry** (only `arrangement_clip.notes.add`, `unknown`, for the Arrangement extension) | absent |
| Read notes back (`/live/clip/get/notes`) | **no entry** | absent |
| Name the clip, set loop end | **no entry** | absent |
| Undo | `song.undo` | `tested` (single step; a track plus clip created together were reverted by one undo, so callers must read back) |
| Arrangement MIDI clip / notes | `track.create_midi_clip`, `arrangement_clip.notes.*` | `unknown`; needs an extension (earlier note Q6) |

Consequence: nothing on the MIDI-clip route may be built as a tool until the bridge-engineer adds the missing entries (`contract-change` PR, status `unknown`) and the user's runs move them to `tested`. The MIDI-file route touches no Live function and is outside the capability rule.

## 3. Tests the user would run in Live (to move entries to `tested`)

Same style as E1-E7 in the MIDI/devices note; E1 there already covers "create track + clip + 4 notes + read back". Proposed acid-specific additions, each with read-back (`/live/clip/get/notes`) and a whole-track-list check around it. Live 12.4.5, user's Windows machine.

| ID | Run | Moves to `tested` |
| --- | --- | --- |
| A1 | `create_midi_track -1`, `clip_slot/create_clip t 0 4.0`, 16 notes on 0.25-beat starts with all five fields. Read back: 16 tuples, same values. Also read `/live/clip/get/length` and `loop_end`. | `song.create_midi_track`, `clip_slot.create_clip`, `clip.notes.add`, `clip.notes.get` |
| A2 | Mixed velocities 127 and 100 (accent / normal). Read back the exact integers. | velocity round-trip |
| A3 | Durations 0.125 (gate) and 0.28125 (step + overlap). Read back: are the floats unchanged, or snapped? | duration precision |
| A4 | Two overlapping notes of **different** pitch (slide), then two overlapping notes of the **same** pitch. Read back the count and durations. Finding 8 leaves open whether the API drops or shortens the earlier note. | overlap behaviour |
| A5 | `create_clip` on an occupied slot and on an audio track. Record the `/live/error` text. | error path |
| A6 | `clip/set/name` and, if needed, `set/loop_end`; one `song.undo` after the clip and notes (read back whether one undo or more is needed, as in the `song.undo` evidence). | name / loop / undo cost |
| A7 | MIDI file: user drags the generated `.mid` into a MIDI track. Report: note count, velocities, whether the overlap is kept, whether Live changes the set tempo or asks about it, clip length. | route (a) |
| A8 | Ears, user only: put Drift in Mono with legato on and glide time above 0, play the clip, say whether the slid notes glide and the accented ones stand out. **No claim about sound is made here.** | none (listening result, not a capability) |

CI can test the pure mapping (section 4) and the MIDI file bytes. It cannot test A1-A8.

## 4. Mapping and minimal format (PROPOSAL ONLY)

### Mapping to notes (PROPOSAL)

All values are defaults the user may change; none is a measured or sourced optimum.

- Step `i` (0-15) starts at `i * 0.25` beats; the clip is 4.0 beats (one bar of 4/4).
- Rest step: no note.
- Normal note: velocity 100 (PROPOSAL), duration 0.125 beat (half a step, a "staccato" gate; Roland's article says slides work best against short notes).
- Accent: velocity 127 (PROPOSAL). Whether accent then also opens the filter depends on the target synth's velocity routing; this is not claimed.
- Slide: the slid note gets duration `0.25 + overlap` with `overlap = 0.03125` (PROPOSAL, 1/128 note), so it still sounds when the next note starts. A monophonic synth with legato and glide (Drift: finding 6) is the only kind of target where this produces a glide; a polyphonic patch would just play two notes at once.
- Slide into a rest, or into the same pitch: no overlap needed. Same pitch: lengthen the first note to end at the next note's end and drop the second note (a tie). This avoids the unknown overwrite rule of finding 8 and test A4.
- The pitch is `root_midi + scale_interval[degree] + 12 * octave`; the Acid 303 should write the resolved `note` too (below), so the importer does not need the scale tables.
- Note on slide semantics: on the hardware the slide flag is stored per step, and the opened sources only say that it ties two notes. Which step carries the flag (the one slid from or the one slid to) is **not established by an opened source**; the format below defines it explicitly (open question 2).

### Acid-line JSON (PROPOSAL ONLY, not a contract)

Determinism: the Acid 303 owns the random generator. The file stores the **resolved** steps plus the generator inputs, so a consumer never has to re-run a random generator (a different language's generator would give different steps). Same file in, same notes out.

```json
{
  "format": "acid_line",
  "version": "0.1-proposal",
  "seed": 1234,
  "root": "A",
  "root_octave": 2,
  "scale": "minor",
  "steps": [
    {"on": true,  "degree": 0, "octave": 0, "accent": true,  "slide": false, "note": 45},
    {"on": false},
    {"on": true,  "degree": 2, "octave": 0, "accent": false, "slide": true,  "note": 48}
  ],
  "length": 16,
  "render": {"velocity": 100, "accent_velocity": 127, "gate": 0.125, "slide_overlap": 0.03125}
}
```

Rules: `steps` has exactly `length` entries (16 default; 1-32 allowed by the format, open question 3); `slide` on step `i` means "glide from this note into the next sounding step" (PROPOSAL, flagged because of the semantics note above); `note` is an integer 0-126; `render` is optional and falls back to the defaults above. Tempo is not part of the line: the line is in beats and the host sets BPM.

### Generation rules: what is standard and what is not

| Rule | Status | Source |
| --- | --- | --- |
| 16 steps per pattern by default | standard (hardware) | [TB-303 manual p. 5](https://rolandcloud.com/getmedia/b3e2da28-1951-467e-bd79-7aae34481570/TB-303-Manual-E.pdf?ext=.pdf), [MusicRadar](https://www.musicradar.com/news/producers-guide-roland-tb-303) |
| Work in one chosen key, start from the root | sourced advice | MusicRadar |
| Octave jumps are part of the sound, together with slides; stay about one octave up (the hardware range) | sourced advice | MusicRadar, [MusicTech](https://musictech.com/guides/essential-guide/how-to-create-a-chicago-style-acid-house-bassline) |
| Accents and slides are set separately from pitch and are scattered; too many accents flatten the groove; slides work best against short notes | sourced advice | [Roland article](https://articles.roland.com/?p=92325), MusicTech |
| Odd pattern lengths (9, 11, 13, 15) drift against the 4/4 bar | sourced advice | Roland article, MusicTech |
| Which scale (minor, phrygian, pentatonic ...) | **no opened source names one** | none; the generator's scale list is a design choice of the Acid 303 |
| Density (share of steps that are notes) and the number of accents/slides per bar | **no number in the opened sources** (MusicTech: fill all sixteen quickly, then prune); any numeric default is the Acid 303's own choice | none |

## 5. Pitfalls

- Overlapping notes with the same pitch may be overwritten, shortened or rejected (finding 8, test A4); the tie rule avoids them by construction.
- The client must send all five fields per note (finding 2); `mute` as `0` is what the earlier E1 plan uses, whether `false` is also accepted is unchecked.
- A second `create_clip` on a used slot errors; check `clip_slot.has_clip.get` first (`tested`).
- Setters and `create_clip` return no reply (protocol note, fact 4); success must come from read-back.
- The default `get/notes` range may miss pitch 127 (MIDI/devices note, Q1); irrelevant for a bass line but relevant for a generic read-back.
- A `.mid` file may carry a tempo; whether Live applies it to the set is undocumented (finding 7, A7).
- Glide is a property of the target synth, not of the MIDI: a sample-based kick-style track or a polyphonic patch will not glide.

## 6. Test strategy hints

- **CI:** golden tests of `acid_line -> notes` (including the tie rule, rests, accent, slide, odd lengths); a property test over seeded random lines (every note inside 0-126, no same-pitch overlap, no overlap longer than `slide_overlap`, the notes are sorted); a byte-identical-output test for the `.mid` writer; parse the file back with an independent reader (mido as a dev-only dependency, MIT, would be an independent reference; a stdlib writer would need no new dependency in the product).
- **Not CI:** A1-A8. Report them as user runs, never as CI.

## 7. Implications for the lead (PROPOSALS)

1. Open one issue for route (a): `acid_line` JSON validator + `notes` mapping + `.mid` writer (audio-engineer or a new owner of `src/`; the lead decides). It needs no Live.
2. Open a `contract-change` issue for the bridge-engineer: capability entries `clip_slot.create_clip`, `clip.notes.add`, `clip.notes.get`, `clip.name.set`, `clip.loop_end.set` as `unknown` (this note does not change any status).
3. Ask the user to run A1-A7 in one script run (the E1 style), then decide on route (b).
4. If the line should be a contract later: the format above is not one; it needs its own `contract-change` PR and an owner (INTERFACES.md).
5. A new dependency (`mido`) is not needed for the product; mention it only for tests, with a PR reason.

## Blocked or unverified

- ableton.com's Drift manual page (`live-audio-effects-and-instruments`) failed to fetch; Drift facts come from the Cycling '74 device page. Operator, Analog and Bass glide behaviour is not checked.
- No Live version beyond 12.4.5 was considered. AbletonOSC pages were read through a summarising fetch, not line by line today; file/line cites come from the earlier notes at commit `0ca6821`.
- Slide step semantics and MIDI-file tempo handling are open (above).
