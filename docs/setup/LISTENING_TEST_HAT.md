# Hörtest Hi-Hat (Issue #295)

Nur du kannst sagen, wie die Hi-Hats klingen. Die Zahlen im PR beschreiben nur die Signale. Dauer: etwa 14 Minuten plus 5 Minuten Aufbau. Lies bis zum Ende des Tests nichts anderes zu diesem Test (keine Pläne, nicht `LISTENING_TEST_HAT_LEAD.md`).

## Was du bekommst

Einen Ordner mit 20 WAV-Dateien: `Kick.wav` (der Kick, gegen den du die Hats hörst) und 19 anonyme Hats (`T1_A`, `T1_B`, `T0_A` ...). Es sind **Einzelschläge**, keine Loops. Das Muster baust du einmal selbst (siehe Aufbau).

## Aufbau (einmal, 5 Minuten)

Projekttempo **136 BPM**, nichts auf dem Master, keine Effekte. Zwei Audio-/Instrumentenspuren:

1. **Kick:** `Kick.wav` in einen Simpler (Classic). 1-Takt-MIDI-Clip, Loop an, eine Note auf **jedem Beat** (4 Noten).
2. **Hat:** ein zweiter Simpler mit einem Hat. Einstellung: Voices **1**, Retrigger an, Fade Out ca. 3 ms (falls der Regler da ist), damit der nächste Schlag den vorigen abschneidet. Zwei MIDI-Clips (1 Takt, Loop):
   - **Closed-Clip:** eine Note auf **jedem 16tel** (16 Noten). Gilt für die Blöcke T1, T0, T2, T3, T6.
   - **Open-Clip:** eine Note auf **jedem Off-Beat-8tel** (Positionen 1.1.3, 1.2.3, 1.3.3, 1.4.3, also 4 Noten). Gilt für T4 und T5. Dazu kein Closed-Hat.

Für jede Datei: aus dem Browser auf den Hat-Simpler ziehen (oder Hot-Swap) und den Clip laufen lassen. Hat-Spurfader einmal so stellen, dass der Hat neben dem Kick hörbar, aber nicht dominant ist, und **danach nicht mehr anfassen**. Die Lautheit ist je Block schon angeglichen (gleiche Energie in den ersten 30 ms bei Closed, 100 ms bei Open). Angeglichen heißt nicht gleich laut empfunden: wenn dir eine Datei trotzdem lauter vorkommt, schreib das bei „Anmerkung" dazu.

Hinweis: Die Schritte in Live (Simpler-Einstellungen, Hot-Swap) sind nicht von uns in Live geprüft. Wenn etwas anders heißt oder fehlt, sag es kurz, das Ergebnis des Tests bleibt gültig, solange alle Dateien gleich behandelt werden.

## Reihenfolge und Fragen

Reihenfolge: **T1 → T0 → T2 → T5 → T4 → T3 → T6.** Nach T2 eine Minute Pause. Bei T1, T0, T2, T3 und T6 läuft der Closed-Clip, bei T5 und T4 der Open-Clip.

| # | Frage (eine pro Block) | Antwortmöglichkeiten |
| --- | --- | --- |
| T1 | Hör `T1_A`, dann `T1_B`. **Welche Hi-Hat passt besser zu deinem Kick-Muster?** Wenn die kürzere etwas verliert: was (ein Wort)? | A / B / kein Unterschied · Wort |
| T0 | Gleiche Frage für `T0_A` und `T0_B`: **Welche Hi-Hat sitzt besser?** | A / B / kein Unterschied |
| T2 | Drei Dateien (X, Y, Z). **Welche ist zu dunkel, welche zu hell, welche passt?** | z. B. X dunkel, Y passt, Z hell |
| T5 | **Hat eine der beiden (A, B) etwas, das die andere nicht hat? Wenn ja, welche und was (ein Wort)?** | A / B / kein Unterschied · Wort |
| T4 | Drei Dateien (X, Y, Z). **Sortiere von „mein Open Hat" bis „am wenigsten mein Open Hat".** Danach: **Ist die beste zu lang, richtig oder zu kurz?** | Reihenfolge, z. B. Z > X > Y · zu lang / richtig / zu kurz |
| T3 | Drei Dateien (X, Y, Z). **Sortiere von „mein Hat" bis „am wenigsten mein Hat".** Danach: **Ist die beste zu rauschig, richtig oder zu blechern?** | Reihenfolge · zu rauschig / richtig / zu blechern |
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
Anmerkung (z. B. Pegel, Simpler-Einstellung): ____
```

Schick die ausgefüllte Vorlage ins Issue #295 (oder sag sie dem Lead).

## Paket neu erzeugen (Entwickler)

Der Befehl steht in `docs/setup/LISTENING_TEST_HAT_LEAD.md` (Abschnitt 1), weil die Datei-Tabelle dort den Schlüssel verrät. Das Paket besteht aus Einzelschlägen von `python -m audio_engine.kick --category hat`; es gibt keinen Loop-Generator.
