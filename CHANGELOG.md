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
