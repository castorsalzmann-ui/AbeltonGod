# Research: assembling a drum kit in Live and basic mixer helpers (feasibility, user test list, contract needs)

_Date: 2026-11-02 · Researcher B. Sources opened 2026-11-02. **Nothing here was run in Live; nothing is claimed `tested`.** Docs only: no code, no capability status change, no contract change. Extends (does not repeat): [drum-rack choke and one-shot placement](2026-11-02_drum-rack-choke-and-oneshot-placement.md) (Drum Rack manual facts, `choke_group`, issue sequence D0-D3), [MIDI/arrangement/devices](2026-10-29_live-midi-arrangement-devices.md) (Q3 static values, Q4 loading), [AbletonOSC protocol](2026-10-28_abletonosc-protocol-and-create-audio-clip.md), [acid lines to Live](2026-11-02_acid-lines-to-live.md) (MIDI-clip route, tests A1-A8), [mix loudness targets](2026-10-29_mix-loudness-targets.md), [generate-sample tool design](2026-11-02_generate-sample-tool-design.md)._

## For workers

- **Possible?** Yes, in two stages. **Stage 1 (reachable now, no new Ableton capability):** five audio tracks (kick, clap, hat, snare, rim), one `clip_slot.create_audio_clip` each (`tested`). Per-track volume/pan/sends are then reachable with already-existing AbletonOSC handlers, but those handlers are not yet in `contracts/capabilities.json` (so not usable by a tool until added and tested). **Stage 2 (a real playable kit):** a Drum Rack on a MIDI track. AbletonOSC cannot create racks, chains or pads, or load samples onto pads; that needs a new handler and user tests.
- **Sampler is not an option for this user:** per Ableton's edition comparison, Sampler is Suite only; Simpler, Drum Sampler, Drum Rack and Impulse are in Standard (finding 1).
- **Recommended route:** Stage 1 + a hand-built Drum Rack recipe (already in the choke note, section 5) + read-only probe, then write access. Mixer helpers (volume, pan, send, mute) are a separate small step that does not depend on the kit.
- **Mixer writes are all `confirm`** (the orchestrator already forces `confirm` for any capability that is not a read, `src/orchestrator/tools.py` module docstring). Reads are `routine`. Section 3 gives the mapping.
- **Hard limits found in AbletonOSC source:** the track handler addresses only `song.tracks`, so **return tracks and the master track are not reachable** for volume/pan (finding 9). A wildcard `*` as track index would write to **every** track (finding 10): the client must never send it.
- **Contract:** a kit tool needs a new tool schema and, for stage 2, a kit manifest; the strict optional-parameter budget is already 24 of 24, so every new field must be **required** (section 4). `sample-metadata` category enum is `kick, clap, hat` only: snare and rim need an additive change before their files can carry sidecars.
- **Read first:** section 1 (options table), section 5 (user test list M1-M12), section 4 (contract sketch).
- **Effort:** stage 1 kit tool small-medium; mixer reads/writes medium (registry entries, client, tests with fake server, user run); Drum Rack build from files large and possibly "not possible without a user drag".
- **Blockers:** user tests M1-M12; whether the Python remote-script API offers the Max-LOM classes (inference, unchanged from earlier notes).
- **Open questions for the user only:** (1) Is "five audio tracks with clips" good enough as the first kit, or must the kit be playable from MIDI/keys right away? (2) May the copilot ever write volume above the current value (louder), or only equal/lower? (3) Group the five tracks in one Group Track? (cosmetic; no API evidence yet).

## 1. Options for a full kit in Live 12 Standard

