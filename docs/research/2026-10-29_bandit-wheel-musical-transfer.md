# Research: Bandit Wheel, musical transfer to more sample categories and to the arrangement planner

- **Date:** 2026-10-29.
- **Author role:** sound-designer.
- **Receiving issue:** #151 (user request 2026-10-29 16:47: reuse what the Bandit Wheel already knows). Also feeds the arrangement planner (D-024, [arrangement note](2026-10-29_arrangement-planner-sections-energy.md), #139) and the circle-picker categories (questionnaire tab 3, task B3).
- **Researched against:** the user's artifact "Bandit Wheel", local copy `bandit_wheel.html` (9,259 lines, HTML/JS) in the lead's session scratchpad. It was **read as text, not run**. Every `file:line` below refers to that copy. No web sources were opened for this note. Where the artifact cites sources, they are quoted second-hand and marked **S**.
- **Companion note:** the audio-engineer writes the technical/DSP transfer for #151 (voices, envelopes, filters, noise, determinism of the synthesis). This note covers only the **musical** side: roles, patterns, groove, keys, levels, arrangement, variations. Voice recipes (`dvHat`, `dvClap`, `dvSnare`, `dvPerc`, …) are left to that note.
- **Scope:** read-only. No code. Nothing here says how anything sounds. No artist or track names (the artifact has some in its genre "facts", e.g. `bandit_wheel.html:1251-1319`; none are carried over). Every value is a starting point for the user's ear, not a default.

## How to read this note

**Who decided what.** The artifact was built over several agent sessions with user feedback rounds (comments at `bandit_wheel.html:108`, `:2380`, `:3764`, `:6329`, `:7518-7525`). So "it is in his artifact" does not mean "the user chose it". Each finding carries one tag:

| Tag | Meaning | How much weight |
| --- | --- | --- |
| **U** | User decision, stated as such in the artifact ("feedback round", "decided with the user") or in our repo (`2026-10-28_kick-gen2-learnings.md`, section 1) | His taste. Highest weight. |
| **A** | Artifact design whose author is not established. The user kept it, but no comment says he chose it | Candidate taste. Confirm by ear before it becomes a default. |
| **S** | Convention the artifact attributes to sources (sources not opened here) | Second-hand convention |
| **G** | Generic convention (e.g. clap on 2 and 4, General MIDI drum notes) | Convention |
| **X** | Agent decision explicitly made **without** user feedback (`bandit_wheel.html:7525`) | No taste weight |

**Rule from the kick learnings note.** That note says not to port the prototype's value tables (`2026-10-28_kick-gen2-learnings.md`, "How to use this note", lessons P1 and P2). Issue #151 now asks for the knowledge transfer explicitly. This note therefore describes **structures and rules** with line references, and quotes single values only where a rule needs them. It does **not** propose copying the tables as defaults. Lesson P2 still holds and shapes the proposals below: 18 narrow genre profiles felt "too specific" to the user. Profiles should come back as data on one shared parameter space, ideally as a few families.

**Confidence (all questions).** **High** for what the artifact contains: it was read directly, with line references. **Low / _Interpretation_** for every proposal and every mapping onto our project. The **S** items keep the artifact's own second-hand weight.

**Pattern notation.** Steps are 16ths, 0-based, on a 2-bar grid of 32 steps (`bandit_wheel.html:2058`). Steps 0/4/8/12 are beats 1–4; step 2 is the offbeat 8th of beat 1.

---

## Q1. Which categories ("machines") and role tiers did the user design? (circle picker, task B3)

**Answer.** Ten machines, in this order (`bandit_wheel.html:7693-7705`):

| id | Label | One-line role in the artifact |
| --- | --- | --- |
| `kick` | KICK | "The boom under everything" |
| `hats` | HATS | "Top loops: hats, rides, shakers" |
| `clap` | CLAP | "The backbeat on 2 and 4" (hit types: clap, snare, clap+snare, rim) |
| `perc` | PERC | "Toms, congas, rims, bells", plus percussion layers |
| `bass` | BASS | "Rolling, offbeat, rumble, reese" |
| `acid` | ACID | 303-style line. Its role is decided at runtime: **bass** when no BASS plays, otherwise **lead** (`:4654-4677`) |
| `chord` | CHORDS | "Dub chords and rave stabs" |
| `lead` | LEAD | "Arps and hypnotic sequences" |
| `atmos` | ATMOS | "Pads, drones, textures" |
| `fx` | FX | "Risers, impacts, sweeps, fills". **Hidden from the wheel** after feedback: "FX left the loop (it made loops repetitive)". Transitions are placed by the track instead (`:7706-7708`, `:2380-2381`). **U** |

**Role tiers per genre.** Every genre lists its machines in three tiers: `recipe` = core, `extra`, `rare` (`:2145-2379`; tier lookup `bwRole`, `:2443-2448`). Two rules apply after the feedback round (`:2380-2389`), **U**:
- FX is never a loop element.
- CHORDS and LEAD never both count as core. The second one moves to `extra`, and in the track they play in different sections.

**Typical options per reel.** Each machine has reels with 4–10 options. The genre marks which options count as "typical" (★). Spins pick typical 70 %, the related style family 25 %, anything 5 % (`:2140-2144`, `:2893-2898`). **A**. A "TEXTBOOK" button returns the classic version directly (`:3198`, `:2015`). Never gating the best result is a user rule (learnings P1; rewards "never lock a feature, a genre or a sound", `:6329`), **U**.

**Core/extra/rare for the user's tempo range** (136–146 BPM; genres whose artifact BPM range overlaps it, `:5448-5452`):

