# Research: the next sound category after the kick (proposal for a decision)

- **Date:** 2026-11-02. Researcher role.
- **Receiving issue:** #151 (more sample categories); the keyword-vocabulary part answers a question from #226. Docs PR `Refs #151`.
- **Context:** the user closed the kick generator on 2026-11-02 after listening test 3 (`docs/CURRENT_STATE.md`, Phase 05 row). Techno/Trance focus; deterministic DSP, no generative model (D-005); Live 12 Standard, no Max for Live (D-001).
- **Opened on 2026-11-02 (repo state `origin/main` 826fe3f):** `CLAUDE.md`, `docs/CURRENT_STATE.md`, `docs/PRODUCT_SPEC.md` (section 5.1 only), `docs/INTERFACES.md` (tool inputs, lines 69-92), `docs/DECISIONS.md` (D-005, D-013), `docs/ROADMAP.md` (parking lot), `contracts/kick-params.schema.json`, `contracts/sample-metadata.schema.json`, `src/audio_engine/` (all modules, signatures and the render path of `kick.py`), `src/library/layout.py`, `src/orchestrator/arrangement_timeline.py`, `tests/fixtures/arrangement_plan/T1-T3.json`, and these notes: [bandit-wheel synthesis transfer](2026-10-29_bandit-wheel-synthesis-transfer.md) (called "synthesis note"), [bandit-wheel musical transfer](2026-10-29_bandit-wheel-musical-transfer.md) ("musical note"), [kick in tracks](2026-10-29_kick-in-tracks.md), [mix and loudness targets](2026-10-29_mix-loudness-targets.md), [arrangement plan generator design](2026-11-02_arrangement-plan-generator-design.md), [arrangement planner sections/energy](2026-10-29_arrangement-planner-sections-energy.md) ("planner note"), plus kick-gen2 learnings for the rules it states. Issue #226 text read via the REST API.
- **Not done:** nothing was rendered or listened to. No sound claim is made. The artifact (Bandit Wheel) was not reopened; its numbers are quoted from the two notes above and are prior art, not defaults.

## For workers

