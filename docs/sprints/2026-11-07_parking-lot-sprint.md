# Sprint W2 — parking-lot features (2026-11-07 08:00 → 2026-11-09 13:00)

Lead-owned. User, 2026-11-07 07:57: "lass uns den nächsten sprint planen und sachen aus dem parkplatz tacklen. Selbes prinzip". Decision record: D-032.

## Workstreams (one owner each; every PR reviewed, CI Ubuntu + Windows green, gate = CI on `main` after each merge)

| ID | Parking-lot item | What exists afterwards | Owner | Issue |
| --- | --- | --- | --- | --- |
| P | More sample categories: percussion | Contract `perc-params` v0.1 (models conga, tom, shaker, cowbell, clave), engine, presets, CLI, GUI page (via the category registry), library folder `Samples/Drums/Percs` | audio-engineer | new |
| L | Listening/choice log (#110) | Contract for a JSONL choice log; library page buttons "Favorit", "Passt nicht", note; log viewer; sidecar link by sha256; no upload, no model training | general-purpose (GUI) + contract-change | #110 |
| R | Reference steering, first slice (#58) | GUI page "Referenz": pick a WAV, run the existing deterministic analysis, show measured values next to the nearest kick preset/variant, "als Startwerte übernehmen" fills the kick form; no claim that it sounds alike | audio-engineer (fit) | #58 |
| A | Arrangement planner page (#139, D-024) | GUI page over the merged planner (`generate_plan`, `derive_timeline`): template, length, energy nodes drawn on a curve, section table, export plan JSON; no Live writes | general-purpose (GUI) | #139 |
| F | FX transitions (riser, downlifter, impact, noise sweep) | Dated research note with targets and a contract proposal; engine follows in a later sprint | researcher | new |

Wave 1 (Sat): P contract, L contract, A page, F note. Wave 2 (Sat night–Sun): P engine + GUI, L GUI, R. Wave 3 (Sun–Mon): polish, tour/inventory updated for new pages, exe build, CURRENT_STATE, user checklist additions.

## Scope boundary

No Live writes beyond `tested` capabilities; no listening or taste claims; toms only as a `perc` model, default off outside presets named for hard groove (user's stated dislike, musical note H3); no generative audio; no new heavy dependency without a reason in the PR; usage budget: at most 4–5 agents at once.

## Done when

Each workstream's PR merged with review; GUI tour covers the new pages and stays without known gaps; Windows exe build green with screenshots; `docs/USER_GUIDE.md` lists what to try.
