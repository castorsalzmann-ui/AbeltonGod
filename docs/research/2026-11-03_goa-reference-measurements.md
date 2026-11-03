# Measurements: the user's three Goa reference tracks (tempo, sections, kick, bass, mid/lead, stereo, loudness) against the Goa voice plan

_Date: 2026-11-03 · Refs #338 · Role: sound-designer · Docs only: no code, no contract, no decision changed. Applies the intake proposal in section 6 of [the reference-tracks note](2026-11-03_goa-reference-tracks.md) (PR #388) and section 5 of [the synth-voice plan](2026-11-03_goa-synth-voice-plan.md), under D-026 point 3. **I cannot listen: every statement below is a measurement with its method and limit, an inference marked as such, or "not established". Nothing says how anything sounds.**_

Labels: **measured** = a number from a command I ran today (method named); **inferred** = my reasoning from measured numbers; **not established** = no measurement decides it; **PROPOSAL** = a replacement value for a plan window, for the lead and the user to accept or reject; nothing is applied.

Input: three user-uploaded files, read-only, outside the repo: `The_Infonaut_-_Cthugha.aiff` (7:19.7), `Lunar_Asylum_-_Twister.aiff` (8:48.8), `SETI_Project_-_Ephidrine.aiff` (7:16.8); 44.1 kHz, 16-bit PCM stereo AIFF with an embedded cover image. **No audio, excerpt, spectrogram image or note sequence is in this PR.** Converted copies exist only in the session scratchpad (outside the repo) and were used only for measurement. Names below are measurement sources only; no track is a target in code or contracts, nothing is resynthesised.

## For workers

1. **Tempo (measured, two independent methods agree to 0.01 BPM, grid stable): Cthugha 142.04, Twister 144.85, Ephidrine 150.00 BPM.** All three are above the plan's default of 140 and inside the 135-150 window; Ephidrine sits exactly on the upper edge. (Section 1.)
2. **Length: about 260 / 319 / 273 bars** (7:19.7 / 8:48.8 / 7:16.8). The 288-bar template is inside that range. Only **Twister has a kick-out breakdown (bars 186-219, 34 bars, 59-69 % of the track)**; Cthugha and Ephidrine keep the kick on every beat from kick-in to the outro (single-bar kick drops only). Two of three (Cthugha 24 bars, Twister 32 bars) have **no kick for the first 24-32 bars**; all three **end with a kick-less tail of 7-17 bars**. (Section 2.)
3. **Bass rhythm is not one pattern across the three.** Cthugha carries onsets on every 16th (all three off-kick steps present in 78 % of kick-bar beats). Twister and Ephidrine are dominated by the **off-beat 8th (+2 steps after the kick) at 65 % / 51 % of beats**, with weaker onsets at +1 and +3 (28-38 %). **A triplet gallop and the "steps 1 and 3" gallop were not found in any of the three** (control positions 3-5 %; mask `x.x` 1.9-5.9 %). The D-026 default (`three_after_kick`) is therefore supported by one track and not dominant in the other two. (Section 4.)
4. **Bass register and tonic candidates (measured f0 histogram; key stays a candidate):** Cthugha C2/C3 (65.4/130.8 Hz) with C#3 and E3; Twister C2 (about 47-59 % of notes) plus lower neighbours, weak; Ephidrine E1/E2 (41.2/82.4 Hz) with F (a semitone above) in about 15 %. A raised-second-degree (b2) pitch is present in the bass of two tracks (Cthugha, Ephidrine). (Section 4.5.)
5. **Cutoff-sweep-like rises of the 500 Hz-10 kHz centroid last 4-16 bars** in all three tracks; lead/acid-line quantities (filter decay, resonance, accent, slide, unison) are **not measurable from these stereo mixes** (section 5, section 8).
6. **Stereo: Cthugha is near-mono** (side/mid -39.5 dB, L/R correlation 1.000); Twister and Ephidrine are stereo above about 250 Hz (correlation 0.38-0.73 between 500 Hz and 4 kHz) and near-mono below it (correlation >= 0.93 below 250 Hz). **Loudness: -11.2 / -11.5 / -7.2 LUFS integrated**, true peak -2.4 / +0.4 / +0.9 dBTP (label masters, section 6).
7. **Plan windows (section 7):** the evidence changes few of them, because most Class B quantities are inside voices that a stereo mix hides. Proposed replacements are marked PROPOSAL; the rule "a window changes only where >= 2 tracks agree" is applied row by row.
8. **Effort:** none for the repo; the lead decides which PROPOSAL values go to the plan and to `goa_patterns` presets. Three questions for the user are in section 9.

## Method and tools

- Conversion: `ffmpeg -i <in>.aiff -vn -map 0:a:0 -c:a pcm_s16le <scratchpad>/audio/<name>.wav` (lossless, drops the cover image). Python 3 with numpy 2.5.3 and scipy 1.18.1; **no new repo dependency; librosa was not installed or used.** Scripts are in the session scratchpad (`.../scratchpad/code/`), not in the repo; the exact parameters are given per section so another agent can re-implement them.
- Loudness: `ffmpeg -nostats -i <wav> -af ebur128=peak=true -f null -` (EBU R128: integrated, LRA, true peak).
- Mono mix = (L+R)/2 unless a section says otherwise. Mid/side: M = (L+R)/2, S = (L-R)/2.
- Bar numbering: the beat grid starts at the first full beat after the file start (first beat at 0.383 s / 0.001 s / 0.053 s). **The grouping of beats into bars is an assumption** (4 beats per bar, bar phase taken from the first kick-in: beat index mod 4 = 0 / 1 / 0). A different phase shifts every bar number by less than one bar and changes no length.
- Kick-bar: a bar with a low-band kick hump (30-120 Hz) within 8 dB of the track's 90th-percentile kick level on all 4 beats; 222 / 222 / 240 bars in the three tracks.
- **The data are label digital masters of 1990s material** (documented in the reference-tracks note); what is measured is the master, not the original mix.

