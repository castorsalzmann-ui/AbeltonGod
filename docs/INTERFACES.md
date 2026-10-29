# Interfaces

Machine-readable contracts live in `contracts/`. This file explains them. Changing a contract needs its own PR with the `contract-change` label.

| Contract | Producer → Consumer | Status |
| --- | --- | --- |
| `contracts/kick-params.schema.json` | Orchestrator / CLI → audio engine | draft v0.3 proposal (#104); the engine renders 0.2 only |
| `contracts/sample-metadata.schema.json` | Audio engine → library, orchestrator | draft v0.1 — finalised in Phase 01 |
| `contracts/capabilities.json` (+ `capabilities.schema.json`) | Bridge → orchestrator | v1 — statuses updated in Phase 02 (#42: entry `track.mute.get` added, no format change) and Phase 03 (#50: `clip_slot.create_audio_clip` → `tested`, no format change) |
| `contracts/guard-policy.schema.json` → `config/guard-policy.json` | User config → resource guard | v1 — default values are untuned starting points |
| `contracts/tool-list-tracks.schema.json`, `contracts/tool-import-sample.schema.json` | Claude (tool arguments) → orchestrator | v1 (#81) — input schemas only; not wired yet |

## Kick parameters

All numeric parameters are bounded; out-of-range values are rejected, never clamped silently. `seed` makes output reproducible. `variants` asks for N variations around the given parameters, each with its own derived seed.

Envelope semantics (v0.2, issue #7; full text in the schema's `description`s):

- `pitch_decay_ms` is the **time constant** τ of `f(t) = pitch_end_hz + (pitch_start_hz − pitch_end_hz) · e^(−t/τ)`, not the time until the pitch arrives. `pitch_end_hz` is the asymptote. Default 15 ms (was 40).
- `amp_decay_ms` is the time to fall **60 dB** after the attack (−20 dB after a third, −40 dB after two thirds).
- **Pitch-settle guideline** (not enforced by the schema): presets and Claude keep `pitch_decay_ms ≤ audio_engine.params.max_settled_pitch_decay_ms(params)`, so the pitch is within 5 % of `pitch_end_hz` once the level is 20 dB down (or at `length_ms`). Larger values only for a deliberately pitchy kick.
- A silent render never gets a sidecar: `write_kick` refuses it, so `features.peak_dbfs` stays a required number.
- Version coupling: `sample-metadata` stays at 0.1, but its `parameters` object now carries kick-params 0.2. A **request** with kick-params 0.1 is rejected (it may rely on the old default). A **sidecar** with 0.1 parameters can still be rendered, because it stores every resolved value: `rerender_from_sidecar` upgrades it to 0.2 when `pitch_decay_ms` is present and rejects it otherwise. Every 0.1 sidecar written so far comes from engine 0.0.1, so it needs `allow_engine_mismatch=True` (see below).

v0.3 proposal (#104, Phase 05 tasks "Grundton nach Tonart", "Kick-Länge nach Tempo", "mehr Biss im Klick", "zwei Kicks abstimmen"; `clip_db` weighted by listening test 1 pair P3, #103; full text in the schema):

| Field | Range | Default | Meaning |
| --- | --- | --- | --- |
| `tail_note` | integer 23 … 46 | absent → `pitch_end_hz` | MIDI note (69 = 440 Hz, equal temperament); sets `pitch_end_hz` = 440 · 2^((n − 69)/12). 23 … 46 = the notes inside 30 … 120 Hz. Excludes `pitch_end_hz`. The contract takes the number only; converting note names ("F1", Ableton "F0") and keys to it is done by the UI/orchestrator. |
| `length_beats` | 0.25 … 4 | absent → `length_ms` | File length in quarter notes at `bpm` (required); excludes `length_ms`; the resulting ms must lie in 80 … 2000 (engine check). The rendered output must be 60 dB down before that end: a missing `amp_decay_ms` is derived to fit, an explicit one that does not fit is rejected (user decision on PR #114). Exact rule in the schema: rectangular 5 ms RMS (`sample_rate // 200` samples), hop 1 sample, on the quantised WAV samples; the end of the first window 60 dB below the RMS maximum must lie before the 5 ms end fade-out; derivation by bisection on a 0.1 ms grid 20 … 2000 ms; no fit at 20 ms → rejected. |
| `click_decay_ms` | 0.5 … 12 | 3 (engine 0.1.0 constant) | Click decay time constant; click window max(15, 5 · τ) ms. |
| `click_q` | 0.5 … 8 | 0.9 (engine 0.1.0 constant) | Q of the click band-pass. |
| `polarity` | 1 or −1 | 1 | Sign of the whole output, after the peak ceiling. |
| `offset_ms` | 0 … 12 | 0 | Silence before the kick; file length unchanged. |
| `clip_db` | 0 … 12 | 0 (stage off) | Hard clip before the ceiling: peaks pushed `clip_db` over the clip point (oversampled), then back to `peak_ceiling_dbfs`. |

- The v0.3 fields are allowed only with `schema_version` "0.3" (they sit in the schema's `allOf` 0.3 branch; the schema uses `unevaluatedProperties: false`). A 0.2 document is unchanged: every 0.2 request, preset and sidecar still validates, and resolving it adds no new key, so sidecar and WAV bytes stay the same.
- **Resolved form** (what `resolve_kick_params` returns, the sidecar stores and `rerender_from_sidecar` renders from): every default is filled, but `tail_note` is replaced by the derived `pitch_end_hz`, `length_beats` by the derived `length_ms`, and an `amp_decay_ms` derived under `length_beats` is stored as `amp_decay_ms`. A resolved form therefore never holds `tail_note` or `length_beats`, is valid under the same schema, and re-renders the same samples without a new derivation. The inputs are recoverable (`tail_note` = 69 + 12 · log2(`pitch_end_hz` / 440), `length_beats` = `length_ms` · `bpm` / 60000). `features` are measured from the WAV and do not depend on this. Whether the library or the file name shows the note is for #120.
- The engine refuses `schema_version` "0.3" until it implements these fields (`audio_engine.params.RENDERED_SCHEMA_VERSIONS`), so no field is ever silently ignored. The implementation PR moves the fields into `properties`.

## Sample metadata

Every generated WAV gets a sidecar `<name>.json` with the parameters, seed, engine version, measured features (peak, length, fundamental, decay) and creation time. The engine must be able to re-render the exact WAV from its sidecar.

Engine version (#35): `ENGINE_VERSION` is bumped on every change that alters rendered bytes, and golden SHA-256s in `tests/audio_engine/test_engine_version.py` catch a byte change without a bump. So a sidecar can only be reproduced by the engine version that wrote it: `rerender_from_sidecar` raises `audio_engine.io.EngineVersionMismatch` (a `ValueError`) when the sidecar's engine name or version differs. `allow_engine_mismatch=True` renders its parameters with the current engine anyway; the result is a new render, not a reproduction.

## Guard policy

One profile per request type (`kick_generation`, `mentor_answer`, …). The orchestrator picks the profile; the guard enforces it. Limits: output tokens per call, model calls, tool calls, cost estimate, timeout, identical tool calls (loop), files written, Ableton writes, and a warn threshold. Global: session and daily budget, max concurrent requests. Budget reservations must be atomic once requests run in parallel.

## Capabilities

Each entry: `id`, OSC address or LOM path, `status`, `evidence` (required when `tested`), `notes`. Only `tested` entries may be wrapped as Claude tools.

## Tool inputs (`list_tracks`, `import_sample`)

D-002: every model-callable tool has an input schema in `contracts/`. Phase 04b has three tools: `generate_kick` (`kick-params.schema.json`), `list_tracks` (`tool-list-tracks.schema.json`) and `import_sample` (`tool-import-sample.schema.json`). These files are the input contract only; the results the tools return are defined in the wiring issue.

**Strict subset.** Both tool schemas use only keywords that are in the documented strict tool-schema subset *and* in the bundled CLI's strict-compatibility set (`docs/research/2026-10-28_tool-schema-generation.md`, Q1): `type` (one name), `description`, `title`, `properties`, `required`, `additionalProperties: false` on every object, `items`, `enum`, `const`, `anyOf`. `$schema` and `$id` appear only at the root; the tool builder drops them. Every field has a `description` (the model reads it), with no change history in it. `tests/test_contracts.py` checks this with a hand-written checker that is shown to fail on 24 constructed violations (17 in a field, 7 at the root) and on `kick-params.schema.json`. Optional fields: 0 + 1, so with the 16 of `generate_kick` 0.2 the strict limit of 24 holds.

Consequence: no `minimum`, `minLength` or `pattern`. `track_index: -1` and `sample_id: ""` are schema-valid. The handler rejects them (local validation, D-002), and that would happen anyway, because the valid range of a track index depends on the open set. Whole-number floats (`2.0`) pass as integers under 2020-12; the handler converts them to `int`.

### `list_tracks`

No arguments (`properties: {}`, `additionalProperties: false`). Read only, approval `routine`. Reads `song.track_names.get` (`tested`), `track.has_audio_input.get` and `song.num_scenes.get`. The two last are not registry entries of their own yet (#142).

### `import_sample`

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `sample_id` | string | yes | An id that `generate_kick` returned for a kick **in this session**. Opaque; not a file name or a path. |
| `track_index` | integer | yes | 0-based index of an **existing audio track**, as `list_tracks` returned it. |
| `slot_index` | integer | no | 0-based clip slot (scene). Absent → the first empty slot of that track. |

**Decision (#81): the model never names a file.** `import_sample` takes a `sample_id`, never a path. The orchestrator keeps a session table `sample_id → absolute WAV path`. It fills that table only from what its own `generate_kick` handler wrote with `library.place_kick` into the project's kick folder. The project folder comes from the session configuration (set by the user, checked like `kick_to_live.project_problem`), never from a tool argument. Right before the import, the handler checks the resolved path again with `bridge.clip_import.validate_wav_path(path, library_root=library.library_folder(project))`.

So a file outside the library cannot be imported through the model, even when it is a valid WAV. A kick from an earlier session cannot be imported either. That limit is deliberate, until a library-listing tool hands out ids for existing entries (a later contract change).

Rejected alternatives:
- **A path argument plus the `library_root` check.** The check is right, but the model would still choose a file system string, and every handler would have to repeat the check.
- **A file name inside the kick folder.** The strict subset has no `pattern`, so the schema cannot restrict it. It also invites the model to guess names.
- **Render and place inside `import_sample` (kick-params as input).** That mixes a routine file write with a confirm-level Live write in one call. The user picks one of several rendered kicks after listening, and that kick is the one to import, not a new render.

**What the handler checks before anything is sent** (all refusals leave Live unchanged; these semantics are part of this contract):
1. `sample_id` is in the session table, and its file still passes `validate_wav_path` inside the library folder.
2. `track_index` names an existing track that is an audio track (`track.has_audio_input.get`).
3. `slot_index`, when given, satisfies 0 ≤ `slot_index` < number of scenes, and that slot is empty. When it is absent, the first empty slot is used; if there is none, the call is refused. An occupied slot is never overwritten.
4. Approval level `confirm`. The plan shows the track name and slot as read from Live, and `ClipImporter.run` compares the state again (`expected_before`).

**Not in v1:** a new audio track as the target. `song.create_audio_track` is `supported`, not `tested` (D-004). It becomes an additive contract change once its undo run passes. Undo is not part of this tool either.

**Capabilities used:** `clip_slot.create_audio_clip` (`tested`), `song.track_names.get` (`tested`), and four reads that still borrow the `create_audio_clip` gate: `track.has_audio_input.get`, `clip_slot.has_clip.get`, `clip.file_path.get`, `song.num_scenes.get`. They need their own registry entries (#142) before either tool is wired.

**Preconditions for wiring `import_sample`** (from the PR #122 round-2 review, recorded on #81):
- #83 V10 has been run.
- The request deadline is checked again after the user confirms.
