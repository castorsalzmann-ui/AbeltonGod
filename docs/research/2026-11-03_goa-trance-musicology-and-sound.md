# Research: Goa trance for a deterministic generator — musicology, sound targets, delivery route, `goa_line` proposal, arrangement template, listening tests

_Date: 2026-11-03 · Refs #338 (Goa track G1) · Role: researcher. All web pages were opened on 2026-11-03 through the session's fetch tool (a small model summarises each page; I could not open `ableton.com` or `kvraudio.com` with curl, and one page, the Helsinki repository, was blocked: see "Gaps"). Nothing here was run in Live, nothing was rendered, nothing was heard. Docs only: no code, no contract, no decision changed. Every number marked "starter" is a hypothesis for the user's ear, not a finding._

Labels used below: **documented** = a page I opened says it (with the page's own weakness named); **inferred** = my reasoning from documented facts; **not established** = no source found or sources disagree.

Related notes, not repeated: [acid lines to Live](2026-11-02_acid-lines-to-live.md) (the `acid_line` mapping and the MIDI-file route), [bass targets](2026-11-02_bass-targets.md) (measurable bass quantities and the analysis-helper gaps), [arrangement planner](2026-10-29_arrangement-planner-sections-energy.md) (phrase grid, section vocabulary), [arrangement-plan generator design](2026-11-02_arrangement-plan-generator-design.md), [live MIDI/devices](2026-10-29_live-midi-arrangement-devices.md).

## For workers

- **Possible?** Yes, in two layers. (1) **MIDI + a written patch recipe for Live's own instruments**: needs no new engine and no Live bridge; the existing `src/audio_engine/acid_midi.py` already turns a 16-step line into a `.mid` the user drags in. (2) **Rendered audio** (rolling-bass note one-shots, risers, a swept acid loop) needs new engine voices: a band-limited saw, a time-varying resonant filter and a bass/lead envelope do not exist in `src/audio_engine/dsp.py` (it has fixed-coefficient RBJ biquads, `square_bank`, `substreams`).
- **Edition fact that changes the plan:** Live 12 **Standard has no Operator, no Wavetable, no Sampler, no Meld, no Max for Live** (Echo and Roar: Standard status **not established**, the user checks Live's device browser). It has **Analog, Drift, Simpler, Collision, Electric, Tension, Drum Synths**, Auto Filter, Saturator, Delay, Reverb, Phaser-Flanger, Chorus-Ensemble, Arpeggiator, Scale, Note Echo (section 4). Any recipe must use Drift or Analog.
- **Recommended route:** MIDI + recipe first (small), engine voices second (medium-large, after the user has judged the MIDI result). Do not build the sound engine before the user supplies Goa reference tracks: **no published numeric target for a Goa lead, bass or filter sweep was found** (section 3).
- **Read first:** section 1 (what is documented about Goa), then section 5 (`goa_line`) and section 6 (arrangement); section 4 for the device list.
- **Effort:** `goa_line` generator + adapter to `acid_midi` = small; Drift/Analog recipes = small (doc); rolling-bass one-shot voice = medium; swept-filter acid loop render = medium-large; riser/FX voices = medium.
- **Blockers:** (a) no Goa references from the user yet (taste ranges cannot be derived); (b) writing filter automation into Live is not a `tested` capability (the `.mid` carries notes and velocity only; CC-to-parameter mapping is not established); (c) the one scholarly source (Aittoniemi 2012) was only readable in part.
- **Open questions only the user can answer:** (1) Which 3-5 Goa tracks are the reference (title or file)? (2) Authentic Goa arc (long, no hard drop) or a DJ-mixable intro/outro (the user's earlier requirement)? (3) Default tempo (starter 140, range 130-150)? (4) Drift or Analog as the default synth in the recipe? (5) Is the `acid_line` slide-on-the-step-you-slide-from convention confirmed?

## 1. Findings

| # | Finding | Label / confidence | Source |
| --- | --- | --- | --- |
| 1 | Goa trance began in the early 1990s in Goa, India (cited to AllMusic on the page). Its tempo is given as 130-150 BPM, some tracks 110 or 160, 4/4, length 8-12 minutes, "low and thick" kick with prominent sub-bass, drone-like basslines; **tempo, length and kick statements are uncited on the page** | documented, medium-low (Wikipedia, mostly uncited) | [Wikipedia: Goa trance](https://en.wikipedia.org/wiki/Goa_trance) |
| 2 | Other tempo statements: 135-145 BPM (two commercial genre guides, no sources); 135-150 BPM (Psytrance Guide); full-on 140-148 (Wikipedia, cited to an Ektoplazm page; also Psytrance Guide); progressive psy 130-140; Nitzhonot 145-160. A Goa thesis' figure captions mention tracks at 128 ("slow by modern standards"), about 142 ("fast for its time") and 145 BPM | documented as ranges, **no measured distribution found** | [ClassicTrance](https://www.classictrance.com/subgenres/goa-trance); [Trance Nexus](https://trance-nexus.com/blog/what-is-goa-trance); [Psytrance Guide](https://psytranceguide.com/); [Wikipedia: Psychedelic trance](https://en.wikipedia.org/wiki/Psychedelic_trance); [Aittoniemi 2012 (Academia copy), figure captions 21, 24, 38](https://www.academia.edu/65115221/Cultural_and_Musical_Dimensions_of_Goa_Trance_and_Early_Psychedelic_Trance_in_Finland_The_history_translation_and_localization_of_an_internationally_mobile_electronic_dance_music_scene) |
| 3 | The only scholarly source found (Aittoniemi, MA thesis, Musicology, University of Helsinki, 2012) says the tonal dimension "is almost always utilized" but music is "primarily rhythmic" (p. 19); the classic repertoire's tonal space "is typically limited to only a few set scales" (p. 19; **the scales are not named in the part I could read**); Eastern scales are a documented influence (section 4.2.4, title only; Fig. 47 "pseudo-eastern feel") | documented, medium (partial read) | Aittoniemi, same link |
| 4 | Same thesis, rhythm: additive groupings such as **3+2+3** are "of very common occurrence in Goa trance" (example: Juno Reactor, "High Energy Protons", 1993); asymmetric 3+3+3+3+4 over the 16th grid (Mandra Gora, "Wicked Warp", 1993); metric displacement in an acid line ("Feeling Weird", The Infinity Project, 1993) | documented, medium (paraphrase of a fetch summary of the thesis) | same |
| 5 | Same thesis, form and bass: an "accumulative / subtractive" form, typical track shape "a rising sawtooth-wave curve" of build-ups and breakdowns; drive comes from each section holding more energy than the one before; bass is often layered as a **sub-bass drone plus a higher bass line**; a caption names a "galloping sub-bass" and a "heavy kick drum"; a section title is "Filter cutoff as an instrument" (4.4.4, contents only) | documented, medium | same |
| 6 | Wikipedia (Goa): energy builds steadily, "more intense second half, a climax, and a fairly quick taper"; Wikipedia (psytrance): tracks 6-10 minutes (cited to Easwaran 2004); leads/rhythms/beats generally change **every 8 bars** and layers are added every 4-8 bars until a climax (cited to a moodbook.com definition), then a breakdown of about 30 s to over a minute starts a new rhythmic pattern over the same bass line | documented, medium-low | [Goa trance](https://en.wikipedia.org/wiki/Goa_trance); [Psychedelic trance](https://en.wikipedia.org/wiki/Psychedelic_trance) |
| 7 | **Sources disagree on drops.** ClassicTrance: "long organic builds with no traditional drop or breakdown" (Goa). Bonedo (a German production crash course on **psytrance**, not Goa; it does not use the word Goa): tracks "often 7 to 9 minutes", intro / build-up / drop / breakdown / outro, builds of 8, 16 or 32 bars, a pause of about four beats before a drop, drops in 16-bar blocks, one main breakdown about two-thirds in and up to 64 bars, short breaks up to 16 bars, outro reduced to kick and bass, two or three drops per track | documented for psytrance; **Goa-specific bar counts not established** | [ClassicTrance](https://www.classictrance.com/subgenres/goa-trance); [Bonedo #4](https://www.bonedo.de/artikel/crashkurs-psytrance-produzieren-4-vocals-arrangement-mixing) |
| 8 | **Rolling bass, one documented recipe** (psytrance, not labelled Goa): kick on every quarter; **three short bass hits, each one 16th, after each kick** (the first 16th of the beat is the kick's); the first bass note after the kick played quieter; sawtooth through a low-pass whose cutoff closes within a few milliseconds (pluck); the kick tail should overlap the first bass 16th without cancelling it (phase, low-cut, or tempo); the **offbeat** variant (one eighth after the kick, ringing one eighth) is called "common in progressive psytrance". No tempo, cutoff, resonance or envelope time is given | documented, medium (one tutorial) | [Bonedo #1](https://www.bonedo.de/artikel/psytrance-produzieren-workshop-1-kick-bass-percussion/) |
| 9 | A "rolling triplet / galloping" bass is called "the genre's most identifiable signature" by one guide, with no source. A 16th-grid roll (above) and a triplet roll are different rhythms; **which one 1990s Goa used is not established** by what I could open (the thesis' own bass section 4.4.2, p. 84, was not readable) | **not established** | [Trance Nexus](https://trance-nexus.com/blog/what-is-goa-trance); thesis caption "galloping sub-bass" |
| 10 | Squelchy sound: "a sawtooth wave run through a resonant band-pass or high-pass filter" and a gear list (TB-303, Juno-60/106, Bass Station, MS-10, SH-101) — both marked "citation needed" on Wikipedia | documented as **uncited** | [Goa trance](https://en.wikipedia.org/wiki/Goa_trance) |
| 11 | TB-303: 24 dB/oct resonant, non-self-oscillating low-pass; sawtooth and square oscillators; envelope-controlled filter; the page gives no accent, slide or decay-time figures and does not mention Goa | documented, medium | [Wikipedia: TB-303](https://en.wikipedia.org/wiki/Roland_TB-303); [Roland TB-303 manual](https://rolandcloud.com/getmedia/b3e2da28-1951-467e-bd79-7aae34481570/TB-303-Manual-E.pdf?ext=.pdf) (16 steps, per-step pitch/slide/gate/accent, from the earlier note) |
| 12 | Scale facts: Phrygian dominant is the fifth mode of harmonic minor, degrees 1 b2 3 4 5 b6 b7 (augmented second between degrees 2 and 3). Phrygian = flattened second ("slightly darker", Attack Magazine). Neither page mentions trance or Goa | documented (theory); **Goa use of each mode not established** | [Wikipedia: Phrygian dominant](https://en.wikipedia.org/wiki/Phrygian_dominant_scale); [Attack Magazine](https://attackmagazine.com/technique/the-breakdown/julio-bashmore-au-seve/2) |
| 13 | Psytrance melody idioms (Bonedo #2, not Goa): step-sequencer melodies "often built on monotone 16th-note sequences" where rhythm and melody come from note jumps; arpeggiators; random-note recording then splicing; modes named only as "Dorian, Phrygian, Lydian etc."; super saws = unison detuned saws (**no detune amount, no voice count given**); filter cutoff automation "slowly opens the filter to add energy"; ping-pong delay with dotted-quarter or eighth notes; plucks = low-pass filter envelopes (no times); a Sample-and-Hold on a band-pass cutoff at a 16th rate ("fractal" sounds) | documented, medium | [Bonedo #2](https://www.bonedo.de/artikel/psytrance-produzieren-2-synths-melodien-und-sounddesign) |
| 14 | "Oriental aesthetics, mostly Indian consonance" and "modal, often Eastern-scale melodies" — **no scale named** by either page | documented as vague | [Psytrance Guide](https://psytranceguide.com/); [ClassicTrance](https://www.classictrance.com/subgenres/goa-trance) |

### 1.1 What "Goa" means against later psytrance (what the sources support)

- **Tempo.** Goa is placed at 135-145 (two unsourced guides) or 135-150 (Psytrance Guide); Wikipedia's 130-150 covers "Goa trance" and gives full-on as 140-148. The ranges overlap; **a tempo alone does not separate Goa from full-on** (inferred from the overlap). The thesis captions suggest a spread of at least 128-145 within the 1990s repertoire (captions only).
- **Structure.** The scholarly source describes a rising, accumulating form; commercial guides disagree on whether there are drops. The clearest bar-count source (Bonedo) is about psytrance in general. **Bar counts for 1990s Goa specifically: not established.**
- **Bass.** Sources agree there is a kick on each quarter and a constant, driving bass under the melody. Whether the 1990s bass was a 16th roll, a gallop or a drone plus a upper line is split between sources (findings 5, 8, 9). The "three 16ths after the kick" pattern is a documented psytrance recipe, not a documented Goa fact.
- **Not established anywhere I could open:** a measured BPM distribution of 1990s releases, a measured kick spectrum, scale frequencies by mode, typical section lengths for named Goa albums.

## 2. Scales, modes and melody idioms

### 2.1 Scale sets (semitone offsets from the root; theory is documented, the Goa weighting is not)

| Mode | Offsets | Basis |
| --- | --- | --- |
| Aeolian (natural minor) | 0 2 3 5 7 8 10 | textbook; derived |
| Phrygian | 0 1 3 5 7 8 10 | b2 vs aeolian (Attack Magazine) |
| Harmonic minor | 0 2 3 5 7 8 11 | raised 7th; Wikipedia says phrygian dominant is its 5th mode |
| Phrygian dominant | 0 1 4 5 7 8 10 | derived from the page's degrees 1 b2 3 4 5 b6 b7; the augmented second (3 semitones between degrees 2 and 3) is the "Eastern" interval (inferred association) |

Starter weights for a generator (proposal, **inferred**, no source ranks the modes for Goa): aeolian 0.3, phrygian 0.3, harmonic minor 0.15, phrygian dominant 0.25. The thesis says only "a few set scales"; the user's references should replace these weights.

### 2.2 Idioms the sources support

| Idiom | Support | How it maps to steps |
| --- | --- | --- |
| Monotone / repeated-note 16th sequence with note jumps | documented (Bonedo #2) | root repeated, accent and octave jumps carry the "melody" |
| Additive rhythm 3+2+3 (8 steps), 3+3+3+3+4 (16 steps), repeated | documented (Aittoniemi, from tracks of 1993) | group starts at steps 0, 3, 5 and 8, 11, 13 for 3+2+3 twice; 0, 3, 6, 9, 12 for 3+3+3+3+4 (arithmetic) |
| Metric displacement of a short motif against the 16-step loop | documented (Aittoniemi, "Feeling Weird") | a 3- or 5-step motif looped over a 16-step grid |
| Filter cutoff as an instrument / slow opening | documented (thesis section title; Bonedo #2) | automation over 8-32 bars; not a MIDI note |
| Octave jumps | the only mention is a hard-house/trance bass pattern (every 8th, alternating octaves; [The Producer School](https://theproducerschool.com/blogs/featured-blogs/5-essential-bass-patterns-that-define-hard-house-and-trance-music)); **no Goa source** | `octave` field per step |
| Arpeggios that develop over many bars | documented as a statement (unsourced guide, Trance Nexus; Bonedo #2 for arpeggiators) | 16th arpeggio over a chord, root moves per 8 bars (inferred) |
| Accent and slide (303 idiom) | documented in the TB-303 manual (accent, slide, gate per step); Goa use as "acid-style sweeps" documented only by unsourced guides | existing `acid_line` flags |
| Note length: bass note = one 16th; stabs shorter | documented for the bass (Bonedo #1); lead lengths not given | `render.gate` |

Not established: interval statistics (stepwise vs leaps), typical ambitus of leads, how often accents fall on which step, how long ostinati run before changing (Wikipedia: change every 8 bars, moodbook-cited second hand).

## 3. Synth sound targets as measurable quantities

Same stance as the [bass targets note](2026-11-02_bass-targets.md): the quantity and the way to measure it are proposals; **starter ranges have no published Goa source unless a source is named in the row.** I found no numeric target for a Goa lead, acid line, pluck, pad or riser. The ranges below are wide search windows for the engine tests and the first listening round, not taste claims. Measure from the onset, on stationary windows, and against a 4x-rate render for aliasing (kick learnings, bass note P1-P9); those pitfalls apply unchanged.

| Element | Quantity (how measured) | Starter range (hypothesis) | Source for the number | Moves with (proposed field) |
| --- | --- | --- | --- | --- |
| Rolling bass | Pitch accuracy (cents) on the stationary window | 0 +/- 5 | none (engine claim) | `note` |
| Rolling bass | Note length against one 16th (gate ms / 16th ms); 16th = 60000 / (4 x BPM) ms: 107.1 ms at 140, 111.1 at 135, 102.7 at 146 (arithmetic) | gate 0.6-1.0 of a 16th | Bonedo #1: "one sixteenth per hit" (gate fraction is inferred) | `gate`, `release_ms` |
| Rolling bass | Filter-closing time: time for the centroid in the first 30 ms to fall to its stationary value | 2-40 ms | Bonedo #1: "closes within a few milliseconds"; upper end is inferred | `lp_env_decay_ms` |
| Rolling bass | Level of the first roll note against the other two (dB) | -12 to 0 | Bonedo #1: "played quieter", amount "left to taste" | `roll_first_velocity` |
| Rolling bass | Overlap with the kick tail (kick tail 45-60 Hz in the user's own kicks, median 53 Hz, [kick learnings section 2](2026-10-28_kick-gen2-learnings.md)): bass fundamental versus 45-60 Hz | avoid or reinforce is a mix question for the user | Bonedo #1 (phase / low-cut) | `note`, `hp_hz` |
| Sub drone | Fundamental and level of a held sine below the roll | note 24-36 (32.7-65.4 Hz) | thesis only says a sub drone plus an upper line exists; the register is inferred | `note`, `gate` |
| Acid / lead | Spectral centroid range (Hz) in the stationary part and its change over an 8-bar cutoff sweep | **no range proposed** (depends on cutoff and Q) | none | `cutoff_start_hz`, `cutoff_end_hz` |
| Acid / lead | Filter cutoff envelope shape: decay time of the centroid after each accented note | 80-400 ms | none; the TB-303 pages give no decay figures | `env_decay_ms` |
| Acid / lead | Resonance: peak height of the resonant bump over the surrounding harmonic envelope (dB) | 3-18 dB | none; the 303 filter is documented as non-self-oscillating, so the upper end is bounded | `res` |
| Acid / lead | Filter slope: 24 dB/oct low-pass | fixed | 303 filter (Wikipedia, Roland); Live's Auto Filter and Analog offer 24 dB / 4th-order | `lp_order` |
| Acid / lead | Accent effect: cutoff and level lift of an accented against a normal note (dB, octaves) | level +3 to +8 dB, cutoff +0.5 to +2 oct | none; the manual says accent raises the strength, the earlier note's finding 5 | `accent_gain_db`, `accent_cutoff_oct` |
| Acid / lead | Slide: glide time between slid notes (ms) | 30-120 ms | none | `glide_ms` |
| Lead stack | Detune spread in cents between unison saws, voice count | 5-25 cents, 3-7 voices | none; Bonedo gives no amount or count; Analog's detune range is up to 300 cents (that is a device limit, not a target) | `unison_voices`, `detune_cents` |
| Lead | Octave/semi layer: second oscillator at +7 semitones for stabs | 0 or +7 | Bonedo #2 ("seven semitones above the main oscillator", chord stabs) | `osc2_semi` |
| Pluck | Filter-envelope decay of the pluck (ms), amplitude decay (ms) | 60-300 / 80-400 | none (Bonedo #2 gives no times) | `pluck_decay_ms` |
| Pad | Attack (ms), centroid of the stationary window, stereo width | attack 200-1500 ms | none | `pad_attack_ms` |
| Riser / FX | Centroid slope over the riser (Hz per bar) and length (bars) | 4-16 bars | Bonedo #4: build-up 8, 16 or 32 bars with risers, snare rolls, filter sweeps | `riser_bars` |
| Delay | Ping-pong, dotted quarter or eighth | 3/16 or 1/8 beat | Bonedo #2 (note values; feedback not given) | recipe only |

### 3.1 How each could be produced deterministically in this repo

State of the code (read on `origin/main` fac11b1, the worktree base): `dsp.py` has `rbj_lowpass/highpass/peaking` (fixed coefficients per call, a pure-Python loop in `_biquad`), `square_bank` (additive band-limited square), `substreams(seed, count)` (independent seeded generators), `biquad_bandpass`, one-pole filters, oversampling helpers. `acid_midi.py` maps a 16-step line to a `.mid` (PPQ 480, accent = velocity 127, slide = overlap or tie).

| Need | Gap in the repo | Deterministic route (inferred) |
| --- | --- | --- |
| Band-limited saw | none (only square is provided) | additive sum `sum sin(2 pi k f t) / k` over `k * f < sr/2`, same style as `square_bank` |
| Swept resonant low-pass | `_biquad` has fixed coefficients | update coefficients per block of N samples (state kept across blocks) or a state-variable filter with per-sample cutoff; both are pure arithmetic, so same inputs give the same bytes on one platform. **Windows byte-identity** of float loops is already a stated risk in CI (see CURRENT_STATE "Windows golden hashes") and applies here |
| Cost | the loop is pure Python | measured today on this box: a plain biquad loop ran 2,000,000 samples in 0.76 s (about 0.38 microseconds per sample, no coefficient update). A 2-bar loop at 140 BPM is 3.43 s = 165k samples at 48 kHz, so it is cheap; a full 8-minute track in one stem is about 23M samples, i.e. several seconds per filter pass before any per-sample coefficient maths. **Not measured on the user's PC** |
| Unison detune | none | N saws with fixed cent offsets and phases from `substreams(seed, n)` (random starting phase only) |
| 303-style accent / slide | none | accent = per-note multiplier on level and on envelope depth; slide = exponential pitch glide over `glide_ms` |
| Riser | `hat`/`clap` have noise and band-pass pieces | seeded noise, band-pass with a swept centre, amplitude ramp; pure arithmetic |
| Rolling-bass one-shot | planned by the bass note, no voice exists | saw + sine sub, fast filter envelope, 16th gate; analysis needs the bass note's stationary-window helpers |

Seeds: the line generator (section 5) uses `random.Random(seed)` or `numpy` via `substreams`; no global RNG, no clock. The MIDI bytes depend only on the line JSON (the module already guarantees this).

## 4. What can be delivered how

### 4.1 Which devices Live 12 Standard has (documented; the page snapshot is current, not tied to 12.4.5)

From the [Ableton edition comparison](https://www.ableton.com/en/live/compare-editions/) (fetched through the summarising tool on 2026-11-03; two passes agree):

| Device | Intro | Standard | Suite |
| --- | --- | --- | --- |
| Drift | yes | **yes** | yes |
| Analog | no | **yes** | yes |
| Simpler | yes | yes | yes |
| Collision, Electric, Tension, Drum Synths | no | yes | yes |
| **Operator, Wavetable, Sampler, Meld** | no | **no** | yes |
| Echo, Roar | no | **not established** | not established; the summarising fetch tool read Echo as Suite-only and Roar as Suite-only, a reviewer recalls Echo in Standard. The user checks Live's device browser |
| Auto Filter, Saturator, Delay, Reverb, Phaser-Flanger | yes | yes | yes |
| MIDI: Arpeggiator, Scale, Chord, Note Length, Pitch, Random, Velocity, CC Control | yes | yes | yes |
| MIDI: Note Echo | no | yes | yes |
| MIDI: Melodic Steps | no | no | yes |
| Max for Live | no | no | yes |

Caveats: the page's overview counts (12 instruments in Standard) do not match the rows I could read (14), a mismatch the page does not explain; I did not see the rows for Chorus-Ensemble, Auto Pan, EQ Eight and the dynamics devices, which the Live 12 manual does document. **This corrects the task brief's assumption that Operator and Wavetable might be in Standard: per the page they are not.** (The earlier [acid-lines note](2026-11-02_acid-lines-to-live.md) lists Operator as an unchecked glide case; it can be dropped.)

### 4.2 Device capabilities that matter for a Goa recipe ([Live 12 manual: Instrument Reference](https://www.ableton.com/en/live-manual/12/live-instrument-reference/), [Audio Effect Reference](https://www.ableton.com/en/live-manual/12/live-audio-effect-reference/); fetched via the summarising tool)

| Device | Documented capabilities relevant here |
| --- | --- |
| Drift | Osc 1: Sine, Triangle, Shark Tooth, Saturated, Saw, Pulse, Rectangle; Osc 2: Sine, Triangle, Saturated, Saw, Rectangle with Detune in semitones; filter with Type I (12 dB/oct) and Type II (24 dB/oct), Freq, Res, Key, HP; Envelope 1 (amp) ADSR, Envelope 2 (mod) ADSR or cycling; voice modes Poly, Mono (Thickness, Legato, Glide), Stereo, Unison; Drift slider; Shape Mod sources include Velocity. **No separate sub oscillator parameter in the Drift text.** The [Cycling '74 page](https://docs.cycling74.com/reference/abl.device.drift~) (earlier note, finding 6) says glide needs mono voice mode and legato playing |
| Analog | Two oscillators (sine, saw, rectangle, noise; Pulse Width; Sync; Sub level one octave below), Detune up to 300 cents; two filters with 2nd/4th-order low-pass, band-pass, notch, high-pass, formant; Drive modes; per-envelope ADSR with Slope, **Env < Vel**, Loop; Unison with 2 or 4 voices and Detune; Glide with Time and Legato, Const or Prop mode; Freq Mod and Res Mod sources LFO, note pitch, filter envelope |
| Auto Filter | Low-pass, High-pass, Band-pass, Notch etc.; 12 or 24 dB/oct; Res; envelope follower; LFO; circuits SVF, DFM, MS2, PRD (the page lists these four); no numeric cutoff range stated |
| MIDI Arpeggiator, Scale, Chord, Note Echo | present in Standard (table above). Whether Scale can force a generated line into a chosen mode inside Live is not checked (Scale's behaviour was not read) |

### 4.3 Delivery matrix

| Element | As MIDI + recipe (Drift/Analog) | As rendered audio (engine) | Recommendation |
| --- | --- | --- | --- |
| Rolling bass (16th roll, first note quieter, 16th gate) | Fits: notes plus velocity profile; sound = Drift mono saw, Type II low-pass, Env 2 to filter with a short decay (the "pluck"); kick-gap in the line | One-shot per note (needs the bass voice); sidechain/phase handling in the mix is outside both | MIDI + recipe first |
| Sub drone | Fits: Analog Sub level or a Drift sine layer | Fits (a held sine is trivial and exact) | MIDI + recipe |
| Acid line (accent, slide) | Fits via existing `acid_midi`: accent = velocity 127; slide = overlap with legato + glide (Drift Mono Glide, Analog Glide Legato). Accent-to-cutoff needs the device to read velocity (Analog Env < Vel and Freq Mod sources; Drift Shape Mod Velocity source; **whether either lifts cutoff as the TB-303 accent does: inferred, not tested**) | Needs the swept resonant filter voice; gives exact accent/slide control and a fixed sound | MIDI + recipe first; audio later |
| Lead ostinato / arpeggio | Fits: notes; super-saw via Analog Unison (2 or 4 voices) or Drift Unison | Needs the stack voice | MIDI + recipe |
| **Cutoff sweep over 8-32 bars ("the melody")** | **Not carried by a `.mid`**: notes and velocity only. A CC lane might be mapped to a parameter in Live, but that mapping is **not established**; clip envelope writing via AbletonOSC is not a `tested` capability | Fits as a baked sweep in a rendered loop | The user draws the automation (one line in the recipe) or a baked loop; automation write is a bridge topic, not this one |
| Plucks, chord stabs | Fits (Drift/Analog, short filter envelope) | Fits as one-shots | MIDI + recipe |
| Pad | Fits (Analog/Drift, long attack) | Possible, low value | MIDI + recipe |
| FX riser | Noise in Analog plus Auto Filter; time-consuming to describe | Fits: seeded noise + swept band-pass + ramp, N bars long | Rendered audio |
| Delay / reverb | Live's Delay (Standard), Reverb | Not worth baking | Recipe only (whether Echo is in Standard is not established; use Delay) |

Test boundary: everything above that touches Live (drag-in of the `.mid`, device parameter names, glide behaviour) runs only on the user's Windows machine; CI can test the `.mid` bytes and the line generator only. The `acid_midi` module is pure and deterministic (its own docstring), so route (1) needs no new `capabilities.json` entry.

## 5. Proposal: `goa_line` parameter set (PROPOSAL ONLY, no contract exists)

`goa_line` is a superset of `acid_line` ("same steps, more roles"). Reason: `acid_midi.validate_line` rejects any other `format` string and caps `length` at 32 steps (2 bars), so the cheapest route is a pure adapter that rewrites `format`/`version` and passes `steps` and `render` through. Clips are loops: a 2-bar line loops in Live for 8-32 bars.

### 5.1 JSON shape

```json
{
  "format": "goa_line", "version": "0.1-proposal", "seed": 1234,
  "role": "roll_bass",
  "bpm_hint": 140,
  "root": "F", "root_octave": 1,
  "mode": "phrygian",
  "length": 16,
  "steps": [
    {"on": false},
    {"on": true, "note": 29, "accent": false, "slide": false, "degree": 0, "octave": 0, "vel_scale": 0.6},
    {"on": true, "note": 29, "accent": false, "slide": false, "degree": 0, "octave": 0},
    {"on": true, "note": 29, "accent": false, "slide": false, "degree": 0, "octave": 0}
  ],
  "render": {"velocity": 100, "accent_velocity": 127, "gate": 0.24, "slide_overlap": 0.03125}
}
```

(The example shows one beat; a real file has `length` entries. `vel_scale` is new and informational for the adapter, which would convert it to a velocity; `acid_midi` has no per-step velocity today.) `note` stays the only pitch input, as in `acid_line`.

### 5.2 Generator parameters (what the user/Claude steers; all ranges are starter hypotheses)

| Field | Type / range | Starter | Basis |
| --- | --- | --- | --- |
| `role` | `roll_bass`, `acid`, `lead_ostinato`, `arp`, `sub_drone` | `roll_bass` | roles from findings 5, 8, 13 |
| `bpm_hint` | 120-160 | 140 | findings 1-2; user range 136-146 (arrangement note) |
| `root` / `root_octave` | pitch class, bass octave 0-2 | F, 1 (43.65 Hz) | inferred; the user's kick tail is 45-60 Hz (clash risk, see section 3) |
| `mode` | `aeolian`, `phrygian`, `harmonic_minor`, `phrygian_dominant` or `auto` (seeded draw by the weights in 2.1) | `phrygian` | section 2 |
| `length` | 16 or 32 (steps) | 16 | `acid_midi` limit |
| `roll_pattern` (bass) | `three_after_kick` (steps 1,2,3 of each beat), `offbeat_8th` (step 2 of each beat), `gallop` (steps 1,3 of each beat, a guess at "galloping", **not established**), `full_16th` (not 0 mod 4 left empty) | `three_after_kick` | Bonedo #1 for the first two; the others are inferred |
| `kick_gap_steps` | subset of 0..3 per beat | {0} | the kick owns step 0 (Bonedo #1) |
| `roll_first_velocity` | 0.3-1.0 of normal | 0.6 | "played quieter", amount unspecified (Bonedo #1) |
| `octave_jump_prob` | 0-0.5 | 0 for bass, 0.15 for ostinato | no Goa source; hard-house octave bass exists (Producer School) |
| `rhythm_group` | `[3,2,3]`, `[3,3,3,3,4]`, `[4,4,4,4]`, `[3,3,2]` repeated | `[3,2,3]` | Aittoniemi (first two) |
| `accent_mode` | `group_starts`, `random`, `none` | `group_starts` | accents on the first step of each group (inferred) |
| `accent_density` | 0-0.5 of notes | 0.25 | none |
| `slide_prob` | 0-0.4 | 0.15 (acid role only) | none |
| `rest_prob` | 0-0.4 | 0.1 | none |
| `motif_steps` | 3-8 | 5 (acid/ostinato) | displacement idea (Aittoniemi); length is inferred |
| `phrase_change_bars` | 4, 8, 16 | 8 | Wikipedia (psytrance: change every 8 bars), moodbook-cited |
| `render.gate` | open interval (0, 0.25) beat (a `acid_midi` rule) | 0.24 for the roll (about one 16th), 0.125 for stabs | Bonedo #1: one 16th per hit |
| Sound (recipe fields, not MIDI) | `cutoff_start_hz`, `cutoff_end_hz`, `sweep_bars`, `res`, `env_decay_ms`, `glide_ms`, `unison_voices`, `detune_cents` | per section 3 | section 3 (all hypotheses) |

Determinism: the same `seed` and parameters must give the same `steps` (a seeded `random.Random`, no global state, no clock), so the MIDI bytes repeat. Property tests belong to the worker, not to this note.

## 6. Arrangement template (PROPOSAL; inferred from the documented grid, not from measured Goa tracks)

Basis: 8-bar change grid (finding 6), build-ups of 8/16/32 bars and four-beat pause (finding 7), main breakdown about two-thirds in (finding 7), rising accumulative form with a late climax and a fairly quick taper (findings 5, 6). The thesis' "rising sawtooth curve" is applied as: each section's energy peaks higher than the previous one's peak. Length: **288 bars = 9 x 32** = 493.7 s = **8:14 at 140 BPM** (arithmetic: 288 x 240 / 140), inside the 7-9 minute psytrance range of Bonedo and the 8-12 minute Goa figure of Wikipedia (uncited); 8:14 at 140 BPM is also 8:25 at 137 and 7:47 at 148 (467.0 s). Whether the intro/outro should be DJ-shaped is open question 2.

Element presence 0-1 (0 = silent, 1 = full level in that section); "E" = overall energy 0-1 at the section's end. Elements: **K** kick, **B** rolling bass, **S** sub drone, **A** acid line, **L** lead/ostinato, **R** arp/pluck, **P** pad, **H** hats/perc, **X** FX/riser.

| # | Bars | Section | K | B | S | A | L | R | P | H | X | E |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1-32 | Intro (K+H from bar 1, B enters bar 17 at low level, S from bar 25) | 1 | 0.3 | 0.5 | 0 | 0 | 0 | 0.3 | 0.5 | 0.2 | 0.35 |
| 2 | 33-64 | Groove A (acid line from bar 41) | 1 | 1 | 0.7 | 0.5 | 0 | 0 | 0.3 | 0.8 | 0.2 | 0.55 |
| 3 | 65-96 | Groove B (first lead motif, cutoff opens over 32 bars) | 1 | 1 | 0.7 | 0.7 | 0.6 | 0.4 | 0.4 | 1 | 0.3 | 0.7 |
| 4 | 97-112 | Break 1 (K and B out, L melodic, P up) | 0 | 0 | 0.6 | 0 | 0.7 | 0.6 | 0.8 | 0.2 | 0.4 | 0.35 |
| 5 | 113-128 | Build 1 (B returns filtered, snare-style roll, riser, 4-beat pause at bar 128) | 0.7 | 0.6 | 0.6 | 0.4 | 0.3 | 0.7 | 0.6 | 0.8 | 1 | 0.8 |
| 6 | 129-176 | Peak 1 (3 x 16 bars: acid + lead A, lead B, both) | 1 | 1 | 0.8 | 0.8 | 0.9 | 0.8 | 0.5 | 1 | 0.4 | 0.9 |
| 7 | 177-208 | Main breakdown at 61 % (16 bars melodic, 16 bars build) | 0 | 0 | 0.7 | 0.3 | 0.8 | 0.7 | 1 | 0.1 | 1 | 0.4 -> 0.85 |
| 8 | 209-256 | Peak 2 / climax (3 x 16 bars; highest lead, widest unison, fastest cutoff sweeps) | 1 | 1 | 0.9 | 1 | 1 | 0.9 | 0.5 | 1 | 0.5 | 1.0 |
| 9 | 257-288 | Outro (elements leave every 8 bars down to K+B; sub last) | 1 | 0.8 | 0.6 | 0.3 | 0 | 0 | 0.2 | 0.5 | 0.1 | 0.6 -> 0.2 |

Check: 32+32+32+16+16+48+32+48+32 = 288. Peak 1 (0.9) and the climax (1.0) rise as the thesis' accumulative form needs; the break at bar 177 sits at 61 % of the track, and sections 4 and 7 respect Bonedo's up-to-16 and up-to-64 limits. "Faster taper" (Wikipedia, uncited) would argue for a 16-bar outro; kept at 32 for the DJ requirement. All numbers in the table are **inferred**; none is measured on a Goa track.

## 7. Listening tests to calibrate with the user (no listening claims; every item is a question for the ear)

Each item is a blind pair or short set of renders/clips; the user chooses or rates; nothing here predicts the answer. Aim at 15-20 minutes in total, as in the kick tests (items marked R need rendered audio and wait for engine voices; the rest can run on MIDI in Drift/Analog).

| ID | Compare | What it settles |
| --- | --- | --- |
| G1 | Same material at 136 / 140 / 145 BPM | default tempo and the tempo range (finding 2) |
| G2 | Bass `three_after_kick` vs `offbeat_8th` vs `gallop` vs `full_16th` (same notes, same synth, kick present) | which roll the user means by "Goa" (finding 9 not established) |
| G3 | First roll note at 0.3 / 0.6 / 1.0 velocity | `roll_first_velocity` |
| G4 | Roll gate at 0.5 / 0.8 of a 16th, and at the maximum `acid_midi` allows (0.249 beat, just under a full 16th); a gate of exactly 1.0 of a 16th (0.25 beat) is refused by `acid_midi` (gate must be below 0.25 beat), so it needs the lead's decision on the gate rule (section 9, item 4) | `render.gate` |
| G5 | Bass with and without a held sub drone | whether the drone layer (finding 5) is wanted |
| G6 | Same rhythm in aeolian / phrygian / harmonic minor / phrygian dominant | mode weights (section 2.1) |
| G7 | Acid line: accents on 3+2+3 groups vs `random` vs none; slides 0 / 0.15 / 0.3 | `rhythm_group`, `accent_*`, `slide_prob` |
| G8 | Cutoff sweep over 8 / 16 / 32 bars on the same line (user-drawn automation, or R: baked loops) | `sweep_bars` and how fast the user wants the "melody" to move |
| G9 | Lead: unison 1 / 3 / 5 / 7 voices x detune 0 / 8 / 16 / 24 cents (R, or Analog unison 2 / 4 voices) | `unison_voices`, `detune_cents` |
| G10 | Pluck decay 60 / 150 / 300 ms (R) | `pluck_decay_ms` |
| G11 | Riser 4 / 8 / 16 bars (R) | `riser_bars` |
| G12 | Arrangement: 288-bar template vs a shorter 192-bar version with the same section order | length and intro/outro shape (open question 2) |
| G13 | **Reference intake (not a listening pair):** the user names 3-5 Goa tracks; the sound-designer measures tempo, bass rhythm, kick tail pitch, spectral centroid of leads | replaces the hypotheses in sections 3 and 6 |

## 8. Gaps, pitfalls and limits of this note

- **The scholarly source was read only in part.** The Academia copy of Aittoniemi (2012) was cut off before Chapter 4; I had its table of contents, figure captions and section 2.3. The bass rhythm (4.4.2), scales (4.3.4, 4.2.4) and "filter cutoff as an instrument" (4.4.4) text were **not read**. A worker or the lead should open the University of Helsinki repository copy (my attempt to reach it was blocked by the tool's permission prompt) before treating findings 3-5 as complete.
- **Commercial guides are weak sources.** ClassicTrance and Trance Nexus give no references; Trance Nexus' two track lengths contradict each other (8-12 and 8-10 minutes). Wikipedia's Goa page marks the squelch and gear claims "citation needed". The Gumroad course page, a KVR thread, a Gearspace thread and an Elektronauts thread were opened or tried and yielded nothing usable (the first listed no production details; two failed to load; the third held only a question).
- **Fetch-tool summaries.** Every page was read through a summarising model, not as raw text; Ableton's pages could not be fetched with curl from this sandbox. The edition table (4.1) is the item with the largest effect on the plan, so it deserves a one-minute check by someone looking at the page (or in Live's own device browser: if Operator or Wavetable show up, section 4 changes).
- **No Goa-specific psychoacoustic or measured data** (kick spectra, lead centroids, cutoff-sweep rates) was found. Section 3 therefore gives measurable quantities and methods, not targets.
- **Genre drift risk.** Most production recipes found describe modern psytrance (Bonedo does not use the word Goa). A generator built on them may produce a modern full-on feel; whether that is wanted is for the user (open question 1, G13).

## 9. Implications for the lead (proposals, nothing decided)

1. **File a parking-lot/feature issue "goa_line generator + Drift/Analog recipe"**, small: pure function `(params, seed) -> goa_line JSON`, adapter into `acid_midi` (rewrite `format`/`version`), tests like the acid ones; blocked by nothing in Live.
2. **Record the edition fact** (no Operator, Wavetable, Sampler, Meld, Max for Live in Standard; Echo and Roar not established) in the next State update, and check that no spec or recipe in the repo assumes them; grep of `docs/` shows Operator only in three research notes (acid-lines, bass-targets, snare-rim-bass), none a decision.
3. **Ask the user for 3-5 Goa references** before any engine voice (G13); the sound-designer then measures them. This is the cheapest way to replace every hypothesis in section 3.
4. **Decision for the lead:** whether the `acid_midi` `gate` rule (strictly below one 16th) and the 32-step cap are enough for `goa_line`, or whether a `contract-change`-style extension (per-step velocity, longer `length`) is wanted; the note recommends the adapter for now.
5. **Bridge side (not this track):** writing filter automation into a Live clip is the missing piece for "filter automation as the melody"; today the user must draw it. Worth one parking-lot line, not a task here.

### State update proposal (for the lead after merge; the researcher does not edit `CURRENT_STATE.md`)

- Goa track G1 done as research: `docs/research/2026-11-03_goa-trance-musicology-and-sound.md` (Refs #338).
- Known gap: Live 12 Standard lacks Operator and Wavetable (Ableton edition page, 2026-11-03); Goa recipes must use Drift/Analog.
- Known gap: no measured Goa references; the scholarly source (Aittoniemi 2012) was read only in part.
- Next: user supplies Goa references; then `goa_line` generator issue (small) and the sound-designer's measurement pass.

## Sources opened on 2026-11-03

[Wikipedia: Goa trance](https://en.wikipedia.org/wiki/Goa_trance) · [Wikipedia: Psychedelic trance](https://en.wikipedia.org/wiki/Psychedelic_trance) · [Wikipedia: Roland TB-303](https://en.wikipedia.org/wiki/Roland_TB-303) · [Wikipedia: Phrygian dominant scale](https://en.wikipedia.org/wiki/Phrygian_dominant_scale) · [Attack Magazine, Phrygian Mode](https://attackmagazine.com/technique/the-breakdown/julio-bashmore-au-seve/2) · [Aittoniemi 2012, Academia copy](https://www.academia.edu/65115221/Cultural_and_Musical_Dimensions_of_Goa_Trance_and_Early_Psychedelic_Trance_in_Finland_The_history_translation_and_localization_of_an_internationally_mobile_electronic_dance_music_scene) · [Bonedo #1 Kick, Bass, Percussion](https://www.bonedo.de/artikel/psytrance-produzieren-workshop-1-kick-bass-percussion/) · [Bonedo #2 Synths, Melodien, Sounddesign](https://www.bonedo.de/artikel/psytrance-produzieren-2-synths-melodien-und-sounddesign) · [Bonedo #4 Vocals, Arrangement, Mixing](https://www.bonedo.de/artikel/crashkurs-psytrance-produzieren-4-vocals-arrangement-mixing) · [ClassicTrance: Goa Trance](https://www.classictrance.com/subgenres/goa-trance) · [Trance Nexus: What is Goa Trance](https://trance-nexus.com/blog/what-is-goa-trance) · [Psytrance Guide](https://psytranceguide.com/) · [The Producer School: 5 bass patterns](https://theproducerschool.com/blogs/featured-blogs/5-essential-bass-patterns-that-define-hard-house-and-trance-music) · [Production Music Live: rolling bassline](https://www.productionmusiclive.com/blogs/news/how-to-make-a-rolling-bassline) (melodic techno, no Goa; only used to confirm that a roll with a quiet first 16th is described outside psytrance too) · [Ableton: compare editions](https://www.ableton.com/en/live/compare-editions/) · [Live 12 manual: Instrument Reference](https://www.ableton.com/en/live-manual/12/live-instrument-reference/) · [Live 12 manual: Audio Effect Reference](https://www.ableton.com/en/live-manual/12/live-audio-effect-reference/) · [JaraLuca Goa course page](https://jaralucastudio.gumroad.com/l/goa_course_3h) (no production content) · [Elektronauts thread](https://www.elektronauts.com/t/psytrance-kick-bass-parameters/253875) (question only). Not opened: KVR thread (failed), Gearspace Goa thread (failed), Helsinki repository (blocked).