## 1. Tempo and tempo stability

Two independent methods (full-band onset autocorrelation; kick-band envelope), plus a grid-fold refinement.

| Quantity (method) | Cthugha | Twister | Ephidrine |
| --- | --- | --- | --- |
| M1 onset-flux autocorrelation, lag of 1 beat (STFT 2048 / hop 256, mono, log-magnitude flux; peak searched 100-180 BPM, parabolic) | 142.009 (r 0.91) | 144.893 (r 0.87) | 149.968 (r 0.88) |
| M1 same, lag of 16 beats (4 bars) | 142.042 (r 0.89) | 144.845 (r 0.86) | 149.999 (r 0.88) |
| M1 grid fold refinement (period scanned +-0.4 %, peak sharpness) | 142.0414 | 144.8500 | 149.9985 |
| M2 kick-band (30-120 Hz) level autocorrelation, 16-beat lag (10 ms envelope, 1 s trend removed) | 142.036 (r 0.91) | **fails** (r 0.09, 143.57) | 150.000 (r 0.89) |
| M2 kick-time regression (per-beat energy centroid time of the 30-120 Hz envelope vs beat index; strong beats only) | 142.040 (893 beats, residual sd 2.9 ms) | 144.848 (874 beats, 5.2 ms) | 149.998 (950 beats, 2.6 ms) |
| 64-beat window regression, min / median / max BPM | 142.015 / 142.042 / 142.066 (27 windows) | 144.829 / 144.849 / 144.879 (23) | 149.975 / 149.999 / 150.022 (29) |
| **Adopted** | **142.04** | **144.85** | **150.00** |
| Beat / 16th period | 422.4 / 105.6 ms | 414.2 / 103.6 ms | 400.0 / 100.0 ms |

Reading: the tempo is constant to +-0.03 BPM over the whole track in all three (machine-sequenced grid; autocorrelation stays at r 0.86-0.89 up to 16 beats). Limits: Twister's kick-band autocorrelation fails because the bass shares the band and varies its level; its tempo rests on M1 and the kick regression (they agree to 0.005 BPM). An earlier variant of M2 (autocorrelation of the log-derivative of the 30-150 Hz envelope) locked on **1.25 beats (113.6 BPM)** for Cthugha, i.e. a polyrhythm of the bass/kick band, and was discarded; it is mentioned because it shows the 5-against-4 trap the brief warned about (the 16-beat level autocorrelation and the regression do not have it). The labels' own BPM is not known (reference-tracks note section 2); 144.85 is not an integer and may be a sequencer/clock offset (cause not established).

## 2. Section map (bar level)

Method: per beat, band powers of the mid channel (STFT 4096 / hop 1024; bands 30-120, 120-500, 500-2000, 2000-8000, 8000-20000 Hz), spectral centroid, kick-hump level per beat; per bar mean; a piecewise-constant change-point fit (dynamic programming, squared error on the five band levels in dB, log-centroid and kick count, penalty 300, minimum 4 bars) gives the boundaries below, hand-merged with the kick runs. A boundary bar is the first bar whose features differ; a pickup bar can precede the downbeat. Levels are dB relative to the mean of the track's kick bars (mastered files: dynamics are small).

**Cthugha (259 bars, 142.04 BPM)**

| Bars | Length | Time | Kick beats per bar (of 4) | Level dB | Remark (measured) |
| --- | --- | --- | --- | --- | --- |
| 1-7 | 7 | 0:00-0:12 | 0.00 | -15.6 | one spectral peak at 196.0 Hz (bars 3-6, 2^18-point FFT), constant level |
| 8-16 | 9 | 0:12-0:27 | 0.00 | -6.1 | bass band enters; level ramps up in bars 8-9 |
| 17-24 | 8 | 0:27-0:41 | 0.00 | -4.6 | 2-8 kHz band +11 dB |
| 25-252 | 228 | 0:41-7:06 | 3.9 | -0.4 to 0 | kick on every beat; mid centroid drifts up (thirds of kick bars: 668 / 864 / 866 Hz full-band); kick drops (<= 2 of 4 beats) in single bars 49, 113, 162, 194, 227 and 252 |
| 253-259 | 7 | 7:06-7:18 | 0.00 | -15.6 | back to the 196 Hz single tone, same level as bars 1-7 |

**Twister (318 bars, 144.85 BPM)**

| Bars | Length | Time | Kick beats per bar | Level dB | Remark |
| --- | --- | --- | --- | --- | --- |
| 1-31 | 31 | 0:00-0:52 | 0.0 (bars 15-18: one hit per bar) | -15 to -10 | no kick; centroid sweeps inside (section 5) |
| 32-185 | 154 | 0:52-5:07 | 3.8-4.0 | -4 to +0.5 | kick-in at bar 33 (one pickup kick in bar 32); short low-level interlude bars 124-129 (-4.1 dB, kick <= 2 of 4 in bars 121-122, 129-130) |
| **186-195** | 10 | 5:07-5:24 | 0.2 | -8.1 | **kick out** |
| **196-219** | 24 | 5:24-6:03 | 1.6 (2 of 4 beats from bar 204) | -3.3 | half-time kick; level rises about 9 dB across bars 190-219 |
| 220-301 | 82 | 6:03-8:19 | 3.9 | -0.8 to +1.1 | kick back at bar 220; last 50 bars +1.1 dB |
| 302-318 | 17 | 8:19-8:47 | 0.0 | -18 to -11 | kick-less tail |

