# Galileo — SRS (Software Requirements Specification)

| | |
|---|---|
| **Project** | Galileo — Cross-Platform Astrophotography Imaging Suite |
| **Document** | SRS (Software Requirements Specification), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-09-16 |
| **Upstream document** | [PSD (Project Scope Document)](PSD.md) |
| **Downstream documents** | SDD (Software Design Description), RTM (Requirements Traceability Matrix) |

---

## 1. Introduction

### 1.1 Purpose

This SRS decomposes the requirement domains identified in the [Project Scope Document](PSD.md) (Sections 8–9) into individually numbered, verifiable requirements. Every requirement ID is prefixed with the domain code established in the scope document (e.g. `SEQ-ADV`, `NFR-REL`) so it can be carried forward unchanged into the SDD and Requirements Traceability Matrix.

### 1.2 Scope

Covers all functional domains (`ARCH`, `EQP`, `PROF`, `OBS`, `IMG`, `SEQ`, `SEQ-ADV`, `SKY`, `FRAME`, `SKYMAP`, `SCHED`, `CAL`, `FOC`, `PLT`, `MFLIP`, `GUIDE`, `DOME`, `SAFE`, `HIST`, `META`, `NOTIF`, `PLUG`, `UI`, `LOG`, `LIB`, `VST`, `VST-AN`) and non-functional domains (`NFR-PERF`, `NFR-REL`, `NFR-PORT`, `NFR-EXT`, `NFR-USE`, `NFR-I18N`, `NFR-SEC`, `NFR-OFFLINE`, `NFR-INSTALL`) defined in the scope document. Out-of-scope items (Section 5 of the scope document) are not addressed here.

### 1.3 Requirement ID Convention

`<DOMAIN>-<###>`, numbered in increments of 10 within each domain to leave room for later insertion without renumbering (e.g. `FOC-010`, `FOC-020`). Device-specific equipment requirements additionally carry a device code, e.g. `EQP-CAM-010`.

### 1.4 Priority Convention

- **MVP** — required for v1 release
- **P2** — targeted for the second release phase
- **P3** — targeted for a later release phase

Priorities are inherited from the scope document and may be adjusted during SRS review.

### 1.5 Definitions, Acronyms, Abbreviations

See scope document Section 15 (Glossary). Additional terms are defined inline where first used.

### 1.6 References

- [Project Scope Document](PSD.md)
- INDI protocol: https://indilib.org/
- ASCOM Alpaca API: https://ascom-standards.org/AlpacaDeveloper/
- NINA documentation (behavioral reference only): https://nighttime-imaging.eu/docs/master/site/

---

## 2. Overall Description

### 2.1 Product Perspective

Galileo is a standalone cross-platform desktop application. It is not a service or plugin to another application. It communicates with astronomical hardware exclusively through two external protocol layers — INDI and ASCOM Alpaca — never through direct hardware/driver binding.

### 2.2 Product Functions (Summary)

Equipment connection and control; guided imaging capture; basic and advanced sequencing; target planning via sky atlas and framing assistant; calibration frame automation; autofocus; plate solving; meridian flip automation; guiding coordination; dome synchronization; safety/weather monitoring; session history; metadata-rich image output; notifications; a plugin framework; UI theming; diagnostics/logging; a merged image-library subsystem (repository cataloging, deduplication, smart-telescope ingestion, master-calibration processing, quality metrics, cloud sync); and a merged variable-star workflow (AAVSO target planning/scripting and photometric analysis/reporting); a live interactive star-map/planetarium view; a multi-night observatory scheduler; and multi-mount observatory management (multiple independent telescopes coordinated within one application instance).

### 2.3 User Classes and Characteristics

See scope document Section 10 (Personas). The dominant user class is the hobbyist deep-sky astrophotographer running unattended overnight sessions; the SRS favors robustness and guided workflows over expert-mode density, without removing advanced capability (the same simple-plus-advanced sequencer split several established imaging suites, NINA included, converge on).

### 2.4 Operating Environment

Windows 10/11 (x64), macOS (current and prior major version, Apple Silicon + Intel), and major Linux distributions (Debian/Ubuntu, Fedora, Arch), per scope document Section 7.

### 2.5 Design and Implementation Constraints

- All device I/O goes through INDI or Alpaca; no ASCOM COM interop, no vendor SDK linking (`ARCH-010`).
- No bundled post-processing, stacking, or planetary/lucky-imaging pipeline (scope document Section 5).
- No bundled guiding algorithm; guiding is via an external guider's control protocol (`GUIDE` domain).

### 2.6 Assumptions and Dependencies

See scope document Section 11 (A1–A3, C1–C2).

---

## 3. External Interface Requirements

| ID | Requirement | Priority |
|---|---|---|
| EXT-010 | The system shall provide a graphical desktop user interface as the sole primary interface; no requirement exists for a CLI or headless mode in v1. | MVP |
| EXT-020 | The system shall connect to device drivers only via an INDI server (TCP, INDI XML protocol) or an Alpaca device (HTTP/REST, JSON, per the ASCOM Alpaca specification, including UDP discovery). | MVP |
| EXT-030 | The system shall support connecting to an INDI server or Alpaca device on the local machine or over a LAN/WAN network address. | MVP |
| EXT-040 | The system shall interoperate with external plate-solving engines via their documented command-line or local HTTP interfaces (e.g. ASTAP, astrometry.net local solve, PlateSolve2-compatible solvers), configurable per installation. | MVP |
| EXT-050 | The system shall interoperate with external autoguiding applications via their documented control protocol (e.g. a PHD2-compatible JSON-RPC event/command interface). | MVP |
| EXT-060 | The system shall write image files in FITS format only, to a user-configured filesystem location. FITS shall be the sole supported image file format; no other format (e.g. XISF) is supported. | MVP |
| EXT-070 | The system shall support outbound notification integrations (e.g. webhook, email, push-notification service) as configurable, optional endpoints. | P3 |
| EXT-080 | The system shall connect to smart-telescope network shares via SMB/CIFS (e.g. SEESTAR, StellarMate) and via FTP/FTPS (e.g. DWARF, iTelescope) for remote file browsing and download. | MVP |
| EXT-090 | The system shall synchronize repository contents with Google Cloud Storage via its documented API, authenticated per user-supplied credentials. | P2 |
| EXT-100 | The system shall retrieve variable-star target data from the AAVSO Target Tool API and comparison-star data from the AAVSO VSP API. | MVP |
| EXT-110 | The system shall query the Simbad astronomical database for target coordinate/magnitude lookup where not already available from the AAVSO catalog data. | MVP |
| EXT-120 | The system shall retrieve calibrated FITS images from a remote-telescope data server via SFTP, in addition to the FTP/FTPS access already required by `EXT-080`. | MVP |
| EXT-130 | The system shall query the Open-Meteo API for location geocoding and weather-forecast data. | P2 |

