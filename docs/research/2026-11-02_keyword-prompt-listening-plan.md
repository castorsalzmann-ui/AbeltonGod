# Listening check for the kick keyword prompt parser (PR #248, issue #233)

_Date: 2026-11-02 · Role: sound-designer · Status: **plan and expectations, not a result.** Nothing here was heard. Numbers describe signals only; whether a step is audible or "means what the word says" is for the user's ear. Refs #233 (parser, PR #248), vocabulary: [kick-keyword-vocabulary](2026-11-02_kick-keyword-vocabulary.md); format: [listening-test-3 plan](2026-11-02_listening-test-3-plan.md)._

## Short version

1. **Question 1 (direction):** does each of the 8 keywords move the sound in the direction the vocabulary promises? **Question 2 (steps):** are the steps audible, i.e. does an end (w = 0 or w = 2) differ from `dense`, and does the user name the property the vocabulary names? Plus 6 combined prompts typical for the user's taste (question 3: does a combined prompt sound "closer to my kick" than `dense`; all by ear).
2. **24 files** (limit 25): `REF` (`dense`, empty prompt) + 16 ends (8 keywords x 2) + 1 identical twin of `REF` (control) + 6 combined. The middle step w = 1 **is** `REF`, so it is not rendered again. Exception: `wums` is an add-on, w = 0 is `REF` and the two ends are `wums:1` (3 dB) and `wums:2` (6 dB).
3. **Single-file questions against `REF`, no A/B pairs.** Each file is judged against `REF` only ("different? what is the main difference? more or less?") from one neutral word list that is the same for every file. This keeps the guide free of the keyword names (the clap-test lesson: a guide that says which property to listen for steers the answer). `kein Unterschied` is always allowed; the twin of `REF` is the visible chance baseline.
4. **Lead can check by numbers first** (section 3, script outline in section 6): all 24 expectations below were measured on the PR branch (`9e2aefc`). Two things the lead should know before rendering: (a) `bite` is weak by the numbers, "kein Unterschied" is a plausible answer, not a bug; (b) `drive:0` is 6.6 dB quieter than `REF` at the same peak, so the package needs headroom (section 4).
5. About 13 minutes of listening, 24 files, one answer sheet (section 8).

## 1. What only the user can decide (by ear)

- Whether any end file is audibly different from `REF`, and which word he uses for the difference.
- Whether a combined prompt is closer to "my kick" than `REF` (`dense`).
- Whether a missing difference (e.g. `bite`) matters to him.

The measurements below only say that the signal moved, in which direction and by how much compared with the seed variation of `dense`.

## 2. Method and commands (what I ran)

- Branch `origin/phase-05/233-keyword-parser` at `9e2aefc`, exported with `git archive` into the session scratchpad (not the repo), NumPy 2.5.3, SciPy 1.18.1. Script `kwcheck.py` (scratchpad, not committed, independent of `audio_engine.analysis`): `parse_prompt(prompt)` then `render_kick(params)`, then the measures of vocabulary section 6, run as `PYTHONPATH=<export>/src python kwcheck.py`. All files seed 1001 (the preset seed, parser default).
- Engine `f0` from the CLI: `python -m audio_engine.kick --prompt "<p>" --out DIR` (prints `f0=`, `d40=`, `peak=`): `REF` 52 Hz, `sub:1.5, punch:1.2, dunkel, note:Am` 55 Hz, `sub:1.7, tail:1.5, note:31` 49 Hz (as the notes 33 and 31 promise).
- Measures (definitions as vocabulary section 6, from the onset = first sample at 10 % of peak): **crest** 0-100 ms (dB) · **sub** energy < 100 Hz, whole file · **sub150** same on the first 150 ms · **body** RMS dB of the 80-300 Hz band, 5-80 ms · **on1k** energy share > 1 kHz in the first 10 ms · **clickdb / clickcent** RMS dB / centroid (Hz) of the part > 1 kHz in the first 15 ms · **d40** first 5 ms-RMS frame 40 dB under the maximum (`nan` = not reached inside the file; for the check that counts as "longer than the file") · **harm** power at 2-8 x f0 / power at f0, 100-300 ms.
- Small differences to the vocabulary note: `REF` on1k reads 0.0298 here (0.0256 there; window or filter detail of my script), everything else matches to the digit shown there. Compare only inside one script.
- **Seed yardstick** (six seeds 1001-1006 of `dense`, same script): crest 2.158-2.294 dB, body -3.34 ... -3.20 dB, sub150 0.5560-0.5565, d40 450 for all, harm 0.0007 for all, **clickdb -20.7 ... -18.4 dB, on1k 0.021-0.035, clickcent 2164-4455 Hz**. The click measures vary strongly with the seed (the click is noise); that is why the check below always compares **the same seed**, and the click-based thresholds are weaker evidence than the others.
- Parser reports (`adjustments`) seen in these renders: pitch-settle cut in `sub:0` (52 -> 43.721 ms), `tail:0` (40 -> 34.335 ms) and `kurz, punch:1.2, click:1.2` (40 -> 38.037 ms); no clamp fired. Whether the CLI prints them is the PR's business.

