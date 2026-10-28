# Kick von Hand in Live ziehen (Fallback, Phase 03)

Dieser Weg braucht weder AbletonOSC noch die AbeltonGod-Erweiterung. Er ist der Ersatz, wenn `scripts/live_import.py` nicht geht (Erweiterung fehlt, unbekannte AbletonOSC-Version, Fehler beim Import), und er wird einmal von dir ausprobiert (Abnahme von Issue #50).

Noch **nicht auf deinem Rechner durchgespielt**. Die Bedienschritte in Live stammen aus dem Live-12-Handbuch (Drag & Drop von Dateien aus dem Explorer in die Session-Ansicht), nicht aus einem Test in diesem Projekt. Weicht etwas ab, bitte in Issue #50 schreiben.

## 1. Ordner öffnen

Liegt der Kick z. B. in `C:\Users\<du>\Music\AbeltonGod-Test`, in PowerShell:

```powershell
explorer "$env:USERPROFILE\Music\AbeltonGod-Test"
```

Oder mit `Win + E` den Ordner von Hand öffnen. Sobald die Sample-Bibliothek (#64) da ist, liegen die Kicks im Projektordner unter `Samples\Drums\Kicks\`.

Neben jeder WAV liegt eine `.json`-Datei mit den Parametern. Die nicht nach Live ziehen; sie gehört zu AbeltonGod.

## 2. In Live ziehen

1. Live und das Explorer-Fenster nebeneinander anordnen.
2. In Live die **Session-Ansicht** öffnen (`Tab` wechselt zwischen Session und Arrangement).
3. Die WAV-Datei mit der Maus aus dem Explorer auf eine **leere Zelle einer Audiospur** ziehen und loslassen.
   - Ziehst du sie auf den leeren Bereich rechts neben den Spuren (wo „Drop Files and Devices Here“ steht), legt Live eine neue Audiospur mit dem Clip an.
   - Auf eine MIDI-Spur geht es nicht als Audio-Clip.
4. Die Zelle mit dem kleinen Dreieck starten und anhören.

Live verweist dabei auf die Datei an ihrem Ort. Ob Live sie zusätzlich in den Projektordner kopiert, hängt von deiner Einstellung *Optionen → Einstellungen → Bibliothek / Dateien* ab (beim Speichern mit „Sammeln und speichern“ kopiert Live alle Dateien ins Projekt). AbeltonGod verändert und löscht die WAV-Datei nie.

## 3. Rückgängig machen

`Strg + Z` in Live nimmt das Einfügen zurück, oder Clip anklicken und `Entf`. Die Datei auf der Festplatte bleibt.

## 4. Was ins Issue gehört

Kurz in Issue #50:

- ob der Clip in der Zelle erschien und der Kick spielte,
- ob Live beim Ziehen eine Meldung zeigte (z. B. zu Sample-Rate oder Analyse),
- ob die Schritte oben so stimmten (Menünamen, Hinweistext im leeren Bereich).
