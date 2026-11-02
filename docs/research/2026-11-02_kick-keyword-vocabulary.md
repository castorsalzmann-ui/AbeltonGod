# Design proposal: kick keyword vocabulary with weights (#226)

- **Date:** 2026-11-02 · **Role:** sound-designer · **Receiving issue:** #226 · **Status:** proposal for the user's decision. No code, no contract change, **no listening claims**: every effect below is a measured number, whether it sounds as intended is "to be checked by ear".
- **Base:** `origin/main` 826fe3f (engine `src/audio_engine/`, `kick-params` v0.3). Measured with an independent script in the session scratchpad (not in the repo; definitions in section 6), rendering the engine through `render_kick`.
- **Builds on:** [kick-gen2 learnings](2026-10-28_kick-gen2-learnings.md) (P3, P6, F1, section 4, rule "one parameter space, genre only as data"), [layering and reference steering](2026-11-02_kick-layering-and-reference-steering.md), [listening-test-3 plan](2026-11-02_listening-test-3-plan.md) (noise yardstick), user result on #103.

## 0. Decision summary

1. **Eight weighted keywords** (`sub, punch, click, bite, tail, drive, wums, bright`) plus five **slots** that are not weights (`note, bpm, beats, seed, variants`). All eight map onto existing `kick-params` fields. **No contract change is needed** for them.
2. **One weight scale, defined once (section 2):** weight `w` runs 0 ... 2, `w = 1` is the `dense` preset (the kick the user closed as finished), `w = 0` / `w = 2` are one full step down / up. Unmentioned keyword = `dense` value (exception: `wums` is an add-on, unmentioned = off).
3. **Opposites are one axis** (`tail` below 1 = short, above 1 = long), so conflicts mostly cancel by arithmetic, not by special rules (section 4).
4. **Two things the measurements rejected** (section 3, worth knowing before building): `click_level` and `tone` do **not** move the sub share (a first "sub" macro built on them failed), and a longer `amp_attack_ms` did **not** make the 10 ms onset less bright; so there is no `soft` keyword in v1.
5. **Five wishes need new parameters** (section 5): real rumble, wavefold/curve family, hold time, separate sub sine, noise "air". Proposals only.
6. **Open questions: 4** (section 8).

## 1. What is already known (no new evidence in this note)

| Source | Finding | Used here as |
| --- | --- | --- |
| #103 K1 | `drive` 0.45 (`dense`) > 0.60 > 0.30 | `drive` w = 1 is 0.45; w = 0.67 / 1.33 are exactly the K1 neighbours (0.30 / 0.60) |
| #103 K2 | `clip_db` 3 preferred ("mehr wums") over `dense` | `wums` typical value 3 dB. **Weak evidence:** K0 (identical files) also got a pick, so a forced pick is a bias-level guess |
| #103 K3 | layer on `dense`: "kaum hörbare Unterschiede" | **No `layer` keyword.** `polarity` / `offset_ms` stay engine fields, not vocabulary |
| #103 K4 | `dense` (560 ms decay) preferred over 1 beat / 28 ms at 136 BPM | `beats` is a slot, never a default; `tail` below 1 has no taste support yet |
| #103 K5 | all four seed variants liked, similar | Seed variation (`variants`) stays the way to get "same character, other draw". The vocabulary is for **other** characters |
| learnings 2 | taste range: tail f0 45-60 Hz, 75-90 % sub, clean tails, click amount freest axis | `note` slot offers notes inside 45-60 Hz; `click` is the freest axis |
| learnings P3 | every exposed control must move an analysis value | each keyword below has a measured primary value and a seed-noise check |
| learnings P6 | cause to effect beats genre labels | genre words only as optional bundles on top (section 7) |

## 2. The weight scale (defined once)

All keywords start from the `dense` preset with `clip_db` 0 (`schema_version` 0.3). Each keyword lists, for each field it moves, a **step**:

