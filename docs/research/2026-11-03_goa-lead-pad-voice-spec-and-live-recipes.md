# Goa lead / pad / pluck voice: measurable spec for our own DSP, plus Drift and Analog patch recipes and a user test plan

_Date: 2026-11-03 · Refs #338 · Decision context: D-026 (Goa go; MIDI into Live's own synths is the primary route, Drift default, Analog second; a lead/pad audio voice waits for this spec and a user listening round) · Role: sound-designer · Docs only: no code, no contract, no decision changed._

_Nothing here was rendered, nothing was run in Live, nothing was heard. I ran no analysis; the only numbers I computed are arithmetic (labelled). Every range and every recipe value is a **hypothesis / starting point**. No statement is made about how anything sounds._

Labels: **documented** = stated by a page I opened (named) or by repo code I read today; **inferred** = my reasoning; **not established** = no source or test; **hypothesis** = a proposal to be confirmed or rejected by measurement or by the user.

Read for this note: `CLAUDE.md`; `docs/DECISIONS.md` D-026; [voice plan](2026-11-03_goa-synth-voice-plan.md) (sections 2-4 especially); [Goa musicology and sound (G1)](2026-11-03_goa-trance-musicology-and-sound.md); `src/audio_engine/dsp.py` and the function list of `src/audio_engine/bass.py`; `contracts/bass-params.schema.json`; header of `src/audio_engine/goa_patterns.py`. Not repeated: the Goa sources, scale table, arrangement template, measurement pitfalls (see the voice plan and the kick learnings).

Manual pages opened with WebFetch on 2026-11-03 (a small model summarises each page; names below are as that summary quoted the manual; the last ~7 000 characters of each manual page were not read):

