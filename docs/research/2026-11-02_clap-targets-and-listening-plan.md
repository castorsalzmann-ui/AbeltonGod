# Clap: measurable target ranges, hypotheses and listening-test plan (C3)

_Date: 2026-11-02 · Role: sound-designer · Issue: #232 (after #231 = C2 clap voice) · Status: **plan and hypotheses, not a result.** Nothing here was heard. Numbers describe signals only; every "better", "tighter", "more punch" is for the user's ear. All parameter values below are proposals inside `contracts/clap-params.schema.json` v0.1; none is a default or a taste claim._

## Short version

1. Three styles are defined by contract fields plus four non-pitched features (`spectral_centroid_hz`, `hf_share_8k`, `t60_ms`, `rise_time_ms`, v0.2 `sample-metadata`): **tight techno**, **long trance**, **layered** (section 2).
2. The ranges come from my own NumPy model of the v0.1 recipe, **not from the engine** (C2 is not on `main` yet) and **not from reference audio** (none was supplied). They are hypotheses until the audio-engineer re-measures them on the real voice (H1).
3. One pitfall found by the model: `rise_time_ms` is not usable as a style target for a multi-burst noise clap (section 3, P1). `t60_ms` is `null` for roomy claps that do not fall 60 dB inside the file (P2).
4. Listening plan: 7 items, 18 blind-named files from 11 unique renders, about 12 minutes, identical control pair, blind names, key file, German answer sheet (section 5).

## 1. Read and method

Read: issue #232, `contracts/clap-params.schema.json` (v0.1), `contracts/sample-metadata.schema.json` (feature definitions, lines 35-38), `2026-11-02_next-category-proposal.md` (3.6 clap line, section 2), `2026-10-29_bandit-wheel-synthesis-transfer.md` (4.1-4.3, V8), `2026-10-29_bandit-wheel-musical-transfer.md` (3.3, H4, H6), `2026-11-02_listening-test-3-plan.md` (format).

Measurement: `clapsim.py` in my scratchpad (`/tmp/claude-0/-home-claude/8969c227-1cdb-551a-898a-46125f9a8cff/scratchpad/clapsim.py`, not in the repo), NumPy 2.5.3 + SciPy 1.18.1, run with `python3 clapsim.py`. It implements the contract text independently of any engine code: seeded white noise, RBJ band-pass (`bp_hz`, `bp_q`) before the envelope, per-burst exponential (60 dB in `burst_decay_ms`) held until the next onset, tail from one spacing after the last onset, RBJ high-pass (Q 0.7071) after the envelope, optional room = noise IR with cubic taper mixed dry/wet at equal power. 48 kHz, no quantisation, no drive. Features: centroid and HF share from one FFT of the whole file; `t60` = time from the peak of a 1 ms RMS envelope to -60 dB; rise = 10 % to 90 % of that peak envelope. Ranges below are min..max over seeds 1-8 of the same parameters. Model details that are my reading of the schema text (for example how a burst behaves when the next one starts before it has fallen) may differ from C2.

## 2. Target ranges per style (hypotheses H-T, source: model above)

Fields not listed keep the contract default. All values are inside the v0.1 ranges.

| | **Tight techno** | **Long trance** | **Layered** |
| --- | --- | --- | --- |
| Construction | one voice | one voice, `room` | two renders summed (no layer field in v0.1) |
| `bursts` / `burst_spacing_ms` | 3 / 8 | 4 / 12 | tight: 3 / 8 + wide: 6 / 14 |
| `burst_decay_ms` / `burst_level_falloff` | 12 / 0.80 | 25 / 0.85 | 12 / 0.80 and 30 / 0.95 |
| `tail_level` / `tail_decay_ms` | 0.4 / 90 | 0.7 / 350 | 0.4 / 90 and 0.6 / 250 |
| `bp_hz` / `bp_q` / `hp_hz` | 1500 / 1.6 / 600 | 1300 / 1.2 / 450 | 1500 / 1.6 / 600 and 1200 / 1.0 / 400 |
| `room` / `room_length_ms` | 0 | 0.3 / 500 | 0 |
| `length_ms` | 300 | 900 | 700 |
| **Model: spectral_centroid_hz** | 2400-2800 | 2300-2600 | about 2400-2700 (one sum measured: 2622 for tight + 0.5 x a 1300 Hz long voice, a different pair) |
| **Model: hf_share_8k** | 0.03-0.05 | 0.03-0.045 | 0.04-0.05 |
| **Model: t60_ms** | 80-105 | 440-500 with room, 295-330 dry | 240-300 (wide voice alone); the tight + long sum did not reach -60 dB inside 300 ms (`null`) |
| rise_time_ms | not a target (P1) | not a target (P1) | not a target (P1) |

