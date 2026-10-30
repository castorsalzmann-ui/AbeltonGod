# Kick erzeugen, in den Projektordner legen und in Live importieren (Phase 03, Issue #129)

Noch **nicht auf deinem Rechner geprüft.** Ein Befehl macht drei Schritte:

1. erzeugt einen Kick aus einem Preset (wie `python -m audio_engine.kick --preset …`, gleicher Dateiname `<preset>_s<seed>_v0.wav`),
2. legt WAV + Sidecar (`.json`) in `<Projektordner>\Samples\Drums\Kicks\` ab. Eine vorhandene Datei wird **nie** überschrieben; ein zweiter Lauf schreibt `…_v0_002.wav`,
3. importiert genau diese Datei in Live, mit demselben Ablauf wie `scripts/live_import.py` 0.4.0 (Abschnitt 7.2 in `ABLETONOSC_WINDOWS.md`): Test-Set-Frage, Ziel, Plan, Bestätigung, Zurücklesen, Undo-Frage **vor** dem Anhören.

Voraussetzung: die AbeltonGod-Erweiterung ist installiert (`ABLETONOSC_WINDOWS.md`, Abschnitt 7.1) und Live hat das **Test-Set** offen.

## Projektordner finden

Der Projektordner ist der Ordner, in dem die `.als`-Datei deines Test-Sets liegt (Live legt beim ersten Speichern einen Ordner `<Name> Project` an). Suchen in PowerShell (liest nur, ändert nichts):

```powershell
Get-ChildItem "$env:USERPROFILE\Music", "$env:USERPROFILE\Documents" -Recurse -Filter *.als -ErrorAction SilentlyContinue | Select-Object FullName
```

- Treffer unter `...\Backup\` sind Lives Sicherungskopien, **nicht** der Projektordner. Nimm den Ordner darüber (dort liegt die `.als`-Datei ohne Datum im Namen).
- **Findet die Suche dein Test-Set nicht** (es wurde nie gespeichert): in Live **Datei → Live-Set speichern unter …** (englisch *File → Save Live Set As…*), z. B. in `Musik\AbeltonGod-Test` unter dem Namen `AbeltonGod-Test`. Live legt dann den Ordner `AbeltonGod-Test Project` mit `AbeltonGod-Test.als` darin an. Diesen Ordner als `--project` nehmen. (Die genauen Menünamen sind hier nicht gegen das Handbuch oder deine Oberfläche geprüft; gemeint ist „Speichern unter“ für das Live-Set.)

Das Script nimmt nur einen **vollen Pfad** zu einem **vorhandenen Ordner mit einer `.als`-Datei direkt darin**. Es lehnt ab (und schreibt nichts): leeres `--project`, einen relativen Pfad, einen `Backup`-Ordner, einen Ordner ohne `.als`-Datei und jeden Ordner im AbeltonGod-Ordner selbst.

## Aufruf

```powershell
python scripts/kick_to_live.py --preset dense --project "C:\voller\Pfad\Test Project"
```

Weitere Optionen: `--seed <Zahl>`, `--set FELD=WERT` (mehrfach, wie beim Kick-CLI), `--slot <Zelle>`.

## Was du siehst

Zuerst (vor jeder Frage):

```text
AbeltonGod kick_to_live 0.1.0 (Import wie live_import 0.4.0)

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
| `unknown (see the messages above)` | Zeitüberschreitung, die das Zurücklesen nicht klären konnte (siehe „Späte Bestätigung“ in `ABLETONOSC_WINDOWS.md` Abschnitt 7.2), Verbindung nach der Bestätigung verloren, *Strg + C* während des Imports oder des Undo, verweigertes oder ungeklärtes Undo: **erst in Live nachsehen** |

## Fehler vor Live

| Fall | Erwartet |
| --- | --- |
| unbekanntes Preset oder ungültiger `--set`-Wert | `FEHLER in den Kick-Werten: …`, nichts geschrieben, nichts gesendet, Exit-Code 4 |
| Projektordner abgelehnt (leer, relativ, gibt es nicht, keine `.als`, `Backup`, im AbeltonGod-Ordner) | `FEHLER mit dem Projektordner: …`, `kick_written: no (project folder refused)`, Exit-Code 4 (kein Ordner wird angelegt) |
| Pfad zu lang (Windows MAX_PATH) | Meldung mit `MAX_PATH`, nichts geschrieben, Exit-Code 4 |
| Schreiben fehlgeschlagen (Platte voll …) | `FEHLER beim Schreiben: …`, Exit-Code 6 |
| *Strg + C* während des Erzeugens | `ABGEBROCHEN mit Strg+C beim Erzeugen des Kicks …`, Exit-Code 130 |
