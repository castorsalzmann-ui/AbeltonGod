# Snare: measurable quantities, starter ranges (hypotheses), analysis gaps, contract-field proposal and listening-test skeleton

_Date: 2026-11-02 · Role: sound-designer · Refs #151 (next categories after hats) · Status: **pre-work, plan and hypotheses, not a result.** Docs only. Nothing here was rendered, measured or heard; no number comes from an engine, a model run or reference audio. Every "better", "tighter", "more snap" is for the user's ear. All parameter values are proposals; none is a default or a taste claim. No snare engine exists. `contracts/` is not touched._

Read before writing: `CLAUDE.md`; [kick-gen2 learnings](2026-10-28_kick-gen2-learnings.md) (section 4 pitfalls, section 5 rules); the researcher note [snare, rim and sub-bass design](2026-11-02_snare-rim-and-sub-bass-design.md) (merged as #253; its research is **not repeated**, findings are cited as S1-S11); [clap targets and listening plan](2026-11-02_clap-targets-and-listening-plan.md) and [hat targets and listening plan](2026-11-02_hat-targets-and-listening-plan.md) (structure); `src/audio_engine/analysis.py` on `origin/main` 5fdb159; PR #265 (`phase-06/251-hat-analysis`, **open, not merged**, read through the REST API and `git show origin/phase-06/251-hat-analysis:...`).

Labels: *sourced* = a page opened today or the researcher note's cited source says it; *derived* = my inference from sourced facts or from existing notes; *unverified* = could not be checked.

## Short version

1. A techno/trance snare is described by **nine measurable quantities** (section 1): body pitch (and its drop), second-partial ratio, body-to-noise balance, noise band (high-pass, low-pass), body decay, noise decay, noise attack, overall centroid/HF share, and tail length. Seven of them need a **band-split** or **early-window** analysis that does not exist yet.
2. **No taste range exists.** The researcher note found no published numeric target for techno/trance snares, and the user has not supplied reference snares. Section 2 therefore lists only **sourced points** (a handful of single values from hobby pages, a tutorial and a code sample) and the proposal range that spans them. Most fields have **no source at all** and are marked so.
3. **Correction to the researcher note (S1):** I opened the SOS article today. The 180 Hz and 330 Hz values are, in the article's wording, the author's own modular model ("I used a single VCA and contour generator for the 180Hz and 330Hz partials"), **not** figures attributed to the Roland 909. The article gives **no** 808 or 909 frequencies, cutoffs or decay times. Treat 180/330 Hz as one software-recipe data point, not as a machine fact. The ratio 1.83 survives only as that recipe's ratio.
4. Existing analysis can measure the **whole-file** side (centroid, HF share, `t60_ms`, `rise_time_ms`, `peak_dbfs`, `length_ms`); the PR #265 hat helpers add Welch flatness, `hf_share` with a free split, `lf_leak_db`, line-fit `t60`, `early_late_centroid_ratio` once merged. **Missing** for the snare: body peak and ratio, band-limited envelopes and `t60`, body-to-noise balance, an early-window pitch track, noise-onset time (section 4).
5. A **`snare-params` v0.1 field list** is proposed in section 5 (proposal only; the researcher note section 2.2 is the base, with seven decisions for the lead).
6. A **listening-test skeleton** (7 items, 21 blind files, 14 unique renders, about 16 minutes, about 14 without N6) is in section 6. It cannot be run before a snare voice exists and the ranges are re-measured on it.

## 1. Which measurable quantities define the snare

All rows are **derived** from the researcher note's findings S1-S11 unless a source is named; none is yet measured on any audio. "Window" is where the quantity should be read, following the kick learnings (measure from the onset, per zone).

| # | Quantity | Why it defines the snare (derived) | Window / method | Moves with (proposal field) |
| --- | --- | --- | --- | --- |
| Q1 | **Body pitch** (lower partial) | Two short pitched partials are the part of the snare that has a pitch (S1, S4, S10); the user's taste for "tuned" snares is unknown | peak in 100-500 Hz, first 40 ms; instantaneous frequency or zero crossings, **not** a short FFT (kick pitfall 3) | `body_hz`, `pitch_drop`, `pitch_drop_ms` |
| Q2 | **Pitch drop** | Bridged-T bend (S5); artifact uses 1.6x in 30 ms (S11) | frequency at 5 ms versus at 40 ms after onset | `pitch_drop`, `pitch_drop_ms` |
| Q3 | **Second partial ratio** | Upper/lower partial 1.83 / 2.0 / 1.89 across three sources that disagree (researcher 1.2) | two strongest peaks in 100-800 Hz | `mode_ratio` |
| Q4 | **Body-to-noise balance** | S9: "a snare hit is mostly broadband noise"; the balance separates "snappy" from "tonal" | energy 100-500 Hz versus 2-12 kHz, first 80 ms (rectangular window) | `body_level`, `snappy` |
| Q5 | **Noise band** (low edge and high edge) | S10 high-passes at 2000 Hz; S9 "Tone" is a low-pass on the noise | spectrum 0-80 ms: -6 dB corners of the noise region; `hf_share_8k`, centroid | `noise_hp_hz`, `noise_lp_hz`, `tone_peak_*` |
| Q6 | **Body decay** | Short ringing partials (S10: gain to 0 in 0.1 s) | RMS envelope (5 ms) of the 100-500 Hz band, time to -60 dB (or to -20/-40 dB if -60 is not reached) | `body_decay_ms`, `body2_decay_ratio` |
| Q7 | **Noise decay** | S9: noise decays longer than the tone; S10: 0.2 s | RMS envelope (5 ms) of the band above `noise_hp_hz`, same thresholds; overall `t60_ms` is dominated by it (derived) | `noise_decay_ms`, `noise_band_mix` |
| Q8 | **Noise attack** | S9: "Snappy" changes noise attack speed | onset to peak of the high band on a 0.25-1 ms window; **not** `rise_time_ms` of the whole file (P3 below) | `noise_attack_ms`, `snappy` |
| Q9 | **Overall brightness and length** | Existing sidecar features | centroid, `hf_share_8k`, `t60_ms`, `length_ms` | `noise_hp_hz`, `noise_lp_hz`, `noise_decay_ms`, `length_ms` |

Not a snare quantity in v0.1 (derived): stereo, a rattle or wire model, room (the clap has it; a snare tail could be gated instead, see `gate_ms` in section 5).

## 2. Starter ranges (HYPOTHESES) and where each number comes from

Rules for this table: a **sourced point** is a value a source gives; the **proposal range** is the researcher note's section 2.2 range, which is the envelope of those points widened by the researcher's judgement. It is **not** a measured taste range. "none" means no source gives any number. Source ids are the researcher note's.

| Quantity / field | Sourced points | Source and confidence | Proposal range (hypothesis) | Starter value (hypothesis) |
| --- | --- | --- | --- | --- |
| `body_hz` (lower partial) | 180 Hz; 238 Hz; 185 Hz; 150-280 Hz (triangle) | S1 (SOS: **author's own model**, see short version 3), S4 (hobby page, rounded), S10 (code sample), S11 (artifact, existing note); low-medium | 120 .. 400 | 190 |
| `mode_ratio` (upper/lower) | 330/180 = 1.83 (S1 model); 476/238 = 2.0 (S4); 349/185 = 1.89 (S10) | derived ratios from three sources that disagree slightly; low-medium | 1.5 .. 2.4 | 1.85 |
| `pitch_drop` (start/end) | 1.6x (artifact) | S11, existing note only; the bridged-T bend of more than an octave is stated for the **kick** (S5), not the snare | 1.0 .. 2.0 | 1.4 |
| `pitch_drop_ms` | 30 ms (artifact) | S11 | 3 .. 60 | 25 |
| `body_decay_ms` | about 100 ms to zero (S10) ; artifact 70 ms + decay setting | S10, S11; low | 30 .. 300 | 90 |
| `body2_decay_ratio` | none (S1 only says each partial has its **own** envelope and level) | S1: separate VCA and contour per partial in the article's model | 0.3 .. 1.2 | 0.7 |
| `noise_decay_ms` | 200 ms (S10); "longer than the tone" (S9, no number) | S9 medium (qualitative), S10 low-medium | 60 .. 800 | 180 |
| `noise_hp_hz` | 2000 Hz (S10); 1200 Hz + 10 x tone (artifact) | S10, S11; low-medium | 500 .. 6000 | 1800 |
| `noise_lp_hz` | **none** ("Tone" = low-pass on the noise, no cutoff, S9; S1 low-passes the noise, no cutoff) | S1, S9: qualitative only | 3000 .. 16000 | 9000 (no source; placeholder) |
| `noise_attack_ms` | 0.8 ms (artifact) | S11 | 0.1 .. 12 | 0.8 |
| `body_level` / noise share | equal mix (S10); "mostly broadband noise" (S9, qualitative) | S9, S10; low-medium | 0 .. 1 | 0.6 (no source for 0.6; the S10 equal mix would be 0.5) |
| `noise_band_mix`, `snappy`, `tone_peak_hz`, `tone_peak_db`, `gate_ms` | **none** | the 909 two-band noise structure is described by S1 without numbers; the rest is the researcher's derived idea | as in the researcher note 2.2 | as in 2.2 |
| Target values for **centroid, HF share, t60, rise time of a techno/trance snare** | **none** | the researcher note found no published numeric target (2.3); the kick learnings' 77-kick taste range does not transfer | **no range proposed**; the analysis reports, it does not pass or fail on taste values until references exist | - |

Things the research did **not** give, listed so nobody invents them: genre-specific values (all sources are drum-machine or generic software recipes, none is about techno/trance), any t60/decay of a real snare, band-pass Q, the level ratio of the second partial, the noise-band split frequency of the 909 two-band structure, how a gated-reverb tail is measured. The 808 values from S4 and S6 come from one hobby page I did not re-open; the Roland service manual (named by S4 as the primary source) was not opened by anyone.

Single-field effect directions below are **hypotheses by construction** (the field is built to move the quantity); they are listed so the engine tests can check them, not as findings:

| Hypothesis | Field moved | Quantity expected to move | Measurement that would reject it |
| --- | --- | --- | --- |
| T1 | `body_hz` up | Q1 up by the same ratio; centroid up a little | Q1 within 3 % of `body_hz` at 40 ms after the end of the drop; if not, the drop is not finished or the pitch tracker is wrong |
| T2 | `pitch_drop` up at fixed `pitch_drop_ms` | Q2 ratio up; Q1 at 40 ms unchanged | Q2 does not follow, or Q1 shifts |
| T3 | `mode_ratio` up | Q3 up | the two strongest peaks in 100-800 Hz are not the two partials (noise in that band), see P2 |
| T4 | `body_level` up | Q4 up; `hf_share_8k` down | Q4 not monotone over seeds 1-8 |
| T5 | `noise_hp_hz` up | `hf_share_8k` up, centroid up, Q4 up | `hf_share_8k` saturates (hat P6) or falls; compare with the rule from the hat note |
| T6 | `noise_decay_ms` up | Q7 up; `t60_ms` up; Q6 unchanged | overall `t60_ms` does not follow (body dominates the envelope maximum, P4) |
| T7 | `noise_attack_ms` up | Q8 up | Q8 not stable over seeds (P3) |
| T8 | Seed changes | only the noise changes; at `body_level` 1 the render is seed-independent | any change at `body_level` 1 |
| T9 | Variants of one preset | stay inside the seed spread of the preset's box | spread larger than the box; same check as hat H12, clap H10 |

## 3. Analysis pitfalls for a snare

From the kick learnings (all apply unchanged; section numbers refer to that note): Hann over a whole one-shot mutes the onset (1); measure from the onset, not the RMS maximum (2); a short FFT window quantises pitch (3); decay on a 1 ms envelope catches ripple, use at least 5 ms RMS (4); "never reached" is `None` (5); reference folders contain loops, count hits and measure only the first (6, 7); a "no duplicates" claim needs a positive control (8); no labels from file names (9).

Snare-specific, all **derived** (a transfer from hats/claps or from the kick pitfalls; each is to be confirmed by a measurement on real renders, none was measured here):

- **P1 Body and noise overlap in frequency.** The noise is high-passed at 500-6000 Hz in the proposal, so its lower edge can sit inside the 100-500 Hz body band when `noise_hp_hz` is low, and the noise skirt adds energy to Q1 and Q4. A body measurement should be made in a short window right after the onset and checked with `noise_level` zero (a body-only render) as a positive control.
- **P2 Two partials plus a pitch drop smear the spectrum.** A 40 ms FFT window has 25 Hz bins (kick pitfall 3); with a 1.4x drop the lower partial moves by tens of Hz inside the window. Use the zero-crossing or instantaneous-frequency track for Q1 and Q2, and the spectrum only for Q3, with the same check against the other method.
- **P3 `rise_time_ms` on the whole file is not a noise-attack target.** The hat note found `rise_ms` not seed-stable below about 3 ms of attack (hat P4) and the clap note found it unstable for multi-burst noise (clap P1); the snare has one impact, but the noise-attack range starts at 0.1 ms, so the same instability is expected below 3 ms (hypothesis). Measure Q8 in the high band on a 0.25 ms window and report the seed spread.
- **P4 Overall `t60_ms` is a mix of two decays.** The envelope maximum is probably in the body or at the click; the -60 dB crossing is probably set by the noise tail (derived). Read Q6 and Q7 in their bands and report the overall value as a third number. The first-crossing `t60` undershot long decays by up to 9 % in the hat model (hat P3, model, not a measurement of an engine); expect a tolerance of about 10 % until the engine shows otherwise.
- **P5 Reference snares may carry a room or a reverb tail, or be layered with a clap.** Their decay is then censored or two-source (kick pitfall 7); record whether the end of the file is set by a fade, and exclude such files from decay statistics only.
- **P6 Sample-rate band edge.** For 44.1 kHz or lossy references, compare `hf_share_8k` and centroid only inside a stated band (hat note section 6 point 1).
- **P7 Seed independence.** At `body_level` 1 the render must be seed-independent (T8); a test needs a positive control (a render with the noise on must differ between seeds).

## 4. Which analysis helpers measure what, and what is missing

State of the code: `origin/main` 5fdb159 for `analyse`, `analyse_nonpitched`, `spectral_flatness`, `rms_envelope`, `t60_ms`, `rise_time_ms`. PR #265 (hat helpers) is **open and not merged**; its functions are read from the branch and are not on `main`. A snare helper may not rely on them until #265 merges.

| Quantity | Existing helper | Status | Gap |
| --- | --- | --- | --- |
| Q9 centroid, `hf_share_8k`, `t60_ms`, `rise_time_ms`, `peak_dbfs`, `length_ms` | `analyse_nonpitched` (main) | exists; whole file, rectangular window | none for the whole-file values; the cautions P3, P4 apply |
| Q9 HF share at another split (for example 12 kHz) | `hf_share(audio, sr, split_hz)` (PR #265) | on branch only | none once merged |
| Q5 brightness in a band, noise edge | `welch_flatness(audio, sr, f_lo, f_hi)` (PR #265) for flatness in the noise region | on branch only | a **band-edge finder** (-6 dB corners of the noise region) does not exist |
| Q7 / Q9 tail length with less bias | `t60_line_fit_ms` (PR #265): line fit -10..-40 dB on a 4 ms RMS envelope | on branch only; fixed to the **full-band** envelope | no band input (cannot give Q6/Q7); not checked on a snare |
| Q9 early versus late brightness | `early_late_centroid_ratio` (PR #265): first 20 ms over 60-100 % of the line-fit `t60` | on branch only | windows are hat-oriented (20 ms); a snare body (about 100 ms) is inside the "early" window; not checked on a snare |
| Hat-specific: `lf_leak_db`, `peak_count` | PR #265 | on branch only | not needed for the snare; `lf_leak_db` could check a low-frequency leak of the noise high-pass (derived, optional) |
| Q1 / Q2 body pitch and drop | `zero_crossing_frequency(segment, sr)` and `tail_window` in `analyse` (main) | exist, **kick-oriented** (tail of the last 100 ms) | a **pitch track in the first 40-60 ms** (per-cycle zero crossings or instantaneous frequency) does not exist; applicability of `zero_crossing_frequency` to a short segment of a snare was not checked |
| Q3 partial ratio | none | missing | peak picker for the two strongest peaks in 100-800 Hz with a window sized by the sample (needs P2 care) |
| Q4 body-to-noise balance | none | missing | band energies 100-500 Hz versus 2-12 kHz, first 80 ms, rectangular window |
| Q6 / Q7 band `t60` | `rms_envelope`, `t60_ms` operate on a given array (main) | the building blocks exist; the **band split** (a filter before the envelope) and the wrapper do not | `body_t60_ms`, `noise_t60_ms`: band-pass or high-pass first, then `rms_envelope` (5 ms) and `t60_ms`, with the `None` rule |
| Q8 noise attack | `rise_time_ms` takes an envelope array | a 0.25 ms RMS envelope of the high band could be fed to it | not available as a ready function; seed-spread report needed |

Policy (derived from the hat precedent, issue H2): new snare measurements start as **design and test helpers next to `analyse_nonpitched`, not as sidecar fields** (the sidecar `features` object stays at four non-pitched features, which keeps kick and clap sidecars valid). Promoting `body_peak_hz`, `body_noise_ratio_db`, `body_t60_ms`, `noise_t60_ms` into `sample-metadata` is a `contract-change` and is the researcher note's step S0; this note recommends doing it only after the user's first listening result shows which of them he steers by.

## 5. Proposed contract fields for a future `snare-params` (PROPOSAL ONLY, `contracts/` untouched)

Base: the researcher note section 2.2, which is not copied in full here. Names and ranges are proposals; defaults are placeholders until the audio-engineer re-measures and the user listens.

**Group A, shared with `clap-params` v0.1** (same names and meaning): `schema_version`, `seed`, `variants`, `bpm`, `sample_rate`, `bit_depth`, `length_ms`, `drive`, `polarity`, `offset_ms`, `peak_ceiling_dbfs`, `preset`. (The clap schema's `length_ms` range is its own; the snare range 100 .. 1500 is the researcher's proposal.)

**Group B, snare-specific:**

| Field | Group | Range (proposal, section 2) | Note |
| --- | --- | --- | --- |
| `body_hz`, `mode_ratio`, `body_shape` | body | 120 .. 400 / 1.5 .. 2.4 / 0 .. 1 | `mode_ratio` stays a parameter because three sources disagree |
| `pitch_drop`, `pitch_drop_ms` | body | 1.0 .. 2.0 / 3 .. 60 | upper partial follows the lower by `mode_ratio` (the contract must say so) |
| `body_decay_ms`, `body2_decay_ratio` | body | 30 .. 300 / 0.3 .. 1.2 | decay = time to -60 dB after the attack, as the hat text |
| `body_level` | mix | 0 .. 1 | contract must say **where the power share is measured** (hat finding P1 / issue H0 point 1: before or after the noise filters); a decision for the lead, with the hat result H2 as the precedent |
| `noise_decay_ms`, `noise_band_mix` | noise | 60 .. 800 / 0 .. 1 | the second (narrow) band has its own faster decay (909 structure, S1) |
| `noise_hp_hz`, `noise_lp_hz` | noise | 500 .. 6000 / 3000 .. 16000 | cross-field rule `noise_lp_hz` > 1.2 x `noise_hp_hz` (engine rule; JSON Schema cannot express it, as in the hat text) |
| `noise_attack_ms` | noise | 0.1 .. 12 | |
| `tone_peak_hz`, `tone_peak_db` | colour | 2000 .. 8000 / -6 .. +6 | optional static peaking, as hats |
| `gate_ms` | tail | 0 or 20 .. 500 | optional, no source; clap analysis found one gated reference (clap note); candidate to drop from v0.1 |

**Cross-field and global rules to state in the contract (derived):** upper partial `body_hz` x `mode_ratio` x `pitch_drop` below 0.45 x `sample_rate`; the body is deterministic and the seed changes only the noise (so `body_level` 1 is seed-independent); each noise layer takes its own `substreams` stream; reject out-of-range values, do not clamp; `noise_lp_hz` below Nyquist; first sample 0, DC removal and fade as in clap.

**Decisions for the lead (not mine to take):**

1. `snappy` as a field or only as a vocabulary keyword weight (researcher note: open). It is a macro of two other fields, so as a field it is a redundant degree of freedom, which makes the "every field moves a measurable value" rule harder to test (derived).
2. Rim shot as a separate `rim-params` (researcher's proposal) or a `model` of snare; this note assumes separate and does not cover rim.
3. Is `gate_ms` in v0.1 or deferred (no source, one derived idea).
4. Whether `body_shape` (sine to triangle) earns a field in v0.1: sources conflict (S9 sine, S10 and the artifact triangle) and nothing measurable separates it except harmonic content above the partials (derived; a harmonic-ratio measurement would be needed).
5. Where `body_level` is measured (see above).
6. Category enum: `snare` added to `sample-metadata` `category` (now `kick`, `clap`; `hat` is planned by the hat issues). A separate `contract-change` issue per the hat precedent.
7. Whether the kick vocabulary note-name resolver (`note:`, `key:`) applies to `body_hz` (a snare tuned to a key). Not researched; left open.

## 6. Listening-test skeleton (for a later snare test; depends on a snare voice and the hat/clap test results)

Same method as the clap and hat tests: identical control pair, blind names, A/B mixed by a fixed seed, German answer sheet, key file `Schluessel.md` opened after the test, "kein Unterschied" always allowed. Rendered by the audio-engineer, decoded by the lead. **This is a skeleton**: the preset values are the section 2 starter values (hypotheses) and must be replaced by engine-measured numbers (T1-T9) before the test.

**Common setup (my choices, not the user's):** 4 bars at 136 BPM (as in the other tests), mono 48 kHz / 24-bit, `dense` kick on every beat, snare on beats 2 and 4, each hit cut at 1 beat with a 3 ms cosine fade, peak at most -0.3 dBFS, warp off, no master effects, `seed` 1. Level match within each item by RMS over 0-100 ms of the snare alone (hypothesis: that window follows body and noise attack, not the tail; the lead checks and records the gains in the key). Base render **D** = starter values of section 2.

| Item | Files (blind) | Single question answered | Changed vs. D |
| --- | --- | --- | --- |
| **N0** control | A = B, identical bytes (D) | How often a side is picked with no difference | none |
| **N1** body pitch | three files: `body_hz` 150 / 190 / 260 | Rank "mein Snare"; is the best too tief, richtig or zu hoch | `body_hz` |
| **N2** body/noise share | three files: `body_level` 0.3 / 0.6 / 0.85 | Rank; is the best too rauschig, richtig or zu tonal | `body_level` |
| **N3** tail length | three files: `noise_decay_ms` 90 / 180 / 350 | Which fits the kick pattern; does the long one smear | `noise_decay_ms` |
| **N4** noise brightness | three files: `noise_hp_hz` 1000 / 1800 / 3500 | Which is too dunkel, too hell, right | `noise_hp_hz` |
| **N5** snare against clap | three files: D alone, a clap (existing voice, tight techno style of the clap note) alone, D + clap summed (clap at -6 dB, as clap test C5) | Which is "mein Backbeat"; does the sum have something the single files lack (and which word) | category / layer |
| **N6** variants | four seed variants of D (`variants` 4) | Which sound like the same snare, which falls out | `variants` |

Blind-named files: N0 2, N1 3, N2 3, N3 3, N4 3, N5 3, N6 4 = **21**. Unique renders: **14** (D, used in N0 A and B, once each in N1-N4, in N5 as "alone" and as N6 v0; plus 13 others: `body_hz` 150 and 260, `body_level` 0.3 and 0.85, `noise_decay_ms` 90 and 350, `noise_hp_hz` 1000 and 3500, the clap alone, the sum, variants v1-v3). Copies of D differ in bytes only by the per-item level-match gain; N0 A and B must be byte-identical. Time estimate: pairs about 1 minute, three- and four-file items about 2 minutes, set-up 2, one break: about 16 minutes. That is above the 15-minute guide; drop N6 (variants are tested without the user in T9) to get about 14 minutes. **Order:** N3 -> N0 -> N4 -> N5 -> N1 -> N2 (the likely audible difference first, control in the middle, rankings last).

**Frageblock (skeleton, German):**

| # | Frage (eine pro Block) | Antwortmöglichkeiten |
| --- | --- | --- |
| N3 | **Welche Snare passt besser zu deinem Kick-Muster?** Wenn die längere etwas gewinnt: was (ein Wort)? | kurz / mittel / lang / kein Unterschied · Wort |
| N0 | **Welche Snare sitzt besser?** | A / B / kein Unterschied |
| N4 | Drei Dateien. **Welche ist zu dunkel, welche zu hell, welche passt?** | z. B. X dunkel, Y passt, Z hell |
| N5 | Drei Dateien. **Welche ist „mein Backbeat"? Hat die Summe etwas, das die Einzeldateien nicht haben (ein Wort)?** | Reihenfolge · Wort |
| N1 | Drei Dateien. **Sortiere von „mein Snare" bis „am wenigsten".** Danach: **Ist die beste zu tief, richtig oder zu hoch?** | Reihenfolge · zu tief / richtig / zu hoch |
| N2 | Drei Dateien. **Sortiere.** Danach: **Ist die beste zu rauschig, richtig oder zu tonal?** | Reihenfolge · zu rauschig / richtig / zu tonal |
| N6 | Vier Dateien. **Welche klingen für dich wie dieselbe Snare? Welche fällt raus (wenn eine rausfällt)?** | Liste |

**How the lead reads the answers (skeleton):**

| Answer | Reading | Next step |
| --- | --- | --- |
| N0 not "kein Unterschied" | The user picks a side without a difference | Weigh all answers against it; repeat the pair reversed |
| N1 "passt" is not 190 | `body_hz` default shifts toward his pick | Preset value, not a contract change |
| N1 best is at the edge (150 or 260) | The range may be too narrow | Extend inside the contract (120 .. 400) |
| N2 best = 0.3 or 0.85 | The balance default is off | Preset value; the word names the quantity to measure (Q4) |
| N3 long preferred or the long one gains a word | Tail length matters | Two tail presets; the word names the property (Q7, low-mid) |
| N4 "passt" is not 1800 | `noise_hp_hz` default shifts | Preset value |
| N5 sum preferred, or the sum gains a word | A snare and clap layer has value | Question for the planner: is `snare` a timeline element (researcher open question 2) |
| N5 clap alone preferred | The snare may not be needed as a backbeat | Priority of the snare category goes down (lead decides) |

## 7. What could not be sourced

- **Any numeric taste range for a techno/trance snare.** No published target, no user references. The 77-kick taste range does not transfer.
- **Any real-machine value.** The SOS article gives no 808 or 909 frequencies, cutoffs or decay times (verified by opening the page today). The 238/476 Hz and the 808 rim values (S4, S6) come from one hobby page I did not re-open; the Roland service manual (the page's own named source) was not opened.
- **The researcher's S1 wording** ("named 180 Hz and 330 Hz" as a 909 mode) does not match the article: they are the author's model values (short version 3). The researcher note is not edited by this PR (owner: researcher); the lead may ask for a correction line.
- `noise_lp_hz`, band-pass Q, the second-partial level, the 909 noise-band split frequency, a real snare's decay times: no number found.
- No measurement of any kind was made for this note: no model run (unlike the clap and hat notes), no engine, no render, no reference audio. The only command I ran against a source was one page fetch (below). The `PR #265` helper behaviour is taken from its PR body and function signatures, not from running it.
- Not covered: rim shot, clave, snare+clap layering design beyond the N5 question, stereo, a note-name input.
- Open for the user (from the researcher note, still the blockers): can you supply 3-5 snares (audio only, never names as targets) so the ranges in section 2 become measured; and does your Techno/Trance use snare, clap or both layered.

## 8. Commands run

```
cd /home/claude/abeltongod && git fetch origin && git log --oneline origin/main | head -3        # base 5fdb159
gh api repos/castorsalzmann-ui/abeltongod/pulls/265 --jq '{state,title,head:.head.ref,merged,body}'   # open, not merged
gh api repos/castorsalzmann-ui/abeltongod/pulls/265/files --jq '.[].filename'                       # analysis.py, test_hat_analysis.py
git show origin/phase-06/251-hat-analysis:src/audio_engine/analysis.py | grep -n -A3 "^def ..."      # helper signatures
jq -r '.properties|keys|join(" ")' contracts/clap-params.schema.json                                 # shared-field names
jq -r '.properties.features.properties|keys|join(" ")' contracts/sample-metadata.schema.json         # sidecar features
WebFetch https://www.soundonsound.com/techniques/practical-snare-drum-synthesis                      # numeric values: 180/330 Hz are the author's model; no 808/909 numbers
```