Style-defining quantities (hypotheses): **t60_ms separates tight from long by a factor of about 3-5 (≈ 90 vs ≈ 300-490 ms)**; centroid and HF share barely separate the styles in the model (differences inside the seed spread) because both use a similar band-pass. Style differences in brightness come from `bp_hz`, `bp_q` and `hp_hz`, not from the style label (section 4 sweeps, tight base, seed 1):

| Field moved | Values | centroid Hz | hf_share_8k | t60_ms |
| --- | --- | --- | --- | --- |
| `bp_hz` | 800 / 1500 / 3000 | 1877 / 2678 / 4162 | 0.027 / 0.042 / 0.081 | 77 / 103 / 102 |
| `hp_hz` | 300 / 600 / 1200 | 2633 / 2678 / 2992 | 0.041 / 0.042 / 0.052 | ≈ 102 |
| `bp_q` | 0.7 / 1.6 / 6 | 3626 / 2678 / 2004 | 0.091 / 0.042 / 0.017 | 102 / 103 / 84 |
| `tail_decay_ms` | 40 / 90 / 300 | 2773 / 2678 / 2555 | 0.047 / 0.042 / 0.036 | 57 / 103 / 284 |
| `room` | 0 / 0.5 / 1.0 | 2678 / 2798 / 2669 | 0.042 / 0.047 / 0.042 | 103 / null / null |

Source and confidence: model only, one seed per sweep cell, no engine, no reference clap; low-medium confidence. The user's taste range for claps is unknown: **no clap reference audio exists in the repo**. If the user supplies a few claps (audio only, never names as targets), the same four features measured on them replace this whole table (H2).

## 3. Pitfalls found

- **P1 rise_time_ms.** Over seeds 1-8 the same parameters gave rise times from 0.06 ms to 16 ms (tight), up to 38 ms (default) and 59 ms (long). With noise bursts the 1 ms envelope peak can fall in the second or third burst, so the "peak" is not the first onset and 10 %-90 % reads the build-up to that later burst. Proposal for the audio-engineer: either measure the rise on the first burst only (window 0 to `burst_spacing_ms`) or leave `rise_time_ms` out of clap targets and use `t20` (time from the peak to -20 dB: model 1-13 ms tight, 4-50 ms long) as a hypothesis. To be decided on real renders.
- **P2 t60_ms null.** With `room` > 0 and `length_ms` close to the tail plus IR the envelope often does not reach -60 dB in the file (model: `null` for room 0.5 and 1.0 at length 300). The sidecar then holds `null`; tests must not compare it numerically.
- **P3 whole-file features hide time structure.** A burst-heavy front and a long tail can give the same centroid. A short-window centroid (first 30 ms versus 50-200 ms) is a possible extra measurement; not in the contract.

## 4. Hypotheses for the audio-engineer (test after C2)

All are hypotheses; "confirm" and "reject" refer to measurements on the real voice, not to sound.

| # | Hypothesis | Measurement | Confirms / rejects |
| --- | --- | --- | --- |
| H1 | The section 2 ranges hold on the engine voice, with seed spread as in the table | Render the styles with seeds 1-8, run the engine analysis, compare min..max | within 15 % of the model: confirm; otherwise replace the table with engine numbers |
| H2 | The user's taste range (once references exist) sits inside the contract ranges | Same four features on the user's reference claps (independent script as in test 3) | a reference outside every style box: the fields or ranges are too narrow (contract-change proposal) |
| H3 | `t60_ms` is monotone in `tail_decay_ms` and nearly independent of `bp_hz` | Sweep each over its full range, 8 seeds | rank correlation of t60 with `tail_decay_ms` above 0.95, with `bp_hz` below 0.3 |
| H4 | `bp_hz` moves centroid and HF share monotonically; `bp_q` moves them inversely (low Q = wider and brighter) | Sweeps as in section 2 | direction as in the table over 8 seeds |
| H5 | Burst count changes the front, not the level of the tail: more bursts give a longer onset time to full level, same t60 | `bursts` 1-6 at fixed tail: onset-to-peak time (first-burst window), t60 | t60 constant within 10 %; time of the last burst onset equals (bursts - 1) x spacing |
| H6 | `burst_decay_ms` above `burst_spacing_ms` makes bursts overlap and raises the burst-region RMS relative to the first 5 ms | RMS 0-`bursts` x spacing versus peak, `burst_decay_ms` 5 / 23 / 60 | RMS ratio rises with decay |
| H7 | `room` raises the energy after 150 ms without moving the first 30 ms (with `hp_hz` fixed) | Energy 0-30 ms and 150 ms-end for `room` 0 / 0.3 / 0.6 | first-30 ms energy within 1 dB, late energy rises |
| H8 | `drive` raises `hf_share_8k` and centroid | `drive` 0 / 0.3 / 0.6, aliasing bound as for the kick (-68 dB) | direction holds, alias bound met |
| H9 | The "layered" style (sum of two renders) has a lower comb risk than the clap + snare layer in V8: band energy with each layer on and off differs by less than 3 dB in 400-3000 Hz | Kick-gen2 layer phase check, seeds 1-8, polarity +/- | all within 3 dB: layering safe without alignment; otherwise add an explicit layer offset field (proposal) |
| H10 | Seed variants of one preset stay inside one style box | `variants` 4-8 on each preset: centroid, HF share, t60 | spread no larger than the seed spread in section 2; a variant outside the box means the variant spread is too wide |
| H11 | The clap sits below the kick in the 40-120 Hz band at the planner's level (-5 LU against the kick, musical note H4) | Band energy below 150 Hz of the clap as a share of its total; the contract's `hp_hz` minimum is 100 Hz | share under 0.01 at `hp_hz` 450: confirm (no sub content to fight the kick) |

