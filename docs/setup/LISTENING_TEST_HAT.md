# Hörtest Hi-Hat (Issue #295)

Nur du kannst sagen, wie die Hi-Hats klingen. Die Zahlen im PR beschreiben nur die Signale. Dauer: etwa 14 Minuten plus 2 Minuten Aufbau. Lies bis zum Ende des Tests nichts anderes zu diesem Test (keine Pläne, keine anderen Dokumente zu diesem Test).

## Was du bekommst

Einen Ordner `hoerer/` mit **19 anonymen Loops** (`T0_A` ... `T6_D`). Jede Datei ist ein fertiger Loop: 4 Takte, 136 BPM, Kick auf jedem Beat plus Hi-Hat. In den Blöcken T1, T0, T2, T3, T6 läuft die Hat auf **jedem 16tel**, in T5 und T4 ist es eine **offene Hat auf jedem Off-Beat-8tel** (ohne Closed-Hat). Jeder Hat-Schlag wird vom nächsten abgeschnitten (3 ms Fade), das steckt in der Datei. Pegel und Muster sind fest; du baust nichts.

## Aufbau (2 Minuten)

Projekttempo **136 BPM**, nichts auf dem Master, keine Effekte. Alle Dateien auf **eine** Audiospur nacheinander oder auf getrennte Spuren ziehen, **Warp aus** (die Loops haben das Tempo schon), Loop-Klammer um die 4 Takte (Länge 16 Beats). Den Spurfader einmal einstellen und **danach nicht mehr anfassen**. Die Hat ist je Block schon auf gleiche Energie angeglichen (gleiche RMS in den ersten 30 ms bei Closed, 100 ms bei Open). Angeglichen heißt nicht gleich laut empfunden: wenn dir eine Datei trotzdem lauter vorkommt, schreib das bei „Anmerkung“ dazu.

Hinweis: Das Laden und Loopen in Live ist von uns nicht in Live geprüft. Wenn etwas anders heißt oder fehlt, sag es kurz; das Ergebnis bleibt gültig, solange alle Dateien gleich behandelt werden.

## Reihenfolge und Fragen

Reihenfolge: **T1 → T0 → T2 → T5 → T4 → T3 → T6.** Nach T2 eine Minute Pause. Bei T1, T0, T2, T3 und T6 spielt die Hat auf jedem 16tel, bei T5 und T4 auf jedem Off-Beat-8tel.

| # | Frage (eine pro Block) | Antwortmöglichkeiten |
| --- | --- | --- |
| T1 | Hör `T1_A`, dann `T1_B`. **Welche Hi-Hat passt besser zu deinem Kick-Muster?** Wenn eine der beiden etwas verliert: was (ein Wort)? | A / B / kein Unterschied · Wort |
| T0 | Gleiche Frage für `T0_A` und `T0_B`: **Welche Hi-Hat sitzt besser?** | A / B / kein Unterschied |
| T2 | Drei Dateien (A, B, C). **Welche ist zu dunkel, welche zu hell, welche passt?** | z. B. A dunkel, B passt, C hell |
| T5 | **Hat eine der beiden (A, B) etwas, das die andere nicht hat? Wenn ja, welche und was (ein Wort)?** | A / B / kein Unterschied · Wort |
| T4 | Drei Dateien (A, B, C). **Sortiere von „mein Open Hat" bis „am wenigsten mein Open Hat".** Danach: **Ist die beste zu lang, richtig oder zu kurz?** | Reihenfolge, z. B. C > A > B · zu lang / richtig / zu kurz |
| T3 | Drei Dateien (A, B, C). **Sortiere von „mein Hat" bis „am wenigsten mein Hat".** Danach: **Ist die beste zu rauschig, richtig oder zu blechern?** | Reihenfolge · zu rauschig / richtig / zu blechern |
| T6 | Vier Dateien (A bis D). **Welche klingen für dich wie dieselbe Hi-Hat? Welche fällt raus (wenn eine rausfällt)?** | Liste |

„Kein Unterschied" ist bei jeder Frage mit zwei Dateien eine gültige und nützliche Antwort.

## Auswertungsvorlage

```
Test Hat, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Pegel gleich gelassen: ja / nein
T1: ___   Verlust (Wort): ____
T0: ___
T2: dunkel ___ ; hell ___ ; passt ___
T5: ___   Wort: ____
T4: Reihenfolge ___ > ___ > ___    beste: zu lang / richtig / zu kurz
T3: Reihenfolge ___ > ___ > ___    beste: zu rauschig / richtig / zu blechern
T6: gleiche Hi-Hat: ___ ; fällt raus: ___
Gesamt: Welche Datei des ganzen Tests ist „meine Hi-Hat"? ____ (oder „keine")
Anmerkung (z. B. Pegel): ____
```

Schick die ausgefüllte Vorlage ins Issue #295 (oder sag sie dem Lead).
