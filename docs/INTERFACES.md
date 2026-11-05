# Interfaces

Machine-readable contracts live in `contracts/`. This file explains them. Changing a contract needs its own PR with the `contract-change` label.

| Contract | Producer → Consumer | Status |
| --- | --- | --- |
| `contracts/kick-params.schema.json` | Orchestrator / CLI → audio engine | v0.3 (#104, follow-ups #131); the engine renders 0.2 and 0.3 (PR #130) |
| `contracts/tool-generate-kick.schema.json` | Orchestrator (tool definition) → Claude | strict-subset variant of kick-params 0.3 for the `generate_kick` tool, for when it is sent strict (#131; the choice is #148's, see "Strict tool variant"); the engine still validates against `kick-params.schema.json` |
| `contracts/sample-metadata.schema.json` | Audio engine → library, orchestrator | v0.2 (#229): kick keeps 0.1; categories `kick`, `clap`, `hat` (#249), `snare` (#272), `rim` (#296), `bass` (#320); non-pitched features; engine identity per category. v0.1 kick sidecars stay valid |
| `contracts/clap-params.schema.json` | Orchestrator / CLI → audio engine | v0.2 (#280): v0.1 plus optional extreme-sound fields behind `schema_version` `0.2`; v0.1 documents stay valid; ranges are measured and may be adjusted by the engine PR |
| `contracts/hat-params.schema.json` | Orchestrator / CLI → audio engine | v0.1 proposal (#249); no engine yet; ranges are proposals the engine PR measures and may adjust |
| `contracts/snare-params.schema.json` | Orchestrator / CLI → audio engine | v0.1 proposal (#272); no engine yet; ranges are placeholders the engine PR measures and may adjust |
| `contracts/laser-params.schema.json` | Blaster GUI / CLI / orchestrator → audio engine | v0.1 proposal (#416, D-030); stereo category; `sample-metadata` gets category `laser` |
| `contracts/rim-params.schema.json` | Orchestrator / CLI → audio engine | v0.1 proposal (#296); no engine yet; ranges are hypotheses from one weak source plus placeholders the engine PR measures and may adjust |
| `contracts/bass-params.schema.json` | Orchestrator / CLI → audio engine | v0.1 proposal (#320); no engine yet; ranges are placeholders (one tutorial is the only source) the engine PR measures and may adjust |
| `contracts/capabilities.json` (+ `capabilities.schema.json`) | Bridge → orchestrator | v1 — statuses updated in Phase 02 (#42: entry `track.mute.get` added, no format change) and Phase 03 (#50: `clip_slot.create_audio_clip` → `tested`, no format change; #143: `song.create_audio_track` → `tested`, own `tested` entries `track.has_audio_input.get`, `clip_slot.has_clip.get`, `clip.file_path.get`, `song.num_scenes.get` (no borrowed gate any more), no format change; one undo may revert track + clip together; #140: 12 Arrangement-check entries added as `unknown`, no format change) |
| `contracts/guard-policy.schema.json` → `config/guard-policy.json` | User config → resource guard | v1 — default values are untuned starting points |
| `contracts/tool-list-tracks.schema.json`, `contracts/tool-import-sample.schema.json` | Claude (tool arguments) → orchestrator | v1 (#81) — input schemas only; not wired yet |
| `contracts/arrangement-plan.schema.json` | Planner window ↔ plan generator → Live builder | v0.1 (#146, D-024) — format only; no editor, generator or Live writes yet; not a Claude tool input |

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
- Error texts of the −60 dB rule (the contract quotes the engine; a test pins both): no fit under (6a) → `amp_decay_ms: neither 2000.0 nor 20.0 ms decays 60 dB within length_beats at this bpm (…), so the bisection of rule (6a) finds no amp_decay_ms. …`; an explicit value that does not fit → `amp_decay_ms <v> does not decay 60 dB within …; the rule (6a) derives <d> for these values …`, or `amp_decay_ms <v>: ` + the (6a) text when (6a) rejects. These texts reach Claude through `generate_kick`, so they carry no issue numbers (#164; a test scans the engine's strings).

**Strict tool variant** (`contracts/tool-generate-kick.schema.json`, #131). `kick-params.schema.json` is not inside the strict tool-schema subset (`docs/research/2026-10-28_tool-schema-generation.md` Q1: no `minimum`/`maximum`/`maxLength`/`default`, no `if`/`then`, `dependent*`, `not`, `unevaluatedProperties`). The tool file is the same parameter space in that subset:

- Fields: every field of `properties` plus the seven v0.3 fields, flat in one `properties`, same names, same `required` (`schema_version`, `seed`), `additionalProperties: false`. 25 fields, **23 optional** (the same count PR #144 budgets for `generate_kick`: 23 + 0 + 1 = 24 of 24).
- Structure from the contract: `type` kept; `enum` kept with `type` added (`integer` for `sample_rate`, `bit_depth`, `polarity`); `schema_version` becomes `{"type": "string", "const": "0.3"}`, because without `if`/`then` the "v0.3 fields only with 0.3" gate cannot be expressed, and a 0.3 request without v0.3 fields gives the same samples as at 0.2 (its sidecar carries 0.3 and the v0.3 defaults).
- Dropped and moved into the field `description` as text: ranges (`Range lo ... hi`), defaults (`Default d` / `No default`), `preset` at most 64 characters, the exclusions `tail_note`/`pitch_end_hz` and `length_beats`/`length_ms`, and `length_beats` requires `bpm`. Descriptions are model-facing (no issue numbers, at most 600 characters).
- So the tool schema is **looser** than the contract: out-of-range values, the two exclusions, `length_beats` without `bpm` and a longer preset name pass it. The engine (`resolve_kick_params`, D-002) rejects them with its full error list; the handler must call it and never treat "valid against the tool schema" as valid. The other direction holds: every valid 0.3 request is valid against the tool schema (seeded test).
- Root `$schema`, `$id`, `title` are metadata; the tool builder drops them (same wiring precondition as the #81 tool schemas).
- `tests/test_contracts_generate_kick.py` regenerates the structure from `kick-params.schema.json` and compares, and parses every range, default and maximum length out of the descriptions and compares them for equality, so a contract change that is not carried over turns red. Strict subset, root metadata, model-facing text and the optional count are checked by the strict checker in `tests/test_contracts.py` (`STRICT_TOOLS`).
- **Which file the wiring sends is #148's choice** (trade-off, research note Q2/Q4 and Implications). On the Agent SDK route (D-014) `strict` cannot be set, so this file brings no grammar guarantee there. Built from `kick-params.schema.json` instead (minus `$id`/`$schema`, with a model-facing root description), the SDK's `jsonschema` pre-check enforces every range, exclusion and dependency before the handler runs, and the model sees the ranges as keywords; that is the research note's recommendation for that route. This file is the one to send if `generate_kick` is ever sent strict (Messages API route), and it keeps the 24-field budget. Either way `resolve_kick_params` stays the authority (D-002). Engine-only rule on both routes: `pitch_end_hz` (or the `tail_note` frequency) must not exceed `pitch_start_hz`; it is contract-valid and tool-valid, the engine rejects it.
- **Root `description` vs. `$comment` (#169).** The root `description` of `kick-params.schema.json` is the text the model reads when the tool is built from this file; it is guidance only (<= 300 characters, pinned by a test). Version history, the resolved-form rule and the length snap/recovery text live in the root `$comment`, which the tool builder drops (`DROPPED_ROOT_KEYS`). Contract tests quote those rules from `$comment`.

## Sample metadata

Every generated WAV gets a sidecar `<name>.json` with the parameters, seed, engine version, measured features (peak, length, fundamental, decay) and creation time. The engine must be able to re-render the exact WAV from its sidecar.

Engine version (#35): `ENGINE_VERSION` is bumped on every change that alters rendered bytes, and golden SHA-256s in `tests/audio_engine/test_engine_version.py` catch a byte change without a bump. So a sidecar can only be reproduced by the engine version that wrote it: `rerender_from_sidecar` raises `audio_engine.io.EngineVersionMismatch` (a `ValueError`) when the sidecar's engine name or version differs. `allow_engine_mismatch=True` renders its parameters with the current engine anyway; the result is a new render, not a reproduction.

Sidecar read checks (#85): reading a sidecar for rendering also refuses non-finite numbers, a `file` that differs from the WAV name next to it (compared case-sensitively, also on Windows), a `created_at` that is not a subset of RFC 3339 (only upper-case `T`/`Z`, no leap second 23:59:60, no year 0000, although RFC 3339 allows them), and a `sha256` that does not match the WAV. `sha256` is compared only when the WAV exists as a file: with no WAV (missing, a directory named `.wav`, a dangling symlink) the check is skipped, because rendering does not use `sha256` and there is nothing to compare.

**Categories and engine identity (#229, D-025).** `schema_version` `0.1` is the kick-only form written so far and stays valid; `0.2` is required for `category: clap` and refused for kick (kick keeps writing 0.1). The engine never rewrites old sidecars. Engines are versioned **per category**: kick keeps `engine.name` `abeltongod-audio-engine` and `ENGINE_VERSION` (unchanged, no kick byte changes); clap uses `engine.name` `abeltongod-audio-engine-clap` with its own version constant, and a later hat engine will do the same with its own name. `rerender_from_sidecar` compares only the pair of the sidecar's own category, so a byte change in clap code never makes a kick sidecar refuse to re-render. D-013 (bump on every byte change, golden hashes) applies inside each category. The schema pins the kick engine *name* (`abeltongod-audio-engine`; a kick sidecar with another engine name is refused, #262), the clap engine *name* and `parameters` shape (`schema_version` `0.1`, `seed` required); the version value is not pinned. `parameters` holds the category's params object (kick-params or clap-params).

Features for non-pitched samples (v0.2, all optional, number or null): `spectral_centroid_hz`, `hf_share_8k` (energy share above 8 kHz, 0..1), `t60_ms`, `rise_time_ms`. `fundamental_hz` stays optional and is left out or null for a clap. How the engine measures them is decided with the analysis code, not in this contract, with one exception (#313, description only): `t60_ms` is read on the signal after a 30 Hz high-pass, so a sub-audio DC remainder cannot hold the envelope above the -60 dB line. Sidecars written earlier keep their old value until re-rendered.

## Clap parameters

`clap-params.schema.json` v0.1 is a proposal: seeded noise, band-passed, `bursts` (1..6) short exponential bursts `burst_spacing_ms` apart, a longer tail, high-passed. Fields shared with kick-params keep name and meaning (`seed`, `variants`, `bpm`, `sample_rate`, `bit_depth`, `length_ms`, `drive`, `polarity`, `offset_ms`, `peak_ceiling_dbfs`, `preset`); decay fields mean time to -60 dB like the kick's `amp_decay_ms`. Out-of-range values are rejected, never clamped. Ranges come from the Bandit Wheel transfer note (section 4.1) widened to leave room for different characters; the audio-engineer measures them and may adjust them in the engine PR (then a contract change). Snare and rim are not in v0.1 (a later `voice` field or their own contract). The longest burst onset (5 x 30 ms) is below the minimum `length_ms` of 200, so there is no cross-field rule. No tool schema (`generate_clap`) exists; the 24/24 strict budget question belongs to that later issue.

**clap-params v0.2 (#280, additive).** `schema_version` accepts `0.1` and `0.2`. The new optional fields are allowed only with `0.2` (a `0.1` document that carries one is rejected, the way kick-params 0.3 gates its fields); they sit in an `allOf` branch for `0.2` and the root uses `unevaluatedProperties: false` (root `properties` stay the v0.1 set, so tool builders and a `0.1` resolved form do not change). Fields, off value in brackets: `fold` 0..1 (0), `crush` 0..1 (0), `rate_div` integer 1..16 (1), `ring_hz` 20..3000 with `ring_mix` 0..1 (0), `comb_hz` 100..4000 with `comb_fb` 0..0.95 (0), `gate_ms` 0 or 5..500 (0), `tail_reverse` boolean (false). The resolved form of a `0.2` document fills the off values (`ring_hz` 440 and `comb_hz` 800 are inactive while their mix/feedback is 0); a stage at its off value is skipped, so a `0.2` document with everything off renders the bytes of its `0.1` twin. Signal order: noise, band-pass, envelope, [crush, rate_div, ring, comb], `hp_hz` high-pass, room, fold, `drive`, [gate_ms, tail_reverse], fade-out, mean removal, ceiling. Out-of-range values are rejected, never clamped. `fold` is a sine fold only; `crush` has no dither; a second noise layer stays the mix-two-renders convention (no field); `bursts` and `burst_spacing_ms` keep their v0.1 ranges; stereo is out of scope. `t60_ms` is relative to the peak and not a target for extreme presets. A sample-metadata clap sidecar may embed `parameters.schema_version` `0.1` or `0.2`. The engine renders the new stages in the second part of #280; until then it must not be fed `0.2` documents with a field on.

## Hat parameters

`hat-params.schema.json` v0.1 (#249) is a proposal for one mono closed or open hi-hat. `model` is `metal_bank` (six band-limited squares at 205.3, 304.4, 369.6, 522.7, 540, 800 Hz times `pitch_scale`, all odd harmonics below sr/2, start phases 0, mixed with seeded noise) or `noise` (noise only). Shaker, ride and stereo are not in v0.1; they are added later by a contract-change that adds `model` values. Closed versus open is only `decay_ms` (10..900, time to -60 dB, exponential). Fixed by the contract text (details in the schema `$comment`):

- `metal` is the share of **passband power after the high-pass chain**: bank and noise are filtered, RMS-normalised, then mixed as sqrt(metal) bank + sqrt(1-metal) noise. If the engine render shows a correlation with the pure bank below 0.5 at `metal` 0.6, the pre-filter reading is documented instead (contract-change).
- Cross-field rule `lp_hz` > 1.2 x `hp_hz`: JSON Schema cannot express it; the engine rejects violations with an error text, never clamps. Defaults and all five target-note styles satisfy it.
- `t60_ms` in the sidecar is the first crossing of -60 dB and agrees with `decay_ms` within 10 % (for `body_mix` 0). `choke_ms` 0 = off, else 5..900: cut with a 5 ms fade, the prefix before the fade is unchanged. The body path is high-passed too (no unfiltered low path).
- `body_mix` (wording clarified in #293, no value change): at `body_mix` > 0 the filtered mix is split by frequency at 1.5 x `hp_hz` (capped at 0.45 x sample rate). The part below keeps the slow envelope (`decay_ms`); the part above gets (1 - `body_mix`) x slow + `body_mix` x fast, fast = `decay_hi_ratio` x `decay_ms`. It is not a level share of an oscillator group. Limit found on the engine (hypothesis H10 of the targets note, rejected): early/late brightness reaches only 1.10-1.16 at `body_mix` 0.4 and `decay_hi_ratio` 0.5, because the body model is high-passed.
- `bp_mix`: output = signal + `bp_mix` x band-pass(signal) with 0 dB peak gain at `bp_hz`, applied after the high-pass, peaking and low-pass stages and before the RMS normalisation.
- `seed` seeds only the noise: at `metal` 1 (model `metal_bank`) it has no effect on the samples; at model `noise` it always has.
- Sidecars: category `hat`, `schema_version` `0.2`, `engine.name` `abeltongod-audio-engine-hat` with its own version (D-025), `parameters.schema_version` `0.1`, same non-pitched features as clap.

All ranges are proposals (design note section 4, targets note section 2); `attack_ms` is narrowed to 0.1..5 because the shaker is out, `body_mix` defaults to 0 (single envelope). The audio-engineer measures them and may adjust them in the engine PR. No tool schema (`generate_hat`, H7) exists.

## Snare parameters

`snare-params.schema.json` v0.1 (#272) is a proposal for one mono snare: a sine body of two partials (lower `body_hz`, upper `body_hz` x `mode_ratio`, both with the same exponential pitch drop `pitch_drop` over `pitch_drop_ms`, so the ratio is `mode_ratio` at every instant) plus shaped noise (wide band and a narrow high-passed band with a faster decay). Lead decisions on the research note's open points: `snappy` is not a field (keyword weight only); rim shot is a separate future `rim-params`, not a `model`; `gate_ms`, `body_shape` (sine only) and a note-name resolver for `body_hz` are not in v0.1. Fixed by the contract text (details in the schema `$comment`):

- `body_level` is the share of **passband power after the noise filters** (body and noise RMS-normalised, mixed as sqrt(body_level) body + sqrt(1-body_level) noise), the same reading as hat `metal`. The body has no randomness; the seed changes only the noise (two sub-streams), so `body_level` 1 is seed-independent.
- `body_decay_ms` and `noise_decay_ms` are the time to -60 dB after the attack; the upper partial decays in `body_decay_ms` x `body2_decay_ratio`.
- Cross-field rule `noise_lp_hz` > 1.2 x `noise_hp_hz`: JSON Schema cannot express it; the engine rejects violations with an error text, never clamps. An omitted partner never breaks it (defaults 1800 / 9000).
- Out-of-range values are rejected, never clamped. All defaults are placeholders until measured and listened to.
- Sidecars: category `snare`, `schema_version` `0.2`, `engine.name` `abeltongod-audio-engine-snare` with its own version (D-025), `parameters.schema_version` `0.1`.

No tool schema (`generate_snare`) exists.

## Rim parameters

`rim-params.schema.json` v0.1 (#296) is a proposal for one mono rim shot: two damped sine partials (`f1_hz`, `f1_hz` x `f2_ratio`, relative amplitude `level2`, own decays `decay1_ms` / `decay2_ms` as time to -60 dB), a high-pass `hp_hz` and an optional noise click (`click_level`, `click_ms`). Separate `rim-params`, not a snare `model` (lead decision on #272). The research note's few sourced numbers are weak (one hobby page); every range and default is a placeholder. Decisions taken in this draft, open for the lead: a single partial is `level2` 0 (no "off" value in `f2_ratio`); `f3_ratio`, pitch `bend`, `tone_peak_*` and a `clave` model are not in v0.1; category `rim` (not `perc`). Fixed by the contract text (details in the schema `$comment`):

- Cross-field rule `hp_hz` < 0.8 x `f1_hz`: JSON Schema cannot express it; the engine rejects violations with an error text, never clamps. The default `hp_hz` (200) satisfies it for every `f1_hz` in range.
- Partials start with phase 0; the seed changes only the click, so `click_level` 0 is seed-independent. The highest partial (3500 x 5.0 Hz) is below 0.45 x `sample_rate`.
- Out-of-range values are rejected, never clamped.
- Sidecars: category `rim`, `schema_version` `0.2`, `engine.name` `abeltongod-audio-engine-rim` with its own version (D-025), `parameters.schema_version` `0.1`.

No tool schema (`generate_rim`) exists.

## Bass parameters

`bass-params.schema.json` v0.1 (#320) is a proposal for one mono, pitched, gated bass note: `note` (MIDI 24 .. 55) + `cents`, three phase-0 sine-series oscillators (`saw_level`, `square_level`, `sine_level`) and `sub_octave_level`, high-pass `hp_hz`, 2nd-order low-pass with a closing cutoff envelope (`lp_hz` = sustained cutoff, `lp_q`, `lp_env_amount` in octaves, `lp_env_decay_ms`), linear `amp_attack_ms`, `gate_ms`, linear `release_ms`, `drive`. File length is `gate_ms` + `release_ms`; there is no length field. Only one tutorial sources any number (high-pass about 65 Hz, low-pass about 350 Hz, G2 = 98 Hz); every range and default is a placeholder the engine PR measures and may adjust. Decisions taken in this draft, open for the lead (details in the PR body): default note 43 (sourced) not 31; `hp_hz` default 20 so the default satisfies the cross-field rule for every note; `detune_cents` and `model` left out of v0.1; `lp_hz` is the sustained cutoff; `fundamental_hz` is the note, not the sub octave; `seed` kept but inert for the core voice; no new sidecar features. Fixed by the contract text (details in the schema `$comment`):

- Cross-field rules, engine-checked with an error text, never clamped: `hp_hz` < 0.8 x note frequency; `lp_hz` >= 1.2 x `hp_hz`; `lp_hz` x 2^`lp_env_amount` < 0.45 x `sample_rate`; at least one oscillator level above 0.
- Measurement method per field is written into the contract: pitch from the stationary window (40 % to 80 % of the gate) by two independent methods, `fundamental_hz` null if that window holds fewer than 2 periods; envelope readings on peak envelopes (the release: the last sample with |x| >= 0.01 of the stationary peak lies at most one period before 0.99 x `release_ms`, no upper bound claimed, only read where `release_ms` is at least 4 periods; a period-long RMS never reaches -40 dB before the linear ramp ends with the file, #375). `rise_time_ms` / `t60_ms` and the kick `tail_window` are not used for bass (they mis-measure gated low notes).
- Sidecars: category `bass`, `schema_version` `0.2`, `engine.name` `abeltongod-audio-engine-bass` with its own version (D-025), `parameters.schema_version` `0.1`.

No tool schema (`generate_bass`) exists.

## Laser parameters

`laser-params.schema.json` v0.1 (#416, D-030) describes one sci-fi laser shot (RX ear candy). It is the first **stereo** category: the engine API `render_laser(params: dict, seed: int) -> np.ndarray` returns float64 of shape `(n, 2)` (left, right; identical channels at `stereo_width` 0), peak-normalised for the quantised file, and the WAV is 2-channel PCM. `sample-metadata.schema.json` gets the category `laser` (sidecar `schema_version` `0.2`, `engine.name` `abeltongod-audio-engine-laser` with its own version, `parameters.schema_version` `0.1`); its features are the existing non-pitched ones measured on the mid signal, `peak_dbfs` is the joint peak of both channels.

- Six selectable families ("dimensions") in one shared parameter space: `pew`, `plasma`, `ion`, `rift`, `subboom`, `glitch` (what each does: schema `$comment` point 1). A family changes the oscillator and its modulation, never the set of fields.
- Fields: `pitch_start_hz` / `pitch_end_hz` / `sweep_ms` / `sweep_curve`, `length_ms` (100 .. 3000), `attack_ms`, `decay_ms` (time to -60 dB), `fm_amount` / `fm_ratio`, `ring_amount` / `ring_hz`, `noise_level` / `noise_hz`, `crackle`, `glitch_steps`, `echo_mix` / `echo_ms` / `echo_feedback`, `stereo_width`, `variation`, plus the shared `seed`, `variants`, `bpm`, `sample_rate`, `bit_depth`, `drive`, `polarity`, `offset_ms`, `peak_ceiling_dbfs`, `preset`.
- No cross-field rule; out-of-range values are rejected, never clamped. Fields marked "no effect at 0" are documented in their descriptions. With `noise_level`, `crackle` and `variation` all 0 the output is seed-independent.
- All ranges and defaults are proposals for a wide space, not measured; no claim about how a family sounds.

No tool schema (`generate_laser`) exists.

## Guard policy

One profile per request type (`kick_generation`, `mentor_answer`, …). The orchestrator picks the profile; the guard enforces it. Limits: output tokens per call, model calls, tool calls, cost estimate, timeout, identical tool calls (loop), files written, Ableton writes, and a warn threshold. Global: session and daily budget, max concurrent requests. Budget reservations must be atomic once requests run in parallel.

## Capabilities

Each entry: `id`, OSC address or LOM path, `status`, `evidence` (required when `tested`), `notes`. Only `tested` entries may be wrapped as Claude tools.

## Tool inputs (`list_tracks`, `import_sample`)

D-002: every model-callable tool has an input schema in `contracts/`. Phase 04b has three tools: `generate_kick` (`tool-generate-kick.schema.json`, the strict variant of `kick-params.schema.json`, see "Kick parameters"; which of the two the wiring sends is #148's choice), `list_tracks` (`tool-list-tracks.schema.json`) and `import_sample` (`tool-import-sample.schema.json`). These files are the input contract only; the results the tools return are defined in the wiring issue.

**Strict subset.** Below the root, both tool schemas use only keywords that are in the documented strict tool-schema subset *and* in the bundled CLI's strict-compatibility set (`docs/research/2026-10-28_tool-schema-generation.md`, Q1): `type` (one name), `description`, `properties`, `required`, `additionalProperties: false` on every object, `items`, `enum`, `const`, `anyOf`. Every field has a `description` (the model reads it), with no change history in it.

The contract files also carry `$schema`, `$id` and `title` at the root. They are **not** part of that intersection: `$id` is in neither list (Q1: it alone makes the CLI fall back to non-strict), and `$schema` and `title` are only in the CLI set. So the contract file as it is is *not* strict-compatible. Only the schema the tool builder produces from it is.

**Wiring precondition:** the tool builder drops `$schema`, `$id` and `title`, and a wiring test checks that its output passes the strict checker with no root allowance (`strict_subset_problems(..., allow_root_metadata=False)`). `tests/test_contracts.py` already shows that the contract minus these three keys passes that check.

The checker is hand-written. It is shown to fail on 28 constructed violations (21 in a field, 7 at the root) and on `kick-params.schema.json`.

**Optional-parameter budget (strict limit: 24 across all strict tools of a request).** `generate_kick` has 23 optional fields: 16 in kick-params 0.2 plus the 7 v0.3 fields (in `allOf[0].then` of `kick-params.schema.json`, flat in `tool-generate-kick.schema.json`; both files count 23). With 0 here and 1 in `import_sample`, the total is 23 + 0 + 1 = **24, exactly the limit, with no headroom**. Any further optional field in one of the three tools needs a choice first: make it required, or leave an optional kick field out of the strict `generate_kick` variant. Whether `generate_kick` is sent strict at all is the wiring's choice (#148; the Python Agent SDK cannot set `strict`, research note Q4). The test counts the kick fields from the tool file and from kick-params (including the conditional branch) and pins the sum at 24.

Consequence: no `minimum`, `minLength` or `pattern`. `track_index: -1` and `sample_id: ""` are schema-valid. The handler rejects them (local validation, D-002), and that would happen anyway, because the valid range of a track index depends on the open set. Whole-number floats (`2.0`) pass as integers under 2020-12; the handler converts them to `int`.

### `list_tracks`

No arguments (`properties: {}`, `additionalProperties: false`). Read only, approval `routine`. Reads `song.track_names.get` (`tested`), `track.has_audio_input.get` (`tested`) and `song.num_scenes.get` (`tested`). The last two are registry entries of their own since #153 (closed #143). Limit from #153: `has_audio_input == false` has never been observed on the user's machine.

### `import_sample`

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `sample_id` | string | yes | An id that `generate_kick` returned for a kick **in this session**. Opaque; not a file name or a path. |
| `track_index` | integer | yes | 0-based index of an **existing audio track**, as `list_tracks` returned it. |
| `slot_index` | integer | no | 0-based clip slot (scene). Absent → the first empty slot of that track. |

**Decision (#81): the model never names a file.** `import_sample` takes a `sample_id`, never a path. The orchestrator keeps a session table `sample_id → (absolute WAV path, WAV sha256)`. It fills that table only from what its own `generate_kick` handler wrote with `library.place_kick` into the project's kick folder. The sha256 is the `sha256` field of the sidecar written with the WAV (sample-metadata).

The project folder comes from the session configuration, set by the user, never from a tool argument. It gets the same rules as `scripts/kick_to_live.py` `project_problem`: an existing absolute folder with a `.als` file in it, not `Backup`, not inside the checkout. That function lives in `scripts/` and returns German CLI text, so `src/orchestrator/` must not import it. The shared check belongs in `src/library/` as a function with a structured result, used by both the script and the orchestrator (#149; it is needed before wiring). Right before the import, the handler checks the resolved path again with `bridge.clip_import.validate_wav_path(path, library_root=library.library_folder(project))`.

So a file outside the library cannot be imported through the model, even when it is a valid WAV. A kick from an earlier session cannot be imported either. That limit is deliberate, until a library-listing tool hands out ids for existing entries (a later contract change).

Rejected alternatives:
- **A path argument plus the `library_root` check.** The check is right, but the model would still choose a file system string, and every handler would have to repeat the check.
- **A file name inside the kick folder.** The strict subset has no `pattern`, so the schema cannot restrict it. It also invites the model to guess names.
- **Render and place inside `import_sample` (kick-params as input).** That mixes a routine file write with a confirm-level Live write in one call. The user picks one of several rendered kicks after listening, and that kick is the one to import, not a new render.

**What the handler checks before anything is sent** (all refusals leave Live unchanged; these semantics are part of this contract):
1. **The id resolves to the file the user heard:**
   - `sample_id` is in the session table.
   - Its file still passes `validate_wav_path` inside the library folder.
   - Its sha256, computed right before the import, equals the hash stored at generate time. A mismatch is refused: the file was edited, replaced, or deleted and its name reused.
   - When `generate_kick` places a new kick at a path that an older id of this session points to (possible after the user deleted that file, because `place_kick` reuses free names), the older id is removed from the table, so it is refused as unknown. With the hash check this is a second, independent guard.
2. **The track is an existing audio track:**
   - `track_index` is an `int` (a whole-number float is converted first) with `0 <= track_index < len(track_names)`, written out explicitly. A negative index is refused, never used as a Python index from the end.
   - The track is an audio track (`track.has_audio_input.get`).
   - The handler never passes `track_index=None` to `ClipImporter.run`, because `None` means "create a new track".
   - It builds the bridge without `allow_untested`.
3. **The slot exists and is empty.** When given, `slot_index` satisfies `0 <= slot_index <` number of scenes, and that slot is empty. When it is absent, the first empty slot is used; if there is none, the call is refused. An occupied slot is never overwritten.
4. **Approval level `confirm`.** The plan shows the track name and slot as read from Live, and `ClipImporter.run` compares the state again (`expected_before`).

**Not in v1:** a new audio track as the target. `song.create_audio_track` is `tested` since #153, but stays out of v1 (v1 limit, #81). Adding it is a later additive contract change; new-track undo was shown in one run only (one undo reverted track and clip together). Undo is not part of this tool either.

**Capabilities used:** `clip_slot.create_audio_clip` (`tested`), `song.track_names.get` (`tested`), and four reads that are registry entries of their own with status `tested` since #153 (closed #143): `track.has_audio_input.get`, `clip_slot.has_clip.get`, `clip.file_path.get`, `song.num_scenes.get`. None of them borrows the `create_audio_clip` gate any more. Limit from #153: `has_audio_input == false` has never been observed on the user's machine.

**Preconditions for wiring:**
- From the PR #122 round-2 review, recorded on #81:
  - #83 V10 has been run.
  - The request deadline is checked again after the user confirms.
- From the PR #144 review:
  - the tool builder's output passes the strict checker with no root allowance (see "Strict subset");
  - the shared project-folder check exists in `src/library/` (#149);
  - the four reads have their own registry entries (#143) — **met** by #153: all four are `tested`.

## Arrangement plan (`arrangement-plan.schema.json`)

v0.1 (#146, D-024). One plan per track, shared by the planner window, the plan generator and the Live builder. Defaults and their sources: `docs/research/2026-10-29_arrangement-planner-sections-energy.md` (sections 3, 4, 6, 8). This is the format only: no editor, no generator and no Live writes exist yet.

**Not a Claude tool input.** Claude does not send whole plans. Chat edits ("the second drop should be harder", B7) will go through a narrow edit tool with its own strict schema (a later contract change). Reasons: the strict subset has no `minimum`, `multipleOf`, `if`/`then` or `$ref`, so a strict plan schema would lose nearly every rule below; and the strict optional-parameter budget is already 24 of 24 (see "Tool inputs"). So this schema is free to use the full 2020-12 vocabulary. It is not in `TOOL_SCHEMAS` and must not be registered as a tool.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | `"0.1"` | |
| `bpm` | number 20–999 | Live's tempo range, not a taste range. 136–146 is an editor default. |
| `time_signature` | `"4/4"` | Fixed in v0.1. 1 bar = 4 beats. |
| `phrase_bars` | `8` | The section grid (see "Grid" below). |
| `total_bars` | integer, multiple of 8, 32–1024 | Must equal the end of the last section. 32 = shortest intro + outro; 1024 is a sanity bound. |
| `sections[]` | `{type, start_bar, length_bars}` | `type` ∈ `intro, groove, break, breakdown, build, drop, outro`. `start_bar` is 1-based. Allowed lengths per type: intro / breakdown / drop / outro 16, 32, 64; groove 16, 32, 48, 64; break 8, 16; build 8, 16, 32. |
| `energy_nodes[]` | `{pos, value, drawn}` | `pos`: whole bars from the track start (0 = start of bar 1, `total_bars` = end of the last bar). `value`: 0–1. `drawn`: `true` when the user placed or moved the node. |
| `settings` | object, all 11 keys required | See "Settings". |

**One checker, no second implementation.** The rules JSON Schema cannot express live in `src/orchestrator/arrangement_plan.py` (`plan_problems`, `energy_at`, `ENTRY_MODE`, `B3_MARGIN`, `TOL`). The planner window, the plan generator and the Live builder import it; `tests/test_contracts_arrangement_plan.py` imports it too and writes no checker of its own. The positive and negative instances are data, not code: `tests/fixtures/arrangement_plan/` holds the templates `T1.json`, `T2.json`, `T3.json` and `cases.json` (a base plan, RFC 6902 `add`/`remove`/`replace` patches, and the expected rule codes; `{"$number": "nan"}` stands for a float JSON cannot hold). A reader in another language runs the same cases. Writers emit JSON integers for every integer field; JSON Schema 2020-12 also accepts a whole-number float (`8.0`), so the checker does too.

**Rules beyond the schema** (part of this contract; checked by `plan_problems`, codes in brackets):
- Sections tile the track: the first starts at bar 1, each next one at the previous `start_bar + length_bars`, the last ends at `total_bars` (`tiling`, `total_bars`). With lengths in multiples of 8, every start is at bar 8k + 1 (S1).
- The first section is `intro`, the last is `outro`, and neither appears anywhere else (`first_not_intro`, `last_not_outro`, `intro_outro_inside`; S3).
- Nodes: `pos` never decreases in array order (`node_order`). The first node is at 0 and the last at `total_bars` (`first_node_pos`, `last_node_pos`). At most two nodes share a `pos` (`three_at_pos`), and never at 0 or `total_bars` (`pair_at_edge`).
- `bpm` and every `value` are finite (`nonfinite`). JSON Schema lets NaN through `minimum`/`maximum`, so a reader must reject NaN and Infinity.
- Rules that are only editor warnings are **not** format rules: S2 (4–7 min window), S4 (build before a drop), S6 (breakdown count), T5 (step limits), soft value ranges (B6).

**Curve semantics.** Linear interpolation between consecutive nodes. A step is a **step pair**: two nodes at one `pos`. The first is the value arriving from the left, the second the value leaving to the right. Array order is binding: a sort must be stable by `pos` and must never reorder a pair. Most reorderings break no rule (a jump into a `step` section is legal either way), but they change the curve, so keeping the order is a duty of every reader and writer. A pair with equal values is allowed.

**Boundary rules** (apply only to nodes with `drawn: false`; a drawn node is never changed by settings, templates or recomputed defaults):
- Entry mode per type: `build`, `outro` = `continue`; `groove`, `break`, `breakdown`, `drop` = `step`. The intro has none (it is first).
- **B2** At the start of a `continue` section, an undrawn step pair must not jump (`b2_jump`). If either node of the pair is drawn, the jump stands.
- **B3** If the node arriving at a build's end is undrawn, its value is max(value leaving the build's start, value leaving the build's end − 0.05), within 1e-9 (`b3_build_end`). So when the user moves the drop's first node, the build end follows. **Consequence for a single end node:** without a step pair at the build's end, the arriving and the leaving node are the same node, so its value `v` must satisfy `v = max(start, v − 0.05)`, which holds only for `v = start`: an undrawn build that ends in one node is **flat**. A generator that wants a ramp writes a step pair at the end (build end | drop start), as the templates do, or marks the end node `drawn`.

**Grid (#146 Must-resolve 1).** Sections always sit on the 8-bar phrase grid (`phrase_bars`), whatever `change_grid` says. `change_grid` (a whole number of bars from 1 to 64, default 8; user decision 2026-10-30: „frei einstellbar aber default 8 takte“) only sets where elements may switch on or off inside sections (T1). Changing the setting never moves a section or a node, drawn or not: there is no re-snap. This replaces S7 of the research note ("lengths and starts snap to `change_grid`").
- **Origin (user decision 2026-11-01, „Ab Abschnittsbeginn“):** the grid counts from the start of each section. Every section start is a change point; inside a section the points are start, start + g, start + 2g, … A section of 16 bars at bar 33 with `change_grid` 12 has change points at bar 33 and bar 45, not at bar 37 or 49. The end of the track is not a change point. `change_points(plan)` in the checker module returns them (positions in whole bars, `pos`).
- **Upper bound 64:** the longest section is 64 bars; any larger value would leave only the section starts, the same as 64. So the schema refuses values above 64 instead of storing meaningless numbers. A value at least as long as a section (grid 12 in an 8-bar break) leaves only that section's start.
- **`fills = every_8` is independent of `change_grid`:** it counts 8-bar phrases of a section, and every section start is on the phrase grid.
- T2's 8-bar break and build are valid at every `change_grid`, and `plan_problems` does not read the setting (the schema checks its range). What a generator does with the setting (keeping sections and drawn nodes still for every value) is checked on generated plans: V6 of the planner note and V2 of the musical-transfer note belong to the generator issue (A6/A10), not to this format.

**Outro entry (#146 Must-resolve 2).** The outro enters with `continue` (user decision 2026-10-30: „Fließend weiter“): it starts at the previous section's end value, with no step down at its start, then decays inside the section. This drops the note's start value min(previous end, 0.55) and keeps B2. A user-drawn jump into the outro stays allowed.
- **At most one element per 8-bar boundary (user decision 2026-11-01, „Max. 1 Element pro Grenze“)** applies to the default outro, and to the default intro (note section 5.1, C7). It is a template rule, not a validity rule: a plan the user drew with more changes is still valid. `default_outro(start_value, min_length)` builds the default.
- **The default walk** (_Interpretation_, built on the thresholds of note section 5.1, which are a proposal): each 8-bar phrase holds one value; the first phrase keeps the previous end value; every later phrase takes the lower bound of the next element interval below (…0.80, 0.75, 0.70, 0.65, 0.55, 0.40, 0.30; the interval of 0.25 ends the walk at 0.25). An element is on at energy ≥ its threshold, so exactly one element goes at each boundary. Kick (always on) and bass (set by `intro_outro_bass`) are not counted. The walk replaces the first draft's evenly spaced steps (1.00 / 0.75 / 0.50 / 0.25 change 2, 4 and 2 elements).
- **The outro gets longer when needed:** the length is the smallest of 16, 32, 64 bars with one phrase per interval of the walk (and at least `min_length`). From a full drop (0.90 and above) the walk needs nine phrases; the format's longest outro has eight, so the walk stops at the interval of 0.30 and the outro ends at 0.30 instead of 0.25. Consequence for the templates: T1 outro 64 bars (192 bars in total), T2 and T3 256 bars. The note's S2 window (4 to 7 minutes) is an editor warning and does not apply to the format.
- **Soft range:** the note's soft range for the outro is 0.10–0.55. The default walk starts at the previous end value (up to 1.00) and stays above 0.55 for its first five phrases, so the editor's soft-range warning would fire on its own default. This is a decision for the planner window issue (exempt the default outro's walk from the warning, or show the warning); the format does not clamp. The last 16 bars (mix zone) stay at or below the cap 0.50.

**Third node (#146 Must-resolve 3).** A third node at a `pos` that already holds a step pair is invalid, drawn or not; the format never merges or replaces it. The planner window turns a click on a pair into an edit of the pair's arriving or leaving node (whichever side was hit) and never creates a third node.

**Settings** (`settings`, all required, so a later default change never changes a stored plan; a setting changes defaults and rule parameters only, never a section or a drawn node):

| Key | Allowed | Default | Basis of the default |
| --- | --- | --- | --- |
| `build_kick` | `filtered_in_build`, `at_drop` | `filtered_in_build` | C5 (psytrance source) |
| `intro_length` | 16, 32, 64 (bars) | 32 | C1, C3 |
| `outro_length` | 16, 32, 64 (bars) | 32 | C1, C3 |
| `intro_outro_bass` | `on`, `outside_mix_zone`, `off` | `on` | C3, C5; open user question D1 (`2026-10-29_bandit-wheel-musical-transfer.md`) |
| `breakdown_count` | 1, 2 | 1 | C5, C7; max 2 is _Interpretation_ |
| `breakdown_length` | 16, 32, 64 (bars) | 32 | _Interpretation_ inside C4/C5's range |
| `breakdown_rumble` | `off`, `on` | `off` | C5 |
| `second_drop` | `stronger`, `equal`, `ask` | `stronger` | _Interpretation_ (no source) |
| `change_grid` | integer 1–64 (bars), counted from each section's start | 8 | C2 (measured), C1; user decision 2026-10-30 |
| `pre_drop_gap` | 0, 1, 2, 4 (beats; 0 = off, 4 = 1 bar) | 4 | C5 (psytrance source) |
| `fills` | `off`, `section_change`, `every_8` | `off` | user decision 2026-10-30 („Keine“); see below |

Length settings apply when the user places a section; a template keeps its own lengths (T1 has a 16-bar breakdown with `breakdown_length` 32).

**Fills (#146 Must-resolve 4).** C8 supports only "do not repeat the same fill", not a density. So variation is a fixed rule, not a setting: consecutive fills never repeat identically. Density is the setting (`off`, `section_change`, `every_8`, from D5 of the musical-transfer note). The default is `off` (user decision 2026-10-30: „Keine“): the generator places no fills; fills come only where the user sets them. User-placed fills need an events field, which v0.1 does not have yet (see "Not in v0.1").

**Not in v0.1** (each a later additive contract change): user-placed fills; derived `events[]` (riser, impact, downlifter, fill, pre-drop gap) and per-phrase element states, both generator output; sub-bar node positions; a per-type number ("Drop 2"), which the UI derives from the order; the `build_kick` option "kick out for the last N bars" (D3 of the musical-transfer note).

**Templates.** T1 Kurz (192 bars), T2 Techno and T3 Trance (256 bars each; 160 and 224 in the note before the outro rule above) are JSON files in `tests/fixtures/arrangement_plan/` with the default nodes of the note's section 4 and the outro walk. They are valid plans.
