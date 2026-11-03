# Plan: a deterministic Goa lead / bass / pad voice — measurable targets, WAV versus MIDI split, listening tests, open questions

_Date: 2026-11-03 · Refs #338 (Goa, synth voices follow G1) · Role: sound-designer · Docs only: no code, no contract, no decision changed. Nothing here was rendered, nothing was run in Live, nothing was heard. I ran no analysis command for this note; the only numbers I computed are arithmetic (labelled). Every range is a **hypothesis** for the user's ear, not a finding. No statement about how anything sounds, and no statement about what Live does beyond what the two input notes document._

Labels: **documented** = stated in an input note or in repo code I read today (file named); **inferred** = my reasoning; **not established** = no source or test; **hypothesis** = a proposal to be confirmed or rejected by measurement or by the user.

Read for this note: `CLAUDE.md`; [Goa musicology and sound (G1)](2026-11-03_goa-trance-musicology-and-sound.md); [Goa arrangement delivery to Live (G3)](2026-11-03_goa-arrangement-delivery-to-live.md); issue #338 (body, no comments); `src/audio_engine/bass.py` and `contracts/bass-params.schema.json` (on `origin/main` 1deb07e); the header of `src/audio_engine/goa_patterns.py`; the [bass targets note](2026-11-02_bass-targets.md) (section 1 only). Not repeated from them: the sources, the scale table, the `goa_line` format (superseded by `goa_patterns.py`, see its header), the arrangement template.

## Short version

1. **The repo already has a bass voice** (`bass.py`, contract `bass-params` v0.1): additive saw/square/sine/sub-octave, 2nd-order high-pass, a low-pass with a per-note exponential cutoff envelope and resonance, gate, drive. G1 section 3.1 omits `bass.py` and treats the rolling-bass voice as still to be built; that row is out of date (documented: `bass.py` module docstring). A rolling-bass one-shot is therefore a **parameter-range question, not a new engine**, as far as the contract ranges reach (section 3).
2. **No lead or pad voice exists.** Lead needs: pitch range above the bass contract (`note` max 55 = 196 Hz), unison with detune, glide, accents. Pad needs a long attack (`amp_attack_ms` max 30 ms in the bass contract) and a slow, wide, low-level stationary body. Both would be new voices with new contracts (`contract-change` issues; section 6).
3. **The cutoff sweep over 8-32 bars has no representation in a one-shot.** The `bass-params` cutoff envelope is per note and decays; a bar-scale sweep (G1: "filter cutoff as an instrument") is either baked into a rendered loop (new engine work) or drawn by the user in Live (G3: filter automation write is not a `tested` capability; CC-to-parameter mapping not established).
4. **Recommended split (hypothesis, for the user to confirm):** notes, rhythm, accents, slides and arrangement go as MIDI (existing `goa_patterns.py` + `arrangement_midi.py`); the **rolling-bass one-shot** and **sub drone** can be rendered now with the existing bass voice for A/B against a Live-synth recipe; **lead, pad, pluck and riser** are MIDI + recipe first and rendered only after the user names references and decides that a fixed rendered sound is wanted.
5. **Measurable targets exist as quantities and methods, not as taste ranges.** G1 found no published numeric Goa target for lead, bass, sweep or pad; the user has given no Goa reference audio. Section 2 therefore fixes (a) engine-correctness checks that do not need taste and (b) starter windows that the references (section 5) must replace.
6. **Blocker for any taste claim:** Goa reference audio from the user (open question 1).

## 1. What is documented about the inputs (so nothing is re-derived)

