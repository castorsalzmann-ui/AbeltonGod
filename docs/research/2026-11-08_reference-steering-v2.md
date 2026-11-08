# Reference steering v2: features per category, parameter fit, folder import (#522, #58)

- **Date:** 2026-11-08
- **Receiving issues:** #522 (reference steering v2, "first step"), parent #58
- **Author role:** sound-designer
- **Status:** design note with three feasibility experiments run in a scratchpad outside the repo (section 5). **No listening claims.** Every number below describes signals rendered by our own engines. Whether any fit "sounds like" a reference is decided by the user's ears only (D-032: "no synthesis that claims to match a reference").
- **Extends, does not repeat:** [kick layering and reference steering](2026-11-02_kick-layering-and-reference-steering.md) (staged-fit experiment 6.3, risks section 7, licence finding 11), [kick-gen2 learnings](2026-10-28_kick-gen2-learnings.md) (section 4 pitfalls, section 2 method), the per-category target notes ([hat](2026-11-02_hat-targets-and-listening-plan.md), [snare](2026-11-02_snare-targets.md), [rim](2026-11-02_rim-targets.md), [bass](2026-11-02_bass-targets.md), [clap references](2026-11-02_clap-reference-analysis.md), [toms/percs](2026-11-02_toms-percs-and-sidechain-feasibility.md), [fx transitions](2026-11-07_fx-transitions.md)). Their quantity lists (Q1-Q11, R1-R8 etc.) are the source of the per-category features below; this note decides which of them a *fit* uses and how they are weighted.
- **Versions:** repo `origin/main` at branch time (2026-11-08), Python 3.14 / NumPy 2.5.3 in the scratchpad (Linux, 2 cores). SciPy 1.18.1 is installed in the scratchpad but **not used** by any experiment here and is not a repo dependency (`pyproject.toml` has no `scipy`).

## For workers

- **Possible?** Yes, NumPy-only and deterministic, for all nine categories. But the experiments in section 5 show two limits that shape the design: (1) the measured features are **many-to-one**: a fit can bring the feature distance close to 0 while several parameters stay far from the true ones (hat `pitch_scale` off by +39 to +74 % at feature distance 0.25-0.77); (2) in one full-range draw, the search from the nearest preset did not reach 5 very short kick references (`amp_decay_ms` 21-43 ms): their distance stayed at 3.15-3.50 after 300 renders. That is a single draw and the cause is not established, so no general claim about references far from presets follows from it.
- **Design:** per category, a short list of *explained features* (shown to the user, one row each) plus a *spectro-temporal profile* (fit objective only, never shown as a claim). Fit = stage 0 discrete choices by candidates, stage 1 analytic estimates for directly measurable parameters, stage 2 deterministic bounded coordinate search in a normalised parameter space. No random numbers in the fit; a fixed fit seed; budget in renders **and** seconds; every report names the parameters the measures do not determine.
- **Main honest check:** synthetic references rendered by our own engines with known parameters, recovered within per-parameter tolerances that are **tiered** (asserted for identifiable parameters, reported only for the rest). This is an "inverse crime" (the model contains the target) and therefore an upper bound for real references.
- **Folder import:** category guess by nearest centroid on 10 features was right for 77.7 % of 528 engine renders (top-2: 86.2 %), leave-one-preset-out; `perc` only 19 of 72. So the GUI shows the top-2 guess, marks small margins as "unsicher", and the user can always override.
- **Read first:** sections 2, 3 (your category), 4, 7. Then section 10 for the issue split.

## 1. What exists today (read in `src/audio_engine/`, `src/gui_core/`)

| Need | Present | Gap for v2 |
| --- | --- | --- |
| Reading a user WAV | `reference.read_reference_wav`: RIFF PCM 16/24 bit (incl. EXTENSIBLE), mono/stereo (stereo -> mean), 44.1/48 kHz, 50 ms ... 3 s, 64 MB | 32-bit float and 96 kHz are rejected; 3 s is too short for laser (contract up to 6000 ms) and fx (up to 72 000 ms, rule A); stereo is reduced to mono before any width could be measured; no multi-hit split (loops are rejected only by length) |
| Kick measures | `reference.measure`: `fundamental_hz`, `body_hz` (zero crossings 10-70 ms on a 400 Hz low-pass), `decay_20db_ms`, `decay_40db_ms`, `sub_share` (< 100 Hz), `click_share` (> 1 kHz in first 10 ms); onset at 10 % of peak, DC removed, peak-normalised | no pitch curve at several times, no tail harmonics, no body-zone energy; start pitch is "not established" (kick-gen2 section 2) |
| Distance | `reference.distances`: semitones / log ratio / linear share divided by a scale; one-sided `None` counts 3; total = RMS over measures | scales are set by hand (1 semitone, 25 % time, 5 points share); no per-category table, no weights |
| Non-pitched features | `analysis.analyse_nonpitched`: `spectral_centroid_hz`, `hf_share_8k`, `t60_ms` (30 Hz HP, first crossing), `rise_time_ms`; helpers `welch_flatness`, `lf_leak_db`, `hf_share`, `peak_count`, `t60_line_fit_ms`, `early_late_centroid_ratio`, `spectral_flatness` | not measured from the onset (the reference must be cut at the onset first); `rise_time_ms` unusable on multi-burst claps (clap reference note P1) |
| Category features | bass: `fundamental_hz` in the stationary window needs the *resolved* params (`analyse_bass(audio, sr, p)`): cannot run on a reference without a gate estimate. laser/fx: `analyse_laser` = non-pitched features on the mid signal | no stereo-width feature, no pitch-track for laser sweeps, no fx level-curve feature |
| Loudness | `loudness.py`: BS.1770-4 momentary / short-term / integrated in NumPy | integrated is `-inf` below 400 ms (one block), so for one-shots only a level match on longer files (fx, long laser) is possible; not a feature for short drums |
| Candidates | kick only: 6 presets x 8 variants, cached per process | presets exist for every category (counted: clap 11, hat 5, snare 5, rim 5, bass 8, laser 14, perc 9, fx 8, kick 6), variant modules `*_variants.make_variants` exist for all |
| GUI | `gui_core/reference.py`: one kick WAV, table of six rows, "Als Startwerte übernehmen" into the kick form | one category, one file, no fit |

