# Research: delivering a Goa arrangement to Live without writing through unverified functions

_Date: 2026-11-03 · Refs #338 (track G3) · Role: bridge-engineer. Sources opened 2026-11-03. **Nothing here was run in Live.** No capability status changes, no contract change. Builds on (not repeated): [acid lines to Live](2026-11-02_acid-lines-to-live.md) (route a, tests A1-A8), [MIDI/arrangement/devices](2026-10-29_live-midi-arrangement-devices.md), [arrangement planner](2026-10-29_arrangement-planner-sections-energy.md) (sections, energy), [drum kit and mixer](2026-11-02_drum-kit-assembly-and-mixer-feasibility.md)._

## For workers

- **Recommended path:** one multi-track Standard MIDI File (format 1) that the user drags into the Arrangement. It writes nothing through AbletonOSC, so the capability rule does not apply. Built: `src/audio_engine/arrangement_midi.py` (this PR).
- **`.als` generation: not now.** Format is undocumented and version-specific, and Live refuses sets saved by a newer point release. A writer would have to start from a set saved by the user's own Live. Only a read-only inspector (`scripts/als_inspect.py`) is delivered, so the user's real file can settle the open points (tests S1-S3).
- **AbletonOSC delivery (c):** out for now. `song.create_midi_track`, MIDI-clip creation, note writes and arrangement placement are `unknown` or absent in `contracts/capabilities.json`.
- **What Live does with the file is partly unverified.** Test list in section 5 (T1-T8). Unknowns that change the result: tempo import, section markers, empty tracks, clip length.

