# Hörtest Snare: Schlüssel und Hinweise für den Lead (Issue #316)

**Erst nach dem Test lesen.** Diese Datei verrät den Inhalt jeder Datei (Kontrollpaar, Parameterstufen) und darf nicht vor oder während des Hörens zum Hörer gelangen. Die Anleitung für den Hörer ist `docs/setup/LISTENING_TEST_SNARE.md`. Nichts hier ist gehört worden; Zahlen beschreiben nur Signale. Gestapelt auf PR #312 (Snare-Engine 0.1.0, 5 Presets); kein Engine-Code geändert.

## 1. Paket erzeugen

Aus dem Repo-Stamm, Bash, Engine auf dem Pfad (`PYTHONPATH=src` oder editable install). `OUT` ist ein neuer, leerer Ordner **außerhalb** des Repos. Verschickt wird nur `OUT/hoerer/`; `OUT/render/` enthält Sidecars (Namen und Parameter verraten den Schlüssel). Aufruf: `bash build.sh OUT` mit dem Block unten als `build.sh`.

<!-- build.sh:start -->
```bash
set -euo pipefail
OUT=${1:?output folder}
[ ! -e "$OUT" ] || [ -z "$(ls -A "$OUT")" ] || { echo "OUT must be new or empty" >&2; exit 2; }
mkdir -p "$OUT/render" "$OUT/hoerer"
C=peak_ceiling_dbfs
s() { d="$1"; shift; python -m audio_engine.kick --category snare --out "$OUT/render/$d" "$@" > /dev/null; }
# Level-Angleich: RMS 0-150 ms, alle Dateien auf die leiseste (tight); Werte = peak_ceiling_dbfs
# Block A: die fünf Presets
s tight   --preset tight   --set $C=-0.3
s default --preset default --set $C=-2.2
s long    --preset long    --set $C=-3.9
s tonal   --preset tonal   --set $C=-2.8
s bright  --preset bright  --set $C=-1.6
# Block B: body_level (Rest wie default)
s b0.2 --preset default --set body_level=0.2 --set $C=-2.7
s b0.4 --preset default --set body_level=0.4 --set $C=-2.3
s b0.8 --preset default --set body_level=0.8 --set $C=-2.5
s b1.0 --preset default --set body_level=1.0 --set $C=-5.0
# Block C: noise_hp_hz (Rest wie default)
s c600  --preset default --set noise_hp_hz=600  --set $C=-2.1
s c1200 --preset default --set noise_hp_hz=1200 --set $C=-2.5
s c3000 --preset default --set noise_hp_hz=3000 --set $C=-1.8
s c5000 --preset default --set noise_hp_hz=5000 --set $C=-1.7
# Block D: noise_decay_ms (Rest wie default; length_ms 800, damit 600 ms Abklingzeit nicht abgeschnitten wird)
s d80  --preset default --set noise_decay_ms=80  --set length_ms=800 --set $C=-0.7
s d120 --preset default --set noise_decay_ms=120 --set length_ms=800 --set $C=-1.4
s d350 --preset default --set noise_decay_ms=350 --set length_ms=800 --set $C=-3.9
s d600 --preset default --set noise_decay_ms=600 --set length_ms=800 --set $C=-5.6
# der Kick
python -m audio_engine.kick --out "$OUT/render/kick" --preset dense > /dev/null
# anonyme Namen: Position je Eintrag aus blind_order(Block, n), Eintragsreihenfolge wie unten
python - "$OUT" <<'PY'
import glob, shutil, sys
from pathlib import Path
from audio_engine.listening_test3 import blind_order
out = Path(sys.argv[1])
blocks = {
    "A": ["default", "tight", "long", "tonal", "bright", "default"],  # letzter Eintrag: byte-gleicher Zwilling
    "B": ["b0.2", "b0.4", "b0.8", "b1.0"],
    "C": ["c600", "c1200", "c3000", "c5000"],
    "D": ["d80", "d120", "d350", "d600"],
}
def wav(folder):
    (path,) = glob.glob(str(out / "render" / folder / "*.wav"))
    return path
for letter, folders in blocks.items():
    for folder, pos in zip(folders, blind_order(f"snare-{letter}", len(folders))):
        shutil.copyfile(wav(folder), out / "hoerer" / f"{letter}{pos + 1}.wav")
shutil.copyfile(wav("kick"), out / "hoerer" / "Kick.wav")
PY
```
<!-- build.sh:end -->

