# AllSkyCam Plugin — PSD (Project Scope Document)

| | |
|---|---|
| **Project** | Galileo — AllSkyCam Plugin (indi-allsky all-sky camera viewer) |
| **Document** | PSD (Project Scope Document), v0.1, draft |
| **Status** | Draft — for review |
| **Date** | 2026-10-22 |
| **Parent project** | [Galileo Core PSD](../../PSD.md) |
| **Downstream documents** | SRS ([SRS.md](SRS.md)), SDD ([SDD.md](SDD.md)), RTM ([RTM.md](RTM.md)) |

---

## 1. Purpose of This Document

This document defines the scope of the **AllSkyCam plugin** — a first-party Galileo plugin that shows the current sky as seen by an [indi-allsky](https://github.com/aaronwmorris/indi-allsky) all-sky camera on the user's network. It follows the same PSD→SRS→SDD→RTM structure as [the core chain](../../PSD.md) and the other plugins' chains ([VSTarget](../vstarget/PSD.md), [Kasa Switch](../kasa_switch/PSD.md), [Generic Relay](../generic_relay/PSD.md)), and stays above implementation detail; design belongs in [SDD.md](SDD.md).

## 2. Background and Motivation

Many observatories run an all-sky camera alongside the imaging rig, and indi-allsky is the common open-source choice. It captures, processes and publishes a continuously updated sky image through its own web interface. An imaging session benefits from seeing that image next to the controls: clouds arriving, the Moon rising into the field, a dew-shrouded dome. Today that means a second browser window.

indi-allsky has no dedicated REST API. It does, however, expose `/latestimage`, which answers with a redirect to the newest processed image of a camera (optionally `?camera_id=N`). That is enough to fetch "the current image on demand" without any change to indi-allsky itself, which is why this plugin consumes the existing route rather than adding one upstream.

## 3. Vision Statement

> A Galileo user with an indi-allsky camera sees the current all-sky image, and the last few minutes of it as an animation, inside Galileo — in a screen of its own, or in a pane docked beside whatever they are doing — with no change to their indi-allsky installation.

## 4. Goals and Objectives

| # | Goal |
|---|---|
| G1 | Deliver the viewer as the `ASC` plugin — a first-party plugin distributed as a ZIP from the Galileo Plugins repository (`PLUG-090`/`PLUG-110`), independently enabled/disabled (`PLUG-060`), not bundled in the installer |
| G2 | Fetch the newest processed image from a configurable indi-allsky address on a configurable schedule, without blocking the UI and without re-downloading an image that has not changed |
| G3 | Optionally pause fetching during daytime, decided from the selected Observatory's own location rather than indi-allsky's configuration |
| G4 | Offer two views — the latest image as retrieved, and an animation of the last *n* images (*n* configurable) — in a screen of its own with its own top-level icon in the left menu |
| G5 | Offer the animation as an optional pane docked inside the Galileo window |
| G6 | Keep every option in Galileo's database, with a Test-connection check and in-app help for each control |

## 5. Non-Goals (Explicitly Out of Scope)

- **No changes to indi-allsky.** The plugin uses its existing `/latestimage` route only.
- **No authentication.** An indi-allsky install that requires login for all views is not supported; the plugin detects the login page and says so. Token or session login would need a change to indi-allsky and is a possible later addition.
- **No raw/FITS frames.** The processed JPEG/PNG is the product; raw capture and FITS handling remain core's.
- **No history beyond memory.** The animation holds recent images in memory only and refills after a restart; nothing is written to the Library.
- **No image processing.** No stretching, annotation, cloud detection or safety-monitor feed (the latter would be a separate device-backend plugin, `PLUG-010`/`SAFE-080`).

## 6. Dependencies on Galileo Core

| Core capability | Core requirement | How this plugin uses it |
|---|---|---|
| Plugin loading, manifest/version check, fault isolation | `PLUG-010`–`PLUG-050` | Discovered, loaded and isolated like any plugin |
| Enable/disable, inertness | `PLUG-060` | Disabling stops fetching and closes the pane |
| Panel placement declared by the plugin | `PLUG-070` | Declares a top-level sidebar section |
| Top-level section with its own icon | `PLUG-130` | The AllSkyCam entry in the left menu |
| Dockable plugin pane | `PLUG-140` | The optional animation pane |
| Plugin settings in the database | `PLUG-150` | All options, via `ctx.settings()` |
| Observatory site location | `PLUG-160` | The daytime pause, via `ctx.site_location()` |
| Solar position | `galileo.planning.visibility.sun_altitude_deg` (also used by `CAL-070`) | Sun altitude for the daytime test |
| Inline help | `HELP-060` | The plugin ships its own help Markdown |

## 7. Requirement Domain

One domain, **`ASC`** (AllSkyCam), specified in [SRS.md](SRS.md).

## 8. Stakeholders and Primary Persona

The Observatory Operator persona of the core PSD: someone imaging from a fixed or semi-fixed site who already runs an all-sky camera and wants the sky overview in the same window as their imaging controls.

## 9. Project Constraints

| # | Constraint |
|---|---|
| PC1 | Cross-platform (Windows/macOS/Linux, including Raspberry Pi 5-class ARM): no platform-specific code; modest memory and CPU (compressed frames, decode-on-display, animation timer only while visible) |
| PC2 | All configuration in the shared database (core's firm rule), never a plugin-private file or `QSettings` |
| PC3 | Network access must never run on the Qt UI thread |
| PC4 | GPL-3.0-or-later, as the other first-party plugins |
