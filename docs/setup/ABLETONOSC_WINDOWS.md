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

Im Projektordner, im aktivierten venv (siehe README). Der Projektordner muss auf dem Branch `main` und aktuell sein (`git branch --show-current` zeigt `main`; sonst erst die `git`-Befehle aus Abschnitt 5 ausführen) — sonst endet der Test mit `ModuleNotFoundError`.

```powershell
python -c "from bridge.osc_client import AbletonBridge; AbletonBridge.connect().ping(); print('AbletonOSC antwortet')"
```

- **Erfolg:** `AbletonOSC antwortet`. In Live ändert sich dabei nichts (der Test liest nur zweimal das Tempo).
- **Keine Antwort:** Eine Fehlermeldung nennt die möglichen Ursachen. Vom Python-Programm aus lässt sich nicht unterscheiden, ob Live geschlossen ist oder AbletonOSC nicht ausgewählt ist — beides prüfen. Ein offener Dialog in Live (z. B. Speichern) kann Antworten ebenfalls aufhalten.
- **„cannot bind reply port 127.0.0.1:11001“:** Ein anderes Programm empfängt schon auf Port 11001 (z. B. ein zweites Terminal mit demselben Befehl). Dieses schließen.

Dieser Test ändert nichts im Set. Der ausführliche Check mit Tempo, Spuren und einer rückgängig gemachten Mute-Änderung steht in Abschnitt 5.

## 5. Bridge-Check ausführen (Issue #5)

Der Check liest ein paar Werte aus Live. Danach — nur wenn du zweimal mit `y` bestätigst — schaltet er eine Spur kurz stumm, wieder laut, wieder stumm und schickt dann einmal **Undo** an Live. Vorher und nachher liest er Tempo, Taktart, alle Spurnamen und den Mute-Zustand aller Spuren und vergleicht sie.

**Undo-Risiko:** Undo nimmt den *letzten* Schritt in Lives Widerrufen-Historie zurück. Ob Live die Mute-Änderung des Scripts dort einträgt, ist genau das, was der Check prüft. Wenn nicht, nimmt Undo deine letzte eigene Aktion zurück (z. B. eine eingefügte Spur). Das Script erkennt das an Tempo, Taktart, Spuranzahl, Namen und Mute-Zuständen, meldet `FAIL` und schickt nichts mehr — rückgängig machen kann es das aber nicht. Darum die Vorbereitung unten genau so machen.

**Was der Vergleich nicht sieht:** Clips, Geräte und Automation; Return- und Master-Spuren (AbletonOSC liefert nur die normalen Spuren); das Vertauschen zweier Spuren mit gleichem Namen und gleichem Mute-Zustand. Bei vielen Spuren dauert der Vergleich länger (zweimal eine Anfrage pro Spur, in Live nicht gemessen) — für ein Test-Set mit 2–3 Spuren unerheblich.

**Vorbereitung:**
1. In Live ein **neues Test-Set** anlegen (*Datei → Neues Live-Set*), zwei oder drei Spuren genügen, und es z. B. als `AbeltonGod-Test` speichern. Nicht mit einem echten Projekt ausführen.
2. Das Set **schließen und neu öffnen** (über das Datei-Menü, z. B. die Liste der zuletzt verwendeten Sets; die genaue deutsche Menübezeichnung ist hier nicht geprüft). Laut Live-12-Handbuch (Abschnitt „Undo History“, deutsches Handbuch „Widerrufen-Historie“) leert Live beim Öffnen eines Sets diese Liste. In diesem Projekt ist das noch nicht in Live geprüft — schau nach dem Öffnen kurz in die Widerrufen-Historie (*Strg + Alt + Z*; Menü *Ansicht → Widerrufen-Historie* laut deutschem Handbuch, in deiner Live-Oberfläche noch nicht geprüft; englische Oberfläche *View → Undo History*), ob die Liste leer ist. Dort nur schauen, keinen Eintrag anklicken: laut Handbuch setzt ein Klick das Set auf diesen Stand zurück.
3. **Transport gestoppt, keine Tempo-Automation, Link/Sync aus:** Wiedergabe stoppen, im Test-Set keine Tempo-Automation, und in Live *Link* sowie externen Sync (MIDI-Clock) ausschalten. Sonst kann sich das Tempo während des Checks von selbst ändern, und der Vergleich nach dem Undo meldet `FAIL`, obwohl Undo funktioniert hat.
4. Danach **nichts mehr am Set ändern**, bis das Script fertig ist.