Render cost (measured, one render per preset, section 5.1): median 0.001-0.041 s for kick, hat, snare, clap, rim, perc and bass; laser median 0.33 s (max 0.83 s); fx median 1.38 s, max 10.8 s (riser 32 bars, 58.7 s of audio). The fit budget therefore has to be per category and in seconds, not only in renders.

## 2. Shared rules for every category

1. **Preprocessing (same for reference and candidate):** stereo -> mid `(L+R)/2` for all mono features; side/mid energy ratio as an *extra* feature only for laser and fx (their engines render stereo); DC removed; cut at the onset (first sample at 10 % of the peak, kick-gen2 pitfall 2); peak-normalised. A file whose level never falls far enough gives `None`, never a guess (pitfall 5).
2. **Transform per feature type:** frequencies in semitones (`12 log2 f`), times as natural log, shares and flatness linear, ratios (early/late centroid, partial level ratio) in dB. This is the existing `reference.MEASURES` convention, extended.
3. **Scale = the smallest difference the measurement can resolve on our own renders, never a taste weight.** Proposal: scale_f = max(method error_f, seed spread_f), both measured once per category on engine renders: method error = deviation of the feature from its known value on synthetic signals (e.g. `fundamental_hz` +-5 % on short kicks, analysis.py docstring); seed spread = max - min of the feature over seeds 1-8 at fixed parameters (hat note H12 gives centroid +-4 %, HF share +-3 %, t60 +-10 % as the variant box). Until that calibration exists (issue E3) the provisional scales in section 3 are used and marked "provisional".
4. **Weights:** all explained features weight 1 after scaling. Reason: the scale already encodes "one unit = one resolvable step"; any further weighting would encode which difference *matters to the ear*, which is a listening claim. Two exceptions, both measurable: (a) a feature gets weight 0 for the fit when its seed spread (max - min over seeds 1-8 at fixed parameters, mean over the candidates) is at least one third of its between-candidate spread (max - min of the per-candidate seed means over the candidate set), both in the transformed units of rule 2. This ratio does not use the scale, so it can trigger even though scale = max(method error, seed spread). Such a feature mostly measures the noise realisation, not the parameters. It stays visible in the table; (b) the profile (rule 6) counts as one feature in the total.
5. **Missing values:** one side `None` = 3 units (as today); both `None` = 0. A censored reference (the file ends before the threshold) keeps `None`, and the report says "nicht messbar".
6. **Spectro-temporal profile (fit objective only):** band energies in 12 log-spaced bands from 30 Hz to 16 kHz in 6 time zones counted from the onset (category-specific zone edges, kick: 0-5, 5-15, 15-40, 40-100, 100-250, 250-450 ms), dB relative to the largest cell, floored at -60 dB; distance = RMS cell difference / 3 dB. Rectangular windows inside each zone (pitfall 1). Why: section 5.3 shows that the explained features alone leave parameters undetermined; the profile adds time-frequency shape without needing the reference's phase or noise realisation (same reason as the DDSP magnitude loss, prior note finding 8). It is **not** shown to the user as "Ähnlichkeit".
7. **Fit seed:** the reference's noise is an unknown realisation. The seed is never fitted; the fit uses the seed of the start candidate and reports it. The click/noise parts are matched by magnitude and envelope only (prior note 6.3 (c)).

## 3. Features per category

Columns: feature · how measured (existing function, or **missing**) · transform / provisional scale · parameters it mainly depends on (the search set). "Main parameters" come from the contracts and the target notes; they are the parameters stage 2 searches. Parameters not listed are held at the start candidate's value.

### 3.1 Kick (`kick-params` 0.2/0.3)

