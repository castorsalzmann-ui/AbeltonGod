# Hörtest Clap (Issue #232)

Nur du kannst sagen, wie die Claps klingen. Die Zahlen im PR beschreiben nur die Signale. Dauer: etwa 12 Minuten plus 2 Minuten Aufbau. Plan: `docs/research/2026-11-02_clap-targets-and-listening-plan.md` (Abschnitt 5), Parameterwerte: Startsätze S/L/B aus `docs/research/2026-11-02_clap-reference-analysis.md`.

## Aufbau (einmal, 2 Minuten)

Alle `*.wav` des Pakets in eine Audiospur laden, Warp aus, Projekttempo **136 BPM**, jede Datei als Loop. Gleiche Lautstärke an der Spur, nichts auf dem Master. Die Dateinamen sind anonym (`C1_A`, `C1_B` ...). `Schluessel.md` erst nach dem Test öffnen.

Jede Datei ist ein Loop über 4 Takte: der dichte Kick (`dense`) auf **jedem Beat**, die Clap auf **Beat 2 und 4**. Du hörst also immer das Muster, in dem die Clap später sitzen soll, nicht die Clap allein. Die Lautheit der Clap ist je Item schon angeglichen (RMS über die ersten 60 ms der Clap): Fader nicht anfassen. Angeglichen heißt nicht gleich laut empfunden: wenn dir eine Datei trotzdem lauter vorkommt, schreib das bei „Anmerkung" dazu.

## Reihenfolge und Fragen

Reihenfolge: **C1 → C0 → C4 → C5 → C3 → C2 → C6.** Nach C3 eine Minute Pause.

| # | Frage (eine pro Item) | Antwortmöglichkeiten |
| --- | --- | --- |
| C1 | Hör `C1_A`, dann `C1_B`. **Welche Clap passt besser zu deinem Kick-Muster?** Wenn die kürzere etwas verliert: was (ein Wort)? | A / B / kein Unterschied · Wort |
| C0 | Gleiche Frage für `C0_A` und `C0_B`: **Welche Clap sitzt besser?** | A / B / kein Unterschied |
| C4 | **Hilft der Raum, oder stört er den nächsten Kick?** | hilft / stört / kein Unterschied (welche Datei: A / B) |
| C5 | **Hat eine der beiden etwas, das die andere nicht hat? Wenn ja, welche und was (ein Wort)?** | A / B / kein Unterschied · Wort |
| C3 | Drei Dateien (A, B, C). **Welche ist zu dunkel, welche zu hell, welche passt?** | z. B. A dunkel, B passt, C hell |
| C2 | Drei Dateien. **Sortiere von „mein Clap" bis „am wenigsten mein Clap".** Danach: **Ist die beste zu verschmiert, richtig oder zu hart?** | Reihenfolge, z. B. B > A > C · zu verschmiert / richtig / zu hart |
| C6 | Vier Dateien (A bis D). **Welche klingen für dich wie dieselbe Clap? Welche fällt raus (wenn eine rausfällt)?** | Liste |

„Kein Unterschied" ist eine gültige und nützliche Antwort. C0 ist absichtlich zweimal dieselbe Datei: es zeigt, ob du ohne Unterschied eine Seite wählst.

## Auswertungsvorlage

```
Test Clap, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Pegel gleich gelassen: ja / nein
C1: ___   Verlust (Wort): ____
C0: ___   (A=B identisch; war die Antwort „kein Unterschied"?  ja / nein)
C4: ___   (hilft / stört / kein Unterschied)   Datei: ___
C5: ___   Wort: ____
C3: dunkel ___ ; hell ___ ; passt ___
C2: Reihenfolge ___ > ___ > ___    beste: zu verschmiert / richtig / zu hart
C6: gleiche Clap: ___ ; fällt raus: ___
Gesamt: Welche Datei des ganzen Tests ist „meine Clap"? ____ (oder „keine")
Anmerkung (z. B. Pegel): ____
```

Schick die ausgefüllte Vorlage ins Issue #232 (oder sag sie dem Lead). Dann erst `Schluessel.md` öffnen, falls du magst.

## Was der Lead mit den Antworten macht

Der Lead entschlüsselt die Antworten mit `Schluessel.md` (Datei → Render, Gain, Messwerte) und liest sie so:

- **C0 nicht „kein Unterschied":** du wählst eine Seite ohne Unterschied. Alle Paarantworten werden dagegen gewichtet, das Paar wird vertauscht wiederholt, bevor darauf gebaut wird.
- **C1:** lang bevorzugt oder kurz verliert ein Wort: Länge zählt für dich, das Wort benennt, was gemessen wird. Kurz bevorzugt ohne Verlust: kurz bleibt Standard, lang bleibt Option.
- **C2 / C3:** weicht dein Favorit von 4 Bursts bzw. `bp_hz` 1200 ab, wird ein neues Preset mit dem Nachbarwert gebaut (innerhalb des Vertrags).
- **C4:** „hilft": Kandidat-Preset mit `room` 0.4. Sonst bleibt `room` eine Option.
- **C5:** „hat mehr" mit Wort: Vorschlag für ein Layer-Feld (eigenes Contract-Change-Issue). „kein Unterschied": kein Feld nötig.
- **C6:** fällt eine Variante raus, wird die Streuung der Varianten für dieses Preset begrenzt.

Ein einzelner Durchgang eines Hörers ist ein Hinweis, kein Beweis.

## Abweichungen vom Plan

Die Startsätze S/L haben 4 Bursts und 10 ms Abstand (der Plan ging von 3 und 8 aus). Darum vergleicht C2 `bursts` 1 / 4 / 6 und C3 `bp_hz` 800 / 1200 / 2000 (jeweils mit der Mitte als „T", dem Preset `short`). Die breite Clap in C5 nutzt Seed 2 und die Werte der Spalte „Layered" des Plans.

## Paket neu erzeugen (Entwickler)

```
python -m audio_engine.listening_test_clap --out <neuer, leerer Ordner außerhalb des Repos>
```

Schreibt `<Ordner>/package/` (18 WAVs und `Schluessel.md`, das wird verschickt). Gleicher Code gibt byte-gleiche Dateien. Keine Audiodateien ins Repo committen.
