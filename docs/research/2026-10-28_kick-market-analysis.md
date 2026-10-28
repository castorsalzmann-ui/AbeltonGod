# Research: Kick synth market analysis, condensed for Kick Gen 2.0

_Date: 2026-10-28 · Status: input for Phase 01 and later kick work. Not a decision, not a spec. Scope still comes from the issue._

Source: the user's own document "Kick-Synth Marktanalyse & Referenz-Spezifikation" (2026-10-28, German, built from vendor pages, reviews and retailer texts). This note keeps only what changes engineering choices here. **Product facts (prices, release dates, feature lists) were not re-verified by this session.** In the source, "not documented" means "not mentioned in the sources read", not "missing".

Companion note: `2026-10-28_kick-prior-learnings.md` (what we measured in the user's reference kicks, lessons from the earlier prototype, measurement pitfalls). Read both before kick-engine work.

## 1. How to use this note

- **Genre-fluid.** The source names a genre focus (hard groove / dark techno around 142 BPM, goa / progressive trance). The user's standing instruction is to keep everything genre-fluid for now. So the focus is used here only as a reason for **capabilities** (rumble, length in beats, tail phase), never for genre-keyed presets, ranges or code paths. The two statements are in tension; the PR asks the user to confirm the reading.
- **Two labels.** Keep the source's habit: say whether a claim is *documented* (comes from a source) or *derived* (an inference). Internal DSP of commercial products is not published; write "not established", do not guess.
- **Numbers marked "proposal"** (e.g. an aliasing limit) are suggestions from the source or from this session, not vendor values and not requirements.

## 2. Findings that shape the engine

| # | Finding | Status | Consequence here |
| --- | --- | --- | --- |
| F1 | Products split a kick into three time zones: **click** (0–10 ms, 2–10 kHz), **body/punch** (≈ 5–80 ms, 80–300 Hz), **sub/tail** (from ≈ 50 ms, 40–70 Hz). The source calls these production rules of thumb, not vendor data. | Documented (rule of thumb) | Report analysis per zone, not only per file. Our measured tail fundamental (median 53 Hz, interquartile range 47–57 Hz) lies inside the 40–70 Hz rule of thumb. |
| F2 | Core principle everywhere: one sine oscillator whose pitch envelope falls to the tail pitch, an amplitude envelope, layered click/texture, saturation, final EQ/compressor/limiter. Products differ in edit depth, analysis and effects, not in the principle. | Documented | `kick-params` v0.1 covers the core. Gaps are listed in section 3. |
| F3 | Hard problems every product solves: **fixed start phase** (every hit identical), **aliasing** from fast sweeps plus hard distortion, **tail tuned to the key**, **phase between layers** (low-end cancellation; common fix is a 180° flip per layer), **relation to the bass** (show tail length and fundamental so the bass can follow). | Fixed phase: documented as needed; the rest documented | Fixed phase is already required by D-005 (byte-identical output). Aliasing has **no requirement and no test anywhere in the repo yet**. Tail fundamental and decay times are already in `sample-metadata`. |
| F4 | The prototype (Bandit Wheel) already capped decay by tempo (`max decay = 60 / BPM × beats`). | Derived from the prototype code | Prior art for tempo-aware length (S2 below). |

## 3. The source's requirement lists, triaged for AbeltonGod

Fit: **Core** = already in Phase 01 scope · **Candidate** = fits, needs a `parking-lot` issue and (if it adds a parameter) a `contract-change` PR before anyone builds it · **Later** = needs the bridge, the orchestrator or a plugin · **N/A** = does not apply to a GUI-less, Python-only, deterministic engine.

| ID | Source requirement | Fit | Notes |
| --- | --- | --- | --- |
| M1 | Sine with fixed start phase; two renders bit-identical | **Core** | Same as D-005; the hash test in the Phase 01 spec covers it. |
| M2 | Free pitch/amp envelopes (≥ 64 nodes, tension per segment) | Candidate | v0.1 has one exponential drop (`pitch_decay_ms`) and one `amp_decay_ms`. The engine-side equivalent of an editor is a node list with tension in the params. Depends on issue #7 (envelope semantics are not defined yet). |
| M3 | Log/lin time view | N/A (GUI) | Engine-side lesson: analysis must resolve the first 10 ms finely (see pitfalls in the companion note). |
| M4 | Phase lock at the tail | Candidate | In an offline renderer this becomes "tail start phase is a parameter, independent of attack edits". Related to S2. |
| M5 | ≥ 3 sample layers with own envelopes | Later, if ever | Needs licensed audio and a rights decision by the user; the MVP's sounds come from synthesis (D-005). The user's Splice references are measurement input only, never layer material. |
| M6 | Harmonics generator (≥ 4 partials: tuning, gain, decay) | Candidate | Our measured tails are almost pure sine (tail harmonic ratio median 0.01), so harmonics would serve attack/body, not the tail. Do not switch on by default. |
| M7 | Key tuning: note name next to Hz, snap to key; selective MIDI keytracking | Candidate (note name, snap) / Later (MIDI) | v0.1 takes `pitch_end_hz` only. MIDI keytracking needs the bridge. |
| M8 | Sample analysis → editable patch (pitch/amp curves synthetic, top end optionally as sample) | Candidate, high value | `analysis.py` already measures features. A step that **fits kick-params to a reference kick** connects the user's reference set to the engine. See section 4, gap 5. |
| M9 | Distortion chain with oversampling ≥ 4×; source proposes aliasing products below −90 dBFS for a 10 kHz sweep | **Core-adjacent, missing** | `drive` exists, aliasing is untested. An offline NumPy render can oversample by rendering at a higher rate and decimating (derived). See rules in section 5. |
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

## 4. Gaps the source names, mapped to the user's goal

The user wants a better kick generator than the prototype and a stronger link to a signature sound. The source's market gaps:

1. **Rumble is built into no product.** Producers build it in the DAW. → S3.
2. **Precision and character are split.** Precise tools sound clean; the character tool has coarser curves. → M2 + S1.
3. **Per-hit modulation is missing nearly everywhere.** → S4, in a deterministic form.
4. **Kick and bass are thought of separately.** → S2 + S7.
5. **Analysis hands back samples, not synthesis.** The market leader keeps the original top end as a sample, which the source says raises rights questions with third-party audio. A fit that rebuilds click and body from parameters fits D-005. This is a claim from the source, not legal advice. → M8.
6. **Physical modelling is almost unoccupied.** → Kann.

*Proposed order for issues (this session's judgement, not from the source; the user decides):* (a) fit-to-reference (M8), because it closes the loop between the reference kicks and the engine; (b) deterministic per-hit variation (S4); (c) tail note name, length in beats, tail phase (M7, S2, M4); (d) aliasing test and oversampling (M9), which is a quality gate for everything that adds drive; (e) rumble (S3).

## 5. Rules for agents who pick this up

- Everything in section 3 except "Core" is **not scope** until an issue says so. New engine parameter → `parking-lot` issue, then a `contract-change` PR.
- **Aliasing test (M9):** follow the testing rules in `CLAUDE.md`. The reference must be independent of the code under test (for example the same kick rendered at a much higher rate, not the same function with a different flag). Prove the test can fail (disable oversampling → it must go red). Treat −90 dBFS as a proposal to be tested against what the render actually achieves.
- **Layer phase check (derived here):** when a click layer is added to a body, the energy below 100 Hz must not drop unexpectedly; test with the click on and off.
- **References are measurement input only.** Never commit audio; never copy a commercial product's presets or parameter tables; before shipping a preset derived from one specific commercial sample, ask the user.
- Do not state how a commercial product works internally beyond this note. Say "not established".

## Limits

- Second-hand: built from the user's document, whose sources this session did not open.
- Genre focus in the source (60 % / 40 %) vs. the user's genre-fluid instruction: see section 1.
- Acceptance numbers in the source are proposals by its author.
