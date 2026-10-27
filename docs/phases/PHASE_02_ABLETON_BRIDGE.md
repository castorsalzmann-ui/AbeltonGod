# PHASE 02 — Ableton bridge (AbletonOSC, Live 12 Standard)

**Status:** PLANNED · **Agent:** `bridge-engineer` · **Tested in:** user's Windows machine (+ CI with a fake OSC server)

## Objective

A verified, documented path to read from and write to the user's Live set, with undo, and a filled capability registry.

## Prerequisites

Phase 00 done. User has noted their exact Live version (Help → About Live) and which control-surface slots are in use.

## Scope

1. Installation guide for AbletonOSC on Windows (`docs/setup/ABLETONOSC_WINDOWS.md`): download, folder, Control Surface selection, how to see the log.
2. `src/bridge/osc_client.py`: request/response over UDP localhost with timeouts and clear errors when Live or the script is not running.
3. `src/bridge/capabilities.py`: load `contracts/capabilities.json`; refuse calls to capabilities that are not `tested` (configurable for test scripts).
4. `scripts/bridge_check.py`: a manual check script the user runs. It prints Live version, tempo, time signature, track names, then (after a y/N prompt) mutes and unmutes a track, then calls undo, and prints a result block to paste into the issue.
5. AbletonOSC's README does not list `ClipSlot.create_audio_clip`. Confirm in the AbletonOSC source, then design (do not yet build) the smallest extension handler for Phase 03. Record findings in `docs/research/`.
6. CI: a fake OSC server fixture so the client logic is tested without Live.

## Out of scope

Sample import (Phase 03), Claude, arrangement changes, anything destructive (delete track/clip), modifying the user's real projects beyond the test set.

## Safety

The check script must only run against a project the user created for testing. It prints what it will change and asks first.

## Acceptance criteria

- [ ] CI tests for the OSC client pass (fake server).
- [ ] User ran `bridge_check.py` against a test set; output pasted in the issue.
- [ ] Capabilities touched by the check are set to `tested` (with the issue link as evidence) or `unsupported`.
- [ ] Behaviour with Live closed / script not selected produces an understandable error (user-verified).

## Handoff

PR body: real output from the user's run, capability changes, open risks, State update proposal.
