# Hörtest Rim: Schlüssel und Hinweise für den Lead (Issue #359)

**Erst nach dem Test lesen.** Diese Datei verrät den Aufbau (Kontrollpaar, Inhalt jeder Datei) und darf nicht vor oder während des Hörens zum Hörer gelangen. Die Anleitung für den Hörer ist `docs/setup/LISTENING_TEST_RIM.md`. Hypothesen-Hintergrund: `docs/research/2026-11-02_rim-targets.md` Abschnitt 6 (Skelett; dieses Paket weicht davon ab, siehe unten). Nichts hier ist gehört worden; Zahlen beschreiben nur Signale.

## 1. Paket erzeugen

```bash
python -m audio_engine.listening_test_rim --out /pfad/zu/neuem/ordner
```

Der Ordner muss neu oder leer sein und liegt **außerhalb** des Repos; Engine auf dem Pfad (`PYTHONPATH=src` oder editable install). Ergebnis: `hoerer/R?_?.wav` (18 Loops, wird verschickt) und `Schluessel.md` (nicht verschicken; Dateiname-zu-Inhalt, Gains, Pegel, Klick-Verhältnis). Gleicher Code gibt byte-identische Dateien.

Jeder Loop: 4 Takte, 136 BPM, mono, 48 kHz, 24 Bit; `dense`-Kick auf jedem Beat (Bus -6 dB), geschlossener Hat `closed-std` auf jedem 16tel als Beet (Bus -14 dB; beides aus `listening_test_hat` wiederverwendet), Rim auf jedem Off-Beat-8tel (Bus -8 dB plus Angleich-Gain <= 0; feste Startpegel, kein Lautheitsurteil). Jeder Rim-Schlag wird am nächsten Off-Beat mit 3 ms Fade abgeschnitten, falls länger. Positionen A bis E: SHA-256 mit festem Seed 359 (`listening_test3.blind_order`).

Pegelangleich je Block: RMS des Rims allein über die ersten 60 ms, alle Dateien auf die leiseste des Blocks gezogen. Das ist ein Signalangleich. Das Fenster ist so gewählt, dass es beide Partialtöne des Standard-Rims überdeckt; beim kürzesten Preset (`tight`, 18 ms) liegt ein Teil des Fensters im Nachklang-Rest.

## 2. Blöcke, Fragen, Hypothesen (alles messbare Hypothesen, keine Hörbehauptung)

| Block | Dateien (Rendering) | Frage | Hypothese zum Prüfen |
| --- | --- | --- | --- |
| R1 | die 5 Presets `clave`, `high`, `long`, `rim`, `tight` | Welches ist „mein Rim“; fehlt/zu viel (Wort) | Presets unterscheiden sich für den Hörer; die Wahl setzt einen neuen Standard. Kein Preset gewinnt eindeutig, wenn die Ränge streuen |
| R0 | Kontrollpaar: `rim` zweimal, byte-identisch | Wie oft wird eine Seite gewählt, obwohl kein Unterschied | Antwort ungleich „kein Unterschied“ heißt: Wahl ohne Unterschied, alle anderen Antworten dagegen abwägen |
| R2 | `click_level` 0 ohne Klick; `click_level` 0,6 mit `click_ms` 3 / 1 / 0,2 | Welche haben hörbaren Anschlag; Rang | Der wirksame Klickpegel hängt von `click_ms` ab (0,92 bei 3 ms, 0,80 bei 1 ms, 0,39 bei 0,2 ms, Review PR #330). Erwartung (Hypothese): 3 ms und 1 ms unterscheidbar von ohne Klick; 0,2 ms nicht oder kaum. Gemessen im Schlüssel: Energie über 4 kHz, erste 3 ms zu nächste 30 ms. |
| R3 | Preset `high` (`f1_hz` 900) mit `hp_hz` 200 / 500 / 700 | Rang; Wort zur „Tiefe“ | Mehr `hp_hz` nimmt Energie unter dem Eckwert; Unterschied klein bei 200 vs. 500. Obergrenze: `hp_hz` < 0,8 · `f1_hz` = 720, Wert 700 liegt nahe daran |
| R4 | `rim` mit `f2_ratio` 2 / 3,66 / 5 und `level2` 0 (ein Partialton) | Rang; klingt eine nur noch wie ein Ton | Trägt der zweite Partialton die Identität (RT3 der Rim-Ziele)? Ein Einzelton gewinnt = Clave-Sonderfall genügt |

Abweichung vom Skelett in der Rim-Ziele-Notiz: Statt M1 bis M5 (Tonhöhe, Länge, zweiter Partialton, Klick, Rim gegen Clap) deckt dieses Paket auf Wunsch von Issue #359 die fünf Presets, `click_ms`, `hp_hz` und das Partialverhältnis ab; Tonhöhe, Länge und Rim-gegen-Clap sind nur über die Presets (R1) berührt, nicht einzeln.

## 3. Auswertung

| Antwort | Lesart | Nächster Schritt |
| --- | --- | --- |
| R0 nicht „kein Unterschied“ | Seitenwahl ohne Unterschied | Alle anderen Antworten dagegen abwägen; Paar mit vertauschter Reihenfolge wiederholen |
| R1 klarer Favorit | Preset-Standard verschieben | Presetwert, kein Vertragswechsel |
| R1 „gleich“-Liste enthält Presets | Presets zu ähnlich | Presets zusammenlegen oder weiter auseinander ziehen (Issue) |
| R2: nur 3 und 1 ms hörbar | `click_ms` unter etwa 1 ms ohne Wirkung | Untere Grenze von `click_ms` im Vertrag prüfen (eigener Issue) |
| R2: 0,2 ms hörbar | Wirksamer Pegel 0,39 reicht | Kein Handlungsbedarf |
| R3: kein Unterschied | `hp_hz` im erlaubten Bereich nahe `f1_hz` zu schwach | Feld nicht weiter ausbauen |
| R4: Einzelton gewählt oder „klingt wie ein Rim“ | Zweiter Partialton ist nicht nötig | `level2` Standard prüfen |
| R4: Einzelton „nur ein Ton“ | Zweiter Partialton trägt die Identität | Standard behalten; gewähltes Verhältnis messen |

Gesamtfrage am Ende („Welche Datei ist mein Rim?“): Schlüssel öffnen und Parameter der Datei als neuen Preset-Vorschlag notieren (nicht als Standard übernehmen ohne Lead-Entscheid).

## 4. Grenzen

- Nicht in Live geprüft; das Paket wurde nur erzeugt und vermessen (Tests in `tests/audio_engine/test_listening_test_rim.py`).
- Der Pegelangleich gleicht RMS in 60 ms an. Er macht die Dateien nicht gleich laut empfunden; bei Antworten zu „lauter“ gilt die Anmerkung des Hörers.
- Die Rim-Werte sind Platzhalter aus der Rim-Ziele-Notiz (keine Messung an echten Rims).
