# TODO — remaining scope

What is still to be implemented, compiled from the README status, the changelog, the PSD domain list and the UI wiring as of 2026-09-19. Requirement IDs refer to [`docs/SRS.md`](docs/SRS.md). "Logic exists" means the domain module is present and tested but no screen uses it.

Out of scope for v1 (see PSD §5): post-processing/stacking beyond calibration and photometry, planetary imaging, mobile apps, a bundled guiding engine, an MCP/LLM control surface, predictive guiding.

## Placeholder screens ("not implemented yet")

- [ ] **Planning > Sequence** (`SEQ`, `SEQ-ADV`) — basic and advanced sequencer UI, templates, file-name macros. Logic exists (`galileo.sequencer.*`).
- [ ] **Planning > Scheduler** (`SCHED`) — job queue UI, constraints, multi-night progress. Logic exists (`galileo.scheduler`).
- [ ] **Science > Variable Stars** (`VST`, `VST-AN`) — target planning, photometry, AAVSO report UI. Logic exists (`galileo.vstarget.*`).
- [ ] **Options** — the menu and a page per section exist, and **Library** has its real settings (AstroFiler's configuration screen); the other pages (Equipment, Star Atlas, Planning, Framing, Imaging, Guiding, Focus, Solve, Science) are still placeholders, and theme/layout customization (`UI`), notification configuration and per-user preferences are not built.

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

- [ ] Library: `fitsProcessing.createMasterCalibrationFrames` (the older `galileo.library.core.calibration` path) creates no masters — it looks sessions up by an id that is `None`. The screens and the `auto_calibration` command use `galileo.library.core.auto_calibration`, which works; remove or repair the older path.
- [ ] Library: the repository statistics dashboard (`LIB-080`, `TC-LIB-080`) was removed from the Library on request and is not built; either reinstate it or retire the requirement in the SRS/RTM.
- [ ] Library: two source-adapter sets coexist — `galileo.library.adapters` (SMB/FTP/SFTP, small) and `galileo.library.services.telescope` (AstroFiler's full smart-telescope manager, used by the Download dialog). Merge them behind the `RemoteSourceAdapter` interface in SDD §4.23.
- [ ] Library: the iTelescope password is stored in plain text in `library.ini` (as AstroFiler did); move it to the OS keychain (`NFR-SEC`).
- [ ] Library: the Sessions and Images screens run their queries on the UI thread; move the slow ones to a worker (`ARCH`, concurrency model).
- [ ] Star Atlas: comets/asteroids/satellites (`SKYMAP-040`), FOV/mount overlay (`SKYMAP-050`), slew-from-map polish (`SKYMAP-060`).
- [ ] Equipment pages poll devices on the UI thread while visible; move to a worker thread.
- [ ] Parked-mount guard does not cover Sync or tracking on/off.
- [ ] Plugin framework (`PLUG`): marketplace raises `NotImplementedError` (`galileo/plugins.py`); `VST`/`VST-AN` not yet packaged as installable first-party plugins.
- [ ] `galileo/vstarget/analysis/transform_apply.py` applies a placeholder correction (`Tv * 0.05`); implement the real transformation formula.
- [ ] Framing (`FRAME`): verify survey-image overlay, mosaic-to-sequencer handoff and constellation/grid overlay against the SRS; the README lists only the input panel as working.
- [ ] Planning (`SKY`): horizon-profile editing (`SKY-040`), survey thumbnail caching (`SKY-080`), geocoding (`SKY-090`) — confirm wired to the UI.

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
