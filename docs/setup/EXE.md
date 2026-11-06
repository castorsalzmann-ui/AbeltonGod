# AbeltonGod.exe (Windows, ohne Python)

Status: gebaut und getestet nur auf dem GitHub-Actions-Runner `windows-latest`
(`.github/workflows/build-exe.yml`). Auf deinem PC und in Live ist die exe noch nicht gelaufen.

Im Ordner liegen zwei Programme (#445), die sich `_internal\` teilen:

| Datei | Art | Wofuer |
| --- | --- | --- |
| `AbeltonGod.exe` | Fensterprogramm, ohne Konsole | Doppelklick: die Oberflaeche |
| `AbeltonGod-cli.exe` | Konsolenprogramm | Kommandozeile und Textmenue |

## Bekommen

1. GitHub, Reiter Actions, Workflow "Build exe", letzter gruener Lauf, Artifact
   `AbeltonGod-windows` herunterladen (oder den Workflow per "Run workflow" neu starten).
   Wenn ein Release veroeffentlicht wurde, liegt dieselbe ZIP-Datei unter Releases. Ein Release
   entsteht nur, wenn der Workflow von Hand mit dem Feld `release_tag` gestartet wird.
2. Die ZIP-Datei in einen Ordner entpacken, z. B. `C:\AbeltonGod\`. Der Ordner muss
   zusammenbleiben: `AbeltonGod.exe`, `AbeltonGod-cli.exe`, `_internal\`, `contracts\`, `config\`.
3. Windows SmartScreen kann warnen (die exe ist nicht signiert): "Weitere Informationen",
   dann "Trotzdem ausführen".

## Benutzen: Oberflaeche

Doppelklick auf `AbeltonGod.exe` oeffnet das Hauptfenster. Es oeffnet sich kein schwarzes
Konsolenfenster: die exe ist ein Fensterprogramm (Windows-Subsystem "GUI", in der CI am
PE-Kopf geprueft). Frueher wurde die Konsole einer Konsolen-exe nachtraeglich versteckt; das
ist unter Windows Terminal (Standard ab Windows 11 22H2) unzuverlaessig und entfaellt.

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
- Ein Fensterprogramm hat keine Textausgabe. Was es trotzdem ausgibt, landet in
  `%LOCALAPPDATA%\AbeltonGod\logs\output.log` (bei jedem Start neu).

## Wenn die Oberflaeche nicht startet

Ein Fehler beim Start geht nie still verloren:

- Er wird angehaengt an `%LOCALAPPDATA%\AbeltonGod\logs\startup-errors.log`
  (z. B. `C:\Users\<du>\AppData\Local\AbeltonGod\logs\`). Anderer Ort: Umgebungsvariable
  `ABELTONGOD_LOG_DIR`. Die Datei bleibt unter 256 KB (aeltere Haelfte wird verworfen).
- Ein Meldungsfenster "AbeltonGod - Startfehler" zeigt den Fehler und den Pfad der Logdatei:
  von Qt, wenn Qt schon laeuft, sonst ein Windows-eigenes Meldungsfenster. Laeuft der Start in
  einer Konsole (`python -m launcher`), steht der Fehler dort und die Konsole wartet auf Enter.
- Exit-Code dann 4. `AbeltonGod-cli.exe` startet das Textmenue ohne Oberflaeche.
- Fehler waehrend des Laufs (in einem Knopf o. ae.) landen ebenfalls in der Logdatei
  (`stage: running`), zeigen aber kein Fenster.
- Geprueft auf dem Runner: erzwungene Fehler in drei Startphasen (vor Qt, Qt da, Fenster) in der
  gebauten `AbeltonGod.exe` schreiben die Logdatei und enden mit Exit-Code 4. Die
  Meldungsfenster selbst sind nur mit Attrappen getestet: ohne Bildschirm (`QT_QPA_PLATFORM`
  `offscreen`) werden sie absichtlich nicht gezeigt, weil niemand sie wegklicken koennte.

## Benutzen: Kommandozeile und Textmenue

`AbeltonGod-cli.exe` ohne Argumente (auch per Doppelklick) startet das Textmenue. Mit Argumenten
ist es ein Kommandozeilenwerkzeug (`cmd` oder PowerShell im Ordner):

```
AbeltonGod-cli.exe --version
AbeltonGod-cli.exe --list
AbeltonGod-cli.exe kick --preset centre --seed 7 --out C:\Samples\kicks
AbeltonGod-cli.exe goa-arrangement --seed 3 --out C:\Samples\goa1
AbeltonGod-cli.exe <werkzeug> --help
AbeltonGod-cli.exe --gui-selftest      # startet die Oberflaeche ohne Bildschirm und beendet sich
```

`AbeltonGod.exe` versteht dieselben Argumente, zeigt aber keine Ausgabe (sie steht in
`output.log`); fuer die Kommandozeile also `AbeltonGod-cli.exe` nehmen.

`AbeltonGod-cli.exe <werkzeug> ...` ist dasselbe wie das jeweilige `python -m ...` bzw.
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
dem Ordner neben den exe-Dateien (Vorlage: `.env.example`, wird mitgeliefert). Ohne `.env`
laufen alle anderen Funktionen normal.

## Groesse (#435)

Gemessen auf dem Runner ([Lauf 42215660939](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/42215660939)):
408 MB entpackt, 190 MB als ZIP (vorher 430 MB / 192 MB, [Lauf 42212869135](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/42212869135)).

| Teil | MB | Anmerkung |
| --- | --- | --- |
| `claude.exe` (Claude-CLI im `claude-agent-sdk`) | 283 | fuer `chat` und den Copilot noetig (gepinnte CLI 2.1.310); bleibt (Lead-Entscheidung) |
| Qt (PySide6) | 40 | vorher 72; entfernt 32 MB, siehe unten |
| numpy + OpenBLAS | 26 | |
| `AbeltonGod.exe` + `AbeltonGod-cli.exe` | je 10 | jede traegt den Python-Code; die zweite exe kostet 10 MB |
| cryptography, pydantic_core, Python, OpenSSL u. a. | ~30 | |

Aus Qt entfernt (`QT_PRUNE` in `scripts/build_exe.py`): `opengl32sw.dll` (19,7 MB, Software-OpenGL,
die Oberflaeche zeichnet ohne OpenGL), Qt-Uebersetzungen (6,7 MB, nicht geladen), Bildformat-
und Icon-Plugins (2,4 MB, PNG ist in QtGui eingebaut), Netzwerk/TLS (`Qt6Network.dll`), SVG,
Touch-Eingabe ueber das Netz und die Plattform-Plugins `qdirect2d`/`qminimal`. Belegt durch den
Rauchtest: `--gui-selftest` (alle Seiten, alle drei Fenster) mit `offscreen` und mit dem echten
Plattform-Plugin `windows`; eine Kopie ohne `qwindows.dll` faellt durch (die exe beendet sich
dann nicht, der Test bricht nach 60 s ab).

## Warum ein Ordner und keine einzelne Datei (onedir)

Die Engine sucht `contracts\` und `config\` relativ zu ihrem Modulpfad; im Ordner-Build ist das
der Ordner der exe. Eine Einzeldatei entpackt sich in einen Temp-Ordner, in dem diese Suche
nicht funktioniert. Der Ordner startet ausserdem schneller und loest seltener
Virenscanner-Alarm aus.

## Selbst bauen

```
pip install -e ".[build,gui]"
python scripts/build_exe.py          # Ergebnis: dist\AbeltonGod\AbeltonGod.exe und AbeltonGod-cli.exe
python scripts/build_exe.py --report dist\AbeltonGod      # Groessen
python scripts/build_exe.py --subsystem dist\AbeltonGod   # GUI = 2, CLI = 3
python scripts/exe_smoke.py dist\AbeltonGod\AbeltonGod-cli.exe
```

## Nicht abgedeckt

- Kein Lauf auf deinem PC, keiner mit Live (die CI hat kein Live).
- Kein echter Doppelklick im Explorer: ob wirklich kein Konsolen- oder Terminal-Fenster
  erscheint, ist nur am PE-Kopf (Subsystem 2) geprueft, nicht gesehen.
- Die Oberflaeche lief auf dem Runner offscreen und einmal mit dem Plattform-Plugin `windows`
  (ohne dass jemand hinsah): wie sie unter Windows aussieht, Drag-and-drop einer WAV nach Live
  oder in den Explorer und der Klang auf einem echten Geraet (Vorhoeren ueber `winsound`) sind
  nicht geprueft.
- Keine Signatur, kein Installer, kein Auto-Update.
- `chat` ist nur auf `--help` getestet (Imports im Bundle), nicht mit echtem Zugang.
