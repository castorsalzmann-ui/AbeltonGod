# Clap reference analysis: 13 one-shots measured against H1-H11 (C3, input to #232)

_Date: 2026-11-02 · Role: sound-designer · Issue: #232 · Compares with PR #240 (`docs/research/2026-11-02_clap-targets-and-listening-plan.md`, branch `phase-06/232-clap-plan`) · Status: **measurements and hypotheses, not a result.** I did not hear any file; every number describes a signal. The audio files are the user's third-party samples and are **not** in the repo; only numbers and file names are. Reference audio is measurement input, never copied, never a target by name._

**For the user:** tell me if you want any of the 13 files excluded (for example the loop file or one you do not like after all). The cluster ranges below change with that; section 4 marks which numbers depend on which file.

## Short version

1. 13 files, all 44.1 kHz, 24-bit PCM, 11 stereo and 2 mono. 12 are one-shots (177-952 ms); `FO4_HDT_126_clap_tenet.wav` is a **3.81 s loop of four claps** (hits at about 0.50, 1.45, 2.40, 3.35 s) with a continuous bed near -30 dB between hits; I analysed only hit 1 (0.495-1.445 s) and treat its tail numbers as invalid.
2. Three clusters by measured traits (section 3): **S short, mid-band** (t60 142-192 ms, centroid 1486-2471 Hz), **L long, mid-band** (t60 257-361 ms or not reached, centroid 2220-2458 Hz), **B bright, broadband** (centroid 3060-3397 Hz and HF share 0.078-0.116, one outlier at 5379 Hz / 0.206). The loop is unclassified.
3. PR #240's model ranges are **partly outside the references**: the tight style's `t60` 80-105 ms is below every reference (lowest 142 ms); `bp_hz` 1500 for tight is above every fitted reference centre (11 usable fits, 643-1490 Hz; the closest is `vc_clap_petite` at 1490); the room-long style's `t60` 440-500 ms is not reached by any one-shot. The long style without room (295-330 ms) matches L.
4. Real claps support the P1 pitfall (peak is often not the first onset), H11 (no sub content), and a stable first-burst spacing of about 10-12 ms. They contradict the tight preset's short burst region. H3-H5, H7-H10 cannot be tested on single files.
5. Starter sets for S, L, B are in section 5 with the values my own NumPy model gives for them (not the engine, not the references).

## 1. Method

