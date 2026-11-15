# Lead handoff (2026-11-15)

For the next **lead** session. Read this, then `CLAUDE.md`, the top block of `docs/CURRENT_STATE.md`, and `docs/DECISIONS.md` D-035 to D-037. Lead-owned file; replace it at the next handoff.

## Repo state

- `main` = the commit that carries this file (after 8d33e0e), CI timeout raised to 30 min (the Windows job needs about 18).
- **Open PR:** #576 (fit core kick/bass, #564). Reviewer: APPROVE-READY (round 1). Its Windows CI hit the old 20-minute limit. Next step: update the branch, wait for green CI on both OSes, squash-merge (the user ordered "merge alles" on 2026-11-15), then add one line to `docs/CURRENT_STATE.md`. Do not call kick `pitch_start_hz` / `pitch_decay_ms` recovered (#577).
- Latest Windows build: Build exe run 43729550861 on 8d33e0e (artifact `AbeltonGod-windows`). It contains the new Goa clips and preview. The cloud session cannot download artifacts.
- Merging: on 2026-11-10 the permission system refused the lead's merge; after the user's explicit "merge" on 2026-11-15 it worked. Without such a message, ask him.

## Waiting on the user (ask again only if he raises it)

1. **Goa in the exe** (checklist item 25 in `docs/USER_GUIDE.md`): does it sound like the listening pack of 2026-11-15 ("hört sich top an")? Does the window freeze annoy him (#575)? Clips in Live on his own synths?
2. Optional detail on the pack: favourite of A/B/C, variants 09-12 (major third, lead doubles the arp, 3+3+2 grouping, chord change), reverb, delay amount.
3. #556 noise on all samples: heard in Live or another player too? Does it stop when nothing plays?
4. Listening feedback on items 20-24; Acid preview status text if still silent; #484; choice-log B6.
5. A side-finding from the review of #567 is not filed (bass `sub_share` depends on the file length for notes near 100 Hz); the user was asked whether to file it and has not answered.

## Next work (lead decides; 1-3 agents)

- #576 merge (above), then #577 (fit follow-ups) before any GUI use of the fit (G1 of the reference note).
- Goa follow-ups: #575 (preview render off the GUI thread; re-check lead register 79-93; reverb only if the user asks), #574 (page texts, dead "Arp-Muster" field, later page controls for the new options).
- Side findings: #568 (kick `body_hz` seed jump), #569 (laser 0.1 rounding boundary), #537, #534, #527.
- Parking lot: #521, #519, #539.
- Scratch material in the lead's clone, untracked: `reports/`, `research_notes/` (the Goa research; the report is in the repo as `docs/research/2026-11-10_klassische-goa-leads-und-melodien.md`).

## User rules (binding)

- Talk to him in short, plain German.
- End every reply with his to-do list, or with "Für dich gibt es gerade nichts zu tun."
- Give a GitHub link with every issue or PR number.
- Decide yourself and document it; ask him only what only he can answer (his ears, his PC, his Live).
- Full merge rights, but only after an independent `reviewer` says APPROVE-READY and CI is green on Ubuntu and Windows.
- At most 2 review rounds per PR.
- Before every merge, the PR's CI base must contain all earlier merges, and main CI must be green (CLAUDE.md lesson #458/#461).
- Make no listening, taste or Live claims.
- Leave closing issues to the user.
- Never remove worktrees or delete remote branches: the classifier and the proxy deny both. Never merge without a review.

## How the lead worked (what proved efficient)

- **Agents.** Brief each agent with the issue, the file ownership for this issue (hand over files explicitly when needed), the targeted test command (`/usr/local/bin/python3 -m pytest -o pythonpath=src -n 1 --basetemp=.pytest_tmp_<name> …`; the container has 2 cores; for GUI tests set `QT_QPA_PLATFORM=offscreen`), uniquely named body files, and the trailer lines.
  - Reviewers get a focused list of what to check, and post via `jq … | gh api -X POST …/pulls/<n>/reviews`.
  - Round 2: resume the same reviewer with SendMessage.
- **Stacked PRs.** After squash-merging the base PR, the next PR conflicts. Resume its author to run `git merge origin/main` and keep main's versions. Watch for silent duplicate blocks; that happened once in `src/gui/audio.py`.
- **Drafts.** REST cannot un-draft a PR. Close it and re-open from the same branch (done for #549 → #561).
- **Merge queue.** Run this script in the background. It merges PRs one after another, each only when the PR CI and main CI are green and main has not moved:

```bash
#!/bin/bash
# usage: mergeq.sh <pr>...
R=repos/castorsalzmann-ui/abeltongod
w(){ for i in $(seq 1 150); do s=$(timeout 30 gh api "$R/actions/runs?head_sha=$1" --jq '[.workflow_runs[]|select(.name=="CI")][0] | "\(.status) \(.conclusion)"' 2>/dev/null); case "$s" in completed*) echo "$s"; return;; esac; sleep 20; done; echo timeout; }
for p in "$@"; do
  m=$(timeout 30 gh api $R/commits/main --jq .sha); a=$(w $m); echo "main ${m:0:7} CI: $a"
  case "$a" in *success*) ;; *) echo "stop: main not green"; exit 1;; esac
  hb=$(timeout 30 gh api $R/pulls/$p --jq .head.sha)
  if ! timeout 30 gh api "$R/compare/$m...$hb" --jq .behind_by | grep -qx 0; then
    timeout 60 gh api -X PUT $R/pulls/$p/update-branch --jq .message; sleep 20; fi
  h=$(timeout 30 gh api $R/pulls/$p --jq .head.sha); b=$(w $h); echo "PR$p ${h:0:7} CI: $b"
  m2=$(timeout 30 gh api $R/commits/main --jq .sha)
  case "$b" in *success*) [ "$m" = "$m2" ] && timeout 60 gh api -X PUT $R/pulls/$p/merge -f merge_method=squash --jq "\"merged $p \(.sha)\"" || { echo "stop: main moved"; exit 1; };; *) echo "stop: PR$p not green"; exit 1;; esac
  sleep 20
done
m=$(timeout 30 gh api $R/commits/main --jq .sha); echo "final main ${m:0:7} CI: $(w $m)"
```

- **Build exe.** Dispatch with `gh api -X POST $R/actions/workflows/408474385/dispatches -f ref=main` after main CI is green, then send the user the run link.
- **Screenshots for the user.** Run `QT_QPA_PLATFORM=offscreen /usr/local/bin/python3 scripts/qa/gui_tour.py --shots <scratch dir> --scale 1 --no-renders`, then send the PNGs with SendUserFile. Say that they are rendered on Linux.
