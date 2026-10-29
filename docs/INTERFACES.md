# Interfaces

Machine-readable contracts live in `contracts/`. This file explains them. Changing a contract needs its own PR with the `contract-change` label.

| Contract | Producer → Consumer | Status |
| --- | --- | --- |
| `contracts/kick-params.schema.json` | Orchestrator / CLI → audio engine | v0.3 (#104, follow-ups #131); the engine renders 0.2 and 0.3 (PR #130) |
| `contracts/tool-generate-kick.schema.json` | Orchestrator (tool definition) → Claude | strict-subset variant of kick-params 0.3 for the `generate_kick` tool (#131); the engine still validates against `kick-params.schema.json` |
| `contracts/sample-metadata.schema.json` | Audio engine → library, orchestrator | draft v0.1 — finalised in Phase 01 |
| `contracts/capabilities.json` (+ `capabilities.schema.json`) | Bridge → orchestrator | v1 — statuses updated in Phase 02 (#42: entry `track.mute.get` added, no format change) and Phase 03 (#50: `clip_slot.create_audio_clip` → `tested`, no format change; #143: `song.create_audio_track` → `tested`, own `tested` entries `track.has_audio_input.get`, `clip_slot.has_clip.get`, `clip.file_path.get`, `song.num_scenes.get` (no borrowed gate any more), no format change; one undo may revert track + clip together) |
| `contracts/guard-policy.schema.json` → `config/guard-policy.json` | User config → resource guard | v1 — default values are untuned starting points |

## Kick parameters

All numeric parameters are bounded; out-of-range values are rejected, never clamped silently. `seed` makes output reproducible. `variants` asks for N variations around the given parameters, each with its own derived seed.

Envelope semantics (v0.2, issue #7; full text in the schema's `description`s):

- `pitch_decay_ms` is the **time constant** τ of `f(t) = pitch_end_hz + (pitch_start_hz − pitch_end_hz) · e^(−t/τ)`, not the time until the pitch arrives. `pitch_end_hz` is the asymptote. Default 15 ms (was 40).
- `amp_decay_ms` is the time to fall **60 dB** after the attack (−20 dB after a third, −40 dB after two thirds).
- **Pitch-settle guideline** (not enforced by the schema): presets and Claude keep `pitch_decay_ms ≤ audio_engine.params.max_settled_pitch_decay_ms(params)`, so the pitch is within 5 % of `pitch_end_hz` once the level is 20 dB down (or at `length_ms`). Larger values only for a deliberately pitchy kick.
- A silent render never gets a sidecar: `write_kick` refuses it, so `features.peak_dbfs` stays a required number.
- Version coupling: `sample-metadata` stays at 0.1, but its `parameters` object now carries kick-params 0.2. A **request** with kick-params 0.1 is rejected (it may rely on the old default). A **sidecar** with 0.1 parameters can still be rendered, because it stores every resolved value: `rerender_from_sidecar` upgrades it to 0.2 when `pitch_decay_ms` is present and rejects it otherwise. Every 0.1 sidecar written so far comes from engine 0.0.1, so it needs `allow_engine_mismatch=True` (see below).

v0.3 (#104, rendered since PR #130; Phase 05 tasks "Grundton nach Tonart", "Kick-Länge nach Tempo", "mehr Biss im Klick", "zwei Kicks abstimmen"; `clip_db` weighted by listening test 1 pair P3, #103; full text in the schema):

| Field | Range | Default | Meaning |
| --- | --- | --- | --- |
| `tail_note` | integer 23 … 46 | absent → `pitch_end_hz` | MIDI note (69 = 440 Hz, equal temperament); sets `pitch_end_hz` = 440 · 2^((n − 69)/12). 23 … 46 = the notes inside 30 … 120 Hz. Excludes `pitch_end_hz`. The contract takes the number only; converting note names ("F1", Ableton "F0") and keys to it is done by the UI/orchestrator. |
| `length_beats` | 0.25 … 4 | absent → `length_ms` | File length in quarter notes at `bpm` (required); excludes `length_ms`; the resulting ms must lie in 80 … 2000 (engine check; a result at most 1e-9 ms outside counts as that limit). The rendered output must be 60 dB down before that end: a missing `amp_decay_ms` is derived to fit, an explicit one that does not fit is rejected (user decision on PR #114). Exact rule in the schema: rectangular 5 ms RMS (`sample_rate // 200` samples), hop 1 sample, on the quantised WAV samples; the end of the first window 60 dB below the RMS maximum must lie before the 5 ms end fade-out; derivation by bisection on a 0.1 ms grid 20 … 2000 ms (2000.0 fits → 2000.0; 20.0 does not fit → rejected). Fitting is **not** monotonic in `amp_decay_ms` (PR #130, cause not established), so the derived value is the bisection result: it fits, but is not always the longest fitting value, and a rejection only means that neither 2000.0 nor 20.0 fits. |
| `click_decay_ms` | 0.5 … 12 | 3 (engine 0.1.0 constant) | Click decay time constant; click window max(15, 5 · τ) ms. |
| `click_q` | 0.5 … 8 | 0.9 (engine 0.1.0 constant) | Q of the click band-pass. |
| `polarity` | 1 or −1 | 1 | Sign of the whole output, after the peak ceiling. |
| `offset_ms` | 0 … 12 | 0 | Silence before the kick; file length unchanged. Whole samples: `n_off = round(offset_ms · sample_rate / 1000)` (Python `round`, halves to even). The kick is rendered into `n − n_off` samples (DC blocker, clip, 5 ms end fade-out, mean correction and normalisation included), then `n_off` zeros are put in front; polarity comes after. |
| `clip_db` | 0 … 12 | 0 (stage off) | Hard clip before the ceiling: peaks pushed `clip_db` over the clip point (oversampled), then back to `peak_ceiling_dbfs`. |

- The v0.3 fields are allowed only with `schema_version` "0.3" (they sit in the schema's `allOf` 0.3 branch; the schema uses `unevaluatedProperties: false`). A 0.2 document is unchanged: every 0.2 request, preset and sidecar still validates, and resolving it adds no new key, so sidecar and WAV bytes stay the same.
- **Resolved form** (what `resolve_kick_params` returns, the sidecar stores and `rerender_from_sidecar` renders from): every default is filled, but `tail_note` is replaced by the derived `pitch_end_hz`, `length_beats` by the derived `length_ms`, and an `amp_decay_ms` derived under `length_beats` is stored as `amp_decay_ms`. A resolved form therefore never holds `tail_note` or `length_beats`, is valid under the same schema, and re-renders the same samples without a new derivation. The derived `length_ms` is the float result of `length_beats` · 60000 / `bpm`; a result at most 1e-9 ms below 80 or above 2000 is stored as exactly 80.0 / 2000.0 (2.14 beats at 64.2 BPM compute as 2000.0000000000002 ms). The inputs are recoverable **only up to float rounding**: `tail_note` = 69 + 12 · log2(`pitch_end_hz` / 440), `length_beats` = `length_ms` · `bpm` / 60000 (3.97 beats at 180.4 BPM recover as 3.9699999999999993; the snap adds at most 1e-9 · `bpm` / 60000 beats). `features` are measured from the WAV and do not depend on this.
- The engine renders 0.2 and 0.3 (`audio_engine.params.RENDERED_SCHEMA_VERSIONS`, PR #130). The v0.3 fields stay in the `allOf` branch (#131): under `properties` the engine would fill their defaults into every 0.2 sidecar.
- Error texts of the −60 dB rule (the contract quotes the engine; a test pins both): no fit under (6a) → `amp_decay_ms: the contract's bisection (rule 6a) found no amp_decay_ms of 20 ms or more that decays 60 dB within length_beats at this bpm (…): 20.0 ms does not fit. …`; an explicit value that does not fit → `amp_decay_ms <v> does not decay 60 dB within …; the rule (6a) derives <d> for these values …`, or `amp_decay_ms <v>: ` + the (6a) text when (6a) rejects.

**Strict tool variant** (`contracts/tool-generate-kick.schema.json`, #131). `kick-params.schema.json` is not inside the strict tool-schema subset (`docs/research/2026-10-28_tool-schema-generation.md` Q1: no `minimum`/`maximum`/`maxLength`/`default`, no `if`/`then`, `dependent*`, `not`, `unevaluatedProperties`). The tool file is the same parameter space in that subset:

- Fields: every field of `properties` plus the seven v0.3 fields, flat in one `properties`, same names, same `required` (`schema_version`, `seed`), `additionalProperties: false`. 25 fields, **23 optional** (the same count PR #144 budgets for `generate_kick`: 23 + 0 + 1 = 24 of 24).
- Structure from the contract: `type` kept; `enum` kept with `type` added (`integer` for `sample_rate`, `bit_depth`, `polarity`); `schema_version` becomes `{"type": "string", "const": "0.3"}`, because without `if`/`then` the "v0.3 fields only with 0.3" gate cannot be expressed, and a 0.3 request without v0.3 fields gives the same samples as at 0.2 (its sidecar carries 0.3 and the v0.3 defaults).
- Dropped and moved into the field `description` as text: ranges (`Range lo ... hi`), defaults (`Default d` / `No default`), `preset` at most 64 characters, the exclusions `tail_note`/`pitch_end_hz` and `length_beats`/`length_ms`, and `length_beats` requires `bpm`. Descriptions are model-facing (no issue numbers, at most 600 characters).
- So the tool schema is **looser** than the contract: out-of-range values, the two exclusions, `length_beats` without `bpm` and a longer preset name pass it. The engine (`resolve_kick_params`, D-002) rejects them with its full error list; the handler must call it and never treat "valid against the tool schema" as valid. The other direction holds: every valid 0.3 request is valid against the tool schema (seeded test).
- Root `$schema`, `$id`, `title` are metadata; the tool builder drops them (same wiring precondition as the #81 tool schemas).
- `tests/test_contracts_generate_kick.py` regenerates the structure from `kick-params.schema.json` and compares, checks the strict subset, the optional count and every range/default text, so a contract change that is not carried over turns red.

## Sample metadata

Every generated WAV gets a sidecar `<name>.json` with the parameters, seed, engine version, measured features (peak, length, fundamental, decay) and creation time. The engine must be able to re-render the exact WAV from its sidecar.

Engine version (#35): `ENGINE_VERSION` is bumped on every change that alters rendered bytes, and golden SHA-256s in `tests/audio_engine/test_engine_version.py` catch a byte change without a bump. So a sidecar can only be reproduced by the engine version that wrote it: `rerender_from_sidecar` raises `audio_engine.io.EngineVersionMismatch` (a `ValueError`) when the sidecar's engine name or version differs. `allow_engine_mismatch=True` renders its parameters with the current engine anyway; the result is a new render, not a reproduction.

## Guard policy

One profile per request type (`kick_generation`, `mentor_answer`, …). The orchestrator picks the profile; the guard enforces it. Limits: output tokens per call, model calls, tool calls, cost estimate, timeout, identical tool calls (loop), files written, Ableton writes, and a warn threshold. Global: session and daily budget, max concurrent requests. Budget reservations must be atomic once requests run in parallel.

## Capabilities

Each entry: `id`, OSC address or LOM path, `status`, `evidence` (required when `tested`), `notes`. Only `tested` entries may be wrapped as Claude tools.
