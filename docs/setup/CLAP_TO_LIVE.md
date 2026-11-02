# Clap in Live importieren (Testrezept, Phase 03)

**Nicht auf deinem Rechner geprüft.** Bisher lief dieser Weg nur gegen einen simulierten AbletonOSC-Server in CI. Das Script sendet dieselben Befehle wie beim Kick (`create_audio_clip`, ggf. `create_audio_track`, Zurücklesen); es gibt keine neue Ableton-Funktion. Live benennt den Clip nach der Datei und benennt eine Standard-Audiospur selbst um; das Script benennt nichts um.

Voraussetzung: Erweiterung installiert (`ABLETONOSC_WINDOWS.md`, Abschnitt 7.1), Live mit dem **Test-Set** offen, gespeichert (Projektordner mit `.als`).

1. **Clap erzeugen.** In PowerShell im AbeltonGod-Ordner (legt WAV und `.json` unter `<Projektordner>\Samples\Drums\Claps\` ab; ändert nichts in Live):
   ```powershell
   python -c "from library import place_sample; print(place_sample('clap', {'schema_version': '0.1', 'seed': 1}, r'C:\voller\Pfad\Test Project'))"
   ```
   Der Befehl druckt den Pfad der WAV. Den Pfad für Schritt 2 kopieren.

2. **Importieren.**
   ```powershell
   python scripts/live_import.py "C:\voller\Pfad\Test Project\Samples\Drums\Claps\<Dateiname>.wav"
   ```
   Erwartet: im Plan steht `Sample: clap: <Dateiname>`, im Ergebnis-Block `sample_category: clap`. Fragen wie beim Kick beantworten (Test-Set `y`, Spur wählen oder `n`, ausführen `y`). Bei der Undo-Frage `Enter`, dann den Clip in Live starten: „Spielt der Clap?“ ehrlich beantworten.

3. **Ablehnung prüfen (ändert nichts in Live).** Dieselbe WAV in den Ordner `Kicks` kopieren (Datei und `.json`) und das Script mit dem kopierten Pfad starten. Erwartet: `FEHLER mit der Datei: ... Claps ...` und `Es wurde nichts in Live geändert`, noch bevor eine Verbindung aufgebaut wird.

Den Ergebnis-Block aus Schritt 2 und die Meldung aus Schritt 3 als Kommentar in Issue #129 einfügen (Evidenz für den Clap-Import; `contracts/capabilities.json` ändert sich dadurch nicht).

---

# Clap via the copilot (generate_sample) - test recipe for the user's PC

Issue #258. Needs the chat started as usual with a project folder (see `KICK_TO_LIVE.md`).
CI ran only a fake model and a fake AbletonOSC; **no real Claude call and no Ableton test has
been done for this tool.** Your run is the first one. Write the result into issue #258.

1. Start the chat with your Live project folder, as for the kick.
2. Type: `Mach mir eine kurze, helle Klatsche.`
   Expect: one tool call `generate_sample` (category `clap`), a `clap-1` id, two files (WAV +
   JSON) in the clap folder of the project, Live unchanged, no question for approval.
3. Type: `Mach sie 15 Prozent kuerzer und gib mir drei Varianten.`
   Expect: a call with a valid `adjust` entry (e.g. `length_ms`) and three claps (6 files), or
   a clear refusal that names the wrong key or value, after which Claude tries again.
4. Type: `Importiere die zweite auf Spur 3.`
   Expect: the usual question before the Live write; after "j" the clap lies in the clip slot.
5. Type: `Mach den Hall auf 5000.` (out of range)
   Expect: a refusal naming the allowed range (`room` 0 to 1), no new file, nothing clamped.
6. Report in the issue: the tool-call arguments Claude sent (chat log), how often it needed a
   repair round, and whether the clap sounds as asked (your ear, not ours).

Limits to know: at most 6 claps per request (the real policy, `kick_generation` in
`config/guard-policy.json`, allows 12 files per request; 8 claps would be 16 files and are
refused with the numbers). `prompt` must stay empty for the clap: there is no keyword parser
for it yet.
