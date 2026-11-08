# Research: atmospheres and drones as a sample category (`atmos-params` v0.1 proposal)

- **Date:** 2026-11-08. Researcher role, instance A (sound and audio; D-018). Receiving issue: #518 (user, 2026-11-08 20:51: "Atmos und drones wären noch interessant"). Docs PR `Closes #518`.
- **Repo state read:** `origin/main` 90c4fb0 — `src/audio_engine/fx.py` (module docstring lines 1-66, `noise_layer` / `svf` / `_additive` / `dry_signal` / `pump_gain` lines 348-561), `src/audio_engine/laser_fx.py` (`echo_v2` 277-321, `reverb_wet` 338-389), `src/audio_engine/loudness.py` (BS.1770, lines 54-61), `src/audio_engine/categories.py` (line 37), `src/orchestrator/arrangement_timeline.py` (lines 24, 49-50, 121), `contracts/fx-params.schema.json` (field list), `contracts/bass-params.schema.json` (`note`, `$comment` point 1), `contracts/sample-metadata.schema.json` (line 12, `category` enum), `contracts/capabilities.json` (statuses).
- **Notes this builds on (not re-researched):** [FX transitions](2026-11-07_fx-transitions.md) (Live warp facts F1-F3, BS.1770 F12, laser reverb/echo reuse), [Goa reference measurements](2026-11-03_goa-reference-measurements.md) (tonic notes, stereo per band), [Goa musicology](2026-11-03_goa-trance-musicology-and-sound.md) (sub drone, edition facts), [Bandit Wheel musical transfer](2026-10-29_bandit-wheel-musical-transfer.md) (atmos level and low cut, prior art), [arrangement planner](2026-10-29_arrangement-planner-sections-energy.md) (atmos/pad thresholds), [next-category proposal](2026-11-02_next-category-proposal.md) (atmos coverage, "needs a loop/stereo contract"). The kick learnings note has no atmos content; its rules (determinism, measure before claiming) apply unchanged.
- **Not done:** nothing was rendered with an engine and nothing was listened to. **No claim is made about how anything sounds.** The five scratchpad experiments in section 3 use synthetic signals only (own code, not repo code). All ranges and defaults are proposals.

## For workers

- **Possible with our stack?** Yes, as rendered stereo WAV loops of 1-32 bars at a given BPM, numpy only, no new dependency. Seamless loops come from building every stage **circularly** (period = file length): FFT-shaped noise, bin-locked additive partials, modulations with whole cycles per loop, circular grain overlap-add, and a steady-state pre-roll for the recursive stages (time-varying filter, FDN reverb). No Max for Live (D-001), no generative model (D-005).
- **Route:** (1) `contract-change` PR `atmos-params` v0.1 (section 6) + `atmos` in the sample-metadata `category` enum, engine name `abeltongod-audio-engine-atmos` (D-025); (2) engine `src/audio_engine/atmos.py` in the order of section 7 (noise_bed → drone → resonant → granular), reusing `fx.svf`, `fx` polynomial helpers, `laser_fx.reverb_wet`, `dsp.substreams`, `loudness`; (3) GUI and CLI via the category registry.
- **Read first:** sections 3 (seam method, measured), 5 (Live), 6 (contract), 7 (plan and tests).
- **Effort:** contract small-medium; engine medium (new: circular toolkit, steady-state pre-roll, bin-locked additive, grains); Live check small (user, section 5 X1-X3).
- **Blockers:** none for contract and engine. In Live: an **unwarped audio clip cannot loop** (manual 8.9), so every loop is warped; whether Warp at the render tempo and Live's 0-4 ms clip fades leave the seam untouched is not documented (X1-X3). Clip warp/loop properties are not in `capabilities.json`.
- **Decision needed first:** D-028 item 3 froze new categories; D-032 added `perc` and `fx`. `atmos` needs the same explicit lead/user entry (section 9).
- **Open questions only the user can answer:** U1-U8 in section 8 (lengths, tonal vs non-tonal first, key source, tuning tolerance, tempo changes in Live, width, one-shot swells, reference files).

## 1. Findings

Confidence: **high** = official documentation, own repo code or own measurement with the command stated; **medium** = magazine tutorial or community source (labelled); **low** = unpublished prior art; **inference** = my reasoning.

