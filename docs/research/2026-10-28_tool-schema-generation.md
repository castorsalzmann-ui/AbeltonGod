# Research: tool-schema generation from `contracts/` for Phase 04b

- **Date:** 2026-10-28. All web sources were opened on 2026-10-28.
- **Receiving issue:** #23 (Phase 04b, scope item 1: tool definitions generated from `contracts/` schemas). The tool definitions are step 2 of D-020; they wait for the Phase 03 Live result.
- **Researched against:** `claude-agent-sdk` (Python) **0.2.172**, installed here, with bundled Claude Code CLI **2.1.308** (`claude_agent_sdk/_cli_version.py`). The newest version on PyPI today is 0.2.174 and was not checked. `anthropic` (Python client SDK) **2.3.0** wheel, read only for `transform_schema`. `jsonschema` 4.26.0, `mcp` 2.3.0. Claude API docs at platform.claude.com as of today. MCP spec revision 2025-11-25. Model: Opus 5.5 (D-014).
- **Cluster boundary (D-019):** cluster 1 covers Agent SDK runtime behaviour (`max_turns`, budget, hooks, how a stop is reported). This note covers only schemas, tool definitions and tool names.
- **Not covered:** `contracts/capabilities.json` and the bridge tools (`list_tracks`, `import_sample`). They have no input schema in `contracts/` yet (see Implications).

Paths `SDK/…` mean `site-packages/claude_agent_sdk/…` in version 0.2.172. Lines marked **Interpretation** are my reading of the sources. The sources do not say them directly.

## Summary for the implementer

