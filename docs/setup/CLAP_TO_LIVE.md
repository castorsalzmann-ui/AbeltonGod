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