| Feature | Measured by | Transform / scale | Main parameters |
| --- | --- | --- | --- |
| Tail fundamental | `reference.measure` -> `analysis.analyse` | semitone / 1 | `pitch_end_hz` (or `tail_note`) |
| Body pitch 10-70 ms | `reference.measure` `body_hz` | semitone / 2 | `pitch_start_hz`, `pitch_decay_ms` |
| Pitch at 5, 10, 20, 40 ms | **missing**: instantaneous frequency (Hilbert via NumPy FFT) on a 700 Hz low-pass, as kick-gen2 section 2; values before 5 ms excluded (start pitch not established) | semitone / 1 | `pitch_start_hz`, `pitch_decay_ms` |
| Decay to -20 / -40 dB | `reference.measure` | log / ln 1.25 | `amp_decay_ms`, `drive` (drive lengthens the measured decay, analysis.py docstring) |
| Sub share < 100 Hz | `reference.measure` | lin / 0.05 | `pitch_end_hz`, `pitch_decay_ms`, `tone` |
| Click share > 1 kHz, 0-10 ms | `reference.measure` | lin / 0.05 | `click_level`, `click_tone_hz`, `click_decay_ms`, `click_q` |
| Tail harmonics 2-8 / fundamental | **missing** (re-implemented outside the repo in the #58 comment) | dB / 3 | `drive`, `clip_db` |
| Body-zone energy 80-300 Hz, 5-80 ms (dB re total) | **missing** | dB / 1.5 | `drive`, `pitch_decay_ms` |

Constraints during the fit: every trial goes through `resolve_kick_params`; `pitch_decay_ms` is kept at or below `params.max_settled_pitch_decay_ms` unless the start candidate itself is above it (then the report says so); `length_ms` is taken from the reference length clipped to the contract (80-2000 ms) and not fitted. Known weak cases from the prior note: fast pitch drops (true `pitch_decay_ms` 6.5 ms gave -25 % start pitch) and heavy drive.

### 3.2 Hat (`hat-params` 0.1)

| Feature | Measured by | Transform / scale | Main parameters |
| --- | --- | --- | --- |
| Spectral centroid | `analyse_nonpitched` | semitone / 1 (hat H12 +-4 % = 0.7 st) | `hp_hz`, `lp_hz`, `color`, `peak_hz`/`peak_db` |
| HF share > 8 kHz | `analyse_nonpitched` | lin / 0.03 | `hp_hz`, `color`, `lp_hz` |
| T60 (line fit) | `analysis.t60_line_fit_ms` (first-crossing `t60_ms` undershoots by up to 9 %, hat P3) | log / ln 1.1 | `decay_ms`, `decay_hi_ratio` |
| Flatness 8-16 kHz (Welch) | `analysis.welch_flatness` | lin / 0.05 | `metal` |
| Line count 4-20 kHz | `analysis.peak_count` (compare at equal decay only, hat P8) | log1p / 0.3 | `metal`, `pitch_scale`, `decay_ms` |
| Early/late centroid | `analysis.early_late_centroid_ratio` | dB / 1 | `body_mix`, `decay_hi_ratio` |
| Rise time | `rise_time_ms` | **weight 0** below 3 ms attack (not seed-stable, hat H4); shown only | `attack_ms` |

Discrete: `model` (`metal_bank` / `noise`) in stage 0. Section 5.3: `pitch_scale` and `metal` are not separated by centroid/HF/T60/flatness/early-late plus the profile (pitch_scale +39 to +74 % off in 5 of 6 near-preset fits); `peak_count` and the predicted line set of hat H8 are the measures that can separate them, so they are part of the list.

### 3.3 Snare (`snare-params` 0.1)

| Feature | Measured by | Transform / scale | Main parameters |
| --- | --- | --- | --- |
| Body pitch at 40 ms after drop | **missing** (snare Q1: peak 100-500 Hz) | semitone / 0.5 | `body_hz` |
| Pitch drop 5 ms vs 40 ms | **missing** (Q2) | semitone / 1 | `pitch_drop`, `pitch_drop_ms` |
| Partial ratio | **missing** (Q3: two strongest peaks 100-800 Hz; snare P2: noise can win) | semitone / 0.5 | `mode_ratio` |
| Body/noise balance, 0-80 ms | **missing** (Q4: 100-500 Hz vs 2-12 kHz, rectangular) | dB / 1.5 | `body_level` |
| Noise band corners (-6 dB) | **missing** (Q5) | semitone / 2 | `noise_hp_hz`, `noise_lp_hz`, `noise_band_mix` |
| Body decay / noise decay | **missing** (Q6, Q7: band RMS envelopes) | log / ln 1.15 | `body_decay_ms`, `body2_decay_ratio`, `noise_decay_ms` |
| Centroid, HF share, T60 | `analyse_nonpitched` (`t60_ms` with 30 Hz HP, #313) | as hat | `noise_hp_hz`, `noise_lp_hz`, `noise_decay_ms` |
| Noise attack | **missing** (Q8: high band, 0.25-1 ms window; not `rise_time_ms`) | log / ln 1.5 | `noise_attack_ms` |

### 3.4 Clap (`clap-params` 0.1/0.2)

| Feature | Measured by | Transform / scale | Main parameters |
| --- | --- | --- | --- |
| Burst count and first spacing | **missing**: peaks of a 1 ms RMS envelope in the first 60 ms (clap references: count is noise-sensitive, first spacing 8-12 ms is stable) | spacing log / ln 1.15; count weight 0 (shown) | `bursts`, `burst_spacing_ms` |
| Energy share first 30 ms | **missing** (clap P3: 0.18-0.97 across references) | lin / 0.05 | `burst_decay_ms`, `burst_level_falloff`, `tail_level` |
| T60 / -40 dB time | `analyse_nonpitched` (`t60_ms` can be `null`, clap P2) | log / ln 1.15 | `tail_decay_ms`, `room`, `room_length_ms` |
| Centroid, HF share | `analyse_nonpitched` | semitone / 1, lin / 0.03 | `bp_hz`, `bp_q`, `hp_hz`, `drive` |
| Sub-150 Hz share | **missing** (H11: below 0.01 in all 13 references) | dB / 3 | `hp_hz` |
| Energy after 150 ms | **missing** (H7) | dB / 3 | `room`, `tail_level` |

v0.2 stages (`fold`, `crush`, `rate_div`, `ring_*`, `comb_*`, `gate_ms`, `tail_reverse`) are **not searched** in v2: each one adds a discrete on/off decision whose identifiability is unmeasured. A later issue can add them once section 7 tests exist for v0.1. `rise_time_ms` weight 0 (clap P1).

### 3.5 Rim (`rim-params` 0.1)

| Feature | Measured by | Transform / scale | Main parameters |
| --- | --- | --- | --- |
| Lower partial (strongest peak, first 30 ms) | **missing** (rim R1) | semitone / 0.3 | `f1_hz` |
| Partial ratio | **missing** (R2, 300-6000 Hz; rim P3: click or HP can win) | semitone / 0.3 | `f2_ratio` |
| Partial level ratio | **missing** (R3) | dB / 1 | `level2` |
| Per-partial decay -20/-40 dB | **missing** (R4: band-pass around each line) | log / ln 1.15 | `decay1_ms`, `decay2_ms` |
| Low-edge leak | `analysis.lf_leak_db` at the fitted `hp_hz` (R5) | dB / 3 | `hp_hz` |
| Click energy > 4 kHz, first 3 ms | **missing** (R7) | dB / 2 | `click_level`, `click_ms` |

Rim is the most identifiable category (two damped sines, seed-independent at `click_level` 0, rim RT7): stage 1 alone (peak picking + per-band decay) should give most parameters; stage 2 refines `level2`, click and `drive`.

### 3.6 Perc (`perc-params` 0.1; fit per `model`)

The five models (conga, tom, shaker, cowbell, clave) are different signals; stage 0 picks the model first (section 6 shows the guesser confuses them with rim/clap/kick). Features per model family:

| Model | Features (measured by) | Main parameters |
| --- | --- | --- |
| conga, tom | pitch at 40 ms and bend ratio 2 ms vs 40 ms (**missing**, like the kick pitch curve; tom/conga = kick body, toms note T1-T2), T60 (`analyse_nonpitched`), tick energy > 1 kHz first 5 ms (**missing**) | `tune_semitones`, `bend_ratio`, `bend_ms`, `decay_scale`, `tick_level`, `tick_hz` |
| cowbell, clave | strongest two peaks (rim R1/R2 method, **missing**), T60, centroid | `tune_semitones`, `decay_scale`, `attack_scale`, `hp_hz` |
| shaker | centroid, HF share, flatness (`welch_flatness`), rise time 10-90 % (attack is long here, so usable), T60 | `tune_semitones`, `attack_scale`, `decay_scale`, `hp_hz` |

`drive` is searched for all models; `length_ms` from the reference.

### 3.7 Bass one-shot (`bass-params` 0.1)

| Feature | Measured by | Transform / scale | Main parameters |
| --- | --- | --- | --- |
| Note frequency (stationary window) | `bass.fundamental_hz` needs the resolved gate; for a reference **missing**: a gate estimate from the envelope (last sample above -6 dB of the sustain level) | semitone / 0.1 -> `note` (integer) + `cents` | `note`, `cents` |
| Harmonics 2nd, 3rd over fundamental (dB) | **missing** (bass Q2) | dB / 1.5 | `saw_level`, `square_level`, `sine_level`, `sub_octave_level`, `drive` |
| Sub share < 100 Hz | as kick | lin / 0.05 | oscillator levels, `lp_hz`, `hp_hz` |
| Centroid in the stationary window | **missing** (Q4) | semitone / 1 | `lp_hz`, `lp_q` |
| Filter movement: centroid 0-30 ms / stationary | **missing** (Q5; not valid below 2 periods in 30 ms, bass P4) | dB / 1 | `lp_env_amount`, `lp_env_decay_ms` |
| Attack 10-90 % | `rise_time_ms` on a period-long envelope (Q6) | log / ln 1.3 | `amp_attack_ms` |
| Gate length, release to -40 dB | **missing** (Q8, Q11) | log / ln 1.1 | `gate_ms`, `release_ms` |

`note` is integer: stage 1 sets it from the measured frequency (nearest MIDI note, cents = remainder within +-50); stage 2 does not move it. This is the only category with an exact analytic estimate for its main parameter.

### 3.8 Laser (`laser-params` 0.1/0.2; fit per `family`)

| Feature | Measured by | Transform / scale | Main parameters |
| --- | --- | --- | --- |
| Pitch track: start, end, time to 90 % of the sweep | **missing** (instantaneous frequency of the dominant partial; FM/ring sidebands can capture a zero-crossing tracker, so a peak track over short frames is needed) | semitone / 1; log / ln 1.25 | `pitch_start_hz`, `pitch_end_hz`, `sweep_ms`, `sweep_curve` |
| Sweep curvature (pitch at 25 / 50 % of sweep time) | **missing** | semitone / 1 | `sweep_curve` |
| Sideband density (spectral lines around the carrier) | **missing** | log1p / 0.3 | `fm_amount`, `fm_ratio`, `ring_amount`, `ring_hz` |
| Noise share / flatness | `welch_flatness`, **missing** band share | lin / 0.05 | `noise_level`, `noise_hz`, `crackle` |
| T60, centroid, HF share | `analyse_laser` | as hat | `decay_ms`, `attack_ms`, `lp_hz`, `hp_hz` |
| Shot count and spacing | **missing** (onset count on the envelope) | count exact; spacing log / ln 1.1 | `salvo_count`, `salvo_spacing_ms` (mode `ms` only in v2) |
| Side/mid energy ratio | **missing** | dB / 2 | `stereo_width`, `salvo_pan_*`, `reverb_width` |
| Late energy (echo/reverb) | **missing**: energy after the dry decay | dB / 3 | `echo_mix`, `echo_ms`, `echo_feedback`, `reverb_mix`, `reverb_decay_ms` |

Discrete in stage 0: `family`, `salvo_count`, `salvo_rate_mode` (fixed to `ms`), `filter_slope`, `echo_sync` (off). `variation` and `salvo_humanize` are held at 0 (they are seeded randomness; fitting them would fit the noise realisation). Many laser parameters interact (FM, ring, crackle, glitch); expect a large "not determined" list.

### 3.9 FX by kind (`fx-params` 0.1; fit per `kind`)

The reference's tempo is unknown from audio alone with any certainty, and every fx length is in beats. **Rule: the fit uses the project tempo from the GUI settings** (the user's tempo) and fits lengths in beats at that tempo; it never guesses BPM. The reader must accept up to 72 s (rule A).

| Kind | Features (all **missing** unless noted) | Main parameters |
| --- | --- | --- |
| riser, downlifter, sweep | centroid track over time (frames of 1/4 beat; fx note F10 measured centroid rise on mixes), level track in dB (BS.1770 momentary from `loudness.py` for files >= 0.4 s, or RMS frames), flatness (`welch_flatness`), tone partial track if `tone_level` > 0 | `cutoff_start_hz`, `cutoff_end_hz`, `sweep_curve`, `filter_mode`, `filter_q`, `level_start_db`, `level_end_db`, `level_curve`, `length_beats`, `noise_color`, `tone_*` |
| impact | tone pitch start/end and glide time (as kick pitch curve), T60 of the tone, noise share, late energy | `tone_start_hz`, `tone_end_hz`, `tone_glide_beats`, `tone_decay_beats`, `noise_level`, `reverb_mix`, `reverb_decay_ms` |
| noise_crash | HP corner (-6 dB), level fall over time, late energy | `cutoff_start_hz`, `level_end_db`, `ramp_beats`, `reverb_*` |
| reverse_crash | as noise_crash but in reversed time: level rise, end aligned (anchor end) | `length_beats`, `level_start_db`, `level_curve`, `reverb_*` |
| all kinds | side/mid ratio (`stereo_width`), pump depth (level modulation at the beat rate: **missing**), echo energy at the note delay | `stereo_width`, `pump_depth`, `echo_mix`, `echo_note` |

Budget matters most here (one riser render up to 10.8 s, section 5.1): the fx fit should render at a reduced test length first (same curves, `length_beats` scaled down) only if a test shows the features scale with length; otherwise the fit is limited to stage 0 + stage 1 plus at most ~20 renders. This is a proposal to be measured in E6.

## 4. Proposed fitting method (deterministic, NumPy only)

**Stage 0 - discrete choices.** For every discrete field (kick: none; hat `model`; perc `model`; laser `family`, `salvo_count`; fx `kind`, `filter_mode`, `noise_color`, `tone_wave`; clap `bursts`), render the candidate set (presets x 8 variants, filtered to each discrete value) and pick the value of the nearest candidate by the total distance (explained features + profile). Ties: grid order (as `reference.match_measures`). Output: start candidate and its distance = **"before"**.

**Stage 1 - analytic estimates.** Parameters with a direct measurement are set from it, then checked by one render: kick `pitch_end_hz` from the tail fundamental; bass `note`/`cents`; rim `f1_hz`, `f2_ratio`, decays; snare `body_hz`, `mode_ratio`; hat `decay_ms` from T60; perc tune from pitch; laser `pitch_start/end_hz`, `salvo_count`, `salvo_spacing_ms`; fx `length_beats` from file length at the project tempo. The estimate is kept only if it lowers the total distance against the stage-0 start (else the start value stays and the report says "Schätzung verworfen").

**Stage 2 - bounded coordinate search.**
- Each searched parameter p with range [lo, hi] from the contract maps to u in [0, 1]: u = ln(p / lo) / ln(hi / lo) for Hz, ms and ratio fields, linear otherwise. Integers are rounded after the map and moved by at least one step.
- Start: stage-1 point. Step 0.25. In a fixed parameter order (the order of the category table), try u + step then u - step; accept the first improvement and go to the next parameter. A pass without improvement halves the step. Stop when the step is below 1/256, or the render budget, or the time budget is used up. No random numbers, so the same reference, code and NumPy build give the same fit (cross-machine bit equality of FFT results is not promised, prior note section 7).
- Every trial goes through the category's `resolve`; a `ValueError` (cross-field rule, kick length rule, fx rule A/B/C) counts as a rejected trial with infinite cost and is counted in the report. Values are never clamped silently: the u-map is clipped to [0, 1], so every trial is inside the range.
- Why not `scipy.optimize`: no new dependency is needed for a first version; the prior note's `least_squares` joint fit stopped at large errors (6.3); a pattern search is easy to make deterministic and to budget. If E6 shows the search is the bottleneck, a `contract`-free proposal to add SciPy goes into its PR with the reason (CLAUDE.md dependency rule).

**Budget (proposal, to be confirmed in E6):** kick, hat, snare, clap, rim, perc, bass: 300 renders and 30 s; laser: 120 renders and 60 s; fx: stage 0 + 1 plus 20 renders and 120 s. Measured in section 5.3: 300 kick renders took 4.1-12.4 s, hat fits of 186-300 renders took 2.4-52.9 s (long open hats render slowly), so the time budget is the binding limit for long sounds. The GUI runs the fit in a worker thread with a cancel button; a cancelled fit returns the best point so far, labelled "abgebrochen".

**Report (before / after):**
- Per explained feature: reference value, start candidate value, fit value, distance before, distance after (same table layout as today's Referenz page plus one column).
- Total distance before and after; profile distance before and after, labelled "Form (nur für die Suche)".
- Renders used, seconds, stop reason (step / renders / time / cancelled), rejected trials.
- Per searched parameter: start value, fit value, and a **determination flag** from a local sensitivity check at the end: cost change when u moves +-1/32; below 0.05 units on both sides = "von den Messwerten nicht festgelegt" (the value is a start point, not a measurement). The flags of section 7 tests (parameters that are weak by design) are shown too.
- No sentence that the fit sounds like, or is similar to, the reference.

**Variants around the fit:** N renders (N <= 8, `variants` contract range) from the category's existing `make_variants(fit, N)`, so the spread is the same seeded box the user already knows; each variant gets its total distance in the list. Optional later: spread only along parameters flagged "not determined" (they are free by the measures, so moving them keeps the measured distance; whether the ear agrees is a listening question).

## 5. Experiments run for this note (scratchpad, not in the repo)

All scripts import `audio_engine` from this worktree's `src/` and run with `python3 -I` from the scratchpad. Throw-away; workers rewrite them as tests.

### 5.1 Render cost per category

`timing.py`: one render per preset per category, `time.perf_counter` around `Category.render`.

| Category | Presets | Render s, median / max | Length s, median / max |
| --- | --- | --- | --- |
| kick | 6 | 0.025 / 0.054 | 0.46 / 0.75 |
| hat | 5 | 0.041 / 0.130 | 0.15 / 0.53 |
| snare | 5 | 0.024 / 0.038 | 0.40 / 0.60 |
| clap | 11 | 0.019 / 0.050 | 0.50 / 0.90 |
| rim | 5 | 0.013 / 0.015 | 0.20 / 0.20 |
| perc | 9 | 0.001 / 0.036 | 0.15 / 0.40 |
| bass | 8 | 0.020 / 0.055 | 0.22 / 0.36 |
| laser | 14 | 0.332 / 0.832 | 1.45 / 3.00 |
| fx | 8 | 1.384 / 10.793 | 8.44 / 58.67 |

One run, Linux, 2 cores, other agents possibly active; read as orders of magnitude. The kick is about 8x faster than the 0.21 s of the 2026-11-02 note (cause not investigated here).

### 5.2 Category guess on engine renders

`guess.py` then `guess2.py`: every preset of every category x 8 variants (fx: 3), 528 renders. Features from the onset, peak-normalised mid signal: ln centroid, share < 100 Hz, share 100-1000 Hz, share > 8 kHz, ln T60 (line fit; file length if `None`), Welch flatness 200 Hz-16 kHz, click share > 1 kHz in 10 ms; `guess2.py` adds pitch drop (ln of zero-crossing frequency 5-40 ms over 100-300 ms, 400 Hz low-pass), sustain (fraction of the first 300 ms within -12 dB of the peak, 4 ms RMS) and ln(1 + burst count in 60 ms). Z-scored, nearest centroid, **leave-one-preset-out** (all variants of the tested preset are removed from the centroids; the z-score mean and std are computed over all 528 renders including the held-out preset, which is a small leak, effect not measured).

| Run | Top-1 | Top-2 | Per category top-1 |
| --- | --- | --- | --- |
| 7 features | 366 / 528 (69.3 %) | not computed | kick 43/48, hat 40/40, snare 32/40, clap 78/88, rim 32/40, perc 3/72, bass 48/64, laser 66/112, fx 24/24 |
| 10 features | 410 / 528 (77.7 %) | 455 / 528 (86.2 %) | kick 48/48, hat 40/40, snare 32/40, clap 87/88, rim 30/40, perc 19/72, bass 64/64, laser 72/112, fx 18/24 |

- Pitch drop + sustain removed the kick/bass confusion (16 bass renders guessed as kick before, 0 after; bass 64/64).
- `perc` is the weak class (19/72): its five models resemble rim (32 perc renders guessed rim in run 1), clap and kick. Inference: guessing should target (category, model) pairs, and a held-out perc model that has no sibling preset of the same model in training cannot be recognised by a centroid method at all.
- Margin = distance to the 2nd centroid minus distance to the 1st (z units): median 1.27 when right, 0.41 when wrong. With margin >= 1.0, 281 of 528 renders are decided and 13 of those are wrong; with >= 0.5, 385 decided and 40 wrong.
- Limits: in-domain only (our own renders, our own presets). Real reference files are produced by other synths, layered, processed; the rate on them is **not established** and probably lower (inference).

### 5.3 Fit feasibility: coordinate search on synthetic references

`fit.py` (explained features only), `fit2.py` (plus the profile of rule 6, weight = one feature) and `fit_near.py` (= `fit2.py` with references drawn near presets; the exact changed line is quoted in (c)). All three read the contract schemas from the hard-coded path `/home/claude/wt-refsteer2/contracts`. Truth = a random preset variant with its searched parameters replaced; reference seed 1234; fit seed 7 (different on purpose); start = nearest of the candidate set; stage 2 of section 4 without stage 1; budget 300 renders; generator `PCG64(52201)`. Kick searched 8 parameters (`pitch_start_hz`, `pitch_end_hz`, `pitch_decay_ms`, `amp_decay_ms`, `click_level`, `click_tone_hz`, `drive`, `tone`) with the six `reference.MEASURES`; hat searched 6 (`decay_ms`, `metal`, `pitch_scale`, `color`, `hp_hz`, `drive`) with centroid, HF share > 8 kHz, line-fit T60, Welch flatness 2-16 kHz, early/late centroid ratio.

**(a) Full-range references (each searched u uniform in [0, 1]), features + profile:**
- Kick, 6 references: distance before 1.92-7.28, after 0.51-3.50. The accepted truths had `amp_decay_ms` 21, 849, 39, 30, 29 and 43 ms, so in this draw 5 of 6 were very short kicks. This is a property of the draw, not of the sampling: log-uniform sampling of 20-2000 ms gives P(<= 43 ms) = ln(43/20) / ln(100) = 0.17. The draw also had two rejected truths; both were rejected by the pitch-order rule (`pitch_end_hz` above `pitch_start_hz`), not by a decay rule (replayed by the reviewer of PR #524). For the five short ones `amp_decay_ms` came out +2437 to +7704 % and the distance stayed at 3.15-3.50. Cause not established (candidates: local minimum of the pattern search, `None` decay measures on very short kicks counting a flat 3 units, start candidate far away).
- Hat, 6 references: before 1.52-4.26, after 0.31-1.38; `decay_ms` within 16 % in 5 of 6; `pitch_scale` -61 to +115 % off.

**(b) Same, explained features only (`fit.py`):** kick reference 2 reached distance **0.02** with `click_tone_hz` +1200 % and `amp_decay_ms` +104 % off; hat reference 2 reached 0.02 with `pitch_scale` +38 % off. This is the clearest evidence that low feature distance does not mean the parameters were found: the six kick measures and the five hat measures are many-to-one.

**(c) Near-preset references, features + profile** (the realistic case for "a reference that is like one of our sounds"). Script `fit_near.py`. Its only change against `fit2.py` is in fit.py's truth line, where
`from_u(cat, k, float(rng.uniform()))` becomes
`from_u(cat, k, to_u(cat, k, base[k]) + float(rng.uniform(-0.15, 0.15)))`.
`base` is the drawn candidate (a preset variant, not the bare preset), and `from_u` clips u to [0, 1] at the range edges. A second run of `fit_near.py` gave the same parameter errors and distances; only the times differed (they are given as the range of both runs).

| Kick ref | Before -> after | `pitch_end_hz` | `amp_decay_ms` | `pitch_start_hz` | `pitch_decay_ms` | `click_tone_hz` | `click_level` | `drive` | `tone` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.39 -> 0.27 | -1 % | +5 % | +5 % | -4 % | +16 % | -0.20 | -0.03 | +0.74 |
| 2 | 2.90 -> 0.46 | -3 % | -9 % | +5 % | -5 % | -92 % | +0.43 | +0.06 | +0.48 |
| 3 | 1.19 -> 0.70 | -2 % | +12 % | +23 % | -10 % | +63 % | -0.11 | +0.01 | +0.52 |
| 4 | 1.65 -> 0.92 | -2 % | +88 % | -61 % | +86 % | -36 % | +0.07 | -0.20 | +0.63 |
| 5 | 1.83 -> 1.07 | +7 % | +36 % | +106 % | -75 % | -55 % | -0.05 | -0.29 | +0.45 |
| 6 | 1.14 -> 0.52 | +2 % | +11 % | +23 % | -33 % | -53 % | +0.17 | -0.03 | -0.14 |

300 renders each, 4.1-12.4 s. `pitch_end_hz` within 7 % in 6 of 6; `amp_decay_ms` within 12 % in 4 of 6; `pitch_start_hz` and `pitch_decay_ms` trade off against each other (refs 4, 5: start +106 %, decay -75 %), as in the prior note; `click_tone_hz` and `tone` are not recovered.

Hat near-preset, 6 references: before 0.82-1.96 -> after 0.25-0.77, 186-300 renders, 2.4-21.0 s. `decay_ms` within 3 % in 6 of 6; `hp_hz` within 15 % in 6 of 6; `drive` within 0.15 in 6 of 6; `metal` off by 0.08-0.48 and `pitch_scale` by +39 to +74 % in 5 of 6 (they trade off: the features used do not include `peak_count` or the predicted line set).

**What follows (inference):** (1) the explained features need the "missing" entries of section 3 (pitch curve for kick; line count for hat) before parameter recovery can be asserted for the parameters they govern; (2) tests must check parameter recovery per parameter, not only distance; (3) the start point may matter. The only evidence is the single full-range draw in (a), where 5 very short kicks (`amp_decay_ms` 21-43 ms) were not reached in 300 renders, cause not established. Stage 1 estimates are proposed for that reason and must be checked in E6. In any case the report has to show a high "after" distance openly.

### Commands

```
# scratchpad: /tmp/claude-0/-home-claude/8969c227-1cdb-551a-898a-46125f9a8cff/scratchpad/rs2
python3 -I -c "import sys; sys.path.insert(0,'/home/claude/wt-refsteer2/src'); exec(open('timing.py').read())"
python3 -I -c "import sys; sys.path.insert(0,'/home/claude/wt-refsteer2/src'); exec(open('guess.py').read())"
python3 -I -c "import sys; sys.path.insert(0,'/home/claude/wt-refsteer2/src'); exec(open('guess2.py').read())"
python3 -I -c "import sys; sys.path.insert(0,'/home/claude/wt-refsteer2/src'); exec(open('fit.py').read())"
python3 -I -c "import sys; sys.path.insert(0,'/home/claude/wt-refsteer2/src'); exec(open('fit2.py').read())"
python3 -I -c "import sys; sys.path.insert(0,'/home/claude/wt-refsteer2/src'); exec(open('fit_near.py').read())"   # (c), run twice
# all fit scripts read the schemas from /home/claude/wt-refsteer2/contracts (hard-coded)
```

## 6. Category guessing for folder import

1. **Audio only.** File and folder names are never used (kick-gen2 pitfall 9), even when they look like "hat_01".
2. **Per file:** read (E1), first hit only (onset count on the envelope; a file with several hits is marked "Loop: erster Schlag gemessen", pitfall 6), censored-tail flag (pitfall 7), then the 10 features of 5.2 (extended by the stereo ratio for laser/fx).
3. **Guess target:** (category, discrete sub-choice): `kick`, `hat/metal_bank`, `hat/noise`, `snare`, `clap`, `rim`, `perc/<model>`, `bass`, `laser/<family>`, `fx/<kind>`. Centroids from all presets x 8 variants, recomputed when presets change (cached by a hash of the preset files).
4. **Shown:** best guess, second guess, margin; margin below a threshold (proposal 1.0 z units, from 5.2: 13 wrong of 281 decided on engine renders) shows "unsicher" and requires a click to confirm before any fit. Override is a dropdown per row; the override is what the fit uses.
5. **Duplicates:** onset-aligned correlation over the first 250 ms, threshold 0.98 with the positive control of kick-gen2 section 2; duplicates are listed, not dropped silently.
6. **Batch:** files are analysed one after another in a worker thread; a file that fails shows its German reader error in its row; the rest continue. Fits run only on request per row (budget!), not for the whole folder at once.

## 7. Test ideas

**Main honest check - recovery of synthetic references (per category, slow-marked where needed):**
- References = renders of our own engine with known parameters, drawn seeded (`PCG64`, fixed seed in the test) in two boxes: (a) near presets (u +- 0.15, the case section 5.3 (c) measured), (b) the full contract range. Reference seed differs from the fit seed. At least 8 references per category in (a), 4 in (b).
- **Tiered tolerances, written as numbers in the test** (independent of the fit code): tier A parameters (directly measured, e.g. kick `pitch_end_hz`, bass `note`, rim `f1_hz`, hat `decay_ms`) asserted for every reference in box (a); first proposals from 5.3 (c): kick `pitch_end_hz` within 8 %, hat `decay_ms` within 5 %. Tier B (searched, expected to be found) asserted on a share (e.g. 6 of 8). Tier C (known weak: kick `click_tone_hz`, `tone`; hat `metal`/`pitch_scale` until `peak_count` is in) not asserted but must appear with the "nicht festgelegt" flag in the report. Box (b) asserts only "after <= before" and that the report states the stop reason.
- **Distance property:** for every reference, after <= before (stage 2 accepts only improvements; a test that fails here means a bug).
- **Identity:** a reference that *is* a candidate (same params, same seed) gives before = 0 and the fit keeps it (no move away from an exact match).
- **Determinism:** same reference + same code -> identical fit params and report twice in one process and in two processes.
- **Fault injection (CLAUDE.md rule):** the mutant has to move the parameter further than the tolerance gap, or it survives for the wrong reason.
  - Example, kick tier A: scale the tail-fundamental extractor by **1.20**. The tolerance is 8 % and the largest error measured so far is 7 % (5.3 (c)). A shift above 8 + 7 = 15 % therefore puts every reference outside the tolerance, also those whose error had the opposite sign. Stage 1 sets `pitch_end_hz` directly from this measure, so the shift reaches the parameter in full, and the test must turn red for every reference.
  - A 1.02 mutant stays inside 8 % for most references and is **not** a valid check.
  - Rule for E6: measure every mutant against the drawn references before the tolerance is fixed, and put the chosen factor and its red/green result in the PR.
  - Second mutant: swap the u-map of one log parameter to linear. Recovery of that parameter should degrade; the size is to be measured in E6.
  - Third mutant: drop the profile. Without it, 5.3 (b) found distance 0.02 with wrong parameters, but only on full-range references, where box (b) asserts only after <= before. Its effect on the near-preset box (a) has not been measured; to be measured in E6 before this mutant counts as evidence.
- **Feature extractors alone (before any fit):** each new "missing" feature is tested against values written in the test for synthetic signals with known answers (a sine sweep with known exponential for the pitch curve, two damped sines for the rim partial finder, a noise burst train with known spacing for the clap burst detector), never against the engine's own formula.
- **Guess test:** leave-one-preset-out top-1 on engine renders at or above a stated rate (proposal: the 5.2 numbers minus a margin, e.g. >= 70 % overall, kick and bass >= 95 %), and a test that a file name never changes the guess.
- **Reader:** 32-bit float, 96 kHz, long fx files, stereo kept for width; error texts in German for each refusal.
- **Cannot be tested in CI:** whether any fit resembles the reference to the ear; behaviour on the user's own references (those never enter the repo). A local, opt-in script can print the report for the user's folder; its output is information, not a test.

## 8. What "similar" can and cannot mean without listening

- **Can mean:** the stated features of the fit lie within N scale units of the reference's features, measured by the stated methods; and the profile distance is X. That is all the report may say ("Messwerte liegen näher": "Abstand vorher 2,9, nachher 0,5").
- **Cannot mean:** "sounds like", "same character", "same punch", "close enough". Section 5.3 (b) shows two renders with distance 0.02 whose parameters differ by +1200 % (`click_tone_hz`): the measures do not see every audible difference, and nothing here says which differences the ear cares about.
- **Cannot cover:** what the engine cannot render (sound-designer H3 on #58: layered bodies, attack-only density, sample layers, processing chains of the reference). A large "after" distance is a finding about the engine's reach, not a failure to hide.
- **Direction of error is unknown:** a feature the user does not care about may dominate the distance, and one they do care about may be absent. Only a listening test can say which; the plan for that comes after E6 with the user's own references (#58 "What I need from the user").
- **Not a copy:** the fit outputs engine parameters only; the reference audio is never resynthesised, stored or uploaded (issue #522 scope). Fitted parameters of a commercial sample stay outside the repo; before any preset derives from one specific commercial sample, the user is asked (prior note section 7).

## 9. Contract and reader gaps (for the issue split)

- Reader: 32-bit float PCM (format tag 3), 96 kHz, per-category maximum length (laser 6 s, fx 72 s), stereo kept as two channels for width, first-hit split. No contract change (reader is engine code).
- Sidecar: a fitted sample's parameters are an ordinary params object, so `sample-metadata` needs **no change** for v2 to re-render it. Recording "this came from a fit, distance X" in the sidecar would need a `contract-change` (closed `features` key set); proposal: keep the fit report as a separate local JSON next to the user's reference list, outside the repo, and decide on a sidecar field only if the user asks.
- No parameter-contract change is proposed. Features that point outside the engine (H3 of #58) would become `parking-lot` -> `contract-change` issues, as before.

## 10. Issue split (titles and Done-when; not filed)

Engine (owner `audio-engineer`):

- **E1 · Reference reader v2: float, 96 kHz, per-category length, stereo kept, first hit.** Done when: 32-bit float and 96 kHz files read (tests with files written in the test); per-category length limits from the contracts (laser 6 s, fx 72 s) with German errors beyond; stereo available as (n, 2) for width features; a multi-hit file yields its first hit plus a flag, and a censored-tail flag; existing kick reader tests still green.
- **E2 · Reference features per category (explained features of section 3).** Done when: one function per category returns the section 3 features from a `ReferenceAudio`; every "missing" feature has tests against values written in the test for synthetic signals with known answers; `reference.measure` keeps its six values byte-equal (kick page unchanged).
- **E3 · Scale calibration per feature.** Done when: method error and seed spread (seeds 1-8) per feature are measured on engine renders by a script whose output table is committed as data with the command; the distance uses scale = max(both). The table also holds each feature's between-candidate spread, and features whose seed spread is at least one third of it carry weight 0 (rule 2.4 (a)). A test reads the table and fails if a scale is 0 or missing, or if a weight does not follow from that ratio. A test with a synthetic feature whose seed spread is made larger than its between-candidate spread shows that the weight-0 rule triggers.
- **E4 · Candidate sets for all categories.** Done when: presets x 8 variants per category (per discrete sub-choice) are rendered and measured once per process and cached; fx candidates at the project tempo; total build time per category is reported in the PR.
- **E5 · Category guesser.** Done when: (category, sub-choice) guess with second guess and margin from E2/E4 features; leave-one-preset-out on engine renders reaches the stated rates (proposal >= 70 % top-1 overall, kick and bass >= 95 %); a test proves file names do not change the guess.
- **E6 · Fit core: stages 0-2, budget, report.** Done when: deterministic fit per category as in section 4 (no RNG, contract-bounded, rejected trials counted, time and render budget, cancel returns best so far); synthetic recovery tests per category with tiered tolerances (section 7) green, including near-preset and full-range boxes; after <= before for every reference; identity and determinism tests; fault-injection results in the PR; render budget and seconds per category measured and stated.
- **E7 · Variants around the fit.** Done when: N variants from `make_variants(fit, N)` with per-variant distances; byte-identical re-render from each variant's params.
- **E8 (optional, only if the user wants it) · `contract-change`: fit provenance in the sidecar.** Done when: the user decides yes; until then the fit report stays a local JSON.

GUI (owner per the GUI files' current owner):

- **G1 · Referenz page v2: all categories, fit with before/after.** Done when: category chosen by the guess or by the user; "Anpassen" runs the fit in a worker thread with progress and cancel; table shows reference / start / fit / distance before / after per feature, plus "nicht festgelegt" flags, renders, seconds and stop reason; "Als Startwerte übernehmen" fills the form of that category; texts contain no similarity claim (test greps the German strings for "klingt", "ähnlich" outside the disclaimer).
- **G2 · Folder import with category guess.** Done when: a folder (or several files) is listed with best/second guess, margin, "unsicher" marker and override; failing files show their error and do not stop the batch; duplicates and loops are marked; nothing is copied or uploaded (test checks no file is written outside the user's library/settings).
- **G3 · Render N variants from the fit into the library.** Done when: variants are written as ordinary category renders with sidecars that re-render byte-identically; the reference file itself is never copied.

Sound-designer (after E6 and G1): **S1 · Listening plan with the user's own references** (3-5 files per category the user cares about; pairs: start candidate vs fit, fit vs variant; one question each; under 15 minutes).

## 11. Decisions on the former open questions (lead, 2026-11-08, relayed in the review round of PR #524)

1. **First slice: kick + bass.** The other categories follow after E6 has run for these two.
2. **Commercial-pack references may be analysed, locally only.** Nothing is copied or uploaded, and neither the audio nor the per-reference parameters enter the repo. The rule of section 8 still applies: before a shipped preset derives from one specific commercial sample, the user is asked.
3. **Fits never run automatically over a folder**, only on request per file. Folder import (G2) guesses categories only.

## Implications for the lead

- First slice (lead decision, section 11): E1 + E2 + E3 for kick and bass, then E6 for those two; folder import (E5, G2) does not need the fit and can run in parallel.
- The kick v2 fit is blocked on the pitch-curve feature (E2); without it `pitch_start_hz`/`pitch_decay_ms` trade off (5.3 (c), refs 4-5).
- No new dependency is needed; SciPy stays out unless E6 shows otherwise.

**State update proposal (for the PR body):** "Research note `docs/research/2026-11-08_reference-steering-v2.md` (#522): per-category features with scales from measured method error and seed spread, staged deterministic fit (discrete candidates, analytic estimates, bounded coordinate search) with before/after report and 'not determined' flags; measured on engine renders: category guess 77.7 % top-1 (perc weak), fit recovers directly measured parameters near presets but measures are many-to-one; issue split E1-E8, G1-G3, S1 proposed, not filed."
