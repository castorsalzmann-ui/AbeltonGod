# PHASE 04a — Agent Resource Guard

**Status:** PLANNED · **Agent:** main session (+ `reviewer`) · **Tested in:** CI only (no Claude, no Ableton needed)

## Objective

A guard that every product Claude call and every model-callable tool must pass, enforcing `config/guard-policy.json`. Decision: D-011.

## Prerequisites

Phase 00 done. No dependency on Phases 01–03: the guard is pure Python and can be built in parallel. It must be merged **before** Phase 04b makes the first real Claude call.

## Scope

1. `src/guard/policy.py`: load and validate the policy against `contracts/guard-policy.schema.json`; pick a profile by name; reject unknown profiles.
2. `src/guard/budget.py`: per-request counters (model calls, tool calls, output tokens, cost estimate, files written, Ableton writes) plus session and daily totals. Reserve before a call, settle with actual usage after it. If actual usage is missing, count the reserved (conservative) amount. Thread-safe reservations.
3. `src/guard/loop.py`: detect the same tool with the same arguments more than `max_identical_tool_calls` times in one request.
4. `src/guard/guard.py`: one entry point the orchestrator uses, e.g. `with guard.request("kick_generation") as req:` then `req.before_model_call(...)`, `req.after_model_call(usage)`, `req.before_tool(name, args, writes_files=n, live_writes=n)`. Returns a level: `ok`, `warn`, `stop`. On `stop` it raises a typed `GuardStop` carrying what was done and what is open.
5. Timeout per request (monotonic clock, injectable for tests).
6. `src/guard/usage_log.py`: append-only JSONL in a local, git-ignored folder: timestamp, profile, call kind, estimated vs actual tokens/cost, level, stop reason.
7. Mapping notes for Phase 04b: which limits are passed to the Agent SDK (`max_turns`, `max_budget_usd`) and which the guard enforces itself.

## Out of scope

Real Claude calls, model downgrade, context summarisation, CPU/GPU budgets, UI/dashboard.

## Tests (CI)

- Default policy file validates; malformed policies are rejected.
- Each limit triggers `warn` at the threshold and `stop` at the limit — one test per limit.
- Session and daily totals stop a request even if its own profile has room.
- Loop detection: same tool + same args stops; same tool + different args does not.
- Timeout stops via an injected clock (no real sleeping).
- Missing usage data counts conservatively.
- Concurrent reservations (threads) never exceed a budget.
- A stopped request can never produce a "success" result object.

## Acceptance criteria

- [ ] All tests above pass on Ubuntu and Windows.
- [ ] `ruff check .` clean.
- [ ] README section for the user (German): what the limits mean and how to change them in `config/guard-policy.json`.