| Item | Documented in | Consequence here |
| --- | --- | --- |
| Live 12 Standard has Drift, Analog, Simpler, Collision, Electric, Tension, Drum Synths; Operator, Wavetable, Sampler, Meld, Max for Live are Suite-only; Echo and Roar: Standard status **not established** | G1 section 4.1 (Ableton edition page via a summarising fetch tool; one-minute check by the user recommended) | Recipes name only Drift and Analog in detail. Echo/Roar are not used in any recipe; Delay and Reverb are. |
| Drift: Osc 1 Sine/Triangle/Shark Tooth/Saturated/Saw/Pulse/Rectangle, Osc 2 with Detune, Type I 12 dB/Type II 24 dB filter, Mono/Poly/Stereo/Unison modes with Thickness, Legato, Glide; no separate sub-oscillator in the text read | G1 4.2 | Sub drone on Drift = a second MIDI track or a Drift sine layer; not established whether one Drift instance can do saw + sub |
| Analog: 2 oscillators, Sub level one octave below, Detune up to 300 cents, 2nd/4th-order filters, Unison 2 or 4 voices, Glide with Legato, Env < Vel | G1 4.2 | Closest single device to the saw + sub + low-pass + unison plan |
| Collision, Electric, Tension, Simpler: only their **edition membership** is documented | G1 4.1 | Their parameter sets, and whether any of them suits a Goa pluck, pad or lead, are **not established** (not read in G1 or G3). I do not recommend a patch on them. See section 4. |
| A `.mid` carries notes and velocity; per-parameter automation written to a clip is not a `tested` capability | G3 findings 4-6, section 4; G1 4.3 | Cutoff movement, accents lifting cutoff, and glide depend on the device and on the user |
| Multi-track SMF drag-in is the delivery route; its Live behaviour (track names, tempo, markers, empty tracks) is unverified until T1-T8 | G3 section 5 | The whole MIDI half of this plan inherits "not verified in Live" |
| `goa_patterns.py` writes `acid_line` dicts for `bass`, `lead`, `arp` | file header | The note-side generator exists; the sound side is what this plan covers |
| Bass voice: saw/square/sine/sub-octave levels, `hp_hz` 20-120, `lp_hz` 60-4000, `lp_q` 0.5-6, `lp_env_amount` 0-4 (octaves), `lp_env_decay_ms` 5-800, `gate_ms` 50-1500, `amp_attack_ms` 0.5-30, `note` 24-55, `drive` 0-1; partials limited to `k f0 < 0.45 sr`; no randomness (`seed` only labels the render) | `bass.py`, `bass-params.schema.json` | Everything in section 3 that says "inside the contract" is checked against this list |

## 2. Measurable targets

### 2.1 Class A: engine-correctness targets (need no taste; any new voice must pass them)

These are checks the engine or a test can assert. Method notes follow the kick/bass pitfalls (stationary windows, 4x-rate render for aliasing, peak not 1 ms RMS for attack); I have not re-measured any of them today.

| ID | Target | Method (independent of the code under test) | Pass condition (proposal) |
| --- | --- | --- | --- |
| A1 | Same params + seed give identical bytes | render twice, compare file hashes; on Windows too (G1 3.1: byte identity of float loops is a stated risk) | identical on one platform; cross-platform status reported, not assumed |
| A2 | Pitch accuracy of a held voice | long-window spectral peak and autocorrelation on a stationary window, compare both; reference computed in the test from `440 * 2^((n-69)/12)` | within 5 cents (G1 3, "engine claim") |
| A3 | No aliasing foldback in the saw/lead stack | render at the target rate and at 4x; compare energy in bins that fold; arithmetic: at 48 kHz the partial limit is 0.45 sr = 21 600 Hz, so a 440 Hz saw has 49 partials and a 98 Hz bass 220 | foldback below a threshold the audio-engineer sets from the 4x comparison (no value proposed without a measurement) |
| A4 | Start and end click | largest sample-to-sample step in the first and last 5 ms against the stationary peak (bass targets Q9) | first and last sample 0, as in `bass.py` |
| A5 | Unison determinism | N voices with fixed cent offsets and phases from a seeded generator; same seed same bytes; different seeds differ only in starting phase | A1 plus a test that detune offsets equal the parameter |
| A6 | Level headroom | peak on the quantised file against `peak_ceiling_dbfs` | as `bass.py` |
| A7 | Cost | wall time to render a 2-bar loop and a 32-bar stem on the user's PC | reported; G1 measured only a plain biquad on the sandbox (0.38 microseconds per sample), **not established on the user's PC** |

### 2.2 Class B: sound-character quantities (starter windows = hypotheses, from G1 section 3)

The quantity and method are proposals; the window is a search window for engine tests and the first listening round. **None of these has a Goa source** unless the "Source" column names one.

