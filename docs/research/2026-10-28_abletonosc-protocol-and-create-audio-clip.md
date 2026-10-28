# Research: AbletonOSC wire protocol and a `create_audio_clip` handler

_Date: 2026-10-28 · Issue #4 · Source: [AbletonOSC](https://github.com/ideoforms/AbletonOSC) at commit
`0ca68214bd62c9b5cb641ca34006cfd70ba94430` (2025-11-19), read in full for the files cited below.
Nothing here was run inside Ableton Live; Live behaviour is verified in #5 on the user's machine._

## Protocol facts the OSC client relies on

| # | Fact | Source (file, location) |
| --- | --- | --- |
| 1 | Listens on UDP 11000, replies on 11001. | `abletonosc/constants.py`; README "Usage" |
| 2 | A reply goes to the **sender's host** on the **fixed** port 11001, not to the sender's port. A client must bind 11001 to receive anything. | `abletonosc/osc_server.py`, `process_message` (`response_addr = (remote_hostname, self._response_port)`) |
| 3 | A query is answered on the same address it was sent to. There is no request id. Getters built with `_get_property` echo extra params after the value. | `osc_server.py` `process_message`; `handler.py` `_get_property` returns `(value, *params)` |
| 4 | Methods and setters (`/live/song/undo`, `/live/track/set/mute`, `/live/song/create_audio_track`) return `None` → **no reply**. | `handler.py` `_call_method`, `_set_property`; `song.py` method list; `track.py` `properties_rw` |
| 5 | `/live/test` shows "Received OSC OK" in Live and replies `'ok'`. | `manager.py` `test_callback`; README Application API |
| 6 | Unknown addresses and exceptions in a handler are logged at ERROR; an ERROR log record is relayed as `/live/error <message>` (text after the first `": "`). | `osc_server.py` `process_message` / `process`; `manager.py` `LiveOSCErrorLogHandler` |
| 7 | The socket is polled once per ~100 ms tick on Live's main thread; all queued datagrams are processed in order. An exception stops the loop for that tick; the rest is processed next tick. | `manager.py` `tick`; `osc_server.py` `process` |
| 8 | On startup AbletonOSC sends unsolicited `/live/startup` and `/live/application/get/average_process_usage`. | `application.py` `init_api` |
| 9 | `/live/application/get/version` returns `(major, minor)` only — no patch level. | `application.py` `get_version` |
| 10 | Logs: `logs/abletonosc.log` inside the installed `AbletonOSC` folder. | `manager.py` `start_logging`; README "Installation" |

Client consequences (implemented in `src/bridge/osc_client.py`):

- Bind 11001 and send from that socket. Serialise requests (one lock).
- **Request bracketing.** There is no request id (fact 3), and when Live's main thread is blocked (a dialog, a heavy set load), queued requests are processed late but in order (fact 7). A first version confirmed writes with `/live/test 'ok'`. Review found that a late `'ok'` from an earlier, timed-out write could then confirm a later write that failed in Live. A grace period only narrows that window. The current client sends every request as `marker(start) + payload + marker(end)`. A marker is `/live/song/get/tempo <nonce>`, and the getter echoes the nonce (fact 3). Only messages between the echo of `start` and the echo of `end` belong to the request. Everything before `start` — late replies or `/live/error` from earlier requests — is discarded.
- A write is confirmed only by the echo of its own `end` marker with no `/live/error` in between. A query whose `end` echo arrives without a matching reply is a protocol error (decided at once, no timeout).
- Before each request, queued datagrams and stale Windows ICMP resets are drained. This is not needed for correctness, but a stale reset would otherwise fail a healthy request.

