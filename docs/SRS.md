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

Covers all functional domains (`ARCH`, `EQP`, `PROF`, `OBS`, `IMG`, `SES`, `SKY`, `WUT`, `FRAME`, `SKYMAP`, `SCHED`, `CAL`, `FOC`, `PLT`, `MFLIP`, `GUIDE`, `DOME`, `SAFE`, `HIST`, `META`, `NOTIF`, `PLUG`, `UI`, `LOG`, `LIB`) and non-functional domains (`NFR-PERF`, `NFR-REL`, `NFR-PORT`, `NFR-EXT`, `NFR-USE`, `NFR-I18N`, `NFR-SEC`, `NFR-OFFLINE`, `NFR-INSTALL`) defined in the scope document. Out-of-scope items (Section 5 of the scope document) are not addressed here. **`VST`/`VST-AN`** (variable-star target planning and photometric analysis) are **not** covered here — they are the VSTarget plugin's own requirements, decomposed in [`docs/plugins/vstarget/SRS.md`](../plugins/vstarget/SRS.md) against this document's `PLUG` domain rather than embedded in it.

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

**`EXT-100` is retired** (left as a gap rather than renumbering, matching this document's ID conventions elsewhere): it covered the AAVSO Target Tool/VSP API, which is not a Galileo-core-wide integration — only the VSTarget plugin uses it, so it now lives as `VST-EXT-010` in [`docs/plugins/vstarget/SRS.md`](../plugins/vstarget/SRS.md). `EXT-110` (Simbad) and `EXT-120` (SFTP) stay here and are reworded to drop their AAVSO-specific framing, since both are genuinely shared infrastructure — `EXT-110` also backs `SKY-100`'s fallback lookup, and `EXT-120`'s SFTP adapter lives in core `galileo.library.adapters` (SDD Section 4.23) and is the Library's alone — the VSTarget plugin does no image retrieval of its own (its `VST-AN-010` is retired) and reads its images from the library.

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
| ARCH-010 | The system shall define a device-abstraction interface per device category (camera, mount, filter wheel, focuser, rotator, guider, switch, flat panel, weather, dome, safety monitor, aux) that is implemented independently by an INDI backend and an Alpaca backend. | MVP |
| ARCH-020 | The system shall allow each connected device to independently use either the INDI backend or the Alpaca backend, simultaneously, within a single equipment profile (e.g. an INDI camera with an Alpaca focuser). | MVP |
| ARCH-030 | The system shall query a connected device's advertised capabilities (INDI properties / Alpaca `Can*` flags) and expose only the corresponding controls in the UI. | MVP |
| ARCH-040 | The system shall detect and surface a device disconnect event to the equipment layer within a bounded time, without crashing or requiring application restart. | MVP |
| ARCH-050 | The system shall support INDI server and Alpaca device discovery (INDI: configured host/port list; Alpaca: UDP discovery per the Alpaca spec) to populate a connect dialog. | P2 |
| ARCH-060 | The system shall isolate a single misbehaving device connection so that it does not block or degrade control of other connected devices. | MVP |
| ARCH-070 | The device-abstraction layer shall be the sole integration point plugins use to register new device backends (traces to `PLUG-010`). | P2 |
| ARCH-080 | The device-abstraction layer shall support multiple concurrent, independently-addressable device pools (one per Pier), rather than assuming a single global set of connected devices, so that multi-Pier observatory support (`OBS`) does not require retrofitting the device layer. | MVP |
| ARCH-090 | The system shall store all application and user configuration (Options pages, per-screen preferences, panel layouts, equipment profiles, library settings) in the shared Peewee database through one common settings store, not in per-module JSON/ini files; an older settings file found in the config folder shall be imported once and renamed `*.migrated`, and settings access shall fall back to defaults rather than fail when the database is unavailable. Secrets remain in the OS keychain (`NFR-SEC-030`). | MVP |

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
| EQP-MNT-060 | The Mount page shall provide a Meridian Flip section: when "Flip if HA >" is checked and the mount is tracking on the west side of the pier with the hour angle more than the configured number of degrees past the meridian, the system shall perform a meridian flip (`MFLIP-020`) and resume tracking, and shall show whether a flip is inactive, armed or done, and the pier side with the direction the telescope points. | P2 |
| EQP-MNT-070 | The Mount page shall provide altitude (minimum, maximum, optionally tracking-only) and hour-angle (maximum, in hours) limits. While the mount is tracking or slewing the system shall stop it and report which limit was exceeded, and shall refuse a slew whose target is outside the enabled limits. Settings are saved per Pier. | P2 |
| EQP-FW-010 | The system shall enumerate configured filter names/slots and issue filter-change commands, exposing change-in-progress status. | MVP |
| EQP-FW-020 | The system shall allow per-filter focus-offset configuration for use by the autofocus and filter-change workflows. | MVP |
| EQP-FOC-010 | The system shall issue absolute and relative focuser move commands and display current position and temperature (where supported). | MVP |
| EQP-FOC-020 | The system shall support configurable focuser backlash compensation applied to move commands. | P2 |
| EQP-FOC-030 | The system shall clamp absolute and relative focuser move commands to the device's valid travel range (0 to the backend-reported MaxStep), rather than issuing an out-of-range command unchecked, regardless of whether the underlying transport is known to protect itself. | MVP |
| EQP-FOC-040 | The system shall support a *Pulse* focuser mode for INDI focusers that can only be driven by a timed move (`FOCUS_TIMER`) and report no position: moves are issued as pulses (1 unit = 1 ms, minimum 32 ms) along a virtual 0–50000 position axis advanced by each completed pulse, starting from the retained position or, if none, the middle (25000). The Focuser page shall offer an Absolute/Pulse selector, show the Pulse-only controls (including *Reset to middle*, to confirm the focuser is at the middle of its travel) only in Pulse mode, and not offer Pulse for Alpaca. | P2 |
| EQP-FOC-050 | The system shall retain a focuser's mode, last known position and user-set minimum/maximum travel with its saved device configuration, so a restart does not lose a pulse focuser's position, and shall hold every move command (absolute, relative or pulse) between the set travel limits as a guard against the physical stops. | P2 |
| EQP-ROT-010 | The system shall issue rotator move-to-angle commands and display current mechanical/sky position angle. | P2 |
| EQP-GDR-010 | The system shall expose guider connect/start-guiding/stop-guiding/dither controls, delegating to the external guiding interface (`GUIDE` domain). | MVP |
| EQP-SW-010 | The system shall enumerate switch/relay devices and their read/write state, supporting both boolean and analog (variable) switches. | P2 |
| EQP-FP-010 | The system shall control an electroluminescent/flat-panel device's cover open/close (where supported) and brightness level. | MVP |
| EQP-WX-010 | The system shall poll and display weather-device readings (e.g. cloud cover, wind, humidity, temperature, rain) at a configurable interval. | P2 |
| EQP-WX-020 | The system shall allow the user to mark any Weather-Station reading as safety-related and configure the comparison operator and threshold value that reading must cross to be considered unsafe (e.g. Rain is YES, Wind Speed >= 20 km/h), from the Equipment > Weather screen. This evaluation is advisory/display-only and shall not itself drive an automated sequence abort — only a connected Safety Monitor device (`SAFE-070`/`SAFE-080`) is authoritative for `SAFE-010`. | P2 |
| EQP-DOME-010 | The system shall issue dome slew-to-azimuth, open/close-shutter, and park commands and display current azimuth and shutter state. | P2 |
| EQP-SAFE-010 | The system shall poll a connected safety-monitor device's SAFE/NOT-SAFE state, and its accompanying human-readable explanation string where the driver provides one, at a configurable interval, and surface state changes (with explanation) to the sequencer (traces to `SAFE-010`). | P2 |
| EQP-SAFE-020 | The system shall surface, on the Equipment > Safety Monitor screen, the current value and SAFE/UNSAFE verdict of every Weather-Station reading configured as safety-related (`EQP-WX-020`), separately from the connected Safety Monitor device's own SAFE/NOT-SAFE state, alongside a trend graph of recent readings (e.g. wind speed, temperature, dew point) so a developing unsafe condition is visible before it trips. | P2 |
| EQP-AUX-010 | The system shall provide an "Aux" equipment category for connecting a miscellaneous INDI driver, or an ASCOM Alpaca Switch device, that has no dedicated Galileo device category, and shall present the connected device's driver-defined properties as a tabbed control panel — one tab per INDI property group, or a single tab for an Alpaca Switch device — with fields and switches generated from the driver's own property definitions rather than a fixed per-category UI. | P2 |
| EQP-SW-020 | The system shall list as Switch devices every INDI device whose `DRIVER_INTERFACE` includes the INDI power interface, together with every INDI device whose name a registered switch profile claims (`EQP-SW-080`), selectable from the Equipment > Switches page like any other category (traces to `EQP-040`). | P2 |
| EQP-SW-030 | For a device using the INDI power interface, the system shall build a structured switch panel from the standard power-interface properties (`POWER_CHANNELS`, `USB_PORTS`, `DEW_CHANNELS` with `DEW_DUTY_CYCLES`, `VARIABLE_CHANNELS` with `VARIABLE_VOLTAGES`, `AUTO_DEW_CONTROL`, and their `*_LABELS` and `*_CURRENTS`): one group per port type, one channel per element, each labelled from the driver's own label property, with a group present only if the driver defines it. | P2 |
| EQP-SW-040 | The switch panel shall also present the device's overall readings and global controls where the driver defines them: voltage, current and power (`POWER_SENSORS`), per-channel currents, LED control, power-cycle-all, power-off-on-disconnect and over-voltage protection. | P2 |
| EQP-SW-050 | The system shall apply a channel toggle, a dew duty change, a regulator voltage change or a generic value change (`EQP-SW-140`) by writing the corresponding element of the INDI driver's property vector or the corresponding Alpaca switch channel, and shall display state read back from the device (the INDI live property cache, or the Alpaca channel's current value), never from the last command issued. A write to a property or channel the device does not define or defines read-only shall raise a reportable error (`DevicePropertyError`) rather than silently succeeding. | P2 |
| EQP-SW-060 | The system shall present dew duty cycle on a 0–100 % scale regardless of the driver's native range, converting to and from the native scale (for example 0–255) on read and write and clamping to it, and shall hold a variable-voltage setting within the driver-declared minimum and maximum. | P2 |
| EQP-SW-070 | Every property of a connected power device that the standard mapping or its profile does not claim shall remain reachable from the Switches page in an "Other" group built with the Aux property model (`EQP-AUX-010`), so that mode selectors, setpoints, calibration and reboot controls are never hidden; BLOB properties are skipped. | P2 |
| EQP-SW-080 | The system shall define a declarative *switch profile* for a driver that does not use the power interface, comprising: the INDI device names it may report; a signature of (property name, property kind) pairs that must all be defined on the connected device; the channel, sensor and display-only-channel mappings to property elements, with labels, native scale, optional-property marking and values to be treated as "no reading". The system shall resolve a connected device to a profile by signature, never by device name alone, choosing the profile with the largest satisfied signature; where no profile's signature is satisfied it shall report the device as not recognised, and where two tie it shall report the ambiguity, rather than guessing. | P2 |
| EQP-SW-090 | The Equipment > Switches page shall render a connected device's switch panel with a section per group; a toggle per switchable channel; a read-only entry, with no toggle, per display-only channel; a slider or numeric field per dew duty and variable voltage; the readings and global controls of `EQP-SW-040`; and the "Other" group of `EQP-SW-070`. It shall refresh on an interval no longer than 5 s and continue to host plugin-contributed panels (`PLUG-070`) on the same page. | P2 |
| EQP-SW-100 | Every toggle channel of every Switch device shall remain addressable by a stable identifier through the flat switch contract (`list_switches`/`set_switch`), so that contract — which the Kasa, Generic Relay and SwitchBot plugin backends implement, and which any other consumer such as a future Sessions block would use — keeps working unchanged. | P2 |
| EQP-SW-110 | Before a channel is switched off from the Switches page while a session is running on the Pier, the system shall ask the user to confirm, naming the channel. The prompt applies to the Switches page only: a switch action a session itself performs is its author's explicit intent and is not prompted. | P2 |
| EQP-SW-120 | A property a driver defines or deletes while connected (as several drivers do on a mode change), a property absent from a given firmware, or the loss of the INDI server shall remove or disable only the affected controls and show an explanatory state, and shall not raise an unhandled error or affect any other device (traces to `ARCH-060`). | P2 |
| EQP-SW-130 | For an ASCOM Alpaca Switch device (ISwitchV2), the system shall build the same switch panel from the device's own channel list — name, description, writability, minimum, maximum and step, and current value — in one group, since Alpaca defines none: a channel with range 0..1 and step 1 becomes a toggle, a writable channel with any other range becomes a generic value (`EQP-SW-140`), and a read-only channel becomes a reading (a read-only boolean as a display-only channel). Each toggle channel shall also appear in the flat switch contract (`EQP-SW-100`), and Alpaca devices shall be listed and selected through the existing Alpaca discovery (`EQP-040`, `ARCH-050`). | P2 |
| EQP-SW-140 | The switch model shall provide a generic *value* channel for a numeric channel whose meaning the device does not declare (any non-boolean Alpaca switch channel): it shall be presented with exactly the minimum, maximum and step the device declares and no assumed unit or scale (no volts, no percentage), as a slider or numeric field when writable and as a reading when read-only. | P2 |