---

## 4. Functional Requirements

### 4.1 `ARCH` — Protocol & Device Abstraction Layer

| ID | Requirement | Priority |
|---|---|---|
| ARCH-010 | The system shall define a device-abstraction interface per device category (camera, mount, filter wheel, focuser, rotator, guider, switch, flat panel, weather, dome, safety monitor) that is implemented independently by an INDI backend and an Alpaca backend. | MVP |
| ARCH-020 | The system shall allow each connected device to independently use either the INDI backend or the Alpaca backend, simultaneously, within a single equipment profile (e.g. an INDI camera with an Alpaca focuser). | MVP |
| ARCH-030 | The system shall query a connected device's advertised capabilities (INDI properties / Alpaca `Can*` flags) and expose only the corresponding controls in the UI. | MVP |
| ARCH-040 | The system shall detect and surface a device disconnect event to the equipment layer within a bounded time, without crashing or requiring application restart. | MVP |
| ARCH-050 | The system shall support INDI server and Alpaca device discovery (INDI: configured host/port list; Alpaca: UDP discovery per the Alpaca spec) to populate a connect dialog. | P2 |
| ARCH-060 | The system shall isolate a single misbehaving device connection so that it does not block or degrade control of other connected devices. | MVP |
| ARCH-070 | The device-abstraction layer shall be the sole integration point plugins use to register new device backends (traces to `PLUG-010`). | P2 |
| ARCH-080 | The device-abstraction layer shall support multiple concurrent, independently-addressable device pools (one per Pier), rather than assuming a single global set of connected devices, so that multi-Pier observatory support (`OBS`) does not require retrofitting the device layer. | MVP |

### 4.2 `EQP` — Equipment Control

#### 4.2.1 Cross-Device Generic Requirements

| ID | Requirement | Priority |
|---|---|---|
| EQP-010 | For every supported device category, the system shall provide connect, disconnect, and live connection-status indication in the equipment panel. | MVP |
| EQP-020 | For every supported device category, the system shall display and allow configuration of device-specific settings exposed by the backend (e.g. gain, port, polling interval). | MVP |
| EQP-030 | The system shall log all device connect/disconnect/error events with timestamps to the diagnostics log (traces to `LOG-010`). | MVP |
| EQP-040 | The system shall allow a device to be selected from all currently reachable INDI/Alpaca devices of its category, with a manual refresh action. | MVP |
| EQP-050 | The system shall surface a device-reported error/alert state distinctly from a normal disconnect in the equipment panel. | MVP |
| EQP-060 | The system shall provide an advanced device-property inspector/control panel exposing raw INDI properties or Alpaca device parameters, for diagnostic/expert use distinct from the normal guided controls. | P2 |

#### 4.2.2 Device-Specific Requirements

| ID | Requirement | Priority |
|---|---|---|
| EQP-CAM-010 | The system shall control camera exposure start/abort, exposure time, gain/offset (where supported), binning, and readout/frame-type (light/dark/flat/bias) selection. | MVP |
| EQP-CAM-020 | The system shall support cooled cameras: set target temperature, monitor current temperature and cooler power, and issue a warm-up sequence. | MVP |
| EQP-CAM-030 | The system shall retrieve captured frame data from the camera backend and render it in the imaging tab (traces to `IMG-010`). | MVP |
| EQP-CAM-040 | The system shall support a simulator camera backend for development and testing without physical hardware. | MVP |
| EQP-MNT-010 | The system shall control mount slew-to-coordinates, slew-abort, tracking on/off, tracking rate selection, and park/unpark. | MVP |
| EQP-MNT-020 | The system shall display current mount right ascension/declination, altitude/azimuth, pier side, and tracking state, refreshed on a bounded polling interval. | MVP |
| EQP-MNT-030 | The system shall support mount sync-to-coordinates as issued by the plate-solving workflow (traces to `PLT-030`). | MVP |
| EQP-MNT-040 | The system shall support slewing to and tracking a non-sidereal target (e.g. comet, asteroid, satellite) at a custom tracking rate, where the mount backend supports it. | P2 |
| EQP-FW-010 | The system shall enumerate configured filter names/slots and issue filter-change commands, exposing change-in-progress status. | MVP |
| EQP-FW-020 | The system shall allow per-filter focus-offset configuration for use by the autofocus and filter-change workflows. | MVP |
| EQP-FOC-010 | The system shall issue absolute and relative focuser move commands and display current position and temperature (where supported). | MVP |
| EQP-FOC-020 | The system shall support configurable focuser backlash compensation applied to move commands. | P2 |
| EQP-ROT-010 | The system shall issue rotator move-to-angle commands and display current mechanical/sky position angle. | P2 |
| EQP-GDR-010 | The system shall expose guider connect/start-guiding/stop-guiding/dither controls, delegating to the external guiding interface (`GUIDE` domain). | MVP |
| EQP-SW-010 | The system shall enumerate switch/relay devices and their read/write state, supporting both boolean and analog (variable) switches. | P2 |
| EQP-FP-010 | The system shall control an electroluminescent/flat-panel device's cover open/close (where supported) and brightness level. | MVP |
| EQP-WX-010 | The system shall poll and display weather-device readings (e.g. cloud cover, wind, humidity, temperature, rain) at a configurable interval. | P2 |
| EQP-DOME-010 | The system shall issue dome slew-to-azimuth, open/close-shutter, and park commands and display current azimuth and shutter state. | P2 |
| EQP-SAFE-010 | The system shall poll a connected safety-monitor device's is-safe state at a configurable interval and surface state changes to the sequencer (traces to `SAFE-010`). | P2 |

### 4.3 `PROF` — Equipment Profiles (Piers)

Refined against the KStars/EKOS "Optical Trains" model (Project Scope Document, Section 6.6): a profile is a **Pier** — one mount plus one or more named optical trains, not a flat device list. Multiple Piers can be grouped into an Observatory (`OBS`) for multi-mount operation (`ARCH-080`).

