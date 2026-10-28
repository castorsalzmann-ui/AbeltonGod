# Current State

_Last updated: 2026-10-28 · Written only by the lead session on `main` after a merge._

## Phase

- **Phase 00 — Setup:** done except the user's local check (#1).
- **Phase 01 — Kick engine:** core merged (#2 via PR #8). Open: #11, #12, then #3.

## What works (with evidence)

| Item | Evidence |
| --- | --- |
| Repo scaffold, contracts, contract tests | [CI run 40604382687](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/40604382687) |
| Deterministic kick engine core: `render_kick`, `analyse`, `write_kick`, `rerender_from_sidecar` (`src/audio_engine/`) | [PR #8](https://github.com/castorsalzmann-ui/AbeltonGod/pull/8), merged as 7316f85 after six independent review rounds; `899 passed, 2 skipped`; [CI run 40666798325](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/40666798325) ubuntu + windows. ffmpeg decodes the WAVs bit-identically (round-6 review). |

**Measured limits of the kick core** (details in PR #8):
- Pitch accuracy: ±3 % for windows ≥ 80 ms, ±5 % below (user decision).
- About 10 % of very short, fast-decay kicks report `fundamental_hz: None`.
- Byte identity is proven per platform only, not Linux vs. Windows.
- No listening test yet.

## What does not exist yet

- Kick presets, variants, CLI (#3)
- Ableton bridge / AbletonOSC setup (Phase 02: #4, #5)
- Sample import into Live (Phase 03)
- Agent Resource Guard (Phase 04a, #6): policy contract and defaults exist, no code
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
| Reference tracks / artists | Not provided yet. Reference kick measurements are proposed in open PR #10 (another session); not merged. |

## Next step

- **Kick track:**
  1. #11 — tests for tone, drive and the envelope; nothing protects them today.
  2. #12 — WAV/sidecar nits, incl. the 24-bit pad byte that matters for the Ableton import.
  3. #7 — contract semantics.
  4. Then #3 — presets, variants, CLI and the first listening test, which includes #9.
- **Bridge track, in parallel:** #4 (OSC client, `bridge-engineer`), then #5 (needs #1 and the user's machine).
- **Lower priority:** #6 (resource guard), before Phase 04b.
- **User:**
  - #1 (`pytest` locally, `gh auth login`).
  - Decide on PR #10 (reference-kick note from another session). It also proposes D-012 "genre-fluid kick engine" and renaming the `hard-trance` example preset; these are not adopted until merged.

## Open questions

- #9 — is the DC-correction sub-bass tail of very short or extreme kicks audible? Up to 11.4 % of peak at the extremes, plus a −28 dB tail from the DC blocker. To be answered in the #3 listening test.
- Reference tracks / artists for later style work: user will provide them later; not needed for the MVP.
