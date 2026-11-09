# Lead handoff (2026-11-09 evening)

For the next **lead** session. Read this, then `CLAUDE.md`, the top block of `docs/CURRENT_STATE.md`, and `docs/DECISIONS.md` D-032 to D-035. Lead-owned file; replace it at the next handoff.

## Repo state

- `main` = 42e9161 or later, CI green. **No open PRs.**
- Latest Windows build: Build exe run 42628586313 (artifact `AbeltonGod-windows`). The user downloads it from the Actions page; this cloud session cannot download artifacts (blob storage is blocked by the proxy).
- The user tested on his own PC for the first time on 2026-11-09. All his feedback from that test is merged (D-035). His checklist is `docs/USER_GUIDE.md`, items 20–24.

## Waiting on the user (ask again only if he raises it)

1. **#556, noise on all samples.** Engine files and the 16-bit preview copy measure clean. Only the default bass has about -80 dBFS above 4 kHz. Two questions to him are still unanswered:
   - Does he hear it in Live or another player too?
   - Does it stop when nothing is playing?
2. **Listening feedback** on items 20–24: Goa preview, volume, loop preview, Acid preview, Blaster tail. Also: is the riser build now too slow (start at -60 dB)?
3. If the Acid preview is still silent on his PC: the status line under the play buttons now shows the reason. Ask him for that text.
4. Old optional items: #484 (Live warp), choice-log B6. He may delete the branches `tmp/laser-dbg` and `tmp/screens-b64`.

## Next work (lead decides; 1–3 agents)

- **Reference steering v2, step E6, the fit** (note `docs/research/2026-11-08_reference-steering-v2.md` §4, §7, §10; slice 1 merged in #541).
  - Lead decision: feature scales come from the method error measured on degraded copies (resampling, 16-bit with dither, gain, DC, small trim), with the provisional scale only as a fallback. No floor at the provisional scale.
  - First categories: kick and bass.
- Side findings:
  - #554: blaster presets ion and pew-wide-echo cut their own echo.
  - #542: the exe does not bundle `calibration/reference_scales.json`. This is needed before the GUI uses v2.
  - #537: smoke-runner checks do not fit seamless atmos loops.
  - #534: the atmos contract text says MIDI 36 = C2; Live calls it C1.
  - #527: flaky live-import test.
- Parking lot: #521 (planner takes over the Goa form options), #519 (copilot reads the Live tempo), #539 (copilot cap on atmos render time).
- Nits:
  - The Acid status line keeps saying "Spielt: …" after Stop.
  - The main-window nav entry still says "Goa-Melodie"; it could become "Goa-Clips".
  - The launcher has no `goa-clips` entry.

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