| Genre id (artifact) | BPM range | Core | Extra | Rare |
| --- | --- | --- | --- | --- |
| `hg` hard groove | 135–145 | kick, hats, perc, clap, bass | chord, atmos | acid, lead |
| `peak` peak time | 128–140 | kick, hats, clap, bass, perc | chord, lead, atmos | acid |
| `acid` acid techno | 132–145 | kick, acid, hats, clap, perc | bass | chord, lead, atmos |
| `hardtech` hard techno | 145–160 | kick, bass, hats, clap, perc | chord, atmos | lead, acid |
| `goa` goa/psy | 135–150 | kick, bass, hats, lead, acid, atmos | clap | chord, perc |
| `prog` progressive trance | 126–138 | kick, bass, hats, clap, perc, chord | lead | acid |
| `hardtrance` hard trance | 140–150 | kick, bass, hats, clap, lead | chord, acid | atmos, perc |

(Lists after the rules at `:2384-2389` were applied, i.e. FX removed and the CHORDS/LEAD rule applied. Read from `:2146-2326`.) **A**, the BPM ranges **S** (`:5436-5442`).

**Transfer to the circle picker (proposal, _Interpretation_).** The task B3 text itself was not available to me; this follows the lead's brief.
- **Inner ring:** the categories in the user's wheel order: kick, hats, clap/snare/rim, perc, bass/rumble, acid. Then chords, lead, atmos as later categories. FX not as a loop category (**U**).
- **Per-genre-family marks** (core = filled, extra = outline, rare = hidden behind "more"), from the tiers above. Proposed as **data on one category list**, not as separate pickers per genre (learnings P2).
- **Sub-categories** per category, taken from the reel names: hats → RHYTHM, TONE, GROOVE, EXTRA; clap → HIT, BODY, GHOSTS, ROOM; perc → VOICE, PITCH, RHYTHM, MOVE; bass → STYLE, NOTES, LENGTH, SOUND (`:3610-3632`, `:3690-3711`, `:3791-3806`, `:3978-4012`). The reel names describe musical choices; most map onto future sample parameters. The mapping is the audio-engineer's call.

Confidence: **high** for what the artifact contains (read directly). **Low** for the picker proposal (interpretation).

## Q2. Genre profiles: what transfers, and in what form?

**Answer.**
- **Profile = role tiers + typical options + swing + scale + BPM range + arrangement family + break style + loudness target.** `BW_SPEC` (`:2145-2379`), `BW_GENRE_ARR` (`:2480-2486`), `BW_GENRE_EXTRA` (`:2489-2508`), `BW_BPM` (`:5448-5452`). **A** structure, **S** for the cited parts.
- **Style families.** 18 genres map onto 9 drum styles (`BW_STYLE_OF`, `:2848`): techno (hg, peak, dark, acid, ebm), hard (hardtech, schranz, hardstyle), trance (goa, prog, hardtrance), and house, garage, dnb, jungle, breaks, half. Patterns are written **per family, not per genre** (`rkPattern`, `:2059-2136`). This is the structure lesson P2 asks for. **A**.
- **Blending two genres** (`bwBlendSpec`, `:2397-2425`): genre A sets the drums, groove and scale. Both supply typical sounds. Swing is the mean of the two. An element is core if its tier score (core 2, extra 1) sums to ≥ 3. **A**.
- **Swing per genre** (`:2146-2367`): hard groove 54, house 54, tech house 56, UK garage 58, breaks 52. Every techno, hard and trance genre is **50 (straight)**. **A**.
- **Scale per genre:** minor everywhere except goa (Phrygian) (`:2146-2367`). **A**.

**What transfers (proposal).** Keep three families for the user's range: **techno** (hg, peak, dark, acid), **hard** (hardtech, schranz), **trance** (goa, prog, hardtrance). Each is one data block: tiers, typical options, swing, scale, BPM range, arrangement family. Genres become named presets inside a family. _Interpretation_, following learnings P2 and the user instruction "genre does not matter for now, but must stay possible later".

Confidence: high (content), low (proposal).

## Q3. Step patterns and groove per category

### 3.1 Groove and swing (all categories)

- **Swing formula** (`bwStepTime`, `:2879-2882`): every odd 16th is delayed by (swing/100 − 0.5) · 2 · one 16th. So 54 % moves the odd 16ths by 8 % of a 16th. **A**.
- **Hat groove offsets** on top of the song swing (`:3622-3626`, applied at `:3658`): STRAIGHT 0, LIGHT SWING +5, SHUFFLE +12, PUSHED −5 (hard styles only; it moves the odd 16ths *early*). Clamped to 44–75. **A**.
- The 303 converts swing with its own scale (`:4122`, `:2679`). The swing amount can therefore differ between machines; cause and effect not checked (to verify, V9).