## 1. Findings

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| 1 | Live imports a MIDI file by browser drag or Create > Import MIDI File; Session View into the selected slot, Arrangement at the insert marker; clips do not reference the file. | high | [Live 12 manual, Managing Files and Sets](https://www.ableton.com/en/live-manual/12/managing-files-and-sets/) (earlier note, finding 7) |
| 2 | Tracks of a multitrack MIDI file "appear as individual clips distributed across consecutive Live MIDI tracks", new MIDI tracks created as needed; all clips start at the same timeline position (empty space is added at the start of a clip whose track starts later); Live ignores MIDI channels, so one track holding several channels becomes one clip. | medium (one magazine article, summarised fetch; Live version of the article not stated) | [Sound On Sound, MIDI files DAW to DAW](https://www.soundonsound.com/techniques/ableton-midi-files-daw-daw) |
| 3 | A format-0 file lands on ONE track; re-saving as format 1 "creates a new live-Track for each midi-Track in the file". | medium (forum, old thread, user reports) | [Ableton forum thread](https://forum.ableton.com/viewtopic.php?p=1078384) |
| 4 | Live reads tempo changes from an imported MIDI file when the file contains "a MIDI note, or group of notes which span the entire length of the tempo changes"; a prompt appears, Yes accepts, the result is automation on Master > Song Tempo. The article is about tempo MAPS (changes); whether a single constant tempo event triggers the same prompt is not stated. | medium-high for maps, gap for a constant tempo | [Ableton help: Importing a tempo map](https://help.ableton.com/hc/en-us/articles/360003387979-Importing-a-tempo-map) |
| 5 | Section markers (MIDI marker meta events) and track-name events: no opened source says whether Live turns them into locators or track/clip names. | gap | searched, nothing found (Ableton help, SOS, forum) |
| 6 | Live exports clips as SMF (File > Export MIDI Clip) but "cannot export a tempo map". | medium | same help article |
| 7 | `.als` is "a simple XML file compressed with gzip"; root `<Ableton>` carries `MajorVersion`, `MinorVersion`, `SchemaChangeCount`, `Creator`, `Revision`; project data under `LiveSet`; tracks are a flat list; `NextPointeeId` must exceed every Pointee Id and Ids must be unique. The author says Live opened files that follow this rule "without errors" but "not thoroughly tested". | medium (one community write-up) | [lucas-ywk/ableton-save](https://github.com/lucas-ywk/ableton-save) |
| 8 | Ableton: "Sets created or saved in later versions of Live cannot be opened in earlier versions", also between point releases (a 12.3 set does not open in 12.2). The user runs 12.4.5, so a template saved by a 12.4.6 Live would likely not open. | high | [Ableton help: Backward Compatibility](https://help.ableton.com/hc/en-us/articles/360000841004) |
| 9 | Existing .als writers clone a real saved set rather than build from scratch: `expressive-liveset` (MIT code, "gzipped, undocumented, version-specific XML", template saved by Live 12.4.6, writes MIDI tracks, session and arrangement clips, notes, scenes, tempo; no instrument unless opted in; locators not mentioned; no validity guarantee stated). `buildable` (PyPI, alpha, edits existing sets, licence not stated). `pyableton` (MIT, parses sets, read side). | medium (README level, not run) | [expressive-liveset](https://github.com/swwallowws/expressive-liveset), [buildable](https://pypi.org/project/buildable), [pyableton](https://pypi.org/project/pyableton) |
| 10 | Locators in the LOM: `Song.cue_points`; AbletonOSC can add/name them on the Session side (earlier note Q2) but every call is `unknown`. In an .als they are plain data, but their exact tags were not opened here. | gap | earlier note; `als_inspect.py` S2 settles it |
| 11 | No opened source gives Ableton's licence stance on generating or editing `.als` files (EULA not read here). No Ableton document describes the format. | gap | not found |

## 2. Path a: multi-track SMF (format 1)

**What the exporter writes.** One conductor track (title, tempo, 4/4, a text event `key: A phrygian`, one marker per section at its first tick) and one track per instrument (track name, notes, end-of-track at the common final tick). PPQ 480, channel 1, sections one after another in 4/4, a pattern repeated per section and cut at the section end. Energy 0-1 scales velocity by `0.70 + 0.30 * energy` (PROPOSAL). Same input, same bytes.

**What is expected in Live (confidence per section 1).** One MIDI track per instrument, one clip each, all starting where the file is dropped (findings 2, 3: medium). Names, markers, tempo: see tests T3-T6. The conductor track holds no notes, so by finding 4 a tempo prompt may not appear; if it does not, the user sets 145 BPM by hand.

**Risks.**
- Leading space: an element that first plays in bar 33 yields a clip that starts at the drop position with empty time before the first note (finding 2). That is fine for alignment but means long clips; the user may split them.
- Empty elements (never active) still get a track; whether Live creates an empty clip, a clip of full length or no track is unknown (T6).
- The Live track has no instrument: the user must put an instrument on each MIDI track (drum rack, Drift, own synth). The file cannot choose devices.
- Sound design (patches, FX) is out of the file's reach; presets by name need either a saved set template (section 3) or a verified AbletonOSC device-load path (not available).

## 3. Path b: Live Set (.als)

**What can be generated** (by cloning a user-saved set; finding 9): MIDI tracks, MIDI clips with notes at arrangement positions, names, tempo, scenes. Locators, device presets by name, and automation are not shown by any opened source.

**Format and risk.**
- Undocumented, version-specific (findings 7, 8, 9, 11). A hand-written skeleton from scratch is not recommended: ID rules (Pointee Ids), schema counters and device chains are easy to get subtly wrong, and a wrong set may fail to open or open with a repair dialog. Unverified in this project.
- Newer-version rule (finding 8) means the base set must come from the user's own Live 12.4.5. A template shipped in the repo would only work for the same or a newer Live and would be Ableton-produced content (licence unknown, finding 11): do not commit one.
- Third-party code (`expressive-liveset`) is MIT but not run and not audited; adopting it would be a new dependency and needs a PR reason.
- A bad write cannot damage Live itself, only the generated file; the user opens it as a new set (never overwrite their project). Generation therefore is low-risk for data loss if it always writes a new file, but every claim "opens in Live" stays unverified until S4.

**Validation without Live (structure checks only).** gunzip succeeds; XML parses; root is `Ableton` with the version attributes of the template; track count and names equal the plan; every note start/duration equals the plan (parse back); Pointee Ids unique and below `NextPointeeId`; locator count equals the sections. These prove consistency with our own plan and with the template's shape. They do NOT prove Live accepts the file.

**Delivered now:** `scripts/als_inspect.py` (read-only) so the user's own set can show real tag names. No writer is shipped: the research does not show a low-risk way (no documented schema, no template we may commit, unknown validity).

## 4. Path c: AbletonOSC

Out. In `contracts/capabilities.json`: `song.create_midi_track`, MIDI clip, note write/read, locators and Arrangement placement are `unknown` or have no entry (see the acid note section 2 and the MIDI/devices note). The capability rule forbids building a tool on them. Route (b) of the acid note stays the follow-up once A1-A8 are run.

## 5. Recommendation and user test list

**Recommend:** path a now (file in, user drags, everything checkable by eye and by Export MIDI Clip). Path b only after S1-S3 show the real structure and the user wants a one-click set; path c after the acid tests.

Run on the user's Windows machine, Live 12.4.5. The writes below are limited to the user's own manual drag into a scratch set (undo with Ctrl+Z, or close without saving). The agent sends nothing to Live.

Create the file: `python -m audio_engine.arrangement_midi goa_demo.mid` (from the repo with `pip install -e .`, or `PYTHONPATH=src`). Demo: 32 bars at 145 BPM, tracks `kick`, `hat`, `bass`, `lead`; sections Intro 1-8, Groove 9-16, Break 17-20, Peak 21-28, Outro 29-32; the patterns are placement test patterns, not Goa claims.

| ID | Step | Expected result (what would count as PASS) |
| --- | --- | --- |
| T1 | New empty set, tempo 120. Drag `goa_demo.mid` onto the Arrangement at bar 1. | Four new MIDI tracks named like `kick`, `hat`, `bass`, `lead` (or numbered; report which). One clip each. Report the result in your own words. |
| T2 | Look at the clip start and end of each track. | All clips start at bar 1; each clip ends at bar 33 (32 bars) or at its last note. Report which. |
| T3 | Check the tempo box after the drop. Was a Yes/No prompt shown about tempo? | PASS if either (a) prompt shown, Yes sets 145, or (b) tempo stays 120 and nothing was asked. Report which; no judgement of either. |
| T4 | Look at the Arrangement for locators or markers named Intro, Groove, Break, Peak, Outro. | Report: present at bars 1, 9, 17, 21, 29, or absent. Absent is a finding, not a failure. |
| T5 | Select the `bass` clip, open it: count notes in bar 1-8 (should be none) and bars 9-16 (should be 12 per bar: steps 2-4 of every beat). In the Peak section the notes of `bass` and `lead` should both exist. | Bass starts at bar 9, `lead` at bar 17, `kick` and `hat` at bar 1. Counts as given (kick 4 per bar in Intro). |
| T6 | Repeat T1 with a variant file where one element is never used (user asks the agent for it) or just inspect: is any track empty? | Report what Live made for an element that never plays (empty clip, no track, error). |
| T7 | On the `kick` clip: File > Export MIDI Clip; send the file for a byte comparison with the generated one (note count, start, duration, velocity). | Same notes as in the generated file within 1/480 beat (the agent compares with its own reader). |
| T8 | Undo (Ctrl+Z) the drop. | All four tracks and clips removed in one or more undo steps (report how many) or close the scratch set without saving. |

Optional ears step (user only, no claim made): put Drift on `bass`/`lead`, a Drum Rack or any kit on `kick`/`hat`, play the Peak section and say whether the energy steps (velocity only) are audible.

.als reading tests (only if the user wants path b later):

| ID | Step | Expected result |
| --- | --- | --- |
| S1 | Save a set that has 1 MIDI track with one clip (3 notes) and one locator "Test". Run `python scripts/als_inspect.py "<path>.als"`. | Prints root attributes (version), tempo, `track MidiTrack ...: clips: 1, notes: 3`. Any line saying `not found` is a finding (tag names differ). Paste the output. |
| S2 | Same file, locator line. | `locators: 1` and `locator 'Test' at beat <n>`; if "not found" the tag layout differs from what the script assumes. |
| S3 | Add an Arrangement clip and a Drum Rack to the track, save again, inspect again. | Report whether clips count rises and how the arrangement clip is named in the XML (the user may attach the gunzipped file, after removing private paths). |
| S4 | (later, only if a writer is ever built) Open the generated set as a new file. | Opens without a repair dialog; tracks and notes as planned. Not available now. |

## 6. Test strategy for the exporter (CI vs user)

CI (no Ableton, labelled as such): parse the written file with a reader defined in the test, compare with a per-tick reference render, byte identity, range and error paths. Not CI: T1-T8. Never report the CI run as a Live test.

## Blocked or unverified

- Whether Live creates locators from marker events and applies a constant tempo from a format-1 file: no source found (T3, T4).
- Behaviour of overlapping same-pitch notes in Live: the exporter refuses same-pitch overlaps inside a pattern and cuts at section ends, so none is written.
- The `.als` licence/EULA position and every .als claim in section 3 rest on community READMEs, none run here.
- The Sound On Sound article date and Live version were not shown by the fetch.

## State update proposal (for the PR body)

Add: delivery of a Goa arrangement is by multi-track SMF; `arrangement_midi.py` merged; not verified in Live until T1-T8 are reported; `.als` writer not built.