| ID | Requirement | Priority |
|---|---|---|
| PROF-010 | The system shall allow the current set of device connections and per-device settings to be saved as a named equipment profile. | MVP |
| PROF-020 | The system shall allow a saved equipment profile to be loaded, reconnecting all devices it references. | MVP |
| PROF-030 | The system shall allow multiple equipment profiles to be created, renamed, and deleted, supporting users with more than one imaging rig. | MVP |
| PROF-040 | The system shall persist the last-used equipment profile and offer to reload it on application start. | MVP |
| PROF-050 | The system shall export a profile to a portable file and import a profile from one, to support sharing/backup. | P2 |
| PROF-060 | The system shall warn, rather than silently fail, when a profile references a device no longer reachable at load time, and allow proceeding without it. | MVP |
| PROF-070 | The system shall allow devices to be organized into a named "optical train" — an ordered chain from telescope/lens, through intermediate elements (reducer/flattener, filter wheel, rotator, off-axis guider), to the final imaging camera — rather than requiring each device to be configured independently. | MVP |
| PROF-080 | The system shall support multiple concurrently defined optical trains within one equipment profile, each independently selectable by the imaging, sequencer, and framing modules. | MVP |
| PROF-090 | The system shall automatically derive effective focal length and plate scale for framing (`FRAME-010`) and plate-solving (`PLT`) calculations from the active optical train's chained components, rather than requiring manual re-entry per setup. | MVP |

### 4.3a `OBS` — Multi-Mount Observatory Management (exceeds EKOS, Section 6.6)

A single Galileo instance manages multiple independent Piers (`PROF`), deliberately going beyond EKOS's own single-mount-per-application-instance model. Unlike `DOME`/`SAFE` (which may be Pier- or Observatory-scoped, `OBS-030`/`OBS-050`), guiding is never Observatory-scoped — see `GUIDE-060`.

| ID | Requirement | Priority |
|---|---|---|
| OBS-010 | The system shall allow multiple Piers to be grouped into a named Observatory. | P2 |
| OBS-020 | The system shall allow independent sequences and scheduler jobs to run concurrently across different Piers within an Observatory, each targeting a different object. | P2 |
| OBS-030 | The system shall allow a safety-monitor/weather source to be scoped at the Observatory level (shared across all member Piers) or at the Pier level (independent), configurable per Observatory. | P2 |
| OBS-040 | When an Observatory-scoped safety-monitor reports an unsafe condition, the system shall pause or abort active sequences and park equipment across every Pier in that Observatory (traces to `SAFE-010`), not just the Pier that detected it. | P2 |
| OBS-050 | The system shall allow a dome/roof to be scoped at the Observatory level (one shared roof covering multiple piers) or at the Pier level (independent domes), configurable per Observatory. | P2 |
| OBS-060 | The system shall present a multi-Pier status dashboard (equipment/sequence/scheduler state for every Pier in an Observatory at a glance), in addition to a focused single-Pier view. | P2 |
| OBS-070 | The scheduler (`SCHED`) shall support assigning jobs to any Pier within an Observatory and shall coordinate Observatory-scoped shared-resource constraints (e.g. a shared dome/roof state) across the Piers that depend on them. | P2 |
| OBS-080 | The system shall connect to and concurrently operate the device sets of multiple Piers within a single running application instance (traces to `ARCH-080`). | P2 |

### 4.4 `IMG` — Imaging Tab

| ID | Requirement | Priority |
|---|---|---|
| IMG-010 | The system shall display a newly captured frame in a live preview within a bounded time after camera readout completes. | MVP |
| IMG-020 | The system shall compute and display an auto-stretch preview of the displayed frame without altering the saved file's raw pixel data. | MVP |
| IMG-030 | The system shall display a histogram of the current frame, updated per capture. | MVP |
| IMG-040 | The system shall compute per-frame statistics (mean, median, min/max, star count, HFR) and display them alongside the preview. | MVP |
| IMG-050 | The system shall overlay detected stars used for HFR computation on the frame preview, toggleable by the user. | P2 |
| IMG-060 | The system shall allow the user to pan and zoom the displayed frame. | MVP |
| IMG-070 | The system shall support a manual single-exposure capture independent of any running sequence. | MVP |
| IMG-080 | The system shall allow the user to configure the imaging-tab panel layout (traces to `UI-020`). | P2 |
| IMG-090 | The system shall display live exposure countdown and camera/download status during an in-progress capture. | MVP |
| IMG-100 | The system shall allow saving the currently displayed frame independently of the automatic sequence save path. | P2 |

### 4.5 `SEQ` — Sequencer (Basic)

| ID | Requirement | Priority |
|---|---|---|
| SEQ-010 | The system shall allow definition of an ordered list of imaging targets, each with exposure count, exposure time, filter, and binning. | MVP |
| SEQ-020 | The system shall support dynamic file-naming macros (e.g. target name, filter, date, frame number, frame type) applied to saved files. | MVP |
| SEQ-030 | The system shall execute a defined sequence start-to-finish without further user interaction, capturing and saving each configured frame. | MVP |
| SEQ-040 | The system shall allow a running sequence to be paused, resumed, and stopped by the user. | MVP |
| SEQ-050 | The system shall display live sequence progress (current target, frame N of M, elapsed/remaining estimate). | MVP |
| SEQ-060 | The system shall persist a sequence definition to a file for reuse across sessions. | MVP |
| SEQ-070 | The system shall record, per captured frame, sufficient metadata to reconstruct which sequence step produced it (traces to `META` domain). | MVP |
| SEQ-080 | The system shall continue to the next sequence step and log a recoverable error rather than terminate the sequence, when a single non-fatal capture error occurs. | MVP |
| SEQ-090 | The system shall support running capture sequences in parallel across two or more optical trains (`PROF-080`) sharing the same mount, using a lead/follower model: one optical train's job defines the target and scheduling criteria (the lead), while the others (followers) capture in parallel; shared mount-related events (slew, dither, plate-solve/align, meridian flip) are synchronized across all participating trains, matching the EKOS multi-train pattern. | P3 |

### 4.6 `SEQ-ADV` — Sequencer (Advanced)