Offsets computed with `numbers.py` (session scratchpad `sd151/`, re-typed formula, not the artifact's code; run as `python3 -I numbers.py`):

| Swing | 136 BPM | 140 BPM | 146 BPM | Share of a 16th |
| --- | --- | --- | --- | --- |
| 52 | 4.4 ms | 4.3 ms | 4.1 ms | 0.04 |
| 54 | 8.8 ms | 8.6 ms | 8.2 ms | 0.08 |
| 56 | 13.2 ms | 12.9 ms | 12.3 ms | 0.12 |
| 58 | 17.6 ms | 17.1 ms | 16.4 ms | 0.16 |

### 3.2 Hats (`rkPattern` hats, `:2064-2104`; machine `:3600-3677`)

Techno, hard and trance family, per 16th position in the beat:
- **Offbeat 8th** (pos % 4 = 2): always a hit. Closed at 0.85 velocity, or open if the OPEN knob is > 15 (velocity 0.75–0.95).
- **On the beat** (pos % 4 = 0): closed at 0.45, with probability density · 0.45.
- **Other 16ths:** probability = density (trance: 0.5 + 0.5 · density), velocity 0.5–0.75.

So the offbeat carries the accent and the beat positions stay mostly free for the kick. **A**, consistent with **G**.
- An open hat is **choked** by the next hat hit, at most 8 steps later (`:3662-3665`, fade at `:2965-2972`). **G** (classic drum machine behaviour).
- **Top layer** (EXTRA reel): ride or shaker. The ride plays offbeat 8ths when density < 0.45, otherwise 8ths accented on the offbeat (`:2123-2134`). **A**.
- RHYTHM reel presets set density: 16TH ROLL 65, 8THS 30, BUSY 90, SPARSE 12 (`:3612-3616`). **A**.
- MIDI notes: closed 42, open 46, ride 51, shaker 70 (`:3672-3676`). **G** (General MIDI).

### 3.3 Clap / snare / rim (`:2105-2113`; machine `:3680-3750`)

- **Backbeat:** steps 4 and 12 (beats 2 and 4) in every bar; half-time styles use step 8 only (`:2106`). **G**.
- **Ghost candidates by family** (`:2107`): techno 15 and 7, hard 15, trance 15. Each is placed with probability ghost-density · 0.6, velocity 0.3–0.5, and played at 0.6 of the main gain (`:3735-3740`). **A**.
- **HIT reel:** CLAP (techno/house/trance/hard), SNARE, CLAP+SNARE (both layered at 0.6 each), RIM (`:3691-3696`, `:3721-3733`). **A**.
- **Genre picks in the user's range** (`:2151-2321`): techno genres mostly CLAP or CLAP+SNARE with NONE/FEW ghosts. Dark techno allows RIM. Trance: CLAP, with no ghosts in prog and hard trance. **A**.
- MIDI notes: clap 39, snare 38, rim 37 (`:3742-3747`). **G**.

### 3.4 Percussion (`:2114-2122`, machine `:3753-3893`)

- **Even spread:** k hits per 16-step bar, placed where (i·k) mod 16 < k. That is an evenly spaced (Euclidean-type) rhythm, rotated by a seeded offset 0–15, with k = 2 + round(hits/100 · 6), i.e. 2–8 (`:3848-3851`, `:3842`). With 60 % probability one hit in bar 2 moves by one step (`:3852`). Reel labels: "3/4/5/7 OVER 16". **A**.
- **Tuned to the key:** the drum sits on a scale degree (ROOT, FIFTH, "MINOR 3RD" = degree 3, OCTAVE). Octave per voice: conga 4, tom 3, rim 6, bell 5 (`:3793-3800`, note at `:3858`). Observation: "MINOR 3RD" uses scale degree 3. In a major mode that is a major third. **A**.
- **Movement:** PAN SWAY (one sine cycle per bar), ACCENTS (beats louder), ECHO (copy 3 steps later at 0.3 gain, mirrored pan). See `:3862-3872`. **A**.
- **Decay ranges per family:** "short dry knocks in techno and hard styles". Techno decay 12–38, hard 8–28, trance 18–42 (knob units 0–100) (`:3750-3763`). **A**.
- **Toms off by default** except in hard groove: "they turned cool loops goofy" (`:3764-3765`). **U**: a stated taste.
- **Percussion layers** (players, `:3486-3496`), each a fixed 2-bar pattern. **A** patterns, **G** idea:
  - shaker: 16ths, offbeat accent.
  - tambourine: offbeat 8ths plus a pickup on step 31.
  - congas: two tones in a tumbao-type pattern.
  - bongos: 8ths, the high drum answers.
  - clave: steps 0, 3, 6, 10, 12, i.e. the 3-3-4-2-4 pattern.
  - cowbell: sparse.
  - metal hits: 5 sparse hits.
  - tom groove: fills the gaps.
- **Which layers per genre** (`:2489-2508`, typical / optional). **A**:
  - hard groove: conga, shaker, tom / clave, bongo, metal.
  - peak: shaker / tom, tamb, metal, clave.
  - dark: metal / shaker, tom.
  - acid: none / shaker, cowbell, clave.
  - hard techno: shaker / metal, tom.
  - schranz: metal, shaker / tom.
  - prog: shaker, tamb, conga / bongo, clave, cowbell, tom.
  - goa and hard trance: none / shaker, tamb.
- Layers stay out of the DJ intro and outro, and come in wherever the main perc plays (`:4789`). **A**.
- MIDI notes: General MIDI per layer (`:3886-3888`). **G**.

### 3.5 Ghost kicks (quiet extra kicks; `:3461-3466`, render `:3588-3591`)

Three patterns, velocity 0.35–0.55:
- `pre`: steps 7, 15, 23, 31, the last 16th before beats 3 and 1. The label says "before 2 + 4"; the steps sit before beats 3 and 1.
- `bounce`: the last 16th of every beat.
- `roll`: step 7, then 29–31.

The ghost is the same kick with an 80 ms fade at 0.55 gain, "so it pushes without adding low-end mud" (`:3589`). Typical only in hard groove; offered in peak, dark, hard techno, schranz and tech house (`:2490-2499`). **A**. Relevant later for kick variants. Out of scope for #151.

### 3.6 Bass / rumble (machine `:3968-4099`)

STYLE reel positions inside each bar (`:4019-4030`):

| Style | Steps per bar | Kick collision | Typical in |
| --- | --- | --- | --- |
| OFFBEAT | 2, 6, 10, 14 (offbeat 8ths) | skipped where the kick plays | techno, trance, house, hard |
| ROLLING | 1, 2, 3 after every beat ("kick, bass, bass, bass") | skipped | trance, techno |
| RUMBLE | 1, 5, 9, 13 (the 16th after every kick), long (up to 3 steps) | — | hard, techno |
| RUNNING 16THS | every 16th; degree 4 on 16ths 4/12, degree 7 on 6/14 | — | trance, house, techno |
| SEQUENCE | 8ths | — | techno, hard (EBM) |
| REVERSE | 1, 5, 9, 13, swelling up to the next kick | skipped | hard (hardstyle) |
| GROOVE / REESE / WOBBLE / DUB SUB | syncopated, outside the user's genres | — | house, dnb, half |

- **NOTES reel** (scale degrees, `:3991-3997`): ROOT ONLY, ROOT + 5TH, OCTAVES, MINOR WALK (0, 2, 3, 4), 7TH DROP, ARP. **A**.
- **Note length** (`:4051-4062`): at most 2 steps (rumble 3), scaled by the LENGTH knob from 30 % to 100 %. **A**.
- **Duck:** the bass always ducks under the kick. Default duck 70 → depth 0.6 (`:3974`, `:4090`, envelope `:3912-3926`: 4 ms attack, 110 ms release constant). Tip: "the bass steps aside every time the kick hits" (`:3202`). **A**, **G**.
- **Genre picks in range** (`:2153-2322`). **A**:
  - hg: GROOVE/OFFBEAT, minor walk.
  - peak: OFFBEAT/RUMBLE/RUNNING, root only or root + 5th.
  - dark: RUMBLE/OFFBEAT, root only, long, sine sub.
  - hardtech: RUMBLE, root only, dirty.
  - goa: ROLLING, short.
  - prog: OFFBEAT/RUNNING, warm saw.
  - hardtrance: RUNNING/OFFBEAT/ROLLING, short.

**Bass register vs kick tuning.**
- Sub styles (rumble, reese, sub, reverse) put the bass root at MIDI 28 + ((key − 4) mod 12), i.e. **E1–D#2 = 41.2–77.8 Hz**. Other styles sit one octave higher, 82–156 Hz (`:4013`).
- The artifact's kick tunes its tail to MIDI 27 + ((key − 3) mod 12), i.e. **D#1–D2 = 38.9–73.4 Hz** (`:1368-1371`).
- So a sub-style bass on the kick's pitch class sits **in the same octave as the kick tail**. The one exception is D#, where the two are an octave apart.
- The user's measured kick taste is 45–60 Hz tail fundamental (`2026-10-28_kick-gen2-learnings.md`, section 2).
- Whether the kick key and the song key are linked in the artifact: **not established** (not traced).

### 3.7 Acid (`ACID` block, `:2512-2836`; machine `:4103-4200`)

The block's comments are in German, unlike the rest of the file. That suggests it comes from an earlier separate tool. Whether the user wrote it is **not established**.
- **Interval weights for note choice** (`:2529-2530`): root 10, fifth 7, minor third 6, minor seventh 5, b2/m6 (1, 4) 4. The comment says root, fifth, minor third and minor seventh "carry acid". **A**.
- **11 modes**, each a set of probabilities: density, tie, mutation, accent, slide, octave jumps, note pool size, knob ranges (`:2533-2556`). **A**. Several modes are **per section**:
  - `buildup`: "the filter opens, notes get denser, the last bar rolls up".
  - `drop`: "wide open, hard accents".
  - `breakdown`: "lots of space, long slides".
  - `outro`: "the filter closes and the line thins out".
  - Loop modes: `driving`, `hypnotic`, `squelch`, `rolling` (offbeat bass), `minimal` ("two notes … a DJ tool"), `melodic`, `stabs`.
- **Family defaults** (`:4102`): techno → driving, hard → squelch, trance → rolling. Genre picks (`:2154-2323`): acid techno driving/squelch/hypnotic, goa squelch/melodic/driving, hard trance squelch/drop. **A**.
- **Pattern rules** (`genPattern`, `:2572-2656`):
  - A 4/8/16-step rhythm cell is tiled and lightly mutated.
  - The note walk moves in steps of ±1–2 inside the pool and returns to the root on 8-step anchors.
  - Every 4th bar: 30 % note variation.
  - Fill in the last 4 steps of every 8-bar phrase.
  - Build mode: thins out first, then rolls the last 2 bars with an octave jump at 75 %.
  - Outro mode: thins non-beat steps with probability rising to 65 %.

  **A**.
- **Filter automation shapes** (`autoAt`, `:2659-2670`), in octaves of cutoff offset: `rise` −2.4 + 3.3·t^1.7, `fall` 0.6 − 3.0·t^0.8, `wobble` (2-bar sine), `breathe` (4-bar sine), `tweak` and `slow` (sines). **A**.
- **Role rule** (`:4654-4677`):
  - ACID is the bass if no BASS plays (it then ducks under the kick).
  - Otherwise ACID is the lead, with a 160 Hz low cut.
  - Both as bass gives the warning "Two basslines".
  - LEAD + ACID-as-lead = "two hooks": in the track they take turns (acid in groove and switch sections, lead in the drops).

  **A**.

## Q4. Key and scale handling

- **Scales:** six modes, ordered dark → bright: Phrygian, minor, Dorian, Mixolydian, major, Lydian (`:2842-2846`). The 303 has 10, including harmonic minor, minor pentatonic, blues and Phrygian dominant (`:2517-2528`). **G**.
- **One key and one tempo per track**, "so DJs can mix it". Section moods may change scale colour, filters and width, but never tempo or key (`:5430-5434`). Kick, bass and fx never take a section mood (`BW_MOOD_FIXED`, `:5550`). **A**.
- **Everything melodic or tuned is written in scale degrees** (`bwDegree`, `:2884-2889`; `bwScaleShift`, `:6002-6008`): bass, percussion tuning, perc layers, acid pool. Changing key or scale re-tunes all of them at once. **A**, and _Interpretation_: this is the property worth keeping.
- **Note spelling:** flats or sharps follow the parent key (`bwSetKey`, `:2866-2872`). The track also gets a **Camelot code** for DJs (`:5268-5270`). **G**.
- **Clash rule** (symbiosis option, `:7536-7570`): avoid a minor second or a tritone against the sounding chord. Accented notes may move at most one scale step onto a chord tone. **G** for the rule. The default level GENTLE is **X** (an agent decision without user feedback, `:7525`).
- **Mood → scale** (`bwMoodScale`, `:5507-5513`): "sad" stays at minor or darker; "hopeful" goes one step brighter; "euphoric" goes 2–4 steps brighter. **A**.

## Q5. Level and mix heuristics

**Loop levels relative to the kick** (`BW_LOOP_LVL`, `:4978-4982`). The artifact itself says: "There is no published standard for these numbers … starting values from common club-mix practice" (`:4975-4977`). I = integrated loudness of the loop minus the kick loop's integrated loudness (LU). M = cap on the loudest 400 ms against the same reference.

| Element | I (LU vs kick) | M cap | Genre shifts in the user's range (`:4984-4990`) |
| --- | --- | --- | --- |
| hats | −10 | −5 | hard groove +1, hard techno +2, schranz +3 |
| clap | −5 | −1 | schranz +1 |
| perc | −11 | −5 | hard groove +3, hard techno +2, schranz +3 |
| bass | −3 | 0 | schranz −2 |
| acid (lead role) | −7 | −3 | acid techno +2, goa +2 |
| acid (bass role) | −3 | 0 | — |
| chord | −10 | −6 | prog +1 |
| lead | −8 | −4 | goa +2, prog +1, hard trance +2 |
| atmos | −22 (I), −15 (M) (`:4922`) | | |
| transitions (momentary, `:4922`) | riser −10, roll −11, impact −7, crash −15, downlifter −14, fill −12 | | |

- **Why the table exists:** before it, each machine had a fixed trim; "measured: hats and clap only 3-4 dB under the kick, perc spreading 8 dB between rolls" (`:4970-4973`). Measured in the artifact; our session did not re-measure. **A**.
- **Clean-up EQ per element** (`bwEqDef`, `:4680-4694`): a low cut per element, each with one −1.5 to −3 dB bell. **A**, **G** practice.
  - Low cuts: kick 28 Hz, bass 32 Hz, perc 110 Hz, fx 140 Hz, acid as lead 160 Hz, clap 180 Hz, chord 220 Hz, lead 260 Hz, atmos 300 Hz, hats 420 Hz.
  - Then mono below 120 Hz for every loop (`:4751`).
  - Pad clash (chord pad + atmos pad): atmos low cut 500 Hz and −2.5 dB (`:4664-4666`, `:4711`).
- **Hard-genre grit:** schranz and hard techno add drive plus fast compression to hats, clap, perc and bass (`BW_GRIT`, `:4712-4738`). Basis cited: "heavily compressed and filtered loops", **S**.
- **Master loudness target per genre** (`BW_GENRE_ARR`, `:2480-2486`): −7 LUFS for techno and goa, −6 for hard styles and hard trance, −8 for prog and house. The track rating accepts −8.3 … −5.8 and true peak ≤ −1 dBTP (`:6291-6292`). **A**. Our [mix-loudness note](2026-10-29_mix-loudness-targets.md) found **no** published club target and treats the −11 … −6 LUFS chart range as a reference, not a target. These artifact numbers therefore carry no source weight.
- **Melodic density:** at most "one or two" melodic layers in front. The artifact warns at four (`:4673-4674`, `:6261`). **A**.

Mapping to our engine: these are **mix/arrangement** heuristics. They matter once several categories play together (arrangement planner A10, Live import). For a single one-shot sample the per-element level is not defined. A one-shot has no "loop loudness vs kick". _Interpretation_.

## Q6. Arrangement: what the artifact does vs the D-024 planner note

**Section types** (`BW_SECT`, `:2456-2469`) map onto the planner note's 7 types:

| Artifact | Planner note type | Artifact rule (from `bwDefaultOn`, `:4762-4788`) |
| --- | --- | --- |
| INTRO (16) | `intro`, first half | kick, hats, perc |
| INTRO 2 (16) | `intro`, second half | all drums; "the clap joins. Still no bass" |
| STEADY `groove` (32) | `groove` | drums, bass, atmos, chords, hook-acid. Lead only outside techno |
| SWITCH `groove2` | `groove` | "the hook steps back, the groove carries" |
| BUILD (16) | `build` | clap, hats, perc, atmos, chord, lead, kick. Bass only if coming from a groove |
| DROP / DROP 2 / PEAK (32) | `drop` | everything (except lead when it would clash with acid as hook) |
| BREAK, techno 16 "subtle" | `break` | no kick, no bass. Hats, perc and melodic parts stay |
| BREAK, trance 32 "melodic" | `breakdown` | melodic parts only |
| OUTRO (16) | `outro`, first half | all drums, **no bass** |
| OUTRO 2 (16) | `outro`, second half | **kick and hats only** |

Template lengths (`BW_ARR`, `:2470-2478`, sources **S** at `:2450-2455`), times from `numbers.py`:

| Family | Sections | Bars | 136 / 140 / 146 BPM |
| --- | --- | --- | --- |
| techno | intro 16 · intro2 16 · groove 32 · build 16 · drop 32 · break 16 · drop2 32 · outro 16 · outro2 16 | 192 | 5:39 / 5:29 / 5:16 |
| trance | intro 16 · intro2 16 · groove 32 · build 16 · drop 32 · break 32 · build2 16 · drop2 32 · outro 16 · outro2 16 | 224 | 6:35 / 6:24 / 6:08 |

The artifact's trance template has the same order and the same 224 bars as the planner's **T3 Trance**. The techno template is the planner's T2 without its 8-bar break and 8-bar build, and with only one build.

**Events** (`bwPlanEvents`, `:4810-4837`):
- Before every drop: a riser over the last 8 bars, and a snare roll over the last 4 in roll genres. Roll genres are the trance, hardstyle, dnb and half families plus hard techno and schranz.
- In a build: over the last 4 bars, a **bass fade-out** and a **kick-out**; a high-pass sweep over the whole build.
- An impact on bar 1 of every drop. A crash on every groove after the first section.
- Into a break: a reverb throw on the last beat, then a 2-bar downlifter.
- In a break: a low-pass that opens over 75 % of it. In the groove: chords open over the whole section.
- **Fills every 8 bars**, "big" on every 16th bar, never in intro, outro or break. Where a riser leads into a drop, the riser replaces the fill.
- Roll subdivision per quarter of the roll: 4, 8, 16, 16 hits per bar, doubled in the last bar (`:4949-4955`).

**A**, with **S** for the general shape.

**Energy base values** (`BW_RATE_BASE`, `:6184`) vs the planner note's defaults (section 4):

| Type | Artifact | Planner note |
| --- | --- | --- |
| intro / intro2 | 0.25 / 0.35 | 0.30 → 0.45 in 8-bar steps |
| groove / groove2 | 0.65 / 0.70 | 0.60 → 0.70 |
| build / build2 | 0.55 / 0.60 | ramp from previous to next |
| drop / drop2 / peak | 0.90 / 0.95 / 1.00 | 0.90–0.95; drop 2 0.95–1.00 |
| break | 0.30 | breakdown 0.30 → 0.20 → 0.35; break 0.45 |
| outro / outro2 | 0.30 / 0.20 | ≤ 0.55 → 0.25 in 8-bar steps |

The two shapes agree within about 0.1 everywhere except the short `break`. They came about independently: the artifact was not used for the planner note.

**Differences the user should decide (proposals, not decisions):**

| # | Topic | Artifact | Planner note default | Proposal |
| --- | --- | --- | --- | --- |
| D1 | **Bass in intro and outro** | out of the whole intro and outro. The track rating subtracts points for bass in the intro: "so two basslines never clash while mixing" (`:6271`, `:2458`) | `intro_outro_bass = on` (bass stays to the outro's last bar) | The user's own artifact points to `off` or `outside_mix_zone`. Ask the user which default he wants (listening plan step 1). The setting already exists (D-024) |
| D2 | **Change grid** | 16-bar phrases; the rating warns on any section that is not a multiple of 16 (`:6277`) | `change_grid = 8` | Keep 8 as a setting; offer 16 as an option. Ask the user |
| D3 | **Kick before the drop** | kick out for the last 4 bars of every build (`:4820`) | `pre_drop_gap` = 1 bar; `build_kick = filtered_in_build` | Add "2 bars" and "4 bars" to the allowed `pre_drop_gap` values (planner contract, A5). The user picks the default |
| D4 | **Clap in the intro** | joins at bar 17 (intro2) | clap threshold 0.55 is above intro energy 0.30–0.45, so no clap in the intro | Ask the user; the artifact gives one data point for "clap in the 2nd half of the intro" |
| D5 | **Fills** | every 8 bars, bigger every 16 | one fill before a section change (T4) | Make fill density a setting (`fills`: `off`, `section_change`, `every_8`) |
| D6 | **Two hooks** | lead and acid take turns between sections | no rule | Add a planner rule: at most one hook element per section by default (_Interpretation_ of `:4667`, `:4670`) |
| D7 | **Melodic parts in a techno break** | "subtle" break keeps hats and perc | `break` keeps drums except kick and bass | Same. Nothing to change |

**Track rating as a checklist** (`bwRateTrack`, `:6206-6300`). Several checks are planner tests waiting to be written:
- intro ≥ 16 bars, kick in bar 1;
- outro ≥ 16 bars;
- every drop has kick and bass;
- the climax lies between 35 % and 90 % of the track;
- an energy dip before the last drop;
- energy range ≥ 0.3;
- no section that copies an earlier one of the same type;
- not 32 bars without any change;
- 0.5–9 variations per 16 bars;
- BPM inside the family range;
- the first kick on sample 0.

**A**; the sources for the DJ-intro parts are **S** (`:2450-2455`).

## Q7. Variations per section

- **Eight kinds** (`BW_VAR_KINDS`, `:5895-5904`): fill, mute, filter (up or down), mutate (a few notes/hits move), add (extra hits or a perc layer), throw (last beat into reverb), octave, accent. **A**, each a **G** technique.
- **Allowed per element** (`BW_VAR_OF`, `:5906-5917`). **A**:
  - kick: fill, mute, accent only ("a kick never gets filtered or thrown").
  - hats: fill, add, mutate, mute, filter, accent.
  - clap: fill, add, mute, filter, throw, accent.
  - perc: fill, add, mutate, mute, filter, throw.
  - bass: mutate, octave, add, mute, filter, accent.
  - acid: mutate, mute, filter, throw, accent.
- **DJ zone** (`:5919-5925`): in intro and outro there are no kick, bass or acid variations, and other elements only get filter, add or fill. "The DJ intro and outro stay steady so a DJ can mix." **A**. This matches the planner note's mix-zone idea.
- **Section sliders** [variance, energy, density, surprise] with defaults per section type (`:5927-5933`): intro 25/40/40/5, build 60/80/65/25, drop 50/75/55/20, break 35/30/30/30, peak 65/90/70/30, outro2 20/30/30/0. Variance sets the period: "something every 16 / 8 / 4 bars" (`:5934`). Energy and density shift the kind weights: more fills/adds/accents at high energy, more mutes/throws at low energy (`:5942-5946`). **A**.
- **Placement:** one slot per period. A variation sits at the **end** of its block (mutate at the start). It is 1 bar for fill/throw, 1–2 bars for mute, 2–4 bars otherwise (`:5950-5961`). Variations are deterministic from section seed + spin number + element (`:5963-5987`). **A**.
- **Long patterns:** forms AABA, ABAB, AAAB, ABAC over 16–48 bars for hats, clap, perc, bass, acid, chord, lead (`:6086-6127`). B and C parts are mutate/add/octave variants of A. **A**, the forms **G**.

Transfer: the planner's "parameter changes inside a phrase" (note section 5) and the T4 fill rule can take this set almost as is. It is a contract question for A5 (`events[]` would gain a `variation` kind). _Interpretation_.

## Q8. What does not transfer

| Item | Where | Why not |
| --- | --- | --- |
| Gamification: coins, ranks, badges, themes, rare "gold" draws | `:6333-6370`; learnings P1 | User: never gate the best result (**U**) |
| 18 separate narrow genre profiles reachable only through discrete reel steps | `:2145-2379`; learnings P2 | "Too specific" (**U**). Use families as data on one parameter space |
| Genre "facts" with artist and label names | `:1251-1319` | Project rule: no artist or track names |
| Random seeds and spin tiers from `Math.random`, random section ids | `:2054`, `:2859`, `:3271`, `:3524`, `:5375` | D-005: the seed must be an explicit, stored input. Patterns are then reproducible: the PRNG is seeded (`:2045-2053`) |
| Symbiosis default level | `:7525` | Agent decision without user feedback (**X**) |
| Quiz-to-mood mapping | `:5460-5530` | No basis beyond the artifact. Possible later chat vocabulary ("darker", "wider"); park it |
| Web Audio voices and offline rendering | throughout | Technical side; covered by the audio-engineer note |

---

## Per-category transfer tables

### Clap / snare / rim (questionnaire rank 1)

| Transfers | Transfers with changes | Does not transfer |
| --- | --- | --- |
| Backbeat on 2 and 4 (**G**); hit types clap, snare, clap+snare, rim; ghost positions per family (techno 7 + 15, trance 15); the clap's level about 5 LU under the kick in a loop (**A**) | Ghost density as a seeded, stored parameter instead of a random spin; for **one-shots** only the hit type, body (tight/punchy/long/bright) and room choice matter: these are sample parameters for the audio-engineer, while the pattern belongs to the planner/MIDI side | Spin tiers (70/25/5) as the only way to reach an option |

### Hats (rank 2)

| Transfers | Transfers with changes | Does not transfer |
| --- | --- | --- |
| Offbeat-accent rule for techno/trance; open hat choked by the next hat (**G**); top layer ride/shaker; hats about 10 LU under the kick (**A**) | Groove offsets (light swing +5, shuffle +12, pushed −5) as a stored setting; tone presets (bright, dark, metallic, dusty) as sample-parameter starting points, values set by the audio-engineer | — |

### Percussion (rank 3)

| Transfers | Transfers with changes | Does not transfer |
| --- | --- | --- |
| Evenly spread k-of-16 hits with rotation; tuning to scale degrees; short decays for techno/hard; **toms off by default outside hard groove (U)**; layer players and the per-genre layer list; layers out of the DJ zone | Rotation and per-hit velocity from an explicit seed; the "MINOR 3RD" degree label should become "third" (major in major modes); decay ranges re-expressed in our parameter units | — |

### Bass / rumble / acid (rank 4)

| Transfers | Transfers with changes | Does not transfer |
| --- | --- | --- |
| Style positions (offbeat, rolling, rumble, running, sequence); skipping kick steps; always ducking under the kick; ACID is the bass when no bass plays, otherwise the lead with a low cut; the "two basslines" and "two hooks" rules; the acid interval weights; acid modes per section (buildup/drop/breakdown/outro) | Bass register relative to the kick tail (hypothesis H5); duck depth and release as a stored setting | Reese, wobble, dub sub (outside the user's genres; keep only as data) |

### Arrangement planner (D-024)

| Transfers | Transfers with changes | Does not transfer |
| --- | --- | --- |
| Section types and element on/off per type (Q6); events (riser, roll, impact, crash, throw, downlifter, filter opens); fill rule; DJ-zone rules; variation kinds and per-element limits; section slider defaults; rating checks as tests | Differences D1–D7 as settings with a user-chosen default; 16-bar phrases → setting `change_grid` | Score verdicts ("CLUB READY") as a quality claim; master LUFS targets as targets |

## Hypotheses for the user's ear

Each item is a **hypothesis**. The measurement can confirm that the signal property is present; only the user's ear decides whether he wants it.

| # | Hypothesis | Measurement that confirms or rejects the property | What it would move |
| --- | --- | --- | --- |
| H1 | The user prefers intro and outro **without bass** for mixing (his artifact does this) | In a rendered outro: energy below 120 Hz between the kick hits (window from 60 ms after each kick onset to the next onset) is at least 20 dB below the groove's value | Planner default `intro_outro_bass` |
| H2 | Straight 16ths (swing 50) fit his techno/trance range. Light swing (52–54, 4–9 ms) belongs to hard groove only | Onset times of the odd 16ths vs the grid in the rendered hats/perc, against the table in 3.1 | Family swing defaults |
| H3 | Toms in the percussion layer make loops "goofy" for him outside hard groove (**U**, already stated) | Not a signal question. Confirmed by his statement; re-check only if he asks | Perc voice default |
| H4 | Loop levels vs the kick (hats −10, clap −5, perc −11, bass −3 LU) are a usable starting point | Integrated loudness (BS.1770) of each rendered stem minus that of the kick stem, same section | Planner/mix defaults (later) |
| H5 | A sub-style bass whose root shares the kick's pitch class in the same octave (artifact behaviour) competes with the kick tail more than a bass one octave up | During the duck release (0–150 ms after the onset), the band energy at the kick's tail fundamental with and without bass; plus the pitch-class interval kick vs bass root | Bass register default; kick key choice |
| H6 | A clap entering in the second half of the intro (bar 17) suits him better than no clap in the intro | Not a signal question; listening plan step 3 | Planner threshold for clap in `intro` |

## Listening-test plan (under 15 minutes, in the user's own Bandit Wheel)

No new render is needed: the user can open his artifact. The lead or the user sets it up; every answer is "to be checked by ear". Genre **Peak Time** (or Hard Groove for step 2), 140 BPM if the range allows; otherwise use the top of the range, 140. One question per pair.

1. **Outro bass (H1, D1), 4 min.** Build the track. Play the last 32 bars once as built (no bass). Then play them again with BASS switched on in OUTRO and OUTRO 2. Question: *"Soll der Bass bis zum Ende des Outros bleiben?"* Answer → `intro_outro_bass` default.
2. **Swing (H2), 3 min.** Same loop, hats GROOVE reel on STRAIGHT, then on LIGHT SWING. Question: *"Welche Variante passt zu deinen Tracks?"* Answer → family swing default.
3. **Clap in the intro (H6, D4), 3 min.** Play INTRO + INTRO 2 as built (clap from bar 17). Then mute CLAP in INTRO 2. Question: *"Soll die Clap schon im Intro kommen?"*
4. **Kick-out before the drop (D3), 3 min.** Play BUILD → DROP as built (kick out for 4 bars). Question: *"Ist eine 4-Takt-Pause der Kick vor dem Drop zu lang, richtig oder zu kurz?"* Answer → `pre_drop_gap` values.

Order: 1 → 4. Steps 1 and 3 feed settings that already exist (D-024), so they come first.

## To verify by experiment

Each item becomes an issue for the owning role (the lead files them).

| # | What | How | Owner | Where |
| --- | --- | --- | --- | --- |
| V1 | Defaults D1, D3, D4 and swing (H1, H2, H6) | Listening plan steps 1–4 | user (by ear); set-up by the lead | user's PC |
| V2 | Planner settings: `pre_drop_gap` gets 2 and 4 bars; `fills` gets `every_8`; `change_grid` keeps 16 as an option; one-hook rule (D3, D5, D2, D6) | Contract proposal for task A5. Property test: every generated plan keeps fills/gaps on the grid for every setting value | contract owner for the plan format | CI |
| V3 | Rating checks (Q6 list) as planner tests | Seeded property tests over generated plans; fault injection (e.g. bass moved into the intro) must turn each check red | owner of the planner generator (A10) | CI |
| V4 | Evenly spread perc rhythm and per-family hat/clap rules are reproducible from a stored seed | Same seed + parameters → identical step pattern, byte for byte; different seeds cover all 16 rotations | audio-engineer (if patterns are rendered) | CI |
| V5 | Level offsets (H4) on our own renders | BS.1770 integrated loudness per stem vs kick stem, over seeded random patterns and the full parameter range | audio-engineer | CI |
| V6 | Kick tail vs bass root (H5) | Render a kick at 45–60 Hz tail with a sub bass on the same pitch class, on the fifth and one octave up; measure band energy at the tail fundamental during 0–150 ms after each onset | audio-engineer; ear: user | CI + user's PC |
| V7 | Whether the artifact links the kick key to the song key | Read `KickMachine` → `KickCore` key flow (`:3498-3600`, `:1368-1426`) | sound-designer (follow-up) | read-only |
| V8 | Circle-picker categories and tier marks (Q1) | Show the proposal to the user with the B3 task text | lead → user | questionnaire |
| V9 | Swing scaling of the 303 vs the drum machines (3.1) | Re-type both formulas and compare offsets at swing 54 | sound-designer (follow-up) | read-only |

## Limits

- Read-only text analysis of one artifact copy. Nothing was executed, rendered, measured on audio or heard.
- The **U/A** split rests on comments in the artifact and on our learnings note. Where no comment exists, the author of a design choice is **not established**.
- Sources the artifact cites (**S**) were not opened. Their weight is second-hand.
- The questionnaire task B3 text was not available to me. Q1's picker proposal follows the lead's brief only.
- Line numbers refer to the 9,259-line copy read on 2026-10-29. A newer artifact version may differ.
- Two label inconsistencies were noted in the artifact, not in our repo: the ghost-kick pattern `pre` (3.5) and the perc pitch label "MINOR 3RD" (3.4). They are reported here, not fixed.
