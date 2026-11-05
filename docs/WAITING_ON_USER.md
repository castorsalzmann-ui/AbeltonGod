# Waiting on the user

**Status since 2026-11-05 (D-028): nothing blocks the project.** The user asked for finalisation without listening tests. Every item below is an **optional later verification**; no work item waits for it. The lead keeps this file current after every merge; the cockpit (`scripts/qa/cockpit_collect.py`) reads it and adds every open PR automatically. One line per item, `Aufgabe` in German and short.

Until an item is done, the matching function stays "not verified" (`contracts/capabilities.json` is unchanged) and no listening claim is made.

| Was | Link | Aufgabe | Seit |
| --- | --- | --- | --- |
| Optional: Hören | https://github.com/castorsalzmann-ui/AbeltonGod/issues/356 | Hörtests (Kick, Hat, Snare, Clap, Rim, Bass, Goa-Bass) nach den Anleitungen in `docs/setup/LISTENING_TEST_*.md`; nur wenn du Zeit hast | 2026-11-02 |
| Optional: Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/368 | Rim, Bass und Snare in Live importieren (`docs/setup/RIM_BASS_TO_LIVE.md`, `docs/setup/SNARE_TO_LIVE.md`); bisher nur gegen Fake-Server geprüft | 2026-11-03 |
| Optional: Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/129 | Goa-Arrangement in Live testen (T1-T8 in `docs/research/2026-11-03_goa-arrangement-delivery-to-live.md`) | 2026-11-03 |
| Optional: Test | https://github.com/castorsalzmann-ui/AbeltonGod/issues/277 | Acid 303: „Test-Ton“ drücken, Pegelanzeige melden | 2026-11-02 |