| ID | Requirement | Priority |
|---|---|---|
| SEQ-ADV-010 | The system shall provide an advanced sequence editor composed of nested instruction, condition, and trigger blocks, organized into instruction groups/containers. | P2 |
| SEQ-ADV-020 | The system shall provide, at minimum, the following instruction categories: capture (single/many exposures), mount (slew, sync, park), filter change, focuser (move, autofocus), rotator move, guider (start/stop, dither), dome (park, sync), switch set, wait (for time, for altitude, for duration), external script execution, and user message/prompt. | P2 |
| SEQ-ADV-030 | The system shall provide, at minimum, the following loop-condition types: repeat-for-count, loop-until-time, loop-while-safe, loop-while-above-horizon. | P2 |
| SEQ-ADV-040 | The system shall provide, at minimum, the following trigger types: autofocus-after-HFR-increase, autofocus-after-temperature-change, autofocus-after-time-interval, autofocus-on-filter-change, meridian-flip, safety-monitor-unsafe-abort. | P2 |
| SEQ-ADV-050 | The system shall allow instructions, conditions, and triggers to be nested within instruction-group containers to arbitrary depth. | P2 |
| SEQ-ADV-060 | The system shall allow a configured instruction-group to be saved and reused as a template across sequences. | P2 |
| SEQ-ADV-070 | The system shall allow a plugin to register a new instruction, condition, or trigger type that appears alongside built-in ones in the editor (traces to `PLUG-020`). | P2 |
| SEQ-ADV-080 | The system shall visually indicate the currently executing instruction during a running advanced sequence. | P2 |
| SEQ-ADV-090 | The system shall allow editing of a sequence's not-yet-executed instructions while the sequence is running. | P3 |
| SEQ-ADV-100 | The system shall provide a documented migration path or converter from a basic (`SEQ`) sequence to an advanced-sequence equivalent. | P2 |

### 4.7 `SKY` — Sky Atlas

| ID | Requirement | Priority |
|---|---|---|
| SKY-010 | The system shall provide a searchable deep-sky object catalog of at least 10,000 objects, including common name and catalog designations (Messier, NGC/IC, etc.). | MVP |
| SKY-020 | The system shall filter the catalog by object type, magnitude, size, and current/tonight visibility. | MVP |
| SKY-030 | The system shall plot an object's altitude over the current night for the configured observing location. | MVP |
| SKY-040 | The system shall allow definition of a custom horizon profile (obstruction line) per observing location and reflect it in altitude charts and visibility filtering. | P2 |
| SKY-050 | The system shall allow selecting an object from the atlas to populate it as a sequence/framing target. | MVP |
| SKY-060 | The system shall support one or more configured observing locations, each with latitude, longitude, and elevation. | MVP |
| SKY-070 | The system shall operate using a locally cached catalog with no live internet dependency for core search/filter/chart functions (traces to `NFR-OFFLINE`). | MVP |
| SKY-080 | The system shall fetch and cache a sky-survey cutout thumbnail image (e.g. via a DSS/STScI cutout service) for a catalog object when it is added to a user's active target list, for offline reference thereafter. | P2 |
| SKY-090 | The system shall resolve a location name/address to latitude, longitude, and timezone via a geocoding lookup (traces to `EXT-130`), as a convenience when configuring an observing location (`SKY-060`). | P2 |

### 4.8 `FRAME` — Framing Assistant

| ID | Requirement | Priority |
|---|---|---|
| FRAME-010 | The system shall display a field-of-view rectangle computed from the active camera's sensor dimensions and the active telescope's focal length, overlaid on a sky image. | P2 |
| FRAME-020 | The system shall support at least one online sky-survey image source and one offline/cached star-field rendering mode for the framing background. | P2 |
| FRAME-030 | The system shall allow the user to rotate the framing rectangle to preview a given camera/rotator position angle. | P2 |
| FRAME-040 | The system shall support defining a mosaic as a grid of overlapping framing panels with configurable overlap percentage. | P3 |
| FRAME-050 | The system shall allow a defined framing target (and each mosaic panel) to be sent to the sequencer as a target. | P2 |
| FRAME-060 | The system shall overlay constellation lines and a coordinate grid on the framing view. | P2 |

### 4.8a `SKYMAP` — Interactive Star Map / Planetarium (KStars/EKOS-informed)

A live, rendered sky view — distinct from the catalog-based `SKY` and the FOV-preview `FRAME` — presented as a third peer-level sky-related panel.

| ID | Requirement | Priority |
|---|---|---|
| SKYMAP-010 | The system shall render an interactive, pannable, zoomable real-time sky view for the configured observing location and time, displaying stars down to a configurable magnitude limit, deep-sky objects, and the Sun/Moon/planets. | MVP |
| SKYMAP-020 | The system shall allow clicking an object on the sky map to identify it, and double-clicking to center and track it. | MVP |
| SKYMAP-030 | The system shall overlay constellation lines/art and a coordinate grid on the sky map, each independently toggleable. | MVP |
| SKYMAP-040 | The system shall display comets, asteroids, and artificial satellites on the sky map from a periodically updated orbital-elements source. | P2 |
| SKYMAP-050 | The system shall overlay the active optical train's field-of-view rectangle and the mount's current pointing position live on the sky map, sharing FOV geometry with `FRAME-010`. | P2 |
| SKYMAP-060 | The system shall allow slewing the connected mount directly to a location clicked or selected on the sky map. | P2 |

### 4.8b `SCHED` — Observatory Scheduler (KStars/EKOS-informed)

Multi-night/multi-target job scheduling, distinct from `SEQ`/`SEQ-ADV`'s single-session execution ordering — a `SCHED` job references a `SEQ`/`SEQ-ADV` sequence, a target, and an equipment profile/optical train, and triggers that sequence's execution when its constraints are met.

| ID | Requirement | Priority |
|---|---|---|
| SCHED-010 | The system shall provide a prioritized job queue where each job specifies a target, a sequence definition (`SEQ` or `SEQ-ADV`), and a Pier/optical train (`PROF-080`) — traces to `OBS-070` when the Pier belongs to a multi-Pier Observatory. | MVP |
| SCHED-020 | The system shall allow jobs to be added, removed, reordered, and modified both before and during scheduler execution. | MVP |
| SCHED-030 | The system shall support per-job constraints: minimum target altitude, minimum moon separation, twilight restriction, and artificial-horizon/terrain-blockage avoidance, reusing the visibility computation shared with `SKY-030`. | MVP |
| SCHED-040 | The system shall support per-job startup conditions: immediate, at culmination, or at a specific time. | MVP |
| SCHED-050 | The system shall support per-job completion conditions: run once, repeat a specified number of times, or repeat indefinitely. | MVP |
| SCHED-060 | The system shall gate job startup and continued execution on a connected safety-monitor's state (traces to `SAFE-010`): suspend imaging on a warning state, and perform a full protective shutdown on an alert state. | MVP |
| SCHED-070 | The system shall continuously replan the job queue using priority-based preemption, allowing a higher-priority job to preempt a lower-priority one when it becomes runnable. | P2 |
| SCHED-080 | The system shall display each queued job's altitude trajectory and projected run window as a chart. | P2 |
| SCHED-090 | The system shall track per-job capture progress across multiple nights and avoid recapturing frames already obtained when a job resumes. | MVP |
| SCHED-100 | The system shall persist the job queue and per-job progress across application restarts. | MVP |

