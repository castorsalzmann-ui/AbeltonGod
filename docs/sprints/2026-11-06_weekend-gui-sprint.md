# Sprint W1 — GUI fully integrated and working (2026-11-06 13:00 → 2026-11-09 13:00)

Lead-owned. User away for three days, all approvals granted (user, 2026-11-06 12:40). Goal in the
user's words: "die gesamte GUI integriert und funktionabel".

## Goal and "done when"

**What exists afterwards:** one `AbeltonGod.exe` whose main window and three tool windows (Goa,
Acid, Blaster) form one app: every category renders, previews, lands in the library and can be
handed to the Live import; every window shares settings (output/project folder, sample rate, bit
depth), theme and widget kit; no dead button, no "not implemented" path without an honest message.

**Done when (checkable without the user):**
1. A GUI tour test (offscreen, Linux + Windows CI) clicks through every page and window, renders
   one sample per category (kick, clap, hat, snare, rim, bass, laser) plus Goa, Acid and Blaster,
   and finds each result in the library list. Screenshots of every page at 100 % and 150 %.
2. Every button/control of every page is listed in a control inventory with its effect; a test
   fails on a control without a handler.
3. Known GUI side-findings closed or decided: #413, #414, #424, #428, #434, #436; #435 measured.
4. Live import from the GUI works against the fake AbletonOSC server for every category (CI only;
   **not** a Live test, capabilities unchanged).
5. `ruff check . && pytest` green on merged `main`; Windows CI green; "Build exe" green with the
   GUI smoke; artifact link handed to the user.
6. `docs/USER_GUIDE.md` has a 10-minute test checklist for the user's return.

**Scope boundary:** no new sound engines, no contract changes (laser #422 stays open), no VST/plugin,
no Live writes beyond the existing tested capabilities, no taste/listening claims, no public release.

## Waves

| Wave | When | Work | Agents |
| --- | --- | --- | --- |
| W1 | Fri 13:00 → Sat morning | Audit (control inventory + gap issues + GUI tour harness); fixes of known side-findings in four disjoint areas; Windows-risk research note | 6 |
| W2 | Sat → Sun morning | Gap issues from the audit: shared settings, library/Live flow for all windows, honest error paths, Acid/Goa/Blaster export into the library | 5–8 |
| W3 | Sun → Mon morning | Polish and consistency (theme/widget kit everywhere, 150 % layout), perf, tour on Windows CI, user checklist | 4–6 |
| W4 | Mon morning | Final gate, exe build, CURRENT_STATE, hand-over | lead + 1 reviewer |

Every PR: independent `reviewer` (max 2 rounds), CI Ubuntu + Windows green, lead gate on merged
`main`. Agents work in disjoint file areas (one owner per file, D-017); the lead re-plans when an
area collides.

## Areas (one owner each)

- **A Library/Live flow:** `src/gui/live_panel.py`, `src/gui/library_panel.py`, `src/gui_core/live.py`, `src/gui_core/library.py`, Goa sample sidecars (#413, #414, #415).
- **B Form correctness/speed:** `src/gui_core/links.py`, `form.py`, `form_layout.py`, `valuemap.py`, `src/gui/category_panel.py`, `src/gui/widgets/`, blaster `fields.py` (#424, #428, #434).
- **C exe/launcher/build:** `src/launcher/`, `scripts/build_exe.py`, `.github/workflows/build-exe.yml` (lead hands this file over), `docs/setup/EXE.md` (#435, #436).
- **D QA tour/inventory:** `tests/gui/test_tour*.py`, `scripts/qa/gui_tour.py`, `tests/gui/conftest.py`.
- **E Tool windows:** `src/gui/acid/`, `src/gui/blaster/` (except `fields.py` in wave 1), `src/gui/skin/`, `src/gui/goa_panel.py`, `src/gui/windows.py`.
- **F Research:** `docs/research/2026-11-06_windows-gui-risks.md`.

## Lead routine

- Heartbeat: scheduled self-reminders every ~3 h keep the sprint moving if no agent reports.
- Keep 5–6 agents running; when one hands back, start the reviewer or the next issue in the same turn.
- After each merge: gate on merged `main`; after each wave: "Build exe" run, CURRENT_STATE line.
- Short phone-readable status via message after each wave.
