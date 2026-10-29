# PHASE 04b — Claude orchestrator (kick workflow end-to-end)

**Status:** IN PROGRESS · **Agent:** main session (+ `reviewer`) · **Tested in:** CI (schemas, fake bridge, recorded responses) + user's machine

## Objective

The user types a request in German or English ("drei trockene, dunkle Kicks für 136 BPM, kurzer Tail") and gets kick variants generated, previewed and imported.

## Prerequisites

Phases 01–03 and **04a (resource guard)** accepted. Decision on auth method (D-008) confirmed with the user before coding.

## Scope

1. Tool definitions generated from `contracts/` schemas: `generate_kick`, `list_tracks`, `import_sample` — only for `tested` capabilities.
2. Orchestrator loop: user text → Claude tool call → schema validation → local execution → structured result back to Claude → answer to the user.
3. Approval levels: generating files = routine; touching the Live set = confirm.
4. Minimal UI: start with a terminal chat; desktop UI is a separate later phase.
5. Auth behind one config switch (subscription via Agent SDK or API key).
6. Every model call and every tool goes through the 04a guard with profile `kick_generation`; pass `max_turns` / `max_budget_usd` to the SDK from the same profile. Show the user a short German message when the guard warns or stops.

## Out of scope

Arrangement, mixing, other instruments, desktop UI polish.

## Acceptance criteria

- [x] CI: invalid tool arguments from the model are rejected; tests use recorded/fake model responses, no live API calls. (step 1, PR #89)
- [ ] User-verified: one complete request → three kicks → one imported into Live.
- [ ] Engine and bridge still work when Claude is unreachable (clear error, no crash).
- [x] CI: a fake model that loops on one tool is stopped by the guard, and the user sees what finished and what did not. (step 1, PR #89)
- [ ] No code path calls Claude or a model-callable tool without passing the guard (reviewer checks).
