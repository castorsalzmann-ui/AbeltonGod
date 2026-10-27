# Roadmap

One phase at a time. A phase starts only after the previous phase's acceptance criteria are met and the user has approved.

| Phase | Spec | Goal | Tested where |
| --- | --- | --- | --- |
| 00 | `phases/PHASE_00_SETUP.md` | Repo, CI, agent rules | CI |
| 01 | `phases/PHASE_01_KICK_ENGINE.md` | Deterministic kick synthesis, 3 variants, WAV + metadata, no Claude | CI + user listening test |
| 02 | `phases/PHASE_02_ABLETON_BRIDGE.md` | AbletonOSC in Live 12 Standard: read, one harmless write, undo, capability registry filled | User's machine |
| 03 | `phases/PHASE_03_SAMPLE_IMPORT.md` | Generated kick lands in the Live project | User's machine |
| 04 | `phases/PHASE_04_CLAUDE_ORCHESTRATOR.md` | Natural language → validated kick parameters → engine → import | CI (schemas, fake bridge) + user's machine |

Phases 01 and 02 are independent and may run in parallel (different agents, different folders).

## Later (no spec yet)

Stabilisation (action log, error handling) · more sample categories (bass, percussion, hats) · reference sample analysis · MIDI and arrangement engine with energy curve · mix analysis (needs a validated audio capture path) · mastering · Max for Live UI if the user upgrades to Suite · own VST3 plugins (JUCE) · personal sound profile · generative audio backend.
