# Hörtest Bass: Schlüssel und Hinweise für den Lead (Issue #361)

**Erst nach dem Test lesen.** Diese Datei verrät den Aufbau (Kontrollpaar, Inhalt jeder Datei) und darf nicht vor oder während des Hörens zum Hörer gelangen. Die Anleitung für den Hörer ist `docs/setup/LISTENING_TEST_BASS.md`. Hintergrund: `docs/research/2026-11-02_bass-targets.md` Abschnitt 6, Issue #335 (Drive-Default und DC). Nichts hier ist gehört worden; Zahlen beschreiben nur Signale.

## 1. Paket erzeugen

```bash
python -m audio_engine.listening_test_bass --out /pfad/zu/neuem/ordner
```

Der Ordner muss neu oder leer sein und liegt **außerhalb** des Repos. Ergebnis: `hoerer/B?_?.wav` (18 Loops, wird verschickt) und `Schluessel.md` (nicht verschicken; enthält Datei, Inhalt, Gain, Spitze und Pegel im Fenster). Jeder Loop: 4 Takte, 140 BPM, mono, 48 kHz, 24 Bit, `dense`-Kick auf jedem Beat (Bus -6 dB, `listening_test3.build_loop` mit `bpm=140`), Bass-Bus -9 dB plus Angleich-Gain (<= 0; fester Startpegel, kein Lautheitsurteil). Positionen mit festem Seed 361 (`listening_test3.blind_order`), Wiederholung ergibt byte-gleiche Dateien.

Muster (jede Note wird am Slot-Ende mit 3 ms Fade abgeschnitten, nur wenn sie länger ist):

- `offbeat` (B1 bis B3): eine Note je Off-Beat-8tel (Beat b + 0,5), 16 Noten, Slot 1 Beat (428,6 ms).
- `bar` (B4, B5): eine Note je Takt bei Beat 0,5, 4 Noten, Slot 4 Beats.
- `rolling` (B6): Note auf allen 16teln außer den Beat-Positionen (Schritt % 4 = 0), 48 Noten, Slot ein 16tel.

## 2. Inhalt der Blöcke

Alle Renders mit Seed 1 und Ceiling -0,3, Note 28 (E1) soweit nicht anders genannt. Die Presets laufen alle auf Note 28 (sonst unterschiede sich `low` durch die Tonhöhe, nicht nur durch Gate und Preset).

| Block | Dateien (Definitionsreihenfolge, nicht blind) | Frage dahinter |
| --- | --- | --- |
| B1 | `default`, `sub`, `rolling`, `bright`, `low` | Preset-Vergleich |
| B2 | `default`, `default` (**byte-gleiche Kopie, Kontrollpaar**) | Wird „kein Unterschied“ geantwortet? Sonst alle Paar-Antworten dagegen gewichten |
| B3 | Note 28 (E1), 31 (G1), 33 (A1), jeweils `default` | Welche Tonhöhe sitzt zum Kick |
| B4 | `default` mit `drive` 0 und `drive` 0,2, jeweils `gate_ms` 1000 | DC/Wummern (#335) |
| B5 | `default` mit `gate_ms` 120, 250 (Preset), 800 | kurz gegen lang; Wummern-Frage wie B4 |
| B6 | `rolling`, `default`, `sub` im 16tel-Muster | Muster-Treiben |

Hinweis: `default` hat `drive` 0,2 (Vertragsdefault); B4 ist der direkte Vergleich 0 gegen 0,2 bei langen Noten. Die Wummern-Frage in der Hörer-Anleitung ist offen formuliert (ja / nein / weiß nicht je Datei), ohne zu sagen, welche Datei Drive hat. Zahlen aus #335: Mittelwert der Datei mit Drive 0,2 etwa -0,060, ohne Drive 0,0018 (gemessen vom Autor von #334, hier nicht neu gemessen).

## 3. Pegelangleich

Eigenes Maß, nicht das der Kick-Tests: RMS einer **einzelnen Note allein** (float, vor Mix und Quantisierung) über ein stationäres Fenster von 40 % bis 80 % der **kürzesten** `gate_ms` des Blocks, absolutes Fenster gleich für alle Dateien des Blocks (B1: 44 bis 88 ms wegen `rolling` mit 110 ms; B4: 400 bis 800 ms; B5: 48 bis 96 ms; B6: wie B1). Jede Datei wird auf die leiseste des Blocks heruntergezogen. Folgen: In B5 gleicht das Fenster nur den Anfang der langen Note an, nicht ihren Gesamtpegel; in B1 und B6 ist das Fenster kürzer als zwei Perioden der tiefsten Note und ein Kompromiss zwischen Fenstertreue und Gate-Länge. Ob die Dateien gleich laut wirken, ist nicht gemessen und nicht behauptet; die Pegel-Anmerkung des Hörers auswerten.

Gegenprobe (Test `tests/audio_engine/test_listening_test_bass.py`): Datei minus quantisierter Kick-Loop, RMS im selben Fenster ab Notenanfang, drei Slots je Datei; Spreizung im Block unter 0,5 dB. Spitze aller Dateien <= -0,3 dBFS.

## 4. Was der Lead mit den Antworten macht

B2 zuerst. Ein einzelner Durchgang eines Hörers ist ein Hinweis, kein Beweis. Das Ergebnis von B4/B5 entscheidet nur zusammen mit dem Nutzer über #335 (Drive-Default, DC-Blocker); der Test beantwortet nicht, ob das Wummern von DC kommt (Ursache nicht geklärt). Offene Punkte: Kick-Bass-Verhältnis (Bus -6 / -9 dB) ist ein fester Startwert; Live-Schritte im Aufbau nicht in Live geprüft.
