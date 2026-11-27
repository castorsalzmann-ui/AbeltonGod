# AbeltonGod – Endstand (2026-11-27)

Für den Nutzer. Letzter Stand der Entwicklungsphase mit Claude als Lead. Diese Seite sagt, was du hast, wie du es benutzt, was nie geprüft wurde und wie es später weitergehen kann.

## Die exe

- Download: GitHub → Actions → „Build exe“ → der neueste grüne Lauf auf `main` → unten „Artifacts“ → `AbeltonGod-windows`. Der genaue Link des letzten Laufs steht ganz oben in `docs/CURRENT_STATE.md`. Artefakte laufen nach 90 Tagen ab.
- Neu bauen (ohne Claude, kostenlos): GitHub → Actions → „Build exe“ → „Run workflow“ → Branch `main`. Nach etwa 10 Minuten liegt ein neues Artefakt dort. Mit einem Wert im Feld `release_tag` (z. B. `exe-v1.0`) wird zusätzlich ein dauerhaftes, öffentliches Release angelegt.
- Benutzen: ZIP ganz entpacken, `AbeltonGod.exe` starten. `AbeltonGod-cli.exe` ist dieselbe Software für die Kommandozeile.

## Was die exe kann

| Bereich | Stand |
| --- | --- |
| Samples: Kick, Clap, Hat, Snare, Rim, Bass, Perc, Laser, FX, Atmos | Presets und Varianten als WAV mit Sidecar; Vorhören, Lautstärke-Regler (Start 45 %), Loop-Vorschau im Takt |
| Blaster-Fenster | Laser-Sounds mit Salve, Filter, Delay, Reverb, Presets, Bank-Export |
| Acid-Fenster | 303-artige MIDI-Linie mit grober Vorschau |
| Goa-Clips (D-037) | Lead, Arp, Pad, Acid-Linie als MIDI-Clips nach dem Zellenmodell; Regler u. a. Skala, Grundton, Takte, Lead (eigene Linie / doppelt den Arp), Muster (wandernd / 3+3+2 / 3+3+3+3+4); grobe Vorschau mit Filter und Delay, im Hintergrund gerechnet |
| Bibliothek, Kit-Export, Arrangement-Planer | Favoriten, Kits unter `Samples/Kits/`, Plan-Dateien unter `Plans/` |
| Referenz-Seite | eigene Kick-WAV → nächster Kandidat als Startwerte (v1) |
| Live-Import, Copilot | vorhanden; siehe „Nie geprüft“ |

Alles ist deterministisch: gleiche Einstellungen und gleicher Seed ergeben dieselbe Datei.

## Was du selbst gehört hast

- Goa neu (Hörpaket vom 15.11.2026): „hört sich top an“. Das Paket kam aus dem Code, nicht aus der exe.
- Erster Test am PC am 9.11.2026: daraus kamen Lautstärke-Regler, Loop-Vorschau, Goa als Clip-Generator, Blaster-Ausklang, Acid-Vorschau.

## Nie geprüft (ehrlich)

- Die letzte exe auf deinem PC: Start, Ton, Aussehen der zwei neuen Goa-Regler, Schließen während eine Vorschau rechnet. Automatisch getestet ist das nur ohne Bildschirm und auf GitHub-Rechnern.
- Alles in Ableton Live: Import von Clips, Goa-MIDI auf deinen Synths (Slides brauchen einen Mono-Synth mit Legato und Glide; Akzente brauchen Velocity auf dem Filter), Warp langer Riser (#484). In `contracts/capabilities.json` steht nichts davon auf `tested`.
- Der Copilot mit echtem Claude-Aufruf aus der exe. Er braucht ein eigenes Claude-Konto oder einen API-Schlüssel; ohne das ist die Copilot-Seite ohne Funktion. Alles andere läuft ohne Claude.
- Hörtests für Kick-Schlüsselwörter, Hat, Snare, Rim, Bass, Clap-xtreme (#356) und die Punkte 20–25 in `docs/USER_GUIDE.md`.
- Das Rauschen bei allen Samples (#556): die Dateien messen sauber; ob du es auch in Live oder einem anderen Player hörst, wurde nie beantwortet.

## Gebaut, aber ohne Oberfläche

- Referenz-Steuerung v2 (Fit für Kick und Bass, #564): rechnet aus einer Referenz-Datei Parameter mit Vorher/Nachher-Bericht. Es gibt keinen Knopf dafür. Bekannte Schwächen stehen in #577.

## Offen geblieben

Die Liste steht im obersten Block von `docs/CURRENT_STATE.md`. Das Wichtigste: #577 (Fit-Nachträge), #556 (Rauschen), #522 (Referenz v2 für alle Kategorien und Oberfläche), #521 (Planer übernimmt Goa-Optionen), #519 (Copilot liest das Live-Tempo), Hall in der Goa-Vorschau (nur falls dir Tiefe fehlt).

## Wenn du später weitermachen willst

- Mit Claude: eine neue Sitzung im Projekt öffnen und schreiben: „Du bist der Lead von AbeltonGod. Lies docs/LEAD_HANDOFF.md, dann CLAUDE.md und den oberen Block von docs/CURRENT_STATE.md, und mach dort weiter.“
- Ohne Claude: der Code läuft mit Python 3.11+ (`pip install -e ".[dev,gui]"`, `pytest`, `ruff check .`); Einrichtung unter Windows steht im README.
