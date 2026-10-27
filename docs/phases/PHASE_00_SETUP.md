# PHASE 00 — Repository & workflow setup

**Status:** IN PROGRESS · **Owner:** lead session · **Tested in:** CI

## Objective

A repository where agents can pick up any issue in a fresh session, with CI that checks the contracts.

## Scope

- `CLAUDE.md`, docs, decisions, phase specs, agent and skill definitions.
- Draft contracts in `contracts/` and tests that validate them.
- GitHub Actions running `ruff` and `pytest` on Ubuntu and Windows.
- Issue/PR templates and labels.

## Out of scope

Any audio, Ableton or Claude-API code.

## Acceptance criteria

- [ ] `pytest` and `ruff check .` pass locally.
- [ ] CI is green on `main` (Ubuntu + Windows).
- [ ] Labels and the Phase 01 and Phase 02 issues exist on GitHub.
- [ ] The user has cloned the repo on Windows and `pytest` passes there (user confirms in the Phase 00 issue).

## Handoff

Lead session updates `CURRENT_STATE.md` and marks this phase DONE.