**Generic power-device support, INDI and Alpaca (`EQP-SW-020`–`EQP-SW-140`).** Most INDI power boxes (Pegasus PPBM/PPBA/UPB3, Terrans PowerBoxGo V2/PowerBoxPro V2, and others) use INDI's standard power interface, whose property names are identical across vendors, so core serves them with no per-vendor code: the INDI Switch adapter maps those properties onto a structured Switch model (port groups, labelled channels, dew duty, regulator voltage, sensors) that the Equipment > Switches page renders, while the flat switch contract that any other consumer would use is kept (`EQP-SW-100`). Drivers that do not use the standard interface (currently the Wanderer Astro WandererBox Pro V3, Plus V3 and Dew Terminator) are supported by declarative *switch profiles* a plugin registers (`EQP-SW-080`, `PLUG-210`; [`docs/plugins/wandererbox/SRS.md`](plugins/wandererbox/SRS.md), `WBOX-*`), applied by the same mapping engine. An ASCOM Alpaca Switch device (ISwitchV2) is standardised, so it needs no profile: it produces the same structured model from its own channel list (`EQP-SW-130`), as one flat group because Alpaca has no grouping, and a channel whose meaning the interface does not say is shown as a generic value (`EQP-SW-140`).

**`EQP-SW-010` also has three first-party plugin consumers for hardware that speaks neither INDI nor Alpaca.** For these the Equipment > Switches screen is populated only by the plugin's own panel; the Kasa Switch plugin ([`docs/plugins/kasa_switch/SRS.md`](plugins/kasa_switch/SRS.md), `KASA-*`) and Generic Relay plugin ([`docs/plugins/generic_relay/SRS.md`](plugins/generic_relay/SRS.md), `RELAY-*`) each register their own `DeviceBackend` for `DeviceCategory.SWITCH` (`ARCH-070`/`PLUG-010`) satisfying this same requirement for TP-Link Kasa devices and generic HTTP-toggled relay boards respectively, surfaced through their own plugin panels rather than this screen. A third, the SwitchBot Bot plugin ([`docs/plugins/switchbot_bot/SRS.md`](plugins/switchbot_bot/SRS.md), `SBOT-*`), does the same for SwitchBot Bot buttons pressed over Bluetooth LE — chiefly to power a Seestar on and off.

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
| PROF-130 | The system shall refuse, wherever the user specifies the host or URL of a device (an INDI server or an Alpaca device), a loopback address — `localhost`, `127.0.0.0/8`, `::1` or `0.0.0.0` — with a message asking for the machine's real hostname or LAN address, and shall flag a stored profile that already contains one when it is loaded. A single `is_loopback(address)` check shall serve every caller. This applies whether or not any plugin is installed, so that a stored address means the same machine on every node. | MVP |

### 4.3a `OBS` — Multi-Mount Observatory Management (exceeds EKOS, Section 6.6)

A single Galileo instance manages multiple independent Piers (`PROF`), deliberately going beyond EKOS's own single-mount-per-application-instance model. Unlike `DOME` (which may be Pier- or Observatory-scoped, `OBS-050`) and `SAFE` (always Observatory-scoped, `OBS-030`), guiding is never Observatory-scoped — see `GUIDE-060`.

| ID | Requirement | Priority |
|---|---|---|
| OBS-010 | The system shall allow multiple Piers to be grouped into a named Observatory. | P2 |
| OBS-020 | The system shall allow independent sequences and scheduler jobs to run concurrently across different Piers within an Observatory, each targeting a different object. | P2 |
| OBS-030 | The system shall scope safety devices — weather stations and safety monitors — and their per-reading safety rules at the Observatory level: they are configured, saved and connected once per Observatory and shared by every member Pier, never per Pier (one station watches the sky over the whole enclosure). Selecting another Pier of the Observatory neither reloads nor disconnects them, and a Pier's own Connect/Disconnect leaves them alone. | P2 |
| OBS-040 | When an Observatory-scoped safety-monitor reports an unsafe condition, the system shall pause or abort active sequences and park equipment across every Pier in that Observatory (traces to `SAFE-010`), not just the Pier that detected it. | P2 |
| OBS-050 | The system shall allow a dome/roof to be scoped at the Observatory level (one shared roof covering multiple piers) or at the Pier level (independent domes), configurable per Observatory. | P2 |
| OBS-060 | The system shall present a multi-Pier status dashboard (equipment/sequence/scheduler state for every Pier in an Observatory at a glance), in addition to a focused single-Pier view. The Dashboard screen realises this as the per-Pier activity timelines of `OBS-150`. | P2 |
| OBS-070 | The scheduler (`SCHED`) shall support assigning jobs to any Pier within an Observatory and shall coordinate Observatory-scoped shared-resource constraints (e.g. a shared dome/roof state) across the Piers that depend on them. | P2 |
| OBS-080 | The system shall connect to and concurrently operate the device sets of multiple Piers within a single running application instance (traces to `ARCH-080`). | P2 |
| OBS-090 | The system shall allow an Observatory record to carry the operator's own contact details — email address, phone/SMS number, and which channel(s) `NOTIF` should use (email, text, or both) — since being notified is scoped to the person running the Observatory, not to an individual Pier within it (traces to `NOTIF-020`, `NOTIF-040`). | P2 |
| OBS-100 | The system shall arbitrate Observatory-scoped shared resources (the dome/roof) between Piers: each Pier registers the work it is doing against the resource (e.g. imaging), and a request by another Pier for a disruptive action on it (closing the roof, slewing the dome) shall be denied while that work is active. Non-disruptive actions (opening the roof) and Pier-scoped resources (`OBS-050`) are never denied. | P2 |
| OBS-110 | A requester may queue for a contended shared resource for a bounded wait; the request is granted when the blocking Pier releases its work, or denied when the wait expires. A denied session block is skipped and logged, not fatal. | P2 |
| OBS-120 | Every arbitration outcome (granted, denied with the blocking Pier(s), released) shall be published on the event bus rather than by direct calls between Piers (traces to `ARCH-060`). | P2 |
| OBS-130 | Priority rules: a safety-driven action (unsafe conditions, `OBS-040`) carries emergency priority and overrides other Piers' imaging; all other requests have equal priority. | P2 |
| OBS-140 | Scheduled sessions shall start on every Pier of the Observatory whose equipment is connected, not only the Pier selected in the top bar: each Pier's session is run against that Pier's own devices, all gated on the Observatory's safety devices and rules (`OBS-030`, `SCHED-060`) — readings older than the poll interval are re-read first, and a connected device that cannot be read counts as unsafe — while a Pier with nothing connected waits without holding the others, and the Dashboard (`OBS-060`) reports each Pier's own connection state. | P2 |
| OBS-150 | The Dashboard shall show, for every Pier of the selected Observatory, a compact activity timeline recorded from the Pier's live state whether or not the screen is showing: one lane each for the session, mount, meridian flip, guiding, plate solving, focusing and capture (capture cut into one box per frame), the guide error as a trace over time and as a scatter plot, and a time axis; no control is needed to choose a Pier. Above the timelines it shall provide an area for plugin views (`PLUG-180`), sized to the height the timelines leave free so that every Pier's timeline is visible. | P2 |

### 4.4 `IMG` — Imaging Tab

`IMG-050` (star-overlay toggle) is removed: the checkbox never had a corresponding on-preview overlay renderer behind it, and the Imaging tab's View panel no longer carries a control for it. The ID is retired, not reused.