- **Agent SDK route (D-014, what 04b uses):** `@tool("generate_kick", desc, schema_dict)` passes our JSON Schema dict to the CLI **unchanged** (same dict object; verified by identity and JSON equality, not by inspecting the bytes on the wire). Before the handler runs, the SDK validates the arguments with `jsonschema` against that same dict and returns any failure to Claude as a tool error. No transformation is required by anything that is documented. Two changes are recommended: drop `$id` and `$schema`, and write a tool-facing description. Whether the API accepts `$id`/`$schema` in a non-strict tool is **not documented** (see "To verify").
- **Strict mode** (`strict: true`) exists, is GA and covers Opus 5.5. The Python Agent SDK's `@tool` has **no way to set it**. It would also drop our ranges (`minimum`/`maximum` are not supported in strict schemas). So our own validation (D-002) is the only range check either way.
- **Runtime topics are not in this note.** Tool search (which decides when the model first sees our schemas), the `mcp__<server>__<tool>` names at runtime and the closed tool surface are covered by the cluster-1 note `docs/research/2026-10-28_agent-sdk-behaviour.md` (PR #79; [lead decision on the overlap](https://github.com/castorsalzmann-ui/AbeltonGod/pull/80#issuecomment-6481391661)). This note keeps only what is schema-specific.
- **Web-doc claims were checked only through WebFetch summaries.** This covers the strict guarantees, the 400 behaviour, the name regex, the 24-optional-parameter limit and the `tool_choice` 400. `curl` to platform.claude.com was blocked, and the reviewer could not re-fetch the pages. These claims stay on the "To verify" list (item 7).

## Q1 — Which JSON Schema subset do tool `input_schema`s accept? What is ignored, what is rejected?

**Answer.**
- **Non-strict tools (the default):**
  - The API reference types `input_schema` as a "JSON schema" that links to **draft 2020-12**, with `type: "object"`, optional `properties` and optional `required`. It does not say whether other keywords are allowed, ignored or rejected.
  - Official examples use `enum` and `description`. The Agent SDK guide's example uses `minimum`/`maximum` in a non-strict tool. Neither page lists `const`, `default`, `$id`, `$schema` or `additionalProperties`.
  - The MCP spec, which the Agent SDK's custom tools use, says an `inputSchema` without `$schema` defaults to 2020-12. It shows `$schema` (draft-07) and `additionalProperties: false` in valid examples.
  - **For non-strict tools, the sources state no "ignored vs. rejected" rule.**
- **Strict tools (`strict: true`) and structured outputs share one documented subset:**
  - **Supported:** all basic types, `enum` (scalars only), `const`, `anyOf`/`allOf` (limited), local `$ref`/`$defs`, `default`, `required`, `additionalProperties` (must be `false` on every object), a fixed list of string `format`s, and `minItems` 0 or 1. `description` is listed among the API-enforced constraints.
  - **Not supported:** `minimum`, `maximum`, `multipleOf`, `minLength`, `maxLength`, other array constraints, recursive schemas, and `additionalProperties` other than `false`.
  - **Behaviour:** an unsupported feature sent directly to the API returns a **400 error**.
  - `$id` and `$schema` are not mentioned at all.
- **Interpretation:** the bundled CLI 2.1.308 has its own strict-compatibility check. Its allowed-keyword set is `$schema, type, description, title, properties, required, additionalProperties, items, enum, const, anyOf`. Without `minimum`, `$id` or `default`, the CLI would fall back to non-strict with a warning. This was read from minified internal code and is not a documented interface.

**Sources.**
- [Messages API reference, `tools[].input_schema`](https://platform.claude.com/docs/en/api/messages/create) — "JSON schema" links to draft 2020-12; fields `type`, `properties`, `required`.
- [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) — examples with `enum`/`description`.
- [Structured outputs → JSON Schema limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations) — supported and unsupported lists; "Both JSON outputs and strict tool use share these limitations"; 400 on unsupported features.
- [Agent SDK custom tools](https://code.claude.com/docs/en/agent-sdk/custom-tools) — `get_precipitation_chance` example with `minimum`/`maximum`.
- [MCP spec 2025-11-25, Tools → Tool](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) — 2020-12 default, draft-07 example.
- Bundled CLI binary `SDK/_bundled/claude` — string `Ve=new Set(["$schema","type",…,"anyOf"])` next to the function that logs "has strict: true but its schema is not strict-compatible … sending non-strict".

**Confidence.** High for the strict subset (one official page, stated explicitly). Medium for non-strict: the docs are silent, so "accepted" rests on examples, not on a rule. Low for the CLI keyword set (minified internals; may change in any release).

## Q2 — Can `contracts/kick-params.schema.json` be passed as-is? If not, what is the minimal transformation?

**Answer.**
- **Agent SDK `@tool` (our route): it can be passed as-is as far as the SDK is concerned.**
  - `_build_input_schema` returns any dict that has a string `type` and a `properties` key unchanged (`SDK/__init__.py:438-444`). I checked locally that `_build_input_schema(tool) is schema` is `True` for our file.
  - The SDK then calls `jsonschema.validate(arguments, schema)` (`SDK/__init__.py:630`). Because our `$schema` names 2020-12, `jsonschema` picks `Draft202012Validator`. Checked locally: `drive: 1.02`, `seed: -1` and an unknown key are rejected; `{schema_version: "0.2", seed: 1}` passes.
  - The open point is whether the CLI or the API refuses a key such as `$id` (documentation silent, Q1). This needs one real run (see "To verify").
- **Minimal change for the non-strict route:** nothing is required by any source. Recommended, each with its reason:
  1. **Drop `$id`.** It is not documented for tools, and the model does not need it.
  2. **Drop `$schema`, or keep it.** MCP defaults to 2020-12 without it. The SDK's local `jsonschema.validate` then falls back to the latest draft its installed version supports. That is 2020-12 in `jsonschema` 4.26.0 (**interpretation** of `jsonschema` behaviour; worth one assertion in a test).
  3. **Replace the root `description`.** It reads "Draft v0.2 - finalised in Phase 01 … v0.2 (issue #7): …", which is change history, not guidance for the model. It ends up inside the schema the model reads (Q3).
  4. **Optional design choice, not required:** remove `schema_version` from the model-facing schema and have the orchestrator insert `"0.2"`. Then the model cannot get the version wrong. This is a proposal for the lead (Implications).
- **Strict route (only if the Messages API with an API key is ever used), the minimal transformation is:**

| Field(s) | Change | Why |
| --- | --- | --- |
| `seed`, `variants`, `bpm`, `length_ms`, `pitch_start_hz`, `pitch_end_hz`, `pitch_decay_ms`, `amp_attack_ms`, `amp_decay_ms`, `click_level`, `click_tone_hz`, `drive`, `tone`, `peak_ceiling_dbfs` (14 fields) | remove `minimum`/`maximum` | not supported in strict schemas → 400 |
| `preset` | remove `maxLength` | not supported → 400 |
| `schema_version` (`const` only), `sample_rate`, `bit_depth` (`enum` only) | add `"type": "string"` / `"integer"` | Strict lists `const`/`enum` as supported without saying whether `type` is required. `anthropic` 2.3.0 `transform_schema` raises `ValueError: Schema must have a 'type'…` on our file (`lib/_parse/_transform.py:155-156`; reproduced locally). |
| root `$id`, `$schema` | remove | not in the supported list; the result is not documented |
| root | keep `additionalProperties: false` | already compliant |

  - `anthropic.transform_schema` (2.3.0, `_transform.py:98-218`) removes the unsupported keywords and appends each one to the field's `description` as text, for example `{minimum: 0, maximum: 1, default: 0.2}` (`_transform.py:207-216`). After I added the three `type`s, it ran without error on our file. **Running `transform_schema` is not enough**, because it also loses or leaks things (all reproduced locally on 2026-10-28):
    - **It drops `const`.** `const` is not one of the keys it copies (`_transform.py:143-205`). `schema_version` becomes `{"type": "string", "description": "{const: 0.2}"}`, so under strict any string would be schema-valid. Add `const` back by hand: it is in the documented strict subset, or use `"enum": ["0.2"]`.
    - **It leaks the root `$schema` and `$id` URLs into the root `description`**, which the model reads: `… {$schema: https://json-schema.org/draft/2020-12/schema, $id: https://github.com/castorsalzmann-ui/AbeltonGod/contracts/kick-params.schema.json}`. Remove both keys before transforming.
    - It also moves `default` into the description text, although `default` is in the documented strict subset (interpretation: harmless, but the structured `default` is gone).
  - So the strict table above lists what the *documentation* rules out. A transformed schema still needs a hand-check, and a real compile run (To verify, item 6), before it can be trusted.

**Sources.**
- `SDK/__init__.py:436-456` (`_build_input_schema`) and `:604-641` (`create_sdk_mcp_server`, validation at `:630`). Local run on 2026-10-28 (commands in the PR body).
- `anthropic` 2.3.0 wheel, `anthropic/lib/_parse/_transform.py:98-218`.
- [Structured outputs → How SDK transformation works](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations).

**Confidence.** High for what the SDK does with the dict (source read plus a local run). Medium for "the API accepts it as-is", which is not yet observed. Medium for the strict transformation table. It follows the documented unsupported list, but that list was read only through WebFetch summaries. The table has not been sent to the API, and the only tool that automates it (`transform_schema`) drops `const` and leaks URLs.

## Q3 — Does the model see `default` / `description`, and do they influence argument choice?

**Answer.**
- **Documented: the model sees the schema.**
  - With `tools`, the API builds a system prompt that contains "Here are the functions available in JSONSchema format: {{ TOOL DEFINITIONS IN JSON SCHEMA }}". Tool and field descriptions are therefore model input.
  - Anthropic calls detailed descriptions "by far the most important factor in tool performance", and asks that each parameter's meaning be explained.
  - The API reference adds: "You can use natural language descriptions to reinforce important aspects of the tool input JSON schema."
  - The Agent SDK guide says a field description added via `Annotated[...]` is one "Claude sees".
- **`default`:**
  - No source says the API or the model applies `default`, or that it steers the model.
  - The Agent SDK guide says to "apply the default in the handler".
  - **Interpretation:** the model probably reads `default` as part of the JSON text and may treat it as a hint, but there is no documented effect. Our engine already fills defaults itself (`src/audio_engine/params.py:86-88`), so we do not depend on the model.
- **Documented alternative for steering:** `input_examples`, schema-valid example inputs placed in the prompt. Invalid examples return 400. They add about 20–200 tokens each. This is a Messages API field; the Python `@tool` has no parameter for it (`SDK/__init__.py:277-282`).
- **When the model sees the schema** depends on the Agent SDK's tool search. That is a runtime topic, covered in `docs/research/2026-10-28_agent-sdk-behaviour.md` (PR #79). The schema-specific point: field descriptions only help once the full schema is in the model's context.

**Sources.**
- [Define tools → Tool use system prompt / Best practices / Providing tool use examples](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools).
- [Messages API reference, `tools[].description`](https://platform.claude.com/docs/en/api/messages/create).
- [Agent SDK custom tools](https://code.claude.com/docs/en/agent-sdk/custom-tools) — "Make a parameter optional".

**Confidence.** High that descriptions are model input and matter. High that `default` has no documented effect. The influence of `default` is an **interpretation**, not established.

## Q4 — Is there a strict / structured-output mode for tool arguments, and does it guarantee schema-valid arguments?

**Answer.**
- **Yes on the Messages API:** `strict: true` on a tool definition. It is GA, needs no beta header, and supports Opus 5.5 and Sonnet 5.5 among others.
  - It uses grammar-constrained sampling.
  - Documented guarantees: "Tool `input` strictly follows the `input_schema`" and "Tool `name` is always valid".
- **The guarantee is narrower than our contract:**
  1. **Ranges are not enforced.** It covers only the supported subset; `minimum`/`maximum`/`maxLength` must be removed (Q1/Q2). An out-of-range value would still be "schema-valid" against the reduced schema.
  2. **Documented exceptions:** `stop_reason: "refusal"` or `"max_tokens"` can produce output that does not match the schema. Enum values "might differ from the schema only in capitalization".
  3. **Complexity limits:** at most 20 strict tools per request, and **24 optional parameters across all strict schemas** in a request. Our kick schema alone has 16 optional fields (18 properties, 2 required; counted locally), leaving 8 for the other tools.
- **Opus 5.5 and Sonnet 5.5 reject `tool_choice` `any`/`tool` with a 400.** Anthropic's suggested replacement is `auto` plus strict tool use.
- **Agent SDK (our route, D-014):**
  - The Python `@tool` signature has no `strict` parameter (`SDK/__init__.py:277-282`). The Python SDK reference and the custom-tools guide never mention strict for custom tools.
  - The SDK's own guarantee is the opposite kind: arguments are **validated after generation** with `jsonschema` against the full schema, and invalid input comes back to Claude as an error result (`SDK/__init__.py:343-344, 594-597, 628-632`).
  - **Interpretation:** the bundled CLI has internal code that sends `strict: true` for tools it marks strict, but there is no documented way to mark an SDK MCP tool strict.
- **Consequence:** with or without strict, D-002 validation (`validate_params`) remains required. Strict would only reduce wrong types and missing fields, never range errors.

**Sources.**
- [Strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use) — guarantees, GA status, model list.
- [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) — complexity limits, invalid outputs, enum casing.
- [Define tools → Forcing tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) — Opus 5.5 400 on forced tool use.
- [Tool reference → Tool definition properties](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-reference) — `strict` row.
- [Python SDK reference → `@tool`](https://code.claude.com/docs/en/agent-sdk/python) — no `strict`.
- `SDK/__init__.py` lines as cited.

**Confidence.** High for the API facts as the WebFetch summaries reported them. They are official and stated explicitly, but they have not been re-read at the source (To verify, item 7). High that the Python `@tool` cannot set strict (signature read). Low for the CLI internals.

## Q5 — How do the Agent SDK's custom tools take a schema, and how are tool names constrained?

**Answer.**
- **Schema forms** (`@tool(name, description, input_schema, annotations=None)`, `SDK/__init__.py:277-361`):
  1. A dict of name → Python type, like `{"seed": int}`. Every key becomes required (`:445-453`). `Annotated[T, "text"]` adds a description (`:372-379`). `str`/`int`/`float`/`bool`/`list`/`dict`/unions are mapped, and **any other type silently becomes `{"type": "string"}`** (`:415`). There is no enum, no range and no optional key.
  2. A `TypedDict` class. `NotRequired` keys become optional (`:418-433`).
  3. A full JSON Schema dict, passed through unchanged when it has a string `type` and `properties` (`:438-444`).
  - The guide says form 3 is needed "when you need enums, ranges, optional fields, or nested objects". That is our case.
  - The handler gets the arguments only after `jsonschema` validation (`:630`). A raised exception or `is_error: True` reaches Claude as an error result (`:633-641`).
- **Names:**
  - The API requires `^[a-zA-Z0-9_-]{1,128}$` for every tool name.
  - At runtime the Agent SDK prefixes custom tools as `mcp__{server_key}__{tool_name}`. That naming, and its use in `allowed_tools` and hooks, is covered in `docs/research/2026-10-28_agent-sdk-behaviour.md` (PR #79).
  - The MCP spec's naming rule is only a SHOULD (1–128 chars, `A-Z a-z 0-9 _ - .`). The dot is allowed there but not by the API regex.
  - **Duplicate names are not rejected, and they mix up schema, description and handler.** The Python SDK does not check names: `tool()` stores the string. `create_sdk_mcp_server` builds `tools_by_name` and `schemas` as dicts keyed by name, so there the later tool wins (`:605-606`). The advertised list `wire_tools` is built from the original list, so it keeps **both** entries (`:607-618`).
    - Reviewer's repro on PR #80 (two tools named `dup`): the list shows two `dup` entries, the first with tool 1's description but tool 2's schema. Every call runs tool 2's handler (`:625`, `:633`).
    - Recommendation: assert unique tool names when building the tool list, in code and in a CI test.
  - **Interpretation:** the API regex applies to the full `mcp__…` name the CLI sends. So server key plus tool name must stay within 128 characters and use no dots. `mcp__abeltongod__generate_kick` (31 chars) is fine.

**Sources.**
- `SDK/__init__.py` lines as cited.
- [Agent SDK custom tools → Create a custom tool / Call a custom tool](https://code.claude.com/docs/en/agent-sdk/custom-tools).
- [Agent SDK MCP → Tool naming convention](https://code.claude.com/docs/en/agent-sdk/mcp).
- [Messages API reference, `tools[].name`](https://platform.claude.com/docs/en/api/messages/create) and [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) (regex).
- [MCP spec 2025-11-25 → Tool Names](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

**Confidence.** High (source read plus official docs). Medium for the interpretation about the full-name length.

## Known pitfalls

- **Whole-number floats pass as integers.** Both the SDK's `jsonschema` check and ours accept `variants: 2.0` for an `integer` field (2020-12 semantics, reproduced locally). `validate_params` converts such values to `int` (`params.py:83-85`), so the result is consistent. Do not add a second "is int" check that disagrees.
- **Double validation, different messages.** The SDK rejects invalid arguments before our handler runs, with its own text "Input validation error: …" (`SDK/__init__.py:632`, first error only). Our `KickParamsError` lists all errors, but on the SDK path it only runs for inputs the SDK already accepted. Tests that expect our message must call the handler directly, or go through a fake model client (D-020 step 1).
- **Shared dict, two copies.** The SDK keeps a reference to our schema dict, not a copy (`:444`, stored in `schemas` at `:606`), and validates every call against that live dict (`:630`). The advertised `Tool` is built once at registration (`Tool.model_validate`, `:608-616`).
  - **Observed in the reviewer's repro on PR #80:** the copy made at registration is **shallow**. Top-level keys are copied, but `properties` is the same object.
  - So a nested change (for example raising a field's `maximum`) shows up in both the advertised schema and validation.
  - Only top-level changes (for example `required` or `additionalProperties`) make the advertised schema and validation diverge.
  - Never mutate the loaded schema after registering; build the tool-facing schema as a new dict.
- **Dict-of-types shortcut.** Using `{"bpm": float}` for convenience loses ranges, enums and optionality, and unknown types become strings (`:415`). Always pass the JSON Schema dict.
- **Duplicate tool names** silently produce a mixed tool (Q5). Assert uniqueness.
- **`transform_schema` drops `const` and leaks root URLs** into the description (Q2). Never use its output unchecked.
- **Optional-parameter budget** (strict only): 16 of 24 used by `generate_kick` alone.

## Test-strategy hints (what CI can do)

- **CI, no network:**
  - Build the tool-facing schema from `contracts/kick-params.schema.json` and assert it (a) has no `$id`, (b) still rejects every out-of-range value our contract rejects (property test over the full range, CLAUDE.md rule).
  - Register it with `@tool` / `create_sdk_mcp_server` and assert the wire schema `create_sdk_mcp_server` lists is identical to the input (catches an SDK upgrade that starts transforming).
  - Feed recorded or fake tool calls through the in-process server's call path (no CLI needed) to confirm the SDK-level rejection and our `validate_params` agree on a seeded random set of valid and invalid inputs.
  - Inject a fault (e.g. raise `maximum` of `drive` to 1.02) and confirm the agreement test turns red.
  - Assert unique tool names. Fault injection: register two tools with the same name and confirm the test turns red.
- **Needs a real login (user's machine or a dev session; never CI):** the items under "To verify".

## To verify by experiment

Each item becomes an issue for the owning role (`orchestrator-engineer` unless noted).

1. **API/CLI accepts the as-is schema.**
   - Run one real Agent SDK `query()` with `generate_kick` registered from the unchanged contract (including `$id`, `$schema`, `const` without `type`), using the closed tool surface from the cluster-1 note.
   - Expect no 400, and `mcp__<server>__generate_kick` in the init message's `tools`.
   - Repeat without `$id`/`$schema`.
2. **What the model receives.**
   - Confirm that `description` and `default` text reach the model unchanged. Ask the model, in a throwaway session, to quote the `default` of `pitch_decay_ms` from its tool definition.
   - Record the result as observed behaviour, not as a documented guarantee.
3. **Tool search:** moved to the cluster-1 note (`docs/research/2026-10-28_agent-sdk-behaviour.md`, PR #79, items V1/V6). It is not repeated here.
4. **Out-of-range behaviour in practice.** Over N real requests (for example the three example prompts from the phase spec), count how often Opus 5.5 produces arguments the SDK or `validate_params` rejects, and save them as recorded fixtures for CI.
5. **Strict through the Agent SDK.** Confirm there is no supported way to mark an SDK MCP tool `strict` in 0.2.172/0.2.174 (check the changelog at the start of 04b step 2). If one appears, re-run Q2's strict table against it.
6. **Only if the API-key route is ever switched on (D-008/D-014 switch):** send the hand-checked strict schema with `strict: true` and confirm it compiles (no 400, no "Schema is too complex"). Use the `transform_schema` output with `const` restored and `$schema`/`$id` removed beforehand. Also confirm that the raw contract with `strict: true` returns 400 as documented.
7. **Re-read the web-doc claims at the source.** They were checked only through WebFetch summaries, and the reviewer could not re-fetch them:
   - the strict guarantees (input follows the schema; name always valid) and their exceptions (refusal, `max_tokens`, enum casing)
   - 400 on unsupported strict keywords
   - the name regex `^[a-zA-Z0-9_-]{1,128}$`
   - the limits of 20 strict tools and 24 optional parameters
   - the 400 on `tool_choice` `any`/`tool` for Opus 5.5

   Owner: whoever starts 04b step 2, by opening the pages directly. Until then they count as "not verified".

## Implications (proposals for the lead; not decisions)

- **Tool-schema builder.** Generate the `generate_kick` input schema in code from `contracts/kick-params.schema.json` rather than writing a second copy. It should drop `$id`, replace the root `description` with model-facing text, and keep every range, enum and `additionalProperties: false`, so the SDK's pre-check enforces the full contract. No new contract file is needed for this. Whether the derived schema should also drop `schema_version` (the orchestrator inserts `"0.2"`) is a design choice for the `orchestrator-engineer` issue.
- **Tool and field descriptions are product text.** The `pitch_decay_ms` guideline already lives in the schema `description`. That is good, since it is what the model reads, but it is long. Write the tool description (what `generate_kick` does, when to use it, that ranges are enforced and out-of-range calls are rejected, not clamped) as part of the 04b step-2 issue.
- **Keep D-002 validation as the authority.** Strict mode cannot replace it (no ranges), and it is not reachable from the Python Agent SDK anyway.
- **Bridge tools need schemas first.** `list_tracks` and `import_sample` have no input schema in `contracts/`. D-002 says every tool has a JSON schema in `contracts/`. This is now tracked as issue #81 (`contract-change: input schemas for list_tracks and import_sample (04b step 2)`).
- **Assert unique tool names** in the tool builder (Q5).
- **Tool-search setting:** see the cluster-1 note (PR #79). This note makes no separate proposal.
- **Staleness.** Re-check Q4/Q5 against the SDK version pinned at the start of 04b step 2. 0.2.174 is already out.
