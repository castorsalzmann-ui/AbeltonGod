# Current State

_Last updated: 2026-10-28 · Written only by the lead session on `main` after a merge._

## Phase

**Phase 00 — Setup: in progress.** Repository scaffold, CI and agent rules exist. Nothing product-related is implemented yet.

## What works (with evidence)

| Item | Evidence |
| --- | --- |
| Repo scaffold, contracts, contract tests | `pytest`: 8 passed (lead session, Linux); [CI run 40604382687](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/40604382687) green on ubuntu-latest and windows-latest |
| Labels and issues #1–#5 | Created on GitHub 2026-10-28 |

## What does not exist yet

- Kick synthesis engine (Phase 01)
- Ableton bridge / AbletonOSC setup (Phase 02)
- Sample import into Live (Phase 03)
- Agent Resource Guard (Phase 04a) — policy contract and defaults exist, no code
- Claude orchestrator / chat (Phase 04b)

## Environment facts (from the user, 2026-10-28)

| Fact | Value |
| --- | --- |
| OS | Windows |
| Ableton | Live 12 **Standard** (no Max for Live), always updated to the latest release → well above 12.0.5; exact number to note at Phase 02 start |
| Project sample rate | 48 kHz (engine default 48 kHz / 24-bit) |
| GPU | NVIDIA RTX 5070 |
| Claude access | Max subscription (no separate API key yet) |
| First sample type | Kick |
| Languages | German and English |
| Control surfaces / controllers in use | None — all 6 slots free |
| Reference tracks / artists | Not provided yet |

## Next step

- User, when back at the Windows PC: finish issue #1 (`pytest` locally, `gh auth login`). Does not block #2, #4 or #6.
- Ready to start in parallel: #2 (kick core, `audio-engineer`) and #4 (OSC client, `bridge-engineer`).
- Also ready, lower priority: #6 (Agent Resource Guard, D-011). Must land before Phase 04b makes a real Claude call.
- Blocked until their dependencies land: #3 (needs #2), #5 (needs #4 and #1).

## Open questions

- Reference tracks / artists for later style work — user will provide later; not needed for the MVP.
