# Galileo

![License: GPL v3](https://img.shields.io/badge/License-GPL--3.0-blue.svg)
![Status: Pre-alpha](https://img.shields.io/badge/status-pre--alpha%20%E2%80%94%20design%20phase-orange.svg)
![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

A cross-platform astrophotography imaging application for Windows, macOS, and Linux — built on [INDI](https://indilib.org/) and [ASCOM Alpaca](https://ascom-standards.org/AlpacaDeveloper/) instead of Windows-only ASCOM/COM device drivers.

Galileo is not affiliated with, derived from, or endorsed by the [N.I.N.A.](https://nighttime-imaging.eu/) project.

## Why Galileo

Two things motivate this project:

1. **Non-Windows imaging software has a UI/UX gap.** Existing cross-platform options (KStars/EKOS chief among them) have interfaces that have aged over a decade or more of incremental growth. Galileo aims to bring a modern, guided imaging workflow to Windows, macOS, and Linux alike, using INDI and ASCOM Alpaca so it isn't tied to any one platform's device-driver ecosystem.
2. **Consolidating prior work into one cohesive application.** Galileo's author has built several separate astronomy tools over time — an image manager, a variable-star planner, observatory-automation scripts, an all-sky cloud-detection classifier. Bringing that scattered work together into a single application, rather than maintaining it as several disconnected tools, is a primary goal of this project, not an afterthought.

## Status

**Pre-alpha — this repository is currently in the requirements and design phase.** There is no runnable application yet. What exists today:

- A complete set of planning documents: a Project Scope Document, a Software Requirements Specification (227 numbered requirements across 27 functional domains and 9 non-functional domains), and a Software Design Description covering the full planned architecture.
- One real, working, tested reference plugin ([`plugins/mlclouddetect/`](plugins/mlclouddetect/)) demonstrating the planned plugin architecture end-to-end, independent of the (not-yet-written) host application.

If you're looking for a working imaging application today, this isn't it yet — check back, or watch the repository for progress.

## Documentation

| Document | Contents |
|---|---|
| [`docs/PSD.md`](docs/PSD.md) — Project Scope Document | Goals, non-goals, functional/non-functional requirement domains, constraints, risks |
| [`docs/SRS.md`](docs/SRS.md) — Software Requirements Specification | Numbered, testable requirements decomposed from the PSD |
| [`docs/SDD.md`](docs/SDD.md) — Software Design Description | Architecture, module-by-module design, and the design decisions (ADRs) behind it |

## Planned Capabilities

- **Equipment control** for cameras, mounts, filter wheels, focusers, rotators, guiders, domes, and safety/weather monitors, via INDI or ASCOM Alpaca — mixed freely within one setup
- **Guided imaging** with a basic sequencer and an advanced instruction/condition/trigger sequencer
- **Sky navigation**: a catalog-based Sky Atlas, a Framing Assistant, and a live interactive planetarium-style Sky Map
- **Autofocus, plate solving, automated meridian flip, and external-guider integration**
- **A multi-night observatory Scheduler** with altitude/moon/twilight/horizon constraints and weather-gated execution
- **Multi-mount observatory management**: one Galileo instance coordinating several independent telescopes ("Piers"), with shared or per-telescope dome/safety scoping — deliberately going beyond what EKOS itself supports
- **An image library and repository manager**: cataloging, deduplication, smart-telescope ingestion, master calibration-frame creation/application, and quality metrics
- **A variable-star workflow**: AAVSO target planning and photometric analysis/reporting, presented as a peer to the Sky Atlas
- **Layered safety monitoring**: connected weather/rain/cloud sensors (including an ML-based all-sky-camera cloud classifier) trusted for automated aborts, with an independent crash/hang watchdog
- **An extensible plugin architecture** — the same one the `mlclouddetect` reference plugin already demonstrates
- **FITS-only image I/O**, including required tile-compressed FITS — deliberately no XISF, in favor of the multi-vendor IAU standard

See the [PSD](docs/PSD.md) for the full requirement domain list and what's explicitly out of scope for v1.

## Built On

Galileo consolidates and builds on several of the author's existing projects:

- [AstroFiler](https://github.com/gordtulloch/astrofiler-gui) — image cataloging and calibration processing (merged in full)
- [VSTarget](https://github.com/gordtulloch/VSTarget) — AAVSO variable-star planning and photometry (merged in full)
- [Obsy](https://github.com/gordtulloch/obsy) — target-visibility and sky-survey-thumbnail logic (retired as an app, its GPL-3.0 code ported directly into the Sky Atlas/Framing Assistant)
- [mlCloudDetect](https://github.com/gordtulloch/mlCloudDetect) — all-sky-camera cloud detection (reimplemented as this repo's reference plugin)
- [AstroLlama](https://github.com/gordtulloch/AstroLlama) and [MCP](https://github.com/gordtulloch/MCP) — selectively harvested for specific device-abstraction and safety-sensor functionality

See the PSD's Background section for the full picture of what's merged, harvested, or kept as reference only, and why.

## Tech Stack

Python 3 with [PySide6](https://doc.qt.io/qtforpython/) (Qt for Python), chosen for native rendering performance on ARM SBCs (e.g. Raspberry Pi-class hardware at the telescope) and direct reuse of the existing Python astronomy ecosystem (`astropy`, `pyindi-client`, `alpyca`). See [SDD Section 2.1](docs/SDD.md) for the full rationale.

## License

[GPL-3.0](LICENSE)

## Author

[Gord Tulloch](https://github.com/gordtulloch)
