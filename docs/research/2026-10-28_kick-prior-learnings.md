# Research: Prior learnings for the kick engine

_Date: 2026-10-28 · Status: input for Phase 01 (#2, #3). Not a decision, not a spec, not a listening result._

## How to use this note

These are **lessons**, not a parameter table. They come from two sources, and neither one should be copied:

1. **"Bandit Wheel"**, an earlier browser prototype by the user (Web Audio, 18 genre profiles, slot-machine UI). Its value tables are deliberately **not** reproduced here. The goal is a better kick engine, not a port.
2. **37 reference kick one-shots** that the user picked from various Splice packs. They show the user's **taste in kicks** (what they choose), not how the user builds kicks. The audio is licensed and stays out of the repo. Only aggregate measurements appear below.

Use this note to choose defaults, variant axes and analysis methods. Derive your own values and verify them with tests and the user's ears (Phase 01 acceptance criteria).

## 1. Lessons from the prototype

| # | Lesson | Consequence for AbeltonGod |
| --- | --- | --- |
| P1 | The prototype hid its cleanest kick (centre of every range, zero random jitter) behind a 1 % / 0.2 % random "Gold/Platinum" draw. That is gamification, not quality. The user explicitly does not want the best results to be gated. | The best-balanced version of a preset is always directly reachable. Variants (`variants: N`) add range, never rarity. |
| P2 | 18 genre profiles with separate narrow ranges, each only reachable through 4 discrete steps, felt "too specific" to the user. | Presets are **starting points in one shared continuous parameter space**, not separate code paths. Blending and leaving a preset's range must stay possible. |
| P3 | Some controls only had names and no audible effect (e.g. drive labels). | Every parameter that gets exposed must change the sound measurably. The test is an analysis value that moves when the parameter changes. |
| P4 | Seeded PRNG (mulberry32) made every render reproducible. | Already required by D-005. Confirmed to be useful in practice for A/B comparison. |
| P5 | Character mostly came from a small set of building blocks: sine body + exponential pitch drop, amp envelope with a short **hold**, a **waveshaper with selectable curve family** (hard clip / tanh / asymmetric tanh / wavefold), band-filtered noise click, optional **separate sub sine**, optional **rumble tail** (noise convolved, low-passed, saturated), optional **two-layer body + top**. | `kick-params` v0.1 covers pitch env, amp env, click, `drive`, `tone`. **Not covered:** hold, curve family, separate sub, rumble, layering. These are candidates for later, not scope for #2/#3. Each needs a `parking-lot` issue and a `contract-change` PR before anyone builds it. |
| P6 | Cause → effect is more useful than genre labels. Faster tempo → shorter decay and brighter transient. Kick carries the bassline → longer, more tonal, more driven. Curve family = harmonic colour (hard clip harsh, tanh round, wavefold metallic), not loudness. Sub amount depends on what else fills the low end. Rumble is its own axis, independent of tempo. | Write preset descriptions and future Claude prompts in these terms ("short because 150 BPM"), not as genre facts. |

## 2. Taste fingerprint from 37 reference kicks

Method: mono sum, peak-normalised, all timing measured **from the onset** (first sample above −20 dB of peak). Envelope = 5 ms RMS. Tail pitch = instantaneous frequency (Hilbert phase) of a 700 Hz low-passed signal, median over 60 ms after onset until −30 dB, cross-checked by zero-crossing count. 41 files were supplied. 4 contained several hits (loops) and were excluded.

Accuracy check on synthetic kicks with known values: tail pitch within 4 %, pitch settle time and −40 dB decay within about 10 %. On the real files, the two tail-pitch methods agree within 5 % for 24 of 37 kicks. Two of three note-tagged kicks match their note (G# → 51.2 Hz, A → 54.7 Hz). The third, tagged F#, does not; cause not established.

| Measure | p25 | median | p75 | Confidence | Note |
| --- | --- | --- | --- | --- | --- |
| Tail fundamental (Hz) | 51 | 56 | 64 | Medium–high | Centre is around A1 (55 Hz). The schema default `pitch_end_hz: 48` sits at the low edge of this set. |
| Pitch settle, 90 % of drop done (ms) | 19 | 34 | 47 | Medium (n = 29) | For an exponential drop this is ≈ 2.3 × the time constant, so τ ≈ 8–20 ms. Map it onto `pitch_decay_ms` only after #7 defines its meaning. |
| Decay to −20 dB (ms) | 165 | 224 | 287 | Medium | |
| Decay to −40 dB (ms) | 217 | 326 | 398 | Medium | One kick never reaches −40 dB in its file. Compare with `amp_decay_ms` only once #7 defines its meaning. |
| Length to −60 dB (ms) | 252 | 343 | 423 | Medium | |
| Energy share below 100 Hz | 0.74 | 0.81 | 0.86 | High | Strongly sub-weighted; consistent across the set. |
| Onset (first 10 ms) energy share above 1 kHz | 0.06 | 0.21 | 0.41 | Medium | **Widest spread of all measures (p10 0.02, p90 0.60).** Click amount is where the user's picks differ most. |
| Tail harmonics 2–8 vs fundamental | 0.00 | 0.01 | 0.01 | Medium | Tails are almost pure sine. Audible saturation, if any, sits in the attack. Only 2 kicks exceed 0.05. |
| Start pitch | — | — | — | **Not established** | Values in the first 1–4 ms are mixed with click energy and run into the 700 Hz filter limit. Do not use. |

What follows for #3 (presets/variants). These are hypotheses until the user has listened:

- A default around **55 Hz tail**, a clean sine tail and **~80 % sub energy** matches this selection better than the current defaults.
- **Click level/tone is the most natural variant axis.** It varies most within one person's taste, while tail pitch and sub weight stay comparatively stable.
- Body drive should be a deliberate choice, not a default, because the user's picks mostly have clean tails.

## 3. Analysis pitfalls (relevant to `analysis.py`, PR #8)

Each of these produced wrong numbers during this work before it was fixed:

1. **A Hann window over a whole one-shot mutes its onset.** The sub share read 100 % instead of 71 % on a synthetic kick. Use a rectangular window for whole-file band shares, or window only steady segments.
2. **Measure from the onset, not the RMS maximum.** The RMS peak can lag the onset by about 10 ms, and by then most of the pitch drop is over (synthetic: 137 Hz measured vs ~219 Hz true).
3. **A short FFT window quantises pitch.** A 40 ms window gives 25 Hz bins, which produced a fake 50 Hz floor. Use instantaneous frequency or zero crossings for the tail fundamental, and check one method against the other.
4. **Decay on a 1 ms mean-abs envelope catches click ripple.** −20 dB times came out at a few ms. Use an RMS envelope of ≥ 5 ms.
5. **"Never reached" is not 0.** Return `None` when a threshold is not crossed inside the file.
6. **Sample folders contain loops.** Count hits before averaging.
7. **Never derive labels from file or archive names.** An earlier pass of this analysis called the set "future rave/trance" because of the ZIP name. That was wrong: the ZIP was simply named after one file. Pack prefixes in filenames are not genre labels either.

The first pass of this analysis (not in the repo) reported a pitch-sweep ratio of ~2.8× and a −40 dB decay of ~190 ms. Both were wrong because of pitfalls 1–4. **Retracted.**

## Limits

- The data shows what the user selects, not their own productions. There are no genre labels per file.
- 37 samples from commercial packs. 44.1 kHz except 3 files at 48 kHz. Mono sum of stereo files.
- Numbers describe signals. They do not say whether a kick sounds good; only the user's listening test decides that (Phase 01 acceptance).

## Open questions for the user

- Do the medians above match the kicks you would actually use in your own tracks?
- Per-file genre labels would allow per-genre fingerprints. Without them, the set stays one group.
