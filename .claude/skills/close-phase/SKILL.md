---
name: close-phase
description: Lead session only - after a PR is merged, apply its state update to CURRENT_STATE.md and DECISIONS.md on main. Use as /close-phase <pr-number>.
---

1. `git switch main && git pull`.
2. `gh api $R/pulls/$ARGUMENTS --jq .body` plus its comments and reviews (`$R/issues/$ARGUMENTS/comments`, `$R/pulls/$ARGUMENTS/reviews`) — read the "State update proposal" and the review verdict.
3. Update `docs/CURRENT_STATE.md` (date, phase status, "What works" with evidence links, next step). Keep it short; remove stale lines.
4. If the PR introduced a binding choice, append a new decision to `docs/DECISIONS.md`.
5. If a phase is complete, set its spec's Status to DONE and open the next phase's issues if they do not exist.
5a. Budget revision: run `python scripts/dev_budget_report.py` and read the PR's "Budget check". For every kind marked RECURRING, or any avoidable waste the PR names, add one line under "Budget lessons" in `CLAUDE.md` (pattern → what to do instead), or sharpen an existing line. If the fix needs code or a limit change in `config/dev-budget.json`, open an issue labelled `process` instead. Then run it again with `--mark-reviewed`.
6. Commit `state: apply #$ARGUMENTS` and push to `main`.
7. Tell the user in German what changed and what is next, including the budget result in one line (no warnings / which lesson was added).
