# TODO — remaining scope

What is still to be implemented, compiled from the README status, the changelog, the PSD domain list and the UI wiring as of 2026-09-23. Requirement IDs refer to [`docs/SRS.md`](docs/SRS.md). "Logic exists" means the domain module is present and tested but no screen uses it.

Out of scope for v1 (see PSD §5): post-processing/stacking beyond calibration and photometry, planetary imaging, mobile apps, a bundled guiding engine, an MCP/LLM control surface, predictive guiding.

## Placeholder screens ("not implemented yet")

- [ ] **Planning > Sequence** — now the **Sessions** screen (`SES`, formerly `SEQ`/`SEQ-ADV`; SRS §4.5 execution engine, §4.5a screen authoring/lifecycle, §4.6 nested instruction/condition/trigger blocks). Execution-engine logic exists (`galileo.sequencer.*`), but there is no `galileo.ui.sessions` module at all yet — `tests/test_ses.py`'s `SES-100`–`230` range (block-based drag/drop authoring, per-Pier ownership, Save/Save-as-Template/Load-from-Template/Schedule/Deschedule, the v1 block catalog) is written against a screen that doesn't exist.
- [ ] **Planning > Scheduler** (`SCHED`) — job queue UI, constraints, multi-night progress. Logic exists (`galileo.scheduler`).
- [ ] **Science > Variable Stars** (`VST`, `VST-AN`) — target planning, photometry, AAVSO report UI. Logic exists (`galileo.plugins.vstarget.*`) and is tested, but note the requirements themselves moved out of core SRS into the plugin's own doc chain (`docs/plugins/vstarget/SRS.md`) — this is now a plugin-scoped gap, not a core one (see also the plugin-packaging gap below).
- [ ] **Options** — the menu and a page per section exist. **Library** (AstroFiler's configuration screen), **Star Atlas** (horizon file upload), **Planning** (the "do not slew where obstructed" option) and **Imaging** (`IMG-170`'s saved-frame BITPIX/sample-format picker) have real settings; the other pages (Equipment, Framing, Guiding, Focus, Solve, Science) are still placeholders, and theme/layout customization (`UI`), notification configuration and per-user preferences are not built.

## Domain logic with no UI

