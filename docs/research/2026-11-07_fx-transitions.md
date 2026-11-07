# Research: FX transitions (riser, downlifter, impact, noise sweep, reverse crash)

- **Date:** 2026-11-07. Researcher role (instance A, sound and audio; D-018). Sprint W2 workstream F (D-032).
- **Receiving issue:** #476. Docs PR `Closes #476`.
- **Repo state read:** `origin/main` d441b22 — `src/audio_engine/laser_fx.py`, `src/audio_engine/dsp.py` (lines 11-26, 160-172, 241-253), `src/orchestrator/arrangement_timeline.py` (lines 1-37, 158-173), `contracts/laser-params.schema.json`, `contracts/kick-params.schema.json` (`length_beats`), `contracts/sample-metadata.schema.json` (`category` enum), `contracts/capabilities.json` (statuses).
- **Notes this builds on (not re-researched):** [next-category proposal](2026-11-02_next-category-proposal.md) (FX ranked third, section 2), [arrangement planner](2026-10-29_arrangement-planner-sections-energy.md) (5.2-5.4, rules T1/T2), [Goa musicology](2026-11-03_goa-trance-musicology-and-sound.md) (riser 4-16 bars, G11), [Goa reference measurements](2026-11-03_goa-reference-measurements.md) (centroid rises), [mix loudness targets](2026-10-29_mix-loudness-targets.md) (BS.1770 libraries).
- **Not done:** nothing was rendered, measured or listened to. **No claim is made about how anything sounds.** All ranges and defaults below are proposals.

## For workers

- **Possible with our stack?** Yes, as rendered WAV one-shots: seeded noise + swept filter + level ramp + optional tone glide + the laser reverb/echo. No new dependency, no Max for Live (D-001), no generative model (D-005). Delivery uses the only `tested` import path (Session clip slot, `clip_slot.create_audio_clip`); placing a clip at an Arrangement bar is still `unknown`.
- **Route:** (1) `contract-change` PR `fx-params` v0.1 (section 5) + `fx` in the sample-metadata `category` enum; (2) engine `src/audio_engine/fx.py` reusing `laser_fx.low_pass`/`high_pass`/`reverb_wet`/`echo_v2`/`note_ms` and `dsp.substreams`; (3) a small adapter from `derive_timeline` events to fx-params (section 6); (4) GUI via the category registry.
- **Read first:** this note sections 3-6; `laser_fx.py` lines 214-260 (sweep filter bank) and 338-389 (reverb); `arrangement_timeline.py` `_events`.
- **Effort:** contract small; engine medium (long files, band-pass sweep, loudness measurement are new); planner adapter small.
- **Blockers:** none for the contract. For engine acceptance: no BS.1770 loudness code exists in `src/` (grep 2026-11-07), so "level vs kick" cannot be measured until it is added (section 4).
- **Open questions only the user can answer:** U1-U8 in section 8 (lengths, gap behaviour, level vs kick, noise colour, tone layer, reverse crash, Goa vs techno defaults, tail into the drop).

## 1. Findings

Confidence: **high** = official documentation or own repo code; **medium** = magazine tutorial or community source (labelled); **inference** = my reasoning, not a source statement.

