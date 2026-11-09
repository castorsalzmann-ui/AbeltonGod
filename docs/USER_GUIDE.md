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
| Goa-Melodie | Lead, Arp, Pad, Pluck als MIDI, alles einstellbar; Seite „Goa-Melodie“ und Goa-Fenster machen nur Melodien (D-033), arrangiert wird im Arrangement-Planer | `python -m audio_engine.goa_melody --out <Ordner> --seed 1 --bpm 145` |
| Goa-Arrangement (nur Kommandozeile, D-033) | Mehrspur-MIDI mit Drums und Bass; nicht mehr in der Oberfläche | `python -m audio_engine.goa_arrangement --out <Ordner> --seed 1 --bpm 145` |
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

## 10-Minuten-Test der Oberfläche (Stand Sprint W1, 2026-11-09)

Download: GitHub → Actions → „Build exe“ → neuester Lauf auf `main` → Artifact `AbeltonGod-windows` (ZIP entpacken). Ergebnisse bitte als Kommentar auf das Sprint-Issue oder als neue Bugs.

1. `AbeltonGod.exe` doppelklicken: Hauptfenster öffnet sich, **kein Konsolen- oder Terminal-Fenster**. (Startfehler stehen sonst in `%LOCALAPPDATA%\AbeltonGod\logs\startup-errors.log`.)
2. Passt das Fenster auf deinen Bildschirm (deine Skalierung)? Alle Texte lesbar, nichts abgeschnitten?
3. Kick-Seite: Preset wählen, einen Regler ziehen (ruckelt es?), „Rendern“. Die Datei erscheint unter Ergebnisse und in der Bibliothek (`Samples/Drums/Kicks/kick_…wav`). „Abspielen“: hörst du den Kick?
4. Laser-Seite und „Laser-Blaster“-Fenster: Abzug drücken, Schuss hören, „In Bibliothek speichern“.
5. Acid-Linie: „WAV exportieren“: taucht ohne Neustart in der Bibliothek auf. Goa-Fenster: rendern: eine MIDI-Datei (Lead/Arp/Pad/Pluck) unter `Goa/`.
6. „Einstellungen …“: Projektordner deines Test-Sets (Ordner mit `.als`) setzen; App schließen und neu öffnen: Einstellung und Fensterpositionen bleiben.
7. Live mit AbletonOSC offen: Live-Seite, eine Kick-Datei → Import. Der Clip liegt danach in `<Projekt>\Samples\Drums\Kicks\` und spielt.
8. Einen Blaster-Schuss in eine Live-Spur ziehen, Blaster schließen: spielt der Clip noch?
9. Copilot-Seite: eine kurze Frage stellen: Antwort kommt, **kein** Konsolenfenster geht auf.
10. `AbeltonGod-cli.exe kick --help` in einer Eingabeaufforderung: Hilfe erscheint.

**Neu aus Sprint W2 (Parkplatz, 2026-11-07), weitere ~10 Minuten:**

11. Perc-Seite: alle 9 Presets anhören (Conga, Bongo, Shaker, Cowbell, Clave, Hard-Groove-Toms). Passen sie in einen Techno-Loop, willst du die Toms überhaupt?
12. FX-Seite: Tempo auf das deines Tracks stellen, `riser-8bar` und `reverse-crash` rendern, in Live auf einen Drop legen: endet der Riser auf dem Taktstrich? (Live kann lange Dateien automatisch warpen, #484.)
13. Referenz-Seite: eine eigene Kick-WAV wählen, „Als Startwerte übernehmen“, rendern: ist der Vorschlag ein brauchbarer Startpunkt?
14. Arrangement-Planer: Energiekurve zeichnen, „Exportieren“: Plan-Datei unter `Plans/`.
15. Bibliothek: ein paar Samples „Favorit“ / „Passt nicht“ markieren, dann „Kit erstellen“ → „Aus Favoriten“ → „Kit exportieren“: Ordner unter `Samples/Kits/`.
16. Copilot: „Mach mir drei dunkle Kicks für 140 BPM“, dann einen in Live importieren lassen: Bestätigungsdialog erscheint, Nein = nichts passiert, Ja = Clip in Live (bei gesetztem Projektordner als Kopie im Projekt).

**Neu seit 2026-11-08:**

17. Ein Monitor mit Live: Hauptfenster mit Win+Pfeil rechts an den Rand schnappen: Seitenauswahl als Klappmenü sichtbar, nichts abgeschnitten? „Immer im Vordergrund“ anhaken, in Live klicken: bleibt AbeltonGod oben? Nach Neustart noch angehakt? Ein Sample aus Bibliothek oder Ergebnissen in eine Live-Spur ziehen.
18. Copilot: „Mach mir einen 8-Takt-Riser“ ohne Tempo: er fragt nach dem Tempo statt zu raten; mit Tempo landet der Riser in der Bibliothek.
19. Atmos-Seite: Tempo deines Tracks, 8 Takte, Preset `dark-bed` und `drone-root-fifth` rendern, in Live als Loop (Warp-Modus „Texture“) laufen lassen: hörst du an der Loop-Naht einen Klick? Passt die Länge auf den Takt?
20. Goa-Melodie: rendern: eine MIDI-Datei mit Lead/Arp/Pad/Pluck, keine Drums.

Jeder Punkt ist bisher nur automatisch (ohne Bildschirm bzw. gegen einen nachgebauten Live-Server) oder gar nicht geprüft; deine Rückmeldung ist der erste echte Beleg.

## Wenn du irgendwann testen willst (alles optional)

1. Hören: `docs/setup/LISTENING_TEST_*.md` (blinde Pakete, Anleitungen), Antworten auf [#356](https://github.com/castorsalzmann-ui/AbeltonGod/issues/356).
2. Import in Live: `docs/setup/RIM_BASS_TO_LIVE.md`, `SNARE_TO_LIVE.md`, Ergebnis auf [#129](https://github.com/castorsalzmann-ui/AbeltonGod/issues/129).
3. Goa-Arrangement in Live: T1–T8 in `docs/research/2026-11-03_goa-arrangement-delivery-to-live.md`.

Erst mit solchen Belegen darf eine Fähigkeit auf `tested` (CLAUDE.md, Capability-Regel).