In PowerShell, im Projektordner. Zuerst prüfen, auf welchem Branch der Projektordner steht:

```powershell
git branch --show-current
```

Steht dort etwas anderes als `main` (z. B. `phase-00/pytest-xdist`), holt `git pull` **nicht** den aktuellen Stand — dann meldet es „Already up to date“, und das Script findet später Module nicht (z. B. `ModuleNotFoundError: No module named 'bridge.osc_client'`). Darum immer erst auf `main` wechseln:

```powershell
git switch main
git status
git pull
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python scripts/bridge_check.py
```

Nach `git status` sollte oben `On branch main` stehen (bei deutscher Sprache: `Auf Branch main`). Bricht `git switch main` mit einem Hinweis auf lokale Änderungen ab, nichts erzwingen, sondern die Meldung in Issue #5 kopieren.

Das Script fragt dreimal:

1. `Ist das geöffnete Set ein eigenes TEST-Set (kein echtes Projekt)? [y/N]` — nur `y`, wenn es wirklich das Test-Set ist. Alles andere (auch Enter) beendet das Script nach dem Lesen, ohne etwas zu ändern.
2. `Welche Spur soll kurz stummgeschaltet werden? Index 0-… [Enter = 0 '…']` — Nummer der Spur oder Enter für die erste. Nach drei ungültigen Eingaben überspringt das Script die Änderung.
3. Es zeigt die geplanten Schritte und den Undo-Hinweis an. `Diese Änderungen jetzt ausführen? [y/N]` — `y` nur, wenn du das Set wie oben frisch geöffnet und nicht verändert hast.

**Erwartete Ausgabe (gekürzt):**

```text
Verbindung zu AbletonOSC (127.0.0.1:11000) steht.

--- Teil 1: nur lesen (ändert nichts) ---
Live-Version (laut API, nur Haupt.Neben): 12.4
Tempo: 120 BPM
Taktart: 4/4
Spuren (2):
  0: 1-Audio
  1: 2-MIDI
...
  R1: Spur 0 ist stumm (erwartet: stumm) OK
  R2: Spur 0 ist nicht stumm (erwartet: nicht stumm) OK
  R3: Spur 0 ist stumm (erwartet: stumm) OK
  R4: Spur 0 ist nicht stumm (erwartet: nicht stumm) OK
Undo hat die letzte Mute-Änderung zurückgenommen. Tempo, Taktart, Spuranzahl, Spurnamen und Mute-Zustand aller Spuren sind wie vorher.
(Nicht prüfen kann das Script: Clips, Geräte, Automation sowie Return- und Master-Spuren.)
```

Im Ergebnis-Block steht hinter `song.undo: PASS …` ein `note=checked: …`, der genau sagt, was verglichen wurde.

Bei einem großen Set kann eine Anfrage länger als 1 Sekunde dauern. Meldet das Script „antwortet nicht“, obwohl Live offen ist, einmal mit `python scripts/bridge_check.py --timeout 3` wiederholen.

In Live siehst du den Mute-Knopf der Spur kurz an- und ausgehen. Die Live-Version zeigt nur `12.4`, weil AbletonOSC keine Patch-Nummer liefert; die genaue Version (12.4.5) steht schon in Issue #5.

**Was ins Issue gehört:** Am Ende steht ein Block zwischen ` ```text ` und ` ``` `, beginnend mit `AbeltonGod bridge_check result`. Diesen Block **komplett** (mit den drei Backticks) als Kommentar in Issue #5 einfügen. Steht irgendwo `FAIL` oder `ABWEICHUNG`, bitte zusätzlich die letzten ~30 Zeilen von `abletonosc.log` (siehe Abschnitt 6) anhängen.