- **Recommendation:** build **hats (closed and open as one engine)** first, **clap** second, **riser/impact FX** third. Sub/rumble bass has the highest audible weight but its useful form needs a note/pattern/MIDI path that does not exist yet, so it is fourth (section 2).
- **Possible with our stack?** Yes. A hat is band-limited oscillators plus seeded noise plus RBJ filters plus an exponential envelope. All of it is vectorisable NumPy except the biquads (pure-Python loop, about 1 us per sample in the synthesis note's probe, so a 600 ms hat costs tens of ms). No new dependency: `pyproject.toml` has numpy only, no scipy.
- **Route:** one shared "percussive one-shot" scaffold (contract generalisation, DSP blocks, non-pitched analysis, category-neutral write/params path) then the hat voice on top. The clap then reuses the scaffold (end of section 3.6).
- **Read first:** this note, section 3; synthesis note sections 1, 3 and 6; kick-gen2 learnings section 5 (rules); `src/audio_engine/params.py` and `io.py` (kick-named, must be generalised).
- **Effort class:** scaffold medium; hat voice medium; clap small-medium after that; FX small-medium.
- **Blockers:** (1) `sample-metadata.schema.json` allows only `"category": "kick"` and `features` requires pitch-oriented fields, so a `contract-change` comes first (H0). (2) The strict tool budget is 24 of 24 optional parameters, so a `generate_hat` tool cannot add optional fields (INTERFACES line 85); the tool wiring needs a design choice. (3) Placing hits in the arrangement is blocked by the 12 `unknown` arrangement capabilities (#140); a one-shot is useful to the user today only if he plays it himself (Drum Rack, Simpler).
- **Open questions only the user can answer:** four, section 6 (one-shot vs pattern loop; hat or clap first; mono OK; reference hats).

## 1. What a complete track needs, from the planner's element list

The element list and thresholds are the planner note's proposal (section 5.1; thresholds are marked _Interpretation_ there and not confirmed by the user) as implemented in `ELEMENT_THRESHOLDS` and `derive_timeline` (`src/orchestrator/arrangement_timeline.py`). I ran `derive_timeline` on the three fixtures and counted, per element, the share of bars in which it is on (script in the session scratchpad, not committed; reproducible with the repo code and the fixtures at 826fe3f).

| Element in the timeline | Category it needs | Bars on T1 (192 bars) | T2 (256, techno) | T3 (256, trance) |
| --- | --- | --- | --- | --- |
| kick | kick (done) | 92 % | 84 % | 88 % |
| atmos (non-tonal texture, from E 0.20) | texture bed | 92 % | 91 % | 88 % |
| hats_closed (from 0.30) | **hat** | 83 % | 78 % | 75 % |
| bass (0.45; intro/outro by setting) | bass / sub | 79 % | 75 % | 78 % |
| perc1 (0.40) | perc | 71 % | 69 % | 66 % |
| synth (0.65) | tonal synth | 58 % | 66 % | 69 % |
| clap (0.55) | **clap/snare** | 58 % | 56 % | 56 % |
| pad (0.70) | tonal pad | 42 % | 50 % | 50 % |
| hat_open (0.75) | **hat** (open) | 29 % | 34 % | 34 % |
| perc2 (0.80) | perc | 25 % | 31 % | 31 % |
| synth2 (0.90) | tonal synth | 21 % | 28 % | 28 % |
| events: riser, impact, downlifter (pre_drop_gap is silence) | FX | 3 | 6 | 5 |

Reading notes. The percentages count presence, not importance, and they depend on thresholds the user has not confirmed (the timeline also caps energy in the DJ mix zone, and kick is off in breaks). The `hats_closed` and `hat_open` rows are one engine with different decay. The kick is the only element with an engine today (`CURRENT_STATE`, "What does not exist yet").

A second, weaker signal for audible weight is the artifact's own loop-level table (integrated loudness vs the kick loop, in LU): bass -3, clap -5, impact -7, hats -10, riser -10, perc -11, atmos -22 (musical note, Q5; the artifact states there is no published standard for these numbers, and our mix note found no club loudness standard either). I use it only to break ties.

## 2. Ranking: value against effort (deterministic DSP only)

Effort classes: small (one voice, existing blocks), medium (new blocks or contract work), large (new subsystem or an outside dependency). Effort follows the synthesis note's transfer tables (what ports as is, with changes, or not) and the engine code read today.

| Rank | Category | Value for a complete track | Effort | Dependencies / why this rank |
| --- | --- | --- | --- | --- |
| **1** | **Hats: closed + open** (one voice, `decay_ms` makes it open) | Two timeline elements; on in 75-83 % of bars (closed) and 29-34 % (open); the first drum element after the kick and allowed in the intro/outro mix zone. Level about -10 LU vs kick (artifact). | medium (scaffold) + small (voice) | Needs no pitch, key, pattern or MIDI. Recipe is plain DSP: square bank + noise + HP/peaking/LP + envelope (synthesis note section 3). The 808 hat is documented as six square oscillators in roughly 200-800 Hz through a steep high-pass, with separate envelopes for a higher-pitched start and a lower body ([Cherry Audio, Transistor 808 Hats docs](https://docs.cherryaudio.com/misfit-audio/transistor-808-hats), opened 2026-11-02, vendor documentation, medium confidence). That page says white noise works poorly for cymbals, while the artifact mixes noise in (synthesis note 3.1); so the noise share must be a parameter and a listening question, not a given. |
| **2** | **Clap (and snare/rim as variants)** | One element; on in 56-58 % of bars; the backbeat (musical note 3.3: beats 2 and 4, **G** convention); about -5 LU vs kick, the loudest drum after the kick in the artifact table. The user ranked clap first in the questionnaire (musical note, Q1; the questionnaire itself was not opened by me). | small after rank 1 | Band-passed seeded noise with a multi-burst envelope (synthesis note 4.1-4.2, "transfers with changes"). Reuses everything the hat scaffold builds. Clap is off in the intro mix zone by the energy cap (0.50 < 0.55), so hats cover more of the DJ-critical part. |
| **3** | **Riser / impact / downlifter** | Planner events: 3 / 6 / 5 per template (section 1). The only category where an event is exactly one sample (position and length come from `derive_timeline`, in beats). | small-medium | Filtered noise with a swept corner and a level ramp; impact = short pitched drop + noise + tail (rumble-like convolution is optional). Length is in bars: reuses the `length_beats` idea of kick v0.3. Usable through the already tested audio-clip import path. Not in the synthesis note (it scanned no FX recipe: the artifact hid FX from the wheel, musical note Q1), so recipes need their own look. |
| 4 | Sub / bass (note or line) and rumble | Highest audible weight (bass -3 LU; on in 75-79 % of bars). | one-shot sub note: small-medium; **a bass line that plays through sections: large**; rumble: medium | A single sub note is a kick body at a fixed pitch and is nearly expressible with the kick engine (kick `pitch_end_hz` range 30-120 Hz). But the planner's "bass" is a line over time. That needs notes or a pattern (key choice, kick/bass register conflict, hypothesis H5 in the musical note), a MIDI or loop path (all arrangement capabilities `unknown`, #140), and the time-varying filter with its stability check (synthesis note V4). Rumble is kick-derived (kick-gen2 S3 candidate) and loop-shaped. Swap with rank 3 if the user weighs the low end above transitions; ranks 1-2 do not change. |
| 5 | Percussion (perc1, perc2) | 69-71 % / 25-31 % of bars | medium | Needs per-style tuned voices (membrane, FM, square banks). The user's stated dislike of toms outside hard groove (musical note H3, **U**) shrinks the safe set. Build after hats/clap show how much of the scaffold generalises. |
| 6 | Atmos, pad, synth, synth2 | Coverage high (atmos 88-92 %) but audible weight lowest (atmos -22 LU) and none has a taste anchor | large | Loops of N bars (seamless), usually stereo, tonal ones need chords/notes. Out of reach for a one-shot engine; needs a loop/stereo contract (synthesis note V9) first. |

Confidence: the coverage numbers are exact for the three fixtures and the current thresholds. The ranking is my judgement from those numbers plus the effort reading; the effort classes are estimates, not measurements.

## 3. Top pick: the hat engine (first scope)

### 3.1 What exists in `src/audio_engine/` and what can be reused

Read from signatures and the render path of `kick.py`; whether each piece drops in unchanged is not tested.

| Existing piece | Reuse for a hat | Change needed |
| --- | --- | --- |
| `dsp.py`: `biquad_bandpass`, `one_pole_highpass/lowpass`, `raised_cosine`, `kaiser_lowpass`, `oversampled` | yes | Add RBJ high-pass, low-pass, peaking (static), as the synthesis note section 6 lists. The 303 ladder and time-varying filter are not needed for hats. |
| `kick.py`: `_amp_envelope` (linear attack, exp. decay to -60 dB), `_fade_out`, `_remove_mean`, `_normalise` (ceiling measured on the quantised file), `_drive` (anti-aliased residual) | yes, as shared helpers | Move to a neutral module or import across; kick bytes must stay identical (golden hashes in `tests/audio_engine/test_engine_version.py`). |
| `params.py`: schema-driven resolve, error lines, defaults | pattern yes; code is kick-named (`resolve_kick_params`, `KickParamsError`, `KICK_SCHEMA_FILE`) | Generalise by category or copy the pattern for `hat-params.schema.json`. |
| `io.py`: `encode_wav`, sidecar, no-overwrite naming, `rerender_from_sidecar` | yes | `write_kick`/`render_kick_wav` are kick-named; sidecar `engine` holds one global `ENGINE_NAME`/`ENGINE_VERSION` (see section 7, D-013 coupling). |
| `variants.py`: salted hash draws, spread boxes, rounding | pattern yes | New salt per category; boxes per field. |
| `length.py`: T60 measurement (`t60_seconds`), 20 ms to 2000 ms grid | measurement yes; bisection rule is kick-specific | A hat gets a simpler rule: file length >= decay to -60 dB plus fade; reuse the T60 measure as the test reference. |
| `analysis.py`: envelope in dB, decay times | partly | `fundamental_hz` is meaningless for a hat; add spectral features (3.3). |
| `library/layout.py`: `place_kick` -> `Samples/Drums/Kicks` | pattern yes | A category-aware `place_sample`, folder `Samples/Drums/Hats`. |
| `cli.py`, presets JSON, `tests/support/kick_params.py` fresh-seed helpers | pattern yes | Per category. |

### 3.2 Proposed parameter space (names and ranges are proposals; the audio-engineer measures ranges)

One shared space for closed and open (kick-gen2 rule: one parameter space per category; presets are data). Prior-art values in brackets are the artifact's, quoted from the synthesis note section 3.1, not defaults.

| Parameter | Meaning | Analysis value it must move |
| --- | --- | --- |
| `decay_ms` | time to -60 dB (same definition as kick `amp_decay_ms`) | measured T60 |
| `attack_ms` | linear attack [0.8] | onset rise time |
| `metal` 0..1 | power share of the square bank vs seeded noise | spectral flatness / tonal peak count |
| `pitch_scale` | multiplier of the six fixed oscillator frequencies [205.3 ... 800 Hz] | spectral centroid |
| `hp_hz`, `lp_hz` | RBJ high/low-pass corners [5-9.5 kHz; 6.5/18 kHz] | energy below `hp_hz`, above `lp_hz` |
| `peak_hz`, `peak_db` | one peaking boost [8.5-9.5 kHz, +4 dB] | band energy ratio |
| `body_split` (optional) | high partial decays faster than the low part, as in the documented 808 design (Cherry Audio page above) | early vs late centroid |
| `drive` | optional anti-aliased saturation (reuse kick residual method) | harmonic energy |
| `length_ms` or `length_beats` + `bpm`, `seed`, `offset_ms`, `polarity`, `sample_rate`, `bit_depth`, `peak_ceiling_dbfs` | same meaning as kick | as for kick |

Fields shared with the kick keep the kick's name and meaning where they mean the same thing (`seed`, `drive`, `polarity`, `offset_ms`, `peak_ceiling_dbfs`, `length_beats`). Kick `tone` is a tilt around a 1500 Hz pivot (`TONE_PIVOT_HZ`); the hat equivalent would need its own pivot, so I propose `pitch_scale`/`hp_hz` instead of reusing the name with another meaning.

### 3.3 Presets, determinism, structure

- **Presets (data, proposals):** closed tight, closed standard, open short, open long. Values come from prior art until the user supplies hats (question Q4); they are starting points, not taste.
- **Seeds:** noise from `np.random.SeedSequence([seed, layer_id])` sub-streams (synthesis note 1.1: additive offsets collide across layers). Square-bank start phases fixed and written in the contract.
- **Band-limited squares:** additive odd harmonics below Nyquist for fixed frequencies (synthesis note 1.2). At 48 kHz an 800 Hz square still has odd harmonics up to 23.2 kHz (29th), just under Nyquist, so the rule for which harmonics are summed (and the 0.45*sr style cap the kick click uses) must be written into the contract.
- **Structural range (lesson from test 3):** the user said the finished kicks "share a similar character" (`CURRENT_STATE`, Phase 05). To avoid the same outcome the first hat contract needs structurally different families, not only narrow parameter ranges: square bank vs noise-dominated (`metal` 0..1 covers both) and a body split on/off. Whether that range is wide enough is a listening question.
- **Non-pitched analysis (new):** spectral centroid, share of energy above 8 kHz (the planner/synthesis notes name it), spectral flatness, T60, onset rise time. Known pitfall carried from kick-gen2: analysis windows must be long enough for the signal, and short transients need fine onset resolution (synthesis note 4.2, "M3").

### 3.4 Measurable acceptance criteria for the hat engine

Per "Test what matters": normal path, documented errors, wrong-audio failures. Numbers marked "measure" are for the engineer to set from a run, not from this note.

1. **Determinism.** Same params and seed give byte-identical WAV and sidecar re-render; seed + 1 changes the bytes whenever `metal` < 1 or noise is present. Golden SHA-256 for 3 renders, hard failure on Linux and Windows CI (as D-013 does for the kick). Fresh seeds over the whole contract range (property test, helpers in `tests/support/`).
2. **Every exposed parameter moves its analysis value** (kick-gen2 rule), over seeded random draws: `decay_ms` -> measured T60 within the tolerance the kick length rule already uses (read `length.py`); `pitch_scale` -> centroid rises; `hp_hz` -> energy below the corner at least N dB under the passband (N: measure); `metal` -> flatness; `attack_ms` -> rise time. Expected directions written in the test, not computed from engine code (CLAUDE.md "keep the reference independent").
3. **Aliasing.** Render vs the same voice at 4x rate decimated with an independent filter; in-band error at most the bound used for the kick drive (-68 dB, kept by the user's decision of 2026-11-02, `CURRENT_STATE`) unless the measurement says otherwise; report achieved levels. Square banks at high `pitch_scale` are the case that could fail.
4. **Wrong-audio failures.** Peak ceiling holds on the quantised file; no DC; first sample 0 and no click at the end (fade); a render that decays 60 dB inside the file for every `decay_ms` the contract allows, or a documented error text.
5. **Contract.** Instances validate, out-of-range is rejected (not clamped), sidecar re-renders. Kick golden hashes unchanged after the scaffold change.
6. **Fault injection (main checks only, ~6 mutants):** decay x 1.02; seed ignored; noise layers sharing one stream; high-pass corner shifted; oscillator harmonics not cut at Nyquist; ceiling off by 0.5 dB. Each turns at least one test red.
7. **Speed.** Open hat, 1 s at 48 kHz renders in well under the kick's 15 s request target (user target, `CURRENT_STATE`); measure on the CI box and report.

### 3.5 Listening test needed

One short test, in the style of test 3 (lessons from `CURRENT_STATE`: forced picks carry bias, the identical control pair received a pick):

- Material: 4 closed hats (3 presets + 1 duplicate of one preset as control), 2 open hats (short, long), all with the `dense` kick in a 2-bar offbeat loop at 140 BPM. The loop is made by a small check script (test material, not a product feature) or placed by the user in a Drum Rack.
- Questions (German, one per pair): which one sits better with the kick; too bright / too dark; open hat too long / right / too short; do four seed variants of one preset feel like one family. Allow "no difference" as an answer.
- Needs the user's ears and Live; CI cannot decide it. Plan authored by the sound-designer; the listening guide file belongs to the audio-engineer (`docs/setup/LISTENING_TEST_*.md`, ownership table).

### 3.6 Split into small issues for the audio-engineer

Each issue is small; WIP = 1 per role. H0 needs the lead's decision on the contract shape first.

| # | Issue | Scope | Not in scope | Done when |
| --- | --- | --- | --- | --- |
| H0 | `contract-change`: category generalisation + `hat-params` v0.1 | `category` enum gets `hat`; `features` for non-pitched samples (centroid, HF share, T60, rise time; `fundamental_hz` stays optional); `hat-params.schema.json`; INTERFACES section; proposal for per-category engine version (D-013, see implications) | engine code, tool wiring | schema valid; positive and negative instances; kick sidecars still validate and re-render; user merge (contract-change) |
| H1 | DSP blocks | RBJ HP/LP/peaking; additive band-limited square bank; `SeedSequence` sub-streams helper | voice, contract | each block tested against an independent reference (magnitude response measured by FFT of an impulse response; harmonic count by direct sum) |
| H2 | Non-pitched analysis | the features of 3.3; synthetic-signal tests | changing `analyse` for kicks | known signals give known values; kick `analyse` output byte-identical |
| H3 | Category-neutral write/params path | generalise `resolve_*`, `write_*`, `rerender_from_sidecar`, `place_*` by category | any new sound | all kick tests unchanged and green; kick golden hashes unchanged |
| H4 | Hat voice | `hat.py` render, param resolution, golden hashes, acceptance 1-5 and 7 of 3.4 | presets, CLI | criteria met with fresh seeds; mutants of 3.4 point 6 reported |
| H5 | Presets, variants, CLI | 4 presets, variant boxes, `cli --category hat` | tool wiring | variants stay inside contract and are reproducible from seed |
| H6 | Listening test package | rendering script + guide + decode helper | verdicts | package ready for the user; sound-designer plan linked |
| H7 | `generate_hat` tool (owner `orchestrator-engineer`) | strict schema without new optional fields; handler; guard wiring | Live import changes | blocked by the budget decision (INTERFACES line 85) |

Order: H0 -> (H1, H2, H3 in parallel by one engineer in sequence) -> H4 -> H5 -> H6 -> H7. Clap then becomes: schema (small), voice (multi-burst envelope on band-passed noise; synthesis note 4.2), presets; about the size of H4 + H5 without H1-H3.

## 4. What carries over from the keyword-vocabulary idea (#226)

The vocabulary note does not exist yet (checked: no vocabulary file in `docs/research/` at 826fe3f; #226 is the design request). So this section says what the #226 text implies for other categories, not what the note contains.

| Part of #226 | Carries to hats/clap? | How |
| --- | --- | --- |
| Mechanism: keyword -> parameter fields and direction, weight 0 = off, 1.0 = neutral, one scale defined once | **Yes, unchanged** | Build the combination code once and category-neutral (`schema + base params + keyword weights -> params`). The weight scale and the conflict/combination rules are category-independent. |
| Each keyword is a measurable hypothesis (an analysis value that should change) | **Yes, but needs H2** | For kicks the values are pitch, decay, click energy. Hats need centroid, HF share, T60, flatness first; without H2 a hat keyword cannot be checked. |
| Bilingual list, producer meanings, German cheat sheet, worked prompts | Pattern yes, words partly | Shared axes keep the same word: hell/dunkel (bright/dark), kurz/lang (tight/long), schmutzig (drive), hart/weich (attack), trocken/Raum (dry/room), "Variante" (seed). Targets differ per schema. |
| Kick-only words: sub weight, pitch sweep, tail note/root key, clip, punch via click | **No** | Hat words are separate: offen/geschlossen (a decay range, not a switch), metallisch (`metal`), sizzle/zischend (HF share, `peak_db`), dumpf. Pattern words ("16th roll") are not sample words and stay out. |
| Hard limits from the contract ranges and the length rule | Yes | Each category's schema supplies its own limits; the combination code must clamp nothing silently (contract rule: out-of-range is rejected). |

Consequence for the hat design: choose hat parameter names so shared axes map onto the same words (section 3.2 does this where the meaning is equal). Do not write the hat vocabulary before the user has approved the kick vocabulary. A vocabulary is also the cheapest route to the "different character" the user wants (`CURRENT_STATE`, Phase 05), so every later category should expose the axes that allow it.

## 5. Findings

| Finding | Confidence | Source |
| --- | --- | --- |
| Share of bars on per element (table in section 1) | High for fixtures and current thresholds | `derive_timeline` run on T1-T3 at 826fe3f |
| Thresholds behind the numbers are unconfirmed proposals | High | planner note 5.1 ("Interpretation") |
| `sample-metadata` allows only `kick`; `features` requires `peak_dbfs`, `length_ms`, with pitch-oriented optional fields | High | `contracts/sample-metadata.schema.json` lines 8-12 and the features object |
| `io.py` writes mono PCM only; stereo needs a contract change | High | `io.py` lines 3, 63-65; synthesis note 1.4 |
| Strict tool budget is exactly used (23 + 0 + 1 = 24 of 24) | High for the repo; the limit itself rests on the tool-schema note's web reading (medium) | `docs/INTERFACES.md` line 85 |
| `ENGINE_VERSION` is global and a byte change bumps it, which makes old sidecars refuse to re-render | High | `src/audio_engine/__init__.py`, D-013 |
| No scipy dependency; filters are hand-written | High | `pyproject.toml` |
| The 808 hat: six square oscillators (about 200-800 Hz), steep high-pass, separate high/low envelopes; page says noise works poorly for cymbals | Medium (vendor documentation) | [Cherry Audio](https://docs.cherryaudio.com/misfit-audio/transistor-808-hats), opened 2026-11-02 |
| The artifact's hat recipe mixes six squares and noise | High for the artifact content (read in the synthesis note) | synthesis note 3.1 |
| User ranks clap first, then hats, perc, bass (questionnaire) | Medium (second-hand via the notes; questionnaire not opened) | synthesis/musical note headers, #151 body |
| Bass line / MIDI / arrangement placement is blocked by `unknown` capabilities | High | `docs/research/2026-11-02_arrangement-plan-generator-design.md` section 6 |

## 6. Open questions for the user (only those that change the design)

1. **One-shot or also a pattern loop?** Should the first hat/clap engine make only single hits (the user places them in Live), or also a rendered 1-2 bar loop at the track BPM with swing? Recommendation: one-shots only. A loop adds a pattern parameter set, swing, loop-seam handling and a length-in-bars contract, and placing the clip in the arrangement is blocked by #140; patterns belong to the planner/MIDI side.
2. **Hat first or clap first?** The data in section 1 favours hats (more bars, in the intro, two elements); your questionnaire rank put clap first. Both need the same scaffold, so the order only changes which voice is H4.
3. **Is mono enough for the first version?** The current WAV writer and metadata are mono. Stereo width (and a stereo room tail on claps) needs a contract change. Recommendation: mono now.
4. **Do you have hats (and claps) whose character you like?** With reference files we can measure a taste range as was done with the 77 kicks (fit-to-reference route); without them the presets come from prior art and your first listening test sets the range. This decides whether H5 is preset-first or reference-first.

## 7. Implications for the lead

- Propose to open H0-H7 after the user answers Q1-Q4; H0 is a `contract-change`. Q2 only reorders; H0-H3 are the same for hat or clap.
- **D-013 coupling:** one global `ENGINE_VERSION` means a future byte change in hat code would bump the version and make every kick sidecar refuse to re-render (`EngineVersionMismatch`). Proposal: version per category engine (sidecar `engine.name` or a `category` key), decided in H0; needs the lead to amend D-013 or add a decision.
- **Tool budget:** the 24/24 limit blocks an optional-field `generate_hat`. Options for H7: a tool with required fields only (preset enum + seed + length), or dropping low-value optional kick fields from the strict variant. Needs the orchestrator-engineer and the lead; not a user question unless it removes kick fields.
- Hats/clap do not by themselves get into an arrangement: the timeline has the elements, but placing clips is unknown (#140). Until then the new sounds serve the user's manual work in Live and the listening tests.
- No decision is contradicted. D-001 and D-005 are respected (no Max for Live, no generative model).
- Side findings: none opened.

## State update proposal (for the PR body)

"Research note `docs/research/2026-11-02_next-category-proposal.md` (Refs #151): proposes hats (closed+open) as the next category, then clap, then riser/impact FX; sub/rumble bass fourth because its useful form needs a note/pattern/MIDI path. Gives engine scope, acceptance criteria, listening test and issues H0-H7, and what carries over from #226. Four user questions open. Nothing implemented, nothing run in Live, nothing listened to."