| Option | What it is | Needs from Live API | Choke / retrigger | Mixing | Status for this project |
| --- | --- | --- | --- | --- | --- |
| **A. Audio track per sound, one clip each** | Five audio tracks; each holds the WAV as a clip (loop or trigger) | `create_audio_clip` (`tested`); track creation `song.create_audio_track` (`tested`) | None between tracks; hat tail only via render option `choke_ms` | One mixer strip per sound: easy | **Reachable now.** Not playable from MIDI. A pattern = a rendered loop or many clips |
| **B. Drum Rack on one MIDI track** | One rack, one pad per sound, Simpler or Drum Sampler per pad | Create rack (`Track.insert_device`, 12.3+), create chains (`RackDevice.insert_chain`, 12.3+), load sample (`SimplerDevice.replace_sample`, 12.4+), set `in_note` / `choke_group` | Choke groups (16), `Simpler.retrigger` | One strip for the whole rack; per-pad level via chain mixer (not researched here) | Every step `unknown`. Best musical result, largest effort |
| **C. Simpler (or Drum Sampler) per MIDI track** | Five MIDI tracks, one instrument each | `song.create_midi_track` (`unknown`), device load, `replace_sample` | No cross-track choke | Strip per sound | Same device-load blockers as B without B's benefits; not recommended |
| **D. Sampler** | Full sampler instrument | n/a | n/a | n/a | **Not available in Standard** (finding 1); would need the user to upgrade to Suite |
| **E. Impulse** | 8-slot one-shot player | not researched for API | Has its own Trigger/Gate decay modes ([manual 31.7.4](https://www.ableton.com/en/live-manual/12/live-instrument-reference/)) | One strip | Not examined further (no LOM page was read) |

_Interpretation:_ A answers "get the five sounds into the set and balance them" today. B answers "play the kit and program drums". C has no advantage over B. The acid-lines note already needs a MIDI track with a synth for route (b); the kit and the bass line would share the same "create MIDI track + load native device" blocker (M1, M2).

### Findings

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| 1 | Edition comparison: Simpler, Drum Sampler, Drum Rack and Impulse in both Standard and Suite; Sampler only in Suite; Max for Live only in Suite. (Page read through a summarising fetch, first 100,000 of 128,256 characters.) | medium-high | [Ableton: compare editions](https://www.ableton.com/en/live/compare-editions/) |
| 2 | Drum Sampler arrived with Live 12.1 (free update). Its manual section describes Trigger mode (sample plays for the Hold time after note release, Hold can be `inf`) and Gate mode (fade by Decay after note release); it is described as a device for one-shot samples in Drum Racks. | medium (news article for the version; manual summary for the modes) | [RouteNote on 12.1](https://routenote.com/blog/ableton-live-12-1-update-adds-drum-sampler-more/), [Manual: Instrument Reference 31.4](https://www.ableton.com/en/live-manual/12/live-instrument-reference/) |
| 3 | LOM `SimplerDevice`: `playback_mode` (get/set/observe; 0 Classic, 1 One-Shot, 2 Slicing), `retrigger` (get/set/observe), `voices`, `replace_sample(file_path)` (absolute path, supported format). The LOM page gives no version column. | high for existence, version from release notes (12.4, earlier note) | [LOM SimplerDevice](https://docs.cycling74.com/apiref/lom/simplerdevice/) |
| 4 | The manual text for Simpler's One-Shot/Gate behaviour could **not** be read (the fetch of the Instrument Reference was cut off before the Simpler chapter, twice). What One-Shot does on note-off is therefore not claimed. | gap | same manual page |
| 5 | LOM `RackDevice`: `chains`, `return_chains`, `drum_pads` (128 pads of the top-level Drum Rack), `has_drum_pads`, `copy_pad(source_index, destination_index)`, `insert_chain([index])` (since Live 12.3; "throws an error if insertion isn't possible"). | high (doc) | [LOM RackDevice](https://docs.cycling74.com/apiref/lom/rackdevice/) |
| 6 | LOM `DrumPad`: `chains` (get/observe), `mute`, `solo`, `name`, `note` (get only), function `delete_all_chains` (page gives no details). Nothing there loads a sample. | high (doc) | [LOM DrumPad](https://docs.cycling74.com/apiref/lom/drumpad/) |
| 7 | AbletonOSC `device.py` registers only `class_name`, `name`, `type` plus the parameter handlers. A grep for `rack`, `chain`, `drum` in the file finds no match. `track.py` has device lists (`devices/name`, `class_name`, `type`, `can_have_chains`) and `delete_device`. Read on `master` today; the project pins commit `0ca68214` (capability note), which was **not** diffed against master. | high for master, unverified for the pin | [device.py](https://raw.githubusercontent.com/ideoforms/AbletonOSC/master/abletonosc/device.py), [track.py](https://raw.githubusercontent.com/ideoforms/AbletonOSC/master/abletonosc/track.py) |
| 8 | `song.py` exposes `create_audio_track`, `create_midi_track`, `create_return_track`, `delete_return_track`, `delete_track`, `duplicate_track` as methods (list around lines 24-32). Only `create_audio_track` is `tested`. | high (source), registry status from `capabilities.json` | [song.py](https://raw.githubusercontent.com/ideoforms/AbletonOSC/master/abletonosc/song.py) |

## 2. Programmability matrix (stage 1 and 2)

| Need | Call | Exists in AbletonOSC (master)? | Registry id to add (new ids are not yet in `contracts/capabilities.json`; they enter as `unknown` and stay so until the user's run) |
| --- | --- | --- | --- |
| New audio track per sound | `/live/song/create_audio_track` | yes | `song.create_audio_track` is already `tested` |
| Clip with the WAV | `/live/clip_slot/create_audio_clip` | via the AbeltonGod extension | already `tested` |
| Name the track | `/live/track/set/name` | yes: `name` is in `properties_rw` (`track.py`) | `track.name.set` |
| Colour the track | `/live/track/set/color_index` | yes (`properties_rw`) | `track.color_index.set` (cosmetic, low priority) |
| Create MIDI track | `/live/song/create_midi_track` | yes | `song.create_midi_track` (already listed, `unknown`) |
| Insert Drum Rack / Simpler | `Track.insert_device(name)` | **no** (needs handler) | `track.insert_device` |
| Create chain, set `in_note`, `choke_group` | `RackDevice.insert_chain`, `DrumChain.*` | **no** | `drum_rack.chain.create`, `drum_rack.chain.in_note.set`, `drum_rack.chain.choke_group.set` |
| Load sample on a pad | `Chain.insert_device` + `SimplerDevice.replace_sample` | **no**; the Drum Sampler's LOM class was not looked up | `drum_rack.pad.load_sample` |
| Read what exists | `/live/track/get/devices/class_name`, `.../can_have_chains` | yes | `track.devices.class_name.get` |

The earlier note ([drum-rack choke](2026-11-02_drum-rack-choke-and-oneshot-placement.md) section 2) already lists the Drum Rack rows; this table adds the track naming/creation rows for stage 1.

## 3. Basic mixing helpers (what the Remote Script can do)

### Calls (AbletonOSC master, read today)

| Helper | OSC address | LOM object | Source line |
| --- | --- | --- | --- |
| Volume get/set (+ listen) | `/live/track/get/volume`, `/live/track/set/volume` | `track.mixer_device.volume` (`DeviceParameter`) | `track.py` ~lines 78-91; `_set_mixer_property`, `_get_mixer_property` ~lines 234-240 |
| Pan get/set | `/live/track/get/panning`, `/live/track/set/panning` | `track.mixer_device.panning` | same |
| Send level get/set | `/live/track/get/send <track> <send>`, `/live/track/set/send <track> <send> <value>` | `track.mixer_device.sends[i].value` | `track.py` ~lines 94-103 |
| Mute / solo / arm | `/live/track/set/mute|solo|arm` | `Track.mute` etc. | `properties_rw` list; `track.mute.*` is `tested` |
| Output meter | `/live/track/get/output_meter_level` (+ left/right) | `Track.output_meter_*` | `properties_r` list |
| Device parameter values | `/live/device/get|set/parameter/value`, `/live/device/get/parameters/value|min|max|name` | `Device.parameters[i]` | `device.py`, functions `device_get_parameter_value` / `device_set_parameter_value` and the `parameters/*` handlers (about the last 80 lines) |
| Create return track | `/live/song/create_return_track` | `Song.create_return_track()` | `song.py` method list |
| Undo | `/live/song/undo` | `Song.undo()` | `song.undo` is `tested` |

Line numbers are from a read of `master` on 2026-11-02 and are approximate to a few lines. `track.py`, `device.py` and `song.py` at the pinned commit `0ca68214` were diffed against `master` by the reviewer and are identical (reviewer's check; I did not run that diff myself). The earlier note cites `track.py:81-86`, `:98-103`, `device.py:128-131` from another snapshot (consistent in content).

### Findings

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| 9 | `TrackHandler` resolves a track index only against `self.song.tracks` (`track_callback` in `init_api`). A grep for `return_tracks` and `master` over `track.py`, `device.py`, `song.py` returned nothing relevant. So **return-track and master-track volume/pan/devices are not reachable** through these handlers (inference from absence; verify with M10). A send level **is** reachable (`mixer_device.sends`) once a return exists. | medium-high | [track.py](https://raw.githubusercontent.com/ideoforms/AbletonOSC/master/abletonosc/track.py) |
| 10 | The first argument `"*"` makes `track_callback` loop over **all** tracks; with `set/volume` or `set/mute` that writes every track. | high (source) | same |
| 11 | LOM `MixerDevice`: `volume`, `panning`, `sends` (one per return track), `track_activator`, split-stereo pans are `DeviceParameter` children, **get only** on the child; the value is changed via the parameter. `panning_mode` is get/set. The page gives **no ranges and no units**. | high | [LOM MixerDevice](https://docs.cycling74.com/apiref/lom/mixerdevice/) |
| 12 | LOM `DeviceParameter`: `value` is "internal value between min and max" (get/set/observe); `min`, `max`, `default_value` (non-quantized only), `automation_state` (0/1/2), `str_for_value(v)`, `display_value` (get/set/observe), `re_enable_automation`. No dB mapping on the page. | high | [LOM DeviceParameter](https://docs.cycling74.com/apiref/lom/deviceparameter/) |
| 13 | A commonly quoted "0.85 = 0 dB" for the volume fader is **not** on either LOM page. Not used here; a client must read `min`, `max`, `default_value` and `str_for_value` from the user's Live (M6) and convert dB through a table it measures. | high that the pages lack it | LOM pages above |
| 14 | Setting a parameter that has automation probably puts it in the "overridden" state (inference, see MIDI note Q3 pitfall). Unverified. | low | earlier note |

### Risk of writes

| Helper | Worst realistic harm | Reversible? | Proposed approval | Notes |
| --- | --- | --- | --- | --- |
| Read volume/pan/sends/meters/devices | None | n/a | `routine` | The read-only `list_mixer` would be a sibling of `list_tracks` |
| Set volume | Sudden level jump, loudness on the user's monitors | Via `song.undo` is **unknown** for value changes (only clip creation was shown, run 4 in the registry notes); safer: read old value, send the old value back | `confirm`, with a plan "track X: -x dB -> -y dB" | Clamp locally to a user-set ceiling; refuse a raise above the current value unless the plan says so (open question 2) |
| Set pan | Mild | same as above | `confirm` | Range from `min`/`max` at runtime |
| Set send | Reverb/delay level jump | same | `confirm` | Needs a return track to exist; refuse an index >= number of returns |
| Mute / solo | Silence confusion | `tested` write for mute | `confirm` (a registry `write`) | Solo changes other tracks' audibility: show it in the plan |
| Set device parameter | Wrong index sets a different knob | undo unknown | `confirm`; local check against the parameter list (`name`, `min`, `max`, `is_quantized`) read right before | Never address by index only: re-read the name and compare |
| Create return track | Adds a track to the set | undo unknown for this call | `confirm` | Not in the registry as tested |
| Wildcard track `*` | Writes every track | n/a | **forbidden** by the client | Reject any non-integer track index |

**Mapping to the guard (D-011).** D-011 names the guard levels green/warn/stop (resource use). The *approval* levels are a different mechanism in the orchestrator: `Approval.ROUTINE` and `Approval.CONFIRM` (`src/orchestrator/tools.py`, lines 76-78), where "a capability that is not a read needs approval `confirm`". So: reads `routine`, every write `confirm`. Each confirmed write counts toward the profile limit `max_live_writes` (`config/guard-policy.json`: `kick_generation` allows 2, `mentor_answer` 0). A mix pass touching five tracks (volume + pan + one send each) is 15 writes, so it needs its own profile or a "one confirm for a listed batch counts as N writes" rule. _That rule is a proposal for the lead; no decision exists._

### Meters and loudness

`output_meter_level` / `_left` / `_right` are readable properties (`properties_r`). The LOM pages read here do not state what scale they use or whether they are peak or RMS; so a "gain staging" helper that sets levels from meters is **not** supported by evidence yet (M11). Loudness targets in LUFS need an audio capture path (see [mix loudness targets](2026-10-29_mix-loudness-targets.md)); the meters do not give that.

## 4. What a minimal "kit builder" tool needs in `contracts/`

Existing facts (from the repo): `import_sample` takes `sample_id` (never a path), `track_index`, optional `slot_index`, approval `confirm`, 1 optional field; `generate_sample` ids are `<category>-N` in the same session table and `import_sample` takes them unchanged (`src/orchestrator/sample_tools.py` docstring); the strict optional-parameter budget is **24 of 24** (INTERFACES.md, "Optional-parameter budget"); no `minimum`/`pattern` in the strict subset; `sample-metadata` `category` enum is `kick, clap, hat`.

### Sketch (PROPOSAL for the lead; not a design decision)

1. **Stage 1 tool `build_kit_tracks`** (new `contracts/tool-build-kit-tracks.schema.json`). Input, every field **required**, so it adds 0 optional fields:
   - `pieces`: array of objects `{role, sample_id, track_index, slot_index}`, `role` an enum (`kick`, `clap`, `hat`, `snare`, `rim`), `track_index` an existing audio track (the v1 rule of `import_sample`), `slot_index` required (the first-empty-slot convenience would be an optional field).
   - `additionalProperties: false`, no `minItems` (strict subset); the handler enforces 1 to 5 pieces and no duplicate role/track.
   - Behaviour: the same checks as `import_sample` per piece (sha256, library path, empty slot), one combined plan, one `confirm`, then N `create_audio_clip` calls with read-back per clip. Partial failure is reported per piece; nothing is silently retried (D-002).
   - Capabilities: `clip_slot.create_audio_clip`, `song.track_names.get`, `track.has_audio_input.get`, `clip_slot.has_clip.get`, `clip.file_path.get`, `song.num_scenes.get` (all `tested`). Naming tracks would add `track.name.set` (needs a test, M4). Guard: `max_live_writes` = number of pieces.
2. **Stage 2 manifest `contracts/drum-kit.schema.json`** (a file the user keeps, produced by the planner and used by a later Drum Rack builder): `{schema_version, name, pads: [{role, sample_id, file, sha256, note, choke_group | null}]}`. The `note` default (36 kick upward, GM-like) is a **proposal**; Live's own Drum Rack default for the first pad is C1 = note 36 in common Live use, but that was not read in the sources here and must be confirmed (M9).
3. **Additive contract change for sidecars:** `sample-metadata` `category` enum gets `snare` and `rim` when their params contracts land (owner audio-engineer; the existing `snare-targets` and `rim-targets` notes are about targets, not contracts).
4. **Mixer tools:** `list_mixer` (no arguments, `routine`, reads volume/pan/sends/mute) and `set_mixer` (confirm). To stay inside the 24-optional budget, `set_mixer` would take one required array `changes` of `{track_index, parameter (enum volume|panning|send|mute), send_index, value}` with all four keys required (use `-1` / `0` as an agreed "not used" placeholder for `send_index` only if the lead accepts it; this is a design smell, hence **proposal only**). Value units: store **dB or percent on our side**, convert with the runtime-read `min`/`max` and a measured map (finding 13).
5. **Capabilities registry:** add the ids from sections 2 and 3 as `unknown` in one `contract-change` PR (owner bridge-engineer). `tool-*` schemas may only name `tested` capabilities (orchestrator rule), so the mixer tools can be defined and tested with the fake bridge in CI but stay off the live toolbox until M6-M8 are green.

### Not needed in contracts for stage 1

No kit manifest, no MIDI. The kit is "five existing tool calls and one plan".

## 5. User test list M1-M12 (Windows PC, Live 12.4.5)

Prefix `M` (mixer/kit) to avoid clashing with A1-A8 in the acid-lines note and with K1-K5, the listening-test labels used elsewhere. All use a scratch set, never the user's real project. A script that logs raw replies and read-backs is assumed (bridge-engineer); no test has been run. "Unlocks" = the registry id that may move from `unknown` to `tested` in its own `contract-change` PR with the log excerpt (CLAUDE.md: only the user's evidence can do this).

| # | Test | Expected result | Unlocks |
| --- | --- | --- | --- |
| M1 | `/live/song/create_midi_track -1`, then read `track_names` | A new MIDI track appears at the end; `/live/track/get/has_midi_input` = true; one `song.undo` removes it | `song.create_midi_track`, `track.has_midi_input.get` |
| M2 | Handler for `Track.insert_device("Drum Rack")` on the M1 track (needs the extension); read `devices/class_name` | Device appears; class name printed (record the real string, do not assume); a deliberately wrong device name fails with an error, no crash (the Standard-vs-Suite device list was not checked, so no Suite-only name is proposed) | `track.insert_device`, `track.devices.class_name.get` |
| M3 | On a **hand-built** Drum Rack with 5 pads loaded by drag: read `RackDevice.drum_pads`, `DrumPad.chains`, `DrumChain.in_note`, `choke_group` via a new read-only handler | Five non-empty pads, notes printed, class name of the per-pad device (Simpler or Drum Sampler) printed | `drum_rack.chain.choke_group.get` (and read ids) |
| M4 | `/live/track/set/name` on an audio track, then read back; also `color_index` | Name equal on read-back; undo restores (record whether it does) | `track.name.set`, `track.color_index.set` |
| M5 | Five new audio tracks (`create_audio_track` x5), one `create_audio_clip` each (kick, clap, hat, snare, rim WAV), read back `file_path`; Live must stay responsive | Five clips, five equal `file_path` read-backs; track names changed by Live as seen before (registry note); **this widens the already-tested scope (new track, five calls in a row)**, no new id | none new; extends `clip_slot.create_audio_clip` evidence |
| M6 | On one track: read `volume` (AbletonOSC returns only the value; `min`, `max`, `str_for_value` need an added read on the mixer parameter), set a value, read back, set the old value back | Read-back equals the sent value (within float tolerance); the audible fader moves; min/max/default recorded for the dB table | `track.volume.get`, `track.volume.set` |
| M7 | Same for `panning` (set -1, 0, +1 if the range allows) | Read-back equal; pan knob moves | `track.panning.get`, `track.panning.set` |
| M8 | `create_return_track`, then `set/send 0` value on a kick track, read back; a send index beyond the number of returns | Read-back equal; the out-of-range index returns an error, not a crash or a silent no-op | `song.create_return_track`, `track.send.get`, `track.send.set` |
| M9 | Does the volume write survive `song.undo`? (Set, undo once, read back.) And: with a parameter that has automation drawn by the user, set it and read `automation_state` | Record: undo restores or not; `automation_state` becomes 2 or not (answers finding 14). Also record the first Drum Rack pad's receive note shown by Live | evidence for `reversible` flags only, not a status |
| M10 | `/live/track/get/volume <index of the master or a return>` (index = number of tracks, then a negative index) | Index == track count: expect an error (`IndexError` in Live's log) and no write. This shows only that the index is out of range; whether master/return volume is reachable stays an **inference** (finding 9). A negative index is valid Python (`song.tracks[-1]` is the last track), so Live would likely **address the last track**, not fail: the client itself must reject negative indices and indices >= track count; do not rely on Live to refuse (probe the negative case only with a read, never a write). **Do not** test `*` on a set that matters; a one-track set only | negative evidence; informs the contract |
| M11 | While a clip plays, poll `output_meter_level` ten times; compare with Live's meter by eye | Values change; record the range (0-1?) and whether it correlates with the meter. No loudness claim | `track.output_meter_level.get` |
| M12 | Device parameter set: on a native device on an audio track (the user drops Live's Utility), read `parameters/name`, set `Gain` through `set/parameter/value`, read back, re-read the name first | Name matches, value equal on read-back | `device.parameter.value.get`, `device.parameter.value.set` |

Not in this list because it is already specified: the hand-built Drum Rack and choke recipe (choke note, section 5) and the `replace_sample` / `insert_chain` probes (choke note D3), which become a M13+ only after M2 and M3 pass.

## Known pitfalls

- **Index vs name.** A device-parameter index changes when the device changes; re-read names right before a write (risk table).
- **`create_audio_clip` rules.** Registry limits: verified only on an existing audio track, Session view, one WAV, undo unreliable after user interaction. Five tracks in a row (M5) is outside what was shown.
- **Replies have no request ids** (protocol note); a mix pass of many writes needs the client's marker bracketing per request.
- **Drum Rack default In Note** is "All Notes" (-1) on creation, which greys Choke (choke note, finding 5).
- **Strict-budget trap:** an optional `slot_index` or `send_index` in a new tool breaks the 24 limit and the pinned test (INTERFACES.md).
- **Summarising fetches.** Ableton pages (compare editions, Instrument Reference) and the LOM pages were read through a summarising fetch; wording is paraphrased. The Instrument Reference was truncated before the Simpler chapter.

## Test strategy hints

- **CI (fake OSC server, labelled "not an Ableton test"):** argument shape of each new address; refusal of `*`, negative, non-integer, out-of-range indices before any send; plan text shows old and new values; read-back mismatch is reported as failure; gate refuses while the capability is `unknown`; kit tool refuses a duplicate role, a modified file (sha256), an occupied slot, a MIDI track; guard counts one Live write per piece.
- **User's machine:** all of M1-M12; the sound of a changed level or pan; whether undo reverts value writes.
- **Mutation ideas for the foundation checks:** index check removed (a `*` must then reach the fake server and the test turn red); read-back comparison removed.

## Implications for the lead

- A kit can be assembled **today** at the clip level with only `tested` capabilities (M5 widens the evidence). A playable Drum Rack waits on M1-M3 and new handlers; do not promise it before those results.
- Sampler is Suite-only; Drum Sampler is in Standard and arrived in 12.1 (medium confidence); Simpler's One-Shot behaviour is **not** read, so no claim is made about hat decay in a Simpler pad.
- Return and master tracks are probably out of reach for AbletonOSC volume/pan; a "master bus" helper needs either an extension or is dropped. Worth saying before a mix feature is promised.
- Any mixer write tool needs: no wildcard, old-value readback, a confirm plan, a measured dB map. Suggest a guard profile with a higher `max_live_writes` for mix passes (the lead's call).
- Suggested State update line: "Research: drum-kit assembly and mixer helpers surveyed; stage 1 (five audio tracks) possible with tested capabilities; Drum Rack build, volume/pan/send writes unverified; user test list M1-M12 proposed; nothing run in Live."
- Not opened: Max for Live (rejected by D-001; would need the user to reopen it), Sampler (Suite only).

## Decisions (lead, 2026-11-02)

From the lead's comment on #332 (the user wants no questions):
1. First kit = five audio tracks with one clip each; no MIDI-playable rack yet. Drum Rack steps stay `unknown` until M1-M12.
2. Volume writes may raise or lower; every write is `confirm`; a mix pass larger than `max_live_writes` is refused until the user raises the limit (not changed now).
3. No Group Track in stage 1.

(The three open questions in "For workers" are answered by these decisions.)
