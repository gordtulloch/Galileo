# Galileo — SDD (Software Design Description)

| | |
|---|---|
| **Project** | Galileo — Cross-Platform Astrophotography Imaging Suite |
| **Document** | SDD (Software Design Description), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-09-16 |
| **Upstream documents** | [PSD (Project Scope Document)](PSD.md), [SRS (Software Requirements Specification)](SRS.md) |
| **Downstream document** | RTM (Requirements Traceability Matrix) |

---

## 1. Introduction

### 1.1 Purpose

This SDD describes how Galileo's architecture and module decomposition satisfy the requirements enumerated in the [SRS](SRS.md). Each module section below states which SRS requirement IDs it is responsible for satisfying, so the RTM can be built as a direct join between this document and the SRS.

### 1.2 Scope

Covers system architecture, the technology-stack decision, module/component decomposition (one section per SRS domain), data design, interface design, concurrency/error-handling design, and deployment topology. It does not specify class-level APIs or pixel-level UI layout — that is implementation detail below the SDD's altitude.

### 1.3 References

Acronyms and abbreviations used throughout this document are defined at first use, or in the PSD's Glossary (PSD.md, Section 15) if not defined here.

- [Project Scope Document](PSD.md)
- [SRS](SRS.md)
- Qt for Python (PySide6): https://doc.qt.io/qtforpython/
- INDI Python client: https://github.com/indilib/pyindi-client
- ASCOM Alpaca Python client: https://ascom-standards.org/AlpacaDeveloper/ (`alpyca`)

---

## 2. Design Considerations

### 2.1 Technology Stack Decision (ADR-001)

**Decision:** Galileo is implemented in **Python 3 with PySide6** (Qt for Python) as the UI toolkit.

**Rationale:**
- PySide6 renders through the same native Qt widget engine as a C++/Qt build, giving the same proven performance and memory footprint on ARM SBCs (Raspberry Pi 5-class hardware) that the KStars/Ekos ecosystem already relies on via StellarMate OS. UI performance is therefore not a Python-vs-C++ question — Qt's C++ core does the rendering either way.
- Direct reuse of the domain's existing Python library ecosystem: `astropy.io.fits` for FITS I/O (`META`), `numpy`/`photutils` for star detection and HFR (`IMG-040`, `FOC-010`), a native Python implementation of the INDI wire protocol (see Section 4.2 for why not `pyindi-client`), and the official ASCOM `alpyca` Alpaca client. This avoids reimplementing or wrapping these in a language without equivalent libraries.
- Python is the most common scripting language in the amateur-astronomy tooling community (ASTAP/astrometry.net wrapper scripts, PHD2 event scripts, Siril scripting), which materially lowers the barrier for third-party plugin authors (`PLUG` domain).
- Faster development velocity than C++ for the same Qt-based UI fidelity target.

