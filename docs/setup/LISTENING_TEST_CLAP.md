# Hörtest Clap (Issue #232)

Nur du kannst sagen, wie die Claps klingen. Die Zahlen im PR beschreiben nur die Signale. Dauer: etwa 12 Minuten plus 2 Minuten Aufbau. Lies bis zum Ende des Tests nichts anderes zu diesem Test (keine Pläne, kein `Schluessel.md`).

## Aufbau (einmal, 2 Minuten)

Alle `*.wav` des Pakets in eine Audiospur laden, Warp aus, Projekttempo **136 BPM**, jede Datei als Loop. Gleiche Lautstärke an der Spur, nichts auf dem Master. Die Dateinamen sind anonym (`C1_A`, `C1_B` ...).

Jede Datei ist ein Loop über 4 Takte: der dichte Kick (`dense`) auf **jedem Beat**, die Clap auf **Beat 2 und 4**. Du hörst also immer das Muster, in dem die Clap später sitzen soll, nicht die Clap allein. Die Lautheit der Clap ist je Item schon angeglichen: Fader nicht anfassen. Angeglichen heißt nicht gleich laut empfunden: wenn dir eine Datei trotzdem lauter vorkommt, schreib das bei „Anmerkung" dazu.

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

„Kein Unterschied" ist bei jeder Frage mit zwei Dateien eine gültige und nützliche Antwort.

## Auswertungsvorlage

```
Test Clap, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Pegel gleich gelassen: ja / nein
C1: ___   Verlust (Wort): ____
C0: ___
C4: ___   (hilft / stört / kein Unterschied)   Datei: ___
C5: ___   Wort: ____
C3: dunkel ___ ; hell ___ ; passt ___
C2: Reihenfolge ___ > ___ > ___    beste: zu verschmiert / richtig / zu hart
C6: gleiche Clap: ___ ; fällt raus: ___
Gesamt: Welche Datei des ganzen Tests ist „meine Clap"? ____ (oder „keine")
Anmerkung (z. B. Pegel): ____
```

Schick die ausgefüllte Vorlage ins Issue #232 (oder sag sie dem Lead). Erst danach `Schluessel.md` öffnen, falls du magst.

## Paket neu erzeugen (Entwickler)

```
python -m audio_engine.listening_test_clap --out <neuer, leerer Ordner außerhalb des Repos>
```

Schreibt `<Ordner>/package/` (18 WAVs plus Schlüsseldatei, das wird verschickt). Gleicher Code gibt byte-gleiche Dateien. Keine Audiodateien ins Repo committen. Für den Lead: `docs/setup/LISTENING_TEST_CLAP_LEAD.md`, erst nach dem Test lesen.
