# Research: tom/perc voices, sidechain/pump without Max, reverb tails for claps and snares

- **Date:** 2026-11-02. Researcher A (sound and audio, D-018). All web sources below were opened on this date; article dates are given where the page showed one.
- **Question (lead):** for Techno/Trance, (1) tom/perc/shaker voices: is deterministic DSP enough, which measurable targets, which extra categories earn a place after rim and bass; (2) sidechain/pump as a generated or described effect: what can the copilot do in Live 12 Standard without Max; (3) reverb/room tails for claps and snares as sample-side processing.
- **Read first (repo `origin/main` af6dd3a):** `CLAUDE.md`, `docs/ROADMAP.md`, `docs/CURRENT_STATE.md` (line 19, lead decisions), `docs/DECISIONS.md` (D-001, D-005, D-018 by reference), `contracts/capabilities.json`, `contracts/clap-params.schema.json`, `src/audio_engine/clap.py` (`_room`, lines 147-148 and 163-173), `src/audio_engine/dsp.py` (function list), and these notes, which are **not repeated** here: [next-category proposal](2026-11-02_next-category-proposal.md), [bandit-wheel synthesis transfer](2026-10-29_bandit-wheel-synthesis-transfer.md) (sections 3, 5), [bandit-wheel musical transfer](2026-10-29_bandit-wheel-musical-transfer.md), [hat synthesis design](2026-11-02_hat-synthesis-design.md), [hat targets](2026-11-02_hat-targets-and-listening-plan.md), [clap targets](2026-11-02_clap-targets-and-listening-plan.md), [clap experimental options](2026-11-02_clap-experimental-options.md), [snare targets](2026-11-02_snare-targets.md), [snare/rim/sub design](2026-11-02_snare-rim-and-sub-bass-design.md), [rim targets](2026-11-02_rim-targets.md), [bass targets](2026-11-02_bass-targets.md), [MIDI/arrangement/devices](2026-10-29_live-midi-arrangement-devices.md), [kick gen2 learnings](2026-10-28_kick-gen2-learnings.md).
- **Not done:** nothing was run in Live, nothing rendered or heard. No sound claim is made. One timing probe (section 4) ran in this sandbox.

## For workers

- **Toms/percs (section 1):** deterministic DSP is enough for tuned membranes (tom, conga) and for shaker/ride; they reuse blocks that exist (sine body with exponential pitch drop as in the kick, seeded noise, RBJ filters). **No outside source gave numeric targets for techno toms**, so targets must come from user-supplied reference samples, as for claps and hats. Effort: small-medium for a tom/conga voice after the hat scaffold; shaker is already a `model` candidate in the hat design.
- **Extra categories after rim and bass (section 1.4):** my order is (1) shaker/ride as a hat `model`, (2) tom/conga (tuned membrane), (3) impact/riser FX (already third in the next-category note), (4) metal/cowbell/clave. Reason: bar share in the planner timeline and reuse of existing blocks. Tom is the one with a stated user dislike outside hard groove (musical note), so it needs the user's yes first.
- **Sidechain/pump (section 2):** the safe, buildable form today is a **described effect** (the copilot writes Compressor settings as text), plus an optional **sample-side duck curve** for loops. Everything that writes a Compressor into Live is **unknown / needs user test**: `capabilities.json` has no `device.*` or `send` entry at all (13 tested, 12 unknown, 1 unsupported; none about devices). AbletonOSC at `0ca6821` cannot set a Compressor's sidechain source (no device-level routing property in `device.py`).
- **Reverb tails (section 3):** the clap already has a sample-side `room` (seeded noise impulse response, FFT convolution). For snares, the cheapest route is the same stage plus the proposed `gate_ms`. An algorithmic reverb (Dattorro) is possible but is a pure-Python loop in our stack (probe: 0.124 s for 0.8 s of a 6-stage Schroeder, section 4).
- **Blockers:** none for sections 1 and 3 beyond the existing contract work (category enum). Section 2 device writes are blocked by missing capability entries and a missing custom handler.
- **Open questions only the user can answer:** (a) are toms wanted outside hard groove (his stated dislike, musical note H3, **U**); (b) can he supply 3-5 reference toms/percs/shakers he likes (targets depend on it); (c) does he want the copilot to only describe the sidechain setting, or to set it in Live (needs device-write approval and a test on his PC).