## 3. Measurable expectations per keyword (lead pre-check)

`REF` (w = 1): crest 2.189 dB, sub 0.6232, sub150 0.5560, body -3.237 dB, on1k 0.0298, clickdb -19.49 dB, clickcent 2582 Hz, d40 450 ms, harm 0.00067. Observed = this run. **Pass** = the monotone direction holds and each step is at least the minimum size; "marginal" = inside or near the seed yardstick.

| Keyword | Primary measure (direction as w rises) | Minimum size per step | Observed w = 0 / 1 / 2 | Secondary measure | Verdict from numbers |
| --- | --- | --- | --- | --- | --- |
| `sub` | sub150 up, body down | sub150 +0.10; body -0.4 dB | sub150 0.431 / 0.556 / 0.713; body -2.82 / -3.24 / -4.64 | sub whole 0.524 / 0.623 / 0.752 | clear (seed range of sub150 is 0.0005) |
| `punch` | body up, sub whole down | body +0.4 dB; sub -0.08 | body -4.13 / -3.24 / -2.71; sub 0.725 / 0.623 / 0.529 | sub150 0.667 / 0.556 / 0.450 | clear; body step 1 -> 2 is 0.53 dB (about 4x seed range) |
| `click` | clickdb up, on1k up | clickdb +1.5 dB; on1k +0.008 | clickdb -21.62 / -19.49 / -16.07; on1k 0.0207 / 0.0298 / 0.0575 | clickcent 1182 / 2582 / 3692 (w = 0 has no click, the centroid then reads the tail) | w = 1 -> 2 clear; w = 0 -> 1 on1k step is **inside the seed range** (marginal), clickdb step 2.1 dB |
| `bite` | clickcent up | w = 2 at least +300 Hz over w = 1; w = 0 only needs to be lower | clickcent 2436 / 2582 / 3201; clickdb -19.05 / -19.49 / -20.03 | on1k 0.0310 / 0.0298 / 0.0277 (falls, not rises) | **weak**: only the centroid moves, and the seed range (2164-4455 Hz) is wider than the whole step. A "kein Unterschied" or a mixed answer is plausible |
| `tail` | d40 up, length up | d40 +80 ms; file length by construction | d40 350 / 450 / nan (> 648 ms file); length 356 / 480 / 648 ms | sub whole 0.577 / 0.623 / 0.708; harm 0.00009 / 0.00067 / 0.0038 (more drive residue in the longer tail) | clear; play uncut (section 4) |
| `drive` | crest down, harm up | crest -0.3 dB; harm x2 | crest 8.80 / 2.19 / 1.74; harm 1e-6 / 0.00067 / 0.0039 | sub whole 0.325 / 0.623 / 0.683; clickdb -27.9 / -19.5 / -16.7 | w = 0 is a **very large jump** (crest 8.8 dB, 6.6 dB quieter), w = 1 -> 2 is crest -0.45 dB (3x seed range) |
| `wums` | crest down (from `REF`) | crest -0.3 dB | `REF` 2.19 -> `wums:1` 0.96 -> `wums:2` 0.67 | clickdb -19.49 / -16.55 / -14.69; body -3.24 / -2.30 / -2.17 | clear; the two ends are w = 1 and w = 2 |
| `bright` | clickcent up, on1k up | clickcent +300 Hz (w = 2); on1k +0.008 | clickcent 2027 / 2582 / 2900; on1k 0.0188 / 0.0298 / 0.0448 | crest 2.12 / 2.19 / 3.99; body -3.15 / -3.24 / -5.05 | w = 2 clear (also -1.8 dB body, +1.8 dB crest); w = 0 -> 1 on1k step marginal |

