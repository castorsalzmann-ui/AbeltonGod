# PHASE 05 — Kick character

**Status:** IN PROGRESS · **Agents:** `audio-engineer`, `sound-designer` (+ `bridge-engineer` for two-track layering) · **Tested in:** CI + user listening tests + user's machine

## Objective

Kicks with their own character instead of "well made, rather generic" (user, listening test #3): more body and density, key-matched, length matched to the tempo, and two kicks that can be layered without losing bass.

## Prerequisites

Phase 01 accepted. Listening tests 1 and 2 (#103) done. Questionnaire tab "1 Klang erzeugen" answered (D-022).

## Scope

1. Preset `dense` (`centre` + drive 0.45) — the user's choice in listening tests 1 and 2 (#116).
2. kick-params v0.3 contract (#104): `tail_note`, `length_beats` (rule a: automatic decay so the kick is −60 dB before the beat end), `polarity`, `offset_ms`, `clip_db`, `click_decay_ms`, `click_q` — field list decided by the user on PR #114.
3. Engine implementation of the v0.3 fields (#120).
4. Layering: two chosen kicks matched (level, offset, polarity, no bass loss), delivered as two WAVs; later as two tracks in Live.
5. Reference kicks: measure the user's 3–5 "main character" kicks and compare with the presets (files stay outside the repo; only audio content counts).
6. Machine-readable listening and choice log as the base of the sound profile (#110).

## Out of scope

Other sample categories, generative audio (D-005), arrangement, mixing.

## Acceptance criteria

- [x] Listening test 1 and 2 run and decoded (#103, 2026-10-29).
- [ ] Preset `dense` renders byte-identical to the file the user chose (#116).
- [ ] kick-params v0.3 contract merged by the user (#104).
- [ ] v0.3 fields implemented; v0.2 renders byte-identical (#120).
- [ ] Layering: for the preset pairs from #57, the matched sum loses no energy below 100 Hz.
- [ ] User-verified: the user uses an AbeltonGod kick in a real track instead of a library kick (questionnaire answer 8).
