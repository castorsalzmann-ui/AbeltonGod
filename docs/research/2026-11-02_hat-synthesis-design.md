# Research: hat synthesis design (closed, open, shaker, ride) for a `hat-params` v0.1

- **Date:** 2026-11-02. Researcher role. Docs-only PR, `Refs #151`.
- **Question (lead, user order: clap first, then hats):** deterministic DSP recipes for closed/open hats and shakers/rides in Techno/Trance, a proposed parameter list for a `hat-params` v0.1 contract, and measurable analysis features. This is pre-work for H0-H7.
- **Read before writing (2026-11-02, `origin/main`):** `CLAUDE.md`, [next-category proposal](2026-11-02_next-category-proposal.md) (H0-H7 split, parameter table in its 3.2, acceptance criteria in 3.4), [bandit-wheel synthesis transfer](2026-10-29_bandit-wheel-synthesis-transfer.md) (section 3: artifact hat/ride/shaker recipes with line numbers, sections 1 and 6), [kick-gen2 learnings](2026-10-28_kick-gen2-learnings.md) (rules), and the existence of the kick vocabulary notes.
- **Not repeated here:** the artifact's recipe constants, the reuse table of `src/audio_engine/`, the issue split H0-H7 and the generic acceptance criteria. They stay in the two notes above. This note adds outside sources, the choke and envelope model, ride/shaker design, a concrete field list and the analysis feature definitions.
- **Not done:** nothing was rendered or listened to. No sound claim is made. No code, no contract change.

## For workers

- **Possible?** Yes, with numpy only: band-limited square bank (additive) + seeded noise + RBJ filters + envelopes. No new dependency, no Max for Live (D-001), no generative model (D-005).
- **Route:** one `hat` engine with a `model` field. Closed and open are one voice differing in `decay_ms` and choke; shaker and ride are further `model` values (same blocks, other constants). Do not build a separate contract per sub-type.
- **Read first:** this note sections 1, 3, 4; synthesis note section 3; next-category proposal 3.2-3.6.
- **Key new facts (all with sources below):** (1) The 808 oscillator frequencies in the artifact (205.3, 304.4, 369.6, 522.7, 540, 800 Hz) are confirmed independently by a peer-reviewed circuit analysis; the oscillators are ~48 % duty cycle squares, so a fixed 50 % duty square bank is a simplification. (2) The 808 filters are two band-passes near 3.4 and 7.1 kHz plus Sallen-Key high-passes with a resonance near 10.5 kHz. (3) Choke is documented as: closed hat triggered while open hat rings cuts the open tail; both triggered together gives the closed (short) envelope. (4) The 909 hats are 6-bit samples with analog envelope/filter, so a "909 hat" is not an oscillator bank; our square-bank recipe is the 808 route.
- **Effort class:** the hat voice itself small (given H1-H3); my parameter list adds `model` (4 values) which pushes H4 to small-medium.
- **Blockers:** same as the proposal (H0 contract change first; tool budget 24/24). New: no authoritative numeric spectral target for Techno/Trance hats was found (section 5); targets in this note are derived proposals, to be set by measuring user-supplied reference hats.
- **Open questions only the user can answer:** (a) Q4 from the proposal still stands: can he supply 3-5 hats he likes as references; (b) should the first release include shaker and ride, or only closed/open; (c) is mono acceptable for hats (the 808/909 are mono; Web Audio artifact is mono).

## 1. Findings