Pass rule for the lead: a keyword is "confirmed by numbers" when its primary measure is monotone for w = 0 / 1 / 2 and both steps reach the minimum; `click` w = 0 and `bright` w = 0 are "marginal", `bite` is "weak". A failed row is a parser/mapping bug to report **before** the user listens.

### Combined prompts (expectation vs `REF`, same script)

| ID | Prompt | Expected direction vs `REF` (hypothesis) | Observed |
| --- | --- | --- | --- |
| C1 | `sub:1.5, punch:1.2, dunkel, note:Am` | sub150 up, body slightly down, click level down, tail pitch 55 Hz | sub150 0.599, body -3.45, clickdb -21.5, clickcent 2275, f0 55 Hz, crest 2.17 |
| C2 | `kurz, punch:1.2, click:1.2` | shorter, click up, sub down; settle cut fires | d40 380, length 401 ms, sub150 0.508, clickdb -18.7, on1k 0.037, crest 2.42 |
| C3 | `sub:1.5, lang, dunkel, click:0.5` | sub up, long, dark, little click | sub150 0.680, d40 not reached (length 575 ms), clickdb -23.5, clickcent 1517, harm 0.0024 |
| C4 | `punch:1.3, click:1.3, drive:1.2, wums:1` | body up, harder attack, crest down | crest 0.89, body -2.15, clickdb -15.2, on1k 0.052, sub150 0.582 |
| C5 | `drive:1.3, bite:1.5, wums:1` | saturated, attack clipped | crest 0.68, body -2.09, clickdb -15.7, harm 0.0015 |
| C6 | `sub:1.7, tail:1.5, note:31` | sub up, long, lower tail note | sub150 0.696, d40 545, length 558 ms, body -4.24, f0 49 Hz |

Not covered in this check (say so, do not imply it): `sauber`, `beats`/`bpm`, `key`, `variants`, weights between 0 and 2 other than those in C1-C6, the error and clamp messages of the CLI.

## 4. Package (for the audio-engineer or lead to render)

- **Rendering:** one CLI call per file, one output folder per prompt (the CLI names files `prompt_s<seed>_v<i>`): `python -m audio_engine.kick --prompt "<prompt>" --out DIR_<id>`; `REF` = empty prompt (renders `dense`). Twin of `REF` = a byte copy of the `REF` hit under another name (rendered once, copied; check with a hash).
- **Playback loop:** 136 BPM, **one hit per bar (1.765 s)**, 4 bars, mono 48 kHz / 24-bit, 3 ms cosine fade at the end, Warp off. *Not* one hit per beat as in test 3: the beat length is 441 ms, which would cut the tails of `tail:0/1/2` (d40 350 / 450 / more than 480 ms) and hide the `tail` and `sub` differences.
- **Level:** first scale everything by a common gain so that `REF` peaks at about -7 dBFS; then match each file to the `REF` onset RMS over 0-100 ms (measured gains at equal peak: `drive:0` +6.61 dB, `bright:2` +1.80, `tail:0` +0.49, `wums:1` -1.23, `wums:2` -1.52, C4 -1.30, C5 -1.51; all others within +-0.3 dB), assert every peak <= -0.3 dBFS and write all gains into the key. Reason: at the CLI default (-0.3 dBFS peak) `drive:0` cannot be boosted. Level matching removes loudness as a cue for most files; a remaining loudness difference can be answered with the word "Lautstärke".
- **Names and order:** single files `E01 ... E17` (16 ends + twin), combined `K01 ... K06`, plus `REF.wav` (the only open name). Numbering by the blind-order rule of `listening_test3.blind_order` (SHA-256 of seed, block, index; block names `kw-single` and `kw-combo`, seed 103), written into `Schluessel.md`. Package files: the 24 `.wav`, `Anleitung.md` (section 7, copied verbatim), `Antwortbogen.md` (section 8), and `Schluessel.md` (section 9, **delivered to the lead, not to the user**).

## 5. Order and timing

`REF` is played before every file (the user loops `REF`, then the file). Order: `E01 ... E17` in file order (the control sits at a position set by the shuffle, not told to the user), then `K01 ... K06`. About 20 s per single file (about 6 min), about 40 s per combined file (about 4 min), plus set-up 2 min and the final question 1 min: **about 13 minutes**. Break of one minute after `E09`.

