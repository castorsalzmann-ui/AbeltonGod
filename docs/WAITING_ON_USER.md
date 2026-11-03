# Waiting on the user

What only the user can do. The lead keeps this table current after every merge or new agent result (the housekeeping agent between merges, issue https://github.com/castorsalzmann-ui/AbeltonGod/issues/339); the cockpit (`scripts/qa/cockpit_collect.py`) reads it and also adds every open PR automatically. Keep one line per item, `Aufgabe` in German and short. Items whose issue or PR is closed are removed, except a listening or test task that is still open although its package issue was closed by the merge (marked "Paket gemergt"); the cockpit shows those as closed.

| Was | Link | Aufgabe | Seit |
| --- | --- | --- | --- |
| Hören | https://github.com/castorsalzmann-ui/AbeltonGod/issues/356 | Hörtests offen: Kick-Hörpaket (`hoerer.zip`, Schlüsselwörter), Hat nach `docs/setup/LISTENING_TEST_HAT.md` (T5 darf „kein Unterschied“ sein), Snare nach `docs/setup/LISTENING_TEST_SNARE.md`; Goa noch ohne Paket (Rim und Bass siehe eigene Zeilen) | 2026-11-02 |
| Hören | https://github.com/castorsalzmann-ui/AbeltonGod/issues/232 | Clap-Hörtest: Antworten schicken; dazu Xtreme-Claps nach `docs/setup/LISTENING_TEST_CLAP_XTREME.md` | 2026-11-02 |
| Hören | https://github.com/castorsalzmann-ui/AbeltonGod/issues/359 | Rim-Hörtest nach `docs/setup/LISTENING_TEST_RIM.md` (18 Loops, blind; Paket gemergt, Issue geschlossen) | 2026-11-03 |
| Hören | https://github.com/castorsalzmann-ui/AbeltonGod/issues/361 | Bass-Hörtest nach `docs/setup/LISTENING_TEST_BASS.md` (18 Loops, blind; Paket gemergt, Issue geschlossen) | 2026-11-03 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/368 | Rim und Bass in Live importieren nach `docs/setup/RIM_BASS_TO_LIVE.md` (Test-Set; bisher nur gegen Fake-Server geprüft; Issue geschlossen, Test offen); Ergebnis-Blöcke als Kommentar in https://github.com/castorsalzmann-ui/AbeltonGod/issues/129 | 2026-11-03 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/pull/350 | Goa-Arrangement in Live testen: `.mid` in leeres Set ziehen, Tests T1-T8 aus `docs/research/2026-11-03_goa-arrangement-delivery-to-live.md` (Paket gemergt) | 2026-11-03 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/345 | Im Geräte-Browser von Live prüfen, ob Echo, Roar und Operator in deiner Edition (Standard) vorhanden sind | 2026-11-03 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/277 | Acid 303: „Test-Ton“ drücken, Pegelanzeige melden | 2026-11-02 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/96 | `pytest tests/audio_engine/test_write_interrupts.py -rs` ausführen, `no_tracer` darf nicht überspringen | 2026-11-01 |
| Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/174 | Echte Nutzungswerte vom PC liefern, damit die Guard-Limits angepasst werden können | 2026-11-01 |
| Entscheidung | https://github.com/castorsalzmann-ui/AbeltonGod/issues/151 | Toms-Frage: Toms/Percussion als nächste Kategorie, ja oder nein? | 2026-11-02 |
| Entscheidung | https://github.com/castorsalzmann-ui/AbeltonGod/issues/284 | Vertragsfrage `acid_line`: eigenes Austauschformat festschreiben (Contract-Change), ja oder nein? | 2026-11-02 |
| Entscheidung | https://github.com/castorsalzmann-ui/AbeltonGod/issues/301 | Kick-0.1-Sidecar gilt mit fremdem Engine-Namen: Vertrag anpassen? | 2026-11-02 |
| Entscheidung | https://github.com/castorsalzmann-ui/AbeltonGod/issues/311 | Clap `peak_ceiling_dbfs` Maximum -12,0 zu streng für laute Presets: Grenze ändern? | 2026-11-02 |
| Entscheidung | https://github.com/castorsalzmann-ui/AbeltonGod/issues/335 | Bass: Standard-Drive 0 oder DC-Blocker (DC-Offset bei Drive 0,2)? | 2026-11-03 |
| Entscheidung | https://github.com/castorsalzmann-ui/AbeltonGod/issues/338 | Goa-Plugin (Pionierarbeit): Go oder No-Go? Dazu 3-5 Goa-Referenztracks nennen | 2026-11-03 |
| Entscheidung | https://github.com/castorsalzmann-ui/AbeltonGod/pull/369 | Goa-Stimmenplan: 7 offene Fragen beantworten, Abschnitt 8 von `docs/research/2026-11-03_goa-synth-voice-plan.md` (Referenzen, MIDI oder gerenderter Klang, Drift oder Analog, Bass-Rhythmus, Intro/Outro, Operator/Wavetable/Echo in Live Standard, Renderzeit; Plan gemergt) | 2026-11-03 |
