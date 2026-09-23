# VSTarget Plugin — SRS (Software Requirements Specification)

| | |
|---|---|
| **Project** | Galileo — VSTarget Plugin |
| **Document** | SRS (Software Requirements Specification), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-09-23 |
| **Upstream document** | [PSD (Project Scope Document)](PSD.md) |
| **Downstream documents** | SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SRS](../../SRS.md) |

---

## 1. Introduction

### 1.1 Purpose

This SRS decomposes the requirement domains identified in [this plugin's PSD](PSD.md) (Section 8) into individually numbered, verifiable requirements, structurally parallel to [Galileo core's own SRS](../../SRS.md). `VST`/`VST-AN` IDs are unchanged from their original core-embedded form — only the document they live in moved.

### 1.2 Scope

Covers the `VST` and `VST-AN` domains plus one plugin-scoped external-interface requirement (`VST-EXT-010`, AAVSO API access) that has no other consumer in Galileo core and so does not belong in core's own `EXT` domain. Everything else this plugin depends on (device abstraction, the plugin framework, visibility computation, plate solving, Simbad lookup, remote-telescope FTP/FTPS/SFTP retrieval, Scheduler submission) is an existing core requirement, listed in [PSD.md Section 7](PSD.md#7-dependencies-on-galileo-core) and cited by ID below rather than redefined here.

### 1.3 Requirement ID Convention

Unchanged from core: `<DOMAIN>-<###>`, numbered in increments of 10. `VST-EXT-010` follows the same convention with a plugin-local `EXT` sub-prefix, distinguishing it from core's own `EXT-*` numbering rather than colliding with it.

### 1.4 Priority Convention

