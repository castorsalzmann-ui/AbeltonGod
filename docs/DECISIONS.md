# Decisions

Binding until replaced by a newer decision. Add new entries at the bottom; never edit an accepted decision, supersede it.

Format: ID · date · status · decision · reason · rejected alternatives · consequences.

**Rejected means rejected.** Do not re-propose a rejected alternative unless the user explicitly reopens the decision. If you believe a decision is wrong, open an issue labelled `side-finding` and keep working within it.

_2026-10-28: "Rejected" lines added to D-001–D-011 as a clarification; no decision changed._

---

## D-001 · 2026-10-28 · accepted — Ableton bridge = Python Remote Script (AbletonOSC), not Max for Live

**Decision.** Integrate with Live through a Python control-surface (Remote) script based on [AbletonOSC](https://github.com/ideoforms/AbletonOSC), talking OSC on localhost (default ports 11000 in, 11001 out).

**Reason.** The user has Live 12 Standard; Max for Live needs Suite or a paid add-on. AbletonOSC supports Live 11+ and several community MCP projects already drive Live this way.

**Rejected.** Max for Live device (needs Suite or paid add-on). VST3/AU plugin as the control interface (sees only its own channel, no access to the set). Writing our own remote script from scratch (AbletonOSC already covers most of the LOM; we only extend it where needed).

**Consequences.** Remote scripts run on Live's GUI thread (reported jitter 1–16 ms) — fine for control, never for audio timing. Live allows 6 control-surface slots. Rendering/export is not reachable via the API. Not every LOM function is exposed; see D-004.

## D-002 · 2026-10-28 · accepted — Claude orchestrates, local code executes

**Decision.** Claude only chooses tools and parameters. Audio generation, analysis and Ableton calls run in local code behind validated schemas.

**Reason.** Real-time audio must not depend on network calls; schema validation keeps AI output safe and reproducible.

**Rejected.** Claude generating audio or DSP code at runtime. Claude sending raw OSC/LOM commands. Any model call inside a real-time audio path.

**Consequences.** Every tool has a JSON schema in `contracts/`. Engine and bridge must work without Claude.

## D-003 · 2026-10-28 · accepted — Order: kick engine → bridge → import → Claude

**Decision.** Build the deterministic kick engine first, without Claude. Validate the Ableton bridge on the user's machine separately. Connect them, and only then add the Claude orchestrator and chat UI.

**Reason.** The two biggest risks (sound quality, Ableton access) are tested independently before anything depends on them. Kick was chosen by the user as the first element.

**Rejected.** Chat UI and Claude integration first (builds on unproven foundations). Starting with several sample categories at once (spreads the sound-quality risk).

## D-004 · 2026-10-28 · accepted — Capability registry

**Decision.** `contracts/capabilities.json` lists every Ableton function the product wants, with status `unknown | supported | tested | unsupported`.

**Reason.** "AbletonOSC exposes the LOM" is a project goal, not a guarantee for every function in every Live version.

**Rejected.** Assuming full LOM coverage. Marking functions as working based on documentation alone.

**Consequences.** Claude-facing tools may only wrap `tested` capabilities. `tested` requires evidence from the user's machine.

## D-005 · 2026-10-28 · accepted — Deterministic DSP in the MVP, no generative audio model

**Decision.** MVP sounds come from deterministic Python DSP (NumPy). Generative models (e.g. Stable Audio Open family) are a later, optional, swappable backend.

**Reason.** Reproducible, testable, fast, free, no licence questions for released tracks. RTX 5070 keeps the generative option open later.

**Rejected.** Stable Audio Open (or another generative model) for kicks in the MVP: not reproducible, licence must be checked for releases, slower to iterate. Cloud audio-generation APIs: cost and dependency.

**Consequences.** Same parameters + seed → byte-identical WAV. This makes golden-file and feature-tolerance tests possible in CI.

## D-006 · 2026-10-28 · accepted — Undo in three layers

**Decision.** (1) Action log with before/after values for every change; (2) Live's own undo via AbletonOSC `/live/song/undo` where it applies; (3) a project copy before large changes. File operations never overwrite; new files get new names.

**Reason.** Live's undo does not cover file operations and is not reliable for multi-step actions.

**Rejected.** Relying only on Live's undo. Overwriting sample files in place.

## D-007 · 2026-10-28 · accepted — No JUCE / C++ in the MVP

**Decision.** Python only until a custom VST3 plugin is actually needed.

**Reason.** The schema-based engine interface lets a JUCE implementation replace the Python one later without changing callers.

**Rejected.** JUCE/C++ as the DSP base from day one (slower iteration, no MVP benefit). Rust audio stack (no plugin need yet, extra toolchain).

## D-008 · 2026-10-28 · accepted — Claude access via Max subscription first, API key later if needed

**Decision.** Development uses Claude Code with the user's Max subscription. The product's orchestrator (Phase 04b) is built so the auth method is a single configuration point (subscription via Claude Agent SDK, or an API key).

**Reason.** The subscription covers Claude.ai and Claude Code but is not a separate API product, and Anthropic's stance on third-party use of subscription auth has changed before. Switching must stay cheap.

**Rejected.** Buying API credits now (no need before Phase 04b). Hard-wiring subscription auth (policy risk). Unofficial proxies that expose the subscription as an OpenAI-compatible API (unsupported, may violate terms).

## D-009 · 2026-10-28 · accepted — Test boundary

**Decision.** CI runs unit tests, schema tests and backend tests against a fake bridge. Tests that need Live run only on the user's machine and are recorded in the issue/PR with their real output.

**Rejected.** Running Ableton in CI (not possible on hosted runners, licence). Treating mock runs as integration evidence.

## D-010 · 2026-10-28 · accepted — Few agents, single writer for state

**Decision.** Main session + `audio-engineer`, `bridge-engineer`, `reviewer`. Only the lead session on `main` edits `CURRENT_STATE.md` and `DECISIONS.md`.

**Reason.** Each subagent starts without context and consumes the shared subscription usage window; parallel edits to one state file cause constant merge conflicts.

**Rejected.** Five or more specialised agents plus a lead from the start. Every agent updating the state file. One monolithic blueprint file loaded every session (too many tokens; the split docs are read on demand).

## D-011 · 2026-10-28 · accepted — Agent Resource Guard for every product Claude call

**Decision.** All Claude calls made by the product go through one guard module (`src/guard/`). It enforces, per request profile (`config/guard-policy.json`, schema in `contracts/`): output tokens per call, model calls, tool calls, cost estimate, wall-clock timeout, identical-tool-call loops, files written and Ableton writes; plus session and daily budgets. It records estimated and actual usage per call in a local log.

**How.** Use the Claude Agent SDK's own limits (`max_turns`, `max_budget_usd`) as the first line; the guard adds what the SDK does not cover (tool-call counts, loop detection, timeout, action budget, session/daily totals) and wraps every tool the model can call, including tools used by sub-agents.

**Levels.** Green: normal. Warn (≥ `warn_at_fraction` of any limit): no new sub-tasks, shorter answers. Stop: no further model calls; the user gets what was finished and what is still open. A request stopped by the guard is never reported as successful.

**Scope.** Product runtime only. Development sessions in Claude Code are kept small by process (one issue per fresh session, few subagents), not by this module.

**Reason.** `max_tokens` alone does not bound a request: input tokens, tool loops and repeated requests add up. Cheap but uncontrolled agents can still do damage through file and Ableton writes.

**Rejected.** A plain `max_tokens` counter. A four-level traffic light with automatic model downgrade, context summarisation, CPU/GPU budgets and a dashboard in the MVP (revisit when generative audio or multi-agent product features arrive).

**Consequences.** Built and tested in CI before the orchestrator makes its first real Claude call (Phase 04a). With subscription auth, USD values are API-equivalent estimates; the real constraint is the usage window.

## D-012 · 2026-10-28 · accepted — Kick pitch criterion: split check, staged tolerance (user decisions on PR #8)

**Decision.** The kick engine's pitch is verified by two separate checks:

1. **Analyser accuracy:** `analyse()` matches an independent analytic-signal (Hilbert) reference over the same crossing interval, ±1 %.
2. **Parameter fidelity:** the measured tail pitch matches the closed-form mean of f(t) = f_end + (f_start − f_end)·e^(−t/τ) over exactly the measured interval. Tolerance is **±3 %** for measurement windows ≥ 80 ms and **±5 %** below. The formula is written in the test, not taken from the engine.

`pitch_end_hz` is the **asymptote**, not a promise: a kick with a long `pitch_decay_ms` may fade out before it reaches it. When the tail is too short to measure, `fundamental_hz` is `None`.

**Reason.** The original "±10 % to `pitch_end_hz`" cannot hold over the full schema range. Short windows have real measurement limits (DC blocker, click), and the user accepted ±5 % for them.

**Rejected.** ±10 % to `pitch_end_hz` regardless of settling. Restricting the schema so the pitch always settles (less sound-design range). A uniform ±3.5 % tolerance (tuned to observed failures). Comparing crossing counts of two signals in the same window (it produced false failures up to 13 %).

**Consequences.** Do not loosen these tolerances, add skips or `xfail` without a new user decision. The schema wording follows in #7. Evidence and reviews: PR #8.

## D-013 · 2026-10-28 · accepted — Engine version follows rendered bytes (user decision on #35)

**Decision.** `audio_engine.ENGINE_VERSION` changes in every PR that changes the bytes of any rendered WAV (minor bump, e.g. 0.1.0 → 0.2.0; patch only for changes that keep all bytes identical). The same PR updates the golden SHA-256s in `tests/audio_engine/test_engine_version.py` and ticks the PR-template checkbox. `rerender_from_sidecar` refuses a sidecar from another engine name or version with `EngineVersionMismatch`; `allow_engine_mismatch=True` renders it with the current engine as a new render.

**Reason.** `INTERFACES.md` and D-005 promise that a sidecar reproduces its WAV byte for byte. Three byte changes (#20, #26, #16) shipped under version 0.0.1, so a re-render silently gave different bytes (#35).

**Rejected.** Bumping only for audible changes (format fixes would still break re-render silently). Migrating old sidecars (only test renders exist).

**Consequences.** A byte change without a bump fails the golden-hash test; a bump without new hashes fails the version check. Golden hashes are a hard failure on Linux and Windows (Windows CI matched all 5 cases, PR #40). Old sidecars are not migrated. Evidence and reviews: PR #40.
