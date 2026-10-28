# Hörtest Phase 01: Kick-Presets und Varianten (#3)

Dieser Test gehört zu Issue #3. Nur du kannst sagen, wie die Kicks klingen. Die Zahlen im PR beschreiben nur die Signale. Dauer: etwa 30–45 Minuten.

## 1. Kicks rendern (Windows, PowerShell)

Im Projektordner, auf `main`, nachdem der PR gemergt ist:

```powershell
git switch main
git pull
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m audio_engine.kick --list-presets
```

Die letzte Zeile listet die fünf Presets. Dann alles in einen eigenen Ordner außerhalb des Repos rendern:

```powershell
$out = "$HOME\Music\AbeltonGod-Hoertest-01"
foreach ($p in "centre", "dark-dry", "punchy", "rumble-ready", "driven") {
  python -m audio_engine.kick --preset $p --variants 4 --out $out
  if ($LASTEXITCODE) { "Fehler bei $p (Exit-Code $LASTEXITCODE)" }
}
python -m audio_engine.kick --preset centre --set pitch_decay_ms=15 --out $out
python -m audio_engine.kick --preset centre --set pitch_decay_ms=8 --out $out
python -m audio_engine.kick --preset driven --set drive=0 --out $out
python -m audio_engine.kick --preset centre --set length_ms=450.02 --out $out
python -m audio_engine.kick --preset punchy --set length_ms=80 --set amp_decay_ms=60 --out $out
explorer $out
```

Jeder Aufruf gibt pro Datei eine Zeile aus (Pfad, gemessene Tonhöhe, Abklingzeit, Spitze). Ein Fehler steht als eigene Zeile `error: …` da; in der Schleife meldet zusätzlich `Fehler bei <Preset>` jeden fehlgeschlagenen Aufruf. Bei den Einzelbefehlen danach zeigt `echo $LASTEXITCODE` nur den Exit-Code des letzten Befehls (`0` = ok). Es werden nie Dateien überschrieben: Wenn du die Befehle zweimal ausführst, entstehen Dateien mit `_002` am Ende.

Was die Namen bedeuten: `punchy_s1003_v0.wav` = Preset `punchy`, Grund-Seed 1003, Variante 0 (= das Preset selbst). `v1`–`v3` sind Varianten. `_custom` heißt: ein Wert wurde mit `--set` geändert. Zu jeder WAV gehört eine `.json` mit allen Werten.

Danach sollte der Ordner diese Dateien enthalten (jeweils `.wav` + `.json`):

| Datei | Wofür |
| --- | --- |
| `centre_s1001_v0` … `v3`, ebenso `dark-dry_s1002_*`, `punchy_s1003_*`, `rumble-ready_s1004_*`, `driven_s1005_*` | Punkte 1 und 2 |
| `centre_s1001_v0_custom` (pitch_decay 15), `centre_s1001_v0_custom_002` (8) | Punkt 3 |
| `driven_s1005_v0_custom` (drive 0) | Punkt 4 |
| `centre_s1001_v0_custom_003` (450,02 ms, 21601 Samples) | Punkt 5 |
| `punchy_s1003_v0_custom` (80 ms) | Punkt 6 |

Welche `_custom`-Datei welche ist, steht in ihrer `.json` unter `description` ("Custom values: …").

## 2. In Live 12.4.5 laden

1. Samplerate einstellen. Sie gilt in Live global für das Audiogerät, nicht pro Projekt: Strg + , → Audio → Samplerate → Ein-/Ausgangs-Samplerate 48000 (bei ASIO-Interfaces ggf. im Treiber-Kontrollfeld). Dann ein neues Set öffnen.
2. Den Ausgabeordner im Browser von Live hinzufügen: Orte → Ordner hinzufügen… → `AbeltonGod-Hoertest-01` in deinem Musik-Ordner wählen. Die WAVs dann aus dem Browser (oder per Drag & Drop aus dem Explorer) in Audiospuren oder in ein Drum Rack ziehen.
3. Ein 4/4-Pattern bei deinem üblichen Tempo, Fader auf 0 dB, keine Effekte auf den Spuren und im Master.
4. Alle Dateien haben −0,3 dBFS Spitze. Die Spitze ist gleich, die Lautheit nicht unbedingt: Kicks mit langem Schwanz wirken lauter. Wenn du fair vergleichen willst, die Fader nach Gehör angleichen und notieren, um wie viel.