Die Nummern kommen aus `audio_engine.listening_test3.blind_order("snare-A", 6)` = `[2, 0, 3, 4, 5, 1]` (Position 0-basiert je Eintrag in der Reihenfolge default, tight, long, tonal, bright, Zwilling) sowie `"snare-B"` = `[3, 0, 1, 2]`, `"snare-C"` = `[3, 0, 1, 2]`, `"snare-D"` = `[2, 0, 1, 3]`. B und C haben dieselbe Mischung, weil `blind_order` nur Block-Name und Index hasht und die beiden Blöcke zufällig dieselbe Reihenfolge ergeben; die Stufen sind aufsteigend in der Eintragsreihenfolge. Der Pegel-Angleich ist `peak_ceiling_dbfs` (nur Verstärkungsfaktor, keine zweite Stufe); Sidecars in `render/` zeigen den Wert je Render.

## 2. Schlüssel (Datei zu Render)

Basis ist das Preset `default` (Seed 1, `body_hz` 190, `body_level` 0.6, `noise_decay_ms` 180, `noise_hp_hz` 1800, `length_ms` 400).

| Datei | Render | Änderung gegenüber `default` | `peak_ceiling_dbfs` |
| --- | --- | --- | --- |
| A1 | Preset `tight` | `noise_decay_ms` 90, `body_decay_ms` 70 | -0.3 |
| A2 | Zwilling | **byte-gleiche Kopie von A3** (Kontrollpaar) | -2.2 |
| A3 | Preset `default` | keine | -2.2 |
| A4 | Preset `long` | `noise_decay_ms` 350, `length_ms` 600 | -3.9 |
| A5 | Preset `tonal` | `body_level` 0.85 | -2.8 |
| A6 | Preset `bright` | `noise_hp_hz` 3500 | -1.6 |
| B1 | default + `body_level` 0.4 | | -2.3 |
| B2 | default + `body_level` 0.8 | | -2.5 |
| B3 | default + `body_level` 1.0 | Rauschen aus (nur Körper) | -5.0 |
| B4 | default + `body_level` 0.2 | | -2.7 |
| C1 | default + `noise_hp_hz` 1200 | | -2.5 |
| C2 | default + `noise_hp_hz` 3000 | | -1.8 |
| C3 | default + `noise_hp_hz` 5000 | | -1.7 |
| C4 | default + `noise_hp_hz` 600 | | -2.1 |
| D1 | default + `noise_decay_ms` 120 | `length_ms` 800 | -1.4 |
| D2 | default + `noise_decay_ms` 350 | `length_ms` 800 | -3.9 |
| D3 | default + `noise_decay_ms` 80 | `length_ms` 800 | -0.7 |
| D4 | default + `noise_decay_ms` 600 | `length_ms` 800 | -5.6 |
| Kick | Kick-Preset `dense` | | unverändert |

Hinweis: B3 (`body_level` 1.0) enthält nach Vertrag kein Rauschen. Die Engine-Konstanten, die nicht im Vertrag stehen (oberer Teilton 0.5, schmale Rauschschicht 1.5x/0.4x), stehen in `snare.py` und sind nicht gehört.

## 3. Gemessen (Signalwerte, keine Hörurteile)

| Datei | Länge ms | Peak dBFS | RMS 0-30 ms | RMS 0-150 ms | RMS 0-400 ms | Crest dB |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | 400 | -0.30 | -15.92 | -22.89 | -27.15 | 26.8 |
| A2, A3 | 400 | -2.20 | -16.14 | -22.91 | -27.17 | 25.0 |
| A4 | 600 | -3.90 | -16.77 | -22.89 | -27.14 | 25.0 |
| A5 | 400 | -2.80 | -16.05 | -22.92 | -27.18 | 24.4 |
| A6 | 400 | -1.60 | -16.09 | -22.86 | -27.12 | 25.5 |
| B1 | 400 | -2.30 | -16.23 | -22.93 | -27.19 | 24.9 |
| B2 | 400 | -2.50 | -15.99 | -22.85 | -27.11 | 24.6 |
| B3 | 400 | -5.00 | -15.97 | -22.92 | -27.18 | 22.2 |
| B4 | 400 | -2.70 | -16.27 | -22.91 | -27.17 | 24.5 |
| C1 | 400 | -2.50 | -16.16 | -22.93 | -27.19 | 24.7 |
| C2 | 400 | -1.80 | -16.13 | -22.91 | -27.17 | 25.4 |
| C3 | 400 | -1.70 | -16.13 | -22.90 | -27.16 | 25.5 |
| C4 | 400 | -2.10 | -16.13 | -22.90 | -27.16 | 25.1 |
| D1 | 800 | -1.40 | -16.00 | -22.92 | -27.18 | 28.8 |
| D2 | 800 | -3.90 | -16.77 | -22.89 | -27.14 | 26.2 |
| D3 | 800 | -0.70 | -15.89 | -22.85 | -27.11 | 29.4 |
| D4 | 800 | -5.60 | -17.76 | -22.94 | -27.12 | 24.5 |