## 5. Listening-test plan (for the C3 render step)

Rendered by the audio-engineer (script + guide under `docs/setup/LISTENING_TEST_*.md`), answers decoded by the lead. Same method as test 3: identical control pair, blind names, A/B positions mixed by a fixed seed, German answer sheet, key file `Schluessel.md` opened after the test, "kein Unterschied" always allowed.

**Common setup.** 4 bars at 136 BPM (as test 3), mono 48 kHz / 24-bit, `dense` kick on every beat, clap on beats 2 and 4 (**G** convention, musical note 3.3), each hit cut at 1 beat with a 3 ms cosine fade (the long clap is cut at 2 beats: 882 ms). Peak at most -0.3 dBFS. **Level match within each item by RMS over 0-60 ms of the clap alone** (hypothesis: that window follows the bursts, not the tail; the lead checks that the louder files are scaled down, gains go in the key). Presets use the section 2 values; `seed` 1 unless stated. Warp off, project tempo 136 BPM, no master effects.

| Item | Files (blind) | Single question answered | Changed vs. tight techno |
| --- | --- | --- | --- |
| **C0** control | A = B, identical bytes (tight techno) | How often does a side get picked with no difference | none |
| **C1** style | A = tight techno, B = long trance | Which tail fits the kick pattern; does the shorter one lose something | whole style, section 2 |
| **C2** burst count | three files: `bursts` 1 / 3 / 6 (spacing 8, others as tight) | Rank "mein Clap"; is the best one too smeared, right or too hard | `bursts` |
| **C3** brightness | three files: `bp_hz` 1000 / 1500 / 2500 | Which one is too dark / too bright; which is right | `bp_hz` |
| **C4** room | A = tight techno, B = tight techno + `room` 0.4, `room_length_ms` 300 | Does the room help or get in the way of the kick | `room` |
| **C5** layer | A = tight techno, B = tight techno + wide clap (6 / 14 / 30 / 0.95, `bp_hz` 1200) at -6 dB, summed, normalised to -0.3 dBFS | Does B have something A lacks | second layer |
| **C6** variants | four seed variants of tight techno (`variants` 4) | Which sound like the same clap, which falls out | `variants` |

Blind-named files the user loads: C0 2, C1 2, C2 3, C3 3, C4 2, C5 2, C6 4 = **18**. Unique renders: **11**. The tight-techno render T (seed 1) is used 7 times under different blind names (C0 A and B, C1-A, C2 `bursts` 3, C3 `bp_hz` 1500, C4-A, C5-A) and C6 v0 is T as well (`variants` 4: v0 = the preset), so render it once and copy it. The other ten unique renders: (1) long trance, (2) `bursts` 1, (3) `bursts` 6, (4) `bp_hz` 1000, (5) `bp_hz` 2500, (6) tight + `room` 0.4, (7) tight + wide-clap sum (C5-B), (8-10) variants v1, v2, v3. Copies of T are the same render; only the per-item level-match gain may differ (so bytes can differ between items, but C0 A and B must be byte-identical); the key file lists which blind name is which render. The C5 sum is normalised to -0.3 dBFS and then RMS-matched to its partner T (0-60 ms, as above), like every other pair, so the sum may be scaled below -0.3 dBFS. Time: pairs about 1 minute each, the three-file items 2 minutes, set-up 2 minutes, one-minute break after C3: about 12 minutes. **Order:** C1 → C0 → C4 → C5 → C3 → C2 → C6 (the pair with the most likely audible difference first, control in the middle, rankings last).

