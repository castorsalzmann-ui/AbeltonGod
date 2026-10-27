# AbeltonGod

KI-Musikproduktions-Copilot für Ableton Live 12 (Windows), Schwerpunkt Techno und Trance.

Der Copilot soll Samples erzeugen und verfeinern, Arrangements vorschlagen, beim Mixing helfen und dabei erklären, was er tut. Er ersetzt keine kreativen Entscheidungen, sondern unterstützt einen eigenen Signature Sound.

**Stand:** Phase 00 (Setup). Es gibt noch keine lauffähige Funktion. Was tatsächlich funktioniert, steht immer in [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md).

## Architektur in einem Satz

Eine lokale Python-Audio-Engine erzeugt Samples, eine Remote-Script-Bridge (AbletonOSC) spricht mit Ableton, und Claude entscheidet als Orchestrator, welche Werkzeuge aufgerufen werden. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), Entscheidungen: [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Reihenfolge

| Phase | Ziel |
| --- | --- |
| 00 | Repo, CI, Agentenregeln |
| 01 | Kick-Engine ohne Claude: deterministische Synthese, drei Varianten, WAV + Metadaten |
| 02 | Ableton-Bridge: AbletonOSC in Live Standard 12, Lesen, harmlose Schreibaktion, Undo |
| 03 | Sample-Import: Kick landet im Ableton-Projekt |
| 04 | Claude-Orchestrator: Sprache → validierte Parameter → Engine |

Phasenspezifikationen: [`docs/phases/`](docs/phases/).

## Einrichtung unter Windows

Voraussetzungen: [Git](https://git-scm.com/download/win), [Python 3.12+](https://www.python.org/downloads/windows/), [GitHub CLI](https://cli.github.com/) und Claude Code.

```powershell
git clone https://github.com/castorsalzmann-ui/AbeltonGod.git
cd AbeltonGod
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
gh auth login
```

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
