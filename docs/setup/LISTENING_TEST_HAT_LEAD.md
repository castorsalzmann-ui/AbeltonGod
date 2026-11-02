# Hörtest Hi-Hat: Schlüssel und Hinweise für den Lead (Issue #295)

**Erst nach dem Test lesen.** Diese Datei verrät den Aufbau (Kontrollpaar, Inhalt jeder Datei) und darf nicht vor oder während des Hörens zum Hörer gelangen. Die Anleitung für den Hörer ist `docs/setup/LISTENING_TEST_HAT.md`. Plan und Hypothesen: `docs/research/2026-11-02_hat-targets-and-listening-plan.md` Abschnitt 5. Nichts hier ist gehört worden; Zahlen beschreiben nur Signale.

## 1. Paket erzeugen

Aus dem Repo-Stamm, mit der Engine auf dem Pfad (`PYTHONPATH=src` oder editable install), Bash. `OUT` ist ein neuer, leerer Ordner **außerhalb** des Repos. Verschickt wird nur `OUT/hoerer/`; `OUT/render/` enthält die Sidecars (Dateinamen und Parameter verraten den Schlüssel).

```bash
set -euo pipefail
OUT=/pfad/zu/neuem/ordner
mkdir -p "$OUT/render" "$OUT/hoerer"
C=peak_ceiling_dbfs
h() { d="$1"; shift; python -m audio_engine.kick --category hat --out "$OUT/render/$d" "$@" > /dev/null; }
# T1 (Level-Angleich: RMS 0-30 ms, auf die leiseste Datei des Blocks)
h T1_loose --preset closed-loose --set $C=-2.9
h T1_tight --preset closed-tight --set $C=-0.3
# T0, T2, T3, T6 (closed-std und Abwandlungen)
h T0_S      --preset closed-std --set $C=-0.3
h T2_S      --preset closed-std --set $C=-1.7
h T2_hp9000 --preset closed-std --set hp_hz=9000 --set $C=-0.3
h T2_hp4500 --preset closed-std --set hp_hz=4500 --set $C=-0.8
h T3_m1 --preset closed-std --set metal=1 --set $C=-0.3
h T3_m0 --preset closed-std --set metal=0 --set $C=-0.3
h T3_S  --preset closed-std --set $C=-3.2
h T6_v0 --preset closed-std --set $C=-3.9
h T6_v1 --preset closed-std --seed 1517744281 --set decay_ms=63.1094 --set hp_hz=6474.2371 --set metal=0.6219 --set pitch_scale=0.9712 --set color=0.5927 --set $C=-0.3
h T6_v2 --preset closed-std --seed 548367253  --set decay_ms=73.2791 --set hp_hz=5752.0998 --set metal=0.5841 --set pitch_scale=1.0306 --set color=0.464  --set $C=-2.2
h T6_v3 --preset closed-std --seed 3486530176 --set decay_ms=75.3099 --set hp_hz=6309.3145 --set metal=0.5616 --set pitch_scale=1.0151 --set color=0.5127 --set $C=-0.9
# T5, T4 (Level-Angleich: RMS 0-100 ms)
h T5_split --preset open-long --set body_mix=0.4 --set decay_hi_ratio=0.5 --set $C=-0.3
h T5_long  --preset open-long --set $C=-0.5
h T4_choke --preset open-long --set choke_ms=220 --set $C=-1.3
h T4_short --preset open-short --set $C=-0.3
h T4_long  --preset open-long --set $C=-1.3
# der Kick
python -m audio_engine.kick --out "$OUT/render/kick" --preset dense > /dev/null
# anonyme Namen
w() { cp "$OUT"/render/"$1"/*.wav "$OUT/hoerer/$2.wav"; }
w kick Kick
w T1_loose T1_A;  w T1_tight T1_B
w T0_S T0_A;      cp "$OUT/hoerer/T0_A.wav" "$OUT/hoerer/T0_B.wav"
w T2_S T2_X;      w T2_hp9000 T2_Y;  w T2_hp4500 T2_Z
w T5_split T5_A;  w T5_long T5_B
w T4_choke T4_X;  w T4_short T4_Y;   w T4_long T4_Z
w T3_m1 T3_X;     w T3_m0 T3_Y;      w T3_S T3_Z
w T6_v2 T6_A;     w T6_v0 T6_B;      w T6_v3 T6_C;  w T6_v1 T6_D
```

