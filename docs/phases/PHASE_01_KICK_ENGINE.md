# PHASE 01 — Deterministic kick engine (no Claude)

**Status:** PLANNED · **Agent:** `audio-engineer` · **Tested in:** CI + user listening test

## Objective

Generate techno/trance kicks from a bounded parameter set, reproducibly, and write WAV + metadata. Prove the sound is good enough before anything else depends on it.

## Prerequisites

Phase 00 done. `contracts/kick-params.schema.json` and `contracts/sample-metadata.schema.json` exist as drafts.

Read `docs/research/2026-10-28_kick-gen2-learnings.md` once before starting (lessons from the earlier prototype, the measured taste range, market candidates, analysis pitfalls). It is input, not scope: nothing in it changes this phase's scope or acceptance criteria.

## Scope

1. `src/audio_engine/kick.py`: kick synthesis from `kick-params` (sine body with pitch envelope, amplitude envelope, transient/click layer, optional drive/saturation, DC-safe, no clipping above the configured ceiling).
2. `src/audio_engine/analysis.py`: measure peak (dBFS), length, estimated fundamental of the tail, decay time (−20 dB / −40 dB), DC offset.
3. `src/audio_engine/io.py`: write 24-bit WAV (48 kHz default) + sidecar JSON per `sample-metadata`; never overwrite (append a counter).
4. Variants: `variants: N` yields N kicks with derived seeds and small, documented parameter spreads.
5. 3–5 named presets (e.g. `dark-dry`, `punchy`, `rumble-ready`, `hard-trance`) as JSON in `src/audio_engine/presets/`.
6. CLI: `python -m audio_engine.kick --preset dark-dry --variants 3 --out <folder>`.
7. Finalise both contracts (bump to v1.0) in a separate `contract-change` PR if fields change.

## Out of scope

Claude, Ableton, UI, other instruments, generative models, real-time playback.

## Tests (CI)

- Same params + seed → byte-identical WAV (hash).
- Every preset renders; peak ≤ ceiling; no NaN/Inf; DC offset below a set threshold.
- Measured fundamental within ±10 % of `pitch_end_hz`; length within ±1 ms of `length_ms`.
- Invalid params (out of range, missing, unknown fields) are rejected with a clear error.
- Sidecar JSON validates against the schema and re-renders the identical WAV.

## Acceptance criteria

- [ ] All CI tests above pass on Ubuntu and Windows.
- [ ] The user ran the CLI on Windows, listened to all presets in Ableton, and noted in the issue which ones are usable. **The agent must not claim a listening result.**
- [ ] Known limitations documented in the PR.

## Handoff

PR body: what was built, real test output, open sound-design questions, State update proposal.