| Voice | Quantity | How measured | Starter window | Source | Moves with |
| --- | --- | --- | --- | --- | --- |
| Rolling bass | gate as fraction of one 16th (107.1 ms at 140 BPM, arithmetic) | `gate_ms` over `60000 / (4 bpm)` | 0.6-1.0 | one tutorial ("one sixteenth per hit", G1 finding 8); fraction inferred | `gate_ms`, `release_ms` |
| Rolling bass | filter-closing time | centroid of the first 30 ms falling to the stationary centroid | 2-40 ms | same tutorial ("a few milliseconds"); upper end inferred | `lp_env_decay_ms` (contract minimum 5 ms) |
| Rolling bass | first roll note against the others | dB, from velocity profile or rendered level | -12 to 0 dB | same tutorial ("played quieter") | MIDI velocity, not an engine field today (`goa_patterns.py` does not implement it, per its header) |
| Rolling bass | fundamental, kick relation | spectral peak versus the user's kick tail (median 53 Hz in the user's kicks, kick learnings section 2) | `note` 24-36 for a drone, bass note per user | G1 3 (register inferred) | `note`, `hp_hz` |
| Acid / lead | filter envelope decay after an accented note | centroid decay time | 80-400 ms | none | `lp_env_decay_ms` (contract allows 5-800) |
| Acid / lead | resonance bump over the harmonic envelope | dB of the peak over the surrounding harmonics | 3-18 dB | none | `lp_q` (contract 0.5-6; the mapping from Q to dB is **not established**, to be measured once) |
| Acid / lead | accent lift | level and cutoff difference accented versus normal | +3 to +8 dB, +0.5 to +2 oct | none | not in the bass contract (no per-note accent) |
| Acid / lead | slide time | glide ms between slid notes | 30-120 ms | none | not in the bass contract (no glide) |
| Lead | unison voices, detune | count, cents between voices | 3-7 voices, 5-25 cents | none (Analog detune range is a device limit only) | new voice |
| Lead | second oscillator offset | semitones | 0 or +7 | one tutorial (chord stabs) | new voice |
| Pluck | amplitude and filter decay | ms | 80-400 / 60-300 | none | `lp_env_decay_ms`, `gate_ms` |
| Pad | attack, stationary centroid, width | ms, Hz, correlation between channels | attack 200-1500 ms | none | new voice (bass `amp_attack_ms` max 30 ms) |
| Sweep | centroid slope over the sweep | Hz per bar of the stationary centroid across a loop | no window proposed | none | needs time-varying cutoff across bars |
| Riser | length, centroid slope | bars, Hz per bar | 4-16 bars | one tutorial (build-ups of 8, 16, 32 bars) | new voice |

Hypotheses attached to the table (each with the measurement that would confirm or reject it):

1. **H-voice-1: the existing bass contract covers a rolling-bass one-shot.** Confirm: render the contract corner cases for a 16th gate at 135-146 BPM (gate 50-1500 ms already allows 102.7-111.1 ms) and check A2, A4, Q5 (filter movement) from the bass-targets note. Reject: a needed value falls outside a range (candidates: `lp_q` above 6, `amp_attack_ms` below 0.5, per-note accent).
2. **H-voice-2: accent and slide are not expressible in a one-shot and must live in MIDI plus the Live device.** Confirm: the bass contract has no per-note field for them (documented). Whether a Live device realises "accent lifts cutoff" via velocity is **not established** (G1 4.3, "inferred, not tested").
3. **H-voice-3: a Goa lead is mostly a filtered saw stack whose character is decided by cutoff, resonance and sweep rate, not by the oscillator.** Confirm or reject only against references (section 5): compare centroid distributions of the references with centroids of a saw stack rendered at several cutoffs. Without references: **not established**.
4. **H-voice-4: the roll pattern (16th roll versus triplet gallop) matters more to "Goa" identity than the patch.** G1 finding 9: which rhythm 1990s Goa used is **not established**. Settled only by listening test T2 below and by references.

## 3. What can be rendered as WAV with the existing DSP

Read from `bass.py` and `dsp.py` (documented), not run today.

