# AbeltonGod — Agent Instructions

AI music production copilot for **Ableton Live 12 Standard on Windows** (Techno/Trance focus).
First goal: generate, refine and import a **kick** sample. Everything else comes later.

Keep this file short. It is loaded into every session; details live in the files below.

## Source of truth (read only what your task needs)

| File | What it holds |
| --- | --- |
| `docs/CURRENT_STATE.md` | What works, what is open, what is next. **Read at the start of every task.** |
| `docs/DECISIONS.md` | Binding architecture decisions. Do not contradict them; propose a new decision instead. |
| `docs/phases/PHASE_XX_*.md` | Scope, out-of-scope, deliverables and acceptance criteria per phase. |
| `docs/INTERFACES.md` + `contracts/` | Shared formats between modules. Never invent a parallel format. |
| `contracts/capabilities.json` | Which Ableton functions are `tested`, `supported`, `unknown` or `unsupported`. |
| `docs/ARCHITECTURE.md` | Layers and data flow. |
| `docs/PRODUCT_SPEC.md` | Full product vision (long, German). Read only when a task needs product context. |
| `docs/research/` | Dated research notes with sources. Check here before researching again. |
| `docs/research/2026-10-28_kick-gen2-learnings.md` | **Read once before any kick-engine work** (Phase 01 onward): lessons, measured taste range, market candidates, analysis pitfalls, rules. |

GitHub Issues are work assignments. Pull Requests carry the evidence and the review.

## Hard constraints

- **No Max for Live.** The user has Live 12 *Standard*. The Ableton bridge is a Python Remote Script based on AbletonOSC.
- **Claude decides, local code executes.** No AI call ever sits in a real-time audio path.
- **Capability rule.** Only build tools/actions on Ableton functions with status `tested` in `contracts/capabilities.json`. Anything else stays behind a clear "not yet verified" path.
- **Test boundary.** CI (GitHub Actions) has no Ableton. Anything touching Live is tested on the user's Windows machine. Never report a mock or CI run as an Ableton integration test.
- **Technical honesty.** Never claim something is implemented, tested or compatible without evidence. Never invent test results or listening impressions.
- **Deterministic DSP first.** No generative audio model in the MVP. Same parameters + same seed must give byte-identical output.
- Secrets (API keys, tokens) never go into the repo. Use `.env` (git-ignored); document variables in `.env.example`.
- New dependency → say why in the PR before adding it. No vague quality claims ("robust", "production-ready") — state the exact boundary of what was verified.

## Before you start any task

Have all four, from the issue and phase spec: **What** will exist afterwards · **Why** (one sentence) · **Scope boundary** (what is not part of it) · **Done when** (checkable criteria). If one is missing or unclear, ask once, briefly. Do not invent it.

## Requests that are not in the issue

Classify before acting and say which class it is:

- **A — fits the issue:** do it, mention it in the PR.
- **B — valid but outside the issue:** ask whether to open a new issue or change scope. Do not implement yet.
- **C — contradicts a decision in `DECISIONS.md`:** quote the decision; it has to be reopened by the user first.
- **D — new idea:** open an issue labelled `parking-lot` so it is not lost, then continue.

Things you notice that are wrong or risky but outside scope are **side findings**: open an issue labelled `side-finding`. Never fix them silently.

## Gate

`ruff check . && pytest` — must be green before any PR, any "done", any state update. Never weaken a test or a "Done when" criterion to make it pass; fix the cause.

## Testing and debugging rules (learned in PR #8, five review rounds)

- **Test the whole input range, not favourite cases.** Add seeded random property tests over the full contract range next to curated cases. A test that only passes for one seed or one value is not evidence.
- **Prove a test can fail.** For each important check, inject a fault (e.g. scale a parameter by 1.02) and confirm the test turns red. Report the mutation results in the PR.
- **Keep the reference independent.** Do not compare the code against a formula or helper taken from the same code. Write the expected value in the test, or measure it with a different method.
- **Find the cause before changing a limit.** On a deviation, isolate it (switch parts off one by one) before touching a tolerance, adding a skip or an `xfail`. One root cause often explains several symptoms.
- **Never state an unproven cause.** Say "cause not established" until an experiment shows it. Retract wrong explanations openly in the PR.
- **Re-check what your fix touched.** A fix is new code: test its failure paths too (disk full, interrupts, edge values).
- **Count and quote real output.** Test counts, error sizes and seeds come from a command you ran, not from memory.
- **Independent review before merge.** Every PR gets a `reviewer` run started by the lead (implementers cannot start agents, D-017). For foundation code (engine, analysis, file writing, anything that writes to Ableton) the review is full-depth; small doc or text changes get a short one.

