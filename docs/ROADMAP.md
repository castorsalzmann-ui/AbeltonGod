# Roadmap

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

Since 2026-10-29 several tracks run side by side, one task per role at a time (D-019). Status as of 2026-10-29 16:15; the cockpit shows the live state.

| Track | Phase | Role(s) | Goal | Status |
| --- | --- | --- | --- | --- |
| A | arrangement planner (D-024) | bridge-engineer, sound-designer, later orchestrator-engineer | Plan a track as an energy line on a DJ-phrase grid; AbeltonGod builds the arrangement | Phase 03 DONE (2026-10-29); sections/energy proposal PR #141; arrangement capability check #140 in work; then plan-format contract and planner window |
| B | 04b step 2 | orchestrator-engineer | Claude generates kicks and imports them | Agent SDK client merged (PR #122); first real Claude call on the user's PC (#83); tool schemas #81 in work |
| C | 05 kick character | audio-engineer, sound-designer | Kicks with own character | Preset `dense`, v0.3 contract and engine merged (PRs #123, #114, #130); contract follow-ups #131; fresh-seed findings #115 |
| D | ongoing | qa-tester | Faster checks without less depth | Shared generator (PR #117) and hotfix #137 (PR #138) merged; #119 next |
| R | parking-lot pre-work | researcher | Feasibility notes before any parking-lot feature (D-023) | All five notes merged (#98–#102) |

Waiting for user decisions (questionnaire "Braucht eine Entscheidung", D-022): further sample categories, MIDI/arrangement, mix check, desktop UI, AI audio (D-005 stays until reopened), sound profile details (#110).

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
