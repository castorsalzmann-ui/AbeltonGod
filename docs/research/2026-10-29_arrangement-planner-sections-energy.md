# Research: arrangement planner — section types, default energy shapes, energy → elements rules

- **Date:** 2026-10-29. All web sources were retrieved on 2026-10-29.
- **Author role:** sound-designer.
- **Receiving issue:** #139 (user message 2026-10-29 15:59). Feeds questionnaire tab 3 tasks A4 (rules for the user's tracks), A5 (shared data format), A6 (song structure) and A10 (energy curve → elements).
- **Inputs read:** the user's questionnaire answers, tab 3 "Produktion in Live" section a and tasks A1–A18. `docs/research/2026-10-29_live-midi-arrangement-devices.md` (what Live can do).
- **User facts this note rests on** (tab 3, a):
  - The user works directly in the Arrangement View.
  - Tempo 136–146 BPM, track length 4–7 minutes.
  - Tracks must be DJ-mixable: clean intro and outro, phrases of 8, 16 or 32 bars.
  - Energy is steered both by drawing and by chat.
  - The copilot may build drums, bass, leads, structure, build-ups/breaks and automation.
- **Scope:** a proposal only. No code. Nothing here says how anything sounds. No artist or track names as targets. A rule with no source is marked _Interpretation_. All values are defaults for the user to confirm or change; none is a decision.

Confidence: **high** = stated by several independent sources or measured on real data. **medium** = one producer/DJ education source, or forum consensus. **low / Interpretation** = my proposal, no direct source.

---

## 1. Genre conventions found (sources)

