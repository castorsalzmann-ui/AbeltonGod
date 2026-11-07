# GUI control inventory

Every button, action, shortcut, input and interactive widget of the main window pages and the
three tool windows (Goa, Acid, Laser-Blaster), with its handler and effect. Issue #437 (sprint
W1, area D). As of `main` `d922923` (2026-11-06).

**How this list is kept true.** `tests/gui/test_tour_inventory.py` walks the freshly opened
windows (`scripts/qa/gui_controls.py`) and compares the IDs in the first column with what it
finds, in both directions: a new control fails the test until it has a row here, a removed one
until its row is deleted. The same test fails when a button, action, shortcut or custom widget
has no receiver (`QObject.isSignalConnected`), or when a widget-kit container (chips, segmented
buttons, number fields ...) passes nothing on. Print the current list with
`python scripts/qa/gui_controls.py` (`NEW` = missing here, `GONE` = row without a control).

**Reading an ID.** `area · class · label`. Areas: `main` (left list, window buttons, render
column), the category pages `kick` … `laser`, `library`, `goa-page`, `planner`, `live`, `chat`, and the
windows `goa`, `acid`, `blaster`. `Container/Class` means a control generated inside a kit
container, one row per kind (`*`), because their number follows the contract fields. Inputs
without a caption are named by the attribute that holds them (`AcidWindow.seed_edit`).

**What it does not prove.** A receiver exists; whether it does the right thing is checked by the
GUI tour (`tests/gui/test_tour.py`) and the area tests. Controls that only appear later (after a
render) are not walked. Plain inputs (line edits, combo boxes, spin boxes, lists) are listed but
not held to the receiver rule, because many are read only when an action runs (e.g. the Acid
generator fields). The one button without a receiver that is allowed is
`blaster · QCheckBox · Dauerfeuer beim Halten` (state, read when the trigger is pressed);
hidden `ActiveDot` layout spacers are left out.

