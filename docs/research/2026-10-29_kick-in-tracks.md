# Research: finding and measuring kicks in full tracks and loops

- **Date:** 2026-10-29 (all sources opened on this date unless a paper is cited by DOI)
- **Receiving issue:** #100 (D-023 research cluster 3; questionnaire tab 2, task A-1)
- **Author role:** researcher
- **Scope:** audio content only. Reference audio is measurement input, never copied and never committed (see [kick-gen2-learnings](2026-10-28_kick-gen2-learnings.md), short version point 7). No artist or track names. No sound claims. Live functions, desktop window, mix targets and AI audio generation are other clusters and are not answered here.
- **Status:** researched, **not verified**. Nothing here was run on audio by this session.

## Versions researched against

| Item | Version / state on 2026-10-29 | Source |
| --- | --- | --- |
| AbeltonGod `src/audio_engine/analysis.py` | `main` at 61088d1 | repo |
| Python in this repo | `requires-python = ">=3.11"` | `pyproject.toml` line 10 |
| librosa | 1.0.0, uploaded 2026-08-11, ISC, **`requires_python >=3.12`**, pure-Python wheel | PyPI JSON API (`pypi.org/pypi/librosa/json`) |
| madmom | 0.16.1, uploaded 2018-11-14, sdist only (no wheels); code BSD, model/data files CC BY-NC-SA 4.0 | PyPI JSON API; [github.com/CPJKU/madmom](https://github.com/CPJKU/madmom) README |
| aubio | 0.4.9, uploaded 2019-02-08, GPL-3, sdist only | PyPI JSON API |
| essentia | 2.1b6.dev1438, uploaded 2026-05-19, AGPL-3.0-only; latest release lists macOS and manylinux wheels, **no Windows wheel** | PyPI JSON API |
| demucs | 4.1.0, uploaded 2026-07-11, MIT, `>=3.10`; home page is the maintained fork `adefossez/demucs`; the original `facebookresearch/demucs` was archived on 2025-01-01 | PyPI JSON API; [pypi.org/project/demucs](https://pypi.org/project/demucs/); [github.com/facebookresearch/demucs](https://github.com/facebookresearch/demucs) |
| torch | 2.15.0, uploaded 2026-10-28, `>=3.11`, `win_amd64` wheel on PyPI | PyPI JSON API |
| LarsNet | README state of 2026-10-29 (commit not recorded: GitHub API access to external repos was blocked in this session) | [github.com/polimi-ispl/larsnet](https://github.com/polimi-ispl/larsnet) |
| ADTOF | README state of 2026-10-29 (commit not recorded) | [github.com/MZehren/ADTOF](https://github.com/MZehren/ADTOF) |
| DOSE | README state of 2026-10-29 (commit not recorded) | [github.com/HSUNEH/DOSE](https://github.com/HSUNEH/DOSE) |

Discrepancy noted: the librosa documentation banner still names 0.11.0 as the latest release ([librosa.org/doc/main/.../onset_strength](https://librosa.org/doc/main/generated/librosa.onset.onset_strength.html)), while PyPI lists 1.0.0. PyPI is taken as the authority for the version; the API pages cited below were read on the development docs and may differ in detail from 1.0.0.

## Short answers

| # | Question | Answer in one line | Confidence |
| --- | --- | --- | --- |
| 1 | How to locate kick hits | Two stages: (a) **find hit times** with a low-band onset function (librosa, ISC, CPU) or a drum-transcription model (ADTOF / madmom, both **non-commercial** model licences); (b) **refine each onset to the sample** with a threshold method, because detectors work on ~10–23 ms frames and are scored with a ±50 ms window. Optional (c) **isolate the kick**: Demucs (MIT, drums stem only, not kick) then a drum-stem splitter (LarsNet: kick stem, weights CC BY-NC 4.0). All run on CPU; GPU (RTX 5070 = Blackwell) needs a PyTorch CUDA ≥ 12.8 build. | High for tools/licences; medium for the two-stage recipe (interpretation) |
| 2 | Reliability on a separated/masked kick | **No source found that measures pitch curve, decay or click energy on separated kicks against the clean one-shot.** Published separation scores (SDR, spectral distances) do not translate into feature errors. Documented mechanisms predict specific biases (bass bleed in the sub band, Wiener-filter "ducking", ~23 ms mask time resolution). Must be measured by our own experiment with engine kicks as ground truth. | High that no feature-level evidence exists in the sources read; mechanisms medium (interpretation) |
| 3 | Which `analysis.py` features survive | `fundamental_hz`: **conditionally** (needs onset-aligned cut and little bass in 40–100 Hz). `decay_20db_ms`: **conditionally** (usually reached before the next hit). `decay_40db_ms`: **often censored** at four-on-the-floor tempos. `peak_dbfs`, `length_ms`, `dc_offset`: **do not describe the kick** on this route. | Medium (derived from the code and the tempo arithmetic; untested) |

## Question 1 — Methods to locate kick hits in a full track or loop

**Question.** Methods to locate kick hits in a full track or loop (onset/transient detection, drum source separation): open libraries, licences, CPU vs GPU (RTX 5070), accuracy limits.

### 1a. Onset / transient detection (where is a hit?)

| Finding | Source | Confidence |
| --- | --- | --- |
| `librosa.onset.onset_strength` passes extra keyword arguments to the mel spectrogram when no `S` is given, so `fmin`/`fmax`/`n_mels` can restrict the onset function to a band. The documented example uses `fmax=8000`. Restricting to a low band for kicks is our use, not a documented recipe. | [librosa onset_strength](https://librosa.org/doc/main/generated/librosa.onset.onset_strength.html) (dev docs, 2026-10-29) | High (API); kick band use is interpretation |
| `librosa.onset.onset_detect` defaults: `hop_length=512`, `backtrack=False`, `units='frames'`. `backtrack=True` moves each onset to the preceding energy minimum and is documented as useful for slicing. Derived: hop 512 is 23.2 ms at the default 22 050 Hz and 11.6 ms at 44 100 Hz. | [librosa onset_detect](https://librosa.org/doc/latest/generated/librosa.onset.onset_detect.html) | High (API); time resolution derived |
| librosa 1.0.0 requires Python ≥ 3.12; this repo allows 3.11. Adding it would raise our floor or pin an older librosa. | PyPI JSON API; `pyproject.toml` line 10 | High |
| madmom: onset and beat features; code BSD, **model and data files CC BY-NC-SA 4.0** (commercial use needs permission). Last PyPI release 0.16.1 (2018), sdist only, so a Windows install has to compile. | [madmom README](https://github.com/CPJKU/madmom); PyPI | High (licence, release); Windows build effort is interpretation |
| aubio (GPL-3) and essentia (AGPL-3.0, no Windows wheel in the latest release) have onset detection; both licences are copyleft. | PyPI JSON API | High |
| Standard onset evaluation counts a detection as correct within **0.05 s** of the reference (mir_eval default). A published F-measure therefore says nothing about sample accuracy. | [mir_eval onset](https://mir-eval.readthedocs.io/latest/api/onset.html) | High |

### 1b. Kick-specific detection (which hit is a kick?)

| Finding | Source | Confidence |
| --- | --- | --- |
| ADTOF: drum-transcription model and dataset (359 h of annotated music), 5 classes incl. kick; TensorFlow/Keras with madmom; a PyTorch port exists (~0.2 % F-measure loss). **Repository content licensed CC BY-NC-SA 4.0.** Tested with Python 3.10 on macOS. | [ADTOF README](https://github.com/MZehren/ADTOF); classes per [arXiv 2509.24853](https://arxiv.org/html/2509.24853v1) | High |
| ADT with melodic instruments present is ~14.5 % worse than drums-only; error analysis found **accented bass guitar notes labelled as bass drum** and missed weak bass drum onsets. Evaluation tolerance 50 ms. Training data rock/pop; no conclusion for electronic music possible. | Weyers, Uhle, Müller, Lang, *Understanding Performance Limitations in Automatic Drum Transcription*, ISMIR 2025 ([PDF](https://www.audiolabs-erlangen.de/content/05_fau/professor/00_mueller/03_publications/2025_WeyersUML_LimitationsADT_ISMIR_ePrint.pdf)) | High (paper); transfer to techno is open |
| Separation before ADT (Demucs v4 → MDX23C drum splitter → ADTOF) gives essentially the same 5-class accuracy as ADTOF alone; on RBMA (electronic drum sounds) the 8-class score was 2 % below baseline, attributed to sounds outside the acoustic-drum training domain. No per-class kick numbers. | [arXiv 2509.24853](https://arxiv.org/html/2509.24853v1), 2025-09-29 | High (paper) |
| No per-class kick F-measure was found in the ADTOF analysis paper's abstract page. | [ISMIR 2024 poster 68](https://ismir2024program.ismir.net/poster_68.html) | High (absence in that page) |

### 1c. Isolating the kick (source separation)

| Finding | Source | Confidence |
| --- | --- | --- |
| Demucs v4 (`htdemucs`) separates drums / bass / other / vocals, 44.1 kHz stereo; **no kick stem**. MIT. Overall SDR 9.0 dB on MUSDB HQ (mean of four sources; per-source drums value not in the pages read). GPU needs ≥ 3 GB, ~7 GB with defaults; CPU time "roughly 1.5×" the track duration (hardware not stated). `--shifts` multiplies run time. | [Demucs README](https://github.com/facebookresearch/demucs); Rouard, Massa, Défossez, [arXiv 2211.08553](https://arxiv.org/abs/2211.08553) | High |
| LarsNet splits a **drums-only** stereo mix into kick, snare, toms, hi-hat, cymbals: five U-Nets producing soft masks on a magnitude STFT (Hann 4096, hop 1024, mixture phase reused). Kick nSDR 27.19 dB (with α = 1 Wiener filter) on held-out kits. Speed: 0.016 × real time on a TITAN V GPU, 0.15 × real time on a Xeon E5-2687W CPU. **Trained and tested on StemGMD = MIDI rendered with 10 acoustic kits**; no electronic kits, no full-mix input. | Mezza, Giampiccolo, Bernardini, Sarti, *Toward Deep Drum Source Separation*, Pattern Recognition Letters 183 (2024) 86–91, doi:10.1016/j.patrec.2024.04.026 ([arXiv](https://arxiv.org/abs/2312.09663)) | High (paper) |
| LarsNet repo: weights **CC BY-NC 4.0**, ~562 MB; code licence not stated on the page; CLI `separate.py -i <dir> [-d cuda:0] [-w α]`. README warns the Wiener option can cause **side-chain-compression-like artefacts** (α ≥ 1) or more bleed (α < 1). | [LarsNet README](https://github.com/polimi-ispl/larsnet) | High |
| Community drum splitters with a kick stem (DrumSep on Hybrid Demucs, MIT code, weights licence not stated; MDX23C, SCNet, Roformer variants) report kick SDR 14–22 dB on a test set the page does not describe; most have no public weights or licence. | [MVSEP drum algorithms](https://mvsep.com/algorithms/29); [inagoy/drumsep](https://github.com/inagoy/drumsep) | **Medium** (community service, test set undocumented) |
| DOSE extracts a kick one-shot from a full mix by **generating** codec tokens (MusicGen-style transformer + DAC), trained on synthetic loops; it beats LarsNet + MIDI-aligned slicing on spectral distance and FAD. Code Apache-2.0, checkpoint licence not stated, tested with Python 3.10. | Hwang et al., [arXiv 2504.18157](https://arxiv.org/html/2504.18157v1), 2025-04-25; [DOSE repo](https://github.com/HSUNEH/DOSE) | High (paper/README) |
| Score-informed NMF deconvolution (NMFD) can decompose a drum loop into its individual drum sounds when the hit times are known; it is CPU-only linear algebra and model-free. | Dittmar & Müller, *Reverse Engineering the Amen Break*, IEEE/ACM TASLP 24(9) 2016, 1531–1543, doi:10.1109/TASLP.2016.2567645 ([AudioLabs page](https://audiolabs-erlangen.com/resources/MIR/2016-IEEE-TASLP-DrumSeparation)) | High (paper exists and has this aim); fit for electronic loops not established |
| Signal averaging of N time-locked repetitions lowers uncorrelated noise power by N (amplitude by √N); correlated "noise" is not reduced. | [Wikipedia: Signal averaging](https://en.wikipedia.org/wiki/Signal_averaging) | High (textbook result) |

### 1d. CPU vs GPU (RTX 5070)

| Finding | Source | Confidence |
| --- | --- | --- |
| RTX 50-series (compute capability sm_120) is supported by **PyTorch binaries built with CUDA 12.8 or newer**; the usual failure is an older torch in the environment; check `torch.cuda.get_arch_list()` contains `sm_120`. A Windows 11 user confirmed the fix (2025-10-26). | [PyTorch forum thread](https://discuss.pytorch.org/t/nvidia-geforce-rtx-5070-ti-with-cuda-capability-sm-120/221509) (staff answer) | Medium–high (forum, staff statement) |
| Whether the default PyPI `win_amd64` torch 2.15.0 wheel is CPU-only or CUDA-enabled was **not established**: the PyTorch wheel index was not reachable from this session and the get-started page served a stale selector (2.7.0). | attempted `download.pytorch.org/whl/cu128/torch/` (403 via proxy); [pytorch.org/get-started](https://pytorch.org/get-started/locally/) | — |
| Onset detection (librosa) and NMF are NumPy/SciPy and need no GPU. Separation models run on CPU too; LarsNet is faster than real time on a 2010s Xeon. | as above | High |

### Answer to Q1

1. **Hit times.** For loops and four-on-the-floor tracks a low-band onset function (e.g. librosa with `fmax` ≈ 150–200 Hz; band choice is our assumption, not a source value) is the cheapest route: ISC licence, CPU, no model. A transcription model (ADTOF) is the documented way to tell kick from other hits, but its licence is non-commercial and its known failure mode is bass notes read as kicks, which is exactly the techno/trance risk (interpretation).
2. **Sample-accurate onset.** All detectors above give frame positions (~10–23 ms) and are judged within ±50 ms. Our analysis measures from the onset, and the gen2 note (pitfall 2) shows that ~10 ms of offset already falsifies pitch values. So each detected hit needs a second, sample-level step (e.g. the gen2 note's "first sample above 10 % of peak" inside a short window around the detected frame). This is derived, not from a source.
3. **Isolation.** Full mix → Demucs (MIT) drums stem → LarsNet or a community splitter for the kick stem. Every public kick-level splitter found has a non-commercial or unstated weight licence, and none was trained on electronic kits. DOSE generates its output, so features measured on it describe the model's rendition (interpretation; whether that is acceptable under D-005 is for the lead).
4. **Model-free alternative for repeated kicks (interpretation).** Electronic loops often repeat one identical kick sample (the gen2 note measured 0.999–1.0 hit-to-hit correlation in 7 of 10 loops). Averaging N onset-aligned hits reduces whatever differs between hits by 10·log10(N) dB (16 hits → 12 dB, 64 → 18 dB), with no model and no licence question. It does **not** remove anything that repeats in lock-step with the kick (a bass on the same grid, sidechain ducking, a layered clap).
5. **Accuracy limits.** No source gives kick-onset accuracy for electronic full mixes; ADT numbers are multi-class, rock/pop-trained and use a 50 ms tolerance; separation numbers come from acoustic, synthetic test sets.

**Confidence:** high for the tool facts and licences; medium for the recipe, which is this session's synthesis.

## Question 2 — Reliability of kick features on a separated or masked kick

**Question.** How reliable are kick features (pitch curve, decay, click energy) measured on a separated or masked kick vs a clean one-shot?

**Answer.** No source read measures these features on separated kicks against their clean originals. The available evaluations score separation with SDR/nSDR (LarsNet, Demucs), multi-scale spectral distance and FAD (DOSE), or onset F-measure (ADT). None reports pitch-curve, decay-time or click-energy error. **Reliability is therefore not established and has to come from our own experiment** (see "To verify").

What the sources do document, and the bias each would predict (predictions are **interpretation**, not measured):

| Documented mechanism | Source | Predicted effect on features (interpretation) |
| --- | --- | --- |
| Mask-based separation on a 4096/1024 STFT (93 ms window, 23 ms hop at 44.1 kHz, derived), mixture phase reused | LarsNet paper | The mask changes at most every ~23 ms, about the length of the median pitch settle (24 ms) in the reference set; the pitch drop and the 0–10 ms click are where the error should be largest. The tail (> 50 ms) should fare best. |
| Wiener post-filter gives side-chain-like ducking (α ≥ 1) or more bleed (α < 1) | LarsNet README | Ducking shortens measured decay; bleed lengthens it or floors the envelope above −40 dB. |
| Bass notes confused with kick; melodic content degrades ADT by ~14.5 % | Weyers et al. 2025 | Bass energy in the kick's band ends up in the kick estimate: sub share (energy < 100 Hz) biased up, tail fundamental pulled toward the bass note. |
| Separators trained on acoustic kits (LarsNet: StemGMD; drum-ADT: rock/pop); electronic sounds outside the domain reduced scores on RBMA | LarsNet paper; arXiv 2509.24853 | Synthetic techno kicks (long sine tails at 45–60 Hz) are out of domain; errors could be larger than the published numbers. |
| DOSE output is generated through a neural codec; the codec round trip alone ("reconstruction") already differs from the original (kick MSS 1.83 on RMOD) | DOSE paper, Table I | Features measured on DOSE output include codec error even in the best case. |
| Averaging removes only content uncorrelated across hits | Signal averaging | Averaged kicks keep a lock-step bass and sidechain shape; only non-repeating content is reduced. |
| A hit cut out of a loop can have its decay cut by the next hit | gen2 note, pitfall 7 | Decay must be treated as censored, not measured, whenever the next onset comes first. |

Already known for **clean** one-shots (gen2 note section 2; not repeated here): start pitch is "not established" even on clean files, tail pitch is within 4 % and settle/decay within ~10 % on synthetic kicks. Any separated-kick figure must be compared to these clean-file errors, not to zero.

**Confidence:** high that the literature read gives no feature-level reliability figures; medium for the listed mechanisms' effects (interpretation).

## Question 3 — Which features from `analysis.py` survive this route?

**Question.** Which features from our analysis (`src/audio_engine/analysis.py`) survive this route?

`analyse()` returns six fields (lines 49–63). Assessment, derived from the code; nothing measured:

| Field | Survives? | Why (file/line) |
| --- | --- | --- |
| `fundamental_hz` | **Conditionally** | Zero-crossing rate over the 100 ms ending at the −40 dB point, never before 20 ms from **sample 0** (`TAIL_EARLIEST_MS`, line 42; `tail_window`, lines 66–76). Needs (a) the cut to start at the sample-refined onset, (b) little other energy near 40–100 Hz: zero crossings of a sum follow whichever component dominates the waveform, so a bass residual can move or break the count (interpretation; to verify). If −40 dB is never reached before the cut, the window falls back to the file end (line 70–71), i.e. the last 100 ms before the next hit. |
| `decay_20db_ms` | **Conditionally** | Time from **sample 0** to 20 dB below the envelope peak (lines 116–122, 40 ms max-abs frames). Survives if the cut is onset-aligned and the floor of the separated/averaged signal is more than 20 dB below the peak. The docstring's known bias (−14 to +4.4 ms on clean kicks, lines 20–27) adds on top. |
| `decay_40db_ms` | **Often censored** | At a 4/4 kick the next hit comes after 461.5 ms at 130 BPM, 428.6 ms at 140 BPM, 400 ms at 150 BPM (60 000 / BPM). The reference set's −40 dB decay has median 327 ms and p75 424 ms (gen2 note, section 2), so roughly a quarter or more of such kicks reach the next hit first at ≥ 140 BPM (derived). It also needs a residual floor below −40 dB. Returns `None` when not crossed (line 120–121), which is correct, but on this route `None` means "censored", not "long". |
| `peak_dbfs` | **No** | Depends on mix gain, mastering, separation gain and averaging, not on the kick. |
| `length_ms` | **No** | Equals the cut length, i.e. the inter-onset interval or our window choice. |
| `dc_offset` | **No** | A cut from a mastered mix or a separated stem says nothing about the kick's DC. |

The gen2 note's extra measures (not in `analysis.py`) under the same reasoning (interpretation): tail harmonics 2–8 and energy share < 100 Hz are biased by bass bleed; onset energy share > 1 kHz in the first 10 ms is biased by any hat, clap or top layer on the same beat and by the separator's time resolution; pitch settle time falls in the region where mask resolution is coarsest. Start pitch stays "not established".

**Confidence:** medium. The code facts are high; the survival verdicts are derived and must be checked by the experiment below.

## To verify by experiment

Each item becomes an issue for the owning role (D-019). V1–V5 are CI-runnable because the engine provides ground truth; V6–V8 need the user's machine.

| # | Experiment | Owner (proposal) | Where |
| --- | --- | --- | --- |
| V1 | **Ground-truth harness:** render engine kicks over the full `kick-params` range (seeded), place them on a 4/4 grid at 120–150 BPM, add masking material from our own synthesis (sine/saw bass on the same grid and off-grid, noise hats, a clap on 2 and 4, sidechain-style gain ducking). Measure every `analysis.py` field on the clean one-shot vs on the hit recovered from the mix. Report error distributions per field, not single cases. | audio-engineer | CI |
| V2 | **Onset refinement:** frame onset (low-band onset function) + sample-level threshold vs the known render position; error in samples over the V1 set; confirm that a 1–2 ms offset moves `fundamental_hz`/`decay_*` measurably (fault injection). | audio-engineer | CI |
| V3 | **Synchronous averaging:** error of each feature vs N (1, 4, 16, 64 hits) with off-grid vs on-grid bass; checks the 10·log10(N) prediction and that lock-step bass is not removed. | audio-engineer | CI |
| V4 | **Zero crossings under bass residual:** `fundamental_hz` error vs bass level (−40 … 0 dB relative) and bass frequency (35–110 Hz); find the level at which it breaks. | audio-engineer | CI |
| V5 | **Censoring:** share of V1 kicks whose −40 dB point lies beyond the next onset per tempo; confirm the analysis returns `None` and does not report the cut length. | audio-engineer | CI |
| V6 | **Separation on our ground truth:** run Demucs (MIT) and, if the lead accepts non-commercial weights for local analysis, LarsNet on V1 mixes; same error tables. Needs the large torch dependency, so outside CI by default. | audio-engineer + lead (dependency/licence decision) | user's machine or a manual job |
| V7 | **RTX 5070:** `torch.cuda.get_arch_list()` contains `sm_120` with the installed torch; Demucs run time CPU vs GPU on one 6-minute track. | bridge-engineer or user (setup doc) | user's machine |
| V8 | **Real references:** on the user's licensed loops, compare features of the loop's first hit cut cleanly (gen2 method) vs the same hit found by the V2/V3 route. No audio committed, aggregates only. | sound-designer (plan) + user | user's machine |

## Implications for the lead (proposals, not decisions)

1. **Licence gate before any model.** Every public kick-level splitter or kick-aware detector found (LarsNet weights, ADTOF, madmom models) is non-commercial or unlicensed for weights. Whether local, analysis-only use is acceptable is a user decision; until then a model-free route (low-band onset + sample refinement + synchronous averaging, optionally NMF) is the only one with clean licences.
2. **Dependency floor.** librosa 1.0.0 needs Python ≥ 3.12, our floor is 3.11. A low-band onset function is a few lines of NumPy; deciding between "write it" and "raise the floor" is the lead's call.
3. **Contract hint (no change proposed here).** If measurements from tracks ever enter `sample-metadata`, a field for "censored by next hit" and the measurement route (clean / averaged / separated) would keep these numbers apart from clean one-shot numbers. Any such change needs its own `contract-change` PR.
4. **DOSE** is a generative model; using it even for analysis input touches D-005's spirit. Noted, not recommended; the user would have to decide.
5. **Rule kept:** reference audio stays measurement input; only aggregates leave the user's machine (gen2 note rule 7).
