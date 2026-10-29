# Kick erzeugen, in den Projektordner legen und in Live importieren (Phase 03, Issue #129)

Noch **nicht auf deinem Rechner geprüft.** Ein Befehl macht drei Schritte:

1. erzeugt einen Kick aus einem Preset (wie `python -m audio_engine.kick --preset …`, gleicher Dateiname `<preset>_s<seed>_v0.wav`),
2. legt WAV + Sidecar (`.json`) in `<Projektordner>\Samples\Drums\Kicks\` ab. Eine vorhandene Datei wird **nie** überschrieben; ein zweiter Lauf schreibt `…_v0_002.wav`,
3. importiert genau diese Datei in Live, mit demselben Ablauf wie `scripts/live_import.py` 0.3.0 (Abschnitt 7.2 in `ABLETONOSC_WINDOWS.md`): Test-Set-Frage, Ziel, Plan, Bestätigung, Zurücklesen, Undo-Frage **vor** dem Anhören.

Voraussetzung: die AbeltonGod-Erweiterung ist installiert (`ABLETONOSC_WINDOWS.md`, Abschnitt 7.1) und Live hat das **Test-Set** offen.

## Projektordner finden

Der Projektordner ist der Ordner, in dem die `.als`-Datei deines Test-Sets liegt (Live legt beim ersten Speichern einen Ordner `<Name> Project` an). Suchen in PowerShell:

```powershell
Get-ChildItem "$env:USERPROFILE\Music", "$env:USERPROFILE\Documents" -Recurse -Filter *.als -ErrorAction SilentlyContinue | Select-Object FullName
```

Liegt dort keine `.als`-Datei, sagt das Script `Hinweis: In … liegt keine .als-Datei.` und macht trotzdem weiter.

## Aufruf

```powershell
python scripts/kick_to_live.py --preset dense --project "C:\voller\Pfad\Test Project"
```

Weitere Optionen: `--seed <Zahl>`, `--set FELD=WERT` (mehrfach, wie beim Kick-CLI), `--slot <Zelle>`.

## Was du siehst

Zuerst (vor jeder Frage):

```text
AbeltonGod kick_to_live 0.1.0 (Import wie live_import 0.3.0)

Kick: Preset dense, Seed 1001
Schreibe WAV + Sidecar nach:
  C:\voller\Pfad\Test Project\Samples\Drums\Kicks
(vorhandene Dateien werden nie überschrieben; neue Datei bekommt dann _002 ...)
Geschrieben:
  C:\voller\Pfad\Test Project\Samples\Drums\Kicks\dense_s1001_v0.wav
  C:\voller\Pfad\Test Project\Samples\Drums\Kicks\dense_s1001_v0.json
```

Danach dieselben Fragen und Meldungen wie bei `live_import.py`. Am Ende steht immer eine **Zusammenfassung**: ob ein Clip in Live ist, und wo die Kick-Datei liegt. Die Dateien bleiben in jedem Fall im Projektordner, auch nach einem Undo (Lives Undo betrifft keine Dateien); das Script löscht nichts. Ist kein Clip in Live (Nein bei einer Frage, Live geschlossen, Erweiterung fehlt, Undo), steht dort auch, wie du die WAV von Hand in Live ziehst (`SAMPLE_IMPORT_FALLBACK.md`).

Im Ergebnis-Block (in **Issue #129** einfügen) stehen zusätzlich zu den `live_import`-Zeilen: `kick_written`, `kick_wav`, `kick_sidecar` und `kick_in_live` mit einem dieser Werte:

| `kick_in_live` | Bedeutung |
| --- | --- |
| `none (nothing sent to Live)` | nichts an Live gesendet |
| `in Live (track <n>, slot <z>)` | Clip ist im Set (kein Undo) |
| `removed by undo (read back)` | Clip per Undo entfernt, zurückgelesen |
| `removed by undo (read back; track names not restored)` | wie oben, aber ein Spurname ist nicht wie vorher |
| `unknown (see the messages above)` | Zeitüberschreitung, verweigertes oder ungeklärtes Undo, *Strg + C* während des Undo: bitte in Live nachsehen |

## Fehler vor Live

| Fall | Erwartet |
| --- | --- |
| unbekanntes Preset oder ungültiger `--set`-Wert | `FEHLER in den Kick-Werten: …`, nichts geschrieben, nichts gesendet, Exit-Code 4 |
| Projektordner gibt es nicht | `FEHLER: Den Projektordner gibt es nicht: …`, Exit-Code 4 (der Ordner wird nicht angelegt) |
| Pfad zu lang (Windows MAX_PATH) | Meldung mit `MAX_PATH`, nichts geschrieben, Exit-Code 4 |
| Schreiben fehlgeschlagen (Platte voll …) | `FEHLER beim Schreiben: …`, Exit-Code 6 |
| *Strg + C* während des Erzeugens | `ABGEBROCHEN mit Strg+C beim Erzeugen des Kicks …`, Exit-Code 130 |
