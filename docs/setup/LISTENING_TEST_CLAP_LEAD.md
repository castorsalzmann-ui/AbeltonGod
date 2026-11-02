# Hörtest Clap: Hinweise für den Lead (Issue #232)

**Erst nach dem Test lesen.** Diese Datei verrät den Aufbau (Kontrollpaar, Inhalt der Dateien) und darf nicht vor oder während des Hörens zum Hörer gelangen. Die Anleitung für den Hörer ist `docs/setup/LISTENING_TEST_CLAP.md`.

## Kontrollpaar

C0 ist absichtlich zweimal dieselbe Datei (byte-gleich). Es zeigt, ob der Hörer ohne Unterschied eine Seite wählt. In der Auswertungsvorlage des Hörers steht deshalb nur „C0: ___"; der Lead notiert selbst, ob die Antwort „kein Unterschied" war.

## Was der Lead mit den Antworten macht

Der Lead entschlüsselt die Antworten mit `Schluessel.md` (Datei → Render, Gain, Messwerte) und liest sie so:

- **C0 nicht „kein Unterschied":** der Hörer wählt eine Seite ohne Unterschied. Alle Paarantworten werden dagegen gewichtet, das Paar wird vertauscht wiederholt, bevor darauf gebaut wird.
- **C1:** lang bevorzugt oder kurz verliert ein Wort: Länge zählt für den Hörer, das Wort benennt, was gemessen wird. Kurz bevorzugt ohne Verlust: kurz bleibt Standard, lang bleibt Option.
- **C2 / C3:** weicht der Favorit von 4 Bursts bzw. `bp_hz` 1200 ab, wird ein neues Preset mit dem Nachbarwert gebaut (innerhalb des Vertrags).
- **C4:** „hilft": Kandidat-Preset mit `room` 0.4. Sonst bleibt `room` eine Option.
- **C5:** „hat mehr" mit Wort: Vorschlag für ein Layer-Feld (eigenes Contract-Change-Issue). „kein Unterschied": kein Feld nötig.
- **C6:** fällt eine Variante raus, wird die Streuung der Varianten für dieses Preset begrenzt.

Ein einzelner Durchgang eines Hörers ist ein Hinweis, kein Beweis. Auch die Pegel-Anmerkung des Hörers auswerten: Der Angleich ist RMS über die ersten 60 ms der Clap allein, nicht empfundene Lautheit.

## Abweichungen vom Plan

Plan: `docs/research/2026-11-02_clap-targets-and-listening-plan.md` Abschnitt 5, Startsätze: `docs/research/2026-11-02_clap-reference-analysis.md`.

Die Startsätze S/L haben 4 Bursts und 10 ms Abstand (der Plan ging von 3 und 8 aus). Darum vergleicht C2 `bursts` 1 / 4 / 6 und C3 `bp_hz` 800 / 1200 / 2000 (jeweils mit der Mitte als „T", dem Preset `short`). Die breite Clap in C5 nutzt Seed 2 und die Werte der Spalte „Layered" des Plans. Kick- und Clap-Bus: -6 / -11 dB.
