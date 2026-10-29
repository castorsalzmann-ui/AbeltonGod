# Research: a small desktop window for the copilot on Windows

- **Date:** 2026-10-29. All web sources retrieved on 2026-10-29.
- **Versions researched against:** Windows desktop APIs as documented on learn.microsoft.com (RegisterHotKey: min. client Windows Vista; low-level hook timeout rule: Windows 10 1709+). Ableton Live 12 manual (web, no build stamp; the user runs **Live 12.4.5**, `CURRENT_STATE.md`). Python **3.14.4** on the user's machine (`CURRENT_STATE.md`). Packages as listed by the PyPI JSON API on 2026-10-29: `PySide6` / `PySide6-Essentials` **6.12.0**, `PyQt6` 6.12.0, `wxPython` **4.3.2**, `pywebview` **6.2.1** (needs `pythonnet` 3.2.1 on Windows), `tkinterdnd2` **0.7.0**, `pynput` 1.8.2, `keyboard` 0.13.5, `pywin32` 312, `pytest-qt` 4.5.0, `qasync` 0.28.0, `dearpygui` 2.3.1, `flet` 1.0.5. Qt docs pages are Qt **6.12.0**; wxPython docs 4.3.2; pynput docs are titled **1.7.6** (older than the 1.8.2 release).
- **Receiving issue:** #99 (D-023 research cluster 2; questionnaire tab 3, task B1). Rules: D-019 point 3, D-023.
- **Existing notes checked:** `docs/research/` has no note on a desktop UI, hotkeys or drag-and-drop. [`2026-10-28_ableton-integration.md`](2026-10-28_ableton-integration.md) row 8 / Implications names drag-and-drop from `Samples/` as the fallback if `create_audio_clip` fails. This note adds the outside-Live side of that fallback.
- **Not covered here (other clusters):** Live functions over OSC, kick placement in tracks, mix targets, AI audio.
- **Interpretation** is marked _(interpretation)_. Everything else paraphrases the cited source.

## Short answers

| # | Question | Answer in one line | Confidence |
| --- | --- | --- | --- |
| 1 | Window options | Four realistic routes: **Tkinter** (stdlib, no new dependency), **PySide6** (LGPL, ≥ 84 MB of wheels for `PySide6-Essentials` + `shiboken6`), **wxPython** (wxWindows licence, ~20 MB wheel), **pywebview** (BSD, needs pythonnet + WebView2). All can keep a window on top. Every Python route can run in the same process as the orchestrator. No source gives startup times; measure them. | High for licence/size/on-top; startup not established |
| 2 | Global hotkeys while Live has focus | Possible. `RegisterHotKey` defines a system-wide hotkey and fails if the combo is already taken. Live 12 uses many Ctrl/Alt/Shift combos. Ctrl+Alt+Shift has only two Live shortcuts (F, E), so free Ctrl+Alt+Shift+letter combos exist. No Microsoft page says whether the key also reaches Live. | High for the API and Live's list; pass-through unverified |
| 3 | Drag from our window into Live's clip slots | Live accepts file drops from Explorer. A Windows file drag is the `CF_HDROP` format. Qt, wxPython and tkinterdnd2 can each act as a file-drag source. A third-party desktop app (Splice) documents dragging samples into Live tracks. No source shows a drop **on a specific Session clip slot** from a non-Explorer app. Both programs must run at the same privilege level. | Medium; slot-level drop unverified |
| 4 | Effort, risks, CI | Tkinter: small to medium. PySide6: medium. wxPython: medium. pywebview: medium to large (no documented file drag-out). Electron: large. CI can test logic, widget state and the hotkey registration call. It cannot test the drop into Live, focus behaviour with Live, or how the window looks. | Medium (interpretation from the sources) |

## Question 1 — Options for a small always-on-top / second-screen window that talks to our Python backend

**Answer.**