| Part | Existing building blocks | Gap | Verdict |
| --- | --- | --- | --- |
| Rolling-bass note one-shot (one 16th, saw + sine, fast low-pass envelope) | `render_bass` with `saw_level`, `sine_level`, `lp_hz`, `lp_env_amount`, `lp_env_decay_ms`, `gate_ms`, `hp_hz` | roll first-note level is a placement question; a 16th roll needs the notes placed on a grid (a Drum-Rack-like or Simpler-like player in Live, **not established**) or a rendered bar loop (new loop composer) | **Renderable now as one-shots.** Bar loops need a small new composer. |
| Sub drone (held sine, note 24-36) | `sine_level`, `sub_octave_level`, `gate_ms` up to 1500 ms | gate cap 1500 ms; a drone of one or more bars at 140 BPM is 1714 ms per bar (arithmetic: 4 x 60000 / 140) | One-shot up to 1.5 s only; a longer drone is a MIDI note on a Live synth or a loop with a loop point (Live behaviour on loops not established) |
| Acid / lead note (saw, resonant low-pass, accent) | partly: saw, resonant filter, per-note envelope | pitch above `note` 55, accent, glide, unison | New voice (needs `contract-change`) |
| Unison stack | `substreams(seed, n)` for seeded phases | none in the bass voice | New voice |
| Sweep over bars | `_lowpass_varying` (cutoff per sample, pure Python, direct form I) | cutoff law is the per-note exponential; a bar-scale law needs a new cutoff function and a loop renderer | New voice or new mode; cost estimate A7 |
| Pad | `amp_attack_ms` ceiling 30 ms | long attack, slow body, width | New voice, low value if a Live synth does it |
| Pluck | like the roll note with longer `lp_env_decay_ms` and `gate_ms` | pitch range | Renderable inside the bass range; lead range needs the new voice |
| Riser | noise, `biquad_bandpass` exist in `dsp.py` | swept centre, ramp, bar length | New voice |

Honest limit: the pure-Python per-sample filter loop makes long stems expensive (A7); a full-track stem is about 23 million samples at 48 kHz for 8:14 (arithmetic from G1: 288 bars at 140 BPM = 493.7 s, 493.7 x 48 000). Not measured on the user's PC.

## 4. What should be MIDI to Live's Standard devices

Scope of "recommended": hypothesis; the user decides after the ears step in section 6. Device behaviour beyond G1 section 4.2 is **not established**, and nothing here has been run in Live.

| Part | Route | Device (from the documented Standard list) | What remains unestablished |
| --- | --- | --- | --- |
| Rolling bass | MIDI from `goa_patterns.bass_line`; recipe on Drift (mono, saw, Type II low-pass, Env 2 short decay) or Analog (saw + Sub, 4th-order low-pass) | Drift or Analog | whether the Env/velocity mapping gives the accent the user wants; first roll note level (needs a velocity profile the generator lacks) |
| Sub drone | MIDI long notes, sine / Analog Sub | Analog (Sub level) or Drift sine | one Drift instance doing saw + sub: not established |
| Acid line (accent, slide) | `acid_line` MIDI, slide as overlap + glide | Drift (Mono, Glide) or Analog (Glide, Legato) | accent lifting cutoff: inferred, not tested; legato glide needs overlapping notes, G3 says Live behaviour for overlaps is unverified |
| Lead ostinato / arp | MIDI; unison via Analog Unison (2 or 4 voices) or Drift Unison | Drift or Analog | voice count and detune ranges: Analog Unison only 2 or 4 (documented), so 3, 5, 7 voices (section 2.2) is not reachable there |
| Pad | MIDI, long notes, long attack | Analog or Drift | none specific |
| Pluck / stab | MIDI, short filter envelope | Drift or Analog | none specific |
| Mallet / bell / metallic parts, if wanted | MIDI | Collision, Electric, Tension | **not established**: their capability is not documented in G1 or G3, and nothing in the Goa sources I was given asks for them. I list them only because the brief names them; no recipe proposed. |
| One-shot player for rendered WAVs (bass note, riser) | rendered WAV dragged onto a track; MIDI plays it | Simpler (Standard, documented) | whether Simpler suits one-shot bass notes, what pitch tracking it offers and how it handles retrigger: **not established**; to be checked by the user (T-S below) |
| Cutoff sweep | user-drawn automation, or baked loop | Auto Filter / device filter | writing automation into a clip: not a `tested` capability; MIDI CC mapping: not established |
| Delay / space | recipe only | Delay, Reverb (documented Standard); Echo: not established | none |
| Drift (Poly/Unison etc.) | edition membership documented | | Both Drift (Mono Glide) and Analog (Glide with Legato) document glide (G1 4.2); the Cycling '74 page says glide needs mono mode and legato playing (G1 4.2) |

