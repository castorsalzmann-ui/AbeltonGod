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

- User: finish issue #1 (pytest on Windows, exact Live version, occupied control-surface slots, `gh auth login`).
- Ready to start in parallel: #2 (kick core, `audio-engineer`) and #4 (OSC client, `bridge-engineer`).
- Blocked until their dependencies land: #3 (needs #2), #5 (needs #4 and #1).

## Open questions

- Which other control-surface scripts or controllers occupy slots in Live?
- Preferred sample rate for the project folder (44.1 kHz vs 48 kHz)? Default assumed: 48 kHz / 24-bit.