Die T6-Varianten sind die Parameter von `--variants 4` (aus den Sidecars von `closed-std --variants 4` gelesen) als einzelne Renders, weil jede Variante ihren eigenen Pegel-Angleich braucht. Ohne Angleich (Ceiling -0.3) sind die Bytes der Variante gleich denen von `--variants 4`.

## 2. Schlüssel (Datei zu Render)

| Datei | Render | Änderung gegenüber `closed-std` (S: `decay_ms` 70, `hp_hz` 6000, `metal` 0.6, Seed 1) | `peak_ceiling_dbfs` |
| --- | --- | --- | --- |
| T1_A | closed-loose | `decay_ms` 120, `hp_hz` 5000 | -2.9 |
| T1_B | closed-tight | `decay_ms` 35, `hp_hz` 7000 | -0.3 |
| T0_A, T0_B | S | keine; **byte-gleiche Kopie** (Kontrollpaar) | -0.3 |
| T2_X | S | `hp_hz` 6000 | -1.7 |
| T2_Y | S | `hp_hz` 9000 | -0.3 |
| T2_Z | S | `hp_hz` 4500 | -0.8 |
| T5_A | open-long | `body_mix` 0.4, `decay_hi_ratio` 0.5 | -0.3 |
| T5_B | open-long | `decay_ms` 500 | -0.5 |
| T4_X | open-long | `choke_ms` 220 | -1.3 |
| T4_Y | open-short | `decay_ms` 250 | -0.3 |
| T4_Z | open-long | `decay_ms` 500, ungechoked | -1.3 |
| T3_X | S | `metal` 1.0 | -0.3 |
| T3_Y | S | `metal` 0 | -0.3 |
| T3_Z | S | `metal` 0.6 | -3.2 |
| T6_A | S Variante 2 | Seed 548367253 | -2.2 |
| T6_B | S Variante 0 (= S) | Seed 1 | -3.9 |
| T6_C | S Variante 3 | Seed 3486530176 | -0.9 |
| T6_D | S Variante 1 | Seed 1517744281 | -0.3 |
| Kick | Kick-Preset `dense` | | -0.3 |