- **Ratio field** (Hz, ms): `value = base x r^(w-1)`; step `r`. w = 0.5 gives `r^-0.5`, w = 1.5 gives `r^0.5`.
- **Linear field**: `value = base + (w-1) x d`; step `d`. Where the field has a natural zero (`click_level`, `drive`) `d` equals the `dense` value, so **w = 0 means off** and w = 2 doubles it.
- **Add-on** (`wums`, stage is off in `dense`): `value = w x typical`; w = 0 off, w = 1 typical, w = 2 twice.
- **Reading the weights:** 0 = lowest step / off, 0.5 = half a step down, 1 = `dense`, 1.5 = half a step up, 2 = one full step up. Practical range 0.5-1.5; 0 and 2 are the edges. Weights outside 0-2 are rejected.
- **Direction rule:** the weight is "how much of the property". Where more of the property means a *smaller* number (`sub` shortens the pitch fall time), the step ratio is below 1.

Keywords that share a field **add in the field's own unit** (ratio fields multiply, linear fields add). Then the result is clamped to the contract range; every clamp is reported to the user, never silent.

## 3. The vocabulary (8 keywords) with measured effect

Primary value = the analysis value that must move (hypothesis; confirmed or rejected by the measurement in the last column). **Seed noise** = range over the four `dense` variants (K5 yardstick: sub 0.597-0.623, crest 2.19-2.60 dB, body 80-300 Hz level -3.64...-3.24 dB, click-zone level -19.7...-18.2 dB). An effect counts as measurable when it exceeds that range. Numbers: base `dense`, one keyword at a time, w = 0 / 1 / 2.

| EN | DE | Meaning (producer language) | Fields and step (w = 2 relative to w = 1) | Primary value, w = 0 / 1 / 2 | vs seed noise |
| --- | --- | --- | --- | --- | --- |
| `sub` | Sub | more weight in the low end, less "mid knock" | `pitch_start_hz` x1/1.2 (200 -> 167), `pitch_decay_ms` x1/1.3 (40 -> 30.8) | sub share 0-150 ms: 0.431 / 0.556 / 0.713; body 80-300 Hz level: -2.82 / -3.24 / -4.64 dB | sub: 6x range; body: 3.5x range. **Confirmed** |
| `punch` | Punch | more body energy 80-300 Hz at the start, fall begins higher | `pitch_start_hz` x1.3 (200 -> 260) | body level: -4.13 / -3.24 / -2.71 dB; sub share (whole file): 0.725 / 0.623 / 0.529 | body: w = 0 clear (2x), w = 2 only 1.3x range (marginal). Sub share: clear. **Partly confirmed** |
| `click` | Klick | amount of the high-frequency click | `click_level` + 0.35 (0 -> 0.70) | high-pass 1 kHz level, first 15 ms: -21.6 / -19.5 / -16.1 dB; onset share above 1 kHz: 0.0156 / 0.0256 / 0.0553 | 2-4x range. **Confirmed** (w = 0 is off) |
| `bite` | Biss | pitch of the click (higher = thinner, harder) | `click_tone_hz` x1.5 (3500 -> 5250) | centroid of the above-1-kHz part, first 15 ms: 2436 / 2582 / 3201 Hz | w = 2 +24 %, but the seed variants span 2582-4164 Hz. **Weak: only readable in a single-axis comparison.** |
| `tail` | Ausklang | length of the body / tail | `amp_decay_ms` x1.35 (560 -> 756), `length_ms` x1.35 (480 -> 648) | time to -40 dB (own 5 ms RMS from the onset, see section 6; not `analyse()`): 331 / 450 / 604 ms; sub share (whole file) 0.577 / 0.623 / 0.708 | 3-4x range. **Confirmed.** Side effect: tail harmonic ratio 0.0003 / 0.0018 / 0.0083 (longer tail carries more drive residue) |
| `drive` | Sättigung | saturation of the whole kick (tanh) | `drive` + 0.45 (0 -> 0.90) | crest factor 0-100 ms: 8.80 / 2.19 / 1.74 dB; tail harmonic ratio 0 / 0.0018 / 0.0095 | w = 0 to 1 is a very large jump (crest 8.8 dB, sub share 0.325): **below w = 0.67 the kick is no longer the K1 optimum region.** Confirmed |
| `wums` | Wums | peaks pressed flat at the attack (hard clip), tail stays clean | `clip_db` = w x 3 (add-on: 0 / 3 / 6) | crest: 2.19 / 0.96 / 0.67 dB; onset share above 1 kHz 0.0256 / 0.0358 / 0.0483; click-zone level -19.5 / -16.6 / -14.7 dB | crest 3.7x range at w = 1. **Confirmed.** Follows the K2 file (`clip_db` 3) |
| `bright` | Helligkeit | spectral tilt toward the top | `tone` + 0.5 (0 -> 0.5) | click-zone centroid: 2027 / 2582 / 2900 Hz; onset share above 1 kHz: 0.0156 / 0.0256 / 0.0395 | clear. Side effect: crest 2.12 / 2.19 / 3.99 dB and body level -3.15 / -3.24 / -5.05 dB (tilt takes body level away) |

