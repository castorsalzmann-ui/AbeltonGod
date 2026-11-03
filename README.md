# AbeltonGod

KI-Musikproduktions-Copilot für Ableton Live 12 (Windows), Schwerpunkt Techno und Trance.

Der Copilot soll Samples erzeugen und verfeinern, Arrangements vorschlagen, beim Mixing helfen und dabei erklären, was er tut. Er ersetzt keine kreativen Entscheidungen, sondern unterstützt einen eigenen Signature Sound.

**Stand (03.11.2026):** Der Kick-Generator ist abgeschlossen (Hörtest 3, Preset `dense`); Kick-Prompts mit Schlüsselwörtern sind gemergt, das Hörpaket liegt beim Nutzer (Keyword-Reihe in der Roadmap daher noch „In Arbeit“). Der Kick lässt sich per Terminal-Chat mit Claude erzeugen und in ein Ableton-Projekt importieren, jeweils durch den Ressourcen-Wächter; der Abnahmelauf am PC steht aus. Ein Arrangement-Planer (auch als Claude-Werkzeug `plan_arrangement`) erzeugt Pläne aus Genre, Tempo und Länge; ins Live schreiben kann er noch nicht. Neue Kategorien: Clap (inkl. Xtreme-Presets) und Hat sind als Stimmen gemergt, Hörantworten stehen aus; Clap- und Hat-Import in Live sind nur gegen eine Simulation getestet. Snare, Rim und Bass sind als Stimmen gemergt (Snare mit Claude-Adapter), noch nicht angehört und nicht in Live probiert; Rim- und Bass-Adapter fehlen. Dazu ein `.mid`-Schreiber für Acid-Linien (Test in Live offen) und, als Parkplatz-Idee mit Go/No-Go beim Nutzer, ein Goa-Plugin: Recherche, Mustergenerator und Arrangement-Export als `.mid` liegen auf `main`, ohne Klang und ohne Test in Live. Alle offenen Hörtests: [Issue 356](https://github.com/castorsalzmann-ui/AbeltonGod/issues/356).

**Cockpit:** Roadmap, Forschungsnotizen, offene Aufgaben für den Nutzer und wer gerade arbeitet: [Projekt-Cockpit](https://castorsalzmann-ui.github.io/AbeltonGod/) (aktualisiert sich alle 30 Minuten selbst; der Banner oben zeigt das Alter der Daten). Was nur der Nutzer tun kann, steht in [`docs/WAITING_ON_USER.md`](docs/WAITING_ON_USER.md), die Feature-Tabelle in [`docs/ROADMAP.md`](docs/ROADMAP.md), der ausführliche Stand in [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md).

## Architektur in einem Satz

Eine lokale Python-Audio-Engine erzeugt Samples, eine Remote-Script-Bridge (AbletonOSC) spricht mit Ableton, und Claude entscheidet als Orchestrator, welche Werkzeuge aufgerufen werden. Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), Entscheidungen: [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Reihenfolge

| Phase | Ziel | Status |
| --- | --- | --- |
| 00 | Repo, CI, Agentenregeln | fertig |
| 01 | Kick-Engine ohne Claude: deterministische Synthese, Varianten, WAV + Metadaten | fertig |
| 02 | Ableton-Bridge: AbletonOSC in Live Standard 12, Lesen, harmlose Schreibaktion, Undo | fertig (Arrangement-Funktionen warten auf einen Lauf in Live) |
| 03 | Sample-Import: Kick landet im Ableton-Projekt | fertig |
| 04a | Resource Guard: Grenzen für Tokens, Aufrufe, Kosten, Zeit, Schleifen, Datei- und Ableton-Schreibzugriffe | fertig |
| 04b | Claude-Orchestrator: Sprache → validierte Parameter → Engine → Import | in Arbeit (Abnahmelauf am PC offen) |
| 05 | Kick-Charakter: Preset `dense`, Hörtests, Keyword-Prompts | Kick fertig (Hörtests abgeschlossen); Keyword-Prompts in Arbeit (Hörpaket beim Nutzer) |
| 06 | Weitere Klangkategorien (Clap, Hat, Snare, Rim, Bass) | in Arbeit (Clap, Hat, Snare, Rim, Bass als Stimmen gemergt; Hörtests und Live-Import offen) |

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