Ein globaler Angleich über alle 17 Snares: **ein Ziel** (RMS 0-150 ms der leisesten Datei, `tight`, -22.89 dBFS), Spreizung nach dem Angleich 0.09 dB (-22.85 bis -22.94); vorher bei gleichem Peak -0.3: 5.3 dB (-17.63 bei `noise_decay_ms` 600 bis -22.89 bei `tight`). Das Fenster 0-150 ms enthält Körper und Beginn des Rauschens. In den **kurzen** (0-30 ms) und **langen** Fenstern bleibt der Angleich nicht gleich: 0-30 ms Spreizung 1.87 dB (-15.89 bis -17.76), 0-400 ms 0.08 dB. Die Dateien mit langem Rauschschwanz (A4, D2, D4) liegen im Anschlag (0-30 ms) 0.5 bis 1.8 dB unter den anderen, weil sie für gleiche 0-150 ms-Energie leiser gestellt sind. Folge für die Lesung: gleiche Energie heißt nicht gleich empfundene Lautheit; Anmerkung des Hörers auswerten. Crest (Peak zu RMS über die ganze Datei) ist bei Block D nicht mit den anderen vergleichbar (800 ms Datei, mehr Stille).

Messmethode (anders als die Engine): Skript im Arbeitsbereich (nicht im Repo), liest die WAV-Dateien mit dem Python-Modul `wave`, dekodiert die 24-Bit-Werte selbst (nicht `audio_engine.io.wav_samples`); RMS = Quadratsumme über das Fenster geteilt durch die feste Fensterlänge (kürzere Dateien zählen als Stille). Die Ceiling-Werte kamen aus einer Vormessung der 17 Renders mit Ceiling -0.3 (Differenz zur leisesten, auf 0.1 dB gerundet), die Tabelle ist die Nachmessung an den fertigen Dateien in `hoerer/`.

Determinismus: `bash build.sh OUT` wurde in zwei getrennten Läufen in zwei neue Ordner ausgeführt, `sha256sum` über `hoerer/*.wav`, `diff`: identisch (19 Dateien; A2 und A3 haben denselben Hash). SHA-256:

```
0935e48ef0d5616bdd89215b7c6f3e403442dbe663a43ee2c48a7c6f2591126a  A1.wav
62eb2cccf83a5bc5ec931f7a70f048ab40949661f94260f1986aba4af954cdc8  A2.wav
62eb2cccf83a5bc5ec931f7a70f048ab40949661f94260f1986aba4af954cdc8  A3.wav
d557bfd1b0be0a2d76b1d99e59a3f347b85d1e3d66c7db3b5bc80630fc036ad2  A4.wav
6e66325b2a4a0afabb4b386f20c4ae832f3d28bf560146c292db6414a99e92be  A5.wav
4bba4f414efd38d4dffa45f498d9f3cdbd8b7d3634b3f0402e4fafa5245bc5c7  A6.wav
239260791b1c0af7d4593a4b0ae4443847fe3276b5e87979d64a8fc72ab9ce27  B1.wav
27046641d39c0876bd375475664cb5d65d0bbc2fcec30b143fdeb33cf5922323  B2.wav
c3e23a2f1d456d7af40f183e119f45bb98d45112d63662cf0388cc19529a202c  B3.wav
0f9b7bcc58f301d1f1234b40c0d0dabcf391d065ff86e0621f8555db013ba634  B4.wav
a593f517acd36903f481e9376a9e1b441d40706eeb2fca74e916b14ad95f7035  C1.wav
f8348afdea8738c3051ccf1399de7ae40621f66df4a6226a7b17a23d09addf8c  C2.wav
ac5149ba711d47912f4b3eaaf02cf51289a80a1ef1c75cccc875465b365b6dd7  C3.wav
782e941a34fc64fd2f2b88a446242266c390212fb3b0c38433bc7ed151a9f30f  C4.wav
29f80b982c8888593ffc655dcb488e9baed3dfd6a3c77e1d6ec1434b7ae2b62c  D1.wav
bbd9068967ebb4c903fe7b7d93084b7bd1c4d9bb3e37f48246080d40d72010c1  D2.wav
c82bd3badbe9c72e5570dd81c634bd73581c04254d3a6287a0cee4592db172e1  D3.wav
3f66e744f5535a037806e372f3438a1e7bbae93b815a2869f20dbfa643369f0d  D4.wav
b461098c510824b72a16b673370c5873f321820d70d717245f0be97fac52a4e9  Kick.wav
```

