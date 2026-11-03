# Hörtest Goa-Bass: Schlüssel und Hinweise für den Lead (Issue #381, Refs #338)

**Erst nach dem Test lesen.** Diese Datei verrät den Aufbau (Kontrollpaar, Inhalt jeder Datei) und darf nicht vor oder während des Hörens zum Hörer gelangen. Die Anleitung für den Hörer ist `docs/setup/LISTENING_TEST_GOA_BASS.md`. Hintergrund: `docs/research/2026-11-03_goa-synth-voice-plan.md` (Hypothese H-voice-1), D-026. Nichts hier ist gehört worden; Zahlen beschreiben nur Signale. Alle Presetwerte sind Hypothesen, keine Befunde; für Goa liegen keine Referenz-Audios des Nutzers vor, „klingt nach Goa“ ist allein das Urteil des Nutzers.

## 1. Paket erzeugen

```bash
python -m audio_engine.listening_test_goa_bass --out /pfad/zu/neuem/ordner
```

Der Ordner muss neu oder leer sein und liegt **außerhalb** des Repos. Ergebnis: `hoerer/G?_?.wav` (13 Loops, wird verschickt) und `Schluessel.md` (nicht verschicken). Jeder Loop: 4 Takte, 140 BPM, mono, 48 kHz, 24 Bit, `dense`-Kick auf jedem Beat (Bus -6 dB), Bass-Bus -9 dB plus Angleich-Gain (<= 0; fester Startpegel, kein Lautheitsurteil). Positionen mit festem Seed 338, Wiederholung ergibt byte-gleiche Dateien. Kick, Muster-Slots und Fensterregel kommen aus `listening_test_bass.py`.

Muster: `rolling` = Note auf allen 16teln außer den Beat-Positionen (drei je Beat, Slot ein 16tel = 107,1 ms bei 140 BPM); `offbeat` = eine Note je Off-Beat-8tel (Slot ein Beat). Nicht enthalten: leiserer erster Roll-Ton (Velocity, kein Feld im Bass-Vertrag), Galopp- und Triplet-Rhythmus.

## 2. Presets (alle Note 36, Saw 0,9, Sine 0,4, Attack 1,5 ms, Hochpass 30 Hz, Tiefpass 320 Hz, Q 2, Filterhub 2,5 Oktaven, Drive 0,2 Vertragsdefault)

| Preset | gate_ms | release_ms | lp_env_decay_ms | Gate als Anteil eines 16tels (140 / 146 BPM, Rechnung) |
| --- | --- | --- | --- | --- |
| `goa-roll-short` | 62 | 12 | 8 | 0,58 / 0,60 |
| `goa-roll-medium` | 85 | 14 | 15 | 0,79 / 0,83 |
| `goa-roll-long` | 100 | 8 | 25 | 0,93 / 0,97 |

Fenster aus dem Plan Abschnitt 2.2: Gate 0,6 bis 1,0 eines 16tels, Filter-Schließzeit 2 bis 40 ms. Bei Note 36 enthält das stationäre Fenster (40 bis 80 % des Gates) bei `goa-roll-short` weniger als 2 Perioden, `fundamental_hz` im Sidecar ist dort `null` (Vertragsregel 6, kein Fehler).

## 3. Inhalt der Blöcke

| Block | Dateien (nicht blind) | Frage dahinter |
| --- | --- | --- |
| G1 | `short`, `medium`, `long` im 16tel-Roll | Gate-Länge: treiben / matschen; Goa-Reihenfolge |
| G2 | `medium`, `medium` (**byte-gleiche Kopie, Kontrollpaar**) | Wird „kein Unterschied“ geantwortet? Sonst alle Paar-Antworten dagegen gewichten |
| G3 | `medium` mit Filter-Zerfall 5, 20, 40 ms | Filter-Schließzeit (Grenzen des Plans 2 bis 40 ms; Vertragsminimum 5 ms) |
| G4 | `medium` gegen `long` mit Gate 200 / Release 15 (klingt über ein Off-Beat-8tel aus) im `offbeat`-Muster | Off-Beat-8tel-Variante (Bonedo #1, Psytrance, nicht als Goa belegt) |
| G5 | `medium` mit Note 31, 36, 40 | Tonhöhe zum Kick (Kick-Tail Median 53 Hz in den Kicks des Nutzers; Mischfrage) |

## 4. Pegelangleich

Wie im Bass-Test: RMS einer **einzelnen Note allein** (float) über 40 % bis 80 % der **kürzesten** `gate_ms` des Blocks, absolutes Fenster gleich für alle Dateien (G1: 24,8 bis 49,6 ms; G2, G4, G5: 34 bis 68 ms; G3: 34 bis 68 ms), alle Dateien auf die leiseste des Blocks heruntergezogen. Das Fenster ist kürzer als zwei Perioden von Note 36 bei G1; es gleicht den Notenanfang an, nicht den Gesamtpegel (z. B. G4 `long` mit 200 ms Gate). Ob die Dateien gleich laut wirken, ist nicht gemessen und nicht behauptet; die Pegel-Anmerkung des Hörers auswerten. Gegenprobe im Test: Datei minus quantisierter Kick-Loop, RMS im selben Fenster; Spreizung unter 0,5 dB; Spitze <= -0,3 dBFS.

## 5. Was der Lead mit den Antworten macht

G2 zuerst. Ein einzelner Durchgang ist ein Hinweis, kein Beweis. Antworten bestätigen oder verwerfen nur die Preset-Fenster; ohne Goa-Referenzen des Nutzers bleibt „Goa“ eine Nutzerdefinition. Live-Schritte im Aufbau sind nicht in Live geprüft.