## 3. Was du vergleichst

1. **Presets** (`*_v0`): Welche sind brauchbar, welche nicht? Was soll sich ändern (z. B. „mehr Klick“, „Schwanz zu lang“)?
2. **Varianten** (`v1`–`v3` je Preset gegen `v0`): Hörst du einen Unterschied? Zu wenig, passend oder zu viel?
3. **pitch_decay 8 / 15 / 40** auf `centre`: `centre_s1001_v0` (40 ms) gegen die `_custom`-Dateien mit 15 und 8. Welcher Wert klingt richtig? Der erste Hörtest (2026-10-28) lief noch mit `centre` = 8 ms und `--set pitch_decay_ms=40`; du hast 40 gewählt. Seit #59 hat `centre` deshalb 40 ms; der Standardwert im Vertrag bleibt 15 ms.
4. **Drive** (anti-aliased #20, stetig ab 0 #38): `driven_s1005_v0` (drive 0,45) gegen `driven_s1005_v0_custom` (drive 0). Klingt der Drive in Ordnung, oder hörst du Artefakte (Kratzen, metallische Obertöne)? Die alte Version ohne Anti-Aliasing gibt es nicht mehr; beurteile nur, ob er so in Ordnung ist.
5. **WAV-Format** (Format-Tag 1, 24 bit, ungerade Samplezahl): die 450,02-ms-Datei in Live ziehen. Lädt und spielt sie ohne Warnung?
6. **Sub-Bass-Schwanz kurzer Kicks (#9):** die 80-ms-Datei (`punchy_s1003_v0_custom`). Hörst du ein Grummeln, oder siehst du im Spectrum-Analyzer etwas unter 20 Hz? Pumpt ein Limiter im Master darauf?
7. **Klick / Helligkeit des Anschlags:** Vier der fünf Presets haben gemessen weniger Höhen im Anschlag als die meisten deiner 77 Referenz-Kicks; nur `driven` liegt im mittleren Bereich. Ist dir der Klick bei `centre`, `dark-dry`, `punchy`, `rumble-ready` zu leise? Wenn ja, wird daraus ein eigenes Issue für einen stärkeren Klick (neuer Parameter).
8. **Dichte von `driven` (#30/#31):** Ist `driven` dicht und druckvoll genug, oder fehlt ihm etwas gegenüber dem, was du von einem stark gefahrenen Kick erwartest? Gemessen: der Crest-Faktor sinkt von 11,8 (drive 0) auf 4,0 (drive 0,45). Bei viel Drive, viel Klick und heller Tonblende kostet die Engine heute etwas Dichte. Ob das hörbar ist, entscheidest du.

## 4. Rückmeldung in #3

Als Kommentar in Issue #3, kurz pro Punkt:

```
Hörtest Phase 01 (Live 12.4.5, 48 kHz, Python <Version>)
Exit-Codes alle 0: ja/nein
1. Presets: centre …, dark-dry …, punchy …, rumble-ready …, driven …
2. Varianten: zu wenig / passend / zu viel Unterschied (bei …)
3. pitch_decay: 8 / 15 / 40 → am besten: …
4. Drive: ok / Artefakte bei …
5. 24-bit-Datei mit ungerader Länge: lädt ja/nein, Warnung: …
6. Sub-Schwanz der 80-ms-Datei: nicht hörbar / hörbar (wie) …
7. Klick: reicht / zu leise bei …
8. driven: dicht genug / zu wenig Druck …
Sonstiges: …
```