**Aliases (words that are a fixed weight of the same axis):** `kurz` = `tail:0.4`, `lang` = `tail:1.6`, `dunkel` = `bright:0.4`, `hell` = `bright:1.6`, `sauber` = `drive:0.5` (see warning in the `drive` row: K1 ranked 0.30 last).

**Slots (not weights):**

| Slot | Field | Rule |
| --- | --- | --- |
| `note` | `tail_note` (23-46) | Replaces `pitch_end_hz`. Notes inside the measured taste range 45-60 Hz: 30 = 46.25 Hz, 31 = 49.00, 32 = 51.91, 33 = 55.00, 34 = 58.27 Hz. `dense` has 52 Hz, about note 32. Name convention open (question 3) |
| `bpm`, `beats` | `bpm`, `length_beats` | `beats` replaces `length_ms` and the engine derives `amp_decay_ms`; **`tail` is then ignored** (reported). Needs `bpm` (60-200); 0.25-4 beats and the -60 dB length rule apply |
| `seed`, `variants` | `seed`, `variants` | Same prompt + same seed = byte-identical (D-005) |

**Not covered, expert only (via `--set`):** `click_q`, `click_decay_ms`, `amp_attack_ms`, `peak_ceiling_dbfs`, `polarity`, `offset_ms`, `sample_rate`, `bit_depth`.

**Measured and dropped (v1):**
- *First idea for `sub` (lower `click_level`, `tone`)*: sub share 0.6218 / 0.6233 / 0.6245 across w = 0/1/2, i.e. inside seed noise. Hypothesis **rejected**; the sub share is moved by pitch fall, tail length and saturation, so `sub` uses the pitch fall.
- *`soft` (longer `amp_attack_ms`, 0.125 / 0.5 / 2 ms)*: the above-1-kHz onset share went **up** (0.0261 / 0.0256 / 0.0369), the opposite of the hypothesis (the body rises later, so the click is relatively larger). No primary value that behaves; left out.
- *`snap` as click tone plus shorter click decay*: shorter decay lowered the click energy and hid the tone effect (onset share above 3 kHz 0.0105 / 0.0078 / 0.0056). Reduced to `bite` (tone only).

## 4. Combination and conflict rules

