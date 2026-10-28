---
name: start-task
description: Start work on a GitHub issue in a fresh session. Use as /start-task <issue-number>.
---

Start work on issue `$ARGUMENTS`.

1. Run `git switch main && git pull` (stop and tell the user if the tree is dirty).
2. Read `docs/CURRENT_STATE.md`.
3. Read the issue and its comments via REST (see `CLAUDE.md` → GitHub access): `gh api $R/issues/$ARGUMENTS --jq .body` and `gh api $R/issues/$ARGUMENTS/comments --jq '.[].body'`. Identify the phase and the agent label.
4. Read the linked phase spec in `docs/phases/` and only the contracts it names.
5. If the issue is labelled `status:blocked`, or its dependencies are not met per CURRENT_STATE, stop and tell the user why.
6. Create the branch: `git switch -c phase-XX/<short-name>` (XX = phase number from the issue).
7. Comment on the issue (`gh api -X POST $R/issues/$ARGUMENTS/comments -f body="Started on branch <branch>."`) and swap the label `status:ready` → `status:in-progress`.
8. Reply to the user in German with: goal in one sentence, your plan in 3–6 steps, anything they must do on their machine, and which agent you will delegate to (if any). Then begin.

Keep the context small: do not read `docs/PRODUCT_SPEC.md` unless the issue needs product context.
