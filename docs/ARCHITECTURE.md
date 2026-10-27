# Architecture

Status markers: **[planned]** not built · **[building]** in progress · **[done]** merged with evidence.

```
┌───────────────────────────────┐
│ UI / Chat  [planned, Phase 04]│  Desktop app or CLI first
└──────────────┬────────────────┘
               │ user intent
┌──────────────▼────────────────┐
│ Orchestrator  [planned, 04]   │  Claude: chooses tools + parameters,
│                               │  validated against contracts/*.schema.json
└───┬───────────────┬───────────┘
    │               │
┌───▼──────────┐ ┌──▼──────────────────────┐
│ Audio engine │ │ Ableton bridge           │
│ [planned, 01]│ │ [planned, 02]            │
│ Python DSP   │ │ OSC client (Python)      │
│ kick synth,  │ │   ⇅ localhost 11000/11001│
│ analysis,    │ │ AbletonOSC remote script │
│ WAV + JSON   │ │   inside Live 12 Standard│
└───┬──────────┘ └──┬──────────────────────┘
    │ files         │ LOM calls (only `tested` capabilities)
┌───▼───────────────▼───────────┐
│ Project folder on disk        │  Samples/Drums/…, sidecar metadata JSON
└───────────────────────────────┘
```

## Modules (target layout)

| Path | Responsibility | Phase |
| --- | --- | --- |
| `src/audio_engine/` | Kick synthesis, later other elements; analysis; WAV + metadata writing | 01 |
| `src/bridge/` | OSC client, capability checks, action log, undo helpers | 02 |
| `src/library/` | Project folder layout, safe file naming, import workflow | 03 |
| `src/orchestrator/` | Claude tool definitions, schema validation, approval levels | 04 |
| `contracts/` | JSON schemas and the capability registry shared by all modules | 00+ |

## Rules

- Engine and bridge never import the orchestrator. The orchestrator calls them through schemas.
- Nothing in the audio path waits on the network.
- Files are never overwritten; a new variant gets a new name.
- Approval levels (from PRODUCT_SPEC 3.3): suggest → confirm → approved routine → critical (re-confirm).
