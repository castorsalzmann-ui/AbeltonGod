# Listening test 3: kick character after `dense`, layering, tempo fit, and the Bandit Wheel defaults

_Date: 2026-11-02 · Role: sound-designer · Status: **plan and hypotheses, not a result.** Nothing here was heard. Numbers describe signals only; every "better", "fuller", "more character" is for the user's ear. Issues: #103 (follow-up of listening tests 1 and 2), #151 (musical transfer, plan steps V1), #57 / #58 (parked ideas)._

## Short version

1. Listening tests 1 and 2 of #103 are done. The user chose `centre` + `drive 0.45` (now preset `dense`) in every comparison and said it has enough bite. This note does **not** repeat them. It plans what is still open: **Session 1 (kick, about 11 min, 5 items, 9 distinct files)** and **Session 2 (Bandit Wheel defaults, about 12 min, 4 steps, no engine render)**.
2. Open after LT1/LT2: (a) is `dense` near the optimum on drive in both directions (only 0.8 was tested, never lower); (b) does layering still add anything on top of `dense` (LT1 only tested layers against `dense`, not on it); (c) onset-only clipping (`clip_db`, now in the engine, was never heard); (d) tempo fit: `dense` does not fit one beat at 136 BPM without a change of character (measured below); (e) do the seed variants of `dense` keep its character.
3. New in the method: a **control pair** (two identical files labelled A and B) so the user's answers have a visible chance baseline, and **A/B positions mixed by a seed** (LT1/LT2 had a fixed order and no repeat).
4. **Engine gap:** the CLI cannot render `clip_db`, `length_beats` or `tail_note` (it refuses `--set schema_version`, and the presets are v0.2). The measurements and the Python render below work; the lead needs either that Python path or a small CLI change from the `audio-engineer` (request on #103).

## What only the user can decide (by ear)

- Whether any pair is audibly different at all. Several differences below are small in the numbers (see the noise yardstick); "I hear no difference" is a valid, useful answer.
- Which file is better, fuller, has more character, fits his track.
- Whether a tail "carries" or "is in the way" next to his bass and kick pattern.
- Whether a layered version is wanted at all (this closes #57 if the answer is no).
- Which Bandit Wheel default he wants (Session 2). The measurements only say whether the property is present.

## Method and commands

Engine from `origin/main` a0ca3a5 (ENGINE_VERSION 0.1.0), Python 3 with NumPy 2.5.3 and SciPy 1.18.1, worktree `.claude/worktrees/sd-lt3`. The measuring script is mine, in my scratchpad (not in the repo), and independent of `audio_engine.analysis`; definitions follow section 4 of the kick-gen2 note: from the onset (first sample at 10 % of peak), rectangular window for band shares, 5 ms RMS envelope, `None` where a threshold is not crossed.

- **crest** = peak / RMS over 0–100 ms after the onset (dB). **RMS0–100** in dBFS.
- **body** = RMS of the 80–300 Hz band over 5–80 ms (dB re full scale).
- **sub** = energy share below 100 Hz, whole file. **on>1k / on>3k** = energy share above 1 / 3 kHz in the first 10 ms.
- **harm** = power at 2–8 × f0 divided by power at f0, 100–300 ms (Hann window). Not the definition of the 77-reference table; compare only inside this note.
- **f0 engine** = `audio_engine.analysis.analyse` `fundamental_hz`. **f0 Hilbert** = median instantaneous frequency of the 700 Hz low-passed signal, 60–200 ms (it reads about 8 % above the asymptote for `dense`; a known effect of the pitch fall that has not finished, see CURRENT_STATE "Measured limits").
- **d40** = time from onset to −40 dB (5 ms RMS). `None` = not reached inside the file.

The numbers for `dense` reproduce the earlier values: crest 2.19 dB, sub 0.62 (comment on #103, 2026-10-29). The `body` value differs from that comment (−3.24 here, −2.48 there): the band filter is not the same. Compare only within this note.

```
# render (Python, because the CLI cannot set the v0.3 fields)
from audio_engine.kick import render_kick
from audio_engine.presets import load_preset
p = dict(load_preset("dense")); p.update(schema_version="0.3", clip_db=3)   # etc., see the table
audio, resolved = render_kick(p)
# CLI renders that do work today (v0.2 fields only):
python -m audio_engine.kick --preset dense --out OUT
python -m audio_engine.kick --preset dense --set drive=0.30 --out OUT
python -m audio_engine.kick --preset dense --set drive=0.60 --out OUT
python -m audio_engine.kick --preset dense --variants 4 --out OUT        # v1..v3 are K5
```

Checks run: the CLI renders above exit 0; `--set schema_version=0.3` exits 2 (`this field cannot be set`); `--set clip_db=3` and `--set length_beats=1` on a v0.2 preset exit 2 with the v0.3 message. All files in the table have `pitch_settles` = True except where marked.

**Noise yardstick.** The four seed variants of `dense` (K5) differ among themselves by: crest 2.19–2.60 dB (range 0.41), body −3.64 … −3.24 dB, sub 0.597–0.623, on>1k 0.024–0.031, harm 0.0008–0.0018, d40 409–450 ms. A difference between two test files that is clearly larger than this is "more than seed variation"; a smaller one probably is not worth asking about.

## The five items (Session 1)

Common setup (as LT1/LT2, one change: **136 BPM** instead of 128, the tempo of the 2026-10-30 acceptance run): 4 bars, one hit per beat (441.18 ms), mono 48 kHz / 24-bit, each hit cut at the next beat with a 3 ms cosine fade, Warp off, peak at most −0.3 dBFS, **RMS-matched over 0–100 ms within each item** (the louder files are scaled down to the quietest; gains below). Labels are blind; the lead draws the A/B positions with a fixed seed and writes the key (`Schluessel.md`) for after the test.

| Item | Files (blind) | Changed parameters vs. `dense` | Hypothesis (measurable) | Measured (this note) | Gain to match RMS |
| --- | --- | --- | --- | --- | --- |
| **K0** control | A = B = `dense` (identical bytes) | none | None. Baseline: how often does the user pick a side when there is no difference | n/a | 0 |
| **K1** drive neighbourhood | three files | `drive` 0.30 / 0.45 (`dense`) / 0.60 | Lower drive: higher crest, fewer tail harmonics; higher drive: the opposite. The three differ by more than the K5 yardstick in crest and sub | crest 2.70 / 2.19 / 1.91 dB · sub 0.573 / 0.623 / 0.652 · harm 0.0006 / 0.0018 / 0.0037 · d40 421 / 450 / 460 ms · f0 engine 52.0 for all | 0 / −0.51 / −0.78 dB |
| **K2** onset clip | pair | `clip_db` 3 (schema_version 0.3) | The clip flattens the loudest part and leaves the tail: crest falls, on>1k rises, tail harmonics and f0 stay about the same | crest 2.19 → 0.96 dB · on>1k 0.026 → 0.036 · on>3k 0.008 → 0.010 · harm 0.0018 → 0.0018 · d40 450 → 469 ms · sub 0.623 → 0.670 | clip −1.23 dB |
| **K3** layer on `dense` | pair | B = `dense` + second kick at −6 dB, summed, normalised to −0.3 dBFS. Second kick = `dense` with `pitch_start_hz` 500, `pitch_end_hz` 110, `pitch_decay_ms` 6, `amp_decay_ms` 110, `length_ms` 150, `click_level` 0.6, `click_tone_hz` 4000, `drive` 0.2 (settle limit 8.72 ms, 6 ms follows it). Polarity +1 | The layer raises the crest and the 110–300 Hz share but not the sub: crest rises, sub share falls, on>3k barely moves | crest 2.19 → 4.54 dB · body −3.24 → −5.19 dB (at the level of the sum before matching) · sub 0.623 → 0.541 · on>1k 0.026 → 0.025 · on>3k 0.008 → 0.010 · sub ratio of the two layers 0.998 (polarity does not decide the sub here; opposite polarity: body −7.60 dB instead of −5.19 dB). Unnormalised sum peaks at +2.9 dBFS, so the normalisation matters | `dense` −2.35 dB |
| **K4** tempo fit at 136 BPM | pair | B = `dense` with `bpm` 136, `length_beats` 1, `pitch_decay_ms` 28 (v0.3). `amp_decay_ms` is derived by the engine (380.6) | `dense` as is (560 ms decay) is still 33 dB below its maximum when the next beat cuts it; B has decayed to −55 dB at the end of the beat. The cost is the body: B has less sub and less body | level at the end of the beat (5 ms RMS re max): A −33.2 dB, B −55.1 dB · sub 0.623 → 0.632 · body −3.24 → −4.45 dB · crest 2.19 → 2.88 dB · d40 450 → 301 ms · f0 engine 52.0 vs. 52.01 (Hilbert 56.0 vs. 52.7) | `dense` −0.69 dB |
| **K5** variants of `dense` | four files | `--variants 4`: v0 = `dense`, v1 … v3 move `pitch_start_hz`, `pitch_end_hz`, `pitch_decay_ms`, `amp_decay_ms`, click and drive by the variant spread | The variants stay inside the K5 yardstick (that is the yardstick). Question is only whether the user hears the same "main character" | v1 crest 2.22 · v2 2.60 · v3 2.34 (v0 2.19); sub 0.614 / 0.620 / 0.597; tail f0 engine 52.99 / 52.65 / 52.04 Hz; all `pitch_settles` True | v0 −0.41 · v1 −0.38 · v2 0 · v3 −0.26 dB |

Notes on K4 and the tempo-fit finding (measured, `render_kick` with `bpm` 136):

- `dense` unchanged with `length_beats` 1 is **refused** by the engine: `amp_decay_ms 560 does not decay 60 dB within length_beats 1 at 136 BPM … the rule (6a) derives 384.2`. So dense cannot be fitted to one beat at 136 BPM without changing `amp_decay_ms`.
- With the derived 384.2 ms and `pitch_decay_ms` 40, the pitch-settle guideline **fails** (limit 31.8 ms) and sub falls to 0.50. With `pitch_decay_ms` 28 it settles (limit 31.5) and sub is 0.632 (this is the K4 file). With 25 ms: sub 0.666, body −4.84 dB.
- At **1.5 beats (661.8 ms)** `dense` keeps its numbers: `amp_decay_ms` derived 576.2, settles True, crest 2.16 dB, sub 0.640, harm 0.0021, d40 459 ms, level at the end −58.1 dB. The "tempo fit" must can therefore be met at 136 BPM without touching the character if the user accepts 1.5 beats; at one beat something has to give. Which of the two he wants is a listening and taste question: this is why K4 asks about the one-beat version.
- Hypothesis for the next engine step (not a proposal for a value): the tempo-fit rule and the pitch-settle guideline interact in the short-length corner; the audio-engineer may want a combined derivation. Not established beyond the three requests measured here (1, 0.75 and 0.5 beats all return `settles False` at `pitch_decay_ms` 40).
- Tail f0 of the K4 file: engine analysis 52.01 Hz (dense: 52.0), so the shorter decay does not move the measured tail pitch. Its `decay_40db_ms` by the engine analysis is 339 ms (my 5 ms RMS method: 301 ms; the two methods differ, compare within one method only).

## Order and German texts for the user (Session 1, about 11 minutes)

Order (least tiring first, the pair most likely to show a difference early, control in the middle): **K2 → K0 → K3 → K1 → K4 → K5.** Pairs first because they are quick; the two multi-file items last when ears are tired but the questions are only rankings. Take a break of a minute after K1.

**Aufbau (einmal, 2 Minuten):** Alle `*.wav` des Pakets in eine Audiospur laden, Warp aus, Projekttempo 136 BPM, jede Datei als Loop. Gleiche Lautstärke an der Spur, nichts auf dem Master. Die Dateinamen sind anonym (A/B/C). Schluessel.md erst nach dem Test öffnen.

**Schritt 0 (30 Sekunden):** Tonart oder Grundton des Tracks, den du gerade im Kopf hast (falls vorhanden). Wird nur für den Zusatzblock gebraucht.

| # | Frage (eine pro Block) | Antwortmöglichkeiten |
| --- | --- | --- |
| K2 | Hör die Datei K2_A, dann K2_B. **Welche hat mehr Wumms und Volumen im Anschlag?** | A / B / kein Unterschied |
| K0 | Gleiche Frage für K0_A und K0_B: **Welche ist voller?** | A / B / kein Unterschied |
| K3 | **Hat eine der beiden etwas, das die andere nicht hat? Wenn ja, welche und was (ein Wort)?** | A / B / kein Unterschied · Wort |
| K1 | Drei Dateien (X, Y, Z). **Sortiere von „mein Kick" bis „am wenigsten mein Kick".** Danach: **Ist die beste zu viel, zu wenig oder richtig verzerrt?** | Reihenfolge, z. B. Y > X > Z · zu viel / richtig / zu wenig |
| K4 | Der Kick läuft auf jedem Beat. **Welcher Schwanz stört den nächsten Schlag weniger, ohne dass dir etwas fehlt?** Wenn die kürzere Variante etwas verliert: was (ein Wort)? | A / B / kein Unterschied · Wort |
| K5 | Vier Dateien. **Welche klingen für dich wie derselbe Kick? Welche fällt raus (wenn eine rausfällt)?** | Liste |

**Zusatzblock O (nur wenn du in Schritt 0 einen Grundton genannt hast, 3 Minuten, optional):** drei Dateien `dense` mit `tail_note` 30 / 32 / 34 (46,25 / 51,92 / 58,28 Hz, Engine-Messung) oder die Noten, die dein Grundton ergibt. Spiel sie gegen deine Bassnote und sag, **welche trägt oder stört**. Hinweis: Ableton nennt MIDI-Note 60 „C3"; die Dateien sind mit der Notennummer und Hz beschriftet (Schluessel), damit nichts verwechselt wird. Was „trägt" bedeutet, entscheidest nur du.

## Auswertungsvorlage (user fills in, or the lead copies it into #103)

```
Test 3, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Pegel gleich gelassen: ja / nein
Schritt 0 (Tonart/Grundton): ____
K2: ___   Anmerkung: ____
K0: ___   (A=B identisch; war die Antwort „kein Unterschied"?  ja / nein)
K3: ___   Wort: ____
K1: Reihenfolge ___ > ___ > ___    Verzerrung der besten: zu viel / richtig / zu wenig
K4: ___   Verlust (Wort): ____
K5: gleicher Kick: ___ ; fällt raus: ___
O (optional): Note ___ trägt / stört: ____
Gesamt: Welche Datei des ganzen Tests ist „mein Kick"? ____ (oder „dense reicht")
```

**Lead / audio-engineer: how to read the answers** (decoded with the key; each is one listener, one session, not a finding about the sound):

| Answer | Reading | Next step |
| --- | --- | --- |
| K0 not "kein Unterschied" | The user picks a side without a difference; weigh all other pair answers against this | Repeat that pair reversed before building on it |
| K1 best = drive 0.30 or 0.60, or "zu viel" / "zu wenig" | `dense` is not at the optimum on that side | One new preset proposal with that drive (inside v0.3); no new curve field needed |
| K1 best = `dense`, "richtig" | `dense` stays; the drive axis is closed | None |
| K2 clipped file preferred | Onset clipping adds something he wants | Preset `dense` + `clip_db` as a candidate (contract field exists; decision: the user) |
| K2 "kein Unterschied" or `dense` preferred | `clip_db` stays an option, not a preset value | None |
| K3 "layered" preferred with a word | Layering has value on top of `dense` | Reopen #57 for the fuse feature; the word names the property to measure next |
| K3 "kein Unterschied" or `dense` preferred | A second kick adds nothing on top of `dense` (one listener, one layer) | Close #57 as not needed; keep polarity and offset as engine fields only |
| K4 B (one beat) preferred, nothing lost | The tempo fit can use `length_beats` 1 with `pitch_decay_ms` about 28 | Audio-engineer issue: a combined rule between tempo fit and pitch-settle |
| K4 B loses a word (e.g. "weniger Tiefe") | Body at one beat conflicts with the character | Offer 1.5 beats at 136 BPM; ask which length he wants as a default |
| K5 one variant falls out | Variants of `dense` can leave the character | Ask the audio-engineer to bound the spread for `dense` (parameter, not a value from me) |
| O: a note carries | A key-matched tail is useful | Feeds the "key-matched kick" must (Q2) |

## Session 2: Bandit Wheel defaults (about 12 minutes, no engine render)

This is the "listening plan" from the musical transfer note (`2026-10-29_bandit-wheel-musical-transfer.md`), condensed. The categories (clap/snare/rim, hats, percussion, bass) do not exist in the engine, so nothing is rendered; the user works in his own artifact. **Set-up to be checked by the lead first:** that a machine can be switched on or off for a single section (per-section switch, not the global mixer mute). The note traced `toggleLoop` (`:8169`) and `laneOn` (`:8629`); which button reaches it in the track view was not traced.

Genre Peak Time (or Hard Groove for step 2), 140 BPM. One question each, answered in the same template style:

1. **Bass im Outro (4 Min).** Die letzten 32 Takte einmal wie gebaut (ohne Bass) hören, dann mit Bass im OUTRO und OUTRO 2. *Soll der Bass bis zum Ende des Outros bleiben?* A = ohne / B = mit / egal. Property to check afterwards (H1): energy below 120 Hz between the kick hits, from 60 ms after each onset to the next onset, at least 20 dB lower in the version without bass. Moves `intro_outro_bass`.
2. **Swing (3 Min).** Hats GROOVE-Rad auf STRAIGHT, dann auf LIGHT SWING. *Welche Variante passt zu deinen Tracks?* A = straight / B = leicht / egal. Property (H2): onset times of the odd 16ths vs. the grid (light swing 52–54 means 4–9 ms in the note's table). Moves the family swing defaults.
3. **Clap im Intro (3 Min).** INTRO und INTRO 2 wie gebaut (Clap ab Takt 17), dann CLAP in INTRO 2 aus (nur dort). *Soll die Clap schon im Intro kommen?* ja / nein / egal. Not a signal question (H6). Moves the clap threshold for `intro`.
4. **Kick-Pause vor dem Drop (3 Min).** BUILD → DROP wie gebaut (Kick 4 Takte aus). *Ist die Pause der Kick zu lang, richtig oder zu kurz?* Moves `build_kick` (D3).

Order 1 → 4 as in the note (1 and 3 feed settings that already exist in D-024). Answer template:

```
B1 Bass im Outro: ohne / mit / egal    B2 Swing: straight / leicht / egal
B3 Clap im Intro: ja / nein / egal     B4 Kick-Pause: zu lang / richtig / zu kurz
```

What only the user decides: all four. The measured properties in 1 and 2 only confirm that the signal property is present.

## Not done and limits

- No file was rendered to WAV for the package; the numbers come from `render_kick` and my script. The package (loops, key) is built by the lead, as LT1/LT2.
- The K3 second kick and the gain (−6 dB) are my choice, one of many; the table shows polarity and the two other levels I measured (−9 dB: crest 3.96; −12 dB: 3.48) in the scratchpad only. A "no difference" answer closes this one layer, not layering in general.
- K1 differences (crest range 0.79 dB, sub range 0.08) are about twice the K5 spread; whether that is audible was not tested.
- The control pair K0 is one trial. It shows a bias if the user picks a side; it cannot measure bias precisely.
- The earlier LT1/LT2 results rest on one listener and a fixed order; this plan's A/B positions are mixed but it is still one listener in one session.
- The `tail_note` renders (30, 32, 34) were checked with the engine f0 (46.25, 51.92, 58.28 Hz), `pitch_settles` True for all three (limits 44.6, 46.3, 48.2 ms).
- Engine request (comment on #103): CLI or documented Python path for the v0.3 fields; K2 and K4 need it.
