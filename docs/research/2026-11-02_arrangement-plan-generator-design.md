# Research: arrangement plan generator — interface, split of work, tests, way into Live (design draft)

- **Date:** 2026-11-02. Researcher B (integration and product).
- **Receiving issue:** #139 (hand-over comment of 2026-11-01: V6, V2, outro rule, soft-range question). Not a parking-lot note; no `*parking*` note exists in `docs/research/` on `origin/main` (checked at `a0ca3a5`, 2026-11-02).
- **Read first (all opened 2026-11-02, repo state `a0ca3a5`):** `CLAUDE.md`; `docs/CURRENT_STATE.md`; `docs/INTERFACES.md`, section "Arrangement plan" (line 135 onward) and "Tool inputs" (line 69 onward); `src/orchestrator/arrangement_plan.py`; `tests/test_contracts_arrangement_plan.py`; `tests/fixtures/arrangement_plan/T1-T3.json`; `contracts/capabilities.json`; issues [#139](https://github.com/castorsalzmann-ui/AbeltonGod/issues/139) and [#146](https://github.com/castorsalzmann-ui/AbeltonGod/issues/146) with all comments.
- **Notes this builds on (not repeated):** [`2026-10-29_arrangement-planner-sections-energy.md`](2026-10-29_arrangement-planner-sections-energy.md) (sections, energy shapes, element thresholds, settings; called "planner note" below), [`2026-10-29_live-midi-arrangement-devices.md`](2026-10-29_live-midi-arrangement-devices.md) (what Live can take), [`2026-10-29_bandit-wheel-musical-transfer.md`](2026-10-29_bandit-wheel-musical-transfer.md) (D1-D7, V2), [`2026-10-28_tool-schema-generation.md`](2026-10-28_tool-schema-generation.md) (strict tool schemas).
- **No web source was opened for this note.** Genre claims are the planner note's (sound-designer, retrieved 2026-10-29) and are not re-verified here. Everything below is read from the repo, or computed/measured with the checker in a throw-away prototype (see "Prototype"), or marked _Interpretation_.
- **Scope:** design draft only. No code in the repo, no change to a contract, spec or decision, no claim about how anything sounds, and no Live function is assumed to work.

## For workers

- **Possible with our stack?** Yes. A pure-Python generator that turns (genre, bpm, length, settings, optional drawn nodes) into a plan that `plan_problems` accepts needs no Live, no new dependency and no AI call. A prototype of the node part (sections given) produced 0 rule violations on 3000 random section sequences and reproduced `T1.json` exactly.
- **Route:** put it in `src/orchestrator/` as a library function first (owner `orchestrator-engineer`), CLI and Claude tool later. Always run the result through `plan_problems` before returning; never write a second checker (INTERFACES, "One checker").
- **Read first:** INTERFACES "Arrangement plan" in full (boundary rules B2/B3, outro walk, "Not in v0.1"); `arrangement_plan.py` (`default_outro`, `change_points`, `boundary_changes`); this note, sections 2, 3 and 5.
- **Big finding 1 (tests):** 6 of the 11 settings (`build_kick`, `intro_outro_bass`, `breakdown_rumble`, `change_grid`, `pre_drop_gap`, `fills`) change nothing in a v0.1 plan except their own echo in `settings`, because v0.1 has no element states and no events. V6/V2 from #139 therefore cannot be tested on a generated v0.1 plan: any such test would be construction-truth. They need a derived timeline (element states per phrase, events), see section 5 and issues G3/G4.
- **Big finding 2 (product):** the templates T2/T3 (256 bars) are longer than 7:00 at every tempo from 136 to 146 BPM (7:32 at 136, 7:19 at 140, 7:01 at 146). The outro rule (1 element per boundary, 64-bar outro after a full drop) and the user's 4-7 min window collide. The generator needs a policy; question Q1.
- **Effort:** medium for the plan generator (G1+G2), medium for the contract-change v0.2 (G3), large for the timeline derivation with its tests (G4), small for the CLI/tool (G5). Live building (G6) is blocked.
- **Blockers:** Live side blocked by #140 (12 arrangement capabilities `unknown`). Q1 and Q3 change G1; Q2 changes the split (G5/G7); Q4 adds a seed.
- **Open questions only the user can answer:** Q1-Q4 in section 8.

## 1. What the generator is (and is not)

A deterministic function `request -> plan`, where `plan` is arrangement-plan v0.1 (`contracts/arrangement-plan.schema.json`, INTERFACES line 135). D-002/D-024 apply: Claude decides what the user wants; local code computes every number. No generative audio model, no randomness unless a seed is part of the request (D-005 spirit: same request, byte-identical plan).

Not in scope: the planner window (user designs it), element sounds (only the kick exists as an engine), writing to Live.

## 2. Interface

### 2.1 Input (`PlanRequest`, proposal)

| Field | Type / range | Meaning | Source of the rule |
| --- | --- | --- | --- |
| `genre` | `techno` or `trance` | Picks the section skeleton (T2 or T3 of the planner note, section 3.1). | Planner note 3.1 |
| `bpm` | number, 20-999 | Goes into the plan; also converts minutes to bars. 136-146 is a default range, not a limit. | INTERFACES `bpm` row |
| `target_bars` **or** `target_minutes` | bars: multiple of 8, 32-1024; minutes: number | Exactly one. Minutes are converted by code: bars = round(minutes · 60 · bpm / 240) to the nearest multiple of 8 (formula from planner note section 2; the tie rule must be fixed in G1 and tested). | INTERFACES `total_bars` row; planner note 2 |
| `settings` | partial map of the 11 keys | Merged over the defaults; the plan always carries all 11 (INTERFACES "Settings"). Unknown key or value outside the list is an error. | INTERFACES "Settings" |
| `sections` (optional) | list of `{type, length_bars}` | Explicit layout, e.g. from the planner window. When given, `genre` only selects node defaults and the layout is not fitted. | _Interpretation_ (window needs it, the format already allows any order) |
| `drawn_nodes` (optional) | list of `{pos, value}`, array order binding | The user's energy line from the window. They become `drawn: true`, are never changed, and the undrawn nodes are rebuilt around them (B2/B3). | INTERFACES "Boundary rules" |
| `seed` (only if Q4 = variants) | integer | Selects a variant. Absent: the one default plan. | Q4 |

### 2.2 Output

| Field | Meaning |
| --- | --- |
| `plan` | A dict that passes `plan_problems` (checked inside the function; a failure here is an internal bug and raises, it is never returned). |
| `adjustments[]` | What the generator changed to make the request fit, as `{code, detail}`: e.g. `outro_lengthened` (32 to 64 because the walk needs it), `sections_shortened`. |
| `warnings[]` | Editor-style hints that do not make the plan invalid: `duration_window` (outside 4-7 min at this bpm; S2 is only an editor warning in v0.1), `soft_range` (B6). Recommendation: the generator does **not** warn about its own default outro (INTERFACES "Soft range" leaves this to the planner window issue). |

### 2.3 Error cases (a refused request returns no plan)

| Code | Cause | Detail returned |
| --- | --- | --- |
| `bad_genre`, `bad_bpm`, `bad_setting` | value outside the lists above | field and allowed values |
| `length_both_or_none` | both or neither of `target_bars`/`target_minutes` | - |
| `length_not_multiple_of_8`, `length_out_of_range` | not a multiple of 8, or outside 32-1024 | nearest valid values |
| `length_infeasible` | no choice of allowed section lengths adds up to the target for this skeleton and settings | the nearest feasible totals below and above; a request with one of them must succeed (property P3) |
| `sections_invalid` | explicit `sections` break a format rule | the `plan_problems` codes (tiling, first/last, lengths) |
| `drawn_node_invalid` | NaN/Infinity, value outside 0-1, `pos` outside 0..`total_bars`, more than two at one `pos`, a pair at 0 or `total_bars`, a decreasing `pos` | index of the node |
| `outro_slot_too_short` | drawn nodes make the outro start high, so the walk needs a longer outro than its slot, and the caller did not allow a length change | required length. _Interpretation_: the format says a drawn node never moves a section, so the generator reports instead of silently lengthening |

## 3. Who decides what

| Decision | Claude (reads the user's words) | Local code |
| --- | --- | --- |
| Genre, tempo, length in minutes or bars | Maps "6 minute techno track at 140" to `genre`, `bpm`, `target_minutes`. | Converts to bars, validates, fits. |
| Which settings to change | Maps "no bass in the intro" to `intro_outro_bass = off`. | Knows the allowed values; refuses the rest (strict tool schemas have no `minimum`/`enum` range help beyond `enum`, so range checks are local anyway: INTERFACES line 81 onward). |
| Section layout | Chooses a skeleton (genre) or, later, a list of section types. | Chooses the lengths (fit), tiles the sections, enforces first/last. |
| Energy values | Does not invent numbers for undrawn nodes. | All default node values, B2/B3, the outro walk, `second_drop`. |
| Energy wishes | Only through a narrow edit tool (Q2), as a named change ("second drop harder"), not as a whole plan. | Turns the wish into node values within the soft range. |
| Explaining the result | Reads `adjustments` and `warnings` back to the user in German. | Supplies them as data. |

INTERFACES line 139 already says Claude does not send whole plans and that chat edits go through a narrow edit tool with its own strict schema.

**Tool-schema consequence (read from INTERFACES line 81):** the strict optional-parameter budget is 24 of 24. A `plan_arrangement` tool therefore must have **no optional parameters**: required `genre`, `bpm`, `target_bars` (Claude does the minutes-to-bars arithmetic itself, or a required `target_minutes` and the handler does it), and one required array `setting_changes` of `{key, value}` (empty allowed). _Interpretation_: whether an array of objects with required fields counts against the optional-parameter limit is not stated in the repo; check it in the tool-wiring issue before relying on it (the tool-schema note lists the 24-parameter limit as read through WebFetch summaries only).

## 4. Algorithm sketch (what the three layers do)

1. **Layout (G1).** Start from the skeleton, apply `intro_length`, `breakdown_length`, `breakdown_count`, compute the outro length first (it depends only on the last section's end value, see `default_outro`: from 0.65 and above 64 bars, 0.40 up to 0.64 32 bars, below 0.40 16 bars; measured with `default_outro` on 2026-11-02). Fit the remaining "elastic" sections to `target_bars` over their allowed lengths (planner note section 3 and INTERFACES `sections[]` row): a small exhaustive search over at most nine sections with at most four lengths each, deterministic tie-break (smallest total deviation from the default lengths, then lexicographic). No random search.
2. **Nodes (G2).** Per section type, the default shapes of planner note section 4 as amended by INTERFACES (outro "continue", build end = max(start, next start - 0.05), `second_drop` +0.05 capped at 1.0). Intro and outro are one step per 8-bar phrase so that at most one element changes per boundary. Then overlay `drawn_nodes` (drawn wins; undrawn nodes at a position that already holds a drawn pair are dropped, because the format forbids a third node there) and recompute the undrawn B2/B3 anchors.
3. **Check.** `plan_problems(plan) == []`, else raise.

**Pitfall found in the prototype:** 0.90 + 0.05 gives 0.9500000000000001 in floating point and the fixture holds 0.95, so a byte-identical or fixture comparison fails. Round node values to a fixed number of decimals (4 was enough here) when they are produced.

### Prototype (throw-away, scratchpad, not committed)

I wrote the node part of step 2 for a given section list (intro steps 0.30-0.45, groove 0.60-0.70, break 0.45, breakdown 0.30-0.20-0.35, drop 0.90-0.95 and +0.05 from the second drop, build ramp, outro from `default_outro`) and ran it with the repo's checker:

| Check | Result (2026-11-02) |
| --- | --- |
| Section lists of `T1.json`, `T2.json`, `T3.json` with default settings | T1: all 31 nodes equal to the fixture. T2, T3: 36 and 34 nodes, equal except one value (0.9500000000000001 vs 0.95, see above). All three pass `plan_problems`. |
| 3000 random section sequences (intro, 0-6 random middle sections of any type and allowed length, outro), `change_grid` random 1-64, seed 1 | 0 problems from `plan_problems`. Includes build followed by build or by outro (the build stays flat there; consistent with the B3 consequence in INTERFACES). |
| `boundary_changes` of the generated intros (16, 32, 64 bars) and a 64-bar outro | at most 1 per boundary |

Limits: no drawn nodes, no element states, no `second_drop = ask`, one seed, and the checker is the only reference. This shows a total function exists for the node part; it is not a test of the real generator.

## 5. Testing generated plans (answers V6 and V2 of #139)

### 5.1 Why a plan-only test is empty

From the INTERFACES `settings` table and "Not in v0.1" (line 202):

| Setting | Visible in a v0.1 plan? |
| --- | --- |
| `intro_length`, `outro_length`, `breakdown_count`, `breakdown_length` | yes: section lengths / sequence (when the layout is generated) |
| `second_drop` | yes: node values of the second drop (`ask` needs a rule: _Interpretation_, produce `equal` and a warning, or refuse) |
| `build_kick`, `intro_outro_bass`, `breakdown_rumble` | no: element states only |
| `change_grid` | no: by decision it never moves a section or a node; it only gates where elements may switch |
| `pre_drop_gap`, `fills` | no: events only |

For the second group, "the setting changes the plan" is false by design, and "elements switch only on `change_points(plan)`" has nothing to talk about, because v0.1 stores no elements. The test in `tests/test_contracts_arrangement_plan.py` (`test_the_checker_never_reads_settings_beyond_the_schema`) says the same about its own limit. So V6/V2 need **a derived timeline** `derive_timeline(plan) -> {phrase element states, events}` that reads the plan and its settings. Whether that timeline is stored in the plan (contract v0.2, G3) or stays a code-level structure is a decision for the lead; the Live builder needs a stable shape, which argues for the contract.

### 5.2 Property tests (ranges, references)

Use the repo's fresh-seed helpers (`tests/support/kick_params.py`, CLAUDE.md "fresh seeds", #119) and report the seeds that ran.

| # | Property | Range | Independent reference |
| --- | --- | --- | --- |
| P1 | Every generated plan has `plan_problems == []`. | genre x bpm (20, 100, 136, 140, 146, 180, 999 and random) x every feasible `target_bars` x every value of each single setting (including `change_grid` 1-64) x seeded random combinations of all 11 settings | `plan_problems` is the oracle for validity only |
| P2 | Golden: default settings reproduce `T1/T2/T3.json` exactly. | the three templates at 140 bpm | the fixture files (hand-checked by the contract PR) |
| P3 | Fit: result has `total_bars == target_bars`, or the request fails with `length_infeasible` and its `nearest` values succeed. | all multiples of 8 from 32 to 1024 | brute force over all length combinations of the skeleton, written in the test; not the fitter's search |
| P4 | Drawn nodes survive: every drawn node is in the output with identical `pos`, `value`, order, `drawn: true`; undrawn nodes obey B2/B3; at most two per `pos`. | random drawn nodes, including 0 and 1 as values, `pos` on and between section boundaries, single nodes on a default pair, pairs on boundaries | expected node lists written by hand for curated cases, plus the checker for the random ones |
| P5 | Settings bite: for each of the five visible settings and each allowed value, the plan differs from the default plan exactly where the table in 5.1 says. | all allowed values | hand-written expectations (e.g. `second_drop = equal` gives the second drop the values of the first) |
| P6 (V6) | For every `change_grid` 1-64 (and every section layout of P1): sections and drawn nodes are identical to the plan at grid 8, and **every element switch in `derive_timeline` lies in `change_points(plan)`**. | grid 1-64 | an element table written in the test from the thresholds of planner note 5.1 (the existing test file already keeps such a second table) |
| P7 (V2) | Fills and the pre-drop gap start on the grid for every setting value; `fills = off` gives no fill events. | all `fills` x `pre_drop_gap` x grid values | hand-computed positions for curated plans |
| P8 | Outro and intro: at most 1 element change per 8-bar boundary in a default plan, for every `intro_length`/`outro_length`/`second_drop`. | all | `boundary_changes` plus a hand-listed expectation for the 64-bar outro (one threshold per boundary) |
| P9 | Determinism: two calls with equal requests give equal JSON text. | random requests | byte comparison |

P6-P8 depend on G4. P1-P5 and P9 can be written with G1+G2.

**Mutation checks to run (CLAUDE.md, "prove a test can fail"):** drop the B3 adjustment; skip the outro walk (use 4 evenly spaced steps); ignore `second_drop`; hard-code the grid to 8; count the grid from bar 1 instead of the section start; let a drawn node be overwritten by a default; change the fit tie-break; round node values differently. Each must turn at least one of P1-P8 red.

**What CI can test:** all of the above (pure Python, no Live). **What needs the user:** nothing in G1-G5; the sound of any default is not tested here and no sound claim is made.

## 6. How a plan would later reach Live (context only)

All 12 arrangement entries in `contracts/capabilities.json` are `unknown` (added by PR #150, check not yet run in Live): `song.create_midi_track`, `track.has_midi_input.get`, `track.arrangement_clips.get`, `song.is_playing.get`, `song.current_song_time.get`, `song.current_song_time.set`, `song.cue_points.get`, `song.cue_point.add_or_delete`, `song.cue_point.set_name`, `track.create_midi_clip`, `arrangement_clip.notes.add`, `arrangement_clip.notes.get` (12 entries with status `unknown`, counted by script on 2026-11-02). Under the capability rule none of them may become a tool until `tested`. This section therefore describes the shape of the connection, not what works.

1. **Plan** (this note) is data only.
2. **Derived timeline** (G4): per phrase which elements are in, plus events. Still data only.
3. **Build plan / dry run** (G6): a list of intended Live operations, each tagged with the capability id it needs and that capability's current status. Section starts map to arrangement time in beats as `(start_bar - 1) · 4` (4/4 is fixed in v0.1; this arithmetic is _Interpretation_; the unit "beats" is from the live-midi note, Q2). A locator for a section would use the cue-point calls; the live-midi note says adding a locator at an existing position deletes it, so the builder must read first. Placing clips at bar positions is **not exposed** in AbletonOSC today (same note, Q2) and sits behind the unknown `track.create_midi_clip`/arrangement extension entries. Automation lanes have no known route (that note, Q3; experiment E7).
4. **Execution** only for operations whose capability is `tested`, behind approval `confirm` (the Approval enum in `src/orchestrator/tools.py` has `routine` and `confirm`) and the D-006 undo layers; everything else stays "not yet verified". Only the kick exists as a sound source, so a first Live build could at most place kick clips; the other elements have no engine.
5. The generator never talks to Live; the builder never changes the plan.

## 7. Decomposition into issues (each small; WIP = 1 per role)

Owner for G1-G5 is `orchestrator-engineer` unless stated (D-024: planner owner). Names are working titles.

### G1 - Plan layout: genre skeleton and length fit
- **Scope:** `PlanRequest` validation (section 2.1/2.3 errors for genre, bpm, length, settings), minutes to bars, skeleton per genre, outro length, fit of elastic sections to `target_bars`, tiling. Returns sections + errors. Nodes are not produced yet.
- **Why:** the fit is the part with real choices (and with Q1/Q3); doing it first keeps the node work free of length logic.
- **Not in scope:** nodes, settings beyond their length effects, drawn nodes, CLI, tool, Live.
- **Done when:** for every multiple of 8 in 32..1024 and each genre the result is either a section list that satisfies the format's section rules or `length_infeasible` with `nearest` values that succeed (P3, brute-force reference in the test); error table 2.3 covered by one test per code; determinism (P9); mutants of the fit (tie-break, outro length, off-by-one) killed.

### G2 - Default energy nodes, settings effects and drawn-node overlay
- **Scope:** node defaults per section type (planner note 4 as amended by INTERFACES), `second_drop`, outro via `default_outro`, B2/B3, value rounding, overlay of `drawn_nodes`, final `plan_problems` gate, `adjustments`/`warnings`.
- **Why:** this makes a complete valid plan, and carries the "settings change plans" tests for the five visible settings.
- **Not in scope:** element states, events, `change_grid` effects (none in a v0.1 plan), UI, Claude tool.
- **Done when:** P1 (without P6), P2 (T1-T3 reproduced exactly), P4, P5, P8 for intro/outro, P9 pass with fresh seeds over the ranges in 5.2; mutation list of 5.2 reported (killed/survived, survivors explained); no new dependency.
- **Depends on:** G1.

### G3 - contract-change: plan format v0.2 with derived `events[]` and element states
- **Scope:** additive schema fields for what INTERFACES "Not in v0.1" lists as generator output: `events[]` (riser, impact, downlifter, fill, pre-drop gap; position and length in whole bars or beats) and per-phrase element states; checker rules for them (positions on `change_points`, no fill repeat, gap length from setting); fixtures; INTERFACES section; label `contract-change`. Strict-schema statement if Claude will send them (INTERFACES says plans are not a tool input).
- **Why:** V6/V2 are untestable without them (section 5.1), and the Live builder needs a stable input.
- **Not in scope:** the derivation itself, any generator change, sub-bar node positions, user-placed fills.
- **Done when:** schema valid 2020-12; positive and negative instances including T1-T3 with derived data; mutants killed; the user merges (contract-change). Decision for the lead first: contract field or code-level structure only (then G3 shrinks to an internal type and moves into G4).
- **Depends on:** G2 merged (so the fixtures match what the generator emits).

### G4 - Timeline derivation and the settings tests (V6, V2, V5)
- **Scope:** `derive_timeline(plan)`: element on/off per phrase from the thresholds and families of planner note 5.1-5.3, `build_kick`, `intro_outro_bass`, `breakdown_rumble`; events with `pre_drop_gap`, `fills` (off by default), riser/impact/downlifter rules of 5.4; gating by `change_points`. Property tests P6, P7, P8 and the monotonicity test V5 (raising energy inside a family never removes an element).
- **Why:** it is the only place where the six invisible settings can be tested for real instead of by construction.
- **Not in scope:** sounds, parameter ramps rendered to audio, writing to Live, new thresholds (they are proposals of the planner note; changing them is a user decision).
- **Done when:** P6-P8 and V5 green over the full ranges (grid 1-64 etc.); each setting value shown to change the timeline in the documented way (hand-written expectations); fault injection on thresholds, grid origin and gap length turns tests red; thresholds are imported from or compared with one table (`ELEMENT_THRESHOLDS`), the test keeps its own copy.
- **Depends on:** G2, G3.

### G5 - Entry points: CLI and Claude tool `plan_arrangement`
- **Scope:** `scripts/plan_arrangement.py`-style CLI that writes plan JSON (owner decision: bridge-engineer owns `scripts/`, so the CLI may be an orchestrator-side module instead); a strict tool schema with no optional parameters (section 3), approval `routine`, result with `adjustments`/`warnings`; where the plan lives (session table with a `plan_id` like `sample_id`, or a file; decision for the issue, no Live involved).
- **Why:** without it Claude cannot use the generator and the user cannot run it.
- **Not in scope:** drawn nodes from chat, the narrow edit tool (B7), planner window, any Live write.
- **Done when:** strict-subset checker passes on the built schema (INTERFACES "Strict subset"); optional-parameter total still within 24; tool refuses each error code of 2.3 with a model-facing text; a fake-model test shows a chat request becoming a plan; not reported as a Live test.
- **Depends on:** G2 (G4 for the timeline in the result). Wiring waits for the current Phase 04b tools to be merged so the budget is known.

### G6 - Live build plan (dry run), blocked
- **Scope:** `plan + timeline -> list of operations` with required capability id and current status from the registry; refusal when any status is not `tested`; no sending.
- **Why:** it fixes the interface between planner and bridge now, so the capability check result (#140) only has to flip statuses.
- **Not in scope:** sending anything to Live, automation lanes, clip content for elements without an engine.
- **Done when:** operations for T1-T3 listed with section start in beats; with all arrangement entries `unknown` the dry run reports every operation as blocked; property: no operation without a capability id; owner `bridge-engineer` for the Live-facing part (default owner of `src/bridge/`).
- **Depends on:** G4 and the user's run of #140 (`tested` statuses by `contract-change` with evidence). Do not start before.

## 8. Open questions for the user (only those that change the design)

**Q1 - Length versus the outro rule.** T2/T3 are 256 bars, longer than 7:00 at 136-146 BPM (computed from 240/bpm seconds per bar: 7:32, 7:19 and 7:01), because a full drop needs a 64-bar outro under "at most one element per boundary". What should the generator do by default?
- (a) Keep the outro rule; the 4-7 min window is only a warning (tracks of 7:01 to 7:32 for the long layouts).
- (b) Keep the outro rule and shorten other sections to stay at or below 7:00 (for example intro and groove 16 instead of 32 bars; the layout then loses 32 bars of the first half).
- (c) Allow two elements per boundary in the outro only when the window would otherwise be broken. This changes the 2026-11-01 decision for those cases.

**Q2 - Energy through chat in the first version.** The planner facts say energy is steered by drawing and by chat. Should chat already change energy in the first generator tool?
- (a) No. Chat sets genre, tempo, length and settings; energy comes from the planner window; a later edit tool ("second drop harder") follows. (Smallest; G5 as written.)
- (b) Yes, coarse: chat can say "lower / higher" for a named section and the code turns it into numbers within the soft range. (Adds an issue: the narrow edit tool with its own strict schema, and a rule for the numbers.)

**Q3 - Where does a second breakdown go?** `breakdown_count = 2` has no defined layout in the planner note (the maximum of 2 is marked _Interpretation_ there).
- (a) The first breakdown stays where T2/T3 have it (between drop 1 and build 2); the second replaces the short break (techno) or sits before the first build (trance), keeping the track length.
- (b) The second is added after drop 2, before a third build and drop (a longer track; _Interpretation_: well beyond 7:00 at the same outro rule).
- (c) Allowed only when the user places sections in the window; the generator with `breakdown_count = 2` and a genre only refuses with a clear message.

**Q4 - One plan or several to choose from?** For kicks the user listens to several variants.
- (a) One deterministic plan per request (no seed; smallest).
- (b) Up to three variants per request that differ in lengths and energy offsets within the allowed ranges, chosen by a seed (adds `seed`, tests per seed, and a rule for what may differ).

Not asked, because a default is enough for now: genre-specific energy shapes beyond the skeleton (the planner note's trance source C7 says elements arrive one at a time; v1 uses the skeleton difference only), and the soft-range warning for the default outro (a decision for the planner window issue).

## 9. Findings

| Finding | Confidence | Source |
| --- | --- | --- |
| The plan format has no element states or events; they are listed as "later additive contract change". | High | INTERFACES "Not in v0.1" (line 202); schema `$defs`: `section`, `energy_node`, `settings` only |
| Six of eleven settings cannot change a v0.1 plan beyond their echo; V6/V2 need a derived timeline. | High for the premise, _Interpretation_ for the consequence | INTERFACES `settings` table and "Grid"; test docstring in `tests/test_contracts_arrangement_plan.py` |
| T2/T3 at 256 bars are 7:01-7:32 for 136-146 BPM; T1 (192) is 5:16-5:39. | High (arithmetic) | computed 2026-11-02 with 240/bpm s per bar; planner note section 2 formula |
| `default_outro` returns 64 bars from a start value of 0.65 and above, 32 bars from 0.40 to 0.64, 16 bars below 0.40. | High (run) | `default_outro` called on 23 start values, 2026-11-02; matches INTERFACES "The outro gets longer when needed" |
| Node values produced with `+ 0.05` need rounding (0.9500000000000001). | High (run) | prototype, 2026-11-02 |
| A deterministic node builder for any valid section list passes the checker (3000 random lists, grid 1-64). | Medium (prototype only, no drawn nodes, one seed) | prototype, 2026-11-02 |
| The strict optional-parameter budget is exhausted, so a planner tool needs required parameters only. | High for the budget (repo), low for how arrays of objects are counted | INTERFACES line 81; tool-schema note (WebFetch-based) |
| Arrangement clip placement, automation and locator writes are `unknown`/unexposed today. | High | `contracts/capabilities.json` (12 entries `unknown`); live-midi note Q2/Q3 |

## 10. Implications for the lead

- Open G1-G5 as `orchestrator-engineer` issues in the order G1, G2, G3 (after the lead decides contract field vs code structure), G4, G5; keep G6 as a blocked issue linked to #140.
- Hand Q1-Q4 to the user together; Q1 and Q3 gate G1, Q2 gates G5, Q4 gates G2's interface.
- Put the V6/V2 hand-over of #139 into G4's "Done when" explicitly; without G3/G4 the format PR's own docstring (the checker "never reads settings") stays the honest limit.
- No change to a decision is proposed. D-024 point 3 (every style choice a setting) is what makes six settings invisible in v0.1; that is a consequence, not a conflict.
- Side finding candidates (not opened by me): none beyond the already known #186.

## State update proposal (for the PR body)

"Research note `docs/research/2026-11-02_arrangement-plan-generator-design.md`: draft for the plan generator (interface, split G1-G6, property tests, Live context). Finds that V6/V2 need a derived timeline, and that T2/T3 exceed 7:00 at 136-146 BPM. Not implemented, nothing run in Live; four user questions (Q1-Q4) open."
