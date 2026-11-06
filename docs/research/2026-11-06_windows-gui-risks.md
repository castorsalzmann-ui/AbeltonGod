# Research: Windows risks of the GUI exe (DPI, sound, drag-and-drop, console, SmartScreen, size)

- **Date:** 2026-11-06. All web sources opened on 2026-11-06. Role: `researcher` (sprint W1, area F).
- **Receiving issue:** #438 (sprint plan `docs/sprints/2026-11-06_weekend-gui-sprint.md`, area F).
  Related open issues: #435 (bundle size), #436 (start errors invisible with hidden console).
- **Versions researched against:** Qt docs pages titled **Qt 6.12**; PySide6-Essentials **6.12.0**
  win_amd64 wheel (downloaded and listed, not run); PyInstaller docs and source **6.22.3**;
  `claude-agent-sdk` **0.2.174** (our pin, `pyproject.toml` line 17) and 0.2.178 win_amd64 wheels
  (listed, not run); Python `winsound` docs page titled **3.15.2**; Live 12 manual (web, no build
  stamp; the user runs Live 12.4.5). Repo code read at `origin/main` d922923.
- **Existing note checked:** [`2026-10-29_desktop-window-windows.md`](2026-10-29_desktop-window-windows.md)
  (toolkit choice, CF_HDROP, Live drop targets, elevation). This note does not repeat it. It adds the
  exe, DPI, sound and size side, plus the drag lifetime problem found in today's code.
- **Nothing here was run on Windows.** Every "works on Windows" statement cites a source, or is
  marked _(interpretation)_ or "not established".

## For workers

