# Current State

_Last updated: 2026-10-28 (evening) · Written only by the lead session on `main` after a merge._

## Phase

- **Phase 00 — Setup:** DONE (#1 closed 2026-10-28).
- **Phase 03 — Sample import:** starting (#50).
- **Phase 01 — Kick engine:** core merged (#2 via PR #8); drive anti-aliased (#13 via PR #20); contract semantics (#7 via PR #28). WAV/sidecar nits (#12 via PRs #26, #33); tone/drive/envelope tests (#11 via PR #34). Drive continuous from 0 (#16 via PR #38); ENGINE_VERSION rule (#35 via PR #40, D-013). Analysis limits #27, #32 documented (PR #49); crest-factor mechanisms #30, #31 documented (PR #51). Presets, variants, CLI (#3 via PRs #54, #56); user listening test done; `centre` pitch decay 40 ms (#59 via PR #60). **DONE 2026-10-28.**
- **Phase 02 — Ableton bridge:** DONE (#5 via PR #42, 2026-10-28). Seven capabilities `tested` on Live 12.4.5. Open follow-up: PR #48 (setup-guide fixes, #43).
- **Phase 04a — Agent Resource Guard:** DONE (#6 via PR #15).

## What works (with evidence)

| Item | Evidence |
| --- | --- |
| Repo scaffold, contracts, contract tests | [CI run 40604382687](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/40604382687); user's Windows machine (Python 3.14.4): `ruff` clean, `899 passed, 2 skipped` ([#1](https://github.com/castorsalzmann-ui/AbeltonGod/issues/1#issuecomment-6467168168)) |
| Deterministic kick engine core: `render_kick`, `analyse`, `write_kick`, `rerender_from_sidecar` (`src/audio_engine/`) | [PR #8](https://github.com/castorsalzmann-ui/AbeltonGod/pull/8), merged as 7316f85 after six independent review rounds; `899 passed, 2 skipped`; [CI run 40666798325](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/40666798325) ubuntu + windows. ffmpeg decodes the WAVs bit-identically (round-6 review). |
| Agent Resource Guard (`src/guard/`): policy, per-request limits, session/daily budget rebuilt from `logs/guard-usage.jsonl`, loop detection, timeout, sticky stop that can never report success | [PR #15](https://github.com/castorsalzmann-ui/AbeltonGod/pull/15), merged as 90e4a7e after one review round (8 findings fixed); 1008 passed; 28/29 fault injections caught; [CI run 40678523757](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/40678523757) ubuntu + windows |
| Drive anti-aliasing: tanh at 8× oversampling (Kaiser low-pass, frequency-domain resampling, spectrum cache) | [PR #20](https://github.com/castorsalzmann-ui/AbeltonGod/pull/20), merged as b0d2014 after one pre-PR review round (2 medium findings fixed). Aliasing ≤ 20 kHz vs. an ideal band-limited reference: worst −79 dB RMS rel. peak (was −41 dB); 12 fault injections all caught; [CI run 40684108652](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/40684108652) ubuntu + windows |
| Tests run in parallel (pytest-xdist, `-n auto`, fixed temp folder `.pytest_tmp`); `pytest -n 0` runs serially | [PR #22](https://github.com/castorsalzmann-ui/AbeltonGod/pull/22), merged as c6ddf9b; user's Windows PC: 12 workers, `1008 passed, 2 skipped in 6.41s` ([#21](https://github.com/castorsalzmann-ui/AbeltonGod/issues/21#issuecomment-6468776786)) |
| Kick Gen 2 research note (prototype lessons, taste range from 77 reference kicks, market candidates, analysis pitfalls, agent rules) | [PR #10](https://github.com/castorsalzmann-ui/AbeltonGod/pull/10), merged as 2c13642: `docs/research/2026-10-28_kick-gen2-learnings.md`, required reading for kick-engine work |
| Budget watch for development sessions (`.claude/hooks/waste_watch.py`, warn only) | [PR #18](https://github.com/castorsalzmann-ui/AbeltonGod/pull/18), merged as 00485b1 after one review round (3 findings fixed); CI ubuntu + windows. Windows user test still open. |
| Bug workflow: issue form "Bug" (required repro), labels `severity:blocker/major/minor/nit`, regression corpus `tests/regressions/` (1 case from PR #8 review 1), "Bugs" rules in `CLAUDE.md` | [PR #24](https://github.com/castorsalzmann-ui/AbeltonGod/pull/24), merged as 9b0b5a9 after one review round (3 minor fixed); `1132 passed, 2 skipped`; [CI run 40691016877](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/40691016877) ubuntu + windows. User check of the form on GitHub open. |
| AbletonOSC Windows guide (`docs/setup/ABLETONOSC_WINDOWS.md`), OSC client with nonce-marker bracketing per request, capability gate (`src/bridge/`), fake AbletonOSC server for CI | [PR #25](https://github.com/castorsalzmann-ui/AbeltonGod/pull/25), merged as ddef95a after three review rounds (7, 3, then no findings); 28/28 fault injections caught; merged tree `1252 passed, 2 skipped`; bridge tests 10/10 green under CPU load; CI on 1ff93e4 ubuntu + windows. **Not yet run against Live.** No capability status changed. |
| kick-params **v0.2**: written envelope semantics (`pitch_decay_ms` = time constant τ, `amp_decay_ms` = time to −60 dB), default `pitch_decay_ms` 40 → 15; pitch-settle guideline `max_settled_pitch_decay_ms` / `pitch_settles` for presets and Claude; silent renders refused; v0.1 sidecars still re-render | [PR #28](https://github.com/castorsalzmann-ui/AbeltonGod/pull/28), merged as fd7ae72 after one pre-PR review round (5 findings fixed); 17/17 fault injections caught; `1377 passed, 2 skipped`; CI on d4507a4 ubuntu + windows green |
| WAV/sidecar robustness (#12): RIFF pad byte for odd 24-bit data chunks, dangling symlinks count as taken names, `created_at` must be aware (whole-minute offset), Decimal/Fraction/complex rejected | [PR #26](https://github.com/castorsalzmann-ui/AbeltonGod/pull/26), merged as 816b042 **without review and with an empty PR template**; [post-merge review](https://github.com/castorsalzmann-ui/AbeltonGod/pull/26#pullrequestreview-5683501845): code sound, 276 WAV cases checked with stdlib `wave` and ffmpeg, 17/18 fault injections caught; CI on c9b3a1d ubuntu + windows. Follow-ups: test gap closed by PR #33; engine version → #35; format-tag question moved to #3. |
| #12 follow-up: `KickParamsError` lists type errors together with all other problems; stricter "nothing written" tests (incl. missing nested `out_dir`) | [PR #33](https://github.com/castorsalzmann-ui/AbeltonGod/pull/33), merged as 69a5890 after one pre-PR review round; `1379 passed, 2 skipped`; 4/4 new mutants caught (incl. the post-merge review's survivor); CI on d7f7df9 ubuntu + windows |
| `scripts/bridge_check.py` 0.3.0: reads version/tempo/signature/tracks; after two default-No prompts mutes, unmutes, re-mutes a test track, calls Live undo and compares a whole-set snapshot (tempo, signature, track count/names/order, all mutes) before/after; Ctrl+C and write errors abort with a result block | PRs [#37](https://github.com/castorsalzmann-ui/AbeltonGod/pull/37) (merged as bc3809e **before its review finished**; review found a false undo PASS → #39), [#41](https://github.com/castorsalzmann-ui/AbeltonGod/pull/41) (ded4876, 1 re-review round), [#45](https://github.com/castorsalzmann-ui/AbeltonGod/pull/45) (bbce65e, approve-ready review); `1791 passed, 2 skipped`, 278 bridge+regression tests; CI ubuntu + windows. **User run in Live 12.4.5 with script 0.1.0** (pre-#41): all PASS, set restored ([#5](https://github.com/castorsalzmann-ui/AbeltonGod/issues/5#issuecomment-6474540867)); error cases Live closed / script not selected (exit 2) and port busy shown and understood ([#5](https://github.com/castorsalzmann-ui/AbeltonGod/issues/5#issuecomment-6474653513)). User decision: accept the 0.1.0 undo result with a documented limitation (PR #42). |
| Drive continuous from 0 (#16, user decision): gain `10·drive^0.8`, shaper `tanh(gx)/tanh(g)` applied as residual through the 8× oversampler, Taylor fallback below g = 0.01. drive 1e-6 differs from drive 0 by −161 dB (was −12 dB); drive ≥ 0.2 keeps gain within 4.5 % of before | [PR #38](https://github.com/castorsalzmann-ui/AbeltonGod/pull/38), merged as 04f264c after one independent review (approve-ready; reviewer reproduced continuity on 26 fresh sets, −159.5 dB at 1e-6, aliasing −78 dB worst on 24 new cases); 12/12 fault injections caught; `1797 passed, 2 skipped`; CI ubuntu + windows |
| ENGINE_VERSION rule (#35, D-013): `ENGINE_VERSION` 0.1.0; 5 literal golden SHA-256s (48k/24-bit odd, even, drive 0.6; 44.1k/16-bit tone 0.7 + click; 44.1k/24-bit tone −0.7 + attack), hard failure on Linux **and Windows**; coverage-guard test; `rerender_from_sidecar` raises `EngineVersionMismatch` unless `allow_engine_mismatch=True`; PR-template checkbox | [PR #40](https://github.com/castorsalzmann-ui/AbeltonGod/pull/40) (`contract-change`), merged as c10020f after two review rounds (1 major: tone path uncovered → fixed); `1821 passed, 2 skipped`; Windows CI matched all 5 hashes ([run 40731270024](https://github.com/castorsalzmann-ui/AbeltonGod/actions/runs/40731270024)) |
| Capability registry filled from the user's Live run: `app.version`, `song.tempo.get`, `song.signature.get`, `song.track_names.get`, `track.mute.set`, `track.mute.get`, `song.undo` = `tested` (`live_version_tested` 12.4.5); `song.undo` notes carry the user-accepted limitation of script 0.1.0; `track.mute.get` has its own gate; contract tests pin the version and the limitation | [PR #42](https://github.com/castorsalzmann-ui/AbeltonGod/pull/42) (`contract-change`), merged as 43df818 after one review round (1 minor fixed); `1949 passed, 2 skipped`; CI ubuntu + windows. Evidence: [#5](https://github.com/castorsalzmann-ui/AbeltonGod/issues/5#issuecomment-6474540867) |
| Budget watch counts reviewer runs (word match `\breview`) and `PermissionDenied` events; `.claude/settings.json` pinned by a test (only the hook block allowed) | [PR #46](https://github.com/castorsalzmann-ui/AbeltonGod/pull/46), merged as 8111731 after one review round (2 minor fixed); 12/12 mutants caught; CI ubuntu + windows. User test open (Windows auto mode: warning after 4 denials, no "hook error"). |
| Research note: Claude auth options for Phase 04b (fact-checked against official sources) | [PR #47](https://github.com/castorsalzmann-ui/AbeltonGod/pull/47), merged as 3f8edb0; decision D-014 |
| Analysis limits documented: `fundamental_hz` on kicks with `amp_decay_ms` < ~110 ms (#27, DC-blocker tail + mean correction); `decay_20db_ms` offsets and drive effect (#32) | [PR #49](https://github.com/castorsalzmann-ui/AbeltonGod/pull/49), merged as 844ff46; comments only, golden hashes unchanged; triage comments on #27 and #32 |
| Preset `centre` `pitch_decay_ms` 8 → 40 (user's ear, #59 option c): schema default stays 15 ms; centre and all its variants follow the pitch-settle guideline (reviewer: 4000 variants on fresh seeds, worst +4.9997 % vs. 5 % limit); no `ENGINE_VERSION` bump (engine unchanged, golden cases use no preset; old sidecars re-render byte-identically) | [PR #60](https://github.com/castorsalzmann-ui/AbeltonGod/pull/60), merged as 94ea1a4 after one independent review (approve-ready, 3 nits; nit 1 → #63); `2089 passed, 2 skipped`; CI on 537df14 ubuntu + windows green. Note: the #3 listening files `centre_s1001_v*` were rendered with 8 ms and differ from today's `--preset centre`. |
| Independent tests for tone, drive and the amplitude envelope (#11), 282 tests | [PR #34](https://github.com/castorsalzmann-ui/AbeltonGod/pull/34), merged as eb14b8d after one pre-PR review round (3 findings fixed); `1659 passed, 2 skipped`; 11 fault injections, all caught (drive × 0.5 by only 2 tests); CI on `main` eb14b8d green |

**Known limits of the bridge** (details in `docs/research/2026-10-28_abletonosc-protocol-and-create-audio-clip.md`):
- A timed-out write has an unknown outcome and may still be applied later; read back before any undo (rule for #5).
- The marker echo the bracketing relies on is confirmed in Live 12.4.5 (`bridge.marker_echo: PASS`, #5).
- The undo check cannot see clips, devices, automation, return/master tracks. Reopening a set clears Live's undo history per the Live 12 manual; not yet verified in this project. Tempo drift (Link, automation) gives a false FAIL (#43).

**Measured limits of the kick core** (details in PR #8):
- Pitch accuracy: ±3 % for windows ≥ 80 ms, ±5 % below (user decision).
- About 10 % of very short, fast-decay kicks report `fundamental_hz: None`.
- Byte identity Linux vs. Windows is proven for the 5 golden cases on CI (Python 3.12); the user's Python 3.14 on Windows is not yet checked.
- Render with `drive > 0` costs ~3× more than before anti-aliasing (2 s kick ≈ 54 ms on the CI-like Linux box); every WAV with `drive > 0` differs from pre-#20 renders.
- Sidecars from engine 0.0.1 (all written before #35) no longer re-render without `allow_engine_mismatch=True`; they are not migrated.
- No crest-factor test covers click + tone > 0 (cause of the excess not established, #31). The 10 Hz DC blocker skews attack fits on the shipped output by up to 1.7 ms (PR #34) and raises the crest factor at high drive (#30).
- The pitch-settle guideline describes the pitch curve. The measured `fundamental_hz` can still be up to ~17 % above `pitch_end_hz` for kicks that follow it (review of #7).
- `fundamental_hz` is approximate (±5 %) or `None` for very short kicks; never derive `amp_decay_ms` as 3 × `decay_20db_ms` (with drive up to +87 %). Causes in PR #49.

**Known limits of the guard** (details in `docs/research/2026-10-28_guard-sdk-mapping.md`):
- One copilot process at a time: calls in flight in another process are invisible to the daily budget.
- The guard cannot interrupt a running model call; it stops at the next guard step.
- SDK stop behaviour for `max_turns` / `max_budget_usd` is not verified yet (Phase 04b).

## What does not exist yet

- Sample import into Live (Phase 03)
- Claude orchestrator / chat (Phase 04b)

## Environment facts (from the user, 2026-10-28)

| Fact | Value |
| --- | --- |
| OS | Windows |
| Local Python | 3.14.4 (CI uses 3.12) |
| Ableton | Live 12 **Standard** 12.4.5 (Build 2026-08-19_225ce5e356), no Max for Live, always updated to the latest release |
| Project sample rate | 48 kHz (engine default 48 kHz / 24-bit) |
| GPU | NVIDIA RTX 5070 |
| Claude access | Max **5x** subscription; product auth = subscription login, default model Opus 5.5 (D-014) |
| First sample type | Kick |
| Languages | German and English |
| Control surfaces / controllers in use | AbletonOSC in slot 1 (since 2026-10-28). An AbletonMCP server is installed on the PC; whether its remote script uses a slot is not known. |
| Reference tracks / artists | 77 reference kick files measured (taste range, not a target): see `docs/research/2026-10-28_kick-gen2-learnings.md`. Full reference tracks still open. |
| Genre | Not relevant for now. Later the user wants **both** genre-specific and free synthesis by values: one shared parameter space, genre profiles only as optional data on top. Deliberately **not** a decision. Only audio content of references counts, never names. |

## Next step

Lead: one cloud lead session (D-015); the PC session only runs commands and Live tests. Team: flat, specialised roles, no helper agents (D-017); limit 15 / normal 10, WIP = 1 per role, just-in-time researchers (D-019, supersedes D-018). Agent definitions for all seven roles and the file-ownership table in `CLAUDE.md` merged (PR #62). Open: `docs/TEAM.md` (gates G0–G5, role cards, label state machine) waits for the user's team draft; `researcher.md` still describes D-018 and must follow D-019. The lead also keeps the project cockpit current after every merge (collector into the repo: PR #72, in review).

- **Kick track:** Phase 01 DONE; preset descriptions name no numbers (#63 via PR #68). Test gap #70 (tampered sidecars) paused under WIP = 1 until #64 is done. `sound-designer` is writing hypotheses and a listening plan on #57/#58.
- **QA:** test runtime and gap report #69; mutation runner PR #75 (in review); budget warning from 10 agents #74 (in progress); fake-server teardown #71 waits for #50.
- **Phase 03 (#50, sample import):** unblocked. Split by D-017 file ownership: `src/library/` (layout, naming, no overwrite) → `audio-engineer`; import handler, check script, setup guide → `bridge-engineer`. `clip_slot.create_audio_clip` is still `unknown` and needs a Live run by the user.
- **Phase 04b** (#23): auth decided (D-014: subscription login, Opus 5.5); research note PR #47. Blocked until Phases 01–03 are accepted.
- **Parking lot from the listening test:** #57 kick layering (fuse two kicks), #58 own reference samples to steer synthesis ("main character").
- **User:**
  - Windows test of the budget watch (PR #18): let Claude Code run `git status` three times; a "Budget: …" message should appear.
  - GitHub → New issue → **Bug**: check that the form appears with "Repro" required (PR #24).
  - After pulling: run `pytest` once on Python 3.14 (golden hashes on your Windows machine, PR #40).
  - Before every pull: `git switch main` (the first bridge runs failed on an old branch).
  - Never merge a PR before the lead says "bereit zum Mergen" (PR #37 was merged mid-review).

## Open questions

- Answered in the #3 listening test (2026-10-28): drive has no audible artefacts; 24-bit odd-length WAVs with format tag 1 load in Live without warning; pitch decay 40 ms preferred (→ #59); #9 sub tail not audible (closed); click level and `driven` density acceptable for now (#30/#31 alternatives not needed).
- Reference tracks / artists for later style work: user will provide them later; not needed for the MVP.
