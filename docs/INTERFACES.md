# Interfaces

Machine-readable contracts live in `contracts/`. This file explains them. Changing a contract needs its own PR with the `contract-change` label.

| Contract | Producer → Consumer | Status |
| --- | --- | --- |
| `contracts/kick-params.schema.json` | Orchestrator / CLI → audio engine | draft v0.1 — finalised in Phase 01 |
| `contracts/sample-metadata.schema.json` | Audio engine → library, orchestrator | draft v0.1 — finalised in Phase 01 |
| `contracts/capabilities.json` (+ `capabilities.schema.json`) | Bridge → orchestrator | v1 — statuses updated in Phase 02 |

## Kick parameters

All numeric parameters are bounded; out-of-range values are rejected, never clamped silently. `seed` makes output reproducible. `variants` asks for N variations around the given parameters, each with its own derived seed.

## Sample metadata

Every generated WAV gets a sidecar `<name>.json` with the parameters, seed, engine version, measured features (peak, length, fundamental, decay) and creation time. The engine must be able to re-render the exact WAV from its sidecar.

## Capabilities

Each entry: `id`, OSC address or LOM path, `status`, `evidence` (required when `tested`), `notes`. Only `tested` entries may be wrapped as Claude tools.
