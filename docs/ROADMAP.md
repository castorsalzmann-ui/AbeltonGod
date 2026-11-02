# Roadmap

Live cockpit (updates itself every 30 minutes): <https://castorsalzmann-ui.github.io/AbeltonGod/>

One phase at a time. A phase starts only after the previous phase's acceptance criteria are met and the user has approved.

| Phase | Spec | Goal | Tested where |
| --- | --- | --- | --- |
| 00 | `phases/PHASE_00_SETUP.md` | Repo, CI, agent rules | CI |
| 01 | `phases/PHASE_01_KICK_ENGINE.md` | Deterministic kick synthesis, 3 variants, WAV + metadata, no Claude | CI + user listening test |
| 02 | `phases/PHASE_02_ABLETON_BRIDGE.md` | AbletonOSC in Live 12 Standard: read, one harmless write, undo, capability registry filled | User's machine |
| 03 | `phases/PHASE_03_SAMPLE_IMPORT.md` | Generated kick lands in the Live project | User's machine |
| 04a | `phases/PHASE_04A_RESOURCE_GUARD.md` | Agent Resource Guard: limits for tokens, calls, cost, time, loops, file and Ableton writes | CI |
| 04b | `phases/PHASE_04B_CLAUDE_ORCHESTRATOR.md` | Natural language → validated kick parameters → engine → import, all through the guard | CI (schemas, fake bridge) + user's machine |
| 05 | `phases/PHASE_05_KICK_CHARACTER.md` | Kicks with own character: preset `dense`, kick-params v0.3 (key, length by tempo, layering, clip, click shape), reference kicks | CI + user listening tests + user's machine |

Phases 01, 02 and 04a are independent and may run in parallel (different agents, different folders). 04b needs all of 01–04a.

## Pipeline (parallel tracks, D-020 / D-023)

Since 2026-10-29 several tracks run side by side, one task per role at a time (D-019). Status as of 2026-11-02; the cockpit shows the current state.

