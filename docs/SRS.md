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

This SRS decomposes the requirement domains identified in the [Project Scope Document](PSD.md) (Sections 8–9) into individually numbered, verifiable requirements. Every requirement ID is prefixed with the domain code established in the scope document (e.g. `SES`, `NFR-REL`) so it can be carried forward unchanged into the SDD and Requirements Traceability Matrix. **`SEQ`/`SEQ-ADV` is retired and replaced by `SES`** ("Sessions"), matching the scope document's Section 8.1 rename of the Sequence screen to Sessions and its retirement of the separate basic/advanced split — there is no `SEQ` or `SEQ-ADV` prefix anywhere in this revision.

### 1.2 Scope

Covers all functional domains (`ARCH`, `EQP`, `PROF`, `OBS`, `IMG`, `SES`, `SKY`, `FRAME`, `SKYMAP`, `SCHED`, `CAL`, `FOC`, `PLT`, `MFLIP`, `GUIDE`, `DOME`, `SAFE`, `HIST`, `META`, `NOTIF`, `PLUG`, `UI`, `LOG`, `LIB`) and non-functional domains (`NFR-PERF`, `NFR-REL`, `NFR-PORT`, `NFR-EXT`, `NFR-USE`, `NFR-I18N`, `NFR-SEC`, `NFR-OFFLINE`, `NFR-INSTALL`) defined in the scope document. Out-of-scope items (Section 5 of the scope document) are not addressed here. **`VST`/`VST-AN`** (variable-star target planning and photometric analysis) are **not** covered here — they are the VSTarget plugin's own requirements, decomposed in [`docs/plugins/vstarget/SRS.md`](../plugins/vstarget/SRS.md) against this document's `PLUG` domain rather than embedded in it.

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

Equipment connection and control; guided imaging capture; basic and advanced sequencing; target planning via sky atlas and framing assistant; calibration frame automation; autofocus; plate solving; meridian flip automation; guiding coordination; dome synchronization; safety/weather monitoring; session history; metadata-rich image output; notifications; a plugin framework; UI theming; diagnostics/logging; a merged image-library subsystem (repository cataloging, deduplication, smart-telescope ingestion, master-calibration processing, quality metrics, cloud sync); a live interactive star-map/planetarium view; a multi-night observatory scheduler; and multi-mount observatory management (multiple independent telescopes coordinated within one application instance).

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

