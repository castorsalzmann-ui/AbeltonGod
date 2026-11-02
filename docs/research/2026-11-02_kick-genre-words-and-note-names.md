# Research: genre words for kick prompts (techno, trance, rumble) and the note-naming table (#234)

- **Date:** 2026-11-02 · **Role:** sound-designer + researcher · **Receiving issue:** #234 · **Status:** proposal for the user's decision. Docs only. Nothing here was rendered or listened to; every bundle is a **hypothesis, to be checked by ear**.
- **Builds on:** [keyword vocabulary (#226, PR #228)](2026-11-02_kick-keyword-vocabulary.md) (weight scale, section 8 question 3 and 4), [kick-gen2 learnings](2026-10-28_kick-gen2-learnings.md) (taste range, rule "genre only as data on top of one parameter space"), `contracts/kick-params.schema.json` v0.3 (`tail_note` 23-46).
- **Labels:** *sourced* = a page I opened says it. *derived* = my arithmetic or inference. *unverified* = from my background knowledge or a page I could not open; do not rely on it.

## 0. Decision summary

1. **Genre sources are thin and mostly tutorials, not measurements.** The only numbers I could source: techno body peak ~65 Hz and click boost ~3.5 kHz, a sub that fills about half a beat, rumble = long-decay kick into a heavily wet, low-passed reverb. **Nothing sourced for trance kick numbers** (sample-pack text only says "drive and clarity", no figures). So the `trance` bundle is the weakest of the three.
2. **Genre words become bundles of the eight vocabulary keywords plus slots, stored as data** (learnings rule). Bundles below are proposals; two of three use the `note`/`beats` slots rather than invented weights.
3. **Reference tracks: none named here.** I found no source that ties a specific track to a measured kick, and naming tracks from memory would be unverified. I list sourced tutorials and one commercial trance pack as listening/measuring references; **the user names 2-3 kicks per word** (open question 1), which the audio-engineer or I then measure with the existing independent method (no audio in the repo).
4. **Camelot mapping is defined, not guessed (section 4):** the Camelot code names a *key*; the kick root is the key's **tonic** (mode ignored); the octave is the one whose note lies in 27-38 (closest to 52 Hz). One code = one `tail_note`. Pitch-class input (`note:Am`, `key:8A`) avoids the octave-name confusion.
5. **Open questions: 3** (section 6).

## 1. Measurable characteristics per genre word

| Word | Characteristic | Value | Label / source |
| --- | --- | --- | --- |
| techno | body peak | around 65 Hz; sine layer tuned to the song key nearest 65 Hz | sourced: [musicguymixing, Techno Kick EQ](https://www.musicguymixing.com/?p=1616) |
| techno | click / transient | boost ~3.5 kHz by 1-3 dB; mud cut ~400 Hz | sourced: same page |
| techno | layer split | sub low-passed at 120 Hz, body band 120-400 Hz, top above 400 Hz; sub trimmed to "about half of the beat" | sourced: [Audiotent, Anatomy of the Techno Kick](https://www.audiotent.com/blogs/production-tips/anatomy-of-the-techno-kick) (no ms values given) |
| techno | decay at 130 BPM, half a beat | 60000 / 130 / 2 = 231 ms | derived (reading "about half the beat" as a length) |
| techno | tempo | 128-135 BPM in the rumble tutorial | sourced: [Attack, Beat Dissected: Dark Techno Rumble](https://www.attackmagazine.com/technique/beat-dissected/dark-techno-rumble/) |
| rumble | construction | a second kick with longer decay and much low end, long-decay heavily wet reverb, low-pass on the reverb send (darker), saturation, sidechain pumping | sourced: Attack page above (no cutoff, no decay time given) |
| rumble | filter / EQ numbers | Auto Filter at 96.6 Hz after a 100 % wet convolution reverb; notch 135 Hz; mono below 120 Hz | sourced: [MusicRadar, rumbling techno kick](https://musicradar.com/how-to/rumbling-techno-kick) (reverb decay and saturation values not given) |
| trance | kick numbers | none found | **not established.** [Zenhiser Kick Masters Trance](https://rekkerd.org/zenhiser-kick-masters-trance/) is a 200-kick pack described as "drive and clarity", no figures |
| psytrance (adjacent) | kick/bass | kick EQ cut where it clashes with bass, "often in the 100-500 Hz range"; bass in 16th notes | sourced: [soundbridge, mixing kick and bass](https://www.soundbridge.io/mixing-kick-and-bass). Psytrance is not trance; listed only because it is the only trance-family source that gave anything |
| all | "tuning" | no per-genre tuning rule found; the measured taste range (all genres mixed, 77 files) is 45-60 Hz, median 53 Hz | learnings section 2 |

Things I could not open or that held no usable numbers: Elektronauts "Psytrance kick bass parameters" (header only), the Native Instruments thread (no figures). Typical trance claims (offbeat bass, 125-140 BPM, kick "longer and more tonal") are **unverified** background knowledge and are not used below except as labelled.

## 2. Reference material (listening and measuring, nothing committed)

| Word | Sourced references | Needed from the user |
| --- | --- | --- |
| techno | Audiotent and musicguymixing pages (section 1) as recipe references | 2-3 kicks (audio) you call "techno" |
| rumble | Attack "Dark Techno Rumble" tutorial and the MusicRadar rumble tutorial (steps, no audio) | 2-3 kicks you call "rumble" |
| trance | Zenhiser Kick Masters Trance (commercial pack, vendor text only; I did not hear it) | 2-3 kicks you call "trance" |

Method once audio exists (derived, reuses vocabulary section 6): crest 0-100 ms, sub share 0-100 Hz and 0-150 ms, body level 80-300 Hz, click-zone level, time to -40 dB (own 5 ms RMS from onset), tail fundamental, tail harmonic ratio. Reference audio is measurement input only; file and pack names carry no meaning (learnings rule 9).

## 3. Proposed bundles (weight scale of the vocabulary; proposals, not rendered)

Weights as in vocabulary section 2 (1 = `dense`). Unmentioned = `dense`. Each line says what it rests on.

| Word | Bundle (proposal) | Rests on |
| --- | --- | --- |
| `techno` | `note:36, punch:1.2, click:1.2, bite:1.1, bpm:130 beats:0.5` | note 36 = C2 = 65.41 Hz (sourced ~65 Hz body; **outside** the 45-60 Hz taste range, so check by ear, alternative `note:34`); click/bite from the 3.5 kHz boost; `beats:0.5` from "sub fills half a beat" (the -60 dB rule in the contract must accept it; `tail` is then ignored). Steps 1.2/1.1 are guesses |
| `rumble` | `lang, dunkel, click:0.5, drive:1.2, note:32` | tutorials: long decay, darker, saturated (sourced); weights are the vocabulary's section 8 approximation (`lang` = tail 1.6, `dunkel` = bright 0.4). **The real rumble (noise or reverb tail) needs the new `rumble_*` parameters of vocabulary section 5**; this bundle only lengthens a sine. `drive:1.2` is my guess |
| `trance` | **no bundle proposed.** If one is wanted before sources exist, the only grounded direction is the learnings rule P6 (cause to effect): faster tempo means shorter decay and brighter click, and a kick that carries the bass is more tonal and driven; that gives a *guess* `tail:0.8, click:1.1, drive:1.1` which I would not ship without the user's 2-3 reference kicks | learnings P6 (derived from the user's old prototype); unverified for trance |

Checks the audio-engineer can do without ears (derived): each bundle stays inside the contract ranges; `techno` with `beats:0.5` at 130 BPM gives 231 ms and must decay 60 dB inside it (contract rule), otherwise the engine rejects it with a message that names the allowed range. I did not run it.

Rule kept from the learnings: the best-balanced kick stays reachable without any genre word; bundles are starting points, any single weight can still be overridden after the genre word.

## 4. Note names and Camelot keys to `tail_note`

**Definitions.**
- `tail_note` is a MIDI number, 12-tone equal temperament, note 69 = 440 Hz: `f = 440 * 2^((n-69)/12)` (contract text; standard definition). 23-46 = 30.87-116.54 Hz; 32 = 51.91 Hz.
- **Octave names differ.** The MIDI Association states only that note 60 is middle C and that it may be labelled C3, C4 or C5 depending on convention ([MIDI.org thread](https://midi.org/community/midi-specifications/midi-octave-and-note-numbering-standard)). Scientific pitch notation: 60 = C4, so 32 = G#1. The contract says Ableton calls 60 "C3" (then 32 would show as G#0); **I could not confirm Live's label from a source** (an Ableton forum thread contradicted itself), so: **unverified, check in Live's piano roll.** The table therefore uses scientific names (60 = C4).
- **Camelot wheel** (Mixed In Key notation): number 1-12 plus letter A = minor, B = major; the same number with the other letter is the relative key (8A = A minor, 8B = C major) ([Mixed In Key](https://mixedinkey.com/?p=7073)). The wheel names a **key** (tonic plus mode), not a single note.
- **Mapping used here (definition, not a fact about music):** the kick root is the **tonic** of the key. Mode is ignored, a kick has no third. 8A -> A, 8B -> C. Relative pairs (8A/8B) therefore give different roots (A and C). The octave is the one whose note lies in **27-38** (closest to 52 Hz = note 32.03, one octave window), so every pitch class gives exactly one `tail_note`.

| Root | `tail_note` | Hz | Scientific name | Minor code (A) | Major code (B) | In 45-60 Hz taste range? |
| --- | --- | --- | --- | --- | --- | --- |
| D# / Eb | 27 | 38.89 | D#1 | 2A | 5B | no (low) |
| E | 28 | 41.20 | E1 | 9A | 12B | no (low) |
| F | 29 | 43.65 | F1 | 4A | 7B | no (3 % under 45) |
| F# / Gb | 30 | 46.25 | F#1 | 11A | 2B | yes |
| G | 31 | 49.00 | G1 | 6A | 9B | yes |
| G# / Ab | 32 | 51.91 | G#1 | 1A | 4B | yes (the `dense` area) |
| A | 33 | 55.00 | A1 | 8A | 11B | yes |
| A# / Bb | 34 | 58.27 | A#1 | 3A | 6B | yes |
| B | 35 | 61.74 | B1 | 10A | 1B | no (just above) |
| C | 36 | 65.41 | C2 | 5A | 8B | no (above; equals the sourced techno ~65 Hz) |
| C# / Db | 37 | 69.30 | C#2 | 12A | 3B | no (above) |
| D | 38 | 73.42 | D2 | 7A | 10B | no (above) |

All 24 Camelot codes appear exactly once. Hz values are computed from the formula above (python, 2 decimals). The other octave of each pitch class is also valid (23-46 holds each pitch class twice), reachable by number.

**Proposal for the vocabulary slot:** accept (a) a number `note:32`, (b) a note with scientific octave `note:G#1`, (c) a pitch class `note:Am` / `key:8A`, resolved by the window 27-38 above. The response always prints number, Hz and scientific name, so any octave mix-up is visible. (c) needs no octave convention at all.

## 5. Limits

- Genre numbers come from tutorials (opinion, not measurement); none from audio I analysed. Techno ~65 Hz and the 45-60 Hz taste range disagree; the taste range comes from the user's picks and wins until the user listens.
- Mixed In Key's table is the one Camelot source I read; the tonic rule is my definition.
- Nothing was rendered, so no bundle has a measured value. Whether `techno`, `rumble`, `trance` sound like their word is for the user's ears.

## 6. Open questions for the user

1. Name 2-3 kicks (audio) per word, so bundles are measured from content, not tutorials. Until then `trance` stays empty.
2. Should `techno` follow the sourced 65 Hz (note 36, outside your 45-60 Hz range) or stay in your range (note 34)?
3. Which octave name should answers show: scientific (60 = C4) or Ableton's? Check once in Live's piano roll and tell me what note 60 is called.