Own scripts in my scratchpad, not in the repo, none uses the engine: `/tmp/claude-0/-home-claude/8969c227-1cdb-551a-898a-46125f9a8cff/scratchpad/clapref.py` (features), `env.py` / `env2.py` (envelope checks), `fit.py` (band-pass fit), `bend.py` (burst-region length), `clapsim.py` (model of the v0.1 recipe from PR #240). NumPy 2.5.3, SciPy 1.18.1, run as `python3 -I <script> <dir>`. `scipy.io.wavfile` reads the files; stereo is mixed to mono for everything except the stereo columns.

| Quantity | Definition |
| --- | --- |
| peak / RMS | dBFS of the whole file (RMS of the mono mix) |
| envelope | 1 ms moving RMS for t20/t40/t60; 2 ms for burst peaks and burst region |
| bursts | peaks of the 2 ms envelope in the first 150 ms, prominence at least 6 dB, at least 4 ms apart, within 25 dB of the maximum; **count depends on the prominence threshold** (see P-note below) |
| peak ms | time of the maximum of the 2 ms envelope |
| t20 / t40 / t60 | time from the envelope maximum to first falling below -20 / -40 / -60 dB; `-` = not reached inside the file |
| burst region | last time (first 250 ms) at which the 2 ms envelope is still within -12 dB of its maximum; "b12" |
| centroid, HF share | Welch spectrum (Hann, 2048) of the 300 ms after the onset (first sample above 5 % of peak): centroid and share of power at 8 kHz and above; PR #240's model used one FFT of the whole file, so values differ a little by window |
| band fit | grid search over RBJ band-pass (500-8000 Hz, Q 0.5-12) times RBJ high-pass (Q 0.7071, 100-3000 Hz) fitted to the 0-120 ms Welch spectrum on a log axis 250-14000 Hz, level free; the result is **indicative only** (residual in dB shown; a second-order model cannot follow a narrow or tilted spectrum) |
| sub-150 Hz | share of Welch power below 150 Hz |
| stereo | `corr` = correlation of L and R over the file; `side` = 10 log10(side energy / mid energy), -200 = exactly mono |

Header check: every file is PCM format 1, 24 bit; chunks besides `fmt `/`data` exist in several files (JUNK, LIST, ID3, bext, iXML, minf, elm1) and were ignored.

## 2. Table per file

Length, peak/RMS and time structure (peak ms = time of the envelope maximum; b12 = burst-region length).

| File | ch | len ms | peak / RMS dBFS | bursts (6 dB) in 150 ms | first onsets, ms | peak ms | b12 ms | t20 / t40 / t60 ms | energy 0-30 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 059_AT_Fluid_Clap | 2 | 269 | -0.1 / -20.1 | 6 | 10.1, 20.2, 31.2, 37.7 | 4.0 | 79.0 | 7 / 127 / 167 | 0.60 |
| 91V_HED_clap_dance | 2 | 177 | -1.0 / -16.8 | 3 | 21.4, 33.1, 102.9 | 21.4 | 67.7 | 58 / 108 / 142 | 0.56 |
| FJAAK_clap_rave | 2 | 461 | -1.0 / -16.7 | 7 | 2.9, 10.2, 22.6, 38.3 | 10.2 | 90.1 | 10 / 304 / - | 0.42 |
| FO4_HDT_126_clap_tenet (hit 1 only) | 2 | 3810 (loop; hit 1 segment 950) | -1.1 / -26.4 (segment) | 3 | 25.4, 93.1, 119.3 | 3.6 | 32.2 | invalid (bed at -30 dB) | 0.65 |
| MARS_909_clap_warm_hi_mid | 1 | 402 | -1.0 / -18.2 | 8 | 11.4, 23.0, 31.7, 84.1 | 23.0 | 63.5 | 9 / 124 / 284 | 0.50 |
| MARS_909_clap_warm_mid | 1 | 366 | -1.0 / -18.2 | 8 | 12.3, 23.6, 39.4, 101.3 | 23.6 | 63.0 | 41 / 130 / 257 | 0.53 |
| MARS_ACID_Clap_01 | 2 | 952 | -0.5 / -18.6 | 6 | 3.1, 10.8, 22.2, 44.0 | 22.2 | 86.7 | 70 / 158 / 361 | 0.43 |
| STCR2_PMT_Clap_One_Shot_Freaky | 2 | 465 | -0.1 / -23.9 | 5 | 1.9, 11.2, 21.2, 31.3 | 1.9 | 53.2 | 58 / 117 / 316 | 0.67 |
| ULTRA_oberheim_dx_clap_02_v2 | 2 | 217 | -1.0 / -15.3 | 7 | 3.9, 18.6, 30.7, 43.9 | 30.7 | 84.5 | 67 / 142 / 142 | 0.46 |
| ZEN_RUPT_clap_distorted | 2 | 750 | -1.0 / -13.8 | 0 (flat) | - | 4.7 | 250 | 254 / 299 / 340 | 0.18 |
| dmt_clap_one_shot_synthetic_high_brushy_figure | 2 | 248 | -1.0 / -21.8 | 0 | - | 4.4 | 29.5 | 57 / 163 / 244 | 0.89 |
| dtdk_drum_kit9_clap | 2 | 489 | -0.1 / -28.4 | 4 | 2.7, 8.0, 23.9, 36.0 | 2.7 | 9.2 | 7 / 49 / 149 | 0.97 |
| vc_clap_petite | 2 | 500 | -0.0 / -19.4 | 3 | 27.2, 36.6, 46.8 | 0.1 | 39.9 | 43 / 52 / 192 | 0.84 |

Spectrum, band fit and stereo.

| File | centroid Hz | HF share (>= 8 kHz) | sub-150 Hz share | fit bp Hz / Q / hp Hz (residual dB) | -6 dB low corner Hz | 85 % rolloff Hz | corr / side dB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 059_AT_Fluid_Clap | 2471 | 0.045 | 0.0000 | 1158 / 1.0 / 365 (2.8) | 581 | 4673 | 0.47 / -4.4 |
| 91V_HED_clap_dance | 3397 | 0.094 | 0.0000 | 643 / 0.5 / 1135 (2.0) | 861 | 6417 | 0.88 / -12.0 |
| FJAAK_clap_rave | 2458 | 0.021 | 0.0027 | 1370 / 1.4 / 430 (2.4) | 711 | 4091 | 0.997 / -28.4 |
| FO4 tenet (hit 1) | 2079 | 0.000 | 0.0001 | poor fit (7.6) | 1421 | 2713 | 0.04 / -0.4 |
| MARS_909_clap_warm_hi_mid | 2220 | 0.030 | 0.0003 | 1065 / 1.0 / 594 (2.5) | 646 | 3747 | mono |
| MARS_909_clap_warm_mid | 2442 | 0.040 | 0.0007 | 1158 / 1.0 / 430 (2.2) | 668 | 3854 | mono |
| MARS_ACID_Clap_01 | 2271 | 0.024 | 0.0002 | 1370 / 1.4 / 225 (1.9) | 840 | 3704 | 0.999 / -32.8 |
| STCR2_PMT_Clap_One_Shot_Freaky | 3060 | 0.078 | 0.0001 | 700 / 1.4 / 1335 (2.2) | 689 | 5405 | 0.86 / -11.3 |
| ULTRA_oberheim_dx_clap_02_v2 | 1931 | 0.002 | 0.0019 | 1260 / 3.0 / 100 (4.8) | 797 | 2735 | 1.000 / exactly mono |
| ZEN_RUPT_clap_distorted | 3084 | 0.116 | 0.0000 | 1370 / 0.7 / 225 (2.7) | 689 | 6826 | 0.81 / -9.7 |
| dmt_clap_one_shot_synthetic_high_brushy_figure | 5379 | 0.206 | 0.0083 | poor fit (4.2); Welch peak 5233 Hz, -3 dB band 4974-5448 | 4737 | 9152 | 0.91 / -13.2 |
| dtdk_drum_kit9_clap | 1486 | 0.004 | 0.0053 | 761 / 2.0 / 264 (4.1); Welch peak 1873 Hz | 474 | 1960 | 1.000 / exactly mono |
| vc_clap_petite | 2210 | 0.023 | 0.0005 | 1490 / 2.0 / 100 (3.2) | 1292 | 2756 | 1.000 / -52.5 |

Notes on the tables.

- **Burst counts are not stable.** The same file gives different counts with prominence 4 / 6 / 8 dB (`059_AT_Fluid_Clap` 9 / 6 / 4, `MARS_909_clap_warm_hi_mid` 11 / 8 / 6, `FJAAK_clap_rave` 12 / 7 / 5). Treat the count column as 3-8 with no better resolution. The first three or four onsets are stable: `STCR2_PMT` 1.9 / 11.2 / 21.2 / 31.3, `059_AT_Fluid` 10.1 / 20.2 / 31.2, `MARS_909_hi_mid` 11.4 / 23.0 / 31.7, `FJAAK` 2.9 / 10.2 / 22.6 / 38.3, `MARS_ACID` 3.1 / 10.8 / 22.2 / 44.0: gaps of about 8-12 ms.
- **`ZEN_RUPT` has no bursts to count**: its 2 ms envelope stays within 4 dB of the peak for about 250 ms and then falls from -8 dB at 250 ms to -37 dB at 340 ms and to the noise floor at 400 ms (the file is 750 ms long, silent after about 400 ms). That is a flat-topped, gated shape, not an exponential tail. Its crest factor (peak minus RMS) is 12.8 dB, the lowest of the set.
- **`dmt_clap_..._high_brushy_figure`**: narrow spectral peak near 5.2 kHz (Welch -3 dB band 4974-5448 Hz), energy in the first 30 ms 0.89, burst region 29.5 ms. The band fit is poor and its centre (1763 Hz) is not meaningful.
- **Fitted high-pass 100 Hz** (ULTRA, vc, tenet) is the lower edge of my search grid, so it only means "at or below 100 Hz"; the `-6 dB low corner` column is the more honest low-end number (474-861 Hz for all except dmt and tenet).
- **Several t60 values may be set by the file end or a fade**, not by a natural decay: `91V_HED` (t60 142, effective length 173 of 177 ms), `dmt` (244 vs 245 of 248 ms), `FJAAK` (never reaches -60 dB inside 461 ms; t40 is 304 ms; level is -31 dB at both 200 and 300 ms, a flat bed, cause not established).
- Crest factor, peak minus RMS (dB), from the tables: fluid 20.0, 91V 15.8, FJAAK 15.7, 909 hi-mid 17.2, 909 mid 17.2, ACID 18.1, STCR2 23.8, ULTRA 14.3, ZEN 12.8, dmt 20.8, dtdk 28.3, vc 19.4.

## 3. Clusters (by measured traits, not by taste)

Axes: decay (`t60`) and brightness (centroid, HF share). Thresholds chosen after looking at the table: t60 above/below about 230 ms, centroid above/below about 2700 Hz.

| Cluster | Files | t60 ms | centroid Hz | HF share | b12 ms | other measured traits |
| --- | --- | --- | --- | --- | --- | --- |
| **S: short, mid-band** (4) | 059_AT_Fluid, ULTRA_oberheim_dx, dtdk_drum_kit9, vc_clap_petite | 142-192 | 1486-2471 | 0.002-0.045 | 9-85 (spread: dtdk 9, vc 40, fluid 79, ULTRA 85) | 3 of 4 exactly or nearly mono; 3 of 4 have energy in the first 30 ms of 0.46-0.97; sub-150 Hz share up to 0.0053 |
| **L: long, mid-band** (4) | MARS_909_clap_warm_hi_mid, MARS_909_clap_warm_mid, MARS_ACID_Clap_01, FJAAK_clap_rave | 257-361, FJAAK not reached (t40 304) | 2220-2458 | 0.021-0.040 | 63-90 | all four mono-compatible (2 true mono, 2 with corr >= 0.997); fitted bp 1065-1370 Hz, Q 1.0-1.4, hp fit 225-594 |
| **B: bright, broadband** (4) | 91V_HED_clap_dance, STCR2_PMT_Clap_One_Shot_Freaky, ZEN_RUPT_clap_distorted, dmt_clap_..._high_brushy_figure | 142-340 | 3060-3397 (dmt 5379) | 0.078-0.116 (dmt 0.206) | 30-250 | all four with `corr` 0.81-0.91 (wider than the other clusters); `ZEN` has a gated plateau and the lowest crest factor; `dmt` is a narrow peak near 5.2 kHz |
| unclassified (1) | FO4_HDT_126_clap_tenet (loop) | invalid | 2079 (hit 1) | 0.000 | 32 | not a one-shot; `corr` 0.04 (decorrelated), a continuous bed near -30 dB |

Sub-group inside B: `91V` and `STCR2` (fitted bp 643 / 700 Hz with fitted hp 1135 / 1335 Hz, i.e. a low-centre band-pass with a high high-pass) form the core; `ZEN` and `dmt` are each one-off shapes. The ranges for B in section 4 rest on two files and are the least reliable.

## 4. Hypotheses H1-H11 against the references

"Supported / contradicted" means the measurement is consistent / inconsistent with the hypothesis; it says nothing about how a clap sounds.

| # | Hypothesis in PR #240 | Result on the 13 references |
| --- | --- | --- |
| H1 | Section 2 model ranges hold on the engine voice | **Cannot test** (no engine, no reference parameters). The model-versus-reference comparison, though, is informative: tight `t60` 80-105 ms vs S 142-192 (**contradicted**, nothing below 142 ms); tight centroid 2400-2800 and HF share 0.03-0.05 vs S 1486-2471 and 0.002-0.045 (model sits at or above the top of S); long dry `t60` 295-330 vs L 257-361 (**consistent**); long with room 440-500 (**no one-shot reaches it**); model burst region (b12) tight 30-43 ms vs refs 40-90 (below), long 98-128 vs refs 63-90 (above) |
| H2 | The user's taste range sits inside the contract ranges | **Mostly supported**, with five exceptions: (a) `dmt` has a narrow peak at about 5.2 kHz, above `bp_hz` max 4000 (my model reaches centroid 5795-6245 and HF share 0.21-0.27 at `bp_hz` 3000, Q 0.5, hp 1000, so broad brightness is reachable, a narrow 5 kHz line is not); (b) `ZEN` has a flat-topped, gated envelope; the contract's exponential tail cannot hold a plateau for 250 ms and then drop; (c) 5 of 13 files have `corr` below 0.9 (fluid 0.47, ZEN 0.81, STCR2 0.86, 91V 0.88, tenet 0.04) and the contract voice is mono; (d) `FO4 tenet` is a loop, not a one-shot; (e) 91V is 177 ms long, below `length_ms` min 200 (cosmetic: its effective length is 173 ms). Burst spacing 9-17 ms, `bp_hz` fit 643-1490, `bp_q` fit 0.5-3, `tail_decay` implied by t60 142-361 are all inside the ranges |
| H3 | `t60` monotone in `tail_decay_ms`, independent of `bp_hz` | **Cannot test** on single files (no parameter sweep). Note: two files show a two-stage decay (909 hi-mid and 909 mid: t40 124 / 130 ms but t60 284 / 257 ms), which one exponential tail plus bursts only approximates |
| H4 | `bp_hz` raises centroid/HF share, `bp_q` lowers them | **Cannot test** causally. Weak hint only: the brightest files (91V, STCR2) fit to a low `bp_hz` (643, 700) with a high-pass at 1135-1335, so brightness there comes from the high-pass/low-Q side, not from a high centre; in the model a low `bp_hz` with Q 0.5 and hp 800 does reach centroid 3.0-3.8 kHz (section 5) |
| H5 | Burst count changes the front, not the tail | **Cannot test.** Reference bursts are 3-8 by a noise-sensitive count (section 2 note); the stable fact is a first-onset spacing of 8-12 ms |
| H6 | `burst_decay_ms` above `burst_spacing_ms` makes bursts overlap and raises burst-region RMS | **Partly supported**: in 9 of 13 files the envelope stays within -12 dB of its peak for 40-90 ms, i.e. well past 3 x 10 ms of bursts, so each burst decays slower than the spacing (or levels fall off slowly). Exceptions: dtdk (9 ms), dmt (30 ms), the loop segment (32 ms), ZEN (250 ms, plateau) |
| H7 | `room` raises energy after 150 ms, not the first 30 ms | **Cannot test.** Energy after 150 ms is 0.3 % or less of the total in 10 of the 12 one-shots; exceptions `FJAAK` 2.5 % (flat bed at -31 dB, cause not established) and `ZEN` 29 % (plateau to 250 ms). Room versus long tail cannot be told apart from one file |
| H8 | `drive` raises HF share and centroid | **Cannot test** (no controlled pair). Consistent in direction: `ZEN_RUPT_clap_distorted` has HF share 0.116, centroid 3084 Hz and the lowest crest factor (12.8 dB); `ULTRA` also has a low crest factor (14.3 dB) but is dark (centroid 1931 Hz), so low crest alone does not imply bright |
| H9 | Layering has low comb risk | **Cannot test** on single files |
| H10 | Variants stay inside one style box | **Cannot test.** The two MARS_909 files (`warm_hi_mid`, `warm_mid`) are the nearest to a variant pair: centroid 2220 vs 2442, HF share 0.030 vs 0.040, t60 284 vs 257, b12 63.5 vs 63.0, fit bp 1065 vs 1158. Their spread (about 10 % in centroid, about 10 % in t60) is a datum for how far variants of one source can differ, not a test |
| H11 | Clap has no sub content under 150 Hz (share < 0.01 at hp 450) | **Supported for all 13**: sub-150 Hz share is at most 0.0083 (dmt), at most 0.0053 for the rest (dtdk), and below 0.003 for 11 of 13. This says nothing about level against the kick |
| P1 | `rise_time_ms` unusable for multi-burst noise claps | **Supported**: the envelope maximum falls at the first onset (within 5 ms) in 7 files (fluid 4.0, STCR2 1.9, dmt 4.4, dtdk 2.7, vc 0.1, ZEN 4.7, tenet hit 3.6) and at the second to fourth burst in 6 (FJAAK 10.2, 91V 21.4, ACID 22.2, 909 hi-mid 23.0, 909 mid 23.6, ULTRA 30.7). Onset-to-peak is 0-31 ms and says which burst is loudest, not how fast the clap starts |
| P2 | `t60_ms` can be `null` | **Supported**: `FJAAK` never reaches -60 dB inside 461 ms |
| P3 | Whole-file features hide time structure | **Supported**: energy in the first 30 ms ranges from 0.18 (ZEN) to 0.97 (dtdk); in 4 of 13 files (FJAAK 0.42, ACID 0.43, ULTRA 0.46, ZEN 0.18) more than half of the energy comes after 30 ms, while the centroid of the whole file is one number |

## 5. Revised ranges and starter parameter sets (hypotheses)

### 5.1 Revised target ranges

Min..max over the cluster's files; n is 4 per cluster (B rests on 2 core files). These replace the model-only ranges of PR #240 section 2 for the features measured here. Everything is a hypothesis until the engine voice is measured (H1).

| Quantity | S short mid-band | L long mid-band | B bright | PR #240 tight / long (model) |
| --- | --- | --- | --- | --- |
| `t60_ms` | 142-192 | 257-361 (or not reached in 461 ms) | 142-340 | 80-105 / 295-330 dry, 440-500 with room |
| `spectral_centroid_hz` | 1486-2471 | 2220-2458 | 3060-3397 (+ dmt 5379) | 2400-2800 / 2300-2600 |
| `hf_share_8k` | 0.002-0.045 | 0.021-0.040 | 0.078-0.116 (+ dmt 0.206) | 0.03-0.05 / 0.03-0.045 |
| burst region b12 (ms) | 9-85 (typical 40-85) | 63-90 | 30-250 (gated outlier) | 30-43 / 98-128 (model) |
| first-onset spacing (ms) | 8-12 | 8-14 | 10-12 | 8 / 12 |
| fitted `bp_hz` | 760-1490 | 1065-1370 | 643-700 (core) | 1500 / 1300 |
| fitted `bp_q` | 1-3 | 1.0-1.4 | 0.5-1.4 | 1.6 / 1.2 |
| fitted `hp_hz` / -6 dB low corner | 100(grid edge)-365 / 474-797 | 225-594 / 646-840 | 225-1335 / 689-861 | 600 / 450 |
| sub-150 Hz share | <= 0.0053 | <= 0.0027 | <= 0.0083 | not stated |
| stereo | 3 of 4 mono-compatible | 4 of 4 mono-compatible | `corr` 0.81-0.91 | mono voice |

Concrete changes proposed to PR #240 (all inside the v0.1 ranges, so no contract change):

1. Tight preset: `tail_decay_ms` 90 up to about 150 and `burst_spacing_ms` 8 up to 10; `bp_hz` 1500 down to about 1200; `hp_hz` 600 down to about 350. Reason: S's `t60` is 142-192, the spacing 8-12 ms, fitted `bp_hz` 760-1490.
2. Long preset: drop `room` as the way to reach length; use `tail_decay_ms` about 380 dry (model `t60` 310-355 ms) because no reference one-shot reaches 440 ms; keep `room` as an option, not a style default (no reference identifies room).
3. Burst decay and falloff: `burst_decay_ms` 12 with falloff 0.8 gives a burst region (b12) of 30-43 ms in the model, below nine of the references (40-90 ms). Test `burst_decay_ms` about 25 with `burst_level_falloff` about 0.9 (starter sets below).
4. `rise_time_ms`: do not use as a clap target (P1 confirmed on real claps); `t20` is not a stable target either (7-70 ms depends on which burst peaks); the useful time quantities are `t40`/`t60` and the burst-region length b12.
5. A style box for "bright" needs `bp_q` near 0.5 with a high-pass near 800 Hz rather than a high `bp_hz`.

### 5.2 Starter sets (clap-params v0.1 field values)

Fields not listed keep the contract defaults (`variants` 1, `sample_rate` 48000, `bit_depth` 24, `drive` 0, `room` 0, `polarity` 1, `offset_ms` 0, `peak_ceiling_dbfs` -0.3). `seed` is free. "Model" = my NumPy model of the v0.1 recipe over seeds 1-8 (not the engine, not the references; min..max). The columns after it are the cluster range from 5.1 for comparison.

| Field | **S short mid-band** | **L long mid-band** | **B bright** |
| --- | --- | --- | --- |
| `bursts` | 4 | 4 | 4 |
| `burst_spacing_ms` | 10 | 11 | 10 |
| `burst_decay_ms` | 25 | 25 | 25 |
| `burst_level_falloff` | 0.9 | 0.9 | 0.9 |
| `tail_level` | 0.4 | 0.7 | 0.5 |
| `tail_decay_ms` | 150 | 380 | 200 |
| `bp_hz` | 1200 | 1250 | 1100 (between the two measured runs, see below) |
| `bp_q` | 1.4 | 1.2 | 0.5 |
| `hp_hz` | 350 | 450 | 800 |
| `length_ms` | 250 | 700 | 450 |
| Model `spectral_centroid_hz` | 2015-2287 | 2274-2399 | about 3000-3770 (see below) |
| Model `hf_share_8k` | 0.024-0.036 | 0.030-0.037 | about 0.06-0.10 |
| Model `t60_ms` | 132-166 | 310-355 | 189-214 |
| Model b12 (ms) | 49-62 | 98-138 | 51-75 |
| Reference cluster | centroid 1486-2471, HF 0.002-0.045, t60 142-192, b12 40-85 | centroid 2220-2458, HF 0.021-0.040, t60 257-361, b12 63-90 | centroid 3060-3397, HF 0.078-0.116, t60 142-340 |

Where the model misses the references:

- **S**: model `t60` lower bound 132 is just under the S minimum 142; raise `tail_decay_ms` to about 170 if the engine confirms the same. Model b12 49-62 is inside the reference spread.
- **L**: model b12 98-138 is longer than the references (63-90) because `tail_level` 0.7 keeps the tail within 12 dB for longer; lower `tail_level` to about 0.55 is a candidate, not measured.
- **B**: measured model runs, tail 0.5 / 200 ms / 450 ms, `bp_q` 0.5 or 0.6, 8 seeds: `bp_hz` 1000, Q 0.6, hp 800: centroid 2966-3267, HF 0.061-0.077; `bp_hz` 800, Q 0.5, hp 800: centroid 2945-3238, HF 0.061-0.076; `bp_hz` 1150, Q 0.5, hp 800: centroid 3459-3765, HF 0.082-0.102; `bp_hz` 1250, Q 0.5, hp 800: centroid 3606-3920, HF 0.087-0.110. The references have centroid 3060-3397 with HF share 0.078-0.116, a higher HF share at a given centroid than the model gives (the model's HF share and centroid rise together, the references' HF share is higher relative to centroid). I list `bp_hz` 1100 as a starter between the 1000 and 1150 runs; that exact setting was not run. Whether `drive` (0.2-0.3) closes the gap is untested (the model has no drive).
- `dmt`-type (narrow 5 kHz peak) and `ZEN`-type (gated plateau, wide, distorted) have no starter set; see 6.

Wide stereo (5 of 13 files) is not covered by any starter set: the v0.1 voice is mono.

## 6. What is still a hypothesis, and what would settle it

| Open point | What settles it |
| --- | --- |
| Starter sets reproduce cluster numbers on the engine voice | audio-engineer renders the three sets with seeds 1-8, runs the same four features plus b12 (H1) |
| Cluster boundaries (230 ms, 2700 Hz) are an artefact of 13 files | more reference claps from the user; the user states which of the 13 to exclude |
| Burst count and spacing | stable only for the first 3-4 onsets; a better count needs a different method (for example onset detection on a high-passed band), not done |
| Whether the user's own taste sits in S, L or B | the listening test in PR #240 section 5 (C1, C3), with the S/L/B starters replacing the model presets; I did not hear any reference |
| Gated plateau (`ZEN`), narrow 5 kHz peak (`dmt`), stereo width | these three would need contract fields (tail hold/gate, bp above 4000 or a second band, stereo); one file each is too thin for a `contract-change` proposal; they are candidates if the user confirms the sounds matter |
| Room versus long tail | no reference separates them; needs a controlled room/no-room pair (C4 in PR #240) |
| `FJAAK` flat bed at -31 dB | cause not established |
| Loop file | if the user wants its hits used, cut hit 1 and re-measure |

## 7. Commands run

```
python3 -I .../scratchpad/clapref.py .../scratchpad/claps_ref      # per-file features (tables in section 2)
python3 -I .../scratchpad/env.py     .../scratchpad/claps_ref      # envelope peaks at prominence 4 / 6 / 8 dB
python3 -I .../scratchpad/env2.py <file> 10                        # ZEN, loop, dtdk envelope shapes
python3 -I .../scratchpad/fit.py     .../scratchpad/claps_ref      # RBJ band-pass x high-pass fit
python3 -I .../scratchpad/bend.py    .../scratchpad/claps_ref      # b12 (and -6 dB) burst-region length
python3 -I -  (imports clapsim.py)                                  # starter-set checks, 8 seeds
```

`scratchpad` = `/tmp/claude-0/-home-claude/8969c227-1cdb-551a-898a-46125f9a8cff/scratchpad`. The scripts are not in the repo (scratchpad rule); the reference WAVs are not in the repo (third-party samples).