---

## 6. Script outline for the lead's number check (scratchpad, not committed)

```
# check_kw.py  (PYTHONPATH=<branch>/src; run before the user listens)
KW = ["sub","punch","click","bite","tail","drive","wums","bright"]
ends = {f"{k}:{w}": ... for k in KW for w in (0, 2)}   # wums: (1, 2); w = 1 is REF = ""
for prompt in [""] + list(ends) + COMBINED:
    pp = parse_prompt(prompt)                  # also print pp.adjustments
    x, res = render_kick(pp.params); sr = 48000
    m = measures(x, sr)                        # crest, sub, sub150, body, on1k, clickdb,
                                               # clickcent, d40, harm  (vocabulary section 6)
    store[prompt] = m
for k in KW:                                   # monotone + minimum step, table in section 3
    a, b, c = store[w0(k)], store[REF], store[w2(k)]
    assert sign(b[prim[k]] - a[prim[k]]) == dir[k] and abs(b[prim[k]] - a[prim[k]]) >= MIN[k]
    assert sign(c[prim[k]] - b[prim[k]]) == dir[k] and abs(c[prim[k]] - b[prim[k]]) >= MIN[k]
# determinism: same prompt twice -> identical WAV bytes (D-005)
# control: sha256(E_twin) == sha256(REF)
# package: all peaks <= -0.3 dBFS, 24 files, gains in the key
```

Use the same seed for every file; the click measures are the noisiest (section 2).

## 7. Anleitung für den Hörer (Datei `Anleitung.md`, keine Stichwörter, keine Prompts)

> **Hörcheck: Kick-Varianten (ca. 13 Minuten)**
>
> **Aufbau (2 Minuten):** Alle `.wav` des Pakets in eine Audiospur laden, Warp aus, Projekttempo 136 BPM, jede Datei als Loop (ein Kick pro Takt). Gleiche Lautstärke an der Spur, nichts auf dem Master. Die Dateinamen sind anonym. `REF.wav` ist dein Vergleichskick. Eine `Schluessel`-Datei bekommst du nicht; sie liegt beim Lead.
>
> **So gehst du vor (für jede Datei `E01` bis `E17`, dann `K01` bis `K06`):**
> 1. Höre `REF`, dann die Datei, dann nochmal `REF`. Beliebig oft wiederholen.
> 2. Antworte im Antwortbogen: **Hörst du einen Unterschied zu `REF`?** (ja / nein / unsicher). „Nein" ist eine gültige und wichtige Antwort. Ein Teil der Dateien ist absichtlich nicht oder kaum anders.
> 3. Wenn ja: **Was ist der Hauptunterschied?** Kreuze höchstens zwei Wörter aus der Liste an und sag jeweils **mehr** oder **weniger** als `REF`.
>
> **Wortliste (gilt für jede Datei gleich):** Tiefbass · Körper (Mitten) · Klick · Höhe vom Klick · Länge des Ausklangs · Sättigung · Anschlag-Wumms · Helligkeit insgesamt · Lautstärke · etwas anderes (ein Wort).
>
> **Für `K01` bis `K06` zusätzlich:** **Ist die Datei näher an „meinem Kick" als `REF`?** (ja / gleich / nein).
>
> **Wichtig:** Rate nicht. Wenn du nichts hörst, schreib „nein". Du musst nicht jede Datei begründen. Nicht zwischendurch in den Schlüssel schauen (es gibt keinen). Am Ende: Welche Datei ist am ehesten „mein Kick", oder reicht `REF`?

## 8. Antwortbogen (Datei `Antwortbogen.md`, der Hörer füllt aus)

```
Hörcheck Kick-Varianten, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Pegel gleich gelassen: ja / nein

Datei | Unterschied zu REF? (ja/nein/unsicher) | Hauptunterschied (max. 2 Wörter aus der Liste) | mehr / weniger
E01   | ___ | ___ | ___
...   (E02 bis E17 gleich)
K01   | ___ | ___ | ___   | näher an "meinem Kick" als REF? ja / gleich / nein: ___
...   (K02 bis K06 gleich)

Gesamt: Welche Datei ist am ehesten "mein Kick"? ____  (oder: "REF reicht")
Anmerkungen: ____
```

