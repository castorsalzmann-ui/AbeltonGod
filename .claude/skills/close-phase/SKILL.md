---
name: close-phase
description: Lead session only - after a PR is merged, apply its state update to CURRENT_STATE.md and DECISIONS.md on main. Use as /close-phase <pr-number>.
---

1. `git switch main && git pull`.
2. `gh pr view $ARGUMENTS` — read the "State update proposal" and the review verdict.
3. Update `docs/CURRENT_STATE.md` (date, phase status, "What works" with evidence links, next step). Keep it short; remove stale lines.
4. If the PR introduced a binding choice, append a new decision to `docs/DECISIONS.md`.
5. If a phase is complete, set its spec's Status to DONE and open the next phase's issues if they do not exist.
6. Commit `state: apply #$ARGUMENTS` and push to `main`.
7. Tell the user in German what changed and what is next.
