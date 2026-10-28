# Research: Kick Gen 2.0 learnings and market analysis

_Date: 2026-10-28 · Status: **required reading, once, before any kick-engine work** (Phase 01 onward). Input, not a decision, not a spec, not a listening result. Scope still comes from the issue and the phase spec._

## Short version

1. **Genre-fluid.** No genre-keyed presets, fingerprints, ranges or code paths. Name presets by sound character. (User instruction, 2026-10-28.)
2. **Never gate the best result.** The best-balanced version of a preset is always directly reachable. `variants` add range, never rarity.
3. **The measured taste is a range, not a point:** tail fundamental about 45–60 Hz, 80–90 % of the energy below 100 Hz, clean sine tails, click amount the freest axis. These are hypotheses until the user has listened.
4. **Market features are candidates, not scope.** Each one needs a `parking-lot` issue and, if it adds a parameter, a `contract-change` PR first (section 3.2).
5. **Aliasing has no requirement and no test yet.** Anything that adds `drive` should get one (section 3.2, M9).
6. **Nine measurement pitfalls** already cost wrong numbers once. Use them when writing or reading analysis code (section 4).
7. **Reference audio is measurement input only.** Never commit it, never copy prototype or commercial parameter tables, count each kick once.
8. **Say what is documented and what is derived.** Write "not established" instead of guessing.

## How to use this note

These are **lessons and findings**, not a parameter table. Three sources, none of which should be copied:

1. **"Bandit Wheel"**, an earlier browser prototype by the user (Web Audio, 18 genre profiles, slot-machine UI). Its value tables are deliberately **not** reproduced here. The goal is a better kick engine, not a port.
2. **77 reference kick files** (two uploads: 41 + 36) that the user picked from various Splice packs. Each file counts **once**; see section 2 for how loops and duplicates were handled. They show the user's **taste in kicks** (what they choose), not how the user builds kicks. The audio is licensed and stays out of the repo. Only aggregate measurements appear below.
3. **The user's kick-synth market analysis** (a Claude document, "Kick-Synth Marktanalyse & Referenz-Spezifikation", 2026-10-28, German, built from vendor pages, reviews and retailer texts), condensed in section 3. The source also names a genre focus; the user said to ignore it, and nothing here depends on it.

Use this note to choose defaults, variant axes and analysis methods. Derive your own values and verify them with tests and the user's ears (Phase 01 acceptance criteria). Keep the source's habit of labelling a claim *documented* (comes from a source) or *derived* (an inference).

**Standing guidance from the user (2026-10-28): keep everything genre-fluid for now.** The reference set stays one group. This is the user's instruction in chat, not yet a recorded decision; a decision entry is proposed in the PR body.

## 1. Lessons from the prototype

| # | Lesson | Consequence for AbeltonGod |
| --- | --- | --- |
| P1 | The prototype hid its cleanest kick (centre of every range, zero random jitter) behind a 1 % / 0.2 % random "Gold/Platinum" draw. That is gamification, not quality. The user explicitly does not want the best results to be gated. | The best-balanced version of a preset is always directly reachable. Variants (`variants: N`) add range, never rarity. |
| P2 | 18 genre profiles with separate narrow ranges, each only reachable through 4 discrete steps, felt "too specific" to the user. | Presets are **starting points in one shared continuous parameter space**, not separate code paths. Blending and leaving a preset's range must stay possible. |
| P3 | Some controls only had names and no audible effect (e.g. drive labels). | Every parameter that gets exposed must change the sound measurably. The test is an analysis value that moves when the parameter changes. |
| P4 | Seeded PRNG (mulberry32) made every render reproducible. | Already required by D-005. Confirmed to be useful in practice for A/B comparison. |
| P5 | Character mostly came from a small set of building blocks: sine body + exponential pitch drop, amp envelope with a short **hold**, a **waveshaper with selectable curve family** (hard clip / tanh / asymmetric tanh / wavefold), band-filtered noise click, optional **separate sub sine**, optional **rumble tail** (noise convolved, low-passed, saturated), optional **two-layer body + top**. | `kick-params` v0.1 covers pitch env, amp env, click, `drive`, `tone`. **Not covered:** hold, curve family, separate sub, rumble, layering. These are candidates for later, not scope for #2/#3. Each needs a `parking-lot` issue and a `contract-change` PR before anyone builds it. |
| P6 | Cause → effect is more useful than genre labels. Faster tempo → shorter decay and brighter transient. Kick carries the bassline → longer, more tonal, more driven. Curve family = harmonic colour (hard clip harsh, tanh round, wavefold metallic), not loudness. Sub amount depends on what else fills the low end. Rumble is its own axis, independent of tempo. | Write preset descriptions and future Claude prompts in these terms ("short because 150 BPM"), not as genre facts. |