- [ ] Autofocus (`FOC`) — the Focus screen (`galileo/ui/focus.py`) starts, stops and displays a run with its V-curve. Still to do: trigger configuration, saving step size/points/exposure/backlash per profile (`FOC-070`), running the Aberration Inspector from the screen (`FOC-080`; it also still reads the camera without exposing), CFZ and Advisor tools, and recording runs for review (`FOC-040`).
- [ ] Plate solving (`PLT`) — the Solve screen (`galileo/ui/solve.py`) captures, solves, syncs/slews and shows results. Still to do: solver configuration UI (ASTAP path, search radius, field-of-view hint per profile — `PLT-060`), the astrometry.net backend (`_run_astrometry` is a stub), Mount Model and Polar Alignment, Bin/Gain/ISO/Dark/Filter options for the solve exposure (the camera capture path can't set them), and an Options > Solve page. `PlateSolver.solve_and_center` (`PLT-040`; nothing calls it yet — the sequencer and meridian flip, `MFLIP-030`, are meant to) slews back to the target without first syncing to the solution, so it cannot correct a pointing error, and compares RA without `cos(Dec)`; when those callers are written, use `SolveWorkflow` (sync-then-slew) or fix it first.
- [ ] Calibration / Flat Wizard (`CAL`).
- [ ] Meridian flip (`MFLIP`).
- [ ] Safety and weather (`SAFE`) — unsafe-condition handling, safe-park.
- [ ] Dome slaving (`DOME`).
- [ ] Session history review (`HIST`).
- [ ] Notifications configuration (`NOTIF`).
- [ ] Multi-Pier status dashboard (`OBS`).

## Known gaps

- [x] ~~Library: `fitsProcessing.createMasterCalibrationFrames` (the older `galileo.library.core.calibration` path) creates no masters — it looks sessions up by an id that is `None`.~~ Removed: `galileo/library/core/calibration.py` (`CalibrationProcessor`) and its three `fitsProcessing` wrapper methods (`createMasterCalibrationFrames`, `createMasterCalibrationFramesForSessions`, `checkCalibrationSessionsForMasters`) had zero callers anywhere in the app, CLI or tests — the working path is `galileo.library.core.auto_calibration`, already used everywhere. Deleted rather than repaired a broken, unreachable duplicate.
- [x] ~~Library: the Mappings screen's **Reorganize Files** and **Apply Mappings** actions are no-ops.~~ The six dead-end methods this described (`apply_database_mappings`, `reorganize_repository_files`, `reorganize_file`, `calculate_new_file_path`, `cleanup_empty_directories`, `apply_file_folder_mappings`) were never wired to any button and duplicated the real, working per-row Apply path — removed. That real path (`apply_single_mapping`) now honours all three checkboxes (Apply mappings to database / Update FITS headers on disk / Reorganize repository folders) independently instead of ignoring two of them; new test `test_mappings_apply_button_gates_each_effect_on_its_own_checkbox`.
- [x] ~~Library: `auto_calibration.py`'s quality-assessment step accepts a `generate_report` flag but never writes one.~~ `generate_quality_report()` now writes a per-file CSV (star count, FWHM, eccentricity, HFR, SNR, image scale, a summary row) to a new `galileo.platform.get_reports_dir()`; wired into `perform_quality_assessment`'s `generate_report` path, which the `galileo-auto-calibration --report` CLI flag and Options-driven quality runs both reach. New test `test_tc_lib_070_quality_assessment_writes_a_report_when_requested`.
- [x] ~~Library: `auto_calibration.py`'s workflow orchestrator reports a hardcoded `light_frames_calibrated = 10`.~~ `runAutoCalibrationWorkflow`'s `calibrate` step now diffs `get_calibration_statistics()`'s `calibrated_frames` before/after the run for the real count — the same number the Auto-Calibration dialog displays to the user. New test `test_tc_lib_060_workflow_reports_the_real_calibrated_frame_count`.
- [ ] Library: the repository statistics dashboard (`LIB-080`, `TC-LIB-080`) was removed from the Library on request and is not built; either reinstate it or retire the requirement in the SRS/RTM.
- [ ] Library: two source-adapter sets coexist — `galileo.library.adapters` (SMB/FTP/SFTP, small) and `galileo.library.services.telescope` (AstroFiler's full smart-telescope manager, used by the Download dialog). Merge them behind the `RemoteSourceAdapter` interface in SDD §4.23.
- [ ] Library: the iTelescope password is stored in plain text in `library.ini` (as AstroFiler did); move it to the OS keychain (`NFR-SEC`).
- [ ] Library: the Sessions and Images screens run their queries on the UI thread; move the slow ones to a worker (`ARCH`, concurrency model).
- [ ] Star Atlas: comets/asteroids/satellites (`SKYMAP-040`), FOV/mount overlay (`SKYMAP-050`), slew-from-map polish (`SKYMAP-060`).
- [ ] Equipment pages poll devices on the UI thread while visible; move to a worker thread.
- [ ] Parked-mount guard does not cover Sync or tracking on/off.
- [ ] Horizon obstruction guard (`SKYMAP-080`, `galileo.core.slew_guard`) checks only the slew destination, not the path the mount takes; it skips jogging and Find Home, treats RA/Dec as of date, and does nothing for an Observatory with no latitude/longitude.
- [ ] Plugin framework (`PLUG`): marketplace raises `NotImplementedError` (`galileo/plugins/__init__.py`); `VST`/`VST-AN` moved to `galileo/plugins/vstarget/` (nested under the plugin framework, per its updated ADR-VST-001) but still pre-loaded/imported directly rather than discovered via entry points — not yet a genuinely installable first-party plugin.
- [x] ~~`galileo/vstarget/analysis/transform_apply.py` applies a placeholder correction (`Tv * 0.05`); implement the real transformation formula.~~ `apply_transformation` (now `galileo/plugins/vstarget/analysis/transform_apply.py`) takes the whole set of same-epoch, same-target measurements across filters (matching VST-AN-070's literal "multi-filter observations" wording, which a single-``PhotometryResult`` signature couldn't satisfy — a colour index needs two filters) and applies the real AAVSO colour transformation: B/V pair -> `(B-V)_std = Tbv*(b-v)`, `V' = v + Tv*(B-V)_std`, `B' = V' + (B-V)_std`; V/R pair used as a fallback via `Tvr`/`Tr` when there's no B. A lone filter with no companion is passed through unchanged with `is_transformed=False` rather than claiming a correction that was never computed. Test `test_tc_vst_an_070_apply_transformation_to_multifilter` rewritten to assert the actual corrected magnitudes, not just that *something* changed.
- [ ] Framing (`FRAME`): verify survey-image overlay, mosaic-to-sequencer handoff and constellation/grid overlay against the SRS; the README lists only the input panel as working.
- [ ] Planning (`SKY`): horizon-profile editing (`SKY-040`; upload, display and clearing exist under Options > Star Atlas, but there is no point-by-point editing), survey thumbnail caching (`SKY-080`), geocoding (`SKY-090`) — confirm wired to the UI.

## Non-functional and release

- [ ] `NFR-INSTALL` — one-step installer per platform (current launch scripts are temporary).
- [ ] `NFR-PORT` — verify on macOS, Linux and Raspberry Pi 5; only Windows appears exercised.
- [ ] `NFR-I18N` — confirm all UI strings are externalized.
- [ ] `NFR-SEC` — review handling of WAN-exposed INDI/Alpaca endpoints.
- [ ] `NFR-REL` — soak tests and an overnight run with transient disconnects.
- [ ] Hardware/integration tests against the reference observatory (roll-off roof, two Seestars) and real PHD2/solver installs.
- [ ] CI — no `.github/` workflow; add lint (`ruff`), types (`mypy`) and test runs.
- [ ] Crash reporting (`LOG`) — confirm implemented.
- [ ] `alpyca` is commented out in `pyproject.toml`; confirm the Alpaca adapters don't need it.
- [ ] Keep the README status section and `CHANGELOG.md` current as items close.
