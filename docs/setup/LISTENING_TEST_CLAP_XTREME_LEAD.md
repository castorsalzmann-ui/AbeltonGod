# Hörtest Clap: Schlüssel und Hinweise für den Lead (Issue #309)

**Erst nach dem Test lesen.** Diese Datei verrät den Inhalt jeder Datei und darf nicht vor oder während des Hörens zum Hörer gelangen. Die Anleitung für den Hörer ist `docs/setup/LISTENING_TEST_CLAP_XTREME.md`. Nichts hier ist gehört worden; Zahlen beschreiben nur Signale. Gestapelt auf PR #305 (die sieben `xtreme-*`-Presets); kein Engine-Code geändert.

## 1. Paket erzeugen

Aus dem Repo-Stamm, Bash, Engine auf dem Pfad (`PYTHONPATH=src` oder editable install). `OUT` ist ein neuer, leerer Ordner **außerhalb** des Repos. Verschickt wird nur `OUT/hoerer/`; `OUT/render/` enthält Sidecars (Namen und Parameter verraten den Schlüssel). Aufruf: `bash build.sh OUT` mit dem Block unten als `build.sh`.

```bash
set -euo pipefail
OUT=${1:?output folder}
mkdir -p "$OUT/render" "$OUT/hoerer"
c() { d="$1"; shift; python -m audio_engine.kick --category clap --out "$OUT/render/$d" "$@" > /dev/null; }
for p in default xtreme-saturated xtreme-folded xtreme-crushed xtreme-metal xtreme-gated xtreme-reversed xtreme-wreck; do
  c "$p" --preset "$p"
done
for f in 0 0.02 0.05 0.1; do c "fold$f" --preset xtreme-folded --set fold=$f; done
python -m audio_engine.kick --out "$OUT/render/kick" --preset dense > /dev/null
python - "$OUT" <<'PY'
import sys, glob, shutil
from pathlib import Path
from audio_engine.io import encode_wav, wav_samples
out = Path(sys.argv[1])
# file -> (render folder, gain in dB); gains are fixed values measured on the 0-900 ms total energy
items = {
    "A1": ("xtreme-reversed", -1.96), "A2": ("xtreme-saturated", -12.00),
    "A3": ("xtreme-wreck", -12.70),   "A4": ("xtreme-folded", -10.70),
    "A5": ("xtreme-metal", 0.00),     "A6": ("default", -2.12),
    "A7": ("xtreme-gated", -4.37),    "A8": ("xtreme-crushed", -0.67),
    "A9": ("default", -2.12),
    "B1": ("fold0.05", -5.62), "B2": ("fold0.02", -1.43),
    "B3": ("fold0.1", -7.93),  "B4": ("fold0", 0.00),
}
for name, (folder, gain_db) in items.items():
    src = glob.glob(str(out / "render" / folder / "*.wav"))[0]
    audio = wav_samples(Path(src).read_bytes()) / 2**23 * 10.0 ** (gain_db / 20.0)
    (out / "hoerer" / f"{name}.wav").write_bytes(encode_wav(audio, 48000, 24))
shutil.copy(glob.glob(str(out / "render" / "kick" / "*.wav"))[0], out / "hoerer" / "Kick.wav")
PY
```

Warum eine Gain-Stufe im Skript statt `peak_ceiling_dbfs`: die Spreizung ist 12.7 dB bei gleichem Peak, `peak_ceiling_dbfs` geht nur bis -12.0 (Vertrag), die lauteste Datei bräuchte -13.0. Das Skript skaliert deshalb die fertigen 24-Bit-Renders um feste dB-Werte (nur abschwächen, nie anheben, Peak bleibt <= -0.3) und schreibt sie neu mit `encode_wav`. Die Sidecars in `render/` beschreiben die ungedämpften Renders. Die Gain-Werte sind fest im Skript; sie wurden unabhängig gemessen (Abschnitt 3).

## 2. Schlüssel (Datei zu Render)

| Datei | Render | Parameter | Gain dB |
| --- | --- | --- | --- |
| A1 | `xtreme-reversed` | Seed 2106, `tail_reverse` an, `tail_level` 1, `tail_decay_ms` 300, `length_ms` 700 | -1.96 |
| A2 | `xtreme-saturated` | Seed 2101, `drive` 0.8 | -12.00 |
| A3 | `xtreme-wreck` | Seed 2107, `drive` 0.6, `fold` 0.3, `crush` 0.4, `rate_div` 2, `comb_hz` 1500, `comb_fb` 0.6 | -12.70 |
| A4 | `xtreme-folded` | Seed 2102, `bp_hz` 1500, `fold` 0.4 | -10.70 |
| A5 | `xtreme-metal` | Seed 2104, `ring_hz` 400, `ring_mix` 0.7, `comb_hz` 800, `comb_fb` 0.8 | 0.00 |
| A6 | `default` | Seed 2001 (Referenz) | -2.12 |
| A7 | `xtreme-gated` | Seed 2105, `tail_decay_ms` 800, `length_ms` 900, `gate_ms` 120 | -4.37 |
| A8 | `xtreme-crushed` | Seed 2103, `hp_hz` 600, `crush` 0.7, `rate_div` 4 | -0.67 |
| A9 | `default` | **byte-gleiche Kopie von A6** (Kontrollpaar) | -2.12 |
| B1 | `xtreme-folded` mit `fold` 0.05 | sonst wie A4 | -5.62 |
| B2 | `xtreme-folded` mit `fold` 0.02 | | -1.43 |
| B3 | `xtreme-folded` mit `fold` 0.1 | | -7.93 |
| B4 | `xtreme-folded` mit `fold` 0 | (Stufe aus) | 0.00 |
| Kick | Kick-Preset `dense` | Peak -0.3 dBFS | unverändert |