**Ephidrine (272 bars, 150.00 BPM)**

| Bars | Length | Time | Kick beats per bar | Level dB | Remark |
| --- | --- | --- | --- | --- | --- |
| 1-8 | 8 | 0:00-0:13 | 2-3 hits at about -7 dB re full kick | -4.6 | bar 5: 2-8 kHz band appears (centroid 648 -> 2877 Hz) |
| 9-259 | 251 | 0:13-6:55 | 3.75-4.0 | -1.3 to +0.4 | full kick from bar 9; kick drops (<= 2 of 4) in single bars 40, 92, 188, 249, 251; bars 237-260: centroid and 8-20 kHz band close (air band -34 dB -> -70 dB in absolute terms, 24 bars) |
| 260-272 | 13 | 6:55-7:15 | 0.0 | -6.6 to -34 | kick-less tail |

Cross-section facts (measured):

- **Kick-less intro before kick-in:** 24 bars (Cthugha), 32 bars (Twister), 0 (Ephidrine, hits from bar 1, full kick from bar 9).
- **Kick-less tail:** 7 / 17 / 13 bars. Time from kick-out to end: 12 s / 28 s / 20 s.
- **Breakdown (kick absent >= 4 consecutive bars inside the kick span):** Twister only, 34 bars; Cthugha and Ephidrine have none.
- **Kick-level dynamics:** mean level of the first / middle / last third of the kick bars differs by <= 1.1 dB in all three (Cthugha -15.0 / -14.5 / -14.7, Twister -14.9 / -14.8 / -13.8, Ephidrine -11.2 / -10.7 / -10.7 dB). An "accumulative" form is not visible in broadband level; the mid centroid does rise across thirds in Cthugha and Twister (668 / 864 / 866 and 291 / 854 / 1072 Hz full-band).
- **16-bar phrase marks (Cthugha):** the mid centroid spikes (+0.5 to +1 octave for one bar) on bars 65, 81, 97, 113, 145, 161, 225 ... i.e. bars congruent 1 mod 16 (inferred: a crash/transient on phrase starts; not identified by ear).
- **Boundary alignment:** change-point boundaries at bar number - 1 divisible by 4: Cthugha 4 of 5, Ephidrine 7 of 8, Twister 0 of 16 (its boundaries fall one bar before a multiple of 4, i.e. a pickup bar; consistent with the kick pickup in bar 32). Divisible by 8: 3 of 5, 1 of 8, 0 of 16. **An 8-bar change grid is not clearly visible; 4-bar alignment holds for two tracks.**

## 3. Kick

Method: kick-hump level per beat in the 30-120 Hz band (zero-phase 4th-order Butterworth + Hilbert envelope, 3 ms smoothing); kick trigger time from the kick click (1-10 kHz flux, 512-point frames) in sparse passages, which coincided with the strongest 80-400 Hz onset of each beat (validated in Twister bars 34-47 and Ephidrine bars 245-248).

| Quantity | Cthugha | Twister | Ephidrine |
| --- | --- | --- | --- |
| Kick spacing | 1 beat (422.4 ms), sd 2.9 ms | 1 beat (414.2 ms), sd 5.2 ms | 1 beat (400.0 ms), sd 2.6 ms |
| Beats with kick hump within 6 dB of the track reference / all beats | 86 % | 68 % | 89 % |
| Kick-bar count | 222 | 222 | 240 |
| Kicks between the beats (off-beat kick) | none seen in kick bars (the 30-120 Hz energy at the off-beat 8th is a bass note in Twister, see 4.2) | same | same |
| Isolated kicks found (no bass for >= 0.9 step after the kick) | **0** | **1** | **65** |
| Instantaneous frequency of the 25-160 Hz band at 15-30 / 30-50 / 50-75 / 75-100 ms after the trigger, **isolated kicks** | n/a | n/a | 129 / 89 / 66 / **55.6 Hz** |
| Same, all kick beats (bass leaks in) | 112 / 134 / 123 / 86.5 Hz | 84 / 96 / 89 / 72.9 Hz | 127 / 88 / 67 / 58.6 Hz |
| Same, cleanest 10 % of beats (lowest bass + sub level after the kick) | 126 / 154 / 123 / 85.9 Hz | 88 / 88 / 79 / 69.3 Hz | 129 / 89 / 66 / 55.6 Hz |
| Stacked power-spectrum peak of the 40-100 ms segment | 110.4 Hz | 91.5-94.2 Hz | 61.9 Hz |

Reading: **only Ephidrine yields a clean kick-tail pitch: a downward sweep from about 129 Hz to 55.6 Hz within 100 ms** (65 isolated kicks, interquartile range <= 0.7 Hz in the last window). The user's own kicks have a median tail of 53 Hz (kick learnings note); 55.6 Hz is 2.6 Hz above it. For Cthugha and Twister the tail is **not separable from the bass** (no isolated kicks; the Cthugha kick hump is short, about 40 ms, and a bass note sits on the same 16th); the values above are bounds, not kick pitches. Limit: instantaneous frequency of a band-limited, decaying hum has an error of several Hz at these window lengths (60 ms is 3-4 periods at 55 Hz).

## 4. Bass

### 4.1 Grid used