### 4.9 `CAL` — Calibration / Flat Wizard

| ID | Requirement | Priority |
|---|---|---|
| CAL-010 | The system shall provide an automated flat-frame capture routine that adjusts exposure time (or panel brightness) to reach a configured target ADU/histogram level. | MVP |
| CAL-020 | The system shall capture a configured number of flat frames per active filter automatically, cycling the filter wheel. | MVP |
| CAL-030 | The system shall support dark-frame and bias-frame capture sequences with configurable exposure/count/binning matching a set of light-frame parameters. | MVP |
| CAL-040 | The system shall integrate with a connected flat panel device to control brightness/cover as part of the flat-capture routine, where present. | MVP |
| CAL-050 | The system shall abort and report the flat-capture routine if a target ADU level cannot be reached within configured exposure-time bounds. | P2 |

### 4.10 `FOC` — Autofocus

| ID | Requirement | Priority |
|---|---|---|
| FOC-010 | The system shall run an autofocus routine that samples HFR at multiple focuser positions and fits a curve (e.g. V-curve/hyperbolic/parabolic) to determine best focus. | MVP |
| FOC-020 | The system shall move the focuser to the computed best-focus position and verify with a confirmation exposure. | MVP |
| FOC-030 | The system shall report autofocus failure (e.g. no valid curve fit, insufficient stars) distinctly from success, without leaving the focuser at an untested position. | MVP |
| FOC-040 | The system shall record each autofocus run's sample points and resulting curve for later review (traces to `HIST-020`). | P2 |
| FOC-050 | The system shall support autofocus invocation both manually (on demand) and via sequencer triggers (traces to `SEQ-ADV-040`). | MVP |
| FOC-060 | The system shall apply the per-filter focus offset (`EQP-FW-020`) when switching filters without requiring a full autofocus run, where offsets are configured. | P2 |
| FOC-070 | The system shall allow configuration of autofocus parameters (step size, number of points, exposure time, backlash handling) per equipment profile. | MVP |
| FOC-080 | The system shall provide an aberration-inspection tool that computes per-region (at minimum 3-point or 4-point) HFR/tilt indicators across the frame, to help diagnose sensor tilt or collimation issues. | P2 |

### 4.11 `PLT` — Plate Solving

| ID | Requirement | Priority |
|---|---|---|
| PLT-010 | The system shall invoke a configured external plate-solving engine against a captured or supplied frame and return solved RA/Dec and rotation. | MVP |
| PLT-020 | The system shall support at least one local/offline solver and remain functional without an internet connection for plate solving (traces to `NFR-OFFLINE`). | MVP |
| PLT-030 | The system shall support a solve-and-sync workflow that syncs the mount's reported position to the solved coordinates. | MVP |
| PLT-040 | The system shall support a solve-and-center workflow that iteratively slews and re-solves until the target is within a configured tolerance of the frame center. | MVP |
| PLT-050 | The system shall report plate-solve failure distinctly from success and allow the invoking workflow (manual or sequencer) to react accordingly. | MVP |
| PLT-060 | The system shall allow configuration of solver search parameters (field-of-view hint, search radius, downsample) per equipment profile. | P2 |

### 4.12 `MFLIP` — Meridian Flip

| ID | Requirement | Priority |
|---|---|---|
| MFLIP-010 | The system shall compute the time remaining until a German equatorial mount reaches its configured meridian-flip limit, based on current target and mount type. | P2 |
| MFLIP-020 | The system shall automatically pause an in-progress sequence, execute the meridian flip, and resume, without user interaction, when enabled. | P2 |
| MFLIP-030 | The system shall re-center (via `PLT-040`) and restart guiding after a meridian flip before resuming exposures. | P2 |
| MFLIP-040 | The system shall allow the meridian-flip limit and pre/post-flip behavior to be configured per equipment profile. | P2 |

### 4.13 `GUIDE` — Guiding Integration

Guiding is always Pier-scoped, never Observatory-scoped (contrast `DOME`/`SAFE`, which may be shared per `OBS-030`/`OBS-050`): expecting one guiding application to guide multiple independent mounts is not a reasonable requirement, so a multi-Pier Observatory runs one independent external-guider connection per Pier.

| ID | Requirement | Priority |
|---|---|---|
| GUIDE-010 | The system shall connect to a configured external guiding application's control interface and reflect its connection/guiding state. | MVP |
| GUIDE-020 | The system shall issue start-guiding and stop-guiding commands to the external guider and await confirmation before proceeding with dependent sequence steps. | MVP |
| GUIDE-030 | The system shall issue a dither command between exposures when configured, and wait for the external guider to settle before resuming capture. | MVP |
| GUIDE-040 | The system shall surface the external guider's reported guide error (RMS) for display and session-history logging (traces to `HIST-010`). | P2 |
| GUIDE-050 | The system shall treat a guiding-connection loss during a running sequence as a recoverable error per the sequencer's error-handling policy, not a silent stall. | MVP |
| GUIDE-060 | The system shall connect each Pier within an Observatory to its own independent external-guider instance (e.g. a separate PHD2 process/instance per Pier), never sharing one guider connection across multiple Piers. | P2 |

### 4.14 `DOME` — Dome Control

Within a multi-Pier Observatory, a dome may be Pier-scoped (independent) or Observatory-scoped (one shared roof) per `OBS-050`; the requirements below apply per-dome regardless of scope.

| ID | Requirement | Priority |
|---|---|---|
| DOME-010 | The system shall support slaving dome azimuth to the mount's current pointing direction while tracking. | P2 |
| DOME-020 | The system shall synchronize dome shutter and park actions with sequence start/end and meridian-flip events, where enabled. | P2 |
| DOME-030 | The system shall allow dome slaving to be disabled for domes controlled by independent third-party slaving hardware/software. | P2 |

### 4.15 `SAFE` — Safety & Weather Monitoring