Die Nummern kommen aus `audio_engine.listening_test3.blind_order("clapxt-A", 9)` = `[5, 1, 3, 7, 4, 6, 0, 2, 8]` (Position 0-basiert je Eintrag in der Reihenfolge default, saturated, folded, crushed, metal, gated, reversed, wreck, Zwilling) und `blind_order("clapxt-B", 4)` = `[3, 1, 0, 2]` (fold 0, 0.02, 0.05, 0.1). Kein Kontrollpaar in B; die Reihenfolge fold aufsteigend ist B4 < B2 < B1 < B3.

Zu B: der Name `xtreme-folded` setzt `bp_hz` 1500, daher sind B4 (fold 0) und A6 (default, `bp_hz` 1300) verschieden. B ist ein eigener Block mit eigenem Pegel (B liegt in der Gesamtenergie 1.19 dB über A, weil B auf B4 und A auf A5 angeglichen ist); nur innerhalb des Blocks vergleichen.

## 3. Gemessen (Signalwerte, keine Hörurteile)

Pegel mit einer anderen Methode als die Engine: Skript im Arbeitsbereich (nicht im Repo), das die WAV-Datei mit dem Python-Modul `wave` liest und die 24-Bit-Werte selbst dekodiert (nicht `audio_engine.io.wav_samples`); RMS = Quadratsumme über das Fenster geteilt durch die feste Fensterlänge (kürzere Dateien zählen als Stille). Fenster 0-900 ms = Gesamtenergie, darauf wurde angeglichen.

| Datei | Länge ms | Peak dBFS | RMS 0-900 ms | RMS 0-300 ms | RMS 0-100 ms |
| --- | --- | --- | --- | --- | --- |
| A1 | 700 | -2.26 | -26.31 | -29.84 | -25.07 |
| A2 | 500 | -12.30 | -26.30 | -21.53 | -16.94 |
| A3 | 500 | -13.00 | -26.31 | -21.54 | -17.50 |
| A4 | 500 | -11.00 | -26.31 | -21.54 | -17.00 |
| A5 | 500 | -0.30 | -26.31 | -21.54 | -16.80 |
| A6, A9 | 500 | -2.42 | -26.31 | -21.54 | -16.79 |
| A7 | 900 | -4.67 | -26.31 | -21.54 | -17.27 |
| A8 | 500 | -0.97 | -26.31 | -21.53 | -16.80 |
| B1 | 500 | -5.92 | -25.12 | -20.35 | -15.61 |
| B2 | 500 | -1.73 | -25.12 | -20.34 | -15.60 |
| B3 | 500 | -8.23 | -25.12 | -20.35 | -15.63 |
| B4 | 500 | -0.30 | -25.12 | -20.35 | -15.60 |

Spreizung in A: 0.01 dB (0-900 ms), 0.01 dB (0-300 ms ohne A1), 0.7 dB (0-100 ms ohne A1). **A1 ist die Ausnahme der kurzen Fenster:** die Energie liegt im Anstieg am Ende der Datei (Peak bei 691.7 ms), daher 0-300 ms um 8.3 dB und 0-100 ms um 8.3 dB leiser als die anderen. Das ist Folge der Wahl des Gesamtenergie-Fensters; ob A1 lauter oder leiser wirkt, entscheidet das Ohr (Anmerkung des Hörers auswerten). Vor dem Angleich (alle Peak -0.3): Spreizung 12.7 dB (0-900 ms).

Fold-Übergang (Block B, Rohdateien vor dem Gain, RMS der Differenz zu fold 0 relativ zum RMS von fold 0): fold 0.02 -14.6 dB, 0.05 -0.5 dB, 0.1 +4.4 dB. Der Fehler wächst monoton; der PR #305 nennt dieselbe Kurve (Reviewer: kein Sprung bei 0.1).

Enden: A1 (`tail_reverse`): größter Betrag der letzten 5 ms bei -1.6 dB zum eigenen Peak, letztes Sample über -60 dB bei 699.8 ms von 700 ms (die Engine setzt eine 5 ms Ausblendung am Ende; ob das als Abbruch gehört wird, ist Sache der Teil-1-Frage b). A7 (`gate_ms` 120): 114.5-120 ms noch bei -2.2 dB zum eigenen Peak, danach unter -60 dB (Schnitt aus hohem Pegel, 1 ms Fade laut PR).

