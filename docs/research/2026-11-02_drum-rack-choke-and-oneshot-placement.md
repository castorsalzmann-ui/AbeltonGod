# Research: placing one-shots as a drum kit in Live 12 Standard (Drum Rack, choke groups)

_Date: 2026-11-02 · Refs #151 · Researcher B. Sources opened 2026-11-02. Nothing here was run in Live. Related: [next-category](2026-11-02_next-category-proposal.md), [hat-synthesis-design](2026-11-02_hat-synthesis-design.md) section 3 (its "Drum Rack choke unverified" item is answered here), [AbletonOSC protocol](2026-10-28_abletonosc-protocol-and-create-audio-clip.md), [MIDI/devices](2026-10-29_live-midi-arrangement-devices.md) Q4, [desktop window](2026-10-29_desktop-window-windows.md) V4._

## For workers

- **Possible?** The Drum Rack and its choke groups are documented. A kit is possible today by hand. By code it is only partly reachable: AbletonOSC has **no** chain or pad access, so every code route needs a new handler in a patch or second remote script (the existing "option A/B" mechanism).
- **Today's tested path is enough for the first drum use:** `clip_slot.create_audio_clip` (tested) puts each one-shot as a clip on an audio track. That gives loops/clips, not a playable kit. Do not wait for Drum Rack automation to ship hats or clap.
- **Choke:** Live's choke group is a per-chain setting (16 groups, UI "Choke" chooser). The LOM has `DrumChain.choke_group` (get/set/observe). It replaces a mutual cut between samples; the hat `choke_ms` render option only truncates one sample. Keep both, see section 3.
- **Recommended route:** (1) user builds the kit by hand with a recipe (section 5), no code; (2) a read-only probe of Drum Rack chains; (3) only then write access (`choke_group`, loading a sample into a pad). Each new capability stays `unknown` until the user's run.
- **Read first:** section 2 table and section 4 issue list; `contracts/capabilities.json` (no Drum Rack entry exists).
- **Effort:** probe small, write path medium, full "build a kit from files" medium to large (pad creation and sample loading are unverified).
- **Blockers:** (a) nothing in the registry covers devices, chains or pads; (b) whether the Python remote-script API exposes the same classes as the Max LOM pages is an inference, not read from a Live install; (c) Live 12.4.5 is the user's version, and `in_note`/`insert_device` need 12.3+, `replace_sample` 12.4+.
- **User questions:** none blocking. One preference: should the first kit be built by the user's hand (recipe) before any write code? (recommended: yes)

