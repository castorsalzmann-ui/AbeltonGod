# Research: mix and loudness targets, mix measurements, fair before/after comparison (cluster 4)

- **Date:** 2026-10-29. All web sources retrieved on 2026-10-29.
- **Versions researched against:**
  - Standards: ITU-R **BS.1770-5** (11/2023), EBU **R 128-2023 (v5.0)**, EBU **Tech 3341 v4** (11/2023), EBU **R 128 s2-2021** (Loudness in Streaming), ITU-R **BS.1116-3** (02/2015, editorial amendments 03/2023), ITU-R **BS.1534-3** (10/2015, editorial amendments 03/2023).
  - Platform pages: Spotify for Artists "Loudness normalization" and SoundCloud Help Center article 360053660014. **Neither page shows a date**; values are as published on 2026-10-29.
  - Libraries (PyPI JSON API, queried 2026-10-29): `pyloudnorm 0.2.0` (MIT, uploaded 2026-01-04, pure-Python wheel), `pyebur128 0.1.1` (MIT, uploaded 2024-09-07, Windows wheels cp38–cp312 only), libebur128 `master` (MIT), `scipy 1.18.1` (BSD-3, cp314 `win_amd64` wheel), `soundfile 0.14.0` (BSD-3), `librosa 1.0.0` (ISC, `requires_python >=3.12`), `essentia 2.1b6.dev1438` (AGPL-3.0-only, no Windows wheel), `pyfar 0.8.1` (MIT). Source files were read from the default branch on 2026-10-29 (the GitHub API was not reachable from this session, so no commit SHA is recorded; line numbers can drift).
  - Project context: repo requires Python >=3.11, CI runs 3.12, the user's Windows machine runs **Python 3.14.4** (`docs/CURRENT_STATE.md`).
- **Receiving issue:** #101 (D-023 research cluster 4; questionnaire tab 2 tasks C-1, D-2). Rules: D-019 point 3, D-023.
- **Not covered here (other clusters):** Live functions and device control, desktop window, kick-in-tracks, AI audio. Nothing here describes how anything sounds.
- **Existing notes checked:** `docs/research/` has no loudness note. `2026-10-28_kick-gen2-learnings.md` uses crest factor for single kick samples (section 2) and lists analysis pitfalls (section 4); this note is about full stereo mixes and does not change that note.

## Short answers

| # | Question | Answer in one line | Confidence |
| --- | --- | --- | --- |
| 1a | Streaming / SoundCloud targets | Spotify normalises to −14 LUFS integrated (ITU 1770; "Loud" −11, "Quiet" −19) and asks for < −1 dBTP, < −2 dBTP if louder than −14 LUFS. SoundCloud says it normalises on playback and gives the same −14 LUFS / −1 dBTP / −2 dBTP advice. | High (official pages, undated) |
| 1b | Club targets | **No standard or official target exists** for club play. Measured dance/pop chart masters average about −8.3 LUFS integrated with true peaks often above 0 dBTP; these are measurements, not targets, and not techno/trance-specific. | High for "no standard"; medium for the measured values |
| 2 | Meaningful mix measurements + libraries | On a stereo export: integrated / short-term / momentary loudness, LRA (≥ 1 min only), true peak, PLR and crest factor, low-band energy share, L/R correlation (width), band-energy shares and a long-term spectrum slope. BS.1770 loudness: `pyloudnorm` (MIT, no true peak). True peak + LRA: libebur128 / `pyebur128` (MIT, no Python 3.14 wheel). Everything else: numpy + scipy (BSD-3). | High for definitions and licences; interpretation for which metrics are "meaningful" |
| 3 | Fair before/after comparison | Gain-match the two versions to equal BS.1770 integrated loudness over the same time-aligned excerpt, gain only (turn the louder one down), then compare blind and in random order. ITU listening-test standards fix the playback level and align loudness before judging. | High for the standards; medium for the LUFS-matching procedure (interpretation) |

## Question 1 — loudness and peak targets for techno/trance club play and for SoundCloud/streaming

**Question.** Common loudness/peak targets for techno/trance club play and for SoundCloud/streaming (LUFS integrated/short-term, true peak), with sources and dates.

