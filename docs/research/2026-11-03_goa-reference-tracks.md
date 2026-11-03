# Research: the user's three Goa reference tracks — identification, what sources say, comparison with the Goa voice plan, intake proposal

_Date: 2026-11-03 · Refs #338 · Role: researcher. Docs only: no code, no contract, no decision changed. All pages were opened on 2026-11-03 through the session's fetch tool (a small model summarises each page; it is not raw HTML). **I did not listen to any of the tracks, did not download or analyse any audio, and quote no lyrics.** Anything about tempo, key, structure, instrumentation or sound that no opened source states is marked "not established". Nothing here is a taste claim; every comparison with the plan is a hypothesis status (confirm / contradict / open)._

Labels: **documented** = an opened page says it (page named, weakness named); **inferred** = my reasoning; **not established** = no source found.

Read first: `CLAUDE.md`, D-026, [Goa musicology and sound (G1)](2026-11-03_goa-trance-musicology-and-sound.md), [Goa synth-voice plan](2026-11-03_goa-synth-voice-plan.md) (its section 5 is the reference-intake protocol this note applies).

## For workers

- **All three names resolve, but two were given as "title - artist" and one as "artist - title".** Most likely meaning (documented on the label's Bandcamp pages): **The Infonaut - "Cthugha"** (album *Informatics*); **Lunar Asylum - "Twister"** (album *Lunar Asylum*, Phantasm Records, 1998); **SETI Project - "Ephidrine"** (album *Lost Gems Vol. 2*, Guido Venier). Section 1.
- **No opened source states BPM, key, bar structure, instrumentation or a sound description for any of the three tracks.** Discogs, Beatport and MusicBrainz could not be opened from this sandbox (blocked), and those are the usual places for BPM/key. Section 2.
- **Only durations and label blurbs exist:** 7:19, 8:48 (or 7:20 on one site), 7:16. Blurbs: "acidic, raw, funky" (Lunar Asylum), "melodic and funky" (Infonaut album), "Goa, acid trance and proto-Goa" (SETI album). Weak, genre-level.
- **Plan impact (section 3):** nothing in the plan is contradicted; almost nothing is confirmed (track lengths are compatible with the 288-bar template; "acid" character is mentioned for two of three). Tempo window, modes, bass rhythm, lead/pad character stay **open** until audio is measured.
- **Effort:** intake measurement = small per track (sound-designer, scratchpad), once the user supplies the files. **Blocker:** the files, and the version identity (section 5).
- **Do not use these tracks as a name-based target in code or contracts** (same stance as the kick/hat reference notes: measured quantities only, files never in the repo).

## 1. Identification

| User wrote | Resolved to | Release (as stated by the label's Bandcamp page) | Confidence | Source |
| --- | --- | --- | --- | --- |
| "The Infonaut - Cthuga" | Artist **The Infonaut**, track **"Cthugha"** (extra "h"), 7:19, track 11 of 12 on *Informatics* | **Classic Goa Trax** (Maarkedal, Belgium; sublabel of Suntrip Records), digital release **22 June 2020**. The page calls the album an *unreleased 1990s album* by the Greek artist The Infonaut, made with Savvas Georgiadis "so the original artists receive their share", and says three tracks on it were "previously released" without saying which. **Original 1990s year/label of "Cthugha": not established** | High for artist/title/album/label/2020 date (one primary page, track and album page agree); original year not established | [Bandcamp: Cthugha](https://classicgoatrax.bandcamp.com/track/cthugha) · [Bandcamp: Informatics](https://classicgoatrax.bandcamp.com/album/informatics) |
| "Twister - Lunar Asylu(m)" | Artist **Lunar Asylum**, track **"Twister"**, track 3 on the self-titled debut album *Lunar Asylum* | Original: **Phantasm Records, 1998** (Bandcamp album page; a Psynews topic titled "Lunar Asylum - Lunar Asylum - 1998" says label Phantasm, 1998). Digital re-release: **Classic Goa Trax, 13 May 2019**. Last.fm lists the members as Chris Stevenson, Paul Greendale and Simmons (user-edited site, medium-low) | High for artist/title/album/1998/Phantasm (three sources agree); member names medium-low | [Bandcamp: album](https://classicgoatrax.bandcamp.com/album/lunar-asylum-lunar-asylum) · [Bandcamp: Twister](https://classicgoatrax.bandcamp.com/track/twister) · [Psynews](https://www.psynews.org/forums/topic/35191-lunar-asylum-lunar-asylum/) · [Last.fm: Twister](https://www.last.fm/music/Lunar+Asylum/lunar+asylum/Twister) |
| "Ephidrine - SETI PROject" | Artist **SETI Project**, track **"Ephidrine"** (the user's spelling matches the label's; not "Ephedrine"), 7:16, track 4 of 8 on *Lost Gems Vol. 2* | **Classic Goa Trax**, cat. no. CGT105, digital, **8 October 2025**. The page says the album is **previously unreleased** tracks by **Guido Venier** (all written, produced and mastered by him; remastered by him), from the "1990s underground trance scene". **Year the track was made: not established** (the page says only 1990s for the scene) | High for artist/title/album/label/2025 date; production year not established | [Bandcamp: Ephidrine](https://classicgoatrax.bandcamp.com/track/ephidrine) · [Bandcamp: Lost Gems Vol. 2](https://classicgoatrax.bandcamp.com/album/lost-gems-vol-2) |

Name-resolution notes:

- **Order.** For tracks 2 and 3 the user's order is "title - artist"; the label pages give artist = Lunar Asylum / SETI Project and title = Twister / Ephidrine (documented). I treat that as the intended meaning; the user should confirm (section 5).
- **Not the same thing (disambiguation):** "Cthugha" by USAO is a different, unrelated recording (a Discogs release title surfaced in search, not opened; the name is a Lovecraft-derived word reused by many works). A Last.fm "SETI Project" page describes an act "formed in 2004 by Paul Yelland" (user-editable); that is not the Guido Venier act of the Classic Goa Trax pages (documented: the label page names Venier). A "Seti Project" profile on Mixgraph lists 118/145/100/140 BPM tracks with other titles; it is not shown to be the same act and does not list "Ephidrine". A Beatport artist page for "Seti Project" and a Discogs release "SETI Project - Reloaded Vol. 1" also appeared in search; the Classic Goa Trax *Reloaded Vol. 1* page (opened) lists ten tracks and **no "Ephidrine"**.
- **Candidates if the user meant something else:** (a) another Infonaut track from *Informatics* (the album page lists Disconnection, Neural Implant, Paranoia, Infra-Red Sensation, Synectics, Scanners, Supernova, Spheroid Objects, Vectors Polygons, Chronos, Cthugha, Mind Directed Energy); (b) another Lunar Asylum track from the same album (Iron Age, Vanishing Point, G Lock, Van Halen, Goldendawn, Meltdown, Depth Charge, We Know Nothing); (c) another track of *Lost Gems Vol. 2* (LSD Valley, Drug Enforcement, Smoke More Weed, Just Keep Breathing, Planet Dope, Fantomas, Freak). I see no sign of a different artist with these exact titles, but I could not search Discogs or MusicBrainz, so this is **not exhaustively checked**.
- **Version risk.** All three are on the same digital label, two of them (Infonaut, SETI Project) as **first-time releases of 1990s material**, and SETI Project's tracks were **remastered by the artist** (documented). The files the user owns may therefore differ from any original release in level and loudness. Lunar Asylum's *Twister* is listed at **8:48** (Bandcamp), **8:47** (Psynews, "08'47\"") and **7:20** (Last.fm); the 7:20 may be another edit or a data error; **not established** which.

## 2. What the opened sources say, per track

"Not established" = I found no page that states it. Descriptions are the label's own blurbs or forum users, so they are promotional or opinion, not measurement.

| Item | The Infonaut - Cthugha | Lunar Asylum - Twister | SETI Project - Ephidrine |
| --- | --- | --- | --- |
| Duration | 7:19 (Bandcamp album page) | 8:48 (Bandcamp album), 8:47 (Psynews), 7:20 (Last.fm) | 7:16 (Bandcamp album page) |
| BPM | not established | not established ("BPM: not listed" on the Psynews topic) | not established |
| Key / scale | not established | not established | not established |
| Structure (bars, sections) | not established | not established | not established |
| Instrumentation | not established | not established. Album-level user comments mention "acid melodies", "hard, strong bass" and "metal samples on some tracks" (Psynews; which tracks is not said, so none can be assigned to *Twister*) | not established |
| Sound description (source and weakness) | Album blurb: "pure goa trance", "more melodic and funky than the label's usual releases", "distinctive 90s feel" (label, promotional) | Album blurb: "old-school goa trance", "acidic, raw, funky", "nighttime edge" (label, promotional). Psynews users: *Twister* is part of an "absolutely mad" group with G Lock and Van Halen; one calls it a "pure psychedelic eruption" (opinion) | Album blurb: Goa trance, acid trance and "proto-Goa" styles, a "time capsule" (label, promotional). The label tags the album "acid" |
| Genre tags | goa, goa trance, psytrance (Bandcamp) | goa, goa trance, acid, psychedelic (Bandcamp) | goa, acid trance, psytrance (Bandcamp) |

Where BPM and key would normally be found: Discogs and Beatport release pages (both returned "client_error" to the fetch tool), MusicBrainz (blocked by robots rules and by the sandbox proxy, HTTP 403 on a direct request), Mixgraph (checked for SETI Project only: a different or unrelated profile, see above). I did not try to estimate BPM from the durations alone: duration cannot give tempo without a bar count.

Arithmetic only (not evidence of tempo): bars = duration (s) x BPM / 240. If a track ran at 135 / 140 / 145 BPM, 7:19 (439 s) would be 247 / 256 / 265 bars; 8:48 (528 s) would be 297 / 308 / 319 bars; 7:16 (436 s) would be 245 / 254 / 263 bars. Intros and tails of unknown length are included in these counts.

## 3. Comparison with the plan's assumptions

The plan is [the synth-voice plan](2026-11-03_goa-synth-voice-plan.md) with D-026 defaults and the G1 starter values. Status words: **confirm** = a cited source about these tracks supports it; **contradict** = a cited source contradicts it; **open** = nothing about these tracks decides it.

| Assumption (where) | Status | Reason, with source |
| --- | --- | --- |
| BPM window 135-150, default 140 (G1 findings 1-2, plan section 2.2) | **Open** | No BPM for any of the three is documented. The SETI album is described as mixing "Goa trance, acid trance, and proto-Goa" (label), and G1 notes that the Goa thesis' captions mention a track at 128 BPM; so a reference outside the window is possible, but nothing says it is. The measurement in section 4 decides |
| Modes: aeolian / phrygian / harmonic minor / phrygian dominant (G1 section 2.1) | **Open** | No key or scale stated anywhere for these tracks |
| Rolling bass: off-kick 16th roll default, off-beat 8th and triplet gallop as variants (D-026, plan S2) | **Open** | No rhythm description. Only an album-level user comment on "hard, strong bass" for Lunar Asylum (Psynews), which says nothing about the rhythm of *Twister* |
| Sub drone plus higher bass line (G1 finding 5) | **Open** | not established for these tracks |
| Section plan, 288 bars = 8:14 at 140 BPM, with a long build and a main breakdown (G1 section 6) | **Weakly compatible, not confirmed** | The three durations (7:16 to 8:48) are in the 7-9 minute range of Bonedo (psytrance) and the plan's 8:14; two are below the 8-minute lower bound of Wikipedia's uncited 8-12 minutes (G1 finding 1). Three durations of digital releases do not show bar counts or section order |
| DJ-friendly intro/outro versus authentic long build (D-026) | **Open** | Nothing known about the intros/outros of the three |
| Acid line with accents and slides as one role (plan 2.2, 5.2 `acid`) | **Weakly supported at genre level** | The label calls *Lunar Asylum* "acidic" and tags *Lost Gems Vol. 2* "acid trance"; neither says that *Twister* or *Ephidrine* contains a 303-style line. The *Informatics* blurb says "melodic and funky", which suggests a lead-heavy character (inferred, not stated) |
| Lead character: saw stack with filter sweep as "the melody" (plan H-voice-3) | **Open** | not established; no source describes these leads |
| Pad character (plan 2.2) | **Open** | not established |
| Reference material may be remastered (plan section 5, step 1) | **New fact** | The SETI Project album is remastered by the artist (documented); the others are digital re-releases or first releases of 1990s material by the same label. Loudness and spectral balance of the user's files therefore reflect the label's masters |

Net: the references neither confirm nor contradict the plan's Class B windows. They are useful only as audio to measure.

## 4. Gaps and limits

- No Discogs, Beatport or MusicBrainz page was readable, so original catalogue numbers, original formats and any BPM/key metadata are missing. A person with a normal browser can read them in a minute (Discogs releases for *Lunar Asylum* and for The Infonaut's *Mind Directed Energy / Chronos* exist per search results; I did not open them, and whether "Cthugha" was among the three "previously released" tracks is not established).
- Everything about sound comes from label blurbs and a few forum comments. Per the research method, forum posts count as medium-low confidence.
- The fetch tool summarises pages, so figures such as durations are as the summary reported them; two durations for *Twister* agree (8:48, 8:47) and one disagrees (7:20).
- I did not listen to or analyse any file.

## 5. What we need from the user

1. **Confirm identity and order:** The Infonaut - Cthugha; Lunar Asylum - Twister; SETI Project - Ephidrine (the Guido Venier / Classic Goa Trax one). If any is wrong, name the album or label.
2. **Which file/version do you own?** Source (CD, vinyl rip, Bandcamp download, streaming) and length shown by the player: it tells us whether you have the 2019/2020/2025 digital masters or an original release, and whether *Twister* is 8:48 or 7:20.
3. **What should we take from each track?** One word each, from: bass, lead/acid line, filter sweeps, arrangement/build, drums/kick, atmosphere/FX, overall feel. Without this we would measure everything and not know what matters.
4. **Timestamps, not stems.** We cannot isolate stems from a stereo file reliably (inferred). For the element in question, give the time (mm:ss) of a passage where it plays alone or almost alone, for example "bass and kick only", "lead alone in the break", "the filter sweep from x to y". Three to five passages per track are enough.
5. **If you know them:** the BPM your DJ software or Live shows for each (Live's warp detection is also fine, label it as such).
6. **Listening questions (answers are the user's, nothing is predicted):**
   - Cthugha: is the part you like the lead melody, the groove, or the build? Is it more "melodic" than the other two?
   - Twister: is the bass pattern what you mean by "rolling" (one note per 16th after the kick), a gallop, or something else? Is the "acid" line present in the part you mean?
   - Ephidrine: is it closer to your idea of Goa or to acid trance? Is the drive from the bass or from the acid line?
   - For all three: would our generated track be better with their tempo, their bass rhythm, or their sound?
7. **Permission to store measured numbers** (not audio) in a research note, under the track and release names above.

## 6. Proposal: measured-reference intake for these three

Applies [the plan's section 5](2026-11-03_goa-synth-voice-plan.md) and D-026 point 3. Audio content is measurement input only; files stay with the user or in a scratchpad outside the repo, never copied into the repo, never used to resynthesise, never re-hosted. No audio is downloaded from any shop or video site by the agent; the user supplies the files.

1. **Intake.** The user places the three files (WAV or the best lossless copy; compressed files are accepted but flagged because encoding changes high-frequency measurements) in a local folder and sends the path or the timestamps. Per file: title, artist, version, length, user purpose tag (bass / lead / full mix) and the passages from section 5.
2. **Measure in a scratchpad (sound-designer), report commands and outputs:**
   - tempo from onset autocorrelation on the whole file and per section, cross-checked against the user's DAW BPM and a bar count from the kick grid; report as "measured, N bars per section";
   - bar-level structure: RMS and spectral centroid per bar, plus kick presence, to find section boundaries and compare the bar counts with the 288-bar template (arrangement question only);
   - bass rhythm: onset occupancy of the 16th grid per beat in the user's "bass and kick only" passages, to settle off-kick roll versus off-beat 8th versus gallop (G1 finding 9); reported as step occupancy, not as a name;
   - kick-tail pitch where the kick is audible alone (comparison with the user's own median 53 Hz);
   - lead material: centroid distribution over time, sweep length in bars where a filter sweep is measurable, accent/level variation per note where notes are separable;
   - key: a chroma-based estimate as a **candidate with confidence**, not a fact; verified by the user's ear or by a reading of the notes in Live.
   Anything not measurable from a stereo mix is reported as "not measurable here", not guessed.
3. **Output.** A dated note `docs/research/<date>_goa-reference-measurements.md` with one table per track (values, method, window, confidence) and a proposed replacement for each Class B window in the plan section 2.2 and the mode weights in G1 section 2.1. A window stays a hypothesis until at least two references agree (plan section 5, item 3); with three references of different character (acid / melodic / proto-Goa per the blurbs) disagreement is likely and is itself a finding.
4. **What is never done:** copying melodies, riffs, samples or note sequences; deriving a recipe that reproduces one track; quoting lyrics; naming a track as a target in a contract or a preset; claiming a result without the command output.
5. **Dependencies.** Any analysis library added to the repo needs a "why" in its PR (CLAUDE.md); scratchpad-only use needs none. Which tools exist on the sound-designer's machine is not checked here.
6. **Test boundary.** CI can test only helper functions on synthetic signals; measurements of the user's files run on the user's or the sound-designer's machine and cannot be reproduced in CI.

## 7. Implications for the lead (proposals, nothing decided)

1. Ask the user the questions in section 5 (one message); items 1, 2, 4 and 5 are the ones that unblock the measurement.
2. Open the measurement issue for the sound-designer only after the files and timestamps arrive; until then the plan's Class B windows remain hypotheses (D-026 point 3).
3. Consider a user-side check of Discogs/Beatport pages for the three releases (BPM, key and original catalogue data are the usual contents); I could not read them from this sandbox.
4. Note for the State update: the three references are all re-releases or first releases on the **Classic Goa Trax** label (Suntrip sublabel); if the user later wants more references in the same spirit, that catalogue is a coherent source of 1990s Goa, but whether it matches the user's taste is for the user.

### State update proposal (for the PR body; the lead edits `CURRENT_STATE.md`)

- Goa reference-track note written: `docs/research/2026-11-03_goa-reference-tracks.md` (Refs #338): three tracks identified (The Infonaut - Cthugha; Lunar Asylum - Twister, Phantasm 1998; SETI Project - Ephidrine, Lost Gems Vol. 2); BPM, key, structure and sound are not established by any opened source; no listening or audio analysis was done.
- Known gap: the user's answers (section 5) and the audio files; the plan's Class B windows stay hypotheses.
- Next: user answers; then the sound-designer's measurement pass (section 6).

## Sources opened on 2026-11-03

[Bandcamp: Cthugha](https://classicgoatrax.bandcamp.com/track/cthugha) · [Bandcamp: Informatics](https://classicgoatrax.bandcamp.com/album/informatics) · [Bandcamp: Mind Directed Energy](https://classicgoatrax.bandcamp.com/track/mind-directed-energy) · [Bandcamp: Lunar Asylum (album)](https://classicgoatrax.bandcamp.com/album/lunar-asylum-lunar-asylum) · [Bandcamp: Twister](https://classicgoatrax.bandcamp.com/track/twister) · [Bandcamp: Ephidrine](https://classicgoatrax.bandcamp.com/track/ephidrine) · [Bandcamp: Lost Gems Vol. 2](https://classicgoatrax.bandcamp.com/album/lost-gems-vol-2) · [Bandcamp: Reloaded Vol. 1](https://classicgoatrax.bandcamp.com/album/reloaded-vol-1) · [Psynews: Lunar Asylum - Lunar Asylum - 1998](https://www.psynews.org/forums/topic/35191-lunar-asylum-lunar-asylum/) · [Last.fm: Twister](https://www.last.fm/music/Lunar+Asylum/lunar+asylum/Twister) · [Last.fm: Seti Project wiki](https://www.last.fm/music/Seti+Project/+wiki) · [Mixgraph: Seti Project](https://www.mixgraph.io/artists/seti-project) (different or unrelated profile) · a Reddit mirror thread on 1990s Goa (no mention of the three). Not readable from this sandbox: Discogs, Beatport, MusicBrainz, YouTube (rate-limited), AcousticBrainz result was an unrelated recording.
