# Rim shot: measurable quantities, starter ranges (hypotheses), analysis gaps, contract-field proposal and listening-test skeleton

_Date: 2026-11-02 · Role: sound-designer · Refs #151 (next categories after hats) · Status: **pre-work, plan and hypotheses, not a result.** Docs only. Nothing here was rendered, measured or heard; no number comes from an engine, a model run or reference audio. Every "tighter", "more woody", "snappier" is for the user's ear. All parameter values are proposals; none is a default or a taste claim. No rim engine exists. `contracts/` is not touched._

Read before writing: `CLAUDE.md`; the researcher note [snare, rim and sub-bass design](2026-11-02_snare-rim-and-sub-bass-design.md) (S1 corrected by PR #268; its research is **not repeated**, findings are cited as S1-S11 and section 2.4); [snare targets](2026-11-02_snare-targets.md) (structure, pitfalls P1-P7, listening method); `src/audio_engine/analysis.py` and `contracts/` on `origin/main` e1e265a (helper signatures and field names read from the files, not run).

Labels: *sourced* = the researcher note's cited source says it (I did not re-open any page for this note, see section 7); *derived* = my inference; *unverified* = could not be checked.

Decision already taken by the lead: rim shot is a **separate** `rim-params`, not a `model` of snare. This note assumes it.

## Short version

1. A rim shot (808-style) is, per the researcher note, **two or three damped sinusoids with no noise path** (S5, S6, S7). Its measurable core is therefore small: **lower partial frequency, partial ratio, the two decays, high-pass edge, brightness, total length, and the attack click** (eight quantities, section 1). It has far fewer unknowns than the snare, but also **almost no sourced numbers**.
2. **No taste range exists.** No published numeric target for a techno/trance rim, and no user reference rims. Section 2 lists the few sourced points (one hobby page for 455 / 1667 Hz, the artifact's constants) and marks the rest "none".
3. **The sourced numbers are weak:** 455 Hz and 1667 Hz (S6) come from one hobby page that nobody re-opened; the Roland service manual was never opened; the ModularGrid 909 rim listing (S8) has a copy-paste error and is low confidence; the SOS article and the DAFx-14 paper give **no** rim numbers (S3, S5).
4. **Existing analysis cannot yet measure the rim well.** Main has whole-file helpers and the hat helpers from #251 (`welch_flatness`, `hf_share`, `lf_leak_db`, `peak_count`, `t60_line_fit_ms`, `early_late_centroid_ratio`). The rim's decays are tens of ms, which is short against the hat helpers' windows (4 ms RMS smoothing, 20 ms early window, 6 ms fade guard); whether that breaks them is only partly checked (P4: a synthetic probe gave numbers, not `None`). **Missing:** a two-peak finder tuned to a short sparse spectrum, per-partial decay, an early-window onset measure (section 4).
5. A **`rim-params` v0.1 field list** is proposed in section 5 (PROPOSAL only; researcher note 2.4 is the base, with decisions for the lead).
6. A **listening-test skeleton** (6 items, 16 blind files, about 12 minutes) is in section 6. It cannot run before a rim voice exists and the ranges are re-measured on it.

## 1. Which measurable quantities define the rim shot

All rows are **derived** from S5-S8 and the artifact (S11) unless a source is named; none is measured on any audio. Windows follow the kick learnings (from the onset, per zone).

| # | Quantity | Why it defines the rim (derived) | Window / method | Moves with (proposal field) |
| --- | --- | --- | --- | --- |
| R1 | **Lower partial frequency** | The only strongly pitched component in the model (S6: about 455 Hz; artifact: square 1.7-2.3 kHz plus a triangle at 0.28 f) | strongest peak in the first 30 ms, Hann window shorter than the sample; cross-check with zero crossings (kick pitfall 3) | `f1_hz` |
| R2 | **Partial ratio** (upper/lower) | S6 1667/455 = 3.66; artifact 1/0.28 = 3.57; ratio sets the "knock" interval (hypothesis) | two strongest peaks in 300-6000 Hz | `f2_ratio`, `f3_ratio` |
| R3 | **Partial level ratio** | The balance of the two resonators | peak levels (dB) of the two lines, first 30 ms | `level2` |
| R4 | **Decay of each partial** | S5: bridged-T pinged = decaying pseudo-sinusoid; decays are tens of ms | band-pass around each line, RMS envelope, time to -20/-40 dB (not -60 if it is not reached) | `decay1_ms`, `decay2_ms` |
| R5 | **Low edge** (high-pass) | S6: the rim is high-passed, no cutoff given | energy under `hp_hz / 2` over total (`lf_leak_db` idea), spectrum -6 dB corner | `hp_hz` |
| R6 | **Brightness** | Existing sidecar features | centroid, `hf_share_8k`, plus `hf_share` at another split | `f1_hz`, `f2_ratio`, `hp_hz`, `click_level` |
| R7 | **Attack click** | The first 1-3 ms decide whether it reads as a tick; S6 says no noise, the artifact adds none, so the click is a derived idea | high-band (above 4 kHz) energy in the first 3 ms over the following 30 ms | `click_level`, `click_ms` |
| R8 | **Total length** | Sets the grid fit; short | `length_ms`, `t60_ms` (see P2) | `decay1_ms`, `length_ms` |

Not a rim quantity in v0.1 (derived): body pitch drop (S5 shows the bend for the kick, its size for the rim is not sourced; optional `bend` below), noise tail, room, stereo.

## 2. Starter ranges (HYPOTHESES) and where each number comes from

Rule for this table: a **sourced point** is a value a source gives; the **proposal range** is the researcher note's section 2.4 range, widened by the researcher's judgement. It is **not** a measured taste range. "none" means no source gives any number.

| Quantity / field | Sourced points | Source and confidence | Proposal range (hypothesis) | Starter value (hypothesis) |
| --- | --- | --- | --- | --- |
| `f1_hz` | 455 Hz (808 rim); artifact square 1.7-2.3 kHz (a different structure: the artifact's high square is the main tone); clave 2500 Hz | S6 low-medium (one hobby page, rounded, not re-opened); S11 existing note | 300 .. 3500 | 455 |
| `f2_ratio` | 1667/455 = 3.66; artifact 1/0.28 = 3.57 | S6 low-medium; S11 | 2.0 .. 5.0 | 3.66 |
| `f3_ratio` | three oscillators in a 909 rim module | S8 low (vendor listing with copy-paste error); no frequency | 0 (off) .. 8 | 0 |
| `level2` | **none** | - | 0 .. 1 | 0.6 (no source) |
| `decay1_ms`, `decay2_ms` | **none** (artifact 12 + 0.4 x decay ms for the square) | S11 only | 5 .. 120 | 40, 15 (no source for either) |
| `hp_hz` | S6 says "high-passed", **no cutoff** | S6 | 200 .. 6000 | 1000 (placeholder) |
| `click_level`, `click_ms` | **none**; S6 and the artifact have no noise | derived idea | 0 .. 1, 0.2 .. 3 | 0.2, 1 (placeholder) |
| `bend` (start/end pitch ratio) | **none** for the rim; bridged-T bend of more than an octave is stated for the kick (S5) | S5 absence for rim | 1.0 .. 1.5 (my narrowing, no source) | 1.0 (off) |
| `length_ms` | **none** | derived from decays plus fade | 50 .. 600 | 200 |
| Target **centroid, HF share, t60, rise time** of a techno/trance rim | **none** | no published numeric target; the 77-kick taste range does not transfer | **no range proposed**; analysis reports, it does not pass or fail on taste | - |

Not given by the research, listed so nobody invents them: genre-specific values (all sources are 808/909 or artifact), any measured decay of a real rim, resonator Q, the high-pass cutoff, partial levels, whether the 909 rim differs from the 808 in frequency (S8 is the only 909 hint and is unreliable), how a layered rim (rim over clap or snare) is measured.

Single-field effect directions below are **hypotheses by construction** (the field is built to move the quantity); they are for the engine tests, not findings:

| Hypothesis | Field moved | Quantity expected to move | Measurement that would reject it |
| --- | --- | --- | --- |
| RT1 | `f1_hz` up | R1 up by the same ratio; centroid up | R1 within a tolerance (set from a measurement) of `f1_hz`; if not, the pitch tracker or the window is wrong (P1) |
| RT2 | `f2_ratio` up | R2 up, R1 unchanged | the two strongest peaks are not the two partials (high-pass or click energy wins, P3) |
| RT3 | `level2` up | R3 up | not monotone over seeds 1-8 (or seed-independent, see RT7) |
| RT4 | `decay1_ms` up | R4 (partial 1) up; `t60_ms` up | per-partial decay not following; the overall `t60_ms` is set by the longer partial (P2) |
| RT5 | `hp_hz` up | R5 shifts up; centroid up; `lf_leak_db` relative to the new corner stays low | leak does not follow the corner |
| RT6 | `click_level` up | R7 up; `hf_share_8k` up | R7 not monotone; or the click moves R1/R2 (leakage into the peak finder) |
| RT7 | Seed changes | with `click_level` 0 the render is seed-independent (damped sines are deterministic); only the click changes | any change at `click_level` 0 |
| RT8 | Variants of one preset | stay inside the seed spread of the preset's box | spread larger than the box (same check as snare T9, hat H12, clap H10) |

## 3. Analysis pitfalls for a rim

From the kick learnings (all apply): Hann over a whole one-shot mutes the onset (1); measure from the onset, not the RMS maximum (2); a short FFT window quantises pitch (3); decay on a 1 ms envelope catches ripple (4); "never reached" is `None` (5); reference folders contain loops, count hits (6, 7); "no duplicates" needs a positive control (8); no labels from file names (9). From the snare note: P5-P7 carry over unchanged (room or layering in references, sample-rate band edge, seed independence needs a positive control).

Rim-specific, all **derived** (none confirmed by a measurement):

- **P1 A short sound has a coarse spectrum.** A 30 ms window has 33 Hz bins; with `decay1_ms` of 5-15 ms the line is also broadened by its own decay (line width on the order of 1/(pi x tau), derived). Peak positions are fine; peak levels and decay come out of the band envelope, not the FFT width. Cross-check R1 with zero crossings on a short segment (applicability to a 20-30 ms segment not checked).
- **P2 `t60_ms` is mostly a fade-guard problem.** `FADE_GUARD_MS` is 6 ms in `analysis.py` and `ENV_RMS_MS` is 1 ms (the main-branch values, read from the file); `t60_line_fit_ms` smooths with 4 ms (`FIT_ENV_MS`); the 5 ms figure is the snare note's rule (from the kick learnings), not a value in the code. For a 10-40 ms decay a 4-5 ms smoothing window is a large part of the decay itself (derived), and `t60_ms` must reach -60 dB before the last 6 ms of the file. Report `None` honestly, prefer -20/-40 dB times for decay comparisons, and do not set `length_ms` so short that the fade eats the tail.
- **P3 The two-peak finder is sensitive to the click and the high-pass.** A noise click raises the floor and can win the second peak; check with `click_level` 0 as the positive control. A high-pass near `f1_hz` suppresses the lower partial (the skirt eats it); this is a parameter interaction, not an analysis bug.
- **P4 Hat helper windows do not fit a rim.** `early_late_centroid_ratio` uses the first 20 ms over 60-100 % of the line-fit `t60` (a window the length of the whole rim), and `t60_line_fit_ms` fits the -10..-40 dB range of a per-sample envelope smoothed with a 4 ms window (the envelope is per sample, so the point count is not the limit). The 4 ms smoothing and the 6 ms guard are the real limits for a 10-40 ms decay. That they make the helpers return `None` is **not established**. One probe (scratchpad `rimprobe.py`, not in the repo; synthetic sum of 455 Hz and 1667 Hz (0.6) sines with exponential decay to -60 dB at the nominal time, 48 kHz, 200 ms file, 5 ms end fade) gave:

  | nominal -60 dB time | `t60_line_fit_ms` | `early_late_centroid_ratio` | `t60_ms(rms_envelope)` |
  | --- | --- | --- | --- |
  | 10 ms | 10.04 | 1.038 | 10.042 |
  | 20 ms | 19.96 | 0.767 | 19.958 |
  | 40 ms | 39.877 | 0.969 | 38.979 |

  The decay times track the nominal value on this idealised signal. The centroid ratio is not a decay measure and moves with the window placement; its meaning for a rim is unchecked. Real renders, other partial levels and short `length_ms` were not probed.
- **P5 `peak_count` is built for 4-20 kHz.** It is the wrong band for `f1_hz` 300-3500 Hz and is not a rim measure.
- **P6 Partial aliasing.** A partial or its click above 0.45 x `sample_rate` aliases; this is a contract rule, and an independent 4x render is the check (as in the other categories).
- **P7 Clave overlap.** With `f2_ratio` off and `f1_hz` near 2500 Hz the voice is the clave special case (researcher note 2.4); a measurement tuned to two peaks will return one. Decide per preset which case it is.

## 4. Which analysis helpers measure what, and what is missing

State of the code: `origin/main` e7d7522. #251 hat helpers are **on main** (signatures read; one synthetic probe, see P4).

| Quantity | Existing helper | Status | Gap |
| --- | --- | --- | --- |
| R6, R8 whole-file values | `analyse_nonpitched` (centroid, `hf_share_8k`, `t60_ms`, `rise_time_ms`, `peak_dbfs`, `length_ms`) | exists; whole file | `t60_ms` returns `None` if -60 dB is not reached before the last 6 ms (P2) |
| R6 HF share at another split | `hf_share(audio, sr, split_hz)` | on main | none |
| R5 low-frequency leak | `lf_leak_db(audio, sr, hp_hz)` | on main; whole file; energy under `hp_hz / 2` | counts all energy under half the corner, including `f1_hz` if `f1_hz` < `hp_hz / 2`; use only when `hp_hz` is well below `f1_hz` |
| R6 brightness/flatness in a band | `welch_flatness` | on main | a rim is sparse (lines), not noise-like; flatness is not a rim target (derived), not needed |
| R8 tail with less bias | `t60_line_fit_ms` | on main | 4 ms smoothing, -10..-40 dB fit; matched the nominal time on a synthetic 10/20/40 ms decay (P4), not checked on real renders |
| Early/late brightness | `early_late_centroid_ratio` | on main | late window is 60-100 % of the whole rim; meaning for a rim unchecked (P4) |
| R1 lower partial | `zero_crossing_frequency`, `tail_window` | on main, kick-oriented (tail of the last 100 ms) | a **first-30-ms peak finder** does not exist |
| R2 partial ratio | none | missing | two strongest peaks in 300-6000 Hz, window sized by the sample, click-robust (P3) |
| R3 level ratio | none | missing | level of each line over the first 30 ms |
| R4 per-partial decay | `rms_envelope`, `t60_ms` operate on a given array | building blocks exist | **band-pass around each line, then envelope**, with the `None` rule and a window of 1 ms (not 5 ms) for decays under 30 ms (P2) |
| R7 click | none | missing | high-band energy, first 3 ms over the next 30 ms; not `rise_time_ms` (hat P4: not seed-stable below about 3 ms) |

Policy (derived from the hat and snare precedent): new rim measurements start as **design and test helpers next to `analyse_nonpitched`, not as sidecar fields**. Promoting `f1_measured_hz`, partial ratio or per-partial decay into `sample-metadata` is a `contract-change`, which this note recommends only after the user's first listening result shows what he steers by. The `category` enum on main is `kick`, `clap`, `hat`; a `rim` value is also a `contract-change` (same pattern as the hat issue H0).

## 5. Proposed contract fields for a future `rim-params` (PROPOSAL ONLY, `contracts/` untouched)

Base: researcher note 2.4, not copied in full. Names and ranges are proposals; defaults are placeholders until the audio-engineer re-measures and the user listens.

**Group A, shared envelope/export fields** (same names and meaning as `clap-params` v0.1 / `hat-params`): `schema_version`, `seed`, `variants`, `bpm`, `sample_rate`, `bit_depth`, `drive`, `polarity`, `offset_ms`, `peak_ceiling_dbfs`, `preset`, `length_ms` (rim range 50 .. 600, the researcher's proposal). Field names read from `clap-params.schema.json`; `bpm` and `drive` are in it on main.

**Group B, rim-specific:**

| Field | Range (proposal, section 2) | Note |
| --- | --- | --- |
| `f1_hz` | 300 .. 3500 | wide so the clave case (2500 Hz) is inside |
| `f2_ratio` | 2.0 .. 5.0 | single partial: needs an explicit "off" (see decision 2) |
| `f3_ratio` | 0 (off) .. 8 | S8 is low confidence; candidate to drop from v0.1 |
| `level2` | 0 .. 1 | |
| `decay1_ms`, `decay2_ms` | 5 .. 120 | decay = time to -60 dB after the attack, as in the hat/snare text |
| `hp_hz` | 200 .. 6000 | cross-field rule: below `f1_hz` (engine rule; JSON Schema cannot express it) |
| `click_level`, `click_ms` | 0 .. 1, 0.2 .. 3 | optional noise tick; own `substreams` stream; the only seed-dependent part |
| `bend` | 1.0 .. 1.5 | optional start/end pitch ratio; no source for the rim |
| `tone_peak_hz`, `tone_peak_db` | not proposed | the snare/hat static peaking is not needed for a closed-form voice (derived) |

**Cross-field and global rules to state in the contract (derived):** every partial `f1_hz` x `f2_ratio` (x `f3_ratio`) x `bend` below 0.45 x `sample_rate`; the partials are deterministic and the seed changes only the click (so `click_level` 0 is seed-independent); the click takes its own `substreams` stream; reject out-of-range values, do not clamp; start phases of the sines fixed in the contract (the first-ms waveform is audible in layering; the researcher note raised this for the bass); first sample 0, DC removal and fade as in clap.

**Decisions for the lead (not mine to take):**

1. `clave` as its own `model` or as the special case `f2_ratio` off with `f1_hz` near 2500 Hz (researcher note says special case). Leaves one field set, but a `model` would make clave presets selectable by name.
2. How a single-partial rim is expressed: `f2_ratio` with an "off" value, or `level2` = 0. Both give the same sound; one field should own it so tests do not have two ways to the same state.
3. Whether `f3_ratio`, `bend` and the click are in v0.1 or deferred (the sourced evidence for each is weak or absent).
4. Whether the rim keeps a `category` of its own (`rim`) or maps to a `perc` category with `perc1` (researcher note: the rim competes with `perc1` for timeline weight). A `contract-change` in either case.
5. Whether the note-name resolver (`note:`, `key:`) applies to `f1_hz`. Not researched; left open.
6. Priority of the rim at all: researcher open question 3 (user) is unanswered.

## 6. Listening-test skeleton (for a later rim test; depends on a rim voice and the earlier test results)

Same method as the snare, clap and hat tests: identical control pair, blind names, A/B mixed by a fixed seed, German answer sheet, key file `Schluessel.md` opened after the test, "kein Unterschied" always allowed. Rendered by the audio-engineer, decoded by the lead. **This is a skeleton**: preset values are the section 2 starter values (hypotheses) and must be replaced by engine-measured numbers (RT1-RT8) before the test.

**Common setup (my choices, not the user's):** 4 bars at 136 BPM, mono 48 kHz / 24-bit, `dense` kick on every beat, rim as an offbeat 16th pattern (a pattern choice for the test; the genre use of a rim is unsourced), each hit cut at one 16th with a 3 ms cosine fade, peak at most -0.3 dBFS, warp off, no master effects, `seed` 1. Level match within each item by RMS over 0-60 ms of the rim alone (hypothesis: that window covers both partials; the lead checks and records the gains in the key). Base render **D** = starter values of section 2.

| Item | Files (blind) | Single question answered | Changed vs. D |
| --- | --- | --- | --- |
| **M0** control | A = B, identical bytes (D) | How often a side is picked with no difference | none |
| **M1** pitch | three files: `f1_hz` 350 / 455 / 700 | Rank "mein Rim"; is the best too tief, richtig or zu hoch | `f1_hz` |
| **M2** length | three files: `decay1_ms` 15 / 40 / 90 (`decay2_ms` scaled by the same factor) | Which fits the kick pattern; does the long one smear | `decay1_ms`, `decay2_ms` |
| **M3** second partial | three files: `level2` 0 / 0.6 / 1 | Which is "mein Rim"; does the single-partial (0) read as a rim at all | `level2` |
| **M4** click | two files: `click_level` 0 / 0.3 | Which has the better attack; "kein Unterschied" allowed | `click_level` |
| **M5** rim against clap | three files: D alone, the existing clap alone, D + clap summed (clap at -6 dB) | Which is "mein Offbeat"; does the sum have something the single files lack (and which word) | category / layer |

Blind-named files: M0 2, M1 3, M2 3, M3 3, M4 2, M5 3 = **16**. Unique renders: **11** (D, used in M0 A and B, once each in M1-M5 where it appears; plus `f1_hz` 350 and 700, `decay1_ms` 15 and 90, `level2` 0 and 1, `click_level` 0 and 0.3, the clap alone, the sum = 10 others). Copies of D differ in bytes only by the per-item level-match gain; M0 A and B must be byte-identical. Time estimate: pairs about 1 minute, three-file items about 2 minutes, set-up 2: about 12 minutes. **Order:** M2 -> M0 -> M4 -> M5 -> M1 -> M3.

**Frageblock (skeleton, German):**

| # | Frage (eine pro Block) | Antwortmöglichkeiten |
| --- | --- | --- |
| M2 | **Welcher Rim passt besser zu deinem Kick-Muster?** Wenn der längere etwas gewinnt: was (ein Wort)? | kurz / mittel / lang / kein Unterschied · Wort |
| M0 | **Welcher Rim sitzt besser?** | A / B / kein Unterschied |
| M4 | **Welcher hat den besseren Anschlag?** | A / B / kein Unterschied |
| M5 | Drei Dateien. **Welche ist „mein Offbeat"? Hat die Summe etwas, das die Einzeldateien nicht haben (ein Wort)?** | Reihenfolge · Wort |
| M1 | Drei Dateien. **Sortiere von „mein Rim" bis „am wenigsten".** Danach: **Ist der beste zu tief, richtig oder zu hoch?** | Reihenfolge · zu tief / richtig / zu hoch |
| M3 | Drei Dateien. **Welche ist „mein Rim"? Klingt die erste (nur ein Ton) noch wie ein Rim?** | Reihenfolge · ja / nein |

**How the lead reads the answers (skeleton):**

| Answer | Reading | Next step |
| --- | --- | --- |
| M0 not "kein Unterschied" | The user picks a side without a difference | Weigh all answers against it; repeat the pair reversed |
| M1 "richtig" is not 455 | `f1_hz` default shifts toward his pick | Preset value, not a contract change |
| M1 best is at the edge (350 or 700) | The range may be too narrow | Extend inside the contract (300 .. 3500) |
| M2 long preferred or gains a word | Tail length matters | Two length presets; the word names the property (R4) |
| M3 best = 0, or "ja" for the single tone | A single-partial rim is enough | Makes `f2_ratio` less important; supports the clave special case |
| M3 best = 1 or "nein" | The second partial carries the identity | Keep `level2` default; measure R2/R3 on his pick |
| M4 click preferred | The attack matters | The word names the property (R7); keep `click_level` in v0.1 |
| M5 sum preferred, or gains a word | A rim and clap layer has value | Question for the planner (timeline element) |
| M5 clap alone preferred | The rim may not be needed | Priority of the rim goes down (lead decides) |

## 7. What could not be sourced

- **Any numeric taste range for a techno/trance rim.** No published target, no user references. The 77-kick range does not transfer.
- **Any real-machine value.** 455 Hz and 1667 Hz (S6) and the 2500 Hz clave come from one hobby page nobody re-opened; the Roland service manual (the page's own named source) was not opened by anyone. I did not open it, nor re-open any page, for this note.
- S7 (syntherjack) gives the circuit structure and no frequencies; S5 (DAFx-14) confirms the bridged-T mechanism and gives no rim numbers; S8 (ModularGrid) is a vendor listing with a copy-paste error.
- `level2`, decays, `hp_hz`, resonator Q, click level and time, the size of any rim pitch bend, a real rim's length: no number found.
- Whether the damped-sine closed form matches the machine: not established (researcher note 1.2 item 3).
- No measurement of any real audio was made for this note: no engine, no render, no reference audio. The only run is the synthetic probe in P4 (idealised damped sines); other helper behaviour on a rim is inferred from the code read.
- Not covered: stereo, a note-name input, layering design beyond the M5 question, how common a rim is in techno/trance (no source opened).
- Open for the user (from the researcher note, still the blockers): can you supply 2-3 rims you like (audio only, never names as targets); do you want a rim before bass at all.

## 8. Commands run

```
cd /home/claude/abeltongod && git fetch origin && git worktree add -b phase-06/rim-targets /home/claude/wtrim origin/main   # created at e1e265a, merged origin/main e7d7522 before the final push
python -I rimprobe.py (scratchpad, PYTHONPATH src)                            # P4 synthetic probe: t60_line_fit_ms, early_late_centroid_ratio, t60_ms
grep -n "^def " src/audio_engine/analysis.py                                  # helper list incl. hat helpers on main
sed -n 216,400p src/audio_engine/analysis.py                                  # helper docstrings (read, not run)
grep -n "^ENV_RMS_MS\|^RISE_" src/audio_engine/analysis.py                    # ENV_RMS_MS = 1.0
jq -r '.properties|keys|join(" ")' contracts/clap-params.schema.json          # shared-field names
jq -c '.properties.category' contracts/sample-metadata.schema.json            # enum: kick, clap, hat
```