**Answer.**

| Finding | Confidence | Source (retrieved 2026-10-29) |
| --- | --- | --- |
| BS.1770-5 defines programme loudness: K-weighting (shelf + RLB high-pass), 400 ms blocks with 75 % overlap, absolute gate −70 LKFS, relative gate −10 LU; L/R weight 1.0. Annex 2 defines true peak: 4× oversampling at 48 kHz (2× suffices at 96 kHz), after −12.04 dB attenuation. Sample-peak meters can under-read (about 3 dB for a tone at fs/4; transients "several dB"). | High | [ITU-R BS.1770-5 page](https://www.itu.int/rec/R-REC-BS.1770-5-202311-I), [PDF](https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1770-5-202311-I!!PDF-E.pdf), Annex 1, Annex 2 and its Attachment 1 |
| EBU Tech 3341 v4: momentary = 0.4 s sliding window, short-term = 3 s sliding window, both ungated; integrated = gated per BS.1770. True-peak meters must meet BS.1770 Annex 2 and the Table 1 tolerances (test signals 15–23, +0.2/−0.4 dB). | High | [EBU Tech 3341](https://tech.ebu.ch/docs/tech/tech3341.pdf), sections 2.2, 2.6 |
| EBU R 128-2023 is a **broadcast** recommendation: −23.0 LUFS programme loudness, max true peak −1 dBTP in production, LRA not recommended under one minute. It gives no music-specific rules. | High | [EBU R 128 v5.0](https://tech-qual.ebu.ch/files/live/sites/tech/files/shared/r/r128v5_0.pdf) |
| EBU R 128 s2-2021 (streaming): default is to stream unchanged at −23 LUFS; an interim distribution level of −20 to −16 LUFS is allowed; for music services it mentions album or anchor-based normalisation; no numeric true-peak ceiling. | High | [EBU R 128 s2 v2.0](https://knowledgehub.ebu.ch/files/live/sites/tech/files/shared/r/r128s2v2_0.pdf), items e, g, i, k |
| Spotify: playback normalised to −14 LUFS integrated (ITU 1770) on "Normal"; −11 "Loud"; −19 "Quiet". Louder tracks get negative gain; quieter tracks get positive gain with 1 dB headroom left for lossy encoding; a limiter is used only on "Loud" (−1 dB sample values, 5 ms attack, 100 ms decay). Master advice: true peak below −1 dBTP, below −2 dBTP if the master is louder than −14 LUFS. | High (official, page undated) | [Spotify for Artists: Loudness normalization](https://support.spotify.com/artists/article/loudness-normalization/) |
| SoundCloud: applies loudness normalisation as tracks are played; recommends −14 LUFS integrated and ≤ −1 dBTP; ≤ −2 dBTP if louder than −14 LUFS; streams in Ogg/Vorbis and AAC (no bitrates given). | High (official, page undated) | [SoundCloud Help: Will SoundCloud play my track at the level it's mastered?](https://help.soundcloud.com/hc/en-us/articles/360053660014-Will-SoundCloud-play-my-track-at-the-level-it-s-mastered) |
| AES TD1008 (2021, successor of TD1004) is reported to recommend −16 LUFS distribution loudness for music (loudest album track at −14 LUFS with album normalisation) and −18 LUFS for speech. **Primary document not readable from this session** (aes.org refused the connection); values come from two secondary sources. | Medium | [Production Advice on TD1008](https://productionadvice.co.uk/td1008/) (Ian Shepherd, 2021-10-01), [Telos Alliance docs](https://docs.telosalliance.com/docs/understanding-loudness-for-streaming-audio); primary: [AES TD1008 PDF](https://aes.org/wp-content/uploads/2024/01/20210924_TD1008_v3.13.pdf) (not opened) |
| **No club loudness standard exists.** A practitioner article calls club loudness "the wild west"; it recommends −16 LUFS / −1 dBTP even for club tracks because DJs gain-match at the mixer. This is one author's advice, not a norm. | High for "no standard" (no standards body found that sets one); low for the −16 advice | [ask.audio, Shane Berry: Loudness standards and EDM/club production](https://ask.audio/articles/how-loudness-standards-relate-to-edm-and-club-music-production) (undated; oldest comment 2018) |
| Measured, not targets: 10 Billboard Hot Dance/Electronic tracks (chart week "March 22nd"; year 2025 inferred from the publication date): integrated −6.2 to −11.3 LUFS, mean −8.3; true peak −0.29 to +1.50 dBTP; max short-term loudness mean −6.1 LUFS (range −8.6 to −4.5); LRA 3.5–13.8 LU. These are chart dance/pop, not techno/trance. | Medium (vendor blog; one author's measurements) | [iZotope, Ian Stewart, 2025-04-08](https://www.izotope.com/en/learn/dance-electronic-analysis) |
| Measured, not targets: 54 Billboard Global 200 top-10 songs (H1 2024): mean −8.3 LUFS, SD 1 LU; max short-term about 2–4 LU above integrated; 43 of 54 had true peak ≥ 0 dBTP. | Medium (vendor blog) | [iZotope, Ian Stewart, 2024-07-16](https://www.izotope.com/en/learn/mastering-trends) |
| DJ software auto-gain (rekordbox, Traktor): no official documentation of the measurement or target level was found; only forum posts. | — (open) | Searches on 2026-10-29 returned only community threads, e.g. [NI community thread](https://community.native-instruments.com/discussion/35592/gain-analysis-parameters-autogain-clipping) |

**Interpretation (not from a source).**
- For streaming/SoundCloud the number that changes playback is −14 LUFS integrated: a louder master is turned down, so extra loudness above −14 LUFS buys no playback level there. The true-peak advice (−1 / −2 dBTP) is the only hard ceiling the platforms publish.
- For club play there is nothing to "meet". A tool could report where a user's export sits relative to (a) the streaming reference −14 LUFS, (b) the measured chart range (about −11 to −6 LUFS), and (c) the −1 dBTP ceiling, without calling any of them a target. Whether techno/trance releases sit in the same range as the chart dance tracks is **not established** (no techno/trance-specific measurement found).
- Short-term loudness has no published target anywhere; only "max short-term" is used descriptively (R 128 says it may be used to check upper loudness tolerance).

**Confidence:** high for the standards and platform values as published on 2026-10-29; medium for TD1008 (secondary) and the measured chart data; no source for a club target.

## Question 2 — meaningful measurements on a user-exported stereo file, and open libraries

**Question.** Which mix measurements are meaningful on a user-exported stereo file (low-end balance, stereo width, crest factor, spectral tilt) and open libraries to compute them (licences).

**Answer — measurements.**

| Measurement | Definition used in a source | Confidence | Source |
| --- | --- | --- | --- |
| Integrated loudness (LUFS) | BS.1770-5 gated K-weighted loudness | High | BS.1770-5 Annex 1 |
| Momentary / short-term loudness, max values | 0.4 s / 3 s ungated windows | High | Tech 3341 §2.2; R 128 v5 |
| Loudness range (LRA, LU) | EBU Tech 3342 distribution of short-term values; **not for programmes under 1 min** | High | R 128 v5; Tech 3342 (cited by R 128) |
| True peak (dBTP) vs sample peak | BS.1770 Annex 2 oversampling; sample peak under-reads | High | BS.1770-5 Annex 2 |
| Crest factor (dB) | peak amplitude / RMS amplitude, in dB | High (definition) | [Wilson & Fazenda, JAES 64(1/2) 2016, §2.2 Table 2](https://salford-repository.worktribe.com/OutputFile/1497447) (author manuscript) |
| PLR (peak-to-loudness ratio) | true peak minus integrated loudness (used as a reported figure, e.g. 7.5 dB for one stereo mix) | Medium (vendor usage; no standard defines PLR) | [iZotope 2025-04-08](https://www.izotope.com/en/learn/dance-electronic-analysis) |
| Low-end balance | "LF energy": fraction of total spectral energy in 20–80 Hz | High (definition) | Wilson & Fazenda 2016 §2.2 |
| Stereo width | 1 − L/R cross-correlation at zero lag; in their data set quality ratings peaked near width 0.17 | High (definition); the 0.17 optimum is for their data set (genres not checked here), not a techno/trance target | Wilson & Fazenda 2016 §2.2, §4.5 |
| High-frequency extent / harshness | spectral rolloff (frequency below which 85 % of energy lies); "harsh energy" = energy share 2–5 kHz | High (definition) | Wilson & Fazenda 2016 §2.2 |
| Spectral tilt | **No standard definition found.** | — | Searched 2026-10-29; Pestana et al., "Spectral characteristics of popular commercial recordings 1950–2010", AES 135th Convention 2013 ([record](https://research.usj.edu.mo/bibliography/JP6VMNFE)) studies long-term spectra, but the abstract and paper were not readable from this session |
| Relation to perceived quality | In Wilson & Fazenda's listening test, quality ratings were most associated with features tied to perceived loudness and dynamic range compression (clips were loudness-equalised first). | Medium (one study, pop music) | [Wilson & Fazenda 2016, repository record](https://salford-repository.worktribe.com/output/1407562/perception-of-audio-quality-in-productions-of-popular-music) |

**Interpretation (not from a source).**
- All of the above work on a single stereo export; none needs stems. They describe the file, they do not say whether it is "good".
- **Spectral tilt** could be defined in our code as the least-squares slope (dB per octave) of a long-term average spectrum (Welch, e.g. `scipy.signal.welch`) between two fixed frequencies. Frequency limits, window and the reference slope are our own choices and must be written into the contract, because no standard fixes them.
- **Low-end mono compatibility** (relevant for club systems) could be the L/R correlation of a low-passed band (e.g. below 120 Hz). The band edge is our choice; no source fixes it.
- Side/mid energy ratio is an alternative width figure; it is not in the sources above.
- Crest factor depends on sample peak; PLR on true peak and gated loudness. Reporting both, with names that say which peak is used, avoids the confusion the kick note already warns about for single samples.

**Answer — libraries (licences as listed on PyPI on 2026-10-29).**

| Library | Version | Licence | What it provides | Fit for our stack | Source |
| --- | --- | --- | --- | --- | --- |
| `pyloudnorm` | 0.2.0 | MIT | `Meter(rate, filter_class="K-weighting", block_size=0.400, overlap=0.75)`; `integrated_loudness()` (meter.py line 33); `loudness_range()` with 3 s blocks at 0.97 overlap (meter.py lines 115–143); `normalize.peak` / `normalize.loudness`. **No true-peak function.** Depends on numpy and scipy. | Pure-Python wheel, so it installs on Python 3.14 | [PyPI](https://pypi.org/pypi/pyloudnorm/json), [meter.py](https://github.com/csteinmetz1/pyloudnorm/blob/master/pyloudnorm/meter.py), [README](https://github.com/csteinmetz1/pyloudnorm) |
| libebur128 | master | MIT | C library: M, S, I modes, LRA (Tech 3342), true-peak scanning, any sample rate; README lists true-peak conformance tests. API in `ebur128/ebur128.h`: `ebur128_loudness_global` (l. 240), `_momentary` (l. 263), `_shortterm` (l. 273), `_range` (l. 304), `ebur128_true_peak` (l. 378). | Needs a binding | [README](https://github.com/jiixyj/libebur128), [ebur128.h](https://github.com/jiixyj/libebur128/blob/master/ebur128/ebur128.h) |
| `pyebur128` | 0.1.1 | MIT | Cython binding of libebur128: `R128State`, `get_loudness_global`, `get_loudness_shortterm`, `get_loudness_range`, `get_true_peak` (returns linear value, 1.0 = 0 dBTP; 4× oversampling below 96 kHz) (`src/pyebur128/pyebur128.pyx` lines 339–641). Docstring warns true-peak values may differ between library versions. | **Windows wheels only for cp38–cp312**; last release 2024-09-07. On the user's Python 3.14 pip would build from source (needs a C compiler) | [PyPI](https://pypi.org/pypi/pyebur128/json), [pyebur128.pyx](https://github.com/jodhus/pyebur128/blob/main/src/pyebur128/pyebur128.pyx) |
| `scipy` | 1.18.1 | BSD-3-Clause | `signal.welch` (spectra), `signal.sosfiltfilt` / `butter` (band splits), `signal.resample_poly` (could build a 4× true-peak estimator per BS.1770 Annex 2 — interpretation, must be validated) | cp314 `win_amd64` wheel present; scipy 1.18 needs Python ≥ 3.12 (older scipy for 3.11) | [PyPI](https://pypi.org/pypi/scipy/json) |
| `soundfile` | 0.14.0 | BSD-3-Clause (bundles libsndfile) | Read WAV/AIFF/FLAC exports as float arrays | `py3-none-win_amd64` wheel | [PyPI](https://pypi.org/pypi/soundfile/json) |
| `librosa` | 1.0.0 | ISC | Spectral centroid / rolloff etc. | `requires_python >=3.12` (repo allows 3.11); pulls numba, scikit-learn — heavy for a few features numpy/scipy can do | [PyPI](https://pypi.org/pypi/librosa/json) |
| `essentia` | 2.1b6.dev1438 | **AGPL-3.0-only** | Has EBU R128 and many descriptors | AGPL obligations; no Windows wheel on PyPI | [PyPI](https://pypi.org/pypi/essentia/json) |
| `pyfar` | 0.8.1 | MIT | Acoustics toolkit | Pulls matplotlib, sofar; more than needed | [PyPI](https://pypi.org/pypi/pyfar/json) |
| ffmpeg `ebur128` / `astats` / `aphasemeter` filters | — | LGPL/GPL (depending on build) | External binary; filters listed in the docs (sections 20.10, 8.59, 20.6); option details not read | Adds an external program dependency | [FFmpeg filters documentation](https://ffmpeg.org/ffmpeg-filters.html) |

**Interpretation.** The smallest dependency set that covers everything is `pyloudnorm` (integrated loudness, LRA) + `scipy` (spectra, band filters, an own true-peak estimator) + `soundfile` (reading exports), all MIT/BSD, all installable on Python 3.14 Windows by wheel. `pyebur128` would give a tested true-peak implementation but has no wheel for the user's Python. This is a proposal, not a decision (new dependencies need a reason in the PR, CLAUDE.md).

**Confidence:** high for licences, versions and API names (read from PyPI and source on 2026-10-29); interpretation as marked.

## Question 3 — comparing two exported versions fairly (level matching)

**Question.** How to compare two exported versions (before/after) fairly (level matching).

**Answer.**

| Finding | Confidence | Source |
| --- | --- | --- |
| ITU-R BS.1116-3 §6: a skilled group adjusts each excerpt's loudness subjectively before the test so all items play at one fixed gain; §8.4.1.1: reference listening level 78 ± 0.25 dBA with pink-noise alignment; if subjects change the gain, it must be reported. §4: double-blind triple-stimulus hidden-reference method; switching about 40 ms. | High | [ITU-R BS.1116-3 PDF](https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1116-3-201502-I!!PDF-E.pdf) |
| ITU-R BS.1534-3 (MUSHRA) §7.1: loudness of each excerpt adjusted subjectively by skilled assessors; §8: listeners may move the level within ±4 dB per session but never within an item; §3: randomised order; §5.1: excerpts about 10 s, preferably ≤ 12 s. Neither ITU test standard names BS.1770 for this step. | High | [ITU-R BS.1534-3 PDF](https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1534-3-201510-I!!PDF-E.pdf) |
| Research practice: compression-preference study matched its seven versions "carefully in loudness" so loudness could be ruled out as the cause of preference. | Medium (abstract only) | [Taylor & Martens, AES 136th Convention 2014, paper 9022](https://aes2.org/publications/elibrary-page/?id=17169) |
| Research practice: Wilson & Fazenda loudness-equalised clips (Glasberg & Moore loudness model) "to mimic modern broadcast standards or programs such as Spotify", played at an average 84 dBA. | High (author manuscript §2.1.2) | [Wilson & Fazenda 2016](https://salford-repository.worktribe.com/OutputFile/1497447) |
| Platform practice: Spotify and SoundCloud already gain-normalise to −14 LUFS integrated on playback, so a listener there hears both versions at about the same integrated loudness (unless a version is too quiet to be raised without exceeding headroom). | High (pages above) | Spotify, SoundCloud pages (Question 1) |
| EBU R 128 treats ±0.2 LU as measurement error in quality control. | High | R 128 v5 |

**Interpretation — a procedure the copilot could follow (proposal, not from one source).**
1. Use the same time-aligned excerpt of both exports (e.g. the same 8–16 bars, a few seconds to 12 s for listening per BS.1534 §5.1; the whole track for numbers).
2. Measure BS.1770 integrated loudness of each excerpt; compute the gain difference; apply it as one static gain in float, **turning the louder version down** (turning up can push true peaks over 0 dBTP).
3. Report the applied gain (e.g. "B was 2.4 LU louder and was turned down by 2.4 dB"), because a loudness difference is itself a result of the change, especially when the change is limiting or compression.
4. Listen blind and in random order at one fixed monitor level; do not change level within an item (BS.1534 §8).
5. Report all Question 2 metrics for both versions side by side, unmatched, so the numeric difference is visible separately from the listening result.

Whether BS.1770 matching makes two bass-heavy techno versions *sound* equally loud is **not established** here (BS.1770 was designed for broadcast programme loudness; no source found that tests it on club mixes). That is a listening question for the user.

**Confidence:** high for the standards' requirements; medium for the procedure (our interpretation built on them).

## To verify by experiment

Each item names the owning role (D-019: each becomes an issue).

1. **pyloudnorm conformance** (audio-engineer, CI): run `pyloudnorm 0.2.0` integrated loudness and LRA on the EBU loudness test set (free download, [EBU announcement](https://tech.ebu.ch/news/ebu-publishes-loudness-test-material-22dec10), now at tech.ebu.ch/publications/ebu_loudness_test_set) and compare with the expected values and tolerances in Tech 3341 / Tech 3342. Licence of the test files must be checked before any are committed.
2. **True-peak route** (audio-engineer, CI + user's machine): either (a) check whether `pip install pyebur128` succeeds on the user's Windows Python 3.14.4 (no wheel exists), or (b) write a scipy 4× oversampling true-peak estimator and validate it on Tech 3341 test signals 15–23 (+0.2/−0.4 dB).
3. **Python-version fit** (audio-engineer): confirm the chosen libraries install on CI Python 3.12 and the user's 3.14 (scipy 1.18 needs ≥ 3.12; repo states ≥ 3.11).
4. **Short exports** (audio-engineer, CI): behaviour of integrated loudness and LRA on short loop exports (a few bars); LRA is not recommended under 1 min (R 128). Decide what the tool reports then.
5. **Metric definitions** (audio-engineer + sound-designer): fix band edges for LF energy, low-band correlation and the spectral-tilt slope in a contract; check determinism (same file → identical numbers on Linux and Windows).
6. **LUFS-matched A/B by ear** (sound-designer plans, user listens): whether BS.1770-matched before/after versions of the user's own techno/trance exports are heard as equally loud. No listening claim is made here.
7. **Genre reference values** (sound-designer): the measured ranges above are chart dance/pop. Measure the user's own reference tracks (techno/trance) with the same code before any range is shown as "typical".
8. **Platform values staleness** (lead at `/close-phase`): Spotify and SoundCloud pages are undated; re-read them when the feature is built.
9. **AES TD1008 primary text** (researcher, if needed): read the primary PDF from a network that reaches aes.org to confirm the secondary-source values.
10. **DJ software auto-gain** (open; only if the user wants club-prep features): no official documentation found for rekordbox or Traktor.

## Implications for the lead (proposals only)

- An analysis feature for stereo exports can start CI-only (numbers from files); nothing in this cluster needs Ableton.
- Present loudness numbers against references, not targets: "−14 LUFS streaming normalisation", "−1 dBTP ceiling", "chart dance range"; no club target exists to quote.
- Before/after comparison should always level-match and state the gain applied; this fits the "technical honesty" rule because it separates "louder" from "different".
- Dependency decision needed when the feature is planned: pure-Python/BSD route (`pyloudnorm` + `scipy` + `soundfile`, own true peak) versus `pyebur128` (tested true peak, no Python 3.14 wheel). `essentia` (AGPL) and `librosa` (Python ≥ 3.12, heavy) look like poor fits.