## Bugs

- Filed with the **Bug** issue form (`bug` label + one `severity:blocker|major|minor|nit`). A bug without a runnable repro goes back to the reporter.
- **A fix starts with a failing regression case:** `tests/regressions/bug_<issue>[_<slug>].json` (format in `tests/regressions/test_regressions.py`). Show it red before the fix, green after; `before_fix` must record the bad value.
- **Ableton bug:** set the affected capability in `contracts/capabilities.json` back to `supported` (D-004, own `contract-change` PR) until it is re-tested on the user's machine. CI cannot reproduce it; the evidence is the user's log.
- **Escaped bug** (found after merge): add one lesson line under "Testing and debugging rules" — what let it through, what catches it now.

## Budget (development sessions)

The user's Max usage is shared by every session. Use it generously where it buys precision or speed; spend nothing on calls that cannot change the result.

- **Waste** = a call whose outcome is already known: re-running the same command without a change, retrying a failure without a new idea, editing one file back and forth, re-reading what is already in context, spawning a subagent for a lookup you can do directly.
- **Proportionate rigour.** Full property tests and fault injection for foundation code (engine, analysis, file writing, guard, anything writing to Ableton). For docs, config and small scripts: targeted tests, no mutation campaign.
- **At most two `reviewer` rounds per PR.** A third needs the user's yes.
- **On a budget warning** (from `.claude/hooks/waste_watch.py`, limits in `config/dev-budget.json`): stop, write two lines — what happened and why — then change approach or ask the user. Do not continue the same pattern. Mention it in the PR's budget check.
- **Revision loop.** `/finish-task` puts the branch's warnings in the PR. `/close-phase` reviews all new warnings; a kind marked RECURRING gets a one-line lesson below or a `process` issue.

### Budget lessons

Add one line per recurring waste pattern: pattern → what to do instead.

