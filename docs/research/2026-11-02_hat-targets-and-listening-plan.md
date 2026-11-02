# Hats: measurable target ranges, hypotheses, listening-test plan and issue texts H0-H3

_Date: 2026-11-02 · Role: sound-designer · Refs #151 (hat category; user order: clap first, then hats) · Status: **plan and hypotheses, not a result.** Nothing here was heard. Numbers describe signals only; every "better", "tighter", "more open" is for the user's ear. All parameter values are proposals; none is a default or a taste claim. No hat engine exists yet; this note prepares it._

Read before writing: [hat synthesis design](2026-11-02_hat-synthesis-design.md) (metal bank, `hat-params` v0.1 proposal, features), [next-category proposal](2026-11-02_next-category-proposal.md) (H0-H7), [clap targets and listening plan](2026-11-02_clap-targets-and-listening-plan.md) (format), [clap reference analysis](2026-11-02_clap-reference-analysis.md) (lessons: model numbers need re-measurement, `rise_time` unstable, seed-stable features only), and the merged scaffold (`src/audio_engine/dsp.py`, `analysis.py`, `categories.py`, `contracts/sample-metadata.schema.json` v0.2, #229-#231 on `origin/main` 4472cb9).

Lead decisions applied: shaker and ride are out of `hat-params` v0.1; mono is accepted. "H1..Hn" below are hypotheses; "issue H0-H7" always means the issue split of the next-category proposal 3.6 (the same double use as in the clap note).

## Short version

1. **Closed and open hats are one voice** and differ in `decay_ms` (and `hp_hz`). Target boxes are in section 2, for t60, centroid, HF share, low-frequency leak, peak count and flatness.
2. **All numbers come from my own NumPy model** of the design note's recipe (script in my scratchpad, not in the repo), seeds 1-8. They are not from the engine (none exists) and not from reference audio (none supplied). The model's features were checked against the repo's `analyse_nonpitched` (#230) on the same model output: centroid, HF share, t60 and rise time were **identical** for all 8 seeds in three styles (section 1).
3. **Most important model finding (hypothesis H2, decides the `metal` definition in issue H0):** if `metal` is a power share measured **before** the high-pass (the design note's reading), the square bank keeps only about 5 % of the passband power at `metal` 0.6, because a square's power sits in its low harmonics and the 4th-order high-pass removes them. Then `metal` from 0 to 0.8 cannot be seen by flatness, peak count or correlation with the pure bank. With the mix normalised **after** the filter chain, the correlation with the pure bank follows sqrt(`metal`) (0.50-0.58 at 0.3, 0.75-0.79 at 0.6, 0.94-0.95 at 0.9) and peak count rises from 0 to 79.
4. Other pitfalls found by the model (section 3): `rise_ms` is not seed-stable below ~3 ms attack; the first-crossing `t60` undershoots long decays by up to 9 %; the full-band `spectral_flatness` of the repo reads 0.06-0.09 for every hat; `peak_db` at 9 kHz lowers the centroid; `pitch_scale` does not move centroid or HF share monotonically.
5. Listening plan: 7 items, 19 blind-named files from 14 unique renders, about 14 minutes, identical control pair, blind names, key file, German answer sheet (section 5).
6. Reference-hat measurement list in section 6; issue texts H0-H3 in section 7, **rescoped to what #229-#231 already merged** (DSP blocks, non-pitched analysis, category registry exist).

## 1. Method

Own scripts in my scratchpad `/tmp/claude-0/-home-claude/8969c227-1cdb-551a-898a-46125f9a8cff/scratchpad/hat/` (**not in the repo**; none uses the engine): `hatsim.py` (model and features), `run1.py`-`run4.py`, `post.py`, `post2.py`. NumPy 2.5.3, SciPy 1.18.1, `python3 <script>` from that folder. 48 kHz, mono, float64, no quantisation, no `drive`. Ranges = min..max over **seeds 1-8** of the same parameters.

Model (my reading of design note sections 2-4; the engine may differ):

- Bank: six band-limited squares (odd harmonics below 0.45 x sr, amplitude 1/k, start phase 0) at 205.3, 304.4, 369.6, 522.7, 540, 800 Hz x `pitch_scale`; `color` crossfades the low three and high three with cos/sin gains. Noise: white, `SeedSequence([seed, 1])`.
- Mix `sqrt(metal) * bank + sqrt(1-metal) * noise`, both RMS-normalised. **Two readings of "before the mixing":** *pre-HP* (normalise before the filter chain, the design note's text, used in the first table) and *post-HP* (normalise after the chain; section 3, P1). The tables say which one applies.
- Chain: high-pass = two cascaded RBJ sections (Q 0.7071), optional peaking (Q 1.0), RBJ low-pass; envelope = linear attack then exponential, -60 dB at `decay_ms` after the attack; length = decay + attack + 30 ms; 5 ms linear fade; DC removed; peak normalised. Optional two-band body: a band-pass at 3440 Hz (Q 0.7, **not** high-passed in my reading) with the full decay mixed with the high-passed path at `decay_hi_ratio` x decay.
- Features (definitions as in `analyse_nonpitched`, #230): centroid and HF share (> 8 kHz) from one FFT of the whole file; `t60` = first time the 1 ms RMS envelope is 60 dB under its peak; `rise` = 10 %-90 % of the peak envelope. Extra (mine, not in the sidecar): `lf_leak_db` = energy below `hp_hz`/2 over total energy (my refinement: the design note's "below `hp_hz`" includes the corner skirt itself and would read about -10 dB); `peak_count` = spectral peaks >= 15 dB above a +-500 Hz running median, 4-20 kHz, first 100 ms, Hann, zero-padded to 16384, peaks >= 50 Hz apart; flatness = geometric/arithmetic mean of a Welch spectrum (512 samples, 50 % overlap); `early_late` = centroid of 0-20 ms over centroid of 60-100 % of t60.
- **Cross-check:** `analysis.analyse_nonpitched` from the worktree applied to the model output (`run4.py`): centroid, HF share, t60 and rise matched my values to the printed precision for closed tight, closed std and open long, seeds 1-8. This checks my feature code, not the model's recipe.

## 2. Target ranges (hypotheses, source: model above)

Fields not listed: `attack_ms` 0.8, `metal` 0.6, `pitch_scale` 1.0, `color` 0.5, `lp_hz` 18000, `peak_db` 0, `body_mix` 0, `drive` 0. All inside the design note's proposed ranges. Pre-HP = design-note reading; post-HP = recommended reading (section 3, P1). Values are min..max over seeds 1-8.

| | **Closed tight** | **Closed std** | **Closed loose** | **Open short** | **Open long** |
| --- | --- | --- | --- | --- | --- |
| `decay_ms` | 35 | 70 | 120 | 250 | 500 |
| `hp_hz` | 7000 | 6000 | 5000 | 6000 | 5500 |
| **`t60_ms` (first crossing)** | 32.5-35.9 | 65.2-69.9 | 109.9-117.9 | 228.7-241.9 | 456-474 |
| `lf_leak_db` pre-HP | -38.6..-35.9 | -40.3..-34.4 | -38.8..-35.5 | -38.7..-36.5 | -37.3..-35.6 |
| `lf_leak_db` post-HP | -32.8..-30.2 | -30.6..-28.8 | -30.3..-29.4 | -30.8..-30.0 | -28.3..-27.8 |
| `spectral_centroid_hz` pre-HP | 12621-13918 | 12156-13089 | 11617-12426 | 12334-12933 | 12071-12494 |
| `spectral_centroid_hz` post-HP | 11700-12600 | 10882-11525 | 10100-10700 | 11000-11400 | 10700-10900 |
| `hf_share_8k` pre-HP | 0.909-0.951 | 0.847-0.905 | 0.778-0.843 | 0.856-0.886 | 0.828-0.849 |
| `hf_share_8k` post-HP | 0.836-0.881 | 0.727-0.779 | 0.626-0.685 | 0.739-0.771 | 0.702-0.717 |
| `peak_count` pre-HP | 0 | 0 | 0 | 0 | 0 |
| `peak_count` post-HP | 0-2 | 7-11 | 9-13 | 15-25 | 15-24 |
| Welch flatness 4-20 kHz post-HP | 0.48-0.60 | 0.57-0.66 | 0.62-0.70 | 0.65-0.70 | 0.69-0.73 |
| `rise_ms` (1 ms window) | 0.7-2.1 | 0.8-2.5 | 0.9-3.3 | 0.9-4.5 | 0.9-4.5 |

Reading the table (hypotheses):

- **Closed versus open is the decay.** The model puts closed at `t60` 33-118 ms and open at 229-474 ms; there is no gap between 118 and 229 in these presets, so the closed/open boundary (design note: closed below about 150 ms, open from 120 ms) is a listening question, not a measured one. Proposal for starters: closed 25-120 ms, open 200-600 ms.
- `t60` is the decay field by construction (the model is built so); the information is the **measurement bias** (P3), not the value.
- Brightness lives in `hp_hz`, `lp_hz`, `peak_hz`/`peak_db` and `metal`; all hats here have 63-95 % of their energy above 8 kHz and a centroid of 10-14 kHz because the band up to Nyquist is nearly flat noise. The centroid is therefore mostly set by `lp_hz`/Nyquist: with `lp_hz` 10000, 14000, 18000, 22000 the pre-HP centroid is 9.2-9.6, 10.7-11.1, 12.2-13.1, 14.1-15.2 kHz. A reference hat measured at 44.1 kHz or from a lossy source will have a different upper edge; compare only with the band stated (section 6).
- Seed spread (variants): closed std centroid +-3.7 %, HF share +-3 % (pre-HP). A variant box wider than that is a design choice (H12).

Single-field sweeps, closed std, pre-HP, seeds 1-8 (`run2.py`):

| Field moved | Values | `hf_share_8k` | centroid kHz | `lf_leak_db` |
| --- | --- | --- | --- | --- |
| `hp_hz` | 3000 / 4500 / 6000 / 8000 / 10000 / 12000 | 0.62-0.74 / 0.74-0.83 / 0.85-0.91 / 0.95-0.97 / 0.986-0.992 / 0.997-0.998 | 10.2-11.0 / 11.2-12.1 / 12.2-13.1 / 13.3-14.2 / 14.3-15.2 / 15.3-16.0 | -43..-34 (all) |
| `lp_hz` | 10000 / 14000 / 18000 / 22000 | 0.62-0.75 / 0.78-0.86 / 0.85-0.91 / 0.89-0.93 | 9.2-9.6 / 10.7-11.1 / 12.2-13.1 / 14.1-15.2 | not a target |
| `peak_db` at 9 kHz | -6 / 0 / +3 / +6 / +9 | 0.88-0.93 / 0.85-0.91 / 0.83-0.90 / 0.82-0.89 / 0.82-0.89 | 13.4-14.5 / 12.2-13.1 / 11.6-12.3 / 11.0-11.7 / 10.6-11.1 | not a target |
| `peak_db` +6 at **14 kHz** | 0 / +6 | 0.85-0.91 / 0.92-0.95 | 12.2-13.1 / 12.7-13.5 | not a target |

`hf_share_8k` saturates: from `hp_hz` 8000 up it is above 0.95 and differences are in the third decimal (P6).

## 3. Pitfalls found by the model

- **P1 `metal` normalisation (the main one).** Pre-HP normalisation: correlation of the render with the pure-bank render (same other fields) is 0.06-0.18 at `metal` 0.3, 0.18-0.29 at 0.6, 0.32-0.42 at 0.8, 0.47-0.55 at 0.9 (decay 70; sqrt(`metal`) would be 0.55, 0.77, 0.89, 0.95). Cause: a 1/k square spectrum keeps about 1.4 % (205 Hz) to 5 % (800 Hz) of its power above 6 kHz (hand calculation: sum of 1/k^2 over odd k above 6000/f over the total pi^2/8); the high-pass then removes the rest. Post-HP normalisation: corr 0.50-0.58 / 0.75-0.79 / 0.88-0.90 / 0.94-0.95, `peak_count` 0-3 / 7-11 / 19-25 / 34-40 / 79 (0.3 / 0.6 / 0.8 / 0.9 / 1.0), Welch flatness 8-16 kHz 0.74-0.83 / 0.70-0.78 / 0.63-0.69 / 0.59-0.64 / 0.52, HF share and centroid fall monotonically (0.793-0.856 to 0.655 for HF). Consequence: the contract text for `metal` must say where the power is measured. Cause established by two renders (pre/post) and the hand calculation; whether the user hears the difference is open.
- **P2 Features that do not separate `metal` pre-HP.** Flatness (4-20 kHz and 8-16 kHz), `peak_count` and the peakiness (p99 - p50 of the dB spectrum: 9.3-11.4 dB for `metal` 0-0.9, 13.4-14.6 at 0.97, 29 at 1.0) only react from about 0.9 up. Also, band choice matters: white noise gives Welch flatness 0.94-1.00 over 4-20 kHz in an unfiltered file, but the filter skirts (high-pass at 6 kHz, low-pass at 18 kHz) pull the same band of a hat down to 0.48-0.73. Use a band inside the passband (about 1.5 x `hp_hz` to 0.8 x `lp_hz`).
- **P3 `t60` first-crossing bias.** Nominal `decay_ms` 35 / 70 / 120 / 250 / 500 gave 32.3-36.3 / 65.2-69.9 / 109.9-117.8 / 228.7-241.9 / 455.9-474.2 ms with the first-crossing rule (1 ms RMS, same as `analyse_nonpitched`), i.e. up to 9 % low for long hats. A line fit of the 4 ms RMS envelope between -10 and -40 dB extrapolated to -60 dB gave 34.6-37.1 / 69.4-72.1 / 114.9-122.1 / 251.1-257.1 / 492.9-509.8 ms. The cause is not proven; the noisy envelope peak sits above the true peak (hypothesis). Engine tests need a tolerance of about 10 % for first-crossing, or the fit.
- **P4 `rise_ms` is not seed-stable for short attacks.** With the 1 ms window: attack 0.8 ms gives 0.8-2.5 ms, attack 3 gives 1.9-3.9 ms; with 0.25 ms window: 0.1 ms attack gives 0.10-1.88 ms. Only attack 10 ms (6.4-8.5) and 25 ms (18.6-21.2) are stable. Same family as clap P1. An alternative reference (peak of a 2 ms envelope, times on a 0.25 ms envelope, first 15 ms) gave 0.00-0.88 / 0.40-1.00 / 1.46-2.54 / 5.33-7.21 ms for attack 0.1 / 0.8 / 3 / 10: tighter, still not exact. Do not use `rise_time_ms` as a hat target; use the field.
- **P5 Repo `spectral_flatness` is full-band.** On the model output it reads 0.056-0.087 for closed tight, closed std and open long (all bins, including the empty bins below the high-pass). It cannot show `metal`; a band-limited Welch version is needed (issue H2).
- **P6 Saturating and sign-flipping features.** `hf_share_8k` > 0.95 from `hp_hz` 8000 up. `peak_db` +6 at 9 kHz **lowers** centroid and HF share (the boost pulls energy toward 9 kHz from a 12 kHz centroid); at 14 kHz it raises both. So the design note's "centroid up with `peak_db`" holds only when `peak_hz` is above the centroid.
- **P7 `pitch_scale` is not seen by centroid or HF share.** Pre-HP, `metal` < 1: centroid 12.3-13.1 / 12.2-13.1 / 12.1-12.9 kHz for 0.5 / 1.0 / 2.0 (no trend). Post-HP, `metal` 0.8: centroid 10.4-11.2 kHz over 0.5-2.0, HF share 0.73-0.77, 0.70-0.75, 0.69-0.72, 0.78-0.80, 0.71-0.76 for 0.5, 0.75, 1.0, 1.5, 2.0 (not monotone). `peak_count` also depends on `pitch_scale` non-monotonically (pre-HP, `metal` 1: 17, 71, 79, 64, 52). The line positions are the identity of the bank; check them against the known set (H8).
- **P8 `peak_count` depends on decay.** Post-HP `metal` 0.6: 7-11 at decay 70 but 15-25 at decay 250, because longer decay narrows the lines. Compare only at fixed decay.
- **P9 `lf_leak_db` depends on the high-pass order and on the bank.** Noise only, `hp_hz` 6000, energy below 3000 Hz over total: 1 section -28.3..-26.8 dB, 2 sections -43.3..-40.0, 3 sections -57.0..-46.9 (100 ms, `run3.py`). With a bank in the mix (post-HP) the leak is -28..-33 dB, because the harmonic skirts of the low squares pass through. The `body_mix` path in my reading is not high-passed: `lf_leak_db` -6 dB at `body_mix` 0.4, so the engine must say whether the body path is high-passed.
- **P10 `early_late` is about 1 without a split** (0.95-1.07, noise-like, nothing to separate), 2.0-2.1 / 2.5-2.6 at `decay_hi_ratio` 0.2 / 0.5 (`body_mix` 0.4, decay 400), 1.0 at ratio 1.0, and 1.04-1.17 at `body_mix` 0.8. The ratio is not monotone in `decay_hi_ratio` (0.2 lower than 0.5), because at ratio 0.2 the high group is mostly gone inside the 20 ms early window of a short-lived tail (explanation not proven).
- **P11 Choke is trivially measurable.** Hard cut: RMS after `choke_ms` + 5 ms is -129..-152 dB below the peak (numerical floor). A test threshold of -60 dB catches an unapplied choke; the prefix before `choke_ms` should be bit-identical to the unchoked render (not run by me).

## 4. Hypotheses for the audio-engineer (test after the hat voice, issue H4)

All are hypotheses; "confirm"/"reject" refer to engine measurements, not to sound.

| # | Hypothesis | Measurement | Confirms / rejects |
| --- | --- | --- | --- |
| H1 | The section 2 boxes hold on the engine voice with the seed spread of the table | Render the five styles, seeds 1-8, `analyse_nonpitched` plus the H2 helpers | within 15 % of the model for t60, HF share and centroid: confirm; else replace the table with engine numbers |
| H2 | Normalising bank and noise **before** the high-pass leaves about 5 % bank power in the passband at `metal` 0.6; normalising **after** makes the correlation with the pure-bank render follow sqrt(`metal`) | Render `metal` 0.3 / 0.6 / 0.9 and 1.0 with the other fields equal, same seed; correlation coefficient of each against `metal` 1.0 | corr within +-0.05 of sqrt(`metal`): the contract text says "passband share"; corr below 0.5 at 0.6: the pre-HP reading stands and `metal` is a pre-filter share |
| H3 | `t60_ms` of the sidecar is within 10 % of `decay_ms` for first-crossing (and within 4 % for a line fit) over the whole `decay_ms` range | 20 log-spaced `decay_ms` from 10 to 900, seeds 1-8 | all within 10 %: use the first-crossing in the sidecar, tolerance 10 %; otherwise the model undershoot is a model artefact |
| H4 | `rise_time_ms` is not seed-stable for `attack_ms` below 3 ms (max/min over seeds above 2) and stable above 10 ms | `attack_ms` 0.1 / 0.8 / 3 / 10 / 25, 8 seeds | confirm: no rise-time test below 3 ms; the field itself is tested by the envelope (first samples) |
| H5 | `hp_hz` moves HF share and centroid up monotonically and `lf_leak_db` stays below a bound that depends on the order (about -40 dB with 2 sections on noise, about -30 dB with the bank in) | Sweep `hp_hz` 3000-12000, 8 seeds; `lf_leak_db` at `hp_hz`/2 | direction holds; bounds within +-4 dB of the model: write them as the test bounds |
| H6 | `lp_hz` raises centroid and HF share; `peak_db` raises them only when `peak_hz` is above the centroid and lowers them below it | Sweeps in section 2, plus `peak_hz` 14000 | the sign rule holds over 8 seeds |
| H7 | Flatness in a passband-inside band falls with `metal` only with post-HP normalisation | Welch 8-16 kHz, `metal` 0 / 0.3 / 0.6 / 0.9 / 1.0 | monotone fall with post-HP: confirm; flat until 0.9 with pre-HP: consistent with P1 |
| H8 | `pitch_scale` shifts the spectral lines by the ratio; centroid and HF share are not suitable to test it | Predicted line set (odd k x f_i x `pitch_scale`) written in the test; fraction of detected peaks within +-20 Hz of a predicted line, `metal` 1.0 and 0.9 (post-HP) | fraction above 0.9: the bank is correct; also verify the 0.45 x sr cap: no line above 21.6 kHz |
| H9 | `peak_count` rises with `metal` at fixed decay and `pitch_scale` (post-HP: 0 / 7-11 / 19-25 / 34-40 / 79) and with decay at fixed `metal` | `metal` sweep at decay 70 and 250 | monotone in both: usable as a seed-stable test; compare only at equal decay |
| H10 | `body_mix` > 0 with `decay_hi_ratio` below 0.6 gives `early_late` above 1.5; without a split it is within 0.9-1.1 | `body_mix` 0 / 0.4 and `decay_hi_ratio` 0.2 / 0.5 / 1.0 | confirm; also report `lf_leak_db` of the body path (high-passed or not) |
| H11 | `choke_ms` leaves the prefix bit-identical and the energy after `choke_ms` + 5 ms below -60 dB | `choke_ms` 5 / 20 / 80 / 150 / 500 | exact prefix equality and level below -60 dB: confirm |
| H12 | Variants of one preset stay inside the seed spread of its box (centroid +-4 %, HF share +-3 %, t60 +-10 %) unless the variant axes are meant to be wider | `variants` 4-8 per preset | spread larger: either bound the axes or state that the preset family is intended to be wide |
| H13 | A closed hat with `t60` up to 120 ms fits one 16th at 136 BPM (110.3 ms) with at most 6 dB lost before the cut | Level at 110 ms relative to peak for each closed preset | informs only the listening loop (section 5), not the engine |

Not testable on single files or without the engine: whether anything above sounds different. That is the listening test.

## 5. Listening-test plan (hat test, rendered by the audio-engineer after H5; decoded by the lead)

Same method as the clap test: identical control pair, blind names, A/B positions mixed by a fixed seed, German answer sheet, key file `Schluessel.md` opened after the test, "kein Unterschied" always allowed. The guide file belongs to the audio-engineer (`docs/setup/LISTENING_TEST_*.md`).

**Common setup.** 4 bars at 136 BPM, mono 48 kHz / 24-bit, `dense` kick on every beat, peak at most -0.3 dBFS, warp off, project tempo 136 BPM, no master effects. **Closed items (T0-T3, T6):** the hat on **every 16th step** (110.3 ms), equal level, each hit cut at the next step with a 3 ms cosine fade. **Open items (T4, T5):** the open hat on every **offbeat 8th**, each hit cut at the next offbeat (1 beat = 441.2 ms) with a 3 ms fade; no closed hat in these two. Presets use the section 2 values; `seed` 1. **Level match within each item by RMS over 0-30 ms of the hat alone for closed items, 0-100 ms for open items** (hypothesis: that window follows the attack and brightness, not the tail; the lead checks the louder file is scaled down and puts the gains in the key). The loop and the pattern are my choice (every step triggered is a documented dance-music pattern, design note F7; the exact pattern is not the user's).

| Item | Files (blind) | Single question answered | Changed vs. closed std (S) |
| --- | --- | --- | --- |
| **T0** control | A = B, identical bytes (S) | How often does a side get picked with no difference | none |
| **T1** closed length | A = closed tight (`decay_ms` 35, `hp_hz` 7000), B = closed loose (120, 5000) | Which fits the kick pattern; does the longer one smear | decay and `hp_hz` |
| **T2** brightness | three files: `hp_hz` 4500 / 6000 / 9000 (decay 70) | Which is too dark, too bright, right | `hp_hz` |
| **T3** metal | three files: `metal` 0 / 0.6 / 1.0 (post-HP normalisation, decay 70) | Rank "mein Hat"; is the best too rauschig, richtig, too blechern | `metal` |
| **T4** open length | three files: open short (250), open long (500), open long with `choke_ms` 220 | Which fits the kick; does the choked long one beat the free long one | decay, `choke_ms` |
| **T5** body split | A = open long (500), B = open long with `body_mix` 0.4 and `decay_hi_ratio` 0.5 | Does B have something A lacks | `body_mix`, `decay_hi_ratio` |
| **T6** variants | four seed variants of S (`variants` 4) | Which sound like the same hat, which falls out | `variants` |

Blind-named files the user loads: T0 2, T1 2, T2 3, T3 3, T4 3, T5 2, T6 4 = **19**. Unique renders: **14**. S (seed 1) is used five times under different blind names (T0 A and B, T2 `hp_hz` 6000, T3 `metal` 0.6, T6 v0), open long twice (T4 and T5-A); the other unique renders: closed tight, closed loose, `hp_hz` 4500, `hp_hz` 9000, `metal` 0, `metal` 1, open short, open long choked, open long split, variants v1-v3. Copies of one render may differ in bytes only by the per-item level-match gain; T0 A and B must be byte-identical. Time: pairs about 1 minute, three- and four-file items 2 minutes, set-up 2, one-minute break after T2: about 14 minutes. **Order:** T1 -> T0 -> T2 -> T5 -> T4 -> T3 -> T6 (likely audible difference first, control second, rankings last).

**Aufbau (einmal, 2 Minuten):** Alle `*.wav` des Pakets in eine Audiospur laden, Warp aus, Projekttempo 136 BPM, jede Datei als Loop. Gleiche Lautstärke an der Spur, nichts auf dem Master. Die Dateinamen sind anonym. Schluessel.md erst nach dem Test öffnen.

| # | Frage (eine pro Block) | Antwortmöglichkeiten |
| --- | --- | --- |
| T1 | **Welche Hi-Hat passt besser zu deinem Kick-Muster?** Wenn die kürzere etwas verliert: was (ein Wort)? | A / B / kein Unterschied · Wort |
| T0 | **Welche Hi-Hat sitzt besser?** | A / B / kein Unterschied |
| T2 | Drei Dateien (X, Y, Z). **Welche ist zu dunkel, welche zu hell, welche passt?** | z. B. X dunkel, Y passt, Z hell |
| T5 | **Hat eine der beiden etwas, das die andere nicht hat? Wenn ja, welche und was (ein Wort)?** | A / B / kein Unterschied · Wort |
| T4 | Drei Dateien. **Sortiere von „mein Open Hat" bis „am wenigsten mein Open Hat".** Danach: **Ist die beste zu lang, richtig oder zu kurz?** | Reihenfolge · zu lang / richtig / zu kurz |
| T3 | Drei Dateien. **Sortiere von „mein Hat" bis „am wenigsten mein Hat".** Danach: **Ist die beste zu rauschig, richtig oder zu blechern?** | Reihenfolge · zu rauschig / richtig / zu blechern |
| T6 | Vier Dateien. **Welche klingen für dich wie dieselbe Hi-Hat? Welche fällt raus (wenn eine rausfällt)?** | Liste |

**Auswertungsvorlage (user fills in, or the lead copies it into the hat listening issue):**

```
Test Hat, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Pegel gleich gelassen: ja / nein
T1: ___   Verlust (Wort): ____
T0: ___   (A=B identisch; war die Antwort „kein Unterschied"?  ja / nein)
T2: dunkel ___ ; hell ___ ; passt ___
T5: ___   Wort: ____
T4: Reihenfolge ___ > ___ > ___    beste: zu lang / richtig / zu kurz
T3: Reihenfolge ___ > ___ > ___    beste: zu rauschig / richtig / zu blechern
T6: gleiche Hi-Hat: ___ ; fällt raus: ___
Gesamt: Welche Datei des ganzen Tests ist „meine Hi-Hat"? ____ (oder „keine")
```

**How the lead reads the answers** (one listener, one session; decoded with the key):

| Answer | Reading | Next step |
| --- | --- | --- |
| T0 not "kein Unterschied" | The user picks a side without a difference | Weigh all pair answers against it; repeat the pair reversed before building on it |
| T1 loose preferred, or tight loses a word | Closed length matters to him | Two closed presets stay; the word names the property to measure (t60, low-mid, HF share) |
| T1 tight preferred, nothing lost | Short closed is the default; loose stays an option | None |
| T2 "passt" is not 6000 | `hp_hz` default shifts toward his pick | New preset value, not a contract change |
| T3 `metal` 0 is best and the 0.6 file is "kein Unterschied" to 0 | Consistent with H2 (pre-HP reading) or the band is not audible | Decide the `metal` definition by H2 plus this answer |
| T3 best = 1.0 or "zu rauschig" for 0 | The bank share matters to him | One preset with the neighbour value; range for `metal` stays |
| T3 best = 0.6 | Default stays | None |
| T4 choked long best | `choke_ms` has value for open hats | Keep the field; preset with `choke_ms` |
| T4 "zu lang" for the best | Open decay should be shorter | New open preset value inside the range |
| T5 B "hat mehr" with a word | The body split has value | Keep `body_mix`; the word names the property to measure |
| T5 "kein Unterschied" | No split needed in v0.1 | Consider removing `body_mix` and `decay_hi_ratio` from the first contract (lead decides) |
| T6 one variant falls out | Variant spread too wide for that preset | Audio-engineer bounds the spread (H12) |

## 6. What a reference-hat analysis must measure (when the user supplies hats)

Audio content only, never artist or track names as targets; the user's files stay out of the repo, only numbers and file names go in. Same method as the clap reference note: independent scripts in a scratchpad, not the engine, report min..max per cluster and name the exclusions.

1. **Per file:** sample rate, bit depth, channels, length, trailing silence or a bed (a loop, not a one-shot); peak, RMS, crest factor; the upper edge of the spectrum (frequency where the 99 % cumulative energy is reached) so that 44.1 kHz or lossy sources are compared on a stated band.
2. **Decay:** `t60` by the first-crossing rule **and** by the -10..-40 dB line fit (P3), t20/t40, whether the end is set by the file end or a fade, closed/open split by `t60` (hypothesis: boundary about 150 ms, to be read from the data), envelope shape (single exponential or two-stage: dB slope 0-20 ms versus 20 ms-t60).
3. **Attack:** time to peak and the 10-90 % rise with the 0.25 ms window and a 2 ms reference (P4), reported with the number of independent onsets; no seed claim possible on single files.
4. **Spectrum:** centroid and HF share above 8 kHz **and above 12 kHz** (P6), within a stated band; -6 dB low corner; `lf_leak_db` at corner/2 and the energy below 2 kHz (P9); spectral tilt in dB per octave between 6 and 16 kHz; a fitted RBJ high-pass (order 2 or 4) x peaking x low-pass to the 0-30 ms spectrum, as in the clap fit, flagged indicative.
5. **Tonal versus noise:** `peak_count` in 4-20 kHz at a stated decay (P8), peakiness (p99 - p50), Welch flatness in a band inside the passband (P2), and the fraction of peaks that sit on a set of lines of a bank (compare with the 808 ratios and with a free fit); correlation of early and late spectrum (does the tail keep the same lines).
6. **Two-band behaviour:** centroid of 0-20 ms over the last 40 % of `t60` (`early_late`); level of energy below 4 kHz in the late part.
7. **Stereo and sub:** `corr` and side/mid (mono is accepted, so this only flags files that would not fold), share below 150 Hz.
8. **Classes:** cluster by measured traits (decay, brightness, peak count), like S/L/B for claps; report which hat-params field each cluster would need and which cluster no field can reach (a contract-change candidate only with more than one file).

## 7. Issue texts H0-H3 (ready to open; rescoped to the merged scaffold)

Merged on `origin/main` (4472cb9): RBJ high/low/peaking, `square_bank`, `substreams` (`dsp.py`), `analyse_nonpitched` (`analysis.py`, #230), the category registry with per-category engine versions (`categories.py`, D-025) and the `place_sample` path with a folder per category (`layout.py`). The proposal's H1-H3 therefore shrink to gap closing. WIP per role is 1; order H0 -> H1, H2, H3 in sequence -> H4 (voice, with the acceptance criteria of proposal 3.4 plus hypotheses H1-H13 above).

### Issue H0 (label `contract-change`, owner audio-engineer)

**Title:** contract-change: `hat-params` v0.1 and category `hat` in sample-metadata

- **What:** `contracts/hat-params.schema.json` v0.1 (field list in `2026-11-02_hat-synthesis-design.md` section 4 without shaker/ride fields; mono; no `model` field in v0.1, noise hat is `metal` 0, the lead may ask for a one-value enum instead), `"hat"` added to the `category` enum of `sample-metadata.schema.json` (schema_version `0.2`, same non-pitched features), matching section in `docs/INTERFACES.md`, positive and negative instances in the contract tests. Contract text must fix: (1) where `metal` is measured: **share of passband power after the high-pass chain** (default proposal, evidence: hypothesis H2 of `2026-11-02_hat-targets-and-listening-plan.md`; if the audio-engineer's render shows corr below 0.5 at `metal` 0.6, the pre-filter reading is documented instead); (2) the harmonic rule of the square bank (all odd k below sr/2, as `square_bank` does today, or the 0.45 x sr cap of the kick click) and start phases 0; (3) `decay_ms` = time to -60 dB after the attack, `t60_ms` in the sidecar = first-crossing, tolerance 10 %; (4) cross-field rule `lp_hz` > 1.2 x `hp_hz`; (5) `choke_ms` = cut with a 5 ms fade, prefix unchanged; (6) whether the body path is high-passed.
- **Why:** the hat engine needs a reviewed contract first (D-004), and the `metal` definition decides whether the field is measurable over its range.
- **Scope boundary:** no engine code, no presets, no tool wiring (`generate_hat` is H7), no shaker/ride, no stereo.
- **Done when:** schema valid; positive and negative instances (out-of-range rejected, not clamped; cross-field rule); kick and clap sidecars and instances still validate; `tests/test_contracts.py` green; the 4 values of the closed/open boxes (section 2) validate; user merges.

### Issue H1 (owner audio-engineer)

**Title:** hat DSP blocks: gap check against `dsp.py`, steep high-pass and passband-normalised mix

- **What:** list which hat blocks exist (`rbj_highpass`, `rbj_lowpass`, `rbj_peaking`, `biquad_bandpass`, `square_bank`, `substreams`) and add only the missing ones: a cascaded high-pass helper (N sections, default 2 for "steep"), a mix helper `mix_passband(bank, noise, share)` that normalises **after** a given filter chain (per H0 text), a hat envelope (linear attack, exponential to -60 dB, 5 ms fade) if `kick.py` helpers do not fit; decision on the harmonic cap (H0 point 2).
- **Why:** the voice (H4) should only compose blocks that are tested against an independent reference (CLAUDE.md "keep the reference independent").
- **Scope boundary:** no voice, no params resolution, no presets; kick and clap bytes unchanged.
- **Done when:** each new block tested against an independent reference (magnitude response from the FFT of an impulse response; harmonic set by a direct sum; passband share by measuring the filtered parts); one fault injection per new block turns a test red (mutation results in the PR); kick and clap golden hashes unchanged; `ruff check . && pytest` green.

### Issue H2 (owner audio-engineer)

**Title:** hat analysis helpers: band flatness, `lf_leak_db`, `peak_count`, `early_late`, line-fit `t60`

- **What:** test and design-tool functions next to `analyse_nonpitched`, **not** sidecar fields (the `features` object keeps its four non-pitched values): Welch flatness in a band, `lf_leak_db` (energy below f/2 over total), `peak_count` (definition in section 1 of the hat targets note), `early_late_centroid_ratio`, `t60` by line fit (-10..-40 dB, 4 ms RMS), HF share above 12 kHz.
- **Why:** the repo's `spectral_flatness` reads 0.06-0.09 for every hat (P5), and the first-crossing `t60` undershoots long decays by up to 9 % (P3); hat parameters cannot be verified without band-limited features.
- **Scope boundary:** `analyse` and `analyse_nonpitched` output unchanged byte for byte; no contract change; no engine.
- **Done when:** known signals give known values written in the test (a sum of three sines at 5, 7, 9 kHz gives `peak_count` 3; white noise 1 s gives Welch flatness 0.99-1.00 in a band; a pure exponential of 100 ms gives the fit within 2 %; a signal with an energy-free band below f/2 gives `lf_leak_db` below -80); seeded random draws over the helper ranges; one fault injection per helper; short-signal handling (a 15 ms hat is shorter than a 2048 window) tested; `ruff check . && pytest` green.

### Issue H3 (owner audio-engineer; depends on H0)

**Title:** category plumbing for `hat`: contract list, library folder, CLI message

- **What:** `"hat"` in `CONTRACT_CATEGORIES` (the existing test compares with the schema file), `LibraryLayout` folder `Samples/Drums/Hats`, `--category hat` accepted by the CLI and refused with the `CategoryUnavailable` text until H4 registers the voice, tests for the three paths.
- **Why:** H4 (voice) then only adds `hat.py`, its params and presets.
- **Scope boundary:** nothing renders; no `Category` registry entry for `hat` (that is H4); no tool wiring.
- **Done when:** `place_sample("hat", ...)` raises `CategoryUnavailable` before any folder is created; layout tests for the new folder; kick and clap tests unchanged; `ruff check . && pytest` green.

## 8. Not done and limits

- No file rendered, nothing heard; the listening package is the audio-engineer's.
- Every number in sections 2-4 comes from my own model, 8 seeds, one decay and corner per cell; no engine, no reference hat, no measurement on the user's material. The pre-HP/post-HP reading and the body path are my interpretations of a design note that did not fix them.
- The sweep cells use one parameter at a time around closed std; interactions (for example `hp_hz` x `metal` x `pitch_scale`) were not run.
- The 4-20 kHz peak and flatness definitions are mine; thresholds (15 dB, 50 Hz, 500 Hz median window) are not tuned.
- The listening loop (every 16th, equal level, offbeat open) and the level-match windows (0-30 / 0-100 ms) are my choices; loudness and perceived loudness differ. The control pair is one trial.
- Open for the user: do you have a few hat files you like (audio only)? Without them section 2 stays a model and the first listening test sets the range.

## 9. Commands run

```
cd /tmp/claude-0/-home-claude/8969c227-1cdb-551a-898a-46125f9a8cff/scratchpad/hat
python3 run1.py     # style table, pre-HP, seeds 1-8
python3 run2.py     # t60 estimators, sweeps (metal, hp, lp, pitch, color, peak_db, attack, body, choke)
python3 run3.py     # peakiness, peak_hz 14000, HP order 1/2/3, alternative rise, short-hat length
python3 run4.py     # repo analyse_nonpitched / spectral_flatness on model output (needs worktree src on sys.path)
python3 post.py     # post-HP normalisation vs metal: peak_count, flatness, corr with pure bank
python3 post2.py    # style table and sweeps, post-HP
```

Inline snippets (no file): Welch flatness of white noise by duration (0.065 / 0.5 / 1 s: 0.94-0.96 / 0.99 / 1.00), flatness 8-16 kHz vs `metal`, correlation with the pure bank pre-HP. The scripts are not in the repo (scratchpad rule).