**Gaps found with this inventory and the tour** (label `gui-gap`): #440 Goa window was a
placeholder (fixed in #450: real Goa form), #441 Goa page does not
follow the output folder, #442 Acid window too tall at 150 % on 1920 x 1080, #443 file names
without category / three output layouts. Already filed before: #413, #414, #439.

### Main window: left list, window buttons, render column

| ID | Handler | Effect |
| --- | --- | --- |
| `main · DragList · results` | `MainWindow._result_selected` | Results of this session; selecting loads the waveform; rows drag out as WAV files |
| `main · QLineEdit · MainWindow.folder_edit` | read on Render / page switch | Output folder for category renders, library and Live page (not for the Goa page, #441) |
| `main · QListWidget · categories` | `MainWindow.show_page` (`currentRowChanged`) | Left list: switches the page; library and Live pages re-read the output folder when shown |
| `main · QPushButton · Abbrechen` | `MainWindow.cancel_render` | Cancels the running render (finished files stay) |
| `main · QPushButton · Abspielen` | `MainWindow.play` | Plays the selected file (winsound on Windows; elsewhere an honest 'no audio output' message) |
| `main · QPushButton · Acid-Linie` | `MainWindow.open_acid_window` | Opens the Acid window with the current output folder (not updated later, #439) |
| `main · QPushButton · Ausgabeordner öffnen` | `MainWindow.open_folder` | Opens the output folder in the file manager; error text if it does not exist yet |
| `main · QPushButton · Goa-Fenster` | `MainWindow.open_goa_window` | Opens the Goa skin window (one instance; see #440: body is a placeholder) |
| `main · QPushButton · Laser-Blaster` | `MainWindow.open_blaster_window` | Opens the Blaster window; it follows the shared settings (#439, fixed in #450) |
| `main · QPushButton · Einstellungen …` | `MainWindow.open_settings` | Settings dialog: output folder, project folder (= Live page "Live-Projekt"), sample rate, bit depth; saved in the user config dir |
| `main · QPushButton · Rendern` | `MainWindow.start_render` | Renders the current category form in a worker thread; disabled with the reason while the form is invalid |
| `main · QPushButton · Stopp` | `MainWindow.stop` | Stops playback |
| `main · QPushButton · Wählen …` | `MainWindow._choose_folder` | Folder dialog for the output folder |

### Main window: category pages `kick`, `hat`, `snare`, `clap`, `rim`, `bass`, `laser`, `perc`

The seven category pages are built by `CategoryPanel` from the category's contract; their rows
differ only in the area. Handler and effect per kind:

- `ChoiceControl · *` — `CategoryPanel._edited` / `_active_toggled`: enum field as buttons, value into the model.
- `ChoiceControl/ActiveDot · *`, `NumberControl/ActiveDot · *`, `BoolControl/ActiveDot · *` — `ParamControl` → `activeToggled`: dot, send this value / use the engine default.
- `Collapsible · *` — self-contained: section ('Erweitert', 'Salve', ...) shows / hides its fields; `Collapsible/QToolButton · *` is its header.
- `NumberControl · *` — `CategoryPanel._edited` / `_committed` / `_active_toggled` / `_reset`: knob or slider + readout; value into the model, limits re-checked, Render enabled or blocked with the reason; double click resets.
- `PresetChips · *` — `CategoryPanel._preset_chosen` (via `chosen`): loads the preset into the model and every field; `PresetChips/QPushButton · *` is one chip per preset.
- `SeedControl · *` — `CategoryPanel._edited`: seed (typed, Up/Down); invalid text blocks Render with the reason.
- `Segmented/QPushButton · *`, `WrapSegmented/QPushButton · *` — `chosen` → `ChoiceControl._chosen`: one button per enum choice (wrapping for many choices: laser pan pattern, notes).
- `BoolControl · *` / `BoolControl/Toggle · *` (clap only) — `CategoryPanel._edited`: on/off field.

| ID | Handler | Effect |
| --- | --- | --- |
| `kick · ChoiceControl · *` | `CategoryPanel._edited` / `_active_toggled` | Enum field (see list above) |
| `kick · ChoiceControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of an enum field |
| `kick · Collapsible · *` | self-contained | Section shows / hides its fields |
| `kick · Collapsible/QToolButton · *` | `Collapsible` (internal) | Section header: expand / collapse |
| `kick · NumberControl · *` | `CategoryPanel._edited` / `_committed` / `_active_toggled` / `_reset` | Number field (see list above) |
| `kick · NumberControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of a number field |
| `kick · PresetChips · *` | `CategoryPanel._preset_chosen` | Preset chips row |
| `kick · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` | One chip per preset |
| `kick · SeedControl · *` | `CategoryPanel._edited` | Seed field |
| `kick · Segmented/QPushButton · *` | `Segmented` -> `chosen` -> `ChoiceControl._chosen` | One button per enum choice |
| `hat · ChoiceControl · *` | `CategoryPanel._edited` / `_active_toggled` | Enum field |
| `hat · ChoiceControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of an enum field |
| `hat · Collapsible · *` | self-contained | Section shows / hides its fields |
| `hat · Collapsible/QToolButton · *` | `Collapsible` (internal) | Section header |
| `hat · NumberControl · *` | `CategoryPanel._edited` / `_committed` / `_active_toggled` / `_reset` | Number field |
| `hat · NumberControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of a number field |
| `hat · PresetChips · *` | `CategoryPanel._preset_chosen` | Preset chips row |
| `hat · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` | One chip per preset |
| `hat · SeedControl · *` | `CategoryPanel._edited` | Seed field |
| `hat · Segmented/QPushButton · *` | `Segmented` -> `chosen` -> `ChoiceControl._chosen` | One button per enum choice |
| `snare · ChoiceControl · *` | `CategoryPanel._edited` / `_active_toggled` | Enum field |
| `snare · ChoiceControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of an enum field |
| `snare · Collapsible · *` | self-contained | Section shows / hides its fields |
| `snare · Collapsible/QToolButton · *` | `Collapsible` (internal) | Section header |
| `snare · NumberControl · *` | `CategoryPanel._edited` / `_committed` / `_active_toggled` / `_reset` | Number field |
| `snare · NumberControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of a number field |
| `snare · PresetChips · *` | `CategoryPanel._preset_chosen` | Preset chips row |
| `snare · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` | One chip per preset |
| `snare · SeedControl · *` | `CategoryPanel._edited` | Seed field |
| `snare · Segmented/QPushButton · *` | `Segmented` -> `chosen` -> `ChoiceControl._chosen` | One button per enum choice |
| `clap · BoolControl · *` | `CategoryPanel._edited` / `_active_toggled` | On/off field |
| `clap · BoolControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of an on/off field |
| `clap · BoolControl/Toggle · *` | `BoolControl._toggled` -> `edited` | The switch itself |
| `clap · ChoiceControl · *` | `CategoryPanel._edited` / `_active_toggled` | Enum field |
| `clap · ChoiceControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of an enum field |
| `clap · Collapsible · *` | self-contained | Section shows / hides its fields |
| `clap · Collapsible/QToolButton · *` | `Collapsible` (internal) | Section header |
| `clap · NumberControl · *` | `CategoryPanel._edited` / `_committed` / `_active_toggled` / `_reset` | Number field |
| `clap · NumberControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of a number field |
| `clap · PresetChips · *` | `CategoryPanel._preset_chosen` | Preset chips row |
| `clap · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` | One chip per preset |
| `clap · SeedControl · *` | `CategoryPanel._edited` | Seed field |
| `clap · Segmented/QPushButton · *` | `Segmented` -> `chosen` -> `ChoiceControl._chosen` | One button per enum choice |
| `rim · ChoiceControl · *` | `CategoryPanel._edited` / `_active_toggled` | Enum field |
| `rim · ChoiceControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of an enum field |
| `rim · Collapsible · *` | self-contained | Section shows / hides its fields |
| `rim · Collapsible/QToolButton · *` | `Collapsible` (internal) | Section header |
| `rim · NumberControl · *` | `CategoryPanel._edited` / `_committed` / `_active_toggled` / `_reset` | Number field |
| `rim · NumberControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of a number field |
| `rim · PresetChips · *` | `CategoryPanel._preset_chosen` | Preset chips row |
| `rim · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` | One chip per preset |
| `rim · SeedControl · *` | `CategoryPanel._edited` | Seed field |
| `rim · Segmented/QPushButton · *` | `Segmented` -> `chosen` -> `ChoiceControl._chosen` | One button per enum choice |
| `bass · ChoiceControl · *` | `CategoryPanel._edited` / `_active_toggled` | Enum field |
| `bass · ChoiceControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of an enum field |
| `bass · Collapsible · *` | self-contained | Section shows / hides its fields |
| `bass · Collapsible/QToolButton · *` | `Collapsible` (internal) | Section header |
| `bass · NumberControl · *` | `CategoryPanel._edited` / `_committed` / `_active_toggled` / `_reset` | Number field |
| `bass · NumberControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of a number field |
| `bass · PresetChips · *` | `CategoryPanel._preset_chosen` | Preset chips row |
| `bass · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` | One chip per preset |
| `bass · SeedControl · *` | `CategoryPanel._edited` | Seed field |
| `bass · Segmented/QPushButton · *` | `Segmented` -> `chosen` -> `ChoiceControl._chosen` | One button per enum choice |
| `laser · ChoiceControl · *` | `CategoryPanel._edited` / `_active_toggled` | Enum field |
| `laser · ChoiceControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of an enum field |
| `laser · Collapsible · *` | self-contained | Section shows / hides its fields |
| `laser · Collapsible/QToolButton · *` | `Collapsible` (internal) | Section header |
| `laser · NumberControl · *` | `CategoryPanel._edited` / `_committed` / `_active_toggled` / `_reset` | Number field |
| `laser · NumberControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of a number field |
| `laser · PresetChips · *` | `CategoryPanel._preset_chosen` | Preset chips row |
| `laser · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` | One chip per preset |
| `laser · SeedControl · *` | `CategoryPanel._edited` | Seed field |
| `laser · Segmented/QPushButton · *` | `Segmented` -> `chosen` -> `ChoiceControl._chosen` | One button per enum choice |
| `laser · WrapSegmented/QPushButton · *` | `WrapSegmented` -> `chosen` -> `ChoiceControl._chosen` | Enum with many choices, wrapping |
| `perc · ChoiceControl · *` | `CategoryPanel._edited` / `_active_toggled` | Enum field |
| `perc · ChoiceControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of an enum field |
| `perc · Collapsible · *` | self-contained | Section shows / hides its fields |
| `perc · Collapsible/QToolButton · *` | `Collapsible` (internal) | Section header |
| `perc · NumberControl · *` | `CategoryPanel._edited` / `_committed` / `_active_toggled` / `_reset` | Number field |
| `perc · NumberControl/ActiveDot · *` | `ParamControl` -> `activeToggled` | Dot of a number field |
| `perc · PresetChips · *` | `CategoryPanel._preset_chosen` | Preset chips row |
| `perc · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` | One chip per preset |
| `perc · SeedControl · *` | `CategoryPanel._edited` | Seed field |
| `perc · Segmented/QPushButton · *` | `Segmented` -> `chosen` -> `ChoiceControl._chosen` | One button per enum choice |
| `perc · WrapSegmented/QPushButton · *` | `WrapSegmented` -> `chosen` -> `ChoiceControl._chosen` | Enum with many choices, wrapping (model) |

### Main window: Bibliothek

| ID | Handler | Effect |
| --- | --- | --- |
| `library · DragList · library` | `LibraryPanel._picked` -> `MainWindow._load_preview` | WAV list with sidecar data; selecting previews; rows drag out as WAV files. Lists WAVs only (no MIDI, #439) |
| `library · QComboBox · LibraryPanel.category_box` | `LibraryPanel._show` | Filter by category (or 'Unlesbar') |
| `library · QLineEdit · LibraryPanel.search` | `LibraryPanel._show` | Search in name, preset, seed, key parameters |
| `library · QPushButton · Aktualisieren` | `LibraryPanel.refresh` | Re-scans the output folder |

### Main window: Goa-Arrangement page

| ID | Handler | Effect |
| --- | --- | --- |
| `goa-page · ActiveDot · Gefüllt: der Wert wird mitgeschickt. Leer: Stand` | `OptionForm._toggled` | Dot of an optional option: pass it / use the module default |
| `goa-page · NumberControl · *` | `OptionForm._edited` | BPM slider |
| `goa-page · OptionForm · -` | `GoaPanel.refresh` (via `changed`) | One option form per mode: preview plan, Render enabled or blocked with the module's message |
| `goa-page · PresetChips · *` | `OptionForm._edited` | Choice / multi-choice options (voices, styles) |
| `goa-page · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` / `changed` | One chip per choice |
| `goa-page · QLineEdit · Abschnitte` | `OptionForm._edited` (`textEdited`) | Free text option, checked by the module's parser |
| `goa-page · QLineEdit · Akkordfolge (Stufen)` | `OptionForm._edited` (`textEdited`) | Free text option |
| `goa-page · QLineEdit · Dichte` | `OptionForm._edited` (`textEdited`) | Free text option |
| `goa-page · QLineEdit · GoaPanel.folder_edit` | `GoaPanel._folder_typed` | New run folder (auto-named, never overwritten) below `<Ausgabeordner>/Goa` (#468); follows the shared settings (#450) |
| `goa-page · QPushButton · An Live senden` | `ResultActions.send_to_live` | Opens the Live page with the first sample WAV chosen; nothing is sent |
| `goa-page · QPushButton · In Bibliothek zeigen` | `ResultActions.show_in_library` | Shows the library with the first sample WAV selected |
| `goa-page · QLineEdit · Grundton` | `OptionForm._edited` (`textEdited`) | Free text option |
| `goa-page · QLineEdit · Register (Oktaven)` | `OptionForm._edited` (`textEdited`) | Free text option |
| `goa-page · QPushButton · Ordner öffnen` | `GoaPanel.open_folder` | Opens the run folder (or the last finished one) |
| `goa-page · QPushButton · Rendern` | `GoaPanel.start_render` | Runs goa_arrangement / goa_melody in a worker; MIDI + README + sample WAVs with sidecars (#414, fixed by #451) |
| `goa-page · Segmented · *` | `GoaPanel.set_mode` / `OptionForm` edits | Mode (Arrangement / Melodie) and enum options of the Goa generator |
| `goa-page · Segmented/QPushButton · *` | `Segmented` -> `chosen` | One button per mode / enum choice |
| `goa-page · StepEdit · Phrasenlänge (Takte)` | `OptionForm._edited` | Phrase length in bars |
| `goa-page · StepEdit · Seed` | `OptionForm._edited` | Seed (typed, Up/Down) |
| `goa-page · Toggle · Keine Samples rendern` | `OptionForm._edited` | Flag: MIDI only, no sample WAVs |

### Main window: Arrangement-Planer page

| ID | Handler | Effect |
| --- | --- | --- |
| `planner · PlannerCanvas · Energiekurve` | `PlannerPanel.refresh` (via `edited`) | Energy curve: click adds a drawn node, drag moves it, click on a default node takes it over, Shift+click adds a step, right click / Delete removes; the planner (`generate_plan`, `derive_timeline`) runs again and the element lanes follow |
| `planner · QPushButton · Gezeichnete Punkte löschen` | `PlannerPanel.clear_drawn` | Removes every drawn node (back to the planner's default curve) |
| `planner · QPushButton · Plan exportieren` | `PlannerPanel.export` | Writes the plan (arrangement-plan v0.1, checked with `plan_problems`) to `<Ausgabeordner>/Plans`, never overwrites; enabled only with a valid plan |
| `planner · QPushButton · Plan-Ordner öffnen` | `PlannerPanel.open_folder` | Opens `<Ausgabeordner>/Plans` (exists after the first export) |
| `planner · StepEdit · BPM` | `PlannerPanel._bpm_edited` | Tempo of the plan (20-999) |
| `planner · StepEdit · Länge` | `PlannerPanel._length_edited` | Track length in minutes or bars; a length the planner refuses shows the nearest ones |
| `planner · Stepper · *` | `PlannerPanel._setting` (`valueChanged`) | Change grid (1-64 bars) |
| `planner · Stepper/QPushButton · *` | `Stepper.step` | - / + of the change grid |
| `planner · WrapSegmented · *` | `PlannerPanel._genre_chosen` / `_unit_chosen` / `_setting` | Genre, length unit and the ten enum style settings of the planner |
| `planner · WrapSegmented/QPushButton · *` | `WrapSegmented` -> `chosen` | One button per choice |

### Main window: Live-Import page

| ID | Handler | Effect |
| --- | --- | --- |
| `live · QComboBox · LivePanel.track_box` | `LivePanel._inputs_changed` | Target track (new audio track at the end or an existing one) |
| `live · QLineEdit · LivePanel.project_edit` | `LivePanel._project_changed` (`textChanged`) | "Live-Projekt": folder with the test set's .als; a render from outside a project is copied into its `Samples/Drums/<category>` before the import (#413, via #451); a change discards the plan |
| `live · QPushButton · Wählen …` | `LivePanel._pick_project` | Folder dialog for the Live project |
| `live · QComboBox · LivePanel.wav_box` | `LivePanel._inputs_changed` | WAV to import (from the library folder or picked); a change discards the plan |
| `live · QPushButton · Andere Datei …` | `LivePanel._pick_file` | File dialog for a WAV outside the library |
| `live · QPushButton · Bibliothek lesen` | `LivePanel.reload_library` | Re-reads the WAV list |
| `live · QPushButton · In Live importieren` | `LivePanel.start_import` | Writes the clip (tested capabilities only); enabled only after plan + test-set confirmation |
| `live · QPushButton · Live-Set lesen` | `LivePanel.start_inspect` | Reads the WAV's sidecar and the set's tracks/scenes over AbletonOSC (read only); a render outside a project needs the "Live-Projekt" folder and names its copy target (#413) |
| `live · QPushButton · Plan prüfen` | `LivePanel.start_plan` | Shows exactly what would be written, nothing is sent yet |
| `live · Stepper · *` | `LivePanel._inputs_changed` (`valueChanged`) | Scene / cell (0 = first free) |
| `live · Stepper/QPushButton · *` | `Stepper.step` | - / + of the scene stepper |
| `live · ToggleRow · *` | `LivePanel._inputs_changed` / `_update_state` | Confirmations: 'unverified capability' (only shown when needed) and 'this is a test set' |
| `live · ToggleRow/Toggle · *` | `ToggleRow` -> `toggled` | The switch of a confirmation row |

### Main window: Copilot page

| ID | Handler | Effect |
| --- | --- | --- |
| `chat · QLineEdit · ChatPanel.input` | `ChatPanel.send` (Enter), `_update_state` | Question to the copilot |
| `chat · QPushButton · Senden` | `ChatPanel.send` | Sends through the guard; no tools, no Live writes (text in the page says so) |

### Goa window (Weitere Fenster)

| ID | Handler | Effect |
| --- | --- | --- |
| `goa · ChromeButton · Animation (Neon-Puls)` | `CompactGoaWindow.set_animation` | Neon pulse on/off (saved in the skin settings) |
| `goa · ChromeButton · Immer im Vordergrund` | `CompactGoaWindow.set_always_on_top` | Stay on top on/off (saved) |
| `goa · ChromeButton · Minimieren` | `QWidget.showMinimized` | Minimise |
| `goa · ChromeButton · Schliessen` | `QWidget.close` | Close (saves position/size) |
| `goa · ActiveDot · Gefüllt: der Wert wird mitgeschickt. Leer: Stand` | `OptionForm._toggled` | As on the Goa page (the window body is the same `GoaPanel`, #440 fixed in #450) |
| `goa · NumberControl · *` | `OptionForm._edited` | BPM slider |
| `goa · OptionForm · -` | `GoaPanel.refresh` (via `changed`) | One option form per mode |
| `goa · PresetChips · *` | `OptionForm._edited` | Choice / multi-choice options |
| `goa · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` / `changed` | One chip per choice |
| `goa · QLineEdit · Abschnitte` | `OptionForm._edited` (`textEdited`) | Free text option |
| `goa · QLineEdit · Akkordfolge (Stufen)` | `OptionForm._edited` (`textEdited`) | Free text option |
| `goa · QLineEdit · Dichte` | `OptionForm._edited` (`textEdited`) | Free text option |
| `goa · QLineEdit · GoaPanel.folder_edit` | `GoaPanel._folder_typed` | New run folder below `<Ausgabeordner>/Goa` (follows the shared settings) |
| `goa · QLineEdit · Grundton` | `OptionForm._edited` (`textEdited`) | Free text option |
| `goa · QLineEdit · Register (Oktaven)` | `OptionForm._edited` (`textEdited`) | Free text option |
| `goa · QPushButton · An Live senden` | `ResultActions.send_to_live` | Opens the main window's Live page with the first sample WAV chosen (only with a readable sidecar); nothing is sent |
| `goa · QPushButton · In Bibliothek zeigen` | `ResultActions.show_in_library` | Shows the main library with the first sample WAV selected |
| `goa · QPushButton · Ordner öffnen` | `GoaPanel.open_folder` | Opens the run folder |
| `goa · QPushButton · Rendern` | `GoaPanel.start_render` | Runs the Goa generator in a worker; the WAVs appear in the main library |
| `goa · Segmented · *` | `GoaPanel.set_mode` / `OptionForm` edits | Mode and enum options |
| `goa · Segmented/QPushButton · *` | `Segmented` -> `chosen` | One button per choice |
| `goa · StepEdit · Phrasenlänge (Takte)` | `OptionForm._edited` | Phrase length in bars |
| `goa · StepEdit · Seed` | `OptionForm._edited` | Seed |
| `goa · Toggle · Keine Samples rendern` | `OptionForm._edited` | Flag: MIDI only |

### Acid window

| ID | Handler | Effect |
| --- | --- | --- |
| `acid · QCheckBox · Animation` | `AcidWindow.set_animation` | Header/footer/grid animation on/off |
| `acid · QComboBox · AcidWindow.root_box` | `AcidWindow._scale_changed` (`activated`) | Root note; re-maps the line |
| `acid · QComboBox · AcidWindow.scale_box` | `AcidWindow._scale_changed` (`activated`) | Scale; re-maps the line |
| `acid · QLineEdit · AcidWindow.accent_edit` | read by `AcidWindow.generate` | Generator accent % |
| `acid · QLineEdit · AcidWindow.bpm_edit` | `AcidWindow._bpm_changed` (`editingFinished`) | Tempo for preview and MIDI |
| `acid · QLineEdit · AcidWindow.density_edit` | read by `AcidWindow.generate` | Generator density % |
| `acid · QLineEdit · AcidWindow.folder_edit` | read by save / export / open | Output folder (initial value from the main window, #439) |
| `acid · QLineEdit · AcidWindow.seed_edit` | read by `AcidWindow.generate` | Generator seed |
| `acid · QLineEdit · AcidWindow.slide_edit` | read by `AcidWindow.generate` | Generator slide % |
| `acid · QPushButton · Generieren` | `AcidWindow.generate` | New pattern from the generator fields |
| `acid · QPushButton · JSON speichern` | `AcidWindow.save_json` | Saves the pattern as JSON |
| `acid · QPushButton · Laden…` | `AcidWindow.load` | Loads a pattern JSON |
| `acid · QPushButton · MIDI exportieren` | `AcidWindow.export_midi` | Writes acid_<seed>.mid (not in the library, #439; not tested in Live) |
| `acid · QPushButton · Neuer Seed` | `AcidWindow.new_seed` | Random seed, then generate |
| `acid · QPushButton · Ordner öffnen` | `AcidWindow.open_folder` | Opens the output folder |
| `acid · QPushButton · Stopp` | `AcidWindow.stop_preview` | Stops the preview |
| `acid · QPushButton · Vorschau` | `AcidWindow.preview` | Rough preview WAV (no 303 sound) through the backend |
| `acid · QPushButton · WAV exportieren` | `AcidWindow.export_wav` | Writes the rough preview as WAV into the run folder `<Ausgabeordner>/Acid/acid_<seed>/` (shared rate/bit depth, no sidecar: no contract) |
| `acid · QPushButton · In Bibliothek zeigen` | `ResultActions.show_in_library` | Shows the main library with the exported WAV selected |
| `acid · QPushButton · An Live senden` | `ResultActions.send_to_live` | Disabled for acid WAVs (no sidecar); the row says why |
| `acid · QSpinBox · AcidWindow.length_spin` | `AcidWindow._length_changed` | Pattern length in steps |
| `acid · QSpinBox · AcidWindow.octave_spin` | `AcidWindow._octave_changed` | Base octave |
| `acid · QSpinBox · AcidWindow.range_spin` | read by `AcidWindow.generate` | Octave range of the generator |
| `acid · StepGridWidget · AcidWindow.grid` | `changed` -> clears the status | Step grid: note, gate, accent, slide per step (edits the model) |

### Laser-Blaster window

| ID | Handler | Effect |
| --- | --- | --- |
| `blaster · BlasterWidget · Abzug drücken: Klick auf den Abzug, Leertaste od` | `BlasterWindow._on_gun_triggered` / `_on_gun_released` | The gun: renders a full shot (worker), plays it, adds it to the history; hold = autofire when enabled |
| `blaster · Collapsible · *` | self-contained | 'Erweitert' sections of the groups |
| `blaster · Collapsible/QToolButton · *` | `Collapsible` (internal) | Section header: expand / collapse |
| `blaster · CurveEditor · Sweep-Kurve` | `BlasterWindow._on_edited` / `_on_committed` / `_reset` | Sweep time and curve; Ctrl+click resets |
| `blaster · DragList · BlasterWindow.history` | `BlasterWindow._on_select` / `_on_replay_item` | Shots of this session (temp folder, not the library, #439); select = show, double click = replay; drag out |
| `blaster · EnumRow · *` | `BlasterWindow._on_edited` | Enum fields (wave, pattern, filter type ...) |
| `blaster · NumberControl · *` | `BlasterWindow._on_edited` / `_on_committed` | Number fields of all groups (knobs, sliders); undo step on commit |
| `blaster · PresetChips · *` | `BlasterWindow._on_preset_chip` / `EnumRow` | Laser presets and long enums |
| `blaster · PresetChips/QPushButton · *` | `PresetChips` -> `chosen` | One chip per preset / choice |
| `blaster · QCheckBox · Dauerfeuer beim Halten` | state, read in `BlasterWindow._on_gun_triggered` | Hold the trigger = repeat at the fire rate (allowed without own receiver) |
| `blaster · QCheckBox · Live-Vorschau (gekürzt)` | `BlasterWindow._on_live_toggled` | Shortened preview after each change |
| `blaster · QCheckBox · Rückstoß-Animation` | `BlasterWindow._on_animation` | Recoil animation on/off |
| `blaster · QLineEdit · BlasterWindow.seed_edit` | `BlasterWindow._on_seed_edited` | Seed of the next shot |
| `blaster · QPushButton · A > B` | `BlasterWindow.copy_to_other_slot` | Copies the settings into the other A/B slot |
| `blaster · QPushButton · Alles würfeln` | `BlasterWindow._on_random_all` | Randomises all unlocked groups (Ctrl+R) |
| `blaster · QPushButton · In Bibliothek speichern` | `BlasterWindow.save_to_library` | Writes the selected shot as WAV + sidecar into `<Ausgabeordner>/Samples/FX/Lasers` (worker, never overwriting) |
| `blaster · QPushButton · In Bibliothek zeigen` | `ResultActions.show_in_library` | Shows the main library with the saved WAV selected |
| `blaster · QPushButton · An Live senden` | `ResultActions.send_to_live` | Opens the Live page with the saved WAV chosen; nothing is sent |
| `blaster · QPushButton · Bank exportieren …` | `BlasterWindow.export_bank_dialog` | Writes WAV + sidecar per shot into Samples/FX/Lasers/laser_bank_NNN under the chosen folder (in the library when chosen inside the output folder) |
| `blaster · QPushButton · Glitch` | `BlasterWindow._on_dim_clicked` | Weapon dimension |
| `blaster · QPushButton · Ion` | `BlasterWindow._on_dim_clicked` | Weapon dimension |
| `blaster · QPushButton · Klassik` | `BlasterWindow._on_dim_clicked` | Weapon dimension (family + look) |
| `blaster · QPushButton · Nochmal abspielen` | `BlasterWindow.replay_selected` | Replays the selected shot |
| `blaster · QPushButton · Plasma` | `BlasterWindow._on_dim_clicked` | Weapon dimension |
| `blaster · QPushButton · Preset laden …` | `BlasterWindow.load_preset_dialog` | Loads a preset file |
| `blaster · QPushButton · Preset speichern …` | `BlasterWindow.save_preset_dialog` | Saves the settings as a preset file |
| `blaster · QPushButton · Riss` | `BlasterWindow._on_dim_clicked` | Weapon dimension |
| `blaster · QPushButton · Rückgängig` | `BlasterWindow.undo` | Undo (Ctrl+Z) |
| `blaster · QPushButton · Sperren` | `BlasterWindow._on_lock(group)` | Locks a group against dice and presets (one per group) |
| `blaster · QPushButton · Sub-Boom` | `BlasterWindow._on_dim_clicked` | Weapon dimension |
| `blaster · QPushButton · Vollqualität rendern` | `BlasterWindow.pull_trigger` | Same as the trigger (Ctrl+Enter) |
| `blaster · QPushButton · Wiederholen` | `BlasterWindow.redo` | Redo (Ctrl+Y) |
| `blaster · QPushButton · Würfeln` | `BlasterWindow._on_random_clicked(group)` | Randomises one group (one button per group) |
| `blaster · QShortcut · Ctrl+1` | `BlasterWindow._slot('A')` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+2` | `BlasterWindow._slot('B')` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+Down` | `BlasterWindow.bump_seed(-1)` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+Enter` | `BlasterWindow.pull_trigger` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+O` | `BlasterWindow.load_preset_dialog` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+R` | `BlasterWindow._on_random_all` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+Return` | `BlasterWindow.pull_trigger` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+S` | `BlasterWindow.save_preset_dialog` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+Shift+Z` | `BlasterWindow.redo` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+Up` | `BlasterWindow.bump_seed(+1)` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+Y` | `BlasterWindow.redo` | Keyboard shortcut (window-wide) |
| `blaster · QShortcut · Ctrl+Z` | `BlasterWindow.undo` | Keyboard shortcut (window-wide) |
| `blaster · QSpinBox · BlasterWindow.bank_count` | read by `BlasterWindow.export_bank_dialog` | Number of shots in a bank |
| `blaster · Segmented · *` | `BlasterWindow._on_ab` / `_on_echo_mode` / `EnumRow` | A/B slot, echo mode and short enums |
| `blaster · Segmented/QPushButton · *` | `Segmented` -> `chosen` | One button per choice |
| `blaster · XYPad · Start-Ton und End-Ton` | `BlasterWindow._on_edited` / `_on_committed` / `_reset` | Start / end pitch in one pad; Ctrl+click resets |