- Command whose exit code matters piped through `| tail` → `set -o pipefail` or no pipe (a 403 push looked successful; #19).
- Files changed with Bash scripts (`python - <<EOF`, `sed -i`) → use Edit/Write; Bash edits are invisible to the budget watch and harder to review (#19).
- Fault injection that removes a check → first check whether the same protection also exists higher up; otherwise the mutant survives for the wrong reason (a redundant inner lock cost three runs; #19).
- PR branch behind `main` → `git merge origin/main` into the branch and push normally; rebase + force-push is blocked in cloud sessions. Check `mergeable_state` right after opening a PR: a conflicted PR gets no CI run (#28).

## Workflow

1. The lead assigns an issue to a role; the agent runs `/start-task <issue-number>` in its own worktree.
2. Work on a branch `phase-XX/<short-name>` based on the newest `origin/main`.
3. Implement only the issue's scope. Stop and comment on the issue if scope or a contract must change.
4. Run `pytest` and `ruff check .`; report the real output.
5. Finish with `/finish-task` → opens a PR with `Closes #<n>`.
6. The lead runs the `qa-tester` pre-check and an independent `reviewer`, then gives the user the merge go-ahead.

## Who writes what

- `docs/CURRENT_STATE.md` and `docs/DECISIONS.md`: **only the lead session on `main` after a merge.** Implementers put a "State update proposal" in their PR body instead, to avoid merge conflicts.
- `contracts/`: changes need their own PR, labelled `contract-change`, reviewed before dependent work continues.

**File ownership (D-017).** Every file has exactly one owner at a time. Default owners:

| Path | Owner |
| --- | --- |
| `src/audio_engine/`, `src/library/`, `tests/audio_engine/`, `tests/library/`, `tests/fixtures/sidecars/` | `audio-engineer` |
| `src/bridge/`, `scripts/` (except `scripts/qa/`), `docs/setup/`, `tests/bridge/` | `bridge-engineer` |
| `src/orchestrator/`, `src/guard/`, `config/guard-policy.json`, their tests | `orchestrator-engineer` |
| `scripts/qa/`, `tests/conftest.py`, `tests/dev_tools/`, `tests/support/`, `tests/qa/`, `tests/regressions/test_regressions.py` | `qa-tester` |
| `docs/research/<date>_<topic>.md` | the role that wrote the note (others add a new dated note that links it) |
| `contracts/` | the role named in the `contract-change` issue (kick-params / sample-metadata → audio-engineer, capabilities → bridge-engineer, guard-policy schema → orchestrator-engineer) |
| `pyproject.toml` | the role whose issue needs the change (reason in the PR) |
| `CLAUDE.md`, `.claude/`, `.github/`, `docs/` outside `research/` and `setup/`, `config/dev-budget.json` | lead |

An issue may hand a file to another role for that issue only (e.g. a qa-tester issue that changes `tests/bridge/fake_abletonosc.py`); the issue says so, and the default owner has no open work on that file.
- `contracts/capabilities.json`: a status may only become `tested` with evidence from the user's machine (log excerpt or user confirmation in the issue).

## Agents

Flat team (D-017): the lead assigns specialised agents directly; **no agent starts helpers or sub-agents**. At most 10 active at once, only what the current phase needs. Each agent works in its own git worktree and writes only to its own files; anything else becomes an issue for the owning role. Definitions in `.claude/agents/`.

- `audio-engineer` — kick engine, DSP, presets, variants, analysis, WAV/sidecars (`src/audio_engine/`, `src/library/`).
- `bridge-engineer` — AbletonOSC, capability registry, import into Live (`src/bridge/`, `scripts/` except `scripts/qa/`, `docs/setup/`).
- `orchestrator-engineer` — Claude copilot, tool definitions, approval levels, guard wiring (`src/orchestrator/`, `src/guard/`; from Phase 04b).
- `reviewer` — independent review of every PR; writes only review comments and finding issues. Never reviews its own work.
- `qa-tester` — less check time, same depth: runtime analysis, targeted test selection, reusable check tools, pre-check before every review (`tests/` infrastructure, `scripts/qa/`).
- `sound-designer` — user feedback → measurable hypotheses and parameter proposals, reference analysis, listening-test plans (issue comments, `docs/research/`; no code, no listening claims).
- `researcher` — dated, sourced feasibility and programmability notes (`docs/research/`). Two instances work ahead on the parking lot (D-018): A sound and audio, B integration and product. **Before designing a parking-lot feature, read its `docs/research/*_parking-*.md` note.**

Worktree agents run tests as `python -m pytest -o pythonpath=src` (the editable install points at the main clone).

## Commands

```
pip install -e ".[dev]"   # setup (inside a venv)
pytest                     # all automated tests, in parallel on all cores (pytest-xdist)
pytest -n 0                # serially: for debugging, pdb or reading print output
ruff check .               # lint
```

**GitHub access:** in cloud sessions GitHub GraphQL is blocked, so `gh issue view`, `gh pr view/diff/create/review` and `gh label list` fail. Use the REST API everywhere (works locally too); R = `repos/castorsalzmann-ui/abeltongod`:

```
gh api $R/issues/<n> --jq .body                      # read issue
gh api $R/issues/<n>/comments --jq '.[].body'         # issue/PR comments
gh api -X POST $R/issues/<n>/comments -f body="..."   # comment
gh api -X POST $R/issues/<n>/labels -f 'labels[]=status:in-progress'
gh api -X DELETE $R/issues/<n>/labels/status:ready
git diff main...<branch>                              # PR diff (local)
jq -n --rawfile b body.md --arg t "title" --arg h "<branch>" \
  '{title:$t, head:$h, base:"main", body:$b}' | gh api -X POST $R/pulls --input -   # open PR
jq -n --rawfile b review.md '{event:"COMMENT", body:$b}' | gh api -X POST $R/pulls/<n>/reviews --input -
gh api "$R/actions/runs?head_sha=<sha>" --jq '.workflow_runs[0] | "\(.status) \(.conclusion)"'  # CI
```

Issue numbers are shared with PRs: read the returned `number` before referencing a new issue.

## Language

Code, comments, commits and agent docs: English. Talk to the user in German unless they write in English.