| # | Finding | Confidence | Source (opened 2026-11-07 unless noted) |
| --- | --- | --- | --- |
| F1 | Live 12 auto-warps long samples by default ("Auto-Warp Long Samples" is on); a long sample gets a warp marker on the first beat of each bar. Live decides short vs long at import; the manual gives **no threshold**. | high | [Live 12 manual, ch. 9, sections 9.2.1 and 9.2.5](https://www.ableton.com/en/live-manual/12/audio-clips-tempo-and-warping) |
| F2 | For short samples the "Loop/Warp Short Samples" default is **Auto**; Live assumes a well-cut loop of 1, 2, 4, 8 or 16 bars and sets the tempo from that. With Warp off a sample plays at its original tempo, independent of the Set tempo. | high | same, 9.2.1 and 9.2.4.1 |
| F3 | Whether a created clip is warped or looped, and its warp/loop properties, are not `tested` capabilities (only `clip_slot.create_audio_clip`, `clip.file_path.get` and a few song/track reads are). | high | `contracts/capabilities.json` @ d441b22 |
| F4 | White-noise riser recipe: white noise through a band-pass (or HP + LP in series), cutoff automated low → high over the rise; resonance adds a pitched whistle and thins the bass; low shelf cut, high shelf boost; big hall reverb about 3 s. No Hz, bar or dB values given. | medium (magazine) | [Attack Magazine, Essential transition FX masterclass p. 1 (2015-08-07)](https://www.attackmagazine.com/technique/tutorials/essential-transition-fx-technique-masterclass/) |
| F5 | Same recipe family: stereo white noise, HP + LP in series, cutoffs automated up or down; a little distortion to squash dynamics; optional flanger/phaser/chorus. No numbers. | medium (magazine) | [MusicRadar / Computer Music, basic white noise filter sweep (2012-11-06)](https://musicradar.com/tuition/tech/how-to-produce-a-basic-white-noise-filter-sweep-566529) |
| F6 | Noise sweep: resonance max, low-pass swept min → max, fast amplitude modulation on the noise. Riser: square oscillator with a pitch LFO whose depth fades in over 8-10 s. Boom/zap impact: self-oscillating filter swept sharply down by an envelope plus heavy reverb. No sub frequency, semitones or lengths given. Downlifter and reverse cymbal not covered. | medium (magazine) | [MusicRadar / Computer Music, 10 classic synth FX (2022-05-24)](https://www.musicradar.com/tuition/tech/10-classic-synth-fx-and-how-to-create-them-634904) |
| F7 | Reverse crash: reverse a crash sample (longer decay = longer rise), align its **end** to the bar line; plate reverb about 30 % mix, 1 s decay. | medium (magazine) | [Attack Magazine masterclass p. 5 (2015-08-07)](https://www.attackmagazine.com/technique/tutorials/essential-transition-fx-technique-masterclass/5/) |
| F8 | Drop crash/impact: white noise from the drop start with its volume faded out over **4 or 8 bars**, low cut at **1000 Hz**, small boost at **7000 Hz**; crashes and the noise may be sidechained to the kick; a short crash of about one beat for a harder hit; "hangover FX": cut the riser at the drop but let its reverb/delay tail run into the next section. | medium (magazine) | [MusicRadar / Computer Music, 4 ways to maximise the impact of your drop (2017-06-28)](https://www.musicradar.com/how-to/4-ways-to-maximise-the-impact-of-your-drop-with-crashes-and-fx) |
| F9 | Builds are 8, 16 or 32 bars; content riser, snare roll, filters opening; risers ramp up, downlifters are their opposite; tempo about 130-150 BPM. | medium | planner note C5-C7 (sources opened 2026-10-29) |
| F10 | In three Goa reference mixes the 500 Hz-10 kHz centroid rises 0.6-1.3 octaves over 4-16 bars, then resets. Measured on the whole mix, **not** on one FX or filter. | medium (own measurement on 3 tracks) | [Goa reference measurements, section 5 and line 263](2026-11-03_goa-reference-measurements.md) |
| F11 | Prior-art loop levels vs the kick loop: impact -7 LU, riser -10 LU; the artifact itself says there is no published standard. | low (unpublished artifact) | [next-category proposal, section 1](2026-11-02_next-category-proposal.md) |
| F12 | EBU loudness: momentary = 0.4 s sliding rectangular window, short-term = 3 s, both ungated; integrated loudness gated per BS.1770 (-70 LUFS absolute, -10 LU relative, 400 ms blocks with 75 % overlap). | high | [EBU Tech 3341 v4 (Nov 2023)](https://tech.ebu.ch/docs/tech/tech3341.pdf) |
| F13 | The timeline already emits the events: `riser` over each whole build (length = build length), `impact` with length 0 on bar 1 of every drop and of a groove after a breakdown, `downlifter` of 4 beats on bar 1 of a break/breakdown (_Interpretation_ in that module), `pre_drop_gap` ending at the drop. All in integer beats. | high (code) | `src/orchestrator/arrangement_timeline.py` lines 29-31, 158-173 @ d441b22 |
| F14 | No source opened today gives numeric cutoff ranges, sweep curves or lengths for a riser/downlifter beyond F8 and F9. Every Hz value in section 5 is therefore a proposal. | high (absence in the sources read) | F4-F8 |

## 2. What each transition is (paraphrase of F4-F9; parameters are inference)

| Type | Where (planner) | Building blocks | Defining movement |
| --- | --- | --- | --- |
| **Riser** (uplifter) | whole `build`, ends at the drop's bar 1 (T2) | noise → band-pass (or HP+LP), optional tone layer, reverb | cutoff up, level up, optional pitch up (F4, F6) |
| **Noise sweep** | inside builds or at phrase ends | noise → resonant LP or HP | one cutoff movement, up or down (F5, F6) |
| **Downlifter** | bar 1 of `break`/`breakdown` | noise (and/or tone) → filter | cutoff down, level down (F9: "opposite of a riser") |
| **Impact / boom** | bar 1 of `drop`, groove after breakdown | short noise burst + low tone with fast downward glide + long reverb | sharp attack, pitch drop, long tail (F6, F8) |
| **Reverse crash** | last 1-2 bars before a boundary | synthetic metallic cymbal (hat blocks) rendered, then reversed | swell that ends exactly on the bar line (F7) |
| **Noise crash** (drop wash) | from the drop's bar 1 | high-passed noise (1 kHz low cut, F8) | level falls over 4-8 bars (F8) |

## 3. Tempo sync (arithmetic, 4/4)

One bar = 240 / BPM seconds. Computed 2026-11-07:

| BPM | 1 bar (s) | 4 bars | 8 bars | 16 bars | 32 bars | 32 bars at 48 kHz (frames) |
| --- | --- | --- | --- | --- | --- | --- |
| 135 | 1.778 | 7.11 | 14.22 | 28.44 | 56.89 | 2 730 667 |
| 140 | 1.714 | 6.86 | 13.71 | 27.43 | 54.86 | 2 633 143 |
| 145 | 1.655 | 6.62 | 13.24 | 26.48 | 52.97 | 2 542 345 |
| 150 | 1.600 | 6.40 | 12.80 | 25.60 | 51.20 | 2 457 600 |

Proposals (inference):
- **Length in beats, not ms**, as in kick v0.3 `length_beats`: `length_ms = length_beats * 60000 / bpm`, frames `n = round(length_ms * sr / 1000)`. A riser must end within one sample of the drop: the musical length (`length_beats`) and the file length (`length_beats + tail_beats`) are separate, and the sidecar records both so a placer knows where the boundary is.
- **Anchor rule.** Riser, sweep, downlifter, impact, noise crash: the file starts on the event's start beat. Reverse crash: the file **ends** on the boundary (F7), so it starts at boundary − `length_beats`; nothing may follow the boundary (no tail, it is reversed).
- Echo time from `laser_fx.note_ms(note, bpm)` (already supports `1/8`, `1/8T`, `1/8D`).
- Live side: render at the Set's tempo. F1/F2 mean Live may warp the file at import with its own tempo guess; a noise riser has no transients, so the guess may be wrong (inference, **not tested**). Experiment for the user's machine in section 7.

## 4. Measurable targets (quantities and methods; ranges are proposals)

| Quantity | Method (deterministic, NumPy) | Proposal | Basis |
| --- | --- | --- | --- |
| Length | frames of the WAV vs `round((length_beats + tail_beats) * 60 / bpm * sr)` | exact | arithmetic |
| Boundary energy (riser) | RMS of the last 10 ms before `length_beats` vs the peak 400 ms RMS | within 6 dB of the peak (riser peaks at the boundary unless `cut_beats` > 0) | inference |
| Sweep range | STFT spectral centroid (or band-energy peak) in 1/4-bar frames; slope in octaves from first to last quarter of `length_beats` | riser +2 to +5 octaves; downlifter the mirror | inference (F14); F10 is a mix, not an FX |
| Sweep shape | octaves vs normalised time t; fit exponent of `t ^ curve` | matches `sweep_curve` ± 0.2 | inference; formula reused from laser rule (2) |
| Level ramp | momentary loudness (0.4 s, F12) at start and end | riser end − start ≥ 12 LU at default | inference |
| Loudness vs kick | max short-term (3 s) loudness of the FX vs short-term loudness of a 4-bar loop of the user's default kick at the same peak ceiling | riser -10 LU, impact -7 LU as **starting points only** | F11 (low confidence) |
| Impact pitch drop | zero-crossing / autocorrelation pitch of the tone layer over the first 500 ms (existing `analysis.zero_crossing_frequency` on windows) | start 80-200 Hz → end 30-60 Hz | inference; no source gave Hz (F6) |
| Low-end leak | `analysis.lf_leak_db` below the high-pass | ≤ -24 dB below 100 Hz for riser/sweep/crash | inference (keeps the kick region clear; F4 "thins the bass") |
| Determinism | sha256 of the WAV, same params + seed, Ubuntu and Windows CI | byte-identical | CLAUDE.md rule |

BS.1770 K-weighting is not in `src/` (grep for `lufs`, `k-weight`, `bs.1770` on 2026-11-07: no match). The mix note lists `pyloudnorm` 0.2.0 (MIT) as an option (opened 2026-10-29); a NumPy K-weighting with the two BS.1770 filter stages avoids a new dependency (inference; the BS.1770 text was not reopened today). Test vectors: the EBU Tech 3341 compliance set, if the implementer wants an independent reference.

## 5. Contract proposal: `fx-params` v0.1 (for the `contract-change` issue; the owner decides)

Conventions copied from `laser-params`: out-of-range values are rejected, never clamped; only `schema_version` and `seed` (and `bpm`, see below) are required; omitted fields take the defaults; a field not used by a `kind` has no effect (like laser `glitch_steps`). Stereo output `(n, 2)`. All values are **proposals, not measured against any reference**.

### 5.1 Common fields

| Field | Type / range | Default | Meaning |
| --- | --- | --- | --- |
| `schema_version` | `"0.1"` | — | required |
| `seed` | int 0 … 2^32-1 | — | required; noise L/R and layers from `dsp.substreams` (one stream per layer, as hat/laser) |
| `bpm` | 60-200 | — | **required** (all lengths are in beats) |
| `kind` | `riser`, `downlifter`, `sweep`, `impact`, `noise_crash`, `reverse_crash` | `riser` | sets the anchor rule (section 3) and which fields are used |
| `length_beats` | number 1-128, multiple of 0.25 | per kind (5.3) | musical length; derived `length_ms` must be ≤ 64000 (32 bars fit down to 120 BPM) |
| `tail_beats` | 0-16 | per kind | reverb/echo tail after `length_beats` ("hangover FX", F8); must be 0 for `reverse_crash` |
| `cut_beats` | 0-8, multiple of 0.25 | 0 | dry signal muted in the last `cut_beats` before the boundary (riser into a `pre_drop_gap`); the tail still runs (U2) |
| `variants` | 1-8 | 1 | as other categories |
| `sample_rate` / `bit_depth` | 44100 / 48000; 16 / 24 | 48000 / 24 | as laser |
| `peak_ceiling_dbfs` | -12 … -0.1 | -1.0 | peak normalisation **after** the level ramp, so the ramp shape survives |
| `stereo_width` | 0-1 | 0.6 | 0 = mono noise; 1 = independent L/R noise streams |
| `drive` | 0-1 | 0 | soft saturation (F5 "squash dynamics") |
| `pump_depth` | 0-1 | 0 | level dip on every quarter note, phase-locked to beat 1 (sidechain-like, F8); 0 = off |

### 5.2 Noise, filter, level, tone, space

| Field | Range | Default | Notes |
| --- | --- | --- | --- |
| `noise_level` | 0-1 | 1 | |
| `noise_color` | `white`, `pink` | `white` | pink is an inference option (no source today); U4 |
| `filter_mode` | `bp`, `lp`, `hp`, `hp_lp` | `bp` | F4, F5 |
| `cutoff_start_hz` | 40-20000 | per kind | for `bp`: centre; for `hp_lp`: the HP corner, LP at `cutoff_* × lp_ratio` |
| `cutoff_end_hz` | 40-20000 | per kind | may be above or below start |
| `lp_ratio` | 1.5-16 | 4 | `hp_lp` only |
| `filter_q` | 0.5-12 | 1.2 | band-pass Q / resonance stage Q; > 4 = audible whistle per F4 (claim of the source, not ours) |
| `sweep_curve` | 0.2-6 | 1.0 | log-frequency position = `t ^ sweep_curve` (laser rule 2 formula); > 1 = late rise |
| `level_start_db` / `level_end_db` | -60 … 0 | per kind | dB linear in `t ^ level_curve` |
| `level_curve` | 0.2-6 | 1.0 | |
| `tone_level` | 0-1 | 0 (riser), 1 (impact) | tonal layer off at 0 |
| `tone_wave` | `sine`, `saw`, `square` | `sine` | band-limited as laser `plasma` |
| `tone_start_hz` / `tone_end_hz` | 20-4000 | per kind | exponential glide |
| `tone_glide_beats` | 0.05-128 | = `length_beats` | impact uses a short glide |
| `tone_decay_beats` | 0.25-32 | per kind | impact / noise crash: -60 dB decay (same definition as laser `decay_ms`) |
| `reverb_mix` | 0-1 | per kind | `laser_fx.reverb_wet` |
| `reverb_decay_ms`, `reverb_size`, `reverb_predelay_ms`, `reverb_damp_hz`, `reverb_width` | laser v0.2 ranges (`reverb_decay_ms` 100-6000 there), except `reverb_decay_ms` up to 8000 | laser defaults, decay 3000 | F4 "about 3 s"; values above 6000 are outside what the laser contract validated |
| `echo_mix`, `echo_feedback`, `echo_damp_hz`, `echo_pingpong` | laser v0.2 ranges (`echo_damp_hz` 500-20000) | 0, 0.4, 6000, 0 | `laser_fx.echo_v2` |
| `echo_note` | `1/4`, `1/8`, `1/8D`, `1/8T`, `1/16` | `1/8D` | via `note_ms` (tempo-synced) |

### 5.3 Per-kind defaults (starting points, all proposals)

| kind | `length_beats` | `tail_beats` | filter | cutoff start → end (Hz) | level start → end (dB) | tone | reverb_mix |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `riser` | 64 (16 bars) | 4 | `bp` | 300 → 9000 (≈ 4.9 oct), curve 1.5 | -36 → 0 | off | 0.3 |
| `sweep` | 16 | 2 | `lp`, Q 4 | 200 → 12000 | -6 → 0 | off | 0.2 |
| `downlifter` | 8 | 4 | `bp` | 8000 → 200, curve 0.7 | 0 → -36 | optional saw 400 → 60 Hz | 0.35 |
| `impact` | 8 | 8 | `hp` 30 Hz | static | noise burst 0 dB, decays in 0.25 beat | sine 150 → 40 Hz, glide 0.5 beat, decay 6 beats | 0.4 |
| `noise_crash` | 16 (4 bars) | 4 | `hp` | 1000 static (F8) | 0 → -60 over `length_beats` | off | 0.3 |
| `reverse_crash` | 4 | 0 (rule) | metallic bank (hat `square_bank`) + noise, `hp` 3000 | static | swell (reversed exponential decay) | off | 0.3 (applied before reversing) |

Only `noise_crash` (1000 Hz, 4-8 bars) and the riser/downlifter lengths (8/16/32 bars, F9) rest on a source; every other number is a placeholder for the audio-engineer's measurement and the user's ears.

Sidecar: `category: "fx"` (new enum value; own engine name `abeltongod-audio-engine-fx`, D-025) plus derived `length_ms`, `boundary_frame` (frame index of the musical boundary) and `anchor` (`start` or `end`).

## 6. Fit with the arrangement planner (adapter proposal)

| Timeline event (F13) | fx-params | Derived from the plan |
| --- | --- | --- |
| `riser` (beat, length L) | `kind: riser`, `length_beats = L`, `cut_beats = pre_drop_gap` only if U2 = "silent gap" | `level_start_db`/`cutoff_start_hz` from the energy at build start, end values from the energy at the drop's bar 1 ("level and brightness follow the energy ramp", planner 5.3). Mapping is a user setting (D-024) |
| `impact` (length 0) | `kind: impact`, file starts on the event beat | none; `tail_beats` decides how long it rings |
| `downlifter` (4 beats) | `kind: downlifter`, `length_beats = 4` | the event length is itself an _Interpretation_; the default 8 above is longer, the adapter should pass the event's value |
| `pre_drop_gap` | no file | informs `cut_beats` |
| (new, optional) phrase-end reverse crash | `kind: reverse_crash`, anchor `end` | **not** emitted by `derive_timeline` today; adding it is a planner change (orchestrator-engineer, own issue) |

Delivery: the plan exports files only (D-032 workstream A). With today's `tested` capabilities a rendered FX can be put into a **Session** clip slot; positioning at Arrangement bars needs the `unknown` AbletonOSC extension (planner note 5.5, E5). The user drags clips to bars by hand until then.

## 7. Pitfalls and test strategy

**Pitfalls (inference unless a source is named):**
1. **Live warps the import (F1, F2).** A 16-bar riser counts as long (probably; threshold not documented) and is auto-warped; if Live's tempo guess differs from the render tempo, the riser is stretched and no longer ends on the drop. A short impact under "Auto" may be treated as a loop. Clip warp/loop properties are not settable through a `tested` capability (F3).
2. **Filter sweep by blended static banks.** `laser_fx.low_pass` blends neighbouring fixed low-passes on a 3-steps-per-octave grid. With a resonant or band-pass filter, a blend of two peaks a third of an octave apart is not one moving peak (inference; not measured). A riser at Q 4-12 may need a finer grid (cost grows with grid size) or a time-varying biquad (pure-Python loop in `dsp._biquad`, about 1 µs per sample per the synthesis note: ≈ 2.7 s per pass for 32 bars).
3. **No band-pass in `laser_fx.filter_sections`** (lp and hp only); `dsp.biquad_bandpass` is a per-sample Python loop. `hp_lp` mode reuses what exists.
4. **File size and cost.** 32 bars at 135 BPM, 48 kHz, stereo float64 = 2.73 M frames ≈ 44 MB per buffer; the FFT filter path pads to the next fast size. Runtime and memory are **not measured**; the FDN reverb runs a block loop with the shortest delay as block size (a few hundred samples), so a 60 s file means thousands of iterations.
5. **Peak normalisation vs level ramp.** Normalising after the ramp keeps the shape but moves the absolute level; "level vs kick" must be measured on the final file.
6. **Cross-platform bytes.** The laser echo needed integer-reduced phases to stay byte-identical across CI machines (`laser_fx.py` comments at lines 264-266 and 298-301). Long FFTs with large phase arguments carry the same risk.
7. **Seeds and layers.** New layers must take new `substreams` indices, or adding a layer later changes existing noise (dsp.py lines 241-253 rule).

**CI can test:** schema valid/invalid cases; exact frame counts per BPM over the full range (property test); anchor rules (`reverse_crash` energy in the last 10 ms, zero tail); centroid slope sign and size; level-ramp monotonicity in 0.4 s windows; low-end leak; determinism on Ubuntu and Windows; adapter mapping from `derive_timeline` fixtures T1-T3; fault injection (e.g. `bpm × 1.02` must break the frame-count test).

**Only the user's machine:** experiment X1 — set the Set tempo to the render BPM, import a 16-bar riser and a 2-bar impact into Session slots, read Warp on/off, loop on/off and the detected BPM in the clip view, and drag the riser so it ends at a bar line; report whether its end sits on the line. X2 — repeat with "Auto-Warp Long Samples" off. **Only the user's ears:** everything in section 8.

## 8. What only the user can judge

| ID | Question | Default proposed |
| --- | --- | --- |
| U1 | Riser length per build (4 / 8 / 16 / 32 bars) and whether it spans the whole build | whole build (planner T2) |
| U2 | Riser during the pre-drop gap: keep playing, or silent with only its tail (`cut_beats`) | keep playing |
| U3 | Level of riser / impact vs kick | -10 / -7 LU (low-confidence prior art) |
| U4 | White or pink noise; band-pass vs HP+LP | white, band-pass |
| U5 | Tonal layer (pitched rise) on risers, or noise only | noise only |
| U6 | Synthetic reverse crash: wanted at all, and where (every boundary or only before drops) | not emitted by default |
| U7 | Techno vs Goa defaults (Goa builds 24-32 bars before the kick in two reference tracks, F10 note) | techno defaults, Goa as presets |
| U8 | Tail into the drop ("hangover", F8): length, or dry cut | 4 beats |

## 9. Implications for the lead

1. Open a `contract-change` issue for `fx-params` v0.1 (owner audio-engineer) with sections 5.1-5.3 as input, plus the `fx` value in the sample-metadata `category` enum.
2. Engine issue (audio-engineer): first measure pitfall 2 (blended-bank band-pass vs a reference time-varying filter) and pitfall 4 (runtime/memory for 32 bars at 135 BPM on the CI runners) before fixing the filter design.
3. Small BS.1770 loudness helper (NumPy, no new dependency) as its own issue; it also serves the planned mix measurements.
4. Bridge-engineer issue for X1/X2 (warp behaviour on import) before any claim that an imported riser ends on the drop; mark clip warp/loop as `unknown` until tested.
5. Planner adapter (orchestrator-engineer) only after the contract merges; a `reverse_crash` event would be a separate planner change.

## Sources (all opened 2026-11-07)

- Ableton, [Live 12 Reference Manual, ch. 9 Audio Clips, Tempo, and Warping](https://www.ableton.com/en/live-manual/12/audio-clips-tempo-and-warping) (sections 9.2.1, 9.2.4.1, 9.2.5).
- EBU, [Tech 3341 v4, Loudness Metering (Nov 2023)](https://tech.ebu.ch/docs/tech/tech3341.pdf).
- Attack Magazine, [Essential transition FX masterclass, p. 1](https://www.attackmagazine.com/technique/tutorials/essential-transition-fx-technique-masterclass/) and [p. 5](https://www.attackmagazine.com/technique/tutorials/essential-transition-fx-technique-masterclass/5/) (2015-08-07).
- MusicRadar / Computer Music, [Basic white noise filter sweep](https://musicradar.com/tuition/tech/how-to-produce-a-basic-white-noise-filter-sweep-566529) (2012-11-06); [10 classic synth FX](https://www.musicradar.com/tuition/tech/10-classic-synth-fx-and-how-to-create-them-634904) (2022-05-24); [4 ways to maximise the impact of your drop](https://www.musicradar.com/how-to/4-ways-to-maximise-the-impact-of-your-drop-with-crashes-and-fx) (2017-06-28).
- Not opened (permission request timed out): Wikipedia "Shepard tone"; a Shepard-style endless riser is therefore not proposed here.
