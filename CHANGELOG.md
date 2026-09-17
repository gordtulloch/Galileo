# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This project does not yet follow Semantic Versioning releases (see `README.md` status) — entries accumulate under `[Unreleased]` until the first tagged release.

## [Unreleased]

### Added

- `CLAUDE.md` guidance file documenting the codebase's architecture, requirement-traceability chain, test conventions, and module map for AI-assisted development.
- `requirements.txt` / `requirements-dev.txt`, mirroring `pyproject.toml`'s dependency groups for environments not using `pip install -e .`.
- `run.sh` / `run.ps1` launch scripts that locate the project's `.venv` (or fall back to `python`/`python3` on `PATH`) and start the app from the repository root regardless of caller working directory.
- Startup splash screen (`galileo/app.py`) showing `assets/images/logo.png` with its transparent background preserved, held on screen for 5 seconds before the main window appears.
- N.I.N.A.-style application shell (`galileo/ui/app_window.py`, `galileo/ui/theme.py`, `galileo/ui/icons.py`):
  - Dark/light QSS themes (palette sampled from N.I.N.A.'s own default theme) with a customizable accent color.
  - A primary icon sidebar (Equipment, Sky Atlas, Framing, Flat Wizard, Sequence, Imaging, Scheduler, Library, Variable Stars, Options), each icon drawn at runtime via `QPainter` rather than shipped as image assets.
  - A Power (quit) button plus three small utility buttons at the bottom of the sidebar: theme toggle (live icon/color re-render), online manual link, and an About dialog.
  - A top bar with Observatory and Pier selectors (see Persistence below).
  - A status bar.
- Equipment section: a context-sensitive secondary sidebar for device categories (Camera, Mount, Filter Wheel, Focuser, Rotator, Guider, Switch, Flat Panel, Weather, Dome, Safety Monitor), each with a Driver (Alpaca/INDI) / Server / Port / Connect panel that performs a real device scan, plus a live scrolling log pane (see Logging below).
- Sky Atlas and Framing pages: real search-criteria / target-and-mosaic-input side panels, wired to the existing `galileo.planning.sky_atlas` and `galileo.planning.framing` backends instead of a placeholder.
- Alpaca Management API discovery (`galileo.adapters.alpaca.get_configured_devices`), querying `GET /management/v1/configureddevices` before touching a specific device — the standard Alpaca discovery sequence, adapted from the pattern in AstroLlama's `alpaca_device_discovery_tool.py`.
- `.local` mDNS hostname resolution (`resolve_mdns_host`, via the `zeroconf` package) for both the INDI and Alpaca adapters, so hostnames like a Seestar's `seestar.local` Alpaca bridge resolve correctly on Windows (which does not resolve `.local` names without Bonjour installed) — ported from the approach proven in the author's VSTarget project.
- A `Port` field (default 32323 for Alpaca, matching the project's own Seestar S30/S30 Pro reference hardware; 7624 for INDI) alongside Driver/Server on each Equipment device page, editable per-device rather than a hardcoded guess.
- Persisted Observatory/Pier settings:
  - `ObservatoryRecord` (Name, Latitude, Longitude, Timezone, Physical Address, Owner) and `PierRecord` (Name, Observatory foreign key) Peewee models (`galileo/library/models/observatory.py`), added to the shared application database.
  - Manager functions `list_observatories`/`create_observatory`/`list_piers`/`create_pier` (`galileo/observatory.py`).
  - Top-bar "New Observatory…" / "New Pier…" creation dialogs; Pier's Observatory is set automatically from whichever Observatory is currently selected.
- Persisted per-Pier device configuration: each Equipment device-category page now has a Save button (bottom right, above the log pane) that stores its Driver/Server/Port and the device picked from the scan results against the currently selected Observatory/Pier (`DeviceConfigRecord`, `galileo/library/models/device_config.py`; `get_device_config`/`save_device_config` in `galileo/observatory.py`). Switching Pier (or Observatory) reloads every device page's fields from that Pier's saved settings. On application startup, if a saved Observatory/Pier exists it is loaded automatically, and if that Pier has a saved camera device, Galileo attempts to connect to it immediately rather than leaving the user to reconnect by hand.
- Camera page now supports any number of additional, independently configured non-guide cameras sharing the same Driver/Server/Port connection as the primary imaging camera — e.g. a Seestar S30 Pro's wide-field camera, exposed as a second device on the same Alpaca bridge. A "+" button next to the "Camera" heading appends a new camera panel (each with its own Device/Pixel Size/Sensor Width/Sensor Height/Sensor Name fields and a Remove button, except the always-present, non-removable Primary panel); the panel list sits in a scroll area since it has no fixed upper bound. A Scan reports what it found (or a failure) to the log pane and the status bar rather than a separate on-screen results box; each panel's Device combo is populated directly from the scan. `DeviceConfigRecord` gained a `slot` column (`"primary"`, `"camera_2"`, `"camera_3"`, …, unique per Pier/category/slot) plus `pixel_size_um`/`sensor_width_px`/`sensor_height_px`/`sensor_name` columns; `get_device_config`/`save_device_config` take a `slot` argument, a new `list_device_config_slots` reports which slots exist (used to rebuild the right number of panels on load), and `delete_device_config` prunes a slot removed from the page. Each panel has its own "Download Info" button that live-queries the device's own pixel size and sensor dimensions over its connection (`AlpacaCameraAdapter.get_sensor_info`, reading the standard ASCOM `PixelSizeX`/`CameraXSize`/`CameraYSize`/`SensorName` properties — works today; `IndiCameraAdapter.get_sensor_info` reads INDI's equivalent `CCD_INFO` fields but is limited by this codebase's current INDI adapter being a lightweight stub, so real hardware support depends on a future real pyindi-client property-fetch). Startup/Pier-switch auto-connect now attempts every configured camera panel independently.
- Focuser page rebuilt on the same multi-device pattern as Camera (a telescope can expose more than one focuser) — a "+" next to the "Focuser" heading adds another panel sharing the connection, each with its own Remove button except the always-present Primary panel, all in a scroll area, with Scan results going to the log/status bar rather than an on-screen list. Each focuser panel is also a live status screen: Is Moving, Is Settling, Max Increment, Max Step, Position (current), Position (target, editable, with a Move button), Temperature Compensation (toggle), and Temperature, refreshed automatically every 2 seconds once connected via a per-panel Connect button (also attempted automatically on startup/Pier-switch for any panel with a saved device). Added `AlpacaFocuserAdapter.get_status()`/`set_temp_comp()` (standard ASCOM `IFocuserV3` properties — `IsMoving`/`Position`/`MaxIncrement`/`MaxStep`/`TempComp`/`Temperature`; ASCOM has no standard "is settling" property, so that field always reports `False` for Alpaca) and the equivalent `IndiFocuserAdapter` methods (limited by this codebase's INDI adapter still being a lightweight stub, same caveat as the camera adapter). Factored the shared "instantiate + connect one device backend" logic out of the Camera page's auto-connect into `AppWindow._connect_device_adapter`, reused by both pages.
- Runtime logging service overhaul (`galileo/diagnostics.py`):
  - Logs to a datestamped file under the application's own `logs/` directory (not the per-platform user log directory).
  - The log file is reset (truncated) at the start of every run instead of accumulating across same-day runs.
  - The root logger is set to `DEBUG` and a single file handler is shared process-wide, so log output from every module — not only calls routed through `DiagnosticsService`'s own methods — is captured.
  - A process-wide in-memory tail buffer (`get_recent_log_lines`) feeds a live, auto-scrolling, 10-line-tall (scrollable to ~300 lines of history) log pane on every Equipment device screen, refreshed on a shared timer.
- `docs/SECURITY.md`, documenting WAN-exposure security implications for INDI/Alpaca (`NFR-SEC-020`).
- `galileo/ui/translations/galileo_en.ts`, a base Qt Linguist translation resource (`NFR-I18N-010`).
- New SRS requirements `LOG-050` (log file resets every run) and `LOG-060` (per-device-screen log pane), with matching `docs/PSD.md`, `docs/SDD.md` (§4.22), and `docs/RTM.md` updates.
- This `CHANGELOG.md`.

### Changed

- The on-screen log pane on every Equipment device-category screen now shows INFO level and above only, while the on-disk datestamped log file keeps every DEBUG-level record — `galileo/diagnostics.py`'s in-memory tail buffer handler (feeding `get_recent_log_lines`) now has its own `INFO` level, separate from the root logger's `DEBUG` level that still gates what reaches the file handler. Previously the on-screen pane showed DEBUG noise not meant for a user glancing at the app's status.
- `galileo/app.py` now calls `galileo.library.database.init_db()` on startup — previously only the CLI tools (`galileo-load-repo`, etc.) initialized the database, so the GUI never persisted anything at all.
- Alpaca and INDI adapters accept a combined `host:port` address (in addition to separate `host`/`port` arguments), matching the convention `alpyca` and the Alpaca Management API use.
- `README.md` rewritten to describe the application's actual current state (working shell, Equipment scanning, Observatory/Pier persistence, Sky Atlas/Framing panels, logging service, versus still-placeholder Sequencer/Imaging/Scheduler/Library/Variable Stars/Flat Wizard/Options screens) instead of the original "pre-alpha, no code written yet" description, and added a "Getting Started" section.
- `docs/PSD.md`, `docs/SRS.md`, `docs/SDD.md`, `docs/RTM.md` updated for the logging service's actual behavior and requirement/coverage counts (235 SRS requirements, up from 233; 249 RTM-covered requirements, up from 247).
- Fixed `pyproject.toml`: the `dependencies` array was nested under `[project.scripts]` instead of `[project]` due to TOML table-ordering (a key/value pair belongs to the nearest preceding table header), so `pip install` was silently never installing the project's own declared dependencies.
- `CLAUDE.md` now requires a `CHANGELOG.md` entry alongside every future change to this repository.
- `README.md`'s Tech Stack section now addresses the GIL directly (UI responsiveness is Qt's native C++ rendering, not an interpreter question; CPU-bound work runs off the main thread in a `ProcessPoolExecutor`), matching the rationale already in `docs/SDD.md` §2.1's accepted-risks table.

### Fixed

- 18 failing tests across the suite, including:
  - `AlpacaFlatPanelAdapter` was missing entirely, so no Alpaca adapter existed for the `FlatPanel` device category.
  - `DevicePool.get_properties()` looked up devices by category key instead of by device name.
  - `ConnectionMonitor.check_once()` discarded an async `get_properties()` result without awaiting it, defeating its own timeout detection.
  - `GuidingService.start_guiding()` skipped the guiding-state confirmation wait whenever a guider client was injected (i.e. always in practice).
  - `Event` subclasses' declared fields (`timestamp`, `recoverable`, `explanation`, etc.) never actually reflected the value passed at construction.
  - A session-scoped pytest fixture was writing a synthetic sky-atlas catalog into the real per-user AppData directory instead of an isolated tmp path, leaking stale data across unrelated runs.
  - A Windows-incompatible manual `asyncio.get_event_loop()` call in a test, a `MagicMock(name=...)` misuse (the constructor kwarg sets the mock's repr, not a `.name` attribute), and a profile export/import test that used the same directory for both internal storage and the "exported" copy.
- The Camera/Equipment "Connect" action always reporting "No devices found," reachable server or not, because `AlpacaAdapter.list_available_devices()` was a hardcoded stub that never made a network call.
- The Camera/Equipment "Connect" action failing with "connection actively refused" against real devices — root-caused to two compounding issues: Windows not resolving `.local` mDNS hostnames without Bonjour, and the UI silently defaulting to the wrong Alpaca port for non-standard servers (now both fixed above).
- Camera page: a camera panel added via "+" *after* a scan had already run (e.g. scanning, seeing a second detected camera, then clicking "+" for it) had an empty, unselectable Device list — the scan only populated the panels that existed at scan time. New panels now seed their Device list from the most recent scan's results.