Within a multi-Pier Observatory, a safety-monitor may be Pier-scoped (independent) or Observatory-scoped (shared, triggering all member Piers per `OBS-040`) per `OBS-030`.

| ID | Requirement | Priority |
|---|---|---|
| SAFE-010 | The system shall abort or pause a running sequence and park equipment when a connected safety-monitor device reports an unsafe condition, per configured policy. | P2 |
| SAFE-020 | The system shall log weather-device readings alongside session history for later correlation with image quality (traces to `HIST-010`). | P3 |
| SAFE-030 | The system shall allow configuration of which unsafe conditions trigger an automatic abort versus a warning-only notification. | P2 |
| SAFE-040 | The system shall prevent automatic sequence resumption after a safety abort until conditions are confirmed safe and, where configured, a user confirms resumption. | P2 |
| SAFE-050 | The system shall optionally display an internet-sourced weather forecast (traces to `EXT-130`) as a planning aid. This data source is advisory only and shall never be used as the sole basis for an automated safety abort — automated abort decisions (`SAFE-010`) shall be driven only by a connected safety-monitor device. | P2 |
| SAFE-060 | The system shall provide an independent heartbeat-timeout watchdog that, if the application stops sending heartbeats for a configurable period (e.g. due to a crash, hang, or lost network connection to a remote imaging host), autonomously parks the mount and then closes/parks the dome — distinct from, and in addition to, the weather-triggered abort path (`SAFE-010`). | MVP |
| SAFE-070 | The system shall support a serial rain-sensor input (e.g. Hydreon RG-11-class) as an additional safety-monitor source feeding automated abort decisions (`SAFE-010`), on the same trust tier as a connected INDI/Alpaca weather device since it is a local physical sensor. | P2 |
| SAFE-080 | The system shall support cloud-cover detection via ML image classification of an all-sky camera frame as an additional safety-monitor source feeding automated abort decisions (`SAFE-010`), on the same trust tier as a connected weather device since it reads a local physical camera. The classification shall require a configurable number of consecutive consistent readings before changing safety state, to avoid state-flapping on a single borderline frame. | MVP |
| SAFE-090 | The system shall optionally display an aurora activity estimate (e.g. via a Kp-index data source) as a planning aid, on the same advisory-only tier as `SAFE-050` — an internet API, not a local sensor, so it shall never drive an automated abort. | P3 |
| SAFE-100 | The system shall optionally display a smoke/transparency estimate (e.g. via a smoke-polygon data source) as a planning aid, on the same advisory-only tier as `SAFE-050` — an internet API, not a local sensor, so it shall never drive an automated abort. | P3 |

### 4.16 `HIST` — Session History & Statistics

| ID | Requirement | Priority |
|---|---|---|
| HIST-010 | The system shall record, per captured frame, HFR, star count, and guide RMS (where available) with a timestamp, for the duration of a session. | P2 |
| HIST-020 | The system shall display session-history metrics as a chart/table reviewable during and after a session. | P2 |
| HIST-030 | The system shall retain session-history data across application restarts, associated with the sequence/session that produced it. | P2 |
| HIST-040 | The system shall allow exporting session-history data to a portable format (e.g. CSV) for external analysis. | P3 |

### 4.17 `META` — Image Metadata

| ID | Requirement | Priority |
|---|---|---|
| META-010 | The system shall write FITS header keywords covering, at minimum: object/target name, exposure time, filter, gain/offset, binning, CCD/sensor temperature, date-obs, telescope/focal length, pixel scale, and frame type. | MVP |
| META-020 | The system shall write plate-solve results (RA/Dec, rotation) to the FITS header when a solve has been performed for the frame. | P2 |
| META-030 | The system shall support writing tile-compressed FITS (e.g. Rice, GZIP, or HCOMPRESS per the FITS tile-compression convention) as a user-configurable, per-profile capture option, with full header metadata preserved identically to uncompressed output. | MVP |
| META-040 | The system shall read and correctly decompress tile-compressed FITS files (e.g. for calibration-frame reuse and image-preview) transparently to the user. | MVP |
| META-050 | The system shall allow the user to add custom, static FITS header keywords applied to all captured frames in a session. | P3 |

### 4.18 `NOTIF` — Notifications

| ID | Requirement | Priority |
|---|---|---|
| NOTIF-010 | The system shall raise an in-app notification for sequence completion, sequence error/abort, and safety-triggered abort. | P2 |
| NOTIF-020 | The system shall support at least one external notification channel (e.g. webhook or push service) configurable by the user, delivering the same event set as `NOTIF-010`. | P3 |
| NOTIF-030 | The system shall allow notification events to be individually enabled/disabled per channel. | P3 |

### 4.19 `PLUG` — Plugin Framework

| ID | Requirement | Priority |
|---|---|---|
| PLUG-010 | The system shall expose a documented API allowing a plugin to register a new device backend implementing the `ARCH-010` abstraction. | P2 |
| PLUG-020 | The system shall expose a documented API allowing a plugin to register a new sequencer instruction, condition, or trigger type (traces to `SEQ-ADV-070`). | P2 |
| PLUG-030 | The system shall provide an in-app plugin manager to browse, install, update, and remove plugins from a configured plugin repository. | P2 |
| PLUG-040 | The system shall load and unload plugins without requiring a full application rebuild, and shall isolate a plugin failure from crashing the core application. | P2 |
| PLUG-050 | The system shall version-check a plugin against the running application's plugin API version and warn on incompatibility. | P2 |

### 4.20 `UI` — Customization & Theming

| ID | Requirement | Priority |
|---|---|---|
| UI-010 | The system shall provide at least a light and a dark color theme, selectable by the user. | P2 |
| UI-020 | The system shall allow the imaging-tab panel arrangement to be customized (e.g. dockable/resizable panels) and persisted across restarts. | P2 |
| UI-030 | The system shall allow accent-color customization within a theme. | P3 |

### 4.21 `LOG` — Diagnostics & Logging

| ID | Requirement | Priority |
|---|---|---|
| LOG-010 | The system shall write structured, timestamped application and session logs to a per-platform standard log directory. | MVP |
| LOG-020 | The system shall provide an in-app log viewer with severity filtering (info/warning/error). | MVP |
| LOG-030 | The system shall capture unhandled exceptions to the log with sufficient detail (stack trace, active sequence step, connected-device state) to diagnose post-hoc. | MVP |
| LOG-040 | The system shall allow exporting a support bundle (recent logs plus non-sensitive configuration) for bug reports. | P2 |

