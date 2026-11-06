# AbeltonGod.exe (Windows, ohne Python)

Status: gebaut und getestet nur auf dem GitHub-Actions-Runner `windows-latest`
(`.github/workflows/build-exe.yml`). Auf deinem PC und in Live ist die exe noch nicht gelaufen.

## Bekommen

1. GitHub, Reiter Actions, Workflow "Build exe", letzter gruener Lauf, Artifact
   `AbeltonGod-windows` herunterladen (oder den Workflow per "Run workflow" neu starten).
   Wenn ein Release veroeffentlicht wurde, liegt dieselbe ZIP-Datei unter Releases. Ein Release
   entsteht nur, wenn der Workflow von Hand mit dem Feld `release_tag` gestartet wird.
2. Die ZIP-Datei in einen Ordner entpacken, z. B. `C:\AbeltonGod\`. Der Ordner muss
   zusammenbleiben: `AbeltonGod.exe`, `_internal\`, `contracts\`, `config\`.
3. Windows SmartScreen kann warnen (die exe ist nicht signiert): "Weitere Informationen",
   dann "Trotzdem ausführen".

## Benutzen: Oberflaeche

Doppelklick auf `AbeltonGod.exe` oeffnet das Hauptfenster:

- Links die Klangkategorien (Kick, Hi-Hat, Snare, Clap, Rim, Bass, Laser), die Bibliothek,
  Goa-Arrangement, Live-Import und Copilot. Rechts Ausgabeordner, Rendern, Ergebnisse, Vorhoeren.
- Links unten "Weitere Fenster": Goa-Fenster, Acid-Linie, Laser-Blaster. Jedes oeffnet sich als
  eigenes Fenster, hoechstens eines je Art (ein zweiter Klick holt es nach vorn). Ein Fenster zu
  schliessen beendet das Programm nicht; das Hauptfenster zu schliessen schliesst alle.
- Laser: Die Seite "Laser" hat dieselben Regler wie die anderen Kategorien (Hauptregler oben,
  Salve, Filter, Delay und Reverb als aufklappbare Gruppen). Abzug, Salven-Muster, A/B und Undo
  gibt es im Fenster "Laser-Blaster".
- Hinter der Oberflaeche steht dieselbe Engine: dieselben Parameter und derselbe Seed ergeben
  dieselben Bytes wie auf der Kommandozeile (fuer Laser mit 3 Faellen getestet).
- Ohne PySide6 im Paket (nur bei Selbstbau ohne `[gui]`) faellt der Doppelklick auf das
  Textmenue zurueck. `AbeltonGod.exe --menu` startet das Textmenue immer.
- Das schwarze Konsolenfenster wird beim Doppelklick versteckt (Windows, nur wenn die exe es
  allein besitzt). Das ist auf dem Runner nicht pruefbar.

## Benutzen: Kommandozeile

Mit Argumenten bleibt die exe ein Kommandozeilenwerkzeug (`cmd` oder PowerShell im Ordner):

```
AbeltonGod.exe --version
AbeltonGod.exe --list
AbeltonGod.exe kick --preset centre --seed 7 --out C:\Samples\kicks
AbeltonGod.exe goa-arrangement --seed 3 --out C:\Samples\goa1
AbeltonGod.exe <werkzeug> --help
AbeltonGod.exe --gui-selftest      # startet die Oberflaeche ohne Bildschirm und beendet sich
```

`AbeltonGod.exe <werkzeug> ...` ist dasselbe wie das jeweilige `python -m ...` bzw.
`python scripts/<name>.py ...`; Optionen und Exit-Codes sind die der Werkzeuge.

| Werkzeug | entspricht |
| --- | --- |
| kick, hat, snare, clap, rim, bass | `python -m audio_engine.kick [--category ...]` |
| goa-arrangement, goa-melody, goa-patterns, arrangement-midi | `python -m audio_engine.<name>` |
| live-import, kick-to-live, bridge-check, arrangement-check, install-abletonosc, als-inspect | `python scripts/<name>.py` |
| plan, chat | `python -m orchestrator.plan_cli`, `python -m orchestrator.chat` |

Die Live-Werkzeuge verhalten sich wie die Skripte (siehe `KICK_TO_LIVE.md`): Sie schreiben nur,
was das jeweilige Skript schreibt, und fragen vorher. Die exe ersetzt die Einrichtung von
AbletonOSC nicht (`ABLETONOSC_WINDOWS.md`).

## Zugangsdaten fuer `chat`

Die exe enthaelt keine Schluessel. `chat` (auch der Copilot im Hauptfenster) liest `.env` aus
dem Ordner neben `AbeltonGod.exe` (Vorlage: `.env.example`, wird mitgeliefert). Ohne `.env`
laufen alle anderen Funktionen normal.

## Warum ein Ordner und keine einzelne Datei (onedir)

Die Engine sucht `contracts\` und `config\` relativ zu ihrem Modulpfad; im Ordner-Build ist das
der Ordner der exe. Eine Einzeldatei entpackt sich in einen Temp-Ordner, in dem diese Suche
nicht funktioniert. Der Ordner startet ausserdem schneller und loest seltener
Virenscanner-Alarm aus.

## Selbst bauen

```
pip install -e ".[build,gui]"
python scripts/build_exe.py          # Ergebnis: dist\AbeltonGod\AbeltonGod.exe
python scripts/exe_smoke.py dist\AbeltonGod\AbeltonGod.exe
```

## Nicht abgedeckt

- Kein Lauf auf deinem PC, keiner mit Live (die CI hat kein Live).
- Die CI startet die Oberflaeche nur ohne Bildschirm (Qt offscreen): wie sie unter Windows
  aussieht, Drag-and-drop einer WAV nach Live oder in den Explorer und der Klang auf einem
  echten Geraet (Vorhoeren ueber `winsound`) sind nicht geprueft.
- Keine Signatur, kein Installer, kein Auto-Update.
- `chat` ist nur auf `--help` getestet (Imports im Bundle), nicht mit echtem Zugang.
