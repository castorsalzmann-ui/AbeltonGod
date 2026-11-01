# Research: kick layering (#57) and steering the engine with own reference samples (#58)

- **Date:** 2026-11-02 (every web source was opened on this date; "opened" below means 2026-11-02)
- **Receiving issues:** #57 (fuse two kicks into one), #58 (own reference samples, "main character")
- **Author role:** researcher A (sound and audio)
- **Status:** researched; three small experiments were run in a scratchpad outside the repo (section 6). **No sound claims.** Whether a fused or fitted kick sounds better is decided by the user's ears only.
- **Builds on, does not repeat:** the `sound-designer` measurements on the issues themselves ([#57 comment](https://github.com/castorsalzmann-ui/AbeltonGod/issues/57), [#58 comment](https://github.com/castorsalzmann-ui/AbeltonGod/issues/58): sub ratio per pair, polarity flips, taste-range table, hypotheses H1-H5, listening plans), [kick-gen2 learnings](2026-10-28_kick-gen2-learnings.md) (M5, M8, F3, section 4 pitfalls, section 5 "layer phase check"), [kick-in-tracks](2026-10-29_kick-in-tracks.md) (extracting kicks from loops and tracks), [ai-audio-one-shots](2026-10-29_ai-audio-one-shots.md) (generative route, not needed here).
- **Versions:** repo `origin/main` a0ca3a5 (engine `src/audio_engine/`, kick-params contract with `polarity`, `offset_ms`, `clip_db`, `click_decay_ms`, `click_q`); Python/NumPy 2.5.3/SciPy 1.18.1 in the scratchpad (Linux); PyPI data read 2026-11-02.

## For workers

- **Possible?** Yes, with the current stack, without Max for Live and without a generative model. Layering needs no new Ableton function (it is offline DSP on two WAVs). Reference steering is feasible as a *staged, deterministic fit* of the existing kick-params to a reference WAV, with a residual report; a one-stage black-box fit does not work (section 6.3).
- **Recommended route #57:** an offline "layer" function in `src/audio_engine/` that takes two rendered kicks (or two kick-params sets), searches polarity and a 0-5 ms offset on the sample grid for the best low-end summation, optionally splits at a crossover (zero-padded zero-phase Butterworth-2 pair, section 3.2), normalises to the peak ceiling, and returns the sum plus a report (sub ratio before/after, peak before normalising, crest, mono check). Plain polarity/offset needs **no new contract field** (`polarity`, `offset_ms` exist in v0.3); the fused-sample sidecar does (its `parameters` field holds exactly one kick-params object).
- **Recommended route #58:** (1) a reference analyser that writes per-zone features (click / body / tail) from a WAV, (2) a staged fit (pitch curve, amplitude slope, then click/drive) to kick-params with a residual report per zone, (3) a per-user preset made of fitted params. Reference audio never enters the repo.
- **Read first:** this note sections 3, 5, 6; `src/audio_engine/kick.py` (signal chain), `analysis.py` (pitfalls in its docstring), kick-gen2 learnings section 4.
- **Effort:** #57 step 1-2 small to medium; #57 crossover/attack-density medium; #58 analyser + staged fit large (new reader for arbitrary WAVs, scipy decision, taste checks).
- **Blockers / decisions only the user can make:** (a) which of the #57 listening pairs (A-E) won: they decide whether H1/H2 (level, clipping) or H3/H4 (two pitches, phase) is the real cause, and so whether summing is the right feature at all; (b) licence of the reference samples (section 7): the Splice FAQ says AI training/modelling use is not permitted, and calls "analysis" nothing explicitly; (c) new dependency `scipy` (section 4); (d) who supplies 3-5 reference kicks.

## 1. Findings table

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| 1 | Polarity inversion of one layer and a small time shift change the low-end sum; transients should be aligned first, then polarity is checked by listening or level; thin sound / lost low end is the symptom. | medium (trade-press articles, practitioner advice, not measurements) | [Attack Magazine, layering kick drum samples p.2](https://attackmagazine.com/technique/tutorials/layering-kick-drum-samples/2), [Sonnox, drum phase alignment](https://sonnox.com/articles/drum-phase-alignment-when-to-nudge-flip-or-leave-alone) |
| 2 | Estimated offset from a problem frequency: offset (ms) = 1000 / (2 x f) (half a period flips the sign). | medium (single article) | Sonnox, same page |
| 3 | A Linkwitz-Riley LR4 crossover is two cascaded 2nd-order Butterworth filters, -6 dB per output at the crossover, low and high outputs add to a flat magnitude (all-pass sum), outputs 360 degrees apart (in phase). | medium-high (reference article, standard result) | [Wikipedia, Linkwitz-Riley filter](https://en.wikipedia.org/wiki/Linkwitz%E2%80%93Riley_filter) |
| 4 | Forward-backward filtering (`sosfiltfilt`) gives no phase delay; default `padtype='odd'`. | high | [SciPy 1.18 `sosfiltfilt`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html) |
| 5 | Punch has a peer-reviewed perceptual model (PM95): transient component only, octave bands 64 Hz-1 kHz, BS.1770-based loudness with changed filter (pre-filter gain 10 dB instead of 4 dB, shelf corner 1 kHz instead of 1.6 kHz) and 280 ms blocks; Pearson r = 0.849, Spearman 0.833 against a pairwise listening test. | high that the paper says this; low-medium that it transfers to kicks (see 5) | [Fenton & Lee, JAES 67(6) 2019, abstract](https://pure.hud.ac.uk/en/publications/a-perceptual-model-of-punch-based-on-weighted-transient-loudness/); [Fenton, Lee, Wakefield, AES 139 preprint](https://eprints.hud.ac.uk/id/eprint/26288/9/AES%20139_Perceptual_Punch_Model_Fenton.pdf) |
| 6 | The AES 139 preprint's own limits: coefficients derived from 11 listeners and 45 synthetic pink-noise bursts, in-sample fit, 2-8 kHz not modelled, onset sidechain unfinished, validation on music qualitative. The JAES version (2019) is later and reports the r above; this session read only its abstract. | high (as read) | AES 139 preprint, section "limitations" |
| 7 | `pyloudnorm` (MIT, 0.2.0) implements BS.1770-4 and lets you change the weighting filter class (it lists Fenton/Lee among alternatives) and block size. It **raises `ValueError: Audio must have length greater than the block size`** for a 300 ms signal at the default 400 ms block. | high (README read + run on 2026-11-02) | [pyloudnorm README](https://github.com/csteinmetz1/pyloudnorm); local run, section 6 |
| 8 | The multi-scale spectral loss used to fit synthesis to audio: per FFT size L1 of linear magnitude + alpha x L1 of log magnitude (alpha = 1), sizes 2048...64, 75 % overlap. It compares magnitudes, so it does not need the reference's phase. | high | [Engel et al., DDSP, arXiv 2001.04643](https://arxiv.org/pdf/2001.04643), section 4.2.1 |
| 9 | `scipy.optimize.least_squares`: methods trf/dogbox/lm, bounds for trf/dogbox, robust losses `soft_l1`/`huber`; no random component in the algorithms (the page does not state determinism explicitly). `differential_evolution` is repeatable only with `rng` (formerly `seed`, renamed in SciPy 1.15.0); `workers != 1` forces `updating='deferred'`. | high / medium (determinism inferred) | [least_squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html), [differential_evolution](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.differential_evolution.html) |
| 10 | `numpy.random.Generator` streams are guaranteed only for the same build, environment and machine; `PCG64` has stronger version-to-version guarantees than `default_rng`. | high | [NumPy RNG compatibility policy](https://numpy.org/doc/stable/reference/random/compatibility.html) |
| 11 | Splice FAQ: commercial use of the sounds in new works is permitted; using them in isolation as source material for another sample (even modified) or redistributing them is not; use as AI training/modelling data "is not permitted". Not legal advice; the FAQ points to Terms section 3.1.1.3 which this session did not open. | medium (FAQ summary, not the Terms) | [Splice Sounds licensing FAQ](https://intercom.help/splice-b7a2d5b83f2e/en/articles/8652642-splice-sounds-licensing-faq) |
| 12 | Spectral flux (log-compressed STFT, positive frame-to-frame difference, summed over bins) is the standard onset-strength measure. | high | [FMP notebook C6S1](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C6/C6S1_NoveltySpectral.html) |

Not opened / not verified: the Ableton Live 12 manual's Utility chapter (the page chunks did not reach it). The `sound-designer` plan names Utility "Invert" and gain; a worker using it should read the manual first. Attack Magazine part 1 says nothing about phase or levels; part 2 is the source for finding 1.

## 2. What the existing engine can do today (read in `src/audio_engine/`)

| Need | Present | Gap |
| --- | --- | --- |
| Two kicks with different shapes | `render_kick(params)` returns mono float64; presets in `src/audio_engine/presets/` | None. A layer function can call it twice. |
| Polarity and lead-in per kick | v0.3 `polarity` (-1 negates the whole output after the ceiling), `offset_ms` (whole samples of exact digital silence in front) | Offset is quantised to whole samples (sample-exact). Sub-sample offsets would need a fractional-delay filter (inference; not needed for a 0-5 ms search at 48 kHz, step 0.021 ms). |
| Density on the attack | `drive` (tanh, whole kick), `clip_db` (hard clip, whole kick), both oversampled 8x with the residual trick (`dsp.oversampled`) | No attack-only stage; no clip after summing. Sound-designer proposal 3. |
| Filters | RBJ band-pass, one-pole LP/HP (`dsp.py`); loops in pure Python per sample | No Butterworth/LR4, no FIR design except the Kaiser resampling filter. |
| Measurement | `analysis.analyse`: peak, length, tail fundamental, 20/40 dB decay, DC | No sub share, no zone energies, no punch measure, no onset-referenced pitch curve. Kick-gen2 section 4 describes the method for those; the `sound-designer` re-implemented it outside the repo. |
| WAV reading | `io.wav_samples` reads only this module's own mono 16/24-bit layout | A reference reader for arbitrary WAVs (stereo, 24-bit, 32-bit float, 44.1/48/96 kHz) does not exist. |
| Sidecar | `sample-metadata` `parameters` = one kick-params object; `category` enum is `["kick"]`; `features` has a closed key set | A fused kick or a fitted kick needs a contract change (two parameter sets + recipe, and a source note for a fit). |
| Speed | one default render took 0.21 s here (one measurement, Linux, this machine); the per-sample Python loops in the click band-pass and one-pole filters dominate (not profiled) | Black-box fitting through `render_kick` costs 0.2 s per evaluation (section 6.3). |

## 3. Deterministic methods for #57

### 3.1 Alignment and summation (no filtering)

1. Render both kicks at the same rate and length; pad to equal length.
2. For polarity p in {+1, -1} and offset k in 0...K samples (K = 5 ms x sr / 1000) of the second kick, compute the energy below ~100 Hz of `A + p x shift(B, k)` and keep the best. Reference quantity: sub ratio = E_sub(sum) / (E_sub(A) + E_sub(B)), as the `sound-designer` defined it (1.0 = no interaction, below 1 = cancellation).
3. Normalise the sum to the peak ceiling (the existing `_normalise` logic: half an LSB of headroom).

Run on five preset pairs (section 6.1, my own script, same sub-ratio definition): naive sum 0.514 / 1.079 / 0.929 / 1.025 / 1.145; best of (polarity x 0-5 ms) 1.486 / 1.174 / 1.170 / 1.029 / 1.406. For `punchy`+`dark-dry` the best is polarity -1 at one sample, and the value 1.486 equals the sound-designer's independently measured polarity-only value (0.514 -> 1.486). Offsets of 3.2 ms won for three pairs. Practitioner sources warn that time-shifting past the transient alignment makes the layers sound like two hits (Attack, Sonnox: "over-aligning"/aligning transients first), so a **cap** on the offset and a transient-alignment term are needed (inference); energy maximisation alone does not know about that, and which offset is acceptable is a listening question.

Side effects to report, not hide: the unnormalised sum peaked at 1.5 to 1.8 of full scale in all five pairs (same finding as #57 H1: +3.6 to +5.3 dBFS); normalising back lowers the level of the first 100 ms below `punchy` alone in 14 of 14 pairs according to the sound-designer. A pure alignment-and-normalise feature therefore does not add loudness by itself.

### 3.2 Frequency separation (crossover)

- **Zero-phase, power-complementary pair:** `sosfiltfilt` of a Butterworth-2 low-pass and the matching high-pass has magnitude equal to the LR4 response and no phase delay, and low + high reconstructs the input. Measured (section 6.2): on four presets the reconstruction error was -261 to -257 dB re peak when the signal is **zero-padded by 1 s on both sides and `padtype=None`**, but only -47 to -78 dB with the default `padtype='odd'`. The cause is edge padding in this experiment (zero padding removed it); that is an observation on four kicks, not a proof for all.
- **Cost of zero-phase (inference):** the filters are non-causal, so band-limited parts ring *before* the kick's first sample; whatever falls before sample 0 is cropped when the output keeps the input length. For a low band from kick A only, this lost part is small but not measured.
- **Causal LR4** (cascaded `sosfilt`): in-phase at the crossover (finding 3) but with the all-pass phase rotation of the network, so the transient of the low band is delayed relative to the high band. Choosing it changes the attack of the fused kick; to be judged by ear.
- Splitting removes the cancellation problem at its root above the split frequency, but also the two-pitch overlap that sound-designer H3 found for some pairs (their proposal 4). Which matters more is a listening question.
- A crossover is not the only deterministic route: a **shared-grid hybrid**, low band of A (sub/body) + high band of B (click) + a level and delay match, equals what producers do with two tracks (finding 1, Attack's "complementary layers": name what is missing, then add it).

### 3.3 Attack density after summing

Sound-designer H2 suggests clipping at the output might be part of the perceived punch. A deterministic, band-limited way exists in the engine: `clip_db` on the *sum*, using the same oversampled residual clipper (`kick._hard_clip`). An attack-only variant (window the clip gain over the first N ms) is new code. This is only worth building if listening pair B of #57 shows H2 contributes.

## 4. Libraries and licences (proposals only; no dependency is added by this note)

| Library | Version / date (PyPI, 2026-11-02) | Licence | Use here | Remark |
| --- | --- | --- | --- | --- |
| NumPy | 2.5.4 (2026-10-10); already a dependency (`numpy>=1.26`) | BSD-3-Clause and others | all array work, FFT, Hilbert via FFT | enough for alignment search, zone energies, STFT loss |
| SciPy | 1.18.1 (2026-08-21), BSD, **`requires_python >=3.12`**, Windows wheels 36-37 MB | BSD | `signal.butter/sosfilt/sosfiltfilt/hilbert/correlate`, `optimize.least_squares/curve_fit` | The repo says `requires-python >=3.11`: SciPy 1.18 does not install on 3.11, an older SciPy would be needed there. Which Python the user runs is not recorded in the files read. Everything except the optimiser can be written in NumPy; the optimiser is the part worth buying. |
| pyloudnorm | 0.2.0 (2026-01-04) | MIT | BS.1770 loudness, custom filter classes | needs SciPy; fails for signals shorter than the block size (finding 7), so unusable for 80-400 ms kicks without a smaller block size; a short K-weighted RMS written in NumPy is less work. |
| soundfile | 0.14.0 (2026-06-06), Windows amd64 wheel exists | BSD-3 | reading 24-bit / float / stereo reference WAVs | alternative: standard-library `wave` (PCM only, no 32-bit float); not checked whether `wave` covers WAVE_FORMAT_EXTENSIBLE (not researched). |
| librosa | 1.0.0 (2026-08-11), `>=3.12` | ISC | onset strength, STFT, pYIN | heavy dependency chain; not needed, see [kick-in-tracks](2026-10-29_kick-in-tracks.md) for the long-form reason. |
| DDSP (magenta) | repo state not checked; the arXiv page states no code licence | n/a | prior art for the loss only | TensorFlow-based; the loss (finding 8) is 10 lines of NumPy and does not need the library. Rejected as a dependency by size and by D-005's spirit (learned models are out of the MVP). |

Learned models (neural timbre transfer, differentiable-synth training) are **rejected by D-005 for the MVP; would need the user to reopen it.**

## 5. Objective measures for "more punch"

None of these is a measure of the user's taste. Only PM95 has a published listening-test validation, and on synthetic noise bursts, not kicks.

| Measure | How to compute (deterministic) | What it can show | Limits |
| --- | --- | --- | --- |
| Sub ratio (summation efficiency) | band energy below 100 Hz of the result / sum of the parts (sound-designer definition) | alignment removed cancellation | says nothing about transient or loudness |
| Zone energies, onset-referenced | click 0-10 ms, body 5-80 ms, tail from ~50 ms; rectangular window; kick-gen2 section 4 pitfalls 1, 2, 4 | where the layer adds energy | zone borders are conventions (kick-gen2 F1: rule of thumb) |
| Crest factor of the first 100 ms | peak / RMS(0-100 ms after onset) | density (lower = denser); sound-designer used it | falls when clipping adds density *or* when the body is loud; not "punch" by itself |
| Transient-to-body ratio / rise time | energy 0-10 ms vs 10-100 ms; 10-90 % rise time of the 5 ms RMS envelope | click prominence | no perceptual weighting |
| Spectral flux peak | finding 12 | attack sharpness | sensitive to window and compression constant |
| Weighted transient loudness (PM95-like) | transient separation (QMF + STFT + median filter), 64 Hz-1 kHz octave bands, BS.1770-style filter with 10 dB pre-filter and 1 kHz shelf corner, 280 ms blocks (finding 5) | the one published predictor | The preprint's temporal-weighting equation is garbled in the text read, so the exact model cannot be rebuilt from it alone; the JAES paper (2019) was read as abstract only; Matlab implementation, no code found. A rebuild would be an inference and must be labelled so. |
| Loudness (K-weighted) of the first 100-400 ms | own implementation | rules out "just louder" (#57 H1) | `pyloudnorm` unusable for short kicks (finding 7) |
| Mono / correlation check | sum L+R vs sides; for mono engine output, compare the sub ratio at several polarity/offset values | cancellation risk | engine is mono, so this is the sub ratio again |

Recommendation (inference): the layer feature reports sub ratio, zone energies, peak before normalisation, and the crest/rise measures as **numbers next to the files**, and the listening pairs of #57 decide. PM95 is a candidate for a later issue, not for the first step.

## 6. Experiments run for this note (scratchpad, not in the repo)

All three scripts import `audio_engine` from this worktree (`render_kick` v0.3, presets as in `src/audio_engine/presets/`), 48 kHz, NumPy 2.5.3, SciPy 1.18.1, Linux. They are throw-away; a worker should rewrite them as tests. They show feasibility, not sound quality.

### 6.1 Polarity/offset search (5 preset pairs)
Described in 3.1. Two runs of the search gave the same SHA-256 of the fused samples (determinism of the procedure on this machine; not across machines).

### 6.2 Crossover reconstruction
Described in 3.2. Zero padding 1 s, `padtype=None`: -261.0 (punchy), -257.1 (dense), -259.3 (centre), -258.1 (dark-dry) dB re peak. Default padding: -77.7, -47.4, -62.5, -70.1 dB.

### 6.3 Fitting kick-params to a reference (synthetic references)
The references here are renders of the engine with known random parameters, so this is a **best case**: the model class contains the target (an "inverse crime"). Real references contain things the engine cannot render (sound-designer H3), so these numbers are an upper bound for what a fit can recover.

- **Naive joint fit** (seven parameters at once, `least_squares`, `soft_l1`, DDSP-style multi-scale spectral loss, initial values from `analysis.analyse`, click seed different from the reference's): stopped after 16-40 function evaluations (45 s for 40 evaluations here) with large errors on five references. `pitch_end_hz` came closest (+1.5 to +20.7 %, four of five within 4.3 %), `amp_decay_ms` -9 to +28 %, `pitch_start_hz` up to +/-54 %, `pitch_decay_ms` up to -79 %, `drive` and `click_level` far off. The loss fell only from 30-120 to 16-73 (a unitless sum of squares). Cause not established (candidates: weak identifiability of start pitch against decay, local minimum, click-seed mismatch, early stop of the optimiser); the follow-up experiment below separates part of this.
- **Staged fit** (three references): (1) instantaneous frequency by Hilbert phase of a 700 Hz low-passed signal, exponential fitted with `curve_fit` from 4 ms until the -30 dB point; (2) amplitude decay from the log-slope of a 5 ms RMS envelope; (3) click level / tone / drive by the spectral loss with the body fixed. Result: on two references the body came out within 0.1-0.9 % (pitch start, end, decay) and 0.9-4.5 % (amplitude decay). On the third (true `pitch_decay_ms` 6.5 ms) the start pitch was off by -25 %, the decay by +37 %, the amplitude decay by +21 %, and stage 3 ended at a loss of 9.2 against 0.15 for the true parameters (a local minimum; `drive` true 0.46, found 0.29). Click level was recovered within 6 % (0.426 vs 0.436) when the reference's click seed was known, and within 5-45 % when it was not (0.259 vs 0.275; 0.226 vs 0.436 in the failed case); click tone within 1-10 % with the known seed, and up to 31 % off without it. This agrees with kick-gen2 pitfall "start pitch not established" for fast drops (the first milliseconds mix with the click).
- **What follows (inference):** (a) a staged analysis-first fit is far better than a black-box fit and should be the design; (b) fast pitch drops and heavy drive are the weak cases and need an explicit "low confidence" flag in the report; (c) a real reference's click is noise from an unknown realisation, so the click should be fitted by its *magnitude spectrum and envelope*, never by waveform match, and its seed should be a fixed constant, not a fitted value; (d) the number of evaluations is bounded by the 0.2 s render (about 5 evaluations per second); stage 3 with 40 evaluations took tens of seconds.

## 7. Risks

| Risk | Detail | Handling (proposal) |
| --- | --- | --- |
| Phase cancellation | Sub ratio over 14 preset pairs was 0.51-1.71, and for two variants of the same preset 0.064 to 1.96 (sound-designer, #57 H4). | Always search polarity (+ offset); report the ratio; refuse or flag below a threshold chosen by the user. |
| Clipping / ceiling | Unnormalised sum peaked at 1.5-1.8 (section 3.1). Normalising with a peak ceiling lowers loudness; clipping after summing is a deliberate sound choice (H2). | Report peak before normalising; clip only through the existing oversampled `clip_db` path, never by the 24-bit quantiser. |
| Aliasing from any new nonlinear stage | The engine's clip/drive are oversampled 8x for this reason. | Any attack-only clip reuses `dsp.oversampled`; aliasing test as in kick-gen2 M9 and section 5. |
| Over-aligned transients | Energy maximisation alone can pick an offset that splits the transient (3.2 ms won in three of five pairs). | Offset cap and a transient-alignment constraint; ear check. |
| Zero-phase edge effects | Default `sosfiltfilt` padding gave -47 dB reconstruction error (6.2). | Zero-pad explicitly; test reconstruction as a property over presets and random kicks. |
| Determinism | Same params + seed must give byte-identical output (D-005). `Generator` streams are guaranteed only per build (finding 10); `differential_evolution` is only repeatable with `rng`. FFT and filter results can differ in the last bits across NumPy/SciPy builds (not tested). | Fused output = pure function of the two params sets plus recipe; the *fit* is an authoring tool whose output is a params JSON, and re-rendering that JSON is deterministic. Do not promise bit-identical fits across machines; pin versions in a golden test. |
| Licence of reference samples | Splice FAQ (finding 11): sounds are for creating new works; isolating them as source material for another sample, redistribution and AI training/modelling data are excluded. Whether extracting numeric parameters from a reference counts as modelling is **not answered by the FAQ and is not legal advice**. Kick-gen2 already says "before shipping a preset derived from one specific commercial sample, ask the user", and the issues say only audio content counts, never names. | Keep reference audio and per-reference parameters out of the repo; fits are stored per user outside git; ask the user before any shipped preset derives from a specific commercial sample; prefer the user's **own** recordings/productions as references. The user decides. |
| Reference quality | A reference kick from a loop may carry a cut-off tail or a neighbouring hit (kick-gen2 pitfalls 6, 7); a stereo file needs a mono rule; sample rates differ. | Reuse the first-hit/censoring rules; define mono sum and resampling (resampy ISC / scipy `resample_poly`) in the reader; report `None` instead of guessing. |
| Overfitting "character" | A fit that reproduces a reference closely reproduces its flaws; the user wants *character*, not a copy. | Use the fitted params as a start of a variant family (seeded perturbation), not as the product. |
| Taste claims | "More punch", "better" are not measurable by the listed numbers. | The numbers go beside the files; the decision is the user's listening, as in the issues' plans. |

## 8. Test strategy hints

- **CI can test (deterministic, no Ableton):** same two kicks + recipe give byte-identical fused WAV; sub ratio of the fused result is at least the naive sum's for every pair over seeded random kicks (property test, full contract range); crossover reconstruction `low + high == input` to a stated dB for all presets and random kicks; peak at or below the ceiling after quantising; no NaN; fused kick starts and ends at exact zero (engine invariant); the fit round-trip: render with known params, fit, assert the *body* parameters within stated tolerances and mark `drive`/fast-drop cases as reported low confidence rather than asserting them; fault injection (flip the polarity sign, drop the zero padding, shift the offset by one sample) must turn tests red (CLAUDE.md rule).
- **Independent reference:** do not compare the search against the same function; compare against a brute-force loop written in the test, and the crossover against an analytic response.
- **Needs the user:** whether the fused kick is "more punch" and which of listening pairs A-E of #57 explains the original impression; whether a fitted kick resembles the reference character (#58); the licence question; which kicks are references. Nothing here touches Live, so no `capabilities.json` change.
- **Time per test:** a reference render is 0.2 s, an alignment search over 2 x 241 offsets took seconds here; keep fit tests to a few cases and slow-mark them.

## 9. Implementation proposal (for a later issue; the lead decides)

**Prerequisite (user):** the #57 listening results. If listening pair A (louder single vs pair) shows H1 only, step 1 below alone will not satisfy the wish.

**#57 Layer v1 (audio-engineer, no contract change except the sidecar):**
1. `layer_kicks(a_params, b_params, *, max_offset_ms=5.0, f_split_hz=None)` in `src/audio_engine/` (new module): render both, search polarity x offset for the best sub ratio (section 3.1), normalise to the ceiling. Report object with sub ratio before/after, unnormalised peak, crest of the first 100 ms, chosen polarity/offset. Property and mutation tests as in section 8. Done when: same inputs give identical bytes; sub ratio >= naive for all tested pairs; a preset-pair table is posted in the PR.
2. Sidecar for a fused kick: `contract-change` PR (audio-engineer owns `sample-metadata`): `parameters` for two sets plus recipe, a `features` addition for the report. Not before the format is decided.
3. CLI/tool wrapper and delivery as one WAV (two-WAV delivery for two tracks in Live is Phase 05 scope item 4 and is already covered by `polarity` and `offset_ms`).
4. Optional after listening: crossover split (3.2) and an attack-only clip (3.3) behind explicit parameters, each with its own listening pair.

**#58 Reference steering v1 (audio-engineer, sound-designer reviews measures):**
1. Reference reader (mono sum, resample, first hit, censored-tail flags). Decide `soundfile` vs own reader (section 4).
2. Reference analyser: zone features of the sound-designer's #58 table (sub share, onset share above 1 kHz, tail harmonics, pitch curve with residual of an exponential fit from 5 ms) as a function, tested on engine renders with known parameters.
3. Staged fit (6.3): pitch curve -> amplitude slope -> click/drive with fixed click seed; residual report per zone and confidence flags. Decide `scipy` (section 4) before this step; the first two stages need only `curve_fit`-class optimisation.
4. Per-user preset: store the fitted params JSON outside the repo; variants as seeded perturbations around it.
5. Compare against the sound-designer's hypotheses H2-H4 with the user's 3-5 kicks (the user has to supply them).

**Out of scope for both:** generative or learned audio (D-005), sample layers from third-party audio (M5), anything touching Ableton.

## 10. Open questions only the user can answer

1. Which two kicks, which faders, which master processing in the #3 test (sound-designer step 0), and the results of listening pairs A-E: they decide what #57 must build.
2. May reference kicks from commercial packs be analysed for parameter extraction at all, given the Splice FAQ (finding 11)? Or only the user's own material?
3. Which Python version does the user's Windows installation use (SciPy 1.18 needs 3.12 or newer, the repo allows 3.11)?
4. Are 3-5 reference kicks available outside the repo, and is the goal to approximate them or to be pushed in their direction?

## Implications for the lead

- Summing plus polarity/offset search is cheap and uses fields that exist; but `punchy`-class level loss after normalisation (sound-designer H1) means this may not be the punch the user heard. Wait for listening pairs A and B before sizing #57.
- The sidecar (`parameters` = one object) blocks a fused kick being re-renderable; plan a `contract-change` for it.
- Reference steering needs three decisions that are not technical: licence stance on reference samples, whether to add `scipy`, and which references.
- A pure-NumPy fallback exists for everything except the optimiser; scipy would still be added for `curve_fit`/`least_squares` in practice.
- The `kick-gen2` required-reading note does not yet mention the new facts in 6.2/6.3 (zero padding; naive joint fit fails); the lead may point the future issue here.

**State update proposal (for the PR body):** "Research note `docs/research/2026-11-02_kick-layering-and-reference-steering.md` answers #57/#58: layering = polarity/offset search + optional zero-phase crossover with reported sub ratio; reference steering = staged deterministic fit with per-zone residuals; open: listening pairs of #57, licence stance on references, scipy and Python version."
