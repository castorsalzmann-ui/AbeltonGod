# AbeltonGod.exe (Windows, ohne Python)

Status: gebaut und getestet nur auf dem GitHub-Actions-Runner `windows-latest`
(`.github/workflows/build-exe.yml`). Auf deinem PC und in Live ist die exe noch nicht gelaufen.

## Bekommen

1. GitHub, Reiter Actions, Workflow "Build exe", letzter gruener Lauf, Artifact
   `AbeltonGod-windows` herunterladen (oder den Workflow per "Run workflow" neu starten).
2. Die ZIP-Datei in einen Ordner entpacken, z. B. `C:\AbeltonGod\`. Der Ordner muss
   zusammenbleiben: `AbeltonGod.exe`, `_internal\`, `contracts\`, `config\`.
3. Windows SmartScreen kann warnen (die exe ist nicht signiert): "Weitere Informationen",
   dann "Trotzdem ausführen".

## Benutzen

- Doppelklick auf `AbeltonGod.exe`: Textmenue. Werkzeug waehlen (Nummer oder Name),
  Ausgabeordner angeben (Enter = `%USERPROFILE%\AbeltonGod-out`), optional weitere Optionen,
  am Ende zeigt das Fenster, wo die Dateien liegen, und wartet auf Enter.
- Kommandozeile (`cmd` oder PowerShell im Ordner):

```
AbeltonGod.exe --version
AbeltonGod.exe --list
AbeltonGod.exe kick --preset centre --seed 7 --out C:\Samples\kicks
AbeltonGod.exe goa-arrangement --seed 3 --out C:\Samples\goa1
AbeltonGod.exe <werkzeug> --help
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

Die exe enthaelt keine Schluessel. `chat` liest `.env` aus dem Ordner neben `AbeltonGod.exe`
(Vorlage: `.env.example`, wird mitgeliefert). Ohne `.env` laufen alle anderen Werkzeuge normal.

## Warum ein Ordner und keine einzelne Datei (onedir)

Die Engine sucht `contracts\` und `config\` relativ zu ihrem Modulpfad; im Ordner-Build ist das
der Ordner der exe. Eine Einzeldatei entpackt sich in einen Temp-Ordner, in dem diese Suche
nicht funktioniert. Der Ordner startet ausserdem schneller und loest seltener
Virenscanner-Alarm aus.

## Selbst bauen

```
pip install -e ".[build]"
python scripts/build_exe.py          # Ergebnis: dist\AbeltonGod\AbeltonGod.exe
python scripts/exe_smoke.py dist\AbeltonGod\AbeltonGod.exe
```

## Nicht abgedeckt

- Kein Lauf auf deinem PC, keiner mit Live (die CI hat kein Live).
- Keine Signatur, kein Installer, kein Auto-Update, keine GUI.
- `chat` ist nur auf `--help` getestet (Imports im Bundle), nicht mit echtem Zugang.
