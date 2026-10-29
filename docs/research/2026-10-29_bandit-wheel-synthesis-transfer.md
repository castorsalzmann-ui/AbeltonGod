# Research: Bandit Wheel synthesis recipes and their transfer to the deterministic engine

- **Date:** 2026-10-29
- **Receiving issue:** #151 (technical half; the musical/genre half — patterns, roles, presets, mix levels — is the sound-designer's note for the same issue and is not repeated here)
- **Author role:** audio-engineer
- **Scope:** synthesis recipes for bass / rumble / acid (303-style), hats (closed, open, ride, shaker), clap / snare / rim, percussion (tom, conga, bongo, bell, clave, tambourine, cowbell, metal). For each: sources, filters, envelopes, saturation, layering, randomness, and what it takes to render it deterministically in `src/audio_engine/` (D-005, D-013). Read only; no repo code changed; no contract changed. No sound claims: everything below describes code and signals, never how something sounds.
- **Status:** read from the artifact source, **not verified** by rendering, except one timing probe (section 1.6). The artifact was treated as data and not executed.
- **Required context:** [kick-gen2-learnings](2026-10-28_kick-gen2-learnings.md) (rules in its section 5 apply unchanged: one shared parameter space per category, never gate the best result, every exposed parameter must move an analysis value, aliasing needs a test).

## Versions researched against

