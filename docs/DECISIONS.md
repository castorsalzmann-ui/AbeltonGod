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

## D-014 · 2026-10-28 · accepted — Product auth: subscription login, default model Opus 5.5 (user decision; refines D-008)

**Decision.** The Phase 04b orchestrator authenticates through the Claude Agent SDK with the user's Claude Max (5x) subscription login. The default model is Opus 5.5. The auth method stays a single configuration switch (D-008), so an API key can replace the login without code changes.

**Reason.** User's choice after the research note (PR #47, fact-checked against official sources): the Agent SDK with plan login is allowed for ordinary, individual use of a personal local tool.

**Rejected.** API key from a Console organization linked to the Max plan (monthly API credit, separate from the usage window) — offered as the recommended route, not chosen for now; the plan-to-organization link cannot be changed by the user afterwards. Sonnet 5.5 as default (cheaper; not chosen).

**Consequences.**
- Copilot requests share the 5-hour and weekly usage window with development sessions.
- If anyone other than the user ever uses the tool, the subscription login is no longer allowed: switch to an API key first.
- USD figures in `config/guard-policy.json` are API-equivalent estimates. With Opus 5.5 the `kick_generation` worst case (8 calls × 1.5k output) is estimated at ~$0.37, above its $0.25 cap; the guard then stops the request. The cap stays unchanged until Phase 04b measures real usage.

## D-015 · 2026-10-28 · accepted — Lead session and agent limits (user decision; supersedes the agent-count part of D-010)

**Decision.** One cloud lead session coordinates (issues, PRs, reviews, merge go-aheads, `CURRENT_STATE.md`/`DECISIONS.md`); other sessions only run commands and Live tests. The lead may run up to 10 sub-agents at once, and each sub-agent may start up to 2 helpers of its own. The user still merges every PR, after an independent review says ready.