Determinismus: das Skript wurde in zwei getrennten Läufen in zwei neue Ordner ausgeführt, `sha256sum` über `hoerer/*.wav`: identisch (14 Dateien; A6 und A9 haben denselben Hash). SHA-256:

```
9a055d1de72e59d129a83bdec5e90a26684ef98a611521c5f0f3696fc9d5b2b3  A1.wav
8e23252a4c2f382f30a66ab173f81a0cdd702ffef19cf3daf00a807529e02cf1  A2.wav
8e07e257bcf1c7e5aad7399bbdbe975fe19b934862b8f8d1533d8add06e0e48f  A3.wav
a67878a7df5e962ade3bdb5e0cc1f4613a24f9e741283b3d5c16a20626b31fd9  A4.wav
251c05227f1052817c0adc7877fe5dbe5d4612c0a2a84465181db482cd94081e  A5.wav
281ba8301eb83be4fc149f5f61286e3d78992a14b8af49626f29eb01d30f2f18  A6.wav
e83c716d79364c4d0b4e9f10c5c67ea52bfdab2a2464591a6a0433f6cc978fe6  A7.wav
1dfb2fc86a83239f729b7dadab745be2d46bdbd7cf58fe226cfee2c187d198a6  A8.wav
281ba8301eb83be4fc149f5f61286e3d78992a14b8af49626f29eb01d30f2f18  A9.wav
7d71464ec8bea1d830405c266e74d64e7dfb410aabbf65ec1d21f3a3bdafc1aa  B1.wav
6341467c49e6cfa21f4f3e82d29a21de2339051464ad9978230b2737dee28c95  B2.wav
fad236f2f87e9c96b1da4b211573738cc840570addf70518b5e8924c41d5b9f1  B3.wav
4ab5cf1e5bb8406628c861d8f4c9a0a717d7787e4adce018ded57267b1aa634c  B4.wav
b461098c510824b72a16b673370c5873f321820d70d717245f0be97fac52a4e9  Kick.wav
```

## 4. Was die Fragen prüfen (Hypothesen, nicht gehört)

- **Teil 1a:** H1: die Entfernung zum normalen Clap steigt mit der Zahl und Art der Stufen (A6 und A9 niedrig, A3 hoch). Bestätigt, wenn A6/A9 gleich bewertet werden und A3 hoch. Widerlegt, wenn der Hörer A6 und A9 verschieden bewertet (Hörerrauschen: dann alle Antworten vorsichtiger lesen).
- **Teil 1b:** H2: A1 (Ende des Anschwellens) und A7 (Schnitt) zeigen „am Ende" bzw. „mittendrin"; A6/A9 „nein". Offene Fragen aus dem Issue: Ende des umgekehrten Anstiegs, abgeschnittener Gate-Ausschnitt. Erst die Antwort entscheidet, ob eine Ausblendung geändert werden soll; Vorschlag nur bei „ja" für A1/A7.
- **Teil 1 Zwilling:** A6/A9 als gleich erkannt = Kontrolle in Ordnung.
- **Teil 2:** H3: Reihenfolge B4 < B2 < B1 < B3 und kein Sprungpaar. Widerlegt, wenn der Hörer ein Sprungpaar nennt (dann zwischen fold 0 und 0.02 oder 0.1 und darüber ist der Übergang nicht glatt; Paar notieren).
- **Teil 3:** H4: die Claps mit dem größten Pegelabstand der kurzen Fenster (A1, A7) fallen im Timing auf (A1: Treffer am Dateiende, Note auf Beat 2/4 setzt den Anstieg davor, also wirkt der Schlag spät). Das ist Folge der Dateistruktur, kein Fehler.

Auswertung wie üblich: ein Durchgang eines Hörers ist ein Hinweis, kein Beweis; Pegel-Anmerkung des Hörers beachten, der Angleich ist Gesamtenergie, nicht empfundene Lautheit.

## 5. Abweichungen und offene Punkte

- **Einzelschläge**, keine Loops (Loops sind #300). Das Muster baut der Hörer; die Live-Schritte sind nicht von uns in Live geprüft.
- **Gain-Stufe außerhalb der Engine** (siehe Abschnitt 1), weil `peak_ceiling_dbfs` bei -12 endet. Möglicher Folgeissue: Vertragsgrenze oder Werkzeug für Pegelabgleich, Entscheidung beim Lead.
- Kein neues Test-Fixture, keine Engine-Änderung; der Hörtest-Text ist Doku.

## 6. Befehle, die für die Messwerte liefen

- Paket: `bash build.sh OUT` zweimal (OUT1, OUT2), danach `cd OUT*/hoerer && sha256sum *.wav`, `diff`: identisch.
- Vor-Messung: acht Presets plus vier `--set fold=...`-Renders mit `python -m audio_engine.kick --category clap`, Peak -0.3, gleiche Messung wie oben; Gain = (leiseste Datei des Blocks) - (Datei), auf 0.01 dB gerundet.
- Nach-Messung: dieselbe Methode an den fertigen Dateien in `hoerer/` (Tabelle in Abschnitt 3).