## 5. Reference intake (replaces the hypotheses)

No Goa reference audio exists in the project yet (G1 blocker a). Protocol, using the stance of the kick/clap/hat reference notes (audio content only, no artist or track names as targets; references are measurement input, never copied):

1. The user supplies 3-5 audio files of the Goa sound they mean (any format the scratchpad tools read; WAV preferred), each tagged by the user as "bass-heavy", "lead-heavy", "full mix" or "isolated element". Isolated elements measure cleanly; full mixes only give tempo and coarse band balance (inferred).
2. I measure, in a scratchpad (never in the repo), and report with the commands: tempo (onset autocorrelation, cross-checked against a bar-count by ear of the user), kick-tail pitch where isolated, bass-note onset grid (16th occupancy per beat to settle the roll versus gallop question, finding 9), centroid and its distribution over time for lead material, level of the first roll note where bass is isolated, sweep length where a filter sweep is audible in the measurement. Anything not measurable from a full mix is reported as "not measurable here", not guessed.
3. The output is a short table per reference, then a proposed replacement of every Class B window in section 2.2; the windows stay hypotheses until two or more references agree.

The sound-designer cannot make that measurement from text sources; it waits on open question 1.

## 6. Listening-test plan (no predictions; every item is a question for the ear)

Aim: under 15 minutes. Two stages. Stage 1 runs on MIDI and Live's own devices and needs no new engine; stage 2 needs rendered bass one-shots, which the existing voice can produce (renders by the lead or the audio-engineer; the sound-designer lists the settings, does not render).

