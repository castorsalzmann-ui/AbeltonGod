# Interfaces

Machine-readable contracts live in `contracts/`. This file explains them. Changing a contract needs its own PR with the `contract-change` label.

| Contract | Producer → Consumer | Status |
| --- | --- | --- |
| `contracts/kick-params.schema.json` | Orchestrator / CLI → audio engine | draft v0.1 — finalised in Phase 01 |
| `contracts/sample-metadata.schema.json` | Audio engine → library, orchestrator | draft v0.1 — finalised in Phase 01 |
| `contracts/capabilities.json` (+ `capabilities.schema.json`) | Bridge → orchestrator | v1 — statuses updated in Phase 02 |
| `contracts/guard-policy.schema.json` → `config/guard-policy.json` | User config → resource guard | v1 — default values are untuned starting points |

## Kick parameters

All numeric parameters are bounded; out-of-range values are rejected, never clamped silently. `seed` makes output reproducible. `variants` asks for N variations around the given parameters, each with its own derived seed.

## Sample metadata

Every generated WAV gets a sidecar `<name>.json` with the parameters, seed, engine version, measured features (peak, length, fundamental, decay) and creation time. The engine must be able to re-render the exact WAV from its sidecar.

## Guard policy

One profile per request type (`kick_generation`, `mentor_answer`, …). The orchestrator picks the profile; the guard enforces it. Limits: output tokens per call, model calls, tool calls, cost estimate, timeout, identical tool calls (loop), files written, Ableton writes, and a warn threshold. Global: session and daily budget, max concurrent requests. Budget reservations must be atomic once requests run in parallel.

## Capabilities

Each entry: `id`, OSC address or LOM path, `status`, `evidence` (required when `tested`), `notes`. Only `tested` entries may be wrapped as Claude tools.
