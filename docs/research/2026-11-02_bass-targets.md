# Bass (sub / rolling techno bass one-shot): measurable quantities, starter ranges (hypotheses), analysis gaps, contract-field proposal and listening-test skeleton

_Date: 2026-11-02 · Role: sound-designer · Refs #276 (B0: bass targets note) · Status: **pre-work, plan and hypotheses, not a result.** Docs only. No bass engine exists; nothing here was rendered with an engine or heard. The only measurements are two small probes on **synthetic test signals I built in a scratchpad** (section 3, P1-P3; commands in section 8); they say how the existing helpers behave on idealised bass-like signals, not how any bass sounds. Every "tighter", "rounder", "more weight" is for the user's ear. All parameter values are proposals; none is a default or a taste claim. `contracts/` is not touched._

Read before writing: `CLAUDE.md`; [kick-gen2 learnings](2026-10-28_kick-gen2-learnings.md) (section 2 taste range, section 4 pitfalls, section 5 rules); the researcher note [snare, rim and sub-bass design](2026-11-02_snare-rim-and-sub-bass-design.md) (section 3, facts B1-B4, its `bass-params` v0.1 proposal is the base and is **not repeated in full**); [next-category proposal](2026-11-02_next-category-proposal.md) (bass rank 4, loudness row); [kick genre words and note names](2026-11-02_kick-genre-words-and-note-names.md) (section 4); [snare targets](2026-11-02_snare-targets.md) and [rim targets](2026-11-02_rim-targets.md) (structure; rim is PR #274, open at the time of writing, read with `git show origin/phase-06/rim-targets:...`); `src/audio_engine/analysis.py`, `dsp.py` and `contracts/sample-metadata.schema.json` on `origin/main` e986751.

Labels: *sourced* = a page I opened today says it; *measured* = I ran it today on a synthetic signal (section 8); *derived* = my inference from sourced facts or from existing notes; *unverified* = could not be checked.

## Short version

1. A bass one-shot is **pitched and held** (a gate), so the kick's measurements transfer only in part. Its measurable core is **eleven quantities** (section 1): pitch accuracy against the note, harmonic ratios, sub share, brightness/low-pass corner, filter movement, amplitude attack, sustain stability, release, start/end click, DC and crest, plus the user's kick/bass relation as a mix question outside the one-shot.
2. **No taste range exists.** The researcher note found no published numeric target for a techno/trance bass; the user supplied no reference basses. The only sourced numeric points are from **one tutorial** (B1: high-pass about 65 Hz, low-pass about 350 Hz, sub low-pass about 80 Hz, note G2 = 98 Hz). B2 (Operator rumble) gives **no numbers at all**. Everything else in section 2 is "none" or a labelled hypothesis.
3. **The "C2 octave range" and "G2" in B1 do not contradict each other.** I re-opened the page today: it says "within the C2 octave range" for the MIDI line, "repeating G notes in the G2 range" and "G2's frequency is exactly 98". In scientific pitch notation the octave C2..B2 is 65.4-123.5 Hz and contains G2 = 98.0 Hz (MIDI note 43). So B1 means MIDI note 43 (derived from the stated 98 Hz; the page names no DAW octave convention, and Live's own label for MIDI 60 is unverified, see the genre-words note). **A real conflict does exist elsewhere:** the researcher's proposed key window for bass (notes 31-42, 49.0-92.5 Hz) **excludes** B1's own note 43 (98.0 Hz), and the proposed default note 31 (49.0 Hz) sits inside the user's measured kick tail range of 45-60 Hz (section 5, decisions 1-2).
4. **Existing analysis helpers mostly mis-measure a gated bass** (section 3, measured on synthetic notes): `analyse()` reads its pitch from a window that falls mostly in the release (204-304 ms of a 310 ms file); the 1 ms RMS envelope behind `rise_time_ms`/`t60_ms` ripples by 9-34 dB on sustained bass notes; `rise_time_ms` read 9-29 ms on a saw note with a true 3 ms attack. The zero-crossing pitch method itself was accurate (0.0 to -0.2 cents) on the synthetic notes tested. Bass needs a **stationary-window** pitch/harmonic reading and a **period-aware envelope** (section 4).
5. A **`bass-params` v0.1 field review** is in section 5: the researcher's field list kept as base, with a source status per field, a corrected note-range question, and ten decisions for the lead (PROPOSAL ONLY).
6. A **listening-test skeleton** (7 items, 20 blind files, 13 unique renders, about 15 minutes, about 13 without W6) is in section 6. It cannot run before a bass voice exists.

## 1. Which measurable quantities define the bass

All rows are **derived** from the researcher note section 3 (B1-B4, the kick comparison table) unless a source is named; none is yet measured on any engine render. "Stationary window" = a window inside the held part of the gate, away from the attack and the release (for example 40-80 % of `gate_ms`), at least two periods long at the lowest note.

| # | Quantity | Why it defines the bass (derived) | Window / method (proposal) | Moves with (proposal field) |
| --- | --- | --- | --- | --- |
| Q1 | **Pitch accuracy** (cents against the note) | The note is the main control (researcher 3.2); `fundamental_hz` is the engine's own claim and can be asserted | stationary window; zero crossings **and** a long-window spectral peak or autocorrelation, compare the two (kick pitfall 3); reference `440 * 2^((note-69)/12) * 2^(cents/1200)` | `note`, `cents` |
| Q2 | **Harmonic ratios** (2nd, 3rd partial over the fundamental, dB) | Separates sine sub from saw/square and from driven bass | stationary window, rectangular or flat-top window, peaks at `k*f0` | `osc_mix`, `drive`, `lp_hz` |
| Q3 | **Sub share** (energy below 100 Hz over total) | Kick learnings F1: sub/tail zone is the weight of a low element; the same quantity exists for kicks (80-90 % sub energy in the user's picks, kick learnings section 2) | whole-file or stationary window, rectangular, split at 100 Hz (and report the split) | `osc_mix`, `sub_octave_level`, `lp_hz`, `hp_hz` |
| Q4 | **Brightness / low-pass corner** | B1 states a low-pass near 350 Hz as the character-defining step | centroid and energy share above 350 Hz / 1 kHz in the stationary window; the -6 dB corner of the harmonic line envelope (envelope of the peaks `k*f0` versus `k`) | `lp_hz`, `lp_q`, `osc_mix` |
| Q5 | **Filter movement** | B1 "fast filter envelope"; the artifact's exponential cutoff envelope (B3) | centroid in the first 30 ms over centroid in the stationary window (hat note `early_late_centroid_ratio` idea; not the same windows) | `lp_env_amount`, `lp_env_decay_ms` |
| Q6 | **Amplitude attack** | B1 "fast attack, first notes not at full volume"; B2 "slow attack to get rid of the clicks": the two tutorials disagree in direction, so this is a taste axis | onset to 90 % of the stationary level on a peak or Hilbert envelope, **not** a 1 ms RMS envelope (P2) | `amp_attack_ms` |
| Q7 | **Sustain stability** | The bass is held; level drift inside the gate is a design property (derived) | max-min of a period-long RMS envelope in 40-80 % of the gate, dB | `lp_env_*`, `osc_mix` |
| Q8 | **Release** | Gate then release; the tail must not click | level 5 ms after the gate end versus level at the gate end (`gate_end_db`), time from gate end to -40 dB | `gate_ms`, `release_ms` |
| Q9 | **Start / end click** | B2 states the click as the reason for the slow attack | first and last sample value, largest sample-to-sample step in the first and last 5 ms against the stationary peak | `amp_attack_ms`, `release_ms` |
| Q10 | **DC and crest** | Sub-bass is low enough for DC removal to matter (P7) | `dc_offset`, `peak_dbfs`, crest factor | `hp_hz`, `drive` |
| Q11 | **Length** | `length_ms` = gate + release (researcher 3.2) | file length; `length_ms` against the 16th of the pattern | `gate_ms`, `release_ms` |

Not a bass quantity in v0.1 (derived): the bass line (notes over time, rhythm, kick gap, sidechain). B1 and B2 describe these (a note on almost every 16th, the first 16th of each beat empty, no notes where the kick falls, sidechain to the kick), and they are a pattern and mix problem; a one-shot cannot carry them. Stereo, reese detune, wobble, FM (B2 "rumble" is a later model per the researcher note).

## 2. Starter ranges (HYPOTHESES) and where each number comes from

Rule for this table: a **sourced point** is a value a source gives; the **proposal range** is the researcher note's section 3.3 range, which is wide on purpose and **not** a measured taste range. "none" means no source gives any number. Source ids are the researcher note's (B1-B4); I re-opened B1 and B2 today.

| Quantity / field | Sourced points | Source and confidence | Proposal range (researcher 3.3) | Starter value (hypothesis) |
| --- | --- | --- | --- | --- |
| `note` (MIDI) | G2 = 98.0 Hz = note 43 ("G2's frequency is exactly 98"); B2: "mainly one note, F", **no octave**; the user's kick tails 45-60 Hz (median 53 Hz) are a different quantity | B1 medium (one tutorial, opinion); B2 no number; kick range measured on 77 files (kick learnings section 2) | 24 .. 55 (32.7 .. 196 Hz) | 43 (B1) or 31 (researcher, 49.0 Hz): **open decision 1**; no basis to choose by taste |
| `cents` | none | - | -50 .. +50 | 0 |
| `osc_mix` (saw, square, sine) | B1: "saw or square waves ... work best"; sub layer is a sampled kick sub (not a synthesised sine) in B1 | B1 medium | each 0 .. 1 | saw 0.7, sine 0.7, square 0 (researcher; **levels have no source**) |
| `sub_octave_level` | none (B1 sub layer is a separate sample, low-passed near 80 Hz, 12 dB/oct; page wording: "Q of 12db/octave", a slope unit, intended setting unclear) | B1 medium-low | 0 .. 1 | 0 |
| `hp_hz` | about 65 Hz (bassline high-pass, B1) | B1 medium | 20 .. 120 | 40 (researcher; note: B1's 65 Hz is above the 49 Hz fundamental of note 31 and below the 98 Hz of note 43, see cross-field rule in section 5) |
| `lp_hz` | about 350 Hz (bassline low-pass, B1); sub layer about 80 Hz (B1); B2 gives a 24 dB/oct slope and **no cutoff** | B1 medium; B2 none | 60 .. 4000 | 350 (B1) |
| `lp_q` | B2: "a touch of resonance", no value | B2 qualitative only | 0.5 .. 6 | 0.9 (researcher; no source for the number) |
| `lp_env_amount`, `lp_env_decay_ms` | B1: "fast filter envelope", no value; B3: the artifact's exponential cutoff envelope exists (values in the synthesis note, not re-read here) | B1 qualitative; B3 high for existence | 0 .. 4 octaves / 5 .. 800 ms | 1.5 / 120 (researcher; no source for the numbers) |
| `amp_attack_ms` | B1: "fast attack", "first notes not at full volume"; B2: "slow attack"; **no value in either** | qualitative; the two disagree in direction | 0.5 .. 30 | 3 (researcher; no source for the number) |
| `gate_ms` | derived from B1 rhythm: a note on almost every 16th; one 16th = 60000 / (4 x BPM) ms = 125.0 ms at 120 BPM, 110.3 ms at 136, 103.4 at 145, 100.0 at 150 | arithmetic on B1's rhythm statement (derived) | 50 .. 1500 | 250 (researcher; for the B1 pattern a gate under one 16th is needed, hypothesis) |
| `release_ms` | none (B1: "a slower release time" for the sidechain envelope, no value; that is a mix effect, not a one-shot release) | - | 5 .. 400 | 60 (researcher; no source) |
| `drive` | B2: overdrive, no values; B1: sub layer overdriven at about 35 % dry/wet in a **named vendor plug-in** (not transferable to our `drive` scale) | B1/B2 qualitative | 0 .. 1 | 0.2 (researcher; no source) |
| `detune_cents` | none (reese is a later model) | - | 0 .. 25 | 0 |
| Target values for **sub share, harmonic ratios, centroid, crest** of a techno/trance bass | **none** | the researcher note found no published numeric target; the kick range (sub energy 80-90 %, kick learnings) does not transfer to a bass with a saw component | **no range proposed**; analysis reports, it does not pass or fail on taste values until references exist | - |
| Loudness of the bass against the kick | -3 LU in the artifact's loop table (kick loop = 0), no published standard | next-category proposal section 1, taken second-hand from the artifact; a loop-level number, not a one-shot level | - | no one-shot level target |

Things the research did **not** give, listed so nobody invents them: any genre-specific value of the saw/sine balance, filter-envelope depth or time, the attack/release times, drive amounts, the pitch of a rumble note (B2 gives F without octave), real-bass spectra, any measurement of a real bass sample. B1 and B2 are both Attack Magazine tutorials: two voices from one publisher, opinion not measurement.

Single-field effect directions below are **hypotheses by construction** (the field is built to move the quantity); they are listed so the engine tests can check them, not as findings:

| Hypothesis | Field moved | Quantity expected to move | Measurement that would reject it |
| --- | --- | --- | --- |
| V1 | `note` (all 24..55) | Q1 within a tolerance to be set from a measurement on the engine | error over the full range (random notes, seeded) above the tolerance; the synthetic probe gave 0.0 to -0.2 cents (section 3), the engine is not measured |
| V2 | `lp_hz` up | Q4 up (centroid up, share above 350 Hz up), Q3 down | centroid does not rise monotonically; a saturated band (centroid bounded by the harmonic count at high notes, Nyquist) |
| V3 | `lp_env_amount` up | Q5 up | the early/late ratio does not follow, or follows only for some notes (the first 30 ms holds fewer than 2 periods at 32.7 Hz, P4) |
| V4 | sine share up (`osc_mix`) | Q2 down, Q3 up | harmonic ratio not monotone; Q1 jumps (octave error, P3) |
| V5 | `amp_attack_ms` up | Q6 up | Q6 does not follow on the Hilbert or peak envelope, or it follows only above one period (P2) |
| V6 | `gate_ms` up | Q11 up, sustain window longer | `length_ms` differs from gate + release by more than a fade |
| V7 | `release_ms` up | Q8 time to -40 dB up | time does not follow, or a click appears at the end (Q9) |
| V8 | `hp_hz` up (below the fundamental) | energy below `hp_hz` down | energy at the fundamental drops by more than a stated amount (cross-field rule, P5) |
| V9 | `drive` up | Q2 up (harmonics), crest down | harmonics do not rise, or aliasing above a limit measured against a 4x-rate render of the same note (kick rule, section 5 of the learnings) |
| V10 | seed changes | at v0.1 **no oscillator or filter uses randomness** (derived), so a seed changes nothing unless variants jitter other fields | any difference between seeds with equal fields; if there is none, `seed` is inert for the bass core (decision 8) |
| V11 | Variants of one preset | stay inside the box of the preset | spread larger than the box (same check as hat H12, clap H10) |

## 3. Analysis pitfalls for a bass

From the kick learnings (all apply; section numbers refer to that note): Hann over a whole one-shot mutes the onset (1); measure from the onset (2); a short FFT window quantises pitch (3); decay on a 1 ms envelope catches ripple (4); "never reached" is `None` (5); reference folders contain loops, count hits and measure only the first (6, 7); a "no duplicates" claim needs a positive control (8); no labels from file names (9).

Bass-specific. P1-P3 are **measured** on synthetic notes (probe scripts in the scratchpad, not in the repo; section 8): additive band-limited saw and sine at 48 kHz, 3 ms linear attack, gate 250 ms, linear release 60 ms, notes 24, 31, 43, 55 (32.7, 49.0, 98.0, 196.0 Hz). They are idealised and say nothing about what the engine will produce. P4-P9 are **derived** and are to be confirmed on real renders.

- **P1 (measured) The kick window lands in the release of a gated bass.** `tail_window` ends where the envelope first falls 40 dB below its peak (or at the file end) and takes the 100 ms before that. For the synthetic notes (gate 250 ms + release 60 ms = 310 ms) it chose **204-304 ms**, i.e. 46 ms of sustain and 54 ms of release, and the release region was most of it. `analyse()["fundamental_hz"]` was still right on these signals because the pitch was constant, but any pitch or level change in the release (a filter closing, a glide) would be read into `fundamental_hz`. The kick docstring defines `fundamental_hz` as the tail; for a bass the sidecar value should come from the stationary window (researcher 3.4 says so; this confirms why).
- **P2 (measured) A 1 ms RMS envelope ripples on bass notes.** `rms_envelope` uses `ENV_RMS_MS = 1.0`. Max/min of that envelope inside the sustain, in dB: sine 24.5 / 21.0 / 15.0 / 8.8 for 32.7 / 49 / 98 / 196 Hz; saw 34.3 / 30.7 / 24.5 / 18.0 dB. A 5 ms window leaves 10.4 / 6.7 / 0.2 / 0.2 dB (sine) and 19.8 / 15.9 / 8.7 / 0.3 dB (saw); a window of one period gave 0.0-0.07 dB everywhere. Consequence: `rise_time_ms` on the whole file read 2.2-4.3 ms on the sine notes and **9.3 / 19.0 / 28.6 ms on the saw notes at 98 / 49 / 32.7 Hz** while the true ramp was 3 ms, and `t60_ms` was `None` (no 60 dB fall inside the gate+release, as expected). `rise_time_ms` and `t60_ms` from `analyse_nonpitched` are therefore not usable as Q6 / Q8 on bass. A period-long window has its own limit: at 32.7 Hz one period is 30.6 ms, longer than the whole proposed attack range (0.5 .. 30 ms), so the attack must be read on a Hilbert or rectified peak envelope, not on a period RMS (hypothesis, untested).
- **P3 (measured) Zero crossings are accurate on partial-poor signals and ambiguous with a sub-octave.** `zero_crossing_frequency` on the stationary window (100-200 ms) gave -0.2 cents at 32.7 Hz and 0.0 at the other three notes, for sine, saw, and saw plus a sine at the same pitch (the latter at 0.7/0.7). With a sine **one octave below** added at four saw/sub level pairs (0.7/0.7, 0.5/1.0, 1.0/0.3, 0.3/1.0), at notes 31 and 43, the result was the saw's pitch `f` in all eight cases, not `f/2`; the zero-crossing rate of a mixture depends on which component crosses (waveform and phase), so this is **not** a general result. A `sub_octave_level` above zero makes "what is the fundamental" a definition question (the engine's note `f` or the lowest strong peak `f/2`): decision 6. Whether strongly driven or resonant bass gives extra crossings per period is untested (hypothesis: yes).
- **P4 Frequency resolution at the low end (derived arithmetic).** One period is 30.6 ms at 32.7 Hz and 5.1 ms at 196 Hz. A spectral peak from a window of T seconds has bins of 1/T Hz: 4 Hz for 250 ms, so cents accuracy at 32.7 Hz needs interpolation or a long window; a 40 ms window gives 25 Hz bins (kick pitfall 3). The first 30 ms of a low note holds one period, so early/late brightness (Q5) is unreliable below about 60 Hz.
- **P5 High-pass against the fundamental (derived).** B1's high-pass at about 65 Hz is above the fundamental of notes 24-36 (32.7-65.4 Hz). With `hp_hz` > `note` frequency the fundamental is attenuated and a spectral "strongest peak" pitch may jump to the second harmonic. A cross-field rule is proposed in section 5; the zero-crossing method may be less affected than the peak method, untested.
- **P6 Kick overlap (derived).** The user's kick tails are 45-60 Hz (median 53 Hz, 77 files). A bass note in notes 31-34 overlaps them in the fundamental. Measure the bass **alone**; a combined render cannot give Q1, Q3 or phase (kick learnings F3: phase between layers). Whether the bass should avoid or reinforce the kick pitch is a mix question for the user.
- **P7 DC blocker and short fades near the fundamental (derived from the analysis docstring).** The kick engine's DC blocker is at 10 Hz (tau 15.9 ms per `analysis.py`). Notes at 32.7 Hz are 3.3 times that corner; whether the bass engine reuses the blocker, and how it changes the first periods, is not established. Fades must be sized to the period: a 5 ms release is less than a quarter period at 49 Hz (20.4 ms) and may click (Q9).
- **P8 Aliasing with a filter envelope (derived).** A band-limited additive saw is exact for a fixed pitch; a time-varying biquad can be unstable at high Q and low cutoff (researcher 3.4 pitfall 2); and `drive` adds harmonics. Test against a 4x-rate render of the same note, as the kick learnings require, and prove the test can fail.
- **P9 Small speakers (derived, unverified).** A sine below about 50 Hz may not be reproduced on small speakers; a note-31 sub could be inaudible there. The harmonic ratios (Q2) and `drive` matter for translation. The user's monitoring is unknown.
- **P10 Reference basses (derived).** Samples are often a full loop or a layered kick+bass; count hits and exclude combined files from pitch statistics only, with the same positive-control rule as kicks (learnings 6-8).

## 4. Which analysis helpers measure what, and what is missing

State of the code: `origin/main` e986751 (the hat helpers of #251 are on main: `welch_flatness`, `lf_leak_db`, `hf_share`, `peak_count`, `t60_line_fit_ms`, `early_late_centroid_ratio`). Signatures read from the file; behaviour on bass measured only where stated in section 3.

| Quantity | Existing helper | Status on bass | Gap |
| --- | --- | --- | --- |
| Q1 pitch | `zero_crossing_frequency(segment, sr)` (main) | accurate on the synthetic partial-poor notes (P3); applicable to any segment I pass | the **window** is wrong: `tail_window` selects the release region (P1). A `stationary_window(audio, sr, gate_ms)` and a second, independent method (long-window peak with interpolation, or autocorrelation) do not exist |
| Q1 `fundamental_hz` in the sidecar | `analyse()` (main) | field exists, description says "Pitched samples (kick)" | for the bass the value must come from the stationary window; a description change, no new field |
| Q2 harmonic ratios | none | missing | peak levels at `k*f0` in the stationary window (rectangular or flat-top), ratio to fundamental |
| Q3 sub share | `_power_spectrum` is private; `hf_share(audio, sr, split_hz)` (main) is the high side | the low side is `1 - hf_share(.., 100)` only if the split semantics are "above" and the whole file is used (derived; not run) | a `lf_share` or `band_share(audio, sr, lo, hi)`; whole-file versus stationary window both needed |
| Q4 brightness | `analyse_nonpitched` centroid (whole file, main) | whole-file centroid mixes attack, sustain and release; the saw note centroids read 136.5 / 195.6 / 355.4 / 632.6 Hz for 32.7 / 49 / 98 / 196 Hz fundamentals (measured, synthetic, `analyse_nonpitched`), i.e. the centroid is tied to the harmonic count, not only to a cutoff | stationary-window centroid, share above 350 Hz and 1 kHz, harmonic-envelope corner finder |
| Q5 filter movement | `early_late_centroid_ratio` (main) | windows are hat-oriented (first 20 ms over 60-100 % of a `t60_line_fit_ms`); `t60_line_fit_ms` returns `None` without a 40 dB fall (derived from its code: it needs the -40 dB crossing before the last 6 ms; the synthetic notes had none, `t60_ms` was `None` by the same criterion, P2) | needs gate-aware windows: first 30 ms over 40-80 % of the gate |
| Q6 attack | `rise_time_ms` (main, 1 ms RMS) | not usable (P2: 9-29 ms for a 3 ms ramp on the saw) | Hilbert or peak-hold envelope; onset-to-90 % of the stationary level |
| Q7 sustain stability | `rms_envelope` building block (main) | 1 ms window ripples (P2) | a period-long envelope with window = max(5 ms, 1 period) |
| Q8 release | `rms_envelope`, `t60_ms` building blocks | `t60_ms` is a peak-referenced decay; the release starts at the gate end | `gate_end_db`, time to -40 dB measured from the gate end (the engine knows `gate_ms`) |
| Q9 start/end click | none | missing | first/last sample, largest step in 5 ms against the stationary peak |
| Q10 DC, crest | `dc_offset`, `peak_dbfs` (main) | exist; crest does not | `crest_db` (peak over RMS) |
| Q11 length | `length_ms` (main) | exists | none |

Policy (derived from the hat and snare precedent): new bass measurements start as **design and test helpers next to `analyse_nonpitched`, not as sidecar fields**. The sidecar `features` object has `additionalProperties: false` and 10 keys; adding `harmonic_ratio_2_3`, `sub_share_100hz` etc. is a `contract-change` (as for the snare, researcher step S0) and should wait for the user's first listening result to show which of them he steers by. A bass sidecar can already carry `fundamental_hz` (kick use, same key) and, because `key` (string or null) exists at the top level of `sample-metadata`, possibly the note name there (decision 4; not checked how the kick uses it).

## 5. Proposed contract fields for a future `bass-params` (PROPOSAL ONLY, `contracts/` untouched)

Base: the researcher note section 3.3 (fields `note`, `cents`, `osc_mix`, `detune_cents`, `sub_octave_level`, `gate_ms`, `release_ms`, `amp_attack_ms`, `lp_hz`, `lp_q`, `lp_env_amount`, `lp_env_decay_ms`, `hp_hz`, `drive`, `length_ms`/`length_beats`, shared export fields). **I do not copy it.** The review of that list against sources:

| Field | Source status (section 2) | Reviewer remark |
| --- | --- | --- |
| `note`, `cents` | B1 note 43 sourced; range hypothesis | range 24 .. 55 covers B1 (43) and the kick region (27-38) |
| `osc_mix` | waveform names sourced (B1), levels none | three levels are three degrees of freedom; Q2 and Q3 are the measurements that separate them |
| `detune_cents`, `sub_octave_level` | none | `detune_cents` is a reese ingredient the researcher defers; with 0 default and no source it is a candidate to drop from v0.1 (decision 7) |
| `gate_ms`, `release_ms`, `length_*` | derived from B1 rhythm | `length_ms` should be derived (gate + release), not a free field; contract text must say so |
| `amp_attack_ms` | B1 and B2 disagree in direction | keep: it is the click axis (Q6, Q9) |
| `lp_hz`, `lp_q`, `lp_env_*` | B1 350 Hz; others qualitative | cutoff semantics (decision 5) |
| `hp_hz` | B1 about 65 Hz | cross-field rule below |
| `drive` | B2 qualitative | as kick/clap |

**Cross-field and global rules to state in the contract (derived):**

- `hp_hz` must stay below the fundamental of `note`: `hp_hz` at most 0.8 times `note` Hz as a starting rule (hypothesis; chosen to leave the fundamental less than a few dB down for a 2nd-order filter, **not measured**); otherwise reject. The researcher default `hp_hz` 40 breaks this rule for notes below about 50 Hz (note 24 gives a limit of 32.7 x 0.8 = 26.2 Hz, note 31 gives 39.2 Hz; arithmetic). So either `hp_hz` is clamped by rule or the range of `hp_hz` and `note` is coupled; this is a real contract question (decision 3).
- `lp_hz` and the peak of the cutoff envelope (`lp_hz` x 2^`lp_env_amount`) below `0.45 x sample_rate`; reject, do not clamp.
- `lp_hz` at least 1.2 x `hp_hz` (as for hats/snare, engine rule).
- Fixed start phase of every oscillator and a defined DC treatment (researcher 3.2, kick learnings F3), part of D-005 byte-identity.
- The note-to-Hz formula in the contract text: `440 * 2^((note-69)/12) * 2^(cents/1200)`; scientific names printed together with the Hz in every response (genre-words note).
- Per-voice gate: file length equals gate plus release within one sample; first and last sample 0.

**Decisions for the lead (not mine to take):**

1. **Default note and starter set.** B1 (sourced, but one tutorial) points at note 43 (98 Hz); the researcher default is note 31 (49.0 Hz, inside the user's 45-60 Hz kick tails). No basis exists to choose by taste; both are hypotheses. A listening item (W1) can decide.
2. **Key window.** The researcher proposes that `note:Am` / `key:8A` resolves into notes 31-42. B1's own G2 (43) is outside that window. Options: widen to 31-43 or 31-45, or take two windows (sub and mid). Also open: whether a key maps to the tonic only (as the kick resolver does) and how B2's "one note, F" is mapped (no octave given).
3. **`hp_hz` against `note`.** The coupling rule above does not hold for the researcher's default range; decide between a derived upper bound, an auto-clamp (contradicts "reject, do not clamp") or narrowing the `hp_hz` range to 20 .. 30 for low notes.
4. **Where the note name lives.** Echo in `key` of the sidecar, in `parameters` only, or both; and whether the kick's `note:`/`key:` resolver is reused as one shared function (researcher B3 step). Not researched how `key` is used for the kick.
5. **Cutoff semantics.** Is `lp_hz` the cutoff at the start of the envelope, the sustained cutoff, or the peak? Measurement is different in each case (Q4 versus Q5). Same style of question as `body_level` in the snare note.
6. **Which pitch is the "fundamental" when `sub_octave_level` > 0** (the note `f` or `f/2`), P3.
7. **`detune_cents` and a `model` field.** Keep `detune_cents` out of v0.1 (reese is a later model), and decide whether the sine-FM rumble (B2) and the saw rolling bass are one voice with presets or two `model` values. B2 gives no numbers, so a rumble model has nothing to be tuned from yet.
8. **`seed` / `variants`.** The bass core has no random source (V10, derived). Either `seed` stays for sidecar uniformity and variants jitter other fields inside preset boxes (as for the kick, to be confirmed by the audio-engineer), or the field is dropped. The "every field moves a measurable value" rule applies to `seed`.
9. **Category enum, sidecar features and tool budget.** `bass` into `sample-metadata` `category` (now `kick`, `clap`, `hat`) is a `contract-change`; new bass features need `additionalProperties` entries; `fundamental_hz` description says "Pitched samples (kick)". The tool budget (24/24 optional parameters, INTERFACES line 85; the lead decided on a generic `generate_sample` tool with Option B, per `CURRENT_STATE`) is the lead's.
10. **One-shot versus loop.** The researcher assumes one-shot; B1 and B2 describe lines (16th rhythm, kick gaps). If the user wants a rendered pattern, the pattern parameters, swing and loop-seam length are a different contract. The note-length question (gate under one 16th) follows from it.

## 6. Listening-test skeleton (for a later bass test; depends on a bass voice and the earlier test results)

Same method as the snare and rim tests: identical control pair, blind names, A/B mixed by a fixed seed, German answer sheet, key file `Schluessel.md` opened after the test, "kein Unterschied" always allowed. Rendered by the audio-engineer, decoded by the lead. **This is a skeleton**: the preset values are the section 2 starter values (hypotheses) and must be replaced by engine-measured numbers (V1-V11) before the test.

**Common setup (my choices, not the user's):** 4 bars at 136 BPM (as in the other tests), mono 48 kHz / 24-bit, `dense` kick on every beat, bass note on the 2nd, 3rd and 4th 16th of every beat and the 1st 16th left empty (the B1 pattern; the 16th is 110.3 ms at 136 BPM), each hit cut at one 16th with a 3 ms cosine fade, peak at most -0.3 dBFS, warp off, no master effects, `seed` 1, no sidechain (the sidechain of B1 and B2 is a mix step outside the one-shot and is left out so that the item answers one question at a time). Level match within each item by RMS over the stationary part of the held note (hypothesis: that window follows the weight of the bass and not the attack; the lead checks and records the gains in the key). Base render **D** = starter values: `note` 43, `osc_mix` saw 0.7 + sine 0.7, `hp_hz` 40, `lp_hz` 350, `lp_env_amount` 1.5, `lp_env_decay_ms` 120, `amp_attack_ms` 3, `gate_ms` 80, `release_ms` 20 (so that gate + release is under the 16th), `drive` 0.2. The choice `note` 43 over 31 follows the only sourced value (B1), not taste; W1 tests the alternative.

| Item | Files (blind) | Single question answered | Changed vs. D |
| --- | --- | --- | --- |
| **W0** control | A = B, identical bytes (D) | How often a side is picked with no difference | none |
| **W1** note | three files: `note` 31 (49.0 Hz) / 38 (73.4 Hz) / 43 (98.0 Hz = D) | Rank "mein Bass"; is the best zu tief, richtig or zu hoch against the `dense` kick | `note` |
| **W2** brightness | three files: `lp_hz` 150 / 350 (D) / 900 | Which is too dunkel, too hell, right | `lp_hz` |
| **W3** filter motion | three files: `lp_env_amount` 0 / 1.5 (D) / 3 | Which has the movement you want; is more movement "zu unruhig" | `lp_env_amount` |
| **W4** sub against saw | three files: sine only / D / saw only (`osc_mix`) | Which is "mein Bass"; does the sine-only read as a bass at all | `osc_mix` |
| **W5** attack | three files: `amp_attack_ms` 1 / 3 (D) / 12 | Which has the better Anschlag; does the 12 ms one lose punch or gain smoothness | `amp_attack_ms` |
| **W6** drive | three files: `drive` 0 / 0.2 (D) / 0.5 | Which is zu sauber, richtig, zu schmutzig; optional second listen on small speakers (P9) | `drive` |

Blind-named files: W0 2, W1 3, W2 3, W3 3, W4 3, W5 3, W6 3 = **20**. Unique renders: **13** (D, which serves as W0 A and B and once in each of W1-W6, plus 12 others: `note` 31 and 38, `lp_hz` 150 and 900, `lp_env_amount` 0 and 3, sine only, saw only, `amp_attack_ms` 1 and 12, `drive` 0 and 0.5). Copies of D differ in bytes only by the per-item level-match gain; W0 A and B must be byte-identical. Time estimate: the pair about 1 minute, three-file items about 2 minutes each, set-up 2: about 15 minutes; drop W6 to get about 13 minutes. **Order:** W3 -> W0 -> W2 -> W5 -> W4 -> W1 (the likely audible differences first, control in the middle, ranking last); W6 last if kept.

**Frageblock (skeleton, German):**

| # | Frage (eine pro Block) | Antwortmöglichkeiten |
| --- | --- | --- |
| W3 | **Welcher Bass hat die Bewegung, die du willst?** Wenn mehr Bewegung etwas gewinnt: was (ein Wort)? | keine / mittel / viel / kein Unterschied · Wort |
| W0 | **Welcher Bass sitzt besser?** | A / B / kein Unterschied |
| W2 | Drei Dateien. **Welche ist zu dunkel, welche zu hell, welche passt?** | z. B. X dunkel, Y passt, Z hell |
| W5 | Drei Dateien. **Welche hat den besseren Anschlag?** Verliert die langsamste Punch oder gewinnt sie Weichheit (ein Wort)? | Reihenfolge · Wort |
| W4 | Drei Dateien. **Welche ist „mein Bass"? Klingt die nur-Sinus-Datei noch wie ein Bass?** | Reihenfolge · ja / nein |
| W1 | Drei Dateien. **Sortiere von „mein Bass" bis „am wenigsten".** Danach: **Ist der beste zu tief, richtig oder zu hoch?** | Reihenfolge · zu tief / richtig / zu hoch |
| W6 | Drei Dateien. **Welche ist zu sauber, richtig, zu schmutzig?** | z. B. X sauber, Y passt, Z schmutzig |

**How the lead reads the answers (skeleton):**

| Answer | Reading | Next step |
| --- | --- | --- |
| W0 not "kein Unterschied" | The user picks a side without a difference | Weigh all answers against it; repeat the pair reversed |
| W1 best is 31 or 38, not 43 | The default note shifts toward his pick; his kick-tail range (45-60 Hz) may matter | Preset value; informs decisions 1-2 (key window) |
| W1 best at an edge (31 or 43) | The range may be too narrow at that side | Extend inside the contract (24 .. 55) |
| W2 "passt" is not 350 | `lp_hz` default shifts | Preset value; B1's 350 Hz is only a tutorial value |
| W3 more movement preferred, or the word names a property | Filter envelope matters | Keep `lp_env_*` in v0.1; the word names the quantity to measure (Q5) |
| W3 "keine" preferred | The filter envelope may be unnecessary in v0.1 | Lead decides whether `lp_env_*` stays (the time-varying filter block, researcher step B1, is the costly part) |
| W4 "nein" for the sine only | A sub-only voice is not a bass for him | `sub_sine` preset deprioritised; Q2 target on his pick |
| W4 sine-only best | The saw component may be unneeded for his use | Simplifies the first voice (no filter block needed); lead decides |
| W5 slow attack preferred | B2's direction (click-free) matches his taste | Preset value; Q6 and Q9 on his pick |
| W6 "passt" is not 0.2 | `drive` default shifts | Preset value |

## 7. What could not be sourced

- **Any numeric taste range for a techno/trance bass.** No published target and no user references. The 77-kick range does not transfer to a bass with a saw component.
- **Every value except B1's four points** (high-pass about 65 Hz, low-pass about 350 Hz, sub layer low-pass about 80 Hz, G2 = 98 Hz). B2 (the Operator rumble) gives a note (F, **no octave**), a 24 dB/oct slope and qualitative statements only: no FM amount, attack time, cutoff, resonance, or drive. Filter-envelope depth/time, attack/release times, osc levels, drive amounts, and sidechain depth are not given by either page. B1's "Q of 12db/octave" for the sub low-pass is a slope unit; the intended setting is unclear.
- **How a DAW labels the octaves in B1.** The page's 98 Hz makes G2 = scientific G2; the page names no DAW convention (it uses Waves plug-ins and a sampled "Kick Sub Butter" from an Ableton pack). Live's label for MIDI 60 is still unverified (genre-words note). Always print the Hz.
- **The artifact's bass voice constants** (B3): existence confirmed by the researcher note; I did not re-read the synthesis note's numbers for this note.
- **Real-bass spectra, sub share or crest of any commercial bass** (no reference audio supplied).
- **The kick/bass relation** in a mix (sidechain depth, which note avoids the kick) is a pattern and mix question; B1 and B2 describe it qualitatively. B1's kick EQ (-4.5 dB at about 98 Hz) is a mix setting and not a one-shot property.
- **Measurements made:** only the two synthetic-signal probes in section 3 (idealised additive saw/sine, linear ramps). They do not describe an engine, and no listening claim follows from them. All other helper behaviour is read from the code.
- Not covered: bass line/pattern design, MIDI, stereo, reese/FM/wobble models, per-note velocity, the arrangement placement (all arrangement capabilities `unknown`, #140).
- Open for the user (from the researcher note, still the blockers): can you supply 3-5 basses you like (audio only, never names as targets); should the first voice be a one-shot you play yourself; and which key window maps a key to a bass note (55-110 Hz or lower).

## 8. Commands run

```
cd /home/claude/abeltongod && git fetch -q origin && git worktree add -b phase-06/276-bass-targets /home/claude/wtbass origin/main   # base e986751
gh api repos/castorsalzmann-ui/abeltongod/issues/276 --jq .body                                         # issue text
WebFetch https://www.attackmagazine.com/technique/tutorials/warehouse-rolling-techno-bass/             # B1: C2 octave range, G2 = 98 Hz, HP ~65, LP ~350, sub LP ~80, rhythm; no env values
WebFetch https://www.attackmagazine.com/technique/synth-secrets/rumbling-techno-bass-ableton-operator/  # B2: note F (no octave), sine+FM, 24 dB/oct LP; no numeric settings
git show origin/phase-06/rim-targets:docs/research/2026-11-02_rim-targets.md                           # structure (PR #274, open)
# probes (scratchpad scripts, not in the repo), run as:
cd /home/claude/wtbass && PYTHONPATH=src python -I -c "exec(open('<scratchpad>/bassprobe.py').read())"    # P1, P3: analyse(), tail_window, zero_crossing_frequency on synthetic notes
cd /home/claude/wtbass && PYTHONPATH=src python -I -c "exec(open('<scratchpad>/bassprobe2.py').read())"   # P2: RMS-envelope ripple, analyse_nonpitched on synthetic notes
```

Probe signal definition (so the numbers can be reproduced): 48 kHz; sine, or additive band-limited saw `(2/pi) * sum_{k=1}^{floor(0.45*sr/f)} sin(2 pi k f t)/k`, or that saw plus a sine; notes 24 / 31 / 43 / 55 (32.70 / 49.00 / 98.00 / 196.00 Hz); amplitude ramp 0 to 1 over 3 ms, held to 250 ms, linear ramp to 0 over 60 ms (total 310 ms); ripple measured as max/min of a centred moving RMS in 100-200 ms.