| ID | Requirement | Priority |
|---|---|---|
| IMG-010 | The system shall display a newly captured frame in a live preview within a bounded time after camera readout completes. | MVP |
| IMG-020 | The system shall compute and display an auto-stretch preview of the displayed frame without altering the saved file's raw pixel data. | MVP |
| IMG-030 | The system shall display a histogram of the current frame, updated per capture. | MVP |
| IMG-040 | The system shall compute per-frame statistics (mean, median, min/max, star count, HFR) and display them alongside the preview. | MVP |
| IMG-060 | The system shall allow the user to pan and zoom the displayed frame. | MVP |
| IMG-070 | The system shall support a manual single-exposure capture independent of any running sequence. | MVP |
| IMG-080 | The system shall allow the user to configure the imaging-tab panel layout (traces to `UI-020`). | P2 |
| IMG-090 | The system shall display live exposure countdown and camera/download status during an in-progress capture. | MVP |
| IMG-100 | The system shall allow saving the currently displayed frame independently of the automatic sequence save path. | P2 |
| IMG-110 | The system shall let the user turn on debayering of the displayed frame from a one-shot-colour camera, using a Bayer pattern (RGGB, GRBG, GBRG or BGGR) that the user sets per camera on its Equipment page and that defaults to RGGB. Debayering shall not alter the frame's raw pixel data, statistics or saved file (traces to `IMG-020`). | MVP |
| IMG-120 | The system shall detect whether the displayed frame is portrait or landscape and lay the imaging tab out for it: for a portrait frame the preview shall be a full-height column one third of the tab's width, with the mount nudge pad, histogram, progress display and log moved to the left of it, beside the capture settings. A checkbox shall let the user choose portrait or landscape manually instead of following the frame (traces to `IMG-010`). | P2 |
| IMG-130 | The system shall provide a mount nudge pad (N/S/E/W and diagonals) on the imaging tab that moves the connected mount at a user-chosen speed for as long as a button is held (stopping on release, and if the button is hidden or the application loses focus), while exposures are in progress, with a control to stop all motion. Axis directions shall match the Mount page's jog pad (traces to `EQP-MNT-010`). | P2 |
| IMG-140 | The system shall keep a current object for each Pier, set to the item most recently selected in the Star Atlas and shown at the top right of the window. Frames the imaging tab saves and the frames captured for plate solving shall be named after it, and Capture & Solve with the Slew to Target action shall slew the mount to its coordinates and correct until the solution is within the accuracy of them (traces to `SKYMAP-010`, `PLT-070`). | P2 |
| IMG-150 | The imaging tab shall let the user set the number of frames one Capture takes and the camera gain to use, take that many frames sequentially with the tab's settings, and stop a series on request. It shall offer an option, on by default, to write each captured frame to a scratch folder and register it in the image library so it appears on the library's Images screen. Frames written by the imaging tab shall carry every FITS header card the application can determine, including every card the library derives file and folder names from (traces to `META-010`, `LIB-150`). | P2 |
| IMG-160 | The imaging tab shall offer a live-stacking option which, for a capture run of more than two frames, shall register each captured frame against the first of the run and combine it into a running mean that replaces the displayed frame, rather than each exposure discarding the last. The stack shall be saveable both to the image library and to a file of the user's choosing, and the saved stack shall record the number of frames combined and the total integration time. Individual frames shall continue to be catalogued separately (traces to `IMG-010`, `IMG-150`). | P2 |
| IMG-170 | An Imaging settings screen shall let the user set a desired FITS sample format (BITPIX) for frames the imaging tab saves, offered as "Auto" (the smallest portable format that fits each frame without losing data) or a fixed 8, 16, 32 or -32; the fixed choices shall clip out-of-range values and round a float to the nearest integer rather than wrapping or raising. No frame the application writes, under any setting, shall use a 64-bit sample format, which common solving and analysis tools cannot read (traces to `META-010`). | P2 |
| IMG-180 | The imaging tab shall provide a Framing… control that opens the Framing Assistant (`FRAME-070`) against the currently selected camera/optical train for immediate-imaging use, including defining and, where a mosaic grid is defined, running a mosaic capture directly from the tab (mosaic execution traces to `FRAME-090`). Where live stacking (`IMG-160`) is enabled for such a capture, each pane's frames shall register onto that pane's own running stack, composited into a single canvas sized to the whole mosaic at each pane's grid position, so the displayed preview shows the mosaic's full extent filling in pane by pane rather than one pane's frame at a time. | MVP |
| IMG-190 | The imaging tab shall provide a slider above the histogram letting the user adjust the strength of the displayed frame's auto-stretch preview, re-rendering the preview as it changes. Adjusting it shall not alter the raw frame, its statistics, its histogram or any saved file (traces to `IMG-020`, `IMG-030`). | P2 |
| IMG-200 | The imaging tab shall provide an Annotate control above the preview that, when turned on, plate-solves the displayed frame (traces to `PLT-010`) and overlays a circle and label at the position of each catalogued star or deep-sky object found within it, using Galileo's own bundled catalogs. Turning it off, or the displayed frame changing (a new capture), shall return the preview to the ordinary auto-stretch view without altering the raw frame, its statistics or its histogram (traces to `IMG-010`, `IMG-020`). | P2 |
| IMG-210 | While Annotate (`IMG-200`) is on and a labelled overlay is current for the displayed frame, Save Frame and Save Stack shall write that annotated view, rendered as an image, in place of the raw FITS file they otherwise save (traces to `IMG-100`, `IMG-160`). | P2 |
| IMG-220 | The Library — both the imaging tab's automatic per-frame registration and its Save Stack to Library control — shall register only the raw captured frame or stack, never an annotated overlay (`IMG-200`), regardless of the Annotate control's state (traces to `IMG-150`, `IMG-160`). | MVP |

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
| SES-115 | The system shall bind each session to one camera of its Pier (default: the camera selected in the top bar when the session is created), persist that choice with the session, use it for every action of the session's run regardless of the top bar's Camera selector, and display it in the top bar while the session runs. | MVP |
| SES-120 | The system shall provide a single right-hand action palette from which blocks are dragged into a session region, insertable before, after, or between existing blocks, and freely reorderable within the region afterward. | MVP |
| SES-130 | The system shall provide, at minimum, the following action blocks in the palette: Target (set active target and slew), Image (capture parameters mirroring the Imaging tab: exposure time, count, filter, binning, gain/offset, frame type; a Framing… control opening the Framing Assistant to set the block's target frame box, traces to `FRAME-070`), Filter Change, Cool Camera/Warm Camera (CCD setpoint temperature plus wait-for-stabilization), Autofocus, Plate Solve, Guide Start/Guide Stop, Dither (also selectable inline as an Image-block option), Flat Capture, and Park Mount/Unpark Mount. | MVP |
| SES-140 | The system shall provide, at minimum, the following additional action blocks: Meridian Flip and Dome Open/Close/Sync. | P2 |
| SES-150 | The system shall provide a Notification action block that sends an alert at that point in the session via the owning Observatory's configured contact channel(s) (traces to `NOTIF-010`, `OBS-090`). | P3 |
| SES-160 | The system shall create a new session pre-populated with a `Target: <name>` block (set active target and slew) when a target is selected on the Targets/Sky Atlas screen (`SKY`), and shall provide an "Add Session" context-menu item that creates an equivalent empty session for manual authoring. | MVP |
| SES-170 | The system shall enforce block-ordering integrity rules (e.g. a Plate Solve block requires a preceding Target block) at block-insertion time and/or session-run time, rather than allowing an invalid session to be built or scheduled. | MVP |
| SES-180 | The system shall allow a session's blocks to be saved to a reusable template (the Save as Template control) storing its Target block as a generic placeholder rather than a specific target, so the template captures a repeatable procedure rather than a one-off plan. | P2 |
| SES-190 | The system shall, when Load from Template is used on a session region that already has a concrete Target (Slew To) block, substitute the template's placeholder with that existing Target block and append the template's remaining blocks in their saved order, leaving the region's other existing blocks (if any) untouched. Load from Template shall be unavailable on a region with no Target (Slew To) block yet. | P2 |
| SES-200 | The system shall submit a session to the Scheduler (`SCHED-010`) only when its region's Schedule control is used; authoring a session, including a fully built-out one, shall have no other side effect — it shall neither run nor queue until Schedule is used. | MVP |
| SES-210 | The system shall, once a session is scheduled, make its region read-only (blocks no longer draggable, reorderable, or editable) and render its boundary distinctly (e.g. red) to indicate it is live rather than a draft; the region's Schedule control shall become a Deschedule control which withdraws the job from `SCHED` and returns the region to its normal, editable state. When the job instead completes successfully (its completion condition, `SCHED-050`, is satisfied) rather than being withdrawn, the session shall be deleted outright rather than returned to editable state — a completed session has nothing left to author. | MVP |
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
| SKY-080 | The system shall fetch and cache a sky-survey cutout thumbnail image (e.g. via a DSS cutout service such as the CDS hips2fits API) for a catalog object when it is added to a user's active target list, cropping the fetched segment to a field size derived from the object's own angular size — rather than a fixed cutout window — so the thumbnail reasonably frames both large and small objects, for offline reference thereafter. | MVP |
| SKY-090 | The system shall resolve a location name/address to latitude, longitude, and timezone via a geocoding lookup (traces to `EXT-130`), as a convenience when configuring an observing location (`SKY-060`). | P2 |
| SKY-100 | The system shall resolve an object-name search primarily via the offline catalog (`SKY-010`), falling back to a live Simbad lookup (traces to `EXT-110`) only when the offline catalog has no match for the searched name and internet is available — **this reverses the previous Simbad-first/catalog-fallback design** so that ordinary object search, not only catalog browse/filter/chart, satisfies `NFR-OFFLINE-010`'s no-internet guarantee. | MVP |
| SKY-110 | The system shall optionally augment object search with the Telescopius API's target-search/suggestion data (traces to `EXT-150`) when the user has configured their own Telescopius API key, never as a substitute for the offline-first/Simbad-fallback path of `SKY-010`/`SKY-100`. | P2 |
| SKY-120 | The system shall allow importing a user's existing Telescopius observing list into a Galileo session/target list (traces to `EXT-150`) when a Telescopius API key is configured. | P2 |

### 4.7a `WUT` — What's Up Tonight

A ranked recommendation layer presented as a new **What's Up Tonight** screen, positioned first in the Planning sidebar ahead of Targets (Project Scope Document, Section 8, G18). This is not a second catalog or ephemeris engine: it composes `SKY-010`–`040`'s catalog/altitude/horizon-profile data, `SAFE-050`'s advisory weather forecast (plus, for the selected date where available, `SAFE-090`'s aurora estimate and `SAFE-100`'s smoke/transparency estimate), and `PROF-080`'s per-Pier optical-train capability into a sky-only **Observability Score**, a per-optical-train **Fit Score**, and a combined ranking — consuming those requirements by reference rather than restating them, the same pattern `SCHED` (Section 4.8b) already uses for `SKY-030`. The core ranked-list capability (`WUT-010`–`080`) is MVP, superseding an earlier P2/P3 default considered during drafting; date selection (`WUT-090`) is a P2 refinement of it, aurora/smoke advisory integration (`WUT-100`) is P3, matching the priority already assigned to `SAFE-090`/`SAFE-100` themselves, and a day/night graphic for the selected date (`WUT-110`) is MVP, alongside the rest of the core screen.

| ID | Requirement | Priority |
|---|---|---|
| WUT-010 | The system shall present a ranked list of catalog objects observable tonight from the active Pier's configured location, combining sky observability (`SKY-020`/`SKY-030`) with the active optical train's imaging capability (`PROF-080`). | MVP |
| WUT-020 | Each ranked entry shall show at least one human-readable reason for its ranking or exclusion (e.g. limiting altitude, equipment mismatch, Moon proximity). | MVP |
| WUT-030 | The system shall display a data-completeness confidence indicator per entry, separate from the ranking score, degrading rather than silently omitting entries when forecast/horizon data is unavailable. | MVP |
| WUT-040 | Re-ranking on Pier/optical-train change shall reuse the already-computed sky-observability data for that location/night rather than recomputing it. | MVP |
| WUT-050 | The system shall show, per ranked entry, prior integration time recorded in the Library for that object, as an informational annotation only — it shall never adjust the entry's score or position in the ranking. | MVP |
| WUT-060 | Each ranked entry shall offer the same Select / Slew To / Add to Session actions as the Targets screen (`SKY-050`, `SKYMAP-060`, `SES-160`), reusing the existing entry points. | MVP |
| WUT-070 | The What's Up Tonight screen shall be the first entry in the Planning sidebar section. | MVP |
| WUT-080 | Where a horizon obstruction profile (`SKY-040`) is defined for the active location, the Observability Score shall exclude altitude/time ranges behind that obstruction; where none is defined, ranking shall proceed on open-horizon altitude alone and reflect the omission via the confidence indicator (`WUT-030`), never blocking the ranked list. | MVP |
| WUT-090 | The system shall allow the user to set an observing date other than the current date, and shall compute the ranked list (`WUT-010`) against that date's local night rather than tonight's, so the screen can be used to plan a future (or review a past) night as well as tonight. A date outside the range covered by the available weather forecast (`SAFE-050`) shall not block ranking — it shall be reflected via the confidence indicator (`WUT-030`) the same way a missing forecast already is. | P2 |
| WUT-100 | For the observing date selected (`WUT-090`), the system shall incorporate the aurora-activity estimate (`SAFE-090`) and the smoke/transparency estimate (`SAFE-100`) into the Observability Score, and shall display each to the user when available for that date, on the same advisory-only basis as the weather forecast (`SAFE-050`) — neither shall be required for ranking to proceed, and where either is unavailable for the selected date the confidence indicator (`WUT-030`) shall reflect the omission rather than blocking the ranked list. | P3 |
| WUT-110 | The screen shall display a graphical band across the top showing, for the selected observing date (`WUT-090`) and location, the Night / Astronomical Twilight / Nautical Twilight / Civil Twilight / Daylight periods spanning that local calendar day, each period's clock-time range and total duration, and the local solar noon/midnight times. | MVP |

### 4.8 `FRAME` — Framing Assistant

**Invoked contextually, not a primary-navigation section (`FRAME-070`):** the Framing Assistant is opened from the Imaging tab's Framing… control (`IMG-180`) or a Session Image block's own Framing… control (`SES-130`), never presented as its own top-level screen. Both entry points share every requirement below and the same underlying design; each retains its own independent framing/mosaic state (the Imaging tab's current immediate-capture setup is separate from any given Session Image block's own stored definition).

| ID | Requirement | Priority |
|---|---|---|
| FRAME-010 | The system shall display a field-of-view rectangle computed from the active camera's sensor dimensions and the active telescope's focal length, overlaid on a sky image. | MVP |
| FRAME-020 | The system shall support at least one online sky-survey image source and one offline/cached star-field rendering mode for the framing background. | MVP |
| FRAME-030 | The system shall allow the user to rotate the framing rectangle to preview a given camera/rotator position angle; the rotation control itself is never disabled. Where the active optical train has a rotator equipped and connected (`EQP-ROT-010`), accepting the change moves it to that angle. Where none is connected, the camera cannot be physically tilted, so the requested angle is instead achieved by covering the tilted rectangle's axis-aligned bounding area with an automatically-sized mosaic of un-rotated panels (traces to `FRAME-040`) rather than the rotation being unavailable — an explicit mosaic grid the user has set themselves takes priority over this fallback. **Supersedes an earlier "rotation unavailable, not silently ignored, without a rotator" model.** | MVP |
| FRAME-040 | The system shall support defining a mosaic as a grid of overlapping framing panels, with a pane-overlap percentage configurable on the Imaging settings screen (`IMG-170`'s kin) and shared by both Framing Assistant entry points (`FRAME-070`) rather than configured separately per entry point. | P2 |
| FRAME-050 | The system shall attach a defined framing target — a single frame, or, where a mosaic grid is defined (`FRAME-040`), the whole mosaic as one unit — to whichever context opened the Framing Assistant (the Imaging tab's current immediate-capture setup, `IMG-180`, or a Session Image block, `SES-130`) as that context's own capture target. **This supersedes an earlier "each mosaic panel sent to the sequencer as its own target" model**: a mosaic is now owned and captured by one Imaging-tab run or one Image block internally (traces to `FRAME-090`), not decomposed into separate per-panel targets upstream of capture. | P2 |
| FRAME-060 | The system shall overlay constellation lines and a coordinate grid on the framing view. | P2 |
| FRAME-070 | The system shall present the Framing Assistant only when invoked from the Imaging tab (`IMG-180`) or a Session Image block (`SES-130`), never as a primary-navigation section of its own, and shall return to whichever context opened it when closed. | MVP |
| FRAME-080 | The system shall provide a Compare Cameras control that overlays a field-of-view rectangle for every camera configured across every Pier in the current Observatory — not only the currently active one — with the survey image auto-scaled to the largest field size among them. | P2 |
| FRAME-090 | Where a run's or session block's target includes a defined mosaic grid (`FRAME-040`), the system shall slew to and capture one exposure at each pane in turn before repeating the pass for any additional exposures per pane, rather than completing all of one pane's exposures before moving to the next. The re-slew between passes is the mechanism that dithers a pane's frames against each other; it is distinct from and does not require a separate guider-dither command (`GUIDE-030`) between exposures of an unchanged target. | P2 |
| FRAME-100 | The system shall pre-fill the framing rotation (`FRAME-030`) from whichever source already knows it — a connected rotator's live position, else an existing plate-solve result for the Imaging tab's current frame — and shall provide a Determine Rotation control that plate-solves the current frame and reads the position angle back from the solution when neither source is available. | P2 |

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
| SCHED-050 | The system shall support per-job completion conditions: run once, repeat a specified number of times, or repeat indefinitely. A job that completes successfully shall be removed from the queue and its originating session deleted (traces to `SES-210`) — only a job withdrawn manually (Deschedule) returns its session to an editable draft. | MVP |
| SCHED-060 | The system shall gate job startup and continued execution on a connected safety-monitor's state (traces to `SAFE-010`): suspend imaging on a warning state, and perform a full protective shutdown on an alert state. | MVP |
| SCHED-070 | The system shall continuously replan the job queue using priority-based preemption, allowing a higher-priority job to preempt a lower-priority one when it becomes runnable. | P2 |
| SCHED-080 | The system shall display each queued job's altitude trajectory and projected run window as a chart. | P2 |
| SCHED-090 | The system shall track per-job capture progress across multiple nights and avoid recapturing frames already obtained when a job resumes. | MVP |
| SCHED-100 | The system shall persist the job queue and per-job progress across application restarts. | MVP |
| SCHED-110 | The system shall provide a per-Pier Schedule screen showing a multi-day calendar grid (one column per day, a shared hour axis), with an Add Pier Operation control for the standalone pier-level operations (Open Dome, Close Dome, Unpark Scope, Park Scope, Dome Sync) reusing the corresponding `SES-140` action-block definitions where one exists; each scheduled session or pier-operation is rendered as a single calendar block sized to its duration. | MVP |
| SCHED-120 | The system shall let the user set a timeline block's start time, end time, and/or duration via a right-click dialog, or move the block directly on the timeline; a block with no start/end set is left for the autoscheduler (`SCHED-160`) to place. | MVP |
| SCHED-130 | The system shall let the user scroll the Schedule timeline backward up to 7 days, to review previously executed entries, and forward without limit to view upcoming ones. | MVP |
| SCHED-140 | The system shall render a completed timeline entry with a green border and an entry that encountered an execution error with a red border, and shall provide a Log control on each entry that opens its execution log. | MVP |
| SCHED-150 | The system shall provide a Run control on each session region in the Sessions screen (`SES-110`) that immediately executes that session without placing it on the Schedule timeline, stopping any scheduler-started session already running on that Pier so the Run takes over, and refusing to start while the safety monitor reports unsafe conditions. | MVP |
| SCHED-160 | The system shall provide an Autoschedule control on the Schedule screen that automatically places every unpositioned timeline entry, in priority order, in the earliest free slot of the displayed night where its altitude, horizon, Moon-separation and twilight constraints hold and which overlaps no other entry on the same Pier, after showing the user a preview to confirm; entries already positioned are not moved, and continuous replanning/preemption remains `SCHED-070`. | P3 |

### 4.9 `CAL` — Calibration / Flat Wizard

| ID | Requirement | Priority |
|---|---|---|
| CAL-010 | The system shall provide an automated flat-frame capture routine that adjusts exposure time (or panel brightness) to reach a configured target ADU/histogram level. | MVP |
| CAL-020 | The system shall capture a configured number of flat frames per active filter automatically, cycling the filter wheel. | MVP |
| CAL-030 | The system shall support dark-frame and bias-frame capture sequences with configurable exposure/count/binning matching a set of light-frame parameters. | MVP |
| CAL-040 | The system shall integrate with a connected flat panel device to control brightness/cover as part of the flat-capture routine, where present. | MVP |
| CAL-050 | The system shall abort and report the flat-capture routine if a target ADU level cannot be reached within configured exposure-time bounds. | P2 |
| CAL-060 | The system shall present the flat-wizard workflow within the Imaging tab (`IMG`) rather than as a separate top-level navigation section. | MVP |
| CAL-070 | The system shall provide a Sky Flats capture mode that: refuses to run outside the local dawn/dusk twilight window; slews the mount to a star-poor vantage point and disables tracking before capturing; adaptively converges each frame's exposure toward a configured fraction of the camera's configured maximum well depth, re-measuring and re-adjusting after every frame; and submits each captured frame to the Library. | MVP |
| CAL-080 | The system shall present a Darks Assistant within the Imaging tab (in the zoom toolbar in landscape layout, in the Tools panel in portrait layout) that: accepts a comma-separated list of exposure lengths (default "10,20,30,60" s); accepts an optional filter selection; captures one dark frame at each listed exposure length in order; submits each captured frame to the Library; and prevents the dialog from being closed (it can only be hidden, see `CAL-100`) while a run is in progress. | MVP |
| CAL-090 | The system shall provide panel flats for the Session Flat Capture block: a Flat Panel method that opens the cover, lights the connected flat panel and sets its brightness through the flat-panel port, and an Observatory Panel method for a fixed light source; both adaptively converge each frame's exposure (and, for a Flat Panel, the panel brightness) toward a fraction of the camera's configured maximum well depth (which is required — the block fails if it is not set), and fail the block when the target ADU cannot be reached. | MVP |
| CAL-100 | The Darks Assistant and Flats Assistant dialogs shall be modeless, so that other Piers remain usable while one is open. While a run is in progress the dialog shall be hideable (Hide button, Esc, window close) without stopping the run; the Imaging tab's Darks…/Flats… button shall be marked as running and shall reopen the Pier's dialog with its live progress; selecting a different Pier shall hide a running dialog and close an idle one; and a failed run shall be reported on the dialog's status line and in the status bar rather than in a modal message box. | MVP |

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
| FOC-100 | The system shall provide **manual focus as a function of the focus module**, alongside autofocus: move the focuser in or out by a chosen step, move to an absolute position, halt, and read the current position and temperature (where the focuser reports one). The functions shall not depend on any screen. | MVP |
| FOC-110 | The desktop Focus screen shall **consume** the module's manual-focus functions rather than drive the focuser directly, so the desktop and every remote client use one implementation and one set of limits. | MVP |
| FOC-120 | The Control Surface (`CSURF-150`) shall publish the module's manual-focus and autofocus operations; manual focus shall not be offered as a generic focuser-device operation. | MVP |
| FOC-130 | A manual focus move started as a *held* move (continuous in/out while a button is held) shall use the deadman semantics of `CSURF-400`. | MVP |

### 4.11 `PLT` — Plate Solving

| ID | Requirement | Priority |
|---|---|---|
| PLT-010 | The system shall invoke a configured external plate-solving engine against a captured or supplied frame and return solved RA/Dec and rotation. | MVP |
| PLT-020 | The system shall support at least one local/offline solver and remain functional without an internet connection for plate solving (traces to `NFR-OFFLINE`). | MVP |
| PLT-030 | The system shall support a solve-and-sync workflow that syncs the mount's reported position to the solved coordinates. | MVP |
| PLT-040 | The system shall support a solve-and-center workflow that iteratively slews and re-solves until the target is within a configured tolerance of the frame center. | MVP |
| PLT-050 | The system shall report plate-solve failure distinctly from success and allow the invoking workflow (manual or sequencer) to react accordingly. | MVP |
| PLT-060 | The system shall allow configuration of solver search parameters (field-of-view hint, search radius, downsample) per equipment profile, and shall allow choosing among the supported solvers (ASTAP, local astrometry.net, nova.astrometry.net, tetra3) and setting the solve exposure's binning, gain, filter and dark subtraction. | P2 |
| PLT-070 | The system shall provide a Solve screen that shows the frame being solved and its solution as a solve happens — whichever part of the application started it (that screen's own Capture & Solve or Load & Slew, or another workflow such as the sequencer) — and shall leave what it shows unchanged while the screen is not in view. From that screen the user shall be able to capture a frame with the selected camera and solve it, choose whether the mount is then synced, slewed back to the target, or left alone, stop a run in progress, and see each solution's position, its error against the target and a log of the run (traces to `PLT-010`, `PLT-030`, `PLT-040`, `PLT-050`). | MVP |
| PLT-090 | The system shall build tetra3 star-pattern databases matched to the fields of view of the Piers' optical tubes and cameras, for the current Pier or for all Piers of all Observatories, from Options > Solve. The build shall run in the background, shall be cancellable, shall reuse an existing database and a downloaded star catalogue, and shall select each database it builds for the Pier(s) it was built for. | P2 |
| PLT-080 | The system shall provide polar alignment on the Solve screen's Polar Alignment tab. With a camera, a mount and the site's latitude and longitude available, it shall plate-solve three frames while turning the mount in RA between them, and find where the mount's RA axis points from where each frame was pointing in the Earth-fixed horizon frame at the time it was taken (not from the mount's own RA readout), allowing for atmospheric refraction unless the user turns that off. It shall show the axis's distance from the celestial pole, split into an altitude and an azimuth correction in plain words, for either hemisphere. It shall not need the scope pre-positioned: it shall first slew the mount to the zenith, plate-solve there to confirm the mount is where it reports being and, if the solution is not at the zenith (for example a mount that has never been synced), sync the mount to the solution and slew to the zenith again, and only then move to the measuring position. It shall then keep solving at the final position and update the error as the user turns the mount's altitude and azimuth knobs, wherever the camera points and allowing for the mount's tracking meanwhile, until stopped. It shall refuse, with a message and without moving the mount, a rotation that would carry a German equatorial mount across the meridian, and shall end with a message rather than a result if a measuring solve fails or the positions cannot define an axis (traces to `PLT-010`, `PLT-070`). | P2 |

### 4.12 `MFLIP` — Meridian Flip

| ID | Requirement | Priority |
|---|---|---|
| MFLIP-010 | The system shall compute the time remaining until a German equatorial mount reaches its configured meridian-flip limit, based on current target and mount type. | P2 |
| MFLIP-020 | The system shall automatically pause an in-progress sequence, execute the meridian flip, and resume, without user interaction, when enabled. | P2 |
| MFLIP-030 | The system shall re-center (via `PLT-040`) and restart guiding after a meridian flip before resuming exposures. | P2 |
| MFLIP-040 | The system shall allow the meridian-flip limit and pre/post-flip behavior to be configured per equipment profile. | P2 |

### 4.13 `GUIDE` — Guiding Integration

Guiding is always Pier-scoped, never Observatory-scoped (contrast `SAFE`, always Observatory-scoped per `OBS-030`, and `DOME`, which may be shared per `OBS-050`): expecting one guiding application to guide multiple independent mounts is not a reasonable requirement, so a multi-Pier Observatory runs one independent external-guider connection per Pier.

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
| GUIDE-100 | The system shall apply the loopback refusal of `PROF-130` to the PHD2 host, and flag an existing guiding setting that contains a loopback address when it is loaded. | MVP |

### 4.14 `DOME` — Dome Control

Within a multi-Pier Observatory, a dome may be Pier-scoped (independent) or Observatory-scoped (one shared roof) per `OBS-050`; the requirements below apply per-dome regardless of scope.

| ID | Requirement | Priority |
|---|---|---|
| DOME-010 | The system shall support slaving dome azimuth to the mount's current pointing direction while tracking. | P2 |
| DOME-020 | The system shall synchronize dome shutter and park actions with sequence start/end and meridian-flip events, where enabled. | P2 |
| DOME-030 | The system shall allow dome slaving to be disabled for domes controlled by independent third-party slaving hardware/software. | P2 |

### 4.15 `SAFE` — Safety & Weather Monitoring

Within a multi-Pier Observatory, safety devices are Observatory-scoped (shared, triggering all member Piers per `OBS-040`) per `OBS-030`.

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
| HIST-050 | The system shall export and import session-history and metric records in a transfer form identified by `(origin_node_id, local_key)`, so that a Master can hold the history of every node with no key collision and an import is an idempotent upsert. | MVP |

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
| NOTIF-050 | The system shall provide an Options > Notifications page to configure external delivery — the e-mail (SMTP server, port, security, login, from address) and SMS (carrier e-mail-to-SMS gateway) channels, fallback recipient e-mail/phone used when the Observatory has no contact details, per-channel enable/disable of each event (`NOTIF-030`), and a test-send for each channel — persisted across restarts, applied to subsequent session runs, with the SMTP password held in the OS credential store rather than a config file (traces to `NOTIF-020`, `NOTIF-030`, `NFR-SEC-030`). | P3 |

### 4.19 `PLUG` — Plugin Framework

Plugins are self-contained ZIP packages (a Python package plus a manifest declaring name, version, API-compatibility range, author, and description). Distribution is via the **galileo-imaging.com plugin page**, where each plugin appears as a direct download link. The **Options > Plugins screen** provides two installation paths and a removal path; both installation paths share the same extraction, validation, version-check, and load logic:

- **Install from file (`PLUG-090`)** — user selects a ZIP from local disk.
- **Plugin Marketplace (`PLUG-100`/`PLUG-110`)** — the screen fetches the list of available plugins by scraping/parsing the galileo-imaging.com plugins page, presents each entry (name, description, version, author), and installs the user's chosen plugin with a single action.
- **Remove (`PLUG-120`)** — uninstall an installed plugin (remove its files, deregister its extension points); a restart may be required for full unload.

Plugins are divided into two tiers: **first-party** (authored by the Galileo project, listed prominently on the website — the VSTarget planning and analysis plugins are the first examples) and **third-party** (community-authored). No plugins are bundled inside the Galileo installer itself; the VSTarget plugin ships exclusively as a downloadable ZIP on the website, making it the concrete proof that the entire distribution pipeline works. Every installed plugin (first-party or third-party) can be independently enabled or disabled; a disabled plugin is fully inert.

| ID | Requirement | Priority |
|---|---|---|
| PLUG-010 | The system shall expose a documented API allowing a plugin to register a new device backend implementing the `ARCH-010` abstraction — including a Safety Monitor device backend (traces to `SAFE-080`), which is trusted identically to an external INDI/Alpaca driver rather than treated as a special case. | MVP |
| PLUG-020 | The system shall expose a documented API allowing a plugin to register a new session action, instruction, condition, or trigger block type (traces to `SES-340`), or a new top-level or nested UI panel. | MVP |
| PLUG-030 | The system shall provide an **Options > Plugins screen** with three capabilities: (1) a list of currently installed plugins showing name, version, enabled/disabled state, and author; (2) an **Install from file** button that accepts a plugin ZIP from the local filesystem; (3) a **Plugin Marketplace** tab that fetches and displays available plugins from the galileo-imaging.com plugin page (`PLUG-100`). Each installed plugin shall have an enable/disable toggle and a **Remove** button (`PLUG-120`). | MVP |
| PLUG-040 | The system shall load and unload plugins without requiring a full application rebuild, and shall isolate a plugin failure from crashing the core application. | MVP |
| PLUG-050 | The system shall version-check a plugin against the running application's plugin API version and warn on incompatibility before completing installation. | MVP |
| PLUG-060 | Every installed plugin — whether first-party or third-party — that is enabled shall be functionally indistinguishable from an equivalent capability built into core; a disabled plugin shall be fully inert (no UI, no background activity). No plugins are bundled into the Galileo installer; all plugins, including first-party ones, are obtained via `PLUG-090` or `PLUG-110`. | MVP |
| PLUG-070 | The system shall allow a plugin to declare where its UI panel appears — in the Science section's menu, on one Equipment device page (e.g. Equipment > Switches), or as its own top-level section (`PLUG-130`) — and shall place the panel there without any per-plugin code in core. | MVP |
| PLUG-080 | The system shall expose, via `PluginContext`, a documented API for a plugin to invoke specific core services it has been granted access to (e.g. submitting a job to the `SCHED` queue) without those services being otherwise part of the plugin extension-point surface (`PLUG-010`/`020`). | MVP |
| PLUG-090 | The system shall install a plugin from a ZIP file selected from the local filesystem: extract it to a configured plugins directory, validate the manifest (schema, required fields), version-check against the running application (`PLUG-050`), and make the plugin available immediately or, if dynamic load is not possible, on the next application restart. | MVP |
| PLUG-100 | The Plugin Marketplace shall fetch the list of available plugins by retrieving and parsing the galileo-imaging.com plugins page (HTML scrape or a structured index file on that page, whichever the website provides), presenting each entry with at minimum: plugin name, short description, current version, author, and a download action. The fetch shall fail gracefully (an explanatory message, not a crash) when the page is unreachable. | MVP |
| PLUG-110 | The Plugin Marketplace shall allow the user to download and install a listed plugin with a single action, using the same extraction/validation/load path as `PLUG-090`. Download progress shall be shown; a partially-downloaded ZIP shall be discarded if the download fails or is cancelled. | MVP |
| PLUG-120 | The system shall allow the user to remove (uninstall) an installed plugin from the Options > Plugins screen: delete its files from the plugins directory, deregister its extension-point contributions, and — if full deregistration requires a restart — disable the plugin immediately and complete removal on the next restart, notifying the user of that requirement. A first-party plugin removed this way is re-installable from the Marketplace like any other. | MVP |
| PLUG-130 | The system shall let a plugin declare a top-level section of its own in the left sidebar, peer to the built-in sections, with an icon the plugin paints (or a generic plugin icon when it supplies none); selecting the entry shows the plugin's page. | MVP |
| PLUG-140 | The system shall let a plugin offer a dockable pane in the main window: created closed unless the plugin asks for it open, movable and floatable by the user, opened and closed by the plugin through `PluginContext`, with the plugin told when the user opens or closes it (and not told that the pane "closed" merely because the main window did). | MVP |
| PLUG-150 | The system shall give each plugin, through `PluginContext`, a settings store in Galileo's shared database under a per-plugin namespace, so plugin configuration follows the same rule as core configuration (no plugin-private config files or `QSettings`); reads fall back to defaults and writes never raise when the database is unavailable. | MVP |
| PLUG-160 | The system shall expose to plugins, through `PluginContext`, the selected Observatory's location (latitude, longitude, elevation, timezone), or nothing when none is selected or it has no coordinates. | MVP |
| PLUG-170 | The system shall let a plugin offer a settings page of its own under Options, listed after Plugins and labelled by the plugin, built by the plugin; a page that fails to build shall be replaced by a placeholder without affecting the rest of the application. | MVP |
| PLUG-180 | The system shall let a plugin offer a view for the Dashboard (`OBS-150`): Galileo adds a *Publish on Dashboard* option to the Options page of any plugin that has one, remembered in the plugin's settings (`PLUG-150`), and shows the view above the Pier timelines only while that option is ticked and the plugin is enabled; a view that fails to build shall be skipped without affecting the Dashboard. | P2 |
| PLUG-190 | The system shall install, update and remove a plugin in the running application with no restart: installing a newer version of an installed plugin shall unload the old version (deactivating it, forgetting its code, folder and help), import and activate the new one in the same process, delete the old version's files and keep its enabled state, and shall restore the old version if the new one fails to load; the sidebar, Science and Options menus and dock panes shall be brought in line with what is loaded. A plugin whose Marketplace version is later than the installed one shall carry an **Update available** tag on its tile in both the Installed and Marketplace tabs, and its Installed tile shall have an **Update** button that downloads and applies it. Should an older version's folder survive (files in use), only the newest version shall be loaded at the next start. | MVP |
| PLUG-200 | **Plugin dependencies.** The system shall let a plugin's `plugin.toml` declare the third-party Python packages it needs (`requires`, PEP 508 specifiers); on install and update shall resolve and install them into an environment private to that plugin, shall fail the install and roll back completely if any cannot be resolved (including when offline), shall never alter Galileo's own environment, and shall remove the plugin's dependencies when the plugin is removed. | MVP |
| PLUG-210 | The system shall let a plugin register, through `PluginContext`, a declarative switch profile (`EQP-SW-080`) describing how a non-standard INDI driver's properties map onto the Switch model, without the plugin holding an INDI connection or writing device-protocol code. Profiles of a disabled plugin shall not be offered (`PLUG-060`) and profiles of a removed plugin shall be deregistered (`PLUG-120`); a malformed profile shall be rejected with a logged reason and shall not affect other profiles or the application. | P2 |

### 4.20 `UI` — Customization & Theming

| ID | Requirement | Priority |
|---|---|---|
| UI-010 | The system shall provide at least a light and a dark color theme, selectable by the user. | P2 |
| UI-011 | The system shall provide a red night-vision color theme, selectable by the user, that uses only red-channel colors (no green/blue component in any theme token, including the accent color) so it does not degrade dark-adapted night vision. | P2 |
| UI-020 | The system shall allow the imaging-tab panel arrangement to be customized (e.g. dockable/resizable panels) and persisted across restarts. | P2 |
| UI-030 | The system shall allow accent-color customization within a theme, except the night-vision theme (UI-011), whose accent is fixed to preserve UI-011's no-green/blue guarantee. | P3 |

### 4.20a `HELP` — In-App Help

| ID | Requirement | Priority |
|---|---|---|
| HELP-010 | The system shall ship help for every screen as Markdown files bundled with the application (one file per screen, one section per control), readable offline, so help is edited as text without changing code. | P2 |
| HELP-020 | The system shall resolve a control with no help entry on its own screen against its parent screen and then a shared set of common-control entries, so a control used on many screens is documented once. | P2 |
| HELP-030 | The system shall provide a help window, reachable from every screen, that lists all documented screens and their controls and can search the help text. | P2 |
| HELP-040 | The system shall show a short description when the user hovers any label, button or input that has a help entry, and shall find that entry from the control's visible text (form-row label, caption, button text or column header) without per-screen code. | P2 |
| HELP-050 | The system shall let the user open the detailed help for a single control: **F1** for the focused control (or the screen, if none), and point-and-click (**Shift+F1**) for any control. | P2 |
| HELP-060 | The system shall provide a developer audit that lists every control on every screen lacking a help entry, and plugins shall be able to register their own help content. | P3 |

### 4.20b `SUP` — Community & Support

| ID | Requirement | Priority |
|---|---|---|
| SUP-010 | The system shall provide, from the application's Help area and from the help window, links that open the project's community forum (GitHub Discussions) in the user's web browser: ask a question, browse discussions and suggest a feature. | P2 |
| SUP-020 | The system shall provide a "Report a problem" link that opens the project's bug-report form with the Galileo version, operating system, Python version and current screen prefilled, and shall transmit nothing itself -- the user reviews and submits the form in the browser. | P2 |
| SUP-030 | The repository shall provide issue and discussion forms (bug report, Q&A, ideas, show-and-tell) whose fields match the prefilled parameters, and shall direct questions and feature requests to Discussions rather than Issues. | P3 |

### 4.21 `LOG` — Diagnostics & Logging

| ID | Requirement | Priority |
|---|---|---|
| LOG-010 | The system shall run a runtime logging service that writes structured, timestamped application and session logs — capturing all runtime log output across every module and severity, not only curated diagnostic events — to a datestamped file under the application's own `logs/` directory. | MVP |
| LOG-020 | The system shall provide an in-app log viewer with severity filtering (info/warning/error). | MVP |
| LOG-030 | The system shall capture unhandled exceptions to the log with sufficient detail (stack trace, active sequence step, connected-device state) to diagnose post-hoc. | MVP |
| LOG-040 | The system shall allow exporting a support bundle (recent logs plus non-sensitive configuration) for bug reports. | P2 |
| LOG-050 | The logging service shall reset (start a new, truncated) datestamped log file at the beginning of every application run, rather than appending to a prior run's log. | MVP |
| LOG-060 | The system shall display, on every Equipment device-category screen, a scrollable pane showing the most recent log lines (at least the last 10 visible at once) without requiring the user to open a separate log viewer. | P2 |
| LOG-070 | The system shall install last-chance crash handlers at start-up (`sys.excepthook`, `threading.excepthook`, the asyncio loop exception handler and `faulthandler`) that write a crash report (traceback, version, platform, recent log tail, with credentials scrubbed) to a crash-reports directory under the platform data directory and, where the Qt application is running, show a fatal-error dialog. | MVP |

### 4.22 `LIB` — Image Library & Repository Management (merged from AstroFiler)

**`LIB-080` is retired** (left as a gap rather than renumbering, matching this document's ID conventions elsewhere): it specified a repository statistics dashboard (frame counts by object/filter/date/instrument, quality-metric trends), whose `StatsWidget` implementation and Library-screen tab were removed on request; retiring the requirement here brings the SRS/RTM back in line with that decision rather than leaving an MVP requirement permanently unmet with no code behind it and no one building toward it.

| ID | Requirement | Priority |
|---|---|---|
| LIB-010 | The system shall recursively scan a configured repository location, ingest discovered FITS files, and extract their header metadata into a catalog. XISF files shall also be ingested, converted best-effort to FITS at ingest time (Galileo's sole internal/output format per `EXT-060`) — an XISF file whose metadata or pixel data cannot be fully mapped shall still be converted with a logged warning identifying what was lost, rather than silently dropped or rejected outright. | MVP |
| LIB-020 | The system shall detect duplicate files within the repository via SHA-256 content hashing and allow the user to review and remove duplicates. | MVP |
| LIB-030 | The system shall automatically rename and organize ingested files into a configurable folder structure derived from FITS metadata (e.g. object, date, filter, session). | MVP |
| LIB-040 | The system shall automatically group and link related frames into sessions based on matching camera, binning, and temperature, plus acquisition date. | MVP |
| LIB-050 | The system shall create master bias, dark, flat, and flat-dark calibration frames from a linked calibration session. | MVP |
| LIB-060 | The system shall apply a matching master calibration frame set (dark subtraction, flat division) to a selected group of light frames in one user action. | MVP |
| LIB-070 | The system shall compute and store per-frame quality metrics (FWHM, HFR, eccentricity, SNR) for ingested frames, supporting later filtering and sorting by quality. | MVP |
| LIB-090 | The system shall browse and selectively download files from a SEESTAR or StellarMate smart telescope over SMB/CIFS (traces to `EXT-080`), enhancing headers as needed during ingest. | MVP |
| LIB-100 | The system shall browse and selectively download files from an iTelescope network share over FTPS (traces to `EXT-080`). | P2 |
| LIB-110 | The system shall browse and selectively download files from a DWARF smart telescope over FTP (traces to `EXT-080`), as an experimental capability; this covers every DWARF variant (DWARF 3, DWARF Mini, ...). | P3 |
| LIB-120 | The system shall synchronize repository contents bidirectionally with Google Cloud Storage (traces to `EXT-090`), using content-hash comparison to avoid redundant transfer, with at least "complete," "backup only," and "on demand" sync profiles. | P2 |
| LIB-130 | The system shall expose repository scanning (`LIB-010`), calibration-frame creation/application (`LIB-050`/`LIB-060`), and cloud sync (`LIB-120`) as command-line-invocable operations, independent of the GUI, for scheduled/automated execution — matching AstroFiler's own `LoadRepo`/`Calibrate`/`CloudSync` command-line utilities (Project Scope Document, Section 6.2), which this requirement generalizes (traces to `EXT-140`). | P2 |
| LIB-140 | The system shall verify file integrity via stored content hashes on demand, flagging any repository file whose content no longer matches its recorded hash. | P2 |
| LIB-150 | The system shall automatically register each frame into the repository catalog as it is written to disk during a running session (`SES`), rather than requiring a separate manual or scheduled scan (`LIB-010`) to discover it. | MVP |
| LIB-160 | The system shall automatically create a session container grouping every frame acquired during one session-block execution, distinct from `LIB-040`'s post-hoc heuristic (camera/binning/temperature/date) grouping of files already in the repository — a session-block container is authoritative because it comes directly from `SES` execution, not inferred from file metadata. | MVP |
| LIB-170 | The system shall browse and selectively download files from an SFTP server (traces to `EXT-120`): every FITS file under a configured remote folder, authenticating with the configured account and a key file or password (kept in the OS keychain, not `library.ini`), with a host-key policy that either logs or refuses unknown servers, from the Download dialog and the `galileo-download` command. This is the Library's only SFTP capability; plugins do not carry their own. | P2 |
| LIB-180 | The system shall treat flat-darks (dark frames taken at a flat's exposure, whatever the `IMAGETYP` spelling: "Flat Dark", "FLATDARK", "Dark Flat") as a calibration type of their own, distinct from darks and flats: filed under `Calibrate/FLATDARK`, grouped into their own sessions, linked to the flat session they match, stacked into a master flat-dark, and — when a light's flat has one — subtracted (less the bias) from that flat before it is normalised. Dark sessions (and flat-dark sessions) link to a target only when exposure matches numerically and CCD temperature is within 5 degrees. | MVP |
| LIB-190 | The system shall browse and selectively download raw FITS files from a Celestron Origin smart telescope over anonymous FTP (traces to `EXT-080`), addressed by IP address or an `origin`/`celestron` hostname, scanning its `RawData` folder. | P3 |
| LIB-200 | The system shall record for each frame (`fitsFile`) a **location** of *Local* or *On Master* (and the holding node), alongside the existing cloud-backed state, set only after the receiving node has verified the whole frame by content hash; an *On Master* frame keeps its catalog row, thumbnail and quality metrics. | MVP |
| LIB-210 | The system shall let a user **retrieve** an *On Master* frame back to the node (a Retrieve action in the Library screens, and a hook that any operation needing the file's pixels calls first), fetching it over Connect Link under the `data.pull` permission, verifying its hash and restoring it to *Local*. | MVP |
| LIB-220 | The system shall let a plugin delete the local copy of a frame whose *On Master* state is verified, and restore it later, without altering the catalog row's identity (its content hash). The Library screens shall show the location and offer Retrieve, with inline help. | MVP |

### 4.23 `VST` / `VST-AN` — Moved

Variable Star Target Planning and Variable Star Analysis & Photometry are no longer decomposed here — they are the VSTarget plugin's own requirements, specified in [`docs/plugins/vstarget/SRS.md`](../plugins/vstarget/SRS.md) Sections 4.1–4.2 against this document's `PLUG` domain (`PLUG-060`/`070`/`080`) and a small number of other core requirements consumed by reference (`SKY-030`, `EXT-110`, `PLT-010`, `SCHED-010`). This section number is kept as a placeholder rather than renumbered away, consistent with this document's ID-stability convention elsewhere (e.g. `SES`'s Section 4.5a).

### 4.24 `LINK` — Connect Link

Connect Link is the core service that carries all communication between a Galileo node and other nodes or clients: it is the one authenticated, encrypted listener, the one pairing-with-approval flow and the one scoped-permission model, shared by the NodeConnect, MobileConnect and WebConnect plugins ([NodeConnect PSD §6.2](plugins/nodeconnect/PSD.md)). Plugins register handlers against it and add no transport of their own.

`LINK-010`–`LINK-090` (the L1–L8 capabilities of that PSD, plus delegated identity `LINK-090`, added by WebConnect) and `LINK-220`–`LINK-270` (the shared relay, the shared request pipeline and the supporting audit, Options, secrets and disable requirements) are specified here; `LINK-100`–`LINK-210` specify **L9, the outreach event facility**.

| ID | Requirement | Priority |
|---|---|---|
| LINK-010 | **(L1) Listener.** The system shall run at most one Connect Link listener per node, serving HTTPS and WebSocket over TLS 1.2 or later, started only while at least one enabled plugin (or core service) has registered a route and stopped when none has. It shall bind to the node's LAN interface by default (never `0.0.0.0` unless the owner chooses it), on a configurable port. A self-signed certificate shall be generated on first use with its private key held in the secret store (never a file); a user-supplied certificate and key shall replace it. Apart from *request pairing* and, during an outreach event, *outreach enrolment* (`LINK-130`), the listener shall answer no request that does not carry a valid peer token. | MVP |
| LINK-020 | **(L2) Pairing with approval.** The system shall pair a peer only by a request the peer sends, held until a person approves it on the receiving node, after which a per-peer token and pinned certificate are issued. The pairing request shall identify the peer (name, kind, platform) and carry a short **confirmation code** that is displayed both on the requesting client and beside the request on the receiving node, so a person approves the request they intend to (apps, browsers and nodes alike). Pending requests shall expire after a configurable time (default five minutes), shall be rate-limited per source address, and shall be refused when the pending list is full. The only endpoints that answer a caller without a valid token are *request pairing* and, during an outreach event, *outreach enrolment* (`LINK-130`). Tokens shall be stored only as salted hashes on the node. Pairings shall be revocable per peer, taking effect at once: the peer's streams are closed and its token refused. | MVP |
| LINK-030 | **(L3) Scoped permissions and audit.** The system shall hold a set of permissions per peer — `config.read`, `config.write`, `data.push`, `data.pull`, `control`, `view` — and the guest-only `outreach.view`; shall never grant `outreach.view` to a paired peer or any paired-peer permission to a guest; shall check the permission a route declares before its handler runs; and shall keep an audit log of who did what (`LINK-240`). The permissions a peer may be granted shall be limited to those the plugin that paired it declares (for example NodeConnect: `config.*`, `data.*`; MobileConnect and WebConnect: `control`, `view`, never `config.*`). | MVP |
| LINK-040 | **(L4) Discovery.** The system shall advertise the node on the LAN by mDNS/zeroconf (service `_galileo-link._tcp`, carrying only the node's display name, node id, port, protocol version and role hint, never a secret) while the listener runs, and shall browse for other nodes' advertisements. A client shall also be able to connect to a manually entered host and port. Advertisement shall stop when the listener stops. | MVP |
| LINK-050 | **(L5) Routes.** The system shall let a plugin register versioned request/response routes under its own prefix (for example `/nodeconnect/v1/...`), each declaring the permission it requires, and shall unregister them when the plugin is disabled or removed. Authentication, permission check and audit shall occur before a handler is found, so an unauthenticated caller cannot learn which routes exist. A plugin shall not be able to register under another plugin's or core's prefix. | MVP |
| LINK-060 | **(L6) Event stream.** The system shall provide a server-push event stream to each connected peer, carrying plugin-defined messages tagged with a per-stream sequence id; a peer that reconnects with its last id shall receive the messages it missed while they are still within a bounded replay window, or be told to resynchronise. The stream shall be closed immediately when the peer is revoked or the plugin disabled. | MVP |
| LINK-070 | **(L7) Transfer.** The system shall provide resumable, chunked, checksummed (SHA-256) binary transfer in both directions, in which an interrupted transfer resumes from the last verified chunk, the whole object is verified before it is reported complete, the receiver can recognise an object it already holds by hash, and transfers run at a priority below interactive requests and below a running session's own work. | MVP |
| LINK-080 | **(L8) Handshake.** The system shall perform a version handshake exchanging the Galileo version, plugin-API version, schema (migration) level and Connect Link protocol version, shall let a plugin extend the handshake payload (for example with capability limits), and shall, on an incompatible schema or protocol version, refuse or restrict the exchange with a message a person can read. | MVP |
| LINK-090 | **(DG) Delegated identity.** The system shall let a peer holding a service credential registered by a plugin present a request **on behalf of** a named, approved client peer of the same plugin. Connect Link shall resolve that client to its own role, scopes and expiry and apply them, not the service's; shall refuse a request naming a client that is revoked, expired or unknown or that belongs to another plugin; shall honour the acting-client designation only from the service credential and only on that plugin's routes; shall never let the service credential hold `config.*`; and shall record the **client** as the actor in the audit log (with the service as carrier). | MVP |
| LINK-100 | **Outreach event lifecycle (L9).** The system shall provide outreach as an **event** that is **off by default**, opened on the Master by its owner with a duration and ended by the end of that duration, by the owner, by disabling Connect Link or by a restart. While no event is open, the system shall register no outreach route, open no outreach listener and answer no outreach request. Ending an event shall disconnect every guest and invalidate every guest token and the event secret. | MVP |
| LINK-110 | **Event options.** The system shall store in Galileo's settings store (never a file): the outreach Wi-Fi network name (SSID); an optional Wi-Fi passphrase, held as a secret in the OS keychain and never logged or audited; the outreach **subnet(s)** as private-range CIDRs; the default duration; the concurrent-guest cap; the guest preview size and quality; the Piers offered for outreach; and which registered surfaces (`LINK-200`) are enabled. Values shall be validated and clamped; a non-private subnet shall be rejected. | MVP |
| LINK-120 | **Event secret.** On opening an event the system shall generate a cryptographically random secret of at least 128 bits, unique to the event, hold it only in memory (as a salted hash once shown), and be able to re-issue it during the event, whereupon enrolments with the old secret shall be refused and already-enrolled guests shall be unaffected. | MVP |
| LINK-130 | **Guest enrolment.** The system shall accept an enrolment that presents the current secret from an address inside an outreach subnet and issue an anonymous **guest token**: opaque, random, bound to the event, expiring when the event ends, carrying only `outreach.view`. Enrolment shall require no name, account or per-device approval. The secret shall be compared in constant time, enrolment attempts shall be rate-limited, and every refusal (wrong secret, wrong subnet, event closed or full) shall be indistinguishable to the caller from a closed port, apart from a readable reason only when the caller holds the secret and the event is full. | MVP |
| LINK-140 | **Subnet confinement.** The system shall check the source address against the outreach subnet(s) **before reading any request body**, on enrolment, on every guest request and on every message of a guest stream, and shall refuse and disconnect any source outside them, including routed, forwarded or internet-originating traffic. If no subnet is configured, an event shall not open. | MVP |
| LINK-150 | **Guest principal and allowlist.** The system shall represent a guest as a principal type of its own with no role, no lease and no catalogue. A guest shall be permitted exactly three operations — list the Piers offered for outreach (display names only), receive the live image of an offered Pier, and switch to another offered Pier — and every other request shall be refused and counted before reaching any plugin handler. A plugin shall not be able to widen the allowlist. | MVP |
| LINK-160 | **Live image and guest previews.** The system shall push to each guest the live image of the Pier it is viewing as each frame completes (for a Pier of this node from its frame-complete event; for a spoke's Pier via the relay, only if that node has granted `view`), shall send the most recent image at once to a guest that joins or switches, and shall produce that image through the core preview service in a **guest mode** that encodes from pixel data with **no FITS header, EXIF, GPS or other embedded metadata**, at no more than the guest preview size and quality. | MVP |
| LINK-170 | **Guest load bounds.** The system shall limit concurrent guests to the configured cap, rate-limit each guest, and give guest work lower priority than a running session and than every paired peer, so that guests never delay imaging or the Emergency operations. | MVP |
| LINK-180 | **Event audit.** The system shall audit each event — who opened and ended it, when, the Piers offered, the surfaces enabled, peak and total guests, and refusals by kind — and aggregate guest counts per Pier, and shall record no personal data about guests: a guest is a random token and a source address held in memory for the duration of the event only. | MVP |
| LINK-190 | **Owner controls and event display.** The system shall provide a Connect Link **Outreach** page on the Master, from which the owner opens, extends and ends an event, ejects all guests, re-issues the secret, sees the time remaining, the guest count and the offered Piers, and sees the **event display**: a standard Wi-Fi QR code for the outreach SSID (with the passphrase only if one is set) and one enrolment QR code per enabled surface, each built from the payload that surface supplies. | MVP |
| LINK-200 | **Surfaces.** The system shall let a plugin register an **outreach surface** — a name, preconditions, the enrolment payload for its QR code, and the transport by which it delivers the facility's guest messages (image, unavailable, ended) — and shall register that surface's routes or listener only while an event is open and the surface is enabled. A surface shall be given the secret only to build its payload, shall be unable to read tokens, issue tokens or alter the allowlist, and shall be able to withhold the event from opening by reporting an unmet precondition (for example, no HTTPS certificate). | MVP |
| LINK-210 | **Fail closed; nothing durable.** The system shall not open an event if any enabled surface reports an unmet precondition or if the subnet check cannot be applied; shall confine a fault in guest handling to the one guest and a fault in a surface to that surface; shall close the event if its in-memory state is lost; and shall never write the secret or any guest token to the database, a file or a log. A restart therefore voids every guest. | MVP |
| LINK-220 | **(WR) Master relay.** The system shall provide in core one relay by which a Master node presents the Piers of every paired spoke node, with the Master's own, as one list, and relays operations, state, events and previews for a spoke's Pier over Connect Link, forwarding the originating client's identity so the spoke can audit it. A spoke shall be reachable only under an opt-in grant (`control`/`view`, never `config.*`) made on the spoke and revocable there at any time; a spoke without the grant shall appear view-only or be absent, and the client told which. The lease for a spoke's Pier shall be held on that spoke (`LEASE-070`). An unreachable spoke shall be reported as such with the time last heard, operations to it refused with that reason, and the relay shall re-attach without re-pairing. Previews shall be rendered on the owning node and relayed. The relay shall expose one interface (`RelayPort`) that contains nothing specific to any front-end plugin. | MVP |
| LINK-230 | **(GW) Request pipeline.** The system shall provide in core one request pipeline (`Gateway`) through which every operation request from a paired client, a relayed spoke request or an outreach guest passes, in fixed order: identify, authorise, validate (against the Control Surface catalogue, `CSURF-040`), lease (`LEASE-060`), confirm (a two-step token for confirm-class operations), idempotency (by client-supplied key; a retried key returns the original result), dispatch (under a load governor with a strict priority order in which emergency operations and a running session come before everything else) and audit (always, including on refusal and error). The pipeline shall reject any catalogue entry of class *config* at start-up (`CSURF-020`), shall never swallow or override a safety refusal, shall return a typed outcome (`ok`, `refused`, `invalid`, `unavailable`, `busy`, `unreachable`) with a displayable reason, shall rate-limit per client, and shall be the only path from a Connect Link route to a domain service. MobileConnect and WebConnect shall consume it through `GatewayPort`, each supplying only its own front-end surface. | MVP |
| LINK-240 | **Audit log.** The system shall keep the Connect Link audit log in a table owned by core (a numbered migration; no plugin ships one), recording for each event the time, the acting peer, the carrying peer (when delegated), the plugin, the route or operation, the outcome and a reason; plugin-defined fields shall be accepted and stored; retention shall be configurable (an option, default 90 days) and enforced; the log shall be queryable by peer and time; and it shall never hold a token, secret, passphrase or guest identifier. | MVP |
| LINK-250 | **Connect Link Options page.** The system shall provide an Options > Connect Link page on which the owner sees the listener's state, port and certificate fingerprint; sees pending pairing requests with their confirmation codes and approves or rejects each; lists paired peers with their kind, plugin, granted permissions and last contact; revokes or deletes a peer; sets the pairing expiry, audit retention and port; and opens the Outreach page (`LINK-190`). Every control shall have inline help. | MVP |
| LINK-260 | **Secrets and configuration.** The system shall store peer-token hashes, service-credential hashes and Connect Link settings in the shared database through the settings store, and TLS private keys and the outreach passphrase in the secret store, never in a configuration file; the only bootstrap exception is the pointer that locates the database itself. | MVP |
| LINK-270 | **Disable.** Disabling Connect Link, or the last plugin that uses it, shall close the listener, end every stream and every outreach event, stop the advertisement and leave no listener or worker, with the pairings preserved so re-enabling needs no re-pairing. | MVP |

### 4.25 `CSURF` — Control Surface (with operation events and held motion)

The Control Surface is the registry through which a domain service declares its **operator-level operations** and **observable state**, so that a remote client is driven from a *catalogue* rather than by code reaching into each module. It is the contract the MobileConnect and WebConnect plugins ([MobileConnect SRS §2.6](plugins/mobileconnect/SRS.md), prerequisites CS, OE, DM) are written against; the desktop UI is not required to use it in v1. The boundary rule is that an operation which takes effect on the sky or on the night's data is in scope and an edit to a stored definition of the observatory (profiles, Observatories, safety limits, Options) is not.

| ID | Requirement | Priority |
|---|---|---|
| CSURF-010 | The system shall provide a registry (`galileo.control_surface`) in which each domain service declares its operations — name, argument schema (names, types, ranges, units, defaults), result schema, permission class (`CSURF-020`), whether it needs the Pier's control lease (`LEASE-060`), whether it is long-running (`CSURF-070`) and an availability predicate — and its observable state (`CSURF-060`). A service shall register by declaration, so that a new operation needs no change in any remote-client plugin. | MVP |
| CSURF-020 | Every operation shall carry exactly one permission class: `read` (state and images only), `operate` (an effect on the sky or the night's data), `confirm` (an operation that is destructive or hard to reverse and needs a two-step confirmation, for example abort a series, stop a session, park, unpark with a dome, run a flip) or `emergency` (`CSURF-300`). The registry shall **refuse at registration** any entry that would edit a stored definition of the observatory (class *config*), and shall do so again at start-up of every consumer. | MVP |
| CSURF-030 | The system shall publish the catalogue — each entry with its schema, class, lease requirement and a version — and shall report, per entry and per Pier, whether it is currently available and, if not, why (no such device, not connected, area not installed). A client shall be able to be driven by the catalogue alone. | MVP |
| CSURF-040 | `invoke(name, arguments, pier, principal)` shall validate the arguments against the declared schema **before** calling the service, and return a typed outcome (`ok`, `refused`, `invalid` with the field path, `unavailable`, `busy`, `unreachable`) with a reason a person can read, never an exception. A request naming anything outside the catalogue, or that would alter a stored definition, shall be `unavailable`. | MVP |
| CSURF-050 | An operation shall invoke **the same domain service method** the desktop screen uses, subject to the same checks, limits and safety interlocks; there shall be no second implementation. No operation shall disable the safety monitor, clear an unsafe state or override a mount limit, and a refusal by the safety service shall be returned verbatim as `refused` with the reason. | MVP |
| CSURF-060 | Each service shall declare its **observable state** per Pier (for example mount position and tracking, camera temperature and exposure state, focuser position, guiding error, session progress, safety inputs), readable on demand and subscribable. A subscription shall deliver a snapshot followed by changes, each tagged with a per-Pier sequence number, so a subscriber can detect a gap and request a new snapshot. | MVP |
| CSURF-070 | A long-running operation (slew, plate solve, autofocus run, calibration set, session, flip) shall publish on the event bus **started**, zero or more **progress**, and exactly one **finished** event (carrying the outcome and a reason), all with a correlation id returned to the caller, so a client can show progress and notify on completion without polling. | MVP |
| CSURF-080 | The registry shall be usable with no remote plugin installed: registering an operation, publishing its events and reading state shall add no listener, thread or measurable cost, and a failure in a subscriber shall never reach the service (`ARCH-060`). | MVP |
| CSURF-100 | **Observatory and Pier.** The catalogue shall let a client list Observatories and Piers, choose the working Pier and read the Dashboard timelines (`OBS-150`) of every Pier. | MVP |
| CSURF-110 | **Devices.** The catalogue shall offer: connect and disconnect each device; mount — slew, sync, track on/off and rate, park/unpark, find home, pulse, held jog; camera — set cooling and temperature, gain/offset/binning/ROI per exposure, expose, abort; filter wheel — select; rotator — move; dome — open, close, slew, follow; flat panel — on/off and brightness; switches — toggle; and the weather and safety-monitor state (read). Connecting a mount through the Control Surface shall perform the same date/time and site synchronisation as connecting at the desktop. Focuser movement shall be offered only under Focus (`CSURF-150`). | MVP |
| CSURF-120 | **Imaging.** The catalogue shall offer the live exposure loop, single and series capture, the current-frame preview with histogram and image statistics (star count, HFR, FWHM), the live-stack view and frame rejection. | MVP |
| CSURF-130 | **Sky and framing.** The catalogue shall offer the sky view with the mount's position, target search and selection, go-to, the Framing Assistant (field of view, rotation, mosaic panels), current-object details, the Planning and visibility lists, and the Telescopius and AAVSO targets already available to the node. | MVP |
| CSURF-140 | **Plate solving and alignment.** The catalogue shall offer solve current/last frame, centre on target, sync and run a polar-alignment routine. | MVP |
| CSURF-150 | **Focus.** The catalogue shall present the focus module as one place: manual focus (`FOC-100`) and autofocus — start and cancel a run, the V-curve and result, temperature-compensation state. | MVP |
| CSURF-160 | **Guiding.** The catalogue shall offer connect/disconnect of the guider service, start/stop guiding, dither, recalibrate, and the error trace and guide-star cut-out. | MVP |
| CSURF-170 | **Meridian flip.** The catalogue shall expose flip state, the time to flip and the outcome (read), and trigger or defer a flip where the service allows it, the trigger being a `confirm` operation. | MVP |
| CSURF-180 | **Sessions, run.** The catalogue shall offer list and load saved sessions, run, pause, resume, skip step and stop, with progress block by block. | MVP |
| CSURF-190 | **Sessions, authoring.** The catalogue shall offer add, remove, reorder and nest instruction, condition and trigger blocks, set their parameters and save, over the same Sessions model as the desktop, including plugin-registered blocks (`SES-340`); `.gses` for import and export. | P2 |
| CSURF-200 | **Scheduler.** The catalogue shall offer view the job queue and next job, create, edit, delete, enable/disable, reorder and run-now jobs, including adding a job from a target chosen in the sky view. | P2 |
| CSURF-210 | **Calibration.** The catalogue shall offer start dark, flat and bias sets and their progress. | P2 |
| CSURF-220 | **Safety.** The catalogue shall expose every safety input, the overall state and the reason a session stopped (read), and **acknowledge** an event. After a safety stop the only operation offered shall be acknowledge; resuming remains the decision of the safety service. | MVP |
| CSURF-230 | **Library and history.** The catalogue shall offer browsing of recent sessions and frames (thumbnails, quality metrics), frame previews, session history and charts (read), and the explicit download of a full FITS frame as an `operate` operation that reports the size first. | P2 |
| CSURF-240 | **Notifications.** The catalogue shall expose recent alerts (read). Notification channels and rules are configuration and shall not be offered. | P2 |
| CSURF-250 | **Plugin surfaces.** A plugin shall be able to register operations and state in the Control Surface under its own namespace, subject to every rule above, and they shall appear in the catalogue. | P3 |
| CSURF-300 | **Emergency operations.** The catalogue shall contain three `emergency` operations — **stop everything**, **park**, **close dome** — which need no lease, may be called by any paired operator, complete in a single request once confirmed on the client, take priority over every other work, and are always audited. | MVP |
| CSURF-400 | **Held motion.** An operation that moves hardware only while a button is held (a manual slew or jog, a manual focuser move) shall be started as a *hold* returning a hold id; the holder shall send a keep-alive (`beat`) at a configured interval; and the service shall **stop the motion** when the keep-alive stops, the holder disconnects, the holder's lease is taken or released, or `stop` is called. | MVP |
| CSURF-410 | The keep-alive interval and the deadman timeout shall be options (defaults 250 ms and 600 ms), validated so that the timeout exceeds twice the interval, and motion shall stop within one second of the last keep-alive in every case. | MVP |
| CSURF-420 | A hold shall be cancelled at once on revocation of the holder's pairing, on disabling the plugin that started it and on a safety stop. | MVP |

### 4.26 `LEASE` — Control Lease

A **control lease** per Pier lets the desktop UI and any number of remote clients contend for the right to issue Pier-affecting commands through one authority, so a desktop and a tablet cannot give a mount conflicting commands at the same moment.

| ID | Requirement | Priority |
|---|---|---|
| LEASE-010 | The system shall keep, for each Pier, at most one **lease holder**, identified as the local desktop or as a named remote client. The lease shall be held in memory only and be clear after a restart. | MVP |
| LEASE-020 | A request to acquire the lease of a Pier with no holder shall be granted at once. | MVP |
| LEASE-030 | A request to acquire a lease held by another shall be refused with the holder's identity and an offer to **take it over**, which requires a confirmation by the requester; taking it over shall notify the previous holder. | MVP |
| LEASE-040 | The lease shall be released on request, on the holder's disconnect or revocation, and after a configurable idle time with no operation by the holder (default 10 minutes); the other clients and the desktop shall be told. | MVP |
| LEASE-050 | A change of holder shall be published on the event bus (`ARCH-060`), so that the desktop shows who holds the lease and every client's view stays correct. | MVP |
| LEASE-060 | An operation whose catalogue entry requires the lease (`CSURF-010`) shall be refused when the caller is not the holder, with `refused` and the holder named. The desktop UI shall honour the same lease: when a remote client holds it the desktop shall show the holder and offer a take-over, rather than silently issue a conflicting command. Read operations and `emergency` operations need no lease. | MVP |
| LEASE-070 | The lease for a spoke node's Pier shall be held **on that spoke**, so that its desktop, a client paired to it and the Master's relay (`LINK-220`) contend through one lease; the Master shall keep no copy of truth. | MVP |
| LEASE-080 | Taking or losing the lease shall stop any held motion of the previous holder (`CSURF-400`). | MVP |

### 4.27 `PREV` — Preview Service

The preview service renders images on the node that owns them, so a remote client receives a small stretched JPEG or a tile instead of a FITS file. It is used by remote clients and by the outreach facility's guest mode (`LINK-160`).

| ID | Requirement | Priority |
|---|---|---|
| PREV-010 | The system shall render, from a frame reference, a preview with a requested stretch, binning, size and JPEG quality, for the current exposure, any Library frame, the live stack and a guide or focus cut-out; the result shall carry the histogram and image statistics (star count, HFR, FWHM) where requested. | MVP |
| PREV-020 | The system shall render a **tile pyramid** (levels, x, y) of a frame with the stretch applied on the node, so a client can pan and zoom, and shall let a client hold tiles of two frames with identical parameters at once for blink and side-by-side comparison. | MVP |
| PREV-030 | Rendered previews and tiles shall be cached under a bounded byte budget (an option) keyed by frame and parameters, so repeated requests do not re-render; the cache shall be evicted least-recently-used and shall hold nothing a guest could see (`PREV-050`). | MVP |
| PREV-040 | Rendering shall never run on the UI thread and shall follow the concurrency model (`asyncio.to_thread` for pure-numpy work, `run_cpu` for GIL-holding work); it shall run at the lowest scheduling class, be dropped or delayed before session work is, and degrade (smaller size, lower quality) rather than delay imaging. | MVP |
| PREV-050 | A **guest mode** shall encode from pixel data with **no FITS header, EXIF, GPS or other embedded metadata**, at no more than a stated size and quality, and shall verify the output contains no segment beyond the minimum (an `assert_clean` check) before it is returned. | MVP |
| PREV-060 | A client shall be able to request a lower quality or size to suit its link, bounded by the options `preview.max_size` and `preview.quality`. | P2 |

### 4.28 `SKYSTR` — Sky Data Streaming

A service by which the Master supplies sky data so that remote clients (the Meta Quest and tablet planetarium views above all) render the sky from streamed data rather than from a catalog and ephemeris they carry. It reuses the bundled catalog of `galileo.planning.sky_atlas`; it adds no second catalog.

| ID | Requirement | Priority |
|---|---|---|
| SKYSTR-010 | The system shall serve catalog objects by region (centre, radius), limiting magnitude and level of detail, **progressively** (bright objects first, fainter as they arrive), with a cursor so an interrupted stream resumes from where it stopped. | MVP |
| SKYSTR-020 | Responses shall be compact: quantised, delta-coded binary with a versioned encoding, so a client can decode a response of any previous encoding version still advertised in the capability report. | MVP |
| SKYSTR-030 | The system shall serve ephemeris (Sun, Moon, planets, and the topocentric positions needed to draw them) for an instant and for a time range, so that a client can scrub time without computing positions. | MVP |
| SKYSTR-040 | The system shall serve the Observatory location and the horizon profile of the working Pier, and the live pointing and field of view of its mount. | MVP |
| SKYSTR-050 | Every response shall carry the Master's **as-of time**, so that clients agree with the Master on time and pointing. | MVP |
| SKYSTR-060 | The system shall report a **capability** — whether streaming is available and at what limits (detail, rate, concurrent clients) — which the Master derives from a measurement of its own hardware rather than from a platform name; on a Raspberry Pi-class Master it shall report VR-class streaming unavailable, with a reason a client can display, and shall serve tablet, phone and browser clients with reduced limits. | MVP |
| SKYSTR-070 | Streaming shall always yield to a running session, be rate-limited per client, limit the number of concurrently streaming clients to the figure in the capability report, and degrade detail before delaying anything else; it shall never interrupt imaging or the emergency operations. | MVP |
| SKYSTR-080 | The system shall render a **static sky image** for a region and time (stars to a limiting magnitude, constellation lines, the mount's position, the field of view and the horizon) on the Master, for a client that cannot render the sky itself. | MVP |

### 4.29 `REPL` — Replication Support (change tracking, registry, busy signal, sync tables)

Facilities in core that let the NodeConnect plugin ([NodeConnect SRS §2.6](plugins/nodeconnect/SRS.md), prerequisites C1–C6) replicate configuration between nodes without the plugin editing core tables. They are useful on their own (the settings-changed event and the busy signal) and add no cost when no plugin uses them. The loopback-address rule (prerequisite C5) is `PROF-130` and `GUIDE-100`; the Library location state (C7) is `LIB-200`–`LIB-220`.

| ID | Requirement | Priority |
|---|---|---|
| REPL-010 | Each **replicable** table shall carry a modification timestamp (UTC), a revision number (`rev`) issued by the Master as one monotonic sequence, a `dirty` flag set when a local write occurs, and the `base_rev` the local edit started from; a write hook shall maintain them for every ordinary write to the table. The columns shall be added by numbered migration under `galileo/library/migrations/`. | MVP |
| REPL-020 | The deletion of a row of a replicable table shall leave a **tombstone** (table, natural key, revision, time), kept until released by the sync owner (`REPL-070`), so that a deletion can be propagated. | MVP |
| REPL-030 | A model shall declare itself replicable to a **registry** with its natural key, its dependency order, its node-local fields, its secret fields and its `to_wire`/`from_wire` converters; `specs()` shall return them in dependency order. A table registered later, including one from a plugin, shall be replicated with no change to the consumer. | MVP |
| REPL-040 | A check run in the test suite shall fail when a table that holds configuration is neither registered nor on an explicit *not configuration* list (the Library catalog tables are on it), so the definition of "complete" stays true as Galileo grows. | MVP |
| REPL-050 | The system shall publish a **settings-changed** event on the event bus, naming the tables, after a bulk apply of replicated rows, and open Options pages and screens shall reload their values on receiving it. | MVP |
| REPL-060 | The session executor shall expose a **busy signal**: `is_busy()` (a session or calibration run is executing) and `on_idle(callback)`, so a bulk apply can wait for an imaging session to end. | MVP |
| REPL-070 | Core shall own, by numbered migrations, the **sync tables** — outbox, inbox, snapshots, run reports, transfer queue and per-node sync state — and offer typed access to them through one storage interface, so a plugin ships no migration and the migration rule of the persistence layer is kept. A plugin shall be able to release tombstones (`REPL-020`) through it. | MVP |
| REPL-080 | The Master shall issue revisions serially per table, so a revision is a total order within a table, and shall expose `commit_rev()` for the arbitration step; a spoke shall never issue a revision. | MVP |

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
| EQP (generic + device) | 44 | 20 | 24 | 0 |
| PROF | 13 | 12 | 1 | 0 |
| IMG | 20 | 10 | 10 | 0 |
| SES (formerly `SEQ`/`SEQ-ADV`; Sections 4.5–4.6) | 30 | 17 | 10 | 3 |
| SKY | 12 | 8 | 4 | 0 |
| WUT | 10 | 8 | 1 | 1 |
| FRAME | 9 | 4 | 5 | 0 |
| SKYMAP | 9 | 3 | 6 | 0 |
| SCHED | 10 | 8 | 2 | 0 |
| CAL | 6 | 5 | 1 | 0 |
| FOC | 13 | 10 | 3 | 0 |
| PLT | 7 | 6 | 1 | 0 |
| MFLIP | 4 | 0 | 4 | 0 |
| GUIDE | 10 | 8 | 2 | 0 |
| DOME | 3 | 0 | 3 | 0 |
| SAFE | 10 | 2 | 5 | 3 |
| HIST | 5 | 1 | 3 | 1 |
| META | 5 | 3 | 1 | 1 |
| NOTIF | 5 | 0 | 1 | 4 |
| PLUG | 21 | 19 | 2 | 0 |
| LINK | 27 | 27 | 0 | 0 |
| CSURF | 28 | 22 | 5 | 1 |
| LEASE | 8 | 8 | 0 | 0 |
| PREV | 6 | 5 | 1 | 0 |
| SKYSTR | 8 | 8 | 0 | 0 |
| REPL | 8 | 8 | 0 | 0 |
| UI | 3 | 0 | 2 | 1 |
| LOG | 6 | 4 | 2 | 0 |
| LIB | 21 | 14 | 5 | 2 |
| NFR-PERF | 3 | 3 | 0 | 0 |
| NFR-REL | 4 | 3 | 1 | 0 |
| NFR-PORT | 2 | 2 | 0 | 0 |
| NFR-EXT | 1 | 0 | 1 | 0 |
| NFR-USE | 2 | 1 | 1 | 0 |
| NFR-I18N | 1 | 1 | 0 | 0 |
| NFR-SEC | 3 | 1 | 2 | 0 |
| NFR-OFFLINE | 2 | 2 | 0 | 0 |
| NFR-INSTALL | 3 | 3 | 0 | 0 |
| **Total** | **338** (exact sum of the rows above; `EXT` requirements are not counted here, see Section 3; `VST`/`VST-AN` moved to the VSTarget plugin's own SRS, Section 4.23 — several other domain rows above are currently stale against the body and due a full re-audit, tracked separately from this revision) | | | |

---

## 7. Path to SDD / Traceability Matrix

1. **SDD** — One architecture/component section per domain in Sections 4–5, describing how the device-abstraction layer (`ARCH`), plugin framework (`PLUG`), and per-domain services satisfy the requirements above.
2. **Traceability Matrix** — A row per requirement ID in this document, mapped to its SDD component(s) and verifying test case(s); Section 6's counts are the expected row totals per domain, useful for sanity-checking matrix completeness.

---

*This document is a living draft. Requirement wording, priorities, and the `SES` (Section 4.6) instruction/trigger/condition catalog in particular should be reviewed against current NINA behavior and INDI/Alpaca capability coverage before being frozen for SDD authoring.*