### 4.22 `LIB` — Image Library & Repository Management (merged from AstroFiler)

| ID | Requirement | Priority |
|---|---|---|
| LIB-010 | The system shall recursively scan a configured repository location, ingest discovered FITS files, and extract their header metadata into a catalog. | MVP |
| LIB-020 | The system shall detect duplicate files within the repository via SHA-256 content hashing and allow the user to review and remove duplicates. | MVP |
| LIB-030 | The system shall automatically rename and organize ingested files into a configurable folder structure derived from FITS metadata (e.g. object, date, filter, session). | MVP |
| LIB-040 | The system shall automatically group and link related frames into sessions based on matching camera, binning, and temperature, plus acquisition date. | MVP |
| LIB-050 | The system shall create master bias, dark, and flat calibration frames from a linked calibration session. | MVP |
| LIB-060 | The system shall apply a matching master calibration frame set (dark subtraction, flat division) to a selected group of light frames in one user action. | MVP |
| LIB-070 | The system shall compute and store per-frame quality metrics (FWHM, HFR, eccentricity, SNR) for ingested frames, supporting later filtering and sorting by quality. | MVP |
| LIB-080 | The system shall present a repository statistics dashboard summarizing frame counts by object, filter, date, and instrument, and quality-metric trends over time. | MVP |
| LIB-090 | The system shall browse and selectively download files from a SEESTAR or StellarMate smart telescope over SMB/CIFS (traces to `EXT-080`), enhancing headers as needed during ingest. | MVP |
| LIB-100 | The system shall browse and selectively download files from an iTelescope network share over FTPS (traces to `EXT-080`). | P2 |
| LIB-110 | The system shall browse and selectively download files from a DWARF smart telescope over FTP (traces to `EXT-080`), as an experimental capability. | P3 |
| LIB-120 | The system shall synchronize repository contents bidirectionally with Google Cloud Storage (traces to `EXT-090`), using content-hash comparison to avoid redundant transfer, with at least "complete," "backup only," and "on demand" sync profiles. | P2 |
| LIB-130 | The system shall expose repository scanning and cloud sync as command-line-invocable operations, independent of the GUI, for scheduled/automated execution. | P2 |
| LIB-140 | The system shall verify file integrity via stored content hashes on demand, flagging any repository file whose content no longer matches its recorded hash. | P2 |

### 4.23 `VST` — Variable Star Target Planning (merged from VSTarget)

Presented as a peer-level UI section to the Sky Atlas (`SKY`), not nested beneath it.

| ID | Requirement | Priority |
|---|---|---|
| VST-010 | The system shall synchronize variable-star target data from the AAVSO Target Tool API (traces to `EXT-100`), filterable by observing section (e.g. Alerts, Cataclysmic Variables, Eclipsing Variables, Long Period Variables). | MVP |
| VST-020 | The system shall display a sortable, searchable variable-star target list with priority indication and solar-conjunction warnings. | MVP |
| VST-030 | The system shall filter the variable-star target list to targets observable from the configured observing location during the current/next night, reusing the visibility computation shared with `SKY-030`. | MVP |
| VST-040 | The system shall support manual import of a variable-star target list from a delimited text file as an alternative to the AAVSO API. | P2 |
| VST-050 | The system shall provide an observation-plan editor allowing per-target filter, exposure count, exposure interval, and binning configuration. | MVP |
| VST-060 | The system shall generate an ACP-compatible observing script, with targets ordered by right ascension, for execution on a supported remote-telescope network (iTelescope in v1). | MVP |
| VST-070 | The system shall persist observation plans across application restarts. | MVP |
| VST-080 | The system shall look up a target's coordinates/magnitude via a Simbad query (traces to `EXT-110`) when not already present in the synced AAVSO catalog data. | MVP |

### 4.24 `VST-AN` — Variable Star Analysis & Photometry (merged from VSTarget)

| ID | Requirement | Priority |
|---|---|---|
| VST-AN-010 | The system shall retrieve calibrated FITS images for a completed observation plan from a remote-telescope data server via FTP/FTPS/SFTP (traces to `EXT-080`, `EXT-120`). | MVP |
| VST-AN-020 | The system shall plate-solve retrieved or captured variable-star images via the existing solver integration (traces to `PLT-010`) to add WCS coordinates. | MVP |
| VST-AN-030 | The system shall produce a registered, mean-stacked image from a set of same-target, same-filter frames for photometric signal-to-noise improvement. This is a bounded photometric-analysis operation, distinct from general-purpose deep-sky image stacking, which remains out of scope. | MVP |
| VST-AN-040 | The system shall perform aperture photometry on a target star against AAVSO VSP comparison stars, using ensemble linear-regression differential photometry. | MVP |
| VST-AN-050 | The system shall generate an AAVSO WebObs Extended-format measurement report from photometry results. | MVP |
| VST-AN-060 | The system shall compute per-telescope, per-filter transformation coefficients from standard-field observations (e.g. M67, NGC 7790, M11, NGC 1252, NGC 3532, Melotte 111, Landolt fields), with interactive review and rejection of outlier measurements. | P2 |
| VST-AN-070 | The system shall apply stored transformation coefficients to multi-filter observations prior to report generation. | P2 |
| VST-AN-080 | The system shall provide an exposure-time calculator calibrated to the configured telescope/filter throughput. | P2 |
| VST-AN-090 | The system shall generate an AAVSO-style finder chart image for a variable-star field, given a target name or coordinates, showing comparison stars and their magnitudes. | P2 |

---

## 5. Non-Functional Requirements

### 5.1 `NFR-PERF` — Performance

| ID | Requirement | Priority |
|---|---|---|
| NFR-PERF-010 | The system shall render a newly downloaded full-frame image (up to at least 100 MP monochrome/OSC sensors) in the imaging tab within 3 seconds on reference hardware. | MVP |
| NFR-PERF-020 | The system shall maintain UI responsiveness (input latency under 200 ms) during active image download, plate solving, or autofocus execution, by performing these operations off the UI thread. | MVP |
| NFR-PERF-030 | The system's memory footprint shall remain stable (no unbounded growth) over a continuous 8-hour imaging session. | MVP |

### 5.2 `NFR-REL` — Reliability