Identical to [core SRS Section 1.4](../../SRS.md#14-priority-convention): MVP / P2 / P3.

### 1.5 Definitions, Acronyms, Abbreviations

See [this plugin's PSD Glossary](PSD.md#13-glossary) and [core PSD's Glossary](../../PSD.md#15-glossary).

### 1.6 References

- [This plugin's PSD](PSD.md)
- [Galileo Core SRS](../../SRS.md)
- AAVSO Target Tool API / VSP: https://www.aavso.org/

---

## 2. Overall Description

### 2.1 Product Perspective

This plugin is not a standalone product — it is a first-party, pre-loaded plugin against Galileo core's plugin architecture (core `PLUG` domain), loaded in-process at application start alongside core, independently enabled/disabled by the user.

### 2.2 Product Functions (Summary)

AAVSO variable-star target planning (catalog sync, observation-plan editing, observing-script generation, direct Scheduler submission) and photometric analysis (remote-image retrieval, plate solving via core, registered mean-stacking, aperture photometry, AAVSO WebObs reporting, transformation-coefficient calibration, exposure-time calculation).

### 2.3 User Classes and Characteristics

See [core PSD Section 10](../../PSD.md#10-stakeholders-and-primary-personas) and [this plugin's PSD Section 9](PSD.md#9-stakeholders-and-primary-persona) — the Variable Star Observer (AAVSO contributor) persona.

### 2.4 Operating Environment

Identical to core (Windows/macOS/Linux) — this plugin introduces no additional platform constraint.

### 2.5 Design and Implementation Constraints

- Loaded exclusively through core's plugin extension points (`PLUG-010`–`PLUG-080`); no direct import of core adapter internals (mirrors core SRS Section 2.5's `ARCH-010` constraint, applied to this plugin specifically).
- No bundled device control of its own — image capture is performed by core (`EQP-CAM-*`) or the image is retrieved pre-captured from a remote-telescope network.

### 2.6 Assumptions and Dependencies

See [this plugin's PSD Section 7](PSD.md#7-dependencies-on-galileo-core) (core capabilities consumed) and Section 10 (PC1–PC3, licensing/dependency assumptions).

---

## 3. External Interface Requirements (Plugin-Scoped)

| ID | Requirement | Priority |
|---|---|---|
| VST-EXT-010 | The system shall retrieve variable-star target data from the AAVSO Target Tool API and comparison-star data from the AAVSO VSP API. | MVP |

Every other external interface this plugin uses is an existing core requirement: Simbad lookup (core `EXT-110`), remote-telescope FTP/FTPS/SFTP retrieval (core `EXT-080`/`EXT-120`) — see [PSD.md Section 7](PSD.md#7-dependencies-on-galileo-core).

---

## 4. Functional Requirements

### 4.1 `VST` — Variable Star Target Planning

Delivered as a first-party, pre-loaded, independently disableable plugin (core `PLUG-060`), not a core-compiled module — enabling it is functionally equivalent to having it built into core. Presented as a peer-level UI section to the Sky Atlas/Targets screen (core `SKY`) at the primary navigation level (core `PLUG-070`), not nested beneath it, when enabled.

| ID | Requirement | Priority |
|---|---|---|
| VST-010 | The system shall synchronize variable-star target data from the AAVSO Target Tool API (traces to `VST-EXT-010`), filterable by observing section (e.g. Alerts, Cataclysmic Variables, Eclipsing Variables, Long Period Variables). | MVP |
| VST-020 | The system shall display a sortable, searchable variable-star target list with priority indication and solar-conjunction warnings. | MVP |
| VST-030 | The system shall filter the variable-star target list to targets observable from the configured observing location during the current/next night, reusing the visibility computation shared with core `SKY-030`. | MVP |
| VST-040 | The system shall support manual import of a variable-star target list from a delimited text file as an alternative to the AAVSO API. | P2 |
| VST-050 | The system shall provide an observation-plan editor allowing per-target filter, exposure count, exposure interval, and binning configuration. | MVP |
| VST-060 | The system shall generate an ACP-compatible observing script, with targets ordered by right ascension, for execution on a supported remote-telescope network (iTelescope in v1). | MVP |
| VST-070 | The system shall persist observation plans across application restarts. | MVP |
| VST-080 | The system shall look up a target's coordinates/magnitude via a Simbad query (traces to core `EXT-110`) when not already present in the synced AAVSO catalog data. | MVP |
| VST-090 | The system shall allow a variable-star target, with its observation-plan parameters, to be submitted directly to core's `SCHED` job queue (core `SCHED-010`) from within this plugin's own interface, without switching to the Scheduler UI first (traces to core `PLUG-080`). | MVP |

### 4.2 `VST-AN` — Variable Star Analysis & Photometry

Delivered as a first-party, pre-loaded, independently disableable plugin (core `PLUG-060`), paired with but separable from `VST` — a user can run `VST` for planning/scheduling without `VST-AN`'s analysis pipeline, or vice versa.

| ID | Requirement | Priority |
|---|---|---|
| VST-AN-010 | The system shall retrieve calibrated FITS images for a completed observation plan from a remote-telescope data server via FTP/FTPS/SFTP (traces to core `EXT-080`, `EXT-120`). | MVP |
| VST-AN-020 | The system shall plate-solve retrieved or captured variable-star images via core's existing solver integration (traces to core `PLT-010`) to add WCS coordinates. | MVP |
| VST-AN-030 | The system shall produce a registered, mean-stacked image from a set of same-target, same-filter frames for photometric signal-to-noise improvement. This is a bounded photometric-analysis operation, distinct from general-purpose deep-sky image stacking, which remains out of scope. | MVP |
| VST-AN-040 | The system shall perform aperture photometry on a target star against AAVSO VSP comparison stars, using ensemble linear-regression differential photometry. | MVP |
| VST-AN-050 | The system shall generate an AAVSO WebObs Extended-format measurement report from photometry results. | MVP |
| VST-AN-060 | The system shall compute per-telescope, per-filter transformation coefficients from standard-field observations (e.g. M67, NGC 7790, M11, NGC 1252, NGC 3532, Melotte 111, Landolt fields), with interactive review and rejection of outlier measurements. | P2 |
| VST-AN-070 | The system shall apply stored transformation coefficients to multi-filter observations prior to report generation. | P2 |
| VST-AN-080 | The system shall provide an exposure-time calculator calibrated to the configured telescope/filter throughput. | P2 |
| VST-AN-090 | The system shall generate an AAVSO-style finder chart image for a variable-star field, given a target name or coordinates, showing comparison stars and their magnitudes. | P2 |

---

## 5. Requirement Summary Counts (for RTM Seeding)

| Domain | Requirement Count | MVP | P2 | P3 |
|---|---|---|---|---|
| VST-EXT | 1 | 1 | 0 | 0 |
| VST | 9 | 8 | 1 | 0 |
| VST-AN | 9 | 5 | 4 | 0 |
| **Total** | **19** | | | |

---

## 6. Path to SDD / Traceability Matrix

1. **SDD** — [SDD.md](SDD.md), one component section per domain above, describing how this plugin's modules satisfy the requirements and which core ports/services they consume.
2. **Traceability Matrix** — [RTM.md](RTM.md), a row per requirement ID here, mapped to its SDD component(s) and a test case ID.

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SRS](../../SRS.md).*
