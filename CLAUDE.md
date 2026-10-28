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
- **Review once, before the PR.** For foundation code (engine, analysis, file writing, anything that writes to Ableton) run the `reviewer` agent on the branch before opening the PR. Small doc or text changes do not need it.

## Workflow

1. Start a fresh session per issue: run `/start-task <issue-number>`.
2. Work on a branch `phase-XX/<short-name>` (or a worktree for parallel work).
3. Implement only the issue's scope. Stop and comment on the issue if scope or a contract must change.
4. Run `pytest` and `ruff check .`; report the real output.
5. Finish with `/finish-task` → opens a PR with `Closes #<n>`.
6. The `reviewer` subagent reviews before the user merges.

## Who writes what

- `docs/CURRENT_STATE.md` and `docs/DECISIONS.md`: **only the lead session on `main` after a merge.** Implementers put a "State update proposal" in their PR body instead, to avoid merge conflicts.
- `contracts/`: changes need their own PR, labelled `contract-change`, reviewed before dependent work continues.
- `contracts/capabilities.json`: a status may only become `tested` with evidence from the user's machine (log excerpt or user confirmation in the issue).

## Agents

Use few agents. Default: this main session plus, when useful, one implementer and the reviewer.

- `audio-engineer` — DSP, kick synthesis, audio analysis, WAV/metadata output.
- `bridge-engineer` — AbletonOSC remote script, OSC client, capability checks, sample import.
- `reviewer` — independent review against the phase acceptance criteria. Never reviews its own code.

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
