# AbletonOSC unter Windows einrichten (Live 12 Standard)

AbletonOSC ist ein Remote Script (MIT-Lizenz), das Ableton Live über OSC auf `localhost` steuerbar macht. AbeltonGod spricht darüber mit Live (Entscheidung D-001). Max for Live wird nicht gebraucht.

Diese Anleitung wurde **noch nicht auf deinem Rechner durchgespielt**. Grundlage: AbletonOSC-README und -Quellcode, Stand Commit `0ca68214` (19.11.2025). Wenn ein Schritt bei dir anders aussieht, schreib es bitte in Issue #5.

## 1. Herunterladen

1. Öffne <https://github.com/ideoforms/AbletonOSC/archive/refs/heads/master.zip> und lade die ZIP-Datei herunter.
2. Entpacke sie. Du bekommst einen Ordner `AbletonOSC-master`.
3. Benenne ihn um in **`AbletonOSC`** (genau so geschrieben). Live erkennt das Script sonst nicht unter dem richtigen Namen.

## 2. In den Remote-Scripts-Ordner kopieren

Kopiere den Ordner `AbletonOSC` nach:

```
C:\Users\<dein Name>\Documents\Ableton\User Library\Remote Scripts\
```

- Gibt es den Ordner `Remote Scripts` nicht, lege ihn an.
- Liegt deine User Library woanders (z. B. auf einer anderen Platte), steht der Pfad in Live unter *Optionen → Einstellungen → Bibliothek*.
- Danach muss es diese Datei geben: `...\Remote Scripts\AbletonOSC\__init__.py`. Liegt dazwischen noch ein zweiter `AbletonOSC`-Ordner, war die ZIP verschachtelt — dann eine Ebene hochschieben.

## 3. In Live auswählen

1. Live **neu starten** (Remote Scripts werden nur beim Start gelesen).
2. *Optionen → Einstellungen → Link, Tempo & MIDI* (in älteren Versionen heißt das Menü „Voreinstellungen“).
3. In einer freien Zeile unter **Control Surface** `AbletonOSC` wählen. Input und Output bleiben auf *Keine*.
4. Unten in der Statusleiste von Live sollte kurz erscheinen: **„AbletonOSC: Listening for OSC on port 11000“**.

Steht dort stattdessen „Couldn't bind to port 11000“, benutzt schon ein anderes Programm diesen Port (z. B. ein zweites OSC-Script). Dann dieses Programm schließen oder die Zeile in Live wieder auf *Keine* stellen.

## 4. Verbindung prüfen

Im Projektordner, im aktivierten venv (siehe README):

```powershell
python -c "from bridge.osc_client import OscTransport; t = OscTransport(); t.ping(); print('AbletonOSC antwortet')"
```

- **Erfolg:** `AbletonOSC antwortet`, und Live zeigt kurz „Received OSC OK“.
- **Keine Antwort:** Eine Fehlermeldung nennt die möglichen Ursachen. Vom Python-Programm aus lässt sich nicht unterscheiden, ob Live geschlossen ist oder AbletonOSC nicht ausgewählt ist — beides prüfen. Ein offener Dialog in Live (z. B. Speichern) kann Antworten ebenfalls aufhalten.
- **„cannot bind reply port 127.0.0.1:11001“:** Ein anderes Programm empfängt schon auf Port 11001 (z. B. ein zweites Terminal mit demselben Befehl). Dieses schließen.

Dieser Test liest und ändert nichts im Set. Der ausführliche Check mit Tempo, Spuren und einer rückgängig gemachten Mute-Änderung kommt in #5 (`scripts/bridge_check.py`).

## 5. Wo die Logs liegen

| Log | Ort | Wofür |
| --- | --- | --- |
| AbletonOSC | `...\Remote Scripts\AbletonOSC\logs\abletonosc.log` | Jede empfangene Nachricht und jeder Fehler des Scripts. |
| Live | `%APPDATA%\Ableton\Live <Version>\Preferences\Log.txt` | Fehler beim Laden des Scripts (z. B. Python-Fehler beim Start). |

Den Live-Ordner öffnest du am schnellsten mit `Win + R` → `%APPDATA%\Ableton` → Enter. Im Ordner deiner Live-Version liegt `Preferences\Log.txt`. Bei Problemen die letzten ~30 Zeilen beider Logs ins Issue kopieren.

## Gut zu wissen

- **Ports:** Live empfängt auf 11000, AbeltonGod empfängt die Antworten auf 11001. Beides läuft nur über `127.0.0.1`; die Windows-Firewall fragt dafür normalerweise nicht. Andere Ports nur ändern, wenn du sie auch im Script änderst (`AbletonOSC\abletonosc\constants.py`); in AbeltonGod stehen sie dann in `.env` (`ABLETON_OSC_SEND_PORT`, `ABLETON_OSC_RECEIVE_PORT`).
- **Nur ein Empfänger:** AbletonOSC schickt jede Antwort fest an Port 11001. Es kann also immer nur ein Programm gleichzeitig mit AbletonOSC reden.
- **Live-Version:** AbletonOSC meldet nur Haupt- und Nebenversion (z. B. 12.3). Die genaue Version (Hilfe → Über Live) bitte in Issue #5 notieren — der spätere Sample-Import braucht mindestens 12.0.5.
- **Updates:** Wenn du AbletonOSC später aktualisierst, ersetzt du einfach den Ordner. Für Phase 03 kann eine kleine Erweiterung nötig werden (siehe `docs/research/2026-10-28_abletonosc-protocol-and-create-audio-clip.md`); sie müsste nach einem Update neu eingespielt werden.
- **Sicherheit:** Nur mit einem Test-Set arbeiten, nicht mit echten Projekten, solange die Bridge nicht auf deinem Rechner geprüft ist.