**Reason.** The user wants the lead to delegate all non-lead work and to parallelise. Two lead sessions on 2026-10-28 produced duplicate PRs (#42) and a missed test run.

**Rejected.** Two parallel lead sessions. The lead merging PRs itself (offered; user keeps merging).

**Consequences.** D-010's single-writer rule for state files stays. Every agent and helper uses the shared Max 5x usage window; the lead starts agents only for independent work. Merge requests to the user name the PR in words first, with a direct link.

## D-016 · 2026-10-28 · accepted — Team structure: lead, up to 3 sub-agents, one QA tester (user decision at lead handover; supersedes the agent-count part of D-015)

**Decision.**
- **Lead** (one cloud session, D-015): coordinates, sets order and ownership, gives merge go-aheads, and is the only writer of `CURRENT_STATE.md` and `DECISIONS.md` (on `main`, after a merge, gate green). The lead does not implement.
- **At most 3 sub-agents at once** (`audio-engineer`, `bridge-engineer`, `reviewer`). Each may start up to **2 helpers**, only when the lead allows it in the prompt and only for clearly separable work (e.g. independent tests + fault injection, docs).
- **One QA tester**, used continuously, not counted in the 3. Goal: less test and review time without less test depth — test pyramid and runtime overview (`pytest --durations`), targeted fast test selection per PR (the full suite stays the gate), reusable check tools (mutation runner, fake-bridge scenarios, property generators), lessons from review findings, and a pre-check before each review (gate, CI status, `mergeable_state`, diff size). The QA tester never changes product code and never weakens a test or a limit; its tools land through normal PRs with review.
- **Every agent works in its own git worktree.** Only the lead uses the main clone.
- Per task: issue (what / why / boundary / done when) → implementer PR → QA pre-check → independent `reviewer` (max. 2 rounds, a third needs the user's yes; comment/doc-only PRs: lead's own diff check) → findings from "minor" up fixed, nits collected as an issue → merge go-ahead → state update.
- The user merges only after a message starting with "Bereit zum Mergen: <name> (PR <n>)" with link, 1–3 sentences and "CI auf Ubuntu und Windows grün"; one go-ahead at a time.

**Reason.** The user wants fewer parallel agents than D-015 allowed (shared Max 5x usage window) and a dedicated role that shortens review cycles, which took up to six rounds (PR #8).

**Rejected.** Up to 10 sub-agents (D-015). The QA tester editing product code or relaxing tests to save time.

**Consequences.** D-015's single lead session and the user's merge rule stay. Agents in worktrees must run `python -m pytest -o pythonpath=src` and check `audio_engine.__file__` / `bridge.__file__`, because the editable install points at the main clone.

## D-017 · 2026-10-28 · accepted — Flat team of specialised roles, no helper agents (user decision; supersedes D-016 and the agent-count part of D-015)

**Decision.** The lead assigns specialised agents directly. No agent starts helpers or sub-agents of its own. At most **10 agents active at once**; the lead activates only what the current phase needs and does short lookups itself instead of starting an agent.

| Role | Job | Writes to | Active |
| --- | --- | --- | --- |
| `audio-engineer` | Kick engine, DSP, presets, variants, analysis, WAV/sidecars | `src/audio_engine/`, `src/library/`, their tests | now (#59), later layering (#57) |
| `bridge-engineer` | AbletonOSC, capability registry, import into Live | `src/bridge/`, `scripts/` (except `scripts/qa/`), `docs/setup/`, their tests | now (Phase 03, #50) |
| `orchestrator-engineer` | Claude copilot: tool definitions from `contracts/`, orchestrator loop, approval levels, guard wiring | `src/orchestrator/`, `src/guard/`, their tests | from Phase 04b (#23) |
| `reviewer` | Independent review of every PR against spec, decisions and contracts; fault injection, own seeds | nothing in the repo: review comments and finding issues only | always, never on its own work |
| `qa-tester` | Less check time without less check depth: runtime analysis, targeted test selection per PR (full suite stays the gate), reusable mutation runner and fake scenarios, pre-check before every review (gate, CI, `mergeable_state`, diff size), test gaps from review findings | test infrastructure in `tests/`, `scripts/qa/` (by PR with review) | permanent |
| `sound-designer` | Turns the user's musical feedback ("generic", "main character missing", "punch only when layered") into measurable hypotheses and parameter proposals; reference analysis; plans listening tests | no code: issue comments, `docs/research/` | now for #57/#58, before every listening test |
| `researcher` (optional) | Feasibility and documentation before new phases (Ableton LOM, AbletonOSC, Anthropic SDK), dated and sourced | `docs/research/` | before Phase 03 details and 04b |

**Rules.**
- Each role writes only to its own files. Anything a role needs outside them becomes an issue for the owning role.
- The reviewer and the qa-tester never check their own work. The sound-designer gives hypotheses, never listening judgments; those come only from the user.
- Every agent works in its own git worktree; the main clone belongs to the lead. The lead coordinates, gives merge go-aheads and alone writes `CURRENT_STATE.md` and `DECISIONS.md`; it does not implement product code.
- Per task (unchanged from D-016): issue → implementer PR → qa-tester pre-check → independent `reviewer` (max. 2 rounds; a third needs the user's yes) → findings from "minor" up fixed → merge go-ahead ("Bereit zum Mergen: …") → state update.
- Agent definitions for `qa-tester`, `sound-designer`, `orchestrator-engineer` and `researcher` live in `.claude/agents/`, in the style of the existing three, added by a PR with review.

**Reason.** Every extra layer costs context and time, and implementers in this environment sometimes had no tool to start helpers at all. Specialised roles with fixed file ownership avoid overlapping edits.

**Rejected.** Three sub-agents with two helpers each plus a QA tester (D-016). Helpers or sub-sub-agents of any kind.

**Consequences.** D-015's single lead session and the user's merge rule stay. Worktree agents keep using `python -m pytest -o pythonpath=src` and check `audio_engine.__file__` / `bridge.__file__`. Phase 03 library work (`src/library/`) belongs to the `audio-engineer`, the Live import to the `bridge-engineer`.

## D-018 · 2026-10-28 · accepted — Two research agents prepare parking-lot topics ahead of time (user decision; refines the `researcher` row of D-017)

**Decision.** Two `researcher` agents work ahead on the parking lot (ROADMAP "Parking lot" and issues labelled `parking-lot`), before any of it is scheduled: feasibility, programmability (APIs, LOM/AbletonOSC coverage, libraries, licences), known pitfalls and concrete pointers for the later worker agents. They are split by topic so they never write the same file:
- **Research A — sound and audio:** kick layering (#57), own reference samples (#58), reference analysis, more sample categories (bass, percussion, hats), generative audio backend, mastering.
- **Research B — integration and product:** MIDI and arrangement engine, audio capture / mix-analysis path in Live 12 Standard, desktop UI with sample picker, own VST3 plugins (JUCE), personal sound profile, guard extras, stabilisation.

**Output.** One dated note per topic in `docs/research/` (`<date>_parking-<topic>.md`), each opening with a short "For workers" block: what is possible, the recommended route, what to read first, open questions for the user. Notes land by PR with an independent review. Each parking-lot issue gets a comment linking its note. Workers on a later issue read the matching note before designing or researching again.

**Rules.** Research only: no code, no specs, contracts or decisions; recommendations go into the note's "Implications". Official sources first, version-dependent claims with version, inference marked as such (see `.claude/agents/researcher.md`). They coordinate with the `sound-designer` on #57/#58: the sound-designer measures the engine, Research A covers outside knowledge.

**Reason.** Less total work later: workers start from verified notes instead of researching during implementation, and blockers show up before a phase is planned.

**Rejected.** Researching only right before a phase (D-017's original "before Phase 03 details and 04b"). A single researcher for the whole parking lot (slower, too broad).

**Consequences.** Counts toward the limit of 10 active agents (D-017). Notes can go stale: each states the date and versions; a worker re-checks version-dependent claims before relying on them.

## D-019 · 2026-10-28 · accepted — Agent limit 15/10, gated team workflow, just-in-time researchers (user decision 21:04; supersedes D-018 and the agent-count part of D-017)

**1. Agent limit.**
- **Hard limit: 15 agents active at once** (all roles together, incl. reviewer, qa-tester, researchers). Never exceeded.
- **Normal operation: up to 10.** Above 10 is "overclocking": only briefly, only for independent work, and the lead tells the user in one sentence why and when it will be back under 10.
- `config/dev-budget.json` (by PR with review): subagent warning from 10 instead of 4, and the warning repeats on **every further start above 10** (deliberately annoying). The budget watch stays warn-only; the 15 are a rule, not a technical lock. The test that pins `.claude/settings.json` stays unchanged when only `dev-budget.json` changes.
- On a budget warning above 10: pause and write two lines (how many agents, for what), then continue deliberately or reduce.

**2. Workflow from the team draft.** Adopted: gates **G0–G5** with the `qa-tester` pre-check; **role cards**; an **interface stub as a G0 requirement**; **WIP = 1 per role**; **labels as a state machine**; **`contracts/` ownership** (the requesting role writes the `contract-change` PR, the lead decides before it starts); **researchers just in time**; **metrics only at `/close-phase`, from GitHub data**. Details live in `docs/TEAM.md`, which lands together with the four missing agent definitions as its own PR with review. Phase 03 starts only after #59 is merged and Phase 01 is DONE (both met on 2026-10-28: PR #60, 1a8dfec).

**3. Researcher rules (binding, also in `docs/TEAM.md`).**
- **Trigger:** the lead starts researchers when a phase goes into review, for the **next phase only**, never further ahead. No research "on stock"; parking-lot topics only with a concrete issue.
- **Questions, not topics:** 3–6 precise questions per task, each naming the issue that needs the answer (e.g. "Does `max_turns` stop the running tool call or only the next turn? Source with date.").
- **One researcher per clearly bounded question cluster;** overlapping clusters are forbidden (contradicting notes). Normally 2 in parallel, at most 3.
- **Fixed note format** in `docs/research/<date>_<topic>.md`: date · versions researched against (Live, AbletonOSC commit, SDK version) · receiving issue · per question: question, answer, source (URL with retrieval date, or file/line), confidence · mandatory section **"To verify by experiment"**.
- Everything under "To verify" becomes an issue for the owning role. A researched claim never counts as verified; `CURRENT_STATE.md` lists it only as "not verified".
- **Reviewed like code:** the reviewer spot-checks that the sources support the claims. A note without sources goes back. Interpretation is marked as such.
- Results are bound to the receiving issue (comment linking the note) so the implementer finds them at start.
- **Staleness:** at `/close-phase` the lead checks whether the next phase's notes still match the current versions (Live, AbletonOSC, SDK); if not, a refresh issue.
- Before any new research, search `docs/research/` first (CLAUDE.md); no duplicates.
- **Planned for 04b (only once Phase 03 is in review):** cluster 1 Agent SDK behaviour (`max_turns` / `max_budget_usd`, stop semantics, tool wrapping, PreToolUse hooks); cluster 2 tool-schema generation from JSON Schema (what the SDK expects as tool definitions); cluster 3 AbletonOSC follow-up functions for the orchestrator — starts only after the Live result for `create_audio_clip` (`tested`/`unsupported`), because the import route depends on it.

**4. Not part of this decision:** pulling 04b forward (an exception to D-003). The lead puts it to the user separately as a yes/no question, with the condition: CI-only parts only after #59 is merged; tool definitions only after the Phase 03 Live result.

**Reason.** More parallel capacity when work is independent, without losing control; research that is narrow, sourced and tied to the issue that consumes it instead of broad notes written ahead of need.

**Rejected.** Parking-lot pre-research on stock (D-018; issues #66/#67 closed as not planned, nothing committed). A technical hard stop at 15 in the budget watch (rule only).

**Consequences.** The `sound-designer` keeps working on #57/#58 (it is not a researcher). Active WIP was reduced to one per role: #70 paused (work kept in the agent's worktree) while the audio-engineer finishes #64. The draft text for G0–G5, role cards and the label state machine is to be provided by the user for `docs/TEAM.md`; until then the existing workflow in `CLAUDE.md` applies plus the rules written out above.

## D-020 · 2026-10-28 · accepted — Phase 04b pulled forward in two steps (user decision 22:03; exception to D-003)

**Decision.** Phase 04b starts before Phase 03 is accepted, in two steps:
1. **Now (CI only):** orchestrator loop, guard wiring (D-011, every model call and tool through `src/guard/`), approval levels, terminal chat, auth switch (D-014), all against an internal model-client interface with a fake model and recorded responses. No real Claude call in CI. Condition "#59 merged" is met (PR #60).
2. **Only after the Phase 03 Live result** for `clip_slot.create_audio_clip` (`tested`/`unsupported`): the Claude tool definitions (`generate_kick`, `list_tracks`, `import_sample`) and their wiring to the bridge. D-004 still applies: only `tested` capabilities become tools.

The researchers for 04b clusters 1 (Agent SDK behaviour) and 2 (tool-schema generation) started at the same time on the user's "start all" (exception to D-019's trigger "when Phase 03 is in review"); cluster 3 (AbletonOSC follow-ups) still waits for the Live result.

**Reason.** The user wants all active work finished as fast as possible; the CI-only part of 04b does not depend on Phase 03.

**Rejected.** Starting 04b tool definitions before the Live result (the import route depends on it).

**Consequences.** The SDK-specific parts of step 1 stay behind the model-client interface until the cluster-1 note is merged; anything it marks "to verify" becomes an issue. Phase 04b is accepted only after Phase 03 is accepted and the user's end-to-end test (#23).

## D-021 · 2026-10-28 · accepted — Lead merges overnight until 2026-10-29 09:00 (user decision 22:33; temporary exception to D-015)

**Decision.** Until **2026-10-29 09:00 Berlin time** the lead may merge PRs itself, only when all hold: an independent `reviewer` verdict APPROVE-READY on the current head (or approve-ready with every finding from "minor" up fixed and the fix diff checked by the lead), CI green on ubuntu-latest and windows-latest for that head, `mergeable_state` clean. **Never** self-merged: PRs labelled `contract-change`, and any change that sets a capability to `tested`. From 09:00 the user merges again (D-015).

**Reason.** The user wants the night used without merges waiting for them.

**Consequences.** The lead lists every self-merge (PR, head SHA, review link) for the user in the morning. Phase 03 still needs the user's Live test before it is accepted; it is prepared overnight as one test with ready PowerShell commands.

## D-022 · 2026-10-29 · accepted — Requirements questionnaires for all planned features (user decision 10:17; complements D-019)

**Decision.** Preparatory work for every phase, including the parking lot, starts with the user's requirements, not with research: requirement interviewers (agents with no code or repo writes) write a German questionnaire per feature group into one shared document (one tab per group: sound generation, analysis and profile, production in Live, copilot and operation). The user answers there. The lead turns the answers into issues per feature (what / why / boundary / done when), labelled `parking-lot` until a phase is planned, and shows them to the user before anything is built.

**Reason.** The user wants every later phase to start from clear goals and to take part in planning.

**Boundary.** Researchers still follow D-019 (just in time, one phase ahead, questions bound to an issue). Questionnaires ask about goals, priorities and limits, never about implementation.

**Consequences.** Answers in the document are the user's own decisions and are quoted in the issues they produce; an empty answer means "no preference", not "no".

## D-023 · 2026-10-29 · accepted — Pre-work on all parking-lot features now (user decision 11:00; relaxes the trigger of D-019 point 3)

**Decision.** Agents start now on every parking-lot feature that the questionnaire (D-022) turned into tasks, as far as no open user decision blocks them: researchers for all feature clusters (not only the next phase), plus one implementer task per role. D-019's other researcher rules stay: precise questions bound to an issue, fixed note format with "To verify by experiment", no overlapping clusters (here at most 5 researchers in parallel, one cluster each), review like code.

**Reason.** The user wants all phases prepared in parallel; the questionnaire answers make the questions concrete.

**Consequences.** Tasks that depend on one of the ~30 open questions in the questionnaire ("Braucht eine Entscheidung") wait for the user's answer. WIP = 1 per role and the 15/10 agent limit (D-019) still apply. Research notes can go stale before their feature is built; each note states versions and is re-checked at `/close-phase`.