Die Positionen (A/B, X/Y/Z, A bis D) sind von Hand festgelegt und gemischt (nicht jede Frage hat die „erwartete" Datei auf A). Die Dateinamen enthalten nur Block und Buchstabe. 19 Hörerdateien aus 14 Renders plus Kick.

## 3. Gemessen (Befehle unten, Signalwerte, keine Hörurteile)

Level-Angleich je Block: RMS des Hats allein über 0-30 ms (Closed-Blöcke) bzw. 0-100 ms (Open-Blöcke), gemessen an den fertigen Dateien in `hoerer/`; jeder Block ist auf die leiseste Datei heruntergezogen, dazu dient `peak_ceiling_dbfs`.

| Block | Fenster | RMS in dBFS je Datei | Spreizung |
| --- | --- | --- | --- |
| T1 | 0-30 ms | A -16.47, B -16.43 | 0.04 dB |
| T2 | 0-30 ms | X -15.79, Y -15.76, Z -15.75 | 0.04 dB |
| T3 | 0-30 ms | X -17.26, Y -17.25, Z -17.29 | 0.04 dB |
| T6 | 0-30 ms | A -18.03, B -17.99, C -17.95, D -18.00 | 0.08 dB |
| T5 | 0-100 ms | A -15.25, B -15.24 | 0.01 dB |
| T4 | 0-100 ms | X -16.04, Y -16.05, Z -16.04 | 0.01 dB |

Vor dem Angleich (alle auf Peak -0.3): bis zu 3.6 dB Unterschied im Block T6 (0-30 ms) und 2.6 dB in T1. Folge für die Lesung: Der Angleich folgt dem Anschlag. Längere Dateien (T1_A mit 151 ms, Open-Hats) haben im Angleichfenster nicht denselben Gesamtpegel; das gilt als Anmerkung, wenn der Hörer „lauter" schreibt.

Determinismus: das Paket wurde in zwei getrennten Läufen erzeugt, SHA-256 aller 20 Dateien in `hoerer/` identisch (`T0_A` und `T0_B` identisch).

## 4. Abweichungen vom Plan (Abschnitt 5 der Hat-Notiz)

- **Einzelschläge statt Loops.** Es gibt keinen Loop-Generator für Hats, und das Issue verbietet Engine-Änderungen. Der Hörer baut das Muster (Kick auf jedem Beat, Hat auf jedem 16tel bzw. Off-Beat-8tel) einmal im Simpler. Folge: das Abschneiden durch den nächsten Schlag (Plan: 3 ms Fade) hängt an den Simpler-Einstellungen des Hörers, nicht an der Datei. Wenn der Test im Ergebnis auf Längenfragen (T1, T4) baut, einmal prüfen, dass der Hörer Voices 1 benutzt hat. Die Live-Schritte sind nicht von uns in Live geprüft.
- **Kick-Level:** nicht festgelegt, der Hörer stellt den Hat-Fader einmal selbst ein. Die Plan-Vorgabe „dense Kick auf jedem Beat" ist erfüllt (Preset `dense`, Peak -0.3 dBFS).
- **T6:** Pegel-Angleich je Variante statt `--variants 4` in einem Lauf (siehe Abschnitt 1).
- **Clap-Vorlage nicht auf main:** `listening_test_clap.py` (PR #254) und `docs/setup/LISTENING_TEST_CLAP*.md` liegen zum Zeitpunkt dieses PR noch nicht auf `origin/main`; als Vorlage diente der Branch `phase-06/232-clap-listening`.
- **Folgeissue (Vorschlag):** ein Loop-Generator `listening_test_hat.py` nach dem Muster von `listening_test_clap.py` (PR #254) würde das Abschneiden und das Muster in die Datei legen und den Hörer-Aufbau auf „Dateien laden, Warp aus" verkürzen. Das ist Engine-/Tool-Arbeit des audio-engineer, nicht Teil dieses Issues.

## 5. Was der Lead mit den Antworten macht

Gleiche Lesetabelle wie in Abschnitt 5 der Hat-Notiz (T0 zuerst: ist die Antwort nicht „kein Unterschied", werden alle Paarantworten dagegen gewichtet und das Paar vertauscht wiederholt). Ein einzelner Durchgang eines Hörers ist ein Hinweis, kein Beweis. Die Pegel-Anmerkung des Hörers auswerten: der Angleich ist RMS über das Fenster oben, nicht empfundene Lautheit.

## 6. Befehle, die für die Messwerte liefen

- Alle Renders: der Block in Abschnitt 1, zweimal in zwei neue Ordner; danach `sha256sum` über `hoerer/*.wav` je Ordner und Vergleich: identisch.
- Pegel: RMS der ersten 30 bzw. 100 ms von `audio_engine.io.wav_samples(...)` (24-Bit-Ganzzahlen), in dBFS umgerechnet mit 20·log10(2^23); Skript im Arbeitsbereich, nicht im Repo.
- Vorab-Messung des Peak-Renders für die Ceiling-Werte: dieselben Presets mit Ceiling -0.3, Differenz zur leisesten Datei des Blocks, auf 0.1 dB gerundet.