## 1. Tom, perc, shaker voices

### 1.1 Findings

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| T1 | The artifact builds toms/congas as a sine that glides from 1.25x (tom) / 1.3x (conga) toward the target pitch with time constants 7 ms / 4 ms, plus a 6 ms noise tick through BP 2.5 kHz. This is prior art, not a target. | high (repo note) | [synthesis transfer, section 5](2026-10-29_bandit-wheel-synthesis-transfer.md) |
| T2 | The same note judges tom/conga "transfers with changes": structure equals our kick body (exponential pitch drop). | high (repo note) | same, section 5.2 |
| T3 | The TR-808 bass-drum circuit analysis (DAFx-14) reports a bridged-T centre of about 49.5 Hz and an attack-related frequency shift of about 6 ms. A footnote says the 808 toms and congas use bridged-T networks similarly, but the paper does not study them. | medium (read through a summarising fetch; numbers are for the bass drum) | [Werner, Abel, Smith, DAFx-14](https://dafx14.fau.de/papers/dafx14_kurt_james_werner_a_physically_informed,_ci.pdf) |
| T4 | An Attack Magazine ES2 tutorial (24 Jan 2013) builds a synth tom from its kick patch (sine, pitch envelope) but shows the values only in a screenshot. **No numeric tom values** are in the text. | medium | [Attack, Drum synthesis in Logic ES2, p. 2](https://www.attackmagazine.com/technique/tutorials/drum-synthesis-in-logic-es2/2/) |
| T5 | A techno beat breakdown (Attack, 21 Nov 2019) uses toms as alternating hits, each tom low-passed with varied resonance; claps with reverb and delay at "nearly 10%" wet; no tuning or level values. Shakers, congas, rides and rims are not in that article. | medium | [Attack, Rolling techno](https://www.attackmagazine.com/technique/beat-dissected/rolling-techno/) |
| T6 | A forum thread (Elektronauts, 10 Mar 2024) describes a basic techno pattern as kick on every beat, off-beat hats **or shaker**, 16th hats, snare/clap on 2 and 4; only the opening post was readable. | low (forum, one post) | [Elektronauts](https://www.elektronauts.com/t/drum-programming-for-techno/209933) |
| T7 | Planner timeline: `perc1` is on in 66-71 % of bars, `perc2` in 25-31 % (three fixtures). Presence, not importance. | high (repo note, thresholds unconfirmed) | [next-category proposal, section 1](2026-11-02_next-category-proposal.md) |
| T8 | The user's stated taste: toms off by default except in hard groove, "they turned cool loops goofy" (artifact comment). A stated taste of the artifact author as recorded in the repo, **U** in the musical note. | medium | [musical transfer, lines 131 and 402](2026-10-29_bandit-wheel-musical-transfer.md) |
| T9 | Shaker in the artifact: seeded noise, BP `4500 + 55*tone` Hz Q 1.5, HP 3 kHz, 12 ms linear attack. The lead decided shaker/ride are **not** in `hat-params` v0.1. | high (repo) | [hat design, 2.3](2026-11-02_hat-synthesis-design.md); `docs/CURRENT_STATE.md` line 19 |

### 1.2 Is deterministic DSP enough?

Inference from T1-T3, not a measured result: a tuned membrane voice is a sine body with a pitch glide and a short noise tick; every block exists in the engine or in the kick (pitch-drop phase integration, seeded noise streams, RBJ filters, soft saturation). No new dependency. The same-seed-same-bytes rule (CLAUDE.md) holds if the voice uses the existing seeded sub-stream pattern. What deterministic DSP cannot settle is **taste**: outside sources give structure, not numbers (T4, T5). Metallic voices (cowbell, clave, metal) are square-bank/FM variants of the hat blocks; the ride is the weakest of those per the hat note.

### 1.3 Measurable targets (proposal; all numbers are hypotheses until references exist)

| Quantity | Definition (follow the kick pitfalls) | Source for a value | Status |
| --- | --- | --- | --- |
| tail pitch `f0_tail_hz` | instantaneous frequency of the tail, not a short FFT peak (kick learnings, pitfall 3) | none for techno toms; user must supply references or choose by ear | no target |
| glide ratio `f0_start / f0_tail` | ratio at onset+2 ms vs at 60-80 % of the decay | artifact: 1.25 (tom), 1.3 (conga); tau 7 / 4 ms | prior art only |
| `t60_ms` | as in the clap/rim notes; `null` if not reached inside the file | artifact durations 60 + 2.2*decay ms (tom) | prior art only |
| tick energy share | energy 1.5-4 kHz in the first 10 ms vs total | artifact tick BP 2.5 kHz | prior art only |
| spectral centroid / rise time | as in hat/clap targets; shaker separates from hat by a 12 ms rise (hat design 2.3) | artifact | prior art only |

Falsifiable hypotheses for a test (my proposals):

- **PH1** Tail `f0` stays within +/-3 % of the requested pitch for the whole sweep range of the voice, measured by instantaneous frequency. A pitch-estimate failure would show the glide is too long.
- **PH2** A tom render with the tick switched off differs from the one with it on only in the first 10-15 ms band energy above 1.5 kHz (layer on/off check, as in the synthesis note V8).
- **PH3** Seed changes move only noise-derived quantities (tick, shaker body), not `f0_tail`.

Pitch mapping to the key: kick-params v0.3 already has a key concept (ROADMAP, Phase 05 row). Whether toms follow the project key (artifact: scale degree and octave per voice, tom octave 3) is a product choice for the user.

### 1.4 Which extra categories earn their place after rim and bass

| Rank | Category | Why (evidence) | Cost | Caveat |
| --- | --- | --- | --- | --- |
| 1 | Shaker / ride as hat `model` values | T6, T9; same blocks as the hat; planner `hat_open` + `perc` rows | small once the hat scaffold exists | lead deferred them out of v0.1; this is only a later order |
| 2 | Tom / conga | T1, T2, T7; reuses the kick body | small-medium | T8: user dislikes toms outside hard groove; ask first |
| 3 | Impact / riser FX | already third in the next-category note; the planner marks 3-6 events per track | small-medium | covered there, not repeated |
| 4 | Metal / cowbell / clave | artifact has recipes (square banks, FM); no techno source found for levels | medium | weakest evidence; needs references |

The ranking is my inference from the bar-share table and block reuse. It is not a measured value ranking and the user has not confirmed it. An `atmos` texture bed is on in 88-92 % of bars (same table) and would outrank all four by presence, but it is a loop/texture problem, not a one-shot, and is outside this question.

## 2. Sidechain / pump without Max

D-001 rules out Max for Live. Live 12 Standard has Compressor, Glue Compressor, Auto Filter, Auto Pan, Utility and the stock Reverb (per Ableton's edition comparison, read through a summarising fetch, not verbatim). That page also showed Hybrid Reverb and Convolution Reverb as Suite-only and Max for Live as Suite-only; the "CV" tool rows it listed as Standard look wrong to me and I did not use them.

### 2.1 What the sources say

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| S1 | Compressor has an external sidechain section with source choosers, Gain, Dry/Wet, Sidechain EQ and Listen. Automatic makeup gain is unavailable with an external sidechain. | medium (summarising fetch of the manual) | [Live 12 manual, audio effect reference, 29.9](https://www.ableton.com/en/live-manual/12/live-audio-effect-reference/) |
| S2 | Auto Filter has external sidechain too (source chooser, tapping point Pre FX / Post FX / Post Mixer, SC Gain, SC filter), so the envelope follower can follow the kick. | medium | same page, 29.2.7 |
| S3 | LOM `CompressorDevice` has four properties: `available_input_routing_types`, `available_input_routing_channels` (get, observe) and `input_routing_type`, `input_routing_channel` (get, set, observe; values are dicts with `display_name`, `identifier`). The page names no Live version. | high for the property list | [LOM CompressorDevice](https://docs.cycling74.com/apiref/lom/compressordevice/) |
| S4 | AbletonOSC `0ca6821`: `device.py` has an empty `methods` list (no `delete_device` there; that call is in `track.py:33`) and read-only properties `class_name`, `name`, `type`, plus the parameter lists/values (lines 26-47, 52-80, 128-131); it has **no** device-level routing property. Routing handlers exist only at track level (`track.py:166-199`, `:202-235`: input and output routing). | high (file read) | [AbletonOSC device.py](https://github.com/ideoforms/AbletonOSC/blob/0ca68214bd62c9b5cb641ca34006cfd70ba94430/abletonosc/device.py), [track.py](https://github.com/ideoforms/AbletonOSC/blob/0ca68214bd62c9b5cb641ca34006cfd70ba94430/abletonosc/track.py) |
| S5 | Parameter get/set by index and value in internal units already exists; `insert_device(name)` is in the LOM since 12.3 (native devices only); the Python browser route `load_item` is medium confidence. Automation envelopes on Arrangement lanes: no call found. | high / medium | [MIDI/arrangement/devices note, Q3, Q4](2026-10-29_live-midi-arrangement-devices.md) |
| S6 | The mixing chapter of the manual that I could read says return-track sends tap Pre or Post the mixer (18.4); its text on sidechain routing was not in the fetched content. | medium | [manual, mixing](https://www.ableton.com/en/live-manual/12/mixing/) |
| S7 | Sidechain tutorials give no numeric settings: "turn the threshold down, raise it until it sounds right", release "depends on tempo and your own taste". | medium (article 3 Nov 2016, edited 25 Jun 2021) | [Mixdown](https://mixdownmag.com.au/features/columns/sidechain-compression/) |
| S8 | The artifact's duck is a gain envelope per kick hit: 4 ms linear dip, exponential recovery tau 110 ms, depth 0.85 x duck setting. Prior art for a sample-side curve. | high (repo note) | [synthesis transfer, section 2 table](2026-10-29_bandit-wheel-synthesis-transfer.md) |

### 2.2 What the copilot could do, per route (nothing here is tested)

| Route | What it needs | Status label |
| --- | --- | --- |
| A. **Describe**: the copilot answers with Compressor/Glue/Auto Filter settings and the routing steps ("Audio From" = kick track) as text | nothing from Live | buildable now (no Live write); the values must be labelled suggestions (S7: no numeric source) |
| B. Insert a Compressor on a track | `Track.insert_device("Compressor", ...)` (LOM, since 12.3) or the Python `browser.load_item` | **unknown / needs user test**; not in `capabilities.json` |
| C. Set sidechain source to the kick track | `CompressorDevice.input_routing_type/channel` (S3) | **unknown / needs user test**; **not exposed by AbletonOSC** (S4); needs a custom handler in the bridge |
| D. Set Threshold, Ratio, Attack, Release, Dry/Wet, Gain | `/live/device/set/parameter/value` (exists, internal units, no range check; S5) | **unknown / needs user test**: Compressor parameter names, indexes and ranges in 12.4.5 are not read; first step is `/live/device/get/parameters/name` on a Compressor |
| E. Turn the sidechain on (the toggle) | probably a parameter, probably index-based | **unknown**; not checked |
| F. Draw a pump shape as volume automation instead of a compressor | Session clip envelope via Python API (medium) or Arrangement lane (no call found) | **unknown / needs user test**; and lane automation likely unreachable |
| G. Duck a bass loop **before** import (sample-side curve, S8) | pure DSP on a rendered loop | buildable in CI; fits only loop-type output (the bass is a one-shot; the bass note says the duck is a mix and pattern matter) |
| H. Max for Live Envelope Follower / LFO tool | Max | rejected by D-001; would need the user to reopen it |

Pitfalls:

- Writing parameters by index lists with `/live/device/set/parameters/value` would also write index 0, usually "Device On" (note linked above).
- A sidechain with the Compressor on the *bass* track and the source on the *kick* track depends on the kick track's routing tap (Pre FX / Post FX / Post Mixer). A wrong tap changes what the compressor hears; this is the Live default behaviour that I did not verify.
- A tempo-linked release is an inference: one beat at 136 BPM is 60/136 = 441 ms. A release that exceeds the beat period would not recover before the next kick. I found no source that states a recommended ratio.

### 2.3 Is "pump" a generated sample?

A one-shot has no kick to duck against, so a pump is not a property of a one-shot (the bass note and the artifact make the same point). It is either a mix setting (A, B-F) or a processing step on a rendered loop (G). The latter needs a loop product that does not exist and a kick pattern as input. My recommendation is A first, G later only with a loop category.

### 2.4 Test strategy

- **CI can test:** a pure function `duck_curve(kick_onsets, sr, depth, attack_ms, release_ms)`: the dip depth, the recovery constant and byte-identical output for the same inputs; and the message shapes the bridge would send, against a fake (not an Ableton integration test).
- **User's machine only:** list the parameters of a freshly inserted Compressor; set the sidechain source; confirm undo of the insert. Proposed experiment ids for the bridge-engineer, following the E-numbers of the devices note: **E14** insert Compressor via LOM `insert_device`; **E15** read Compressor parameter names/ranges; **E16** set `input_routing_type` to a track in 12.4.5; **E17** one undo after E14-E16 (E11-E13 are taken by the devices note; `E01`-`E17` in the keyword listening plan are listening-file names, a separate namespace). Each yields `capabilities.json` entries only after evidence (CLAUDE.md capability rule).
- **Ears:** whether a given Compressor setting pumps pleasantly cannot be tested without the user; I make no claim.

## 3. Reverb and room tails for claps and snares (sample-side)

### 3.1 Findings

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| R1 | The clap contract has `room` (0-1, wet amount) and `room_length_ms` (100-800 ms); the engine convolves the signal with a seeded noise impulse response with exponential 60 dB decay, normalised to unit energy, by FFT. | high (repo) | `contracts/clap-params.schema.json`; `src/audio_engine/clap.py:147-148, 163-173` |
| R2 | A `room` render can fail the `t60_ms` measure: the sidecar then holds `null`; a model run showed `null` for `room` 0.5 and 1.0 at length 300 ms. | high (repo note) | [clap targets, P2](2026-11-02_clap-targets-and-listening-plan.md) |
| R3 | The snare design has no room; a gated tail is proposed as `gate_ms` (0 = off, 20-500) as a derived idea without source. | high (repo) | [snare targets line 34](2026-11-02_snare-targets.md), [snare design line 85](2026-11-02_snare-rim-and-sub-bass-design.md) |
| R4 | A drum-design guide says reverb is "almost always part of the clap sound" and that a short room helps separate clap from snare, with no values (page undated; footer 2026). Its clap values: BP 1-3 kHz, 3-4 hits 10-20 ms apart, noise tail 100-200 ms. | low-medium (one site) | [Beat Kitchen](https://beatkitchen.io/guides/electronic-music/02-drum-design/) |
| R5 | Attack's techno breakdown puts claps through a reverb and a delay at nearly 10 % wet (21 Nov 2019). | medium | [Attack, Rolling techno](https://www.attackmagazine.com/technique/beat-dissected/rolling-techno/) |
| R6 | Gated reverb recipe (Sound on Sound, Mar 2005, Steve Howell): reverb with a medium room, a stereo noise gate after it, instant attack, near-instant release, hold to taste, threshold set so the end of the tail does not flutter; the drum can trigger the gate through its sidechain. No numbers. | medium | [SOS, gated reverb](https://www.soundonsound.com/sound-advice/q-how-do-set-gated-reverb) |
| R7 | Dattorro's plate reverb (JAES 45(9), Sep 1997): one-pole input bandwidth filter, four input all-pass diffusers, a tank of further diffusers with a figure-eight feedback loop, one-pole damping, slow modulation of two taps, stereo output from internal taps; Table 1 gives coefficients (decay 0.50, input diffusion 0.750 / 0.625, damping 0.0005, bandwidth 0.9995, at 29761 Hz). Licence of the paper's text not stated in what I read. | high for structure, medium for the numbers (summarising fetch) | [Dattorro, Effect Design Part 1](https://ccrma.stanford.edu/%7Edattorro/EffectDesignPart1.pdf) |
| R8 | The artifact already uses a seeded noise IR for its voice reverb, with a separate seed for the right channel (`+77`). | high (repo note) | [synthesis transfer, seed table](2026-10-29_bandit-wheel-synthesis-transfer.md) |

### 3.2 Options

| Option | How | Cost in our stack | Notes |
| --- | --- | --- | --- |
| a. Noise-IR room (exists for clap) | `_room`; extend to the snare as the same stage | FFT convolution, no per-sample loop | Reuse; keeps v0.1 hashes valid if absent means skipped (clap options note) |
| b. Gated tail | apply `gate_ms` to the convolved tail (R6 as an offline envelope: hold, then fast release) | cheap | A gated tail stabilises `t60_ms` near the gate time (clap options note, X-gated row) |
| c. Algorithmic reverb (Schroeder / Dattorro) | allpass and comb loops (R7) | pure-Python per-sample loop; section 4 probe | Gives an actual stereo, modulated tail, and a decay that is a parameter instead of an IR length; more code, more risk |
| d. Stereo room | two decorrelated IRs (R8 pattern) | 2x of (a) | Engine voices are mono today (lead decision); stereo would need a contract change |
| e. Recorded IR convolution | external IR files | none in DSP | Needs licensed assets in the repo; not recommended (my inference; no asset question has been put to the user) |
| f. Reverb in Live (Reverb on a return, Standard has it) | device insert + send level | see section 2 | **unknown / needs user test**; track send set/get exists in AbletonOSC (`track.py:94-103`) but no capability entry |

### 3.3 Pitfalls

- A baked tail lengthens the one-shot: the file length must exceed tail + IR or the engine fades out 5 ms (clap schema text). The decay measure can be `null` (R2).
- Wet energy raises RMS at a fixed peak ceiling, so a roomy clap measures louder than its dry twin at the same peak (the same effect the clap options note measured for `drive`: RMS +10.9 dB, t60 166 to 372 ms).
- Several hits in a loop overlap their tails; a Drum Rack choke or the sample length decides (see [choke note](2026-11-02_drum-rack-choke-and-oneshot-placement.md), not re-read in detail here).
- Whether a high-passed or low-passed wet signal keeps the kick clean is **my inference**; the repo sources give a low-pass on the *rumble* reverb only ([genre words note](2026-11-02_kick-genre-words-and-note-names.md)), not for claps.

### 3.4 Test strategy

CI: `room` 0 gives bytes identical to the dry render (exists as a design rule); energy after 150 ms rises with `room` while the first 30 ms stay within 1 dB (clap H7); the same seed gives the same IR. Ears: whether room or gate helps with the kick is the clap listening test C4 (already planned); I claim nothing.

## 4. The one measurement

Plain Python 3.13.18, NumPy 2.5.3, this sandbox (not the user's PC), a single run, so the figures are an order of magnitude only: a Schroeder-style reverb with 4 combs and 2 all-passes over 0.8 s mono at 48 kHz took 0.124 s in a pure-Python per-sample loop; one FFT convolution of 0.8 s with a 0.4 s IR took 3.7 ms (mean of 20). The script is in the session scratchpad, not in the repo. A Dattorro tank has more stages than this probe, so its cost would be higher; I did not measure it.

## 5. Open questions and Implications for the lead

Open for the user: the three in "For workers". Proposals only:

1. **Order after rim and bass:** shaker/ride model, then tom/conga with the user's yes, then FX, then metal (section 1.4).
2. **Reference first:** before a tom or perc contract, ask for 3-5 reference samples; analyse them with the clap/hat method. Outside sources gave structure, not numbers (T4, T5).
3. **Sidechain, step 1:** a described-effect answer in the copilot, flagged as a suggestion. If the user wants Live writes, the bridge-engineer gets E14-E17 first and the capability entries stay `unknown` until his run (CLAUDE.md capability rule).
4. **Snare tail:** reuse `_room` and `gate_ms` in the snare contract rather than a new reverb; defer an algorithmic reverb until a listening test shows the noise IR is not enough.
5. **Labelled unverified:** the PR reviewer could not reach cycling74.com, ccrma.stanford.edu, dafx14.fau.de, attackmagazine.com or soundonsound.com from its sandbox, so claims from those sources have no second pair of eyes. all manual and edition statements come from summarising fetches (the ableton.com host was not reachable by direct request in this session); Compressor parameter names and indexes in Live 12.4.5 are unread; `insert_device` in 12.4.5 is untested.

**State update proposal:** Features table rows "Weitere Sample-Kategorien" and "Kick im Mix (Pegel, Sidechain, Loudness)" may list this note under Research. No decision is changed.