- **Possible with our stack:** yes for all six points; two need a design change, not a tweak.
- **Biggest risks:** (1) Smart App Control on Windows 11 can block the unsigned exe with no per-app
  override; (2) `hide_own_console` is unreliable when Windows Terminal is the default terminal
  (Windows 11 22H2+); (3) Blaster drag-out hands Live a temp file that we delete later, so the Live
  clip goes offline; (4) the bundle is probably dominated by the SDK's 297 MB `claude.exe`, not Qt
  (#435); (5) the main window's minimum width is about 108 "M" widths, which may not fit a 1080p
  screen at 175 % or more.
- **Already safe in code:** every preview path plays a **16-bit** copy, so the 24-bit winsound
  question does not arise today (see S2).
- **Read first:** S4 (console) and S6 (size) for area C; S3 for whoever owns the Blaster; S1 for the
  GUI tour (area D).
- **Effort:** S1 small; S2 small; S3 small (copy to a kept folder before the drag); S4 medium (two
  exes in one folder); S5 small (docs) / large (code signing); S6 small to medium.
- **Blockers:** none for CI work. Smart App Control, real sound, real drops and the console need
  the user's PC.
- **Only the user can answer:** Is Smart App Control on? Which resolution and display scaling? Is
  Windows Terminal the default terminal? Does the copilot have to work from the exe without a
  separate Claude Code install? Is a paid code-signing certificate acceptable?

## Findings

| # | Finding | Confidence | Source |
| --- | --- | --- | --- |
| F1 | Qt 6 is Per-Monitor DPI Aware V2 by default on Windows; the default rounding policy is already `PassThrough`; `QT_SCALE_FACTOR` simulates a scale factor for testing | High | [Qt 6.12 High DPI](https://doc.qt.io/qt-6/highdpi.html) |
| F2 | At 150 % a 1 px stylesheet border can render with uneven thickness (Qt 6.10.2, Windows 10); a Qt Champion calls it a property of fractional scaling, not a bug | Medium (forum) | [Qt forum, 2026-04-20](https://forum.qt.io/topic/164584/setting-border-on-widget-is-inconsistent) |
| F3 | Microsoft: for `WAVE_FORMAT_PCM`, `wBitsPerSample` "should" be 8 or 16; formats with more than 16 bits "can be described" with `WAVEFORMATEXTENSIBLE`. Our engine writes 24-bit with tag 1 (`src/audio_engine/io.py` line 90) | High (what the doc says) | [WAVEFORMATEX](https://learn.microsoft.com/en-us/windows/win32/api/mmeapi/ns-mmeapi-waveformatex), [WAVEFORMATEXTENSIBLE](https://learn.microsoft.com/en-us/windows/win32/api/mmreg/ns-mmreg-waveformatextensible) |
| F4 | No source opened today shows `PlaySound` playing a 24-bit WAV on Windows 10/11. A Stack Overflow asker states that `PlaySound` cannot play 24-bit (no version named); another thread has 24-bit files playing through MCI on Windows 7 but not on XP | Not established | [SO 23831648 (archive)](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/23831648/easily-play-24-bits-wav-audio-files), [SO 6032795 (archive)](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/6032795/playback-24bit-audio-not-possible) |
| F5 | Legacy `waveOut` APIs convert between the app's stream format and the device format; the page does not name `PlaySound` or list which conversions exist | High (what the doc says) | [Core Audio: Device Formats](https://learn.microsoft.com/en-ie/Windows/Win32/coreaudio/device-formats) |
| F6 | `PlaySound` with `SND_FILENAME` plays the **default system sound** if the file cannot be found, unless `SND_NODEFAULT` is set; `SND_PURGE` is "not supported"; a NULL sound stops async playback | High | [PlaySound (archived 2016)](https://learn.microsoft.com/en-us/previous-versions/dd743680(v=vs.85)), [Python winsound](https://docs.python.org/3/library/winsound.html) |
| F7 | All three preview paths already hand `winsound` a 16-bit file: main window (`src/gui_core/preview.py` lines 66-68, stereo drawn and played as mid), Acid (`src/gui_core/acid_preview.py` line 100), Blaster (`src/gui_core/blaster.py` `play_path`, lines 119, 270-281) | High (code read) | repo |
| F8 | 24-bit **mono** WAVs with format tag 1 load in Live without a warning (user, #3); the 24-bit **stereo** laser WAV in Live is not verified | High / not established | `docs/CURRENT_STATE.md` lines 10, 164 |
| F9 | On Windows, `QDrag::exec()` blocks the Qt event loop during the drag (it calls `processEvents()` often) | High | [QDrag, Qt 6](https://doc.qt.io/qt-6/qdrag.html) |
| F10 | Live keeps referencing a dropped file at its original location until "Collect All and Save"; a missing file makes the clip Offline and "Live will play silence"; Live writes an `.asd` next to the sample | High | [Live 12 manual, Managing Files and Sets](https://www.ableton.com/en/live-manual/12/managing-files-and-sets/) |
| F11 | The Blaster offers its shot WAVs for drag-out from a `mkdtemp` folder (`src/gui_core/blaster.py` line 216, `src/gui/blaster/window.py` line 1023), deletes shots older than 40 (`_trim`, lines 283-288, `HISTORY_LIMIT` line 45) and deletes the whole folder on close (line 318) | High (code read) | repo |
| F12 | A JUCE plugin's drag into Live failed ("could not be opened") while the plugin deleted the temp file in the drag-completion callback; not deleting it fixed it. Cause is the poster's inference | Medium (forum) | [JUCE forum, 2020-11-10](https://forum.juce.com/t/performexternaldragdropoffiles-not-working-in-ableton/42675) |
| F13 | Live accepts files dropped from Explorer (§4.10); folders can be dropped into Places (§4.7.8); the manual does not document dropping single files into the browser to copy them | High | [Live 12 manual, Browser](https://www.ableton.com/en/live-manual/12/working-with-the-browser/) |
| F14 | Drag-and-drop between apps of different privilege fails; Ableton's fix is to untick "Run this program as an administrator" | High | [Ableton help](https://help.ableton.com/hc/en-us/articles/360011998859) |
| F15 | PyInstaller windowed mode: `sys.stdin/stdout/stderr` are `None`; writing to them raises `AttributeError` | High | [PyInstaller 6.22.3 pitfalls](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html) |
| F16 | PyInstaller has `--hide-console {hide-early,hide-late,minimize-early,minimize-late}` for console exes that own their console; `--disable-windowed-traceback` exists, so windowed builds show unhandled tracebacks by default _(interpretation of the option text)_ | High / medium | [PyInstaller 6.22.3 usage](https://pyinstaller.org/en/stable/usage.html), [man page](https://pyinstaller.org/en/stable/man/pyinstaller.html) |
| F17 | `--hide-console` (same `GetConsoleWindow` + `ShowWindow` approach as our `hide_own_console`) does not work reliably on Windows 11 with Windows Terminal; works with Windows Console Host as default. Maintainers label it "not-our-bug"; issue open | High (maintainer statements) | [PyInstaller #8022](https://www.github.com/pyinstaller/pyinstaller/issues/8022) |
| F18 | Windows Terminal is the default terminal on Windows 11 22H2 (Terminal ≥ 1.15) | High | [Microsoft devblog, 2022-10-18](https://devblogs.microsoft.com/commandline/windows-terminal-is-now-the-default-in-windows-11/) |
| F19 | With Windows Terminal, `ShowWindow` on the ConPTY pseudo window is forwarded to the whole Terminal window (all tabs); hiding by window style stays an open Terminal issue | High (spec) / high | [Terminal spec #12570 (mirror)](https://source-hub.etos-pro.ru/microsoft/terminal/src/branch/main/doc/specs/%2312570%20-%20Show%20Hide%20operations%20on%20GetConsoleWindow%20via%20PTY.md), [microsoft/terminal #12464](https://www.github.com/microsoft/terminal/issues/12464) |
| F20 | PyInstaller can build several exes into one onedir folder with a shared `COLLECT` | High | [PyInstaller spec files, Multipackage](https://pyinstaller.org/en/stable/spec-files.html) |
| F21 | SmartScreen warns for files and apps without established reputation; reputation checks include the digital signature | High | [Microsoft Defender SmartScreen](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/) (updated 2026-04-23) |
| F22 | Smart App Control blocks unsigned apps whose safety the cloud service cannot predict; "There is currently no way to bypass Smart App Control protection for individual apps" | High | [Microsoft support: What is Smart App Control](https://support.microsoft.com/en-us/topic/what-is-smart-app-control-285ea03d-fa88-4d56-882e-6698afdb7003) (metadata 2026-09-28) |
| F23 | Smart App Control checks the signatures of all loaded code, including DLLs; since April 2026 (Windows 11 25H2) it can be re-enabled after being turned off | Medium (ex-Microsoft engineer's blog) | [Eric Lawrence, 2026-04-28](https://textslashplain.com/2026/04/28/smart-app-control/) |
| F24 | PyInstaller exes get antivirus false positives; PyInstaller sets a valid PE checksum since 2021 to reduce them; Defender still flagged one build afterwards | Medium (issue thread) | [PyInstaller #5579](https://github.com/pyinstaller/pyinstaller/issues/5579), [discuss.python.org, 2024-01](https://discuss.python.org/t/pyinstaller-false-positive/43171) |
| F25 | Files downloaded from the internet carry a `Zone.Identifier` stream (zone 3); `Unblock-File` removes it. Whether Windows' built-in ZIP extraction copies it to the extracted files: no source opened today | High / not established | [Unblock-File](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/unblock-file) |
| F26 | PySide6-Essentials 6.12.0 win_amd64: 219.0 MB unpacked; largest file `opengl32sw.dll` 20.6 MB; `translations/` 14.1 MB | High (listed today) | wheel listing, see S6 |
| F27 | PyInstaller 6.22.3's base PySide6 hook collects `opengl32sw.dll` (and ANGLE DLLs if present) on Windows for every PySide6 app | High | PyInstaller source `PyInstaller/hooks/hook-PySide6.py` line 28; `PyInstaller/utils/hooks/qt/__init__.py` lines 628-648 |
| F28 | `opengl32sw.dll` is Mesa llvmpipe, a software OpenGL fallback; widgets apps need OpenGL only when they use `QOpenGLWidget`/`QOpenGLWindow`. Our GUI imports only QtCore/QtGui/QtWidgets (grep, 86 import lines) | High (doc) / high (grep) | [Qt for Windows – Graphics](https://doc.qt.io/qt-6/windows-graphics.html) |
| F29 | `claude-agent-sdk` 0.2.174 win_amd64 wheel: 297.4 MB unpacked, of which `_bundled/claude.exe` 296.8 MB (0.2.178: 342.4 MB). The SDK uses the bundled CLI before `claude` on PATH (`subprocess_cli.py` lines 255-264, 341-348 in the wheel). `build_exe.py` passes `--collect-all claude_agent_sdk` (line 49) | High (listed today); "it is in our bundle" is an _(interpretation)_ | wheel listing, see S6 |

## S1 — PySide6 high-DPI on Windows 10/11 (125 / 150 / 200 %)

- **Risk: medium.** Qt handles the scale factor itself (F1). What can still go wrong:
  - Uneven 1 px borders at 125 % and 150 % (F2). Our stylesheet uses `1px` borders
    (`src/gui/theme.py` lines 44-51).
  - _(interpretation)_ **Window larger than the screen.** The main window's minimum width is
    `m * 20 + m * 50 + m * 38` plus margins, `m` = width of "M" (`src/gui/main_window.py` lines 111,
    112, 122, 143); default size `m * 112` (line 156). Logical sizes stay the same at every scale.
    The screen's logical width shrinks: 1920 px / 1.5 = 1280, / 1.75 = 1097, / 2.0 = 960. With
    `m` around 10 logical px (not measured; depends on the system font), 108 `m` would not fit a 1080p
    screen at 175 % or 200 %. Windows' "Text size" setting makes `m` bigger as well.
  - Mixed-DPI setups (laptop + external screen): Qt is per-monitor V2 (F1); how our custom-painted
    widgets look while a window moves between screens is not established.
  - `app.py` lines 16-18 set `PassThrough`, which is already Qt 6's default (F1). Harmless.
- **Mitigation testable in CI (Windows runner, offscreen):**
  - The GUI tour screenshots at `QT_SCALE_FACTOR=1.25/1.5/2.0` (sprint goal 1).
  - A test that compares each top-level window's `minimumSizeHint()` (logical px) with target
    logical screen widths, e.g. 1920/1.5 = 1280 and 1366/1.0. Run it on `windows-latest`, where the
    default font is the Windows one. If 1920/1.75 fails, decide whether that case matters (ask the user).
  - A grep-style test: every widget that caches a pixmap uses `devicePixelRatioF()` (the Acid widgets
    do, `src/gui/acid/widgets.py` lines 34-36).
- **Only the user can test:** look at 100 % and the user's own scale; the window fits the screen;
  moving a window to a second screen with a different scale.

## S2 — `winsound.PlaySound` with 24-bit stereo WAV at 48 kHz

- **Does it play?** **Not established.** No source opened today shows it working or failing on
  Windows 10/11 (F4). Microsoft's own format docs say tag-1 PCM "should" be 8 or 16 bits (F3);
  our files are tag 1 at 24 bits. `waveOut` converts formats (F5), but that page does not name
  `PlaySound` or say whether non-conformant headers are accepted.
- **Risk today: low.** The code never sends a 24-bit file to `winsound`: every preview path writes a
  16-bit copy first (F7). The question would come back only if someone removed that copy step.
- **Residual risks in `src/gui/audio.py`:**
  - No `SND_NODEFAULT` (line 23). If the preview file is missing, Windows plays the default system
    sound instead (F6). This needs a deleted temp file, so it is unlikely; at most a `nit`.
  - `stop()` passes `SND_PURGE` (line 28), which both Microsoft and Python call unsupported. The
    `None` sound alone stops playback (F6), so `stop()` should still work _(interpretation)_.
  - Python raises `RuntimeError` "if the system indicates an error" (F6). With `SND_ASYNC` an error
    may surface later or not at all; whether async `PlaySound` reports a device or format error is
    not established. `PreviewController.play` already turns exceptions into a message.
- **Mitigation testable in CI:** a test with a recording fake backend that runs the main preview,
  Acid preview, Blaster fire and Blaster preview, and checks that each file handed to `play()` has
  `wBitsPerSample == 16` in its header. Fault injection: make one path pass the 24-bit file.
  Whether `windows-latest` has an audio endpoint for a real `PlaySound` call is not established;
  do not rely on it.
- **Only the user can test:** preview is audible for kick, laser (stereo source, played as mid),
  Acid and Blaster; Stop stops it; no Windows "ding". Separately: import of the 24-bit stereo laser
  WAV into Live (F8).

## S3 — `QDrag` file drops into Live 12 (browser, track) and Explorer

- **What the code offers:** `text/uri-list` with existing files only, copy action only
  (`src/gui/drag.py` lines 16-41). Qt turns this into `CF_HDROP` on Windows (earlier note, Q3).
- **Risk: Blaster drag-out = high (user-visible), rest = medium.**
  - **Blaster temp files (high).** The Blaster offers files from a temp folder that it deletes
    after 40 newer shots and on close (F11). Live keeps referencing the dropped file where it lies
    (F10). After the Blaster window closes, a clip made from a dragged shot goes Offline and plays
    silence, unless the user ran "Collect All and Save" first _(interpretation from F10 + F11)_.
    The JUCE case (F12) also suggests Live may read the file after the drop finishes. Filed as
    side-finding #444.
  - Main window results and the library list offer files from the output/library folder, which
    the app does not delete _(code read: no `rmtree` on that folder in `src/gui/`)_.
  - **Live browser:** the manual documents dropping **folders** into Places, not single files into
    the browser (F13). A file dropped on the browser may do nothing; not established.
  - **Track / clip slot:** documented for Explorer drops (F13); for drops from a non-Explorer app
    and for a specific clip slot see the earlier note (V4, unverified).
  - **Elevation:** if Live runs as administrator, no drop works (F14).
  - **Event loop:** on Windows the Qt loop is blocked during a drag (F9). Timers (playhead, Blaster
    fire timer) pause until the drop ends _(interpretation)_. Not harmful, but visible.
  - **Explorer:** we offer copy only, so Explorer should copy, not move _(interpretation; no
    Explorer-specific source opened today)_.
- **Mitigation testable in CI:** mime tests exist. Add: every path a `DragList` offers lies outside
  `tempfile.gettempdir()` (or inside the configured output/library folder). Fault injection: offer
  a Blaster temp path; the test must turn red.
- **Only the user can test:** drop from results, library and Blaster onto (a) a Live audio track,
  (b) an empty clip slot, (c) the browser, (d) an Explorer folder; then close the Blaster and check
  whether the Live clip goes Offline.

## S4 — PyInstaller windowed vs console, hiding the console

- **Today:** `--console` (`scripts/build_exe.py` line 92), and `hide_own_console`
  (`src/launcher/gui_start.py` lines 12-30) hides the console with `ShowWindow(GetConsoleWindow(), 0)`
  when this process is the console's only client.
- **Risk: medium to high on Windows 11.** Windows Terminal is the default terminal on Windows 11
  22H2+ (F18). There, the same technique fails or works only sometimes (F17); a hide request
  applies to the whole Terminal window (F19). Possible effects for the user _(interpretation)_:
  the black window stays open behind the GUI; or a Terminal window flashes; closing that window
  ends the GUI (Blender reports this for its console, medium:
  [Blender T96672](https://developer.blender.org/T96672)). Whether `GetConsoleProcessList` returns 1
  under Windows Terminal is not established. Filed as side-finding #445.
- **Windowed instead?** A windowed exe has no console, but `sys.stdout` is `None` (F15). The same
  exe is our CLI (`AbeltonGod.exe kick ...`, `docs/setup/EXE.md`) and `scripts/exe_smoke.py` reads
  its output. A windowed build would break the CLI unless output goes elsewhere.
- **Options (for the lead / area C):**
  1. Two exes in one onedir folder with a shared `COLLECT` (F20): `AbeltonGod.exe` windowed (GUI),
     `AbeltonGod-cli.exe` console (all sub-commands). No console tricks at all. Windowed builds
     show a traceback dialog by default (F16), which also covers #436. Effort: medium (spec file
     instead of CLI flags, smoke tests for both).
  2. Keep one console exe and switch to `--hide-console hide-early` (F16): same weakness as today (F17).
  3. Keep today's code and document the workaround: Windows Terminal setting "Default terminal
     application" = "Windows Console Host" (F17). Cheapest; the user has to change a setting.
- **Mitigation testable in CI:** read the PE header's `Subsystem` field of each built exe (2 = GUI,
  3 = console) in `exe_smoke.py`; start the windowed exe offscreen and check its exit code and a
  log file instead of stdout; keep the CLI smoke tests on the console exe.
- **Only the user can test:** double-click from Explorer: does a black window or Terminal window
  stay open? Does closing it kill the GUI? Same with Windows Terminal and Console Host as default.

## S5 — SmartScreen / Defender on an unsigned onedir exe

- **Risk: high if Smart App Control is on, else low to medium.**
  - **SmartScreen:** an unsigned exe without reputation gets a warning (F21). `docs/setup/EXE.md`
    already explains "Weitere Informationen" → "Trotzdem ausführen". Each new build has a new hash,
    so reputation does not carry over _(interpretation)_.
  - **Smart App Control (Windows 11):** blocks unsigned apps it cannot rate, and there is no
    per-app bypass; the only ways are to turn it off or to sign the app (F22). It checks all loaded
    code, including DLLs (F23); our folder has many unsigned `.pyd`/`.dll` files _(interpretation)_.
    Turning it off was permanent before Windows 11 25H2 (F23).
  - **Defender / other scanners:** PyInstaller bootloaders get false positives (F24). Onedir vs
    onefile: no source opened today compares them (the claim in `build_exe.py` lines 9-10 is not
    sourced here).
  - **Mark of the Web:** the downloaded ZIP is zone 3 (F25); whether extraction copies the mark to
    the exe is not established. `Unblock-File` on the ZIP before extracting removes it (F25).
- **Mitigation testable in CI:** publish the SHA-256 of the ZIP next to the artifact; run
  `Get-AuthenticodeSignature` on the exe and print the status, so the docs never claim a signature
  that is not there. Code signing (a certificate, e.g. a cloud signing service) is the only fix for
  Smart App Control; it costs money and needs the user's decision. Not researched further here.
- **Only the user can test:** Windows Security → App & browser control → Smart App Control state;
  whether SmartScreen or Defender blocks or quarantines the exe or a DLL after unzipping.

## S6 — Qt module trimming for size (#435)

- **What #435 assumes:** "Qt dominates" (430 MB unpacked, 192 MB ZIP); split not measured.
- **What the wheels say (listed today, not built):**
  - The whole PySide6-Essentials 6.12.0 wheel is 219.0 MB unpacked (F26); our build already
    excludes many modules (`build_exe.py` lines 38-47), so Qt's share of the bundle should be well
    below 219 MB _(interpretation)_.
  - The pinned `claude-agent-sdk` 0.2.174 wheel contains a 296.8 MB `claude.exe` (F29). With
    `--collect-all claude_agent_sdk` it is very likely in the bundle _(interpretation; check the
    folder listing)_. If so, it alone is about 70 % of 430 MB, and trimming Qt cannot shrink the
    bundle much.
  - Qt items worth checking in the build: `opengl32sw.dll` 20.6 MB, collected by PyInstaller's
    base hook for every PySide6 app (F27) though our widgets never use OpenGL (F28); Qt
    `translations` (14.1 MB in the wheel; which ones PyInstaller collects for our three modules not
    measured); `icudtl.dat` 10.5 MB is collected only by the WebEngine hook (PyInstaller source
    comment, `qt/__init__.py` lines 58-67), so it should not be in our bundle.
- **Risk of trimming: medium.** A missing Qt plugin shows up only at run time.
  `opengl32sw.dll` is a fallback; removing it only matters if something uses OpenGL (F28).
  Removing `claude.exe` breaks the copilot in the exe unless `claude` is on PATH (F29 lookup order):
  that is a product decision.
- **Mitigation testable in CI:** in `build-exe.yml`, print the 20 largest files and the size per
  top-level folder; fail if the folder exceeds an agreed budget; run the existing `gui` smoke after
  each exclusion (it starts offscreen and opens all windows). Filter `opengl32sw.dll` out of
  `a.binaries` in a spec file and confirm the smoke stays green.
- **Only the user can test:** start time and that the GUI looks the same after trimming (no
  missing style or image plugin); the copilot still answers from the exe.

## Checklist for the user (Windows PC, about 15 minutes)

1. Settings → System → Display: note resolution and scale (100 / 125 / 150 / 175 / 200 %).
2. Windows Security → App & browser control → Smart App Control: on, evaluation or off?
3. Windows Terminal settings → Startup → Default terminal application: which one?
4. Download the ZIP, extract, double-click `AbeltonGod.exe`: SmartScreen text? Defender message?
   Does a black or Terminal window stay open? Close it: does the GUI close too?
5. Main window: fits the screen? Text and borders sharp? Move it to a second screen if you have one.
6. Preview a kick, a laser, an Acid line and a Blaster shot: audible? Stop works? Any Windows "ding"?
7. Drag a result and a library row onto a Live audio track, an empty clip slot, Live's browser and
   an Explorer folder: what happens in each case?
8. Drag a Blaster shot into Live, close the Blaster window, look at the clip in Live: still playing
   or Offline?
9. Is Live set to "Run as administrator"? (If yes, no drag works, F14.)

## Implications for the lead

- **Area C (#435):** measure before trimming Qt; the SDK's `claude.exe` is the likely main item.
  Whether the exe must carry its own Claude CLI is a user/product question (D-014 copilot).
- **Area C (#436 + S4):** consider the two-exe layout (windowed GUI + console CLI); it removes
  `hide_own_console` and gives a crash dialog for free. Otherwise document the Console Host
  workaround in `docs/setup/EXE.md`.
- **Blaster owner (area E):** drag-out must offer a file that outlives the window (copy into the
  output/library folder on drag start, or offer only shots saved to the library). Side-finding #444.
- **Area D (tour):** add the minimum-size-vs-screen test and the 16-bit-to-backend test; both are
  cheap and catch user-visible faults.
- **Docs:** `docs/setup/EXE.md` should name Smart App Control (no "run anyway" there) and the
  administrator rule for drag-and-drop. `capabilities.json` is not affected.
- No decision is contradicted. Code signing would be a new cost decision for the user.