| Option | Licence | Download size (win_amd64, PyPI 2026-10-29) | Always on top | Talks to backend | Source |
| --- | --- | --- | --- | --- | --- |
| **Tkinter** (Tcl/Tk) | Python: PSF; Tcl/Tk: permissive BSD-like terms (use, modify, redistribute, also commercially, if the notice is kept) | 0 extra. Part of the python.org installer as optional feature `Include_tcltk` (default 1). Not in the embeddable package. The page does not say for the new Python install manager. | `wm attributes -topmost` ("displays above all other windows"), all platforms; `-toolwindow` on Windows | Same process; Tk mainloop on one thread | [Tk wm](https://www.tcl-lang.org/man/tcl8.6/TkCmd/wm.htm), [Tcl/Tk licence](https://www.tcl-lang.org/software/tcltk/license.html), [Python 3.14 on Windows](https://docs.python.org/3.14/using/windows.html) |
| **PySide6** (Qt 6.12) | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | `PySide6-Essentials` 82.2 MB + `shiboken6` 1.3 MB (+ `PySide6-Addons` 40.5 MB, WebEngine, Pdf if the meta-package `PySide6` is installed). abi3 wheels, `requires_python <3.16,>=3.10`. | `Qt::WindowStaysOnTopHint` (top-level windows only) | Same process; `qasync` (BSD-2-Clause, 0.28.0) can merge asyncio with the Qt loop | [PyPI JSON](https://pypi.org/pypi/PySide6-Essentials/json), [Qt window flags example](https://doc.qt.io/qt-6/qtwidgets-widgets-windowflags-example.html), [PyPI qasync](https://pypi.org/pypi/qasync/json) |
| PyQt6 | GPL-3.0-only (commercial from Riverbank) | 7.0 MB + `PyQt6-Qt6` (size not queried) | same as Qt | same as Qt | [PyPI JSON](https://pypi.org/pypi/PyQt6/json) |
| **wxPython** 4.3.2 | `LGPL-2.0-or-later WITH WxWindows-exception-3.1` | 19.7 MB, cp314 wheel exists; depends on `numpy` (already ours) | `wx.STAY_ON_TOP` frame style ("stay on top of all other windows"); `wx.FRAME_TOOL_WINDOW` (small title bar, not in the taskbar). The fetched page labelled these as 4.2.3 docs. | Same process | [PyPI JSON](https://pypi.org/pypi/wxPython/json), [wx.Frame](https://docs.wxpython.org/wx.Frame.html) |
| **pywebview** 6.2.1 | BSD-3-Clause | 0.5 MB + `pythonnet` 3.2.1 (MIT, wheel tagged cp311–cp315) + Edge WebView2 Runtime | `create_window(on_top=True)`, also settable at runtime; `focus=False` makes a window that cannot take focus | `js_api` / `window.expose` call Python from JavaScript (basic types only) | [pywebview API](https://pywebview.flowrl.com/api/), [PyPI pywebview](https://pypi.org/pypi/pywebview/json), [PyPI pythonnet](https://pypi.org/pypi/pythonnet/json) |
| Electron / other web shells | — | Node runtime next to Python | — | Separate process; local HTTP/WebSocket to Python _(interpretation)_ | [Electron file drag](https://www.electronjs.org/docs/latest/tutorial/native-file-drag-drop) |
| Dear PyGui 2.3.1 (MIT, 1.9 MB), Flet 1.0.5 (Apache-2.0) | — | — | not researched further: no source opened today shows that either can drag a file out to another app | — | [PyPI dearpygui](https://pypi.org/pypi/dearpygui/json), [PyPI flet](https://pypi.org/pypi/flet/json) |

- **Windows window behaviour, independent of toolkit.**
  - A topmost window stays above all non-topmost windows, even when it is not active.
  - `WS_EX_NOACTIVATE`: clicking the window does not make it the foreground window.
  - `WS_EX_TOOLWINDOW`: a floating-toolbar style, hidden from the taskbar and Alt+Tab.
  - Sources: [SetWindowPos](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos), [Extended window styles](https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles). Confidence: high.
- **WebView2 Runtime.** Microsoft says the runtime "will be included" in Windows 11 and is on "the vast majority" of Windows 10 devices. It advises checking for it at startup (registry key or `GetAvailableCoreWebView2BrowserVersionString`). [WebView2 distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution) Confidence: high.
- **Startup time.** None of the sources gives a figure. Not measured in this task: CI and this sandbox are not the user's Windows machine. → V1.
- _(interpretation)_ **Second screen.** None of these options needs special code for a second monitor; the window is placed by coordinates. Live itself has a second window (Ctrl+Shift+W, [Live shortcuts](https://www.ableton.com/live-manual/12/live-keyboard-shortcuts/)), so the user may already use both screens for Live.
- _(interpretation)_ **Focus conflict.** A chat box needs keyboard focus. While our window has focus, Live's shortcuts and its computer MIDI keyboard do not reach Live. A no-activate window (`WS_EX_NOACTIVATE`, Qt `WindowDoesNotAcceptFocus`, pywebview `focus=False`) avoids that but cannot take typed text unless it is activated on purpose. A design option: no-activate by default, activated by the hotkey (Question 2). Raymond Chen writes that a process gets foreground permission when its registered hotkey is pressed ([Old New Thing, 2009-02-26](https://devblogs.microsoft.com/oldnewthing/20090226-00/?p=19013); Microsoft blog, medium–high).
- _(interpretation)_ **Threading.** The orchestrator loop (`src/orchestrator/loop.py`) is synchronous today. Every GUI route needs either a worker thread for the model and tool calls or an async bridge (`qasync` for Qt), so that a long Claude call does not freeze the window.

## Question 2 — Global hotkeys while Live has focus: possible, reliable, conflicts?

**Answer.**
- **Route A: `RegisterHotKey`** (Win32, via `ctypes`, `pywin32` 312 [PSF] or a toolkit native-event filter).
  - The page says it "defines a system-wide hot key".
  - With `hWnd = NULL` the `WM_HOTKEY` message goes to the calling thread's queue, so that thread needs a message loop. Registering against a window created by another thread fails.
  - It "typically" fails if another hotkey already uses the same keys. Some OS hotkeys (e.g. PrintScreen) may be overridden while the app's window is in the foreground.
  - `MOD_NOREPEAT`: auto-repeat does not send extra notifications.
  - F12 is reserved for the debugger at all times. Win-key combos are reserved for the OS.
  - Source: [RegisterHotKey](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey), [WM_HOTKEY](https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-hotkey). Confidence: high.
- **Does Live still get the key?** Neither Microsoft page says whether a registered hotkey is also delivered to the foreground window. Electron's `globalShortcut` docs say registration fails silently if the combo is taken, and imply that registered shortcuts are intercepted. They do not state it ([Electron globalShortcut](https://www.electronjs.org/docs/latest/api/global-shortcut)). Confidence: not established. → V3.
- **Route B: low-level keyboard hook** (`WH_KEYBOARD_LL`; used by `pynput` 1.8.2, LGPLv3, and `keyboard` 0.13.5, MIT, last release 2020-03-23).
  - The hook is global and is called on the installing thread, which must have a message loop.
  - If the hook procedure takes longer than `LowLevelHooksTimeout`, Windows 7+ **removes the hook silently**; the app is not told. The maximum is 1000 ms on Windows 10 1709+.
  - The hook can swallow a key by returning non-zero.
  - Sources: [LowLevelKeyboardProc](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc), [SetWindowsHookEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowshookexw). Confidence: high.
  - pynput: `GlobalHotKeys` class; `suppress=True` blocks all events system-wide; the listener is a thread, and slow callbacks on Windows can freeze input for all processes ([pynput keyboard docs 1.7.6](https://pynput.readthedocs.io/en/latest/keyboard.html)). Confidence: high (docs are for an older version).
  - _(interpretation)_ Route B is less reliable for us: one slow Python callback (GIL, garbage collection) can make Windows drop the hook without notice. Route A has no such timeout.
- **Privilege.** Microsoft says a lower-integrity process cannot send window messages to, or hook, a higher-integrity process (UIPI) ([IE compat doc on UIPI](https://learn.microsoft.com/en-us/previous-versions/windows/internet-explorer/ie-developer/compatibility/dd565646(v=vs.85))). _(interpretation)_ If Live runs as administrator and our app does not, a low-level hook may not see keys typed into Live. The pages opened today do not say whether `RegisterHotKey` is affected. Confidence: medium.
- **Conflicts with Live 12 (Windows shortcuts, from the [Live 12 shortcut list](https://www.ableton.com/live-manual/12/live-keyboard-shortcuts/)):**
  - **Taken by Live:**
    - Ctrl+Alt+Shift+F (freeze), Ctrl+Alt+Shift+E (audio engine on/off).
    - Many Ctrl+Alt+letters: V B O I S M P R G F T U E J, and the digits 3–7.
    - Many Ctrl+Shift+letters: S R E G L I T M W F C V X D U J A.
    - Alt+0–8, several Alt+Shift combos, Alt+letter for opening menus.
    - F1–F12, Ctrl+F9–F12, Shift+F9/F10.
    - Bare letters while the computer MIDI keyboard is on (Shift+letter then gives the single-letter shortcuts).
  - **Free:** Ctrl+Alt+Shift with any letter except F and E is not in Live's list. Confidence: high (list as published; not checked against 12.4.5 itself).
  - Key Map mode lets the user map computer keys to Live controls ([Live 12 manual: MIDI and key remote control](https://www.ableton.com/en/live-manual/12/midi-and-key-remote-control/)). The page does not say which keys are allowed. _(interpretation)_ A user mapping can collide with our hotkey, so the hotkey should be user-configurable.

## Question 3 — Drag-and-drop from our window into Live's clip slots

**Answer.**
- **Live accepts external files.** "Files can also be dropped directly into Live from the Explorer (Win)/Finder (Mac)" ([Live 12 manual, Working with the Browser §4.10](https://www.ableton.com/en/live-manual/12/working-with-the-browser/)). When several files are dropped, Session View lays them out vertically in one track, or across tracks with Ctrl held ([Live 12 manual, Session View](https://www.ableton.com/en/live-manual/12/session-view/)). Neither page names a single **clip slot** as the drop target. Confidence: high for "drops from Explorer work"; the clip-slot target is unverified.
- **Third-party apps.** Splice documents dragging samples from the Splice desktop app straight onto audio or MIDI tracks in Session and Arrangement View. It says Max for Live devices and third-party plug-ins do not accept the drag ([Splice support](https://support.splice.com/en/articles/12059504-how-to-download-splice-samples-in-ableton-live-12-3)). Confidence: medium (vendor doc, not Ableton). _(interpretation)_ Live therefore takes file drops from apps other than Explorer.
- **What our window must send.** On Windows, Qt maps `text/uri-list` to `CF_HDROP` (the Explorer file-list format) ([QWindowsMimeConverter, Qt 6.12](https://doc.qt.io/qt/qwindowsmimeconverter.html)). A drag starts with `QDrag` + `QMimeData.setUrls([...])` + `exec()` ([Qt drag and drop](https://doc.qt.io/qt-6/dnd.html), [QMimeData](https://doc.qt.io/qt-6/qmimedata.html)). Confidence: high.
- **Other toolkits:**
  - wxPython: `wx.FileDataObject` "uses the same format as Explorer" on Windows; `AddFile` is Windows-only; `wx.DropSource.DoDragDrop` starts the drag ([FileDataObject](https://docs.wxpython.org/wx.FileDataObject.html), [DropSource](https://docs.wxpython.org/wx.DropSource.html)). Confidence: high.
  - Tkinter: Tk has no OLE drag source of its own. `tkinterdnd2` 0.7.0 (MIT, bundles tkdnd 2.9.5 binaries) has `drag_source_register(..., DND_FILES)` plus a `<<DragInitCmd>>` callback ([TkinterDnD.py on master](https://raw.githubusercontent.com/Eliav2/tkinterdnd2/master/tkinterdnd2/TkinterDnD.py), lines ~199–213 on 2026-10-29; [README](https://github.com/Eliav2/tkinterdnd2)). The README documents only drop targets and does not say which Tk version (8.6 / 9) the Windows binaries support. Confidence: medium.
  - pywebview: documents dropping files *into* the window (`pywebviewFullPath`), not dragging files out ([pywebview API](https://pywebview.flowrl.com/api/)). Confidence: high that it is undocumented. _(interpretation)_ A drag-out would need native code through pythonnet. Effort: large, outcome unknown.
  - Electron: `webContents.startDrag({file, icon})` on `ondragstart` ([Electron native file drag](https://www.electronjs.org/docs/latest/tutorial/native-file-drag-drop)). Confidence: high.
- **Privilege level.** If Live runs as administrator, drags from Explorer into Live fail; Windows only allows drag-and-drop between apps at the same privilege level. Ableton's fix: untick "Run this program as an administrator" ([Ableton help](https://help.ableton.com/hc/en-us/articles/360011998859)). A Microsoft blog explains the cause: UIPI blocks the messages from lower to higher integrity ([Microsoft archive blog, 2010-01-28](https://learn.microsoft.com/pl-pl/archive/blogs/patricka/q-why-doesnt-drag-and-drop-work-when-my-application-is-running-elevated-a-mandatory-integrity-control-and-uipi)). Confidence: high.
- _(interpretation)_ **Relation to Phase 03.** If `clip_slot.create_audio_clip` is `tested` (Live result pending, #87), the window does not need drag-and-drop for import: a button can call the bridge. Drag-and-drop stays the manual route and the fallback. Two no-code fallbacks exist already:
  - Drag from Explorer.
  - Add the project's `Samples/` folder to Live's Places (manual §4.7.8, same browser page).
- **Files outside the project.** A dropped file outside the Live project stays external until "Collect All and Save". Live writes an `.asd` analysis file next to the sample when it is first added ([Live 12 manual, Managing Files and Sets](https://www.ableton.com/en/live-manual/12/managing-files-and-sets/)). _(interpretation)_ Drag the WAV from `<project>/Samples/Drums/Kicks/` (what `place_kick` returns), not from a temp folder.

## Question 4 — Effort class and risks per option; what CI can test

_All of this section is interpretation from the sources above, not measured._

| Option | Effort | Main risks |
| --- | --- | --- |
| Tkinter + `tkinterdnd2` + `RegisterHotKey` via `ctypes` | small (window, on-top, chat) / medium (with drag-out) | Tk may be missing (installer option, install manager unclear); tkdnd binaries vs. the user's Tk version (V2); dated look; drag-source support only in code, not in the README |
| PySide6 (+ `qasync`) + `RegisterHotKey` | medium | ~84 MB minimum download (Essentials + shiboken); LGPL obligations only matter if the app is ever distributed; native-event filter for `WM_HOTKEY` is our own code |
| wxPython + `wx.Window.RegisterHotKey` ("Registers a system wide hotkey", [wx.Window 4.3.2](https://docs.wxpython.org/wx.Window.html); no platform note seen) | medium | smaller community than Qt; wheel for 3.14 exists today, future Python versions depend on the project |
| pywebview + pythonnet | medium (window) / large (drag-out) | no documented drag-out; WebView2 Runtime presence; two runtimes (.NET via pythonnet, Chromium) |
| Electron + Python backend over local socket | large | second language and runtime, packaging, process lifecycle |

- **Shared risks for every option:**
  - Our hotkey may collide with another app or a Live Key Map mapping. `RegisterHotKey` then fails; handle the error and let the user choose another combo.
  - Live or our app may run elevated (drag-and-drop fails).
  - Focus stealing from Live (see Question 1).
  - A long Claude call on the GUI thread freezes the window.
- **What CI can test (GitHub Actions, no Ableton):**
  - The view-model logic, without a display: message list, approval prompts, drag payload = absolute paths from `place_kick`.
  - Qt widgets: `pytest-qt` 4.5.0 (MIT). Its docs say ubuntu runners need `libxkbcommon-x11-0` and Xvfb with a window manager, and `QT_QPA_PLATFORM=offscreen` "may also be helpful" ([pytest-qt troubleshooting](https://pytest-qt.readthedocs.io/en/latest/troubleshooting.html)). Qt chooses the platform plugin via `QT_QPA_PLATFORM` ([Qt QPA](https://doc.qt.io/qt-6/qpa.html)).
  - That a `QMimeData` / `wx.FileDataObject` carries the right file list.
  - The `RegisterHotKey` / `UnregisterHotKey` call and its "already taken" error path on `windows-latest`. Whether a hosted runner has an interactive desktop for this was not checked → V6.
- **What only the user's machine can show:**
  - The drop into Live (track vs. clip slot).
  - Hotkey pass-through to Live, and the hotkey working while Live has focus.
  - Behaviour above a full-screen Live (F11).
  - Startup time, and how the window looks on their screens.

## To verify by experiment

| # | What | Where / how | Owner |
| --- | --- | --- | --- |
| V1 | Cold and warm startup time to first painted window for Tkinter, PySide6, wxPython and pywebview. Script: `time.perf_counter()` at process start → first `after`/`QTimer.singleShot(0)` callback. Five runs each. | User's Windows PC | UI implementer (role to be named by lead) |
| V2 | `python -c "import tkinter; print(tkinter.TkVersion)"` on the user's Python 3.14.4; then whether `tkinterdnd2` 0.7.0 loads and can start a `DND_FILES` drag | User's Windows PC | UI implementer |
| V3 | Register Ctrl+Alt+Shift+K with `RegisterHotKey` while Live 12.4.5 has focus. Does `WM_HOTKEY` arrive? Does Live also react? (Map the same key in Key Map mode as a probe.) | User's PC with Live | UI implementer, user |
| V4 | Drag a kick WAV from a Qt (or wx / tkdnd) window onto (a) an empty Session clip slot on an audio track, (b) the track area, (c) the empty space right of the tracks, (d) a Drum Rack pad. Note where the clip lands and whether Live creates the `.asd` file. | User's PC with Live | UI implementer, user |
| V5 | Topmost window above Live in normal, maximised and full-screen (F11) mode, on the main screen and on a second screen; and whether a click into a `WS_EX_NOACTIVATE` window leaves Live's keyboard focus intact | User's PC with Live | UI implementer, user |
| V6 | On `windows-latest`: can a test call `RegisterHotKey` and create a Tk/Qt window (interactive desktop or not)? | CI | qa-tester |
| V7 | wxPython `wx.STAY_ON_TOP` and `wx.Window.RegisterHotKey` work on 4.3.2 with Python 3.14 on Windows (documented; not run) | User's PC | UI implementer |
| V8 | Whether `RegisterHotKey` still fires when Live runs elevated and our app does not (UIPI) | User's PC (only if the user runs Live as admin) | UI implementer |

## Implications for the lead

- No toolkit choice is made here. The user's questionnaire answers (tab 3) decide look, size and whether drag-and-drop matters if `create_audio_clip` passes. A new dependency (Qt, wx, tkinterdnd2) needs its reason stated in the PR (CLAUDE.md).
- A low-risk first step would be Tkinter (no dependency) plus `RegisterHotKey` via `ctypes`. Drag-and-drop would be added only if V4 shows that Live accepts the drop where the user wants it. If drag-out from Tk fails (V2), PySide6 is the documented route.
- "Live not run as administrator" is a precondition for drag-and-drop. It belongs in a setup guide (`docs/setup/`, bridge-engineer) once the feature is planned.
- A UI role or owner does not exist in the D-017 table yet; V1–V5 and V7–V8 need one.