| Track | Phase | Role(s) | Goal | Status |
| --- | --- | --- | --- | --- |
| A | arrangement planner (D-024) | bridge-engineer, sound-designer, later orchestrator-engineer | Plan a track as an energy line on a DJ-phrase grid; AbeltonGod builds the arrangement | Phase 03 DONE (2026-10-29); sections/energy proposal PR #141; arrangement capability check #140 in work; then plan-format contract and planner window |
| B | 04b | orchestrator-engineer | Claude generates kicks and imports them; plans arrangements | Tools `generate_kick`, `list_tracks`, `import_sample` merged; `plan_arrangement` in review (PR #223); user acceptance run on the PC pending |
| C | 05 kick character | audio-engineer, sound-designer | Kicks with own character | **CLOSED 2026-11-02** after listening test 3; next: keyword vocabulary (#226) |
| D | ongoing | qa-tester | Faster checks without less depth | Test-time cuts (PR #219, #225); load-only flaky tests collected in #180 |
| R | parking-lot pre-work | researcher | Feasibility notes before any parking-lot feature (D-023) | All five notes merged (#98–#102) |

Waiting for user decisions (questionnaire "Braucht eine Entscheidung", D-022): further sample categories, MIDI/arrangement, mix check, desktop UI, AI audio (D-005 stays until reopened), sound profile details (#110).

## Features (status, research, work)

One row per feature. The cockpit reads this table (`scripts/qa/cockpit_collect.py`), so keep the columns. Status: `Fertig`, `In Arbeit`, `Geplant`, `Parkplatz`. Research = files in `docs/research/` (comma separated); Work = issues and PRs. Updated by the lead after every merge.

| Feature | Phase | Status | Research | Work |
| --- | --- | --- | --- | --- |
| Kick-Engine (deterministisch, WAV + Sidecar) | 01 | Fertig | 2026-10-28_kick-gen2-learnings.md | PR #8 |
| Kick-Charakter (Preset dense, Tempo-Länge, Klick, Clip) | 05 | Fertig | 2026-10-28_kick-gen2-learnings.md, 2026-11-02_listening-test-3-plan.md | #103, PR #123, #130, #214 |
| Kick-Layering | 05 | Parkplatz | 2026-11-02_kick-layering-and-reference-steering.md | #57 (Hörtest: kaum hörbar, nicht verfolgt) |
| Kick-Keyword-Vokabular mit Gewichten | 05 | In Arbeit | 2026-10-28_kick-gen2-learnings.md | #226 |
| OSC-Client + Capability-Registry | 02 | Fertig | 2026-10-28_abletonosc-protocol-and-create-audio-clip.md | PR #87 |
| Import ins Live-Projekt (create_audio_clip, Undo) | 03 | Fertig | 2026-10-28_ableton-integration.md, 2026-10-28_abletonosc-protocol-and-create-audio-clip.md | #129, PR #134 |
| Agent Resource Guard (Limits, Schleifen, Usage-Log) | 04a | Fertig | 2026-10-28_guard-sdk-mapping.md | PR #15, #174 (Limits aus echten Daten offen) |
| Terminal-Chat mit Claude-Tools (Kicks, Import) | 04b | In Arbeit | 2026-10-28_agent-sdk-behaviour.md, 2026-10-28_claude-auth-options.md, 2026-10-28_tool-schema-generation.md | #23, #83, PR #168; Abnahmelauf am PC offen |
| Arrangement-Planer: Format + Layout + Energie + Timeline | 05 | Fertig | 2026-10-29_arrangement-planner-sections-energy.md, 2026-11-02_arrangement-plan-generator-design.md | #139, PR #182, #216, #220, #224 |
| Arrangement-Planer als Claude-Werkzeug (plan_arrangement) | 04b | In Arbeit | 2026-11-02_arrangement-plan-generator-design.md | #222, PR #223 |
| Arrangement ins Live schreiben (Clips, Locators) | 05 | Geplant | 2026-10-29_live-midi-arrangement-devices.md | #140 (wartet auf deinen Live-Lauf), G6 |
| Planer-Fenster (Energielinie zeichnen) | 05 | Parkplatz | 2026-10-29_arrangement-planner-sections-energy.md | du entwirfst es in Claude Design |
| Weitere Sample-Kategorien (Hats, Clap, Bass, FX) | 06 | Geplant | 2026-10-29_bandit-wheel-synthesis-transfer.md, 2026-10-29_bandit-wheel-musical-transfer.md | #151, Vorschlag in Arbeit |
| Referenz-Sample-Analyse (eigene Kicks als Vorbild) | 06 | Parkplatz | 2026-11-02_kick-layering-and-reference-steering.md | #58 |
| Kick im Mix (Pegel, Sidechain, Loudness) | 07 | Parkplatz | 2026-10-29_kick-in-tracks.md, 2026-10-29_mix-loudness-targets.md | - |
| Mix-Analyse und Mastering | 07 | Parkplatz | 2026-10-29_mix-loudness-targets.md | - |
| Desktop-UI mit Sample-Picker | 08 | Parkplatz | 2026-10-29_desktop-window-windows.md | - |
| Persönliches Klangprofil (Hör- und Wahl-Log) | 08 | Parkplatz | - | #110 |
| Generatives Audio-Backend | 08 | Parkplatz | 2026-10-29_ai-audio-one-shots.md | D-005 gilt bis zur Wiedereröffnung |
| Eigene VST3-Plugins (JUCE) | 08 | Parkplatz | - | - |
| Guard-Extras (Modell-Downgrade, Dashboard) | 08 | Parkplatz | - | - |

## Non-goals for the MVP (Phases 00–04b)

- No sample types other than kick — one element must sound good first.
- No desktop UI — a terminal chat is enough to prove the workflow.
- No arrangement, MIDI generation, mixing or mastering — they need a working bridge and audio capture first.
- No generative audio models — D-005.
- No Max for Live — D-001.
- No changes to the user's real projects — tests run against a dedicated test set.
- No cloud services besides Claude — everything else runs locally.
- No multi-user, accounts or sharing — personal tool.

## Parking lot (no spec yet)

Ideas live here or as GitHub issues labelled `parking-lot`. Revisit after the MVP.

Stabilisation (action log, error handling) · more sample categories (bass, percussion, hats) · reference sample analysis · MIDI and arrangement engine with energy curve · mix analysis (needs a validated audio capture path) · mastering · desktop UI with circular sample picker · Max for Live UI if the user upgrades to Suite · own VST3 plugins (JUCE) · personal sound profile · generative audio backend · guard extras (model downgrade, context summarisation, dashboard).