**`EXT-100` is retired** (left as a gap rather than renumbering, matching this document's ID conventions elsewhere): it covered the AAVSO Target Tool/VSP API, which is not a Galileo-core-wide integration — only the VSTarget plugin uses it, so it now lives as `VST-EXT-010` in [`docs/plugins/vstarget/SRS.md`](../plugins/vstarget/SRS.md). `EXT-110` (Simbad) and `EXT-120` (SFTP) stay here and are reworded to drop their AAVSO-specific framing, since both are genuinely shared infrastructure — `EXT-110` also backs `SKY-100`'s fallback lookup, and `EXT-120`'s SFTP adapter lives in core `galileo.library.adapters` (SDD Section 4.23), reused by the plugin rather than owned by it.

| ID | Requirement | Priority |
|---|---|---|
| EXT-010 | The system shall provide a graphical desktop user interface as the sole primary *interactive* interface for equipment control, sequencing, and other live workflows; there is no requirement for these interactive workflows to be CLI- or headless-driven in v1. Specific domain-core batch functions that don't require interactive equipment control — e.g. repository ingest (`LoadRepo`-equivalent, `LIB-010`) and calibration-frame creation/application (`Calibrate`-equivalent, `LIB-050`/`LIB-060`) — shall be selectively exposed as standalone command-line utilities to facilitate scheduled/automated batch processes, per `EXT-140`. | MVP |
| EXT-020 | The system shall connect to device drivers only via an INDI server (TCP, INDI XML protocol) or an Alpaca device (HTTP/REST, JSON, per the ASCOM Alpaca specification, including UDP discovery). | MVP |
| EXT-030 | The system shall support connecting to an INDI server or Alpaca device on the local machine or over a LAN/WAN network address. | MVP |
| EXT-040 | The system shall interoperate with external plate-solving engines via their documented command-line or local HTTP interfaces (e.g. ASTAP, astrometry.net local solve, PlateSolve2-compatible solvers), configurable per installation. | MVP |
| EXT-050 | The system shall interoperate with external autoguiding applications via their documented control protocol (e.g. a PHD2-compatible JSON-RPC event/command interface). | MVP |
| EXT-060 | The system shall write image files in FITS format only, to a user-configured filesystem location. FITS shall be the sole supported image file format; no other format (e.g. XISF) is supported. | MVP |
| EXT-070 | The system shall support outbound notification integrations (e.g. webhook, email, push-notification service) as configurable, optional endpoints. | P3 |
| EXT-080 | The system shall connect to smart-telescope network shares via SMB/CIFS (e.g. SEESTAR, StellarMate) and via FTP/FTPS (e.g. DWARF, iTelescope) for remote file browsing and download. | MVP |
| EXT-090 | The system shall synchronize repository contents with Google Cloud Storage via its documented API, authenticated per user-supplied credentials. | P2 |
| EXT-110 | The system shall query the Simbad astronomical database for target coordinate/magnitude lookup. | MVP |
| EXT-120 | The system shall retrieve calibrated FITS images from a remote-telescope data server via SFTP, in addition to the FTP/FTPS access already required by `EXT-080`. | MVP |
| EXT-130 | The system shall query the Open-Meteo API for location geocoding and weather-forecast data. | P2 |
| EXT-140 | The system shall provide standalone command-line programs for selected batch/automation functions that don't require interactive equipment control — at minimum repository ingest (`LIB-010`/`LIB-130`), calibration-frame creation/application (`LIB-050`/`LIB-060`/`LIB-130`), and cloud sync (`LIB-120`) — matching the pattern of AstroFiler's own `commands/` utilities (e.g. `LoadRepo`, `Calibrate`; Project Scope Document, Section 6.2), runnable independent of the GUI (e.g. from a cron job or systemd timer on a headless Raspberry Pi at the Pier). | P2 |
| EXT-150 | The system shall optionally query the Telescopius API for object search/target-suggestion data and observing-list import (traces to `SKY-110`/`SKY-120`), authenticated exclusively via a user-supplied Telescopius API key entered in Options — Telescopius access is Patron/Sponsor-gated with no free tier (Project Scope Document, Section 6.9), so Galileo neither bundles nor proxies a shared credential, and this integration shall remain fully optional: its absence or unavailability shall not degrade `SKY-010`/`SKY-070`/`SKY-100`'s offline-first behavior. | P2 |

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
| EQP-070 | For every supported device category, the system shall display the selected device's driver name/information and driver version in its equipment panel. Where the backend allows it (INDI `DRIVER_INFO`, ASCOM `DriverInfo`/`DriverVersion`), this shall be available as soon as the device is selected, before it is connected. | MVP |

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
| EQP-MNT-050 | On completion of a slew, the system shall enable mount tracking at the rate appropriate to the target: the lunar rate where the target is the Moon, the solar rate where it is the Sun, and the sidereal rate otherwise. The rate shall be selected before tracking is enabled, and a mount that cannot select a rate shall still be left tracking (traces to `EQP-MNT-010`, `IMG-140`). | MVP |
| EQP-FW-010 | The system shall enumerate configured filter names/slots and issue filter-change commands, exposing change-in-progress status. | MVP |
| EQP-FW-020 | The system shall allow per-filter focus-offset configuration for use by the autofocus and filter-change workflows. | MVP |
| EQP-FOC-010 | The system shall issue absolute and relative focuser move commands and display current position and temperature (where supported). | MVP |
| EQP-FOC-020 | The system shall support configurable focuser backlash compensation applied to move commands. | P2 |
| EQP-FOC-030 | The system shall clamp absolute and relative focuser move commands to the device's valid travel range (0 to the backend-reported MaxStep), rather than issuing an out-of-range command unchecked, regardless of whether the underlying transport is known to protect itself. | MVP |
| EQP-ROT-010 | The system shall issue rotator move-to-angle commands and display current mechanical/sky position angle. | P2 |
| EQP-GDR-010 | The system shall expose guider connect/start-guiding/stop-guiding/dither controls, delegating to the external guiding interface (`GUIDE` domain). | MVP |
| EQP-SW-010 | The system shall enumerate switch/relay devices and their read/write state, supporting both boolean and analog (variable) switches. | P2 |
| EQP-FP-010 | The system shall control an electroluminescent/flat-panel device's cover open/close (where supported) and brightness level. | MVP |
| EQP-WX-010 | The system shall poll and display weather-device readings (e.g. cloud cover, wind, humidity, temperature, rain) at a configurable interval. | P2 |
| EQP-DOME-010 | The system shall issue dome slew-to-azimuth, open/close-shutter, and park commands and display current azimuth and shutter state. | P2 |
| EQP-SAFE-010 | The system shall poll a connected safety-monitor device's SAFE/NOT-SAFE state, and its accompanying human-readable explanation string where the driver provides one, at a configurable interval, and surface state changes (with explanation) to the sequencer (traces to `SAFE-010`). | P2 |

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
| PROF-100 | The system shall allow one or more optical tubes to be defined per Pier, each with a name, focal length, aperture, optical system (Newtonian, Schmidt-Cassegrain, Mak-Cassegrain, Refractor, or Other), and image alignment (reversed and/or inverted), and shall allow any device already configured on that Pier to be associated with a tube. Optics is an Equipment-section category rather than a device category (`ARCH-010`): it supplies the telescope/lens end of the optical train in `PROF-070`. | MVP |
| PROF-110 | The system shall provide a selector in the top bar, beside the Pier selector, listing the selected Pier's optical tubes (`PROF-100`) so the user can choose which one the current screen works with. It shall be shown on the Framing, Imaging and Solve screens, and only those; with no tubes defined it shall remain visible but disabled. | MVP |
| PROF-120 | The system shall provide a Camera selector in the top bar, beside the optical-tube selector, listing the selected Pier's configured cameras, and shall show it on exactly the screens that show the optical-tube selector. It shall be shown whatever the number of cameras configured, shall indicate for each whether that camera is connected, and with none configured shall remain visible but disabled. The camera chosen shall be the one the capture screens use, and a screen refusing to capture shall name the selected camera (traces to `PROF-110`, `EQP-CAM-010`). | MVP |

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
| OBS-090 | The system shall allow an Observatory record to carry the operator's own contact details — email address, phone/SMS number, and which channel(s) `NOTIF` should use (email, text, or both) — since being notified is scoped to the person running the Observatory, not to an individual Pier within it (traces to `NOTIF-020`, `NOTIF-040`). | P2 |

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
| IMG-110 | The system shall let the user turn on debayering of the displayed frame from a one-shot-colour camera, using a Bayer pattern (RGGB, GRBG, GBRG or BGGR) that the user sets per camera on its Equipment page and that defaults to RGGB. Debayering shall not alter the frame's raw pixel data, statistics or saved file (traces to `IMG-020`). | MVP |
| IMG-120 | The system shall detect whether the displayed frame is portrait or landscape and lay the imaging tab out for it: for a portrait frame the preview shall be a full-height column one third of the tab's width, with the mount nudge pad, histogram, progress display and log moved to the left of it, beside the capture settings. A checkbox shall let the user choose portrait or landscape manually instead of following the frame (traces to `IMG-010`). | P2 |
| IMG-130 | The system shall provide a mount nudge pad (N/S/E/W) on the imaging tab that moves the connected mount briefly, at a user-chosen speed and duration, while exposures are in progress, with a control to stop all motion. Axis directions shall match the Mount page's jog pad (traces to `EQP-MNT-010`). | P2 |
| IMG-140 | The system shall keep a current object for each Pier, set to the item most recently selected in the Star Atlas and shown at the top right of the window. Frames the imaging tab saves and the frames captured for plate solving shall be named after it, and Capture & Solve with the Slew to Target action shall slew the mount to its coordinates and correct until the solution is within the accuracy of them (traces to `SKYMAP-010`, `PLT-070`). | P2 |
| IMG-150 | The imaging tab shall let the user set the number of frames one Capture takes and the camera gain to use, take that many frames sequentially with the tab's settings, and stop a series on request. It shall offer an option, on by default, to write each captured frame to a scratch folder and register it in the image library so it appears on the library's Images screen. Frames written by the imaging tab shall carry every FITS header card the application can determine, including every card the library derives file and folder names from (traces to `META-010`, `LIB-150`). | P2 |
| IMG-160 | The imaging tab shall offer a live-stacking option which, for a capture run of more than two frames, shall register each captured frame against the first of the run and combine it into a running mean that replaces the displayed frame, rather than each exposure discarding the last. The stack shall be saveable both to the image library and to a file of the user's choosing, and the saved stack shall record the number of frames combined and the total integration time. Individual frames shall continue to be catalogued separately (traces to `IMG-010`, `IMG-150`). | P2 |
| IMG-170 | An Imaging settings screen shall let the user set a desired FITS sample format (BITPIX) for frames the imaging tab saves, offered as "Auto" (the smallest portable format that fits each frame without losing data) or a fixed 8, 16, 32 or -32; the fixed choices shall clip out-of-range values and round a float to the nearest integer rather than wrapping or raising. No frame the application writes, under any setting, shall use a 64-bit sample format, which common solving and analysis tools cannot read (traces to `META-010`). | P2 |
| IMG-180 | The imaging tab shall provide a Framing… control that opens the Framing Assistant (`FRAME-070`) against the currently selected camera/optical train for immediate-imaging use, including defining and, where a mosaic grid is defined, running a mosaic capture directly from the tab (mosaic execution traces to `FRAME-090`). | MVP |

### 4.5 `SES` — Sessions (Execution Engine, formerly `SEQ`)

Presented to the user as the **Sessions** screen (Project Scope Document, Section 8.1), renamed from "Sequence" to align with AstroFiler's session terminology (`LIB`). This section covers execution of an already-built session; authoring, per-Pier ownership, templates, and scheduling are Section 4.5a; the nested instruction/condition/trigger blocks a session may contain are Section 4.6.

| ID | Requirement | Priority |
|---|---|---|
| SES-010 | The system shall allow definition of a session as an ordered list of action blocks (`SES-130`), each contributing its own parameters to the session's execution (e.g. an Image block's exposure count, exposure time, filter, and binning). | MVP |
| SES-020 | The system shall support dynamic file-naming macros (e.g. target name, filter, date, frame number, frame type) applied to saved files. | MVP |
| SES-030 | The system shall execute a defined session start-to-finish without further user interaction, capturing and saving each configured frame. | MVP |
| SES-040 | The system shall allow a running session to be paused, resumed, and stopped by the user. | MVP |
| SES-050 | The system shall display live session progress (current block, frame N of M, elapsed/remaining estimate). | MVP |
| SES-060 | The system shall persist a session definition for reuse (traces to the Save control, `SES-110`). | MVP |
| SES-070 | The system shall record, per captured frame, sufficient metadata to reconstruct which session and block produced it (traces to `META` domain). | MVP |
| SES-080 | The system shall continue to the next block and log a recoverable error rather than terminate the session, when a single non-fatal capture error occurs. | MVP |
| SES-090 | The system shall support running capture sessions in parallel across two or more optical trains (`PROF-080`) sharing the same mount, using a lead/follower model: one optical train's job defines the target and scheduling criteria (the lead), while the others (followers) capture in parallel; shared mount-related events (slew, dither, plate-solve/align, meridian flip) are synchronized across all participating trains, matching the EKOS multi-train pattern. | P3 |

