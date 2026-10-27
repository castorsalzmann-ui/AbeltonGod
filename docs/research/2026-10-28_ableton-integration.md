# Research: Ableton Live integration options

_Date: 2026-10-28 · Sources opened on this date. Re-verify version-dependent claims before relying on them._

## Findings

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| 1 | All programmatic access to Live goes through the Live Object Model (LOM), reached from Max for Live or from Python control-surface (Remote) scripts. Not every Live function is in the LOM. | High | [Ableton: Controlling Live using Max for Live](https://help.ableton.com/hc/en-us/articles/5402681764242-Controlling-Live-using-Max-for-Live), [Cycling '74: Live API overview](https://docs.cycling74.com/userguide/m4l/live_api_overview) |
| 2 | Max for Live needs Live Suite or a paid add-on — not available to this user (Live 12 Standard). | High | Ableton product info (see #1) |
| 3 | AbletonOSC is an MIT-licensed remote script exposing LOM functions over OSC, Live 11+. Listens on 11000, replies on 11001. Install into `Documents\Ableton\User Library\Remote Scripts\AbletonOSC`, then select it as Control Surface in Preferences → Link/Tempo/MIDI. | High | [AbletonOSC README](https://github.com/ideoforms/AbletonOSC) |
| 4 | AbletonOSC includes `/live/song/undo` and `/live/song/redo`. | High | AbletonOSC README |
| 5 | Remote scripts run on Live's GUI thread; one report gives 1–16 ms jitter. Fine for control, not for audio timing. | Medium (older report) | [vvvv.org LiveOSC notes](https://vvvv.org/contribution/livvvveosc) |
| 6 | Live allows 6 control-surface slots. | Medium (forum) | [Cycling '74 forum](https://cycling74.com/forums/combine-multiple-midi-remote-scripts-in-max-to-free-up-slots-in-ableton) |
| 7 | Export/render cannot be triggered via the API; community projects use resampling/virtual routing or manual export. Devices cannot be reordered in a chain via the API. | Medium (project docs) | [AbletonMCP on Glama](https://glama.ai/mcp/servers/shymbsx7uh) |
| 8 | **`ClipSlot.create_audio_clip(path)`** creates a Session-view audio clip referencing an absolute file path. Errors if the slot is not on an audio track or the track is frozen. Forum reports: works from **Live 12.0.5**, failed on Live 11 and early 12.0.x. Track-level variant not confirmed. | Medium–high | [LOM ClipSlot reference](https://docs.cycling74.com/apiref/lom/clipslot/), [Cycling '74 forum thread](https://cycling74.com/forums/function-createaudioclip-class-clipslot-and-track-missing-lom) |
| 9 | AbletonOSC's README does **not** list `create_audio_clip` (only `/live/clip_slot/create_clip` for empty MIDI clips). Phase 03 needs a small handler in our own remote-script extension. `/live/application/get/version` returns only major/minor, so the ≥ 12.0.5 check needs Help → About Live. | High (README checked) | [AbletonOSC README](https://github.com/ideoforms/AbletonOSC) |
| 10 | Several community MCP servers already connect Claude to Live via AbletonOSC or a custom remote script, which shows the route works in practice. | High | [ableton-live-mcp-server](https://github.com/Simon-Kansara/ableton-live-mcp-server), [AbletonMCP](https://github.com/jpoindexter/ableton-mcp) |

## Implications

- Bridge = AbletonOSC-based remote script (D-001).
- Phase 03 can likely import samples automatically on Live ≥ 12.0.5 via `create_audio_clip`; must be tested on the user's exact Live version. Fallback: drag-and-drop from the project's `Samples/` folder.
- Check the user's exact Live version (Help → About Live) at the start of Phase 02.