1. **Add in field units** (section 2). Example: `sub:2` x1/1.2 and `punch:2` x1.3 on `pitch_start_hz` give 200 x 1.083 = 216.7 Hz (measured sub share 0.672, close to `dense` 0.623 but not equal, since `sub` also shortens the fall). Opposing words do not erase each other exactly.
2. **Opposing pairs:** `sub` / `punch` (pitch start), `tail` short / long (aliases `kurz` / `lang` on one axis), `bright` high / low (`hell` / `dunkel`), `click` vs `sub` is **not** an opposition (measured: click does not move the sub share).
3. **Hard limits (contract):** `pitch_start_hz` 60-600 and not below `pitch_end_hz`; `pitch_decay_ms` 2-300; `amp_decay_ms` 20-2000; `length_ms` 80-2000; `click_level` 0-1; `drive` 0-1; `clip_db` 0-12; `tone` -1...1. Clamps are reported.
4. **Pitch-settle guideline** (`pitch_settles`, not enforced by the schema): after combining, if `pitch_decay_ms` exceeds `max_settled_pitch_decay_ms`, it is **lowered to that limit** and the change is reported. Measured: `dense` has limit 46.3 ms; `tail:0` (shorter decay) lowers it to 34.3 ms, so `pitch_decay_ms` 40 is cut to 34.3; `sub:0` (start 240 Hz) gives limit 43.7 ms and cuts 52 to 43.7.
5. **Length rule:** `length_ms` and `amp_decay_ms` move together under `tail` (same ratio, as in `dense`: 480 vs 560). With `beats` the engine's -60 dB rule decides and can reject the request; the error text names the allowed range. `tail` is then ignored.
6. **Order of application:** (a) add keyword steps per field, (b) clamp to contract, (c) `start >= end`, (d) pitch-settle fix, (e) engine renders (and may still reject `beats` requests).
7. **Strong stacking:** `tail:2, drive:2, wums:2, click:2` renders (P10 below) but the tail harmonic ratio rises to 0.113 (63x `dense`), far outside the taste range (learnings: tails almost pure sine, median 0.01, 10 of 77 above 0.05). Not forbidden; the response should print the measured tail harmonic ratio when it exceeds 0.05.

## 5. Needs a new parameter (proposals for `contract-change`, not used above)

| Wish | Why it is not covered | Proposed field (proposal) |
| --- | --- | --- |
| real rumble tail | no noise or reverb tail in the engine (learnings S3); `tail:1.6 + sub` only lengthens the sine | `rumble_level`, `rumble_decay_ms`, `rumble_lowpass_hz` |
| metallic / folded / "gritty" saturation | one curve only (tanh, plus hard clip stage) | `drive_curve` enum (tanh, asym, fold) |
| hold before the decay ("fat start") | amp envelope has attack + exponential decay only | `amp_hold_ms` |
| a separate sub sine under the pitch-swept body | one oscillator | `sub_level`, `sub_hz` |
| broadband noise "air" in the click | click is band-passed noise around `click_tone_hz` | `click_noise_mix` |

Recording the prompt with the file needs no contract change: the sidecar already has a free-text `description`.

## 6. Measures (independent script, to move into `analysis.py` later)

`analyse()` today returns only peak, length, `fundamental_hz`, `decay_20db_ms`, `decay_40db_ms`, DC. **Everything else below is not in the engine yet**; a mapping implementation needs it (audio-engineer issue).

- **Crest factor 0-100 ms** = peak / RMS over 100 ms from the onset (first sample above 10 % of peak), dB.
- **Sub share (whole file)** = energy below 100 Hz / total, rectangular window (pitfall 1); **sub share 0-150 ms** same on the first 150 ms (separates body from tail length).
- **Body level 80-300 Hz** = RMS dB of a 4th-order band-pass, 5-80 ms after onset.
- **Onset share above 1 kHz** = energy share above 1 kHz in the first 10 ms (rectangular).
- **Click-zone level / centroid** = RMS dB / spectral centroid of the part above 1 kHz (4th-order high-pass), first 15 ms.
- **Tail harmonic ratio** = power at 2x-8x f0 / power at f0, 100-300 ms, Hann window.
- **Time to -40 dB** (`d40`) = first 5 ms-RMS frame, from the onset, that is 40 dB under the RMS maximum; `None` if never reached inside the file. It is **not** `analyse()['decay_40db_ms']` (that returns `None` for `dense` at its own 480 ms and 498 ms at 1000 ms length; the two methods differ, as in the listening-test-3 plan). The `tail` claim therefore rests on this own measure plus the sub share. `fundamental_hz` is from the engine analysis (52.0 Hz in all rows). Command pattern: `render_kick(params)` on the table's parameters, then the functions above (scratchpad `kw/kw.py`, `kw/bite.py`, `kw/prompts.py`; not committed).

## 7. Ten worked prompts

