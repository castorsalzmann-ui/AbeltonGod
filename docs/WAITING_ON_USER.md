# Waiting on the user

What only the user can do. The lead keeps this table current after every merge or new agent result; the cockpit (`scripts/qa/cockpit_collect.py`) reads it and also adds every open PR automatically. Keep one line per item, `Aufgabe` in German and short. Done items are removed in the next lead update (the cockpit hides items whose issue or PR is closed).

| Was | Link | Aufgabe | Seit |
| --- | --- | --- | --- |
| Merge | https://github.com/castorsalzmann-ui/AbeltonGod/pull/239 | Fundament für Claps und weitere Sounds mergen (Review freigegeben, Kicks unverändert) | 2026-11-02 |
| Merge | https://github.com/castorsalzmann-ui/AbeltonGod/pull/240 | Clap-Ziele und Hörtest-Plan mergen (nur Doku, Review + Gate grün) | 2026-11-02 |
| Merge | https://github.com/castorsalzmann-ui/AbeltonGod/pull/241 | Hat-Recherche mergen (nur Doku, Review freigegeben, Gate grün) | 2026-11-02 |
| Schließen | https://github.com/castorsalzmann-ui/AbeltonGod/issues/103 | Hörtests abgeschlossen: Issue schließen | 2026-11-02 |
| Schließen | https://github.com/castorsalzmann-ui/AbeltonGod/issues/57 | Kick-Layering nicht verfolgt: Issue schließen | 2026-11-02 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/176 | Offline-Test von Claude auf deinem PC wiederholen | 2026-11-01 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/175 | Chat-Gedächtnis testen: antwortet Claude deutsch, nennt er 1-basierte Spurnummern? | 2026-11-01 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/96 | `pytest tests/audio_engine/test_write_interrupts.py -rs` ausführen, `no_tracer` darf nicht überspringen | 2026-11-01 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/140 | Arrangement-Check in Live noch einmal laufen lassen (12 Funktionen warten auf `tested`) | 2026-10-29 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/174 | Echte Nutzungswerte vom PC liefern, damit die Guard-Limits angepasst werden können | 2026-11-01 |
