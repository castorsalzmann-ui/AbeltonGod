# Snare in Live importieren (Testrezept)

**Nicht auf deinem Rechner geprüft.** Bisher lief dieser Weg nur gegen einen simulierten AbletonOSC-Server in CI. Das Script sendet dieselben Befehle wie bei Kick, Clap, Hat, Rim und Bass (`create_audio_clip`, ggf. `create_audio_track`, Zurücklesen); es gibt keine neue Ableton-Funktion und es wird nichts umbenannt. Das Script erkennt die Kategorie `snare` aus dem Sidecar und prüft, dass die WAV im richtigen Ordner des Projekts liegt:

| Kategorie | Ordner im Projekt |
| --- | --- |
| `snare` | `Samples\Drums\Snares` |

Voraussetzung: Erweiterung installiert (`ABLETONOSC_WINDOWS.md`, Abschnitt 7.1), Live mit dem **Test-Set** offen, gespeichert (Projektordner mit `.als`).

1. **Sample erzeugen** (ändert nichts in Live). In PowerShell im AbeltonGod-Ordner:
   ```powershell
   python -c "from library import place_sample; print(place_sample('snare', {'schema_version': '0.1', 'seed': 1}, r'C:\voller\Pfad\Test Project'))"
   ```
   Der Befehl druckt den Pfad der WAV.

2. **Importieren**:
   ```powershell
   python scripts/live_import.py "<Pfad der WAV>"
   ```
   Erwartet: im Plan steht `Sample: snare: <Dateiname>`, im Ergebnis-Block `sample_category: snare`. Fragen wie beim Kick beantworten (Test-Set `y`, Spur wählen oder `n`, ausführen `y`). Bei der Undo-Frage `Enter`, dann den Clip in Live starten: „Spielt der Snare?“ ehrlich beantworten.

3. **Ablehnung prüfen (ändert nichts in Live).** Die Snare-WAV samt `.json` aus `Samples\Drums\Snares\` nach `Samples\Drums\Claps\` kopieren (Ordner ggf. anlegen) und das Script mit dem kopierten Pfad starten. Erwartet: `FEHLER mit der Datei: ... Snares ...` und `Es wurde nichts in Live geändert`, noch bevor eine Verbindung aufgebaut wird.

Den Ergebnis-Block aus Schritt 2 und die Meldung aus Schritt 3 als Kommentar in Issue #129 einfügen. `contracts/capabilities.json` ändert sich dadurch nicht.
