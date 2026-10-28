# PHASE 00 — Repository & workflow setup

**Status:** DONE (2026-10-28) · **Owner:** lead session · **Tested in:** CI

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

- [x] `pytest` and `ruff check .` pass locally.
- [x] CI is green on `main` (Ubuntu + Windows).
- [x] Labels and the Phase 01 and Phase 02 issues exist on GitHub.
- [x] The user has cloned the repo on Windows and `pytest` passes there (user confirms in the Phase 00 issue). Evidence: [#1 comment](https://github.com/castorsalzmann-ui/AbeltonGod/issues/1#issuecomment-6467168168), Windows, Python 3.14.4: `899 passed, 2 skipped`.

## Handoff

Lead session updates `CURRENT_STATE.md` and marks this phase DONE.
