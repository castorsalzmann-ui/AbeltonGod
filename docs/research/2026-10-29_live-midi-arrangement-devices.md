# Research: Live functions for MIDI, arrangement, automation, devices and set copies

- **Date:** 2026-10-29 (all sources opened on this date)
- **Receiving issue:** #98 (D-023 cluster 1; feeds questionnaire tab 3 task A1 and tab 2 task C-7)
- **Versions researched against:**
  - Live Object Model reference at docs.cycling74.com, which states "This document refers to Ableton Live version 12.4.5" ([LOM index](https://docs.cycling74.com/apiref/lom/)). The user runs Live 12 Standard 12.4.5 (`docs/CURRENT_STATE.md`, environment table). Live 12.4.15 was released on 2026-10-28 ([Live 12 release notes](https://www.ableton.com/en/release-notes/live-12/)); nothing below was checked against it.
  - AbletonOSC `master` at `0ca68214bd62c9b5cb641ca34006cfd70ba94430` (2025-11-19). This is the commit the earlier note also used; no newer commit exists. File:line citations below refer to this commit.
  - Python-API usage evidence: [gluon/AbletonLive12_MIDIRemoteScripts](https://github.com/gluon/AbletonLive12_MIDIRemoteScripts) at `e83d519` (unofficial decompile of Live 12.4's bundled scripts). [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) at `9dddc7b` (MIT, community project).
- **Related note, not repeated here:** `docs/research/2026-10-28_abletonosc-protocol-and-create-audio-clip.md`. It covers the wire protocol, the "no reply for setters" rule, the `/live/error` relay and the one-line `methods`-list patch (option A) for `create_audio_clip`. Every "extension" below uses the same two patterns: add a name to a `methods` list, or add a custom handler.
- **Nothing here was run in Live.** Every answer is "not verified" until an experiment in the last section has been done on the user's machine.

Confidence: **high** = official LOM/manual text or AbletonOSC source read directly. **medium** = Ableton's own scripts through an unofficial decompile, or a community project. **low** = inference with no direct source. Text marked _Interpretation:_ is my inference, not what a source says.

---

## Q1 — Which calls create MIDI tracks/clips and write/read notes (Session and Arrangement)?

**Answer.**

| Step | LOM (Live 12.4.5) | AbletonOSC today |
| --- | --- | --- |
| Create MIDI track | `Song.create_midi_track(index)`, where -1 appends | `/live/song/create_midi_track <index>`. Generic method (`abletonosc/song.py:25`, dispatched at `:47-48` via `handler.py:27-29`). No reply. |
| Session MIDI clip | `ClipSlot.create_clip(length)`. Length must be > 0; the slot must be empty and on a MIDI track. | `/live/clip_slot/create_clip <track> <slot> <length>` (`clip_slot.py:30`, `:46-48`) |
| Arrangement MIDI clip | `Track.create_midi_clip(start_time, length)`. Errors on non-MIDI or frozen tracks, on tracks being recorded into, and on times outside [0, 1576800]. | **Not exposed.** `grep` finds no `create_midi_clip`. |
| Write notes | `Clip.add_new_notes({"notes":[…]})` (since 11.0). Required keys: `pitch`, `start_time`, `duration`. Optional: `velocity`, `mute`, `probability`, `velocity_deviation`, `release_velocity`. Returns note IDs. | `/live/clip/add/notes <t> <s> (pitch start dur vel mute)*`. Groups of 5, each built as `Live.Clip.MidiNoteSpecification`, then one `add_new_notes` call (`clip.py:212-222`, `:234`). No probability/deviation fields. Note IDs are not returned. |
| Read notes | `get_notes_extended(from_pitch, pitch_span, from_time, time_span)` (11.0), `get_all_notes_extended` (11.1), `get_notes_by_id` | `/live/clip/get/notes <t> <s> [pitch_start pitch_span time_start time_span]` returns flat 5-tuples (`clip.py:199-210`, `:233`). Defaults: `0, 127, -8192, 16384`. |
| Modify / delete notes | `apply_note_modifications`, `remove_notes_extended`, `remove_notes_by_id` | `/live/clip/remove/notes` (`clip.py:224-231`, `:235`), `/live/clip/remove_notes_by_id` (`clip.py:137`). No `apply_note_modifications`. |
| Notes in Arrangement clips | Same `Clip` class. `Track.arrangement_clips` lists Arrangement clips (since 11.0). | **Not addressable.** Every `/live/clip/*` handler resolves `track.clip_slots[clip_index].clip` (`clip.py:120-122`), so only Session clips work. Arrangement clips are read-only: name/length/start_time lists (`track.py:120-137`). |

**Sources.** [LOM Song](https://docs.cycling74.com/apiref/lom/song/), [LOM ClipSlot](https://docs.cycling74.com/apiref/lom/clipslot/), [LOM Track](https://docs.cycling74.com/apiref/lom/track/), [LOM Clip](https://docs.cycling74.com/apiref/lom/clip/) (all retrieved 2026-10-29); AbletonOSC files and lines as cited.
**Confidence.** High for the LOM and AbletonOSC facts.

_Interpretation:_ `add_new_notes` is called in Python with a tuple of `MidiNoteSpecification` (AbletonOSC `clip.py:216-222`; Ableton's own `novation/print_to_clip.py:118` and `ableton/v3/control_surface/components/note_editor.py:367` do the same), not with the Max dict form. An extension must use the Python form.

_Interpretation (pitfall):_ the default read range `pitch_start=0, pitch_span=127` covers pitches 0–126, if `pitch_span` is a count, as the name suggests. Pitch 127 would then be missed. → To verify.

---

## Q2 — Which calls place clips in the Arrangement, set locators/section names and read song length?

**Answer.**

| Need | LOM | AbletonOSC today |
| --- | --- | --- |
| Session clip → Arrangement | `Track.duplicate_clip_to_arrangement(clip, destination_time)`: the source can be a Session or Arrangement clip; time is in beats. Ableton's own script uses the return value as the new clip (`ableton/v3/live/action.py:164`, medium). | **Not exposed.** |
| New empty MIDI clip in Arrangement | `Track.create_midi_clip(start_time, length)` | **Not exposed.** |
| Audio file into Arrangement | `Track.create_audio_clip(file_path, position)`: absolute path, position in [0, 1576800]. Errors on non-audio or frozen tracks and on tracks being recorded into. | **Not exposed** (same gap as `ClipSlot.create_audio_clip`, see the related note) |
| Read Arrangement clips | `Track.arrangement_clips` | `/live/track/get/arrangement_clips/{name,length,start_time}` (`track.py:120-137`) |
| Add locator | `Song.set_or_delete_cue()` adds or removes a cue at the current Arrangement position | `/live/song/cue_point/add_or_delete` (`song.py:258`). Set the position first with `/live/song/set/current_song_time <beats>` (`song.py:57`, `:93-94`). |
| Name a locator | `CuePoint.name` (get/set/observe) | `/live/song/cue_point/set/name <index> <name>` (`song.py:259-264`) |
| Move a locator | `CuePoint.time` is **get/observe only** | none (only delete + re-add) |
| List locators | `Song.cue_points` | `/live/song/get/cue_points` returns `name, time, …` (`song.py:241-245`) |
| Jump to locator | `CuePoint.jump()` | `/live/song/cue_point/jump <index or name>` (`song.py:247-256`) |
| Song length | `Song.song_length` ("slightly longer than `last_event_time`", beats); `Song.last_event_time` (last automation point, clip end, cue or loop end) | `/live/song/get/song_length` (`song.py:85`). `last_event_time` is **not exposed**. |

**Sources.** [LOM Track](https://docs.cycling74.com/apiref/lom/track/), [LOM Song](https://docs.cycling74.com/apiref/lom/song/), [LOM CuePoint](https://docs.cycling74.com/apiref/lom/cuepoint/) (retrieved 2026-10-29); AbletonOSC lines as cited; decompiled `ableton/v3/live/action.py:136,164` (gluon `e83d519`).
**Confidence.** High (LOM, AbletonOSC). Medium for the return value of `duplicate_clip_to_arrangement`.

_Interpretation:_ Live has no separate "section" object in the LOM class list ([LOM index](https://docs.cycling74.com/apiref/lom/)). "Section names" would be locator (cue point) names.

_Interpretation (pitfall):_ `set_or_delete_cue` is a toggle. Called on an existing locator it deletes that locator. A tool must read `cue_points` first and compare. The release notes record two related crashes. `duplicate_clip_to_arrangement` crashed when source and target track were the same; fixed in 12.4. Max for Live `create_audio_clip`/`create_midi_clip` crashes were fixed in 12.4 ([release notes](https://www.ableton.com/en/release-notes/live-12/)). The user's 12.4.5 includes both fixes.

---

## Q3 — Can automation be written (track volume, device parameters)? Which objects/calls?

**Answer.** Two different things:

1. **Static values (no automation):** yes, already in AbletonOSC.
   - `/live/track/set/volume` and `/live/track/set/panning` set `track.mixer_device.<prop>.value` (`track.py:81-86`, `:234-237`).
   - `/live/track/set/send <t> <send> <value>` (`track.py:98-103`).
   - `/live/device/set/parameter/value <t> <d> <p> <value>` (`device.py:128-131`, `:139`).
   - `/live/device/set/parameters/value` sets all parameters in index order (`device.py:70-72`, `:80`).
   - Values are the parameter's internal `value` in [min, max], not the display value ([LOM DeviceParameter](https://docs.cycling74.com/apiref/lom/deviceparameter/)).
2. **Automation envelopes (breakpoints over time):**
   - **Session clip envelopes, yes, through the Python API, not through AbletonOSC.**
     - Ableton's own Push script calls `clip.automation_envelope(param)`. If that returns nothing, it calls `clip.create_automation_envelope(param)` and then `envelope.insert_step(start, duration, value)`. It reads back with `envelope.value_at_time(t)` (decompiled `pushbase/automation_component.py:92-99`, `:114-121`, `:164`).
     - These four calls are **not** on the Cycling '74 LOM Clip page. That page has only `has_envelopes`, `clear_envelope(device_parameter)` and `clear_all_envelopes` ([LOM Clip](https://docs.cycling74.com/apiref/lom/clip/)). The `AutomationEnvelope` class is not in the LOM index, and its URL returned an error.
   - **Arrangement track automation lanes: no call found.**
     - The manual says Arrangement clips have only *modulation* clip envelopes. Arrangement automation lives on the track's automation lane ([Live 12 manual, Clip Envelopes, 27.1/27.3](https://www.ableton.com/en/live-manual/12/clip-envelopes/)).
     - I found no LOM or Python-API object for a track's Arrangement automation lane.
   - **Automation state:** `DeviceParameter.automation_state` (0 none, 1 active, 2 overridden) and `re_enable_automation()`; `Song.re_enable_automation()`. AbletonOSC exposes only the song-level `/live/song/re_enable_automation` (`song.py:38`).

**Sources.** AbletonOSC lines as cited; [LOM DeviceParameter](https://docs.cycling74.com/apiref/lom/deviceparameter/), [LOM Clip](https://docs.cycling74.com/apiref/lom/clip/), [Live 12 manual: Clip Envelopes](https://www.ableton.com/en/live-manual/12/clip-envelopes/) (retrieved 2026-10-29); decompiled Push script (gluon `e83d519`). The community MCP tool [`write_automation`](https://glama.ai/mcp/servers/wstierhout/ableton-live-mcp/tools/write_automation) also writes *clip* automation only (medium).
**Confidence.**
- Static values: high.
- Session clip envelopes via the Python API: medium. The source is an unofficial decompile and is not documented by Ableton.
- "No Arrangement-lane call": medium. It rests on absence of evidence in the sources I searched.

_Interpretation:_ there are two possible routes to Arrangement automation.
- (a) Write an envelope on a Session clip, then `duplicate_clip_to_arrangement`. Whether Live turns that envelope into track automation, as it does when recording Session to Arrangement, is unknown.
- (b) Record automation in real time: Arrangement record plus parameter writes while playing. Timing would then depend on AbletonOSC's ~100 ms tick (related note, fact 7). The result would not be deterministic.

Both → To verify.

_Interpretation (pitfall):_ setting a parameter that already has automation probably puts it into the "overridden" state (`automation_state = 2`), as a manual change does in Live. → To verify.

---

## Q4 — Can devices/instruments be loaded onto a track and their parameters set (browser access)?

**Answer.**
- **Parameters: yes, today.** AbletonOSC already exposes:
  - device lists per track: names, types, class names, can_have_chains (`track.py:139-163`)
  - parameter name/value/min/max/is_quantized lists, single parameter get/set and value_string (`device.py:52-142`)
  - `/live/track/delete_device` (`track.py:33`)
- **Loading: not in AbletonOSC** (`grep` finds no `browser`, `load_item` or `insert_device`). Two Live routes exist:
  1. **`Track.insert_device(device_name, target_index=end)`, since Live 12.3.** `device_name` is the name shown in Live's UI. Only native Live devices work; Max for Live devices and plug-ins do not. It throws if the device cannot be inserted ([LOM Track](https://docs.cycling74.com/apiref/lom/track/); release notes 12.3 list it under "Max 9.0.9 API additions"). `Chain.insert_device` and `RackDevice.insert_chain` were added at the same time.
  2. **Browser, Python only.**
     - `Live.Application.get_application().browser`, then `browser.load_item(item)`. Ableton's Push script uses `self.application.browser` and `browser.load_item(...)` (decompiled `Push/push.py:359`, `Push/browser_model.py:69`).
     - ableton-mcp finds an item by URI under `browser.instruments/sounds/drums/audio_effects/midi_effects`. It sets `song.view.selected_track = track` and then calls `load_item` (`MCP_Server/bundled_ableton_remote_script/AbletonMCP_init.py:1231-1242`, `:1293-1326`).
     - The `Browser` class is **not** in the Cycling '74 LOM index (Max for Live has no access to it).
- **Reordering:** `Song.move_device(device, target, target_position)` and `Song.find_device_position(...)` are in the LOM ([LOM Song](https://docs.cycling74.com/apiref/lom/song/)). **This corrects finding #7 in `2026-10-28_ableton-integration.md`**, which said devices cannot be reordered via the API (a medium-confidence community source). AbletonOSC does not expose `move_device`.
- Related, but owned by the kick-in-tracks cluster: Live 12.4 added `SimplerDevice.replace_sample(path)` ([release notes](https://www.ableton.com/en/release-notes/live-12/)).

**Confidence.**
- AbletonOSC parameter calls and `insert_device` (LOM text): high.
- Browser `load_item` and its "selected track" target: medium (unofficial decompile plus community code; not documented by Ableton).

_Interpretation (pitfalls):_
- AbletonOSC writes parameter values without range checks (`device.py:128-131`). An out-of-range value would then fail in Live and come back as `/live/error`.
- `/live/device/set/parameters/value` writes parameters in index order starting at 0. A short list therefore also writes parameter 0, which is usually "Device On".
- Under Live 12 **Standard**, `insert_device` with a Suite-only device name should fail. → To verify.

---

## Q5 — Can a copy of the set be made without Save As? What does Live's undo cover for these writes?

**Answer — copy.**
- **No API call saves or copies the set.** The LOM Song page lists no save function. It has only read-only `file_path` and `name`, both empty if the set was never saved ([LOM Song](https://docs.cycling74.com/apiref/lom/song/)). AbletonOSC does not expose these two properties (`song.py:53-87`).
- The manual lists three UI commands: Save Live Set, Save Live Set As, and **Save a Copy**. Save a Copy writes a duplicate under a new name or location and leaves the original open ([Live 12 manual 5.4.1](https://www.ableton.com/en/live-manual/12/managing-files-and-sets/)). Triggering a menu command is in the desktop-window cluster, not answered here.
- Live keeps up to 10 backups in the project's `Backup` folder. Backups start from the second save (Live 10+) and are copies of *saved* versions ([Ableton help: Backup Sets](https://help.ableton.com/hc/en-us/articles/360000377870-Backup-Sets)).

_Interpretation:_ copying the `.als` file at `Song.file_path` on disk gives the last *saved* state, not the open set with unsaved changes. Inside a running set, the closest thing to a "copy" via the API is `Song.duplicate_track` (`/live/song/duplicate_track`, `song.py:32`) before a write. That copies one track, not the set.

**Answer — undo.**
- `Song.undo()`/`redo()` revert "the last operation" (LOM). AbletonOSC exposes `/live/song/undo`, `/live/song/redo` (`song.py:37,45`), `get/can_undo`, and `get/can_redo` (`song.py:82-83`).
- **Project evidence (Live 12.4.5):** one AbletonOSC mute write was reverted by one `/live/song/undo`. Multi-step undo is not verified (`contracts/capabilities.json`, `song.undo` notes; #5).
- Undo grouping exists in the Python API, but AbletonOSC does not expose it. Ableton's own scripts wrap several changes as one step with `song.begin_undo_step()` / `song.end_undo_step()` (decompiled `ableton/v3/control_surface/components/transport.py:65,144`; `ableton/v3/control_surface/elements/touch.py:29-31`). These are not on the Cycling '74 LOM Song page.
- The Undo History (View menu) lists every action since the set was opened. It is **not saved with the set**. Opening or creating a set is the first entry and cannot be undone. The manual states no step limit ([manual 5.4.2](https://www.ableton.com/en/live-manual/12/managing-files-and-sets/)).
- Undo granularity changes between releases. In 12.4.15, duplicating MIDI notes and continued Transformations create one undo step per operation ([release notes](https://www.ableton.com/en/release-notes/live-12/)).

**Confidence.**
- "No save call in the LOM", Save a Copy, the Backup folder, Undo History: high.
- `begin/end_undo_step`: medium.
- Which of the Q1–Q4 writes Live records as undo steps, and how many steps each takes: **unknown**. No source documents it per call.

_Interpretation:_ several calls could create several undo steps for one logical action.
- `/live/clip/add/notes` makes one `add_new_notes` call.
- `/live/device/set/parameters/value` makes one property write per parameter.
- `browser.load_item` may behave differently again.

An "undo my last action" tool should therefore either group the writes with `begin/end_undo_step` in an extension, or record how many undo steps each tool needs. → To verify.

---

## Q6 — Which of these exist in AbletonOSC already vs need an extension like `create_audio_clip`?

| Function | AbletonOSC `0ca6821` | Extension shape (smallest) |
| --- | --- | --- |
| Create MIDI track | **exists** (`song.py:25`) | — |
| Session MIDI clip (`ClipSlot.create_clip`) | **exists** (`clip_slot.py:30`) | — |
| Write/read/remove notes, Session clips | **exists** (`clip.py:199-235`). No probability/velocity_deviation, no note IDs on add. | — (custom handler only if those fields are needed) |
| Notes on Arrangement clips | missing | custom handler: resolve `track.arrangement_clips[i]` instead of `clip_slots[i].clip` |
| Arrangement MIDI clip (`Track.create_midi_clip`) | missing | add to `track.py` `methods` list (`:32-35`). Generic `_call_method` passes `start_time, length`. |
| Arrangement audio clip (`Track.create_audio_clip`) | missing | same one-word `methods`-list patch in `track.py` |
| Session → Arrangement (`duplicate_clip_to_arrangement`) | missing | custom handler (the argument is a Clip object, not a number) |
| Locators add/rename/list/jump, song length | **exists** (`song.py:241-264`, `:85`) | — |
| `last_event_time`, `file_path`, `name` | missing | add to `properties_r` in `song.py` (`:81-87`) |
| Track volume/pan/send, device parameter set/get | **exists** (`track.py:81-103`, `device.py:52-142`) | — |
| Clip automation envelopes (`automation_envelope`, `create_automation_envelope`, `insert_step`) | missing | custom handler (Clip + DeviceParameter objects) |
| Arrangement track automation lane | no Live call found | — (no extension possible without a Live call) |
| `Track.insert_device` (12.3+) | missing | add to `track.py` `methods` list. Generic call passes `device_name[, index]`. |
| Browser `load_item` | missing | custom handler (browser tree walk, select track, load) |
| `Song.move_device` | missing | custom handler (Device/Track objects) |
| Undo / redo / can_undo | **exists** (`song.py:37,45,82-83`) | — |
| `begin_undo_step` / `end_undo_step` | missing | add to `song.py` `methods` list. Python API only (medium). |
| Save / copy set | no Live call | — |

**Confidence.** High for "exists/missing": every row was checked against the source at `0ca6821`, by grep and by reading `song.py`, `track.py`, `clip.py`, `clip_slot.py`, `device.py`, `view.py`.

_Interpretation:_ "methods-list patch" works only when every argument is a plain OSC type (int, float, string). `_call_method` forwards the OSC params unchanged (`handler.py:27-29`). Calls that take Live objects (a Clip, Device, Track or DeviceParameter) need a custom handler that maps indices to objects. The same is true of AbletonOSC's own `duplicate_clip_to` (`clip_slot.py:61-67`).

---

## Implications for the lead (proposals only)

- Session-side MIDI work (create track, create clip, write/read notes, set device parameters, set locators) needs **no extension**. It needs only capability entries and the user's Live tests. That makes it the cheapest first step for tab 3 task A1.
- Arrangement placement, Arrangement notes, clip automation, device loading and undo grouping all need an AbletonOSC extension. The patch-vs-own-script choice in the `create_audio_clip` note applies here. With 6+ new handlers, several of them custom, option B (own remote script) looks more proportionate than many patches to a third-party install. That is for the bridge-engineer and lead to decide after the Phase 03 Live result.
- Arrangement *track-lane* automation has no known API route. Treat it as `unsupported` until experiment E7 says otherwise. Do not promise it in a feature issue.
- A "set copy" feature cannot be built on the API alone. It needs a user step (Save a Copy) or the desktop-window cluster's answer.
- `2026-10-28_ableton-integration.md` finding #7 ("devices cannot be reordered") is superseded by `Song.move_device` (LOM 12.4.5).

## To verify by experiment (user's machine, Live 12.4.5 or the version then installed)

Each item becomes an issue for the owning role (bridge-engineer unless noted).

1. **E1** `/live/song/create_midi_track -1` + `/live/clip_slot/create_clip t 0 4.0` + `/live/clip/add/notes t 0 36 0.0 0.25 100 0` (4 notes): read back with `/live/clip/get/notes`. Expect the same 5-tuples. Also add a note with pitch 127 and check whether the default read returns it (Q1 pitfall).
2. **E2** Undo cost: after E1, count how many `/live/song/undo` calls restore the set (snapshot compare, as in `bridge_check.py`). Do this separately for track create, clip create and one `add/notes` with 16 notes.
3. **E3** Locators: set `current_song_time` to 16.0, `cue_point/add_or_delete`, then `set/name 0 "Intro"`, then `get/cue_points`. Expect `("Intro", 16.0)`. A second `add_or_delete` at 16.0 should delete it. Check how `cue_points` is ordered after adding locators out of time order.
4. **E4** `/live/song/get/song_length` on an empty set, and after an Arrangement clip ends at bar 9. Compare with the clip end time.
5. **E5** (needs an extension) `Track.create_midi_clip(0.0, 16.0)`, `Track.create_audio_clip(path, 0.0)` and `duplicate_clip_to_arrangement(session_clip, 32.0)`: check the result with `/live/track/get/arrangement_clips/start_time` and the return value. Also check behaviour on a frozen track and on a track that is recording.
6. **E6** (needs an extension) clip envelope: `create_automation_envelope(track.mixer_device.volume)` on a Session clip, `insert_step(0, 1, 0.5)`, read back with `value_at_time(0.5)`.
7. **E7** Does E6's envelope become **track Arrangement automation** after `duplicate_clip_to_arrangement`? Look at the track's automation lane in Live.
8. **E8** `/live/device/set/parameter/value` on a parameter that has automation: read `automation_state` (needs an extension, or look in the UI). Expect 2 = overridden.
9. **E9** (needs an extension) `Track.insert_device("Drift")`, `insert_device("Auto Filter", 0)`, and one Suite-only name under Standard: record the result and the `/live/error` text.
10. **E10** (needs an extension) `browser.load_item` with an instrument and an audio effect: which track receives it (the selected track or the hotswap target?), and how many undo steps does it cost?
11. **E11** (needs an extension) `song.begin_undo_step()`, three writes, `end_undo_step()`: does a single `/live/song/undo` revert all three?
12. **E12** Out-of-range `/live/device/set/parameter/value`: does `/live/error` arrive, or does Live clamp the value silently?
13. **E13** Re-check E1–E12 if the user is on 12.4.15 or later (undo-step changes in 12.4.15).
