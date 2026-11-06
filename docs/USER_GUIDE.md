# AbeltonGod – Anleitung (Stand 2026-11-05)

Eine Seite: was es gibt, was du startest, was nicht verifiziert ist. Alle Befehle werden im Projektordner in der venv ausgeführt (`pip install -e ".[dev]"`, Einrichtung unter Windows: README).

## Ehrlicher Status

- Alles ist **deterministisch** (gleiche Parameter + Seed = gleiche Bytes) und automatisch getestet (CI auf Ubuntu und Windows).
- **Nichts davon ist von dir angehört oder in deinem Live getestet.** Qualität und Geschmack sind nirgends behauptet. Was Live betrifft, steht in `contracts/capabilities.json` nicht auf `tested`.
- Hörtests und Live-Tests sind **optional** (`docs/WAITING_ON_USER.md`). Das Projekt blockiert nicht darauf.

## Was es gibt

| Bereich | Was | Einstieg |
| --- | --- | --- |
| Programm mit Oberfläche | `AbeltonGod.exe` (Windows, ohne Python): Doppelklick öffnet das Hauptfenster mit allen Kategorien einschließlich Laser, Bibliothek, Goa, Live-Import, Copilot und Knöpfen für die Fenster Goa, Acid-Linie und Laser-Blaster. Aus Quelltext: `python -m gui` | `docs/setup/EXE.md`; Aussehen unter Windows, Drag-and-drop, Klang auf deinem Gerät und ein Lauf der exe bei dir sind nicht geprüft (die CI startet die Oberfläche nur ohne Bildschirm) |
| Samples | Kick, Hat, Snare, Clap, Rim, Bass, Laser: Presets und Varianten als WAV + Sidecar-JSON | `python -m audio_engine.kick --list-presets`, weitere Kategorien: `src/audio_engine/` (Module `hat`, `snare`, `clap`, `rim`, `bass`), Presets in `src/audio_engine/presets/` |
| Goa-Arrangement | Mehrspur-MIDI: Kick, Bass, Hat, Snare, Clap, Rim (aus Engine-Presets, mit gerenderten One-Shots) plus Melodie | `python -m audio_engine.goa_arrangement --out <Ordner> --seed 1 --bpm 145` |
| Goa-Melodie | Lead, Arp, Pad, Pluck als MIDI, alles einstellbar | `python -m audio_engine.goa_melody --out <Ordner> --seed 1 --bpm 145` |
| Import in Live | WAV als Clip über AbletonOSC (Python-Remote-Script, kein Max for Live) | `python scripts/live_import.py "<Pfad der WAV>"`, Rezepte in `docs/setup/*_TO_LIVE.md` |
| Claude-Copilot | Sprache → geprüfte Parameter → Engine → Import, mit Ressourcen-Wächter | README, Abschnitt „Ressourcen-Wächter“ |

Jeder Generator schreibt ein README in seinen Ausgabeordner, das die gewählten Optionen und die Grenzen nennt. Ein vorhandener Ausgabeordner wird nie überschrieben.

## Einstellbar statt festgelegt (D-027, D-028)

Bass-Rhythmus (`--roll`: jede 16tel, Off-Beat-Achtel, Galopp, Off-Beat mit Ghost-Noten, Triolen-Galopp), Form (`--intro-bars`, Breakdowns, Outro, DJ-Intro/Outro), Tempo (135–150, Standard 145), Skala, Grundton, Dichte, Lage, Arp-Muster. Die Zahlen aus den drei Referenztracks (`docs/research/2026-11-03_goa-reference-measurements.md`) sind nur Voreinstellungen und niedrig belastbar (drei Tracks, Stereo-Mixe).

## Bekannte Grenzen

- Bass-Tonhöhe im Sampler musst du von Hand an die Tonart anpassen (steht im README der Ausgabe).
- Snare/Clap/Rim/Kick/Hat-MIDI-Muster sind fester Code mit Optionen, nicht aus Presets abgeleitet; die Einsatzschwellen der Percussion sind Voreinstellungen, keine Messwerte.
- Melodie-Voreinstellungen sind Entscheidungen der Entwickler, keine gemessenen Goa-Werte; keine Slides/Akzente in der Pluck-/Acid-Linie.
- Live 12 **Standard**: kein Operator, Wavetable, Sampler, Meld, Echo, Roar (an deinem Geräte-Browser bestätigt). Instrumente für die Melodie: Drift (Standard), Analog.
- Der Claude-Orchestrator hat seinen Abnahmelauf am PC noch nicht gehabt (Phase 04b).

## Wenn du irgendwann testen willst (alles optional)

1. Hören: `docs/setup/LISTENING_TEST_*.md` (blinde Pakete, Anleitungen), Antworten auf [#356](https://github.com/castorsalzmann-ui/AbeltonGod/issues/356).
2. Import in Live: `docs/setup/RIM_BASS_TO_LIVE.md`, `SNARE_TO_LIVE.md`, Ergebnis auf [#129](https://github.com/castorsalzmann-ui/AbeltonGod/issues/129).
3. Goa-Arrangement in Live: T1–T8 in `docs/research/2026-11-03_goa-arrangement-delivery-to-live.md`.

Erst mit solchen Belegen darf eine Fähigkeit auf `tested` (CLAUDE.md, Capability-Regel).