**Fehlerfälle prüfen** (Abnahme von #5, je ein Durchlauf genügt):

| Test | So geht's | Erwartet |
| --- | --- | --- |
| Live geschlossen | Live beenden, `python scripts/bridge_check.py` | `FEHLER: AbletonOSC antwortet nicht …` mit Liste der Ursachen, Exit-Code 2 |
| AbletonOSC nicht ausgewählt | Live offen, Control Surface auf *Keine*, Script starten | dieselbe Meldung (beides ist von außen nicht zu unterscheiden), Exit-Code 2 |
| Port 11001 belegt | Zweites PowerShell-Fenster: `python -c "import socket,time; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('127.0.0.1',11001)); time.sleep(60)"`, im ersten das Script starten | `FEHLER: Port 11001 (127.0.0.1) ist schon belegt.`, Exit-Code 3 |

Den Exit-Code zeigt PowerShell direkt danach mit `$LASTEXITCODE`. Schreib bitte ins Issue, ob die Meldungen für dich verständlich waren.

**Wenn etwas schiefgeht:** Bei einem Fehler, einer `ABWEICHUNG` oder wenn du mit *Strg + C* abbrichst, sendet das Script keine weiteren Änderungen und kein (weiteres) Undo. Es nennt den ursprünglichen Zustand der Spur, liest den jetzigen einmal zurück und sagt dir, ob du den Mute-Knopf von Hand zurückstellen musst. Der Ergebnis-Block wird trotzdem ausgegeben (Exit-Code 130 bei *Strg + C* — auch an einer der drei Fragen; dann wurde noch nichts geändert). Noch nicht geprüft ist, ob *Strg + C* an einer Frage unter Python 3.14 auf Windows wirklich zu Exit-Code 130 führt: Manche ältere Python-Versionen werten *Strg + C* in einer Eingabe als Eingabe-Ende, dann endet das Script wie bei „nein“ mit Exit-Code 0. Sicher ist beides, denn an den Fragen wurde noch nichts gesendet. Optional prüfen: an der ersten Frage *Strg + C* drücken, danach `echo $LASTEXITCODE` eingeben (erwartet `130`) und das Ergebnis in Issue #5 notieren. Unterscheiden sich nach dem Undo **nur** Tempo und/oder Taktart, meldet das Script `FEHLER` (im Ergebnis-Block `song.undo: FAIL`) ohne Schuldzuweisung: Entweder hat sich das Tempo von selbst geändert (Tempo-Automation, Link, externe MIDI-Clock), oder Undo hat eine frühere Tempo-Änderung zurückgenommen. Dann die Vorbereitung (Punkt 3) prüfen, das Set neu öffnen und den Check wiederholen. Meldet es nach dem Undo Unterschiede bei Spuren oder Namen, zeigt die Widerrufen-Historie (*Strg + Alt + Z*; Menü *Ansicht → Widerrufen-Historie*, englisch *View → Undo History*) in Live, welcher Schritt zurückgenommen wurde; dort lässt er sich wiederherstellen. *Strg + Z* in Live nur verwenden, wenn du sicher bist, was es zurücknimmt.

## 6. Wo die Logs liegen

| Log | Ort | Wofür |
| --- | --- | --- |
| AbletonOSC | `...\Remote Scripts\AbletonOSC\logs\abletonosc.log` | Jede empfangene Nachricht und jeder Fehler des Scripts. |
| Live | `%APPDATA%\Ableton\Live <Version>\Preferences\Log.txt` | Fehler beim Laden des Scripts (z. B. Python-Fehler beim Start). |

Zeilen wie `[WARNING] AbletonOSC: Non-fatal socket error … ConnectionResetError: [WinError 10054]` sind harmlos: AbletonOSC hat eine Nachricht an Port 11001 geschickt (z. B. beim Start von Live), während dort kein Programm zuhörte, und Windows meldet das beim nächsten Empfang. AbletonOSC arbeitet danach normal weiter.

Den Live-Ordner öffnest du am schnellsten mit `Win + R` → `%APPDATA%\Ableton` → Enter. Im Ordner deiner Live-Version liegt `Preferences\Log.txt`. Bei Problemen die letzten ~30 Zeilen beider Logs ins Issue kopieren.

## Gut zu wissen

- **Firewall:** AbletonOSC lauscht auf *allen* Netzwerkadaptern (`0.0.0.0:11000`), nicht nur auf `127.0.0.1`. Fragt die Windows-Firewall beim Start von Live nach Netzwerkzugriff für Live, wähle **„Abbrechen“ / nicht zulassen**. AbeltonGod braucht nur `127.0.0.1`, und das blockiert die Firewall nicht. Lässt du den Zugriff zu, kann jedes Gerät im selben Netz dein Live-Set über OSC steuern. Hast du schon zugelassen, entferne die Regel unter *Windows-Sicherheit → Firewall → Zugriff von Apps durch die Firewall zulassen*. Prüf danach, ob der Ping-Test oben noch geht.
- **Ports:** Live empfängt auf 11000, AbeltonGod empfängt die Antworten auf 11001 (nur `127.0.0.1`). Andere Ports nur ändern, wenn du sie auch im Script änderst (`AbletonOSC\abletonosc\constants.py`); in AbeltonGod stehen sie dann in `.env` (`ABLETON_OSC_SEND_PORT`, `ABLETON_OSC_RECEIVE_PORT`).
- **Nur ein Empfänger:** AbletonOSC schickt jede Antwort fest an Port 11001. Es kann also immer nur ein Programm gleichzeitig mit AbletonOSC reden.
- **Live-Version:** AbletonOSC meldet nur Haupt- und Nebenversion (z. B. 12.3). Die genaue Version (Hilfe → Über Live) bitte in Issue #5 notieren — der spätere Sample-Import braucht mindestens 12.0.5.
- **Updates:** Wenn du AbletonOSC später aktualisierst, ersetzt du einfach den Ordner. Die AbeltonGod-Erweiterung (Abschnitt 7) ist danach weg und muss neu installiert werden; das Install-Script erkennt eine neue AbletonOSC-Version und ändert sie dann nicht.
- **Sicherheit:** Nur mit einem Test-Set arbeiten, nicht mit echten Projekten, solange die Bridge nicht auf deinem Rechner geprüft ist.

## 7. Kick als Clip importieren (Phase 03, Issue #50)

Noch **nicht auf deinem Rechner geprüft**. AbletonOSC selbst kennt keinen Befehl, um eine WAV-Datei als Clip anzulegen. AbeltonGod fügt deshalb in deiner AbletonOSC-Kopie **ein Wort** hinzu: `"create_audio_clip"` in die Liste `methods` der Datei `abletonosc\clip_slot.py`. Danach versteht AbletonOSC den Befehl `/live/clip_slot/create_audio_clip` und ruft Lives `ClipSlot.create_audio_clip(Pfad)` auf. Nichts von AbletonOSC wird ins AbeltonGod-Repo kopiert.

### 7.1 Erweiterung installieren

1. **Live beenden.**
2. In PowerShell, im Projektordner:

```powershell
git switch main
git pull
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python scripts/install_abletonosc_extension.py --check
```

Erwartet (Pfad mit deinem Benutzernamen; seit Script 0.2.0 zwei Dateien, die zweite für den Arrangement-Check in Abschnitt 8):

```text
AbeltonGod install_abletonosc_extension 0.2.0
AbletonOSC-Ordner: C:\Users\<du>\Documents\Ableton\User Library\Remote Scripts\AbletonOSC
Datei: C:\Users\<du>\Documents\Ableton\User Library\Remote Scripts\AbletonOSC\abletonosc\clip_slot.py
Zustand: original (sha256 989f9f6a6631fd04598fff0b278b9d844e03b3e211ae9b23d293e985b22d4aed)
Datei: C:\Users\<du>\Documents\Ableton\User Library\Remote Scripts\AbletonOSC\abletonosc\track.py
Zustand: original (sha256 512a92ff0a08c7ba8276c3b5f06fbff3f55863b18a51bef3ee0837eceb55ed4a)
Nur geprüft (--check), nichts geändert.
```

Hast du die Erweiterung schon mit Script 0.1.0 installiert (Issue #50), steht bei `clip_slot.py` `Zustand: patched (sha256 7ff30f46…)`; das Script ergänzt dann nur `track.py`.

- Steht `Zustand: unknown`, hast du eine andere AbletonOSC-Version als die geprüfte (Commit `0ca68214`). Das Script ändert dann **keine** der beiden Dateien. Bitte die Ausgabe in Issue #140 einfügen.
- Liegt AbletonOSC woanders: `--abletonosc-dir "D:\...\Remote Scripts\AbletonOSC"` anhängen.

3. Installieren:

```powershell
python scripts/install_abletonosc_extension.py
```

Es zeigt die geplante Änderung und fragt `Live ist geschlossen. Jetzt installieren? [y/N]` — nur `y` installiert. Erwartet am Ende: `Installiert: clip_slot.py, track.py. Sicherungen: ...\clip_slot.py.abeltongod-orig, ...\track.py.abeltongod-orig` (oder nur `track.py`, wenn `clip_slot.py` schon installiert war) und `Jetzt Live neu starten.`

Gibt es schon eine Sicherung `<Datei>.abeltongod-orig`, die nicht Byte für Byte der jetzigen Datei entspricht (z. B. von einem abgebrochenen Lauf oder mit anderen Zeilenenden), meldet das Script `FEHLER: Die vorhandene Sicherung …` und ändert an keiner Datei etwas. Dann die Sicherung wegschieben und die Ausgabe in Issue #140 einfügen. Bricht das Schreiben zwischen den beiden Dateien ab (z. B. Platte voll, *Strg + C*), ist jede Datei entweder unverändert oder vollständig geändert; `--check` zeigt den Stand, ein neuer Lauf ergänzt den Rest.

4. **Live starten.** In der Statusleiste sollte wieder „AbletonOSC: Listening for OSC on port 11000“ erscheinen.

**Rückgängig machen:** Live beenden, `python scripts/install_abletonosc_extension.py --uninstall`, mit `y` bestätigen, Live starten. Die Sicherung bleibt liegen.

### 7.2 Import testen

**Vorbereitung:** neues Test-Set (hat es keine Audiospur, beim Ziel später `n` für eine neue Audiospur eingeben), speichern, schließen und neu öffnen (siehe Abschnitt 5, Vorbereitung 1–4). Eine WAV-Datei bereitlegen, z. B. einen Kick aus Phase 01:

```powershell
python -m audio_engine.kick --preset centre --out "$env:USERPROFILE\Music\AbeltonGod-Test"
dir "$env:USERPROFILE\Music\AbeltonGod-Test\*.wav"
```

(wie im Hörtest `LISTENING_TEST_01.md`; jede andere WAV mit absolutem Pfad geht auch). Den vollen Pfad der WAV aus der `dir`-Liste nehmen. Dann:

```powershell
python scripts/live_import.py "C:\voller\Pfad\zur\kick.wav"
```

Das Script

1. prüft die Datei (absoluter Pfad, `.wav`, gültiger WAV-Kopf),
2. liest Live-Version, Spuren (mit „Audio“ / „keine Audiospur“) und Anzahl der Szenen,
3. prüft, ob die Erweiterung da ist. Dazu sendet es den Import-Befehl **ohne** Argumente; AbletonOSC bricht dabei ab, bevor es das Set anfasst. Im `abletonosc.log` steht danach pro Lauf eine Zeile `[ERROR] AbletonOSC: Error handling OSC message: list index out of range` (darunter eine `[WARNING]`-Zeile mit dem Python-Traceback, der `clip_slot.py` nennt) — die ist erwartet. Weil AbletonOSC jede Nachricht protokolliert, steht diese Zeile meist **nicht** unter den letzten Zeilen. Zum Finden in PowerShell:

```powershell
Select-String -Path "$env:USERPROFILE\Documents\Ableton\User Library\Remote Scripts\AbletonOSC\logs\abletonosc.log" -Pattern "create_audio_clip|Error handling OSC message" | Select-Object -Last 20
```

(Liegt deine User Library woanders, den Pfad anpassen.) Die Ausgabe zeigt die Zeilen mit dem Import-Befehl und die Fehlerzeilen samt Zeilennummer.
4. fragt: `Ist das geöffnete Set ein eigenes TEST-Set (kein echtes Projekt)? [y/N]`
5. fragt das Ziel: Nummer einer Audiospur oder `n` für eine neue Audiospur am Ende. MIDI-Spuren lehnt es ab. Es nimmt die erste freie Zelle (oder `--slot <Nummer>`) und überschreibt nie einen Clip.
6. zeigt die geplanten Änderungen und fragt `Diese Änderungen jetzt ausführen? [y/N]`
7. importiert, liest die Zellen und den Dateipfad des Clips zurück,
8. fragt **sofort** `Import jetzt per Undo zurücknehmen, OHNE Anhören? [y/N]`. Undo oder Anhören, nicht beides: eine Aktion in Live zwischen Import und Undo (ob schon das Starten eines Clips zählt, ist nicht geprüft) kann dazu führen, dass Undo etwas anderes zurücknimmt oder das Script kein Undo sendet (#50, Läufe 2 und 3).
   - `y`: Undo sofort. Bis dahin in Live **nichts** anklicken oder starten. Undo wird nur gesendet, wenn das Set noch genau so aussieht wie nach dem Import, und danach zurückgelesen. Im Ergebnis-Block steht dann `user_hears_kick: not asked (undo chosen before listening)`.
   - Enter (nein): der Clip bleibt. Dann fragt es `Spielt der Kick? [y/n]` — dafür in Live die Zelle starten und hinhören. Danach steht da, wie du Clip (und ggf. neue Spur) von Hand entfernst: Zelle bzw. Spurkopf anklicken, *Entf*.

   Geht ein Undo schief (verweigert oder ohne sichtbare Wirkung) oder brichst du nach dem Import mit *Strg + C* ab, sendet das Script nichts mehr und nennt dieselben Schritte zum Entfernen von Hand (nach dem letzten Zurücklesen; ist der Clip dort schon weg, steht das dabei).

**Erwartete Ausgabe (gekürzt, Ziel Spur 0, leeres Set, Undo `y`):**

```text
AbeltonGod live_import 0.3.0

Verbindung zu AbletonOSC (127.0.0.1:11000) steht.

Live-Version (laut API): 12.4  Szenen: 8
Spuren (2):
  0: 1-Audio  [Audio]
  1: 2-MIDI  [keine Audiospur]
AbeltonGod-Erweiterung: vorhanden.
...
OK: Clip liegt in Spur 0, Zelle 0. Live meldet als Datei:
  C:\voller\Pfad\zur\kick.wav
...
Undo 1: Clip ist wieder weg (zurückgelesen).
Das Set ist wieder wie vor dem Import (geprüft: alle Spurnamen, Anzahl der Spuren und Zellen der Zielspur; nicht geprüft: Clips anderer Spuren, Geräte, Automation).
```

Im Ergebnis-Block sollten dann stehen: `extension: PRESENT`, `clip_slot.create_audio_clip: PASS`, `clip_file_path_read: '<dein Pfad>'`, `user_hears_kick: not asked (undo chosen before listening)`, `song.undo: PASS (clip removed; read back)`. (Mit Enter statt `y`: `user_hears_kick: yes` und `song.undo: SKIPPED (user answered no)`.) Den ganzen Block (mit den drei Backticks) in **Issue #50** einfügen.

Live benennt eine Spur mit Standardnamen nach dem Clip um (im ersten Lauf: `3-Audio` -> `3-centre_s1001_v0`). Den Namen der Zielspur vergleicht das Script beim Zurücklesen deshalb nicht; es meldet die Umbenennung mit `Live hat die Spur umbenannt: …`, im Ergebnis-Block steht der neue Name unter `target_track_name_after_import`. Zur Vorsicht liest das Script bis zu 2 Sekunden lang alle 0,1 s zurück (ein verspäteter Clip wurde bisher nicht beobachtet). Zeigt das Zurücklesen danach immer noch nicht den Clip, meldet das Script `FEHLER: AbletonOSC hat den letzten Schritt bestätigt, aber das Zurücklesen zeigt nicht das erwartete Ergebnis`, sendet kein Undo, und du entfernst Clip/Spur von Hand.

Behält die Spur nach dem Undo den neuen Namen (ob Live das tut, ist nicht geprüft), meldet das Script `ACHTUNG: Undo hat den Import zurückgenommen (zurückgelesen), aber die Spurnamen sind nicht wie vor dem Import: …`, im Ergebnis-Block `song.undo: PARTIAL (…; track names not restored: '<alt>' -> '<neu>')` und Exit-Code 1. Dann die Spur von Hand zurückbenennen und den Block trotzdem einfügen; das ist ein gültiges Ergebnis.

Ob Live den Dateipfad genau so zurückmeldet, wie er gesendet wurde (Groß/Klein, `\` statt `/`), ist nicht geprüft. Das Script vergleicht ohne Rücksicht auf Groß/Klein und Schrägstrich-Richtung. Steht `FAIL` mit einem anderen Pfad, bitte den Block trotzdem einfügen.

**Zweiter Durchlauf (neue Spur):** dasselbe noch einmal, beim Ziel `n` eingeben. Erwartet: `song.undo: PASS (clip removed, track removed; read back)`. Fasst Live Spur und Clip in einem Undo-Schritt zusammen, meldet das Script `PASS (one undo reverted track and clip together)`; das ist auch ein gültiges Ergebnis, bitte einfügen.

**Fehlerfälle** (je ein Durchlauf, Ergebnis-Block einfügen):

| Test | So geht's | Erwartet |
| --- | --- | --- |
| Live geschlossen | Live beenden, Script starten | `FEHLER: AbletonOSC antwortet nicht …`, Exit-Code 2 |
| Erweiterung fehlt | Live beenden, `python scripts/install_abletonosc_extension.py --uninstall`, mit `y` bestätigen, Live starten, Test-Set öffnen, Script starten | `FEHLER: Die AbeltonGod-Erweiterung fehlt …`, `extension: MISSING`, Exit-Code 5; danach wieder installieren |
| MIDI-Spur | beim Ziel die Nummer der MIDI-Spur eingeben, danach bei der wiederholten Frage Enter | `Spur 1 '2-MIDI' ist keine Audiospur.`, die Ziel-Frage kommt erneut (höchstens dreimal); nach Enter `Kein Ziel gewählt. Keine Änderung.`, nichts gesendet, Exit-Code 0 |
| belegte Zelle | `--slot 0`, wenn Zelle 0 der Audiospur schon einen Clip hat | `Zelle 0 von Spur 0 ist schon belegt …`, Exit-Code 1 |

**Wenn etwas schiefgeht:** Bei Zeitüberschreitung oder *Strg + C* während eines Schritts sagt das Script `Ergebnis ist UNBEKANNT`, liest einmal zurück, sendet nichts mehr und **kein** Undo. Dann im Set nachsehen und einen eventuell angelegten Clip oder eine Spur von Hand löschen.

**Aktions-Log:** Jede Änderung steht vor und nach dem Senden in `logs\bridge-actions.jsonl` im Projektordner (eine JSON-Zeile pro Eintrag, nicht im Git). Der Pfad steht im Ergebnis-Block unter `action_log`.

**Ohne Erweiterung** geht der Import von Hand: `docs/setup/SAMPLE_IMPORT_FALLBACK.md`.

## 8. Arrangement-Check (Issue #140)

Noch **nicht vollständig auf deinem Rechner geprüft** (Lauf 1 mit Script 0.1.0 hielt nach der neuen MIDI-Spur an, siehe unten „Späte Bestätigung“; jetzt Script 0.2.0). Der Check prüft, ob AbeltonGod im **Arrangement** arbeiten kann: neue MIDI-Spur, ein MIDI-Clip an einem bestimmten Takt, Noten darin, ein Locator mit Namen, alles zurückgelesen, dann auf Wunsch alles per Undo zurück. AbletonOSC kann weder einen Clip im Arrangement anlegen noch Noten in Arrangement-Clips schreiben; das ergänzt die Erweiterung in `abletonosc\track.py` (Abschnitt 7.1, Script 0.2.0).

**Vorbereitung:** Erweiterung 0.2.0 installiert (Abschnitt 7.1, Live dabei geschlossen). Dann Live starten, ein neues Test-Set anlegen (Taktart 4/4), speichern, schließen und neu öffnen (Abschnitt 5, Vorbereitung 1–4). Die Wiedergabe muss gestoppt sein. Bei Takt 5 darf noch kein Locator liegen.

```powershell
python scripts/arrangement_check.py
```

(Andere Stelle: `--bar 9`; andere Länge: `--bars 2`; anderer Locator-Name: `--name Intro`.)

Das Script

1. liest Live-Version, Taktart (nur 4/4), Spuren, Locator, Abspielposition und ob Live spielt,
2. prüft die Erweiterung: drei Befehle **ohne** Argumente; AbletonOSC bricht dabei ab, bevor es das Set anfasst. Im `abletonosc.log` stehen danach drei erwartete Zeilen `Error handling OSC message: list index out of range`,
3. lehnt ab, wenn bei Takt 5 schon ein Locator liegt (einen Locator setzen ist in Live ein Umschalter; das Script würde ihn löschen),
4. fragt `Ist das geöffnete Set ein eigenes TEST-Set …? [y/N]`, zeigt den Plan und fragt `Diese Änderungen jetzt ausführen? [y/N]`,
5. setzt die Abspielposition auf Takt 5 (wird danach **nicht** zurückgesetzt), legt eine MIDI-Spur am Ende an, darin im Arrangement einen leeren MIDI-Clip ab Takt 5 (4 Takte), schreibt 16 Noten (C1, eine pro Schlag), setzt bei Takt 5 einen Locator und nennt ihn `AbeltonGod Test`. Nach jedem Schritt liest es zurück und hält bei jeder Abweichung an,
6. fragt **sofort** `Alles jetzt per Undo zurücknehmen, OHNE Nachsehen? [y/N]`. Bis dahin in Live **nichts** anklicken, scrollen oder starten.
   - `y`: ein Undo nach dem anderen, jedes zurückgelesen. Unter `undo_chain` steht, welchen Zustand jedes Undo erreicht hat (daraus sehen wir, wie viele Undo-Schritte Live aus den fünf Änderungen macht). Zeigt ein Undo keine sichtbare Änderung oder einen fremden Zustand, hält das Script an und sagt, was von Hand zu entfernen ist.
   - Enter (nein): alles bleibt. Dann fragt es, ob du im Arrangement die neue Spur mit Clip und Noten ab Takt 5 und darüber den Locator siehst. Danach steht da, wie du alles von Hand entfernst (Spurkopf anklicken, *Entf*; Locator anklicken, *Entf*).

**Erwartete Ausgabe (gekürzt, frisches Set mit `1-MIDI`, `2-MIDI`, `3-Audio`, `4-Audio`, Undo `y`):**

```text
AbeltonGod arrangement_check 0.2.0

Verbindung zu AbletonOSC (127.0.0.1:11000) steht.

Live-Version (laut API): 12.4  Taktart: 4/4  Position: Beat 0
Spuren (4): 0: 1-MIDI, 1: 2-MIDI, 2: 3-Audio, 3: 4-Audio
Locator: keine
AbeltonGod-Erweiterung (Arrangement): vorhanden.
...
OK: Spur, Arrangement-Clip, Noten und Locator sind da (zurückgelesen).
...
  undo_1: 'after set_cue_name' -> 'after add_cue'
  ...
Das Set ist wieder wie vor dem Check (geprüft: alle Spurnamen, Anzahl der Spuren, alle Locator; nicht geprüft: Clips anderer Spuren, Geräte, Automation). Die Abspielposition steht auf Beat 16.
```

Im Ergebnis-Block sollten dann stehen: `extension: PRESENT`, je `PASS` bei `song.current_song_time.set`, `song.create_midi_track`, `track.create_midi_clip`, `arrangement_clip.notes.add`, `song.cue_point.add_or_delete`, `song.cue_point.set_name`, `arrangement_clips_read: [(16.0, 16.0)]`, `notes_read: 16 notes; …`, und `song.undo: PASS (… undo(s) for 5 write(s); read back)`. Wie viele Undos es sind und was unter `undo_chain` steht, ist offen; jedes Ergebnis ist gültig. Den ganzen Block (mit den drei Backticks) in **Issue #140** einfügen.

**Späte Bestätigung (ab Script 0.2.0):** Kommt die Bestätigung eines Schritts nicht innerhalb der Zeit (1 Sekunde), liest das Script das Set mit mehr Zeit zurück. Zeigt es genau die geplante Änderung, geht es weiter. Dann steht unter `steps` z. B. `create_midi_track: confirmed (late: no confirmation within 1 s; read-back matched (1 read(s)); end echo after 2.10 s)` und beim Schritt `PASS (late: read-back after timeout)`. Das ist ein gültiges Ergebnis. Die Zahl nach `end echo after` ist die Zeit vom Senden bis zu dem Moment, in dem das Script die Bestätigung gelesen hat. Live hat also höchstens so lange gebraucht, vielleicht weniger (das Script liest die Bestätigung erst, wenn es selbst wieder fragt). Steht dort `end echo not seen`, kam die Bestätigung gar nicht an. Beides bitte mit dem Block einfügen. Für Undo gilt das nicht: läuft ein Undo in die Zeitüberschreitung, hält das Script an.

**Fehlerfälle:** `FEHLER: Die AbeltonGod-Erweiterung 0.2.0 fehlt …` (Exit-Code 5) heißt: Abschnitt 7.1 ausführen. Spielt Live, steht die Taktart nicht auf 4/4 oder liegt bei Takt 5 ein Locator, ändert das Script nichts (Exit-Code 1). Zeigt das Zurücklesen nach einer Zeitüberschreitung nicht genau die geplante Änderung, oder bei *Strg + C* während eines Schritts: `UNBEKANNT`, kein Undo, im Set nachsehen und von Hand entfernen.