| Item | Version / state | Source |
| --- | --- | --- |
| Bandit Wheel artifact | local copy `bandit_wheel.html`, 9,259 lines, sha256 `d236360c714cb6b9dbe71aed7543b258702e16abedcd3da5dc5ee0a15795497f` (copy in the lead's scratchpad; original https://claude.ai/artifact/9csbPrDx456qtpELV84Cka) | file |
| AbeltonGod engine | `origin/main` at 84ed39a (`src/audio_engine/dsp.py`, `kick.py`) | repo |
| Python / NumPy used for the timing probe | CPython 3.13.18, NumPy 2.5.4, 2 cores | `.venv` |
| Web Audio API | **not opened this session** (w3.org and the spec's GitHub repo were blocked by the session proxy). Statements about Web Audio semantics are from memory and are marked *unverified* | — |

All `L<n>` references below are line numbers in that file. "Knob" values in the artifact run 0 … 100; ranges are written as "min … max over the knob range".

## Short answers

| # | Question | Answer in one line | Confidence |
| --- | --- | --- | --- |
| Q1 | Are the artifact's recipes deterministic? | The **sequencing and noise** are (seeded mulberry32, L2559, L2850); the **seeds themselves** come from `Math.random` (L2859, L4155–4160), and most drum and bass voices render through `OfflineAudioContext` nodes whose numerics are browser-defined. | high (code read) |
| Q2 | Which recipes are already plain sample-by-sample JS and can be ported line for line? | The 303 voice (L2673–2748), its delay (L2751–2769), the RBJ biquads (L4604–4630), the transition snare (L4872–4880), the SVF (L4866), grit (L4722–4738), duck (L3912–3926). | high |
| Q3 | Which recipes need a re-implementation of Web Audio nodes? | Hats, ride, shaker, clap, snare, rim, tom/conga, FM bell, tambourine, cowbell (L3363–3484), bass (L3948–4095), kick rumble (L1537–1555), the voice reverb (L3447–3459). Needed: band-limited oscillators, RBJ LP/HP/BP/peaking with the right Q meaning, Web-Audio-style envelopes, tanh waveshaper with oversampling, FFT convolution with a defined normalisation. | high |
| Q4 | What does not transfer? | Real-time scheduling and the UI; `Math.random` seed creation; browser-defined oscillator, waveshaper-oversampling and convolver-normalisation numerics (re-implemented, not ported); "golden"/tier rarity (P1); stereo outputs until a contract allows them. | high |
| Q5 | Is a per-sample Python loop fast enough for the 303 ladder? | A probe of the ladder core runs at **1.19 µs/sample** (0.41 s for 7.11 s of audio at 48 kHz). The full voice has more per-sample work; not measured. | medium (one probe, section 1.6) |

## 1. Cross-cutting findings (apply to every category)

### 1.1 Randomness

| What | Where | Deterministic? | Transfer |
| --- | --- | --- | --- |
| mulberry32 PRNG (two copies) | L2559 `rng`, L2850 `bwRng` | yes, given the seed | Replace by NumPy `default_rng` as in `kick.py:179`. Matching the artifact's random stream is not a goal. |
| Seed creation | L2859 `bwSeed = Math.floor(Math.random()*1e6)`, L4155–4160 (acid spin), L1199/L1201 (kick) | **no** | Seed is a parameter (D-005). Does not transfer. |
| Per-layer sub-seeds by addition | closed hat `seed+1`, open hat `seed+99` (L3368); clap `+3` (L3402); snare `+5` (L3417); perc noise `+11` (L3431); reverb IR `seed+7`, right channel `+77` (L3733, L2946); tambourine noise `+31` (L3472); clave voice `+9` (L3491); metal voice `+13` (L3493) | yes | **Transfer with changes.** Additive offsets collide across voices: the open-hat noise of seed *s* is the closed-hat noise of seed *s*+98. Derive sub-streams with `np.random.SeedSequence([seed, layer_id])` (or an equivalent fixed hash), so layers stay independent and the same seed still gives the same bytes. |
| Seed range folding | `this.state.seed % 1000` for hats, clap, perc (L3652, L3721, L3862) | yes | Does not transfer: it limits every drum voice to 1,000 distinct noise streams. Use the full seed range of the contract. |
| Seed derived from the sound, not from the seed | kick rumble IR seeded by `freq*997 + rumbleLen*7919` (L1541) | yes | Transfer with changes: the rumble IR cannot vary by seed in the artifact. In ours it should come from `seed` (sub-seed "rumble"). |
| Seeded parameter jitter | acid knobs drawn inside a mode's ranges (L2565–2569), perc knobs per style (L3774–3782), tambourine detune `1 + (seed % 7) * 0.003` (L3471) | yes | Transfers as the `variants` mechanism already does it (`variants.py`): a variant draws inside a box around the base value. Ranges per style are the sound-designer's topic. |
| Rarity tiers and "golden" draws | `tier` 70 / 25 / 5 % (L2893–2897, L4155); acid `textbook()` sets fixed seeds 1001…4004 and `golden` (L4164–4169) | no (random tier) | Does not transfer (kick-gen2 P1: never gate the best result). The fixed "textbook" seeds are a useful idea in a different form: a named preset with a fixed seed, directly reachable. |

### 1.2 Web Audio nodes → our DSP

| Artifact construct | Where | Our equivalent today | Change needed |
| --- | --- | --- | --- |
| `OfflineAudioContext` render of a node graph | L2928–2934, L3354–3361 | `render_resolved` in `kick.py` (offline NumPy) | Re-implement each node; output will not equal the browser's samples, and does not need to. |
| `BiquadFilterNode` `bandpass` (constant 0 dB peak, Q linear) | `bwFilt` L2951 | `dsp.biquad_bandpass` (RBJ, constant 0 dB peak gain) | Transfers as is, **if** the Web Audio band-pass is the RBJ constant-0-dB-peak form with linear Q (unverified, from memory; part of V3). |
| `BiquadFilterNode` `lowpass` / `highpass` | `bwFilt` L2951 (default `Q = 0.707`) | none (only one-pole LP/HP) | Add RBJ LP/HP (`bwBq` L4604–4613 is the RBJ cookbook in plain JS). **Q meaning differs (unverified, from memory of the Web Audio spec):** for `lowpass`/`highpass` the node's Q is a resonance in **dB**, i.e. linear Q = 10^(Q/20); for `bandpass`/`peaking` it is linear. So the artifact's "Q 0.707" LP/HP is linear ≈ 1.085, the bass filter `Q = 1 + grit*5` (L4076) is 1 … 6 dB, linear 1.12 … 2.0, and the rumble LP "Q 1.1" (L1546) is linear ≈ 1.135. To verify (V3). |
| `BiquadFilterNode` `peaking` without Q set | hat L3371 (+4 dB) | none | RBJ peaking (`bwBq('bell')` L4610). Default Q of the node is 1 (unverified). |
| `OscillatorNode` square / sawtooth / triangle | hats L3367, ride L3390, rim L3435–3437, tamb L3471, cowbell L3480, snare L3415, bass L3948–3958 | none | Web Audio renders these band-limited (implementation-defined, unverified). Ours: additive band-limited synthesis for fixed frequencies (sum of harmonics below Nyquist; exact and cheap in NumPy), polyBLEP (as L2675) for swept frequencies. A naive `np.sign(sin)` square would alias: the tambourine's 8,900 Hz square already has its 3rd harmonic (26.7 kHz) above Nyquist at 48 kHz. |
| `AudioParam` envelopes | `bwEnv` L3345–3353, `bwAmp` L3960–3965 | `_amp_envelope` (`kick.py:161`, linear attack, exponential decay to −60 dB) | Closed forms (unverified, from memory of the spec): `linearRamp` = straight line; `exponentialRamp` from v0 to v1 over [t0, t1] = v0·(v1/v0)^((t−t0)/(t1−t0)); `setTargetAtTime` = v1 + (v0−v1)·e^(−(t−t0)/τ). `bwEnv(peak, attack, dur)` = linear 0 → peak over `attack`, exponential from peak to the absolute value 0.0008 (≈ −62 dB at peak 1) over `dur`, then linear to 0 in 10 ms. **Maps onto our decay semantics:** `dur` ≈ "decay to −62 dB", close to the kick contract's "decay to −60 dB" (`amp_decay_ms`). Keep the −60 dB definition and convert. |
| Pitch envelopes | snare `exponentialRamp` 1.6·f → f in 30 ms (L3415); tom/conga `setTargetAtTime(f, τ = 7 / 4 ms)` from 1.25·f / 1.3·f (L3429) | `body_phase` (`kick.py:154`) integrates an exponential pitch drop | Transfers with changes: integrate the instantaneous frequency to a phase (closed form or cumulative sum), as the kick already does. |
| `WaveShaperNode` tanh curve, `oversample '2x'` / `'4x'` | `bwShaper` L2952–2956 (bass), kick L1505–1507 | `dsp.oversampled` + Kaiser low-pass (`dsp.py:100–148`) | Transfers with changes: apply `tanh(a·x)/tanh(a)` directly (no 1,024-point lookup table and its interpolation) inside `dsp.oversampled`. Our oversampling filter is defined by us; the browser's is not. Aliasing test required (kick-gen2 M9). |
| `ConvolverNode` with `normalize = true` | voice reverb L3454, FX bus L3942, kick rumble L1543 | none | FFT convolution (NumPy) transfers; the browser's normalisation scale is implementation-specified (unverified). Define our own: e.g. scale the IR to unit energy, write the rule into the future contract. |
| 24-bit WAV writer | L2794–2806 | `io.encode_wav` | Ours already exists; nothing to take. |
| Per-voice cache keyed by `JSON.stringify(params)` | `bwVoice` L3337–3344 | `length.py` caches by params key | Same idea; nothing new. |

### 1.3 Sample rate, precision, control rate

- The artifact renders at **44.1 kHz** (`SR` L2841; kick L1487) in **Float32**. Ours: 48 kHz, float64. All recipe constants are in seconds and Hz, so they carry over. Exceptions: the 303 updates filter coefficients every 4 samples and automation every 32 samples (`n&3`, `n&31`, L2715, L2717, L2724). At 48 kHz that is a shorter control interval in seconds. Byte equality with the artifact is neither reachable nor a goal; equality between two of our renders is (D-005).
- Peak handling: drum voices are peak-normalised to 0.8 (0.7 for tambourine and cowbell) and get a 256-sample linear end fade (`bwMono` L3354–3361). Ours: final ceiling −0.3 dBFS measured on the quantised file and a 5 ms fade (`kick.py:266`, `:288`). Keep ours.

### 1.4 Output format

- Voices are written as **stereo pairs**, often `[d, d]` (identical channels, L3360). True stereo appears only through the reverb IR (two seeded channels, L2945–2948), the 303 ping-pong delay (L2751–2769) and placement pan (L2901–2912). Our engine writes mono, and `contracts/sample-metadata.schema.json` allows only `"category": "kick"` (line 12). So: one-shots transfer mono; stereo reverb/delay tails need a `contract-change` (channels, new categories) first.
- Loops: the artifact folds the tail past the loop end back to the start (`bwFoldTail` L2913–2921, `finish` L2771–2777) and runs biquads twice so the state at the loop start equals the end (`bwBqRun` L4615–4630). Both are plain JS and transfer as is **if** loops ever become an output; one-shots do not need them.

### 1.5 Saturation families seen

| Shape | Where | Note for ours |
| --- | --- | --- |
| Rational tanh approximation `x(27+x²)/(27+9x²)`, hard-limited at \|x\| > 3 | `sat` L2674 (303 ladder input and output drive) | Has a kink in its derivative at \|x\| = 3 (value there is exactly 1). Plain `np.tanh` is an alternative; which one to use is a measurement question (V5). |
| `tanh(a·x)/tanh(a)` | bass L2952–2956, rumble `shaperCurve('tanh', 2.5)` L1553 | Same family as the kick's `drive`. |
| Kick curve families hard / fold / tanh / asym | `shaperCurve` L1468ff | Already listed as a candidate in kick-gen2 P5; not repeated. |
| Loop grit: tanh wet/dry on the loop scaled by its loudest 10 ms RMS × 2.2, then a fast compressor | `bwGrit` L4722–4738, `bwGlue` L5212 | Loop/mix processing, not a one-shot recipe. Plain JS, transfers as is if needed. |

### 1.6 Timing probe (the only thing run in this session)

A plain-CPython loop with the structure of the 303 core (polyBLEP saw, 4-pole zero-delay ladder with `sat` in the feedback path, coefficient update every 4 samples; not a port, not repo code; the script exists only in the author's session scratchpad and is not reproducible from the repo — V7 should put a timing script into the repo or the issue) rendered 341,280 samples (7.11 s at 48 kHz) in **0.41 s, 1.19 µs/sample**, and two renders were byte-identical (sha256 equal). Command: `python -I ladder_timing.py 7.11` with the repo `.venv`. The full voice (gate/accent smoothers, glide, drive, DC blocker, delay) adds work; its cost is not measured.

## 2. Bass, rumble, acid (303-style)

### 2.1 Recipes found

**Acid voice** (`renderSynth` L2673–2748; knobs L4109–4119, all 0 … 1 inside the renderer):

| Block | What the code does | Lines |
| --- | --- | --- |
| Oscillator | polyBLEP saw, or polyBLEP square × 0.75; phase accumulator; pitch kept as log2(Hz) | L2675, L2717–2721 |
| Glide | one-pole on log2 frequency, τ = 20 ms, only on a slid note while the gate is held | L2697, L2711, L2716 |
| Gate | note off at 55 % of the step unless slid; ties extend the note | L2685–2693 |
| Filter | 4-pole zero-delay-feedback ladder (four TPT one-poles), `sat()` on input minus feedback, k = 3.9·res (res ≤ 0.98), output gain 1 + 0.3·k; cutoff clamped 30 Hz … 0.42·sr; coefficients every 4 samples | L2727–2739 |
| Cutoff map | base = 80·2^(5.6·cut) Hz (80 Hz … 3.9 kHz) | L2695 |
| Filter envelope | per-note exponential decay; τ = 0.08·2^(4.1·dec) s (80 ms … 1.37 s); depth 0.5 + 4.2·env octaves (0.6× on accents) | L2695, L2699, L2722, L2725 |
| Accent | accented notes: fixed 90 ms filter-envelope decay, plus a smoothed "accent sweep" (one-pole, 12 ms rise / 120 ms fall) of up to 2.6·acc octaves; amplitude × (1 + 0.9·acc) | L2698–2699, L2712, L2723, L2725, L2742 |
| Amp | one-pole gate follower, 1.2 ms attack / 6 ms release; slow decay τ = 3 s blended 0.62 + 0.38 | L2697, L2699, L2740–2742 |
| Automation | cutoff offset in octaves from a closed-form curve per mode (sine sweeps, rise, fall) | L2659–2670, L2715 |
| Drive | `sat(fo·lvl·(1+7·drv)·0.8)` normalised by `sat` of its max | L2702, L2743 |
| DC blocker | one-pole high-pass 30 Hz | L2701, L2744 |
| Delay (stereo) | ping-pong, 3 sixteenths, feedback 0.46, one-pole LP 3.2 kHz + HP 280 Hz in the loop, send 0.95·dly | L2751–2769 |
| Level | peak-normalised to −1 dBFS (dry and wet separately), later 0.89 | L2778–2790, L4182 |
| Pattern / note choice | seeded rhythm cell, weighted scale pool, random walk, accents, slides per mode | L2572–2656 (musical side, sound-designer) |

**Bass voice** (`BassMachine.render` L4065–4095, oscillators `bwOscs` L3948–3958):

| Block | What the code does | Lines |
| --- | --- | --- |
| Oscillators | saw or square (0.7); "sub" = sine f (0.9) + sine 2f (0.18); "dirty" = saw −6 ct (0.5) + square +6 ct (0.35); "reese" = saws ±13 ct (0.45 each) + sine f/2 (0.5) | L3951–3957 |
| Filter | per-note LP, cut = 70 + (cutoff/100)²·2600 Hz (70 … 2,670 Hz), Q = 1 + 5·grit/100 (Web Audio LP: dB, see 1.2) | L4069, L4076 |
| Filter envelope | starts at 3.2·cut (1.2·cut for reese/sub/reverse), exponential ramp to cut within min(note, 90 ms) | L4077 |
| Wobble | LFO at 2·BPM/60 Hz (eighth notes), depth 1.8·cut Hz added to cutoff | L4078–4081 |
| Amp | linear 3 ms attack, hold, 20 ms linear release, peak 0.6 (0.6 / 0.45 for the 16th run); "reverse" = exponential swell over 92 % of the note | L3960–3965, L4083–4084 |
| Saturation | shared tanh waveshaper, a = 1 + 6·grit/100, 2× oversampling, then LP 9 kHz, HP 28 Hz | L4071–4072, L2952–2956 |
| Sidechain duck | gain envelope per kick hit: 4 ms linear dip, exponential recovery τ = 110 ms, depth 0.85·duck | L3912–3926, L4090 |
| Level | gain = min(0.92/peak, 0.17/RMS) (RMS-targeted) | L4091–4093 |
| Register | MIDI 28 + key offset (E1 …), +12 except rumble/reese/sub/reverse | L4013 |

**Kick rumble tail** (`renderKick` L1537–1555): the amplitude-enveloped kick body (before the waveshaper) is convolved with a seeded noise IR, noise·e^(−i/(len/3.5)), length min(60/BPM, 0.35 … 0.7 s); then LP 90 … 150 Hz ("Q 1.1", dB), tanh shaper a = 2.5, a gain ramp 0 → level over 70 ms, hold, linear to 0 at the IR length; mixed before the kick's final LP. Level 0.12 … 0.55 (L1443–1448, L1463).

### 2.2 Transfer table

| Element | Verdict | What changes |
| --- | --- | --- |
| 303 oscillator (polyBLEP saw/square), glide, gate, ladder, accent sweep, amp follower, DC blocker | **transfers as is** (algorithm) | Port to a Python sample loop (feedback forbids vectorising the ladder). float64 instead of Float32; 48 kHz. Event list from a deterministic note list instead of the pattern generator. |
| 303 drive | **transfers with changes** | `sat` runs at the base rate inside and after the ladder, no oversampling: needs an aliasing test (M9). Oversampling the whole voice (render at 2–4× then decimate with `dsp.kaiser_lowpass`) keeps the ladder and drive band-limited; cost ×2–4 (V2). |
| 303 automation curves | transfers as is | Closed-form functions of bar position; deterministic. In a one-shot or short loop they become an optional "cutoff offset over time" parameter. |
| 303 ping-pong delay | transfers with changes | Plain JS, deterministic. Stereo output needs a contract change; a mono echo variant does not. |
| 303 knob ranges per mode, `filterFromSeed` | transfers with changes | Ranges become optional preset data on one parameter space (kick-gen2 P2); musical values belong to the sound-designer's note. |
| Bass oscillator set (saw, square, sub, dirty, reese) | **transfers with changes** | Band-limited oscillators (polyBLEP or additive). Detune in cents as in the artifact. Each oscillator's start phase must be a defined value (the artifact creates a new oscillator node per note, L4085; what start phase the browser gives it is not established here; ours must state it). |
| Bass LP with exponential cutoff envelope and wobble LFO | transfers with changes | Time-varying RBJ LP (per-sample or per-block coefficients) or a TPT state-variable filter; clamp the modulated cutoff to > 0 Hz (artifact relies on the browser's clamp when depth 1.8·cut drives it negative, unverified). Q in linear units (see 1.2). |
| Bass tanh shaper + 2× oversampling | transfers with changes | `dsp.oversampled` with a direct tanh; aliasing test. |
| Duck / RMS-targeted level | transfers as is | Loop-level processing; only relevant once loops or a kick-relative level exist. A one-shot bass sample is not ducked. |
| Kick rumble (noise-IR convolution → LP → tanh → gain ramp) | **transfers with changes** | FFT convolution in NumPy; IR from `seed` sub-stream (not from `freq`); define IR normalisation ourselves; LP Q in linear units. Belongs to kick-params as candidate S3, not to a bass category. |
| Real-time `AudioParam` scheduling, `OfflineAudioContext` | does not transfer | Replaced by offline sample arrays. |
| Mode "tiers", textbook gold flag | does not transfer | P1. |

### 2.3 Candidate parameter set (for a future `bass-params` / `acid-params` contract; no change now)

One shared space for bass and acid would follow kick-gen2 P2; whether acid is its own category is a product decision. Names below are proposals:

- `osc_shape` (saw / square / sub / detuned pair), `detune_cents`, `sub_level`, `note` (MIDI) or `pitch_hz`, `length_ms` / `length_beats`, `glide_ms` (+ a two-note form for a slide one-shot), `seed`.
- `cutoff_hz`, `resonance` (0 … < self-oscillation, the artifact caps k at 3.9·0.98), `env_mod_oct`, `env_decay_ms` (with a defined meaning, e.g. time to −60 dB of the envelope, as #7 did for the kick), `accent` (0 … 1, with the artifact's three effects: env decay, sweep, level).
- `drive`, `drive_curve` (tanh / rational), `amp_attack_ms`, `amp_release_ms`.
- Excluded for one-shots: duck, delay, automation over bars (loop parameters).

## 3. Hats (closed, open), ride, shaker

### 3.1 Recipes found

| Voice | Sources | Filters | Envelope | Lines |
| --- | --- | --- | --- | --- |
| Closed / open hat | 6 square oscillators at 205.3, 304.4, 369.6, 522.7, 540, 800 Hz × (1 + 0.6·tone/100), each gain 0.12·metal; plus seeded white noise, gain 0.9·(1 − metal) + 0.15 (metal 0.10 … 0.75 from the TONE reel) | HP 5,000 + 45·tone Hz (5.0 … 9.5 kHz, "Q 0.707" dB), peaking 8,500 + 30·tone Hz +4 dB (Q default), LP 18 kHz or 6.5 kHz ("lofi") | linear 0.8 ms attack, exponential to 0.0008 over dur: closed 15 + 1.2·decay ms (15 … 135 ms), open 120 + 5·decay ms (120 … 620 ms); +10 ms linear to 0 | L3362–3376, L3617–3621, L3652 |
| Open-hat choke | open hat cut at the next closed or open hat, 256-sample linear fade | — | — | L2968–2975, L3663–3666 |
| Ride | same 6 squares × (2.2 + tone/100), gain 0.1 each; plus a noise "tick" | squares: BP 7.5 kHz Q 0.6, HP 5 kHz; tick: HP 7 kHz | squares: 1 ms / 250 + 11·decay ms; tick: peak 0.35, 0.6 ms / 50 ms | L3387–3397 |
| Shaker | seeded noise | BP 4,500 + 55·tone Hz Q 1.5, HP 3 kHz | 12 ms linear attack, dur 40 + 1.6·decay ms | L3378–3386 |
| Level, ends | peak 0.8, 256-sample end fade | — | — | L3354–3361 |

### 3.2 Transfer table

| Element | Verdict | What changes |
| --- | --- | --- |
| Six-square metallic bank (fixed frequency ratios) + noise mix | **transfers with changes** | Additive band-limited squares (odd harmonics below Nyquist) at fixed frequencies: vectorised, exact, deterministic. Start phases fixed (all 0, or a seeded set; must be stated). |
| HP → peaking → LP chain | transfers with changes | RBJ HP/LP/peaking (port `bwBq` L4604–4613); Q converted from the artifact's dB convention for HP/LP (V3). |
| Exponential envelope with `dur` to −62 dB | transfers with changes | Express as decay to −60 dB (our convention) plus attack; closed form in NumPy. |
| Open-hat choke | transfers with changes | In a one-shot world: an explicit `length_ms` / choke time with our 5 ms fade (not 256 samples). The pattern-level choke belongs with patterns. |
| Ride, shaker | transfer with changes | Same building blocks (squares, noise, BP/HP, envelope). |
| Seeds `seed % 1000 + 1 / + 99` | does not transfer | SeedSequence sub-streams (1.1). |

### 3.3 Candidate parameter set (future `hat-params`; no change now)

`open` (bool or a continuous decay), `decay_ms` (to −60 dB), `tone` (shared multiplier of oscillator frequencies and filter corners, as the artifact couples them; or separate `osc_scale`, `hp_hz`, `peak_hz`, `peak_db`), `metal` (0 … 1 square-bank vs noise mix), `lp_hz`, `attack_ms`, `seed`. The artifact couples *tone* to three things at once; whether to keep that coupling is a design choice: kick-gen2 rule "every exposed parameter must move an analysis value" holds either way (spectral centroid, energy above 8 kHz).

## 4. Clap, snare, rim

### 4.1 Recipes found

| Voice | Sources | Filters | Envelope | Lines |
| --- | --- | --- | --- | --- |
| Clap | one seeded noise buffer | BP 900 + 16·tone Hz (0.9 … 2.5 kHz) Q 1.4 **before** the gain envelope, HP 450 Hz after | three bursts at 0 / 11 / 22 ms, levels 1 / 0.85 / 0.75, each exponential to 0.06 in 9.5 ms; tail from 31 ms at 0.7, exponential to 0.0008 over 60 + 3·decay ms (60 … 360 ms) | L3399–3410 |
| Snare | triangle oscillator, pitch 1.6·f → f exponential in 30 ms, f = 150 + 1.3·tone Hz (150 … 280 Hz); seeded noise | noise: HP 1,200 + 10·tone Hz | tone: peak 0.9, 0.8 ms, 70 + decay ms; noise: peak 0.8, 0.8 ms, 80 + 2.5·decay ms | L3411–3421 |
| Clap + snare layer | sum 0.6 + 0.6 of the two rendered voices, no time or phase alignment beyond sample 0 | — | — | L3727–3731 |
| Rim | square at f (1.7 … 2.3 kHz as `1700 + 6·tone`, L3726) through BP at f, Q 6; plus triangle at 0.28·f | — | square: 0.4 ms / 12 + 0.4·decay ms; triangle: peak 0.5, 8 ms | L3434–3437, L3725–3726 |
| Transition snare (pure JS) | seeded noise, first difference + one-pole smoothing (0.6/0.4); sine `sin(2π·(175 + 60·e^(−t/10 ms))·t)`: the frequency term multiplies t instead of being integrated, so the instantaneous frequency is 175 + 60·e^(−t/τ)·(1 − t/τ) Hz (235 Hz at t = 0, below 175 Hz after 10 ms, minimum ≈ 166.9 Hz at 20 ms, then back toward 175 Hz) | — | noise e^(−t/75 ms) · 0.9; sine e^(−t/50 ms) · 0.55; 220 ms | L4872–4880 |
| Room | voice convolved with a seeded stereo noise IR (noise·(1 − i/n)³), length 0.4 + 0.02·room s; HP 300 Hz before the convolver; wet 0.9·room/100; `normalize = true` | — | — | L3447–3459, L2941–2950, L3733 |

### 4.2 Transfer table

| Element | Verdict | What changes |
| --- | --- | --- |
| Clap multi-burst envelope on band-passed noise | **transfers with changes** | Piecewise closed-form envelope in NumPy (the artifact's event order: set, exponential ramp, hold until the next set). Burst count, spacing and levels become parameters. `biquad_bandpass` exists already (same RBJ form, constant 0 dB peak). |
| Snare tone + noise layers | transfers with changes | Band-limited triangle (or sine as in L4877) with integrated pitch envelope; RBJ HP on seeded noise. |
| Layer sum (clap + snare) | transfers with changes | Kick-gen2 "layer phase check" applies: measure band energy with each layer on and off. Layer offset in ms should be explicit (artifact: 0). |
| Rim (resonant BP on a square + low triangle) | transfers with changes | Q 6 band-pass on a band-limited square; short envelopes need the onset resolved finely in analysis (kick-gen2 M3). |
| Transition snare | **transfers as is** | Plain JS on a seeded noise array; replace mulberry32 by NumPy. Turning it into pitch parameters needs the real instantaneous-frequency curve above (dip below 175 Hz), not "175 + 60·e^(−t/τ) Hz". |
| Noise-IR room | transfers with changes | FFT convolution; our own IR normalisation; mono IR for a mono file, or stereo after a contract change. IR from a seed sub-stream. |

### 4.3 Candidate parameter set (future `clap-params` / `snare-params`; one space or two is open)

Clap: `bursts` (int), `burst_spacing_ms`, `burst_decay_ms`, `burst_level_falloff`, `tail_decay_ms`, `bp_hz`, `bp_q`, `hp_hz`, `room` (+ `room_length_ms`), `seed`. Snare: `tone_hz`, `tone_pitch_ratio`, `tone_pitch_ms`, `tone_decay_ms`, `noise_hp_hz`, `noise_decay_ms`, `tone_noise_mix`, `seed`. Rim: `pitch_hz`, `q`, `decay_ms`, `sub_ratio` (artifact 0.28), `sub_level`.

## 5. Percussion (tom, conga, bongo, bell, clave, tambourine, cowbell, metal)

### 5.1 Recipes found

| Voice | Recipe | Lines |
| --- | --- | --- |
| Tom / conga (bongo = conga one octave up) | sine from 1.25·f (tom) / 1.3·f (conga) toward f with `setTargetAtTime` τ 7 ms / 4 ms; envelope 0.6 ms attack, dur tom 60 + 2.2·decay ms, conga 50 + 2.5·decay ms; plus a 6 ms noise tick through BP 2.5 kHz Q 1.2 at 0.15 (tom) / 0.3 (conga). The code comment records that the earlier long tom with a 1.7× slide was replaced (L3424). | L3423–3433, L3490, L3494 |
| Bell / metal | 2-operator FM: carrier sine f, modulator sine 1.41·f, frequency deviation f·2 → f·0.05 exponential over dur; dur 120 + 6·decay ms. "Metal hits" = bell at the root of octave 6 × 1.41. | L3438–3444, L3493 |
| Rim / clave | rim recipe (section 4); clave = rim at 2.4 kHz, decay 30 | L3434–3437, L3491 |
| Tambourine | squares at 5,100 / 6,420 / 7,380 / 8,900 Hz × (1 + (seed mod 7)·0.003), 0.06 each, plus noise 0.7, HP 6.5 kHz, 4 ms attack, 130 ms dur, peak 0.7 | L3468–3476 |
| Cowbell | squares 540 + 800 Hz, BP 2.6 kHz Q 1.4, 1 ms / 120 ms, peak 0.7 | L3477–3484 |
| Tuning | percussion pitch = a scale degree of the song key (root, fifth, third degree, octave; options `deg` 0 / 4 / 2 / 7) in a fixed octave per voice. The option labelled `MINOR 3RD` is `deg: 2`, which `bwDegree` (L2884–2889) resolves to the scale's third degree, so it is a major third in major, Mixolydian and Lydian (label inconsistency, also reported in the sound-designer's note for #151), ± 2 semitones by the pitch knob: f · 2^((pitch − 50)/50 · 2/12) | L3798–3799, L3858, L3861 |
| Per-hit variation | none at voice level: one rendered voice per machine, placed with gain and pan per step | L3862–3872 |

### 5.2 Transfer table

| Element | Verdict | What changes |
| --- | --- | --- |
| Tom / conga sine with exponential approach to f + noise tick | **transfers with changes** | Same structure as our kick body (`body_phase`): pitch ratio and time constant become parameters. Analysis: tail pitch by zero crossings / instantaneous frequency (kick-gen2 pitfall 3). |
| FM bell | transfers with changes | Phase modulation in closed form: φ(t) = 2π∫(f + D(t)·sin(2π·1.41f·t))dt, D(t) exponential. Integrate with a cumulative sum in float64; the result is deterministic for the same params on the same platform. The index range (f·2 … f·0.05) creates partials far above f; check aliasing for high f (V2). |
| Tambourine, cowbell square banks | transfers with changes | Additive band-limited squares (the tambourine's fundamentals sit at 5.1 … 8.9 kHz, so only 1–2 harmonics are below 24 kHz). Seed-derived detune becomes an explicit `detune` parameter or a variant axis. |
| Key tuning by scale degree | transfers with changes | Our kick already takes `tail_note` (v0.3 contract, MIDI note → Hz). A shared `note` field for every tuned category keeps one convention; scale/degree logic belongs to the planner, not the engine. |
| Per-hit round-robin | does not exist in the artifact | Kick-gen2 S4 (deterministic per-hit variation from seed + hit index) applies to every category. |

### 5.3 Candidate parameter set (future `perc-params`; one space for all tuned membranes, separate small spaces for FM and square-bank voices, or one `model` enum)

Membrane: `note` / `pitch_hz`, `pitch_ratio`, `pitch_tau_ms`, `decay_ms`, `tick_level`, `tick_bp_hz`, `seed`. FM: `pitch_hz`, `mod_ratio` (artifact 1.41), `index_start`, `index_end`, `decay_ms`. Square bank: `freqs` (list) or `model` preset, `detune`, `hp_hz` / `bp_hz`, `bp_q`, `decay_ms`, `noise_level`.

## 6. What a future implementation needs in `dsp.py` (derived; not scope)

1. RBJ low-pass, high-pass, peaking (static), with linear Q; a documented conversion from the artifact's LP/HP dB-Q if its values are reused (V3).
2. A time-varying low-pass (bass filter envelope, wobble): per-sample or per-block RBJ, or a TPT state-variable filter. The artifact's Chamberlin SVF (`bwSvf` L4866) clamps its cutoff to 0.2·sr because that form becomes unstable higher up; a TPT form does not need that clamp (derived, V4).
3. The 303 ladder (zero-delay feedback, `sat` in the loop) as a sample loop.
4. Band-limited oscillators: additive for fixed frequencies, polyBLEP for swept ones.
5. FFT convolution with a defined IR normalisation.
6. Seed sub-streams per layer (`SeedSequence([seed, layer])`).
7. All existing per-sample loops in `dsp.py` (`biquad_bandpass`, one-poles) are pure Python; the probe in 1.6 says this speed class is ~1 µs/sample for a ladder-sized loop body.

## To verify by experiment

Each item becomes an issue for the audio-engineer when a category is scheduled (D-019).

- **V1 Determinism of each recipe as ported.** Render every recipe twice with the same params and seed: sha256 of the WAV bytes equal; with seed + 1: differs for every noise-bearing voice. Includes the layer sub-seed scheme (closed and open hat with the same seed must not share noise: correlation of the two noise streams ≈ 0).
- **V2 Aliasing** for every voice with a nonlinearity or a high-index FM: 303 drive and ladder, bass tanh, rumble tanh, FM bell at high f, square banks. Reference: the same voice rendered at 4–8× rate and decimated with an independent filter (kick-gen2 section 5). Report the achieved level; −90 dBFS is a proposal. Also measure the cost of oversampling the 303 loop.
- **V3 Web Audio Q semantics.** Open the Web Audio spec (BiquadFilterNode, "lowpass"/"highpass" use Q in dB; default Q value) and confirm or retract section 1.2 before reusing any artifact LP/HP Q value.
- **V4 Time-varying filter stability.** Sweep the bass filter envelope (3.2·cut → cut in ≤ 90 ms) and wobble at full depth through the chosen filter form; check for NaN/Inf and for output bursts above the input peak.
- **V5 `sat` vs `tanh`.** Harmonic content difference between the rational `sat` (L2674) and `np.tanh` at the drive levels the 303 uses; decide on a measured basis.
- **V6 Envelope convention.** Render `bwEnv` closed forms and our "−60 dB decay" with the converted value; the measured T60 (`length.py` method) must agree within the length rule's tolerance.
- **V7 Full 303 voice speed.** Time the complete voice (with accent, glide, drive, DC blocker) for 1, 4 and 16 bars at 48 kHz; decide whether a pure-Python loop is acceptable or whether a dependency (e.g. Numba) is needed. A new dependency needs its reason in the PR. The timing script goes into the repo or the issue (the 1.6 probe is not in the repo).
- **V8 Layer phase.** Clap + snare and tom + tick: band energy with each layer on and off (kick-gen2 "layer phase check").
- **V9 Contract scope.** Whether new categories become separate schemas or one schema with a `category` switch, and whether stereo (reverb, delay) is allowed — needs a `contract-change` issue; `sample-metadata.schema.json` currently allows only `"kick"`.

## Limits

- Read from source only. Nothing in the artifact was rendered; no browser output was compared with any Python output.
- Web Audio semantics (Q in dB for LP/HP, AudioParam ramp formulas, oscillator band-limiting, waveshaper oversampling, convolver normalisation) are from memory; the spec could not be opened in this session (proxy refused w3.org and the spec's GitHub repository). They are marked unverified and listed under V3.
- Musical content (patterns, genre mapping of reels, mix levels, clean-up EQ values in `bwEqDef` L4680–4695, arrangement) is deliberately left to the sound-designer's note for #151.
- The artifact's labels for its options (for example names of drum machines on the TONE reel, L3618–3621) are names, not measured facts, and are not used as evidence here (kick-gen2 pitfall 9).
- Numbers are the artifact's values, quoted to describe its recipes. They are prior art from the user's own prototype, not measured taste and not defaults for our engine; defaults need their own measurements and the user's listening.
