# Decisions

Binding until replaced by a newer decision. Add new entries at the bottom; never edit an accepted decision, supersede it.

Format: ID · date · status · decision · reason · consequences.

---

## D-001 · 2026-10-28 · accepted — Ableton bridge = Python Remote Script (AbletonOSC), not Max for Live

**Decision.** Integrate with Live through a Python control-surface (Remote) script based on [AbletonOSC](https://github.com/ideoforms/AbletonOSC), talking OSC on localhost (default ports 11000 in, 11001 out).

**Reason.** The user has Live 12 Standard; Max for Live needs Suite or a paid add-on. AbletonOSC supports Live 11+ and several community MCP projects already drive Live this way.

**Consequences.** Remote scripts run on Live's GUI thread (reported jitter 1–16 ms) — fine for control, never for audio timing. Live allows 6 control-surface slots. Rendering/export is not reachable via the API. Not every LOM function is exposed; see D-004.

## D-002 · 2026-10-28 · accepted — Claude orchestrates, local code executes

**Decision.** Claude only chooses tools and parameters. Audio generation, analysis and Ableton calls run in local code behind validated schemas.

**Reason.** Real-time audio must not depend on network calls; schema validation keeps AI output safe and reproducible.

**Consequences.** Every tool has a JSON schema in `contracts/`. Engine and bridge must work without Claude.

## D-003 · 2026-10-28 · accepted — Order: kick engine → bridge → import → Claude

**Decision.** Build the deterministic kick engine first, without Claude. Validate the Ableton bridge on the user's machine separately. Connect them, and only then add the Claude orchestrator and chat UI.

**Reason.** The two biggest risks (sound quality, Ableton access) are tested independently before anything depends on them. Kick was chosen by the user as the first element.

## D-004 · 2026-10-28 · accepted — Capability registry

**Decision.** `contracts/capabilities.json` lists every Ableton function the product wants, with status `unknown | supported | tested | unsupported`.

**Reason.** "AbletonOSC exposes the LOM" is a project goal, not a guarantee for every function in every Live version.

**Consequences.** Claude-facing tools may only wrap `tested` capabilities. `tested` requires evidence from the user's machine.

## D-005 · 2026-10-28 · accepted — Deterministic DSP in the MVP, no generative audio model

**Decision.** MVP sounds come from deterministic Python DSP (NumPy). Generative models (e.g. Stable Audio Open family) are a later, optional, swappable backend.

**Reason.** Reproducible, testable, fast, free, no licence questions for released tracks. RTX 5070 keeps the generative option open later.

**Consequences.** Same parameters + seed → byte-identical WAV. This makes golden-file and feature-tolerance tests possible in CI.

## D-006 · 2026-10-28 · accepted — Undo in three layers

**Decision.** (1) Action log with before/after values for every change; (2) Live's own undo via AbletonOSC `/live/song/undo` where it applies; (3) a project copy before large changes. File operations never overwrite; new files get new names.

**Reason.** Live's undo does not cover file operations and is not reliable for multi-step actions.

## D-007 · 2026-10-28 · accepted — No JUCE / C++ in the MVP

**Decision.** Python only until a custom VST3 plugin is actually needed.

**Reason.** The schema-based engine interface lets a JUCE implementation replace the Python one later without changing callers.

## D-008 · 2026-10-28 · accepted — Claude access via Max subscription first, API key later if needed

**Decision.** Development uses Claude Code with the user's Max subscription. The product's orchestrator (Phase 04) is built so the auth method is a single configuration point (subscription via Claude Agent SDK, or an API key).

**Reason.** The subscription covers Claude.ai and Claude Code but is not a separate API product, and Anthropic's stance on third-party use of subscription auth has changed before. Switching must stay cheap.

## D-009 · 2026-10-28 · accepted — Test boundary

**Decision.** CI runs unit tests, schema tests and backend tests against a fake bridge. Tests that need Live run only on the user's machine and are recorded in the issue/PR with their real output.

## D-010 · 2026-10-28 · accepted — Few agents, single writer for state

**Decision.** Main session + `audio-engineer`, `bridge-engineer`, `reviewer`. Only the lead session on `main` edits `CURRENT_STATE.md` and `DECISIONS.md`.

**Reason.** Each subagent starts without context and consumes the shared subscription usage window; parallel edits to one state file cause constant merge conflicts.
