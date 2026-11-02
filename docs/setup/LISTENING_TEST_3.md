# Hörtest 3: Kick nach `dense` (Issue #103)

Nur du kannst sagen, wie die Kicks klingen. Die Zahlen im PR beschreiben nur die Signale. Dauer: etwa 11 Minuten plus 2 Minuten Aufbau. Plan und Messwerte: `docs/research/2026-11-02_listening-test-3-plan.md`.

## Aufbau (einmal, 2 Minuten)

Alle `*.wav` des Pakets in eine Audiospur laden, Warp aus, Projekttempo 136 BPM, jede Datei als Loop. Gleiche Lautstärke an der Spur, nichts auf dem Master. Die Dateinamen sind anonym (A/B/C/D). Schluessel.md erst nach dem Test öffnen.

Jede Datei ist ein Loop über 4 Takte, ein Kick pro Beat. Die Lautheit ist je Block schon angeglichen: Fader nicht anfassen.

## Reihenfolge und Fragen

Reihenfolge: **K2 → K0 → K3 → K1 → K4 → K5.** Nach K1 eine Minute Pause.

| # | Frage (eine pro Block) | Antwortmöglichkeiten |
| --- | --- | --- |
| K2 | Hör die Datei K2_A, dann K2_B. **Welche hat mehr Wumms und Volumen im Anschlag?** | A / B / kein Unterschied |
| K0 | Gleiche Frage für K0_A und K0_B: **Welche ist voller?** | A / B / kein Unterschied |
| K3 | **Hat eine der beiden etwas, das die andere nicht hat? Wenn ja, welche und was (ein Wort)?** | A / B / kein Unterschied · Wort |
| K1 | Drei Dateien (K1_A, K1_B, K1_C). **Sortiere von „mein Kick" bis „am wenigsten mein Kick".** Danach: **Ist die beste zu viel, zu wenig oder richtig verzerrt?** | Reihenfolge, z. B. B > A > C · zu viel / richtig / zu wenig |
| K4 | Der Kick läuft auf jedem Beat. **Welcher Schwanz stört den nächsten Schlag weniger, ohne dass dir etwas fehlt?** Wenn die kürzere Variante etwas verliert: was (ein Wort)? | A / B / kein Unterschied · Wort |
| K5 | Vier Dateien (K5_A bis K5_D). **Welche klingen für dich wie derselbe Kick? Welche fällt raus (wenn eine rausfällt)?** | Liste |

„Kein Unterschied" ist eine gültige und nützliche Antwort.

## Auswertungsvorlage

```
Test 3, Datum: ____   Hörumgebung (Kopfhörer / Monitore): ____   Pegel gleich gelassen: ja / nein
K2: ___   Anmerkung: ____
K0: ___   (A=B identisch; war die Antwort „kein Unterschied"?  ja / nein)
K3: ___   Wort: ____
K1: Reihenfolge ___ > ___ > ___    Verzerrung der besten: zu viel / richtig / zu wenig
K4: ___   Verlust (Wort): ____
K5: gleicher Kick: ___ ; fällt raus: ___
Gesamt: Welche Datei des ganzen Tests ist „mein Kick"? ____ (oder „dense reicht")
```

## Paket neu erzeugen (Entwickler)

```
python -m audio_engine.listening_test3 --out <neuer, leerer Ordner außerhalb des Repos>
```

Schreibt `<Ordner>/package/` (WAVs und `Schluessel.md`, das wird verschickt) und `<Ordner>/sidecars/` (K5-Kicks als Einzelschlag mit Sidecar und Seed; nicht verschicken, die Namen verraten den Schlüssel). Gleicher Code gibt byte-gleiche Dateien.