### 4.5a `SES` — Sessions Screen (Authoring, Per-Pier Ownership, Templates, Scheduling)

New scope versus the former `SEQ`/`SEQ-ADV` split (Project Scope Document, Section 8.1–8.2): the Sessions screen is Pier-scoped, drag-and-drop, block-based, and a session is inert (no side effect) until explicitly scheduled.

| ID | Requirement | Priority |
|---|---|---|
| SES-100 | The system shall scope sessions per Pier: the Sessions screen shall display only the currently-selected Pier's own sessions, and switching the active Pier shall switch the whole set of session regions shown. | MVP |
| SES-110 | The system shall display multiple concurrent sessions as independently bounded, vertically-scrollable regions on the Sessions screen, each with its own Save, Save as Template, Load from Template, Schedule, and Delete controls. | MVP |
| SES-120 | The system shall provide a single right-hand action palette from which blocks are dragged into a session region, insertable before, after, or between existing blocks, and freely reorderable within the region afterward. | MVP |
| SES-130 | The system shall provide, at minimum, the following action blocks in the palette: Target (set active target and slew), Image (capture parameters mirroring the Imaging tab: exposure time, count, filter, binning, gain/offset, frame type; a Framing… control opening the Framing Assistant to set the block's target frame box, traces to `FRAME-070`), Filter Change, Cool Camera/Warm Camera (CCD setpoint temperature plus wait-for-stabilization), Autofocus, Plate Solve, Guide Start/Guide Stop, Dither (also selectable inline as an Image-block option), Flat Capture, and Park Mount/Unpark Mount. | MVP |
| SES-140 | The system shall provide, at minimum, the following additional action blocks: Meridian Flip and Dome Open/Close/Sync. | P2 |
| SES-150 | The system shall provide a Notification action block that sends an alert at that point in the session via the owning Observatory's configured contact channel(s) (traces to `NOTIF-010`, `OBS-090`). | P3 |
| SES-160 | The system shall create a new session pre-populated with a `Target: <name>` block (set active target and slew) when a target is selected on the Targets/Sky Atlas screen (`SKY`), and shall provide an "Add Session" context-menu item that creates an equivalent empty session for manual authoring. | MVP |
| SES-170 | The system shall enforce block-ordering integrity rules (e.g. a Plate Solve block requires a preceding Target block) at block-insertion time and/or session-run time, rather than allowing an invalid session to be built or scheduled. | MVP |
| SES-180 | The system shall allow a session's blocks to be saved to a reusable template (the Save as Template control) storing its Target block as a generic placeholder rather than a specific target, so the template captures a repeatable procedure rather than a one-off plan. | P2 |
| SES-190 | The system shall, when Load from Template is used on a session region that already has a concrete Target block, substitute the template's placeholder with that existing Target block and append the template's remaining blocks in their saved order, leaving the region's other existing blocks (if any) untouched. Load from Template shall be unavailable on a region with no Target block yet. | P2 |
| SES-200 | The system shall submit a session to the Scheduler (`SCHED-010`) only when its region's Schedule control is used; authoring a session, including a fully built-out one, shall have no other side effect — it shall neither run nor queue until Schedule is used. | MVP |
| SES-210 | The system shall, once a session is scheduled, make its region read-only (blocks no longer draggable, reorderable, or editable) and render its boundary distinctly (e.g. red) to indicate it is live rather than a draft; the region's Schedule control shall become a Deschedule control which withdraws the job from `SCHED` and returns the region to its normal, editable state. | MVP |
| SES-220 | The system shall allow a session region to be deleted via its Delete control. | MVP |
| SES-230 | Where an Image block's Framing… control (`SES-130`) defines a mosaic grid, the system shall follow the mosaic capture execution model (`FRAME-090`) for that block's execution instead of single-target capture. | P2 |

### 4.6 `SES` — Sessions (Nested Instruction/Condition/Trigger Blocks, formerly `SEQ-ADV`)

The former `SEQ-ADV` domain is retired as a **separate** editor/mode — there is no longer a distinct "advanced sequence" screen or migration path between a basic and an advanced form (the former `SEQ-ADV-020` instruction-category catalog and `SEQ-ADV-060` template capability are superseded by `SES-130`/`SES-140`'s action-block catalog and `SES-180`/`SES-190`'s template controls respectively; `SEQ-ADV-100`'s basic-to-advanced migration converter has no remaining referent and is dropped outright). What remains distinct here is the nested instruction/condition/trigger *block* catalog itself — the one part of the former advanced sequencer that is still conceptually separate from a plain action block (Section 4.5a) — available from the same single palette, not a separate mode.

| ID | Requirement | Priority |
|---|---|---|
| SES-300 | The system shall allow instruction, condition, and trigger blocks to be nested within container blocks (e.g. a Loop block) placed among the ordinary action blocks in a session, rather than requiring a separate advanced-mode editor or screen. | P2 |
| SES-310 | The system shall provide, at minimum, the following loop/wait blocks: Loop For N, Loop Until Time, Wait Until Time, Wait For Altitude, loop-while-safe, and loop-while-above-horizon. | P2 |
| SES-320 | The system shall provide, at minimum, the following trigger blocks: Autofocus-on-Trigger (conditions: HFR increase, temperature change, time interval, filter change), Meridian-Flip-on-Trigger, and Wait-for-Safe/Abort-if-Unsafe (safety-monitor-unsafe-abort). | P2 |
| SES-330 | The system shall allow instruction, condition, and trigger blocks to be nested within container blocks to arbitrary depth. | P2 |
| SES-340 | The system shall allow a plugin to register a new instruction, condition, or trigger block type that appears alongside built-in ones in the palette (traces to `PLUG-020`). | P2 |
| SES-350 | The system shall visually indicate the currently executing block during a running session. | P2 |
| SES-360 | The system shall allow editing of a session's not-yet-executed blocks while the session is running. | P3 |

### 4.7 `SKY` — Sky Atlas / Targets

Presented as the **Targets** screen (Project Scope Document, Section 6.4/6.9), wiring in and substantially augmenting the visibility/thumbnail logic ported directly from Obsy. `SKY-100` is reworded in this revision: the internal offline database is now the primary object-name search source and Simbad is the fallback, reversing the priority the previous revision specified (see `SKY-100`'s note).

| ID | Requirement | Priority |
|---|---|---|
| SKY-010 | The system shall provide a searchable deep-sky object catalog of at least 10,000 objects, including common name and catalog designations (Messier, NGC/IC, etc.), bundled/cached locally as the primary, offline-capable source for search, filter, and object-name lookup (`SKY-100`). | MVP |
| SKY-020 | The system shall filter the catalog by object type, magnitude, size, and current/tonight visibility. | MVP |
| SKY-030 | The system shall plot an object's altitude over the current night for the configured observing location. | MVP |
| SKY-040 | The system shall allow definition of a custom horizon profile (obstruction line) per observing location and reflect it in altitude charts and visibility filtering. | P2 |
| SKY-050 | The system shall allow selecting an object from the atlas to populate it as a session/framing target (traces to `SES-160`). | MVP |
| SKY-060 | The system shall support one or more configured observing locations, each with latitude, longitude, and elevation. | MVP |
| SKY-070 | The system shall operate using a locally cached catalog with no live internet dependency for core search/filter/chart functions (traces to `NFR-OFFLINE`). | MVP |
| SKY-080 | The system shall fetch and cache a sky-survey cutout thumbnail image (e.g. via a DSS/STScI cutout service) for a catalog object when it is added to a user's active target list, cropping the fetched segment to a field size derived from the object's own angular size — rather than a fixed cutout window — so the thumbnail reasonably frames both large and small objects, for offline reference thereafter. | MVP |
| SKY-090 | The system shall resolve a location name/address to latitude, longitude, and timezone via a geocoding lookup (traces to `EXT-130`), as a convenience when configuring an observing location (`SKY-060`). | P2 |
| SKY-100 | The system shall resolve an object-name search primarily via the offline catalog (`SKY-010`), falling back to a live Simbad lookup (traces to `EXT-110`) only when the offline catalog has no match for the searched name and internet is available — **this reverses the previous Simbad-first/catalog-fallback design** so that ordinary object search, not only catalog browse/filter/chart, satisfies `NFR-OFFLINE-010`'s no-internet guarantee. | MVP |
| SKY-110 | The system shall optionally augment object search with the Telescopius API's target-search/suggestion data (traces to `EXT-150`) when the user has configured their own Telescopius API key, never as a substitute for the offline-first/Simbad-fallback path of `SKY-010`/`SKY-100`. | P2 |
| SKY-120 | The system shall allow importing a user's existing Telescopius observing list into a Galileo session/target list (traces to `EXT-150`) when a Telescopius API key is configured. | P2 |

### 4.8 `FRAME` — Framing Assistant

**Invoked contextually, not a primary-navigation section (`FRAME-070`):** the Framing Assistant is opened from the Imaging tab's Framing… control (`IMG-180`) or a Session Image block's own Framing… control (`SES-130`), never presented as its own top-level screen. Both entry points share every requirement below and the same underlying design; each retains its own independent framing/mosaic state (the Imaging tab's current immediate-capture setup is separate from any given Session Image block's own stored definition).

| ID | Requirement | Priority |
|---|---|---|
| FRAME-010 | The system shall display a field-of-view rectangle computed from the active camera's sensor dimensions and the active telescope's focal length, overlaid on a sky image. | MVP |
| FRAME-020 | The system shall support at least one online sky-survey image source and one offline/cached star-field rendering mode for the framing background. | MVP |
| FRAME-030 | The system shall allow the user to rotate the framing rectangle to preview a given camera/rotator position angle, where the active optical train has a rotator equipped (`EQP-ROT-010`); rotation shall be unavailable, not silently ignored, when no rotator is present. | MVP |
| FRAME-040 | The system shall support defining a mosaic as a grid of overlapping framing panels, with a pane-overlap percentage configurable on the Imaging settings screen (`IMG-170`'s kin) and shared by both Framing Assistant entry points (`FRAME-070`) rather than configured separately per entry point. | P2 |
| FRAME-050 | The system shall attach a defined framing target — a single frame, or, where a mosaic grid is defined (`FRAME-040`), the whole mosaic as one unit — to whichever context opened the Framing Assistant (the Imaging tab's current immediate-capture setup, `IMG-180`, or a Session Image block, `SES-130`) as that context's own capture target. **This supersedes an earlier "each mosaic panel sent to the sequencer as its own target" model**: a mosaic is now owned and captured by one Imaging-tab run or one Image block internally (traces to `FRAME-090`), not decomposed into separate per-panel targets upstream of capture. | P2 |
| FRAME-060 | The system shall overlay constellation lines and a coordinate grid on the framing view. | P2 |
| FRAME-070 | The system shall present the Framing Assistant only when invoked from the Imaging tab (`IMG-180`) or a Session Image block (`SES-130`), never as a primary-navigation section of its own, and shall return to whichever context opened it when closed. | MVP |
| FRAME-080 | The system shall provide a Compare Cameras control that overlays a field-of-view rectangle for every camera configured across every Pier in the current Observatory — not only the currently active one — with the survey image auto-scaled to the largest field size among them. | P2 |
| FRAME-090 | Where a run's or session block's target includes a defined mosaic grid (`FRAME-040`), the system shall slew to and capture one exposure at each pane in turn before repeating the pass for any additional exposures per pane, rather than completing all of one pane's exposures before moving to the next. The re-slew between passes is the mechanism that dithers a pane's frames against each other; it is distinct from and does not require a separate guider-dither command (`GUIDE-030`) between exposures of an unchanged target. | P2 |

### 4.8a `SKYMAP` — Interactive Star Map / Planetarium (KStars/EKOS-informed)

A live, rendered sky view — distinct from the catalog-based `SKY` and the FOV-preview `FRAME` — presented as a third peer-level sky-related panel.

| ID | Requirement | Priority |
|---|---|---|
| SKYMAP-010 | The system shall render an interactive, pannable, zoomable real-time sky view for the configured observing location and time, displaying stars down to a configurable magnitude limit, deep-sky objects, and the Sun/Moon/planets. | MVP |
| SKYMAP-020 | The system shall allow clicking an object on the sky map to identify it, and double-clicking to center and track it. | MVP |
| SKYMAP-030 | The system shall overlay constellation lines and a coordinate grid on the sky map, each independently toggleable. | MVP |
| SKYMAP-040 | The system shall display comets, asteroids, and artificial satellites on the sky map from a periodically updated orbital-elements source. | P2 |
| SKYMAP-050 | The system shall overlay the active optical train's field-of-view rectangle and the mount's current pointing position live on the sky map, sharing FOV geometry with `FRAME-010`. | P2 |
| SKYMAP-060 | The system shall allow slewing the connected mount directly to a location clicked or selected on the sky map. | P2 |
| SKYMAP-070 | The system shall allow a horizon obstruction table of azimuth/altitude pairs to be uploaded from a file for the Observatory (Options > Star Atlas), and shall shade the obstructed sky from the horizon up to each obstruction's altitude in a translucent colour on the sky map, toggleable with a "Horizon" option, so that stars behind it remain visible. | P2 |
| SKYMAP-080 | Where the "Do not slew where obstructed" option is enabled (Options > Planning) and a horizon obstruction table is defined, the system shall refuse any mount slew whose altitude/azimuth falls inside an obstruction and report the error "Unable to slew to that area, it is obstructed". | P2 |
| SKYMAP-090 | The system shall draw a labelled telescope reticle on the sky map for each Pier in the current Observatory, positioned where that Pier's mount reports it is pointing and, where the mount cannot be read, at the Pier's current object. A reticle shall be updated while its mount slews, so the slew's progress can be watched, and shall indicate both that a slew is running and the position it is heading for. The reticles shall be toggleable with a "Telescope markers" option (traces to `SKYMAP-050`, `IMG-140`). | P2 |

### 4.8b `SCHED` — Observatory Scheduler (KStars/EKOS-informed)

Multi-night/multi-target job scheduling, distinct from `SES`'s single-session execution ordering — a `SCHED` job references a `SES` session, submitted from that session's owning Pier's Sessions screen (`SES-200`), and triggers that session's execution when its constraints are met.

| ID | Requirement | Priority |
|---|---|---|
| SCHED-010 | The system shall provide a prioritized job queue where each job is a session (`SES`) submitted via its Schedule control, together with the target and a Pier/optical train (`PROF-080`) the session was authored against — traces to `OBS-070` when the Pier belongs to a multi-Pier Observatory. | MVP |
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
| CAL-060 | The system shall present the flat-wizard workflow within the Imaging tab (`IMG`) rather than as a separate top-level navigation section. | MVP |

### 4.10 `FOC` — Autofocus

| ID | Requirement | Priority |
|---|---|---|
| FOC-010 | The system shall run an autofocus routine that samples HFR at multiple focuser positions and fits a curve (e.g. V-curve/hyperbolic/parabolic) to determine best focus. | MVP |
| FOC-020 | The system shall move the focuser to the computed best-focus position and verify with a confirmation exposure. | MVP |
| FOC-030 | The system shall report autofocus failure (e.g. no valid curve fit, insufficient stars) distinctly from success, without leaving the focuser at an untested position. | MVP |
| FOC-040 | The system shall record each autofocus run's sample points and resulting curve for later review (traces to `HIST-020`). | P2 |
| FOC-050 | The system shall support autofocus invocation both manually (on demand) and via a session's Autofocus-on-Trigger block (traces to `SES-320`). | MVP |
| FOC-060 | The system shall apply the per-filter focus offset (`EQP-FW-020`) when switching filters without requiring a full autofocus run, where offsets are configured. | P2 |
| FOC-070 | The system shall allow configuration of autofocus parameters (step size, number of points, exposure time, backlash handling) per equipment profile. | MVP |
| FOC-080 | The system shall provide an aberration-inspection tool that computes per-region (at minimum 3-point or 4-point) HFR/tilt indicators across the frame, to help diagnose sensor tilt or collimation issues. | P2 |
| FOC-090 | The system shall provide a Focus screen that shows an autofocus run as it happens — the frame being measured, its star count, HFR and FWHM, and the HFR-against-position curve, with the fitted curve and best position once the run ends — whichever way the run was started (from that screen or by a sequencer trigger), and shall leave what it shows unchanged while no run is in progress. It shall let the user start a run (step size, number of points, exposure) and stop a run started from it, offering each control only when it can act (traces to `FOC-010`, `FOC-050`, `FOC-070`). | MVP |

### 4.11 `PLT` — Plate Solving

| ID | Requirement | Priority |
|---|---|---|
| PLT-010 | The system shall invoke a configured external plate-solving engine against a captured or supplied frame and return solved RA/Dec and rotation. | MVP |
| PLT-020 | The system shall support at least one local/offline solver and remain functional without an internet connection for plate solving (traces to `NFR-OFFLINE`). | MVP |
| PLT-030 | The system shall support a solve-and-sync workflow that syncs the mount's reported position to the solved coordinates. | MVP |
| PLT-040 | The system shall support a solve-and-center workflow that iteratively slews and re-solves until the target is within a configured tolerance of the frame center. | MVP |
| PLT-050 | The system shall report plate-solve failure distinctly from success and allow the invoking workflow (manual or sequencer) to react accordingly. | MVP |
| PLT-060 | The system shall allow configuration of solver search parameters (field-of-view hint, search radius, downsample) per equipment profile. | P2 |
| PLT-070 | The system shall provide a Solve screen that shows the frame being solved and its solution as a solve happens — whichever part of the application started it (that screen's own Capture & Solve or Load & Slew, or another workflow such as the sequencer) — and shall leave what it shows unchanged while the screen is not in view. From that screen the user shall be able to capture a frame with the selected camera and solve it, choose whether the mount is then synced, slewed back to the target, or left alone, stop a run in progress, and see each solution's position, its error against the target and a log of the run (traces to `PLT-010`, `PLT-030`, `PLT-040`, `PLT-050`). | MVP |

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
| GUIDE-070 | The Guider screen shall connect to the external guider by host and port alone (PHD2's event server; default port 4400) rather than by selecting a guiding device, save that host and port per Pier, and reconnect to a saved host when the Pier is loaded. A connection failure shall be reported on the screen, not raised. | MVP |
| GUIDE-080 | The Guider screen shall display the external guider's live data: its state (idle/prep/run), the guide-star image, a guide graph of RA/Dec error, SNR and correction pulses over time, a mount-drift scatter plot with target rings, the calibration plot, guide statistics (latest delta, pulse length, RMS per axis and total, SNR, star mass/HFD), scope/lens information from the selected optical tube and the guider's reported pixel scale, and the guider's event log. | MVP |
| GUIDE-090 | The Guider screen shall let the user connect/disconnect the guider's own equipment, loop exposures, start guiding (optionally recalibrating), stop, auto-select a star, dither, set the guide exposure, set the Dec guide mode and clear calibration, offering each control only when the guider can act on it and showing any command the guider rejects. | MVP |

### 4.14 `DOME` — Dome Control

Within a multi-Pier Observatory, a dome may be Pier-scoped (independent) or Observatory-scoped (one shared roof) per `OBS-050`; the requirements below apply per-dome regardless of scope.

| ID | Requirement | Priority |
|---|---|---|
| DOME-010 | The system shall support slaving dome azimuth to the mount's current pointing direction while tracking. | P2 |
| DOME-020 | The system shall synchronize dome shutter and park actions with sequence start/end and meridian-flip events, where enabled. | P2 |
| DOME-030 | The system shall allow dome slaving to be disabled for domes controlled by independent third-party slaving hardware/software. | P2 |

### 4.15 `SAFE` — Safety & Weather Monitoring

Within a multi-Pier Observatory, a safety-monitor may be Pier-scoped (independent) or Observatory-scoped (shared, triggering all member Piers per `OBS-040`) per `OBS-030`.

**Device tiers (reinforces `ARCH-010`: every safety-monitor input reaches Galileo through the device-abstraction layer, never a bespoke ad-hoc path).** Every safety-monitor input — hardware or software-computed — connects as a standard Safety Monitor device through the ordinary device-abstraction layer (`ARCH-010`): either a real external driver reached via `EXT-020` (INDI or Alpaca), or an in-process device backend a plugin registers through `PLUG-010` — the identical extension point every other device category already uses (traces to `ARCH-070`). There is no third, bespoke path that skips the port interface. Two tiers, distinguished by what's behind the reading, not by how Galileo talks to it:
- **Tier 1** — a hardware sensor with its own INDI/Alpaca driver (e.g. a rain sensor via an existing driver such as `indi-hydreon`).
- **Tier 2** — a software/ML-computed safety signal with no single physical sensor behind it (e.g. all-sky-camera cloud classification), exposed as a standard Safety Monitor device either by a dedicated external INDI/Alpaca driver process or by a plugin implementing the same port interface in-process (`PLUG-010`) — Galileo's safety module has no code path that can tell the two apart, by design.
- Both tiers report the same minimum interface: a SAFE/NOT SAFE state plus a human-readable explanation string, and both are equally trusted for automated abort decisions (`SAFE-010`) — the tier is about the underlying data source, not about how much Galileo trusts it, and not about which side of the device-abstraction boundary implements it.

| ID | Requirement | Priority |
|---|---|---|
| SAFE-010 | The system shall abort or pause a running sequence and park equipment when a connected safety-monitor device reports an unsafe condition, per configured policy. | P2 |
| SAFE-020 | The system shall log weather-device readings alongside session history for later correlation with image quality (traces to `HIST-010`). | P3 |
| SAFE-030 | The system shall allow configuration of which unsafe conditions trigger an automatic abort versus a warning-only notification. | P2 |
| SAFE-040 | The system shall prevent automatic sequence resumption after a safety abort until conditions are confirmed safe and, where configured, a user confirms resumption. | P2 |
| SAFE-050 | The system shall optionally display an internet-sourced weather forecast (traces to `EXT-130`) as a planning aid. This data source is advisory only and shall never be used as the sole basis for an automated safety abort — automated abort decisions (`SAFE-010`) shall be driven only by a connected safety-monitor device. | P2 |
| SAFE-060 | The system shall provide an independent heartbeat-timeout watchdog that, if the application stops sending heartbeats for a configurable period (e.g. due to a crash, hang, or lost network connection to a remote imaging host), autonomously parks the mount and then closes/parks the dome — distinct from, and in addition to, the weather-triggered abort path (`SAFE-010`). | MVP |
| SAFE-070 | The system shall connect to a Tier 1 hardware safety-monitor device (e.g. a rain sensor) exclusively via its INDI or Alpaca driver, per `EQP-SAFE-010`, and treat its SAFE/NOT-SAFE state as fully trusted input to automated abort decisions (`SAFE-010`). | P2 |
| SAFE-080 | The system shall connect to a Tier 2 software-computed safety-monitor device (e.g. an ML-based all-sky-camera cloud classifier) via the same device-abstraction path as Tier 1 (`EQP-SAFE-010`) — either an external INDI/Alpaca Safety Monitor driver, or an in-process device backend a plugin registers through `PLUG-010` implementing the identical port interface — and treat its SAFE/NOT-SAFE state as equally trusted for automated abort decisions (`SAFE-010`) regardless of which. Debouncing against a single borderline reading (avoiding state-flapping) is the reporting device backend's own responsibility, not Galileo's, since Galileo consumes only the backend's already-settled state. | MVP |
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

External delivery is narrowed to **email and/or text message (SMS)** as the two concrete channels (superseding the previous "e.g. webhook or push service" wording), delivered using the contact details configured on the Observatory the triggering Pier/session belongs to (`OBS-090`), not a separate per-notification contact configuration.

| ID | Requirement | Priority |
|---|---|---|
| NOTIF-010 | The system shall raise an in-app notification for session completion, session error/abort, and safety-triggered abort (traces to `SES-030`/`SES-080`, `SAFE-010`). | P2 |
| NOTIF-020 | The system shall support external delivery via email and/or text message (SMS), configurable by the user, delivering the same event set as `NOTIF-010`. | P3 |
| NOTIF-030 | The system shall allow notification events to be individually enabled/disabled per channel. | P3 |
| NOTIF-040 | The system shall read external-delivery contact details (email address, phone/SMS number, and which channel(s) to use) from the Observatory record (`OBS-090`) that owns the Pier/session raising the event, rather than maintaining a separate per-notification contact configuration. | P3 |

### 4.19 `PLUG` — Plugin Framework

Distinguishes **first-party, pre-loaded plugins** (shipped with Galileo — the VSTarget plugin, [`docs/plugins/vstarget/`](../plugins/vstarget/SRS.md), is the reference example, specified in its own document chain rather than here) from **third-party plugins** (discovered/installed from a repository, `PLUG-030`). The former requires only `PLUG-010`/`020`/`040`/`050`/`060`/`070`/`080` — the loader and extension-point mechanism — which is therefore MVP; the plugin *marketplace* (`PLUG-030`) is not needed for pre-loaded plugins and stays P2.

| ID | Requirement | Priority |
|---|---|---|
| PLUG-010 | The system shall expose a documented API allowing a plugin to register a new device backend implementing the `ARCH-010` abstraction — including a Safety Monitor device backend (traces to `SAFE-080`), which is trusted identically to an external INDI/Alpaca driver rather than treated as a special case. | MVP |
| PLUG-020 | The system shall expose a documented API allowing a plugin to register a new session action, instruction, condition, or trigger block type (traces to `SES-340`), or a new top-level or nested UI panel. | MVP |
| PLUG-030 | The system shall provide an in-app plugin manager to browse, install, update, and remove third-party plugins from a configured plugin repository. | P2 |
| PLUG-040 | The system shall load and unload plugins without requiring a full application rebuild, and shall isolate a plugin failure from crashing the core application. | MVP |
| PLUG-050 | The system shall version-check a plugin against the running application's plugin API version and warn on incompatibility. | MVP |
| PLUG-060 | The system shall ship one or more first-party plugins pre-loaded (not requiring download/install), each independently enabled or disabled by the user; a disabled pre-loaded plugin shall be fully inert (no UI, no background activity), and an enabled one shall be functionally indistinguishable from an equivalent capability built into core. | MVP |
| PLUG-070 | The system shall allow a plugin's registered UI panel to be inserted at either the primary navigation level (a top-level tab/section, peer to built-in ones) or the secondary level (nested within an existing section), as declared by the plugin. | MVP |
| PLUG-080 | The system shall expose, via `PluginContext`, a documented API for a plugin to invoke specific core services it has been granted access to (e.g. submitting a job to the `SCHED` queue) without those services being otherwise part of the plugin extension-point surface (`PLUG-010`/`020`). | MVP |

### 4.20 `UI` — Customization & Theming

| ID | Requirement | Priority |
|---|---|---|
| UI-010 | The system shall provide at least a light and a dark color theme, selectable by the user. | P2 |
| UI-020 | The system shall allow the imaging-tab panel arrangement to be customized (e.g. dockable/resizable panels) and persisted across restarts. | P2 |
| UI-030 | The system shall allow accent-color customization within a theme. | P3 |

### 4.21 `LOG` — Diagnostics & Logging

| ID | Requirement | Priority |
|---|---|---|
| LOG-010 | The system shall run a runtime logging service that writes structured, timestamped application and session logs — capturing all runtime log output across every module and severity, not only curated diagnostic events — to a datestamped file under the application's own `logs/` directory. | MVP |
| LOG-020 | The system shall provide an in-app log viewer with severity filtering (info/warning/error). | MVP |
| LOG-030 | The system shall capture unhandled exceptions to the log with sufficient detail (stack trace, active sequence step, connected-device state) to diagnose post-hoc. | MVP |
| LOG-040 | The system shall allow exporting a support bundle (recent logs plus non-sensitive configuration) for bug reports. | P2 |
| LOG-050 | The logging service shall reset (start a new, truncated) datestamped log file at the beginning of every application run, rather than appending to a prior run's log. | MVP |
| LOG-060 | The system shall display, on every Equipment device-category screen, a scrollable pane showing the most recent log lines (at least the last 10 visible at once) without requiring the user to open a separate log viewer. | P2 |

### 4.22 `LIB` — Image Library & Repository Management (merged from AstroFiler)

**`LIB-080` is retired** (left as a gap rather than renumbering, matching this document's ID conventions elsewhere): it specified a repository statistics dashboard (frame counts by object/filter/date/instrument, quality-metric trends), whose `StatsWidget` implementation and Library-screen tab were removed on request; retiring the requirement here brings the SRS/RTM back in line with that decision rather than leaving an MVP requirement permanently unmet with no code behind it and no one building toward it.

| ID | Requirement | Priority |
|---|---|---|
| LIB-010 | The system shall recursively scan a configured repository location, ingest discovered FITS files, and extract their header metadata into a catalog. XISF files shall also be ingested, converted best-effort to FITS at ingest time (Galileo's sole internal/output format per `EXT-060`) — an XISF file whose metadata or pixel data cannot be fully mapped shall still be converted with a logged warning identifying what was lost, rather than silently dropped or rejected outright. | MVP |
| LIB-020 | The system shall detect duplicate files within the repository via SHA-256 content hashing and allow the user to review and remove duplicates. | MVP |
| LIB-030 | The system shall automatically rename and organize ingested files into a configurable folder structure derived from FITS metadata (e.g. object, date, filter, session). | MVP |
| LIB-040 | The system shall automatically group and link related frames into sessions based on matching camera, binning, and temperature, plus acquisition date. | MVP |
| LIB-050 | The system shall create master bias, dark, and flat calibration frames from a linked calibration session. | MVP |
| LIB-060 | The system shall apply a matching master calibration frame set (dark subtraction, flat division) to a selected group of light frames in one user action. | MVP |
| LIB-070 | The system shall compute and store per-frame quality metrics (FWHM, HFR, eccentricity, SNR) for ingested frames, supporting later filtering and sorting by quality. | MVP |
| LIB-090 | The system shall browse and selectively download files from a SEESTAR or StellarMate smart telescope over SMB/CIFS (traces to `EXT-080`), enhancing headers as needed during ingest. | MVP |
| LIB-100 | The system shall browse and selectively download files from an iTelescope network share over FTPS (traces to `EXT-080`). | P2 |
| LIB-110 | The system shall browse and selectively download files from a DWARF smart telescope over FTP (traces to `EXT-080`), as an experimental capability. | P3 |
| LIB-120 | The system shall synchronize repository contents bidirectionally with Google Cloud Storage (traces to `EXT-090`), using content-hash comparison to avoid redundant transfer, with at least "complete," "backup only," and "on demand" sync profiles. | P2 |
| LIB-130 | The system shall expose repository scanning (`LIB-010`), calibration-frame creation/application (`LIB-050`/`LIB-060`), and cloud sync (`LIB-120`) as command-line-invocable operations, independent of the GUI, for scheduled/automated execution — matching AstroFiler's own `LoadRepo`/`Calibrate`/`CloudSync` command-line utilities (Project Scope Document, Section 6.2), which this requirement generalizes (traces to `EXT-140`). | P2 |
| LIB-140 | The system shall verify file integrity via stored content hashes on demand, flagging any repository file whose content no longer matches its recorded hash. | P2 |
| LIB-150 | The system shall automatically register each frame into the repository catalog as it is written to disk during a running session (`SES`), rather than requiring a separate manual or scheduled scan (`LIB-010`) to discover it. | MVP |
| LIB-160 | The system shall automatically create a session container grouping every frame acquired during one session-block execution, distinct from `LIB-040`'s post-hoc heuristic (camera/binning/temperature/date) grouping of files already in the repository — a session-block container is authoritative because it comes directly from `SES` execution, not inferred from file metadata. | MVP |

### 4.23 `VST` / `VST-AN` — Moved

Variable Star Target Planning and Variable Star Analysis & Photometry are no longer decomposed here — they are the VSTarget plugin's own requirements, specified in [`docs/plugins/vstarget/SRS.md`](../plugins/vstarget/SRS.md) Sections 4.1–4.2 against this document's `PLUG` domain (`PLUG-060`/`070`/`080`) and a small number of other core requirements consumed by reference (`SKY-030`, `EXT-080`, `EXT-110`, `EXT-120`, `PLT-010`, `SCHED-010`). This section number is kept as a placeholder rather than renumbered away, consistent with this document's ID-stability convention elsewhere (e.g. `SES`'s Section 4.5a).

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
| NFR-SEC-030 | User-supplied third-party service passwords (e.g. iTelescope's FTPS credential) shall be stored in the OS credential store, not in plaintext in an application config file; a plaintext credential left by an older version shall be migrated on next read and removed from the config file. | P2 |

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
| ARCH | 8 | 6 | 2 | 0 |
| OBS | 9 | 0 | 9 | 0 |
| EQP (generic + device) | 27 | 19 | 8 | 0 |
| PROF | 12 | 11 | 1 | 0 |
| IMG | 18 | 9 | 9 | 0 |
| SES (formerly `SEQ`/`SEQ-ADV`; Sections 4.5–4.6) | 30 | 17 | 10 | 3 |
| SKY | 12 | 8 | 4 | 0 |
| FRAME | 9 | 4 | 5 | 0 |
| SKYMAP | 9 | 3 | 6 | 0 |
| SCHED | 10 | 8 | 2 | 0 |
| CAL | 6 | 5 | 1 | 0 |
| FOC | 9 | 6 | 3 | 0 |
| PLT | 7 | 6 | 1 | 0 |
| MFLIP | 4 | 0 | 4 | 0 |
| GUIDE | 9 | 7 | 2 | 0 |
| DOME | 3 | 0 | 3 | 0 |
| SAFE | 10 | 2 | 5 | 3 |
| HIST | 4 | 0 | 3 | 1 |
| META | 5 | 3 | 1 | 1 |
| NOTIF | 4 | 0 | 1 | 3 |
| PLUG | 8 | 7 | 1 | 0 |
| UI | 3 | 0 | 2 | 1 |
| LOG | 6 | 4 | 2 | 0 |
| LIB | 15 | 10 | 4 | 1 |
| NFR-PERF | 3 | 3 | 0 | 0 |
| NFR-REL | 4 | 3 | 1 | 0 |
| NFR-PORT | 2 | 2 | 0 | 0 |
| NFR-EXT | 1 | 0 | 1 | 0 |
| NFR-USE | 2 | 1 | 1 | 0 |
| NFR-I18N | 1 | 1 | 0 | 0 |
| NFR-SEC | 3 | 1 | 2 | 0 |
| NFR-OFFLINE | 2 | 2 | 0 | 0 |
| NFR-INSTALL | 3 | 3 | 0 | 0 |
| **Total** | **258** (exact sum of the rows above; `EXT` requirements are not counted here, see Section 3; `VST`/`VST-AN` moved to the VSTarget plugin's own SRS, Section 4.23) | | | |

---

## 7. Path to SDD / Traceability Matrix

1. **SDD** — One architecture/component section per domain in Sections 4–5, describing how the device-abstraction layer (`ARCH`), plugin framework (`PLUG`), and per-domain services satisfy the requirements above.
2. **Traceability Matrix** — A row per requirement ID in this document, mapped to its SDD component(s) and verifying test case(s); Section 6's counts are the expected row totals per domain, useful for sanity-checking matrix completeness.

---

*This document is a living draft. Requirement wording, priorities, and the `SES` (Section 4.6) instruction/trigger/condition catalog in particular should be reviewed against current NINA behavior and INDI/Alpaca capability coverage before being frozen for SDD authoring.*
