# Research: Claude Agent SDK behaviour for the Phase 04b orchestrator (cluster 1)

- **Date:** 2026-10-28. All web sources retrieved on 2026-10-28.
- **Versions researched against:** `claude-agent-sdk` **0.2.174** (PyPI, uploaded 2026-10-24, `win_amd64` wheel present), source at tag `v0.2.174`, commit `0e89b298e771259378a6cd3734e00d323dff5703`. That wheel bundles Claude Code CLI **2.1.310** (`src/claude_agent_sdk/_cli_version.py`). Docs pages on code.claude.com have no version stamp; their version notes (e.g. "requires v2.1.217") are all older than 2.1.310.
- **Receiving issue:** #23 (Phase 04b). Rules: D-019 point 3. Context: D-011 (guard), D-014 (subscription login, Opus 5.5), D-020 (04b step 1 is CI-only, behind a model-client interface).
- **Extends, does not repeat:** [`2026-10-28_guard-sdk-mapping.md`](2026-10-28_guard-sdk-mapping.md) (limit ↔ SDK mapping) and [`2026-10-28_claude-auth-options.md`](2026-10-28_claude-auth-options.md) (auth routes, rows 14–19 on limits and hooks). Where this note adds to or corrects those, it says so.

Source shorthand: **[src]** = `https://github.com/anthropics/claude-agent-sdk-python/blob/v0.2.174/<path>#L<line>`; paths below are relative to the repository root. Docs pages:
[agent-loop](https://code.claude.com/docs/en/agent-sdk/agent-loop) ·
[cost-tracking](https://code.claude.com/docs/en/agent-sdk/cost-tracking) ·
[hooks](https://code.claude.com/docs/en/agent-sdk/hooks) ·
[custom-tools](https://code.claude.com/docs/en/agent-sdk/custom-tools) ·
[permissions](https://code.claude.com/docs/en/agent-sdk/permissions) ·
[python-ref](https://code.claude.com/docs/en/agent-sdk/python) ·
[tool-search](https://code.claude.com/docs/en/agent-sdk/tool-search) ·
[cli-reference](https://code.claude.com/docs/en/cli-reference) ·
[tools-reference](https://code.claude.com/docs/en/tools-reference) ·
[authentication](https://code.claude.com/docs/en/authentication) ·
[quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart) — all retrieved 2026-10-28.

## Short answers

| # | Question | Answer in one line | Confidence |
| --- | --- | --- | --- |
| 1 | `max_turns` stop point | Enforced by the CLI between turns; no source says it interrupts a running tool (interpretation: it does not). Ends with `ResultMessage(subtype="error_max_turns")`, then `query()` raises `ResultError`. **`max_turns=0` means "no limit".** | High for result/raise; medium for "running tool completes" |
| 2 | `max_budget_usd` | Checked after each model response from the API-reported usage; that response completes, so spend can overshoot. Cost = client-side estimate from a bundled price table, same mechanism for any auth (docs do not distinguish). Ends with `error_max_budget_usd`, then `ResultError`. | High (docs); subscription part medium |
| 3 | PreToolUse hooks | Yes: deny with a reason the model sees; yes: `updatedInput` rewrites arguments; yes: fire for sub-agent tool calls (`agent_id` set). Run first, deny wins, deny holds even in `bypassPermissions`. | High |
| 4 | Custom tools / wrapper | `@tool` + `create_sdk_mcp_server`, passed via `mcp_servers`; names `mcp__<server>__<tool>`. The handler runs in our process, so a wrapper around each handler sees name + validated args + result. Invalid args are rejected by the SDK before the handler. | High |
| 5 | Built-ins off | `tools=[]` removes all built-in tools; add `strict_mcp_config=True`, `setting_sources=[]`, `disallowed_tools` and `permission_mode="dontAsk"` for a closed surface. Check the init message's `tools` list. | High (docs + code); end state unverified |
| 6 | Windows subscription login | Supported in principle: the `win_amd64` wheel bundles the CLI, which uses the `/login` credentials from `%USERPROFILE%\.claude\.credentials.json`. **A set `ANTHROPIC_API_KEY` silently wins** in SDK runs (non-interactive) and bills the Console org instead. | Medium (no Windows run seen) |

## Question 1 — Does `max_turns` stop a running tool call, or only before the next turn? What is returned/raised?

**Answer.**
- The Python SDK does not enforce the limit itself. It only passes `--max-turns N` to the CLI subprocess, and **only when the value is truthy**: `if self._options.max_turns:` — so `max_turns=0` (and `None`) passes no flag and the run is **unlimited**. [src `src/claude_agent_sdk/_internal/transport/subprocess_cli.py#L610-L611`] Confidence: high (code).
- A "turn" is one tool-use round trip (model output with tool calls → tools run → results back). `max_turns` "counts tool-use turns only"; the docs' example says `max_turns=2` "would have stopped before the edit step" (the third turn). [agent-loop, "Turns and messages"] Confidence: high.
- **Correction to watch:** the SDK's own docstring says "A turn consists of a user message and assistant response" [src `src/claude_agent_sdk/types.py#L2405-L2409`], which contradicts the docs page and the Python reference row "Maximum agentic turns (tool-use round trips)" [python-ref]. Treat the docs as current, verify by experiment (V1).
- No source says the limit interrupts a tool that is already running. The docs describe the limit as stopping *before* a turn; the SDK has no code that cancels a tool on this limit (the only tool cancellation path is a CLI `control_cancel_request` [src `src/claude_agent_sdk/_internal/query.py#L420-L426`]). **Interpretation:** the check runs at the turn boundary and a running tool finishes. Whether the model call that opens the over-limit turn is still made (and billed) is not stated. Confidence: medium.
- On stop: a `ResultMessage` with `subtype="error_max_turns"`, `is_error=True`, no `result` text; `total_cost_usd`, `usage`, `num_turns`, `session_id` are still present; `terminal_reason` can be `"max_turns"`. [agent-loop, "Handle the result"; src `src/claude_agent_sdk/types.py#L1695-L1726`] Confidence: high.
- A single-shot `query()` then **raises**. The CLI exits non-zero after an error result; the SDK replaces the bare `ProcessError` with **`ResultError`** (subclass of `ProcessError`) carrying `subtype`, `errors`, `result`, `terminal_reason`. [src `src/claude_agent_sdk/_internal/query.py#L512-L541`, `src/claude_agent_sdk/_errors.py#L56-L86`] The docs show the text "Reached maximum number of turns". A `ClaudeSDKClient` (streaming-input) session stays alive; a queued message starts a new turn and the max-turns count **starts over** for it. [agent-loop, "Turns and budget"] Confidence: high.
- Hooks "may not fire when the agent hits the `max_turns` limit because the session ends before hooks can execute". [hooks, "Hook not firing"] Confidence: high (quoted caveat).
- The CLI flag is "print mode only" and "Exits with an error when the limit is reached". [cli-reference, `--max-turns`] Confidence: high.

## Question 2 — `max_budget_usd`: when is it checked, how is cost estimated (subscription vs API key), what is returned?

**Answer.**
- Passed as `--max-budget-usd` whenever it is `not None`, so `0.0` *is* passed (unlike `max_turns`). [src `src/claude_agent_sdk/_internal/transport/subprocess_cli.py#L613-L614`] Confidence: high (code).
- **When:** Claude Code compares spend with the cap **after each model response arrives**, because the cost comes from the token usage the API returns with it. The response that reaches the cap completes and counts; spend can pass the cap by that one response plus whatever still-running sub-agents spend before they stop. Sub-agent spend counts; once the cap is reached, spawning a sub-agent fails with `Budget limit reached` (needs CLI ≥ 2.1.217; bundled is 2.1.310). [agent-loop, "Budget headroom"; cli-reference, `--max-budget-usd`] Confidence: high. (Already in the auth note, rows 15–16; repeated here only for the stop point.)
- **How estimated:** `total_cost_usd` is a client-side estimate computed locally from a price table bundled at build time (or a `modelPricing` setting), not billing data; it drifts when prices change or the build does not know a model. `model_usage[...].costBasis` says which table priced a model (`list` / `managed` / `unknown`, CLI ≥ 2.1.246). [cost-tracking, warning box and "Break down usage per model"] Confidence: high.
- **Subscription vs API key:** the cost-tracking page does not distinguish auth methods for the estimate. Its only subscription-specific statement: on a subscription within plan usage, the main conversation gets a **1-hour cache TTL** without setting anything; with an API key the default is 5 minutes. [cost-tracking, "Extend the prompt cache TTL to one hour"] **Interpretation:** the same estimate is computed under both auth methods; under subscription it is an API-equivalent figure, nothing is charged (consistent with D-011/D-014). Whether the estimate prices 1-hour cache writes at the 1-hour rate is not stated (V3). Confidence: medium.
- **Scope:** counts only the call's own spend; totals restored from a resumed session do not count; in a streaming session the budget accumulates across messages and a `/clear` starts it over. [python-ref `max_budget_usd` row; cost-tracking, "Track costs in streaming input mode"] Confidence: high.
- **On stop:** `ResultMessage(subtype="error_max_budget_usd", is_error=True)`, no `result`; `usage` **leaves out** the crossing response while `total_cost_usd` and `model_usage` include it; then `query()` raises `ResultError` as in Q1. [agent-loop; cost-tracking, "Track costs on failed conversations"] Confidence: high.
- Extra signal for the subscription window: the SDK yields `RateLimitEvent` with `status` `allowed` / `allowed_warning` / `rejected` and types `five_hour`, `seven_day`, … [src `src/claude_agent_sdk/types.py#L1745-L1790`] Confidence: high (type exists); whether it is emitted for subscription sessions in practice is unverified (V7).

## Question 3 — PreToolUse hooks in Python: deny with a reason, modify arguments, sub-agent coverage?

**Answer.**
- **Registration:** `ClaudeAgentOptions(hooks={"PreToolUse": [HookMatcher(matcher=..., hooks=[cb], timeout=...)]})`. `matcher` is a tool-name pattern (`"mcp__kick__.*"`-style regex or `"A|B"` lists; omitted = every tool). Callback signature `async (input, tool_use_id, context) -> dict`; `context["signal"]` is always `None` in Python. [hooks, "Configure hooks", "Matchers"; src `src/claude_agent_sdk/types.py#L818-L855`, `src/claude_agent_sdk/_internal/query.py#L640-L654`] Confidence: high.
- **Input:** `PreToolUseHookInput` has `tool_name`, `tool_input`, `tool_use_id`, plus optional `agent_id`/`agent_type`. [src `src/claude_agent_sdk/types.py#L348-L354`] Confidence: high.
- **Deny with reason:** return `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`. The docs: `permissionDecision: 'deny'` stops the call, `permissionDecisionReason` "tells the model why", `systemMessage` is for the user. Claude "receives the rejection message instead". [hooks, "Add context and block a tool"; agent-loop, "Hooks"] Confidence: high.
- **Modify arguments:** `updatedInput` inside `hookSpecificOutput`; pair with `allow` (auto-approve) or omit the decision (normal permission flow); ignored with `defer`. Return a new dict, do not mutate. [hooks, "Modify tool input"] Confidence: high.
- **Precedence:** hooks run **first** in the permission order; a hook `deny` holds even in `bypassPermissions`; a hook `allow` does not skip deny rules. Multiple matching hooks run **in parallel**; the most restrictive decision wins (`deny` > `defer` > `ask` > `allow`). [permissions, "How permissions are evaluated" step 1; hooks, note under "Outputs" and "Register multiple hooks"] Confidence: high.
- **Sub-agents:** `agent_id`/`agent_type` are "present only when the hook fires from inside a Task-spawned sub-agent"; they are the "only reliable way" to attribute interleaved sub-agent hook calls. So PreToolUse/PostToolUse **do fire for sub-agent tool calls**. [src `src/claude_agent_sdk/types.py#L329-L345`; hooks, "Inputs"] Confidence: high (matches auth-note row 19).
- **Timeout / failure:** default hook timeout 600 s; on timeout a PreToolUse hook **blocks** the call and the turn continues (CLI ≥ 2.1.210). [hooks, "Hook timeout"] If the Python callback **raises**, the SDK answers the CLI with a control-response error [src `src/claude_agent_sdk/_internal/query.py#L694-L702`]; what the CLI then does (block or allow) is **not documented** (V4). Confidence: high for timeout, unknown for exceptions.
- **Stopping the whole run from a hook:** top-level `continue_: False` + `stopReason` "determines whether the agent keeps running after this hook". [hooks, "Outputs"; src `src/claude_agent_sdk/types.py#L775-L812`] Which `ResultMessage` subtype that produces is not documented (V5).
- **Exempt tool:** `EndConversation` skips PreToolUse, but it is not offered in Agent SDK sessions. [tools-reference, "EndConversation tool behavior"] Confidence: high.

## Question 4 — Registering in-process tools; can a wrapper reliably see name + args + result for the guard?

**Answer.**
- **Define:** `@tool(name, description, input_schema, annotations=None)` returns an `SdkMcpTool` (name, description, input_schema, handler, annotations). `input_schema` can be a simple dict (`{"bpm": float}` → all keys required), a TypedDict, or a **full JSON Schema dict** (recognised when it has `"type"` and `"properties"`; passed through unchanged). [src `src/claude_agent_sdk/__init__.py#L267-L358`, `#L436-L456`; custom-tools, "Create a custom tool"] Confidence: high. (Schema generation itself is cluster 2.)
- **Register:** `create_sdk_mcp_server(name, version="1.0.0", tools=[...])` → `McpSdkServerConfig`; pass `mcp_servers={"kick": server}`; the model sees `mcp__kick__<tool>`; pre-approve with `allowed_tools=["mcp__kick__generate_kick", ...]`. The server runs in our process. [custom-tools, "Call a custom tool"; src `src/claude_agent_sdk/__init__.py#L517-L645`] Confidence: high.
- **Validation and errors:** before the handler runs, the SDK validates arguments with `jsonschema.validate` against the tool's schema; unknown tool, validation error and handler exception all become an `isError` tool result the model can read — the query does not fail. [src `src/claude_agent_sdk/__init__.py#L620-L642`; custom-tools, "Handle errors"] The Python decorator forwards only `content` and `is_error`, not `structuredContent`. [custom-tools, note under "Return structured data"] Confidence: high.
- **Wrapper for the guard (D-011):** three observation points exist:
  1. **Our own wrapper around each handler** — runs in our process with the validated `args` and the returned result; nothing in the SDK can call the handler without it. **Interpretation:** this is the most reliable place for `before_tool` / `after_tool` (name, args, result, files/Live writes). It does **not** see calls rejected by schema validation or unknown-tool calls (they never reach the handler).
  2. **PreToolUse hook** — sees `tool_name` + `tool_input` for *every* tool call incl. built-ins and sub-agents, before execution, and can deny. Interpretation from the order of operations: it fires before the SDK's schema validation, so invalid calls are visible here.
  3. **PostToolUse hook** — `tool_response` (+ `duration_ms`), correlated with PreToolUse by `tool_use_id`; can replace the output via `updatedToolOutput`. [src `src/claude_agent_sdk/types.py#L357-L368`, `#L521-L535`]
  Confidence: high for what each point receives; the split between them is interpretation.
- **Parallelism:** custom tools run sequentially unless annotated `readOnlyHint=True`. [agent-loop, "Parallel tool execution"] Confidence: high.
- **Tool search is on by default and defers SDK MCP tools:** the model first sees a name list and may call the built-in `ToolSearch` to load schemas — an extra round trip. For fewer than ~10 tools the docs say upfront loading is typically faster; disable with `env={"ENABLE_TOOL_SEARCH": "false"}`. [tool-search, "How tool search works", "Configure tool search"; custom-tools, "Add more tools"] Confidence: high. Whether a `ToolSearch` call counts as a turn against `max_turns` is not stated (V1).

## Question 5 — Can built-in tools (Bash, edit, web) be fully disabled so only our tools are callable?

**Answer.**
- `tools=[]` → the SDK passes `--tools ""` [src `src/claude_agent_sdk/_internal/transport/subprocess_cli.py#L592-L601`]; docs: "All built-ins are removed. Claude can only use your MCP tools." `tools` does not affect MCP tools. [custom-tools, "Configure allowed tools"; cli-reference, `--tools`] Confidence: high.
- `allowed_tools` does **not** restrict anything — it only auto-approves; unlisted tools stay available. [permissions, "Allow and deny rules"] Confidence: high.
- Other sources of tools/config the CLI would load otherwise:
  - `strict_mcp_config=True` → only our `mcp_servers`, ignoring project `.mcp.json`, user settings, plugin servers and claude.ai connectors. [python-ref; src `subprocess_cli.py#L700-L701`]
  - `setting_sources=[]` → no user/project/local settings (CLAUDE.md, settings hooks, permission rules). Default `None` loads **all** sources. Endpoint-managed policy still loads. [python-ref `setting_sources` row]
  - `system_prompt=None` (default) → the SDK passes `--system-prompt ""`, i.e. no Claude Code preset prompt. [src `subprocess_cli.py#L576-L577`]
  - `permission_mode="dontAsk"` → every call that would prompt is denied; only `allowed_tools`/hook-approved calls run. [permissions, "Don't ask mode"]
  - `disallowed_tools` bare names (e.g. `"Agent"`, `"Bash"`) remove tools from context as a second layer; `"mcp__*"` would remove our tools too, so do not use it. [permissions table]
  Confidence: high for each option's documented effect.
- `EndConversation` cannot be removed by `--tools`, but it is not present in Agent SDK sessions. [tools-reference] Unknown: whether `ToolSearch` remains when `tools=[]` and MCP tools exist (V6). Verify the end state from the init `SystemMessage`, which lists `tools` and `mcp_servers`. [src `src/claude_agent_sdk/types.py#L1461-L1495`]

## Question 6 — Subscription login from a plain Python script on Windows; what breaks with `ANTHROPIC_API_KEY` set?

**Answer.**
- **Runtime:** the `win_amd64` wheel exists for 0.2.174 (PyPI JSON, 2026-10-28). The SDK first looks for the bundled binary in `_bundled/` and uses it [src `subprocess_cli.py#L257-L260`, `#L341-L352`]; it refuses `.bat`/`.cmd` CLI paths on Windows (since 0.2.124) [src `subprocess_cli.py#L416-L441`; `CHANGELOG.md#L379-L383`]. ARM64 Windows gets the sdist without a binary. [quickstart] Confidence: high.
- **Auth:** the Python SDK has no auth code of its own; the spawned CLI uses its normal precedence: cloud provider → `ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY` → `apiKeyHelper` → `CLAUDE_CODE_OAUTH_TOKEN` → Anthropic profile → subscription `/login`. On Windows the login lives in `%USERPROFILE%\.claude\.credentials.json` (or under `CLAUDE_CONFIG_DIR`). [authentication, "Authentication precedence", "Credential management"] The quickstart only documents API keys, and says third-party developers may not offer claude.ai login (personal use: see auth note rows 3–5). Confidence: high for precedence.
- **Interpretation:** a plain `python orchestrator.py` on Windows uses the subscription when the user has logged in once with Claude Code (`claude` / `claude auth login`) under the same user profile, or has set `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`. The bundled binary is not on `PATH`, so the login step needs a normal Claude Code install or the token route. No source shows a Windows SDK run on subscription; confidence medium (V7).
- **With `ANTHROPIC_API_KEY` set:** "In non-interactive mode (`-p`), the key is always used when present" — the SDK runs the CLI non-interactively, so the key **overrides the subscription without a prompt**; requests then bill the key's Console organisation, and a key from a disabled/expired org causes auth failures. `ANTHROPIC_AUTH_TOKEN` ranks even higher. [authentication] The SDK passes the **whole parent environment** to the CLI (only `CLAUDECODE` is filtered), with `options.env` merged on top — it cannot *remove* a variable. [src `subprocess_cli.py#L814-L824`] So a key loaded from `.env` into `os.environ` reaches the CLI. Confidence: high.
- **Detection:** the init message carries `apiKeySource` — `"ANTHROPIC_API_KEY"`, `"apiKeyHelper"`, `"/login managed key"` or `"none"` (claude.ai login). [src `src/claude_agent_sdk/types.py#L1484-L1487`] The orchestrator can compare this with the D-014 config switch at startup. Confidence: high (field exists); values on the user's machine unverified.

## Pitfalls (summary)

1. `max_turns=0` = unlimited (Q1). `GuardedRequest.sdk_limits()` returns `max(0, int(headroom))` (`src/guard/guard.py:384-392`), so a request with no model-call headroom left would hand the SDK "no limit".
2. Inside one `query()` the SDK makes all model calls itself; the orchestrator only *observes* them afterwards (`AssistantMessage`), so the guard's `before_model_call` cannot gate each API call. Hard stops inside a run are: SDK limits, a hook/handler deny, a hook `continue_: False`, `ClaudeSDKClient.interrupt()`, or cancelling the task.
3. `query()` raises `ResultError` after any error result — catch it, or a guard-limited stop looks like a crash.
4. `usage` undercounts (main loop only; excludes the budget-crossing response); use `total_cost_usd` / `model_usage`. Per-step `output_tokens` is a placeholder.
5. Default `setting_sources=None` loads the user's `~/.claude` settings and hooks — the development setup would leak into the product run.
6. Tool search defers our tools by default → extra `ToolSearch` round trip.

## To verify by experiment

Each becomes an issue for the owning role (orchestrator-engineer unless stated). Where a real Claude call is needed it runs on the user's machine (not CI, D-020); the "fake" ones can use a stub CLI or recorded stream.

| # | Experiment | Needs |
| --- | --- | --- |
| V1 | With `max_turns=N` and a tool that sleeps 3 s: count model calls (`AssistantMessage.message_id`s) and tool executions; confirm the running tool completes, whether the over-limit model call is made/billed, whether a `ToolSearch` call counts as a turn, and that the docstring vs docs definition of "turn" matches the docs. | Real call (user machine) |
| V2 | `max_turns=0` passes no `--max-turns` flag (unit test on our wrapper against `SubprocessCLITransport._build_command`, or a guard that never passes 0). | CI |
| V3 | Budget: overshoot size with a cap below one response; `total_cost_usd` is non-zero under subscription; pricing of 1-hour cache writes. | Real call |
| V4 | PreToolUse deny: the exact tool-result text the model receives; behaviour when the Python callback raises (fail-closed or fail-open?). | Real call |
| V5 | Hook `continue_: False` + `stopReason`: which `ResultMessage` subtype results and whether `query()` raises. | Real call |
| V6 | With `tools=[]`, `strict_mcp_config=True`, `setting_sources=[]`, `ENABLE_TOOL_SEARCH=false`: init `tools` lists only `mcp__kick__*` (no `ToolSearch`, `Agent`, `Bash`). | Real call (init only, cheap) |
| V7 | Windows 11, plain venv script, wheel-bundled CLI, after `claude auth login`: `apiKeySource == "none"`, request succeeds, `RateLimitEvent` appears or not. Repeat with `ANTHROPIC_API_KEY` set → `apiKeySource == "ANTHROPIC_API_KEY"`; check whether `options.env={"ANTHROPIC_API_KEY": ""}` neutralises it. | User's machine |
| V8 | `ResultError.subtype` on `error_max_turns` / `error_max_budget_usd` from a single-shot `query()`; `ClaudeSDKClient` stays usable afterwards. | Real call, or recorded stream in CI |

## Implications for the lead (proposals only)

- **Guard ↔ SDK wiring (issue for orchestrator-engineer):** never pass `max_turns=0`; if `sdk_limits()["max_turns"] == 0` the orchestrator must not start the model call (treat it as a guard stop). Map `max_turns = max_model_calls − 1` only after V1 settles the off-by-one; until then the guard counts model calls from `AssistantMessage.message_id` (deduplicated) and stops at the next tool via a deny.
- **Tool accounting point:** put `before_tool` / `after_tool` in a wrapper around every `@tool` handler (sees validated args and the result); add one catch-all PreToolUse hook (no matcher) that denies any tool name not in our allowlist and records it, so sub-agent or unexpected calls are visible and blocked (D-011 "including tools used by sub-agents"). Do not rely on `can_use_tool`.
- **Closed tool surface:** `tools=[]`, `strict_mcp_config=True`, `setting_sources=[]`, `permission_mode="dontAsk"`, `allowed_tools=[our three]`, `env={"ENABLE_TOOL_SEARCH": "false"}`, short custom `system_prompt`, `agents=None`; assert the init message's `tools` at startup.
- **Auth switch (D-014):** at startup compare `apiKeySource` with the configured auth mode and refuse to run on a mismatch; document in `docs/setup/` that `ANTHROPIC_API_KEY` must not be set machine-wide when subscription mode is chosen.
- **Model-client interface (D-020 step 1):** the fake model should be able to emit `error_max_turns` / `error_max_budget_usd` results followed by a raised `ResultError`, so the CI loop tests cover the SDK's stop path.
- Update `2026-10-28_guard-sdk-mapping.md` row `max_model_calls` in 04b with pitfall 1 and 2 (owner of that note decides; this note does not edit it).
