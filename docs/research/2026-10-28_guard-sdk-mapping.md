# Research: guard limits ↔ Claude Agent SDK (mapping for Phase 04b)

_Date: 2026-10-28 · Re-verify the SDK option behaviour at the start of Phase 04b; only option names were checked._

## Sources

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| 1 | `ClaudeAgentOptions` (Python) has `max_turns` ("maximum number of conversation turns before stopping") and `max_budget_usd` ("maximum budget in USD for the session"). | High for the names; **the stop behaviour and result type are not documented on that page** | [claude-agent-sdk-python: ClaudeAgentOptions](https://www.mintlify.com/anthropics/claude-agent-sdk-python/api/types/claude-agent-options) |
| 2 | The same options object has `can_use_tool` (callback per tool permission request: tool name, input, context → allow/deny) and `hooks` (lifecycle hooks, e.g. before a tool runs). | High for the names; hook events and sub-agent coverage not verified | same |

## Mapping

| Policy limit | Who enforces it | How |
| --- | --- | --- |
| `max_model_calls` | SDK **and** guard | Pass `req.sdk_limits()["max_turns"]` as `max_turns`. The guard still counts each model call via `before_model_call` / `after_model_call` if the orchestrator sees the calls; otherwise per SDK turn (verify what a "turn" is in 04b). |
| `max_budget_usd`, session, daily | SDK **and** guard | Pass `req.sdk_limits()["max_budget_usd"]` (tightest of request, session, daily headroom). Settle the guard with the SDK's reported cost after each call; missing cost counts the reservation. |
| `max_output_tokens` | API/SDK parameter + guard | Use `permit.max_output_tokens` as `max_tokens`. The guard stops if a call reports more. |
| `timeout_s` | guard | Use `req.remaining_s()` as the call timeout. The guard cannot interrupt a running call; it stops at the next guard step. |
| `max_tool_calls`, `max_identical_tool_calls`, `max_files_written`, `max_live_writes` | guard only | Route every tool through `req.before_tool` / `req.after_tool`. Candidate hook point: `can_use_tool` or a pre-tool hook — must also cover tools used by sub-agents (D-011). Verify in 04b. |
| `max_concurrent_requests` | guard only | Entering `guard.request(...)` takes a slot; no slot → `GuardStop`. |
| `warn_at_fraction` | guard → orchestrator | On `Level.WARN`: no new sub-tasks, shorter answers; show `warning_message_de(req.warnings)`. |

## Known limits of the guard (Phase 04a)

- **Other processes:** the daily total is re-read from the usage log before every model call, so settled calls of other Guards or processes on the same log count. Calls still *in flight* in another process are invisible. Run one copilot process at a time.
- **Zero estimates:** `estimated_cost_usd=0` is accepted. With `max_concurrent_requests > 1`, parallel calls with low estimates can overshoot the session budget before they settle (the overshoot is detected and stops the request afterwards). The default policy allows one request at a time. In 04b, pass a real estimate or `None` (reserves all money left).
- **Log size:** the re-read scans the whole log file on every model call. Fine for a personal log; rotate it if it grows large.
- **Timeout:** the guard cannot interrupt a running call; it stops at the next guard step.

## Open for 04b

- What the SDK returns when `max_turns` or `max_budget_usd` is hit, and how it reports per-call cost and tokens.
- Whether `can_use_tool` / hooks fire for sub-agent tool calls.
- With subscription auth the USD figures are API-equivalent estimates (D-011).
