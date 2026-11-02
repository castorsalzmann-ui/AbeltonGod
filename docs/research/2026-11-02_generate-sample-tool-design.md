# Design: one generate tool for all sample categories (G7 proposal)

- **Date:** 2026-11-02. Docs only, no code. Receiving issue: #23 (`Refs #23`).
- **Question:** the strict tool-schema budget (24 optional parameters, see `2026-10-28_tool-schema-generation.md` Q4) blocks one tool per category (`generate_clap`, `generate_hat`, later snare, bass) with all contract fields. What should the generate tool look like?
- **Read:** `src/orchestrator/kick_tools.py`, `plan_tools.py`, `contracts/*`, hat contract on `origin/phase-06/249-hat-contract` (PR #256, unmerged), keyword parser on `origin/phase-05/233-keyword-parser` (PR #248, **open, not merged**), `2026-11-02_kick-keyword-vocabulary.md`, `config/guard-policy.json`.
- Lines marked **[unverified]** rest on docs or reading only, nothing was run against the API.

## 1. Measured facts (counted with `contract_input_schema` and a JSON count, 2026-11-02)

| Schema | Properties | Required | Optional |
| --- | --- | --- | --- |
| `kick-params` (what `generate_kick` is wired to today, `TOOL_CONTRACTS`) | 18 | 2 | **16** |
| `tool-generate-kick` (strict variant, on main; the target named in `kick_tools.py`) | 25 | 2 | **23** |
| `clap-params` v0.1 | 23 | 2 | **21** |
| `hat-params` v0.1 (PR #256 branch) | 28 | 2 | **26** |
| `tool-import-sample` | 3 | 2 | 1 |
| `tool-list-tracks` | 0 | 0 | 0 |
| `plan_arrangement` (`plan_tools.tool_input_schema`) | by design | all | 0 |

- Strict limit **[unverified, WebFetch summary only]**: 24 optional parameters across all strict schemas of a request, 20 strict tools. Strict kick (23) + `import_sample` (1) = **24 of 24**, which is why `plan_arrangement` has no optional parameter.
- **A single hat tool (26) or clap tool (21) with all fields does not fit next to the kick tool.** Even `generate_clap` alone (21) would not fit with strict kick (23).
- **Caveat that matters for the decision:** the Python Agent SDK `@tool` cannot set `strict` (research note Q4, SDK 0.2.172). Today the budget is therefore a rule we keep for a possible API-key route, not a limit we hit on the subscription route. **[unverified for newer SDKs]** The SDK instead validates every call with `jsonschema` against the full schema, so per-field ranges ARE enforced there. Also not measured: how many tool-schema tokens 4+ full-field tools cost per request (the 16-field kick schema is long because of its descriptions).
- Field types: of the three generate contracts only `model` (hat, enum string) and `preset` are strings; `sample_rate`, `bit_depth`, `polarity` are small integer enums; everything else is a number. So a `{key, value:number}` list covers almost all fields.
- Presets: kick 6 (`src/audio_engine/presets/*.json`), clap 4 (`presets/clap/`). Hat: not counted.
- Guard today: profile `kick_generation` has `max_files_written 12`; `generate_kick` is `Approval.ROUTINE` and sets `max_files_written = 2 * max_variants`. `sample_id` prefix is `kick-` and `KickSession` is kick-specific (`place_kick`; `library.place_sample` exists for other categories).

## 2. Options

**A. One tool per category, curated subset + preset + seed.** `generate_clap(preset, seed, variants, + ~6 fields)`.
- Pro: simplest for Claude, categories cannot be confused, per-tool description stays short.
- Con: every curated subset is a new design decision per category and hides fields (a "curated" kick is the existing 23-field tool, so kick would shrink or stay special). Optional count grows by about 8 per category: kick 23 + clap 8 + hat 8 = 39 > 24 under strict. Needs one tool, one session table and one approval entry per category.

**B. One `generate_sample(category, preset, prompt, seed, variants, adjust)`.**
- `category` enum; `preset` string (checked locally against the category's preset list); `prompt` string (kick: keyword parser, `parse_prompt`, PR #248; other categories: must be empty until they get a parser); `adjust` = array of `{key, value}` validated locally against the category's contract (range, integer-ness, unknown key = error listing all problems, never clamped); `seed`, `variants` required.
- **All of these required (empty string / empty array allowed), 0 optional parameters**, the same trick as `plan_arrangement`. Budget stays 1 (`import_sample`) whatever categories are added.
- Pro: adding a category = register contract + presets + engine entry, no new tool and no schema-budget change. Every contract field stays reachable through `adjust`. Ranges stay enforced locally (D-002), which strict could not do anyway.
- Con: Claude loses per-field descriptions in the schema (the model sees `key` as free text). Mitigation: the tool description lists the keys per category with range and default, generated from the contracts (token cost **[unverified]**), and unknown/out-of-range keys return a repair message. Generic `key` strings are a new failure mode that CI cannot judge without a real model run.

**C. Two steps: `list_presets(category)` then `generate_sample(category, preset, adjust, seed)`.**
- Pro: Claude chooses from real preset names instead of guessing; descriptions can be returned on demand (fewer tokens in the fixed schema).
- Con: an extra tool call per request (the profile has `max_tool_calls 15`, `max_model_calls 8`, so two steps cost budget and time on every request), and the first call often could be skipped if the system prompt lists preset names (it can: 6 + 4 names are short). So C collapses into B plus a prompt line. Keep `list_presets` as a later, optional read-only tool.

## 3. Approval via the guard

- Generating files = `routine` (CLAUDE.md approval levels, unchanged for all categories); `import_sample` stays `confirm` (one Live write). `generate_sample` is a new tool, so it passes `Toolbox.run` like the others: guard first, schema check, approval, then the handler; `tests/orchestrator/test_guard_wiring.py` must list it (static bypass check).
- `max_files_written` = 2 x `variants` read before validation, as `generate_kick` does (`kick_files`). Keep the cap at 12 per request from the profile; no new profile needed **[unverified: a combined "make a kick and a clap" request writes up to 2 x 8 x 2 files and would hit 12 at the guard; that is a stop, not a success, and the message must say so]**.
- `sample_id` prefix per category (`kick-`, `clap-`, `hat-`) so the id never lies about the category; `import_sample` takes any id of the session table.

## 4. German chat and strict mode

- The system prompt already tells Claude to answer in the user's language (`loop.py`). Tool arguments stay English identifiers (`key`, preset names). Germans say "Klatsche, kurz und hell": Claude maps that to `preset: short`/`adjust` itself. **Only the kick has a deterministic German word list** (the keyword vocabulary, `dunkel`, `hell`, `kurz`, `lang`, `sauber`). For `prompt` on a kick, Claude should pass the user's words through unchanged when they are vocabulary words (the parser is the reference), otherwise use `adjust`. Whether Claude does that reliably is **[unverified]**, a real-model recording is needed.
- Strict mode (API-key route only): B has no `minimum`/`maximum`, no optional fields, `additionalProperties: false` on the root and on the `adjust` item, and `category` as enum, so it stays inside the documented strict subset **[unverified, never sent to the API]**. `key` cannot be an enum without listing all fields of all categories (about 70 values) in one schema; do not do that.
- Subscription route (SDK `@tool`): not strict. The SDK `jsonschema` check validates the structure; the per-field range check is ours.

## 5. Recommendation

**Option B**, with the system prompt listing preset names per category, and `list_presets` (C) only if a real run shows Claude guesses names. Reason: it is the only option whose strict budget does not grow with each category; clap and hat would otherwise need either a field-subset decision each (A) or an extra call each time (C).

Keep `generate_kick` unchanged for now and add `generate_sample` for `clap` first (kick migration is a later, separate step; no byte or behaviour change for kick). That keeps the one working, user-tested tool intact.

### G7: smallest first PR (orchestrator-engineer)

Adds `generate_sample` for category `clap` only (hat after PR #256 merges), `routine`, via the existing toolbox. No contract change (schema built in code like `plan_tools.tool_input_schema`; moving it to `contracts/` is proposed in the PR). No kick change.

Done when:
1. `generate_sample` is registered next to the existing tools and runs only through `Toolbox.run`; `test_guard_wiring.py` covers it and a fault-injection run (handler called around the guard) turns it red.
2. Schema has 0 optional parameters, root and `adjust` items `additionalProperties: false`, no `minimum`/`maximum`; a test counts optional parameters of all registered tools and fails above 24.
3. `adjust` is validated against `clap-params` locally: unknown key, out-of-range value, wrong integer-ness, duplicate key and a non-empty `prompt` for clap each give an error listing all problems; seeded random property test over the full contract range (valid values accepted, `x1.02` beyond max rejected).
4. Valid call writes WAV + sidecar (category `clap`, sidecar 0.2) through `library.place_sample`, returns `sample_id` `clap-N`, files <= `2 x variants`, `max_files_written` honoured; `import_sample` with that id passes its existing checks (CI uses the fake bridge only, not an Ableton test).
5. Deterministic: same call twice = same SHA-256 of the WAV.
6. Fake-model test: German user message -> recorded tool call -> result; no live API call in CI.
7. Gate green (`ruff check . && pytest`), PR states what ran in CI and that no real Claude call was made.

## 6. User test recipe (user's PC, after G7 is merged; result goes to the issue)

1. Start the chat as usual with a project folder.
2. Type: `Mach mir eine kurze, helle Klatsche.` Expect one tool call `generate_sample`, category `clap`, a `clap-` id, two files in the project folder (WAV + sidecar), no Live change.
3. Type: `Mach sie 15 Prozent kuerzer und gib mir drei Varianten.` Expect an `adjust` with a valid key and three files x 2; or a clear repair message if Claude picked a bad key.
4. Type: `Importiere die zweite auf Spur 3.` Expect the usual confirm question before the Live write.
5. Type: `Mach den Hall auf 5000` (out of range). Expect a refusal listing the allowed range, not a clamped file.
6. Report: the tool-call arguments Claude sent (chat log), how often it needed a repair round, and whether the clap sounds as asked (your ear, not ours).

## 7. Open points

- Does Claude pick valid `adjust` keys from the description alone? Only a real run tells (unverified).
- Hat `model` is a string enum; `value:number` cannot carry it. Options: a fixed preset per model, or `value` as `anyOf [number, string]` (strict `anyOf` limits unverified).
- Parser for clap/hat prompts (a vocabulary note per category, analogous to the kick one) is separate work.
- Whether to merge kick into `generate_sample` later depends on the real-run result and the parser merge (PR #248).
