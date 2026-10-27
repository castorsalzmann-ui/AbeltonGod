---
name: finish-task
description: Finish the current issue - run checks, commit, push and open a pull request with real evidence. Use as /finish-task.
---

1. Run `ruff check .` and `pytest`. Save the real summary lines. If anything fails, fix it or stop and report; never open a PR that claims green when it is not.
2. `git status` — make sure no secrets, generated WAVs or large binaries are staged (they belong in `.gitignore`d folders).
3. Commit with a clear message (`phase-XX: <what>`), push the branch.
4. Open the PR with `gh pr create --title "<phase-XX: what>" --body-file <file>` using `.github/PULL_REQUEST_TEMPLATE.md`. Fill every section with facts. Include `Closes #<issue>`.
5. Mark local/Ableton/listening checks the user still has to do as unchecked boxes under "Needs user test".
6. Swap the issue label `status:in-progress` → `status:in-review`.
7. Tell the user in German: PR link, what is verified, what they must test, and suggest running the `reviewer` agent.

Do not edit `docs/CURRENT_STATE.md` or `docs/DECISIONS.md` — put a "State update proposal" in the PR body.