- [Live 12 manual: Live Instrument Reference](https://www.ableton.com/en/live-manual/12/live-instrument-reference/) (Drift 31.3, Analog 31.1)
- [Live 12 manual: Live Audio Effect Reference](https://www.ableton.com/en/live-manual/12/live-audio-effect-reference/) (Auto Filter, Delay; Reverb and Saturator sections were in the unread tail)
- [Ableton: compare editions](https://www.ableton.com/en/live/compare-editions/) (first 100 000 of 128 256 characters)

## Short version

1. **Part 1 (spec):** a lead/pad/pluck voice needs eleven blocks; `dsp.py` has the filters and the oversampling helpers, `bass.py` has a per-sample varying low-pass and an additive saw, but there is no unison, glide, long-attack envelope, LFO, noise sweep or stereo block (section 1.3). Everything in the spec is a **PROPOSAL ONLY**; no contract is changed by this note.
2. **Part 2 (recipes):** five recipes (lead, acid bass, pluck, pad, riser) on Drift, three of them also on Analog, parameter by parameter. Every value is a starting point, **not tested in Live, not heard**. Control names come from the manual summary; units that the manual did not state are marked "unit not established".
3. **Edition facts re-checked, one changed:** Drift and Analog are in Standard (documented). Auto Filter, Delay, Reverb, Chorus-Ensemble, Saturator, EQ Eight are Standard (documented, compare-editions). **Echo: this pass read Echo as Suite-only (x for Standard), contradicting the "not established" in G1/voice plan; because both are summarised reads it stays "not established" and no recipe uses Echo.** Roar: not mentioned in the part read: not established, not used.
4. **Gap that limits the riser and the sweeps:** the audio-effect page summary does not say that Auto Filter's `Freq` accepts automation; drawing automation by hand in Live is a user action this note does not verify; **our writing automation into a clip is not a `tested` capability** (voice plan section 4).
5. **Part 3 (test plan):** about 12 minutes, five blind items, all questions, nothing assumed.

---

## 1. Spec for a deterministic lead / pad / pluck voice (PROPOSAL ONLY)

Purpose: a later `lead-params` voice that our own DSP could render as a WAV one-shot (pluck, stab, short lead note) or a baked loop. D-026 keeps MIDI + Live synths primary; this spec exists so that the decision "render it ourselves" can be taken after the user's listening round, with ranges already written down. **None of it is a contract.** A `contract-change` issue is needed before any field is used (CLAUDE.md, contracts).

### 1.1 Parameter list (PROPOSAL ONLY; ranges are search windows, not taste claims)

Naming follows `bass-params` where the meaning is the same (shared fields: `seed`, `variants`, `bpm`, `sample_rate`, `bit_depth`, `drive`, `polarity`, `offset_ms`, `peak_ceiling_dbfs`, `preset`, `note`, `cents`, `hp_hz`, `lp_hz`, `lp_q`, `lp_env_amount`, `lp_env_decay_ms`, `gate_ms`, `release_ms`, `amp_attack_ms`). Starters are the voice-plan / G1 section 3 windows; "none" = no source.

| Group | Field | Range (proposal) | Default (proposal) | Basis |
| --- | --- | --- | --- | --- |
| Pitch | `note` | 36-96 (MIDI; bass contract stops at 55) | 60 | inferred: the lead must sit above the bass contract's note 55 (196 Hz) |
| Pitch | `cents` | -50..50 | 0 | as bass |
| Pitch | `glide_ms` | 0-300 | 0 | G1 3: slide 30-120 ms, no source |
| Pitch | `glide_from_semitones` | -12..12 | 0 | needed to render a slid note as a one-shot; none |
| Oscillator | `saw_level`, `square_level`, `sine_level` | 0-1 each | 0.7 / 0 / 0 | as bass (sine-series oscillators) |
| Oscillator | `osc2_semi` | -12..12, integer | 0 | G1: +7 for stabs (Bonedo #2, one tutorial) |
| Oscillator | `osc2_level` | 0-1 | 0 | none |
| Unison | `unison_voices` | 1-7 | 1 | G1: 3-7, none; Bonedo gives no count |
| Unison | `unison_detune_cents` | 0-30 | 0 | G1: 5-25 cents, none |
| Unison | `unison_spread` | 0-1 (stereo; 0 = mono) | 0 | inferred; stereo output is **new** (bass is mono) |
| Filter | `hp_hz` | 20-1000 | 20 | extends the bass range |
| Filter | `lp_hz` | 100-12000 | 2000 | sustained cutoff; none |
| Filter | `lp_q` | 0.5-12 | 0.9 | bass contract stops at 6; G1: bump 3-18 dB; the Q-to-dB mapping is **not established** |
| Filter | `lp_env_amount` | 0-5 octaves | 2 | extends bass (0-4) |
| Filter | `lp_env_decay_ms` | 5-2000 | 150 | G1: acid 80-400, pluck 60-300 |
| Filter | `lp_hz_end` | 100-12000, optional | absent | start/end of a bar-scale sweep for baked loops (`sweep_bars` must be set) |
| Filter | `sweep_bars` | 0-32 (0 = off) | 0 | G1: 8-32 bars; only meaningful with `bpm` and a loop renderer |
| Amplitude | `amp_attack_ms` | 0.5-2000 | 3 | pad needs 200-1500 (G1), none |
| Amplitude | `amp_decay_ms`, `amp_sustain` | 5-2000 / 0-1 | 400 / 0.7 | pluck: 80-400 ms (G1) |
| Amplitude | `gate_ms` | 50-8000 | 250 | bass stops at 1500; a pad note of 2 bars at 140 BPM is 3428.6 ms (arithmetic: 8 x 60000 / 140) |
| Amplitude | `release_ms` | 5-4000 | 60 | pad tails; none |
| Accent | `accent` | 0-1 | 0 | one-shot-level accent: scales level and `lp_env_amount` together; G1: +3 to +8 dB, +0.5 to +2 oct, none |
| Modulation | `lfo_rate_hz`, `lfo_depth_oct`, `lfo_target` (`cutoff`/`pitch`) | 0-12 / 0-3 / enum | 0 / 0 / `cutoff` | none; vibrato only if the user asks |
| Noise | `noise_level`, `noise_color` | 0-1 / white..pink | 0 | needed by the riser and for breath in a pad; none |
| Shaping | `drive` | 0-1 | 0.2 | as bass (anti-aliased saturation) |
| Output | `channels` | 1 or 2 | 1 | new; 2 only with unison spread or pad width |
| Meta | `kind` | `lead`, `pluck`, `pad`, `riser` | `lead` | a preset family, not a different engine |
| Meta | `seed`, `variants`, `bpm`, `sample_rate`, `bit_depth`, `polarity`, `offset_ms`, `peak_ceiling_dbfs`, `preset` | as bass-params | as bass | shared |

Cross-field rules to carry over from the bass contract (documented there; to be re-derived and re-tested for the new ranges): `hp_hz` < 0.8 x f0; `lp_hz` >= 1.2 x `hp_hz`; `lp_hz` x 2^`lp_env_amount` < 0.45 x sample rate; at least one oscillator level > 0; reject out-of-range values, never clamp.

### 1.2 Determinism requirements (PROPOSAL ONLY; same stance as `bass-params` decision 7 and D-005/CLAUDE.md)

1. Same parameters + same `seed` give a byte-identical WAV on one platform. All randomness only from `dsp.substreams(seed, n)`; no clock, no global RNG, no `hash()` of strings.
2. Unison: voice `i` has a cent offset that is a fixed function of `i`, `unison_voices` and `unison_detune_cents` (no randomness), and a starting phase drawn from its own substream. Different seeds differ only in starting phase (test A5 of the voice plan).
3. Filters: a fixed coefficient-update schedule (every N samples, N a constant of the module) and fixed state hand-over between blocks, so block size cannot change the bytes between runs.
4. No data-dependent branching on float equality; every loop bound derived from integers (sample counts rounded once, as `bass.py` does for `file_samples`).
5. Windows byte identity of float loops is an already-stated risk (G1 section 3.1, "Windows golden hashes"); the spec requires the claim to be reported per platform, not assumed.
6. Variants jitter fields only inside a preset box and are themselves seeded (as bass decision 8).

### 1.3 Which blocks exist in `src/audio_engine/dsp.py` and `bass.py`, which are missing (documented from the function lists I read today; behaviour not re-run)

| Block needed | Exists? | Where | Gap |
| --- | --- | --- | --- |
| Fixed-coefficient 2nd-order low-pass / high-pass / peaking | yes | `dsp.rbj_lowpass`, `rbj_highpass`, `rbj_peaking`, `_biquad` | none for static filters |
| Band-pass | yes | `dsp.biquad_bandpass` | fixed centre only |
| One-pole low-pass / high-pass | yes | `dsp.one_pole_lowpass`, `one_pole_highpass` | none |
| 4th-order high-pass | yes | `dsp.highpass_cascade` | no low-pass cascade |
| Oversampling for anti-aliased shaping | yes | `dsp.oversampled`, `kaiser_lowpass`, `fft_size`, `raised_cosine` | none known |
| Seeded independent streams | yes | `dsp.substreams` | none |
| Bandlimited square bank | yes | `dsp.square_bank` | saw is not in `dsp.py` |
| Additive bandlimited saw / sine / sub oscillators (phase 0, partials below 0.45 x sr) | yes, **inside** `bass.oscillators` | `bass.py` | not reusable as a shared block without a move; pitch range limited by the bass contract only (code takes a frequency; whether it accepts note > 55 without change: not checked) |
| Per-sample varying-cutoff resonant low-pass | yes, **inside** `bass._lowpass_varying` | `bass.py` | order 2 only; cutoff law is the per-note exponential (`bass.cutoff_hz`); a bar-scale law is missing |
| Mix of bank and noise with a power share | yes | `dsp.mix_passband` | none |
| Linear attack / hold / linear release amplitude | yes | `bass.amp_envelope` | no decay/sustain stage, no long (pad) range; kick has an exponential envelope (`kick._amp_envelope`, from the G1 note) |
| Unison stack (N detuned oscillators, seeded phases) | **missing** | - | new block |
| Glide (exponential or linear pitch ramp between notes) | **missing** | - | new block; phase continuity across the glide must be specified |
| ADSR with long attack and sustain | **missing** | - | extends `amp_envelope` |
| LFO (cutoff, pitch) | **missing** | - | new block, optional |
| Bar-scale filter sweep (`lp_hz` to `lp_hz_end` over `sweep_bars`) | **missing** | - | new cutoff law plus a loop renderer |
| 4th-order (24 dB) low-pass | **missing** | - | two cascaded sections or a ladder model; which one is a design decision, none proposed |
| Stereo output and width | **missing** | - | engine writes mono today for bass (documented: "Mono"); stereo needs a `channels` decision and sidecar fields |
| Noise source with colour | partly | hat/clap noise pieces exist (G1 3.1); not read today | colour control **not established** |
| Accent (per-note level and envelope-depth multiplier) | **missing** | - | trivial arithmetic once the voice exists |
| Cost: render time of long loops | **not established** | - | the pure-Python filter loop; only a plain biquad was timed (G1: 0.38 microseconds per sample on the sandbox); not measured on the user's PC |

### 1.4 Measurable acceptance targets (all hypotheses)

Class A are engine-correctness checks (no taste; reuse of voice plan section 2.1 with ID prefix kept); Class B are character quantities whose windows must be replaced by Goa references (voice plan section 5). The pass conditions are proposals for the audio-engineer, who sets thresholds only after measuring.

| ID | Target | Independent method | Pass condition (proposal) | Confirms / rejects |
| --- | --- | --- | --- | --- |
| A1 | Byte identity | render twice, hash | equal on one platform | determinism |
| A2 | Pitch accuracy of a held, non-glided note | long-window spectral peak and autocorrelation, expected value written in the test as `440 * 2^((n-69)/12)` | within 5 cents | oscillator code |
| A3 | Aliasing in the saw/unison stack at `note` up to 96 | compare a render at the target rate with one at 4x rate decimated | fold-back energy below a threshold set from the measurement; the highest note is the risk: arithmetic, note 96 is 2093 Hz and 0.45 x 48 000 = 21 600 Hz allows 10 partials of a saw | additive band-limiting |
| A4 | Start/end click | largest sample step in first/last 5 ms versus stationary peak | first and last sample 0 | envelope |
| A5 | Unison offsets | measure the pairwise cent spacing from the spectrum of each voice rendered alone | equals the parameter within 1 cent | unison block |
| A6 | Glide | pitch track (short-time autocorrelation) of a slid pair | reaches target within 1 cent after `glide_ms`; no click | glide block |
| A7 | Sweep | spectral centroid per bar of a baked loop against the requested cutoff law | monotone and matching the law within a tolerance set from the measurement | sweep block |
| A8 | Filter response | partial levels of a saw render against the biquad response written in the test | within 1 dB (bass uses this method) | filter |
| A9 | Headroom | peak of the quantised file against `peak_ceiling_dbfs` | as bass | normalisation |
| A10 | Render cost | wall time for a 1-note, a 2-bar loop and a 32-bar stem on the user's PC | reported, no limit proposed | cost, **not established** |
| B1 | Pluck filter-closing time | centroid of first 30 ms falling to stationary | 60-300 ms (G1) | `lp_env_decay_ms` |
| B2 | Resonance bump | dB of the peak over neighbouring partials | 3-18 dB (G1) | `lp_q` |
| B3 | Accent lift | level and centroid, accented versus normal | +3..+8 dB, +0.5..+2 oct (G1) | `accent` |
| B4 | Unison spread | detune cents between voices | 5-25 cents (G1) | `unison_detune_cents` |
| B5 | Pad attack | time to 90 % of the stationary peak, peak envelope per half period | 200-1500 ms (G1) | `amp_attack_ms` |
| B6 | Pad width | correlation between channels | no window proposed | `unison_spread`, `channels` |
| B7 | Sweep speed | stationary centroid slope in Hz per bar | no window proposed | `sweep_bars` |
| B8 | Riser | length in bars and centroid slope | 4-16 bars (G1, Bonedo #4) | `kind` riser |

Hypotheses (each with the measurement that settles it):

1. **H-spec-1: a lead is a saw (plus optional second oscillator), a resonant low-pass and 3-7 detuned voices; no other block is needed.** Reject if the user's references need an effect the list lacks (candidate: a band-pass or formant filter, which Analog and Auto Filter offer; G1 finding 10 says a resonant band-pass/high-pass for the squelch, uncited). Measure on references: centroid and resonance bump (B2) across notes.
2. **H-spec-2: pluck and lead differ only in envelope times and gate, not in structure.** Confirm: render a pluck and a lead from the same field set (`kind` as a preset family). Reject if a pluck needs a pitch envelope (Analog has one; Drift has no pitch envelope in the control list I read, only an oscillator Pitch Mod source).
3. **H-spec-3: the engine can cover Class A without stereo; width is the only reason for `channels` 2.** Confirm by dropping stereo from the first version and checking with the user whether pad and lead are wanted mono (to be checked by ear).
4. **H-spec-4: bar-scale sweeps are better left to the user's automation in Live than baked.** Confirm or reject with test item L5 below (user draws the sweep on the MIDI recipe; asked whether a baked loop is wanted instead).

Open points this spec does not decide: order of the filter (2nd vs 4th), saw alias handling above note 84, whether `kind` is a field or only a preset name, and sidecar fields (new `sample-metadata` entries would need their own `contract-change`).

---

## 2. Live 12 Standard patch recipes: Drift (default) and Analog

### 2.0 Rules for this part

- **All values are starting points. Not tested in Live. Not heard.** Every recipe row inherits that label; it is not repeated per row. The user's ears decide; the values come from the G1/voice-plan windows (themselves hypotheses) and my reasoning, not from a Goa source, unless a source is named.
- Devices used: Drift, Analog (instruments); Auto Filter, Delay, Reverb, Saturator, Chorus-Ensemble (effects; Standard per compare-editions). **Not used: Operator, Wavetable, Sampler, Meld (Suite-only per issue #345 and the edition-table check the lead made via WebFetch on 2026-11-03, together with G1 section 4.1), Echo, Roar (Standard status not established), Collision, Electric, Tension (edition membership documented, parameters not read, no recipe), Max for Live (not available).** Simpler is named only as a player for rendered one-shots (test plan item T-S).
- Control names are the manual's, as quoted by the fetch summary (section 2.1, 2.2). **Units:** the summary states no units for Drift Glide, Unison Strength, Stereo Spread, Drift amount, or the Analog Unison Detune/Delay and Pitch Env Time. Where I write a time or a percentage for such a control it is a musical intention to be set by ear, marked "unit not established".
- Tempo: the recipes assume the 135-150 BPM window of `goa_patterns.py`; arithmetic anchors at 140 BPM: 1/16 = 107.1 ms, 1/8 = 214.3 ms, dotted 1/8 = 321.4 ms, 1 bar = 1714.3 ms.
- Notes come from the generated `.mid` files (accent = velocity 127, slide = overlapping notes: documented in `acid_midi`); whether Live's import preserves these as the files describe is the open item of G3 tests T1-T8.
- Modulation of the filter by velocity: **inferred, not tested** whether either device lifts cutoff for accented notes (G1 4.3).

### 2.1 Drift: control names (documented, manual summary)

Osc 1 waveform menu (Sine, Triangle, Shark Tooth, Saturated, Saw, Pulse, Rectangle), Oct, Shape, Shape Mod Source/Amount; Osc 2 waveform menu (Sine, Triangle, Saturated, Saw, Rectangle), Oct, Detune; Pitch Mod Source/Amount; mixer Osc 1, Osc 2, Noise, R (retrigger); Filter Freq, Type (Type I 12 dB/oct, Type II 24 dB/oct), Key, Res, HP, Low-pass Modulation Source/Amount (two sources, each -100 to 100 %); Envelope 1 Attack/Decay/Sustain/Release; Envelope 2 / Cycling Envelope (Tilt, Hold, Rate; time modes Rate, Ratio, Time, Sync; Env 2 "is not mapped to amplitude by default and can be used as a source for any modulation"); LFO; Mod section (Source, Destination, Amount; destinations include Osc 1 Gain, Osc 1 Shape, Osc 2 Gain, Osc 2 Detune, Noise Gain, LP Frequency, LP Resonance, HP Frequency, LFO Rate, Cyc Env Rate, Main Volume); global Mode (Poly, Mono, Stereo, Unison), Mono Thickness, Stereo Spread, Unison Strength, Voices, Drift, Legato, Glide, Volume, Vel > Vol, Transpose. Documented behaviour: Mono renders four voices and "Mono Thickness" sets the extra voices' relative volume (0 = one voice); with Legato a new note changes pitch without resetting the envelopes; Unison = four voices per note, each detuned independently; Glide = how long overlapping legato notes take to slide; "Drift" adds random variation per voice (so Drift at a nonzero value is not repeatable between notes: relevant for the user's A/B, not for our determinism).

### 2.2 Analog: control names (documented, manual summary)

Osc 1 / Osc 2: Shape (sine, sawtooth, rectangular, white noise), Width, Octave, Semi, Detune (up to 300 cents), Pitch Mod, Pitch Env (Initial, Time), Key, Sub/Sync (Mode Sub or Sync; Sub Level = oscillator one octave below; Sync Ratio); Noise (switch, Color); Fil 1 / Fil 2 types (2nd order low-pass, 4th order low-pass, band-pass, notch, high-pass, formant), Freq, Reso, To F2, Follow, Freq Mod, Res Mod, Drive (Off, Sym, Asym); Amp 1 / Amp 2 Level, Pan, Pan Mod, Level Mod; envelopes Attack, Att < Vel, Decay, Sustain, S.Time, Release, Env < Vel, Slope, Legato, Free, Loop (Off, AD-R, ADR-R, ADS-R); LFO 1 / 2 Rate, Wave, Width, Delay, Attack, Retrig, Offset; global Volume, Vib, Uni (2 or 4 Voices, Detune, Delay), Gli (Time, Glide Mode Const / Prop), Legato, PB Range, Priority. No Shape Mod and no modulation matrix in Analog (documented). Glide with Legato: sliding only happens if the second note is played before the first is released.

### 2.3 Recipe L: Goa lead (stacked saw, resonant low-pass)

| Control | Drift starting point | Analog starting point | Why (hypothesis) |
| --- | --- | --- | --- |
| Voice mode | Mode Unison; Voices 8 or more; Unison Strength: low-to-mid (unit not established) | Uni on, Voices 4, Detune: low-to-mid (unit not established) | G1: 3-7 voices, 5-25 cents, no source; Drift Unison is fixed at 4 voices per note, Analog at 2 or 4, so 3, 5, 7 are unreachable (documented) |
| Oscillators | Osc 1 Saw; Osc 2 Saw, Detune about +7 to +12 cents if the control is in cents, otherwise small (unit not established; the summary says "semitones" for Osc 2 Detune, which would make +7 a fifth) | Osc 1 sawtooth; Osc 2 sawtooth, Semi 0, Detune about 5-10 cents | Osc 2 at +7 semitones is the chord-stab layer (Bonedo #2); for a lead start at unison |
| Filter | Type II (24 dB/oct); Freq mid-low; Res mid; HP off | Fil 1 4th order low-pass; Freq mid-low; Reso mid; Drive Sym low | G1: 24 dB/oct low-pass is the 303 slope (Wikipedia, Roland); resonance bump 3-18 dB target (hypothesis) |
| Filter envelope | Low-pass Modulation Source = Env 2, Amount +30 to +60 %; Env 2 A 0 ms, D 150-400 ms, S 20 %, R 100 ms | Freq Mod from filter envelope (listed source: documented), amount mid; Env decay 150-400 ms | G1: accent decay 80-400 ms, no source |
| Amp envelope | Env 1 A 2 ms, D 300 ms, S 70 %, R 120 ms | Amp env A 2 ms, D 300 ms, S 70 %, R 120 ms | short click-free attack; hold the note for the ostinato |
| Glide / slides | Mono is not wanted for a stacked lead; for slid notes use a separate Mono track, Legato on, Glide 30-120 ms (unit not established) | Gli Time 30-120 ms (unit not established), Const, Legato on | G1: slide 30-120 ms; overlap needed (documented) |
| Accent | Shape Mod / LP Modulation Source "Velocity" at +20 to +40 % (source listed for Shape Mod; whether it is also an LP Modulation Source: not established) ; Vel > Vol mid | Env < Vel mid; Freq Mod sources do not list velocity in the summary: not established | cutoff-lift by velocity is **inferred, not tested** |
| Space | Delay: Sync on, Dotted 1/8 or 1/8, Feedback low-mid, Ping Pong on, Dry/Wet 15-30 % ; Reverb low | same | Bonedo #2: ping-pong delay at dotted quarter or eighth (note values only) |
| Cutoff movement | User draws Freq automation over 8-32 bars | same | G1: cutoff as an instrument; our write to Live not available |

### 2.4 Recipe B: acid-style bass (303-like squelch, mono)

| Control | Drift | Analog | Why |
| --- | --- | --- | --- |
| Voice mode | Mode Mono; Mono Thickness 0 to low; Legato on; Glide 30-80 ms (unit not established) | Uni off; Gli on, Time 30-80 ms, Legato on | slides need overlapping notes and legato (documented) |
| Oscillators | Osc 1 Saw (or Rectangle); Osc 2 off or Saw at Oct -1 | Osc 1 sawtooth (or rectangular); Sub/Sync Mode Sub, Level low | 303: sawtooth and square (documented); a sub layer is an option, not from a source |
| Filter | Type II; Freq low-mid; Res mid-high; Key on, low | Fil 1 4th order low-pass; Reso mid-high; Key as default | G1: non-self-oscillating 24 dB low-pass; keep Res below the point where the filter rings by itself (the self-oscillation point of either device: not established) |
| Filter envelope | Env 2 to LP Frequency, Amount +50 to +80 %; Env 2 A 0, D 120-300 ms, S 0 | filter envelope, Freq Mod high, D 120-300 ms, S 0 | G1: 80-400 ms; none sourced |
| Amp | Env 1 A 1 ms, D short, S 100 %, R 30-60 ms | A 1 ms, S 100 %, R 30-60 ms | note length one 16th = 107.1 ms at 140 BPM |
| Accent | as recipe L | as recipe L | inferred, not tested |
| Output | Saturator moderate; Auto Filter off | Drive Sym low | none |
| Kick relation | Auto Filter or EQ Eight high-pass at about 40-60 Hz on the bass track only if the roll collides with the kick tail (Bonedo #1: phase, low-cut, or tempo) | same | the user's kick tails are 45-60 Hz median 53 Hz (kick learnings) |

Rolling-bass variant (roll of three 16th notes after each kick, from `goa_patterns.py`): same patch, Env 2 / filter envelope decay 5-40 ms (G1 3: "closes within a few milliseconds"; upper end inferred), Amp D short, gate about 0.6-1.0 of a 16th; first roll note quieter via MIDI velocity (not in the generator today).

### 2.5 Recipe P: pluck / stab

| Control | Drift | Analog | Why |
| --- | --- | --- | --- |
| Voice mode | Poly, Voices 8 | Uni off, polyphonic default | chord stabs |
| Oscillators | Osc 1 Saw; Osc 2 Saw at +7 semitones (Osc 2 Oct/Detune: if Detune is in semitones per the summary, +7) | Osc 1 sawtooth; Osc 2 sawtooth, Semi +7 | Bonedo #2: second oscillator seven semitones above for stabs |
| Filter | Type I or II; Freq low; Res low-mid | 2nd order or 4th order low-pass; Reso low-mid | none |
| Filter envelope | Env 2 to LP Frequency, Amount +60 to +100 %; D 60-300 ms, S 0 | filter env Freq Mod high; D 60-300 ms, S 0 | G1: pluck filter decay 60-300 ms, none |
| Amp | A 0-2 ms, D 80-400 ms, S 0, R 80 ms | same | G1: pluck amp decay 80-400 ms, none |
| Space | Delay as recipe L; short Reverb | same | note values from Bonedo #2 |

### 2.6 Recipe D: pad

| Control | Drift | Analog | Why |
| --- | --- | --- | --- |
| Voice mode | Stereo (Stereo Spread mid) or Unison (Strength low) | Uni on, 4 voices, Detune low | width without a chorus device |
| Oscillators | Osc 1 Saw; Osc 2 Triangle or Saw, small Detune | Osc 1 sawtooth; Osc 2 rectangular, Width mid, Detune small | none |
| Filter | Type I; Freq low-mid; Res low; LP Modulation Source = LFO, small amount, slow rate | 2nd order low-pass; Reso low; Freq Mod from LFO 1, slow | slow movement; none sourced |
| Amp | Env 1 A 200-1500 ms, D long, S 80-100 %, R 400-1500 ms | same | G1: pad attack 200-1500 ms, no source; 1 bar = 1714.3 ms at 140 BPM |
| Space | Chorus-Ensemble (modes Chorus, Ensemble, Vibrato: documented); Reverb long | same | none |
| Level | well below the lead in the mix (by ear) | same | none |

### 2.7 Recipe R: riser

| Control | Drift | Analog | Why |
| --- | --- | --- | --- |
| Source | Noise on in the oscillator mixer, Osc 1 and Osc 2 gain down | Noise switch on, Color mid; Osc levels down | noise-based riser; routes by Noise (documented in both) |
| Filter | HP or band-pass is not selectable in Drift's type list (Type I / Type II low-pass only in the summary; HP is a separate control) ; use HP rising | Fil 1 band-pass or high-pass, Reso mid | G1: seeded noise + swept band-pass is our own render plan |
| Sweep | Freq/HP automation over 4-16 bars, drawn by the user; or Auto Filter after the synth: Filter Type Band-pass, Freq automation, Res mid | same; Freq automation or LFO slow | Bonedo #4: builds of 8, 16, 32 bars with risers (psytrance source) |
| Amp | Env 1 A long (as the riser), S 100 % | same | none |
| Space | Reverb long, Delay as recipe L | same | none |

Automation for riser and cutoff sweeps: the manual page for Auto Filter does not say Freq accepts automation (the summary was silent); whether you can draw it is a Live behaviour **not established here**; test item L5 asks the user.

### 2.8 Where Drift and Analog differ for these recipes (documented)

- Unison: Drift 4 voices per note, Strength; Analog 2 or 4 voices, Detune, Delay. Neither gives 3, 5, 7.
- Sub oscillator: Analog Sub/Sync Mode Sub (Level); Drift: no sub parameter in the control list (use Osc 2 at Oct -1).
- Pitch envelope: Analog has Pitch Env Initial/Time; Drift has Pitch Mod Source/Amount (a pitch envelope via Env 2 as source: plausible, not established).
- Velocity: Drift lists Velocity as a Shape Mod source and Vel > Vol; Analog has Env < Vel and Att < Vel.
- Filter: Drift Type I/II low-pass only; Analog 2nd/4th order low-pass, band-pass, notch, high-pass, formant.
- Randomness: Drift's Drift control adds per-voice random variation; set to 0 for A/B comparisons (the effect of 0 on repeatability: not tested).

---

## 3. Test plan for the user (about 12 minutes; Live 12 Standard; all questions)

Preparation (3 minutes): load the generated lead MIDI clip from `goa_patterns.py` (whichever the lead already made), set the tempo you prefer (135-150), kick on. Build the three variants of each pair below as instrument racks or separate tracks; **a second person or a helper plugin order is not required: use the "blind" shortcut: name the tracks A, B, C and let the lead (or anyone else) shuffle the names, or pick by ear first and only then look at which variant it was.** Everything below is a question; no outcome is assumed. If a control does not behave as described, say so; that is a result.

| ID | What to load | Single question | Blind how | Time |
| --- | --- | --- | --- | --- |
| L0 | Edition check: open the browser, look for Operator, Wavetable, Sampler, Meld, Echo, Roar | Which of these are present? | not applicable | 1 min |
| L1 | Recipe L on Drift versus Analog, same MIDI | Which do you prefer for the lead, or no preference? | hide device names, A/B muted by the lead's shuffle | 2 min |
| L2 | Recipe L with filter envelope amount low / mid / high | Which amount do you mean by "squelchy but not harsh"? (you name the wording) | three tracks, random order | 2 min |
| L3 | Unison: Drift Unison Strength low / mid / high (or Analog Detune) | How wide a stack do you want? | three, random | 2 min |
| L4 | Recipe B bass: filter decay 120 / 200 / 300 ms, then the rolling-bass variant at 5 / 20 / 40 ms | Which decay reads as the bass you want, for the acid line and for the roll? | random | 2 min |
| L5 | Cutoff sweep: draw a Freq automation line over 8, 16, 32 bars on the lead | Can you draw it easily in Live? Which length fits the arrangement? Would you rather have a baked loop? | not blind (it is about Live) | 2 min |
| L6 | Pluck, pad, riser recipes once each | Is the pluck/pad/riser in the right family of sound, or what is off? (free text) | not blind | 1 min |

Optional (T-S, 1 minute): drag a rendered one-shot bass note onto Simpler and report whether it plays and pitches from MIDI (voice plan item T-S).

What to report back: per item one line (pick or "no preference"), plus any control name in these recipes that does not exist in your Live 12 build (that corrects this note).

## 4. What was and was not verified

- Verified (second-hand, WebFetch summaries, 2026-11-03): control names for Drift and Analog; Standard membership of Drift, Analog, Auto Filter, Delay, Reverb, Chorus-Ensemble, Saturator, EQ Eight; a read of Echo as Suite-only.
- Not verified: any parameter range or unit not named in sections 2.1-2.2; Reverb and Saturator control names (unread tail); Echo and Roar status; Collision, Electric, Tension and Simpler parameters; whether either synth lifts cutoff from velocity; automation drawing on Auto Filter and synth filters; every behaviour of the imported `.mid`.
- Nothing rendered, measured on audio, run in Live or heard.

## State update proposal (for the PR body; the lead edits `CURRENT_STATE.md`)

- Goa lead/pad/pluck voice spec and Drift/Analog recipes written: `docs/research/2026-11-03_goa-lead-pad-voice-spec-and-live-recipes.md` (Refs #338, D-026).
- Next: user runs test plan items L0-L6; results decide whether a `lead-params` `contract-change` is opened (parameter proposals in section 1.1 are the starting list).
- Conflicting read: Echo read as Suite-only on the compare-editions page (still not established; recipes avoid it).