Weights as given; unmentioned = `dense` (`wums` unmentioned = off). Parameter changes are those of the table above; measured values from the same render. **Hypotheses; sound is to be checked by ear.**

| # | Prompt | Parameter direction (from `dense`) | Measured (crest dB / sub share 0-100 Hz / body dB / click-zone dB / time to -40 dB ms, own method) |
| --- | --- | --- | --- |
| P1 | *(empty)* = `dense` | none | 2.19 / 0.623 / -3.24 / -19.5 / 450 |
| P2 | `kurz, punch:1.2, click:1.2` (= `tail:0.4`) | decay 468, length 401, start 211, fall cut 40 -> 38.0 (settle), click 0.42 | 2.42 / 0.574 / -3.39 / -18.7 / 371 |
| P3 | `sub:1.5, tail:1.6, dunkel, click:0.5` | start 183, fall 35, decay 670, length 575, click 0.175, tone -0.3 | 2.05 / 0.746 / -3.71 / -23.5 / 533 |
| P4 | `punch:1.3, click:1.3, drive:1.2, wums:1` | start 216, click 0.455, drive 0.54, clip 3 | 0.89 / 0.659 / -2.15 / -15.2 / none (never -40 dB inside file) |
| P5 | `dunkel, click:0.5` | click 0.175, tone -0.3 | 2.13 / 0.625 / -3.17 / -22.0 / 450 |
| P6 | `drive:1.3, bite:1.5, wums:1` | drive 0.585, click tone 4287 Hz, clip 3 | 0.68 / 0.688 / -2.09 / -15.7 / none |
| P7 | `sauber` (= `drive:0.5`) | drive 0.225 | 3.21 / 0.532 / -3.80 / -23.0 / 402 |
| P8 | `sub:1.7, tail:1.5` | start 176, fall 33, decay 651, length 558 | 2.15 / 0.757 / -4.07 / -21.5 / 513 |
| P9 | `sub:2, punch:2` (conflict) | start 217, fall 30.8 | 2.20 / 0.672 / -3.73 / -19.3 / 447 |
| P10 | `tail:2, drive:2, wums:2, click:2` (stacking) | decay 756, length 648, drive 0.9, clip 6, click 0.70 | 1.80 / 0.776 / -3.49 / -13.1 / none; tail harmonic ratio 0.113 |

All ten rendered with the pitch-settle guideline true; no contract clamp fired; the settle cut fired in P2 only (`tail:0.4`). Table cells at w = 0 in section 3 (`sub` sub share 0.431, `tail` sub share 0.577) are measured **after** that kind of settle cut (uncut `sub:0` would be 0.366). Not measured: any alias bundle of section 8, because those are not proposed for use yet.

## 8. Genre words and open questions

**Genre words (`techno`, `trance`, `rumble`):** per the learnings rule they would be **bundles of the keywords above, stored as data**, not code. I do **not** propose values for `techno` / `trance`: nothing in the repo grounds them (the 77 reference kicks carry no genre labels). Only `rumble` has a basis (the preset `rumble-ready`: decay 800, length 750, tone -0.2, click 0.2), and it would be `lang + dunkel + click:0.5` only as an approximation until a real rumble parameter exists (section 5).

**Open questions (each changes the design):**

1. **Absolute or relative?** Proposed: every prompt starts from `dense` (reproducible, same words = same kick). The alternative is "relative to the last kick" (`mehr sub`, `weniger klick` steering step by step). Both can exist, but the first build should choose one.
2. **Is "Sättigung" = `drive` and "Wums" = `wums` (clip)?** From your K3 comment ("bisschen mehr Sättigung") the word came up for a layered file where neither `drive` nor `clip_db` changed, so the meaning of your word is not established.
3. **Note names:** use numbers (30-34), Hz, or names? Ableton calls note 60 "C3", the contract's `tail_note` is the MIDI number (scientific pitch calls 60 "C4"). Which convention should the vocabulary speak?
4. **Genre bundles:** wanted now? If yes, name 2-3 kicks (audio) per word, so the bundle is measured from content, not guessed.