| ID | Requirement | Priority |
|---|---|---|
| NFR-REL-010 | The system shall survive a transient (under a configurable timeout) INDI or Alpaca device disconnect during a running sequence without terminating the sequence, retrying the operation per configured policy. | MVP |
| NFR-REL-020 | The system shall never leave a running sequence silently stalled; any blocking condition (device error, guiding loss, safety abort) shall surface to the user within a bounded time. | MVP |
| NFR-REL-030 | The system shall be capable of running a single sequence unattended for at least 10 continuous hours without requiring restart. | MVP |
| NFR-REL-040 | The system shall persist in-progress sequence state such that an application crash does not lose the record of already-completed frames. | P2 |

### 5.3 `NFR-PORT` — Portability

| ID | Requirement | Priority |
|---|---|---|
| NFR-PORT-010 | The system shall build and run from a single shared codebase across Windows, macOS, and Linux, with platform-specific code isolated to a defined platform-abstraction layer. | MVP |
| NFR-PORT-020 | Any feature unavailable on a given platform shall be explicitly documented, with the UI disabling rather than silently failing the corresponding control. | MVP |

### 5.4 `NFR-EXT` — Extensibility

| ID | Requirement | Priority |
|---|---|---|
| NFR-EXT-010 | Adding a new device backend or sequencer instruction via the plugin API (`PLUG-010`/`PLUG-020`) shall not require modifying or recompiling core application code. | P2 |

### 5.5 `NFR-USE` — Usability

| ID | Requirement | Priority |
|---|---|---|
| NFR-USE-010 | The system shall provide a guided first-run equipment-setup flow covering profile creation and connecting each core device type. | P2 |
| NFR-USE-020 | The system shall provide a guided flat-capture flow requiring no manual exposure-time calculation from the user (traces to `CAL-010`). | MVP |

### 5.6 `NFR-I18N` — Localization

| ID | Requirement | Priority |
|---|---|---|
| NFR-I18N-010 | All user-facing UI strings shall be externalized into a translatable resource format from initial implementation, even where only English is shipped in v1. | MVP |

### 5.7 `NFR-SEC` — Security

| ID | Requirement | Priority |
|---|---|---|
| NFR-SEC-010 | The system shall not transmit equipment-profile credentials or location data to any external service without explicit user configuration and consent. | MVP |
| NFR-SEC-020 | The system shall document the security implications of exposing an INDI server or Alpaca device over a WAN and shall not itself weaken a network-exposed device's authentication where the backend protocol supports it. | P2 |

### 5.8 `NFR-OFFLINE` — Offline Operation

| ID | Requirement | Priority |
|---|---|---|
| NFR-OFFLINE-010 | Core sky-atlas search/filter/chart functions (`SKY` domain) shall function with no internet connection present. | MVP |
| NFR-OFFLINE-020 | At least one supported plate-solving path (`PLT-020`) shall function with no internet connection present. | MVP |

### 5.9 `NFR-INSTALL` — Installability

| ID | Requirement | Priority |
|---|---|---|
| NFR-INSTALL-010 | The system shall provide a Windows installer (MSI or equivalent) requiring no manual dependency installation by the user. | MVP |
| NFR-INSTALL-020 | The system shall provide a signed and notarized macOS installer (.dmg or .pkg) requiring no manual dependency installation by the user. | MVP |
| NFR-INSTALL-030 | The system shall provide at least one Linux distribution format (AppImage, Flatpak, or native package) requiring no manual dependency installation beyond a documented INDI-server prerequisite where applicable. | MVP |

---

## 6. Requirement Summary Counts (for RTM Seeding)

| Domain | Requirement Count | MVP | P2 | P3 |
|---|---|---|---|---|
| ARCH | 8 | 7 | 1 | 0 |
| OBS | 8 | 0 | 8 | 0 |
| EQP (generic + device) | 25 | 17 | 8 | 0 |
| PROF | 9 | 8 | 1 | 0 |
| IMG | 10 | 8 | 2 | 0 |
| SEQ | 9 | 8 | 0 | 1 |
| SEQ-ADV | 10 | 0 | 9 | 1 |
| SKY | 9 | 6 | 3 | 0 |
| FRAME | 6 | 0 | 5 | 1 |
| SKYMAP | 6 | 3 | 3 | 0 |
| SCHED | 10 | 8 | 2 | 0 |
| CAL | 5 | 4 | 1 | 0 |
| FOC | 8 | 5 | 3 | 0 |
| PLT | 6 | 5 | 1 | 0 |
| MFLIP | 4 | 0 | 4 | 0 |
| GUIDE | 6 | 4 | 2 | 0 |
| DOME | 3 | 0 | 3 | 0 |
| SAFE | 10 | 2 | 5 | 3 |
| HIST | 4 | 0 | 3 | 1 |
| META | 5 | 3 | 1 | 1 |
| NOTIF | 3 | 0 | 1 | 2 |
| PLUG | 5 | 0 | 5 | 0 |
| UI | 3 | 0 | 2 | 1 |
| LOG | 4 | 3 | 1 | 0 |
| LIB | 14 | 9 | 4 | 1 |
| VST | 8 | 7 | 1 | 0 |
| VST-AN | 9 | 5 | 4 | 0 |
| NFR-PERF | 3 | 3 | 0 | 0 |
| NFR-REL | 4 | 3 | 1 | 0 |
| NFR-PORT | 2 | 2 | 0 | 0 |
| NFR-EXT | 1 | 0 | 1 | 0 |
| NFR-USE | 2 | 1 | 1 | 0 |
| NFR-I18N | 1 | 1 | 0 | 0 |
| NFR-SEC | 2 | 1 | 1 | 0 |
| NFR-OFFLINE | 2 | 2 | 0 | 0 |
| NFR-INSTALL | 3 | 3 | 0 | 0 |
| **Total** | **227** (exact sum of the rows above; `EXT` requirements are not counted here, see Section 3) | | | |

---

## 7. Path to SDD / Traceability Matrix

1. **SDD** — One architecture/component section per domain in Sections 4–5, describing how the device-abstraction layer (`ARCH`), plugin framework (`PLUG`), and per-domain services satisfy the requirements above.
2. **Traceability Matrix** — A row per requirement ID in this document, mapped to its SDD component(s) and verifying test case(s); Section 6's counts are the expected row totals per domain, useful for sanity-checking matrix completeness.

---

*This document is a living draft. Requirement wording, priorities, and the `SEQ-ADV` instruction/trigger/condition catalog in particular should be reviewed against current NINA behavior and INDI/Alpaca capability coverage before being frozen for SDD authoring.*