## 2. Taste fingerprint from 77 reference kick files

**One vote per kick.** 77 files in two uploads. 13 contained several hits (8 loops of one pack with 8–10 hits, three more loops with 8, 8 and 16 hits, two files with 2 hits). Each of those was cut to its **first hit only**, so a kick that is played 8 times in a loop counts once. Duplicates were checked with an onset-aligned waveform correlation over the first 250 ms (positive control: hit 1 vs hit 2–4 inside the same loop gives 0.999–1.0 in 7 of the 10 loops tested; in the other 3 some hits are different sounds within one pattern and correlate only 0.37–0.94 with hit 1). The highest correlation between two *different* files is 0.886, so no pair counts as the same kick (threshold 0.98) and all 77 stay in. For decay measures, 4 first-hits that ran into the next hit (decay possibly cut off) are excluded; all other measures keep them.

Method: mono sum, peak-normalised, all timing measured **from the onset** (first sample above 10 % of peak). Envelope = 5 ms RMS. Tail pitch = instantaneous frequency (Hilbert phase) of a 700 Hz low-passed signal, median over 60 ms after onset until −30 dB, cross-checked by zero-crossing count.

Accuracy check on synthetic kicks with known values: tail pitch within 4 %, pitch settle time and −40 dB decay within about 10 %. Three of the four note-tagged kicks match their note within 5 % (G# → 51.2 Hz vs 51.9 Hz, A → 54.7 Hz vs 55.0 Hz, an F# in upload 2 → 48.2 Hz vs 46.2 Hz). The fourth, an F# in upload 1, measures 59 Hz (F#1 = 46.2 Hz); cause not established.

| Measure | p25 | median | p75 | Median set 1 / set 2 | Note |
| --- | --- | --- | --- | --- | --- |
| Tail fundamental (Hz) | 47 | 53 | 57 | 56 / **49** | See "The two uploads differ" below. 60 % of all kicks lie between 45 and 60 Hz. The schema default `pitch_end_hz: 48` is inside the interquartile range. |
| Pitch settle, 90 % of drop done (ms) | 15 | 24 | 46 | 34 / **17** | n = 63. For an exponential drop this is ≈ 2.3 × the time constant, so τ ≈ 6–20 ms. Map it onto `pitch_decay_ms` only after #7 defines its meaning. |
| Decay to −40 dB (ms) | 223 | 327 | 424 | 327 / 359 | n = 69. Compare with `amp_decay_ms` only once #7 defines its meaning. |
| Energy share below 100 Hz | 0.75 | 0.81 | 0.89 | 0.81 / 0.86 | Strongly sub-weighted in both uploads; p10 is 0.64. |
| Onset (first 10 ms) energy share above 1 kHz | 0.02 | 0.15 | 0.31 | 0.19 / 0.04 | **Widest relative spread (p10 0.01, p90 0.50).** The set 1 / set 2 gap comes from the 8 loop-first-hits and is not distinguishable without them (see below). |
| Tail harmonics 2–8 vs fundamental | 0.00 | 0.01 | 0.03 | 0.01 / 0.02 | Tails are almost pure sine. 10 of 77 exceed 0.05. |
| Start pitch | — | — | — | — | **Not established.** Values in the first 1–4 ms are mixed with click energy and run into the 700 Hz filter limit. Do not use. |

**The two uploads differ.** Set 1 (41 files) and set 2 (36 files) do not give the same fingerprint:

- **Different beyond chance, also without the 8 loop files:** tail pitch (55.9 vs 49.9 Hz, Mann–Whitney p = 0.001), pitch settle (34 vs 19 ms, p = 0.02), sub share (0.81 vs 0.89, p = 0.0004), crest factor (p = 0.01) and decay (p = 0.002).
- **Not different without the loop files:** onset brightness (p = 0.22). The low click in set 2 comes from the 8 loop first-hits, which also have a high crest factor (median 4.0).
- **Cause not established.** Candidates: different genre mix, different packs, or a change in what the user was looking for between the two uploads. The data cannot tell them apart, and under the genre-fluid guidance this is not pursued for now.

So the "taste" is **a range, not a point**. Tail pitch 45–60 Hz, sub-dominant, clean tails, click amount free.

What follows for #3 (presets/variants). These are hypotheses until the user has listened:

- Do not hard-code one tail pitch. Presets should span **roughly 45–60 Hz** and keep the root note a tunable parameter; a single default near 52 Hz is the least wrong single value.
- **~80–90 % sub energy** and a **clean sine tail** hold in both uploads and are the safest shared base.
- **Click level/tone is the most natural variant axis**: it has the widest relative spread within the selection.
- Body drive should be a deliberate choice, not a default, because the user's picks mostly have clean tails.

## 3. Market analysis: what commercial kick synths do

Condensed from the user's market document. It keeps only what changes engineering choices here. **Product facts (prices, release dates, feature lists) were not re-verified by this session.** In the source, "not documented" means "not mentioned in the sources read", not "missing". Numbers marked "proposal" (for example an aliasing limit) are suggestions from the source or from this session, not vendor values and not requirements.

### 3.1 Findings that shape the engine

| # | Finding | Status | Consequence here |
| --- | --- | --- | --- |
| F1 | Products split a kick into three time zones: **click** (0–10 ms, 2–10 kHz), **body/punch** (≈ 5–80 ms, 80–300 Hz), **sub/tail** (from ≈ 50 ms, 40–70 Hz). The source calls these production rules of thumb, not vendor data. | Documented (rule of thumb) | Report analysis per zone, not only per file. Our measured tail fundamental (median 53 Hz, interquartile range 47–57 Hz) lies inside the 40–70 Hz rule of thumb. |
| F2 | Core principle everywhere: one sine oscillator whose pitch envelope falls to the tail pitch, an amplitude envelope, layered click/texture, saturation, final EQ/compressor/limiter. Products differ in edit depth, analysis and effects, not in the principle. | Documented | `kick-params` v0.1 covers the core. Gaps are listed in 3.2. |
| F3 | Hard problems every product solves: **fixed start phase** (every hit identical), **aliasing** from fast sweeps plus hard distortion, **tail tuned to the key**, **phase between layers** (low-end cancellation; common fix is a 180° flip per layer), **relation to the bass** (show tail length and fundamental so the bass can follow). | Fixed phase: documented as needed; the rest documented | Fixed phase is already required by D-005 (byte-identical output). Aliasing has **no requirement and no test anywhere in the repo yet**. Tail fundamental and decay times are already in `sample-metadata`. |
| F4 | The prototype (Bandit Wheel) already capped decay by tempo (`max decay = 60 / BPM × beats`). | Derived from the prototype code | Prior art for tempo-aware length (S2 below). |

### 3.2 The source's requirement lists, triaged for AbeltonGod

Fit: **Core** = already in Phase 01 scope · **Candidate** = fits, needs a `parking-lot` issue and (if it adds a parameter) a `contract-change` PR before anyone builds it · **Later** = needs the bridge, the orchestrator or a plugin · **N/A** = does not apply to a GUI-less, Python-only, deterministic engine.

| ID | Source requirement | Fit | Notes |
| --- | --- | --- | --- |
| M1 | Sine with fixed start phase; two renders bit-identical | **Core** | Same as D-005; the hash test in the Phase 01 spec covers it. |
| M2 | Free pitch/amp envelopes (≥ 64 nodes, tension per segment) | Candidate | v0.1 has one exponential drop (`pitch_decay_ms`) and one `amp_decay_ms`. The engine-side equivalent of an editor is a node list with tension in the params. Depends on issue #7 (envelope semantics are not defined yet). |
| M3 | Log/lin time view | N/A (GUI) | Engine-side lesson: analysis must resolve the first 10 ms finely (see section 4). |
| M4 | Phase lock at the tail | Candidate | In an offline renderer this becomes "tail start phase is a parameter, independent of attack edits". Related to S2. |
| M5 | ≥ 3 sample layers with own envelopes | Later, if ever | Needs licensed audio and a rights decision by the user; the MVP's sounds come from synthesis (D-005). The user's Splice references are measurement input only, never layer material. |
| M6 | Harmonics generator (≥ 4 partials: tuning, gain, decay) | Candidate | Our measured tails are almost pure sine (tail harmonic ratio median 0.01), so harmonics would serve attack/body, not the tail. Do not switch on by default. |
| M7 | Key tuning: note name next to Hz, snap to key; selective MIDI keytracking | Candidate (note name, snap) / Later (MIDI) | v0.1 takes `pitch_end_hz` only. MIDI keytracking needs the bridge. |
| M8 | Sample analysis → editable patch (pitch/amp curves synthetic, top end optionally as sample) | Candidate, high value | `analysis.py` already measures features. A step that **fits kick-params to a reference kick** connects the user's reference set to the engine. See 3.3, gap 5. |
| M9 | Distortion chain with oversampling ≥ 4×; source proposes aliasing products below −90 dBFS for a 10 kHz sweep | **Core-adjacent, missing** | `drive` exists, aliasing is untested. An offline NumPy render can oversample by rendering at a higher rate and decimating (derived). See section 5. |
| M10 | ≥ 4-band EQ with spectrum, limiter with lookahead | Later | Phase 01 has a peak ceiling only. |
| M11 | WAV export 24/32-bit, length, normalisation | **Core** | 24-bit WAV + sidecar JSON is in scope. `bit_depth` allows 16/24; 32-bit float is not allowed in v0.1. |
| M12 | Undo/redo, A/B comparison, tagged preset browser | Partly covered | Undo in Live: D-006. A/B/C ≈ `variants`. Tags/browser: not now. |
| M13 | VST3/AU/AAX, Apple Silicon | N/A | D-007: Python only until a plugin is needed; the user is on Windows. |
| S1 | 606/808/909-style generators | Candidate | Only one product has them. Which sounds count as "909-style" is a listening question for the user; do not claim it from measurements. |
| S2 | Length in beats (1/4, 1/8, 1/16) and a defined end phase, so the tail joins the bassline | Candidate | v0.1 has `length_ms` and `bpm` as "context only". Genre-agnostic: it is about the tail meeting any bass. |
| S3 | Rumble module: kick → reverb → distortion → high-pass → ducking, inside the tool | Candidate | No product has it built in (source). The prototype had a rumble tail (noise through a short generated impulse response, low-passed, saturated); the seed keeps it deterministic. |
| S4 | Free modulation: velocity, round-robin, random per hit | Candidate | Deterministic version: per-hit variation derived from seed + hit index, so output stays byte-identical. Source calls its absence the biggest criticism of the market leader. `variants` is the current analogue. |
| S5 | Reorderable FX chain, chosen mix-down point | Later | Needs a chain abstraction. |
| S6 | Multi-out per layer | Later | In file terms: write layers as separate stems. |
| S7 | Kick/bass view: read a MIDI bassline, show overlap and phase | Later | Needs bridge capabilities with status `tested` (D-004). Engine-side prep already exists: `fundamental_hz`, decay times in the sidecar. |
| Kann | Physical-model generator (impulse → nonlinear resonant filter); wavetable oscillator; polyphony/glide for 808 bass; randomiser that reaches envelopes; XY/ribbon control; drum-replacement trigger | `parking-lot` / N/A | Physical modelling is the most open niche (source). Offline rendering, which a vendor uses as its key innovation, is what this engine does by construction; its stated downside (no real-time per-hit change) does not apply to rendered files. |

### 3.3 Gaps the source names, mapped to the user's goal

The user wants a better kick generator than the prototype and a stronger link to a signature sound. The source's market gaps:

1. **Rumble is built into no product.** Producers build it in the DAW. → S3.
2. **Precision and character are split.** Precise tools sound clean; the character tool has coarser curves. → M2 + S1.
3. **Per-hit modulation is missing nearly everywhere.** → S4, in a deterministic form.
4. **Kick and bass are thought of separately.** → S2 + S7.
5. **Analysis hands back samples, not synthesis.** The market leader keeps the original top end as a sample, which the source says raises rights questions with third-party audio. A fit that rebuilds click and body from parameters fits D-005. This is a claim from the source, not legal advice. → M8.
6. **Physical modelling is almost unoccupied.** → Kann.

*Proposed order for issues (this session's judgement, not from the source; the user decides):* (a) fit-to-reference (M8), because it closes the loop between the reference kicks and the engine; (b) deterministic per-hit variation (S4); (c) tail note name, length in beats, tail phase (M7, S2, M4); (d) aliasing test and oversampling (M9), which is a quality gate for everything that adds drive; (e) rumble (S3).

## 4. Analysis pitfalls (relevant to `analysis.py`, PR #8)

Each of these produced wrong numbers during this work before it was fixed:

1. **A Hann window over a whole one-shot mutes its onset.** The sub share read 100 % instead of 71 % on a synthetic kick. Use a rectangular window for whole-file band shares, or window only steady segments.
2. **Measure from the onset, not the RMS maximum.** The RMS peak can lag the onset by about 10 ms, and by then most of the pitch drop is over (synthetic: 137 Hz measured vs ~219 Hz true).
3. **A short FFT window quantises pitch.** A 40 ms window gives 25 Hz bins, which produced a fake 50 Hz floor. Use instantaneous frequency or zero crossings for the tail fundamental, and check one method against the other.
4. **Decay on a 1 ms mean-abs envelope catches click ripple.** −20 dB times came out at a few ms. Use an RMS envelope of ≥ 5 ms.
5. **"Never reached" is not 0.** Return `None` when a threshold is not crossed inside the file.
6. **Sample folders contain loops, and a loop repeats one kick many times.** Count hits per file and measure only the first one, otherwise one kick counts as 8 or 16. Check hit 1 vs hit 2 in the same loop as a positive control for any duplicate detector.
7. **A hit cut out of a loop can have its decay cut off by the next hit.** Treat decay and length as censored in that case and leave those files out of the decay statistics only.
8. **A "found no duplicates" result needs a positive control.** The threshold of 0.98 found nothing; it only means something because the same detector returns ≈1.0 for repeated hits of one loop and tops out at 0.886 between different files.
9. **Never derive labels from file or archive names.** An earlier pass of this analysis called the set "future rave/trance" because of the ZIP name. That was wrong: the ZIP was simply named after one file. Pack prefixes in filenames are not genre labels either.

The first pass of this analysis (not in the repo) reported a pitch-sweep ratio of ~2.8× and a −40 dB decay of ~190 ms. Both were wrong because of pitfalls 1–4. **Retracted.** A later 37-file version of this note gave a tail pitch median of 56 Hz and said the schema default of 48 Hz sat at the low edge. With 77 files the median is 53 Hz and 48 Hz is inside the interquartile range; that statement is **retracted**.

## 5. Rules for agents

**Scope and design**
- Everything in 3.2 except "Core" is **not scope** until an issue says so. A new engine parameter needs a `parking-lot` issue, then a `contract-change` PR.
- Genre-fluid. Never gate the best result. Every exposed parameter must measurably change an analysis value, and a test must show it.
- Use the measured taste as a range, not a point (section 2).

**Measuring and testing**
- Analysis code follows section 4: measure from the onset and per zone (click / body / tail), rectangular window for whole-file band shares, RMS envelope of at least 5 ms, `None` for a threshold that is never crossed, only the first hit of a loop.
- **Aliasing test (M9):** follow the testing rules in `CLAUDE.md`. The reference must be independent of the code under test (for example the same kick rendered at a much higher rate, not the same function with a different flag). Prove the test can fail (disable oversampling → it must go red). Treat −90 dBFS as a proposal to be checked against what the render actually achieves.
- **Layer phase check (derived here):** when a click layer is added to a body, the energy below 100 Hz must not drop unexpectedly; test with the click on and off.

**Sources and claims**
- References are measurement input only. Never commit audio; never copy a commercial product's presets or parameter tables; before shipping a preset derived from one specific commercial sample, ask the user.
- Label claims *documented* or *derived*. Do not state how a commercial product works internally beyond this note; say "not established".

## Limits

- The data shows what the user selects, not their own productions. There are no genre labels per file.
- 77 files from commercial packs, two uploads that differ from each other (see section 2). 44.1 kHz except 3 files at 48 kHz. Mono sum of stereo files. 13 files are loops or multi-hit files; only their first hit was measured. 8 of them come from one loop family (A/B, 4 variants each) and make up about 10 % of the set.
- Numbers describe signals. They do not say whether a kick sounds good; only the user's listening test decides that (Phase 01 acceptance).
- Second-hand: built from the user's document, whose sources this session did not open.
- Acceptance numbers in the source are proposals by its author.

## Open questions for the user

- Do the medians above match the kicks you would actually use in your own tracks?
- None blocking. The two uploads differ (tail ≈ 56 vs ≈ 49 Hz); if the user ever wants to know why, per-file notes would be needed. Not requested while everything stays genre-fluid.
