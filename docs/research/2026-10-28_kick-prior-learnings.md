# Research: Prior learnings for the kick engine

_Date: 2026-10-28 · Status: input for Phase 01 (#2, #3). Not a decision, not a spec, not a listening result._

## How to use this note

These are **lessons**, not a parameter table. They come from two sources, and neither one should be copied:

1. **"Bandit Wheel"**, an earlier browser prototype by the user (Web Audio, 18 genre profiles, slot-machine UI). Its value tables are deliberately **not** reproduced here. The goal is a better kick engine, not a port.
2. **77 reference kick files** (two uploads: 41 + 36) that the user picked from various Splice packs. Each file counts **once**; see section 2 for how loops and duplicates were handled. They show the user's **taste in kicks** (what they choose), not how the user builds kicks. The audio is licensed and stays out of the repo. Only aggregate measurements appear below.

Use this note to choose defaults, variant axes and analysis methods. Derive your own values and verify them with tests and the user's ears (Phase 01 acceptance criteria).

See also `2026-10-28_kick-market-analysis.md` (what commercial kick synths do and which of their features are candidates here).

**Standing guidance from the user (2026-10-28): keep everything genre-fluid for now.** No genre-keyed presets, fingerprints, parameter ranges or code paths. Name presets by sound character (e.g. `dark-dry`, `punchy`), not by genre. The reference set stays one group. This is the user's instruction in chat, not yet a recorded decision; a decision entry is proposed in the PR body.

## 1. Lessons from the prototype

| # | Lesson | Consequence for AbeltonGod |
| --- | --- | --- |
| P1 | The prototype hid its cleanest kick (centre of every range, zero random jitter) behind a 1 % / 0.2 % random "Gold/Platinum" draw. That is gamification, not quality. The user explicitly does not want the best results to be gated. | The best-balanced version of a preset is always directly reachable. Variants (`variants: N`) add range, never rarity. |
| P2 | 18 genre profiles with separate narrow ranges, each only reachable through 4 discrete steps, felt "too specific" to the user. | Presets are **starting points in one shared continuous parameter space**, not separate code paths. Blending and leaving a preset's range must stay possible. |
| P3 | Some controls only had names and no audible effect (e.g. drive labels). | Every parameter that gets exposed must change the sound measurably. The test is an analysis value that moves when the parameter changes. |
| P4 | Seeded PRNG (mulberry32) made every render reproducible. | Already required by D-005. Confirmed to be useful in practice for A/B comparison. |
| P5 | Character mostly came from a small set of building blocks: sine body + exponential pitch drop, amp envelope with a short **hold**, a **waveshaper with selectable curve family** (hard clip / tanh / asymmetric tanh / wavefold), band-filtered noise click, optional **separate sub sine**, optional **rumble tail** (noise convolved, low-passed, saturated), optional **two-layer body + top**. | `kick-params` v0.1 covers pitch env, amp env, click, `drive`, `tone`. **Not covered:** hold, curve family, separate sub, rumble, layering. These are candidates for later, not scope for #2/#3. Each needs a `parking-lot` issue and a `contract-change` PR before anyone builds it. |
| P6 | Cause → effect is more useful than genre labels. Faster tempo → shorter decay and brighter transient. Kick carries the bassline → longer, more tonal, more driven. Curve family = harmonic colour (hard clip harsh, tanh round, wavefold metallic), not loudness. Sub amount depends on what else fills the low end. Rumble is its own axis, independent of tempo. | Write preset descriptions and future Claude prompts in these terms ("short because 150 BPM"), not as genre facts. |

## 2. Taste fingerprint from 77 reference kick files

**One vote per kick.** 77 files in two uploads. 13 contained several hits (8 loops of one pack with 8–10 hits, three more loops with 8, 8 and 16 hits, two files with 2 hits). Each of those was cut to its **first hit only**, so a kick that is played 8 times in a loop counts once. Duplicates were checked with an onset-aligned waveform correlation over the first 250 ms (positive control: hit 1 vs hit 2–4 inside the same loop gives 0.999–1.0 in 7 of the 10 loops tested; in the other 3 some hits are different sounds within one pattern and correlate only 0.37–0.94 with hit 1). The highest correlation between two *different* files is 0.886, so no pair counts as the same kick (threshold 0.98) and all 77 stay in. For decay measures, 4 first-hits that ran into the next hit (decay possibly cut off) are excluded; all other measures keep them.

Method: mono sum, peak-normalised, all timing measured **from the onset** (first sample above 10 % of peak). Envelope = 5 ms RMS. Tail pitch = instantaneous frequency (Hilbert phase) of a 700 Hz low-passed signal, median over 60 ms after onset until −30 dB, cross-checked by zero-crossing count.

Accuracy check on synthetic kicks with known values: tail pitch within 4 %, pitch settle time and −40 dB decay within about 10 %. Three of the four note-tagged kicks match their note within 5 % (G# → 51.2 Hz vs 51.9 Hz, A → 54.7 Hz vs 55.0 Hz, an F# in upload 2 → 48.2 Hz vs 46.2 Hz). The fourth, an F# in upload 1, measures 59 Hz (F#1 = 46.2 Hz); cause not established.

| Measure | p25 | median | p75 | Median set 1 / set 2 | Note |
| --- | --- | --- | --- | --- | --- |
| Tail fundamental (Hz) | 47 | 53 | 57 | 56 / **49** | See "The two uploads differ" below. 60 % of all kicks lie between 45 and 60 Hz. The schema default `pitch_end_hz: 48` is inside the interquartile range. |
| Pitch settle, 90 % of drop done (ms) | 15 | 24 | 46 | 34 / **17** | n = 63. For an exponential drop this is ≈ 2.3 × the time constant, so τ ≈ 6–20 ms. Map it onto `pitch_decay_ms` only after #7 defines its meaning. |
| Decay to −40 dB (ms) | 223 | 327 | 424 | 327 / 359 | n = 69. Compare with `amp_decay_ms` only once #7 defines its meaning. |
| Energy share below 100 Hz | 0.75 | 0.81 | 0.89 | 0.81 / 0.86 | Strongly sub-weighted in both uploads; p10 is 0.64. |
| Onset (first 10 ms) energy share above 1 kHz | 0.02 | 0.15 | 0.31 | 0.19 / 0.04 | **Widest relative spread (p10 0.01, p90 0.50).** The set 1 / set 2 gap comes from the 8 loop-first-hits and is not distinguishable without them (see below). |
| Tail harmonics 2–8 vs fundamental | 0.00 | 0.01 | 0.03 | 0.01 / 0.02 | Tails are almost pure sine. 10 of 77 exceed 0.05. |
| Start pitch | — | — | — | — | **Not established.** Values in the first 1–4 ms are mixed with click energy and run into the 700 Hz filter limit. Do not use. |

**The two uploads differ.** Set 1 (41 files) and set 2 (36 files) do not give the same fingerprint:

- **Different beyond chance, also without the 8 loop files:** tail pitch (55.9 vs 49.9 Hz, Mann–Whitney p = 0.001), pitch settle (34 vs 19 ms, p = 0.02), sub share (0.81 vs 0.89, p = 0.0004), crest factor (p = 0.01) and decay (p = 0.002).
- **Not different without the loop files:** onset brightness (p = 0.22). The low click in set 2 comes from the 8 loop first-hits, which also have a high crest factor (median 4.0).
- **Cause not established.** Candidates: different genre mix, different packs, or a change in what the user was looking for between the two uploads. The data cannot tell them apart, and under the genre-fluid guidance this is not pursued for now.

So the "taste" is **a range, not a point**. Tail pitch 45–60 Hz, sub-dominant, clean tails, click amount free.

What follows for #3 (presets/variants). These are hypotheses until the user has listened:

- Do not hard-code one tail pitch. Presets should span **roughly 45–60 Hz** and keep the root note a tunable parameter; a single default near 52 Hz is the least wrong single value.
- **~80–90 % sub energy** and a **clean sine tail** hold in both uploads and are the safest shared base.
- **Click level/tone is the most natural variant axis**: it has the widest relative spread within the selection.
- Body drive should be a deliberate choice, not a default, because the user's picks mostly have clean tails.

## 3. Analysis pitfalls (relevant to `analysis.py`, PR #8)

Each of these produced wrong numbers during this work before it was fixed:

1. **A Hann window over a whole one-shot mutes its onset.** The sub share read 100 % instead of 71 % on a synthetic kick. Use a rectangular window for whole-file band shares, or window only steady segments.
2. **Measure from the onset, not the RMS maximum.** The RMS peak can lag the onset by about 10 ms, and by then most of the pitch drop is over (synthetic: 137 Hz measured vs ~219 Hz true).
3. **A short FFT window quantises pitch.** A 40 ms window gives 25 Hz bins, which produced a fake 50 Hz floor. Use instantaneous frequency or zero crossings for the tail fundamental, and check one method against the other.
4. **Decay on a 1 ms mean-abs envelope catches click ripple.** −20 dB times came out at a few ms. Use an RMS envelope of ≥ 5 ms.
5. **"Never reached" is not 0.** Return `None` when a threshold is not crossed inside the file.
6. **Sample folders contain loops, and a loop repeats one kick many times.** Count hits per file and measure only the first one, otherwise one kick counts as 8 or 16. Check hit 1 vs hit 2 in the same loop as a positive control for any duplicate detector.
7. **A hit cut out of a loop can have its decay cut off by the next hit.** Treat decay and length as censored in that case and leave those files out of the decay statistics only.
8. **A "found no duplicates" result needs a positive control.** The threshold of 0.98 found nothing; it only means something because the same detector returns ≈1.0 for repeated hits of one loop and tops out at 0.886 between different files.
9. **Never derive labels from file or archive names.** An earlier pass of this analysis called the set "future rave/trance" because of the ZIP name. That was wrong: the ZIP was simply named after one file. Pack prefixes in filenames are not genre labels either.

The first pass of this analysis (not in the repo) reported a pitch-sweep ratio of ~2.8× and a −40 dB decay of ~190 ms. Both were wrong because of pitfalls 1–4. **Retracted.** A later 37-file version of this note gave a tail pitch median of 56 Hz and said the schema default of 48 Hz sat at the low edge. With 77 files the median is 53 Hz and 48 Hz is inside the interquartile range; that statement is **retracted**.

## Limits

- The data shows what the user selects, not their own productions. There are no genre labels per file.
- 77 files from commercial packs, two uploads that differ from each other (see section 2). 44.1 kHz except 3 files at 48 kHz. Mono sum of stereo files. 13 files are loops or multi-hit files; only their first hit was measured. 8 of them come from one loop family (A/B, 4 variants each) and make up about 10 % of the set.
- Numbers describe signals. They do not say whether a kick sounds good; only the user's listening test decides that (Phase 01 acceptance).

## Open questions for the user

- Do the medians above match the kicks you would actually use in your own tracks?
- None blocking. The two uploads differ (tail ≈ 56 vs ≈ 49 Hz); if the user ever wants to know why, per-file notes would be needed. Not requested while everything stays genre-fluid.
