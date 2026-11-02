# Clap: experimental and distorted options (C4, step 1: design note)

_Date: 2026-11-02 · Role: sound-designer · Issue: #275 (step 1, docs only) · Status: **proposal and measurements, not a result.** Nothing here was heard. Numbers describe signals only; "harsher", "more extreme", "usable" are for the user's ear. Every field and value below is a **PROPOSAL ONLY**; `contracts/clap-params.schema.json` is untouched (v0.1 stays as is), and the baseline voices `default/short/long/bright` and their golden hashes are not touched by anything here._

User request (2026-11-02 14:14, quoted from #275): "Zu den claps gefällt mir gut als generische baseline. Aber es muss auch einfach krassere optionen geben für verschiedene projekte. Richtung experimentell, distorted usw einfach offene möglichkeit meine kreativität da auszutoben."

## Short version

1. The baseline stays the generic clap. Extra controls are **optional, off by default, and skipped entirely when off**, so a v0.1 document (and every v0.2 document without the new fields) renders the same bytes as today. This is an additive v0.2 (section 4).
2. **Recommended v0.2 fields (PROPOSAL ONLY):** `fold`, `crush`, `rate_div`, `ring_hz` + `ring_mix`, `comb_hz` + `comb_fb`, `gate_ms`, `tail_reverse`. Existing `drive` (v0.1) stays and is the soft-saturation control. A hard clip like the kick's `clip_db` is a candidate but not recommended first (section 3, aliasing). A second noise layer is **not** a new field (use the existing "sum of two renders" convention, C3 item C5).
3. **Measured on the engine's default voice (seed 1):** v0.1 `drive` already moves RMS up by 10.9 dB at the same peak (-22.9 to -12.0 dBFS RMS at drive 1.0). Loudness jumps are therefore the main risk of every distortion option, not clipping at the ceiling: the peak ceiling holds by construction (`_normalise`), RMS and crest factor do not (section 2, table L).
4. **Aliasing, measured:** at the engine's 8x oversampling, smooth curves (tanh, sine fold) leave an error of -88 to -102 dB against a 32x reference. Curves with a corner (hard clip at +36 dB gain, triangle fold) leave -55 to -63 dB at 8x. Bit and rate reduction alias by design (that is the effect), so they are measured as intended energy, not as an error (section 3).
5. **One of the user's own references is already "distorted"** (`ZEN_RUPT_clap_distorted`, from the reference analysis note). Its peak-to-RMS gap (12.8 dB) equals the engine's v0.1 `drive` 0.6 render (12.8 dB), but its HF share (0.116) and centroid (3084 Hz) are above anything v0.1 `drive` reached on the default band-pass (0.044 / 2561 Hz at 0.6; 0.051 / 2680 Hz at 1.0). Hypothesis: the v0.1 range covers that reference's loudness, not its brightness (section 5, H-X1). Windows differ (reference: Welch of 300 ms; engine render: whole file), so this is a rough comparison.
6. A listening-test skeleton for the extreme set (7 items, about 12 minutes, level-matched) is in section 7.

## 1. Read and method

Read: issue #275 body; `contracts/clap-params.schema.json` (v0.1); `src/audio_engine/clap.py` (signal path: band-pass, envelope, high-pass, room, drive, fade-out, mean removal, ceiling); `src/audio_engine/dsp.py` (`oversampled`, `kaiser_lowpass`); `kick.py` (`_drive`, `_hard_clip`, DRIVE constants: 8x, Kaiser transition 0.08, beta 10, tanh gain g = 10 x drive^0.8); `kick-params` `clip_db` text; `2026-11-02_clap-targets-and-listening-plan.md` (C3: styles, H1-H11, listening format); `2026-11-02_clap-reference-analysis.md` (13 reference one-shots, P-notes); `2026-11-02_snare-targets.md` and `2026-11-02_snare-rim-and-sub-bass-design.md` for structure.

Measurements: two scripts in my scratchpad, not in the repo:
`/tmp/claude-0/-home-claude/8969c227-1cdb-551a-898a-46125f9a8cff/scratchpad/xm.py` (features) and `.../xm2.py` (aliasing vs oversampling factor). Run as `cd /tmp && python3 -I <script>` with `sys.path` pointing at `src/` of branch `phase-06/275-clap-experimental`. NumPy 2.5.3, SciPy 1.18.1. Input is the engine's own render (`audio_engine.clap.render_clap`), 48 kHz, drive 0, normalised to peak 1 before the test curve, then renormalised to -0.3 dBFS. The new blocks are **my own NumPy prototypes, not engine code**; the engine does not have them. Features come from the engine helpers `analyse_nonpitched` (centroid, `hf_share_8k`, `t60_ms`), `hf_share` (> 12 kHz) and `lf_leak_db`; RMS, crest, sub-150 Hz share, mean (DC) and "fraction of samples within 0.1 % of the peak" (`atclip`) are my own one-line measures.

Seed note: the preset files carry their own seed (`default` = 2001); rows marked "seed 1" use `{"schema_version":"0.1","seed":1}`. The two differ in absolute RMS by 1.3 dB (-21.6 vs -22.9), so compare only inside one table.

Limit: one seed per row, no spread, a single voice (default). Numbers show direction and size, not a range; the audio-engineer repeats them over seeds 1-8 on the real blocks.

## 2. Options: what each moves, proposed range, how it is measured, risk

All measured values: default voice, seed 1 unless noted, renormalised to -0.3 dBFS. Table L = loudness and spectrum; "RMS" is dBFS over the whole file, "crest" = peak minus RMS in dB.

**Table L, base and existing v0.1 `drive` (engine):**

| Setting | RMS dBFS | crest dB | centroid Hz | hf_share_8k | t60 ms | sub-150 Hz share |
| --- | --- | --- | --- | --- | --- | --- |
| drive 0 | -22.9 | 22.6 | 2341 | 0.031 | 166 | 0.0000 |
| drive 0.3 | -14.9 | 14.6 | 2438 | 0.037 | 313 | 0.0008 |
| drive 0.6 | -13.1 | 12.8 | 2561 | 0.044 | 357 | 0.0017 |
| drive 1.0 | -12.0 | 11.7 | 2680 | 0.051 | 372 | 0.0023 |

Reading: `drive` from 0 to 1 raises RMS by 10.9 dB at equal peak, lowers crest by 10.9 dB, and **lengthens `t60_ms` from 166 to 372 ms** (the tail is lifted towards the peak; the same effect the analysis docstring describes for the kick's decay with drive). Because `t60_ms` is relative to the peak, a "longer t60" after distortion is a level effect, not a longer sound.

### 2.1 `fold` (sine wave folding), range proposal 0 to 1

Quantity moved: harmonic density, HF share, centroid. Mapping proposal (hypothesis): fold factor k = 1 + 15 x `fold` applied as sin(k pi u / 2) on the peak-normalised signal; 0 = stage skipped. Measured (8x oversampled, renormalised):

| Curve | RMS | crest | centroid Hz | hf_share_8k | hf12 | sub-150 | oversampling error at 8x (re 32x) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sine fold k=2 | -15.0 | 14.7 | 2387 | 0.033 | 0.011 | 0.0026 | not measured (naive-vs-8x difference: -40.2 dB) |
| sine fold k=4 | -13.7 | 13.4 | 3278 | 0.082 | 0.032 | 0.0071 | -101.6 dB |
| sine fold k=8 | -13.0 | 12.7 | 4500 | 0.180 | 0.087 | 0.0055 | -91.8 dB |
| sine fold k=16 | not in table L | | | | | | -88.6 dB |

Risk: k=8 puts 18 % of the energy above 8 kHz (clean default voice: 2.5 %). DC before the existing `_remove_mean` was not measured for `fold` (my prototype subtracted the mean before measuring). Hypothesis: `t60_ms` becomes `null` (does not fall 60 dB inside the file) for k ≥ 4 because the tail is lifted; seen for k=4 and k=8, section 6 P-X1.

### 2.2 `crush` (bit reduction), range proposal 0 to 1

Quantity moved: noise floor (quantisation error), HF share, tail character (low-level tail becomes stepped). Mapping proposal: bits = 12 - 9 x `crush` (12 down to 3), 0 = skipped. The error is the effect, so aliasing is not an error here. Measured (round-to-nearest, no dither, input peak 1):

| bits | SNR dB (whole file) | centroid Hz | hf_share_8k | t60 ms | RMS |
| --- | --- | --- | --- | --- | --- |
| 12 | 58.4 | 2228 | 0.025 | 169 | -21.6 |
| 8 | 35.8 | 2230 | 0.026 | 141 | -21.6 |
| 6 | 24.7 | 2258 | 0.027 | 97 | -21.6 |
| 4 | 14.1 | 2511 | 0.045 | 49 | -21.5 |
| 3 | 9.3 | 2949 | 0.071 | 41 | -21.4 |

Reading: the effect on level is nil (RMS within 0.2 dB); it is a **tail and brightness effect**: `t60_ms` falls from 169 to 41 ms because the tail drops under half a quantisation step and becomes silence (the tail is gated by the quantiser). Mean: up to 1.2e-4 at 4 bits (before the existing `_remove_mean`). Hypothesis: with no dither, a tail under 1 LSB turns to digital silence plus idling; the audio-engineer decides whether to dither (deterministic seeded dither would stay byte-identical).

### 2.3 `rate_div` (sample-and-hold rate reduction), integer 1 to 16, 1 = off

Quantity moved: HF imaging/aliasing energy. Measured (hold factor f at 48 kHz; "energy above new Nyquist" in the input vs after the hold):

| f | new Nyquist Hz | share above it, input | share above it, output | centroid Hz | hf_share_8k | sub-150 |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | 12000 | 0.007 | 0.031 | 2584 | 0.046 | 0.0000 |
| 4 | 6000 | 0.048 | 0.096 | 2806 | 0.074 | 0.0005 |
| 8 | 3000 | 0.167 | 0.221 | 2854 | 0.076 | 0.0024 |
| 16 | 1500 | 0.516 | 0.345 | 2104 | 0.045 | 0.0187 |

Reading: images of the band-passed noise are created above the held rate. At f=16 the held rate is 3 kHz, below the band-pass centre, so the spectrum folds into the low end (sub-150 Hz share 1.9 %, mean up to 5.4e-4): the existing high-pass is **before** this stage in the current chain, so a rate-reduction stage must sit **before** the `hp_hz` high-pass (proposal for the order, section 4) or have its own post-filter.

### 2.4 `ring_hz` + `ring_mix` (ring modulation), `ring_hz` 20 to 3000, `ring_mix` 0 to 1, 0 = off

Quantity moved: sideband spectrum (f ± carrier), centroid, sub content. Carrier = sine, phase 0 (so no click at the start; determinism needs no randomness). Measured (mix 1.0; `lf_leak_dB` re the v0.1 default `hp_hz` 450):

| carrier Hz | RMS | centroid Hz | sub-150 share | lf_leak (below 225 Hz) dB | mean |
| --- | --- | --- | --- | --- | --- |
| 50 | -24.2 | 2168 | 0.0000 | -44.6 | 1e-6 |
| 150 | -24.5 | 2261 | 0.0001 | -35.4 | -1.3e-5 |
| 400 | -22.8 | 2217 | 0.0022 | -24.3 | 5.1e-4 |
| 1000 | -24.1 | 2207 | **0.0670** | -9.5 | 2.4e-3 |
| 3000 | -23.5 | 3376 | 0.0180 | -15.9 | 9.8e-5 |

Reading: carriers ≥ 400 Hz create difference products below the baseline's high-pass (at 1000 Hz, 6.7 % of the energy is under 150 Hz, which is the kick's region; baseline: 0.0000). So the stage belongs **before** the `hp_hz` high-pass (the same fix as 2.3), and the metric `sub-150 share` should be a pass/fail check in the engine tests. `t60_ms` for `ring_mix` 0.5 read 10.6 ms (carrier 50) and 30.3 ms (carrier 150), which is a measurement artefact of nulls in the envelope, not a short sound (P-X2).

### 2.5 `comb_hz` + `comb_fb` (feedback comb / formant colouring), `comb_hz` 100 to 4000, `comb_fb` 0 to 0.95, fb 0 = off

Quantity moved: spectral comb peaks at multiples of `comb_hz`; added ring in the tail. Delay = round(sr / comb_hz) samples; stable for `comb_fb` < 1. Measured raw peak gain of the stage (before renormalisation) and result:

| comb_hz / fb | raw peak gain dB | RMS | centroid Hz | t60 ms |
| --- | --- | --- | --- | --- |
| 200 / 0.5 | +0.5 | -21.0 | 2208 | 181 |
| 200 / 0.95 | +6.7 | -17.6 | 2005 | null |
| 800 / 0.8 | +5.1 | -22.6 | 2281 | 173 |
| 800 / 0.95 | +8.5 | -20.6 | 2250 | 224 |
| 2500 / 0.95 | +6.4 | -20.5 | 3325 | 172 |

Reading: loudness effect is small (RMS up to +5 dB at 200 Hz fb 0.95), the t60 effect is large for low `comb_hz` with high feedback. A comb delay of 1/200 Hz = 240 samples is a 5 ms ring that the 5 ms end fade may not cover (check by the pre-fade tail level).

### 2.6 `gate_ms` and `tail_reverse` (tail shape)

Quantity moved: `t60_ms`, envelope shape. Measured on the default voice (gate = cut at g ms with a 1 ms linear fade, then renormalised):

| gate_ms | RMS (default) | t60 ms (default) | RMS (long) | t60 ms (long) |
| --- | --- | --- | --- | --- |
| 30 | -26.3 | 30 | -28.1 | 17 |
| 60 | -22.0 | 24 | -24.3 | 15 |
| 120 | -21.6 | 83 | -22.1 | 75 |

Reversed tail (tail segment only, from the end of the burst region, flipped in time): the level step at the joint is 0.002 (default) and 0.021 (long) relative to the peak, so the joint itself is not a click at these settings (sample difference, not a spectral measurement). The reversed tail rises to its maximum at the very end, where the existing 5 ms fade-out and cut-off apply; `t60_ms` is `null` for reversed tails (P-X1). The user-visible risk: the loudest part sits at the file end, so a short `length_ms` cuts the swell (hypothesis; the engine should reject or document a gate/reverse combination with `length_ms` shorter than the tail, as v0.1 does for a clap shorter than its tail: it cuts and fades).

### 2.7 Hard clip (`clip_db`-style), not recommended as the first new field

Quantity moved: crest, flat-top fraction. Measured (hard clip at gain +12/+24/+36 dB over the peak-normalised signal, 8x oversampled): RMS -13.8 / -10.5 / -9.3 dBFS, crest 13.5 / 10.2 / 9.0 dB, hf_share_8k 0.036 / 0.064 / 0.083, `t60_ms` 198 / null / null. The corner of the clip curve is why it aliases worst (section 3). The kick already has `clip_db` 0 to 12 in kick-params v0.3 (hard clip with the residual through the drive oversampler); for the clap, `drive` (tanh) plus `fold` cover the same ground with a better aliasing margin. If wanted: the same name and range as the kick, 0 to 12, as a later addition.

### 2.8 Layered noise bursts and range widening

- A second noise layer is **not** proposed as a field: the sum of two renders is already C3's construction (item C5), and a layer field needs offset, level, polarity and its own band-pass, which is a contract for a layering feature across categories, not a clap option. Open question for the lead (section 8).
- Range widening of existing fields (additive in v0.2, hypotheses): `bursts` max 6 to 16 and `burst_spacing_ms` min 3 to 1 would allow a buzz (spacing 1 to 3 ms repeats at 1000 to 333 Hz) and a roll. It breaks the contract's own cross-field remark (longest onset (bursts - 1) x spacing must stay below `length_ms` minimum 200: 15 x 30 = 450 ms), so it needs a `dependentSchemas` or a larger minimum length. Not measured. Listed so the lead can decide; not in the recommended list.

## 3. Aliasing, measured

Method (independent of the engine blocks): take the engine's default voice (seed 1), peak-normalise, apply the curve **naively** at 48 kHz and at k-times oversampling with the engine's own `dsp.oversampled` + `kaiser_lowpass(k, 0.08, 10.0)`, and compare each with the **32x** oversampled result. Error = 10 log10( sum of squared difference / sum of squared reference ), in dB. This is a difference between two renders, so it contains aliasing plus the oversampler's own small passband error; it is an upper bound on aliasing, not an exact value. `python3 -I xm2.py`:

| Curve | 1x (naive) | 2x | 4x | **8x (engine)** | 16x |
| --- | --- | --- | --- | --- | --- |
| tanh, g = 10 (= drive 1.0) | -29.4 | -57.3 | -98.5 | **-102.1** | -133.1 |
| sine fold k=4 | -30.5 | -89.8 | -101.0 | **-101.6** | -134.8 |
| sine fold k=8 | -19.1 | -62.9 | -91.6 | **-91.8** | -130.6 |
| sine fold k=16 | -11.3 | -30.9 | -88.3 | **-88.6** | -125.9 |
| triangle fold k=6 | -22.0 | -38.8 | -51.0 | **-63.5** | -75.6 |
| hard clip, +36 dB gain | -18.3 | -29.9 | -42.9 | **-55.3** | -67.3 |

Reading: smooth curves are far below the kick's alias bound (-68 dB, quoted in H8 of the C3 note) already at 8x; **curves with a corner miss -68 dB at 8x** (-63.5 and -55.3). A 16x factor brings the triangle fold to -75.6 dB but hard clip at +36 dB only to -67.3 dB (just above the bound). Proposal: `fold` is sine-shaped (smooth), the hard clip stays out of the first v0.2 cut, or runs at a higher factor. This is the only reason in this note to prefer one shape over another; which sounds better is for the user.

Not measured: aliasing of `crush`, `rate_div` and `ring` by an oversampled reference. Their distortion products are the intent (2.2, 2.3) or a linear sideband process (2.4: with carrier ≤ 3000 Hz and a band-limited input the upper sideband stays far below 24 kHz for the default voice, hf12 0.007 to 0.011; not verified for `bright` plus a 3000 Hz carrier).

## 4. Proposal: contract fields (PROPOSAL ONLY, not for use before a `contract-change`)

Rule for all: **absent or at the default = stage skipped**, same as `room` 0 and `drive` 0, so v0.1 hashes stay valid and a v0.2 document without the new fields renders like its v0.1 twin. v0.1 instances stay valid under v0.2 (`schema_version` `"0.1"` or `"0.2"`; new fields allowed only with `"0.2"`, the way kick-params 0.3 handles its fields, so v0.1 sidecars and resolved forms do not change; the audio-engineer reads the kick's `v03_properties` placement text and copies the mechanism).

Proposed signal order (hypothesis; needs the audio-engineer's check): noise, band-pass, envelope, **[crush, rate_div, ring, comb]**, `hp_hz` high-pass, room, **[fold]**, `drive`, **[gate_ms, tail_reverse]** (shape), fade-out, mean removal, ceiling. Reason from the measurements: 2.3 and 2.4 push energy under the high-pass corner (sub-150 share 1.9 % and 6.7 % in the worst rows), `fold` and `drive` are memoryless and want the oversampler and a clean input; gating after distortion keeps the cut clean.

| Field | Type, range | Default (= off) | Moves (measure) | Fits v0.1? | Risk to test |
| --- | --- | --- | --- | --- | --- |
| `drive` | number 0 to 1 | 0 | RMS, crest, hf_share_8k, t60 (table L) | **Yes, exists** | RMS +10.9 dB at 1.0 |
| `fold` | number 0 to 1 (k = 1 + 15 fold, sine) | 0 | hf_share_8k, centroid | needs v0.2 | alias ≤ -88 dB at 8x, t60 `null`, loudness |
| `crush` | number 0 to 1 (bits 12 to 3) | 0 | SNR, t60, hf_share_8k | needs v0.2 | tail goes to silence, mean |
| `rate_div` | integer 1 to 16 | 1 | hf_share_8k, centroid, sub share | needs v0.2 | folds into sub at f ≥ 8, mean |
| `ring_hz` | number 20 to 3000 | with `ring_mix` 0 | centroid, sub-150 share | needs v0.2 | sideband under `hp_hz`, order |
| `ring_mix` | number 0 to 1 | 0 | same | needs v0.2 | loudness drop (RMS -1.2 to -2.9 dB at mix 1, table 2.4) |
| `comb_hz` | number 100 to 4000 | with `comb_fb` 0 | centroid, t60 | needs v0.2 | tail ring, peak gain up to +8.5 dB before norm. |
| `comb_fb` | number 0 to 0.95 | 0 | same | needs v0.2 | stability (< 1, hard bound) |
| `gate_ms` | number 5 to 500 | absent (off) | t60, RMS | needs v0.2 | cut click (1 ms fade used), absent = no default key |
| `tail_reverse` | boolean | false | envelope shape | needs v0.2 | swell at file end, `t60_ms` null |

Open detail for the audio-engineer: an "absent = off" field (`gate_ms`) has no schema default, so the resolved form (which fills defaults) either needs a sentinel value (0 = off, with minimum 5 for non-zero) or leaves the key out. Pick one in the contract-change PR.

Shared rules (not field-specific): peak ceiling stays the only level guarantee (`_normalise`, unchanged); `polarity` and `offset_ms` stay as in v0.1; every new block uses only the seed's existing streams or none (ring, comb, crush, rate_div, gate, reverse are deterministic functions of the signal; no new random stream, which keeps `N_STREAMS` = 2 and the room/noise streams unchanged).

## 5. Hypotheses (all unverified until marked otherwise)

| # | Hypothesis | Measurement that confirms or rejects |
| --- | --- | --- |
| H-X1 | v0.1 `drive` matches the distorted reference's loudness (crest) but not its brightness; reaching its HF share needs a brighter `bp_hz`/`hp_hz` or `fold` | Render `drive` 0.6 with `bp_hz` 1370 (the fit), hp 225, seeds 1-8; compare crest and hf_share_8k (Welch, 300 ms, as the reference note) with `ZEN_RUPT_clap_distorted` (crest 12.8 dB, HF share 0.116, centroid 3084 Hz). Reject if drive plus bright band-pass reaches the HF share inside the seed spread |
| H-X2 | `fold` is more efficient than `drive` at raising HF share per dB of RMS gain | hf_share_8k against RMS gain at equal RMS (fold k=4: HF 0.082 at RMS -13.7; drive 1.0: HF 0.051 at -12.0, from the tables above): one seed each and different bases (fold on the `default` preset render, drive on seed 1), so not yet a comparison; repeat on one base, seeds 1-8 |
| H-X3 | `crush` and `gate_ms` both shorten `t60_ms`, but only `crush` leaves the first 30 ms spectrum unchanged | Short-window centroid 0-30 ms vs 50-200 ms (P3 of C3) for 4 bits and gate 60 ms |
| H-X4 | A stage that adds energy under the high-pass (`rate_div` ≥ 8, `ring_hz` ≥ 400) must sit before `hp_hz` | Sub-150 share and `lf_leak_db` with the stage before and after the high-pass; limit proposal ≤ 0.005 |
| H-X5 | Every new stage at its extreme keeps the final file at the ceiling and finite | Property test over the full field range, seeds 1-8: peak ≤ ceiling, no NaN, mean < 1e-3 |
| H-X6 | Equal-RMS levelling (not equal peak) is needed for any A/B including a distortion option | RMS spread of the extreme presets at equal peak (section 6) |
| H-X7 | Mean removal and the 5 ms fade hide a DC risk in `crush`/`rate_div` | Mean before and after `_remove_mean` for all rows, extremes of `crush` and `rate_div` |

## 6. Pitfalls found

- **P-X1 `t60_ms` is `null` or a level artefact for distorted claps.** `t60_ms` is relative to the peak: distortion lifts the tail towards the peak (drive 0 to 1: 166 to 372 ms), and for `fold` k ≥ 4, hard clip ≥ +24 dB and the reversed tail it is `null`. Do not use `t60_ms` as a target for extreme presets; use RMS/crest and a fixed-level tail measurement (hypothesis: energy after 100 ms in dB re the 0-30 ms energy).
- **P-X2 `t60_ms` with ring modulation** read 10.6 ms and 30.3 ms for mix 0.5 at carriers 50 and 150 Hz while mix 1.0 read 116 and 165 ms: the 1 ms envelope contains the carrier's nulls. Cause not established beyond that; the number is not usable for ring-modulated claps.
- **P-X3 Loudness at equal peak.** The ceiling holds for every option; RMS does not: engine `drive` 1.0 +10.9 dB (seed 1: -22.9 to -12.0); on the `default` preset render (RMS -21.6): tanh g=10 +9.7 dB, hard clip +36 dB +12.3 dB, sine fold k=8 +8.6 dB (the two bases differ by 1.3 dB through the seed, so compare only within one of them). A/B tests must match RMS, not peak.
- **P-X4 Sample-and-hold is not a band-limited resampler.** The measured rows are the point of the effect; the file's content above the held rate is mirrored, not removed. Do not test it with an alias bound.

## 7. "Extreme" preset family and listening-test skeleton

Preset values are **PROPOSALS** inside the proposed v0.2 ranges plus the existing v0.1 fields; none was rendered or measured as a preset. The only measured parts are the single-block rows above. Names are working names. Baseline for every comparison: `default` (seed 2001 in its file; use a fixed seed 1 for the whole test).

| Preset | Idea | Fields (others default) | Predicted direction (hypothesis, from the single rows) |
| --- | --- | --- | --- |
| `xtreme-saturated` | Saturation only | `drive` 0.8 | RMS +10 dB, crest -10 dB, t60 up (table L) |
| `xtreme-folded` | Fold | `fold` 0.4 (k = 7), `bp_hz` 1500 | hf_share_8k about 0.15 to 0.18, centroid 4000 Hz up |
| `xtreme-crushed` | Lo-fi | `crush` 0.7 (about 6 bits), `rate_div` 4, `hp_hz` 600 | t60 down, hf_share_8k ≥ 0.07 |
| `xtreme-metal` | Ring | `ring_hz` 400, `ring_mix` 0.7, `comb_hz` 800, `comb_fb` 0.8 | sub-150 share must stay ≤ 0.005 (check), centroid ±10 % |
| `xtreme-gated` | Gated | `tail_decay_ms` 800, `length_ms` 900, `gate_ms` 120 | t60 near the gate time (75 to 83 ms at 120) |
| `xtreme-reversed` | Swell | `tail_reverse` true, `tail_level` 1, `tail_decay_ms` 300, `length_ms` 700 | energy peak at the end; `t60_ms` null |
| `xtreme-wreck` | Everything | `drive` 0.6, `fold` 0.3, `crush` 0.4, `rate_div` 2, `comb_hz` 1500, `comb_fb` 0.6 | RMS gain ≥ 8 dB; the one that needs the clip/overshoot test (H-X5) |

**Skeleton (render by the audio-engineer after step 2; this note renders nothing).** Same method as C3 section 5: identical control pair, blind names, A/B positions fixed by seed, German answer sheet, key file. 4 bars at 136 BPM, `dense` kick on every beat, clap on beats 2 and 4, each hit cut at 1 beat (the gated/reversed one at 2 beats), peak at most -0.3 dBFS. **Level match within every item by RMS over the whole hit** (not 0-60 ms as in C3; H-X6 and P-X3: distortion lifts the tail), gains in the key.

| Item | Files (blind) | Single question |
| --- | --- | --- |
| X0 control | A = B, identical `default` | How often does a side get picked with no difference |
| X1 | A = `default`, B = `xtreme-saturated` | Is B a different clap or the same clap louder (RMS-matched)? |
| X2 | A = `xtreme-saturated`, B = `xtreme-folded` | Do drive and fold give different characters, or the same? |
| X3 | A = `xtreme-crushed`, B = `xtreme-metal` | Which fits "experimental" for a project; which is unusable? |
| X4 | A = `xtreme-gated`, B = `xtreme-reversed` | Do the tail shapes work with the kick pattern? |
| X5 | Single: `xtreme-wreck` | Is this still a clap (ja / nein / kommt auf das Projekt an)? |
| X6 | Rank all six non-wreck presets | Which would you use first in a project (Reihenfolge) |

Seven items (about 12 minutes if run in the C3 format, not timed): 11 blind files (X0 2, X1 2, X2 2, X3 2, X4 2, X5 1; the six presets reused for X6 as copies). Order: X1, X0, X2, X3, X4, X5, X6. The user answers in German; the lead decodes with the key; "kein Unterschied" is always allowed. How answers map to next steps (hypothesis): X1 "kein Unterschied" means v0.1 `drive` is enough and `fold` is a duplicate; X2 same means drop one of drive/fold; X3 "unbrauchbar" for one means remove that field from the first v0.2 cut (or narrow its range); X5 "nein" means the wreck combination marks the top of the range, not a preset.

## 8. Not done, sources, limits, open questions

- **Not done:** nothing rendered to a file, nothing heard, no engine code or contract written. All new-block numbers come from my own NumPy prototype on one seed; the engine blocks may differ in detail (oversampling, DC handling, order). No preset-level measurement; the preset column is a prediction.
- **No external sources.** Everything is from the repo files listed in section 1 and from my own measurements; the field names and ranges are my proposals (labelled PROPOSAL ONLY). I did not search the web for DAW clap-distortion practice; nothing here claims how other tools do it.
- **Reference limits:** the only distorted reference is one file (`ZEN_RUPT_clap_distorted`, the user's, 44.1 kHz stereo; not in the repo, numbers from the reference note). It shows what the user's library holds for "distorted", not what the user wants as extreme. Whether experimental should go beyond it is a taste question.
- **Open for the lead/user:** (1) should a second noise layer exist as a field (section 2.8), or stay a mix-two-renders convention; (2) is `bursts`/`burst_spacing_ms` range widening wanted (buzz and roll); (3) fold shape: sine only, or also a triangle fold at 16x oversampling; (4) deterministic dither for `crush`: yes/no; (5) stereo: the v0.1 clap is mono, and the references include wide stereo files; an experimental stereo width option is outside this note.