**Reinforcing evidence:** [AstroFiler](https://github.com/gordtulloch/astrofiler-gui) and [VSTarget](https://github.com/gordtulloch/VSTarget) — two existing, shipping applications by the same author, being merged into Galileo per ADR-002 and ADR-003 respectively — already run Python 3 + PySide6 + AstroPy in production across Windows/Linux/macOS. AstroFiler already uses `SEP` for star-detection/quality metrics and Peewee/SQLite for persistence; VSTarget already uses `astropy`/`photutils`/`astroquery`/`astroalign` for FITS/WCS handling, aperture photometry, and image registration. This is direct evidence from two independent codebases, not just a projection, that the stack performs adequately for this domain, and it fixes several of the library choices below (Sections 2.5–2.6) rather than leaving them open.

**Accepted risks and mitigations:**

| Risk | Mitigation |
|---|---|
| Packaging/installer maturity is weaker than a native compiled build (`NFR-INSTALL`) | Use Nuitka (Python-to-C compilation) rather than a pure interpreter bundle to reduce startup overhead and produce a more native binary; wrap with platform-native installer tooling (Section 2.4). |
| CPU-bound work (star detection, curve fitting) contends with the UI thread under the GIL (`NFR-PERF-020`) | CPU-bound work is dispatched to a `ProcessPoolExecutor` (Section 2.3), not run on the Qt main thread; numpy/astropy operations release the GIL internally for the bulk of their work regardless. |
| ARM64/Raspberry Pi wheel availability for PySide6 and scientific libraries | Build pipeline includes an ARM64 Linux CI target producing tested wheels/AppImage for Pi 5-class hardware (Section 7). |

### 2.2 Architectural Style

Galileo uses a **layered, ports-and-adapters (hexagonal) architecture**:

- **Domain core** — device-abstraction interfaces ("ports"), the sequencer engine, and workflow services (autofocus, plate solving, calibration, etc.) are plain Python with no direct dependency on INDI, Alpaca, Qt, or the filesystem.
- **Adapters** — INDI adapter, Alpaca adapter, filesystem/persistence adapter, external-process adapters (solvers, guiders), notification-channel adapters, and the PySide6 UI itself, all implemented against the domain core's port interfaces.
- **Plugin boundary** — a plugin registers new adapters (device backends) or new domain-core extensions (sequencer instructions) against the same port interfaces used internally; there is no separate "plugin API" distinct from the internal module boundary (`PLUG-010`, `PLUG-020`, `NFR-EXT-010`).

This directly satisfies `ARCH-010` (per-category device abstraction implemented independently by INDI/Alpaca backends) and keeps `NFR-PORT-010` (platform-specific code isolated to adapters) structurally enforced rather than aspirational.

### 2.3 Concurrency Model

| Concern | Approach |
|---|---|
| Qt UI thread | Owns the Qt event loop exclusively; never performs blocking I/O. |
| Async I/O (Alpaca HTTP calls, external solver/guider process calls) | `asyncio` event loop bridged into the Qt event loop via `qasync`, so awaitable I/O is non-blocking without a proliferation of manual `QThread` classes. |
| INDI I/O | `galileo.adapters.indi_client` runs one reader thread per INDI server connection, which parses the XML stream into a thread-safe property cache. Adapter calls use the blocking, thread-safe client API via `asyncio.to_thread`, so they work from any event loop (including the short-lived `asyncio.run` loops the UI uses); results reach the domain core through the event bus / queued Qt signals (`Qt.QueuedConnection`). |
| CPU-bound work (star detection, HFR curve fitting, plate-solve pre/post-processing) | Dispatched to a `concurrent.futures.ProcessPoolExecutor` to avoid GIL contention with the UI thread; results returned via a future/callback marshaled back to the Qt event loop. |
| Cross-module communication | A lightweight in-process event bus (publish/subscribe over Qt signals) decouples the sequencer, device layer, and safety/notification modules, so e.g. a safety-monitor "unsafe" event reaches the sequencer without a direct dependency (`SAFE-010`, `ARCH-060`). |

This model is the mechanism behind `NFR-PERF-020` (UI responsiveness during download/solve/autofocus), `NFR-REL-010`/`NFR-REL-020` (device errors surface rather than stall), and `ARCH-060` (fault isolation between devices).

### 2.4 Packaging and Deployment Build Targets

| Platform | Build approach | Satisfies |
|---|---|---|
| Windows (x64) | Nuitka standalone build, wrapped in an MSI via WiX. Build-pipeline automation (auto-update check, desktop shortcut creation) is informed by AstroFiler's own Windows PowerShell installer script | `NFR-INSTALL-010` |
| macOS (Apple Silicon + Intel) | Nuitka/`py2app`-based `.app` bundle, code-signed and notarized, distributed as `.dmg` | `NFR-INSTALL-020` |
| Linux (x64) | AppImage (via `linuxdeploy`) as primary format, informed by AstroFiler's own Linux Bash installer script; Flatpak manifest as a secondary distribution channel | `NFR-INSTALL-030` |
| Linux (ARM64 / Raspberry Pi 5, Debian) | Same AppImage pipeline, built on a Debian ARM64 CI runner matching the author's own reference test environment (Project Scope Document, Section 6.8: a Raspberry Pi 5 running Debian at the Observatory); documented as a supported target for the network-split deployment topology (Section 7) and for local-GUI/all-in-one use | `NFR-PORT-010`, Section 7 |

### 2.5 AstroFiler Merge Strategy (ADR-002)

**Decision:** AstroFiler's core (non-GUI) modules — repository scanning, hashing/dedup, metadata-driven organization, session linking, master-calibration creation/application, quality-metric computation, smart-telescope ingestion, and cloud sync — are vendored into Galileo as the `galileo.library` module (Section 4.23). AstroFiler's own standalone entry point (`astrofiler.py`) and its independent GUI shell are retired; the equivalent functionality is exposed as a new "Library" tab within Galileo's own PySide6 UI, driven by the same `galileo.library` module.

**Persistence unification:** rather than running two ORMs/two SQLite files, Galileo adopts AstroFiler's existing **Peewee** ORM as the project-wide persistence layer (superseding the unqualified "SQLite" choice made elsewhere in earlier drafts of this document — see Section 5). AstroFiler's `astrofiler.db` schema (via `peewee-migrate`) becomes the basis for Galileo's combined catalog/session-history/repository database, with Galileo-specific tables (equipment profiles remain JSON per Section 4.4; session-history metrics per Section 4.17) added as additional Peewee models in the same migration chain.

**Star-detection library unification:** AstroFiler already uses **SEP** (Source Extractor for Python) for FWHM/HFR/eccentricity/SNR quality metrics. Galileo adopts SEP as the single star-detection library throughout — including the autofocus service (Section 4.11) and imaging-tab statistics (Section 4.5) — rather than introducing `photutils` as a second, overlapping dependency as earlier drafts of this document proposed.

**New external adapters required:** SMB/CIFS (`pysmb`, for SEESTAR/StellarMate ingestion), FTP/FTPS (standard library `ftplib`, for DWARF/iTelescope ingestion), and Google Cloud Storage (`google-cloud-storage`/`google-auth`, for cloud sync) — all carried over directly from AstroFiler's existing, proven dependency set (Section 4.23).

**Licensing (resolved):** Galileo is licensed GPL-3.0, matching AstroFiler (Project Scope Document, Section 11, C4). Every dependency in this document was chosen to be GPL-3.0-compatible; `google-cloud-storage`/`google-auth` (Apache-2.0) in particular requires GPL-3.0 rather than GPL-2.0. Any future third-party dependency added to Galileo must also be GPL-3.0-compatible, and the in-process plugin design (Section 4.20) means third-party plugins must be GPL-compatible-licensed too — this is an accepted, deliberate constraint, not an oversight.

### 2.6 VSTarget Merge Strategy (ADR-003)

**Decision:** VSTarget's planning module (AAVSO client, target list, plan editor, script export) and analysis module (download, plate-solve orchestration, photometric stacking, aperture photometry, transformation calibration, reporting, exposure calculator) are vendored into Galileo as `galileo.vstarget.planning` and `galileo.vstarget.analysis` (Sections 4.24–4.25), mirroring VSTarget's own module split and Galileo's existing `SEQ`/`SEQ-ADV` basic/advanced pattern. VSTarget's standalone entry point and GUI shell are retired; the planning view is exposed as a new UI section presented as a **peer to the Sky Atlas tab**, not nested under it, per the scope document's explicit UI-placement requirement (`VST-090` is a UI-placement, not a functional, requirement enforced at the shell level rather than the module level).

**Dependency reuse, not duplication:** VSTarget already depends on `astropy`, `numpy`, and `astroalign` — no new choice needed there. `photutils` — dropped from `galileo.autofocus`/`galileo.ui.imaging`/`galileo.library` in favor of `SEP` per ADR-002 — is **reintroduced here deliberately, not by oversight**: SEP is a source-extraction/star-detection library, while VSTarget's aperture-photometry engine (ensemble differential photometry against AAVSO comparison stars, with linear regression) is a different problem that `photutils.aperture` solves and SEP does not attempt. The two libraries serve different modules for different reasons; there is no redundant overlap to resolve.

**New dependencies:** `astroquery` (Simbad lookup, `EXT-110`), `paramiko` (SFTP, `EXT-120`), `pandas` (photometry tables), `matplotlib` (interactive transformation-outlier review, embedded via `FigureCanvasQTAgg`). All are GPL-3.0-compatible (Project Scope Document, Section 11, C5). `matplotlib` is a second charting library alongside Qt Charts (used by `galileo.history`); this is an accepted inconsistency (Project Scope Document, Section 12 risk table), not a unification target for v1, because VSTarget's interactive outlier-rejection UX is proven in matplotlib and re-implementing it in Qt Charts would be pure risk with no requirement-level benefit.

**Plate solving reuse:** `galileo.vstarget.analysis` calls into the existing `galileo.platesolve` module (`PLT-010`) rather than embedding its own ASTAP integration, even though VSTarget's original codebase has one — this collapses two independent ASTAP adapters into one.

### 2.7 AstroLlama Selective Tool Harvest (ADR-004)

**Decision:** Unlike AstroFiler/VSTarget/Obsy (all directly ported/merged — ADR-002/003/005), [AstroLlama](https://github.com/gordtulloch/AstroLlama)'s [MCP (Model Context Protocol) server tools](https://github.com/gordtulloch/AstroLlama/tree/main/mcp_server/tools) are GPL-3.0 (no license tension) but architecturally a grab-bag of independent, mostly self-contained tool functions built for an AI-agent/MCP context — only the astronomy-device-specific ones are harvested, each adapted directly into the existing module it corresponds to (Project Scope Document Section 6.5 has the full file-to-module mapping). AstroLlama's generic AI-assistant tools (news/wiki/YouTube/web search, arXiv, Wolfram Alpha, chat orchestration) are not relevant to Galileo and are excluded outright.

**Notably validating, not just informing:** `telescope_interface_tool.py` + `telescope_registry_tool.py` already implement, in working form, the exact pattern Galileo's own `ARCH`/`PROF` design calls for — one control interface routed to an INDI or Alpaca backend based on an active profile in a registry, with per-platform device-type filtering differences already handled. This is treated as validating evidence for the `ARCH`/`PROF` design (Sections 4.1, 4.4), not merely a reference.

**Direct implementation reuse:**
- `astap_plate_solve_tool.py` → `galileo.platesolve`'s ASTAP `SolverAdapter` (Section 4.12): binary-path resolution, RA/Dec regex parsing, a solved/not-solved heuristic, and — worth calling out specifically — path-traversal-safe filename validation, a concrete security detail carried over rather than reinvented.
- `alpaca_telescope_imaging_tool.py` → `galileo.adapters.alpaca` (Section 4.3) and the `PLT-040` solve-and-center workflow: proven slew/capture/plate-solve-verify/park orchestration and FITS-metadata-on-write pattern.
- `alpaca_device_discovery_tool.py` / `indi_device_discovery_tool.py` → `ARCH-050` discovery implementation reference (Section 4.1).
- `variable_comparison_stars_tool.py` / `generate_aavso_map_tool.py` → `galileo.vstarget.analysis` (Section 4.25): AAVSO comparison-star retrieval (reinforcing `VST-AN-040`) and finder-chart rendering (new: `VST-AN-090`).
- `get_latlong_tool.py` / `get_weather_tool.py` → `galileo.planning.sky_atlas` (Section 4.8, `SKY-090`) and `galileo.safety` (Section 4.16, `SAFE-050`) respectively, both via the Open-Meteo API. The weather forecast is explicitly a planning aid, never an input to `SAFE-010`'s automated-abort logic — that remains the sole responsibility of a connected safety-monitor device, preserving the `ARCH`/`NFR-REL` boundary between advisory internet data and safety-critical device state.
- `generate_constellation_map_tool.py` / `generate_map_tool.py` → `galileo.planning.framing` (Section 4.9, `FRAME-060`) rendering reference.

**New dependency:** an Open-Meteo API client (lightweight `requests`-based, no separate SDK needed — matching AstroLlama's own `data_sources.open_meteo` approach) for `SKY-090`/`SAFE-050`/`EXT-130`. No API key required; GPL-3.0-compatible by construction since Galileo only calls the API at runtime rather than redistributing Open-Meteo data (Project Scope Document, Section 11, C7).

### 2.7a Obsy Port Strategy (ADR-005)

**Decision:** [Obsy](https://github.com/gordtulloch/obsy) was originally CC BY-NC-ND 4.0, which forced treating it as architectural reference only — reimplemented clean-room, never ported (this section previously reflected that treatment). **Obsy has since been relicensed to GPL-3.0** (Project Scope Document, Section 11, C6), removing that constraint. Its contribution to `galileo.planning.sky_atlas` (Section 4.8) and `galileo.planning.framing` (Section 4.9) — `astroplan`-based rise/transit/set computation and DSS-cutout thumbnail-fetch logic (`SKY-080`) — is now treated the same as AstroFiler/VSTarget: **ported directly**, not rewritten from scratch. This is a promotion from the "selective harvest" pattern (Section 2.7) to the same "direct port" pattern as ADR-002/003, reflecting the license change.

**What doesn't change:** this is a license change, not an architecture one. Obsy is still a Django web application with no structural counterpart in Galileo's PySide6 modules — there's no Django-shaped hole in Galileo's design for the rest of Obsy to drop into. Direct porting is therefore still practically scoped to the function/algorithm level (the rise/transit/set computation, the thumbnail-fetch helper) rather than wholesale module reuse. Obsy's Django scheduling functionality is still not reused at all (Project Scope Document, Section 5) — that exclusion was always about scope/maturity ("only cursory"), not license, and the relicense doesn't change it.

**Diligence note carried forward:** if Obsy ever had contributors other than the author, that should be confirmed before reuse, independent of the license change (Project Scope Document, Section 11, C6).

---

## 3. Architectural Overview

```
┌───────────────────────────────────────────────────────────────────┐
│  UI Layer (PySide6)                                                │
│  Pier selector/dashboard · Equipment panel · Imaging tab ·      │
│  Sequencer (basic/advanced) · Scheduler ·                          │
│  Sky Atlas/Framing/Sky Map (three peer panels) ·                   │
│  Variable Star Target (peer to Sky Atlas) ·                        │
│  Library · Options · Plugin Manager · Log Viewer                  │
└───────────────────────────────┬─────────────────────────────────--┘
                                 │ Qt signals/slots, view-models
┌───────────────────────────────▼─────────────────────────────────--┐
│  Domain Core (pure Python, no I/O)                                 │
│  Device-abstraction ports · Sequencer engine · Autofocus service · │
│  Plate-solve service · Calibration service · Meridian-flip service │
│  · Safety policy · Session-history aggregator · Event bus          │
└───┬──────────┬──────────┬──────────┬──────────┬──────────┬───────-┘
    │          │          │          │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼────┐ ┌───▼───┐ ┌───▼────┐ ┌───▼────┐ ┌───▼─────┐
│ INDI  │ │ Alpaca│ │Solver/ │ │Notif. │ │Persist.│ │Library │ │ Plugin  │
│adapter│ │adapter│ │Guider  │ │adapters│ │adapter │ │adapter │ │ loader  │
│(pyindi│ │(alpyca│ │process │ │(webhook│ │(Peewee/│ │(SMB/   │ │(entry   │
│-client│ │/HTTP) │ │adapters│ │/email) │ │SQLite/ │ │FTP/FTPS│ │ points) │
│)      │ │       │ │        │ │        │ │FITS)   │ │/GCS)   │ │         │
└───────┘ └───────┘ └────────┘ └────────┘ └────────┘ └────────┘ └─────────┘
```

The `galileo.library` module (Section 4.23, merged from AstroFiler) sits alongside the other domain-core services; it owns the repository/catalog data and the SMB/FTP/FTPS/GCS adapters, and shares the Peewee/SQLite persistence adapter with session history rather than maintaining a separate database. `galileo.vstarget.planning`/`galileo.vstarget.analysis` (Sections 4.24–4.25, merged from VSTarget) likewise sit alongside the other domain-core services, sharing the same persistence adapter and reusing `galileo.platesolve` and `galileo.planning.sky_atlas` rather than duplicating solver or visibility logic.

The domain core depends only on the abstract port interfaces; every box in the bottom row is an adapter implementing one or more ports and is individually replaceable — including by a plugin (Section 2.2). `galileo.observatory` (Section 4.4a) sits above `galileo.equipment.profiles`, grouping Piers rather than adding a new adapter row — a single running Galileo instance holds one `DevicePool` per Pier (Section 4.1, `ARCH-080`) and one sequencer/scheduler pair per Pier, with `galileo.observatory` only adding the cross-Pier grouping/scoping layer on top (Section 4.4a).

---

## 4. Module / Component Design

Each module lists its responsibility, key design elements, external libraries, and the SRS requirement IDs it satisfies (the seed for the RTM's Component column).

### 4.1 `galileo.core.devices` — Device Abstraction Layer

- **Responsibility:** Defines the abstract port interface per device category (camera, mount, filter wheel, focuser, rotator, guider, switch, flat panel, weather, dome, safety monitor); capability negotiation; connection-state and fault-isolation management.
- **Key design:** One `abc.ABC` interface per device category (e.g. `CameraPort`, `MountPort`) declaring only behavior, not transport. A `DeviceCapabilities` value object is populated per-instance from the adapter's introspection of the underlying INDI property set / Alpaca `Can*` flags, and the UI layer queries it to decide what controls to render. This design is validated, not just informed, by AstroLlama's `telescope_interface_tool.py`/`telescope_registry_tool.py` (ADR-004, Section 2.7), which already implement the same one-interface-routed-by-active-profile pattern in working form. `MountPort` supports a non-sidereal tracking-rate parameter (`EQP-MNT-040`) alongside standard sidereal slew/track. `EQP-060`'s raw property inspector reads directly from each adapter's underlying INDI-property/Alpaca-parameter representation, bypassing the port abstraction deliberately, since its purpose is to expose what the abstraction normally hides. Device instances are held in a `DevicePool` keyed by Pier ID (`ARCH-080`) rather than a single global registry — a design decision made specifically so `galileo.observatory` (Section 4.4a) could add multi-Pier support later without this layer needing to change, since retrofitting a device layer that assumed one global device set would have been far more disruptive than designing for multiple pools from the start. `FocuserController` clamps every absolute/relative move to the connected backend's reported `0..MaxStep` range before issuing it (`EQP-FOC-030`) — a transport-agnostic guard, since an ASCOM/Alpaca `IFocuserV3` driver is documented to hard-stop at those limits itself but INDI focuser drivers give no equivalent guarantee, and a silently-clamped hardware move would otherwise leave this controller's cached position out of sync with the device.
- **Libraries:** none beyond the standard library at this layer (transport lives in the adapters).
- **Driver identification (`EQP-070`):** `DeviceBackend.get_driver_info()` returns `name`, `description`, `driver_info` and `driver_version` for any device, and is specified to work *before* connecting — the INDI adapter reads the device's `DRIVER_INFO` property from the (shared, reference-counted) server connection without sending `CONNECT`, and the Alpaca adapter reads the ASCOM `DriverInfo`/`DriverVersion`/`Name`/`Description` common properties, which drivers must serve while disconnected. The equipment pages therefore show a "Driver info" / "Driver version" row as soon as a device is picked from a scan (Camera, Focuser and Rotator per panel; the five scan-only categories at page level — the Guider is not one of them, since it connects to PHD2 by host and port and has no driver to report), and refresh it from the live adapter after connect. The Mount and Filter Wheel pages continue to fill the same fields from their `get_status()` polling. A saved device is deliberately not looked up when a Pier is loaded, so switching Piers never waits on an unreachable server; the row fills on the next device pick or connect.
- **Satisfies:** `ARCH-010`–`ARCH-080`, `EQP-010`–`EQP-070`, `EQP-MNT-040`, `EQP-FOC-030`.

### 4.2 `galileo.adapters.indi` — INDI Adapter

- **Responsibility:** Implements every device port against an INDI server connection.
- **Key design:** Implemented on `galileo.adapters.indi_client`, a native Python client for the INDI XML wire protocol (v1.7) over TCP, rather than on `pyindi-client`. `pyindi-client` is a SWIG wrapper around the `libindi` C++ library, which has no Windows port, so it cannot be built on Windows — a stated target platform (`NFR-PORT`) — whereas a pure-Python client behaves identically on Windows, macOS, Linux and Raspberry Pi. One shared connection per `host:port` (reference-counted) keeps a live property cache updated by a reader thread; each adapter targets one named INDI device and maps Galileo's port methods onto that device's standard properties (`CCD_EXPOSURE`, `EQUATORIAL_EOD_COORD`, `FILTER_SLOT`, `ABS_FOCUS_POSITION`, ...). Devices are classified per category from each driver's `DRIVER_INTERFACE` bit mask; `DeviceCapabilities` are derived from the properties a driver actually defines. Exposures are delivered as FITS BLOBs (zlib-compressed `.z` handled), which the adapter routes to this client only (`UPLOAD_CLIENT`). A device another client (e.g. Ekos) had already connected is left connected on `disconnect()`. `SAFETY_MONITOR` has no INDI interface, so no devices are discoverable for it.
- **Libraries:** none beyond the standard library (`socket`, `xml.etree`, `zlib`) plus `astropy.io.fits` for decoding frames. An alternative binding (`pyindi-client`) can be built on Linux/macOS where `libindi` is available, but is not required.
- **Satisfies:** `ARCH-010`, `ARCH-020`, `ARCH-030`, `ARCH-050`, `EXT-020`, `EXT-030`, and the INDI-transport implementation of every device-specific `EQP-*` requirement: `EQP-CAM-010`–`EQP-CAM-040`, `EQP-MNT-010`–`EQP-MNT-030`, `EQP-FW-010`–`EQP-FW-020`, `EQP-FOC-010`–`EQP-FOC-020`, `EQP-ROT-010`, `EQP-GDR-010`, `EQP-SW-010`, `EQP-FP-010`, `EQP-WX-010`, `EQP-DOME-010`, `EQP-SAFE-010`.

### 4.3 `galileo.adapters.alpaca` — Alpaca Adapter

- **Responsibility:** Implements every device port against an Alpaca (REST/JSON) device.
- **Key design:** Wraps `alpyca`; UDP discovery per the Alpaca spec for device enumeration; HTTP calls issued through the `asyncio`/`qasync` bridge (Section 2.3) to stay non-blocking. Every `_get`/`_put` call parses the device's Alpaca JSON envelope and raises `DevicePropertyError` on a nonzero `ErrorNumber`, so a real driver rejecting a command (e.g. a focuser move outside its range) surfaces instead of being discarded. `AlpacaFocuserAdapter` reads `MaxStep`, `MaxIncrement`, and `Absolute` from the live device on `connect()` rather than assuming simulator-style constants — needed for real `IFocuserV3` hardware such as a Seestar's Alpaca bridge, which may be relative-only and has a device-specific travel range that feeds `FocuserController`'s clamp (`EQP-FOC-030`, Section 4.1).
- **Libraries:** `alpyca` (ASCOM's official Python Alpaca client).
- **Satisfies:** same requirement set as 4.2, via the Alpaca transport instead of INDI — including the Alpaca-transport implementation of the same device-specific `EQP-*` requirements enumerated in 4.2 (`ARCH-010`, `ARCH-020`, `ARCH-030`, `ARCH-050`, `EXT-020`, `EXT-030`).

### 4.4 `galileo.equipment.profiles` — Equipment Profiles (Piers)

- **Responsibility:** Persist and load named equipment configurations. Each profile is a **Pier**: one mount plus one or more **optical trains** — an ordered chain of device-port references from telescope/lens through reducer/flattener, filter wheel, rotator, and off-axis guider to the final camera — rather than a flat per-device settings list. This refines the data model described in earlier drafts of this document, adopted from the KStars/EKOS "Optical Trains" precedent (Project Scope Document, Section 6.6), because it is what makes automatic focal-length/plate-scale derivation (`PROF-090`) and clean multi-rig support (`PROF-080`, `SEQ-090`) possible without ad-hoc special-casing.
- **Key design:** An `OpticalTrain` is an ordered list of `(DevicePort, role)` references; effective focal length and plate scale are computed by walking the train's optical elements rather than being separately configured, and are consumed directly by `galileo.planning.framing` (`FRAME-010`) and `galileo.platesolve`. A `Pier` wraps one `MountPort` plus its `OpticalTrain`s and owns the `DevicePool` slot (Section 4.1) it's keyed under. Profiles serialize to human-readable, schema-validated JSON files under a per-platform config directory; import/export is a file-copy of the same schema. The active-profile/active-train-selection model follows AstroLlama's `telescope_registry_tool.py` precedent (ADR-004, Section 2.7).
- **Optical tube definitions (`PROF-100`):** the telescope/lens end of a train is defined on the Equipment section's Optics page, one panel per tube on the selected Pier: name, focal length (mm), aperture (mm), optical system (Newtonian / Schmidt-Cassegrain / Mak-Cassegrain / Refractor / Other), and image alignment as two independent flags, reversed (mirrored left-right) and inverted (flipped top-bottom), since a tube can be either, both, or neither. Optics is a UI/persistence concept only — it has no device port and does not appear in `DeviceCategory` (`ARCH-010`). Tubes persist as `OpticalTubeRecord` rows (`optical_tubes` table, Pier foreign key, ordered by position) in the project-wide Peewee database (ADR-002), alongside the per-Pier `DeviceConfigRecord` rows they reference. A tube's associated devices are stored as `"<category>:<slot>"` keys into those device-config rows rather than as foreign keys, because the device pages delete and recreate their rows on Save; an association whose device no longer exists degrades to a visible "not configured" entry instead of losing the tube. Columns added to an existing table after release are applied at `init_db` time (`_add_missing_columns`), since Peewee's `create_tables(safe=True)` never alters an existing table. Deriving plate scale from a tube (`PROF-090`) is not yet wired to these records.
- **Active optics selection (`PROF-110`):** the main window's top bar carries an Optics selector beside the Pier selector, populated from the selected Pier's `OpticalTubeRecord`s (each entry: name, or "Optical Tube N" if unnamed, plus focal length and focal ratio when known). It is shown only on the primary sections listed in `_OPTICS_SECTIONS` (Framing and Imaging) and follows the same show/hide-by-section pattern as the multi-camera selector; it is refreshed on Pier change, section change, and after the Optics page saves. The choice is held as the tube's position in the Pier's ordered list (tube rows are rewritten wholesale on save, so row ids are not stable) and exposed to screens via `AppWindow.active_optical_tube()`. Framing and Imaging do not yet consume it.
- **Libraries:** `pydantic` (schema validation/serialization).
- **Satisfies:** `PROF-010`–`PROF-110`.

### 4.4a `galileo.observatory` — Multi-Mount Observatory Management (exceeds EKOS, Section 6.6)

- **Responsibility:** Groups multiple Piers (Section 4.4) into a named Observatory; scopes shared resources (dome, safety monitor) at the Observatory or Pier level; provides the multi-Pier status dashboard. This is the one module in Galileo's design with no EKOS precedent to draw on — EKOS's own Scheduler explicitly isn't built for multiple parallel mounts, and its real-world workaround is running separate application instances. Galileo deliberately goes further.
- **Key design:** An `Observatory` is a named collection of `Pier` references plus a `ResourceScope` map (`{dome: observatory|pier, safety: observatory|pier}`, `OBS-030`/`OBS-050`) — deliberately with no `guide` key, since `galileo.guiding` (Section 4.14) has no Observatory-scoped mode at all (`GUIDE-060`). When a safety source is Observatory-scoped, `galileo.safety` (Section 4.16) publishes its unsafe-state event tagged with the Observatory ID rather than a single Pier ID, and every subscriber (each member Pier's `galileo.sequencer.basic`/`galileo.scheduler`) reacts to events tagged with its own Observatory (`OBS-040`) — this reuses the existing event-bus fault-isolation pattern (`ARCH-060`) rather than adding a new cross-Pier call path. Because `galileo.core.devices` already keys device pools per-Pier (`ARCH-080`), this module only has to add the grouping/scoping layer on top — it does not touch the device layer itself. Each Pier's sequencer/scheduler instance runs independently and concurrently (`OBS-020`); this module does not introduce a second execution engine, it just lets more than one `SequenceRunner`/scheduler job queue exist at once, one per Pier.
- **Libraries:** `pydantic` (Observatory/ResourceScope schema, alongside `galileo.equipment.profiles`).
- **Satisfies:** `OBS-010`–`OBS-080`.

### 4.5 `galileo.ui.imaging` — Imaging Tab

- **Responsibility:** Live frame display, histogram, auto-stretch preview, per-frame statistics, star overlay, manual capture, panel layout, and the entry point for the flat-wizard workflow (`CAL-060`) — the UI is hosted here rather than in its own primary-navigation section; the capture logic remains in `galileo.calibration` (Section 4.10).
- **Key design:** Frame data is decoded off the UI thread (in the process pool for the auto-stretch/statistics computation) and handed to a Qt `QGraphicsView`-based renderer for pan/zoom; layout persistence uses Qt's `QDockWidget` state save/restore.
- **Libraries:** `numpy` (pixel math), `astropy` (FITS decode), `SEP` (star detection for the HFR/star-count statistics, unified with the autofocus service per ADR-002), Qt Graphics View framework.
- **Satisfies:** `IMG-010`–`IMG-100`, `CAL-060`.

### 4.6 `galileo.sequencer.basic` — Sequencer (Basic)

- **Responsibility:** Linear target-list execution: exposure parameters, dynamic file naming, pause/resume/stop, progress reporting.
- **Key design:** A single `SequenceRunner` state machine consumes an ordered list of `SequenceStep` objects; runs on the domain core, issuing device-port calls and awaiting results via the event bus; persists progress so a crash mid-sequence does not lose completed-frame records (`NFR-REL-040`). Publishes a "frame written" event, tagged with the current step's `SessionContainer` ID, after each capture — `galileo.library` (Section 4.23, `LIB-150`/`LIB-160`) is the subscriber, not a direct call, keeping this module unaware of the repository/cataloging layer entirely. Multi-rig parallel capture (`SEQ-090`) runs one `SequenceRunner` instance per optical train (Section 4.4) in a lead/follower arrangement — the lead train's `SequenceRunner` owns the shared `MountPort` (slew/dither/align/meridian-flip), publishing those events on the event bus for follower trains' `SequenceRunner`s to synchronize against, matching EKOS's own multi-train model (Project Scope Document, Section 6.6). This is a P3 capability and not required for v1's single-train path.
- **Satisfies:** `SEQ-010`–`SEQ-090`, `NFR-REL-040`.

### 4.7 `galileo.sequencer.advanced` — Sequencer (Advanced)

- **Responsibility:** Nested instruction/condition/trigger execution model, instruction-group templates, live-editing of not-yet-run steps.
- **Key design:** Instructions, conditions, and triggers are all implementations of a common `SequencerNode` interface (`execute()`, `validate()`, `describe()`); the built-in catalog from `SEQ-ADV-020`–`SEQ-ADV-040` ships as first-party `SequencerNode` implementations registered through the same entry-point mechanism a plugin uses (`PLUG-020`), so there is architecturally no distinction between "built-in" and "plugin" instructions.
- **Satisfies:** `SEQ-ADV-010`–`SEQ-ADV-100`.

### 4.8 `galileo.planning.sky_atlas` — Sky Atlas

- **Responsibility:** Deep-sky object catalog, search/filter, altitude charting, horizon profiles, observing locations.
- **Key design:** Catalog (≥10,000 objects) is bundled and loaded into a local SQLite database at install time, so search/filter/chart operate fully offline (`NFR-OFFLINE-010`); altitude/rise-transit-set computation is ported directly from Obsy's `targets` app (`astroplan` against a configured observer location/timezone — GPL-3.0, ported not reimplemented, per Section 2.7) rather than written from scratch. A target's DSS-cutout thumbnail (`SKY-080`) is fetched and cached on add-to-target-list using the same ported logic: `SkyAtlas._fetch_thumbnail()` requests a 15×15 arcmin FITS cutout from STScI's DSS search service, min/max-normalizes and resizes it to a 150×150 JPEG (via Pillow), off the UI thread via `asyncio.to_thread` — ported directly from Obsy's `Target.save()` (`targets/models.py`, ADR-005) — and degrades to no thumbnail (rather than raising) on any failure. Observing-location geocoding (`SKY-090`) is adapted from AstroLlama's `get_latlong_tool.py` (ADR-004, Section 2.7), via Open-Meteo. The Sky Atlas page's object-name search (`SKY-100`) is Simbad-first, not catalog-first: `SkyAtlas.search_online()` — ported from Obsy's `target_query` view (ADR-005), adapted to the per-instance `Simbad()` call pattern already used by `galileo.vstarget.planning.simbad_client.SimbadClient` rather than Obsy's global-singleton mutation — looks up the name via Simbad (wildcard mode only when the query itself contains a `*`/`?`, since unconditional wildcard mode — as Obsy used — finds nothing for a plain name against the currently-installed Simbad backend) and only falls back to the offline catalog's `search()` (`SKY-010`) when Simbad raises, times out, or returns no rows; `search()` itself stays local-only and unchanged so `SKY-070`/`NFR-OFFLINE-010`'s no-internet guarantee is unaffected. Magnitude is deliberately a separate, best-effort per-object Simbad query (capped to small result sets) rather than part of the primary name/type/coordinate match, because requesting it there silently excludes any object with no cataloged V magnitude — most nebulae and clusters. Selecting a search result on the Sky Atlas page shows this same magnitude/type/coordinate data plus the constellation (`constellation_for()`, via `astropy.coordinates.get_constellation` — ported from Obsy's identical `target_query` use) and the downloaded DSS thumbnail, matching what Obsy's target search populated for a Simbad hit.
- **Libraries:** `astropy.coordinates`, `astroplan` (rise/transit/set), SQLite (bundled catalog), `astroquery.simbad` (online object-name search, `SKY-100`), Pillow (DSS-cutout-to-JPEG thumbnail conversion, `SKY-080`), an Open-Meteo API client (geocoding).
- **Satisfies:** `SKY-010`–`SKY-100`, `NFR-OFFLINE-010`, `EXT-130`.

### 4.9 `galileo.planning.framing` — Framing Assistant

- **Responsibility:** FOV overlay, sky-survey/offline star-field background, rotation preview, mosaic panel grid, constellation/grid overlay, send-to-sequencer.
- **Key design:** FOV rectangle computed from the active `CameraPort`/`MountPort` capability data (sensor size, focal length) already held by the device abstraction layer, so it stays in sync with whatever equipment is actually connected. Constellation/grid rendering (`FRAME-060`) is informed by AstroLlama's `generate_constellation_map_tool.py`/`generate_map_tool.py` (ADR-004, Section 2.7).
- **Satisfies:** `FRAME-010`–`FRAME-060`.

### 4.9a `galileo.ui.skymap` — Interactive Star Map / Planetarium (KStars/EKOS-informed)

- **Responsibility:** Live, rendered, pannable/zoomable sky view distinct from `galileo.planning.sky_atlas`'s catalog/list UI and `galileo.planning.framing`'s FOV-preview UI (Project Scope Document, Section 6.6). Click-to-identify, double-click-to-track, constellation/grid overlay, comet/asteroid/satellite rendering, live FOV/pointing overlay, slew-to-clicked-location.
- **Key design:** Rendered via a `QGraphicsView`-based canvas (consistent with `galileo.ui.imaging`, Section 4.5) rather than a second GUI toolkit; star/DSO rendering reads from the same bundled catalog database as `galileo.planning.sky_atlas` (Section 4.8) rather than a separate one. FOV/pointing overlay (`SKYMAP-050`) shares geometry computation with `FRAME-010`, and slew-to-clicked-location (`SKYMAP-060`) issues the same `MountPort.slew_to_coordinates()` call the equipment panel uses — no separate command path.
- **Libraries:** `astropy.coordinates` (coordinate transforms, shared with `galileo.planning.sky_atlas`), Qt Graphics View framework.
- **Current implementation (Planning section, "Star Atlas"):** the first slice is a `QPainter`-drawn widget (`galileo.ui.star_atlas.StarAtlasView`) over plain-numpy sky maths (`galileo.planning.star_atlas`: precession, sidereal time, alt/az, stereographic `Viewport`), not yet the `QGraphicsView` canvas described above — projecting a few thousand points per frame with numpy and painting them directly was simpler than managing a scene-graph item per star. Stars come from the Yale Bright Star Catalogue (VizieR `V/50`, cached in the user cache directory, with a small built-in named-star fallback offline); deep-sky objects come from the Sky Atlas catalog; Sun/Moon/planets from astropy's built-in ephemeris. Constellation boundaries come from the Delporte catalogue (VizieR `VI/49`, B1875 vertices densified along constant RA/Dec, then precessed to J2000). Implements `SKYMAP-010` and `SKYMAP-020`, and the boundary half of `SKYMAP-030` (figures/art are not built); `SKYMAP-040`–`SKYMAP-060` are not yet built.
- **Satisfies:** `SKYMAP-010`–`SKYMAP-060`.

### 4.9b `galileo.scheduler` — Observatory Scheduler (KStars/EKOS-informed)

- **Responsibility:** Multi-night/multi-target job queue: per-job altitude/moon/twilight/horizon constraints, startup/completion conditions, weather-gated execution, priority-based preemption, multi-night progress tracking. Distinct from and layered above `galileo.sequencer.basic`/`galileo.sequencer.advanced` — a job doesn't duplicate sequence-execution logic, it *triggers* an existing `SequenceRunner` when its constraints are satisfied.
- **Key design:** A `SchedulerJob` references a target, a sequence definition, and a Pier/optical train; constraint evaluation reuses `galileo.planning.sky_atlas`'s visibility service (`SKY-030`) rather than a separate ephemeris path. Weather-gating subscribes to the same unsafe-state event bus `galileo.safety` publishes to (`SAFE-010`) — the scheduler is a consumer of that event, not a second safety authority. The replanning algorithm (`SCHED-070`) is a continuously-reevaluated priority queue (EKOS's own "Greedy Scheduling" approach is the direct precedent — Project Scope Document, Section 6.6); this is explicitly P2, so v1 can ship with static (non-preempting) priority ordering and add continuous replanning after. One `galileo.scheduler` job queue exists per Pier; `galileo.observatory` (Section 4.4a) is what lets several of these run side by side and coordinates the shared-resource constraints (e.g. a shared dome) between them (`OBS-070`) — this module itself stays single-Pier and unaware of Observatory grouping, consistent with the layering elsewhere in this design.
- **Libraries:** none beyond the standard library and Peewee (job/progress persistence, same database as `galileo.library`/`galileo.history` per ADR-002).
- **Satisfies:** `SCHED-010`–`SCHED-100`.

### 4.10 `galileo.calibration` — Flat Wizard / Calibration

- **Responsibility:** Automated flat/dark/bias *capture* routines during a live session, flat-panel integration, target-ADU convergence. Master-frame *creation* and *application* to light frames is a repository-time operation and lives in `galileo.library` (Section 4.23), not here — this module only produces the raw calibration exposures.
- **Key design:** An iterative exposure-time (or brightness) search loop against the `CameraPort`/`FlatPanelPort`, with a bounded iteration count and explicit failure reporting rather than an unbounded retry loop. Captured calibration frames are handed off to `galileo.library` for session linking and master-frame creation.
- **Satisfies:** `CAL-010`–`CAL-050`, `NFR-USE-020`. (`CAL-060`, the Imaging-tab placement of the flat wizard's UI, is satisfied by `galileo.ui.imaging`, Section 4.5; this module stays UI-free.)

### 4.11 `galileo.autofocus` — Autofocus Service

- **Responsibility:** HFR sampling across focuser positions, curve fitting, best-focus move + confirmation, per-filter offsets, manual/triggered invocation, aberration inspection.
- **Key design:** Star detection/HFR computation for each sample runs in the process pool (Section 2.3); curve fitting (`scipy.optimize`) selects among configured fit models; a run's sample points and fit are recorded for `HIST` review. The Aberration Inspector (`FOC-080`, KStars/EKOS-informed — Project Scope Document, Section 6.6) reuses the same HFR-computation pipeline, applied per-region (3- or 4-point) across a single frame rather than across focuser positions, to surface sensor-tilt/collimation indicators.
- **Libraries:** `numpy`, `SEP` (star detection — unified with `galileo.ui.imaging` and `galileo.library` per ADR-002, superseding the `photutils` choice in earlier drafts of this document; `photutils` returns in `galileo.vstarget.analysis` for aperture photometry, a distinct problem — see ADR-003), `scipy` (curve fitting).
- **Satisfies:** `FOC-010`–`FOC-080`.

### 4.12 `galileo.platesolve` — Plate Solving

- **Responsibility:** Invoke configured external/local solvers, solve-and-sync, solve-and-center iteration, failure reporting.
- **Key design:** Each solver backend (ASTAP, local astrometry.net, etc.) implements a common `SolverAdapter` interface (subprocess invocation + result parsing) behind the async I/O bridge, so adding a solver is an adapter, not a core change. The ASTAP `SolverAdapter` is adapted directly from AstroLlama's `astap_plate_solve_tool.py` (ADR-004, Section 2.7), including its path-traversal-safe filename validation.
- **Satisfies:** `PLT-010`–`PLT-060`, `EXT-040`.

### 4.13 `galileo.meridianflip` — Meridian Flip

- **Responsibility:** Flip-time computation, automatic pause/flip/resume, post-flip re-center and guiding restart.
- **Key design:** A domain-core service subscribed to the mount's tracked position via the event bus; on limit approach it emits a sequencer-pausable event consumed by `galileo.sequencer.advanced`'s meridian-flip trigger (`SEQ-ADV-040`).
- **Satisfies:** `MFLIP-010`–`MFLIP-040`.

### 4.14 `galileo.guiding` — Guiding Integration

- **Responsibility:** External guider connection, start/stop, dither + settle wait, guide-error reporting, disconnect handling.
- **Key design:** A `GuiderAdapter` interface with a first-party PHD2-protocol implementation (JSON-RPC-over-TCP event stream) run through the async I/O bridge. Exactly one `GuiderAdapter` instance is owned per Pier (`GUIDE-060`), each connecting to its own PHD2 process/instance (typically a distinct host:port pair) — unlike `galileo.dome`/`galileo.safety`, this module has no Observatory-scoped mode at all: `galileo.observatory` (Section 4.4a) never fans a guiding command or event out across Piers, since one guiding application cannot reasonably guide more than one mount.
- **Guider screen (`GUIDE-070`–`GUIDE-090`):** `galileo.adapters.phd2.Phd2Adapter` is the PHD2 implementation of that interface — a socket plus one reader thread (the same shape as `galileo.adapters.indi_client`), so it works from the Qt thread, from the sequencer's asyncio loop and from tests alike. It matches PHD2's request replies to callers by JSON-RPC id (`request()` returns a future; `call()` blocks) and passes every unsolicited event (`GuideStep`, `StarLost`, `SettleDone`, …) to one callback. `GuidingService` feeds those events into a `GuideModel`, a lock-protected mirror of PHD2's state — app state, guide-step history, running RMS (Welford, since guiding started, in arcsec once PHD2's pixel scale is known), calibration points, the last guide-star image and an event log — and issues the screen's commands as non-blocking futures, logging any PHD2 rejects. `galileo.ui.guider.GuiderPage` never sees a PHD2 thread: a 250 ms timer takes a `GuideModel.snapshot()` and redraws only when the model's version changed, and polls the things PHD2 does not push (equipment-connected, the star cut-out) once a second while the page is visible. One `GuidingService` is kept per Pier record. PHD2 does not stream the full guide frame to network clients, so the page shows the guide-star cut-out (`get_star_image`) rather than the whole frame; PHD2 also has no per-axis RA enable or gain setting over the event server, so the page offers a Dec guide mode instead of the reference screen's RA/Dec direction check-boxes.
- **Satisfies:** `GUIDE-010`–`GUIDE-090`, `EXT-050`.

### 4.15 `galileo.dome` — Dome Control

- **Responsibility:** Azimuth slaving to mount position, shutter/park sync with sequence and meridian-flip events, slaving disable for third-party-controlled domes.
- **Key design:** A dome instance is owned either by a single Pier or, when `OBS-050` scopes it at the Observatory level, by `galileo.observatory` (Section 4.4a) — this module itself is agnostic to which, it just receives park/shutter commands and reports state to whichever module (Pier or Observatory) owns it, the same fault-isolated event-bus pattern used throughout.
- **Satisfies:** `DOME-010`–`DOME-030`.

### 4.16 `galileo.safety` — Safety & Weather Monitoring

- **Responsibility:** Poll safety-monitor/weather devices, apply configurable abort/warning policy, gate sequence resumption.
- **Key design:** Publishes unsafe-state events on the event bus, tagged with either a Pier ID or an Observatory ID depending on `OBS-030`'s scoping; the sequencer and dome modules subscribe independently rather than the safety module calling into them directly, keeping the fault-isolation property from `ARCH-060`. `galileo.observatory` (Section 4.4a) is what fans an Observatory-scoped event out to every member Pier (`OBS-040`) — this module doesn't need to know how many Piers are listening. The internet weather-forecast planning aid (`SAFE-050`, adapted from AstroLlama's `get_weather_tool.py` via Open-Meteo — ADR-004, Section 2.7) is deliberately kept out of the unsafe-state event path: it is display-only and cannot publish an abort event, preserving the connected safety-monitor device as sole authority over `SAFE-010`. The Watchdog (`SAFE-060`, KStars/EKOS-informed — Project Scope Document, Section 6.6) is **not reimplemented from scratch**: where an INDI server is in use, Galileo sends periodic heartbeats to INDI's own existing `indi_watchdog` driver, which independently parks the mount and closes the dome on timeout — this runs outside Galileo's own process, so it still protects against Galileo itself crashing or hanging. For Alpaca-only setups (no INDI server), a lightweight local watchdog thread provides the equivalent behavior directly against the Alpaca `MountPort`/`DomePort`.
- **Device-tier vs. internet-advisory trust tiers:** a general principle applied consistently across this module — **any connected Safety Monitor device**, Tier 1 (hardware, e.g. `SAFE-070`'s rain sensor via `indi-hydreon`) or Tier 2 (software-computed, e.g. an ML-based all-sky-camera cloud classifier, `SAFE-080`), is trusted as an input to automated abort decisions (`SAFE-010`), because both reach this module through the identical `SafetyMonitorPort`/`ARCH-010` path — this module has no code path that distinguishes them, by design, which is what `SAFE-070`/`SAFE-080` actually require. A Tier 2 device runs as its own standalone INDI/Alpaca driver process, never as an in-process Galileo plugin — this is a direct consequence of `EXT-020` (all device I/O via INDI or Alpaca) applying without exception, even to software-computed safety signals — so any debounce/hysteresis logic against a single borderline reading is that driver's own responsibility, not this module's. An **internet API** with no device behind it (`SAFE-050` weather forecast, `SAFE-090` aurora, `SAFE-100` smoke) is a structurally different input — advisory-only, fetched directly by this module rather than through a device port, and structurally unable to publish an abort event, for the same reason `SAFE-050` is walled off. No Tier 2 device is implemented in this repository at present (Project Scope Document, Section 11, C8) — `SAFE-080` and this design note describe the pattern any future one must follow, not a specific product.
- **Libraries:** an Open-Meteo API client (weather forecast), a NOAA Kp-index/OVATION client (`SAFE-090`), a NOAA HMS smoke-polygon client (`SAFE-100`).
- **Satisfies:** `SAFE-010`–`SAFE-100`, `EXT-130`.

### 4.17 `galileo.history` — Session History & Statistics

- **Responsibility:** Per-frame metric recording (HFR, star count, guide RMS), review UI, cross-restart retention, export.
- **Key design:** Append-only Peewee models keyed by session/sequence ID, in the same database as `galileo.library`'s repository catalog (ADR-002) rather than a separate SQLite file; chart rendering via Qt Charts against a query view.
- **Satisfies:** `HIST-010`–`HIST-040`.

### 4.18 `galileo.metadata` — Image Metadata (FITS)

- **Responsibility:** FITS header population, plate-solve result injection, tile-compressed FITS read/write, custom static keywords. FITS is the sole supported image format (Project Scope Document, Section 11, C3) — no XISF or other format support exists in this module.
- **Key design:** Compressed output uses `astropy.io.fits.CompImageHDU`, which wraps CFITSIO's tile-compression implementation directly — no separate compression library or format-specific writer is needed, since this is standard FITS, not an alternate container format. Default compression algorithm is Rice (lossless, low CPU cost, the common default for astronomical CCD/CMOS data); GZIP and HCOMPRESS are selectable per profile.
- **Libraries:** `astropy.io.fits` (covers both plain and tile-compressed FITS read/write).
- **Satisfies:** `META-010`–`META-050`, `EXT-060`.

### 4.19 `galileo.notify` — Notifications

- **Responsibility:** In-app and external notification delivery for sequence/safety events, per-channel/per-event enablement.
- **Key design:** `NotificationChannel` adapter interface (in-app, webhook, email); event set sourced from the same event bus used internally, so no separate event-detection logic is needed.
- **Satisfies:** `NOTIF-010`–`NOTIF-030`, `EXT-070`.

### 4.20 `galileo.plugins` — Plugin Framework

- **Responsibility:** Plugin discovery/load/unload, manifest/version compatibility checking, plugin manager UI (third-party plugins only), fault isolation, first-party pre-loaded plugin enable/disable, UI-panel insertion at primary or secondary navigation level, and the `PluginContext` service-access surface plugins use to call back into core (e.g. submitting a Scheduler job).
- **Key design:** Plugins are Python packages discovered via `importlib.metadata` entry points, declaring device-port, `SequencerNode`, or UI-panel implementations plus a manifest (name, version, API-compatibility range, and — new — a `preloaded: bool` flag distinguishing first-party pre-loaded plugins from third-party repository-installed ones, `PLUG-060`). Every call from the domain core into plugin-provided code is wrapped at the call boundary in an exception handler that logs and disables the offending plugin instance rather than propagating, satisfying `PLUG-040`'s crash-isolation requirement. A UI-panel-registering plugin declares its desired `nav_level` (`primary` or `secondary`, `PLUG-070`) in its manifest; the shell's navigation container reads this the same way for first-party and third-party plugins, so there is no separate "built-in tab" code path a pre-loaded plugin's tab has to fake its way into. `PluginContext` (Section 6.3) exposes a narrow, explicitly-granted set of core service handles (e.g. a `SchedulerJobSubmitter`) rather than the whole domain core, so `PLUG-080`'s callback surface stays auditable rather than becoming a second, informal plugin API.

**Reference implementation:** `galileo.vstarget.planning`/`galileo.vstarget.analysis` (Sections 4.24–4.25, merged from VSTarget) are packaged and shipped as first-party pre-loaded plugins (`plugins/vstarget/`) — the concrete demonstration of pre-loaded-plugin enable/disable (`PLUG-060`), primary-level UI-panel insertion (`PLUG-070`), and the `PluginContext` Scheduler-submission callback (`PLUG-080`, `VST-090`). No implementation exists in the repository yet for the device-backend extension point (`PLUG-010`) — see `galileo.safety` (Section 4.16): a Tier 2 safety device is the intended future case, run as a standalone INDI driver rather than an in-process plugin, but none is currently specified for or committed to this project.

**Design note:** this provides fault isolation, not memory/security sandboxing — a plugin runs in-process with full application privileges; stronger sandboxing (e.g. subprocess-per-plugin) is out of scope for v1 and should be revisited if the plugin catalog admits untrusted third-party code at scale. In-process loading also has a licensing consequence, not just a technical one: under Galileo's GPL-3.0 license (ADR-002), plugins are very likely "combined works" and must themselves be GPL-compatible-licensed to distribute — pre-loaded first-party plugins are trivially compliant since Galileo controls their license too.
- **Satisfies:** `PLUG-010`–`PLUG-080`, `NFR-EXT-010`.

### 4.21 `galileo.ui.theme` — Customization & Theming

- **Responsibility:** Light/dark theme, accent color, dockable panel layout persistence.
- **Key design:** Qt Style Sheets (QSS) driven by a small token set (background/surface/accent/text), so a theme is a token file, not per-widget styling.
- **Satisfies:** `UI-010`–`UI-030`.

### 4.22 `galileo.diagnostics` — Logging & Diagnostics

- **Responsibility:** Runtime logging service capturing all application log output, in-app log viewer (including a per-device-screen live tail), unhandled-exception capture, support-bundle export.
- **Key design:** `DiagnosticsService` sets the root `logging` logger to `DEBUG` and attaches a `logging.FileHandler` writing to a datestamped file under `logs/` in the application's own root directory (`default_log_dir()`, not a per-platform user directory — a deliberate departure from `NFR-INSTALL`-style per-OS conventions, made so the current run's log is always found next to the application itself) — opened in truncate mode (`LOG-050`) so each run starts a fresh file rather than appending to a prior run's. Because the root logger's level and handler are process-wide, every module's own `logging.getLogger(__name__)` calls are captured, not only ones routed through `DiagnosticsService`'s own `log_info`/`log_warning`/`log_error`/`log_exception` convenience methods (`LOG-010`'s "all runtime log output" clause) — this includes third-party library logging (e.g. Peewee's own SQL debug output) picked up along the way. A second handler (`_TailBufferHandler`) feeds a bounded, process-wide in-memory ring buffer exposed via `get_recent_log_lines(n)`, independent of any particular `DiagnosticsService` instance; `galileo.ui.app_window`'s Equipment device-category pages each embed a small read-only, auto-scrolling `QPlainTextEdit` (fixed to a 10-line viewport, scrollable back through a larger buffer) polling that function on a shared timer (`LOG-060`) — a lightweight, always-visible alternative to opening a dedicated Log Viewer for `LOG-020`.
- **Libraries:** standard library `logging` only (no `platformdirs` — the log directory is resolved directly, matching the application-root placement above).
- **Satisfies:** `LOG-010`–`LOG-060`.

### 4.23 `galileo.library` — Image Library & Repository Management (merged from AstroFiler)

- **Responsibility:** Repository scanning/ingestion (FITS and XISF), SHA-256 dedup, metadata-driven file organization, session linking (both heuristic, `LIB-040`, and sequence-authoritative, `LIB-160`), master calibration-frame creation and application, SEP-based quality metrics, repository statistics, smart-telescope ingestion (SMB/CIFS, FTP/FTPS), Google Cloud Storage sync, live auto-registration during acquisition, and CLI entry points.
- **Key design:** This module is the vendored core of AstroFiler (ADR-002), restructured behind the same domain-core/adapter boundary as the rest of Galileo: scanning/dedup/organization/session-linking/master-frame logic is domain-core (no I/O dependency beyond the filesystem and the Peewee models it owns); SMB, FTP/FTPS, and GCS access are adapters (`SmbSourceAdapter`, `FtpSourceAdapter`, `GcsSyncAdapter`) implementing a common `RemoteSourceAdapter` interface, so adding a new smart-telescope source is an adapter, not a core change — consistent with how `PLT` treats solvers and `GUIDE` treats guiders elsewhere in this document.
  - **XISF import (`LIB-010`):** a best-effort `XisfToFitsConverter` runs at ingest time only — this module never reads or writes XISF anywhere else, preserving the FITS-only constraint (Project Scope Document, Section 11, C3) for everything downstream of ingestion. Metadata/pixel data that doesn't map cleanly to FITS keywords is logged, not silently dropped, and the frame is still ingested.
  - **Auto-registration (`LIB-150`):** rather than polling, `galileo.sequencer.basic`/`galileo.sequencer.advanced` (Sections 4.6–4.7) publish a "frame written" event on the domain-core event bus (Section 2.2) after each capture completes; this module subscribes and registers the frame immediately, the same fault-isolated event-bus pattern used for safety/dome coordination elsewhere in this document — `LIB-010`'s scan remains available as a reconciliation path for frames from outside a Galileo-run sequence (manual copies, other tools), not the primary ingestion route once a sequence is running.
  - **Session containers (`LIB-160`):** a `SessionContainer` is created per sequence-step execution and referenced by every frame the "frame written" event carries for that step — this is populated directly from the sequencer's own step boundaries, not inferred from FITS headers after the fact, which is what distinguishes it from `LIB-040`'s heuristic grouping of files already in the repository (the two coexist: a `LIB-160` container is authoritative when available, `LIB-040` grouping is the fallback for repository content that never went through a Galileo sequence).
  - **CLI (`LIB-130`/`EXT-140`):** thin command-line entry points (`galileo-scan`, `galileo-calibrate`, `galileo-sync`) that call directly into this module's domain-core functions, bypassing the UI layer entirely — matching AstroFiler's own `LoadRepo`/`Calibrate`/`CloudSync` pattern (Project Scope Document, Section 6.2). Each entry point exposes exactly one domain-core function selectively, not a general-purpose scripting shell — consistent with `EXT-010`'s "selective exposure," not a backdoor into interactive equipment control.
- **Libraries:** `astropy.io.fits` (metadata extraction, shared with `galileo.metadata`), `peewee`/`peewee-migrate` (catalog persistence, project-wide per ADR-002), `SEP` (quality metrics, unified per ADR-002), `pysmb` (SMB/CIFS), standard-library `ftplib` (FTP/FTPS), `google-cloud-storage`/`google-auth` (cloud sync), `Pillow` (thumbnail/preview generation).
- **Satisfies:** `LIB-010`–`LIB-160`, `EXT-080`, `EXT-090`, `EXT-140`.

### 4.24 `galileo.vstarget.planning` — Variable Star Target Planning (merged from VSTarget)

- **Responsibility:** AAVSO target sync/filtering, variable-star list display, observable-only filtering, manual import, observation-plan editor, ACP observing-script generation, Simbad lookup, direct submission of a target/plan to `galileo.scheduler`'s job queue. Packaged as the first-party pre-loaded plugin `plugins/vstarget/` (Section 4.20), registering a primary-level UI panel (`PLUG-070`) presented as a peer section to `galileo.planning.sky_atlas`, not nested beneath it, when enabled.
- **Key design:** Reuses `galileo.planning.sky_atlas`'s visibility-computation service (Section 4.8) for the observable-only filter (`VST-030`) rather than duplicating rise/transit/set logic. Scheduler submission (`VST-090`) goes through the `PluginContext`-granted `SchedulerJobSubmitter` handle (Section 4.20, `PLUG-080`) rather than a direct import of `galileo.scheduler`, keeping the plugin/core boundary consistent even for a first-party plugin.
- **Libraries:** `requests` (AAVSO Target Tool/VSP API client), `astroquery` (Simbad lookup).
- **Satisfies:** `VST-010`–`VST-090`, `EXT-100`, `EXT-110`.

### 4.25 `galileo.vstarget.analysis` — Variable Star Analysis & Photometry (merged from VSTarget)

- **Responsibility:** Remote-telescope image retrieval, plate-solve orchestration (via `galileo.platesolve`), photometric mean-stacking, aperture photometry against AAVSO VSP comparison stars, AAVSO WebObs report generation, transformation-coefficient calibration, exposure calculator, AAVSO finder-chart generation. Packaged as its own first-party pre-loaded plugin (`plugins/vstarget_analysis/`, paired with but independently enabled/disabled from `plugins/vstarget/`, Section 4.24) — a user can run target planning without the analysis pipeline, or vice versa.
- **Key design:** Photometric stacking (`VST-AN-030`) is a distinct, bounded operation from any general-purpose image stacking — it exists solely to improve SNR for a photometric measurement and is not exposed as a general "stack my lights" feature. Star registration runs in the process pool (Section 2.3) alongside the rest of Galileo's CPU-bound work. Comparison-star retrieval and finder-chart rendering (`VST-AN-090`) are adapted from AstroLlama's `variable_comparison_stars_tool.py`/`generate_aavso_map_tool.py` (ADR-004, Section 2.7).
- **Libraries:** `astroalign` (registration), `photutils` (aperture photometry — see ADR-003 for why this is not a SEP duplication), `pandas` (photometry tables), `matplotlib` (interactive transformation-outlier review, and finder-chart rendering), `paramiko` (SFTP).
- **Satisfies:** `VST-AN-010`–`VST-AN-090`, `EXT-120`.

### 4.26 `galileo.derotation` — Rotator Field Derotation

- **Responsibility:** The domain logic behind the Rotator Equipment page's derotation section (layout reference: `assets/samples/rot.png`): converting a target's RA/Dec to Alt/Az for a site and time, the alt-az field rotation rate, and turning that rate into rotator move commands.
- **Key design:** Pure Python with no Qt, INDI or Alpaca dependency; the page drives a device adapter with it. The rate is `Ω·cos(lat)·cos(az)/cos(alt)` (Ω = 0.25068°/min, clamped near the zenith where it diverges). Sidereal time is computed directly from the Julian date rather than through `astropy`'s Alt/Az frames, which can try to download IERS data at runtime. `Derotator` integrates the rate into a virtual angle and only requests a move once it has drifted a minimum step (default 0.05°) from the last commanded angle, so a rotator isn't commanded for every tiny increment. A target comes from typed RA/Dec, or the newest FITS file in a folder (solved WCS, then `OBJCTRA`/`OBJCTDEC`, then `RA`/`DEC`). The rotator adapters (`galileo.adapters.indi` / `.alpaca`) gained `get_status`, `halt`, `set_reverse`, `sync_position` and `set_backlash`; backlash exists only on INDI drivers implementing it (ASCOM's `IRotatorV3` has none, and the INDI Rotator Simulator lacks it), and reports `DevicePropertyError` otherwise. The Reverse setting also flips the derotation direction. The derotation direction sign has not been validated against a real alt-az rig.
- **Libraries:** standard library plus `astropy.io.fits` for reading headers.
- **Satisfies:** `EQP-ROT-010` (position display and move commands). Derotation itself has no requirement ID yet — it should be added to the SRS/RTM.

---

## 5. Data Design

| Data | Format | Storage |
|---|---|---|
| Equipment profile (Pier) | JSON, `pydantic`-validated schema | Per-platform user config directory |
| Observatory (Pier grouping, resource scoping) | JSON, `pydantic`-validated schema, alongside Pier profiles | Per-platform user config directory |
| Sequence definition (basic + advanced) | JSON, `pydantic`-validated schema | User-chosen file location; also embedded/referenced from session history |
| Sky Atlas catalog | SQLite (bundled, read-only at runtime) | Installed alongside application |
| Image repository catalog, session links, master-frame records, quality metrics | Peewee ORM over SQLite (schema evolved via `peewee-migrate`, inherited from AstroFiler — ADR-002) | Per-platform user data directory |
| Variable-star observation plans, target lists, transformation coefficients | Peewee models in the same database (ADR-002/ADR-003), superseding VSTarget's separate SQLite file | Per-platform user data directory |
| Sky-survey/DSS thumbnail cache (`SKY-080`) | Cached image files, keyed by catalog object ID | Per-platform user cache directory |
| Scheduler job queue and per-job multi-night progress | Peewee models in the same database (ADR-002) | Per-platform user data directory |
| Session history (HFR/star-count/guide-RMS trend data) | Peewee models in the same database as the repository catalog, not a separate SQLite file | Per-platform user data directory |
| Captured images | FITS (plain or tile-compressed — Rice/GZIP/HCOMPRESS) | User-configured capture directory |
| Application/session logs | Timestamped structured text, one datestamped file reset per run (`LOG-010`/`LOG-050`) | `logs/` under the application's own root directory (not a per-platform user directory — see Section 4.22) |
| Plugin manifest | JSON/TOML declared via package `entry_points` | Installed with plugin package |

All schema-validated formats (`pydantic` models) double as the machine-checkable contract for `EXT-060`, `META-010`–`META-030`, and the profile/sequence persistence requirements — schema validation failures surface as the "recoverable error" path required by `SEQ-080`/`PROF-060` rather than a crash.

---

## 6. Interface Design

### 6.1 Device Port Interfaces (internal)

Each device category exposes a minimal, transport-agnostic interface, e.g.:

```
CameraPort: connect(), disconnect(), capabilities() -> DeviceCapabilities,
            start_exposure(params), abort_exposure(), set_cooler_target(temp),
            on_frame_ready: Signal[FrameData], on_status_changed: Signal[DeviceStatus]
```

Both `galileo.adapters.indi` and `galileo.adapters.alpaca` implement every port; the domain core and UI never import either adapter module directly, only the port interfaces (enforced by module-boundary lint rules).

### 6.2 External Process Interfaces

- **Solvers:** subprocess invocation with a documented argument/exit-code/output-file contract per solver adapter (`galileo.platesolve`).
- **Guiders:** PHD2-compatible JSON-RPC-over-TCP event/command stream (`galileo.guiding`).
- **Smart-telescope/cloud sources:** SMB/CIFS session (`pysmb`), FTP/FTPS session (`ftplib`), and Google Cloud Storage API calls, each behind the `RemoteSourceAdapter` interface (`galileo.library`, Section 4.23).
- **AAVSO/Simbad/SFTP:** AAVSO Target Tool and VSP REST API calls (`requests`), Simbad queries (`astroquery`), and SFTP image retrieval (`paramiko`), used by `galileo.vstarget.planning`/`galileo.vstarget.analysis` (Sections 4.24–4.25).
- **Open-Meteo:** geocoding (`galileo.planning.sky_atlas`, `SKY-090`) and weather-forecast (`galileo.safety`, `SAFE-050`) REST calls, adapted from AstroLlama (ADR-004, Section 2.7).

### 6.3 Plugin API Surface

A plugin depends only on: the device port interfaces (4.1), the `SequencerNode` interface (4.7), and a small `PluginContext` object (logging, config directory, event-bus handle) injected at load time. No plugin imports UI or adapter internals directly.

---

## 7. Deployment Design

Two supported topologies, both served by the same codebase (Section 2.1):

- **Topology A — Network split (primary, recommended default):** A Raspberry Pi 5 (or similar SBC) at the telescope runs only `indiserver` + device drivers (or an Alpaca device bridge) — not Galileo itself. Galileo's full GUI runs on a separate desktop/laptop, connecting to the SBC over the local network via the INDI/Alpaca adapters (`ARCH-020`, `EXT-030`). This keeps the SBC's resource constraints out of the GUI's performance budget entirely and is the deployment pattern the INDI ecosystem already assumes.
- **Topology B — Local/all-in-one:** Galileo's full GUI runs directly on the SBC (e.g. an all-in-one imaging box with a local touchscreen, or headless with VNC). PySide6's shared Qt rendering engine (ADR-001) makes this viable on Pi 5-class hardware, at a higher resource cost than Topology A.

The SDD does not mandate one topology for end users — both are supported by the architecture — but Topology A should be the documented recommended default for resource-constrained hardware.

---

## 7. Non-Functional Requirement Traceability

Functional requirements each trace to one primary module's `Satisfies` line (Section 4). Non-functional requirements are mostly cross-cutting and are addressed architecturally rather than by a single module — most already have an inline mention where the relevant design decision is made (e.g. `NFR-PERF-020`/`NFR-REL-010`/`NFR-REL-020`/`ARCH-060` in Section 2.3's concurrency model). The following have no `Satisfies` or inline mention anywhere above and are recorded here so the RTM has a component to point to for every SRS ID, not just the functional ones:

| Requirement | Addressed by |
|---|---|
| `NFR-PERF-010` (full-frame render ≤3s) | `galileo.ui.imaging` (Section 4.5) rendering pipeline; verified by performance test, not a design-time guarantee any single module line can assert |
| `NFR-PERF-030` (stable memory over 8h) | Cross-cutting outcome of the `ProcessPoolExecutor` CPU-work isolation (Section 2.3) and per-sequence progress persistence (`galileo.sequencer.basic`, Section 4.6) not leaking state across long runs; verified by soak test |
| `NFR-REL-030` (10h unattended sequence) | Cross-cutting outcome of `NFR-REL-010`/`020`'s device-error/stall handling (Section 2.3) plus the Watchdog (`galileo.safety`, Section 4.16, `SAFE-060`); verified by soak test, not a single module's responsibility |
| `NFR-PORT-020` (unavailable features disabled, not silently failing) | `galileo.core.devices`' `DeviceCapabilities` model (Section 4.1) — the mechanism the UI already uses to decide what to render is the same mechanism that lets it disable rather than hide an unavailable control |
| `NFR-USE-010` (guided first-run setup) | `galileo.equipment.profiles`/`galileo.observatory` (Sections 4.4/4.4a) own the underlying flow; the guided-wizard UI itself has no dedicated module, it's a UI-layer composition of existing equipment/connection screens |
| `NFR-I18N-010` (externalized UI strings) | A cross-cutting implementation convention (Qt's `tr()`/`.ts` translation-file mechanism) applied across every `galileo.ui.*` module, not owned by any one of them |
| `NFR-SEC-010` (no credential/location exfiltration without consent) | A cross-cutting constraint on every adapter that talks to an external service (`galileo.adapters.*`, `galileo.vstarget.*`, `galileo.library`'s cloud-sync adapter, Open-Meteo clients) — enforced by code review/security review, not one module |
| `NFR-SEC-020` (document WAN-exposure security implications) | A documentation deliverable (user-facing docs), not a code module — tracked here so it isn't lost, not because it traces to a component |
| `NFR-OFFLINE-020` (offline plate-solving path) | `galileo.platesolve` (Section 4.12) — already satisfies `PLT-020`, which this NFR directly restates as a non-functional guarantee rather than a new capability |
| `EXT-010` (GUI as sole primary interface, no CLI in v1) | Architectural given from ADR-001 (Section 2.1) — Galileo is a PySide6 desktop application by construction, not a per-module design choice |
| `NFR-PORT-010` (single codebase, all platforms) | ADR-001 (Section 2.1) and the layered/ports-and-adapters architecture (Section 2.2) as a whole — this is the architecture's central premise, not one module's property |
| `NFR-INSTALL-010`, `NFR-INSTALL-020`, `NFR-INSTALL-030` (per-platform installers) | Section 2.4's packaging/build-target table — a build-pipeline deliverable, not a `galileo.*` module |

---

## 8. Path to Traceability Matrix

The RTM is constructed as: **SRS requirement ID → SDD module (Section 4, "Satisfies" row, or Section 7 for the non-functional requirements without one) → test case ID.** Sections 4 and 7 together are exhaustive over the SRS (every requirement ID appears in exactly one place above), so the RTM's Component column can be generated directly from this document without further mapping work.

---

*This document is a living draft. The plugin-sandboxing posture (Section 4.20) is flagged as an open implementation decision to revisit before RTM sign-off.*