## 9. Cheat sheet (Deutsch, eine Seite)

**So fragst du nach einem Kick:** Wörter mit Gewicht, z. B. `sub:1.5, punch:1.2, dunkel`. Kein Gewicht = Wert wie beim Kick `dense`.

**Gewichte (gilt für alle Wörter gleich):**

| Gewicht | Bedeutung |
| --- | --- |
| 0 | aus bzw. kleinster Schritt |
| 0.5 | halber Schritt weniger |
| **1.0** | **wie `dense` (dein fertiger Kick)** |
| 1.5 | halber Schritt mehr |
| 2.0 | ein ganzer Schritt mehr (Maximum) |

Sinnvoll: 0.5 bis 1.5. Mehr als 2 gibt es nicht. Beispiel: `click:0` = kein Klick, `click:2` = doppelt so viel Klick.

**Die Wörter:**

| Wort | Was es macht | Mehr (über 1) | Weniger (unter 1) |
| --- | --- | --- | --- |
| `sub` | Gewicht im Tiefbass | tiefer, weniger Mitten-Knock | mehr Mitten |
| `punch` | Körper 80-300 Hz am Anfang | mehr Körper-Energie am Start | weniger |
| `click` | Menge des hohen Klicks | mehr Klick (0 = aus) | weniger |
| `bite` | Höhe des Klicks | höherer, dünnerer Klick | tiefer |
| `tail` | Länge des Ausklangs | länger | kürzer |
| `drive` | Sättigung des ganzen Kicks | mehr (1.0 = dein Optimum) | weniger. Unter 0.67 verlässt du den getesteten Bereich |
| `wums` | Spitzen am Anschlag abgeschnitten | 0 = aus, 1 = 3 dB (wie dein K2A), 2 = 6 dB | weniger |
| `bright` | heller / dunkler | heller | dunkler |

**Abkürzungen:** `kurz` (= tail 0.4), `lang` (tail 1.6), `dunkel` (bright 0.4), `hell` (bright 1.6), `sauber` (drive 0.5).

**Zusätze (ohne Gewicht):** `note:32` (Grundton als MIDI-Zahl, 30-34 = 46-58 Hz, dein Bereich), `bpm:136 beats:1` (Länge in Schlägen; dann gilt `tail` nicht), `seed:1001`, `variants:4`.

**Regeln, die immer gelten:**
- Gegenteile gleichen sich aus (`sub` gegen `punch`, `kurz` gegen `lang`), nicht ganz genau.
- Was außerhalb des erlaubten Bereichs liegt, wird auf den Rand gesetzt und **gemeldet**.
- Die Tonhöhen-Absenkung wird bei Bedarf automatisch verkürzt (gemeldet).
- Sehr viel von allem zusammen (`tail:2, drive:2, wums:2`) geht, macht aber den Ausklang unrein (Messwert wird angezeigt).
- Noch nicht möglich (braucht neue Parameter): echter Rumble, Wavefold/Metall, Haltezeit, extra Sub-Sinus, Rausch-Luft.
- Kein `layer`: Schichten waren im Test kaum hörbar (K3).

**Beispiele:** `kurz, punch:1.2, click:1.2` · `sub:1.5, lang, dunkel, click:0.5` · `punch:1.3, click:1.3, drive:1.2, wums:1` · `drive:1.3, bite:1.5, wums:1` · `sub:1.7, tail:1.5, note:31`.

## Limits

- One base (`dense`), one keyword at a time for the table; the ten prompts check combinations only for the numbers shown. Each cell is one render (deterministic, so no repeat), but measures other than `fundamental_hz` come from my script, not from the repo analysis.
- Whether any step is audible, pleasant, or "means what the word says" is for the user's ears. The seed-noise yardstick only says a difference is larger than seed variation, not that it is audible.
- `bite` is weak by the yardstick; `punch` is marginal at w = 2 by body level.
- Steps (1.2, 1.3, 1.35, 1.5, 0.5, 0.45) are my proposals to be adjusted after a first listening round; the scale definition does not change when they do.
