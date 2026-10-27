# Current State

_Last updated: 2026-10-28 · Written only by the lead session on `main` after a merge._

## Phase

**Phase 00 — Setup: in progress.** Repository scaffold, CI and agent rules exist. Nothing product-related is implemented yet.

## What works (with evidence)

| Item | Evidence |
| --- | --- |
| Repo scaffold, contracts, contract tests | `pytest` passes locally in the scaffold commit; CI status: see Actions tab |

## What does not exist yet

- Kick synthesis engine (Phase 01)
- Ableton bridge / AbletonOSC setup (Phase 02)
- Sample import into Live (Phase 03)
- Claude orchestrator / chat (Phase 04)

## Environment facts (from the user, 2026-10-28)

| Fact | Value |
| --- | --- |
| OS | Windows |
| Ableton | Live 12 **Standard** (no Max for Live) |
| GPU | NVIDIA RTX 5070 |
| Claude access | Max subscription (no separate API key yet) |
| First sample type | Kick |
| Languages | German and English |
| Other control-surface scripts in use | Unknown — check before Phase 02 (Live has 6 control-surface slots) |
| Reference tracks / artists | Not provided yet |

## Next step

Close Phase 00 (confirm CI green on GitHub), then start Phase 01: `docs/phases/PHASE_01_KICK_ENGINE.md`.

## Open questions

- Which other control-surface scripts or controllers occupy slots in Live?
- Preferred sample rate for the project folder (44.1 kHz vs 48 kHz)? Default assumed: 48 kHz / 24-bit.