**Aufbau (einmal, 2 Minuten):** Alle `*.wav` des Pakets in eine Audiospur laden, Warp aus, Projekttempo 136 BPM, jede Datei als Loop. Gleiche Lautstärke an der Spur, nichts auf dem Master. Die Dateinamen sind anonym. Schluessel.md erst nach dem Test öffnen.

| # | Frage (eine pro Block) | Antwortmöglichkeiten |
| --- | --- | --- |
| C1 | **Welche Clap passt besser zu deinem Kick-Muster?** Wenn die kürzere etwas verliert: was (ein Wort)? | A / B / kein Unterschied · Wort |
| C0 | **Welche Clap sitzt besser?** | A / B / kein Unterschied |
| C4 | **Hilft der Raum, oder stört er den nächsten Kick?** | hilft / stört / kein Unterschied (welche Datei: A / B) |
| C5 | **Hat eine der beiden etwas, das die andere nicht hat? Wenn ja, welche und was (ein Wort)?** | A / B / kein Unterschied · Wort |
| C3 | Drei Dateien (X, Y, Z). **Welche ist zu dunkel, welche zu hell, welche passt?** | z. B. X dunkel, Y passt, Z hell |
| C2 | Drei Dateien. **Sortiere von „mein Clap" bis „am wenigsten mein Clap".** Danach: **Ist die beste zu verschmiert, richtig oder zu hart?** | Reihenfolge, z. B. Y > X > Z · zu verschmiert / richtig / zu hart |
| C6 | Vier Dateien. **Welche klingen für dich wie dieselbe Clap? Welche fällt raus (wenn eine rausfällt)?** | Liste |

**Auswertungsvorlage (user fills in, or the lead copies it into #232):**

```
Test C3, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Pegel gleich gelassen: ja / nein
C1: ___   Verlust (Wort): ____
C0: ___   (A=B identisch; war die Antwort „kein Unterschied"?  ja / nein)
C4: ___   (hilft / stört / kein Unterschied)   Datei: ___
C5: ___   Wort: ____
C3: dunkel ___ ; hell ___ ; passt ___
C2: Reihenfolge ___ > ___ > ___    beste: zu verschmiert / richtig / zu hart
C6: gleiche Clap: ___ ; fällt raus: ___
Gesamt: Welche Datei des ganzen Tests ist „meine Clap"? ____ (oder „keine")
```

**How the lead reads the answers** (one listener, one session; decoded with the key):

| Answer | Reading | Next step |
| --- | --- | --- |
| C0 not "kein Unterschied" | The user picks a side without a difference | Weigh all pair answers against it; repeat the pair reversed before building on it |
| C1 long preferred, or short loses a word | Tail length matters to him | One preset per style stays; the word names the property to measure (t60, low-mid body) |
| C1 tight preferred, nothing lost | Tight is the default for techno; long stays an option | Trance preset still offered, no default change |
| C2 best = 1 or 6, or "zu verschmiert" / "zu hart" | `bursts` 3 is not at his optimum | One new preset with the neighbour value (inside the contract) |
| C3 "passt" is not 1500 | `bp_hz` default shifts toward his pick | New preset value, not a contract change |
| C4 "stört" or "kein Unterschied" | `room` stays an option, not a preset value | None |
| C4 "hilft" | Room in the preset | Candidate preset with `room` 0.4 |
| C5 B "hat mehr" with a word | Layering has value for claps | Contract-change proposal for an explicit layer field (offset, level); word names the property to measure |
| C5 "kein Unterschied" | No layer field needed in v0.1 | None |
| C6 one variant falls out | Variant spread too wide for that preset | Audio-engineer bounds the spread (H10) |

## 6. Not done and limits

- No file rendered, nothing heard; the C3 package is the audio-engineer's.
- Every number in section 2 and 4 comes from my own model with 8 seeds; no engine, no reference clap, no measurement on the user's material. The "layered" column rests on one sum of two renders, not a sweep.
- Snare, rim and clap + snare are not in v0.1; they are not covered.
- C5's -6 dB and the second layer are my choice, one of many (as K3 in test 3); "kein Unterschied" closes this one layer, not layering.
- Level match by RMS 0-60 ms is a hypothesis; loudness and perceived loudness differ, and the long clap carries more energy after 60 ms.
- The control pair is one trial; it shows a bias if the user picks a side, it cannot measure it.
- Open for the user: do you have a few clap files you like (audio only) for H2? Without them the style ranges stay a model.
