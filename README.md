# AbeltonGod

KI-Musikproduktions-Copilot für Ableton Live 12 (Windows), Schwerpunkt Techno und Trance.

Der Copilot soll Samples erzeugen und verfeinern, Arrangements vorschlagen, beim Mixing helfen und dabei erklären, was er tut. Er ersetzt keine kreativen Entscheidungen, sondern unterstützt einen eigenen Signature Sound.

**Stand (28.10.2026):** Phase 00 ist abgeschlossen. In Phase 01 ist der Kern der Kick-Engine fertig: Sie erzeugt Kicks deterministisch aus Parametern, misst sie und schreibt WAV-Dateien mit Metadaten. Noch nicht vorhanden sind Presets, Varianten und ein Kommandozeilen-Befehl (#3), und die Kicks wurden noch nicht angehört. Ableton-Anbindung und Claude-Steuerung gibt es noch nicht. Was tatsächlich funktioniert, steht immer in [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md).

## Architektur in einem Satz

Eine lokale Python-Audio-Engine erzeugt Samples, eine Remote-Script-Bridge (AbletonOSC) spricht mit Ableton, und Claude entscheidet als Orchestrator, welche Werkzeuge aufgerufen werden. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), Entscheidungen: [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Reihenfolge

| Phase | Ziel | Status |
| --- | --- | --- |
| 00 | Repo, CI, Agentenregeln | fertig |
| 01 | Kick-Engine ohne Claude: deterministische Synthese, drei Varianten, WAV + Metadaten | Kern fertig; Presets, Varianten, CLI und Hörtest offen |
| 02 | Ableton-Bridge: AbletonOSC in Live Standard 12, Lesen, harmlose Schreibaktion, Undo | geplant |
| 03 | Sample-Import: Kick landet im Ableton-Projekt | geplant |
| 04a | Resource Guard: Grenzen für Tokens, Aufrufe, Kosten, Zeit, Schleifen, Datei- und Ableton-Schreibzugriffe | geplant |
| 04b | Claude-Orchestrator: Sprache → validierte Parameter → Engine → Import | geplant |

Phasenspezifikationen: [`docs/phases/`](docs/phases/).

## Einrichtung unter Windows

Voraussetzungen: [Git](https://git-scm.com/download/win), [Python 3.12+](https://www.python.org/downloads/windows/) (getestet mit 3.12 in CI und 3.14 lokal), [GitHub CLI](https://cli.github.com/) (`winget install --id GitHub.cli`) und Claude Code.

PowerShell **ohne** Administratorrechte öffnen und die Befehle einzeln eingeben:

```powershell
cd $HOME\Documents
git clone https://github.com/castorsalzmann-ui/AbeltonGod.git
cd AbeltonGod
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ruff check .
pytest
gh auth login
```

Bei jedem neuen PowerShell-Fenster vorher: `cd $HOME\Documents\AbeltonGod` und `.venv\Scripts\Activate.ps1`.

**Typische Stolpersteine**

- *„Ausführung von Skripts ist deaktiviert“* bei `Activate.ps1`: einmalig `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` ausführen und mit `J` bestätigen.
- *`gh` wird nicht gefunden* nach der Installation: PowerShell-Fenster schließen und neu öffnen.
- *Pfad nicht gefunden*: Ein Admin-Fenster startet in `C:\WINDOWS\system32`; mit `cd $HOME\Documents\AbeltonGod` in den Repo-Ordner wechseln.

## Mit Claude Code arbeiten

Jede Aufgabe ist ein GitHub Issue. Für jedes Issue eine frische Claude-Code-Sitzung starten, damit Chats kurz bleiben:

```
claude
> /start-task 3
```

Claude liest dann nur `CLAUDE.md`, den aktuellen Stand, das Issue und die passende Phasenspezifikation. Am Ende öffnet `/finish-task` einen Pull Request. Der `reviewer`-Agent prüft ihn, du mergst.

Alles, was Ableton betrifft, testest du auf deinem Rechner. Die automatischen Tests auf GitHub laufen ohne Ableton.

## Lizenzhinweise

- AbletonOSC (MIT) wird als externe Abhängigkeit genutzt, nicht ins Repo kopiert.
- Generative Audiomodelle (z. B. Stable Audio Open) sind nicht Teil des MVP. Vor einer kommerziellen Nutzung erzeugter Samples muss deren Modelllizenz geprüft werden.