## 1. What Live offers for one-shots in a Drum Rack

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| 1 | Each pad is one of the 128 MIDI notes; the visible pads move in groups of 16. A chain's **Receive** chooser sets the note it answers; if several chains share a Receive note, that pad triggers all of them. | high (manual) | [Manual: Instrument, Drum and Effect Racks, "Pads and MIDI Notes"](https://www.ableton.com/en/manual/instrument-drum-and-effect-racks/) |
| 2 | Dropping a sample on an **empty pad creates a chain with a Simpler** holding that sample. Dropping another sample on the pad replaces Simpler and sample, keeping downstream audio effects and upstream MIDI effects. A multi-selection maps Simplers chromatically upward from the target pad. | high (manual) | same page, "Samplers per Pad" and "Dragging Samples and Devices onto Pads" |
| 3 | **Choke:** each chain can be assigned to one of **sixteen choke groups**; triggering one chain of a group silences the other chains of that group. The manual's own example is closed hat choking open hat. If Receive is "All Notes", the Play and Choke choosers are disabled. | high (manual) | same page, "Choke Groups", "Pads and MIDI Notes" |
| 4 | Where it is set in the UI: the Choke chooser in the chain list of the Drum Rack. (The page names the "Choke" chooser; the exact on-screen position was not shown in the text I read.) | medium | same page |
| 5 | Live 12.3 added `DrumChain.in_note` (get/set/observe; -1 = "All Notes"); release notes say Drum Racks are *created* with In Note "All Notes" (-1). | medium (summarising fetch of the release notes) | [Live 12 release notes](https://www.ableton.com/en/release-notes/live-12/) |
| 6 | Newer Live 12 has a **Drum Sampler** device as an alternative to Simpler on a pad ("Save as Default Pad" makes new samples on empty pads load a Drum Sampler). It has Trigger mode (plays for the Hold time after note release; Hold can be "inf") and Gate mode (fades by Decay after note release). Which Live version introduced it, and whether Standard includes it, was **not found** in the text I could read. | medium for behaviour, unknown for edition | [Manual: Instrument Reference, 31.4.1 and 31.4.5](https://www.ableton.com/en/manual/live-instrument-reference/) |
| 7 | Simpler's One-Shot/Gate behaviour was **not readable** in the part of the manual I got (the fetch was truncated before it). Not claimed. | n/a | same |
| 8 | Drum Rack return chains: sends for up to six return chains. Not needed for the first kit. | high | Racks page |

## 2. Programmability (LOM / AbletonOSC) and the tested path

| Need | Route | Evidence | Registry status to use |
| --- | --- | --- | --- |
| Put a sample into Live as a clip (loop, clip, per-sample track) | `clip_slot.create_audio_clip` | already `tested` | `tested` (no change) |
| Detect a Drum Rack on a track | `/live/track/get/devices/class_name` exists in AbletonOSC ([README](https://github.com/ideoforms/AbletonOSC), Track section). The class name a Drum Rack reports was **not looked up**; read it on the user's machine, do not hard-code. | high that the call exists, unknown for the value | candidate `track.devices.class_name.get`: `unknown` |
| Read chains, `in_note`, `choke_group` | LOM `DrumChain` has `in_note`, `out_note`, `choke_group`, each get/set/observe ([LOM DrumChain](https://docs.cycling74.com/apiref/lom/drumchain/)). AbletonOSC `device.py` registers only `class_name`, `name`, `type` and parameter handlers; no chain/pad index anywhere (checked on the raw source today, raw.githubusercontent.com `device.py`, master). The README lists nothing on chains either. So a new handler is needed. | high (LOM doc, source), the handler design is inference | candidate `drum_rack.chain.choke_group.get`: `unknown` |
| Set `choke_group` | same property, set access | LOM doc; no run | candidate `drum_rack.chain.choke_group.set`: `unknown` |
| Mute / solo a pad | `DrumPad.mute`, `solo` get/set ([LOM DrumPad](https://docs.cycling74.com/apiref/lom/drumpad/)); `note` get-only | high (doc) | not needed now |
| Create the Drum Rack on a track | `Track.insert_device(device_name)` since 12.3, native devices only, throws on failure ([LOM Track](https://docs.cycling74.com/apiref/lom/track/), see MIDI note Q4; the 12.3 release-note entry was a summarising fetch). Under Standard a name outside Standard should fail: to verify. | medium | candidate `track.insert_device`: `unknown` |
| Put a sample on a pad | **No direct LOM call found.** Candidate routes, all unverified: (i) `Chain.insert_device` ([LOM Chain](https://docs.cycling74.com/apiref/lom/chain/), 12.3+) for a Simpler plus `SimplerDevice.replace_sample(path)` (12.4+, release notes) once a chain with `in_note` exists; whether a chain can be created on a Drum Rack by code (`RackDevice.insert_chain` named in the 12.3 notes) is **unknown**; (ii) browser `load_item` (Python-only, unofficial, see MIDI note Q4); (iii) the user drags files (desktop-window note V4). | low | candidate `drum_rack.pad.load_sample`: `unknown` |

Whether the Python remote-script API offers the same classes and properties as the Max LOM pages is **inferred** (the earlier notes also rely on it). The first probe must confirm it.

**Does the tested path suffice?** For loops and clips: yes. A hat or clap one-shot can already be a clip on an audio track; a pattern would be many clips or a rendered loop. It does **not** give a kit: a clip is one fixed sound at one trigger, there is no per-note retrigger, no choke between hats, and MIDI cannot play it. For "play it as a drum kit" the Drum Rack (user-built or later code-built) is needed. The imports already written under `<project>\Samples\Drums\<Category>\` are exactly what the user drags onto pads, so the library layout needs no change.

## 3. Choke for closed/open hat

- **Live's choke group** = a cut between two chains at trigger time. Group both hat chains in the same group number and the closed hat silences a ringing open hat (manual example). Because the group is symmetrical as the manual states it ("other chains in that group are silenced"), an open hat also cuts a closed-hat tail; for short closed hats this is probably inaudible (inference).
- **Hat `choke_ms`** ([hat design](2026-11-02_hat-synthesis-design.md) section 3) = a fixed truncation inside one sample (5 ms fade at `choke_ms`). It cannot react to a later trigger.
- **They are not alternatives.** In a Drum Rack, render the open hat with `choke_ms = 0` (full tail) and let the choke group cut it at the right time. `choke_ms` stays useful for a stand-alone open hat in a clip (no Drum Rack) or for a fixed short "half-open" sound. A pattern-level cut in a clip loop needs the render option; in a Drum Rack it needs the choke group.
- **How long Live's cut takes, and whether it clicks, is not documented in the pages I read.** Needs the user's ears (section 5, step 4). Never claim it sounds clean.

## 4. Recommended issue sequence (bridge-engineer; none implemented, none claimed tested)

1. **D0 recipe + observation (no code).** Doc `docs/setup/` page with the user recipe below and a table to fill in (Live version, class name seen, choke audible yes/no). *Done when:* the user posts the filled table on the issue.
2. **D1 read-only probe.** New handler (patch or second script, per the earlier option A/B decision) returning, for one Drum Rack device, the chain list with name, `in_note`, `out_note`, `choke_group`. Capabilities added as `unknown`. *Done when:* unit tests with the fake OSC server pass in CI (labelled as not an Ableton test); the user's run on a hand-built kit prints the real values and `drum_rack.chain.choke_group.get` becomes `tested` in its own `contract-change` PR with the log excerpt.
3. **D2 set `choke_group` with read-back.** Only on a Drum Rack the user built; validate group range (UI shows 16 groups; the LOM page gives no range, so also read the real range in D1); read back; undo behaviour measured, not assumed. *Done when:* the user's run shows set, read-back equal, hat choke audible, and undo result as seen; capability `tested` only then.
4. **D3 (optional, last) build a kit from files.** Probe feasibility of creating a rack and chains and loading a sample (section 2, last two rows) before any promise; may end as "not possible without the user's drag". *Done when:* a written verdict from the user's run, or a reduced scope agreed with the lead.

## 5. User test recipe (Windows PC, Live 12 Standard)

1. Create a MIDI track, load a **Drum Rack** (Browser > Drums). Drag a closed-hat WAV from `<project>\Samples\Drums\...` onto one pad and an open-hat WAV onto the next pad. Note which device Live puts on each pad (Simpler or Drum Sampler) and whether you had to enable anything: this answers the edition question of finding 6.
2. In the Drum Rack chain list, set the **Choke** chooser of both chains to the same group (e.g. 1). If the chooser is greyed, check that Receive is not "All Notes".
3. Play the open hat, then the closed hat while it rings. Write down: does the open hat stop? Do you hear a click at the cut?
4. Play the closed hat first, then the open hat. Write down whether the closed tail is cut.
5. Help > About Live: write down the version.
6. Report the five answers on the issue. Nothing else to run; no code is involved.

## Pitfalls

- A Drum Rack's chains start with In Note "All Notes" (release notes, medium), so Choke is greyed until a note is chosen.
- Two chains with the same Receive note both play (finding 1): a user kit with duplicate notes can double-trigger.
- AbletonOSC replies carry no request ids; chain lists would need the same bracketing the client already uses (protocol note, fact 3).
- Fetches of ableton.com were answered through a summarising tool, so wording is paraphrased and not spot-checked; the Instrument Reference page was truncated at about 100,000 characters (Simpler modes unread).

## Test strategy hints

- **CI:** handler argument/response shape against the fake OSC server; capability-gate behaviour (refuse while `unknown`); rendering open hat with `choke_ms = 0` and full length.
- **User's machine:** everything that touches a Drum Rack, class names, range of `choke_group`, undo, audible cut quality.

## Implications for the lead

- Answer for #151 hats: no Drum Rack automation is needed to ship hats; the user can place hats by hand. Offer the recipe in the hat listening material.
- The registry has no device/chain entries; D1 would be the first `contract-change` for them (owner: bridge-engineer).
- Suggested State update line: "Research: Drum Rack choke groups documented (16 groups per chain, LOM `DrumChain.choke_group` get/set); AbletonOSC has no chain access; nothing run in Live."
- Not opened: whether a Max-for-Live route exists is irrelevant (rejected by D-001).

## Open questions (user)

None blocking; answers to the recipe in section 5 would settle findings 4, 6 and the cut quality.