Der Kick `dense` hat Peak -0.3 dBFS und ist nicht angeglichen (er ist der Kontext, nicht Teil der Fragen).


## 4. Was die Fragen prüfen (Hypothesen, nicht gehört)

- **H1 (Teil 1, Nähe 1-5):** der Zwilling wird gleich bewertet wie A3. Bestätigt: gleiche Zahl. Widerlegt: verschiedene Zahlen (dann Hörerrauschen, alle Einzelantworten vorsichtiger lesen).
- **H2 (Teil 1, Wort + Kick):** das Wort des Hörers je Datei zeigt, ob 190 Hz Körper, 0.6 Körper/Rauschen, 180 ms Abklingzeit und hp 1800 Hz der Richtung nach stimmen. Nicht vorhergesagt; die Wörter des Hörers sind die Daten.
- **H3 (Blöcke B, C, D):** die Rangfolge „meine Snare" ist monoton oder hat ein Maximum in der Mitte der Stufen. Ein Maximum in der Mitte deutet auf einen Zielwert im geprüften Bereich; ein Rand auf einen Wert außerhalb. Beides ist erst eine Aussage über diese Stufen, kein Vertragsvorschlag.
- **H4:** Blöcke ohne Zwilling, daher kein Rauschmaß für den Hörer in B bis D. Antwortet er in A auf den Zwilling mit zwei Zahlen, die mehr als 1 auseinanderliegen, werden B bis D nur als Hinweis gelesen.
- **Pegel:** der Angleich ist RMS 0-150 ms. Die Snares unterscheiden sich im Crest-Faktor (Peak zu RMS 22 bis 27 dB, Default 25.0 dB, siehe Tabelle); bei gleichem RMS haben sie verschieden hohe Peaks. Das ist gewollt (PR #312, Reviewer-Hinweis 2); ob eine Datei trotzdem lauter oder leiser wirkt, entscheidet das Ohr (Anmerkung des Hörers auswerten).

Auswertung wie üblich: ein Durchgang eines Hörers ist ein Hinweis, kein Beweis.

## 5. Abweichungen und offene Punkte

- **Einzelschläge**, keine Loops. Das Muster (Kick auf jedem Beat, Snare auf Beat 2 und 4) baut der Hörer; die Live-Schritte sind nicht von uns in Live geprüft.
- **Sidecar `t60_ms` nicht benutzt.** Der Pegel-Angleich und alle Tabellenwerte stammen aus eigener Messung der WAV-Dateien; `t60_ms` der Snare-Sidecars liegt bei etwa 325 ms (Boden durch die Gleichanteil-Entfernung, Befund #313) und sagt nichts über die Abklingzeit.
- **Länge:** Block D hat `length_ms` 800, Block A (long) 600, sonst 400. Die Länge ist bei Einzelschlägen im Simpler nicht von der Abklingzeit zu trennen, wenn der Hörer nicht ausklingen lässt; die Abklingzeit der Rauschschicht ist die geprüfte Größe.
- **Block B und C** haben dieselbe Dateimischung (Hash-Folge), unabhängig vom Inhalt.
- Keine Engine-Änderung, kein neues Test-Fixture; der Hörtest-Text ist Doku.

## 6. Befehle, die für die Messwerte liefen

- Paket: `bash build.sh OUT` zweimal (OUT1, OUT2), danach `cd OUT*/hoerer && sha256sum *.wav`, `diff`: identisch. Das Skript wurde dabei aus diesem Dokument extrahiert (Zeilen zwischen `build.sh:start` und `build.sh:end`, ohne die Zaunzeilen), nicht von Hand kopiert.
- Vormessung: 17 Renders mit `python -m audio_engine.kick --category snare ...` bei Ceiling -0.3, RMS 0-150 ms mit dem `wave`-Skript; Ceiling = -0.3 - (RMS Datei - RMS leiseste), auf 0.1 dB gerundet.
- Nachmessung: dieselbe Methode an `hoerer/*.wav` (Tabelle in Abschnitt 3).