## 9. Schlüssel und Auswertung (nur Lead, `Schluessel.md`; **nicht an den Hörer geben**)

Decode table (file numbers `E01 ...` are filled in by the packager from the blind-order rule; the expected word and sign are the vocabulary's promise, hypotheses):

| ID | Prompt | Expected answer (word, sign vs `REF`) | Number check (observed) |
| --- | --- | --- | --- |
| S1 / S2 | `sub:0` / `sub:2` | Tiefbass weniger / mehr (Körper may come up the other way) | sub150 0.431 / 0.713 |
| P1 / P2 | `punch:0` / `punch:2` | Körper weniger / mehr | body -4.13 / -2.71 dB |
| C0 / C2 | `click:0` / `click:2` | Klick weniger / mehr | clickdb -21.6 / -16.1 |
| B1 / B2 | `bite:0` / `bite:2` | Höhe vom Klick tiefer / höher (**weak**, "nein" plausible) | clickcent 2436 / 3201 |
| T1 / T2 | `tail:0` / `tail:2` | Länge kürzer / länger | d40 350 / not reached |
| D1 / D2 | `drive:0` / `drive:2` | Sättigung weniger / mehr (`drive:0` also changes the whole level and transient; "Lautstärke" or "etwas anderes" counts as audible) | crest 8.8 / 1.74 |
| W1 / W2 | `wums:1` / `wums:2` | Anschlag-Wumms mehr; W2 more than W1 | crest 0.96 / 0.67 |
| H1 / H2 | `bright:0` / `bright:2` | Helligkeit insgesamt weniger / mehr (`bright:2` also lowers body) | clickcent 2027 / 2900 |
| Z | twin of `REF` (byte copy) | **nein** (control) | identical bytes |
| K01 ... K06 | C1 ... C6 of section 3 | closer to "mein Kick": ja / gleich / nein (no prediction); named words should match the table of section 3 | section 3 |

How to read (one listener, one session; not a finding about the sound):

| Answer | Reading | Next step |
| --- | --- | --- |
| Control Z answered "ja" | The user hears a difference where none exists; weigh every "ja" below it against this | Repeat the affected blocks reversed before changing the vocabulary |
| End file: word and sign as expected | Direction confirmed for that end | none |
| End file: expected word, **opposite sign** | The keyword moves the other way (or the measure and the ear name different properties) | Check the number first; if the number is right, the word is not what the ear hears: rename or re-describe in the cheat sheet |
| End file: audible, but a **different word** | The step is audible; the vocabulary names the wrong property | Vocabulary text change (user-facing description), not a mapping change |
| End file: "nein" at **both** ends of a keyword | The step is too small to hear on a 136 BPM bar loop | Larger step `r` / `d` for that keyword (parser constant), re-measure, re-listen. Expected for `bite` |
| End file: "nein" at one end only | The step is asymmetric (e.g. `click:0`, `bright:0`, marginal by the numbers) | Per-end step size, or accept |
| Both ends of `wums` "nein" | `clip_db` 3 / 6 dB is not audible on this kick, in line with the weak K2 evidence on #103 | Treat `wums` as optional in the cheat sheet |
| K file "ja" with words matching section 3 | The combination does what the words say, and he likes it | Candidate for a preset `from_prompt` (decision: the user) |
| K file "nein" or words not matching | The combination does not add up as the single steps suggest | Measure the combination again; open a vocabulary question (section 4 of the vocabulary note) |
| Gesamt "REF reicht" | Keywords are for exploring; `dense` stays the default | none |

## 10. Limits

- One listener, one session, one kick (`dense` with seed 1001); the click measures vary with the seed, so a "nein" on `click` or `bite` could change with another seed.
- The expectations are my script's numbers, not the repo's `analyse()` (it returns only peak, length, `fundamental_hz`, `decay_20db_ms`, `decay_40db_ms`, DC). If the audio-engineer moves these measures into the repo, re-run the lead's check on them.
- The bar loop (one hit per 1.765 s) differs from the real use (hit on every beat). It answers "does the keyword move the sound", not "does it work in a groove".
- The neutral word list is my choice; a user word outside it (such as "Wumms" for the wrong property) is recorded in "etwas anderes" and decoded by the lead.
- No file was rendered into a listening package; the section 4 gains come from the CLI-default renders and may shift slightly with the common pre-gain.