Assumptions and limits:
- Loopback UDP keeps datagram order. The OS does not promise this; no reordering is known on loopback.
- The marker echo (fact 3) is read from source and **must be confirmed on the user's machine in #5**. If it does not hold, every request times out: the failure is closed, never a false success.
- **A timed-out write has an unknown outcome.** It may still sit in Live's queue (e.g. behind a dialog) and be applied after the client gave up. Seen in review with the fake: two writes timed out, both were applied after the release. Callers (first: `bridge_check.py` in #5) must read the state back before assuming nothing happened, and must never send an undo blindly after a timeout — it could undo something else.
- A confirmation shows that AbletonOSC processed the write without an error it reported. It does not show that Live's state changed as intended. Where it matters, read the value back.
- `/live/song/get/track_names` returns all names in one datagram; extremely large sets could exceed it.

## `ClipSlot.create_audio_clip`

**Finding.** Not exposed by AbletonOSC. The clip-slot handler registers only `fire`, `stop`, `create_clip`, `delete_clip` as methods (`abletonosc/clip_slot.py`, `methods` list), and `git log -S create_audio_clip` over the full history returns nothing. This confirms finding #9 of `2026-10-28_ableton-integration.md`, now from source rather than the README.

**LOM side** (from the earlier note, not re-verified): `ClipSlot.create_audio_clip(path)` takes an absolute file path, errors on non-audio or frozen tracks, reported working from Live 12.0.5.

### Options for the smallest extension (design only — not built)

| | A: one-word patch to AbletonOSC | B: own remote script in a second slot |
| --- | --- | --- |
| Change | Add `"create_audio_clip"` to the `methods` list in `abletonosc/clip_slot.py`. The generic `_call_method` then calls `clip_slot.create_audio_clip(path)` with `params[2:]`. | A minimal `AbeltonGodExt` control surface listening on its own port (e.g. 11002) with one handler. |
| Code | 1 line in a third-party install, applied by a small script that checks the pinned commit first. | ~60–100 lines plus its own OSC socket loop (AbletonOSC's server code is MIT and could be reused with attribution). |
| Address | `/live/clip_slot/create_audio_clip track_index, clip_index, path` → no reply. | Own address, can return a confirmation. |
| Errors | LOM exceptions are relayed as `/live/error` (fact 6). | Own handling. |
| Upkeep | An AbletonOSC update overwrites the patch; the script must re-apply and verify. | Independent of AbletonOSC updates; uses one more of the 6 control-surface slots (all free). |

**Recommendation for Phase 03: A**, because it is the smallest change and reuses the error path the client already handles. The client side stays capability-gated (`clip_slot.create_audio_clip`, currently `unknown`) and does three things AbletonOSC will not:

1. Validate before sending: absolute path, file exists, `.wav`, inside `SAMPLE_LIBRARY_ROOT`, target track is an audio track (`/live/track/get/has_audio_input`) and the slot is empty (`/live/clip_slot/get/has_clip`).
2. Send with `send_confirmed`; a `/live/error` means failure.
3. Read back `/live/clip_slot/get/has_clip` and expect `True`.

Switch to **B** if the user's AbletonOSC install turns out to be updated often, or if A fails on their machine. Either way, the capability may only become `tested` after the user's run in Phase 03.

**Licence note.** The repo README says AbletonOSC is used as an external dependency, not copied. Option A keeps that (a patch applied to the user's install). Option B, if it reuses AbletonOSC code, must carry its MIT notice.

## Open points for #5 / Phase 03

- Confirm the marker echo: `/live/song/get/tempo abc` must answer `(tempo, 'abc')`. `bridge.ping()` exercises exactly this.
- On Windows: confirm that a closed Live gives `LiveNotReachableError` (ICMP reset) rather than a timeout, and that a second client on 11001 gets `ReceivePortInUseError`. CI covers both only on Linux or with a simulated reset.

- Confirm on the user's machine that `/live/error` arrives for an unknown address (fact 6) — the client depends on it for fast failure.
- Note the exact Live version (Help → About Live); fact 9 means the client cannot read the patch level.
- Check whether a frozen or group track gives a readable `/live/error` text for `create_audio_clip`.