The mid-channel 80-400 Hz log-magnitude flux (STFT 2048 / hop 128) was folded on the beat period, anchored on the kick. The bass and hat events lie on a **16th grid with four positions per beat in all three tracks**: one event position coincides with the kick click (called **kick step**), the other three are the steps **+1, +2, +3** after the kick (+2 is the off-beat 8th). Controls: onset occupancy at half-step offsets is 5-9 % (80-400 Hz) and at the triplet positions (1/3, 2/3 of the beat) 3-5 % in all three tracks, against 28-98 % at the four grid positions. **No event grid other than the 16th grid was found.**

### 4.2 Occupancy per beat position (fraction of kick-bar beats with a flux peak within +-0.3 of a 16th of the position, above k times the track's median flux; 888 / 888 / 960 beats)

| Band, threshold | Cthugha +1 / +2 / +3 / kick step | Twister | Ephidrine |
| --- | --- | --- | --- |
| 80-400 Hz, 2x | 1.00 / 1.00 / 0.98 / 1.00 | 0.87 / 0.96 / 0.87 / 1.00 | 0.86 / 0.89 / 0.80 / 1.00 |
| **80-400 Hz, 3x (primary)** | **0.98 / 0.98 / 0.81 / 0.97** | **0.35 / 0.65 / 0.38 / 0.95** | **0.28 / 0.51 / 0.28 / 0.86** |
| 80-400 Hz, 4x | 0.85 / 0.82 / 0.39 / 0.73 | 0.07 / 0.36 / 0.14 / 0.65 | 0.05 / 0.25 / 0.08 / 0.52 |
| 80-400 Hz, half-step control at 3x | 0.09 | 0.05 | 0.08 |
| 40-200 Hz (the band asked for), 3x | 0.86 / 0.77 / 0.84 / 0.93 | 0.61 / 0.82 / 0.57 / 0.90 | 0.44 / 0.71 / 0.51 / 0.94 |
| 40-200 Hz, half-step control at 3x | 0.42 | 0.25 | 0.25 |
| Median flux peak per step, relative to the largest step (80-400 Hz) | 0.99 / 1.00 / 0.71 / 0.86 | 0.62 / 0.80 / 0.61 / 1.00 | 0.63 / 0.74 / 0.61 / 1.00 |

The 40-200 Hz row is **not discriminative** (frames of 46 ms cannot resolve onsets at 40-60 Hz; the control rate is 25-42 %), so the 80-400 Hz row is the one to use. The kick-step value contains the kick's own harmonics in all three and cannot show whether a bass note also sits under the kick.

Beat masks over (+1, +2, +3), 80-400 Hz, 3x (`x` = onset present), share of kick-bar beats:

| Mask | Meaning | Cthugha | Twister | Ephidrine |
| --- | --- | --- | --- | --- |
| `xxx` | three after the kick (roll) | **0.778** | 0.065 | 0.033 |
| `xx.` | +1, +2 | 0.184 | 0.205 | 0.099 |
| `.x.` | off-beat 8th only | 0.002 | **0.265** | **0.303** |
| `..x` / `.xx` / `x..` | other | 0.001 / 0.015 / 0.001 | 0.152 / 0.118 / 0.036 | 0.118 / 0.070 / 0.093 |
| `x.x` | "gallop" as defined in G1 section 5.2 (steps 1 and 3) | 0.019 | 0.042 | 0.059 |
| `...` | no onset in the three off-kick steps | 0.000 | 0.117 | 0.225 |

Reading (measured, with the 3x threshold as a stated choice; the 2x and 4x rows show the threshold dependence): Cthugha is a continuous 16th roll in the sense that every off-kick step starts a new event in most beats. Twister and Ephidrine put the strongest and most frequent event on the off-beat 8th and fewer events on the 16ths beside it. **Not established:** whether the weaker +1/+3 events in Twister/Ephidrine are ghost notes, same-pitch re-triggers with little spectral change (flux would miss them), or a different voice.

### 4.3 First note after the kick and note level per step

Median level (dB, 100-400 Hz / 40-200 Hz) 0.2-0.5 of a 16th after each event, relative to the +2 step: Cthugha +1 **+0.7 / +0.4**, +3 +0.2 / +0.3; Twister +1 **-4.3 / -0.9**, +3 -1.3 / -1.7; Ephidrine +1 **-1.9 / -2.7**, +3 0.0 / +0.1. In two of three tracks the first step after the kick is 1-4 dB below the +2 step. Limit: kick tail overlaps +1, most in the 40-200 Hz band.

### 4.4 Note length (gate)

Method: event-aligned median envelope (100-400 Hz, zero-phase Hilbert envelope, 3 ms smoothing; all detected onsets at +1, +2, +3 aligned on their flux peak). Gate = time from the half-height of the rise until the median envelope falls 6 dB below its plateau.

| Step | Cthugha (fraction of a 16th) | Twister | Ephidrine |
| --- | --- | --- | --- |
| +1 | 0.67 | no 6 dB fall within the 16th | no fall |
| +2 | 0.77 | no fall | no fall |
| +3 | 0.81 | no fall | no fall |
| Dip before the next note (median profile) | 8.7-12.0 dB | 2.5-3.5 dB | 1.0-1.2 dB |

Reading: **Cthugha: notes are separated (gate 0.67-0.81 of a 16th, dip 9-12 dB before the next note).** In Twister and Ephidrine the level does not fall by 6 dB inside a 16th: the notes are sustained or overlapped (legato), or a sustained layer sits under them; **the fraction cannot be resolved there** (>= 1 or masked). Per-note distributions were not reliable (the maximum statistic over a noisy envelope gives 0.2-0.35 for every track, an artefact I discarded) and are not reported.

