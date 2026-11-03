# Rim und Bass in Live importieren (Testrezept)

**Nicht auf deinem Rechner geprüft.** Bisher lief dieser Weg nur gegen einen simulierten AbletonOSC-Server in CI. Das Script sendet dieselben Befehle wie bei Kick, Clap und Hat (`create_audio_clip`, ggf. `create_audio_track`, Zurücklesen); es gibt keine neue Ableton-Funktion und es wird nichts umbenannt. Das Script erkennt die Kategorie (`rim` oder `bass`) aus dem Sidecar und prüft, dass die WAV im richtigen Ordner des Projekts liegt:

| Kategorie | Ordner im Projekt |
| --- | --- |
| `rim` | `Samples\Drums\Rims` |
| `bass` | `Samples\Bass` (kein Drum, deshalb nicht unter `Drums`) |

Voraussetzung: Erweiterung installiert (`ABLETONOSC_WINDOWS.md`, Abschnitt 7.1), Live mit dem **Test-Set** offen, gespeichert (Projektordner mit `.als`).

1. **Sample erzeugen** (ändert nichts in Live). In PowerShell im AbeltonGod-Ordner, einmal für Rim, einmal für Bass:
   ```powershell
   python -c "from library import place_sample; print(place_sample('rim', {'schema_version': '0.1', 'seed': 1}, r'C:\voller\Pfad\Test Project'))"
   python -c "from library import place_sample; print(place_sample('bass', {'schema_version': '0.1', 'seed': 1, 'gate_ms': 400}, r'C:\voller\Pfad\Test Project'))"
   ```
   Jeder Befehl druckt den Pfad der WAV.

2. **Importieren** (je Sample):
   ```powershell
   python scripts/live_import.py "<Pfad der WAV>"
   ```
   Erwartet: im Plan steht `Sample: rim: <Dateiname>` bzw. `Sample: bass: <Dateiname>`, im Ergebnis-Block `sample_category: rim` bzw. `bass`. Fragen wie beim Kick beantworten (Test-Set `y`, Spur wählen oder `n`, ausführen `y`). Bei der Undo-Frage `Enter`, dann den Clip in Live starten: „Spielt der Rim?“ / „Spielt der Bass?“ ehrlich beantworten.

3. **Ablehnung prüfen (ändert nichts in Live).** Die Rim-WAV samt `.json` aus `Samples\Drums\Rims\` nach `Samples\Bass\` kopieren (Ordner ggf. anlegen) und das Script mit dem kopierten Pfad starten. Erwartet: `FEHLER mit der Datei: ... Rims ...` und `Es wurde nichts in Live geändert`, noch bevor eine Verbindung aufgebaut wird.

Den Ergebnis-Block aus Schritt 2 (beide) und die Meldung aus Schritt 3 als Kommentar in Issue #129 einfügen. `contracts/capabilities.json` ändert sich dadurch nicht.
