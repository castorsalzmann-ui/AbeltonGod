# Research: snare, rim shot and sub-bass one-shot as further categories (design pre-work)

- **Date:** 2026-11-02. Researcher role. Docs-only PR, `Refs #151`.
- **Question (lead):** (a) snare and rim shot as an extension of the clap-params family, (b) a pitched bass/sub one-shot and how it differs from the kick engine, (c) effort and order (hat, snare, rim, bass) in small steps.
- **Read on 2026-11-02 (`origin/main` 4472cb9):** `CLAUDE.md`; notes [next-category proposal](2026-11-02_next-category-proposal.md), [hat synthesis design](2026-11-02_hat-synthesis-design.md), [clap reference analysis](2026-11-02_clap-reference-analysis.md), [bandit-wheel synthesis transfer](2026-10-29_bandit-wheel-synthesis-transfer.md) (sections 2 and 4), [kick genre words and note names](2026-11-02_kick-genre-words-and-note-names.md); `contracts/clap-params.schema.json`, `contracts/sample-metadata.schema.json` (v0.2 features), `src/audio_engine/categories.py` and `dsp.py` (signatures only).
- **Not repeated:** the artifact's snare/rim/bass constants (synthesis note 2.2, 4.1; they are cited by section, not copied), the hat parameter list, the hat issue split H0-H7, the note-name/Camelot table.
- **Not done:** nothing rendered, nothing listened to, no code, no contract change. No statement about how anything sounds. Labels: *sourced* = a page opened today says it; *derived* = my inference; *unverified* = background knowledge or unreadable source.

## For workers

