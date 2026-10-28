# Current State

_Last updated: 2026-10-28 · Written only by the lead session on `main` after a merge._

## Phase

- **Phase 00 — Setup:** DONE (#1 closed 2026-10-28).
- **Phase 01 — Kick engine:** core merged (#2 via PR #8); drive anti-aliased (#13 via PR #20); contract semantics (#7 via PR #28). Open: #11, #12, #16, then #3.
- **Phase 02 — Ableton bridge:** OSC client and capability gate merged (#4 via PR #25). Open: #5 (bridge check on the user's machine).
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

**Known limits of the bridge** (details in `docs/research/2026-10-28_abletonosc-protocol-and-create-audio-clip.md`):
- A timed-out write has an unknown outcome and may still be applied later; read back before any undo (rule for #5).
- The marker echo the bracketing relies on is read from AbletonOSC source, not yet confirmed in Live.

**Measured limits of the kick core** (details in PR #8):
- Pitch accuracy: ±3 % for windows ≥ 80 ms, ±5 % below (user decision).
- About 10 % of very short, fast-decay kicks report `fundamental_hz: None`.
- Byte identity is proven per platform only, not Linux vs. Windows.
- Render with `drive > 0` costs ~3× more than before anti-aliasing (2 s kick ≈ 54 ms on the CI-like Linux box); every WAV with `drive > 0` differs from pre-#20 renders.
- No listening test yet.
- The pitch-settle guideline describes the pitch curve. The measured `fundamental_hz` can still be up to ~17 % above `pitch_end_hz` for kicks that follow it (review of #7).
- #27: on very fast decays (amp_decay ≈ 20–50 ms) the zero crossings drift from the body pitch around −37 dB; cause not established.

**Known limits of the guard** (details in `docs/research/2026-10-28_guard-sdk-mapping.md`):
- One copilot process at a time: calls in flight in another process are invisible to the daily budget.
- The guard cannot interrupt a running model call; it stops at the next guard step.
- SDK stop behaviour for `max_turns` / `max_budget_usd` is not verified yet (Phase 04b).

## What does not exist yet

- Kick presets, variants, CLI (#3)
- Bridge check against Live and capability evidence (#5)
- Sample import into Live (Phase 03)
- Claude orchestrator / chat (Phase 04b)

## Environment facts (from the user, 2026-10-28)

| Fact | Value |
| --- | --- |
| OS | Windows |
| Local Python | 3.14.4 (CI uses 3.12) |
| Ableton | Live 12 **Standard** (no Max for Live), always updated to the latest release → well above 12.0.5; exact number to note at Phase 02 start |
| Project sample rate | 48 kHz (engine default 48 kHz / 24-bit) |
| GPU | NVIDIA RTX 5070 |
| Claude access | Max subscription (no separate API key yet) |
| First sample type | Kick |
| Languages | German and English |
| Control surfaces / controllers in use | None — all 6 slots free |
| Reference tracks / artists | 77 reference kick files measured (taste range, not a target): see `docs/research/2026-10-28_kick-gen2-learnings.md`. Full reference tracks still open. |
| Genre | Not relevant for now. Later the user wants **both** genre-specific and free synthesis by values: one shared parameter space, genre profiles only as optional data on top. Deliberately **not** a decision. Only audio content of references counts, never names. |

## Next step

- **Kick track:**
  1. #11 — tests for tone, drive and the envelope; nothing protects them today.
  2. #12 — WAV/sidecar nits, incl. the 24-bit pad byte that matters for the Ableton import.
  3. #16 — user decision: should `drive` start continuously at 0? Decide before the listening test.
  4. Then #3 — presets, variants, CLI and the first listening test, which includes #9. Presets must call `max_settled_pitch_decay_ms` (or be named as deliberately pitchy).
- **Bridge track, in parallel:** #5 — `bridge_check.py` (`bridge-engineer`), then the user installs AbletonOSC per `docs/setup/ABLETONOSC_WINDOWS.md`, runs the ping and the check on a test set. Live version known: 12.4.5.
- **Phase 04b** (Claude orchestrator, #23): blocked until Phases 01–03 are accepted and the auth method (D-008) is confirmed with the user.
- **Process:** #19 — budget watch blind spots (cloud reviewer runs, permission denials). New bugs: Bug form + a failing case in `tests/regressions/` first (#14 done).
- **User:**
  - Windows test of the budget watch (PR #18): let Claude Code run `git status` three times; a "Budget: …" message should appear.
  - Decide #16 (drive continuity at 0).
  - GitHub → New issue → **Bug**: check that the form appears with "Repro" required (PR #24).
  - After pulling: `pip install -e ".[dev]"` once (new dependencies pytest-xdist and python-osc).
  - PR #25 user tests (AbletonOSC install, ping, Live closed, port 11001 in use, firewall prompt) — can be done together with #5.

## Open questions

- Does the anti-aliased drive (PR #20) sound different from before? Part of the #3 listening test.
- New default `pitch_decay_ms` 15 vs. the old 40 — compare by ear in the #3 listening test.
- #9 — is the DC-correction sub-bass tail of very short or extreme kicks audible? Up to 11.4 % of peak at the extremes, plus a −28 dB tail from the DC blocker. To be answered in the #3 listening test.
- Reference tracks / artists for later style work: user will provide them later; not needed for the MVP.