| # | Finding | Confidence | Source (opened 2026-11-02) |
| --- | --- | --- | --- |
| F1 | TR-808 cymbal, open hat, closed hat and cowbell share one bank of six Schmitt-trigger square oscillators (HD14584 hex inverter). Nominal frequencies 205.3, 369.6, 304.4, 522.7 Hz; two more are trimmed to 800 and 540 Hz. Each has duty cycle 47.98 %, amplitude 5 V (at 5 V supply). | high (peer-reviewed circuit analysis) | Werner, Abel, Smith, "The TR-808 Cymbal: a Physically-Informed, Circuit-Bendable, Digital Model", ICMC/SMC 2014: [PDF](https://speech.di.uoa.gr/ICMC-SMC-2014/images/VOL_2/1453.pdf), title/venue from [CCRMA page](https://ccrma405080.stanford.edu/papers/tr-808-cymbal-physically-informed-circuit-bendable-digital-model) |
| F2 | The 808 cymbal path has two active band-passes (centres near 3,440 and 7,100 Hz) that emphasise upper overtones, three Sallen-Key high-passes (resonance near 10.5 kHz), a passive fifth-order tone network and an output stage with +6 dB/oct slope in the audio band. Attack smoother time constant about 0.1 ms; trigger pulse 1 ms. | high for the paper's description; medium for transfer to hats (the paper models the cymbal, and hats share the oscillators) | same PDF |
| F3 | The paper gives three envelope generators with decay set by RC; no decay times in seconds. | high (absence) | same PDF |
| F4 | A commercial 808-hat model describes: six squares at irregular intervals, typical span about 200-800 Hz "not critical", steep high-pass, a split into a higher-pitched start and a lower-pitched body with separate envelopes, the high partial decaying faster; choke on = closed hat cuts the open hat's decay. | medium (vendor documentation) | [Cherry Audio Transistor 808 Hats](https://docs.cherryaudio.com/misfit-audio/transistor-808-hats) |
| F5 | Choke in a hardware module: closed hat triggered during the open hat's decay cuts the open tail; both triggered at the same time gives the closed hat's short envelope on both outputs; a switch can disable choke so the open hat always rings out. | medium (manufacturer description of a modular clone) | [Tiptop HATS808 description](https://kraftmusic.com/products/tiptop-audio-hats808-analog-hi-hats-drum-module) |
| F6 | The 909 hats are 6-bit samples with analog envelope (separate closed and open decay) and filtering; tuning changes sample playback. So a 909-style hat is a sampled/filtered noise source, not a square bank. | medium (module vendor description of the original circuit) | [Tiptop HATS909 description](https://kraftmusic.com/products/tiptop-audio-hats909-hi-hats-drum-module); the SOS article says the 909 cymbals are ROM samples clocked by a 30 kHz oscillator: [Reid, "Practical Cymbal Synthesis", SOS July 2002](https://www.soundonsound.com/node/4918183) (high for that statement) |
| F7 | A closed-hat pattern with every step triggered plus an accent pattern is described as a signature of both 808 and 909 closed hats in dance music. This is a pattern fact, not a sample fact. | medium (vendor text) | Tiptop HATS808 description above |
| F8 | Reid's attempt to make cymbals from filtered noise on a Korg MS20 is reported by the author as not sounding like a real cymbal; his best method uses several detuned, frequency-modulated square pairs. | medium (article text; figures not readable via the fetch tool) | SOS article above |
| F9 | A software tutorial recipe: six squares through three high-passes with slightly different envelopes; highest oscillator gets the shortest decay so upper partials die first; add noise blend by macro; small random decay per trigger for variation. | medium (tutorial, Massive-specific) | [Mode Audio, Massive Drum Design part 3](https://modeaudio.com/magazine/massive-drum-design-part-3-hi-hats) |
| F10 | A modular-synth blog builds hats from band-passed white noise instead of squares (BP near 2 kHz, high resonance, two envelopes). | low-medium (anecdotal, "around 2 kHz" from memory per the text) | [Noise Engineering](https://noiseengineering.us/blogs/loquelic-literitas-the-blog/hats-off-to-this-series-synthesizing-hats-in-the-final-percussion-synthesis-post/) |
| F11 | Bitwig's hat devices expose: decay, tune, noise level, a "consistent sound" toggle (v8, 808-inspired) and "sound variation" per note (v9, 909-inspired); closed and open are separate devices. | medium (manual) | [Bitwig user guide, hi-hat](https://www.bitwig.com/userguide/latest/hi-hat) |
| F12 | Oscillator frequency tolerances on real 808 units vary: oscillators have no temperature compensation and drift between machines (module doc) and the paper lists ranges for the two trimmed oscillators. | medium | Tiptop HATS808 description; paper PDF |

Cross-check with the repo: the artifact's six frequencies (synthesis note 3.1) equal F1 for four oscillators and the two trimmed values (800, 540). So the artifact's choice is traceable to the 808 circuit, not to a taste choice. The artifact's HP corner (5.0-9.5 kHz) and peaking (8.5-9.5 kHz) are not found in F2; they are the artifact's own choices.

## 2. Recipes (all deterministic, fixed sample rate 48 kHz, mono, float64 then quantise)

Notation: `sq(f)` = band-limited square from odd harmonics below `0.45*sr` (the kick click rule). Constants marked "A" are the artifact's (synthesis note 3.1), "C" are from the circuit paper, "P" are proposals for the engineer to measure.

### 2.1 Metallic bank (model `metal_bank`, default for closed/open)

1. `bank = sum_i g_i * sq(f_i * pitch_scale)` with `f = [205.3, 304.4, 369.6, 522.7, 540, 800]` (C). Start phases fixed to 0 (contract must say so). Equal `g_i` (A) or two groups (low three, high three) with `color` crossfade (F4).
2. Noise `n` from `SeedSequence([seed, layer_id])` white noise.
3. Mix: `x = metal*bank_norm + (1-metal)*n_norm` where both parts are RMS-normalised before mixing, so `metal` means a power share and is independent of the number of harmonics (the proposal's definition).
4. Optional two-band split (F2, F4): `x_hi = BP(x, ~7.1 kHz)`, `x_lo = BP(x, ~3.4 kHz)` (C), separate exponential envelopes with `decay_hi < decay_lo`, summed by `body_mix`.
5. High-pass: RBJ 2nd order at `hp_hz` (P: 3000-10000). F2 shows a steeper, resonant Sallen-Key high-pass; 4th order = two cascaded RBJ sections is the proposal for "steep" (F4).
6. Optional peaking boost (`peak_hz`, `peak_db`) and low-pass `lp_hz` (A).
7. Envelope (section 3), `_fade_out` 5 ms (existing kick helper), DC removal, normalise to `peak_ceiling_dbfs`.

Aliasing note (derived, not measured): at 48 kHz the highest square (800 Hz * `pitch_scale` 1.0) has odd harmonics up to the 29th (23.2 kHz); at `pitch_scale` 1.5 the fundamental is 1.2 kHz and the cap by `0.45*sr` removes everything above 21.6 kHz. Additive synthesis has no aliasing by construction, which is the reason to prefer it over naive squares.

### 2.2 Noise hat (model `noise_hat`)

Seeded white noise -> high-pass (steep) -> optional BP resonance (F10 reports 2 kHz in a modular patch; for a sample-based chain a corner near the HP corner is more usable: P) -> envelope. This is the `metal = 0` end of 2.1; keep it as a regime of the same model, not a separate model. F8 reports a noise-only cymbal as unconvincing for long cymbal-like decays; for short hats this is a listening question, not a given.

### 2.3 Shaker (model `shaker`)

Artifact (A): seeded noise, BP `4500 + 55*tone` Hz (Q 1.5), HP 3 kHz, 12 ms linear attack, duration 40-200 ms. The slow attack (rise 12 ms vs hat 0.8 ms) is what separates it from a hat in the analysis (rise time feature, section 5). Proposed fields: `bp_hz` (P: 3000-9000), `bp_q` (P: 0.7-3), `attack_ms` (P: 2-25), `decay_ms` (P: 40-300). No source outside the artifact was found for shaker synthesis; flagged as unverified beyond the artifact.

### 2.4 Ride / ping (model `ride`)

Artifact (A): the same six squares at higher ratio (2.2 + tone/100), BP 7.5 kHz Q 0.6 and HP 5 kHz on the squares, plus a noise tick (HP 7 kHz, peak 0.35, 0.6 ms attack, 50 ms decay); square envelope 1 ms attack, decay 250-360 ms. Reid reports good cymbals needed FM pairs (F8), so a bank-only ride is likely the weakest of the four models; offer it only if the user wants it (open question b). Optional FM pair as `fm_index` is a P and is not in any current note's measurements.

## 3. Envelope shapes and choke

| Item | Proposal | Basis |
| --- | --- | --- |
| Attack | linear, `attack_ms` P 0.2-3 for hats (A 0.8 ms; the circuit smoother has about 0.1 ms, F2) | A, F2 |
| Decay | exponential to -60 dB at `decay_ms`, same definition as kick `amp_decay_ms` | next-category proposal 3.2 |
| Closed range | `decay_ms` P 15-150 ms (A 15-135) | A |
| Open range | `decay_ms` P 120-900 ms (A 120-620) | A; upper bound is a proposal |
| Two-band body split | `decay_hi_ratio` P 0.3-1.0 of the low decay (high partials die first) | F4, F9 |
| Fade | 5 ms linear at the end of the file (existing helper, not the artifact's 256-sample) | synthesis note 3.2 |

**Choke in a one-shot world.** A one-shot has no second trigger, so choke has two meanings, only the first belongs in v0.1:

1. `choke_ms` (optional, P 0 = off, 5-500): the render is cut by a 5 ms fade at `choke_ms` after the start. This simulates "closed hat arrives at time t and cuts the open hat" and gives the user an open hat that stops at a chosen point. It is a render parameter, deterministic, and testable (energy after `choke_ms + 5 ms` is below a threshold).
2. Real mutual choke between samples is a Drum Rack function in Live (Choke Group on the pad). I did not verify the Live 12 Standard Drum Rack choke feature in this pass: unverified here; the bridge-engineer or a later note should check the Live manual before any claim. A pattern/trigger-level choke belongs with patterns (synthesis note 3.2), not to the sample engine.

## 4. Proposed `hat-params` v0.1 field list (ranges are proposals; the audio-engineer measures them)

Names reuse kick names where the meaning is equal (next-category proposal 3.2). All ranges are closed intervals and out-of-range is rejected, not clamped (contract rule).

| Field | Type / range (proposal) | Default (proposal) | Notes |
| --- | --- | --- | --- |
| `model` | enum `metal_bank`, `shaker`, `ride` | `metal_bank` | `noise_hat` is `metal_bank` with `metal = 0` |
| `decay_ms` | 10 .. 900 | 60 | time to -60 dB; closed vs open is this field (no boolean) |
| `attack_ms` | 0.1 .. 25 | 0.8 | shaker uses the upper range |
| `metal` | 0 .. 1 | 0.6 | power share of bank vs noise |
| `pitch_scale` | 0.5 .. 2.0 | 1.0 | multiplier of the six fixed frequencies |
| `color` | 0 .. 1 | 0.5 | crossfade low three / high three oscillators (F4) |
| `hp_hz` | 2000 .. 12000 | 6000 | steep high-pass (2 cascaded RBJ sections) |
| `lp_hz` | 8000 .. 22000 | 18000 | must be above `hp_hz` * 1.2 (cross-field rule, state in schema description; JSON Schema cannot express it, so the engine rejects with an error text) |
| `bp_hz`, `bp_q` | 1500 .. 12000, 0.4 .. 4 | 7100, 0.7 | band-pass emphasis (C: 3.4 and 7.1 kHz); `bp_mix` 0..1 = how much BP path is used |
| `peak_hz`, `peak_db` | 5000 .. 14000, -6 .. +9 | 9000, 0 | static peaking |
| `body_mix` | 0 .. 1 | 0.4 | share of the slower low partial group |
| `decay_hi_ratio` | 0.2 .. 1.0 | 0.5 | high-group decay relative to `decay_ms` |
| `drive` | 0 .. 1 | 0 | anti-aliased saturation, as kick |
| `choke_ms` | 0 (off) or 5 .. 900 | 0 | section 3 |
| `length_ms` / `length_beats` + `bpm` | as kick | auto | file length >= decay to -60 dB + fade; the kick bisection rule is not needed |
| `seed`, `offset_ms`, `polarity`, `sample_rate`, `bit_depth`, `peak_ceiling_dbfs` | as kick | as kick | |

Variant axes (for H5 and the later vocabulary note): `pitch_scale`, `hp_hz`, `metal`, `decay_ms`, `color`. Rule from kick-gen2 and test 3: do not pick ranges narrow enough that every output shares one character; `metal` 0 vs 1 and `model` give structurally different families.

Fields deliberately left out: stereo width (contract is mono, synthesis note V9), per-oscillator frequencies (the 808 ratios are the identity of the bank; a free list would need a validation story), velocity (no pattern layer).

## 5. Measurable analysis features (non-pitched; for H2)

Windows: STFT with n_fft 2048 (46.9 Hz bins at 48 kHz) for spectral features; 1 ms-hop envelope for time features. Short transients need the finer onset resolution already required by kick-gen2 M3.

| Feature | Definition | Which parameter it must move | Expected direction (test written independently) |
| --- | --- | --- | --- |
| `t60_ms` | time of the envelope to -60 dB below peak (existing `t60_seconds` measure) | `decay_ms` | monotone, within the kick length tolerance |
| `rise_ms` | time from 10 % to 90 % of the peak amplitude | `attack_ms` | monotone |
| `centroid_hz` | power-weighted mean frequency of the first 50 ms | `pitch_scale`, `hp_hz`, `peak_db` | up with all three |
| `hf_share` | energy above 8 kHz / total energy | `hp_hz`, `lp_hz`, `peak_hz` | up with `hp_hz` while `lp_hz` is above 8 kHz |
| `lf_leak_db` | energy below `hp_hz` relative to the passband (dB) | `hp_hz` | at most a bound the engineer measures (the high-pass does not reach infinite attenuation) |
| `flatness` | geometric / arithmetic mean of the power spectrum in 4-20 kHz | `metal` | the spectrum of a square bank is a sparse line spectrum, noise is flat, so flatness rises as `metal` falls |
| `peak_count` | spectral peaks 15 dB above the local median in 4-20 kHz | `metal`, `pitch_scale` | falls with `metal` -> 0; with `pitch_scale` the peak positions shift by the ratio |
| `early_late_centroid_ratio` | centroid of 0-20 ms over centroid of the last 40 % of the T60 | `decay_hi_ratio`, `body_mix` | above 1 when the high group decays faster |
| `energy_after_choke_db` | RMS after `choke_ms + 5 ms` vs peak | `choke_ms` | below -60 dB when `choke_ms` is set |
| `dc_offset`, `peak_dbfs`, `true-peak` | as kick | | |

**Spectral targets for Techno/Trance hats.** I searched for a published numeric target (centroid, HF share, loudness relative to kick) and found none: the only numbers are the artifact's loop level (hats about -10 LU vs kick loop, no published standard; proposal note section 1) and the circuit values in F1-F2. So the targets below are derived and unverified, to be replaced by measurements of the user's reference hats (open question a):

- A hat should have little energy below `hp_hz`: derived from the recipes (HP 5-9.5 kHz in A; steep high-pass in F4).
- Closed hat T60 below about 150 ms, open hat 120 ms or more: from A's ranges, not from a source on Techno.
- Everything else (centroid target, HF share) is open until reference hats exist. The analysis can report them; it must not pass or fail on them.

## 6. Pitfalls

1. **Seed collisions.** Closed (`seed+1`) and open (`seed+99`) in the artifact share noise streams across seeds; use `SeedSequence([seed, layer_id])` with a defined `layer_id` per layer (synthesis note 1.1).
2. **Bank normalisation.** A sum of six squares has a different RMS from noise; without per-part RMS normalisation `metal` is not a stable power share, and the `flatness` test would pass for the wrong reason.
3. **Duty cycle.** Real oscillators have 47.98 % duty (F1), which adds even harmonics; fixed 50 % is a deliberate simplification. If the audio-engineer wants the circuit-faithful spectrum, it needs a duty-cycle field or a fixed constant stated in the contract. Not measured.
4. **High-pass order.** A 2nd-order RBJ high-pass leaves more low-frequency leakage than F2's multi-stage chain; the `lf_leak_db` test bound depends on the order chosen.
5. **Choke is not mutual.** A one-shot cannot cut another sample (section 3).
6. **Analysis window length.** A closed hat of 15 ms is shorter than one 2048-sample window (42.7 ms); use a window shorter than the sample or pad, otherwise features average silence.
7. **"909 sound".** F6: the 909 hat is a sampled source; a square bank is not a replica, and the repo must not label a preset "909".

## 7. Test strategy hints

- **CI can test:** determinism (golden hashes, byte-identical re-render), each parameter moves its feature in section 5 (seeded random draws), alias residual vs an independent 4x render, ceiling on the quantised file, no DC, schema negative cases (incl. `lp_hz` vs `hp_hz`), choke energy, noise streams uncorrelated between layers (cross-correlation near 0).
- **Needs the user's ears:** whether `metal` families are distinct, closed/open length, whether the top end is acceptable with the kick (listening plan in the proposal 3.5; the sound-designer writes it). Needs the user's machine: nothing from Live except the existing import path.
- **Mutants worth the cost (main checks only):** decay x 1.02, seed ignored, shared noise stream, high-pass corner shifted, harmonics not cut at the cap, peak ceiling off by 0.5 dB, `metal` mixing without RMS normalisation.

## 8. Open questions (user)

1. Reference hats (3-5 files or names) to set spectral targets and a taste range (proposal Q4).
2. Shaker and ride in v0.1, or closed/open only?
3. Mono acceptable?
4. Is a pattern-level hat loop (offbeat / 16th) wanted soon? The sample engine does not produce it.

## 9. Implications for the lead

- **H0 contract:** add `model` as an enum from the start (cheaper than a v0.2 change); keep `decay_ms` continuous with no `open` boolean.
- **H2 analysis:** the feature set in section 5 is enough to check every field in section 4; `fundamental_hz` stays optional.
- **Order with clap:** the clap shares band-passed noise, RMS-normalised layers and `SeedSequence` streams with the hat; building H1 (DSP blocks) once serves both. If clap goes first, H1 and H3 are done by the clap issue and the hat then only needs the bank and the field list.
- **Unverified items to resolve before they become claims:** Live 12 Standard Drum Rack choke behaviour (section 3); the 909 hat sample details beyond F6; any Techno/Trance numeric spectral target.
- **State update proposal:** `docs/ROADMAP.md` row "Weitere Sample-Kategorien" can list this note; `CURRENT_STATE` "next" can reference it under the hat issues (lead decides).