- **Possible with the stack?** Yes, all three. Snare and rim use only blocks already merged (RBJ filters, `square_bank`, `substreams`) plus a damped-sine/pitch-envelope body; no new dependency. Bass needs one new block: a time-varying low-pass (filter envelope). No Max for Live (D-001), no generative model (D-005).
- **Route:** snare = `snare-params` v0.1 in the clap family (same envelope/export fields, same registry entry pattern in `categories.py`); rim = a second `model` of a `perc`-style contract or its own small schema (decision for the lead, section 2.4); bass = its own `bass-params` v0.1 because it is pitched and gated (section 3).
- **Read first:** sections 1.2 (circuit facts), 2.2 (snare field list), 3.2 (what differs from the kick); the synthesis note 4.1 and 2.2 for the artifact's constants.
- **Key facts:** (1) 808 snare = two bridged-T "oscillators" plus gated high-passed noise; 909 snare = two oscillators with waveshapers and separate envelopes, noise split into two bands (SOS, the article author's account; 180/330 Hz there are his own patch values). (2) 808 rim shot = bridged-T resonators, no noise; clave = a single resonator near 2.5 kHz (medium confidence, hobby site). (3) A rolling techno bass in a published tutorial is a saw/square, high-pass about 65 Hz, low-pass about 350 Hz with a fast filter envelope, on G2 (about 98 Hz) in 16ths (Attack Magazine). (4) The kick's `fundamental_hz` (sidecar) applies to bass; the note-name table of the genre-words note applies unchanged, but the bass window is a different octave range (3.4).
- **Effort:** snare small-medium (after hat scaffold, as clap was); rim small; bass medium (new filter block, gate/length semantics, note-name input). Recommended order: hat, snare, rim, bass (section 4).
- **Blockers:** `sample-metadata` `category` enum has only `kick`, `clap`, so each new category needs a `contract-change` (as H0). Tool budget 24/24 (INTERFACES line 85) blocks optional fields on new tools. Placing hits or a bass line in the arrangement is blocked by the `unknown` arrangement capabilities (#140); a one-shot helps only when the user plays it himself.
- **Open questions for the user only:** section 5 (five).

## 1. Findings

### 1.1 Table

| # | Finding | Confidence | Source (opened 2026-11-02) |
| --- | --- | --- | --- |
| S1 | Snare model in the article author's OWN modular patch (modelled on the 909): two oscillators with two waveshapers produce the two modes, which the author sets to 180 Hz and 330 Hz; the author uses one VCA/contour for both partials and says Roland's design gave them two VCAs/contour generators (different level and decay); noise is low-passed, then split into two branches, one high-passed to a narrow band, each with its own VCA/contour. The article gives no 808/909 frequencies, filter cutoffs in Hz or decay times in seconds | medium for the structural description of the 909 (the author's account, no schematic or Roland source opened); the 180/330 Hz are the author's patch settings, NOT sourced 909 values (corrected 2026-11-02, re-opened that day) | [Reid, Practical Snare Drum Synthesis, SOS](https://www.soundonsound.com/techniques/practical-snare-drum-synthesis) |
| S2 | TR-808 snare: two bridged-T oscillators (pitch and decay fixed by components, need only a kick to ring), one gated white-noise source with a single high-pass, a separate "snappy" contour; no per-oscillator envelopes | high (same article) | same |
| S3 | The article does not give 808 frequencies, decay times or filter cutoffs | high (absence) | same |
| S4 | 808 snare body frequencies about 238 Hz and 476 Hz (ratio 2.0), noise high-passed; envelope decays not given; the page defers to the Roland service manual | low-medium (hobby web page quoting rounded numbers; the 180/330 Hz of S1 are the SOS author's own patch values, not 808 or 909 values) | [0b5vr, TR-808 notes](https://scrapbox.io/0b5vr/TR-808) |
| S5 | A peer-reviewed paper confirms that the 808 snare, toms/congas and rim shot/clave all use bridged-T networks that give decaying pseudo-sinusoids when pinged, but gives no snare/rim numbers | high for the statement, absence of numbers | [Werner et al., DAFx-14 PDF, footnote 15](https://dafx14.fau.de/papers/dafx14_kurt_james_werner_a_physically_informed,_ci.pdf) |
| S6 | 808 rim shot about 455 Hz and 1667 Hz (two oscillators, high-passed, no noise source); clave one oscillator about 2500 Hz | low-medium (same hobby page as S4) | [0b5vr, TR-808 notes](https://scrapbox.io/0b5vr/TR-808) |
| S7 | A rim/clave circuit write-up (RS mode vs CL mode): two bridged-T generators mixed through a VCA and a filter; in clave mode generator 1 has no effect and generator 2 gets feedback and bypasses VCA and filter; tuning is one resistor per T-network; no frequencies given | medium (builder's blog, 808 schematic) | [syntherjack, The perfect 808 rimshot/clave](https://syntherjack.net/the-perfect-808-rimshot-clave/) |
| S8 | A 909 rim module is described as an exact copy of the analog circuit with three T-bridge damped-sine oscillators; the same listing mixes in 808 text, so reliability is low | low (vendor listing with a copy-paste error) | [ModularGrid, Tiptop RS909](https://modulargrid.net/e/tiptop-audio-rs909) |
| S9 | Software recipe for a 909-style snare: Tune (two sine modes, drop with shell size), Tone = low-pass cutoff on the noise, Snappy = noise attack speed and the noise-to-resonance balance; "a snare hit is mostly broadband noise"; noise decays longer than the tone | medium (tutorial, no numbers) | [Mode Audio, Massive Drum Design 2](https://modeaudio.com/magazine/massive-drum-design-part-2-snares) |
| S10 | Another software recipe: two triangle oscillators at 185 and 349 Hz through a waveshaper, gain to 0 in 0.1 s; white noise gain to 0 in 0.2 s; noise high-pass 2000 Hz; equal mix | low-medium (code sample in a blog) | [DEV, Browser Beats II](https://dev.to/kabisasoftware/browser-beats-ii-synthesizing-a-snare-drum-and-a-hi-hat-463h) |
| S11 | The artifact's snare (triangle 150-280 Hz with a 1.6x to 1x exponential drop in 30 ms; noise high-pass 1200 + 10 tone Hz) and rim (square 1.7-2.3 kHz through a Q 6 band-pass plus a triangle at 0.28 f) exist; line references are in the synthesis note | high (content read in the existing note) | [synthesis note 4.1](2026-10-29_bandit-wheel-synthesis-transfer.md) |
| B1 | Rolling techno bass (tutorial): saw or square, "transients need to be audible"; high-pass about 65 Hz, low-pass about 350 Hz, fast filter envelope; fast amp attack but first notes not at full volume; G in the C2 octave range (G2, about 98 Hz) on nearly every 16th with the first 16th of each beat left empty; sub layer low-passed near 80 Hz, 12 dB/oct; sidechain to the kick | medium (one tutorial; opinion, not measurement) | [Attack Magazine, Warehouse rolling techno bass](https://www.attackmagazine.com/technique/tutorials/warehouse-rolling-techno-bass/) |
| B2 | Operator rumbling techno bass (tutorial): sine with FM drawn in, slow attack "to get rid of the clicks", 24 dB/oct low-pass with a touch of resonance, overdrive, mostly one note (F), no notes on the kick's position; no numeric values given | medium (tutorial, no numbers) | [Attack Magazine, Rumbling techno bass in Operator](https://www.attackmagazine.com/technique/synth-secrets/rumbling-techno-bass-ableton-operator/) |
| B3 | The artifact's bass voice (oscillator set saw/square/sub/dirty/reese, exponential LP cutoff envelope, wobble, tanh shaper) and the 303 voice (polyBLEP saw, 4-pole ladder, about 1.2 us/sample in a probe) are already analysed | high (existing note) | [synthesis note section 2](2026-10-29_bandit-wheel-synthesis-transfer.md) |
| B4 | The 24 note-name/Camelot roots map to MIDI numbers 27-38 with a rule "tonic, mode ignored"; Live's octave label is unverified | high for arithmetic; Live label unverified | [genre-words note section 4](2026-11-02_kick-genre-words-and-note-names.md) |

### 1.2 What this means (derived)

1. **Snare is a bridge between hat/clap and kick.** Its body is two pitched, short, decaying partials (kick-like, but with a ratio of about 1.8-2.0 between them: 330/180 = 1.83 (author's own model, S1), 476/238 = 2.0 (808 page, S4), 349/185 = 1.89 (blog code, S10)), its top is shaped noise (clap/hat-like). So it needs both a pitch envelope (kick block) and the band/high-pass noise (clap block). The ratio comes from three sources that disagree slightly; keep it a parameter (`mode_ratio`).
2. **The 808 and 909 differ in structure, not only values** (S1, S2): the 909 has separate envelopes per partial and a two-band noise; the 808 has fixed-decay resonators and one high-passed noise. A single parameter space can cover both if it has per-partial decay and two noise decays (section 2.2). Do not label presets "808" or "909" (same rule as hats, hat note pitfall 7): the circuit is only the structural model.
3. **A bridged-T resonator pinged by a pulse is a damped sinusoid with a short pitch bend** (S5, kick analysis in the same paper: about 49.5 Hz centre, a bend of more than an octave at the start). So the rim/clave family can be rendered in closed form, `a * exp(-t/tau) * sin(2 pi f t)`, without a filter and without noise. That is deterministic by construction and cheap; whether it matches the machine is not established.
4. **Rim shot and clave are the same family** (S7: one circuit, two modes), so one `model` field covers both; the difference is the number of resonators and a high-pass.
5. **Bass differs from the kick in one decisive way:** the pitch is held and the sound lasts as long as the note (a gate), instead of decaying to -60 dB on its own (section 3.2).

## 2. Snare and rim as an extension of the clap family

### 2.1 What is shared (read from the repo)

| Shared piece | Where | Use for snare/rim |
| --- | --- | --- |
| Envelope/export fields of `clap-params` v0.1: `seed`, `variants`, `bpm`, `sample_rate`, `bit_depth`, `length_ms`, `drive`, `polarity`, `offset_ms`, `peak_ceiling_dbfs`, `preset` | `contracts/clap-params.schema.json` | identical names and meaning |
| RBJ low-pass/high-pass/peaking, `rbj_*`; `biquad_bandpass`; `square_bank`; `substreams(seed, count)` | `src/audio_engine/dsp.py` | noise shaping, rim partials (optional), one independent stream per noise layer |
| Category registry and generic write/re-render path | `src/audio_engine/categories.py` (`CONTRACT_CATEGORIES = ("kick", "clap")`) | a new category = contract enum value + schema + `Category` entry; the test that compares the registry with the contract enum already exists (comment line 21) |
| Non-pitched features `spectral_centroid_hz`, `hf_share_8k`, `t60_ms`, `rise_time_ms` | `sample-metadata.schema.json` v0.2 | reused; `rise_time_ms` is a poor target for multi-burst sounds (clap analysis P1) but fine for a single-hit snare (derived; verify) |

Not shared: the clap's burst train and `room` (a clap-specific structure). A snare has one impact, not bursts. The strict rule from the kick (one parameter space per category, presets as data) holds.

### 2.2 Proposed `snare-params` v0.1 (names and ranges are proposals; the audio-engineer measures)

Values in brackets are the sourced numbers they derive from; none is a default chosen by ear.

| Field | Type / range (proposal) | Default (proposal) | Basis |
| --- | --- | --- | --- |
| shared fields | as clap (`seed`, `variants`, `bpm`, `sample_rate`, `bit_depth`, `drive`, `polarity`, `offset_ms`, `peak_ceiling_dbfs`, `preset`) | as clap | section 2.1 |
| `length_ms` | 100 .. 1500 | 400 | derived from noise decay range below plus fade |
| `body_hz` | 120 .. 400 | 190 | lower partial [S1 180 (author's own patch), S4 238, S10 185, artifact 150-280] |
| `mode_ratio` | 1.5 .. 2.4 | 1.85 | upper/lower partial [330/180 (S1, author's own patch), 476/238, 349/185] |
| `body_shape` | 0 .. 1 (0 sine, 1 triangle) | 0.5 | S10 and artifact use triangle, S9 sine; additive band-limited triangle/sine mix |
| `pitch_drop` | 1.0 .. 2.0 (start/end frequency) | 1.4 | artifact 1.6x in 30 ms; bridged-T bend (S5, kick) |
| `pitch_drop_ms` | 3 .. 60 | 25 | artifact 30 ms |
| `body_decay_ms` | 30 .. 300 | 90 | time to -60 dB of the lower partial; S10 uses 100 ms to zero, artifact 70 + decay ms |
| `body2_decay_ratio` | 0.3 .. 1.2 | 0.7 | 909 has separate envelopes per partial (S1: the author's account of the 909) |
| `body_level` | 0 .. 1 | 0.6 | relative power share of body vs noise (RMS-normalised, as hat `metal`) |
| `noise_decay_ms` | 60 .. 800 | 180 | S9: noise decays longer than tone; S10 200 ms; artifact 80 + 2.5 decay ms |
| `noise_hp_hz` | 500 .. 6000 | 1800 | S10 2000 Hz; artifact 1200 + 10 tone Hz |
| `noise_lp_hz` | 3000 .. 16000 | 9000 | S1/S9: noise is low-passed ("Tone"); no number sourced |
| `noise_band_mix` | 0 .. 1 | 0.4 | 909 two-band noise (S1: the author's account of the 909): share of the narrow high-passed band with its own faster decay |
| `noise_attack_ms` | 0.1 .. 12 | 0.8 | "Snappy" changes noise attack speed (S9); artifact 0.8 ms |
| `snappy` | 0 .. 1 | 0.5 | macro: raises noise share and shortens noise attack; a vocabulary-level convenience, to be decided if it is a field or only a keyword weight (see lead) |
| `tone_peak_hz`, `tone_peak_db` | 2000 .. 8000, -6 .. +6 | 5000, 0 | optional static peaking, as hat |
| `gate_ms` | 0 (off) or 20 .. 500 | 0 | optional "gated" tail as in a gated-reverb style snare (derived idea; no source; the clap analysis found one gated reference clap, so a gate field is plausible) |

Closed-form recipe (derived): `body = sum_k a_k * exp(-t/tau_k) * shape(phi_k(t))` with `phi_k` the integral of the instantaneous frequency (the kick's `body_phase` does this already); `noise = HP(LP(white))` with two exponential envelopes (wide band, narrow band) summed by `noise_band_mix`; both parts RMS-normalised then mixed by `body_level`; then drive, DC removal, fade, normalise. Noise streams: `substreams(seed, 2)` (wide, narrow), body has no randomness. Seed therefore only changes the noise; the contract must say so (a snare at `noise level 0` is seed-independent, same as the hat `metal = 1` case).

### 2.3 Measurable features (for the snare analysis; extends v0.2)

| Feature | Definition | Parameter it must move |
| --- | --- | --- |
| `body_peak_hz` (new) | frequency of the strongest spectral peak in 100-500 Hz in the first 40 ms (Hann window shorter than the sample) | `body_hz`, `pitch_drop` |
| `mode_ratio_measured` (new) | ratio of the two strongest peaks in 100-800 Hz | `mode_ratio` |
| `body_noise_ratio_db` (new) | energy 100-500 Hz vs 2-12 kHz, first 80 ms | `body_level`, `snappy` |
| `body_t60_ms`, `noise_t60_ms` (new) | -60 dB time of the band envelopes (RMS, 5 ms) of 100-500 Hz and above `noise_hp_hz` | `body_decay_ms`, `noise_decay_ms` |
| `spectral_centroid_hz`, `hf_share_8k`, `t60_ms`, `rise_time_ms` | existing v0.2 definitions | `noise_hp_hz`/`noise_lp_hz`/`tone_peak_db`, `noise_decay_ms`, `noise_attack_ms` |
| `dc_offset`, `peak_dbfs` | existing | |

Reference targets: none sourced for Techno/Trance snares (no published numeric target found; same absence as for hats). The clap work measured the user's 13 claps; the snare needs the user's reference snares to get a taste range (open question 1). Until then analysis reports, it does not pass or fail on taste values.

### 2.4 Rim shot (and clave) design

**Recipe (derived from S5-S7, artifact):** `rim = sum_{i=1..n} a_i * exp(-t/tau_i) * sin(2 pi f_i t + phi_i)`, optionally followed by a high-pass, with an optional short noise tick (hobby source S6 says no noise in the 808 rim; the artifact adds none either but uses a Q 6 band-pass on a square). Two routes, both deterministic:

1. **Damped sines (closed form):** exact, no filter state, no aliasing if `f_i < 0.45 sr`; matches the bridged-T description (S5). Preferred.
2. **Pinged resonators** (impulse through RBJ band-pass, Q high): needs filter ringing control and is less predictable at high Q. Only if route 1 cannot reach a wanted timbre.

| Field (proposal) | Range | Default | Basis |
| --- | --- | --- | --- |
| `model` | `rim`, `clave` | `rim` | S7: same circuit, two modes |
| `f1_hz` | 300 .. 3500 | 455 | S6 (low confidence) |
| `f2_ratio` | 2.0 .. 5.0 | 3.66 | S6: 1667/455; artifact: square at f plus triangle at 0.28 f (ratio 3.57) |
| `f3_ratio` | 0 (off) .. 8 | 0 | S8 (three oscillators, low confidence) |
| `decay1_ms`, `decay2_ms` | 5 .. 120 | 40, 15 | no sourced value; artifact 12 + 0.4 decay ms for the square |
| `level2` | 0 .. 1 | 0.6 | |
| `hp_hz` | 200 .. 6000 | 1000 | S6 high-pass, no cutoff given |
| `click_level`, `click_ms` | 0 .. 1, 0.2 .. 3 | 0.2, 1 | optional noise tick, derived |
| `length_ms` | 50 .. 600 | 200 | |
| shared fields | as snare | | |

`clave` has one resonator near 2.5 kHz (S6); with `f1_hz` 2500 and `f2_ratio` off it is a special case, so a separate `clave` model is not needed. Pitch glide (the bridged-T start bend) as an optional `bend` field: S5 shows the bend for the kick; its size for rim is not sourced.

Features: `f1_measured_hz` (peak in the first 30 ms), ratio of the two peaks, `t60_ms` (short: tens of ms), `rise_time_ms` (single hit, meaningful), `hf_share_8k`, `spectral_centroid_hz`.

**Contract decision for the lead:** rim as part of `snare-params` (a `model` field `snare`/`rim`) would make fields mutually exclusive by model and the schema harder to read; separate `rim-params` is cleaner and small. The hat note chose one contract with a `model` field for a family with the same blocks; rim and snare share blocks only partly (rim has no noise path), so I propose a separate `rim-params` (derived judgement).

### 2.5 Test strategy

- **CI can test:** golden hashes (byte identical, seeds), each parameter moves its feature (random draws, expected direction written in the test), body peak within a tolerance of `body_hz` at the end of the pitch drop (measure), band envelopes decay to -60 dB inside `length_ms`, ceiling on the quantised file, no DC, first sample 0, fade, aliasing against an independent 4x render, schema negative cases (`noise_lp_hz` must exceed `noise_hp_hz` by a margin: engine rule, JSON Schema cannot express it, as in the hat note), noise layers uncorrelated.
- **Mutants worth the cost:** decay x 1.02, seed ignored, shared noise stream, `mode_ratio` ignored, pitch drop sign flipped, ceiling off by 0.5 dB.
- **Needs the user's ears:** whether the snare and the rim sit next to the existing clap and kick; short listening test in the style of test 3 (sound-designer authors the plan). Nothing needs Live except the existing import path.

## 3. Sub-bass / bass one-shot

### 3.1 Scope

A bass **one-shot** is one note of a given pitch, 100-2000 ms, that the user plays from a sampler (Drum Rack/Simpler) or places by hand. A bass **line** (pattern, notes over time) is not a sample and needs the MIDI/arrangement path that is `unknown` (#140); not in scope here (as in the next-category proposal, rank 4).

### 3.2 How it differs from the kick engine

| Point | Kick engine | Bass one-shot | Consequence |
| --- | --- | --- | --- |
| Pitch | `pitch_start_hz` falls to `pitch_end_hz` (or `tail_note`) | held constant, optional slight glide; `fundamental_hz` is exactly the note | `fundamental_hz` in the sidecar applies and can be asserted to within a cents tolerance (derived; measure) |
| Length | decays to -60 dB by itself; `length_ms` found by a bisection rule | has a **gate**: the note is held for `gate_ms` then released; `length_ms` = gate + release; sound can be stationary | new fields `gate_ms`, `release_ms`; the kick's length rule does not apply; start and end must be click free (B2: slow attack avoids clicks) |
| Timbre over time | amplitude envelope, short click | **filter envelope** (low-pass cutoff moves, B1 "fast filter envelope") | needs a time-varying filter (below) |
| Spectrum | click + sine body | harmonics: saw/square + sine sub; body 40-200 Hz; low-pass about 350 Hz in B1 | oscillators by additive synthesis for a fixed pitch (exact band-limit, as `square_bank`), or polyBLEP for glide |
| Key relation | optional `tail_note` | the **main** control: note name or key | reuse the genre-words note section 4, with a different octave window |
| Phase | irrelevant after the first ms | start phase of each oscillator is audible in the first ms and in layering | contract must fix start phases (artifact creates a new oscillator per note, phase not established, synthesis note 2.2 row "Bass oscillator set") |
| Analysis | pitch tail, click energy | stationarity, harmonic ratios, filter movement | new features (3.4) |

### 3.3 Proposed `bass-params` v0.1

| Field | Type / range (proposal) | Default | Basis |
| --- | --- | --- | --- |
| shared export fields | as clap/kick (`seed`, `variants`, `sample_rate`, `bit_depth`, `drive`, `polarity`, `peak_ceiling_dbfs`, `preset`, `bpm` for `length_beats`) | | |
| `note` | integer MIDI 24 .. 55 (32.7 .. 196 Hz) | 31 (G1, 49.0 Hz) | genre-words table; B1 uses G2 (note 43, 98 Hz), B2 the note F; so one octave range 24-55 covers sub to rolling bass; `note:Am`/`key:8A` input resolves to a note by a bass window (proposal: 31-42, nearest to 55-110 Hz; derived, to be decided with the user) |
| `cents` | -50 .. +50 | 0 | fine tune |
| `osc_mix` | saw, square, sine (sub), as three levels 0..1 | saw 0.7, sine 0.7, square 0 | B1 saw/square, sub layer; artifact oscillator set (B3) |
| `detune_cents` | 0 .. 25 | 0 | two saws detuned (reese is a later model; derived) |
| `sub_octave_level` | 0 .. 1 | 0 | sine one octave below |
| `gate_ms` | 50 .. 1500 | 250 | |
| `release_ms` | 5 .. 400 | 60 | |
| `amp_attack_ms` | 0.5 .. 30 | 3 | B2 slow attack vs B1 audible transient |
| `lp_hz` | 60 .. 4000 | 350 | B1 about 350 Hz |
| `lp_q` | 0.5 .. 6 | 0.9 | B2 "a touch of resonance" |
| `lp_env_amount` | 0 .. 4 (octaves) | 1.5 | B1 fast filter envelope |
| `lp_env_decay_ms` | 5 .. 800 | 120 | |
| `hp_hz` | 20 .. 120 | 40 | B1 high-pass about 65 Hz; a fixed sub-cut protects against DC/inaudible energy |
| `drive` | 0 .. 1 | 0.2 | anti-aliased saturation (kick/artifact tanh) |
| `length_ms` / `length_beats` | derived: gate + release, or explicit | auto | |

Rule from the kick: the best-balanced bass reachable with defaults; presets are data (e.g. `sub_sine`, `rolling_saw`, `rumble_sine_fm` as proposals; the third needs FM, B2, which is a later model).

### 3.4 Measurable features and pitfalls

- `fundamental_hz` (existing field): measured in the stationary part of the gate (long window, not the first 30 ms), compared with `440 * 2^((note - 69)/12) * 2^(cents/1200)`; tolerance set from a measurement.
- New: `harmonic_ratio_2_3` (levels of partials 2 and 3 over the fundamental), `sub_share_100hz` (energy below 100 Hz / total), `centroid_early/late` (filter movement; early above late when `lp_env_amount` > 0), `gate_end_db` (level 5 ms after release vs gate), `t60_ms` after release, `dc_offset`, `peak_dbfs`, `crest_db`.
- **Pitfalls:** (1) `lp_hz` envelope must stay below Nyquist and above 0; clamp rule must be in the contract (reject, not clamp). (2) A time-varying biquad changes coefficients per sample or block; the cost in pure Python is about 1 us/sample in the synthesis note's probe (so 1 s = tens of ms), stability at high Q and low cutoff is a test (artifact stability issue V4 in the synthesis note). (3) Bass and kick occupy the same region; the product-level conflict (B1 sidechain, "leave the first 16th empty") is a mix/pattern problem and not solved by the one-shot. (4) The 45-60 Hz kick taste range and a bass note at 49 Hz overlap; which note the bass should take relative to the kick is a key decision (genre-words note). (5) Small speakers do not reproduce < 50 Hz; a bass consisting only of a sine is inaudible there (derived; therefore `drive`/harmonics matter, B2 uses overdrive).
- **CI can test:** golden hashes, fundamental accuracy for the full note range (random notes), gate/release timing, filter movement direction, aliasing (4x render), no click at start/end (first/last sample, derivative bound), DC, ceiling. **Needs ears:** whether the bass sits with the `dense` kick; **needs the user's machine:** nothing beyond the existing import path.

## 4. Effort and order (small steps)

Same shape as the hat issues H0-H7 (next-category proposal 3.6) and the clap steps C0..C3. Each step is one small issue; WIP = 1 per role. Estimates are classes, not measurements.

| Order | Step | Content | Effort |
| --- | --- | --- | --- |
| 1 | **H0-H7** hats | as in the proposal; shares the scaffold already merged (#239) | medium + small |
| 2 | **S0** snare contract | `contract-change`: `snare` in category enum, `snare-params.schema.json` v0.1, features additions (`body_peak_hz`, `body_noise_ratio_db`, `body_t60_ms`, `noise_t60_ms`) | small |
| | **S1** snare DSP + analysis | body (integrated-phase partials), two-band noise, mix/normalise; band-envelope features; tests as 2.5 | small-medium |
| | **S2** presets + variants + CLI + register in `categories.py` | 3 starter styles (e.g. tight, body, noise-heavy) as data; variant boxes | small |
| | **S3** reference measurement + listening plan | sound-designer, needs user snares | small, user-dependent |
| 3 | **R0** rim contract (or `model` in snare) | decision in 2.4; `rim-params` | small |
| | **R1** rim voice + features | damped sines, optional click, hp; tests | small |
| | **R2** presets, variants, CLI | rim, clave | small |
| 4 | **B0** bass contract | `bass` category, `bass-params` v0.1, note-name input rules, features | small-medium |
| | **B1** time-varying low-pass block | per-block/per-sample RBJ low-pass with cutoff curve; stability and cost test | medium (new block) |
| | **B2** bass voice | oscillators (additive), gate/release, filter envelope, drive; accuracy test of pitch | medium |
| | **B3** note names / key input | `note:`/`key:` resolution shared with the kick vocabulary (one implementation, section 3.3) | small |
| | **B4** presets, variants, CLI, listening plan | | small |

Reasoning (derived): hats first (two timeline elements, no pitch; the proposal's ranking). Snare second because it reuses the clap voice's structure and shared blocks and covers the backbeat alternative to the clap; it is small after the scaffold. Rim third because it is the smallest voice (closed-form) but also the least certain in value: it shares timeline weight with `perc1` and no reference exists; it can be swapped with the snare if the user prefers rim. Bass last: highest weight but needs a new block, gate semantics, note-name input and (for real use) a pattern path that is blocked by #140; building it before hats/snare would not help the arrangement more.

## 5. Open questions (only the user can answer)

1. **Reference snares and rims:** can you supply 3-5 snares and 2-3 rims you like (as you did with 13 claps)? This decides preset-first vs reference-first for S2/S3 and R1.
2. **Snare or clap in the backbeat:** do your Techno/Trance tracks use a snare, a clap, or both layered? The timeline names only `clap` (next-category proposal section 1); a `snare` element would need the planner to learn a new element. Not researched: how common snare is in the genre (no source opened).
3. **Rim: needed at all?** Rim shot as percussion competes with `perc1`; do you want it before bass?
4. **Bass:** one-shot notes you play yourself, or a rendered loop of a pattern later? One-shot is assumed here. And the key window: should a key like 8A map to a bass note in the 55-110 Hz area (G1-A2) or lower (sub only)?
5. **Mono for all three?** Same as the hat question; the current WAV/metadata is mono.

## 6. Implications for the lead

- No decision is contradicted; D-001 and D-005 are respected. Each new category needs a `contract-change` PR (enum + schema) and an `engine_name`/`engine_version` entry in the registry (D-025 pattern in `categories.py`).
- The registry's contract-enum test (`CONTRACT_CATEGORIES`) will force the enum and the registry to be changed in the same PR.
- Tool budget: new `generate_*` tools stay blocked by the 24/24 optional-parameter budget (INTERFACES line 85); a single `generate_sample` with a category enum and a free parameter object is not possible under strict mode without relaxing the budget (inference from the existing note; not re-verified today).
- Decide: rim as own contract (proposed) or a `model` of snare; `snappy` as field or only as vocabulary keyword.
- The kick vocabulary note-name input should become one shared resolver so bass and kick do not diverge (B3).
- Unverified items to resolve before building: the 808/909 snare and rim numbers (S4, S6, S8) are single hobby/vendor sources; Live's octave label for MIDI 60; whether Drum Rack choke applies (hat note). The Roland service manual is named by S4 as the source of oscillator frequencies and decay times; I did not open it.
- Side findings: none opened.

## State update proposal (for the PR body)

"Research note `docs/research/2026-11-02_snare-rim-and-sub-bass-design.md` (Refs #151): sourced circuit facts and a deterministic recipe for snare (`snare-params` v0.1 proposal), rim/clave (separate small contract proposed) and a pitched bass one-shot (`bass-params` v0.1 proposal, with the differences from the kick engine), measurable features, test strategy, and order hats, snare, rim, bass in small steps S0-S3, R0-R2, B0-B4. Five user questions open. Nothing implemented, run in Live or listened to."

**Correction (2026-11-02):** S1 was titled "TR-909 snare (named 180 Hz and 330 Hz)". After re-opening the SOS article that day, 180 Hz and 330 Hz are the article author's own modular-model settings, not TR-909 values; the article gives no 808/909 frequencies, filter cutoffs or decay times. S1 and the sentences that relied on it (ratio list, `body_hz`, `mode_ratio`, S4 caveat) were reworded; the numbers are unchanged. The 909 structure claims (separate envelopes per partial, two-band noise) rest on the author's description only.