| # | Finding | Confidence | Source (opened 2026-11-08 unless noted) |
| --- | --- | --- | --- |
| A1 | A drone is a note or chord sounding continuously through most or all of a piece, sustained or repeated, usually on the tonic or the fifth. No techno/trance/ambient statement on the page. | medium (encyclopedia) | [Wikipedia, Drone (music)](https://en.wikipedia.org/wiki/Drone_(music)) |
| A2 | Ambient-techno atmosphere recipe: an 8-bar loop of a source in the track's key into a reverb with freeze (100 % wet), re-recorded; high-pass and low-pass; a second reverb; stereo widening and rotation; a dark reverb variant with a high cut at **400 Hz** and a decay given as "3.62ms" (inference: seconds meant); fewer reflections, more diffusion. | medium (magazine) | [MusicRadar, How to create an ambient techno atmosphere (Sara Simms, 2023-12-06)](https://www.musicradar.com/how-to/techno-ambience-atmosphere) |
| A3 | Drone textures from found sounds: sample played lower (one octave = half speed), looped with equal-power crossfades, bass cut and top boosted, large reverb; band-pass filter driven by a **4-bar sine LFO**; auto-pan, saturation, reverb and delay. No Hz, grain or stretch values. | medium (magazine) | [MusicRadar / Future Music, found sounds into drone textures (2019-04-19)](https://musicradar.com/how-to/how-to-turn-found-sounds-into-atmospheric-drone-textures) |
| A4 | Atmosphere tips: three texture layers (one centred, two auto-panned or a stereo pair); sidechain the texture to the drums or chop it to the beat; small random LFO on a filter cutoff; several reverbs of different length and brightness. No numbers. | medium (magazine) | [MusicRadar / Future Music, 8 ways to add atmosphere (2017-05-23)](https://www.musicradar.com/how-to/8-ways-to-add-atmosphere-and-ambience-to-your-music) |
| A5 | Planner: non-tonal atmos is on from energy 0.20, tonal atmos/pad from 0.70; in a breakdown atmos and pad are always on. In the three fixtures atmos is on in 88-92 % of bars. | high (code) / medium (thresholds are _Interpretation_) | `arrangement_timeline.py` lines 24, 49-50, 121 @ 90c4fb0; next-category note section 1 |
| A6 | Prior art (Bandit Wheel artifact): atmos sits at **-22 LU integrated / -15 LU momentary cap** vs the kick loop; atmos low cut **300 Hz** (500 Hz and -2.5 dB when it clashes with a chord pad); mono below **120 Hz** for every loop. The artifact says no published standard exists. | low (unpublished) | [Bandit Wheel musical transfer, lines 251-258](2026-10-29_bandit-wheel-musical-transfer.md) (opened 2026-10-29) |
| A7 | User's Goa references (whole mixes, 3 tracks): tonic notes E1 (28), C2 (36), C2 (36); L/R correlation 0.38-0.73 at 500 Hz-4 kHz in two tracks, >= 0.95 in 31.5-125 Hz bands; one track near-mono. Mix-level, **not** an atmos measurement. | medium (own measurement on 3 tracks) | [Goa reference measurements, lines 16, 256, 262](2026-11-03_goa-reference-measurements.md) |
| A8 | Granular synthesis: grains of about 1-100 ms, parameters density, envelope, pitch/speed, source position, spatial placement; Gabor (1947), Xenakis, Roads *Microsound* (2001). | medium (encyclopedia) | [Wikipedia, Granular synthesis](https://en.wikipedia.org/wiki/Granular_synthesis) |
| A9 | PaulStretch: STFT overlap-add with a Hann window, **scrambled phase** and very large windows, for extreme stretching; algorithm by Nasca Octavian Paul. No licence statement on the page (only an algorithm is reused, no code). | high (reference manual) | [Csound manual, paulstretch](https://csound.com/manual/opcodes/paulstretch/) |
| A10 | FDN = vector feedback comb: diagonal delay matrix, feedback = diagonal gain × orthogonal matrix. Delay lengths mutually prime (maximises the time before the lossless prototype repeats) and with high mode density (low density is heard as ringing tones per the source). | high (textbook) | J. O. Smith, *Physical Audio Signal Processing*: [FDN](https://ccrma.stanford.edu/~jos/pasp/Feedback_Delay_Networks_FDN.html), [Choice of delay lengths](https://ccrma.stanford.edu/~jos/pasp/Choice_Delay_Lengths.html) |
| A11 | Circular (cyclic) convolution of N-length signals: sum over m of x(m) y(n-m), indices wrapping. (The DFT product property is standard; not on that page.) | high (textbook) | J. O. Smith, *Mathematics of the DFT*: [Convolution](https://ccrma.stanford.edu/~jos/st/Convolution.html) |
| L1 | **Unwarped audio clips cannot be looped**; the Loop switch needs Warp on. Loop position/length default to the clip length. | high | [Live 12 manual, ch. 8 Clip View, 8.9 (and 8.2.1)](https://www.ableton.com/en/live-manual/12/clip-view) |
| L2 | Clip Fade (Session only): 0-4 ms, signal-dependent, at clip start and end; on by default for new clips when "Create Fades on Clip Edges" is enabled (Settings > Record, Warp & Launch). Whether it acts at **loop wraps** is not stated. | high (absence: high) | same, 8.4.4; [Ableton help, Create Fades on Clip Edges](https://help.ableton.com/hc/en-us/articles/209069969-Create-Fades-on-Clip-Edges-to-avoid-clicks) ("up to 4 ms") |
| L3 | Warp modes: **Texture** is for material without clear pitch, "pads, noise, and drones" (Grain Size, Fluctuation = randomness); **Complex Pro** also for polyphonic textures, more CPU; **Re-Pitch** changes pitch with tempo (no transposition). | high | [Live 12 manual, ch. 9, 9.3.3-9.3.5](https://www.ableton.com/en/live-manual/12/audio-clips-tempo-and-warping) |
| L4 | Short samples under "Auto" are assumed to be 1, 2, 4, 8 or 16-bar loops and the tempo is set from that (two warp markers); long samples are auto-warped with a marker per bar; odd-bar loops can be misread (4/4). No short/long threshold is given. | high | same, 9.2.1, 9.2.4.1-9.2.4.2, 9.2.5 (repeats FX note F1/F2) |
| L5 | Devices in the **user's** Live (screenshots 2026-11-03/04): Auto Filter, Auto Pan-Tremolo, Chorus-Ensemble, Corpus, Delay, Filter Delay, Grain Delay, Phaser-Flanger, Resonators, Reverb, Saturator, Utility, EQ Eight, Spectrum, Vocoder, Looper; instruments Analog, Collision, Drift, Simpler, Tension, Electric. **No Echo, no Roar**; also no Hybrid Reverb, Spectral Resonator, Spectral Time, Wavetable, Operator, Sampler, Meld in his lists. | high (user evidence) | #345 comments (lead, 2026-11-03 and 2026-11-04) |
| L6 | Auto Filter: 10 types (incl. Comb, Vowel), tempo-synced LFO. Auto Pan-Tremolo: Time mode period up to **200 s**; Phase offsets L/R LFOs, Spin detunes them. Chorus-Ensemble: wet width up to 200 %. Corpus: 7 resonator types, Decay, Spread. | high | [Live 12 manual, ch. 29, 29.2, 29.3, 29.8, 29.10](https://www.ableton.com/en/live-manual/12/live-audio-effect-reference) (Reverb, Grain Delay, Resonators, Utility sections were **not** in the part of the page I could read) |
| L7 | AbletonOSC exposes clip `warping`, `warp_mode`, `looping`, `loop_start`, `loop_end` as read/write properties (`/live/clip/get|set/<prop>`). None is in `contracts/capabilities.json`; only `clip_slot.create_audio_clip` and `clip.file_path.get` are `tested` for clips. | high (code) | AbletonOSC `abletonosc/clip.py` lines 94-115 (master, fetched 2026-11-08, sha256 `966ba33a…c71d`; the repo's documented pin `0ca68214` was **not** compared); `capabilities.json` @ 90c4fb0 |
| M1 | Exact loop length N = 240·bars·sr/BPM is an integer only for some tempos: at 48 kHz yes for 120/128/144/150 BPM, **not** for 130/135/138/140/142/145; at 44.1 kHz yes for 128 (from 2 bars), 135, 140, 150. | high (arithmetic, E1) | section 3 |
| M2 | FFT-shaped (circular) noise has no seam; a non-periodic signal cut to length can have one. Seam metric (first-difference energy, 5 ms window at the wrap of [x, x], vs median window): circular band-pass noise -0.25…+0.57 dB over 5 seeds; random-walk noise cut to length +4.5…+33 dB. Band-pass noise cut from a longer render also scored -0.8…+0.2 dB, so this metric alone does not prove periodicity. | high (own measurement, E2) | section 3 |
| M3 | A time-varying band-pass SVF (repo topology, cutoff with one LFO cycle per loop) fed with a periodic input reached a **bit-identical (float64) periodic state after one pre-roll loop**: pass 2 = pass 4 exactly, for Q 0.7/4/12 and lowest cutoff 200/60/40 Hz, 1 bar at 140 BPM. First pass differs by 6-9 % of peak. 0.31-0.32 µs/sample (plain Python loop). | high (own measurement, E3; only these settings) | section 3 |
| M4 | Bin-locking a partial (f = k·sr/N) gives an exact loop; worst tuning error = half a bin: 1 bar at 135-150 BPM → 14.8-16.5 cents at 32.7 Hz, 8.8-9.8 at 55 Hz; 4 bars → 3.7-4.1 / 2.2-2.5; 16 bars → 0.9-1.0 / 0.55-0.61. A free 55 Hz sine has a seam step of 0.98 (full scale 1); the bin-locked one 6.7e-14. | high (arithmetic and own measurement, E4/E6) | section 3 |
| M5 | Folding an impulse response modulo N and convolving circularly equals the 10th loop of a linear convolution of the tiled input (max relative difference 5.7e-16). Repo `reverb_wet` on 16 bars at 135 BPM, stereo: 0.77 s (decay 3 s), 0.65 s (8 s). numpy rfft+irfft at the exact N: 0.06-0.26 s; 0.81 s for N with prime factor 4703 (142 BPM). | high (own measurement, E5) | section 3 |

## 2. What atmospheres and drones consist of (paraphrase of A1-A7; parameters are inference)

| Type | Planner role (A5) | Building blocks | Movement | Tonal? |
| --- | --- | --- | --- | --- |
| **Noise bed** (air, wind, hiss) | `atmos`, from E 0.20 | coloured noise, high- and low-pass (A2), wide stereo (A2, A4) | slow filter LFO (A3: 4 bars), small random LFO (A4), amplitude rhythm or sidechain (A2, A4) | no |
| **Drone** (held note/chord) | `pad` slot when no Goa pad is used (see 9.3); Goa sub drone (musicology note) | sustained partials of a root and its fifth/octave (A1), detuned pairs for beating, reverb (A2) | slow per-partial level drift, slow filter | yes |
| **Resonant bed** (noise through tuned resonators) | either | noise → bank of narrow band-passes at the partials of a note/chord (Live's Resonators/Corpus do this in Live, L5/L6) | as noise bed | partly |
| **Granular / frozen texture** | either | short grains (A8) or a frozen spectrum with scrambled phases (A9) of an own source, reverb freeze (A2) | grain position/pitch scatter, slow morph | depends on source |

## 3. Loop seam: method and own experiments (scratchpad, not in the repo)

Scripts: `/tmp/claude-0/-home-claude/8969c227-1cdb-551a-898a-46125f9a8cff/scratchpad/atmos/seam.py` (E1-E5) and `e6.py` (E6), Python 3.13.18, numpy 2.5.3, run as `python3 -I seam.py` / `python3 e6.py`; `fftn.py` (FFT timing). They use synthetic signals and their own SVF copy, not the engine.

**Principle (A11, inference applied to our blocks).** A loop of N samples is seamless when the file is one period of a signal with period N. Every stage must therefore be one of:

1. **Circular by construction** — operations on the N-sample spectrum: noise shaped by a magnitude response (`irfft(rfft(white) · H, N)`), fixed filters, mono-below crossover, tilt; partials on FFT bins k·sr/N; modulations with an integer number of cycles per loop (rate in **cycles per loop**, not Hz); grains overlap-added with indices modulo N.
2. **Steady state of a recursive stage** — time-varying SVF, FDN reverb, echo: run the stage over P pre-roll copies of the periodic input plus one, keep the last period. M3: P = 1 was bit-identical for the SVF settings tested; M5: equivalent to folding the IR. For the FDN choose P = ceil(2.4 · T60 / T_loop) (2.4 · T60 ≈ -144 dB, below 24-bit resolution; arithmetic), e.g. decay 8 s on 1 bar at 150 BPM (1.6 s): P = 12, 13 × 76 800 samples.
3. **Not allowed in loop mode** — anything that is not periodic: free-running LFOs in Hz, partials off the bin grid, a random walk, fades at the file ends (an end fade puts a dip at every wrap).

**Loop length.** N = round(240 · bars · sr / BPM). Where it is not an integer (M1), the file is up to 0.5 sample shorter or longer than the musical length; Live's warp then stretches by at most 0.5 / N (1 bar at 200 BPM, 48 kHz: N = 57 600, ratio 8.7e-6 = 0.015 cents; arithmetic). The sidecar records both N and the exact value.

**Seam metrics (for tests).**
- **Periodicity, independent reference:** re-compute the loop by a different method (linear processing of 3 tiled periods with the test's own filter, keep the middle period) and compare: max difference < 1 LSB of the output bit depth. This is the strongest check; M2 shows a click metric can pass for a non-periodic noise.
- **Seam step (tonal kinds):** |x[N-1] → x[0] step − predicted step| from the local slope; E6: 0.98 for a free sine vs 6.7e-14 bin-locked. The first-difference metric is phase-biased on pure tones (+1.94 dB for an exact loop in E6), so use it for noise kinds only.
- **Seam click (noise kinds):** first-difference energy in a 5 ms window at the wrap within ±3 dB of the median window (E2 range -0.25…+0.57 dB for circular noise).

## 4. Measurable targets (quantities and methods; ranges are proposals)

| Quantity | Method (numpy, deterministic) | Proposal | Basis |
| --- | --- | --- | --- |
| Length | frames == round(240 · bars · sr / BPM) | exact | arithmetic |
| Seam | section 3 metrics | periodic within 1 LSB; step/click as in section 3 | M2-M4 |
| Level stationarity | short-term loudness (3 s, `loudness.short_term_lufs`) on the circularly extended loop; max − min | ≤ `amp_move_db` + 1 LU | inference; "bed" = steady (A5) |
| Level vs kick | integrated loudness of the loop vs a 4-bar loop of the default kick, same peak ceiling | -22 LU integrated, -15 LU momentary cap as **starting points**; set in Live, not baked | A6 (low) |
| Low end | `analysis.lf_leak_db` below `hp_hz` | ≤ -24 dB below `hp_hz`; default `hp_hz` 150 (noise) / per note (tonal) | A2 (HP), A6 (300 Hz prior art); inference |
| Brightness | spectral centroid of the loop; band energy above `lp_hz` | centroid inside [hp, lp]; ≤ -24 dB above `lp_hz` | A2 (LP, 400 Hz dark variant) |
| Noise vs tone | Welch spectral flatness (`analysis.welch_flatness`) | noise_bed > resonant > drone (ordering test, no absolute window) | inference |
| Pitch (tonal) | fundamental by two methods over whole periods (spectral peak with interpolation, autocorrelation), in cents vs `note`+`cents` | within the bin-rounding error the sidecar reports, and that error ≤ `max_tuning_cents` (default 5) | M4; U4 |
| Movement | band-energy (or centroid) envelope; its DFT over the loop peaks at `move_cycles` | peak bin = `move_cycles`; depth within ±1 dB of `amp_move_db` | A3 (4-bar LFO), A4 |
| Stereo | L/R correlation per octave band (as Goa note); side/mid below `mono_below_hz` | correlation ≥ 0.99 below `mono_below_hz` (default 120 Hz); 500 Hz-4 kHz correlation falls monotonically with `stereo_width` | A6 (mono < 120 Hz), A7 (mix-level only) |
| DC | mean / peak | ≤ 1e-4 | inference (bass DC rule, D-028 amendment) |
| Determinism | sha256 of the WAV, same params + seed, Ubuntu and Windows CI | byte-identical | CLAUDE.md, D-005 |
| Runtime | wall time, 32 bars at 120 BPM, 48 kHz, each kind | report, no hard limit until measured on CI | M3, M5 |

## 5. Live 12 Standard handling

**Loop playback.** Looping requires Warp (L1). With Warp on, Live may re-guess the tempo of a short file (L4); an exact 1/2/4/8/16-bar length at the Set tempo is what "Auto" expects (inference: a correct guess is likely, not tested). 32-bar files are outside the 1-16 list in L4. Warp mode: the manual recommends Texture for pads/noise/drones (L3); Re-Pitch would retune a drone if the Set tempo changes (L3); at the render tempo the stretch ratio is 1 (or 1 ± 8.7e-6, section 3). **Whether any warp mode is sample-transparent at ratio 1 is not documented** (X2).

**Seam risks in Live (not established, to test):** Clip Fade 0-4 ms at clip edges (L2) — if it also acts at each loop wrap, a seamless file gets a dip per loop (X1). Warp-engine grain boundaries at the loop point (X2).

**Device recipes (only devices in the user's install, L5/L6).** Treatment after import: Auto Filter LFO (synced, slow) for movement, Auto Pan-Tremolo in Time mode for very slow panning, Chorus-Ensemble for width, Utility for mono-bass, Reverb and Delay for space, Resonators/Corpus to tune a noise bed in Live, EQ Eight for the low cut (A6 300 Hz as a starting point), Spectrum to look. **Echo and Roar are missing** at the user's install; any recipe naming them is wrong for him. Reverb's Freeze, Grain Delay and Utility details were not verified today.

**Delivery path.** Same as other categories: the `tested` Session clip-slot import (`clip_slot.create_audio_clip`). Setting warp/loop by code needs new capabilities (L7) registered `unknown` and tested on the user's machine (D-004); until then the user switches Warp/Loop by hand if Live does not.

**Experiments for the user's machine (bridge-engineer writes the guide):**
- **X1** Import a 4-bar `noise_bed` and a 4-bar `drone` into Session slots at the render tempo; read Warp, Loop, detected BPM, Clip Fade state; let them loop 8 times; record the master to a new audio track (resampling) and send the WAV back. CI then compares the recording against the file tiled 8× (seam dip/click at each wrap).
- **X2** Repeat with Warp mode Texture, Complex Pro and Re-Pitch, and with Clip Fade off.
- **X3** A 32-bar file: does "Auto" warp/loop it, and with what tempo guess.

## 6. Contract proposal: `atmos-params` v0.1 (for the `contract-change` issue; the owner decides)

Conventions as `fx-params`: out-of-range values are rejected, never clamped; required are `schema_version`, `seed`, `bpm`; omitted fields take top-level then per-kind defaults; a field a kind does not use has no effect; stereo `(n, 2)`. **All values are proposals, not measured against any reference.**

### 6.1 Common fields

| Field | Type / range | Default | Meaning |
| --- | --- | --- | --- |
| `schema_version` | `"0.1"` | — | required |
| `seed` | int 0 … 2^32-1 | — | required; one `dsp.substreams` index per layer (noise L, noise R, grain plan, drift curves …), fixed in the contract so a later layer never changes earlier noise (FX note pitfall 7) |
| `bpm` | 60-200 | — | required |
| `kind` | `noise_bed`, `drone`, `resonant`, `granular` | `noise_bed` | |
| `bars` | 1, 2, 4, 8, 16, 32 (4/4) | 8 | loop length; file = N = round(240 · bars · sr / bpm) frames; rule A: N / sr ≤ 72 s (as fx; 32 bars need bpm ≥ 107) |
| `loop_mode` | `seamless`, `oneshot` | `seamless` | seamless: section 3 rules, no end fades; oneshot: linear fades `fade_in_beats` / `fade_out_beats` and recursive tails may ring past the end (file length then = N + `tail_beats`) |
| `fade_in_beats` / `fade_out_beats` / `tail_beats` | 0-64 | 4 / 4 / 0 | oneshot only |
| `variants` | 1-8 | 1 | |
| `sample_rate` / `bit_depth` | 44100 / 48000; 16 / 24 | 48000 / 24 | 44100 gives integer N at 135/140/150 BPM (M1) |
| `peak_ceiling_dbfs` | -12 … -0.1 | -1.0 | peak normalisation of the whole loop (level vs kick is set in Live, A6) |
| `hp_hz` / `lp_hz` | 20-2000 / 200-20000 | per kind | fixed circular filters (2nd-order magnitude, zero phase); cross-field rule B: `lp_hz ≥ 1.5 · hp_hz` |
| `tilt_db_oct` | -6 … +3 | -3 (pink) | spectral tilt of noise sources, reference 1 kHz |
| `stereo_width` | 0-1 | 0.7 | 0 = mono; 1 = independent L/R streams (same mixing law as `fx.noise_layer`) |
| `mono_below_hz` | 0-300 | 120 | side signal removed below (circular crossover, half-octave ramp); 0 = off (A6) |
| `move_cycles` | int 0-64 | 2 | cycles of the filter/level movement per loop; 0 = static. At 8 bars, 2 = one cycle per 4 bars (A3) |
| `move_shape` | `sine`, `smooth_random` | `sine` | `smooth_random` = seeded sum of the first 4 harmonics of `move_cycles`, normalised (periodic) |
| `move_depth_oct` | 0-3 | 1.0 | cutoff/centre movement (noise_bed, resonant) |
| `amp_move_db` | 0-12 | 2 | level movement, same curve |
| `pan_move` | 0-1 | 0 | auto-pan depth, `move_cycles` cycles, L/R in opposite phase |
| `pump_depth` | 0-1 | 0 | quarter-note dip as `fx.pump_gain` (A4 sidechain); periodic because the loop is whole bars |
| `drive` | 0-1 | 0 | as fx (kick `_drive`; note its `np.tanh` is not platform-independent, fx docstring) |
| `reverb_mix` | 0-1 | per kind | `laser_fx.reverb_wet` in steady state (section 3, P pre-roll loops) |
| `reverb_decay_ms` | 100-12000 | 4000 | above fx's 8000; cost is P pre-roll loops (M5: < 1 s per 16 bars per pass) |
| `reverb_size`, `reverb_predelay_ms`, `reverb_damp_hz`, `reverb_width` | laser v0.2 ranges | laser defaults | `reverb_damp_hz` low values give the A2 "dark" variant |

### 6.2 Tonal fields (`drone`, `resonant`; `granular` with a tonal source)

| Field | Range | Default | Notes |
| --- | --- | --- | --- |
| `note` | MIDI 24-72 | 36 (C2, 65.4 Hz) | same formula as bass-params point 1; 36 is the tonic of 2 of 3 Goa references (A7, low confidence) |
| `cents` | -50 … 50 | 0 | |
| `intervals` | array of 1-6 ints, 0-36 semitones, first = 0 | [0, 7, 12] | root, fifth, octave (A1 "tonic or fifth") |
| `partials` | 1-48 | 12 | harmonics per voice, each bin-locked; above 0.45 · sr dropped (fx rule) |
| `brightness_db_oct` | -18 … 0 | -9 | partial level slope per octave |
| `detune_bins` | int 0-8 | 1 | second copy of each partial `detune_bins` bins up → beating of exactly `detune_bins` cycles per loop; the sidecar reports the cents |
| `drift_db` | 0-12 | 3 | per-partial slow level drift (seeded `smooth_random`, periodic) |
| `max_tuning_cents` | 0.5-20 | 5 | rule C: rejected if the bin-rounding error of the fundamental exceeds it (M4: 1 bar at low notes fails at 5) |
| `res_q` | 2-200 | 40 | `resonant`: Q of the band-pass at each partial, applied as a circular magnitude response to the noise |

### 6.3 Granular fields

| Field | Range | Default | Notes |
| --- | --- | --- | --- |
| `source` | `noise`, `drone`, `metal` | `drone` | v0.1: rendered internally from these params (`metal` = hat square bank), so a re-render needs only the params. Own library WAVs as a source = v0.2 (needs the source's sidecar hash in the request) |
| `grain_ms` | 10-500 | 80 | Hann grain (A8: 1-100 ms typical; longer allowed for smear) |
| `grain_density` | 1-200 grains/s | 30 | |
| `grain_pitch_cents` | 0-1200 | 0 | seeded spread; pitch by linear-interpolation resampling of the source |
| `grain_spread` | 0-1 | 0.5 | source-position scatter around a position that moves `move_cycles` times per loop |
| `grain_pan` | 0-1 | 0.6 | per-grain pan spread |

### 6.4 Per-kind defaults (starting points, all proposals)

| kind | `hp_hz` / `lp_hz` | movement | tonal | `reverb_mix` | source of the number |
| --- | --- | --- | --- | --- | --- |
| `noise_bed` | 150 / 8000 | 2 cycles, 1 oct, 2 dB | — | 0.3 | A2 (HP+LP), A3 (4-bar LFO at 8 bars) |
| `drone` | 0.8 · f0 / 6000 | level drift only | [0, 7, 12], 12 partials | 0.35 | A1 |
| `resonant` | 0.8 · f0 / 10000 | 1 cycle, 0.5 oct | Q 40 | 0.3 | L5/L6 analogy (Resonators/Corpus) |
| `granular` | 100 / 12000 | position moves 1 cycle | from `source` | 0.4 | A8 |

**Sidecar** (`category: "atmos"`, engine `abeltongod-audio-engine-atmos`, own version, D-025): resolved params plus `loop_samples` (N), `loop_samples_exact` (float), `seamless` (bool), `tuning_error_cents` (tonal), `realised_detune_cents`, `preroll_loops`, and the section-4 measurements (integrated LUFS, short-term range, centroid, flatness, correlation below `mono_below_hz`, DC).

**Tool budget:** `generate_*` tools hit the 24-optional-parameter limit before (next-category note blocker 2); a `generate_atmos` tool should expose `kind`, `bars`, `bpm`, `note`, `preset` and leave the rest to presets (orchestrator-engineer decides).

## 7. Engine plan for the audio-engineer

### 7.1 DSP options compared (deterministic, numpy only)

| Option | Fits kind | Seam | Cost (16 bars, 48 kHz, stereo) | Risk | Verdict |
| --- | --- | --- | --- | --- | --- |
| FFT-shaped circular noise + circular fixed filters | noise_bed, resonant | exact by construction (M2, A11) | 2-4 FFTs of N: 0.06-0.8 s each (M5) | FFT bytes across platforms (covered by golden hashes, as fx) | **use** |
| Time-varying SVF (`fx.svf`) for cutoff movement, 1+ pre-roll loop | noise_bed, resonant | steady state; bit-identical after 1 pre-roll in E3 | ~0.3-0.7 µs/sample/channel → ≈ 1.8-3.8 s for 2 passes × 2 ch | slower at low cutoff / high Q (not measured beyond E3) → assert convergence in the engine | **use**, with a convergence check |
| Crossfaded bank of fixed circular band-passes | moving filter alternative | exact | K FFTs | blended peaks ≠ one moving peak (FX note pitfall 2) | fallback only |
| Bin-locked additive partials synthesised by sparse `irfft` | drone | exact (M4) | one FFT per channel | tuning error at short loops (M4) → rule C | **use** |
| Per-sample additive (`fx._additive`) | drone | exact only if bin-locked | proportional to partial count (fx: up to 15.8 s for 72 s) | none new | not needed |
| Circular granular overlap-add | granular | exact (indices mod N) | grains × grain length, vectorised per grain | grain count loop in Python (1-6 k grains) | **use** |
| Spectral freeze (magnitude of a source, seeded random phases, PaulStretch-like, A9) | texture from own renders | exact (one N-point irfft) | one FFT | needs a source: v0.2 with library input | **v0.2** |
| FDN reverb (`laser_fx.reverb_wet`) in steady state | all | steady state after P loops (M5) | 0.65-0.77 s per 16-bar pass (M5) × (P+1) | energy match is one scalar over the processed block: compute it on the kept period | **use** |
| Generative model | — | — | — | rejected by D-005; would need the user to reopen it | no |
| Max for Live granular devices | — | — | — | rejected by D-001 | no |

### 7.2 Build order

1. **Contract PR** (`contract-change`): `contracts/atmos-params.schema.json` v0.1 from section 6, `atmos` in `sample-metadata` `category`, sidecar features, `CONTRACT_CATEGORIES` in `categories.py` follows in the engine PR.
2. **Circular toolkit** (in `atmos.py` or `atmos_dsp.py`): `loop_samples(p)`, `circ_noise(seed_streams, N, H)`, `circ_filter(x, H)`, `periodic_curve(cycles, shape, rng, N)` (built from `fx.sin_cycles`, so no platform `sin`), `mono_below(x, f)`, `steady_state(stage, x, preroll)`, `circ_overlap_add(grains, onsets, N)`.
3. **noise_bed** (circular noise + tilt + HP/LP + SVF movement with 1 pre-roll + level/pan movement + mono-below + reverb steady state + normalise). First golden hashes.
4. **drone** (bin-locked partials, detune by bins, drift curves; rule C).
5. **resonant** (noise × partial-comb magnitude response, Q `res_q`).
6. **granular** (internal source render, seeded grain plan from its own substream).
7. Sidecar features, presets (a few per kind, named by content not by genre unless the user gives references), GUI page via the registry, CLI.

### 7.3 Tests (CI)

- **Seam, independent reference:** for each kind, a test re-implements the linear path for the circular stages (its own 2nd-order filter or `np.convolve` with an IR written in the test), runs it over 3 tiled periods, keeps the middle one, and compares with the engine: < 1 LSB. Fault injection: N + 1 frames; one partial at k + 0.01 bins; pre-roll 0 instead of P; `move_cycles` 2 → 2.01 — each must turn red.
- **Seam metrics:** step test for tonal kinds, click test for noise kinds (section 3 limits), seeded property test over bpm 60-200, all `bars`, both rates.
- **Length:** property test N == round(240 · bars · sr / bpm) over the full range; `bpm × 1.02` must break it.
- **Byte re-render:** same params + seed → identical sha256; golden hashes per kind on Ubuntu and Windows CI (cross-platform caveats as fx docstring).
- **Spectrum targets:** `lf_leak_db` below `hp_hz`, energy above `lp_hz`, flatness ordering noise_bed > resonant > drone, fundamental in cents by two methods vs the sidecar's `tuning_error_cents`.
- **Movement:** DFT of the band-energy envelope peaks at `move_cycles`.
- **Stereo:** correlation ≥ 0.99 below `mono_below_hz`; width monotonic.
- **Convergence guard:** the engine asserts that one extra pre-roll changes nothing (bit-equal or < 1 LSB) for the SVF; a test covers the worst corner (`hp_hz` 20, Q 12, 1 bar at 200 BPM).
- **Not in CI:** anything in Live (X1-X3), any listening.

## 8. What only the user can judge

| ID | Question | Default proposed |
| --- | --- | --- |
| U1 | Loop lengths you would use (4 / 8 / 16 / 32 bars) | 8 bars |
| U2 | Non-tonal beds (air, wind) or tonal drones first | noise_bed first (planner uses atmos in ~90 % of bars, A5) |
| U3 | Drone key: fixed note per file, or from the arrangement plan's key | per-file `note`, default C2 |
| U4 | Tuning tolerance for drones (the engine can only hit a bin; short loops miss by up to 16 cents at low notes, M4) | 5 cents |
| U5 | Do you change the Set tempo after importing? (Re-Pitch retunes a drone; Texture/Complex Pro do not, L3) | render at the final tempo |
| U6 | Stereo: width, and mono below 120 Hz | width 0.7, mono below 120 Hz |
| U7 | Also one-shot swells (fade in/out) or only loops | both, loop default |
| U8 | Reference atmos/drone files you like (for a measurement round by the sound-designer) | none yet |

## 9. Implications for the lead

1. **Category entry:** D-028 item 3 froze categories; record a decision (as D-030/D-032 did for laser, perc, fx) that `atmos` is a category, citing the user's 2026-11-08 20:51 message. Then a `contract-change` issue for `atmos-params` v0.1 (owner audio-engineer) with section 6 as input.
2. **Scope boundary with the Goa plugin (D-027):** the Goa plugin owns the melodic pad as MIDI. A rendered `drone` is one held note/chord as audio, not a voice; the lead should state this split in the decision so the two do not overlap. The user said he does not need synth voices now (#518), which fits.
3. **Engine issue** (audio-engineer) with section 7; first deliverable `noise_bed` + the seam test with an independent reference.
4. **Bridge-engineer issue** for X1-X3 (guide in `docs/setup/`) and, separately, registering `clip.warping`, `clip.looping`, `clip.warp_mode` as `unknown` capabilities (L7); no code may set them before they are `tested`.
5. **Planner adapter** (orchestrator-engineer, later): the timeline's `atmos` / `pad` elements could map to `noise_bed` / `drone` files of a section's length; not before the engine merges.

## Sources (all opened 2026-11-08)

- Ableton, Live 12 Reference Manual: [ch. 8 Clip View](https://www.ableton.com/en/live-manual/12/clip-view) (8.2.1, 8.4.4, 8.9); [ch. 9 Audio Clips, Tempo, and Warping](https://www.ableton.com/en/live-manual/12/audio-clips-tempo-and-warping) (9.2.1, 9.2.4, 9.2.5, 9.3); [ch. 29 Live Audio Effect Reference](https://www.ableton.com/en/live-manual/12/live-audio-effect-reference) (29.2, 29.3, 29.8, 29.10; page read only up to 29.21).
- Ableton Help, [Create Fades on Clip Edges to avoid clicks](https://help.ableton.com/hc/en-us/articles/209069969-Create-Fades-on-Clip-Edges-to-avoid-clicks) (no date on the page).
- AbletonOSC, `abletonosc/clip.py` lines 94-115, [raw master](https://raw.githubusercontent.com/ideoforms/AbletonOSC/master/abletonosc/clip.py), sha256 `966ba33a8ba5727cd37824bb5929b5ff82bbbaabb47ac50538b5b42e1f66c71d`.
- J. O. Smith III, *Physical Audio Signal Processing* (2010): [Feedback Delay Networks](https://ccrma.stanford.edu/~jos/pasp/Feedback_Delay_Networks_FDN.html), [Choice of Delay Lengths](https://ccrma.stanford.edu/~jos/pasp/Choice_Delay_Lengths.html); *Mathematics of the DFT* (2nd ed., 2007): [Convolution](https://ccrma.stanford.edu/~jos/st/Convolution.html).
- Csound manual, [paulstretch](https://csound.com/manual/opcodes/paulstretch/).
- Wikipedia, [Drone (music)](https://en.wikipedia.org/wiki/Drone_(music)); [Granular synthesis](https://en.wikipedia.org/wiki/Granular_synthesis).
- MusicRadar: [How to create an ambient techno atmosphere](https://www.musicradar.com/how-to/techno-ambience-atmosphere) (2023-12-06); [found sounds into atmospheric drone textures](https://musicradar.com/how-to/how-to-turn-found-sounds-into-atmospheric-drone-textures) (2019-04-19); [8 ways to add atmosphere and ambience](https://www.musicradar.com/how-to/8-ways-to-add-atmosphere-and-ambience-to-your-music) (2017-05-23).
- Opened but not used (no technique content): Attack Magazine, [2020 best-read technique articles](https://attackmagazine.com/?p=91272).
- Repo evidence: #345 comments (user's device lists), notes linked in the header.
