# Hörtest Clap (Issue #309)

Nur du kannst sagen, wie die Claps klingen. Die Zahlen im PR beschreiben nur die Signale. Dauer: etwa 14 Minuten plus 5 Minuten Aufbau. Lies bis zum Ende des Tests nichts anderes zu diesem Test (keine Pläne, nicht `LISTENING_TEST_CLAP_XTREME_LEAD.md`, nicht die PR-Beschreibung von #305).

## Was du bekommst

Einen Ordner mit 14 WAV-Dateien: `Kick.wav` (der Kick für Teil 3) und 13 anonyme Claps: `A1` bis `A9` und `B1` bis `B4`. Es sind **Einzelschläge**, keine Loops. Die Zahlen in den Namen sind gemischt und bedeuten nichts.

## Aufbau (einmal, 5 Minuten)

Projekttempo **136 BPM**, nichts auf dem Master, keine Effekte. Zwei Spuren mit je einem Simpler (Classic):

1. **Kick:** `Kick.wav`, 1-Takt-MIDI-Clip, Loop an, eine Note auf **jedem Beat** (4 Noten).
2. **Clap:** ein zweiter Simpler. Voices **1**, Retrigger an, Warp aus. Ein MIDI-Clip (1 Takt, Loop) mit je einer Note auf **Beat 2 und Beat 4** (Positionen 1.2.1 und 1.4.1).

Teil 1 und 2 hörst du **einzeln** (Datei im Browser anklicken oder auf den Clap-Simpler ziehen und eine Note spielen, Kick-Spur stumm). Teil 3 mit dem Kick-Muster. Fader der Clap-Spur einmal so stellen, dass der Clap neben dem Kick hörbar, aber nicht dominant ist, und **danach nicht mehr anfassen**. Die Dateien sind je Teil auf gleiche Energie angeglichen. Angeglichen heißt nicht gleich laut empfunden: wenn dir eine Datei trotzdem lauter oder leiser vorkommt, schreib das bei „Anmerkung" dazu.

Hinweis: Die Schritte in Live (Simpler-Einstellungen, Vorhören) sind nicht von uns in Live geprüft. Wenn etwas anders heißt oder fehlt, sag es kurz; das Ergebnis bleibt gültig, solange alle Dateien gleich behandelt werden.

## Teil 1: einzeln hören, `A1` bis `A9` in dieser Reihenfolge (ca. 6 Minuten)

Jede Datei zweimal anspielen. Pro Datei drei Antworten:

| Frage | Antwort |
| --- | --- |
| a) **Wie weit ist das von einem normalen Clap?** | 1 (normaler Clap) bis 5 (kein Clap mehr) |
| b) **Knackt, klickt oder bricht etwas ab?** | nein / am Anfang / mittendrin / am Ende |
| c) **Ein Wort dazu** | frei |

Danach, ohne weiteres Hören nötig oder mit kurzem Nachhören:

- **Welche Dateien klingen für dich gleich?** (Liste, oder „keine")
- **Welche drei möchtest du in einem Projekt benutzen, und wofür (ein Wort pro Datei)?** Wenn keine: „keine".

## Teil 2: vier Dateien, `B1` bis `B4` (ca. 3 Minuten)

Hör alle vier einzeln, so oft du willst.

- **Sortiere von „am wenigsten verfremdet" bis „am stärksten verfremdet".**
- **Klingen zwei Dateien, die in deiner Reihenfolge nebeneinander stehen, wie ein Sprung statt wie ein gleichmäßiger Schritt? Welche zwei?** (oder „keinen Sprung")

## Teil 3: mit dem Kick, `A1` bis `A9` (ca. 5 Minuten)

Kick-Muster und Clap-Clip laufen lassen, pro Datei etwa zwei Takte. Pro Datei:

| Frage | Antwort |
| --- | --- |
| **Passt der Clap zu diesem Kick?** | ja / ein bisschen / nein |
| **Wirkt das Timing seltsam (zu früh, zu spät)?** | nein / ja (Wort) |

„Kein Unterschied" und „weiß nicht" sind bei jeder Frage gültige und nützliche Antworten.

## Auswertungsvorlage

```
Test Clap, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Fader nicht angefasst: ja / nein
Teil 1 (a Entfernung 1-5 / b Knacken: nein, Anfang, mittendrin, Ende / c Wort):
A1: _ / _ / ____    A2: _ / _ / ____    A3: _ / _ / ____
A4: _ / _ / ____    A5: _ / _ / ____    A6: _ / _ / ____
A7: _ / _ / ____    A8: _ / _ / ____    A9: _ / _ / ____
Gleich klingende Dateien: ____
Drei fürs Projekt (Datei, Wofür): ____ ; ____ ; ____
Teil 2: Reihenfolge ___ < ___ < ___ < ___ (wenig bis stark verfremdet)   Sprung zwischen: ___ und ___ / keiner
Teil 3 (passt: ja / ein bisschen / nein ; Timing seltsam: nein / ja Wort):
A1: ___ ; ___   A2: ___ ; ___   A3: ___ ; ___   A4: ___ ; ___   A5: ___ ; ___
A6: ___ ; ___   A7: ___ ; ___   A8: ___ ; ___   A9: ___ ; ___
Anmerkung (z. B. Pegel, Simpler-Einstellung): ____
```

Schick die ausgefüllte Vorlage ins Issue #309 (oder sag sie dem Lead).

## Paket neu erzeugen (Entwickler)

Der Befehl steht in `docs/setup/LISTENING_TEST_CLAP_XTREME_LEAD.md` (Abschnitt 1), weil die Datei-Tabelle dort den Schlüssel verrät.