### 4.5 Fundamentals and key candidates (all "candidate")

Method: per beat, three windows centred 0.4 of a 16th after the +1, +2, +3 events (N = 4096, Hann, 8x zero padding, parabolic peak refinement); f0 = strongest peak in 38-420 Hz, replaced by a peak at 1/2 or 1/3 of its frequency if one exists within 14 dB; the weakest 20 % by amplitude dropped; n = 2131 / 2131 / 2304 windows.

| | Cthugha | Twister | Ephidrine |
| --- | --- | --- | --- |
| f0 percentiles p10 / p50 / p90 (Hz) | 65.2 / 130.5 / 165.0 | 49.7 / 57.9 / 95.8 | 41.4 / 81.6 / 164.5 |
| Tuning estimate from the f0 values (cents re A440) | -2.5 | -12.5 (weak, peak share 0.06) | -2.5 |
| Most frequent f0 notes (share) | C2 0.31, C3 0.30, E3 0.15, C#3 0.13, C4 0.04, C#4 0.02 | C2 0.29, G#1 0.19, G1 0.13, A1 0.12, B1 0.07, G2 0.06, A#1 0.05 | E2 0.43, E1 0.25, F1 0.09, F2 0.06, E3 0.06, F3 0.02 |
| Same, only the two events farthest from the kick (+2, +3) | C3 0.36, C2 0.34, C#3 0.21, C4 0.05 | C2 0.47, B1 0.12, A1 0.10, G2 0.10, A#1 0.07 | E2 0.42, E1 0.27, F1 0.09, F2 0.08, E3 0.05 |
| Tonic candidate (bass) | **C** (octaves C2/C3) | **C** (weak; many notes within 4 semitones below) | **E** (octaves E1/E2) |
| Intervals above the tonic candidate with >= 5 % share | +1 (C#), +4 (E) | none stable (+9, +10, +11 appear as A, A#, B below C) | +1 (F) |
| Krumhansl-Schmuckler key correlation, bass f0 (top 2) | C major 0.37, C minor 0.29 | G minor 0.65, G major 0.63 (from a first, coarser f0 run; superseded by the table above) | E minor 0.68, E major 0.67 |
| Same, mid-band peak chroma 150-2000 Hz (top 2) | C major 0.56, E minor 0.52 | G minor 0.42, G# minor 0.33 | E major 0.75, B major 0.62 |

Reading: **inferred, not a key:** the bass tonic candidates are C, C, E. Margins between the first two key-profile correlations are 0.004-0.096; the major/minor profiles do not contain Phrygian or harmonic modes, so they are shown only to document that the profile method does not settle it. A **b2 (a semitone above the tonic candidate) is present in the bass of Cthugha (13-21 %) and Ephidrine (about 15 %)**; none in Twister. A major third above C (E3, 15 %) appears in Cthugha only (a Phrygian-dominant-like set {0, 1, 4} in the bass: inferred). Limit: the f0 estimate on 93 ms windows, octave errors (3rd harmonics, kick tail at 48-60 Hz in Twister), pitch glides, and a mix that contains the lead, make these shares approximate (+-0.05). The first f0 run with a 10.8 Hz grid mis-assigned C2 as B1 (63.5 Hz) and G1 for Twister; the refined run is the one reported.

## 5. Mid / lead region

Method: STFT (4096 / hop 1024) of the mono mix; centroid = power-weighted mean frequency; per bar over 500-10 000 Hz ("mid-band") and over 30-16 000 Hz (full-band).

| | Cthugha | Twister | Ephidrine |
| --- | --- | --- | --- |
| Full-band centroid in kick bars, p10 / p50 / p90 (Hz) | 606 / 829 / 1152 | 157 / 941 / 1166 | 400 / 733 / 879 |
| Mid-band centroid in kick bars, p10 / p50 / p90 (Hz) | 1943 / 2176 / 2750 | 2008 / 2916 / 4000 | 2036 / 2453 / 3308 |

**Rising mid-band centroid runs followed by a reset** (method: runs of >= 4 bars with net rise >= 0.45 octave, dips tolerated up to 0.08 octave; reset = fall >= 0.5 octave within the next 2 bars). Bars given as start / length / Hz range / rise in octaves:

| Cthugha | Twister | Ephidrine |
| --- | --- | --- |
| 58 / 8 / 2020 -> 3316 / 0.72 | 6 / 4 / 731 -> 2621 / 1.84 | 149 / 13 / 2180 -> 3302 / 0.60 |
| 78 / 4 / 2080 -> 3333 / 0.68 | 11 / 7 / 909 -> 3658 / 2.01 | (bars 1-8: 647 -> 3451 Hz, 2.41 oct, reset only 0.41) |
| 146 / 16 / 2026 -> 3763 / 0.89 | 25 / 5 / 1343 -> 2617 / 0.96 | |
| 216 / 12 / 2004 -> 4897 / 1.29 | 51 / 7 / 1773 -> 3402 / 0.94 | |
| 237 / 16 / 1926 -> 3762 / 0.97 | 231 / 5 / 2955 -> 5015 / 0.76 | |
| (bars 12-32: 21-bar intro rise 745 -> 2861 Hz) | | |

Reading (measured): rises last **4-16 bars** (Cthugha 4, 8, 12, 16, 16; Twister 4-7; Ephidrine 13) and span 0.6-1.3 octaves of the mid-band centroid outside the intros. Cthugha's runs are multiples of 4 bars. Limit: the centroid of 500 Hz-10 kHz mixes hats, claps, lead and pad; it shows that something brightens and resets, **not that a filter cutoff moves** (cause not established), and it cannot give the sweep curve of a single voice.

**Stereo (mid/side power ratio and L/R correlation per octave band, 4th-order Butterworth, whole track):**

| Band centre (Hz) | S/M dB C / T / E | corr(L,R) C / T / E | Mid-channel power share dB re total C / T / E |
| --- | --- | --- | --- |
| 31.5 | -34.1 / -24.8 / -16.9 | 0.999 / 0.994 / 0.964 | -23.8 / -5.0 / -15.3 |
| 63 | -40.4 / -17.1 / -17.5 | 1.000 / 0.961 / 0.966 | -7.3 / -7.0 / -5.1 |
| 125 | -41.5 / -21.9 / -16.3 | 1.000 / 0.988 / 0.954 | -5.2 / -6.8 / -5.7 |
| 250 | -39.4 / -14.5 / -9.9 | 1.000 / 0.933 / 0.833 | -6.7 / -10.7 / -8.0 |
| 500 | -38.8 / -5.5 / -7.9 | 1.000 / 0.561 / 0.724 | -10.0 / -15.4 / -11.5 |
| 1000 | -38.4 / -3.5 / -6.0 | 1.000 / 0.382 / 0.596 | -11.3 / -13.7 / -10.9 |
| 2000 | -37.6 / -4.1 / -5.4 | 1.000 / 0.439 / 0.571 | -12.5 / -12.2 / -13.3 |
| 4000 | -38.1 / -6.4 / -6.1 | 1.000 / 0.628 / 0.610 | -15.1 / -15.4 / -15.9 |
| 8000 | -38.0 / -11.3 / -6.8 | 1.000 / 0.868 / 0.729 | -14.7 / -14.1 / -15.0 |
| 16000 | -36.0 / -14.2 / -10.2 | 1.000 / 0.955 / 0.868 | -18.3 / -18.7 / -23.3 |
| Whole mix | -39.5 / -11.7 / -10.7 | 1.000 / 0.873 / 0.842 | |

Octave bands span centre / sqrt 2 to centre x sqrt 2. Cthugha is not bit-identical dual mono (L = R in 0.5 % of the samples; maximum |L-R| 2876 LSB) but its side channel is about 1 % of the mid in amplitude. In Twister and Ephidrine the kick-bar-only values equal the whole-track values within 1 dB except Twister below 150 Hz (S/M -32.4 / -19.7 / -27.7 dB at 31.5 / 63 / 125 Hz instead of -24.8 / -17.1 / -21.9). Limit: stereo of a full mix includes reverb, delays and panned hats; no voice-level width can be read from it.

## 6. Loudness, peak, crest, spectral balance

| | Cthugha | Twister | Ephidrine |
| --- | --- | --- | --- |
| Integrated loudness (LUFS, ffmpeg ebur128) | -11.2 | -11.5 | -7.2 |
| Loudness range (LU) | 6.3 | 14.5 | 2.6 |
| True peak (dBTP) | -2.4 | **+0.4** | **+0.9** |
| Sample peak (dBFS) | -3.99 | -0.16 | -0.10 |
| RMS of both channels (dBFS) | -14.00 | -13.71 | -9.56 |
| Crest, sample peak minus RMS (dB) | 10.0 | 13.5 | 9.5 |
| True peak minus integrated loudness (dB) | 8.8 | 11.9 | 8.1 |
| Welch spectrum at 16 / 18 / 20 kHz, dB re 1 kHz | -17 / -15 / -24 | -20 / -20 / -21 | -26 / -29 / -33 |

Octave-band balance is the right-hand column of the stereo table. Reading: the three files are loud masters (Twister and Ephidrine exceed 0 dBTP, i.e. inter-sample peaks above full scale); the Twister loudness range of 14.5 LU comes from its 31-bar kick-less intro and 34-bar breakdown. Cthugha has 18 dB less energy in the 31.5 Hz band than Twister (-23.8 vs -5.0 dB re total), and Twister's 63 Hz band is the weakest of the three in the 63-250 Hz block. The Welch spectra show no brick-wall low-pass at 16 or 19 kHz (so no evidence of lossy coding in the history of the files; this is not proof of its absence).

## 7. Cross-track comparison and the plan

### 7.1 Side by side

| | Cthugha | Twister | Ephidrine |
| --- | --- | --- | --- |
| BPM | 142.04 | 144.85 | 150.00 |
| Bars (about) | 260 | 319 | 273 |
| Kick-less intro | 24 bars | 32 bars | none (hits from bar 1) |
| Breakdown | none | 34 bars (59-69 %) | none |
| Kick-less tail | 7 bars | 17 bars | 13 bars |
| Bass events | every 16th (`xxx` 78 %) | off-beat 8th dominant (65 %), +1/+3 28-38 % | off-beat 8th dominant (51 %), +1/+3 28-32 % |
| Bass gate (separated notes) | 0.67-0.81 of a 16th | legato/unresolved | legato/unresolved |
| Tonic candidate (bass) | C | C (weak) | E |
| Stereo | near-mono | stereo above 250 Hz | stereo above 250 Hz |
| LUFS / true peak | -11.2 / -2.4 | -11.5 / +0.4 | -7.2 / +0.9 |

### 7.2 Plan assumptions against the measurements

Rule used: a plan value is **supported** if >= 2 tracks fall inside it, **contradicted** if >= 2 tracks fall outside it, **open** otherwise; a **PROPOSAL** replaces a window only where >= 2 tracks agree. Sources: [plan section 2.2](2026-11-03_goa-synth-voice-plan.md), [G1 sections 2.1, 5.2, 6](2026-11-03_goa-trance-musicology-and-sound.md), D-026.

| Plan item (window or assumption) | Measured | Verdict | PROPOSAL (nothing applied) |
| --- | --- | --- | --- |
| BPM window 135-150, default 140 (G1 findings 1-2, 5.2 `bpm_hint`) | 142.04 / 144.85 / 150.00 | window **supported** (3 of 3 inside; one on the 150 edge); default 140 **contradicted** (3 of 3 above it by 2.0 / 4.9 / 10.0 BPM) | default **145**, preset range **140-150**; keep 135-136 as the user's own lower limit (arrangement-note range 136-146 is the user's, untouched). Sample of three. |
| Default bass rhythm `three_after_kick`, `offbeat_8th`, `gallop`, `full_16th` as selectable variants (D-026) | `xxx` 78 % / 6.5 % / 3.3 %; `.x.` 0.2 % / 26.5 % / 30.3 %; `x.x` ("gallop") 1.9 % / 4.2 % / 5.9 %; triplet positions 3-5 % in all | `three_after_kick` as sole default: **open** (supported by 1 of 3; the other two have it in <= 7 % of beats). **Gallop (steps 1,3) and triplet: not supported by any**. Off-beat 8th as the strongest event: supported by 2 of 3 | keep the default (no ear evidence yet); add a variant `offbeat_ghost` with +2 on 50-65 % of beats and +1, +3 on 28-38 % each (two tracks, threshold-dependent: low confidence); demote `gallop` to "not found in three references" |
| Rolling bass gate 0.6-1.0 of a 16th | Cthugha 0.67-0.81; Twister and Ephidrine: not falling within a 16th (>= 1 or masked) | **supported** (1 inside, 2 consistent with the upper end) | no change |
| Filter-closing time 2-40 ms | not measurable (mix, 3 ms smoothing, 23 ms frames) | **not established** | none |
| First roll note against the others -12 to 0 dB | +0.7, -4.3, -1.9 dB (100-400 Hz); +0.4, -0.9, -2.7 dB (40-200 Hz) | **supported** (all inside; two of three 1-4 dB below) | window **-5 to 0 dB** (was -12 to 0); tighter because three tracks lie between +0.7 and -4.3 |
| Bass fundamental `note` 24-36 for a drone; line register per user | tonic notes E1 (28), C2 (36), C2 (36); line median 130.5 / 57.9 / 81.6 Hz = MIDI 48 / 34 / 40; upper notes to C4 (60) | tonic notes **inside** 24-36 (3 of 3); the running line also uses octave-up notes (2 of 3 have a median above MIDI 36) | line register **MIDI 28-48** for `roll_bass`, drone **28-36**; root pitch classes **C, C, E** observed (G1 5.2 starter root F1 = 43.65 Hz is not observed) |
| Kick tail relation (user's 53 Hz) | only Ephidrine separable: 55.6 Hz (isolated kicks, n = 65) | **open** (1 of 3) | none |
| Mode weights (G1 2.1: aeolian 0.3, phrygian 0.3, harmonic minor 0.15, phrygian dominant 0.25) | b2 in the bass of Cthugha and Ephidrine; none in Twister; a major third only in Cthugha | modes with a b2 (0.55 combined): **supported** by 2 of 3; the split between phrygian and phrygian dominant: **open** (1 track shows both b2 and a major third) | b2-modes combined **0.65** (phrygian 0.35, phrygian dominant 0.30), aeolian 0.25, harmonic minor 0.10; low confidence: bass-only f0 histograms, octave errors, three tracks |
| Acid/lead: filter envelope decay 80-400 ms, resonance 3-18 dB, accent +3 to +8 dB, slide 30-120 ms | not isolable from the stereo mixes; no timestamps given | **not established** | none; needs isolated passages (question 3) |
| Lead unison 3-7 voices, detune 5-25 cents; second oscillator +0/+7 | not measurable | **not established** | none |
| Pluck / pad attack 200-1500 ms | not measurable | **not established** | none |
| Pad / mix width (correlation between channels; plan has no window) | 500 Hz-4 kHz: 0.38-0.73 (Twister, Ephidrine), 1.000 (Cthugha); below 250 Hz: 0.83-1.00 | two stereo tracks agree; the third is mono | mix-level check, not a voice window: correlation **0.4-0.75 between 500 Hz and 4 kHz** and **>= 0.93 below 250 Hz** for a stereo variant (Twister/Ephidrine only; Cthugha shows a mono master is also in the set) |
| Sweep over bars (plan: no window) | mid-band centroid rises of 0.6-1.3 octave over 4-16 bars with a reset, in 3 of 3 tracks | consistent across tracks | window **4-16 bars, 0.6-1.3 octave of mid-band centroid** (measured on the mix, not on one filter) |
| Riser 4-16 bars (plan; G1: builds of 8/16/32) | the same rises; pre-kick builds are 24 and 32 bars (2 tracks) | **supported** for the riser length | no change |
| Arrangement 288 bars (G1 section 6) | about 260 / 319 / 273 bars | total length **supported** (all within +-12 % of 288) | none |
| "Break 1" of 16 bars with kick and bass out, at bars 97-112 (G1 section 6) | no kick-out stretch >= 8 bars before the main breakdown in any track | **contradicted** (0 of 3) | drop or make optional |
| Main breakdown at 61 %, 32 bars with kick out (G1 section 6) | Twister: bars 186-219 = 59-69 %, 34 bars (10 bars no kick, 24 bars half-time kick); Cthugha, Ephidrine: none | **open** (1 of 3) | keep as a variant; add the `no_breakdown` variant (2 of 3) |
| Intro 32 bars with kick from bar 1; D-026 "long authentic build" default and optional 16-bar DJ-friendly intro | kick-less 24 and 32 bars (Cthugha, Twister); kick from bar 1 (Ephidrine) | long kick-less build: **supported** by 2 of 3 | default intro **24-32 bars without kick**; kick-from-bar-1 (the template's current intro) as the DJ-friendly variant (1 of 3 shows it) |
| Outro 32 bars reduced to K+B with the kick on (G1 section 6) | all three end with a kick-less tail of 7 / 17 / 13 bars | **contradicted** (3 of 3) | outro **7-17 bars kick-less** after the last kick bar; keep a 32-bar kick-on outro as the DJ-friendly variant |
| "Accumulative" energy: each peak above the previous (G1 section 6 table E column) | kick-bar level changes <= 1.1 dB across thirds; centroid rises in two | broadband level: **not visible** in these masters | none |

## 8. Measurement limits

1. **Mastered label remasters.** The files are digital label masters (loud, limited; Twister and Ephidrine exceed 0 dBTP). Dynamic quantities (accents, ghost-note levels, kick-to-bass ratio, level rise across sections) are compressed and cannot be taken as the original mix.
2. **Stereo full mixes, no stems.** Every band measurement contains kick, bass, lead, pads, hats and reverb together. Bass-only quantities (gate, occupancy, f0) were taken in bands (80-400, 100-400, 40-200 Hz) where the kick and the lead also have energy.
3. **Polyrhythms and a hidden bass.** A 5-against-4 lock (113.6 BPM) occurred in one method; same-pitch 16th re-triggers produce no spectral flux, so the Twister/Ephidrine occupancy of +1/+3 is a lower bound; legato or a sustained sub layer hides gate and onsets. The bass under the kick cannot be separated.
4. **Kick contamination.** Kick tail leaks into the +1 step (long kicks in Twister, Ephidrine); the 40-200 Hz flux has no usable onset resolution at 46 ms frames (control rate 25-42 %).
5. **Bar phase and bar counts.** The grouping of beats into bars (first kick-in) is an assumption; section lengths are accurate to +-1 bar; the DP penalty (300) and minimum length (4 bars) are choices.
6. **f0 and key.** 93 ms windows, octave and harmonic errors, glides, lead in the mix, tuning estimate peak share 0.06-0.17. Key-profile correlations are shown only to document that they do not decide. Key stays a **candidate** for all three until a human reads the notes in Live.
7. **Centroid is not cutoff.** The mid-band centroid mixes voices; sweep lengths are lengths of brightening, not of a filter movement.
8. **Three tracks, three characters** (label blurbs: acid, melodic, proto-Goa). Disagreement between them is itself a result; with n = 3, "agree" means two or three. Nothing here is a distribution of the genre.
9. **Not measurable here, reported as such:** accent lift, slide, resonance bump, unison voice count and detune, pad attack, filter-closing time, per-note velocity.
10. The reference-tracks note leaves open whether the user's files are the 2019/2020/2025 digital masters; the loudness and peak values belong to the files as delivered.
11. Reproducibility: the scripts are in the session scratchpad, outside the repo; the converted WAV copies stay there and are not committed. Test boundary: nothing here runs in CI; the numbers cannot be reproduced without the user's files.

## 9. Follow-up questions for the user

1. **Bass rhythm (listening).** In Cthugha the bass plays on every 16th. In Twister and Ephidrine the strongest bass event is the off-beat 8th, with weaker events on the 16ths next to it. When you say "rolling", is it the every-16th pattern (Cthugha), the off-beat pattern with ghost notes (Twister, Ephidrine), or something else, and may the generator's default follow your choice instead of `three_after_kick`?
2. **Form.** Two tracks begin without a kick for 24-32 bars, one has a 34-bar kick-out breakdown, and all end with a kick-less tail of 7-17 bars. Should the default arrangement follow that (long kick-less intro, at most one breakdown, short kick-less outro), with the template's kick-from-bar-1 intro and 32-bar kick-on outro as the DJ-friendly option?
3. **Isolated passages.** For the lead/acid-line numbers (filter decay, accent, slide, unison) I need passages where the element plays almost alone. Please give 3-5 timestamps (mm:ss) per track for "lead or acid line alone or nearly alone", and for "bass and kick only" if any exist (Ephidrine's kick tail is the only one I could isolate; Cthugha and Twister have none).

## Commands run (session scratchpad, outside the repo)

`ffmpeg ... -c:a pcm_s16le` (conversion); `ffmpeg -nostats -i <wav> -af ebur128=peak=true -f null -` (loudness); numpy/scipy scripts for flux autocorrelation, grid fold, kick regression, bar features, change-point fit, bass flux folds, event-aligned envelopes, f0 histograms, kick-tail instantaneous frequency, octave-band stereo statistics and Welch spectra. Parameters are stated in each section.

## State update proposal (for the PR body; the lead edits `CURRENT_STATE.md`)

- Goa reference measurements written: `docs/research/2026-11-03_goa-reference-measurements.md` (Refs #338): tempo 142.04 / 144.85 / 150.00 BPM (two methods), section maps, kick, bass rhythm and register, mid/lead, stereo, loudness, plan comparison with PROPOSAL values; no audio in the repo; key remains a candidate; lead/acid quantities not measurable from the mixes.
- Open for the user: bass rhythm choice, form choice, isolated-passage timestamps (section 9).
- Next: lead decides which PROPOSAL values enter the plan and the `goa_patterns` presets; user answers unblock the lead/acid measurement.
