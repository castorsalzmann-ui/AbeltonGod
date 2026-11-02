# Hörtest Snare (Issue #316)

Nur du kannst sagen, wie die Snares klingen. Die Zahlen im PR beschreiben nur die Signale. Dauer: etwa 14 Minuten plus 5 Minuten Aufbau. Lies bis zum Ende des Tests nichts anderes zu diesem Test (keine Pläne, nicht `LISTENING_TEST_SNARE_LEAD.md`, nicht die PR-Beschreibung von #312).

## Was du bekommst

Einen Ordner mit 19 WAV-Dateien: `Kick.wav` (der Kick für den Kontext) und 18 anonyme Snares: `A1` bis `A6`, `B1` bis `B4`, `C1` bis `C4`, `D1` bis `D4`. Es sind **Einzelschläge**, keine Loops. Die Zahlen in den Namen sind gemischt und bedeuten nichts.

## Aufbau (einmal, 5 Minuten)

Projekttempo **136 BPM**, nichts auf dem Master, keine Effekte. Zwei Spuren mit je einem Simpler (Classic):

1. **Kick:** `Kick.wav`, 1-Takt-MIDI-Clip, Loop an, eine Note auf **jedem Beat** (4 Noten).
2. **Snare:** ein zweiter Simpler. Voices **1**, Retrigger an, Warp aus. Ein MIDI-Clip (1 Takt, Loop) mit je einer Note auf **Beat 2 und Beat 4** (Positionen 1.2.1 und 1.4.1).

Bei „einzeln hören" ist die Kick-Spur stumm, du spielst eine Note oder klickst die Datei im Browser an. Bei „mit Kick" läuft das Kick-Muster und der Snare-Clip. Fader der Snare-Spur einmal so stellen, dass die Snare neben dem Kick hörbar, aber nicht dominant ist, und **danach nicht mehr anfassen**. Alle Dateien sind auf gleiche Energie angeglichen. Angeglichen heißt nicht gleich laut empfunden: wenn dir eine Datei trotzdem lauter oder leiser vorkommt, schreib das bei „Anmerkung" dazu.

Hinweis: Die Schritte in Live (Simpler-Einstellungen, Vorhören) sind nicht von uns in Live geprüft. Wenn etwas anders heißt oder fehlt, sag es kurz; das Ergebnis bleibt gültig, solange alle Dateien gleich behandelt werden.

## Teil 1: einzeln hören, `A1` bis `A6` in dieser Reihenfolge (ca. 5 Minuten)

Jede Datei zweimal anspielen. Pro Datei:

| Frage | Antwort |
| --- | --- |
| a) **Wie nah ist das an deiner Snare?** | 1 (genau meine) bis 5 (gar nicht meine) |
| b) **Ein Wort dazu** | frei |

Danach:

- **Welche Dateien klingen für dich gleich?** (Liste, oder „keine")
- **Welche eine Datei würdest du in einem Projekt benutzen?** (oder „keine")

## Teil 2: mit dem Kick, `A1` bis `A6` (ca. 3 Minuten)

Kick-Muster und Snare-Clip laufen lassen, pro Datei etwa zwei Takte. Pro Datei:

| Frage | Antwort |
| --- | --- |
| **Passt die Snare zu diesem Kick?** | ja / ein bisschen / nein |

## Teil 3: vier Blöcke mit je vier Dateien, `B`, `C`, `D` (ca. 6 Minuten)

Pro Block (`B1` bis `B4`, dann `C1` bis `C4`, dann `D1` bis `D4`) hörst du alle vier einzeln, so oft du willst, ohne Kick. Pro Block:

- **Sortiere von „meine Snare" bis „am wenigsten meine Snare".**
- **Fehlt der besten etwas, oder hat sie zu viel von etwas? Ein Wort** (oder „nein").
- **Welche Dateien in diesem Block klingen für dich gleich?** (Liste, oder „keine")

„Kein Unterschied" und „weiß nicht" sind bei jeder Frage gültige und nützliche Antworten.

## Auswertungsvorlage

```
Test Snare, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Fader nicht angefasst: ja / nein
Teil 1 (a Nähe 1-5 / b Wort):
A1: _ / ____   A2: _ / ____   A3: _ / ____
A4: _ / ____   A5: _ / ____   A6: _ / ____
Gleich klingende Dateien: ____
Eine fürs Projekt: ____
Teil 2 (passt: ja / ein bisschen / nein):
A1: ___   A2: ___   A3: ___   A4: ___   A5: ___   A6: ___
Teil 3:
B: Reihenfolge ___ > ___ > ___ > ___   beste fehlt/zu viel (Wort): ____   gleich: ____
C: Reihenfolge ___ > ___ > ___ > ___   beste fehlt/zu viel (Wort): ____   gleich: ____
D: Reihenfolge ___ > ___ > ___ > ___   beste fehlt/zu viel (Wort): ____   gleich: ____
Gesamt: Welche Datei des ganzen Tests ist „meine Snare"? ____ (oder „keine")
Anmerkung (z. B. Pegel, Simpler-Einstellung): ____
```

Schick die ausgefüllte Vorlage ins Issue #316 (oder sag sie dem Lead).

## Paket neu erzeugen (Entwickler)

Der Befehl steht in `docs/setup/LISTENING_TEST_SNARE_LEAD.md` (Abschnitt 1), weil die Datei-Tabelle dort den Schlüssel verrät.