| # | Convention | Source (retrieved 2026-10-29) | Confidence |
| --- | --- | --- | --- |
| C1 | Club tracks are built from phrases of 8, 16 or 32 bars. Changes happen at phrase boundaries. Club records are typically arranged in 32-bar blocks with 8/16-bar sub-phrases inside, "which is why intros and outros so often run to exactly those lengths." | [mixgraph glossary: phrase](https://www.mixgraph.io/glossary/phrase); [DJ TechTools, Phrase Mixing (E. Golden, 2015-10-22)](https://djtechtools.com/2015/10/22/phrase-mixing-throwback-thursday-dj-technique/): phrases "usually also indicate the start of a new melodic or instrumental element" | high |
| C2 | Measured on 1,557 real DJ mixes (20,765 transitions, mostly house and trance): cue points and transition lengths cluster at multiples of **32 beats (8 bars)**. DJs take the phrase structure into account when they cue. | Kim et al., *A Computational Analysis of Real-World DJ Mixes using Mix-To-Track Subsequence Alignment*, ISMIR 2020, sections 4.2, 5.1, 6.3, figs. 3 and 6 ([arXiv 2008.10267](https://arxiv.org/abs/2008.10267v1)) | high (measured; genres mostly house/trance, not techno-specific) |
| C3 | DJs need **16 or 32 bars** of simple elements at the start of a track. Suggested intro elements: kick, hats/percussion, minimal bass, light textures or FX. "Avoid starting the track immediately with the full melody or vocals." Drum-only sections and filtered breakdowns serve as transition spaces. | [Lost Stories Academy, What makes a track DJ-friendly](https://loststoriesacademy.com/blogs-and-tutorials/what-makes-a-track-dj-friendly) (undated) | medium |
| C4 | Example layout from C3: intro 16, build 16, drop 32, breakdown 16, second drop 32 bars. | same | medium |
| C5 | Intro "reduced, built from few elements", so it can be blended into the previous track's outro. The outro removes elements step by step, down to **kick and bass**. In breaks, kick and bass "get a time-out". In build-ups, high- and low-pass filters on kick and bass keep the beat while adding tension. Build-up 8, 16 or 32 bars. Main breakdown about two-thirds into the track, up to 64 bars. Short breaks mostly ≤ 16 bars. About four beats of pause before a drop. | [Bonedo, Crashkurs Psytrance #4 (P. Blunk, 2024-06-18)](https://www.bonedo.de/artikel/crashkurs-psytrance-produzieren-4-vocals-arrangement-mixing). The source is about psytrance (7–9 min tracks), not techno/trance at 136–146 BPM. | medium (adjacent genre) |
| C6 | A build-up is usually 8 or 16 bars and ends on a phrase boundary. Content: a riser, a snare roll, filters opening. The breakdown is where "the drums fall away". The drop is where "the full arrangement lands after a breakdown". The page says its bar figures come from phrase-grid arithmetic, not from measuring tracks. | [mixgraph glossary: build-up](https://www.mixgraph.io/glossary/build-up) | medium |
| C7 | Trance: a few long builds and at least one instrumental breakdown "where the percussion is stripped away", at least two builds per track. Trance "doesn't often have a traditional drop". Elements are introduced "slowly, often one at a time". Risers ramp up; downlifters are their opposite. Tempo about 130–150 BPM. | [Native Instruments blog, What is trance music (A. Kody, undated)](https://blog.native-instruments.com/trance-music/) | medium |
| C8 | 8- and 16-bar phrases are "useful starting points, not mandatory lengths". Contrast by subtraction: mute the bass or a percussion layer before adding a riser. Do not repeat the same fill at every boundary. | [Mixed In Key, How to arrange a dance music track (updated 2026-10-07)](https://mixedinkey.com/captain-plugins/wiki/how-to-arrange-a-dance-music-track/) | medium |
| C9 | Forum views on techno phrasing differ. Some say "almost everything in dance music is 8-bar phrases"; others say a normal phrase is 32 bars, with bigger changes at 64. Minimal/tool techno changes more subtly. | [DJ TechTools forum, Phrasing techno/tool techno/minimal techno (2015-01)](https://forum.djtechtools.com/t/phrasing-techno-tool-techno-minimal-techno/69807) | low (forum) |

No source gave a measured, techno-specific distribution of section lengths or section positions. Everything in sections 3–6 that goes beyond C1–C9 is **interpretation**.

## 2. Bar grid for the user's range

Computed with a 15-line Python script in the session scratchpad (`bars.py`, not committed). Formula: 1 bar = 4 beats = 240/BPM s (4/4); bars in t seconds = t·BPM/240; the multiple-of-8 range is ceil(4 min)…floor(7 min) rounded to 8.

| BPM | 1 bar | 8 bars | 16 bars | 32 bars | 4 min | 7 min | Multiples of 8 bars within 4–7 min |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 136 | 1.765 s | 14.1 s | 28.2 s | 56.5 s | 136.0 bars | 238.0 bars | 136–232 |
| 140 | 1.714 s | 13.7 s | 27.4 s | 54.9 s | 140.0 bars | 245.0 bars | 144–240 |
| 146 | 1.644 s | 13.2 s | 26.3 s | 52.6 s | 146.0 bars | 255.5 bars | 152–248 |

**152–232 bars** (multiples of 8) fit 4–7 min at every tempo from 136 to 146 BPM. In multiples of 16, the range is **160–224 bars**.

| Total bars | 136 BPM | 140 BPM | 146 BPM |
| --- | --- | --- | --- |
| 160 | 4:42 | 4:34 | 4:23 |
| 192 | 5:39 | 5:29 | 5:16 |
| 208 | 6:07 | 5:57 | 5:42 |
| 224 | 6:35 | 6:24 | 6:08 |
| 240 | 7:04 (too long) | 6:51 | 6:35 |

## 3. Section types (proposal)

Bars are 1-based in the tables (bar 1 = first bar of the track). Lengths are in bars. All section starts fall on a multiple of 8 bars + 1.

| Type id | Label (DE UI) | Role | Default length | Allowed lengths | Typical position | Entry at boundary | Basis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `intro` | Intro | DJ mix-in: drums first, few elements, one change per 8 bars | 32 | 16, 32, 64 | always first | — (track start) | C1, C3, C5 |
| `groove` | Groove | Main body between intro and drops; steady, elements rotate | 32 | 16, 32, 48, 64 | after intro; between drops | `step` | Interpretation (C3 "main section", C9) |
| `break` | Kurzer Break | Short kick + bass drop-out, drums otherwise continue | 8 | 8, 16 | inside or between groove/drop blocks | `step` | C5 ("short breaks ≤ 16 bars"), C3 |
| `breakdown` | Breakdown | Main break: kick and bass out, atmos and motif in front | 32 | 16, 32, 64 | about 40–70 % into the track; at most 2 per track (see note) | `step` | C5, C6, C7 |
| `build` | Build-up | Tension towards the next drop: riser, roll, filters open | 16 | 8, 16, 32 | directly before a `drop` | `continue` | C5, C6 |
| `drop` | Drop / Peak | Full arrangement, highest energy | 32 | 16, 32, 64 | after a `build`, or after a `groove` | `step` | C4, C6 |
| `outro` | Outro | DJ mix-out: elements leave one by one, down to kick and bass (setting `intro_outro_bass`, section 8) | 32 | 16, 32, 64 | always last | `continue` | C3, C5 |

Notes:
- **Breakdown position.** C5 places the main breakdown about two-thirds into a 7–9 min psytrance track. Shorter tracks put it earlier, because intro, build and drop still need their phrases after it (_Interpretation_). So the range is 40–70 %. In 224-bar tracks (T2, T3) it starts near 50 %. In the 160-bar template T1 it sits at bars 65–80 (40–50 %).
- Repeated types are numbered in the UI ("Drop 2", "Breakdown 2"). The type stays the same; only the defaults differ (see rule S5).
- A **fill** (1 bar) and a **pre-drop gap** (setting `pre_drop_gap`) are *events* at the end of a section, not sections (section 6).
- _Interpretation:_ a separate "Peak" type next to "Drop" adds no rule the energy value does not already carry. One `drop` type with a higher energy is proposed instead.

### 3.1 Default templates (start points the user can pick, then edit)

| Template | Sections (length in bars) | Total | 136 / 146 BPM |
| --- | --- | --- | --- |
| **T1 Kurz** | intro 32 · groove 32 · breakdown 16 · build 16 · drop 32 · outro 32 | 160 | 4:42 / 4:23 |
| **T2 Techno** | intro 32 · groove 32 · break 8 · build 8 · drop 32 · breakdown 32 · build 16 · drop 32 · outro 32 | 224 | 6:35 / 6:08 |
| **T3 Trance** | intro 32 · groove 32 · build 16 · drop 32 · breakdown 32 · build 16 · drop 32 · outro 32 | 224 | 6:35 / 6:08 |

T2 (224 bars) with bar positions, as an example of the grid:

| Section | Bars | Share of track |
| --- | --- | --- |
| intro | 1–32 | 0–14 % |
| groove | 33–64 | 14–29 % |
| break | 65–72 | 29–32 % |
| build | 73–80 | 32–36 % |
| drop | 81–112 | 36–50 % |
| breakdown | 113–144 | 50–64 % |
| build | 145–160 | 64–71 % |
| drop 2 | 161–192 | 71–86 % |
| outro | 193–224 | 86–100 % |

### 3.2 Structure rules (checkable)

- **S1** Every section start is at bar 8k + 1. Every length is a multiple of 8 bars. (C1, C2)
- **S2** Total length is a multiple of 8 bars and lies inside the 4–7 min window for the set BPM (section 2 table). Default: a multiple of 16 bars between 160 and 224.
- **S3** The first section is `intro`, the last is `outro`. Neither appears anywhere else.
- **S4** A `build` is always followed by a `drop`. The editor warns otherwise.
- **S5** Each `drop`'s default energy follows the setting `second_drop` (section 8). The default is "stronger", i.e. at least the previous drop's energy.
- **S6** The number of `breakdown`s follows the setting `breakdown_count`: default 1, at most 2 (C5 names one main breakdown, C7 "at least one"; the maximum of 2 is _Interpretation_).
- **S7** Section lengths and starts snap to the setting `change_grid` (default 8 bars). S1 is the default case.

## 4. Default energy shapes per section

Energy is a value 0–1 on nodes placed on the bar grid.
- A node position is given here as **t**, the fraction of the section: 0 = start of the section's first bar, 1 = end of its last bar.
- The editor converts t to an absolute position (convention in section 6) and snaps it to whole bars. When a section is resized, its nodes keep their t.
- Values between nodes are **linear** (section 6). A step therefore needs two nodes at the same position. "Step" shapes below are written as `t: a | b`, meaning the value arrives as a and leaves as b.

| Type | Default nodes (t: value) | Shape | Value range the user can drag to (soft limit, warning only) |
| --- | --- | --- | --- |
| `intro` | one step per 8-bar phrase, values evenly spaced from 0.30 to 0.45. For 32 bars: 0: 0.30 · 0.25: 0.30 \| 0.35 · 0.50: 0.35 \| 0.40 · 0.75: 0.40 \| 0.45 · 1: 0.45 | steps up every 8 bars | 0.15–0.55 |
| `groove` | 0: 0.60 · 1: 0.70 | slow rise | 0.45–0.85 |
| `break` | 0: 0.45 · 1: 0.45 | flat dip | 0.25–0.60 |
| `breakdown` | 0: 0.30 · 0.5: 0.20 · 1: 0.35 | dip, then rising out | 0.05–0.50 |
| `build` | 0: = previous section's end · 1: = next section's start − 0.05 | linear ramp | end ≥ start |
| `drop` | 0: 0.90 · 1: 0.95. Drop 2 with `second_drop = stronger`: 0: 0.95 · 1: 1.00; with `equal`: same as drop 1 | high plateau | 0.70–1.00 |
| `outro` | one step per 8-bar phrase, from v0 = min(previous end, 0.55) down to 0.25. For 32 bars: 0: v0 · 0.25: v0 \| 0.45 · 0.50: 0.45 \| 0.35 · 0.75: 0.35 \| 0.25 · 1: 0.25 (a step is skipped if it would rise) | steps down every 8 bars | 0.10–0.55 |

### 4.1 Boundary and neighbour rules

- **B1 Entry mode `step`** (groove, break, breakdown, drop): the value may jump at the boundary. This is like a vertical step in a Live automation lane. **Contract hint (A5):** the format must allow two nodes at the same bar, or a step flag. Otherwise every jump becomes a 1-bar ramp.
- **B2 Entry mode `continue`** (build, outro): the first node takes the previous section's last value. No jump.
- **B3 A build is anchored at both ends.** Its end node = max(its start value, next section's start − 0.05). If the user moves the next drop's first node, the build's end node follows. Nothing else moves.
- **B4 Picking a section** writes its default nodes only inside its own range. It recalculates at most the two neighbouring `continue` anchors (B2, B3). Nodes the user has drawn in other sections are never touched.
- **B5 Re-picking a section over hand-drawn nodes** replaces them only after the user confirms. Undo inside the planner restores them. _Interpretation_ (UI); matches the user's answer "a whole section at once, after one OK" (tab 3, a6).
- **B6** Values are clamped to 0–1. Leaving a soft range shows a warning but is allowed, because the user decides.
- **B7 Chat edits** ("the second drop should be harder", task A11) change nodes in the named section only, then re-apply B3 at its edges.

## 5. Energy → elements (proposal)

Key point: **energy alone cannot decide the elements.** A breakdown at 0.30 has no kick but has atmos and a motif. An intro at 0.40 has a kick but no motif. One energy → element mapping for the whole track would break task A10's test ("higher curve never gives fewer active elements"). That test is stated *per section* in A10, so the proposal is: **elements = f(section family, energy)**, monotonic inside each family.

Families: **drum-led** (`intro`, `groove`, `drop`, `outro`), **break** (`break`, `breakdown`), **build** (`build`).

### 5.1 Drum-led sections: an element is on when energy ≥ its threshold

| Element | On at E ≥ | Parameter change with energy (_Interpretation_) | Intro/outro mix zone (first 16 bars of intro, last 16 bars of outro) |
| --- | --- | --- | --- |
| Kick | 0.00 (always) | none; the kick sample stays fixed | always on, from bar 1 to the last bar (C3, C5) |
| Atmos (non-tonal noise, texture) | 0.20 | — | allowed (C3 "light textures or FX") |
| Closed hats | 0.30 | 8ths below 0.60, 16ths from 0.60; velocity 70 % → 100 % over 0.30–1.00 | allowed |
| Percussion layer 1 | 0.40 | — | allowed |
| Bass / rumble | 0.45 in `groove`/`drop`; in `intro`/`outro` set by `intro_outro_bass` (below) | low-pass on bass from about 300 Hz at 0.45 to about 2 kHz at 0.90 (log scale) | set by `intro_outro_bass` |
| Clap / snare | 0.55 | — | allowed |
| Synth / lead (main motif, incl. acid line) | 0.65 | low-pass from about 400 Hz at 0.65 to fully open at 1.00 (log scale) | **off** (C3: no full melody at the start) |
| Atmos / pad (tonal) | 0.70 | — | **off** |
| Open hat / ride | 0.75 | — | allowed |
| Percussion layer 2 | 0.80 | — | allowed |
| Second synth layer | 0.90 | — | off |

Energy inside the mix zone is capped at 0.50 (_Interpretation_: keeps the zone sparse). C7 says elements come in "often one at a time", so **at most one element changes per 8-bar boundary** inside `intro` and `outro`. In `groove` and `drop` the limit is two.

**Bass in intro and outro.** The outro's default energy (0.45 → 0.25) lies below the 0.45 bass threshold, so a pure threshold rule would remove the bass for the whole outro. Yet C5 says the outro goes "down to kick and bass". Bass in `intro`/`outro` is therefore **not** decided by the threshold but by the setting `intro_outro_bass` (section 8):
- `on` (default): in the outro, bass stays on to the last bar, with its low-pass at the closed end (about 300 Hz). In the intro, it enters at the start of the last 8-bar phrase.
- `outside_mix_zone`: as `on`, but bass is off in the first 16 bars of the intro and the last 16 bars of the outro.
- `off`: no bass in intro and outro.

Inside a section with a fixed setting the monotonicity rule T6 still holds.

**How a phrase's elements are chosen.** An element's on/off state is decided once per 8-bar phrase (T1), from the **mean energy over that phrase**. Filters and velocities follow the continuous value. _Interpretation_. With the step shapes in section 4 the mean equals the step value. With a ramp, an element can only switch at the phrase where the mean crosses its threshold.

### 5.2 Break sections

| Element | `break` (short) | `breakdown` (main) |
| --- | --- | --- |
| Kick | **off** for the whole section (C5) | **off** for the whole section (C5, C6, C7) |
| Bass / rumble | off (C5) | off (C5); low rumble only if `breakdown_rumble = on` (section 8) |
| Hats, percussion, clap | as in 5.1 at the section's energy | hats/percussion from E ≥ 0.40 only, no clap |
| Atmos / pad | as in 5.1 | on from E ≥ 0.00 |
| Synth / lead (motif) | as in 5.1 | on from E ≥ 0.20; low-pass from about 600 Hz at 0.20 to open at 0.50 |
| FX | downlifter/sweep on bar 1 | downlifter/sweep on bar 1 |

### 5.3 Build sections

| Element | Rule |
| --- | --- |
| Riser | on for the whole build; its level and brightness follow the energy ramp; ends exactly at the drop's bar 1 (C6) |
| Snare/clap roll | last 8 bars only: quarters → eighths → sixteenths, one step every 2 bars; thirty-seconds in the last bar (_Interpretation_; C6 names the roll, not the steps) |
| Kick | setting `build_kick` (section 8). Default `filtered_in_build`: in for the whole build, with a high-pass that opens as energy rises (C5). `at_drop`: out until the drop's bar 1. After a `groove` or `break`, the kick is in either way. |
| Bass | follows the kick: in with the same high-pass when the kick is in (C5), otherwise off until the drop |
| Synth / lead | on from E ≥ 0.50; low-pass opens with energy |
| Pre-drop gap | drums and bass silent before the drop's bar 1, for the length in setting `pre_drop_gap` (default 1 bar = 4 beats, C5) |

### 5.4 Transition rules

- **T1 Phrase alignment.** Elements switch on or off only on the `change_grid` (default: bar 8k + 1; C1, C2). Parameter ramps (filter, riser) may move inside a phrase. Planned events (fill, gap) sit in the last bar or beat before a boundary.
- **T2 Riser before every drop.** It ends at the drop's bar 1. An impact/crash lands on bar 1 of every drop and of every groove that follows a breakdown. (C6, C7)
- **T3 Kick drop-out.** Kick off for every `break`/`breakdown` and back on bar 1 of the next drum-led section. Inside drum-led sections the kick never drops out except for a planned fill (T4).
- **T4 Fills.** One fill bar before a section change between drum-led sections. Fills must not repeat identically at consecutive boundaries (C8).
- **T5 Step limits.** A jump of more than +0.30 at a boundary is allowed only into a `drop`. A jump down is allowed only into `break`, `breakdown` or `outro`. Otherwise the editor warns (_Interpretation_).
- **T6 Monotonicity test (for A10).** Within each family (5.1, 5.2, 5.3), raising a section's energy never removes an element and never closes a filter. Across families the test does not apply, by design.

### 5.5 What Live can and cannot take (from `2026-10-29_live-midi-arrangement-devices.md`)

- **Section names → locators.** `cue_point/add_or_delete` and `set/name` exist in AbletonOSC (Q2 of that note). Experiment E3 there is still open. Note the toggle pitfall: adding twice deletes.
- **Clips at bar positions.** Arrangement MIDI and audio clips need an AbletonOSC extension (E5).
- **Filter ramps.** No API route to Arrangement track automation is known (E7). The planner's output should therefore state parameter targets per bar abstractly, e.g. "lead low-pass 400 Hz → open, bars 145–160". It must not assume automation lanes. Two possible routes: clip envelopes (E6/E7, unknown), or rendering the ramp into the audio clip with the project's own engine (questionnaire tab 3, decision 3).

## 6. Input for the plan-format contract (task A5, proposal only)

The contract owner decides the format. Items the planner needs:
- `bpm` (136–146 default range), `total_bars` (multiple of 8), `time_signature` fixed to 4/4.
- `sections[]`: `type` (one of the 7 ids), `start_bar` (1-based, 8k + 1), `length_bars` (multiple of 8), `index` per type (for "Drop 2").
- `energy_nodes[]`: `pos`, `value` 0–1.
  - **Position convention (proposal):** `pos` is in bars from the track start, as a number. `pos = 0` is the start of bar 1; `pos = total_bars` is the end of the last bar.
  - A section with 1-based `start_bar` s and `length_bars` L covers `pos` s − 1 … s − 1 + L, so its t maps to `pos = s − 1 + t·L`. Example: the last outro node of a 224-bar track is at `pos = 224`. A step node at a boundary shares the next section's start position, e.g. `pos = 80` for a drop starting at bar 81.
  - Whole bars by default. Sub-bar positions (multiples of 1/4 bar = 1 beat) only if the change grid or the pre-drop gap needs them.
- **Interpolation:** linear between consecutive nodes, as in a Live automation lane (proposal). A hold/step is written as two nodes at the same `pos`.
- **Equal positions:** at most two nodes per `pos`. Their array order is binding: the first is the value arriving from the left, the second the value leaving to the right. A sort must be stable and must never reorder them.
- `settings{}`: the block of section 8 with its defaults (D-024: every style choice is a user setting).
- `events[]` (derived, not drawn): `riser`, `impact`, `downlifter`, `fill`, `pre_drop_gap`, each with position and length.
- Derived element states per phrase, so a test can check T1 and T6 without re-running the rules.

## 7. How the user can check the defaults later (once A6/A10 render something)

Nothing can be rendered yet. When a planner prototype exists, a check under 15 minutes. Rendering is done by the lead or the audio-engineer; every answer is to be checked by ear.
1. Render T2 at 140 BPM, three takes per section. Question: is each section recognisable without looking at the labels?
2. A/B: `build_kick = filtered_in_build` vs `at_drop`, same drop after it. One question: which leads better into the drop? Checks the `build_kick` default.
3. A/B: `second_drop = stronger` vs `equal`. One question: should drop 2 be stronger? Checks the `second_drop` default.
4. Mix test: play the outro of take A into the intro of take B, aligned at bar 1. One question: does the 32-bar overlap work in a mix, or is 16 enough? Checks the `intro_length` / `outro_length` defaults.

## 8. Settings and defaults (user decision 2026-10-29 16:12, D-024)

The user answered the five taste questions with: "everything configurable in the settings, industry standard as default" (#139). Each former question is therefore a setting. "Basis" says whether the default rests on a source (C-number) or is _Interpretation_ / convention without a measurement.

| Setting | Former question | Default | Allowed values | Basis of the default |
| --- | --- | --- | --- | --- |
| `build_kick` | Q1 | `filtered_in_build`: after a breakdown the kick returns at the build's start, high-pass opening with energy | `filtered_in_build`, `at_drop` | C5 (filters on kick and bass in the build-up). Psytrance source; C7 ("percussion … ramp back up") is consistent but gives no detail |
| `intro_length` | Q2 | 32 bars | 16, 32, 64 | C1 (32-bar blocks, intros/outros "so often" that long), C3 (16 or 32) |
| `outro_length` | Q2 | 32 bars | 16, 32, 64 | as `intro_length` |
| `intro_outro_bass` | Q2 | `on` (bass minimal in the intro, kept to the last bar of the outro; rule in 5.1) | `on`, `outside_mix_zone`, `off` | C3 ("minimal bass" in the intro), C5 (outro "down to kick and bass"). The `outside_mix_zone` option is _Interpretation_ (key clashes in a mix, no source) |
| `breakdown_count` | Q3 | 1 | 1, 2 | C5 (one main breakdown), C7 ("at least one"). Max 2 is _Interpretation_ |
| `breakdown_length` | Q3 | 32 bars | 16, 32, 64 | C4 example 16, C5 "up to 64", C7 "long". 32 is _Interpretation_ inside that range |
| `breakdown_rumble` | Q3 | `off` | `off`, `on` | C5 (kick and bass get a time-out in breaks) |
| `second_drop` | Q4 | `stronger` (+0.05 energy, capped at 1.0) | `stronger`, `equal`, `ask` | _Interpretation_. No source found; follows the user's issue text ("higher nodes → more peak") |
| `change_grid` | Q5 | 8 bars | 4, 8, 16 | C2 (measured: 32-beat clustering), C1 |
| `pre_drop_gap` | Q5 | 1 bar (4 beats) | `off`, 1 beat, 2 beats, 1 bar | C5 (about four beats before a drop). Psytrance source |
| `fills` | — (from T4) | `on`, varied | `on`, `off` | C8 (do not repeat the same fill) |

Rules for the contract (D-024):
- A setting changes defaults and rule parameters only. It never overrides nodes the user has drawn (B4, B5).
- Length settings apply when the user places a section. A template keeps its own lengths: T1 uses a 16-bar breakdown to fit 160 bars.

## To verify by experiment

Each item becomes an issue for the owning role.

| # | What | How | Owner | Where |
| --- | --- | --- | --- | --- |
| V1 | Sections are recognisable | Listening check 1 (section 7) | user (by ear); render by lead/audio-engineer | user's PC |
| V2 | `build_kick` default | Listening check 2 | user (by ear) | user's PC |
| V3 | `second_drop` default | Listening check 3 | user (by ear) | user's PC |
| V4 | `intro_length` / `outro_length` default in a mix | Listening check 4 | user (by ear) | user's PC |
| V5 | Monotonicity per family (A10 / T6) | Seeded property test over the whole energy range 0–1 and every section type and setting value: raising energy never removes an element and never closes a filter inside a family. Fault injection, e.g. one threshold swapped, must turn it red. | audio-engineer (planner generator, A10) | CI |
| V6 | Phrase alignment (T1, S1, S7) and node conventions (section 6: positions, two equal-position nodes kept in order, linear interpolation) | Property test on generated plans for every `change_grid` value | audio-engineer / contract owner (A5) | CI |
| V7 | Locators as section names | Experiment **E3** of `2026-10-29_live-midi-arrangement-devices.md` (add, name, toggle pitfall, ordering) | bridge-engineer | Live, user's PC (#140) |
| V8 | Clips at bar positions in the Arrangement | Experiment **E5** of the same note (needs an AbletonOSC extension) | bridge-engineer | Live, user's PC |
| V9 | Filter ramps as clip envelopes | Experiment **E6** | bridge-engineer | Live, user's PC |
| V10 | Clip envelope → Arrangement track automation | Experiment **E7**. If it fails, filter ramps must be rendered into audio (section 5.5) | bridge-engineer | Live, user's PC |

## Limits

- No source measured techno-specific section lengths or positions. C2 measured where DJs cue (mostly house/trance), not how tracks are built. C5 is about psytrance.
- Thresholds, filter values and energy defaults are **interpretation**. They are starting points for the user's ear, not conventions.
- Nothing here was tested in Live. Live-side statements come from the linked note and keep its experiment status.