Stage 1, MIDI (Live 12.4.5, Drift or Analog; the generated files from `goa_patterns.py` / `arrangement_midi.py`; this stage is about rhythm and notes; the patch is the user's choice and the same for every item). All Live behaviour here is the user's to report; the plan assumes nothing.

| Order | Pair / set | Single question | Notes |
| --- | --- | --- | --- |
| S1 | Same line at 136 / 140 / 145 BPM | Which tempo is "Goa" to you? | same question as test G1 in the G1 note, section 7 |
| S2 | Bass roll: off-kick 16ths (generator default) versus off-beat 8th versus triplet gallop, kick present | Which rhythm do you mean by a Goa bass? | gallop and off-beat variants are not in `goa_patterns.py` today (its header lists only the off-kick roll); an issue for the audio-engineer if the user wants them. Until then S2 compares density settings of the one existing roll. |
| S3 | Same notes in aeolian / phrygian / harmonic minor / phrygian dominant | Which mode reads as Goa? | the generator supports the four scales (header) |
| S4 | Lead ostinato of 1 bar versus 2 bars, same scale | How long a repeat is wanted? | |
| S5 | Acid line: accents 0 / 0.25 / 0.5 of notes, slides 0 / 0.15 / 0.3 | What accent and slide density is wanted? | exact counts per bar (header) |
| S6 | Same 8-bar line, user-drawn cutoff sweep over 8 / 16 / 32 bars | How fast should the sweep move? | user draws; automation write is not a tested capability |
| S7 | Ears: Drift versus Analog with the same recipe | Which of the two should be the default patch? | open question 4 |

Stage 2, rendered bass one-shots (existing `bass-params` v0.1; settings are starter values from section 2.2, all inside the contract; rendering and placement by the lead or audio-engineer; same MIDI roll and same kick as stage 1 so only the sound changes).

| Order | Pair / set | Single question | Settings (hypotheses) |
| --- | --- | --- | --- |
| R1 | Gate 0.5 / 0.8 / 0.95 of a 16th at 140 BPM (about 54 / 86 / 102 ms, arithmetic) | How long should each roll note be? | `gate_ms` 54, 86, 102; all else equal |
| R2 | Filter closing time 5 / 20 / 60 ms | How fast should the pluck close? | `lp_env_decay_ms` 5, 20, 60 with `lp_env_amount` 2 |
| R3 | `lp_q` 0.9 / 2.5 / 5 | How much resonance? | `lp_q` 0.9, 2.5, 5 |
| R4 | With and without a held sub drone (a 1.5 s sine note, `note` 29) | Is a separate drone layer wanted? | drone gate capped at 1500 ms by the contract |
| R5 | Rendered one-shot bass versus Drift recipe bass, same MIDI | Does the user prefer the fixed rendered sound or the live synth? | answers whether rendered voices are worth building beyond the bass |

A-B order is blind and randomised by the lead; the user answers one line per item (pick, or "no preference"). No result is assumed.

User check list for edition facts (2 minutes, not a listening test): (T-E) open Live's browser and report whether Operator, Wavetable, Sampler, Meld, Echo and Roar are present; (T-S) drag one rendered one-shot onto Simpler and report whether it plays and pitches from MIDI notes. These settle G1's open edition fact and the "one-shot player" row in section 4.

## 7. Proposed follow-up issues (proposals; the lead files them)

1. **audio-engineer, small:** a bar-loop composer that places rendered bass notes on the 16th grid with a per-note velocity profile (also closes the "first roll note quieter" gap listed in `goa_patterns.py`). Needs no contract change if it only calls `render_bass`.
2. **audio-engineer, small:** extra roll patterns (off-beat 8th, gallop, full 16th) in `goa_patterns.py` only if listening item S2 shows the user wants them.
3. **contract-change (audio-engineer):** a `lead-params` v0.1 only after reference intake (section 5) and the stage-2 answers; proposals for fields come from section 2.2, none until then.
4. **researcher:** read the University of Helsinki copy of the thesis for scales and bass rhythm (G1 gap) and open Live's Instrument Reference for Collision, Electric, Tension, Simpler (parameters not read in G1/G3).
5. **side-finding candidate:** G1 section 3.1 omits `bass.py` and treats the bass voice as still to be built; `bass.py` exists. Only a doc nit, listed here so it is not lost.

## 8. Open questions for the user

1. Which 3-5 Goa audio files are the reference (any file you can share; measured only, never copied)? Which of them have an isolated bass or lead?
2. Should Goa lead and bass stay MIDI into Live's own synths (editable by you), or do you want fixed rendered sounds (a WAV you cannot re-patch)? Stage 2 item R5 informs this.
3. Default synth for the recipes: Drift or Analog (S7)?
4. Which rolling-bass rhythm do you mean by Goa: the off-kick 16th roll, the off-beat 8th, or a triplet gallop (S2)?
5. Is the DJ-friendly intro/outro required, or an authentic long build (G1 open question 2)?
6. Does your Live 12.4.5 Standard really lack Operator and Wavetable (T-E)? Is Echo present?
7. Is a long render time acceptable for a baked 32-bar loop (A7)?

## 9. Limits of this note

- No taste range exists; Class B windows are G1's starter windows and inherit its weaknesses (one tutorial per number, several uncited).
- Device capabilities for Collision, Electric, Tension and Simpler are **not established**; Drift and Analog capabilities are second-hand from the G1 summary of the Live manual.
- Nothing was measured on rendered audio; nothing was heard; nothing was run in Live. G3's T1-T8 still decide whether the MIDI delivery route works as described.
- `goa_patterns.py` was read only through its module header; behaviour beyond that is not claimed.

## State update proposal (for the PR body; the lead edits `CURRENT_STATE.md`)

- Goa synth-voice plan written: `docs/research/2026-11-03_goa-synth-voice-plan.md` (Refs #338). Correction recorded: a bass voice exists (`bass.py`); G1 section 3.1 omits it and treats the voice as still to be built.
- Known gap: no Goa reference audio; no lead/pad voice or contract; automation write to Live not available.
- Next: user answers section 8 and names references; then the follow-up issues in section 7.
