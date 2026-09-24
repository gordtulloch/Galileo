# Galileo — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — Cross-Platform Astrophotography Imaging Suite |
| **Document** | PSD (Project Scope Document), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-09-16 |
| **Downstream documents** | SRS (Software Requirements Specification), SDD (Software Design Description), RTM (Requirements Traceability Matrix) |

---

## 1. Purpose of This Document

This document defines the scope of Galileo at a level suitable for stakeholder review and sign-off. It identifies *what* the product will and will not do, the platforms and protocols it targets, and the large-scale requirement domains that will later be decomposed into numbered, testable requirements in the SRS. Each requirement domain below is pre-tagged with an ID prefix so that SRS requirements, SDD components, and the RTM can trace back to this document without renumbering.

This document intentionally stays above implementation detail — no UI layouts, class designs, or protocol message schemas. Those belong in the SDD.

## 2. Background and Motivation

The decision to build Galileo rests on two pillars, and the second is at least as important as the first:

1. **Non-Windows imaging software has a UI/UX gap.** Astrophotography imaging software on Windows, macOS, and Linux — [KStars/EKOS](https://kstars.kde.org/) chief among the non-Windows options (Section 6.6) — has largely aging interfaces built up incrementally over a decade or more. Galileo aims to bring a modern, guided, well-designed imaging workflow to non-Windows platforms, rather than accept a dated UI as the cost of cross-platform/INDI-based imaging. [N.I.N.A. (Nighttime Imaging 'N' Astronomy)](https://nighttime-imaging.eu/) — a free, open-source, Windows-only imaging application — is one useful design touchstone for what a modern guided workflow can look like, and informs Galileo's UI/UX approach (Sections 3–4), but Galileo is not an attempt to clone NINA feature-for-feature, and it is **not affiliated with, derived from, or endorsed by the N.I.N.A. project**.
2. **Consolidating the author's prior work into one cohesive application.** Galileo's author has built a substantial, disparate body of astronomy software over several separate projects — an image manager, a variable-star planner, observatory-automation scripts, an all-sky cloud-detection classifier, and more (below). Bringing this scattered prior work together into a single, cohesive application — rather than continuing to maintain several disconnected tools — is a primary motivation for building Galileo, not a secondary benefit realized along the way.

Galileo is an independent, clean-room application. It targets cross-platform, vendor-neutral device protocols instead of NINA's Windows-only ASCOM/COM foundation:

- **INDI** (Instrument Neutral Distributed Interface) — the standard cross-platform device control protocol, mature on Linux/macOS and available on Windows.
- **ASCOM Alpaca** — the network/REST-based evolution of ASCOM that is OS-independent and interoperable with the existing Windows ASCOM driver ecosystem via remoting.

By targeting these two protocols instead of native ASCOM COM or platform-specific SDKs, Galileo can reach the same device ecosystem existing Windows imaging-suite users already own, from any of the three major desktop operating systems.

On pillar 2: Galileo's author has already built [AstroFiler](https://github.com/gordtulloch/astrofiler-gui), a working, GPL-3.0-licensed astronomy image management application (Python/PySide6, using AstroPy, Peewee/SQLite, and SEP) that scans, catalogs, deduplicates, and organizes FITS repositories; ingests from SEESTAR/StellarMate/DWARF/iTelescope smart telescopes; creates and applies master calibration frames; and computes per-frame quality metrics (FWHM/HFR/eccentricity/SNR). AstroFiler already runs on the exact stack chosen for Galileo (Section 2.1 of the SDD), and merging it in is a v1 goal (Section 4, G7) rather than a future integration. AstroFiler's own installation scripts (automated Python/venv/dependency setup, desktop integration, auto-update, covering Windows/Linux/macOS) are also harvested as direct inspiration for Galileo's own self-contained installer/build process (Section 7) — not just its application features.

Several further same-author tools are being folded in for v1:

- [VSTarget](https://github.com/gordtulloch/VSTarget) — a GPL-3.0, Python/PySide6 AAVSO variable-star observation planner and photometric analysis tool. It runs on the same stack as Galileo and AstroFiler, and ships as a first-party, pre-loaded plugin against Galileo's own plugin architecture (`PLUG` domain, Section 8) rather than as a core-embedded domain — its own scope, requirements, and design live in a separate document chain under [`docs/plugins/vstarget/`](plugins/vstarget/PSD.md), not in this document.
- [Obsy](https://github.com/gordtulloch/obsy) — a Django-based observatory management/scheduling system built as a layer over KStars/EKOS. It is being retired in favor of Galileo; its FITS-management functionality has already been superseded by AstroFiler, its scheduling capability was only cursory and is explicitly not being carried forward, but its target/visibility-computation logic (rise/transit/set via `astroplan`, DSS-cutout thumbnail caching) is being ported directly into Galileo's `SKY`/`FRAME` domains. Obsy has since been relicensed to GPL-3.0 (Section 11, C6), removing the earlier CC BY-NC-ND 4.0 constraint that required clean-room reimplementation — direct porting is now the norm here, same as AstroFiler, though Obsy's Django architecture still limits *practical* reuse to specific functions/algorithms rather than whole modules, since Galileo's equivalents are PySide6/Qt desktop code with no Django counterpart to port into.
- [MCP](https://github.com/gordtulloch/MCP) ("Master Control Programs for Observatories and Telescopes," part of the Obsy ecosystem, **relicensed to GPL-3.0** — Section 11, C8) — a set of observatory-automation scripts providing independent rain (Hydreon RG-11 serial sensor), aurora (NOAA OVATION/Kp-index API), and smoke (NOAA HMS smoke-polygon API) detection modules. Its safety-sensor logic is now ported directly, not reimplemented clean-room, into new `SAFE` domain requirements (Section 8); its EKOS-DBus/MQTT/dome-client orchestration modules are EKOS-specific and not applicable to Galileo's own architecture, so they are still not harvested.
- [AstroLlama](https://github.com/gordtulloch/AstroLlama) (specifically its [MCP (Model Context Protocol — unrelated to the "MCP" repo above) server tools](https://github.com/gordtulloch/AstroLlama/tree/main/mcp_server/tools)) — a GPL-3.0 AI-assistant project whose MCP tool functions include a working, standalone INDI/Alpaca device-abstraction-and-profile-registry pattern, an ASTAP plate-solving adapter, an Alpaca slew/capture/plate-solve/park orchestration tool, AAVSO comparison-star and finder-chart generation, and location geocoding/weather lookups via Open-Meteo. This is a third, narrower integration pattern (Section 6.5): only the astronomy-device/imaging-specific functions are selectively harvested into Galileo's existing domains (`ARCH`, `PROF`, `PLT`, `SKY`, `SAFE`) or, in one case, the VSTarget plugin's own analysis module (`docs/plugins/vstarget/`); AstroLlama's generic AI-assistant tools (news/wiki/YouTube/web search, arXiv, Wolfram Alpha, chat orchestration) are explicitly excluded — they have nothing to do with Galileo.

## 3. Vision Statement

> Galileo gives astrophotographers on Windows, macOS, and Linux a single, polished, protocol-agnostic imaging application with a modern guided workflow — replacing both the aging interfaces of existing non-Windows imaging tools and the author's own scattered prior projects with one cohesive application, without requiring Windows or proprietary drivers.

## 4. Goals and Objectives

G1–G6 deliver pillar 1 (Section 2): a modern, guided, cross-platform imaging workflow. G7–G14 deliver pillar 2: consolidating the author's prior work into one cohesive application. G16 and G17 stand apart from both — capabilities (multi-mount observatory management; strict device-abstraction purity for safety devices) that go beyond what NINA or EKOS themselves offer, or enforce more strictly than this document's own earlier drafts did.

| # | Goal |
|---|---|
| G1 | Deliver functional parity with a modern deep-sky imaging workflow — equipment control, sequencing, autofocus, plate solving, calibration, sky navigation — of the kind established imaging suites (NINA among them) provide |
| G2 | Run natively on Windows, macOS, and Linux from a single codebase, with installers for each — explicitly including Raspberry Pi 5-class ARM SBCs running Debian as a first-class target, not just x86 desktops |
| G3 | Support device control exclusively through INDI and ASCOM Alpaca, avoiding OS-specific driver binding |
| G4 | Adopt a modern, guided UI/UX design approach for the imaging tab, the Sessions screen's drag-and-drop instruction/condition/trigger model, and the framing/sky atlas workflow — informed by well-regarded existing imaging suites, NINA's included, rather than any single one |
| G5 | Provide an extensible plugin architecture, in the spirit of established imaging suites' plugin ecosystems, so the community can add device support and workflow instructions without forking core |
| G6 | Be reliable enough for unattended, multi-hour overnight imaging sessions |
| G7 | Merge AstroFiler's repository scanning, cataloging, deduplication, smart-telescope ingestion, master-calibration-frame, and quality-metric capabilities into Galileo as its image-library and calibration-processing foundation, delivered in v1 — extended with best-effort XISF-to-FITS import, live auto-registration of frames during acquisition, sequence-step-scoped session containers, and standalone CLI batch utilities matching AstroFiler's own command-line tools. Galileo's `SES` authoring UI (the "Sessions" screen, Section 8) adopts AstroFiler's session terminology directly rather than coining a parallel term: a session is both the set of related output artifacts *and*, now, the ordered actions that produce them |
| G8 | Deliver a genuinely capable plugin architecture (`PLUG`, Section 8) — not a thin device-driver hook, but one expressive enough that a workflow as substantial as AAVSO variable-star target planning and photometric analysis can be built entirely on top of it, as two separate, pre-loaded, independently-disableable first-party plugins delivered in v1. VSTarget's own scope, requirements, and design are specified separately (`docs/plugins/vstarget/`, Section 6.3) rather than embedded here, precisely to keep this document's own domains free of anything that isn't Galileo core itself |
| G9 | Port Obsy's target-visibility and sky-survey-thumbnail logic directly into the `SKY`/`FRAME` domains (GPL-3.0, Section 11, C6); retire Obsy itself, excluding its scheduling functionality — wired into and augmented as Galileo's own Targets screen with an offline object database, a SIMBAD search fallback, size-aware thumbnail cropping, and optional Telescopius API enrichment (Section 6.9), none of which Obsy itself had |
| G10 | Selectively harvest AstroLlama's astronomy-device MCP tool functions (device abstraction/profile registry, ASTAP adapter, Alpaca imaging orchestration, AAVSO comparison-star/finder-chart generation, geocoding/weather lookup) into the relevant existing domains, excluding all of its non-astronomy generic AI-assistant tooling |
| G11 | Add a live, interactive star-map/planetarium view (`SKYMAP`) as a peer domain to the catalog-based Sky Atlas (`SKY`) and the Framing Assistant (`FRAME`), closing a gap identified against KStars/EKOS (Section 6.6) |
| G12 | Add a multi-night observatory `SCHED`uler modeled on EKOS's (prioritized job queue, altitude/moon/twilight/horizon constraints, weather-gated startup, multi-night progress tracking), in full v1 scope — supersedes the earlier Obsy-driven exclusion of scheduling (Section 5) |
| G14 | Harvest MCP's rain/cloud/aurora/smoke detection approach into the `SAFE` domain as additional safety-monitor input sources, distinguishing local-sensor inputs (rain sensor, all-sky-camera cloud classification — trusted for automated abort) from internet-API inputs (aurora Kp-index, smoke polygons — advisory only, same tier as `SAFE-050`) |
| G16 | Support a single Galileo instance managing multiple independent mounts/telescopes ("Piers") grouped into an "Observatory," with `SCHED` coordinating jobs across them and shared resources (dome/roof, safety monitoring) scoped at the Observatory or Pier level — deliberately exceeding EKOS's own single-mount-per-instance limitation (Section 6.6) |
| G17 | Enforce a strict Tier 1 (hardware)/Tier 2 (software-computed) safety-device model in which *every* safety-monitor input — including an ML-based cloud classifier — connects exclusively through the device-abstraction layer (`ARCH-010`): either an external INDI/Alpaca driver (`EXT-020`) or an in-process device backend a plugin registers through the same `PLUG-010` extension point every other device category already uses. What's forbidden is a bespoke, ad-hoc safety-signal path that skips the port interface entirely — not a plugin using the extension point the architecture already grants it |

## 5. Non-Goals (Explicitly Out of Scope)

- **No ASCOM COM / native driver binding.** Galileo will not talk to Windows ASCOM COM drivers directly; interoperability with the ASCOM ecosystem is provided only via the Alpaca network protocol (including ASCOM's own Alpaca-to-COM bridge, which is the user's responsibility to run, not Galileo's).
- **No deep post-processing suite.** Stacking/integration of light frames into a final aesthetic image, deconvolution, gradient removal, and other PixInsight-style post-processing remain out of scope for the initial product. This boundary has narrowed from earlier drafts with one explicit carve-out: master calibration-frame creation (bias/dark/flat) and application to lights (dark subtraction, flat division), in scope via the AstroFiler merge (`LIB` domain) — a bounded, purpose-specific operation, not general-purpose final-image stacking/integration. (The VSTarget plugin's own bounded, photometric-measurement-only stacking is documented separately, `docs/plugins/vstarget/PSD.md`, Section 5 — it is that plugin's own carve-out, not core's.)
- ~~No observatory scheduling system.~~ **Superseded (Section 6.6, G12).** The original reasoning — that Obsy's own scheduling was too cursory to carry forward — is still correct, but a subsequent KStars/EKOS review found that mature, multi-night observatory scheduling (not Obsy's version) is core to how people actually run unattended campaigns. Galileo now includes a `SCHED` domain modeled on EKOS's Scheduler, in full v1 scope.
- **No planetary/lucky-imaging (high-frame-rate) workflow** in the initial release — Galileo targets deep-sky long-exposure imaging first, the dominant use case across established imaging suites.
- **No mobile applications** (iOS/Android) in the initial release.
- **No bundled guiding engine.** Galileo will integrate with existing external guiders (e.g., PHD2) via their control protocols rather than reimplement guiding algorithms, at least initially.
- **No replacement for planetarium software** — Galileo's Sky Atlas/Framing Assistant is for target selection and framing, not general-purpose astronomical charting.

These exclusions may be revisited in later phases; they are scoped out of v1 to keep the initial delivery achievable.

## 6. Reference: Feature Inventories

### 6.1 NINA Feature Inventory

One input among several (Sections 6.2–6.7 cover the others) to Galileo's scope: the following feature inventory was compiled from NINA's public site and documentation ([nighttime-imaging.eu](https://nighttime-imaging.eu/), [docs](https://nighttime-imaging.eu/docs/master/site/)) and is used as one functional baseline for Section 8, alongside the KStars/EKOS review (Section 6.6).

- **Equipment control:** Camera, Telescope (mount), Filter Wheel, Focuser, Rotator, Guider, Switch (power/relay), Flat Panel, Weather Device, Dome, Safety Monitor
- **Imaging tab:** live capture view, histogram, auto-stretch preview, per-frame statistics, star detection/HFR
- **Sequencer:** Legacy (basic) sequencer for straightforward target lists; Advanced Sequencer with nested instructions, loop conditions, and triggers, organized into reusable templates
- **Sky Atlas:** 10,000+ deep-sky object catalog with filtering and altitude charting
- **Framing Assistant:** sky-survey imagery overlay, field-of-view preview, mosaic planning, offline star-field mapping with constellation/coordinate grid overlays
- **Flat Wizard:** automated flat-frame exposure/brightness calibration, presented within the Imaging tab rather than as its own top-level section
- **Autofocus:** HFR-curve-fit-based automatic focus, triggerable on schedule/temperature/filter-change/HFR-drift conditions
- **Plate Solving:** integration with external/local/online solvers for target centering and pointing verification
- **Automated Meridian Flip**
- **Guiding integration** (dithering, guide-start/stop control)
- **Dome synchronization** with mount slaving
- **Session History:** per-session HFR/star-count/statistics trending
- **FITS/XISF metadata:** extensive header keyword support (Galileo scope: FITS only, including compressed FITS — see Section 11, C3)
- **Options/Settings:** general, equipment, autofocus, dome, imaging, plate-solving configuration domains
- **Plugin framework:** installable plugins that extend equipment support or add sequencer instructions/workflows
- **Customizable UI:** theming, configurable imaging-tab layout
- **Troubleshooting/diagnostics tooling** and logging

### 6.2 AstroFiler Feature Inventory

Compiled from [github.com/gordtulloch/astrofiler-gui](https://github.com/gordtulloch/astrofiler-gui); used as the functional baseline for the new `LIB` domain in Section 8, and for the extension of the `CAL` domain to cover calibration-frame application.

- **Repository management:** recursive directory scanning/ingestion, SHA-256 hash-based duplicate detection and removal, automatic file rename/organization by metadata, batch processing with progress tracking
- **Cataloging:** FITS header extraction, automatic object identification and session tracking, organization by target/date/instrument/camera
- **Smart-telescope integration:** SEESTAR and StellarMate via SMB/CIFS, DWARF via FTP (experimental), iTelescope via FTPS, with network discovery and selective remote download
- **Calibration processing:** automated master bias/dark/flat frame creation, intelligent session grouping/linking by camera/binning/temperature, one-click light-frame calibration
- **Quality analysis:** SEP-based star detection and quality metrics (FWHM, HFR, eccentricity, SNR)
- **Cloud sync:** bidirectional Google Cloud Storage sync with MD5-based dedup and multiple sync profiles, including command-line automation
- **Statistics:** repository statistics dashboard, session management/analysis tools
- **Command-line utilities:** standalone scripts exposing specific batch functions independent of the GUI — e.g. `LoadRepo` (repository scan/ingest) and `Calibrate` (master-frame creation/application) — for scheduled/automated execution (Section 8, `EXT-140`/`LIB-130`)

### 6.3 VSTarget Feature Inventory — Moved

VSTarget's feature inventory, and the rest of its scope/requirements/design documentation, moved to its own document chain: [`docs/plugins/vstarget/PSD.md`](plugins/vstarget/PSD.md) Section 6. It is no longer decomposed into this document's `VST`/`VST-AN` domains (Section 8) — VSTarget is a first-party plugin against the generic Plugin Framework (`PLUG`, Section 8), documented as a plugin, not as a core-embedded merge. This section number is kept as a placeholder (rather than renumbering 6.4 onward) so the many existing cross-references to Sections 6.4–6.9 elsewhere in this document stay valid.

### 6.4 Obsy Feature Inventory (ported elements only)

Compiled from [github.com/gordtulloch/obsy](https://github.com/gordtulloch/obsy), now GPL-3.0 (Section 11, C6). Obsy as a whole is retired (Section 2); only the elements below are ported into Galileo's `SKY`/`FRAME` domains, per the author's guidance that its FITS-management functionality is superseded by AstroFiler and its scheduling was too cursory to carry forward.

- **Target visibility computation:** rise/transit/set time calculation against a configured observer location and timezone — Obsy's own version of this used `astroplan`, but Galileo's is an independent astropy-only implementation (`galileo.planning.visibility.rise_transit_set`, reusing the same `AltAz` altitude curve `altitude_chart()` already computes) rather than a direct port of Obsy's `astroplan`-based code, since adding `astroplan` as a real dependency was explicitly declined (untested on macOS/Linux/RPi5, `NFR-PORT` still open, and `astroplan`'s own rise/set functions are themselves thin wrappers over the same astropy transforms this reuses directly)
- **Sky-survey thumbnails:** automatic DSS (Digitized Sky Survey, via the CDS hips2fits cutout service) cutout-image fetch and thumbnail generation per target

This logic is the engine behind Galileo's **Targets** screen (`SKY`), whose look and feel is informed by Telescopius (Section 6.9) as a best-of-breed reference for this kind of target-planning UI, adjusted to Galileo's own UI rather than copied as-is. The Targets screen is not a bare port, however: Section 8's `SKY` row (offline object database, SIMBAD fallback, size-aware survey-thumbnail cropping, Telescopius augmentation) describes capability Obsy itself never had, layered on top of the ported rise/transit/set and thumbnail logic above.

### 6.5 AstroLlama Tools — Selectively Harvested

Compiled from [github.com/gordtulloch/AstroLlama/tree/main/mcp_server/tools](https://github.com/gordtulloch/AstroLlama/tree/main/mcp_server/tools). AstroLlama is a GPL-3.0 AI-assistant project; only the astronomy-device/imaging-specific tool functions below are harvested, each folded into an existing Galileo domain rather than forming a new one.

| AstroLlama tool file | Harvested into | What it contributes |
|---|---|---|
| `telescope_interface_tool.py` + `telescope_registry_tool.py` | `ARCH`, `PROF` | A working, proven precedent for exactly Galileo's own design: one platform-agnostic control interface routed to an INDI or Alpaca backend based on an active profile held in a registry. Validates the `ARCH`/`PROF` approach rather than just informing it. |
| `alpaca_device_discovery_tool.py`, `indi_device_discovery_tool.py` | `ARCH` | Working device-discovery implementations for `ARCH-050`. |
| `alpaca_telescope_imaging_tool.py` | `EQP` (camera/mount), `PLT` | Proven slew/capture/plate-solve-verify/park orchestration over Alpaca, including FITS output with full metadata — a direct implementation reference for the Alpaca adapter and the `PLT-040` solve-and-center workflow. |
| `astap_plate_solve_tool.py` | `PLT` | A minimal, working ASTAP subprocess adapter (binary resolution, RA/Dec parsing, solved-heuristic, timeout handling, path-traversal-safe filename validation) — a direct implementation reference for `PLT-010`. |
| `variable_comparison_stars_tool.py`, `generate_aavso_map_tool.py` | VSTarget plugin's `VST-AN` (`docs/plugins/vstarget/`) | AAVSO comparison-star photometry retrieval (reinforces `VST-AN-040`) and AAVSO finder-chart generation — the latter is a genuinely new capability, added as `VST-AN-090`. Not a core domain — documented in the plugin's own SDD, not this document. |
| `get_latlong_tool.py` | `SKY` | Geocoding (location name → lat/long/timezone) via the Open-Meteo API — a new capability, added as `SKY-090`. |
| `get_weather_tool.py` | `SAFE` | Internet weather-forecast lookup via Open-Meteo — a new, explicitly non-authoritative planning aid, added as `SAFE-050`; it must never substitute for a connected safety-monitor device in automated abort decisions (`SAFE-010`). |
| `generate_constellation_map_tool.py`, `generate_map_tool.py` | `FRAME` | Sky-map/constellation rendering reference for `FRAME-060`. |

**Explicitly excluded:** `arxiv_search_tool.py`, `news_reader.py`, `openwebui_adapter.py`, `orchestrator.py`, `scrape.py`, `thinking-toggle.py`, `websearch.py`, `wiki_search_tool.py`, `wolfram.py`, `youtube_search_tool.py`, and the `untested/` directory — these are generic AI-assistant/chat-orchestration tools with no astronomy-device relevance to Galileo.

### 6.6 KStars/EKOS Comparative Feature Review

A gap review against [KStars/EKOS](https://kstars.kde.org/) — the other major open-source, cross-platform (and INDI-native) imaging suite, whose UX Galileo is not directly modeling but whose feature coverage is a useful completeness check — compiled from the [KStars Handbook](https://kstars-docs.kde.org/en/user_manual/ekos.html) and [Jasem Mutlaq's Ekosphere release-notes blog](https://knro.blogspot.com/). Findings adopted directly into scope:

| KStars/EKOS capability | Gap in prior Galileo scope | Resolution |
|---|---|---|
| Live, rendered planetarium sky map (100M+ stars, DSOs, solar system, comets/asteroids/satellites; pan/zoom/click-identify/slew-to-here) | Galileo only had the catalog-style Sky Atlas (`SKY`) and FOV-preview Framing Assistant (`FRAME`) — neither is a live rendered sky view | New `SKYMAP` domain (Section 8), user-requested |
| Optical Trains (devices modeled as an ordered chain: telescope→reducer→rotator→filter wheel→camera, not flat per-device settings) | `PROF` modeled equipment as a flat device list | `PROF-070`–`090` added; this refines, not just extends, the `PROF` data model (Section 8) |
| Multi-camera/multi-rig parallel capture across optical trains on one mount | Not addressed | `SEQ-090` added (P3 — advanced/minority use case) |
| Watchdog: independent heartbeat-timeout that parks mount + closes dome if the *software* hangs/crashes/loses network, distinct from weather-triggered abort | `SAFE` only covered device-reported unsafe conditions | `SAFE-060` added; implementation reuses INDI's existing `indi_watchdog` driver rather than reimplementing (SDD Section 4.16) |
| Aberration Inspector (per-region tilt/coma diagnostics) | Not addressed | `FOC-080` added (P2) |
| Non-sidereal tracking (comets/asteroids/satellites, custom rate) | `EQP-MNT` implied sidereal targets only | `EQP-MNT-040` added (P2) |
| Raw INDI/Alpaca device-property control panel for advanced diagnostics | Not addressed | `EQP-060` added (P2) |
| The Scheduler: mature multi-night/multi-target job queue with a greedy scheduling algorithm and altitude/moon/twilight/horizon/weather constraints | Directly conflicted with the earlier decision (Section 5) to exclude observatory scheduling, made on the basis of Obsy's scheduling being "only cursory" — EKOS's is not cursory | **Resolved: added in full v1 scope.** New `SCHED` domain (Section 8, G12); supersedes the earlier non-goal (Section 5) |
| Built-in native autoguiding; experimental AI-predictive-guiding and an MCP server for LLM control (KStars 3.8.4, Aug 2026) | N/A | Native guiding remains a deliberate non-goal (Section 5, external guider only — unchanged). AI-guiding/MCP-control are experimental even in EKOS itself; noted in Section 17 as a future consideration, not v1 scope |
| Multiple instruments on one mount: EKOS supports this via a lead/follower model — one optical train's job sets the target/criteria, others follow, with slew/dither/align/meridian-flip synchronized across all trains | `PROF-080` (multiple optical trains) existed but lacked the concrete coordination mechanism | **Resolved: adopted directly.** `SEQ-090` now specifies the lead/follower model explicitly (SDD `galileo.sequencer.basic`, Section 4.6) |
| Multiple independent telescopes/mounts in one observatory: **EKOS's own Scheduler explicitly does not support this** — its community-documented workaround is running separate KStars/EKOS application instances, one per mount, each against its own INDI server on a different port. There is no single-instance multi-mount scheduling to copy | Not addressed in prior scope; genuinely exceeds what EKOS itself does, rather than a gap versus it | **Resolved: Galileo goes beyond EKOS here**, deliberately. A single Galileo instance manages multiple mounts ("Piers") grouped into an "Observatory," with `SCHED` coordinating across them and shared resources (dome/roof, safety monitor) scoped at the Observatory or Pier level. New `OBS` domain (Section 8, G16) |

### 6.7 MCP Feature Inventory

Compiled from [github.com/gordtulloch/MCP](https://github.com/gordtulloch/MCP), GPL-3.0 (Section 11, C8) — ported directly, not reimplemented clean-room.

- **Rain detection (MCP):** Hydreon RG-11 rain sensor via serial/Arduino, polled with a status query, boolean raining/dry result.
- **Aurora estimate (MCP):** NOAA Space Weather Prediction Center OVATION and Planetary K-index APIs; returns current Kp index and a boolean threshold-exceeded flag for a configured location.
- **Smoke estimate (MCP):** NOAA Hazard Mapping System smoke-polygon KML data; returns a heavy/medium/light/clear/no-data rating for a configured location.
- **Other MCP modules not harvested:** EKOS D-Bus integration, MQTT messaging, live-stacking/post-processing hooks, dome/scope client orchestration — these are EKOS-specific automation, not applicable to Galileo's own architecture.

### 6.8 Reference Test Environment

Galileo's test environment is a real, physical multi-Pier Observatory (`OBS`, Section 8), not a hypothetical one — this directly grounds the `OBS` domain's design rather than leaving it purely speculative:

- **Enclosure:** a roll-off-roof shed, controlled via [indi-rolloffino](https://github.com/wtnate/indi-rolloffino) (an Arduino-based INDI roof-controller driver) — the `DOME` domain's roof-control requirements (`DOME-010`–`030`) are validated against this specific driver, and since the roof covers both Piers, it is configured Observatory-scoped (`OBS-050`).
- **Weather station:** [indi-argentweather](https://github.com/rlancaste/indi-argentweather), an INDI weather-device driver — the `EQP-WX-010`/`SAFE` Tier 1 weather input, Observatory-scoped (`OBS-030`) since one station serves the whole enclosure.
- **Rain monitor:** [indi-hydreon](https://github.com/mconway67/indi-hydreon) for the Hydreon RG-11 rain sensor — the concrete Tier 1 device behind `SAFE-070`.
- **Two Piers:** a Seestar S30 and a Seestar S30 Pro, both connected via **ASCOM Alpaca**, not INDI — confirming both device-abstraction backends need to work side by side in one Observatory (`ARCH-020`), and giving `OBS`'s multi-Pier design a concrete two-Pier validation case with genuinely independent mounts (each Seestar is a self-contained smart telescope, not a shared-mount multi-train rig).

This environment is referenced from Section 7 (Raspberry Pi 5/Debian target platform) as the author's own deployment target.

### 6.9 Telescopius API — Integration Points (`SKY`)

Compiled from [telescopius.com/pages/api](https://telescopius.com/pages/api) and [api.telescopius.com](https://api.telescopius.com/), plus staff/community statements in the [Telescopius forum's "Generating API Key" thread](https://forum.telescopius.com/t/generating-api-key/319). Reviewed as a candidate online augmentation source for the Targets screen (`SKY`), not as a replacement for the offline object database or SIMBAD fallback below — the review's findings shape how it is scoped in Section 8, not just whether it is included:

- **Access model:** the official REST API is gated to Telescopius Patrons/Sponsors — as of the forum thread (February 2025) there is no free tier — and requires a per-user API key generated from the user's own Telescopius account settings. Galileo cannot bundle or proxy access; this is necessarily a **bring-your-own-API-key** integration, entered by the user in Options, the same pattern as any other user-supplied credential (e.g. AAVSO API access in `VST`).
- **Maturity:** the public API is young relative to Telescopius itself — it launched in 2023 with only a "quote of the day" endpoint, and staff describe target search/suggestion endpoints as roadmap items rather than a stable, fully-documented surface at review time. Scope here is therefore an **integration point, not a firm contract**: Galileo should treat whatever object-search/target-suggestion endpoints exist as an optional enrichment source that degrades gracefully (Section 8) rather than a dependency any core Targets-screen behavior relies on.
- **Integration points identified:** (1) object/target search — supplementing a local/SIMBAD lookup with Telescopius's own catalog and community target-suggestion data when a key is configured and the endpoint is available; (2) observing/target-list import — pulling a user's existing Telescopius observing list into a Galileo Targets session rather than requiring manual re-entry. Both are additive to the internal database (Section 8, `SKY`), not required to populate it.
- **Not adopted at this review:** deeper session-planning or eyepiece/FOV-calculator-style endpoints, since Galileo already has its own Framing Assistant (`FRAME`) and Sky Atlas/Framing pipeline covering that ground; re-deriving it from a third-party API would duplicate rather than augment existing scope.

## 7. Target Platforms and Distribution

| Platform | Requirement |
|---|---|
| Windows | Windows 10/11 (x64), self-contained installer (MSI or equivalent), built via the same Nuitka/CI pipeline as the other platforms (SDD Section 2.4) |
| macOS | Current and prior macOS major version (Apple Silicon + Intel), signed/notarized `.dmg` or `.pkg` installer |
| Linux | Major distributions used by the astro community (Debian/Ubuntu, Fedora, Arch) via AppImage/Flatpak/native packages, since INDI itself is Linux-native |
| Linux (ARM SBC) | Raspberry Pi 5-class single-board computers running Debian, as a first-class supported target, not just a theoretical one — see Section 6.8 for the author's own reference deployment on this class of hardware |

Installers for all platforms are a first-class deliverable, not an afterthought — this is a primary differentiator versus Windows-only tools such as NINA. Every platform ships a single, self-contained artifact the user can download and run directly, with no separate tool or manual dependency setup required; AstroFiler's own installation scripts (Section 2) are harvested as implementation inspiration for the build pipeline itself (auto-update behavior, desktop integration), not as an external tool Galileo depends on at install time.

## 8. Functional Requirement Domains (Scope-Level)

Each domain below will decompose into individually numbered SRS requirements under the given ID prefix. "Priority" indicates intended release phase, subject to refinement during SRS authoring.

| ID Prefix | Domain | Scope Description | Priority |
|---|---|---|---|
| `ARCH` | Protocol & Device Abstraction Layer | Unified device abstraction supporting INDI (native protocol, INDI server/client) and ASCOM Alpaca (REST/JSON, device discovery) as interchangeable backends per device; a device-capability model so UI adapts to what a connected device actually supports | MVP |
| `EQP` | Equipment Control | Connect/configure/monitor: Camera, Mount/Telescope, Filter Wheel, Focuser, Rotator, Guider, Switch/Power, Flat Panel, Weather Device, Dome, Safety Monitor | MVP |
| `PROF` | Equipment Profiles (Piers) | Save/load named equipment configurations, each a **Pier**: one mount plus one or more **optical trains** (ordered device chains from telescope/lens through reducer/rotator/filter wheel to camera — KStars/EKOS-informed, Section 6.6), not a flat device list; each Pier's optical tubes are defined on an Equipment "Optics" page (name, focal length, aperture, optical system, image alignment) with the Pier's other devices associated to them; multi-rig support. Multiple Piers can be grouped into an `OBS` Observatory | MVP |
| `IMG` | Imaging Tab | Live capture, histogram display, auto-stretch preview, per-exposure statistics, star detection overlay; a **Framing…** button opens the Framing Assistant (`FRAME`, Section 8.3) against the currently selected camera/optical train for immediate-imaging use, including defining and running a mosaic capture directly from this tab | MVP |
| `SES` | Sessions (formerly "Sequencer"/`SEQ`/`SEQ-ADV` — the earlier basic/advanced split is retired: there is no separate "advanced" surface, one Sessions screen and one palette cover both) | Sessions are planned **per Pier** (`PROF`): the Sessions screen shows the active Pier's own session set, not a global one, so two Piers in the same Observatory (`OBS`) each author and hold an independent set of sessions. The primary navigation item is the **Sessions** screen (renamed from "Sequence" to align with AstroFiler's session terminology — Glossary, `LIB`). One or more sessions are shown as independently scrollable, bounded regions on the screen; each region carries small Save / Save as Template / Load from Template / Schedule / Delete controls. A session's Schedule control submits it to `SCHED`, which schedules it (and sessions from any other Pier) as a queued job — a session otherwise sits inert on screen, so building one has no effect until Schedule is used. A session is built by dragging action blocks — a **Target** block (set active target + slew, inserted automatically when a target is chosen on the Targets/Sky Atlas screen, or via a new "Add Session" context-menu item), exposure/filter/binning blocks, and nested instruction/condition/trigger blocks (loop-for-N, loop-until-time, wait-for-altitude, Autofocus, Plate Solve, autofocus-on-trigger, meridian-flip-on-trigger) — from a single right-hand palette into the region, insertable before/after/between existing blocks and freely reorderable afterward; reusable templates via each region's Save as Template control; instruction set open to plugin extension. Block-ordering integrity rules are enforced when a block is inserted or a session is run (e.g., a Solve block requires a preceding Target/slew block) | MVP/P2 (mixed — see SRS: linear target/exposure/autofocus/solve authoring is MVP, the fuller condition/trigger/template set is P2) |
| `SKY` | Sky Atlas / Targets | Presented as the **Targets** screen, wiring in and augmenting Obsy's visibility/thumbnail logic (Section 6.4), look-and-feel informed by a reference to Telescopius as best of breed, adjusted to Galileo's own UI. An **internal, offline object database** (bundled/cached, same pattern as the synthetic 10K-object catalog already used for offline-capable testing) is the primary search/filter/altitude-visibility source, so the Targets screen works fully disconnected; a **SIMBAD lookup is a fallback**, used only when a user searches for a specific object the internal database doesn't resolve. Sky-survey thumbnails are ported directly from Obsy (Section 6.4) but the cutout is no longer a fixed size — the extracted segment's scale is derived from the object's own angular size (from the database/SIMBAD result) so a large nebula and a small planetary aren't framed identically. Horizon obstruction definitions. **Telescopius API** (Section 6.9) is an optional, user-key-gated online augmentation layered on top — object search/suggestion enrichment and observing-list import when configured — never a dependency of the offline-first path above | MVP/P2 (mixed — see SRS: offline database, SIMBAD fallback, and size-aware thumbnails are MVP; Telescopius augmentation is P2, gated on the API's own maturity per Section 6.9) |
| `FRAME` | Framing Assistant | **Not a top-level navigation item** — invoked contextually (Section 8.3) from a Framing… button on the Imaging tab (`IMG`) or from an Image block on the Sessions screen (`SES`, Section 8.2), never as its own primary section. Loads a sky-survey image (cached copy used when offline), overlays a box showing the current camera/optical train's field size and rotation, offers a Compare Cameras view scaled to the largest field size among every camera available across the Observatory (`OBS`), supports rotating the box always — moving a connected rotator (`EQP`) to match, or, with none connected, covering the tilted box with an automatic mosaic instead of leaving rotation unavailable — and supports expanding the box into a mosaic grid with configurable pane overlap; sky-survey thumbnail logic ported directly from Obsy (Section 6.4) | MVP/P2 (mixed — see SRS: single-frame framing from either entry point is MVP, Compare Cameras and mosaic capture are P2) |
| `SKYMAP` | Interactive Star Map / Planetarium (KStars/EKOS-informed, Section 6.6) | Live, rendered, pan/zoom sky view (stars, DSOs, solar system, comets/asteroids/satellites), click-to-identify, double-click-to-track, live FOV/pointing overlay, slew-to-clicked-location. A third, distinct sky-related panel alongside the catalog-based `SKY` and the FOV-preview `FRAME` | MVP/P2 (mixed — see SRS) |
| `SCHED` | Observatory Scheduler (KStars/EKOS-informed, Section 6.6) | Prioritized multi-night/multi-target job queue, each job a `SES` session submitted from its owning Pier's Sessions screen (Section 8.1) together with the target and constraints authored into it; altitude/moon-separation/twilight/horizon constraints; startup/completion conditions; weather-gated startup and pause (via `SAFE`); priority-based preemption; multi-night progress tracking so completed frames aren't recaptured; coordinates across Piers within an `OBS` Observatory, each of which submits from its own independent session set | MVP |
| `OBS` | Multi-Mount Observatory Management | Group multiple Piers (`PROF`) into a named Observatory; run independent, concurrent sequences/scheduler jobs across different Piers targeting different objects; scope shared resources (dome/roof, safety monitor) at the Observatory or Pier level; multi-Pier status dashboard. Exceeds EKOS's own single-mount-per-instance model (Section 6.6, G16). The Observatory record also carries the operator's own **contact details** — email address, phone/SMS number, and which of those `NOTIF` should use (email, text, or both) — since notification delivery is scoped to the person running the Observatory, not to an individual Pier | P2 |
| `CAL` | Calibration / Flat Wizard | Automated flat-frame capture with brightness/exposure targeting; dark/bias frame capture management (acquisition-time capture only — see `LIB` for master-frame creation and application) | MVP |
| `FOC` | Autofocus | HFR-based star measurement and curve-fit autofocus routine; configurable trigger conditions (temperature delta, time interval, filter change, HFR drift) | MVP |
| `PLT` | Plate Solving | Integration with external/local solvers for pointing verification and precise target centering; blind and near solves | MVP |
| `MFLIP` | Meridian Flip | Automated detection and execution of meridian flip mid-sequence, with re-centering/re-focus/re-guide-start follow-up | Phase 2 |
| `GUIDE` | Guiding Integration | Control interface to external autoguiders (e.g., PHD2-equivalent protocol); dither-between-exposure coordination | MVP |
| `DOME` | Dome Control | Dome slaving to mount azimuth; shutter open/close automation; sync with meridian flip and park events | Phase 2 |
| `SAFE` | Safety & Weather Monitoring | Ingest weather-device/safety-monitor state; automated safe-park/abort-sequence response to unsafe conditions | Phase 2 |
| `HIST` | Session History & Statistics | Per-session logging of HFR, star count, guiding RMS, and other quality metrics over time, with review UI | Phase 2 |
| `META` | Image Metadata | FITS-only file output (including tile-compressed FITS) with comprehensive header keyword population matching community tooling expectations | MVP |
| `NOTIF` | Notifications | Configurable alerts (in-app, plus external delivery via **email and/or text message/SMS**) on sequence events, errors, and safety triggers; external delivery uses the contact details and channel preference (email, text, or both) configured on the Observatory (`OBS`) the alert's Pier belongs to | Phase 3 |
| `PLUG` | Plugin Framework | Documented extension API for adding device drivers, session actions/instructions/conditions/triggers (`SES`), and UI panels (at the primary or secondary navigation level) without modifying core. Distinguishes first-party pre-loaded plugins (enable/disable only, functionally equivalent to core when on) from third-party repository-installed ones. Every first-party plugin — VSTarget (`docs/plugins/vstarget/`) is the first and, currently, only one — is specified in its own PSD→SRS→SDD→RTM document chain under `docs/plugins/<plugin-name>/`, mirroring this document's own structure at plugin scope, rather than being decomposed into core domains; this is deliberate, not a documentation-organization convenience — a plugin whose requirements can't be expressed purely as a consumer of `PLUG`'s extension points and other core requirements-by-reference is a sign `PLUG` itself is under-specified, not a reason to special-case it here | MVP (loader); Phase 2 (third-party marketplace) |
| `UI` | Customization & Theming | Configurable color themes and imaging-tab layout, matching the flexibility users of modern imaging suites expect | Phase 2 |
| `LOG` | Diagnostics & Logging | A runtime logging service capturing all application/session log output (every module, not just curated diagnostic events) to a datestamped log file under the application's own directory, reset at the start of every run; in-app log viewer with severity filtering, including a live scrolling tail visible on every Equipment device screen; crash reporting to aid troubleshooting across all supported platforms | MVP |
| `LIB` | Image Library & Repository Management (merged from AstroFiler) | Cross-session FITS/XISF (XISF converted best-effort to FITS on ingest) repository scanning, cataloging, hash-based deduplication, metadata-driven auto-organization, smart-telescope/network ingestion, master calibration-frame creation and application, quality-metric computation, cloud sync; live auto-registration of frames as they're acquired, with sequence-step-scoped session containers; CLI utilities for batch actions | MVP |

### 8.1 Sessions Screen — Scope Note (`SES`)

The screen previously referred to in this document as "Sequence" is the **Sessions** screen, reusing AstroFiler's own term for a related group of output artifacts (calibration frames plus lights) rather than introducing a second, competing vocabulary (Section 2, G7). That definition is extended, not replaced: a session is now also the ordered set of actions — slew-to-target, autofocus, plate-solve, expose, and so on — that produces those artifacts, authored visually rather than as a flat exposure list.

There is no separate "advanced" sequencer any more: the earlier `SEQ` (basic, linear) / `SEQ-ADV` (nested instruction/condition/trigger) split has been retired into the single `SES` domain above. One Sessions screen and one action palette cover both what used to be a flat exposure list and what used to require the advanced sequencer — a session can be as simple as Target + Exposure blocks or as elaborate as nested loop/wait/trigger blocks, with no separate screen or mode to switch into. The domain's MVP/P2 split (Section 8 table) now falls *within* `SES` rather than between two domains: linear target/exposure/autofocus/solve authoring is MVP, the fuller condition/trigger/template set is P2 — a distinction for SRS numbering, not a distinction the user sees as two surfaces.

At scope level, the Sessions screen supports:

- **Per-Pier session ownership**: a session belongs to exactly one Pier, and the Sessions screen displays only the currently-selected Pier's sessions — switching Piers switches the whole set of regions shown, the same way switching Piers already switches which equipment/optical-train configuration (`PROF`) is active. This is what lets `SCHED` (below) know which Pier a submitted session runs against without the session needing to say so itself, and it's also what tells a session which devices/filters/optical trains it has available to offer through its action blocks (Section 8.2) in the first place.
- **Sessions are specifications until scheduled**: authoring a session — even a fully built-out one — has no side effect on its own; a session only becomes a queued job when its region's **Schedule** control is used, which submits it to `SCHED` (target, Pier, constraints) as a scheduled job rather than starting immediate execution from the Sessions screen itself. This mirrors `SCHED`'s existing scope-level description (Section 8) of each job referencing a `SES` session and a Pier. Because authoring is inert until Schedule is clicked, a user is free to build out as many session regions as they like — draft, compare, or hold several in reserve — without any of them running or queuing prematurely.
- **A scheduled session locks for editing**: once Schedule is used, the region becomes read-only (blocks can no longer be dragged, reordered, or edited) and its boundary is drawn in red to distinguish a live, queued session at a glance from the draft (default-boundary) ones around it. The region's Schedule control itself becomes **Deschedule** in this state; using it withdraws the session's job from `SCHED` and returns the region to its normal boundary and editable state. A job that instead runs to completion on its own is a different outcome, not the same one reached a different way: the session is **deleted**, not handed back as an editable draft — it has nothing left to do, and leaving a "finished" region cluttering the screen would only invite it to be scheduled again by mistake. This is the region-level counterpart to whatever run-state handling `SCHED`/`SES` already need for a job that's actively executing versus merely queued — SRS/SDD-level detail, not scoped further here.
- **Multiple concurrent sessions**, each an independently bounded, vertically-scrollable region on the screen, with its own Save, Save as Template, Load from Template, Schedule, and Delete controls.
- **A single right-hand action palette** (Target, Image, Autofocus, Plate Solve, and the nested condition/trigger set — full catalog in Section 8.2) from which blocks are dragged into a session region, insertable before, after, or between existing blocks, and freely reorderable within the region afterward.
- **Target-driven session creation**: choosing a target on the Targets/Sky Atlas screen inserts a new session pre-populated with a `Target: <name>` block (set active target and slew); the "Add Session" context-menu item creates an equivalent empty session for manual authoring.
- **Templates, target-generic by design**: Save as Template writes a session's blocks to a template store with its Target block stored as a generic placeholder rather than a specific target — a template captures a repeatable *procedure* (e.g. "autofocus, then 20×300s L, 10×300s each RGB"), not a one-off plan tied to the target it happened to be authored against. Load from Template requires the session region to already have a concrete Target block (added first, the same way any session gets one — via the Targets/Sky Atlas screen or "Add Session"); loading substitutes the template's placeholder with that existing Target block and appends the template's remaining blocks in their saved order, leaving the rest of the region's blocks (if any) untouched.
- **Ordering-integrity rules**, enforced by the domain core rather than left to the user to get right (e.g., a Solve block requires a preceding Target/slew block) — the concrete rule set and enforcement point (on insert vs. on run) are SRS/SDD-level detail, not scoped further here.

### 8.2 Initial Block Catalog (`SES`)

The action palette (Section 8.1) is open to plugin extension (`PLUG`) the same way `SEQ-ADV`'s instruction/condition/trigger set always was, but v1 needs a concrete starting catalog, not just the extension mechanism. Each block below mirrors an existing MVP-or-later domain from Section 8 rather than inventing new behavior — a block is a Sessions-screen *front end* onto a capability that domain already specifies; the block itself adds no new capability, only the ability to sequence it. Priority follows the block's underlying domain, consistent with the "linear authoring is MVP, condition/trigger/structural wrapping is P2" split already established for `SES` (Section 8.1).

**Action blocks** — unconditional device/workflow steps a session executes in order:

| Block | Mirrors / Domain | What it holds | Priority |
|---|---|---|---|
| Target | `SKY`/`EQP` (mount) | Target identity, set active target, slew | MVP |
| Image | `IMG`/`EQP` (camera), `META`, `FRAME` | The same capture parameters as the Imaging tab's immediate-capture controls — exposure time, count, filter, binning, gain/offset, frame type (Light/Dark/Bias/Flat) — so a session step and a manual Imaging-tab exposure share one settings model rather than two. Carries its own Framing… button opening the Framing Assistant (Section 8.3) to set the block's target frame box and, optionally, a mosaic grid; when a mosaic is defined, the block's execution follows the mosaic capture model (Section 8.3) instead of single-target capture | MVP (single frame); P2 (mosaic) |
| Filter Change | `EQP` (filter wheel) | Target filter-wheel position, with no exposure taken — used ahead of a per-filter Autofocus or Image block | MVP |
| Cool Camera / Warm Camera | `EQP` (camera) | Target CCD setpoint temperature and a wait-for-stabilization condition | MVP |
| Autofocus | `FOC` | Filter to focus on (defaults to current), pass/fail handling | MVP |
| Plate Solve | `PLT` | Solve-and-center against the session's current Target | MVP |
| Guide Start / Guide Stop | `GUIDE` | Start (optionally calibrate) or stop the external guider | MVP |
| Dither | `GUIDE` | Trigger one guider dither; also available as an inline "dither every N frames" option on the Image block itself rather than forcing a block per exposure | MVP |
| Flat Capture | `CAL` | Automated flat-frame capture with brightness/exposure targeting | MVP |
| Park Mount / Unpark Mount | `EQP` (mount) | Park/unpark, typically session-closing or -opening | MVP |
| Meridian Flip | `MFLIP` | Manually-placed flip-and-recover (re-center/re-focus/re-guide-start) step | Phase 2 |
| Dome Open / Close / Sync | `DOME` | Explicit dome/shutter action or mount-slaved sync | Phase 2 |
| Notification | `NOTIF` | Send an alert at this point in the session via the owning Observatory's configured email/text contact details | Phase 3 |

**Condition/trigger/structural blocks** — wrap or gate other blocks rather than acting themselves; this is the set that used to require the separate "advanced" sequencer (Section 8.1):

| Block | Mirrors / Domain | What it holds | Priority |
|---|---|---|---|
| Loop For N | `SES` (structural) | Repeat its contained blocks a fixed number of times | Phase 2 |
| Loop Until Time | `SES` (structural) | Repeat its contained blocks until a clock time | Phase 2 |
| Wait Until Time | `SES` (structural) | Pause the session until a clock time (e.g. astronomical dusk) | Phase 2 |
| Wait For Altitude | `SES` (structural) | Pause until the current target (or the sun, for a dusk/dawn gate) crosses an altitude threshold | Phase 2 |
| Autofocus-on-Trigger | `FOC`, `SES` (structural) | Wraps an Autofocus block with a trigger condition (temperature delta, time interval, filter change, HFR drift) instead of running it unconditionally | Phase 2 |
| Meridian-Flip-on-Trigger | `MFLIP`, `SES` (structural) | Wraps a Meridian Flip block to fire automatically on mount-reported meridian proximity, rather than needing manual placement | Phase 2 |
| Wait-for-Safe / Abort-if-Unsafe | `SAFE`, `SES` (structural) | Gates on safety-monitor state rather than a device action of its own | Phase 2 |

This catalog is the v1 starting point, not a ceiling — SRS authoring may split or rename individual blocks (e.g. Cool/Warm Camera as one block with a signed setpoint vs. two blocks) as each domain's requirements are numbered.

### 8.3 Framing Assistant — Invocation & Mosaic Capture Model (`FRAME`)

The Framing Assistant is deliberately **not** a primary-navigation section (unlike `SKY`'s Targets screen or `SES`'s Sessions screen) — it is a tool invoked in context, from exactly two entry points, and closed back into whichever one opened it:

- **The Imaging tab's Framing… button** (`IMG`), for immediate-imaging use: framing/mosaic decisions made here apply to a manual capture run started from the Imaging tab itself.
- **A Session Image block's own Framing… button** (`SES`, Section 8.2), for a session step: framing/mosaic decisions made here are stored with that block and apply when the session runs it.

Both entry points open the same Framing Assistant and share the same underlying mosaic-definition model — there is one design, not two — but each keeps its own framing/mosaic state (the Imaging tab's current immediate-capture setup is independent of any given session's Image block).

**Framing view:**

- Loads a sky-survey image for the current target area, using a cached copy when offline (consistent with `FRAME-020`'s existing offline/cached rendering requirement).
- Overlays a box showing the field size and rotation of the **currently selected camera/optical train** (`PROF`).
- A **Compare Cameras** control overlays a box for every camera available across every Pier in the current Observatory (`OBS`), not just the active one, with the survey image auto-scaled to the largest field size among them — a planning aid for choosing which rig best suits a target before committing to it.
- The box can be **rotated**, when the active optical train has a rotator equipped (`EQP-ROT`); with no rotator, rotation is unavailable rather than offered and silently ignored.
- The box can be **expanded into a mosaic grid** (N×M panes), with a pane-overlap percentage configurable on the Imaging setup screen (`IMG`, alongside the existing sample-format setting) — one overlap setting shared by both entry points, not duplicated per-session.

**Mosaic capture execution model**, identical whether started from the Imaging tab or from a session's Image block:

- The telescope slews to the center of the **first** pane and captures **one** exposure, then slews to the center of the **second** pane and captures one exposure, and so on through every pane — a single pass across the whole mosaic, not one pane completed before the next begins.
- Where more than one exposure per pane is configured, the system repeats the same pass again from the first pane rather than taking all of a pane's exposures back-to-back: pane 1/exposure 1, pane 2/exposure 1, …, pane N/exposure 1, pane 1/exposure 2, pane 2/exposure 2, and so on until every pane has its configured exposure count.
- This re-slew between every exposure is deliberate: it is what dithers a mosaic pane's frames against each other (a slightly different pointing solution each visit), rather than requiring — or duplicating — a separate guider-dither command between exposures of an unchanged target (`GUIDE`'s existing dither capability is orthogonal and still applies to guiding itself, not a substitute for this).

This is a materially different execution model from a mosaic authored as separate per-panel targets/sessions (the model implied by `FRAME-050`'s earlier "send each mosaic panel to the sequencer as a target" wording) — one Image block or one Imaging-tab run now owns the whole mosaic and its interleaved capture order internally, rather than the mosaic being decomposed into independent targets upstream of capture.

## 9. Non-Functional Requirement Domains

| ID Prefix | Domain | Scope Description |
|---|---|---|
| `NFR-PERF` | Performance | Responsive UI during large-format FITS capture/display; acceptable memory footprint for multi-hour sessions |
| `NFR-REL` | Reliability | Must tolerate transient device/network disconnects (INDI/Alpaca) during unattended overnight operation without corrupting a running sequence |
| `NFR-PORT` | Portability | Single codebase targeting Windows, macOS, and Linux with equivalent feature availability; no OS-exclusive features without a documented fallback |
| `NFR-EXT` | Extensibility | Plugin architecture (see `PLUG`) must not require core recompilation for new device types or sequencer instructions |
| `NFR-USE` | Usability | Guided/wizard-style workflows for first-time equipment setup and flat capture, matching the approachability of well-regarded modern imaging suites |
| `NFR-I18N` | Localization | UI text externalized for translation from the outset, even if only English ships in v1 |
| `NFR-SEC` | Security | Safe handling of network-exposed INDI server / Alpaca REST endpoints, including remote-observatory (WAN-exposed) use cases |
| `NFR-OFFLINE` | Offline Operation | Sky Atlas and Framing Assistant must support cached/offline catalogs for remote sites without reliable internet |
| `NFR-INSTALL` | Installability | One-step installers per platform (Section 7); no manual dependency installation for end users |

## 10. Stakeholders and Primary Personas

| Persona | Description | Primary Interests |
|---|---|---|
| Visual/DSO Astrophotographer (primary) | Hobbyist imaging deep-sky targets overnight, unattended | Guided sequencing, autofocus, plate solving, reliability |
| Remote/Roll-off-Roof Observatory Operator | Runs equipment unattended from a remote location | Dome/safety integration, remote access, robustness to disconnects |
| Cross-Platform / Non-Windows User | Currently excluded from the best-regarded Windows imaging suites by OS choice | Native macOS/Linux experience, no virtualization/Wine workaround needed |
| Plugin/Driver Developer | Community contributor extending device or workflow support | Documented, stable plugin API |
| Variable Star Observer (AAVSO contributor) | Plans and executes variable-star observation campaigns, submits photometric measurements to AAVSO — served by the optional, pre-loaded VSTarget plugin (`docs/plugins/vstarget/PSD.md`), not a core domain | Target selection/scripting, photometry/reporting accuracy — see the plugin's own PSD Section 9 |

## 11. Assumptions and Constraints

- **A1** — INDI drivers and Alpaca-exposed devices provide sufficient capability parity with the ASCOM devices NINA users currently own; gaps in a given third-party driver's INDI/Alpaca implementation are outside Galileo's control.
- **A2** — External plate-solving engines and guiding applications (or their protocol equivalents) are available cross-platform; Galileo integrates with them rather than reimplementing.
- **A3** — Users needing legacy Windows-only ASCOM COM drivers will run the ASCOM Alpaca-COM bridge themselves; Galileo only speaks Alpaca.
- **C1** — The project has no affiliation with the NINA project; no NINA source code, assets, or trademarks will be used. Feature parity is achieved through independent, clean-room design informed only by NINA's publicly documented behavior.
- **C2** — Initial release prioritizes deep-sky long-exposure imaging; planetary/high-frame-rate workflows are deferred (Section 5).
- **C3** — Galileo supports FITS only for all image I/O, including tile-compressed FITS (Rice/GZIP/HCOMPRESS/PLIO per the FITS tile-compression convention) as a required, not optional, capability. XISF is explicitly excluded: it is a single-vendor (PixInsight/Pleiades Astrophoto) format, whereas FITS is the IAU-endorsed, multi-vendor community standard already required for interoperability with the broader INDI/ASCOM/astropy tooling ecosystem. This is a deliberate divergence from NINA, which supports both.
- **C4 (resolved)** — Galileo is licensed **GPL-3.0**, matching AstroFiler. All dependencies adopted so far are GPL-3.0-compatible; notably, the Apache-2.0-licensed `google-cloud-storage`/`google-auth` (`LIB` domain, cloud sync) requires GPL-3.0 specifically — GPL-2.0 would not have been compatible with it. Accepted consequence: since the plugin architecture (`PLUG` domain, SDD Section 4.20) loads plugins in-process and calls directly into core APIs, third-party plugins are very likely "combined works" under GPL-3.0 and must themselves be GPL-compatible-licensed to distribute — closed-source/commercial plugins (e.g. vendor-provided device support, as some NINA plugins are under NINA's MPL-2.0) are not viable under this model. This is accepted as consistent with an all-open plugin ecosystem; revisit only if vendor-authored closed-source plugins become a goal.
- **C5 (retired)** — Previously covered VSTarget's own license/dependency compatibility as part of a core-embedded merge; VSTarget is now documented as a plugin (`docs/plugins/vstarget/PSD.md`, Section 10, PC1–PC3), which restates this constraint at plugin scope. This ID is left retired rather than reused, consistent with this document's practice of leaving a gap rather than renumbering (Section 4's goal IDs do the same).
- **C6 (resolved)** — Obsy was originally licensed **CC BY-NC-ND 4.0**, which required treating its contribution as architectural reference to be reimplemented clean-room rather than code to vendor or copy verbatim. **Obsy has since been relicensed to GPL-3.0**, removing that constraint entirely: its rise/transit/set (`astroplan`-based) and DSS-cutout thumbnail-fetch logic can now be ported directly into Galileo, the same as AstroFiler's code, with no license tension. This is a license change only, not an architecture one — Obsy is still a Django web application with no structural counterpart in Galileo's PySide6/Qt modules, so in practice direct porting applies at the function/algorithm level (the rise/transit/set computation, the thumbnail-fetch helper), not wholesale module reuse. If Obsy ever had contributors other than the author, that should still be confirmed before reuse, independent of the license change.
- **C7** — AstroLlama is GPL-3.0 licensed, so its selectively harvested tool functions (Section 6.5) carry no license tension. Its geocoding/weather tools depend on the Open-Meteo API, which requires no API key for non-commercial-scale use and has no license/data-rights conflict with GPL-3.0 distribution — Galileo only calls the API at runtime, it does not redistribute Open-Meteo's data.
- **C8 (resolved)** — MCP was originally unlicensed (null on GitHub) but **has since been relicensed to GPL-3.0**, same as Obsy (C6) — its rain/aurora/smoke detection logic can now be ported directly rather than reimplemented clean-room. If MCP ever had contributors other than the author, that should still be confirmed before reuse, independent of the license. (mlCloudDetect — also GPL-3.0 — is removed from scope for now; see Section 6.7.)
- **C9** — The Telescopius API (Section 6.9) is a runtime integration, not vendored/harvested code, so it carries no license tension for Galileo itself, but its data is not Galileo's to redistribute — Galileo calls it live with the user's own API key and does not cache or ship Telescopius data, the same non-redistribution posture already taken with Open-Meteo (C7). Unlike C7, access itself is conditional on the user holding a paid Patron/Sponsor account, so it is scoped as an optional augmentation a user opts into by supplying a key, never a capability any MVP `SKY` behavior depends on (Section 8).

## 12. Risks

| Risk | Impact | Notes |
|---|---|---|
| INDI/Alpaca driver feature gaps vs. native ASCOM COM drivers | Medium-High | Some advanced device features may be unavailable until driver authors add protocol support |
| Cross-platform UI framework may not match NINA's WPF-level polish without significant investment | Medium | Framework choice is an SDD-level decision but should weight UI fidelity heavily |
| Scope creep toward full post-processing suite | Medium | Mitigated by explicit non-goal in Section 5 |
| Plugin ecosystem cold-start (NINA's plugin catalog is a major value driver) | Medium | Plugin API and a small set of first-party reference plugins should ship with v1 |
| Unattended-session reliability bugs are high-cost to users (lost imaging nights) | High | `NFR-REL` should carry disproportionate test investment |
| AstroFiler merge introduces a second, previously independent codebase's persistence/module boundaries into Galileo, risking schema/architecture friction with the `ARCH`/`PROF`/`HIST` designs already established | Medium | Mitigated by unifying on AstroFiler's existing Peewee/SQLite persistence choice rather than running two ORMs (see SDD ADR-002) |
| GPL-3.0 (Section 11, C4) forecloses closed-source/commercial third-party plugins under the current in-process plugin design | Low today (no plugin ecosystem yet); would require a licensing or plugin-isolation redesign if vendor-authored closed-source plugins later become a goal | Accepted for now; revisit only if that goal emerges |
| `OBS` multi-mount support (G16) touches `ARCH`/`EQP`/`SES`/`SCHED`/`DOME`/`SAFE` — every domain built so far implicitly assumed one mount. This is a genuinely bigger change than any single-domain addition in this document | Medium-High | Mitigated architecturally rather than deferred outright: `ARCH-080` (device abstraction supports multiple concurrent per-Pier device pools) is MVP even though `OBS`'s full feature set is P2, so v1 doesn't have to be retrofitted later for something this foundational |
| Telescopius API (Section 6.9) is immature (launched 2023 with a single endpoint), paywalled (Patron/Sponsor-only, no free tier as of review), and not fully documented — its actual v1 endpoint surface may differ from what's anticipated here | Low | Scoped as optional P2 enrichment behind a user-supplied key (Section 8, `SKY`), never a dependency of the offline database/SIMBAD-fallback path; re-review the endpoint surface at SRS authoring time rather than committing to specifics now |

## 13. Success Criteria (Scope-Level)

- A user can complete an entire unattended overnight deep-sky imaging session — connect equipment, frame a target, plate-solve, run an advanced sequence with autofocus and dithered guiding, and safely park at dawn or on weather abort — using only Galileo, on any of Windows, macOS, or Linux.
- All device communication occurs exclusively over INDI or Alpaca; no OS-specific device binding exists in the codebase.
- Installers exist and are tested for all three target platforms.

## 14. Path to SRS / SDD / Traceability Matrix

1. **SRS** — Each domain in Sections 8–9 is decomposed into atomic, testable "shall" requirements numbered `<PREFIX>-###` (e.g., `SES-040`), each tagged with the priority/phase carried over from this document.
2. **SDD** — Architecture and component design map onto the `ARCH` domain and the device-abstraction/plugin boundary described in Section 8; one SDD component section per SRS domain is expected.
3. **Traceability Matrix** — A table of SRS requirement ID → SDD component(s) → test case(s), seeded directly from the ID prefixes established in Sections 8–9 so no remapping is needed later.

## 15. Glossary

| Term | Definition |
|---|---|
| PSD | Project Scope Document — this document |
| SRS | Software Requirements Specification — decomposes this document's domains into numbered requirements |
| SDD | Software Design Description — describes the architecture/modules satisfying the SRS |
| RTM | Requirements Traceability Matrix — maps SRS requirement IDs to SDD components and test cases |
| ADR | Architecture Decision Record — a numbered design-decision entry in the SDD (e.g. ADR-001) |
| GPL | GNU General Public License — Galileo's project license, version 3.0 (Section 11, C4) |
| INDI | Instrument Neutral Distributed Interface — open cross-platform protocol/server for astronomical device control |
| ASCOM | Windows-native COM-based standard for astronomy device drivers |
| Alpaca | ASCOM's network/REST-based protocol, OS-independent, interoperable with ASCOM via a bridge |
| HFR | Half Flux Radius — a star-sharpness metric used for autofocus and image-quality trending |
| Plate Solving | Determining exact sky coordinates of an image by matching star patterns to a catalog |
| WCS | World Coordinate System — the FITS-header convention mapping image pixels to sky coordinates, written by plate solving |
| FOV | Field of View — the area of sky a given camera/telescope combination images |
| Mosaic | A target area larger than one FOV, imaged as a grid of overlapping panes; in Galileo (Section 8.3) one Image block or Imaging-tab run owns an entire mosaic and captures it pane-by-pane in an interleaved round (one exposure per pane per pass), not as separate per-panel targets |
| GEM | German Equatorial Mount — the mount type requiring a meridian flip |
| Meridian Flip | The 180° mount reorientation German equatorial mounts (GEMs) must perform when a target crosses the meridian |
| Dithering | Small random pointing offsets between exposures to reduce fixed-pattern noise in stacked images |
| Session | Two merged meanings by design (Section 8.1, G7): (1) AstroFiler's original sense — a related group of output artifacts (calibration frames plus lights) grouped by camera/binning/temperature/date; (2) the Sessions screen's authoring unit — a bounded, orderable sequence of action blocks (Target, Image, Autofocus, Solve, nested conditions/triggers) that, when run, produces (1). There is no separate "basic" vs. "advanced" session — one `SES` domain and one screen cover both (Section 8.1). Owned by exactly one Pier (`PROF`) and, once authored, submitted to `SCHED` to actually run |
| Action Block / Palette | A single draggable unit of session-authoring behavior (e.g. Target, Autofocus, Solve, Exposure) offered from the Sessions screen's single right-hand palette and dropped into a session region; the built-in set is open to plugin extension (`PLUG`), same as `SES`'s instruction/condition/trigger catalog |
| FITS | The IAU-standard astronomical image file format carrying image data plus metadata headers; Galileo's sole supported image format, including its tile-compression convention (Section 11, C3) |
| XISF | PixInsight's (Pleiades Astrophoto) single-vendor image file format; not supported by Galileo (Section 11, C3) |
| Flat Frame | A calibration exposure of uniform illumination used to correct vignetting/dust artifacts |
| ORM | Object-Relational Mapper — Galileo uses Peewee (Section 11, C4/SDD ADR-002) to map its Python data models onto the SQLite database |
| SEP | Source Extractor for Python — the star-detection library used across `IMG`, `FOC`, and `LIB` (SDD ADR-002) |
| MCP | Two unrelated meanings appear in this document: (1) **Model Context Protocol**, the AI-tool-calling standard used by AstroLlama's harvested tools (Section 6.5) and EKOS's own 3.8.4-release LLM control surface (Section 6.6); (2) the separate same-author project literally named **MCP** ("Master Control Programs for Observatories and Telescopes," Section 6.7). Disambiguated inline at each use |
| DSS | Digitized Sky Survey — the sky-image source (DSS2, fetched via the CDS hips2fits cutout service) used for target thumbnails (`SKY-080`), cropped to the target's own angular size rather than a fixed cutout (Section 8, `SKY`) |
| HMS | NOAA's Hazard Mapping System — the smoke-polygon data source behind `SAFE-100` |
| SIMBAD | CDS Strasbourg's astronomical object database; Galileo's `SKY` fallback lookup for a specific searched object the internal offline database can't resolve (Section 8) |
| Telescopius | A patron/sponsor-gated, user-API-key online astronomy target-search and observing-list service; an optional `SKY` augmentation source reviewed in Section 6.9, never a dependency of the offline-first Targets screen |

## 16. References

- NINA project site: https://nighttime-imaging.eu/
- NINA documentation: https://nighttime-imaging.eu/docs/master/site/
- NINA source (for public-behavior reference only, not reused): https://github.com/isbeorn/nina
- AstroFiler (merged into Galileo, `LIB` domain): https://github.com/gordtulloch/astrofiler-gui
- VSTarget (delivered as a first-party plugin, not a core domain — see [docs/plugins/vstarget/PSD.md](plugins/vstarget/PSD.md) for its own reference list): https://github.com/gordtulloch/VSTarget
- Obsy (retired; GPL-3.0, ported directly into `SKY`/`FRAME` domains): https://github.com/gordtulloch/obsy
- AstroLlama MCP tools (selectively harvested into `ARCH`/`PROF`/`PLT`/`SKY`/`SAFE`, plus the VSTarget plugin's own `VST-AN`): https://github.com/gordtulloch/AstroLlama/tree/main/mcp_server/tools
- KStars/EKOS (comparative gap review, Section 6.6, not affiliated/reused code): https://kstars.kde.org/, handbook at https://kstars-docs.kde.org/en/user_manual/ekos.html, release notes at https://knro.blogspot.com/
- MCP (GPL-3.0; rain/aurora/smoke detection ported into `SAFE`): https://github.com/gordtulloch/MCP
- Telescopius API (optional `SKY` augmentation, Section 6.9, not affiliated/reused code): https://telescopius.com/pages/api, https://api.telescopius.com/, forum thread: https://forum.telescopius.com/t/generating-api-key/319
- SIMBAD astronomical database (CDS Strasbourg; `SKY` fallback lookup, Section 8): https://simbad.u-strasbg.fr/simbad/

## 17. Future Considerations (Not V1)

Identified during the KStars/EKOS review (Section 6.6) but deliberately deferred, not silently dropped:

- **MCP server / LLM control surface for Galileo.** EKOS shipped an in-process MCP server in its 3.8.4 release (August 2026). The author's own AstroLlama project already has direct experience building MCP tools for astronomy device control (Section 6.5), which would make this a natural fit for a later Galileo release — but it is not core acquisition functionality and should not compete with v1 scope.
- **Built-in AI-assisted predictive guiding.** EKOS's version (also from the 3.8.4 release) is explicitly experimental even in a decade-mature codebase; Galileo's external-guider-only design (Section 5) remains the right v1 call, but a future native predictive-guiding mode is worth revisiting once external-guider integration (`GUIDE`) is proven.
- INDI protocol: https://indilib.org/
- ASCOM Alpaca: https://ascom-standards.org/AlpacaDeveloper/

---

*This document is a living draft. Open items, priority calls, and domain boundaries should be resolved with stakeholders before SRS authoring begins.*
