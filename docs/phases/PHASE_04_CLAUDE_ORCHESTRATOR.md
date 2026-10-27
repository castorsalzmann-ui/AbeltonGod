# PHASE 04 — Claude orchestrator (kick workflow end-to-end)

**Status:** PLANNED · **Agent:** main session (+ `reviewer`) · **Tested in:** CI (schemas, fake bridge, recorded responses) + user's machine

## Objective

The user types a request in German or English ("drei trockene, dunkle Kicks für 136 BPM, kurzer Tail") and gets kick variants generated, previewed and imported.

## Prerequisites

Phases 01–03 accepted. Decision on auth method (D-008) confirmed with the user before coding.

## Scope

1. Tool definitions generated from `contracts/` schemas: `generate_kick`, `list_tracks`, `import_sample` — only for `tested` capabilities.
2. Orchestrator loop: user text → Claude tool call → schema validation → local execution → structured result back to Claude → answer to the user.
3. Approval levels: generating files = routine; touching the Live set = confirm.
4. Minimal UI: start with a terminal chat; desktop UI is a separate later phase.
5. Auth behind one config switch (subscription via Agent SDK or API key).

## Out of scope

Arrangement, mixing, other instruments, desktop UI polish.

## Acceptance criteria

- [ ] CI: invalid tool arguments from the model are rejected; tests use recorded/fake model responses, no live API calls.
- [ ] User-verified: one complete request → three kicks → one imported into Live.
- [ ] Engine and bridge still work when Claude is unreachable (clear error, no crash).
