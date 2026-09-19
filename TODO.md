# TODO — remaining scope

What is still to be implemented, compiled from the README status, the changelog, the PSD domain list and the UI wiring as of 2026-09-19. Requirement IDs refer to [`docs/SRS.md`](docs/SRS.md). "Logic exists" means the domain module is present and tested but no screen uses it.

Out of scope for v1 (see PSD §5): post-processing/stacking beyond calibration and photometry, planetary imaging, mobile apps, a bundled guiding engine, an MCP/LLM control surface, predictive guiding.

## Placeholder screens ("not implemented yet")

- [ ] **Planning > Sequence** (`SEQ`, `SEQ-ADV`) — basic and advanced sequencer UI, templates, file-name macros. Logic exists (`galileo.sequencer.*`).
- [ ] **Planning > Scheduler** (`SCHED`) — job queue UI, constraints, multi-night progress. Logic exists (`galileo.scheduler`).
- [ ] **Library** (`LIB`) — repository scan/ingest, dedup, session view, master calibration, quality metrics, cloud sync UI. Backend and CLI commands exist.
- [ ] **Science > Variable Stars** (`VST`, `VST-AN`) — target planning, photometry, AAVSO report UI. Logic exists (`galileo.vstarget.*`).
- [ ] **Options** — the menu and a placeholder page per section (Equipment, Star Atlas, Planning, Framing, Imaging, Guiding, Library, Science) now exist; the actual settings, theme/layout customization (`UI`), notification configuration and per-user preferences do not.

## Domain logic with no UI

- [ ] Autofocus (`FOC`) — run UI, trigger configuration, V-curve display. Only the star overlay/HFR in `galileo/ui/imaging.py` uses it today.
- [ ] Plate solving (`PLT`) — solve-and-center, solver configuration.
- [ ] Calibration / Flat Wizard (`CAL`).
- [ ] Meridian flip (`MFLIP`).
- [ ] Safety and weather (`SAFE`) — unsafe-condition handling, safe-park.
- [ ] Dome slaving (`DOME`).
- [ ] Session history review (`HIST`).
- [ ] Notifications configuration (`NOTIF`).
- [ ] Multi-Pier status dashboard (`OBS`).

## Known gaps

- [ ] Imaging tab: capture does not move the filter wheel; the Filter box only labels the frame.
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
