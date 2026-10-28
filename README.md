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

`pytest` verteilt die Tests automatisch auf alle CPU-Kerne (Zeile `created: N/N workers` in der Ausgabe). Nach einem `git pull` mit neuen Abhängigkeiten einmal `pip install -e ".[dev]"` wiederholen. Zum Fehlersuchen seriell laufen lassen: `pytest -n 0`.

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

## Ressourcen-Wächter (Grenzen für Claude-Anfragen)

Jede Claude-Anfrage des Copiloten läuft durch einen Wächter (`src/guard/`, Entscheidung D-011). Er begrenzt, wie viel eine einzelne Anfrage verbrauchen und verändern darf. Die Grenzen stehen in [`config/guard-policy.json`](config/guard-policy.json), je Anfrageart ein Profil (z. B. `kick_generation`, `mentor_answer`).

| Einstellung | Bedeutung |
| --- | --- |
| `max_output_tokens` | Maximale Länge einer einzelnen Modellantwort. |
| `max_model_calls` | Wie oft Claude pro Anfrage aufgerufen werden darf. |
| `max_tool_calls` | Wie viele Werkzeugaufrufe (z. B. „Kick erzeugen“) pro Anfrage erlaubt sind. |
| `max_budget_usd` | Kostengrenze pro Anfrage. Mit Abo sind das geschätzte API-Kosten, kein echtes Geld; die eigentliche Grenze ist dein Nutzungsfenster. |
| `timeout_s` | Maximale Dauer einer Anfrage in Sekunden. |
| `max_identical_tool_calls` | Wie oft dasselbe Werkzeug mit genau denselben Werten laufen darf, bevor es als Schleife gilt. |
| `max_files_written` | Wie viele Dateien eine Anfrage schreiben darf. |
| `max_live_writes` | Wie viele Änderungen am Ableton-Set eine Anfrage machen darf. Jede Änderung braucht trotzdem deine Freigabe. |
| `warn_at_fraction` | Ab welchem Anteil einer Grenze gewarnt wird (0.8 = 80 %). |
| `global.session_budget_usd` / `daily_budget_usd` | Kostengrenze für die ganze Sitzung bzw. den Tag (der Tageswert übersteht einen Neustart). |
| `global.max_concurrent_requests` | Wie viele Anfragen gleichzeitig laufen dürfen. |

**Was passiert:** Ab der Warnschwelle fasst sich der Copilot kurz und startet keine neuen Teilaufgaben. Wird eine Grenze überschritten, bricht die Anfrage ab, und du siehst, was fertig ist und was offen bleibt. Eine abgebrochene Anfrage wird nie als Erfolg gemeldet.

**Ändern:** Werte in `config/guard-policy.json` anpassen und den Copiloten neu starten. Eine ungültige Datei (fehlender Wert, falscher Typ, `NaN`) wird mit einer Fehlerliste abgelehnt, nichts wird stillschweigend ersetzt. Prüfen mit `pytest tests/test_contracts.py`. Das Nutzungsprotokoll liegt in `logs/guard-usage.jsonl` (nicht im Repo).

## Lizenzhinweise

- AbletonOSC (MIT) wird als externe Abhängigkeit genutzt, nicht ins Repo kopiert.
- Generative Audiomodelle (z. B. Stable Audio Open) sind nicht Teil des MVP. Vor einer kommerziellen Nutzung erzeugter Samples muss deren Modelllizenz geprüft werden.
