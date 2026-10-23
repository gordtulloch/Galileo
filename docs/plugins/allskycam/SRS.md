# AllSkyCam Plugin — SRS (Software Requirements Specification)

| | |
|---|---|
| **Project** | Galileo — AllSkyCam Plugin |
| **Document** | SRS (Software Requirements Specification), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-22 |
| **Upstream document** | [PSD (Project Scope Document)](PSD.md) |
| **Downstream documents** | SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |
| **Parent project** | [Galileo Core SRS](../../SRS.md) |

---

## 1. Introduction

### 1.1 Purpose

This SRS decomposes the `ASC` requirement domain of [this plugin's PSD](PSD.md) into individually numbered, verifiable requirements, structurally parallel to [Galileo core's SRS](../../SRS.md) and the other plugins' SRS documents.

### 1.2 Scope

The `ASC` domain only. What the plugin consumes from core (plugin loading, panel placement, dock panes, settings, site location, help) is existing core requirements, cited by ID and listed in [PSD Section 6](PSD.md#6-dependencies-on-galileo-core).

### 1.3 Requirement ID Convention

`<DOMAIN>-<###>`, numbered in increments of 10.

### 1.4 Priority Convention

MVP / P2 / P3, identical to [core SRS Section 1.4](../../SRS.md#14-priority-convention).

### 1.5 References

[This plugin's PSD](PSD.md); [Galileo Core SRS](../../SRS.md), particularly the `PLUG` domain.

---

## 2. Overall Description

### 2.1 Product Perspective

A first-party plugin distributed as a ZIP from the Galileo Plugins repository and installed through Options > Plugins (`PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`).

### 2.2 Product Functions (Summary)

Fetch the newest image from an indi-allsky server on a schedule; show it as a still and as an animation of the last *n* images; optionally pause by day; show the animation in a docked pane; keep its options in the database.

### 2.3 User Classes and Characteristics

The Observatory Operator ([PSD Section 8](PSD.md#8-stakeholders-and-primary-persona)).

### 2.4 Operating Environment

Identical to core. Requires the indi-allsky server to be reachable by HTTP(S) from the Galileo host and to serve its images without login.

### 2.5 Design and Implementation Constraints

Distributed as a ZIP; loaded only through core's plugin extension points; no import of adapter or UI internals; no network I/O on the UI thread (PSD PC3).

### 2.6 Assumptions and Dependencies

indi-allsky's `/latestimage` route redirects to the newest processed image of the (default or requested) camera, as in the current upstream release. [PSD Section 6](PSD.md#6-dependencies-on-galileo-core) lists the core capabilities consumed.

---

## 3. Functional Requirements

### 3.1 `ASC` — All-Sky Camera Viewer

Delivered as a first-party, independently installable and disableable plugin (`PLUG-060`) with a top-level sidebar section (`PLUG-130`).

| ID | Requirement | Priority |
|---|---|---|
| ASC-010 | The system shall retrieve the newest processed image from an indi-allsky server at a user-configured address by requesting its `/latestimage` route (with `?camera_id=<n>` when a non-default camera is configured) and following the redirect to the image. The address shall be accepted with or without a scheme, trailing slash, or a pasted `/latestimage`; an unusable address shall be reported before any request is made. No change to indi-allsky shall be required. HTTPS certificate errors shall be ignored, since indi-allsky installs normally use self-signed certificates. | MVP |
| ASC-020 | The system shall fetch on a user-configurable interval in the background, never on the UI thread, with at most one fetch in flight. It shall recognise an image unchanged since the last fetch from the redirect target alone and not request it again. Every failure (unreachable server, HTTP error, a login page or other non-image response, an oversized or empty body, a redirect loop) shall be reported in a readable status message without raising into the application, and fetching shall continue on the next interval. | MVP |
| ASC-030 | The system shall, when the user enables **Pause during daytime**, skip fetching while the Sun's altitude at the selected Observatory's latitude/longitude exceeds a user-configurable limit, computing the altitude locally. When the Observatory has no location, or the altitude cannot be computed, it shall not pause and shall say why in the status line. | MVP |
| ASC-040 | The system shall provide, and persist in Galileo's database (`PLUG-150`), these options: server address, camera number, check interval, number of images in the animation, pause during daytime, Sun altitude limit, animation speed, and whether the animation pane is shown. Stored values shall be validated and clamped to sane ranges. A **Test connection** control shall try the form's current values off the UI thread, without saving, and report the outcome. Changing the server or camera shall discard the held images. | MVP |
| ASC-050 | The system shall provide a **Latest** view showing the newest image as retrieved, scaled to fit with its aspect ratio preserved, with when it was fetched. | MVP |
| ASC-060 | The system shall provide an **Animation** view that loops through the last *n* images (*n* the configured number) at the configured speed. Images shall be held as compressed bytes within a total memory cap, dropping the oldest first; frames shall be decoded only for display; the animation timer shall run only while the view is visible. An empty or single-image buffer shall display without error. | MVP |
| ASC-070 | The system shall offer the animation as a pane docked to the Galileo window (`PLUG-140`), openable from the options, movable and floatable by the user, sharing the same fetched images as the main view (one download for both). Closing the pane with its own close button shall turn the option off, and the open/closed state shall persist across restarts. | MVP |
| ASC-080 | The system shall present the plugin as its own top-level section of the left sidebar with its own icon (`PLUG-130`), containing the Latest and Animation views; its options are a page under Options (`PLUG-170`). | MVP |
| ASC-090 | The system shall be inert while the plugin is disabled (no fetching, pane closed) and resume when re-enabled (`PLUG-060`), and shall provide in-app help for every control on its screen (`HELP-060`). | MVP |
| ASC-100 | The system shall offer the animation as a view for the Galileo Dashboard (`PLUG-180`, `OBS-150`), shown above the Pier timelines when the user ticks *Publish on Dashboard* on the plugin's Options page, scaled to the height the Dashboard leaves free, and sharing the same fetched images as every other view. | P2 |

---

## 4. Requirement Summary Counts (for RTM Seeding)

| Domain | Requirement Count | MVP | P2 | P3 |
|---|---|---|---|---|
| ASC | 9 | 9 | 0 | 0 |
| **Total** | **9** | | | |

---

## 5. Path to SDD / Traceability Matrix

1. **SDD** — [SDD.md](SDD.md), describing how the plugin's modules satisfy the requirements above.
2. **Traceability Matrix** — [RTM.md](RTM.md), a row per requirement ID here, mapped to its SDD component and a test case ID.

---

*This document is a living draft, structurally parallel to and subordinate to [Galileo core's SRS](../../SRS.md).*
